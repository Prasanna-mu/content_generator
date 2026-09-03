from pathlib import Path
from typing import List, Optional
import os
from core.models.schemas import UserInput, Lesson, LessonOutput, PipelineConfig
from core.llm.factory import LLMFactory
from core.llm.base import BaseLLMProvider
from core.planning.prompt_analyzer import PromptAnalyzer
from core.planning.lesson_generator import LessonGenerator
from core.planning.subtopic_generator import SubtopicGenerator
from core.generation.content_generator import ContentGenerator
from core.output.writer import OutputWriter


class PipelineOrchestrator:
    def __init__(
        self,
        model_name: str = "qwen2.5:3b",
        provider: str = "ollama",
        base_url: str = "http://localhost:11434",
        output_dir: Path = Path("output"),
        worker_count: int = 4
    ):
        self.model_name = model_name
        self.provider = provider
        self.base_url = base_url
        self.output_dir = output_dir
        self.worker_count = worker_count
        
        self.llm: Optional[BaseLLMProvider] = None
        self.prompt_analyzer: Optional[PromptAnalyzer] = None
        self.lesson_generator: Optional[LessonGenerator] = None
        self.subtopic_generator: Optional[SubtopicGenerator] = None
        self.content_generator: Optional[ContentGenerator] = None
        self.output_writer: Optional[OutputWriter] = None

    def initialize(self):
        self.llm = LLMFactory.create(self.provider, self.model_name, self.base_url)
        
        if not self.llm.check_connection():
            raise ConnectionError(f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?")
        
        available_models = self.llm.list_models()
        if self.model_name not in available_models:
            print(f"Model {self.model_name} not found. Pulling...")
            if not self.llm.pull_model():
                raise RuntimeError(f"Failed to pull model {self.model_name}")
        
        self.prompt_analyzer = PromptAnalyzer(self.llm)
        self.lesson_generator = LessonGenerator(self.llm)
        self.subtopic_generator = SubtopicGenerator(self.llm)
        self.content_generator = ContentGenerator(self.llm, self.worker_count)
        self.output_writer = OutputWriter(self.output_dir)

    def run(self, user_input: UserInput) -> List[LessonOutput]:
        print("\n" + "=" * 60)
        print("Starting Content Generation Pipeline")
        print("=" * 60)
        
        print("\n[1/5] Analyzing prompt...")
        analysis = self.prompt_analyzer.analyze(user_input)
        print(f"    Domain: {analysis.get('domain', 'N/A')}")
        print(f"    Complexity: {analysis.get('complexity', 'N/A')}")
        
        print("\n[2/5] Generating lessons...")
        lessons = self.lesson_generator.generate(user_input)
        lessons = self.lesson_generator.refine_lessons(lessons, user_input)
        print(f"    Generated {len(lessons)} lessons")
        
        print("\n[3/5] Generating subtopics...")
        lessons = self.subtopic_generator.generate_all(lessons, user_input)
        lessons = self.subtopic_generator.adjust_estimates(lessons, user_input)
        total_subtopics = sum(len(l.subtopics) for l in lessons)
        print(f"    Generated {total_subtopics} subtopics")
        
        print("\n[4/5] Generating content (this may take a while)...")
        lesson_outputs = self.content_generator.generate_all(lessons, user_input)
        total_chars = sum(
            c.actual_chars for lo in lesson_outputs for c in lo.generated_contents
        )
        print(f"    Generated {total_chars:,} characters of content")
        
        print("\n[5/5] Writing output files...")
        self.output_writer.write_all(user_input, lesson_outputs)
        
        print("\n" + "=" * 60)
        print("Pipeline Complete!")
        print("=" * 60)
        
        return lesson_outputs

    def run_from_json(self, json_path: Path) -> List[LessonOutput]:
        from userinput import load_user_input_json
        user_input = load_user_input_json(json_path)
        return self.run(user_input)