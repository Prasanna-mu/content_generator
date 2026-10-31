from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
from core.models.schemas import UserInput, Lesson, GeneratedContent, QuizQuestion, QuestionBankItem, LessonOutput
from core.llm.base import BaseLLMProvider
from core.session.manager import SessionManager
from core.session.models import PipelineStage, TaskStatus


class ContentGenerator:
    def __init__(self, llm: BaseLLMProvider, worker_count: int = 4, processing_dir: Path = Path("processing")):
        self.llm = llm
        self.worker_count = max(1, worker_count)
        self.processing_dir = processing_dir

    def generate_lesson_content(self, lesson: Lesson, user_input: UserInput) -> LessonOutput:
        generated_contents = []
        for subtopic in lesson.subtopics:
            content = self.llm.generate_content(lesson.title, subtopic, user_input)
            generated_contents.append(content)
        
        quiz_questions = self.llm.generate_quiz(lesson, user_input)
        question_bank = self.llm.generate_question_bank(lesson, user_input)
        
        return LessonOutput(
            lesson=lesson,
            generated_contents=generated_contents,
            quiz_questions=quiz_questions,
            question_bank=question_bank
        )

    def generate_all(self, lessons: List[Lesson], user_input: UserInput) -> List[LessonOutput]:
        outputs = [None] * len(lessons)
        
        with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
            future_to_index = {
                executor.submit(self.generate_lesson_content, lesson, user_input): i
                for i, lesson in enumerate(lessons)
            }
            
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                lesson = lessons[index]
                try:
                    output = future.result()
                    outputs[index] = output
                    print(f"Completed Lesson {index+1}/{len(lessons)}: {lesson.title}")
                except Exception as e:
                    print(f"Error generating content for Lesson {index+1} ({lesson.title}): {e}")
                    raise
        
        return outputs

    def generate_all_with_checkpoints(
        self, 
        lessons: List[Lesson], 
        user_input: UserInput,
        session_id: str,
        session_manager: SessionManager,
        prompt_dir: Path
    ) -> List[LessonOutput]:
        session_dir = self.processing_dir / "sessions" / session_id
        output_file = session_dir / "lesson_outputs.json"
        
        existing_outputs = {}
        if output_file.exists():
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for lo_data in data.get("lesson_outputs", []):
                lo = LessonOutput(**lo_data)
                existing_outputs[lo.lesson.title] = lo
        
        outputs = [None] * len(lessons)
        
        pending_lessons = []
        for i, lesson in enumerate(lessons):
            if lesson.title in existing_outputs:
                outputs[i] = existing_outputs[lesson.title]
                print(f"  Skipping Lesson {i+1}/{len(lessons)}: {lesson.title} (already completed)")
            else:
                pending_lessons.append((i, lesson))
        
        if not pending_lessons:
            print("  All lessons already completed!")
            return outputs
        
        print(f"  Generating content for {len(pending_lessons)} pending lessons...")
        
        with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
            future_to_index = {}
            
            for i, lesson in pending_lessons:
                task_id = f"lesson_{i}_{lesson.title.replace(' ', '_')}"
                
                checkpoint = session_manager.get_task_checkpoint(
                    session_id, PipelineStage.CONTENT_GENERATION, task_id
                )
                
                if checkpoint and checkpoint.status == TaskStatus.COMPLETED:
                    output_data = checkpoint.output_data
                    outputs[i] = LessonOutput(**output_data)
                    print(f"  Restored Lesson {i+1}/{len(lessons)}: {lesson.title} from checkpoint")
                    continue
                
                session_manager.start_task(
                    session_id, PipelineStage.CONTENT_GENERATION, task_id,
                    "lesson_content", lesson.title,
                    {"lesson": lesson.model_dump(), "user_input": user_input.model_dump()}
                )
                
                future = executor.submit(self._generate_lesson_with_checkpoint, lesson, user_input, session_id, session_manager, task_id, prompt_dir)
                future_to_index[future] = (i, lesson, task_id)
            
            for future in as_completed(future_to_index):
                index, lesson, task_id = future_to_index[future]
                try:
                    output = future.result()
                    outputs[index] = output
                    session_manager.complete_task(
                        session_id, PipelineStage.CONTENT_GENERATION, task_id,
                        output.model_dump()
                    )
                    print(f"  Completed Lesson {index+1}/{len(lessons)}: {lesson.title}")
                except Exception as e:
                    session_manager.fail_task(
                        session_id, PipelineStage.CONTENT_GENERATION, task_id, str(e)
                    )
                    print(f"  Error generating content for Lesson {index+1} ({lesson.title}): {e}")
                    raise
        
        self._save_lesson_outputs(outputs, session_dir)
        return outputs

    def _generate_lesson_with_checkpoint(
        self, 
        lesson: Lesson, 
        user_input: UserInput,
        session_id: str,
        session_manager: SessionManager,
        task_id: str,
        prompt_dir: Path
    ) -> LessonOutput:
        # Generate the lesson content
        output = self.generate_lesson_content(lesson, user_input)
        
        # Update tasklist for each subtopic in this lesson
        self._update_tasklist_for_lesson(lesson, prompt_dir, session_id, session_manager)
        
        return output

    def _update_tasklist_for_lesson(self, lesson: Lesson, prompt_dir: Path, session_id: str, session_manager: SessionManager):
        """Update the tasklist to mark subtopics of this lesson as completed."""
        tasklist_file = prompt_dir / "tasklist.json"
        if tasklist_file.exists():
            try:
                with open(tasklist_file, 'r', encoding='utf-8') as f:
                    tasklist_data = json.load(f)
                
                # Mark tasks for this lesson's subtopics as completed
                if "tasks" in tasklist_data:
                    for task in tasklist_data["tasks"]:
                        if task["lesson_title"] == lesson.title:
                            # Find matching subtopic
                            for subtopic in lesson.subtopics:
                                if task["subtopic_title"] == subtopic.title:
                                    task["completed"] = True
                                    # Generate a content file name for this subtopic
                                    # Using a sanitized version for the filename
                                    import re
                                    filename = re.sub(r'[<>:"/\\|?*]', '_', subtopic.title)
                                    filename = filename.strip().replace(' ', '_')[:100] + ".txt"
                                    task["content_file"] = filename
                                    break
                            break
                
                # Save the updated tasklist
                with open(tasklist_file, 'w', encoding='utf-8') as f:
                    json.dump(tasklist_data, f, indent=2)
                    
            except Exception as e:
                print(f"Warning: Could not update tasklist: {e}")

    def _save_lesson_outputs(self, outputs: List[LessonOutput], session_dir: Path):
        session_dir.mkdir(parents=True, exist_ok=True)
        output_file = session_dir / "lesson_outputs.json"
        data = {
            "lesson_outputs": [lo.model_dump() for lo in outputs if lo is not None]
        }
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)