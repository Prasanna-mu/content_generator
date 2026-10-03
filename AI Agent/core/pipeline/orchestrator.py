from pathlib import Path
from typing import List, Optional, Dict, Any
import os
import json
import shutil
import re
import tempfile
from datetime import datetime
from core.models.schemas import UserInput, Lesson, LessonOutput, GeneratedContent, Subtopic, PipelineConfig
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
        self.prompt_analysis: Optional[Dict[str, Any]] = None
        self.reference_context: Optional[str] = None

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
        # Load reference materials
        self.reference_context = self._load_reference_materials()
        # Set reference context in LLM
        self.llm.set_reference_context(self.reference_context)

    def _load_reference_materials(self) -> str:
        """Load all .md files from the reference directory and return combined content."""
        reference_dir = Path("reference")
        reference_dir.mkdir(exist_ok=True)
        md_files = list(reference_dir.glob("*.md"))
        if not md_files:
            print("    No reference .md files found in reference/ directory.")
            return ""
        
        print(f"    Loading {len(md_files)} reference .md files...")
        combined_content = []
        for md_file in md_files:
            try:
                with open(md_file, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                combined_content.append(f"--- Reference from {md_file.name} ---\n{content}")
                print(f"      Loaded: {md_file.name}")
            except Exception as e:
                print(f"      Warning: Failed to load {md_file.name}: {e}")
        
        return "\n\n".join(combined_content)

    def _sanitize_folder_name(self, name: str) -> str:
        """Sanitize a string to be used as a folder name."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip().replace(' ', '_')[:100]

    def _sanitize_filename(self, name: str, max_length: int = 100) -> str:
        """
        Sanitize a string to be a safe Windows filename.
        - Removes invalid Windows characters
        - Normalizes whitespace
        - Handles reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        - Enforces maximum length
        """
        # Remove invalid Windows characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        # Normalize whitespace (replace multiple spaces/underscores with single underscore)
        name = re.sub(r'[\s_]+', '_', name)
        name = name.strip('_')
        
        # Handle Windows reserved names
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        name_upper = name.upper()
        if name_upper in reserved_names or any(name_upper.startswith(r + '.') for r in reserved_names):
            name = '_' + name
        
        # Enforce maximum length (leave room for extension)
        if len(name) > max_length:
            name = name[:max_length].rstrip('_')
        
        # Ensure not empty
        if not name:
            name = 'unnamed'
        
        return name

    def _build_subtopic_filename(self, lesson_number: int, subtopic_number: int, subtopic_title: str) -> str:
        """
        Build a standardized subtopic filename.
        Format: {lesson_number:02d}_{subtopic_number:02d}_{sanitized_subtopic_title}.txt
        """
        sanitized_title = self._sanitize_filename(subtopic_title, max_length=80)
        return f"{lesson_number:02d}_{subtopic_number:02d}_{sanitized_title}.txt"

    def _markdown_to_docx(self, doc, markdown_text: str):
        """
        Convert Markdown text to Word formatting.
        Supports:
        - # Heading 1, ## Heading 2, ### Heading 3
        - **bold**, *italic*
        - Bullet lists (- item, * item)
        - Numbered lists (1. item)
        - Code blocks (```)
        - Inline code (`code`)
        - Paragraphs with proper spacing
        """
        from docx.shared import Pt, RGBColor
        from docx.enum.style import WD_STYLE_TYPE
        
        lines = markdown_text.split('\n')
        i = 0
        in_code_block = False
        code_block_lines = []
        list_level = 0
        
        while i < len(lines):
            line = lines[i]
            
            if line.strip().startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    code_block_lines = []
                else:
                    in_code_block = False
                    # Add code block as a formatted paragraph
                    if code_block_lines:
                        code_para = doc.add_paragraph()
                        code_para.style = doc.styles['Normal']
                        run = code_para.add_run('\n'.join(code_block_lines))
                        run.font.name = 'Consolas'
                        run.font.size = Pt(9)
                        run.font.color.rgb = RGBColor(0x2D, 0x2D, 0x2D)
                        code_para.paragraph_format.space_after = Pt(6)
                        code_para.paragraph_format.space_before = Pt(6)
                i += 1
                continue
            
            if in_code_block:
                code_block_lines.append(line)
                i += 1
                continue
            
            stripped = line.lstrip()
            leading_spaces = len(line) - len(stripped)
            
            if stripped.startswith('# '):
                heading_text = stripped[2:].strip()
                heading = doc.add_heading(heading_text, level=1)
                heading.paragraph_format.space_after = Pt(12)
                heading.paragraph_format.space_before = Pt(18)
                i += 1
                continue
            
            if stripped.startswith('## '):
                heading_text = stripped[3:].strip()
                heading = doc.add_heading(heading_text, level=2)
                heading.paragraph_format.space_after = Pt(10)
                heading.paragraph_format.space_before = Pt(14)
                i += 1
                continue
            
            if stripped.startswith('### '):
                heading_text = stripped[4:].strip()
                heading = doc.add_heading(heading_text, level=3)
                heading.paragraph_format.space_after = Pt(8)
                heading.paragraph_format.space_before = Pt(12)
                i += 1
                continue
            
            if stripped.startswith('- ') or stripped.startswith('* '):
                list_text = stripped[2:].strip()
                para = doc.add_paragraph(style='List Bullet')
                self._add_formatted_text(para, list_text)
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                i += 1
                continue
            
            if re.match(r'^\d+\.\s+', stripped):
                list_text = re.sub(r'^\d+\.\s+', '', stripped)
                para = doc.add_paragraph(style='List Number')
                self._add_formatted_text(para, list_text)
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                i += 1
                continue
            
            if stripped == '':
                i += 1
                continue
            
            para = doc.add_paragraph()
            self._add_formatted_text(para, line)
            para.paragraph_format.space_after = Pt(6)
            i += 1

    def _add_formatted_text(self, paragraph, text: str):
        """
        Add text to a paragraph with bold/italic/code formatting.
        Supports **bold**, *italic*, `code`
        """
        from docx.shared import Pt, RGBColor
        
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', text)
        
        for part in parts:
            if part.startswith('**') and part.endswith('**') and len(part) > 4:
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith('*') and part.endswith('*') and len(part) > 2:
                run = paragraph.add_run(part[1:-1])
                run.italic = True
            elif part.startswith('`') and part.endswith('`') and len(part) > 2:
                run = paragraph.add_run(part[1:-1])
                run.font.name = 'Consolas'
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x2D, 0x2D, 0x2D)
            else:
                run = paragraph.add_run(part)
            run.font.size = Pt(11)

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
            "output_writing": "pending",
            "docx_export": "pending"
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

    def _update_checklist_custom_stage(self, stage_name: str, status: str):
        """Update a custom stage status in the checklist (e.g., docx_export)."""
        checklist_file = self.prompt_dir / "checklist.json"
        if checklist_file.exists():
            with open(checklist_file, 'r', encoding='utf-8') as f:
                checklist = json.load(f)
            
            if "stages" in checklist and stage_name in checklist["stages"]:
                checklist["stages"][stage_name] = status
                
                with open(checklist_file, 'w', encoding='utf-8') as f:
                    json.dump(checklist, f, indent=2)

    def _update_lessons_json(self):
        """Update the lessons.json file with current lessons data."""
        lessons_file = self.prompt_dir / "lessons.json"
        lessons_data = []
        for lesson in self.lessons:
            lessons_data.append({
                "id": lesson.id,
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
                    "lesson_id": lesson.id,
                    "lesson_title": lesson.title,
                    "subtopic_id": subtopic.id,
                    "title": subtopic.title,
                    "description": subtopic.description,
                    "estimated_chars": subtopic.estimated_chars,
                    "validation_status": subtopic.validation_status,
                    "validation_errors": subtopic.validation_errors,
                    "regeneration_attempt": subtopic.regeneration_attempt,
                    "regeneration_reason": subtopic.regeneration_reason
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
                    "lesson_id": lesson.id,
                    "lesson_title": lesson.title,
                    "subtopic_id": subtopic.id,
                    "subtopic_title": subtopic.title,
                    "completed": False,
                    "content_file": None
                })
        tasklist_data = {
            "tasks": tasks
        }
        with open(tasklist_file, 'w', encoding='utf-8') as f:
            json.dump(tasklist_data, f, indent=2)

    def _update_tasklist_entry(self, lesson_id: str, subtopic_id: str, content_filename: str):
        """Update a single tasklist entry to mark it as completed."""
        tasklist_file = self.prompt_dir / "tasklist.json"
        if not tasklist_file.exists():
            return
        try:
            with open(tasklist_file, 'r', encoding='utf-8') as f:
                tasklist_data = json.load(f)
            
            if "tasks" in tasklist_data:
                for task in tasklist_data["tasks"]:
                    if task["lesson_id"] == lesson_id and task["subtopic_id"] == subtopic_id:
                        task["completed"] = True
                        task["content_file"] = content_filename
                        break
            
            with open(tasklist_file, 'w', encoding='utf-8') as f:
                json.dump(tasklist_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not update tasklist: {e}")

    def _sync_tasklist_from_content_generation(self):
        """Sync tasklist with content_generation.json for resume - mark completed subtopics."""
        content_gen_file = self.prompt_dir / "content_generation.json"
        tasklist_file = self.prompt_dir / "tasklist.json"
        if not content_gen_file.exists() or not tasklist_file.exists():
            return
        try:
            with open(content_gen_file, 'r', encoding='utf-8') as f:
                content_gen_data = json.load(f)
            with open(tasklist_file, 'r', encoding='utf-8') as f:
                tasklist_data = json.load(f)
            
            # Build a map of completed subtopics from content_generation.json
            completed_map = {}
            for entry in content_gen_data.get("subtopics", []):
                if entry.get("status") == "completed" and entry.get("output_file"):
                    lesson_id = entry["lesson_id"]
                    subtopic_id = entry["subtopic_id"]
                    filename = Path(entry["output_file"]).name
                    completed_map[(lesson_id, subtopic_id)] = filename
            
            # Update tasklist
            if "tasks" in tasklist_data:
                for task in tasklist_data["tasks"]:
                    key = (task["lesson_id"], task["subtopic_id"])
                    if key in completed_map:
                        task["completed"] = True
                        task["content_file"] = completed_map[key]
            
            with open(tasklist_file, 'w', encoding='utf-8') as f:
                json.dump(tasklist_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not sync tasklist: {e}")

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
        
        # All intermediate files go under session_dir (NOT prompt-based)
        # This ensures complete session isolation - repeated prompts create isolated state
        self.prompt_dir = session_dir
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize checklist and JSON files in session directory
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
        
        # Run DOCX export stage after all pipeline stages complete
        print("\n[DOCX_EXPORT] Running...")
        try:
            self._update_checklist_custom_stage("docx_export", "running")
            export_output = self._run_docx_export()
            self._update_checklist_custom_stage("docx_export", "completed")
            print("[DOCX_EXPORT] Completed")
        except Exception as e:
            self._update_checklist_custom_stage("docx_export", "failed")
            print(f"[DOCX_EXPORT] Failed: {e}")
            raise

    def _save_lesson_outputs_to_session(self, lesson_outputs: List[LessonOutput]):
        """Save lesson outputs to session directory for OutputWriter consumption."""
        session_dir = self.processing_dir / "sessions" / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        output_file = session_dir / "lesson_outputs.json"
        data = {
            "lesson_outputs": [lo.model_dump() for lo in lesson_outputs if lo is not None]
        }
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

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
            # Restore lesson outputs from checkpoint and save to session directory
            lesson_outputs_data = output_data.get("lesson_outputs", [])
            if lesson_outputs_data:
                lesson_outputs = [LessonOutput(**lo) for lo in lesson_outputs_data]
                self._save_lesson_outputs_to_session(lesson_outputs)
            # Sync tasklist with completed content from content_generation.json
            self._sync_tasklist_from_content_generation()
            # Update checklist
            self._update_checklist_stage(stage, "completed")
        elif stage == PipelineStage.OUTPUT_WRITING:
            pass
            # Update checklist
            self._update_checklist_stage(stage, "completed")

    def _run_prompt_analysis(self) -> Dict[str, Any]:
        analysis = self.prompt_analyzer.analyze(self.user_input)
        self.prompt_analysis = analysis
        print(f"    Domain: {analysis.get('domain', 'N/A')}")
        print(f"    Complexity: {analysis.get('complexity', 'N/A')}")
        return {"analysis": analysis}

    def _run_web_search(self) -> Dict[str, Any]:
        self.web_search_report = self.web_search_manager.run_web_search(self.user_input)
        print(
            f"    Web search completed: "
            f"{self.web_search_report.quality_sources}/{self.web_search_report.total_results} quality sources"
        )
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
        # Generate subtopics with validation and regeneration (all done in generate_all)
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
        # Final validation: check count and that no subtopics have failed status
        if not self.subtopic_generator.validate_subtopics(self.lessons, self.user_input):
            # Check if there are failed subtopics we should report
            failed_subtopics = []
            for lesson in self.lessons:
                for subtopic in lesson.subtopics:
                    if subtopic.validation_status == "failed":
                        failed_subtopics.append(f"{lesson.title}/{subtopic.title}: {subtopic.validation_errors}")
            if failed_subtopics:
                raise ValueError(f"Subtopic validation failed for: {'; '.join(failed_subtopics)}")
            raise ValueError("Subtopic validation failed")
        
        print("    Subtopics validated successfully")
        # Update subtopics.json in prompt directory
        self._update_subtopics_json()
        # Create content-generation JSON
        self._create_content_generation_json()
        return {}

    def _create_content_generation_json(self):
        """Create the content-generation JSON with metadata for each subtopic."""
        content_gen_file = self.prompt_dir / "content_generation.json"
        
        # If the file already exists, do not overwrite (preserve resume capability)
        if content_gen_file.exists():
            print(f"    Content-generation JSON already exists, preserving existing progress.")
            # Still need to migrate in case of schema changes
            self._migrate_content_generation_json(content_gen_file)
            return
        
        # Determine CO, PO, K-level from prompt analysis
        co = ""
        po = ""
        k_level = ""
        if self.prompt_analysis:
            learning_objectives = self.prompt_analysis.get("learning_objectives", [])
            if learning_objectives and len(learning_objectives) > 0:
                co = learning_objectives[0]  # First learning objective as Course Outcome
            po = self.prompt_analysis.get("domain", "")  # Domain as Program Outcome
            k_level = self.prompt_analysis.get("complexity", "")  # Complexity as Knowledge level
        
        # Build lesson and subtopic number maps
        lesson_num_map = {}  # lesson_id -> lesson_number
        for idx, lesson in enumerate(self.lessons):
            lesson_num_map[lesson.id] = idx + 1
        
        subtopic_num_map = {}  # (lesson_id, subtopic_id) -> subtopic_number
        for lesson in self.lessons:
            for idx, subtopic in enumerate(lesson.subtopics):
                subtopic_num_map[(lesson.id, subtopic.id)] = idx + 1
        
        # Build subtopics list with complete schema
        subtopics_data = []
        for lesson in self.lessons:
            for subtopic in lesson.subtopics:
                lesson_number = lesson_num_map.get(lesson.id, 0)
                subtopic_number = subtopic_num_map.get((lesson.id, subtopic.id), 0)
                subtopic_entry = {
                    "lesson_id": lesson.id,
                    "lesson_number": lesson_number,
                    "lesson_title": lesson.title,
                    "subtopic_id": subtopic.id,
                    "subtopic_number": subtopic_number,
                    "subtopic_title": subtopic.title,
                    "subtopic_description": subtopic.description,
                    "subtopic_estimated_chars": subtopic.estimated_chars,
                    "subtopic_quality_score": getattr(subtopic, 'quality_score', None),
                    "co": co,
                    "po": po,
                    "k_level": k_level,
                    "status": "pending",  # pending, processing, completed, failed
                    "output_file": None,
                    "content_file": None,  # relative path to .txt file
                    "quiz_status": "pending",  # pending, processing, completed, failed
                    "quiz_questions_count": 0,
                    "question_bank_count": 0,
                    "quiz_error": None,
                    "quiz_generation_timestamp": None,
                    "metadata": {
                        "actual_chars": 0,
                        "generation_timestamp": None,
                        "error_message": None
                    }
                }
                subtopics_data.append(subtopic_entry)
        
        # Create the content-generation JSON structure
        content_gen_data = {
            "version": 4,  # Schema version for migration tracking
            "session_id": self.session_id,
            "prompt": self.user_input.prompt if self.user_input else "",
            "generated_on": datetime.utcnow().isoformat(),
            "subtopics": subtopics_data
        }
        
        # Atomic write to file
        self._atomic_write_json(content_gen_file, content_gen_data)
        
        print(f"    Created content-generation JSON with {len(subtopics_data)} subtopics")

    def _migrate_content_generation_json(self, content_gen_file: Path):
        """Migrate existing content_generation.json to current schema version."""
        try:
            with open(content_gen_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"    Warning: Could not load existing content_generation.json: {e}")
            return
        
        # Check version
        version = data.get("version", 1)
        if version >= 4:
            return  # Already current
        
        print(f"    Migrating content_generation.json from version {version} to 4...")
        migrated = False
        
        # Build lesson and subtopic number maps for current lessons
        lesson_num_map = {}  # lesson_id -> lesson_number
        lesson_title_map = {}  # lesson_id -> lesson_title
        for idx, lesson in enumerate(self.lessons):
            lesson_num_map[lesson.id] = idx + 1
            lesson_title_map[lesson.id] = lesson.title
        
        subtopic_num_map = {}  # (lesson_id, subtopic_id) -> subtopic_number
        subtopic_title_map = {}  # (lesson_id, subtopic_id) -> subtopic_title
        for lesson in self.lessons:
            for idx, subtopic in enumerate(lesson.subtopics):
                subtopic_num_map[(lesson.id, subtopic.id)] = idx + 1
                subtopic_title_map[(lesson.id, subtopic.id)] = subtopic.title
        
        for entry in data.get("subtopics", []):
            # Add missing fields with defaults
            if "lesson_number" not in entry:
                lesson_id = entry.get("lesson_id")
                if lesson_id:
                    entry["lesson_number"] = lesson_num_map.get(lesson_id, 0)
                    entry["lesson_title"] = lesson_title_map.get(lesson_id, entry.get("lesson_title", ""))
                    migrated = True
            
            if "subtopic_number" not in entry:
                lesson_id = entry.get("lesson_id")
                subtopic_id = entry.get("subtopic_id")
                if lesson_id and subtopic_id:
                    entry["subtopic_number"] = subtopic_num_map.get((lesson_id, subtopic_id), 0)
                    migrated = True
            
            if "subtopic_quality_score" not in entry:
                entry["subtopic_quality_score"] = None
                migrated = True
            
            if "content_file" not in entry:
                entry["content_file"] = None
                migrated = True
            
            if "metadata" not in entry:
                entry["metadata"] = {}
                migrated = True
            
            if "generation_timestamp" not in entry["metadata"]:
                entry["metadata"]["generation_timestamp"] = None
                migrated = True
            
            if "error_message" not in entry["metadata"]:
                entry["metadata"]["error_message"] = None
                migrated = True
            
            # Migrate lesson_id if missing but lesson_title exists
            if "lesson_id" not in entry and "lesson_title" in entry:
                matching_lesson = next((l for l in self.lessons if l.title == entry["lesson_title"]), None)
                if matching_lesson:
                    entry["lesson_id"] = matching_lesson.id
                    migrated = True
            
            # Migrate subtopic_id if missing but subtopic_title exists
            if "subtopic_id" not in entry and "subtopic_title" in entry and "lesson_id" in entry:
                matching_lesson = next((l for l in self.lessons if l.id == entry["lesson_id"]), None)
                if matching_lesson:
                    matching_subtopic = next((s for s in matching_lesson.subtopics if s.title == entry["subtopic_title"]), None)
                    if matching_subtopic:
                        entry["subtopic_id"] = matching_subtopic.id
                        migrated = True
            
            # Add new quiz fields (version 4+)
            if "quiz_status" not in entry:
                entry["quiz_status"] = "pending"
                migrated = True
            if "quiz_questions_count" not in entry:
                entry["quiz_questions_count"] = 0
                migrated = True
            if "question_bank_count" not in entry:
                entry["question_bank_count"] = 0
                migrated = True
            if "quiz_error" not in entry:
                entry["quiz_error"] = None
                migrated = True
            if "quiz_generation_timestamp" not in entry:
                entry["quiz_generation_timestamp"] = None
                migrated = True
        
        data["version"] = 4
        
        if migrated:
            print(f"    Migrated content_generation.json to version 4")
            self._atomic_write_json(content_gen_file, data)

    def _atomic_write_json(self, filepath: Path, data: Dict[str, Any]):
        """Write JSON atomically using temp file + rename."""
        import tempfile
        import os
        temp_fd, temp_path = tempfile.mkstemp(dir=filepath.parent, suffix='.tmp', prefix=filepath.stem + '_')
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Atomic rename on same filesystem
            os.replace(temp_path, filepath)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def _run_content_generation(self) -> Dict[str, Any]:
        print(f"    Generating content for {len(self.lessons)} lessons...")
        
        # Load the content-generation JSON
        content_gen_file = self.prompt_dir / "content_generation.json"
        if not content_gen_file.exists():
            raise FileNotFoundError(f"Content-generation JSON not found: {content_gen_file}")
        
        # Migrate if needed (handles schema updates)
        self._migrate_content_generation_json(content_gen_file)
        
        with open(content_gen_file, 'r', encoding='utf-8') as f:
            content_gen_data = json.load(f)
        
        # Prepare mappings for lesson and subtopic numbers (1-indexed) using stable IDs
        lesson_num_map = {}  # lesson_id -> lesson_number
        lesson_title_map = {}  # lesson_id -> lesson_title
        for idx, lesson in enumerate(self.lessons):
            lesson_num_map[lesson.id] = idx + 1
            lesson_title_map[lesson.id] = lesson.title
        
        subtopic_num_map = {}  # (lesson_id, subtopic_id) -> subtopic_number
        for lesson in self.lessons:
            for idx, subtopic in enumerate(lesson.subtopics):
                subtopic_num_map[(lesson.id, subtopic.id)] = idx + 1
        
        # Determine output directory (same as OutputWriter)
        if self.session_id:
            output_base_dir = self.output_writer.base_output_dir / self.session_id
        else:
            prompt_folder = self._sanitize_folder_name(self.user_input.prompt)
            output_base_dir = self.output_writer.base_output_dir / prompt_folder
        
        # Dictionary to hold generated content per lesson: lesson_id -> list of GeneratedContent
        lesson_contents = {lesson.id: [] for lesson in self.lessons}
        
        # Process each subtopic entry
        for entry in content_gen_data["subtopics"]:
            lesson_id = entry["lesson_id"]
            subtopic_id = entry["subtopic_id"]
            lesson_title = entry["lesson_title"]
            subtopic_title = entry["subtopic_title"]
            status = entry.get("status", "pending")
            
            # Get lesson and subtopic numbers
            lesson_number = lesson_num_map.get(lesson_id)
            subtopic_number = subtopic_num_map.get((lesson_id, subtopic_id))
            if lesson_number is None or subtopic_number is None:
                print(f"    Warning: Could not find lesson/subtopic for {lesson_title}/{subtopic_title} (IDs: {lesson_id}/{subtopic_id})")
                continue
            
            # Compute expected output file path
            filename = self._build_subtopic_filename(lesson_number, subtopic_number, subtopic_title)
            lesson_folder = self._sanitize_folder_name(lesson_title)
            lesson_dir = output_base_dir / lesson_folder
            lesson_dir.mkdir(parents=True, exist_ok=True)
            output_file_path = lesson_dir / filename
            
            if status == "completed":
                # If already completed, try to read the content from the file
                entry["output_file"] = str(output_file_path)
                entry["content_file"] = str(output_file_path.relative_to(output_base_dir)) if output_base_dir in output_file_path.parents else str(output_file_path)
                if output_file_path.exists():
                    try:
                        with open(output_file_path, 'r', encoding='utf-8') as f:
                            content_lines = f.readlines()
                        # Parse the file to extract content (format: Lesson:, Subtopic:, Character Count:, separator, then content)
                        content = ''.join(content_lines[6:])  # Skip first 6 lines
                        actual_chars = len(content)
                        # Update metadata
                        entry["metadata"]["actual_chars"] = actual_chars
                        entry["metadata"]["generation_timestamp"] = datetime.utcnow().isoformat()
                        # Create GeneratedContent object
                        generated_content = GeneratedContent(
                            lesson_title=lesson_title,
                            subtopic_title=subtopic_title,
                            content=content,
                            actual_chars=actual_chars
                        )
                        lesson_contents[lesson_id].append(generated_content)
                    except Exception as e:
                        print(f"Warning: Could not read content from {output_file_path}: {e}. Treating as failed.")
                        status = "failed"
                else:
                    print(f"Warning: Output file not found for completed entry: {output_file_path}. Treating as failed.")
                    status = "failed"
            
            if status in ("pending", "failed", "processing"):
                # Generate content for this subtopic
                entry["status"] = "processing"
                entry["metadata"]["generation_timestamp"] = datetime.utcnow().isoformat()
                entry["metadata"]["error_message"] = None
                # Atomic save to mark as processing
                self._atomic_write_json(content_gen_file, content_gen_data)
                
                try:
                    # Create Subtopic object from entry data
                    subtopic_obj = Subtopic(
                        title=subtopic_title,
                        description=entry["subtopic_description"],
                        estimated_chars=entry["subtopic_estimated_chars"]
                    )
                    # Generate content using LLM
                    generated_content = self.llm.generate_content(
                        lesson_title, subtopic_obj, self.user_input
                    )
                    
                    # Write content to file atomically
                    self._atomic_write_content(output_file_path, generated_content)
                    
                    # Update tasklist to mark this subtopic as completed
                    self._update_tasklist_entry(lesson_id, subtopic_id, filename)
                    
                    # Update entry with completed status and metadata
                    entry["status"] = "completed"
                    entry["output_file"] = str(output_file_path)
                    entry["content_file"] = str(output_file_path.relative_to(output_base_dir)) if output_base_dir in output_file_path.parents else str(output_file_path)
                    entry["metadata"]["actual_chars"] = generated_content.actual_chars
                    entry["metadata"]["generation_timestamp"] = datetime.utcnow().isoformat()
                    entry["metadata"]["error_message"] = None
                    
                    # Add to lesson contents
                    lesson_contents[lesson_id].append(generated_content)
                    
                    print(f"    Generated content for {lesson_title} - {subtopic_title}")
                
                except Exception as e:
                    entry["status"] = "failed"
                    entry["metadata"]["error_message"] = str(e)
                    entry["metadata"]["generation_timestamp"] = datetime.utcnow().isoformat()
                    print(f"    Error generating content for {lesson_title} - {subtopic_title}: {e}")
            
            # Atomic save after each entry update
            self._atomic_write_json(content_gen_file, content_gen_data)
        
        # Final atomic save for content
        self._atomic_write_json(content_gen_file, content_gen_data)
        
        # Now generate quiz and question bank for each lesson - PART OF THE TRANSACTION
        # Track quiz generation status in content_generation.json
        lesson_outputs = []
        quiz_generation_failed = False
        
        for i, lesson in enumerate(self.lessons):
            lesson_output = LessonOutput(
                lesson=lesson,
                generated_contents=lesson_contents[lesson.id],
                quiz_questions=[],  # placeholder
                question_bank=[]    # placeholder
            )
            lesson_outputs.append(lesson_output)
        
        for i, lesson in enumerate(self.lessons):
            # Find all entries for this lesson to update quiz status
            lesson_entries = [e for e in content_gen_data["subtopics"] if e["lesson_id"] == lesson.id]
            
            # Check if quiz already completed (resume case)
            quiz_already_completed = all(e.get("quiz_status") == "completed" for e in lesson_entries)
            if quiz_already_completed:
                # Restore quiz data from existing lesson_outputs if available
                if lesson_outputs[i].quiz_questions and lesson_outputs[i].question_bank:
                    print(f"    Quiz already completed for lesson {i+1}/{len(self.lessons)}: {lesson.title}, skipping")
                    continue
                else:
                    # Need to regenerate quiz even if content is done
                    print(f"    Quiz missing for lesson {i+1}/{len(self.lessons)}: {lesson.title}, regenerating")
            
            # Mark lesson as quiz-generating
            for entry in lesson_entries:
                entry["quiz_status"] = "processing"
                entry["quiz_generation_timestamp"] = datetime.utcnow().isoformat()
            self._atomic_write_json(content_gen_file, content_gen_data)
            
            try:
                quiz_questions = self.llm.generate_quiz(lesson, self.user_input)
                question_bank = self.llm.generate_question_bank(lesson, self.user_input)
                
                lesson_outputs[i].quiz_questions = quiz_questions
                lesson_outputs[i].question_bank = question_bank
                
                # Mark all entries for this lesson as quiz-completed
                for entry in lesson_entries:
                    entry["quiz_status"] = "completed"
                    entry["quiz_questions_count"] = len(quiz_questions)
                    entry["question_bank_count"] = len(question_bank)
                    entry["quiz_generation_timestamp"] = datetime.utcnow().isoformat()
                
                print(f"    Generated quiz and question bank for lesson {i+1}/{len(self.lessons)}: {lesson.title}")
                
            except Exception as e:
                # Quiz generation failed - mark lesson entries as failed
                for entry in lesson_entries:
                    entry["quiz_status"] = "failed"
                    entry["quiz_error"] = str(e)
                    entry["quiz_generation_timestamp"] = datetime.utcnow().isoformat()
                
                print(f"    Error generating quiz/question bank for {lesson.title}: {e}")
                quiz_generation_failed = True
            
            # Atomic save after each lesson's quiz generation
            self._atomic_write_json(content_gen_file, content_gen_data)
        
        total_chars = sum(
            c.actual_chars for lo in lesson_outputs for c in lo.generated_contents
        )
        print(f"    Generated {total_chars:,} characters of content")
        
        # If quiz generation failed for any lesson, fail the entire stage
        if quiz_generation_failed:
            raise RuntimeError("Quiz generation failed for one or more lessons. Check content_generation.json for details.")
        
        # Sync tasklist with completed content
        self._sync_tasklist_from_content_generation()
        
        # Save lesson outputs to session directory for OutputWriter
        self._save_lesson_outputs_to_session(lesson_outputs)
        
        self.session_manager.update_session_status(
            self.session_id, SessionStatus.RUNNING,
            completed_lessons=len(lesson_outputs)
        )
        
        return {"lesson_outputs": [lo.model_dump() for lo in lesson_outputs]}

    def _atomic_write_content(self, filepath: Path, content: GeneratedContent):
        """Write content file atomically using temp file + rename."""
        import tempfile
        import os
        temp_fd, temp_path = tempfile.mkstemp(dir=filepath.parent, suffix='.tmp', prefix=filepath.stem + '_')
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                f.write(f"Lesson: {content.lesson_title}\n")
                f.write(f"Subtopic: {content.subtopic_title}\n")
                f.write(f"Character Count: {content.actual_chars}\n")
                f.write("=" * 60 + "\n\n")
                f.write(content.content)
            os.replace(temp_path, filepath)
        except Exception:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def _run_output_writing(self) -> Dict[str, Any]:
        lesson_outputs = self._load_lesson_outputs()
        output_path = self.output_writer.write_all(
            self.user_input, lesson_outputs, self.web_search_report, self.session_id
        )
        print(f"    Output written to: {output_path}")
        return {"output_path": str(output_path)}

    def _run_docx_export(self) -> Dict[str, Any]:
        """Export completed subtopics to DOCX files in delivery/ folder."""
        from docx import Document
        from docx.shared import Inches, Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        
        # Load content-generation JSON
        content_gen_file = self.prompt_dir / "content_generation.json"
        if not content_gen_file.exists():
            raise FileNotFoundError(f"Content-generation JSON not found: {content_gen_file}")
        
        with open(content_gen_file, 'r', encoding='utf-8') as f:
            content_gen_data = json.load(f)
        
        # Determine delivery directory
        if self.session_id:
            delivery_base_dir = self.output_dir / "delivery" / self.session_id
        else:
            prompt_folder = self._sanitize_folder_name(self.user_input.prompt)
            delivery_base_dir = self.output_dir / "delivery" / prompt_folder
        
        delivery_base_dir.mkdir(parents=True, exist_ok=True)
        
        # Keep track of lessons for which we have copied quiz and question bank
        lessons_copied = set()
        
        # Prepare mappings for lesson and subtopic numbers using stable IDs
        lesson_num_map = {}
        for idx, lesson in enumerate(self.lessons):
            lesson_num_map[lesson.id] = idx + 1
        
        subtopic_num_map = {}
        for lesson in self.lessons:
            for idx, subtopic in enumerate(lesson.subtopics):
                subtopic_num_map[(lesson.id, subtopic.id)] = idx + 1
        
        total_subtopics = len(content_gen_data.get("subtopics", []))
        completed_subtopics = [e for e in content_gen_data["subtopics"] if e.get("status") == "completed"]
        exported_count = 0
        failed_count = 0
        
        print(f"    Exporting {len(completed_subtopics)} completed subtopics to DOCX...")
        
        for entry in content_gen_data["subtopics"]:
            lesson_id = entry.get("lesson_id") or entry["lesson_title"]
            subtopic_id = entry.get("subtopic_id") or entry["subtopic_title"]
            lesson_title = entry["lesson_title"]
            subtopic_title = entry["subtopic_title"]
            status = entry.get("status", "pending")
            export_status = entry.get("export_status", "pending")
            docx_path = entry.get("docx_path")
            
            # Only export completed subtopics that haven't been exported yet
            if status != "completed":
                continue
                
            if export_status == "completed" and docx_path:
                # Verify file exists
                full_docx_path = Path(docx_path)
                if full_docx_path.exists():
                    exported_count += 1
                    continue
                else:
                    # File missing, reset export status
                    entry["export_status"] = "pending"
                    entry["docx_path"] = None
            
            # Update export status to processing
            entry["export_status"] = "processing"
            # Save immediately
            with open(content_gen_file, 'w', encoding='utf-8') as f:
                json.dump(content_gen_data, f, indent=2, ensure_ascii=False)
            
            try:
                # Get lesson and subtopic numbers using stable IDs
                lesson_number = lesson_num_map.get(lesson_id)
                subtopic_number = subtopic_num_map.get((lesson_id, subtopic_id))
                if lesson_number is None or subtopic_number is None:
                    raise ValueError(f"Could not find lesson/subtopic numbers for {lesson_title}/{subtopic_title} (IDs: {lesson_id}/{subtopic_id})")
                
                # Read content from .txt file
                output_file_path = entry.get("output_file")
                if not output_file_path or not Path(output_file_path).exists():
                    raise FileNotFoundError(f"Source .txt file not found: {output_file_path}")
                
                with open(output_file_path, 'r', encoding='utf-8') as f:
                    content_lines = f.readlines()
                
                # Parse content (skip header lines)
                content = ''.join(content_lines[6:]) if len(content_lines) > 6 else ''.join(content_lines)
                
                # Create DOCX
                doc = Document()
                
                # Title
                title = doc.add_heading(f"Lesson {lesson_number}: {lesson_title}", level=1)
                title.alignment = WD_ALIGN_PARAGRAPH.CENTER
                
                # Subtopic
                subtopic_heading = doc.add_heading(f"Subtopic {subtopic_number}: {subtopic_title}", level=2)
                
                # Metadata table
                table = doc.add_table(rows=5, cols=2, style='Table Grid')
                table.cell(0, 0).text = "Lesson"
                table.cell(0, 1).text = f"{lesson_number}: {lesson_title}"
                table.cell(1, 0).text = "Subtopic"
                table.cell(1, 1).text = f"{subtopic_number}: {subtopic_title}"
                table.cell(2, 0).text = "Course Outcome (CO)"
                table.cell(2, 1).text = entry.get("co", "N/A")
                table.cell(3, 0).text = "Program Outcome (PO)"
                table.cell(3, 1).text = entry.get("po", "N/A")
                table.cell(4, 0).text = "Knowledge Level (K-Level)"
                table.cell(4, 1).text = entry.get("k_level", "N/A")
                
                # Content
                doc.add_heading("Content", level=2)
                self._markdown_to_docx(doc, content)
                
                # Build delivery path: delivery/{lesson_number}_{lesson_name}/{lesson_number}.{subtopic_number}_{subtopic_name}.docx
                sanitized_lesson = self._sanitize_folder_name(lesson_title)
                sanitized_subtopic = self._sanitize_folder_name(subtopic_title)
                lesson_folder = f"{lesson_number:02d}_{sanitized_lesson}"
                filename = f"{lesson_number:02d}.{subtopic_number:02d}_{sanitized_subtopic}.docx"
                
                lesson_delivery_dir = delivery_base_dir / lesson_folder
                lesson_delivery_dir.mkdir(parents=True, exist_ok=True)
                
                # Copy quiz and question bank files for the lesson (once per lesson)
                if lesson_title not in lessons_copied:
                    # Output lesson directory (same as in OutputWriter)
                    if self.session_id:
                        output_base_dir = self.output_writer.base_output_dir / self.session_id
                    else:
                        prompt_folder = self._sanitize_folder_name(self.user_input.prompt)
                        output_base_dir = self.output_writer.base_output_dir / prompt_folder
                    
                    output_lesson_dir = output_base_dir / self._sanitize_folder_name(lesson_title)
                    
                    # Define files to copy
                    files_to_copy = ["quiz.csv", "question_bank.csv"]
                    for file_name in files_to_copy:
                        src_file = output_lesson_dir / file_name
                        dst_file = lesson_delivery_dir / file_name
                        if src_file.exists():
                            try:
                                shutil.copy2(src_file, dst_file)
                                print(f"        Copied {file_name} to delivery")
                            except Exception as e:
                                print(f"        Warning: Failed to copy {file_name}: {e}")
                        else:
                            print(f"        Warning: {file_name} not found in output lesson directory: {output_lesson_dir}")
                    
                    lessons_copied.add(lesson_title)
                
                docx_file_path = lesson_delivery_dir / filename
                doc.save(docx_file_path)
                
                # Update entry with success
                entry["export_status"] = "completed"
                entry["docx_path"] = str(docx_file_path)
                exported_count += 1
                
                # Save JSON
                with open(content_gen_file, 'w', encoding='utf-8') as f:
                    json.dump(content_gen_data, f, indent=2, ensure_ascii=False)
                
                print(f"      Exported: {lesson_folder}/{filename}")
                
            except Exception as e:
                entry["export_status"] = "failed"
                entry["export_error"] = str(e)
                failed_count += 1
                print(f"      Failed to export {lesson_title}/{subtopic_title}: {e}")
                
                # Save JSON
                with open(content_gen_file, 'w', encoding='utf-8') as f:
                    json.dump(content_gen_data, f, indent=2, ensure_ascii=False)
        
        # Final validation: check all completed subtopics have DOCX
        all_completed = [e for e in content_gen_data["subtopics"] if e.get("status") == "completed"]
        all_exported = [e for e in all_completed if e.get("export_status") == "completed"]
        
        if len(all_exported) < len(all_completed):
            missing = len(all_completed) - len(all_exported)
            raise RuntimeError(f"DOCX export incomplete: {missing} completed subtopics missing DOCX files")
        
        print(f"    DOCX export complete: {exported_count} exported, {failed_count} failed")
        # Validate that quiz and question bank CSV files exist in delivery for each lesson
        for lesson in self.lessons:
            sanitized_lesson = self._sanitize_folder_name(lesson.title)
            lesson_number = lesson_num_map[lesson.id]
            lesson_folder = f"{lesson_number:02d}_{sanitized_lesson}"
            lesson_delivery_dir = delivery_base_dir / lesson_folder
            quiz_path = lesson_delivery_dir / "quiz.csv"
            question_bank_path = lesson_delivery_dir / "question_bank.csv"
            if not quiz_path.exists():
                raise RuntimeError(f"Quiz CSV missing for lesson {lesson.title} in delivery: {quiz_path}")
            if not question_bank_path.exists():
                raise RuntimeError(f"Question bank CSV missing for lesson {lesson.title} in delivery: {question_bank_path}")

        return {
            "delivery_dir": str(delivery_base_dir),
            "exported_count": exported_count,
            "failed_count": failed_count
        }

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