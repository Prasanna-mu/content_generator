from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import re
from core.models.schemas import UserInput, Lesson, Subtopic, GeneratedContent, QuizQuestion, QuestionBankItem, LessonOutput
from core.llm.base import BaseLLMProvider
from core.session.manager import SessionManager
from core.session.models import PipelineStage, TaskStatus


class ContentQualityReview:
    """Result of LLM-based quality review for generated content."""
    def __init__(
        self,
        score: int,  # 0-10
        strengths: List[str],
        weaknesses: List[str],
        meets_length: bool,
        subtopic_title: str
    ):
        self.score = score
        self.strengths = strengths
        self.weaknesses = weaknesses
        self.meets_length = meets_length
        self.subtopic_title = subtopic_title


class ContentGenerator:
    def __init__(self, llm: BaseLLMProvider, worker_count: int = 4, processing_dir: Path = Path("processing")):
        self.llm = llm
        self.worker_count = max(1, worker_count)
        self.processing_dir = processing_dir
        self.content_quality_threshold = 6  # Minimum quality score (0-10)
        self.max_regeneration_attempts = 2
        self.length_tolerance = 0.3  # Allow 30% deviation from target length

    def generate_lesson_content(self, lesson: Lesson, user_input: UserInput) -> LessonOutput:
        generated_contents = []
        for subtopic in lesson.subtopics:
            content = self._generate_content_with_quality_check(lesson.title, subtopic, user_input)
            generated_contents.append(content)
        
        quiz_questions = self.llm.generate_quiz(lesson, user_input)
        question_bank = self.llm.generate_question_bank(lesson, user_input)
        
        return LessonOutput(
            lesson=lesson,
            generated_contents=generated_contents,
            quiz_questions=quiz_questions,
            question_bank=question_bank
        )
    
    def _generate_content_with_quality_check(
        self, 
        lesson_title: str, 
        subtopic: Subtopic, 
        user_input: UserInput
    ) -> GeneratedContent:
        """Generate content with LLM-based quality review and regeneration if needed."""
        target_chars = subtopic.estimated_chars
        min_chars = int(target_chars * (1 - self.length_tolerance))
        max_chars = int(target_chars * (1 + self.length_tolerance))
        
        for attempt in range(self.max_regeneration_attempts + 1):
            content = self.llm.generate_content(lesson_title, subtopic, user_input)
            
            # Check length
            meets_length = min_chars <= content.actual_chars <= max_chars
            
            # Quality review via LLM
            review = self._review_content_quality(content, lesson_title, subtopic, user_input, target_chars)
            
            if review.score >= self.content_quality_threshold and meets_length:
                return content
            
            if attempt < self.max_regeneration_attempts:
                print(f"    Content quality check failed for '{subtopic.title}' (score: {review.score}/10, length: {content.actual_chars}/{target_chars}), regenerating (attempt {attempt + 1}/{self.max_regeneration_attempts})...")
                # Add feedback to the subtopic for regeneration
                subtopic.validation_errors = review.weaknesses
            else:
                print(f"    Max regeneration attempts reached for '{subtopic.title}', using best effort (score: {review.score}/10)")
        
        return content
    
    def _review_content_quality(
        self,
        content: GeneratedContent,
        lesson_title: str,
        subtopic: Subtopic,
        user_input: UserInput,
        target_chars: int
    ) -> ContentQualityReview:
        """Use LLM to review content quality (0-10 score)."""
        prompt = f"""
Review the quality of this educational content for the subtopic: "{subtopic.title}"
Lesson: "{lesson_title}"
Main topic: {user_input.prompt}
Target length: ~{target_chars} characters
Actual length: {content.actual_chars} characters
Content quality level: {user_input.content_quality.value}

CONTENT TO REVIEW:
{content.content[:3000]}

EVALUATION CRITERIA (score 0-10 for each, then overall 0-10):
1. Accuracy: Is the information factually correct and up-to-date?
2. Depth: Does it cover the topic with appropriate depth for {user_input.content_quality.value} level?
3. Structure: Is it well-organized with clear sections, headers, and flow?
4. Examples: Does it include relevant examples, code snippets, or illustrations?
5. Clarity: Is the writing clear, concise, and easy to understand?
6. Completeness: Does it fully address the subtopic description?
7. Length: Is the content length appropriate (~{target_chars} chars, actual: {content.actual_chars})?

Return JSON format:
{{
    "overall_score": 0-10,
    "accuracy_score": 0-10,
    "depth_score": 0-10,
    "structure_score": 0-10,
    "examples_score": 0-10,
    "clarity_score": 0-10,
    "completeness_score": 0-10,
    "length_score": 0-10,
    "strengths": ["strength1", "strength2"],
    "weaknesses": ["weakness1", "weakness2"],
    "meets_length": true/false
}}
"""
        system_prompt = f"""You are an expert educational content reviewer. 
Evaluate content for {user_input.content_quality.value} level {user_input.content_length.value} length.
Be strict but fair. Score {self.content_quality_threshold}+ = acceptable, <{self.content_quality_threshold} = needs regeneration."""
        
        try:
            result = self.llm.generate_json_with_validation(
                prompt, system_prompt,
                lambda d: self._validate_content_review_json(d),
                max_retries=2,
                save_as=None,
                temperature=0.3
            )
            
            meets_length = result.get("meets_length", True)
            return ContentQualityReview(
                score=result.get("overall_score", 0),
                strengths=result.get("strengths", []),
                weaknesses=result.get("weaknesses", []),
                meets_length=meets_length,
                subtopic_title=subtopic.title
            )
        except Exception as e:
            print(f"    Content quality review failed for '{subtopic.title}': {e}")
            # Default to valid if review fails (fail-open for robustness)
            return ContentQualityReview(
                score=self.content_quality_threshold,
                strengths=["Review failed, assuming acceptable"],
                weaknesses=[f"Review error: {e}"],
                meets_length=True,
                subtopic_title=subtopic.title
            )
    
    def _validate_content_review_json(self, data: Dict[str, Any]) -> bool:
        """Validate content quality review JSON response."""
        if not isinstance(data, dict):
            return False
        required = ["overall_score", "strengths", "weaknesses", "meets_length"]
        for field in required:
            if field not in data:
                return False
        if not isinstance(data["overall_score"], int) or not (0 <= data["overall_score"] <= 10):
            return False
        if not isinstance(data["strengths"], list) or not isinstance(data["weaknesses"], list):
            return False
        if not isinstance(data["meets_length"], bool):
            return False
        return True

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