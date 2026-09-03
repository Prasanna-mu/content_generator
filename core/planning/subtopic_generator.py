from typing import List
from core.models.schemas import UserInput, Lesson, Subtopic
from core.llm.base import BaseLLMProvider


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