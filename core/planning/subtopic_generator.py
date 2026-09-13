from typing import List
from pathlib import Path
from core.models.schemas import UserInput, Lesson, Subtopic
from core.llm.base import BaseLLMProvider
import json


class SubtopicGenerator:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    def generate_for_lesson(self, lesson: Lesson, user_input: UserInput) -> List[Subtopic]:
        subtopics_data = self.llm.generate_subtopics(lesson, user_input)
        
        subtopics = []
        for subtopic_data in subtopics_data:
            subtopic = Subtopic(
                title=subtopic_data.title,
                description=subtopic_data.description,
                estimated_chars=subtopic_data.estimated_chars
            )
            subtopics.append(subtopic)
        
        lesson.subtopics = subtopics
        lesson.estimated_total_chars = sum(s.estimated_chars for s in subtopics)
        return subtopics

    def generate_all(self, lessons: List[Lesson], user_input: UserInput) -> List[Lesson]:
        for lesson in lessons:
            self.generate_for_lesson(lesson, user_input)
        # Save all subtopics after generation
        self._save_subtopics(lessons)
        return lessons

    def adjust_estimates(self, lessons: List[Lesson], user_input: UserInput) -> List[Lesson]:
        length_multipliers = {
            "extreme": 1.5,
            "long": 1.2,
            "medium": 1.0,
            "simple": 0.7
        }
        multiplier = length_multipliers.get(user_input.content_length.value, 1.0)
        
        for lesson in lessons:
            for subtopic in lesson.subtopics:
                subtopic.estimated_chars = int(subtopic.estimated_chars * multiplier)
            lesson.estimated_total_chars = sum(s.estimated_chars for s in lesson.subtopics)
        
        return lessons

    def _save_subtopics(self, lessons: List[Lesson]):
        if self.llm._output_dir:
            data = {
                "subtopics": [
                    {
                        "lesson_title": lesson.title,
                        "subtopics": [
                            {
                                "title": s.title,
                                "description": s.description,
                                "estimated_chars": s.estimated_chars
                            }
                            for s in lesson.subtopics
                        ]
                    }
                    for lesson in lessons
                ]
            }
            filepath = self.llm._output_dir / "subtopics_all.json"
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Saved all subtopics: {filepath}")

    def validate_subtopics(self, lessons: List[Lesson], user_input: UserInput) -> bool:
        """Validate that all lessons have the correct number of subtopics with required fields."""
        expected_per_lesson = user_input.subtopics_per_lesson
        for lesson in lessons:
            if len(lesson.subtopics) != expected_per_lesson:
                print(f"  Validation failed: Lesson '{lesson.title}' has {len(lesson.subtopics)} subtopics, expected {expected_per_lesson}")
                return False
            for subtopic in lesson.subtopics:
                if not subtopic.title or not subtopic.description:
                    print(f"  Validation failed: Subtopic missing title or description in lesson '{lesson.title}'")
                    return False
                if subtopic.estimated_chars <= 0:
                    print(f"  Validation failed: Subtopic '{subtopic.title}' has invalid estimated_chars: {subtopic.estimated_chars}")
                    return False
        return True

    def load_saved_subtopics(self, lessons: List[Lesson], user_input: UserInput) -> List[Lesson]:
        """Load previously saved subtopics from intermediate output and apply to lessons."""
        if self.llm._output_dir:
            filepath = self.llm._output_dir / "subtopics_all.json"
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Create a lookup map
                subtopic_map = {}
                for item in data.get("subtopics", []):
                    subtopic_map[item["lesson_title"]] = item["subtopics"]
                
                # Apply to lessons
                for lesson in lessons:
                    if lesson.title in subtopic_map:
                        saved_subtopics = subtopic_map[lesson.title]
                        lesson.subtopics = []
                        for s_data in saved_subtopics:
                            subtopic = Subtopic(
                                title=s_data["title"],
                                description=s_data["description"],
                                estimated_chars=s_data["estimated_chars"]
                            )
                            lesson.subtopics.append(subtopic)
                        lesson.estimated_total_chars = sum(s.estimated_chars for s in lesson.subtopics)
                
                print(f"  Loaded subtopics for {len(subtopic_map)} lessons from saved output")
                return lessons
        return lessons