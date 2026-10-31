from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from core.models.schemas import UserInput, Lesson, Subtopic, GeneratedContent, QuizQuestion, QuestionBankItem, SubtopicQualityConfig
from pathlib import Path
import json
import re


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
        validator_details: Optional[Callable[[Dict[str, Any]], str]] = None,
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
                    # Get detailed validation errors if validator_details provided
                    if validator_details:
                        errors = validator_details(result)
                        if errors:
                            print(f"  Validation failed (attempt {attempt + 1}/{max_retries}): {errors}")
                        else:
                            print(f"  Validation failed (attempt {attempt + 1}/{max_retries}), retrying...")
                    else:
                        print(f"  Validation failed (attempt {attempt + 1}/{max_retries}), retrying...")
            except Exception as e:
                print(f"  Generation error (attempt {attempt + 1}/{max_retries}): {e}")
        raise ValueError(f"Failed to generate valid JSON after {max_retries} attempts")
        return ""

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

    def validate_lessons_json_with_details(self, data: Dict[str, Any]) -> str:
        """Return detailed error message if validation fails, empty string if valid."""
        if not isinstance(data, dict):
            return "Root is not a JSON object"
        lessons = data.get("lessons", [])
        if not isinstance(lessons, list):
            return "Missing or invalid 'lessons' array"
        if len(lessons) == 0:
            return "Lessons array is empty"
        for i, lesson in enumerate(lessons):
            if not isinstance(lesson, dict):
                return f"Lesson {i} is not an object"
            if not lesson.get("title"):
                return f"Lesson {i} missing 'title'"
            if not lesson.get("description"):
                return f"Lesson {i} missing 'description'"
        return ""

    def validate_subtopics_json(self, data: Dict[str, Any], expected_count: int = 0, quality_config: Optional[SubtopicQualityConfig] = None) -> bool:
        if not isinstance(data, dict):
            return False
        subtopics = data.get("subtopics", [])
        if not isinstance(subtopics, list):
            return False
        if expected_count > 0 and len(subtopics) != expected_count:
            return False
        if quality_config is None:
            quality_config = SubtopicQualityConfig()
        for subtopic in subtopics:
            if not isinstance(subtopic, dict):
                return False
            if not subtopic.get("title") or not subtopic.get("description"):
                return False
            title = subtopic["title"]
            if len(title) > quality_config.max_title_length:
                return False
            if "estimated_chars" not in subtopic or not isinstance(subtopic["estimated_chars"], int):
                return False
            if subtopic["estimated_chars"] <= 0:
                return False
        return True

    def validate_subtopics_json_with_details(self, data: Dict[str, Any], expected_count: int = 0, quality_config: Optional[SubtopicQualityConfig] = None) -> str:
        """Return detailed error message if validation fails, empty string if valid."""
        if not isinstance(data, dict):
            return "Root is not a JSON object"
        subtopics = data.get("subtopics", [])
        if not isinstance(subtopics, list):
            return "Missing or invalid 'subtopics' array"
        if expected_count > 0 and len(subtopics) != expected_count:
            return f"Expected {expected_count} subtopics, got {len(subtopics)}"
        if quality_config is None:
            quality_config = SubtopicQualityConfig()
        for i, subtopic in enumerate(subtopics):
            if not isinstance(subtopic, dict):
                return f"Subtopic {i} is not an object"
            if not subtopic.get("title"):
                return f"Subtopic {i} missing 'title'"
            if not subtopic.get("description"):
                return f"Subtopic {i} missing 'description'"
            title = subtopic["title"]
            if len(title) > quality_config.max_title_length:
                return f"Subtopic {i} title too long ({len(title)} > {quality_config.max_title_length})"
            if "estimated_chars" not in subtopic:
                return f"Subtopic {i} missing 'estimated_chars'"
            if not isinstance(subtopic["estimated_chars"], int):
                return f"Subtopic {i} 'estimated_chars' must be integer"
            if subtopic["estimated_chars"] <= 0:
                return f"Subtopic {i} 'estimated_chars' must be positive"
        return ""

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

    def validate_quiz_json_with_details(self, data: Dict[str, Any], expected_count: int = 0) -> str:
        """Return detailed error message if validation fails, empty string if valid."""
        if not isinstance(data, dict):
            return "Root is not a JSON object"
        questions = data.get("questions", [])
        if not isinstance(questions, list):
            return "Missing or invalid 'questions' array"
        if expected_count > 0 and len(questions) != expected_count:
            return f"Expected {expected_count} questions, got {len(questions)}"
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return f"Question {i} is not an object"
            if not q.get("question"):
                return f"Question {i} missing 'question'"
            options = q.get("options")
            if not isinstance(options, list):
                return f"Question {i} 'options' must be array"
            if len(options) != 4:
                return f"Question {i} must have exactly 4 options, got {len(options)}"
            for j, opt in enumerate(options):
                if not isinstance(opt, str) or not opt.strip():
                    return f"Question {i} option {j} must be non-empty string"
            if "correct_answer" not in q:
                return f"Question {i} missing 'correct_answer'"
            if not isinstance(q["correct_answer"], int):
                return f"Question {i} 'correct_answer' must be integer"
            ca = q["correct_answer"]
            if ca < 0 or ca > 3:
                return f"Question {i} 'correct_answer' must be 0-3, got {ca}"
            k_level = q.get("k_level")
            if not k_level or not isinstance(k_level, str):
                return f"Question {i} missing or invalid 'k_level'"
            import re
            if not re.match(r'^K[1-6]$', k_level):
                return f"Question {i} 'k_level' must be K1-K6, got '{k_level}'"
            if "explanation" not in q:
                return f"Question {i} missing 'explanation'"
        return ""

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

    def validate_question_bank_json_with_details(self, data: Dict[str, Any], expected_count: int = 0) -> str:
        """Return detailed error message if validation fails, empty string if valid."""
        if not isinstance(data, dict):
            return "Root is not a JSON object"
        questions = data.get("questions", [])
        if not isinstance(questions, list):
            return "Missing or invalid 'questions' array"
        if expected_count > 0 and len(questions) != expected_count:
            return f"Expected {expected_count} questions, got {len(questions)}"
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return f"Question {i} is not an object"
            if not q.get("question"):
                return f"Question {i} missing 'question'"
            if not q.get("answer"):
                return f"Question {i} missing 'answer'"
            k_level = q.get("k_level")
            if not k_level or not isinstance(k_level, str):
                return f"Question {i} missing or invalid 'k_level'"
            import re
            if not re.match(r'^K[1-6]$', k_level):
                return f"Question {i} 'k_level' must be K1-K6, got '{k_level}'"
            if "difficulty" not in q:
                return f"Question {i} missing 'difficulty'"
            diff = q["difficulty"]
            if diff not in ("beginner", "intermediate", "technical"):
                return f"Question {i} 'difficulty' must be beginner/intermediate/technical, got '{diff}'"
        return ""

    def generate_lessons(self, user_input: UserInput) -> List[Dict[str, Any]]:
        prompt = self._build_lesson_prompt(user_input)
        system_prompt = self._get_lesson_system_prompt()
        result = self.generate_json_with_validation(
            prompt, system_prompt,
            lambda d: self.validate_lessons_json(d),
            max_retries=3,
            save_as="lessons.json",
            validator_details=lambda d: self.validate_lessons_json_with_details(d)
        )
        return result.get("lessons", [])

    def generate_subtopics(self, lesson: Lesson, user_input: UserInput) -> List[Subtopic]:
        prompt = self._build_subtopic_prompt(lesson, user_input)
        system_prompt = self._get_subtopic_system_prompt()
        expected = user_input.subtopics_per_lesson
        quality_config = user_input.subtopic_quality
        result = self.generate_json_with_validation(
            prompt, system_prompt,
            lambda d: self.validate_subtopics_json(d, expected, quality_config),
            max_retries=3,
            save_as=f"subtopics_{lesson.title.replace(' ', '_')}.json",
            validator_details=lambda d: self.validate_subtopics_json_with_details(d, expected, quality_config)
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
            save_as=f"quiz_{lesson.title.replace(' ', '_')}.json",
            validator_details=lambda d: self.validate_quiz_json_with_details(d, expected)
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
        config = user_input.subtopic_quality
        expected_avg = self._calculate_expected_avg_chars_for_prompt(user_input)
        
        weak_examples = "Introduction, Overview, Basics, Fundamentals, Summary, Conclusion, Getting Started, What Is, Chapter 1, Section 1, Module 1, Topic 1, Unit 1, Lesson 1"
        
        return f"""
Generate EXACTLY {user_input.subtopics_per_lesson} subtopics for lesson: "{lesson.title}"
Lesson description: {lesson.description}
Main topic: {user_input.prompt}

STRICT REQUIREMENTS:
- You MUST generate exactly {user_input.subtopics_per_lesson} subtopics - no more, no less
- Each subtopic must have a title, description, and estimated character count
- Subtopics should cover the lesson comprehensively with NO overlap
- Character estimates based on content length: {user_input.content_length.value} (target ~{expected_avg} chars each)

TITLE QUALITY RULES:
- Title must be SHORT and MEANINGFUL (max {config.max_title_length} characters)
- Title must be SPECIFIC, not generic
- FORBIDDEN generic titles: {weak_examples}
- Each title must clearly indicate the specific topic covered
- Good examples: "Variables and Data Types", "Control Flow Statements", "Function Parameters and Return Values"
- Bad examples: "Introduction", "Basics", "Overview", "Getting Started"

DESCRIPTION QUALITY RULES:
- Description must be specific and detailed, not vague
- Must explain WHAT will be covered and WHY it matters
- Each description must be distinct from others
- Target 50-500 characters

UNIQUENESS:
- No two subtopics may have similar titles or descriptions
- Each subtopic must cover a distinct, non-overlapping aspect of the lesson

Return JSON format:
{{
    "subtopics": [
        {{"title": "Specific Subtopic Title", "description": "Detailed specific description of what this covers and why...", "estimated_chars": {expected_avg}}},
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
{reference_section}Write HIGH-QUALITY educational content for subtopic: "{subtopic.title}"
Lesson: "{lesson_title}"
Main topic: {user_input.prompt}
Subtopic description: {subtopic.description}

REQUIREMENTS:
- Content length: {length_guide.get(user_input.content_length.value, "moderate")}
- Quality level: {quality_guide.get(user_input.content_quality.value, "balanced")}
- Target ~{subtopic.estimated_chars} characters (aim for {int(subtopic.estimated_chars * 0.7)}-{int(subtopic.estimated_chars * 1.3)} chars)
- Well-structured with clear headers, examples, and explanations
- Include practical examples, code snippets, or diagrams where appropriate
- Use clear, professional educational tone
- No markdown formatting in output, plain text only
- Cover the topic comprehensively based on the subtopic description

STRUCTURE GUIDELINES:
1. Start with a brief introduction to the subtopic
2. Cover key concepts with clear explanations
3. Include practical examples or code samples
4. Add summaries or key takeaways
5. Use numbered lists or bullet points for clarity
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
        return """You are an expert content planner. Break down lessons into detailed subtopics with accurate character estimates.
Generate SPECIFIC, MEANINGFUL subtopic titles - NO generic titles like Introduction, Overview, Basics, etc.
Each subtopic must cover a distinct, non-overlapping aspect of the lesson."""

    def _get_content_system_prompt(self, user_input: UserInput) -> str:
        return f"""You are an expert educational content writer. Write {user_input.content_quality.value} level content with {user_input.content_length.value} length.
Follow the structure guidelines precisely. Include practical examples, code snippets, and clear explanations.
Target the specified character count. No markdown formatting - plain text only."""

    def _get_quiz_system_prompt(self, user_input: UserInput) -> str:
        return f"You are an expert assessment designer. Create {user_input.quiz_difficulty.value} level quiz questions."

    def _get_question_bank_system_prompt(self, user_input: UserInput) -> str:
        return f"""You are an expert assessment designer. Create comprehensive question bank items for {user_input.content_quality.value} level.
Include a mix of question types (short answer, essay, problem-solving) with model answers.
Each item must have a difficulty level (beginner/intermediate/technical) and knowledge level (K1-K6).
Cover all subtopics comprehensively with clear, unambiguous questions and detailed answers."""

    def _calculate_expected_avg_chars_for_prompt(self, user_input: UserInput) -> int:
        """Calculate expected average characters per subtopic for prompt guidance."""
        length_base_chars = {
            "simple": 800,
            "medium": 1500,
            "long": 2500,
            "extreme": 4000
        }
        base = length_base_chars.get(user_input.content_length.value, 1500)
        quality_multiplier = {
            "beginner": 0.7,
            "intermediate": 1.0,
            "technical": 1.3
        }
        mult = quality_multiplier.get(user_input.content_quality.value, 1.0)
        return int(base * mult)