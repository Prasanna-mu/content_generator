from typing import List
from pathlib import Path
import uuid
from core.models.schemas import UserInput, Lesson
from core.llm.base import BaseLLMProvider
import json


class LessonGenerator:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    def generate(self, user_input: UserInput) -> List[Lesson]:
        lessons_data = self.llm.generate_lessons(user_input)
        
        lessons = []
        for i, lesson_data in enumerate(lessons_data, 1):
            lesson = Lesson(
                title=lesson_data["title"],
                description=lesson_data["description"],
                subtopics=[],
                estimated_total_chars=0
            )
            lessons.append(lesson)
        
        return lessons

    def refine_lessons(self, lessons: List[Lesson], user_input: UserInput) -> List[Lesson]:
        for lesson in lessons:
            prompt = f"""
Refine lesson:
Title: {lesson.title}
Description: {lesson.description}
Main topic: {user_input.prompt}

Improve the title and description for clarity and progression.
Return JSON: {{"title": "...", "description": "..."}}
"""
            system_prompt = "You are an expert curriculum designer. Refine lesson titles and descriptions."
            result = self.llm.generate_json(prompt, system_prompt, temperature=0.3)
            lesson.title = result.get("title", lesson.title)
            lesson.description = result.get("description", lesson.description)
        
        # Save refined lessons
        self._save_lessons(lessons)
        
        return lessons

    def _save_lessons(self, lessons: List[Lesson]):
        if self.llm._output_dir:
            data = {"lessons": [{"id": l.id, "title": l.title, "description": l.description} for l in lessons]}
            filepath = self.llm._output_dir / "lessons_refined.json"
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Saved refined lessons: {filepath}")

    def load_saved_lessons(self, user_input: UserInput) -> List[Lesson]:
        """Load previously saved lessons from intermediate output."""
        if self.llm._output_dir:
            filepath = self.llm._output_dir / "lessons_refined.json"
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                lessons = []
                for lesson_data in data.get("lessons", []):
                    lesson = Lesson(
                        id=lesson_data.get("id", str(uuid.uuid4())),
                        title=lesson_data["title"],
                        description=lesson_data["description"],
                        subtopics=[],
                        estimated_total_chars=0
                    )
                    lessons.append(lesson)
                print(f"  Loaded {len(lessons)} lessons from saved output")
                return lessons
        return []