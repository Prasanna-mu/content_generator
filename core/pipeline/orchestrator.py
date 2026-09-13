from pathlib import Path
from typing import List, Optional, Dict, Any
import os
import json
from core.models.schemas import UserInput, Lesson, LessonOutput, PipelineConfig
from core.llm.factory import LLMFactory
from core.llm.base import BaseLLMProvider
from core.planning.prompt_analyzer import PromptAnalyzer
from core.planning.lesson_generator import LessonGenerator
from core.planning.subtopic_generator import SubtopicGenerator
from core.generation.content_generator import ContentGenerator
from core.output.writer import OutputWriter
from core.websearch.manager import WebSearchManager
from core.session.manager import SessionManager
from core.session.models import (
    Session, SessionStatus, StageStatus, TaskStatus,
    PipelineStage, StageCheckpoint, TaskCheckpoint
)


class PipelineOrchestrator:
    def __init__(
        self,
        model_name: str = "qwen2.5:3b",
        provider: str = "ollama",
        base_url: str = "http://localhost:11434",
        output_dir: Path = Path("output"),
        worker_count: int = 4,
        processing_dir: Path = Path("processing"),
        session_id: Optional[str] = None,
        resume: bool = False
    ):
        self.model_name = model_name
        self.provider = provider
        self.base_url = base_url
        self.output_dir = output_dir
        self.processing_dir = processing_dir
        self.worker_count = worker_count
        self.session_id = session_id
        self.resume = resume
        
        self.llm: Optional[BaseLLMProvider] = None
        self.prompt_analyzer: Optional[PromptAnalyzer] = None
        self.lesson_generator: Optional[LessonGenerator] = None
        self.subtopic_generator: Optional[SubtopicGenerator] = None
        self.content_generator: Optional[ContentGenerator] = None
        self.output_writer: Optional[OutputWriter] = None
        self.web_search_manager: Optional[WebSearchManager] = None
        self.session_manager: Optional[SessionManager] = None
        self.session: Optional[Session] = None
        self.web_search_report = None
        self.user_input: Optional[UserInput] = None
        self.lessons: List[Lesson] = []

    def initialize_session_manager(self):
        """Initialize only the session manager (for listing sessions, etc.)"""
        if self.session_manager is None:
            self.session_manager = SessionManager(self.processing_dir / "sessions.db")

    def initialize(self):
        self.initialize_session_manager()
        self.llm = LLMFactory.create(self.provider, self.model_name, self.base_url)
        
        if not self.llm.check_connection():
            raise ConnectionError(f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?")
        
        available_models = self.llm.list_models()
        if self.model_name not in available_models:
            print(f"Model {self.model_name} not found. Pulling...")
            if not self.llm.pull_model():
                raise RuntimeError(f"Failed to pull model {self.model_name}")
        
        if self.processing_dir == self.output_dir:
            raise ValueError("processing_dir must be different from output_dir to keep intermediate files separate from final output")
        
        session_intermediate_dir = self.processing_dir / "sessions" / (self.session_id or "temp") / "intermediate"
        self.llm.set_output_dir(session_intermediate_dir)
        
        self.prompt_analyzer = PromptAnalyzer(self.llm)
        self.lesson_generator = LessonGenerator(self.llm)
        self.subtopic_generator = SubtopicGenerator(self.llm)
        self.content_generator = ContentGenerator(self.llm, self.worker_count, self.processing_dir)
        self.output_writer = OutputWriter(self.output_dir)
        self.web_search_manager = WebSearchManager(self.llm, self.worker_count)

    def _sanitize_folder_name(self, name: str) -> str:
        """Sanitize a string to be used as a folder name."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip().replace(' ', '_')[:100]

    def _initialize_prompt_files(self):
        """Initialize JSON files in the prompt directory."""
        # Initialize lessons JSON file
        lessons_file = self.prompt_dir / "lessons.json"
        if not lessons_file.exists():
            with open(lessons_file, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=2)
                 
        # Initialize subtopics JSON file
        subtopics_file = self.prompt_dir / "subtopics.json"
        if not subtopics_file.exists():
            with open(subtopics_file, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=2)
                
        # Initialize tasklist JSON file
        tasklist_file = self.prompt_dir / "tasklist.json"
        if not tasklist_file.exists():
            # Create empty tasklist structure
            tasklist_data = {
                "tasks": []
            }
            with open(tasklist_file, 'w', encoding='utf-8') as f:
                json.dump(tasklist_data, f, indent=2)

    def _update_checklist_info(self, user_input: UserInput):
        """Update the checklist with prompt, session information, and appropriate stages."""
        checklist_file = self.prompt_dir / "checklist.json"
        
        # Define the stages for the checklist
        stages = {
            "subtopic_generation": "pending",
            "lesson_generation": "pending",
            "content_generation": "pending",
            "output_writing": "pending"
        }
        
        # Add web search stage only if needed
        if user_input.web_search_needed:
            stages["web_search"] = "pending"
        
        # Create or update checklist
        if checklist_file.exists():
            with open(checklist_file, 'r', encoding='utf-8') as f:
                checklist = json.load(f)
            
            # Update basic info
            checklist["prompt"] = user_input.prompt
            checklist["session_id"] = self.session_id
            
            # Update stages, preserving any existing completed/failed statuses
            if "stages" not in checklist:
                checklist["stages"] = {}
            
            for stage, status in stages.items():
                if stage not in checklist["stages"]:
                    checklist["stages"][stage] = status
                # If stage exists, keep its current status (could be completed/failed from previous run)
            
            # Ensure tasklist array exists
            if "tasklist" not in checklist:
                checklist["tasklist"] = []
        else:
            # Create new checklist
            checklist = {
                "prompt": user_input.prompt,
                "session_id": self.session_id,
                "stages": stages,
                "lessons": [],
                "subtopics": [],
                "tasklist": []
            }
        
        with open(checklist_file, 'w', encoding='utf-8') as f:
            json.dump(checklist, f, indent=2)

    def _update_checklist_stage(self, stage: PipelineStage, status: str):
        """Update a specific stage status in the checklist."""
        # Map PipelineStage to checklist stage name
        stage_map = {
            PipelineStage.WEB_SEARCH: "web_search",
            PipelineStage.SUBTOPIC_GENERATION: "subtopic_generation",
            PipelineStage.LESSON_GENERATION: "lesson_generation",
            PipelineStage.CONTENT_GENERATION: "content_generation",
            PipelineStage.OUTPUT_WRITING: "output_writing"
        }
        
        checklist_stage_name = stage_map.get(stage)
        if not checklist_stage_name:
            # If stage not in map, skip updating checklist
            return
            
        checklist_file = self.prompt_dir / "checklist.json"
        if checklist_file.exists():
            with open(checklist_file, 'r', encoding='utf-8') as f:
                checklist = json.load(f)
            
            if "stages" in checklist and checklist_stage_name in checklist["stages"]:
                checklist["stages"][checklist_stage_name] = status
                
                with open(checklist_file, 'w', encoding='utf-8') as f:
                    json.dump(checklist, f, indent=2)

    def _update_lessons_json(self):
        """Update the lessons.json file with current lessons data."""
        lessons_file = self.prompt_dir / "lessons.json"
        lessons_data = []
        for lesson in self.lessons:
            lessons_data.append({
                "title": lesson.title,
                "description": lesson.description,
                "estimated_total_chars": lesson.estimated_total_chars
            })
        with open(lessons_file, 'w', encoding='utf-8') as f:
            json.dump(lessons_data, f, indent=2)

    def _update_subtopics_json(self):
        """Update the subtopics.json file with current subtopics data."""
        subtopics_file = self.prompt_dir / "subtopics.json"
        subtopics_data = []
        for lesson in self.lessons:
            for subtopic in lesson.subtopics:
                subtopics_data.append({
                    "lesson_title": lesson.title,
                    "title": subtopic.title,
                    "description": subtopic.description,
                    "estimated_chars": subtopic.estimated_chars
                })
        with open(subtopics_file, 'w', encoding='utf-8') as f:
            json.dump(subtopics_data, f, indent=2)

    def _create_tasklist(self):
        """Create a tasklist for tracking subtopic content generation completion."""
        tasklist_file = self.prompt_dir / "tasklist.json"
        tasks = []
        for lesson in self.lessons:
            for subtopic in lesson.subtopics:
                tasks.append({
                    "lesson_title": lesson.title,
                    "subtopic_title": subtopic.title,
                    "completed": False,
                    "content_file": None
                })
        tasklist_data = {
            "tasks": tasks
        }
        with open(tasklist_file, 'w', encoding='utf-8') as f:
            json.dump(tasklist_data, f, indent=2)

    def _load_or_create_session(self, user_input: UserInput) -> Session:
        config = {
            "model_name": self.model_name,
            "provider": self.provider,
            "base_url": self.base_url,
            "worker_count": self.worker_count,
            "web_search_needed": user_input.web_search_needed,
            "num_lessons": user_input.num_lessons,
            "subtopics_per_lesson": user_input.subtopics_per_lesson,
        }
        
        if self.resume and self.session_id:
            session = self.session_manager.get_session(self.session_id)
            if not session:
                raise ValueError(f"Session {self.session_id} not found")
            print(f"Resuming session: {self.session_id}")
            self.session_manager.recover_interrupted_tasks(self.session_id)
            self.session_manager.recover_interrupted_stages(self.session_id)
            self.session_manager.update_session_status(
                self.session_id, SessionStatus.RESUMED
            )
            return session
        elif self.session_id:
            session = self.session_manager.get_session(self.session_id)
            if session:
                raise ValueError(f"Session {self.session_id} already exists. Use --resume to continue.")
        
        user_input_json = user_input.model_dump_json()
        session = self.session_manager.create_session(
            prompt=user_input.prompt,
            user_input_json=user_input_json,
            config=config
        )
        print(f"Created new session: {session.session_id}")
        return session

    def _load_user_input(self) -> UserInput:
        if self.session and self.session.user_input_json:
            return UserInput.model_validate_json(self.session.user_input_json)
        raise ValueError("No user input found in session")

    def run(self, user_input: UserInput) -> List[LessonOutput]:
        self.session = self._load_or_create_session(user_input)
        self.session_id = self.session.session_id
        
        session_dir = self.processing_dir / "sessions" / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        # No intermediate folder as per sprint 3 requirements
        
        # Create prompt-named folder in processing directory
        prompt_folder = self._sanitize_folder_name(user_input.prompt)
        self.prompt_dir = self.processing_dir / prompt_folder
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize checklist and JSON files in prompt directory
        self._initialize_prompt_files()
        
        # Update checklist with prompt and session info
        self._update_checklist_info(user_input)
        
        # Load user_input from session when resuming, otherwise use provided
        if self.resume:
            self.user_input = self._load_user_input()
        else:
            self.user_input = user_input
        
        self.llm.set_output_dir(session_dir)
        
        print("\n" + "=" * 60)
        print(f"Content Generation Pipeline - Session: {self.session_id[:8]}...")
        print("=" * 60)
        
        try:
            self._run_pipeline()
            self.session_manager.update_session_status(
                self.session_id, SessionStatus.COMPLETED
            )
            print("\n" + "=" * 60)
            print("Pipeline Complete!")
            print("=" * 60)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Session saved for resume.")
            self.session_manager.update_session_status(
                self.session_id, SessionStatus.INTERRUPTED
            )
            raise
        except Exception as e:
            self.session_manager.update_session_status(
                self.session_id, SessionStatus.FAILED, error_message=str(e)
            )
            raise
        
        return self._load_lesson_outputs()

    def _run_pipeline(self):
        all_stages = [
            (PipelineStage.PROMPT_ANALYSIS, self._run_prompt_analysis),
            (PipelineStage.WEB_SEARCH, self._run_web_search),
            (PipelineStage.LESSON_GENERATION, self._run_lesson_generation),
            (PipelineStage.LESSON_REFINEMENT, self._run_lesson_refinement),
            (PipelineStage.SUBTOPIC_GENERATION, self._run_subtopic_generation),
            (PipelineStage.SUBTOPIC_ADJUSTMENT, self._run_subtopic_adjustment),
            (PipelineStage.SUBTOPIC_VALIDATION, self._run_subtopic_validation),
            (PipelineStage.CONTENT_GENERATION, self._run_content_generation),
            (PipelineStage.OUTPUT_WRITING, self._run_output_writing),
        ]
        
        stages = [(s, f) for s, f in all_stages if self.user_input.web_search_needed or s != PipelineStage.WEB_SEARCH]
        stage_names = [s for s, _ in stages]
        
        resume_from = None
        if self.resume:
            resume_from = self.session_manager.get_resume_point(self.session_id)
            if resume_from and resume_from not in stage_names:
                for s in stage_names:
                    status = self.session_manager.get_stage_status(self.session_id, s)
                    if status in (StageStatus.PENDING, StageStatus.RUNNING, StageStatus.FAILED):
                        resume_from = s
                        break
            if resume_from:
                print(f"Resuming from stage: {resume_from.value}")
        
        for stage, stage_func in stages:
            if resume_from and stage != resume_from:
                status = self.session_manager.get_stage_status(self.session_id, stage)
                if status == StageStatus.COMPLETED:
                    print(f"\n[{stage.value}] Skipped (already completed)")
                    continue
            
            if resume_from and stage == resume_from:
                resume_from = None
            
            checkpoint = self.session_manager.get_stage_checkpoint(self.session_id, stage)
            if checkpoint and checkpoint.status == StageStatus.COMPLETED:
                print(f"\n[{stage.value}] Skipped (already completed)")
                self._restore_stage_output(stage, checkpoint.output_data)
                continue
            
            self.session_manager.start_stage(self.session_id, stage, {})
            print(f"\n[{stage.value}] Running...")
            
            try:
                output_data = stage_func()
                self.session_manager.complete_stage(self.session_id, stage, output_data)
                # Update checklist
                self._update_checklist_stage(stage, "completed")
                print(f"[{stage.value}] Completed")
            except Exception as e:
                self.session_manager.fail_stage(self.session_id, stage, str(e))
                # Update checklist with failed status
                self._update_checklist_stage(stage, "failed")
                raise

    def _restore_stage_output(self, stage: PipelineStage, output_data: Dict[str, Any]):
        if stage == PipelineStage.PROMPT_ANALYSIS:
            pass
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.WEB_SEARCH:
            from core.models.schemas import WebSearchReport
            self.web_search_report = WebSearchReport(**output_data)
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.LESSON_GENERATION:
            self.lessons = [Lesson(**l) for l in output_data.get("lessons", [])]
            # Update lessons.json in prompt directory
            self._update_lessons_json()
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.LESSON_REFINEMENT:
            self.lessons = [Lesson(**l) for l in output_data.get("lessons", [])]
            # Update lessons.json in prompt directory
            self._update_lessons_json()
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.SUBTOPIC_GENERATION:
            self.lessons = [Lesson(**l) for l in output_data.get("lessons", [])]
            # Update subtopics.json in prompt directory
            self._update_subtopics_json()
            # Update checklist
            self._update_checklist_stage(stage, "completed")
            # Create tasklist when restoring subtopic generation
            self._create_tasklist()
        elif stage == PipelineStage.SUBTOPIC_ADJUSTMENT:
            self.lessons = [Lesson(**l) for l in output_data.get("lessons", [])]
            # Update subtopics.json in prompt directory
            self._update_subtopics_json()
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.SUBTOPIC_VALIDATION:
            pass
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.CONTENT_GENERATION:
            pass
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.OUTPUT_WRITING:
            pass
            # Update checklist
            self._update_checklist_stage(stage, "completed")

    def _run_prompt_analysis(self) -> Dict[str, Any]:
        analysis = self.prompt_analyzer.analyze(self.user_input)
        print(f"    Domain: {analysis.get('domain', 'N/A')}")
        print(f"    Complexity: {analysis.get('complexity', 'N/A')}")
        return {"analysis": analysis}

    def _run_web_search(self) -> Dict[str, Any]:
        self.web_search_report = self.web_search_manager.run_web_search(self.user_input)
        print(f"    Web search completed: {self.web_search_report.reputable_results}/{self.web_search_report.total_results} reputable sources")
        return {"report": self.web_search_report.model_dump()}

    def _run_lesson_generation(self) -> Dict[str, Any]:
        self.lessons = self.lesson_generator.generate(self.user_input)
        print(f"    Generated {len(self.lessons)} lessons")
        self.session_manager.update_session_status(
            self.session_id, SessionStatus.RUNNING, 
            completed_lessons=len(self.lessons)
        )
        # Update lessons.json in prompt directory
        self._update_lessons_json()
        return {"lessons": [l.model_dump() for l in self.lessons]}

    def _run_lesson_refinement(self) -> Dict[str, Any]:
        self.lessons = self.lesson_generator.refine_lessons(self.lessons, self.user_input)
        print(f"    Refined {len(self.lessons)} lessons")
        # Update lessons.json in prompt directory
        self._update_lessons_json()
        return {"lessons": [l.model_dump() for l in self.lessons]}

    def _run_subtopic_generation(self) -> Dict[str, Any]:
        self.lessons = self.subtopic_generator.generate_all(self.lessons, self.user_input)
        total_subtopics = sum(len(l.subtopics) for l in self.lessons)
        print(f"    Generated {total_subtopics} subtopics")
        # Update subtopics.json in prompt directory
        self._update_subtopics_json()
        
        # Create tasklist for subtopic content generation
        self._create_tasklist()
        
        return {"lessons": [l.model_dump() for l in self.lessons]}

    def _run_subtopic_adjustment(self) -> Dict[str, Any]:
        self.lessons = self.subtopic_generator.adjust_estimates(self.lessons, self.user_input)
        print(f"    Adjusted estimates for content length: {self.user_input.content_length.value}")
        # Update subtopics.json in prompt directory
        self._update_subtopics_json()
        return {"lessons": [l.model_dump() for l in self.lessons]}

    def _run_subtopic_validation(self) -> Dict[str, Any]:
        if not self.subtopic_generator.validate_subtopics(self.lessons, self.user_input):
            print("    Validation failed, attempting to load from saved output...")
            self.lessons = self.subtopic_generator.load_saved_subtopics(self.lessons, self.user_input)
            if not self.subtopic_generator.validate_subtopics(self.lessons, self.user_input):
                raise ValueError("Subtopic validation failed even after loading saved output")
        print("    Subtopics validated successfully")
        # Update subtopics.json in prompt directory
        self._update_subtopics_json()
        return {}

    def _run_content_generation(self) -> Dict[str, Any]:
        print(f"    Generating content for {len(self.lessons)} lessons (workers: {self.worker_count})...")
        
        lesson_outputs = self.content_generator.generate_all_with_checkpoints(
            self.lessons, self.user_input, self.session_id, self.session_manager, self.prompt_dir
        )
        
        total_chars = sum(
            c.actual_chars for lo in lesson_outputs for c in lo.generated_contents
        )
        print(f"    Generated {total_chars:,} characters of content")
        
        self.session_manager.update_session_status(
            self.session_id, SessionStatus.RUNNING,
            completed_lessons=len(lesson_outputs)
        )
        
        return {"lesson_outputs": [lo.model_dump() for lo in lesson_outputs]}

    def _run_output_writing(self) -> Dict[str, Any]:
        lesson_outputs = self._load_lesson_outputs()
        output_path = self.output_writer.write_all(
            self.user_input, lesson_outputs, self.web_search_report, self.session_id
        )
        print(f"    Output written to: {output_path}")
        return {"output_path": str(output_path)}

    def _load_lesson_outputs(self) -> List[LessonOutput]:
        session_dir = self.processing_dir / "sessions" / self.session_id
        output_file = session_dir / "lesson_outputs.json"
        
        if output_file.exists():
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [LessonOutput(**lo) for lo in data.get("lesson_outputs", [])]
        
        return []

    def run_from_json(self, json_path: Path) -> List[LessonOutput]:
        from userinput import load_user_input_json
        user_input = load_user_input_json(json_path)
        return self.run(user_input)

    def list_sessions(self, limit: int = 50) -> List[Session]:
        return self.session_manager.list_sessions(limit)

    def get_session_info(self, session_id: str) -> Optional[Session]:
        return self.session_manager.get_session(session_id)

    def close(self):
        if self.session_manager:
            self.session_manager.close()