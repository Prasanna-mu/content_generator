from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.models.schemas import UserInput, Lesson, GeneratedContent, QuizQuestion, QuestionBankItem, LessonOutput
from core.llm.base import BaseLLMProvider


class ContentGenerator:
    def __init__(self, llm: BaseLLMProvider, worker_count: int = 4):
        self.llm = llm
        self.worker_count = max(1, worker_count)

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