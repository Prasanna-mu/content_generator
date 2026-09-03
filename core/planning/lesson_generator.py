from typing import List
from core.models.schemas import UserInput, Lesson
from core.llm.base import BaseLLMProvider


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
        for i, lesson in enumerate(lessons):
            prompt = f"""
Refine lesson {i+1}/{len(lessons)}:
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
        
        return lessons