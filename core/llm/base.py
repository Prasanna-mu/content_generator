from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from core.models.schemas import UserInput, Lesson, Subtopic, GeneratedContent, QuizQuestion, QuestionBankItem


class BaseLLMProvider(ABC):
    def __init__(self, model_name: str, base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        pass

    @abstractmethod
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        pass

    def generate_lessons(self, user_input: UserInput) -> List[Dict[str, Any]]:
        prompt = self._build_lesson_prompt(user_input)
        system_prompt = self._get_lesson_system_prompt()
        result = self.generate_json(prompt, system_prompt)
        return result.get("lessons", [])

    def generate_subtopics(self, lesson: Lesson, user_input: UserInput) -> List[Subtopic]:
        prompt = self._build_subtopic_prompt(lesson, user_input)
        system_prompt = self._get_subtopic_system_prompt()
        result = self.generate_json(prompt, system_prompt)
        return [Subtopic(**subtopic) for subtopic in result.get("subtopics", [])]

    def generate_content(self, lesson_title: str, subtopic: Subtopic, user_input: UserInput) -> GeneratedContent:
        prompt = self._build_content_prompt(lesson_title, subtopic, user_input)
        system_prompt = self._get_content_system_prompt(user_input)
        content = self.generate(prompt, system_prompt)
        return GeneratedContent(
            lesson_title=lesson_title,
            subtopic_title=subtopic.title,
            content=content,
            actual_chars=len(content)
        )

    def generate_quiz(self, lesson: Lesson, user_input: UserInput) -> List[QuizQuestion]:
        prompt = self._build_quiz_prompt(lesson, user_input)
        system_prompt = self._get_quiz_system_prompt(user_input)
        result = self.generate_json(prompt, system_prompt)
        return [QuizQuestion(**q) for q in result.get("questions", [])]

    def generate_question_bank(
        self,
        lesson: Lesson,
        user_input: UserInput
    ) -> List[QuestionBankItem]:
        prompt = self._build_question_bank_prompt(lesson, user_input)
        system_prompt = self._get_question_bank_system_prompt(user_input)

        result = self.generate_json(prompt, system_prompt)

        questions = []

        for index, q in enumerate(result.get("questions", []), start=1):
            # Some LLM responses may omit difficulty even though
            # the prompt explicitly requests it.
            # Fall back to the user's configured quiz difficulty.
            if not q.get("difficulty"):
                q["difficulty"] = user_input.quiz_difficulty.value

            try:
                questions.append(QuestionBankItem(**q))
            except Exception as e:
                raise ValueError(
                    f"Invalid question bank item #{index} "
                    f"for lesson '{lesson.title}': {q}"
                ) from e

        return questions

    def _build_lesson_prompt(self, user_input: UserInput) -> str:
        return f"""
Generate EXACTLY {user_input.num_lessons} lessons for the topic: "{user_input.prompt}"

STRICT REQUIREMENTS:
- You MUST generate exactly {user_input.num_lessons} lessons - no more, no less
- Each lesson must have a clear title and description
- Lessons should progress logically from basic to advanced
- Cover the topic comprehensively across exactly {user_input.num_lessons} lessons

Return JSON format:
{{
    "lessons": [
        {{"title": "Lesson Title", "description": "Lesson description"}},
        ...
    ]
}}
"""

    def _build_subtopic_prompt(self, lesson: Lesson, user_input: UserInput) -> str:
        return f"""
Generate EXACTLY {user_input.subtopics_per_lesson} subtopics for lesson: "{lesson.title}"
Lesson description: {lesson.description}
Main topic: {user_input.prompt}

STRICT REQUIREMENTS:
- You MUST generate exactly {user_input.subtopics_per_lesson} subtopics - no more, no less
- Each subtopic must have a title, description, and estimated character count
- Subtopics should cover the lesson comprehensively
- Character estimates based on content length: {user_input.content_length.value}

Return JSON format:
{{
    "subtopics": [
        {{"title": "Subtopic Title", "description": "Description", "estimated_chars": 1000}},
        ...
    ]
}}
"""

    def _build_content_prompt(self, lesson_title: str, subtopic: Subtopic, user_input: UserInput) -> str:
        length_guide = {
            "extreme": "very comprehensive, 3000+ characters",
            "long": "detailed, 2000-3000 characters",
            "medium": "moderate, 1000-2000 characters",
            "simple": "concise, 500-1000 characters"
        }
        
        quality_guide = {
            "technical": "highly technical with code examples, formulas, and deep technical details",
            "intermediate": "balanced technical depth with practical examples",
            "beginner": "simple explanations, analogies, minimal jargon"
        }
        
        return f"""
Write content for subtopic: "{subtopic.title}"
Lesson: "{lesson_title}"
Main topic: {user_input.prompt}
Subtopic description: {subtopic.description}

Requirements:
- Content length: {length_guide.get(user_input.content_length.value, "moderate")}
- Quality level: {quality_guide.get(user_input.content_quality.value, "balanced")}
- Target ~{subtopic.estimated_chars} characters
- Well-structured with headers, examples, and clear explanations
- No markdown formatting in output, plain text only
"""

    def _build_quiz_prompt(self, lesson: Lesson, user_input: UserInput) -> str:
        difficulty_guide = {
            "technical": "challenging, requiring deep understanding and application",
            "intermediate": "moderate, testing comprehension and application",
            "beginner": "basic, testing recall and fundamental understanding"
        }
        
        return f"""
Generate {user_input.quiz_question_count} quiz questions for lesson: "{lesson.title}"
Lesson description: {lesson.description}
Subtopics: {[s.title for s in lesson.subtopics]}

Requirements:
- Difficulty: {difficulty_guide.get(user_input.quiz_difficulty.value, "moderate")}
- Multiple choice with 4 options each
- Include correct answer index (0-3) and explanation
- Cover all subtopics

Return JSON format:
{{
    "questions": [
        {{"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": 0, "explanation": "..."}},
        ...
    ]
}}
"""

    def _build_question_bank_prompt(self, lesson: Lesson, user_input: UserInput) -> str:
        return f"""
Generate {user_input.question_bank_count} question bank items for lesson: "{lesson.title}"
Lesson description: {lesson.description}

Requirements:
- Mix of question types (short answer, essay, problem-solving)
- Include difficulty level (beginner/intermediate/technical)
- Provide model answers
- Cover all subtopics comprehensively

Return JSON format:
{{
    "questions": [
        {{"question": "...", "answer": "...", "difficulty": "intermediate"}},
        ...
    ]
}}
"""

    def _get_lesson_system_prompt(self) -> str:
        return "You are an expert curriculum designer. Create structured, progressive lesson plans."

    def _get_subtopic_system_prompt(self) -> str:
        return "You are an expert content planner. Break down lessons into detailed subtopics with accurate character estimates."

    def _get_content_system_prompt(self, user_input: UserInput) -> str:
        return f"You are an expert educational content writer. Write {user_input.content_quality.value} level content with {user_input.content_length.value} length."

    def _get_quiz_system_prompt(self, user_input: UserInput) -> str:
        return f"You are an expert assessment designer. Create {user_input.quiz_difficulty.value} level quiz questions."

    def _get_question_bank_system_prompt(self, user_input: UserInput) -> str:
        return "You are an expert question bank creator. Generate comprehensive practice questions with model answers."