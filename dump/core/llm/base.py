from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from core.models.schemas import UserInput, Lesson, Subtopic, GeneratedContent, QuizQuestion, QuestionBankItem
from pathlib import Path
import json


class BaseLLMProvider(ABC):
    def __init__(self, model_name: str, base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
        self._output_dir: Optional[Path] = None
        self.reference_context: str = ""

    def set_output_dir(self, output_dir: Path):
        self._output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

    def set_reference_context(self, reference_context: str):
        """Set the reference context for content generation."""
        self.reference_context = reference_context

    def _save_intermediate_json(self, filename: str, data: Dict[str, Any]):
        if self._output_dir:
            filepath = self._output_dir / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Saved intermediate output: {filepath}")

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        pass

    @abstractmethod
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        pass

    def generate_json_with_validation(
        self,
        prompt: str,
        system_prompt: Optional[str],
        validator: Callable[[Dict[str, Any]], bool],
        max_retries: int = 3,
        save_as: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        for attempt in range(max_retries):
            try:
                result = self.generate_json(prompt, system_prompt, **kwargs)
                if validator(result):
                    if save_as:
                        self._save_intermediate_json(save_as, result)
                    return result
                else:
                    print(f"  Validation failed (attempt {attempt + 1}/{max_retries}), retrying...")
            except Exception as e:
                print(f"  Generation error (attempt {attempt + 1}/{max_retries}): {e}")
        raise ValueError(f"Failed to generate valid JSON after {max_retries} attempts")

    def validate_lessons_json(self, data: Dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        lessons = data.get("lessons", [])
        if not isinstance(lessons, list) or len(lessons) == 0:
            return False
        for lesson in lessons:
            if not isinstance(lesson, dict):
                return False
            if not lesson.get("title") or not lesson.get("description"):
                return False
        return True

    def validate_subtopics_json(self, data: Dict[str, Any], expected_count: int = 0) -> bool:
        if not isinstance(data, dict):
            return False
        subtopics = data.get("subtopics", [])
        if not isinstance(subtopics, list):
            return False
        if expected_count > 0 and len(subtopics) != expected_count:
            return False
        for subtopic in subtopics:
            if not isinstance(subtopic, dict):
                return False
            if not subtopic.get("title") or not subtopic.get("description"):
                return False
            if "estimated_chars" not in subtopic or not isinstance(subtopic["estimated_chars"], int):
                return False
            if subtopic["estimated_chars"] <= 0:
                return False
        return True

    def validate_quiz_json(self, data: Dict[str, Any], expected_count: int = 0) -> bool:
        if not isinstance(data, dict):
            return False
        questions = data.get("questions", [])
        if not isinstance(questions, list):
            return False
        if expected_count > 0 and len(questions) != expected_count:
            return False
        for q in questions:
            if not isinstance(q, dict):
                return False
            if not q.get("question") or not isinstance(q.get("options"), list) or len(q["options"]) != 4:
                return False
            if "correct_answer" not in q or not isinstance(q["correct_answer"], int):
                return False
            if q["correct_answer"] < 0 or q["correct_answer"] > 3:
                return False
            # Check k_level
            k_level = q.get("k_level")
            if not k_level or not isinstance(k_level, str):
                return False
            import re
            if not re.match(r'^K[1-6]$', k_level):
                return False
        return True

    def validate_question_bank_json(self, data: Dict[str, Any], expected_count: int = 0) -> bool:
        if not isinstance(data, dict):
            return False
        questions = data.get("questions", [])
        if not isinstance(questions, list):
            return False
        if expected_count > 0 and len(questions) != expected_count:
            return False
        for q in questions:
            if not isinstance(q, dict):
                return False
            if not q.get("question") or not q.get("answer"):
                return False
            # Check k_level
            k_level = q.get("k_level")
            if not k_level or not isinstance(k_level, str):
                return False
            import re
            if not re.match(r'^K[1-6]$', k_level):
                return False
        return True

    def generate_lessons(self, user_input: UserInput) -> List[Dict[str, Any]]:
        prompt = self._build_lesson_prompt(user_input)
        system_prompt = self._get_lesson_system_prompt()
        result = self.generate_json_with_validation(
            prompt, system_prompt,
            lambda d: self.validate_lessons_json(d),
            max_retries=3,
            save_as="lessons.json"
        )
        return result.get("lessons", [])

    def generate_subtopics(self, lesson: Lesson, user_input: UserInput) -> List[Subtopic]:
        prompt = self._build_subtopic_prompt(lesson, user_input)
        system_prompt = self._get_subtopic_system_prompt()
        expected = user_input.subtopics_per_lesson
        result = self.generate_json_with_validation(
            prompt, system_prompt,
            lambda d: self.validate_subtopics_json(d, expected),
            max_retries=3,
            save_as=f"subtopics_{lesson.title.replace(' ', '_')}.json"
        )
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
        expected = user_input.quiz_question_count
        result = self.generate_json_with_validation(
            prompt, system_prompt,
            lambda d: self.validate_quiz_json(d, expected),
            max_retries=3,
            save_as=f"quiz_{lesson.title.replace(' ', '_')}.json"
        )
        return [QuizQuestion(**q) for q in result.get("questions", [])]

    def generate_question_bank(
        self,
        lesson: Lesson,
        user_input: UserInput
    ) -> List[QuestionBankItem]:
        prompt = self._build_question_bank_prompt(lesson, user_input)
        system_prompt = self._get_question_bank_system_prompt(user_input)
        expected = user_input.question_bank_count
        result = self.generate_json_with_validation(
            prompt, system_prompt,
            lambda d: self.validate_question_bank_json(d, expected),
            max_retries=3,
            save_as=f"question_bank_{lesson.title.replace(' ', '_')}.json"
        )

        questions = []

        for index, q in enumerate(result.get("questions", []), start=1):
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
        
        reference_section = ""
        if self.reference_context:
            reference_section = f"""
Reference Material:
{self.reference_context}

"""
        
        return f"""
{reference_section}Write content for subtopic: "{subtopic.title}"
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
- Include knowledge level (K1-K6) for each question
- Cover all subtopics

Return JSON format:
{{
    "questions": [
        {{"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": 0, "explanation": "...", "k_level": "K1"}},
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
- Include knowledge level (K1-K6) for each item
- Provide model answers
- Cover all subtopics comprehensively

Return JSON format:
{{
    "questions": [
        {{"question": "...", "answer": "...", "difficulty": "intermediate", "k_level": "K1"}},
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