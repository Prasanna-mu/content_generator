from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json
import uuid
from difflib import SequenceMatcher

from core.models.schemas import UserInput, Lesson, Subtopic, SubtopicQualityConfig
from core.llm.base import BaseLLMProvider


class SubtopicQualityReview:
    """Result of LLM-based quality review for a subtopic."""
    def __init__(
        self,
        score: int,  # 0-10
        strengths: List[str],
        weaknesses: List[str],
        is_duplicate: bool = False,
        duplicate_of: Optional[str] = None,
        duplicate_reason: str = "",
        subtopic: Optional[Subtopic] = None
    ):
        self.score = score
        self.strengths = strengths
        self.weaknesses = weaknesses
        self.is_duplicate = is_duplicate
        self.duplicate_of = duplicate_of
        self.duplicate_reason = duplicate_reason
        self.subtopic = subtopic


# Backwards compatibility alias for existing tests
class SubtopicValidationResult:
    """Deprecated: Use SubtopicQualityReview instead."""
    def __init__(
        self,
        is_valid: bool,
        errors: List[str],
        warnings: List[str],
        subtopic: Subtopic
    ):
        self.is_valid = is_valid
        self.errors = errors
        self.warnings = warnings
        self.subtopic = subtopic
        self.score = 10 if is_valid else 0
        self.strengths = [] if not is_valid else ["Valid"]
        self.weaknesses = errors if not is_valid else []


class SubtopicGenerator:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    def generate_for_lesson(self, lesson: Lesson, user_input: UserInput) -> List[Subtopic]:
        """Generate subtopics for a single lesson without validation."""
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
        """Generate subtopics for all lessons, then run quality review."""
        # Phase 1: Generate complete set for all lessons
        for lesson in lessons:
            self.generate_for_lesson(lesson, user_input)
        
        # Phase 2: Quality review and selective regeneration
        self.quality_review_and_regenerate(lessons, user_input)
        
        # Save all subtopics after generation
        self._save_subtopics(lessons)
        return lessons

    def quality_review_and_regenerate(self, lessons: List[Lesson], user_input: UserInput) -> Dict[str, Any]:
        """Run LLM-based quality review on complete set, regenerate low-scoring subtopics."""
        config = user_input.subtopic_quality
        max_attempts = config.max_regeneration_attempts
        quality_threshold = config.quality_threshold
        
        results = {
            "reviewed": 0,
            "regenerated": 0,
            "failed": 0,
            "failed_subtopics": []
        }
        
        for lesson in lessons:
            lesson_results = self._review_and_regenerate_lesson(lesson, user_input, max_attempts, quality_threshold)
            results["reviewed"] += lesson_results["reviewed"]
            results["regenerated"] += lesson_results["regenerated"]
            results["failed"] += lesson_results["failed"]
            results["failed_subtopics"].extend(lesson_results["failed_subtopics"])
        
        # Remove failed subtopics from lessons
        for lesson in lessons:
            lesson.subtopics = [s for s in lesson.subtopics if s.validation_status != "failed"]
            lesson.estimated_total_chars = sum(s.estimated_chars for s in lesson.subtopics)
        
        return results

    def _review_and_regenerate_lesson(
        self, 
        lesson: Lesson, 
        user_input: UserInput, 
        max_attempts: int,
        quality_threshold: int = 6
    ) -> Dict[str, Any]:
        """Run quality review for a lesson's subtopics and regenerate low-scoring ones."""
        results = {
            "reviewed": 0,
            "regenerated": 0,
            "failed": 0,
            "failed_subtopics": []
        }
        
        # Reset validation state
        for subtopic in lesson.subtopics:
            subtopic.validation_status = "pending"
            subtopic.validation_errors = []
            subtopic.regeneration_attempt = 0
            subtopic.regeneration_reason = None
        
        accepted_subtopics: List[Subtopic] = []
        remaining_subtopics = list(lesson.subtopics)
        
        for attempt in range(max_attempts + 1):
            still_pending = [s for s in remaining_subtopics if s.validation_status not in ("valid", "failed")]
            
            if not still_pending:
                break
            
            # Review each pending subtopic against already-accepted ones
            for subtopic in still_pending:
                if subtopic.validation_status in ("valid", "failed"):
                    continue
                
                review = self._quality_review_subtopic(subtopic, lesson, user_input, accepted_subtopics)
                subtopic.validation_errors = review.weaknesses
                subtopic.quality_score = review.score
                
                if review.is_duplicate:
                    subtopic.validation_errors.append(f"Duplicate of '{review.duplicate_of}': {review.duplicate_reason}")
                
                if review.score >= quality_threshold and not review.is_duplicate:
                    subtopic.validation_status = "valid"
                    accepted_subtopics.append(subtopic)
                    results["reviewed"] += 1
                else:
                    # Will retry or fail
                    pass
            
            # Regenerate invalid subtopics
            invalid_subtopics = [
                s for s in remaining_subtopics 
                if s.validation_status not in ("valid", "failed")
            ]
            
            if not invalid_subtopics:
                break
            
            if attempt < max_attempts:
                for subtopic in invalid_subtopics:
                    if subtopic.validation_status == "failed":
                        continue
                    errors = subtopic.validation_errors
                    print(f"    Regenerating subtopic '{subtopic.title}' (attempt {attempt + 1}/{max_attempts}): {', '.join(errors)}")
                    regenerated = self._regenerate_subtopic(subtopic, lesson, user_input, errors, accepted_subtopics)
                    if regenerated:
                        # Review the regenerated subtopic
                        review = self._quality_review_subtopic(regenerated, lesson, user_input, accepted_subtopics)
                        regenerated.validation_errors = review.weaknesses
                        regenerated.quality_score = review.score
                        
                        if review.score >= quality_threshold and not review.is_duplicate:
                            # Accept the regenerated subtopic
                            subtopic.title = regenerated.title
                            subtopic.description = regenerated.description
                            subtopic.estimated_chars = regenerated.estimated_chars
                            subtopic.regeneration_attempt = attempt + 1
                            subtopic.regeneration_reason = "; ".join(errors)
                            subtopic.validation_status = "valid"
                            accepted_subtopics.append(subtopic)
                            results["regenerated"] += 1
                            results["reviewed"] += 1
                        else:
                            # Still invalid, will retry
                            subtopic.title = regenerated.title
                            subtopic.description = regenerated.description
                            subtopic.estimated_chars = regenerated.estimated_chars
                            subtopic.regeneration_attempt = attempt + 1
                            subtopic.regeneration_reason = "; ".join(errors)
                            subtopic.validation_status = "pending"
                    else:
                        subtopic.validation_status = "failed"
                        results["failed"] += 1
                        results["failed_subtopics"].append({
                            "lesson_title": lesson.title,
                            "subtopic_id": subtopic.id,
                            "subtopic_title": subtopic.title,
                            "errors": errors,
                            "attempts": attempt + 1
                        })
            else:
                # Max attempts reached
                for subtopic in invalid_subtopics:
                    if subtopic.validation_status != "failed":
                        subtopic.validation_status = "failed"
                        results["failed"] += 1
                        results["failed_subtopics"].append({
                            "lesson_title": lesson.title,
                            "subtopic_id": subtopic.id,
                            "subtopic_title": subtopic.title,
                            "errors": subtopic.validation_errors,
                            "attempts": max_attempts
                        })
        
        return results

    def _quality_review_subtopic(
        self, 
        subtopic: Subtopic, 
        lesson: Lesson, 
        user_input: UserInput,
        accepted_subtopics: List[Subtopic]
    ) -> SubtopicQualityReview:
        """Use LLM to review subtopic quality (0-10 score) and check for duplicates."""
        # First check for exact/semantic duplicates against accepted subtopics
        duplicate_checks = self._check_duplicates(subtopic, accepted_subtopics)
        if duplicate_checks:
            # Use the first duplicate found
            dup = duplicate_checks[0]
            return SubtopicQualityReview(
                score=0,
                strengths=[],
                weaknesses=[f"Duplicate detected: {dup['title']} - {dup['reason']}"],
                is_duplicate=True,
                duplicate_of=dup.get("title", ""),
                duplicate_reason=dup.get("reason", ""),
                subtopic=subtopic
            )
        
        # Build context of accepted subtopics for the LLM
        accepted_context = ""
        if accepted_subtopics:
            accepted_context = "ALREADY ACCEPTED SUBTOPICS (DO NOT DUPLICATE):\n"
            for i, s in enumerate(accepted_subtopics, 1):
                accepted_context += f"  {i}. {s.title}: {s.description}\n"
        
        quality_threshold = user_input.subtopic_quality.quality_threshold
        
        prompt = f"""
Review the quality of this subtopic for the lesson: "{lesson.title}"
Lesson description: {lesson.description}
Main topic: {user_input.prompt}
Content length: {user_input.content_length.value}
Content quality: {user_input.content_quality.value}

{accepted_context}

SUBTOPIC TO REVIEW:
Title: {subtopic.title}
Description: {subtopic.description}
Estimated chars: {subtopic.estimated_chars}

EVALUATION CRITERIA (score 0-10 for each, then overall 0-10):
1. Specificity: Is the title specific and meaningful (not generic like "Introduction", "Overview", "Basics")?
2. Relevance: Does it clearly relate to the lesson and main topic?
3. Description quality: Is the description detailed, specific, and informative?
4. Character estimate: Is the estimated_chars realistic for the content length?
5. Distinctness: Is it clearly different from already accepted subtopics?
6. Completeness: Does it cover a meaningful, non-trivial aspect of the lesson?

Return JSON format:
{{
    "overall_score": 0-10,
    "specificity_score": 0-10,
    "relevance_score": 0-10,
    "description_score": 0-10,
    "estimate_score": 0-10,
    "distinctness_score": 0-10,
    "strengths": ["strength1", "strength2"],
    "weaknesses": ["weakness1", "weakness2"]
}}
"""
        
        system_prompt = f"""You are an expert curriculum designer reviewing subtopic quality.
Be strict but fair. Generic titles (Introduction, Overview, Basics, Summary, Chapter X, etc.) should score low on specificity.
Descriptions must be specific and detailed, not vague.
Score {quality_threshold}+ = acceptable, <{quality_threshold} = needs regeneration."""
        
        try:
            result = self.llm.generate_json_with_validation(
                prompt, system_prompt,
                lambda d: self._validate_review_json(d),
                max_retries=2,
                save_as=None,
                temperature=0.3
            )
            
            return SubtopicQualityReview(
                score=result.get("overall_score", 0),
                strengths=result.get("strengths", []),
                weaknesses=result.get("weaknesses", []),
                subtopic=subtopic
            )
        except Exception as e:
            print(f"    Quality review failed for '{subtopic.title}': {e}")
            # Default to valid if review fails (fail-open for robustness)
            return SubtopicQualityReview(
                score=quality_threshold,
                strengths=["Review failed, assuming acceptable"],
                weaknesses=[f"Review error: {e}"],
                subtopic=subtopic
            )

    def _validate_review_json(self, data: Dict[str, Any]) -> bool:
        """Validate quality review JSON response."""
        if not isinstance(data, dict):
            return False
        required = ["overall_score", "strengths", "weaknesses"]
        for field in required:
            if field not in data:
                return False
        if not isinstance(data["overall_score"], int) or not (0 <= data["overall_score"] <= 10):
            return False
        if not isinstance(data["strengths"], list) or not isinstance(data["weaknesses"], list):
            return False
        return True

    def _check_duplicates(self, subtopic: Subtopic, accepted_subtopics: List[Subtopic], config: Optional[SubtopicQualityConfig] = None) -> List[Dict]:
        """Check for exact/semantic duplicates against accepted subtopics. Returns list of duplicate info dicts."""
        if config is None:
            config = getattr(subtopic, '_quality_config', None)
        threshold = getattr(config, 'similarity_threshold', 0.85) if config else 0.85
        
        title = subtopic.title.strip().lower()
        desc = subtopic.description.strip().lower()
        duplicates = []
        
        for other in accepted_subtopics:
            other_title = other.title.strip().lower()
            other_desc = other.description.strip().lower()
            
            if title == other_title:
                duplicates.append({"title": other.title, "reason": "Exact title match"})
                continue
            
            title_similarity = SequenceMatcher(None, title, other_title).ratio()
            if title_similarity >= threshold:
                duplicates.append({"title": other.title, "reason": f"Near-duplicate title ({title_similarity:.0%} similar)"})
            
            if desc and other_desc:
                desc_similarity = SequenceMatcher(None, desc, other_desc).ratio()
                if desc_similarity >= threshold:
                    duplicates.append({"title": other.title, "reason": f"Near-duplicate description ({desc_similarity:.0%} similar)"})
        
        return duplicates

    def _regenerate_subtopic(
        self,
        subtopic: Subtopic,
        lesson: Lesson,
        user_input: UserInput,
        errors: List[str],
        accepted_subtopics: List[Subtopic]
    ) -> Optional[Subtopic]:
        """Regenerate a single subtopic with error feedback."""
        try:
            prompt = self._build_regeneration_prompt(subtopic, lesson, user_input, errors, accepted_subtopics)
            system_prompt = self.llm._get_subtopic_system_prompt()
            
            config = user_input.subtopic_quality
            
            if hasattr(self.llm, '_in_regeneration'):
                self.llm._in_regeneration = True
            
            try:
                result = self.llm.generate_json_with_validation(
                    prompt, system_prompt,
                    lambda d: self._validate_single_subtopic_json(d, config),
                    max_retries=2,
                    save_as=None
                )
            finally:
                if hasattr(self.llm, '_in_regeneration'):
                    self.llm._in_regeneration = False
            
            subtopics_data = result.get("subtopics", [])
            if not subtopics_data:
                return None
            
            data = subtopics_data[0]
            return Subtopic(
                id=subtopic.id,
                title=data["title"],
                description=data["description"],
                estimated_chars=data["estimated_chars"],
                validation_status="pending",
                validation_errors=[],
                regeneration_attempt=subtopic.regeneration_attempt + 1,
                regeneration_reason="; ".join(errors)
            )
        except Exception as e:
            print(f"    Regeneration failed: {e}")
            return None

    def _validate_single_subtopic_json(self, data: Dict[str, Any], config: SubtopicQualityConfig) -> bool:
        """Validate a single subtopic JSON response."""
        if not isinstance(data, dict):
            return False
        subtopics = data.get("subtopics", [])
        if not isinstance(subtopics, list) or len(subtopics) != 1:
            return False
        s = subtopics[0]
        if not isinstance(s, dict):
            return False
        if not s.get("title") or not s.get("description"):
            return False
        if "estimated_chars" not in s or not isinstance(s["estimated_chars"], int):
            return False
        if s["estimated_chars"] <= 0:
            return False
        if len(s["title"]) > config.max_title_length:
            return False
        return True

    def _build_regeneration_prompt(
        self,
        subtopic: Subtopic,
        lesson: Lesson,
        user_input: UserInput,
        errors: List[str],
        accepted_subtopics: List[Subtopic]
    ) -> str:
        """Build a prompt for regenerating a specific subtopic with error feedback."""
        error_feedback = "\n".join(f"- {e}" for e in errors)
        config = user_input.subtopic_quality
        
        existing_titles = [s.title for s in accepted_subtopics]
        existing_desc = [s.description for s in accepted_subtopics]
        
        return f"""
Regenerate ONE subtopic for lesson: "{lesson.title}"
Lesson description: {lesson.description}
Main topic: {user_input.prompt}

PREVIOUS ATTEMPT FAILED WITH THESE ERRORS:
{error_feedback}

ALREADY ACCEPTED SUBTOPICS (DO NOT DUPLICATE):
{json.dumps(list(zip(existing_titles, existing_desc)), indent=2)}

STRICT REQUIREMENTS:
- Generate EXACTLY 1 subtopic
- Title must be short and meaningful (max {config.max_title_length} chars)
- Title must NOT be generic (no "Introduction", "Overview", "Basics", "Summary", "Conclusion", "Chapter X", "Section X", "Module X", "Topic X", "Unit X", "Lesson X", "Getting Started", "What Is")
- Description must be specific and detailed, explaining WHAT will be covered and WHY it matters
- Estimated chars must be realistic for content length: {user_input.content_length.value} (target ~{self._calculate_expected_avg_chars(lesson, user_input)} chars)
- Subtopic must be distinct from all existing subtopics in title AND description
- Cover a specific, non-overlapping aspect of the lesson

Return JSON format:
{{
    "subtopics": [
        {{"title": "Specific Subtopic Title", "description": "Detailed specific description...", "estimated_chars": {self._calculate_expected_avg_chars(lesson, user_input)}}}
    ]
}}
"""

    def _calculate_expected_avg_chars(self, lesson: Lesson, user_input: UserInput) -> int:
        """Calculate expected average characters per subtopic based on content length AND quality."""
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

    def adjust_estimates(self, lessons: List[Lesson], user_input: UserInput) -> List[Lesson]:
        """Adjust estimates for content length."""
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
                        "lesson_id": lesson.id,
                        "subtopics": [
                            {
                                "id": s.id,
                                "title": s.title,
                                "description": s.description,
                                "estimated_chars": s.estimated_chars,
                                "validation_status": s.validation_status,
                                "validation_errors": s.validation_errors,
                                "regeneration_attempt": s.regeneration_attempt,
                                "regeneration_reason": s.regeneration_reason,
                                "quality_score": getattr(s, 'quality_score', None)
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
        all_valid = True
        for lesson in lessons:
            if len(lesson.subtopics) != expected_per_lesson:
                print(f"  Validation failed: Lesson '{lesson.title}' has {len(lesson.subtopics)} subtopics, expected {expected_per_lesson}")
                all_valid = False
            for subtopic in lesson.subtopics:
                if not subtopic.title or not subtopic.description:
                    print(f"  Validation failed: Subtopic missing title or description in lesson '{lesson.title}'")
                    all_valid = False
                if subtopic.estimated_chars <= 0:
                    print(f"  Validation failed: Subtopic '{subtopic.title}' has invalid estimated_chars: {subtopic.estimated_chars}")
                    all_valid = False
                if subtopic.validation_status == "failed":
                    print(f"  Validation failed: Subtopic '{subtopic.title}' in lesson '{lesson.title}' has failed validation: {subtopic.validation_errors}")
                    all_valid = False
        return all_valid

    def load_saved_subtopics(self, lessons: List[Lesson], user_input: UserInput) -> List[Lesson]:
        """Load previously saved subtopics from intermediate output and apply to lessons."""
        if self.llm._output_dir:
            filepath = self.llm._output_dir / "subtopics_all.json"
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                subtopic_map = {}
                for item in data.get("subtopics", []):
                    lesson_key = item.get("lesson_id") or item.get("lesson_title")
                    subtopic_map[lesson_key] = item["subtopics"]
                
                for lesson in lessons:
                    lesson_key = lesson.id if lesson.id in subtopic_map else lesson.title
                    if lesson_key in subtopic_map:
                        saved_subtopics = subtopic_map[lesson_key]
                        lesson.subtopics = []
                        for s_data in saved_subtopics:
                            subtopic = Subtopic(
                                id=s_data.get("id", str(uuid.uuid4())),
                                title=s_data["title"],
                                description=s_data["description"],
                                estimated_chars=s_data["estimated_chars"],
                                validation_status=s_data.get("validation_status", "pending"),
                                validation_errors=s_data.get("validation_errors", []),
                                regeneration_attempt=s_data.get("regeneration_attempt", 0),
                                regeneration_reason=s_data.get("regeneration_reason")
                            )
                            lesson.subtopics.append(subtopic)
                        lesson.estimated_total_chars = sum(s.estimated_chars for s in lesson.subtopics)
                
                print(f"  Loaded subtopics for {len(subtopic_map)} lessons from saved output")
                return lessons
        return lessons

# Backwards compatibility methods for tests
    def _validate_subtopic(
        self,
        subtopic: Subtopic,
        lesson: Lesson,
        user_input: UserInput,
        accepted_subtopics: Optional[List[Subtopic]] = None
    ) -> SubtopicValidationResult:
        """Backwards compatibility: Use basic validation without LLM for test compatibility."""
        return self._validate_subtopic_basic_with_errors(subtopic, lesson, user_input, accepted_subtopics or [])

    def _validate_subtopic_basic_with_errors(
        self,
        subtopic: Subtopic,
        lesson: Lesson,
        user_input: UserInput,
        accepted_subtopics: Optional[List[Subtopic]] = None
    ) -> SubtopicValidationResult:
        """Basic validation without LLM review (for test compatibility)."""
        config = user_input.subtopic_quality
        errors = []
        warnings = []

        title = subtopic.title.strip()
        description = subtopic.description.strip()

        if not title:
            errors.append("Title is empty")
        else:
            if len(title) > config.max_title_length:
                errors.append(f"Title exceeds maximum length ({len(title)} > {config.max_title_length})")

        if not description:
            errors.append("Description is empty")

        if subtopic.estimated_chars <= 0:
            errors.append("Estimated characters must be positive")

        # Check duplicates ONLY against already-accepted subtopics (sequential)
        duplicate_errors = self._check_duplicates(subtopic, accepted_subtopics or [])
        for dup in duplicate_errors:
            if "Exact" in dup['reason']:
                errors.append(f"Exact duplicate title: '{dup['title']}'")
            elif "Near-duplicate title" in dup['reason']:
                match = re.search(r'(\d+)%', dup['reason'])
                pct = match.group(1) if match else '0'
                errors.append(f"Near-duplicate title ({pct}% similar to '{dup['title']}')")
            elif "Near-duplicate description" in dup['reason']:
                match = re.search(r'(\d+)%', dup['reason'])
                pct = match.group(1) if match else '0'
                errors.append(f"Near-duplicate description ({pct}% similar to another subtopic)")

        return SubtopicValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            subtopic=subtopic
        )

    def _validate_and_regenerate_lesson(
        self,
        lesson: Lesson,
        user_input: UserInput,
        max_attempts: int
    ) -> Dict[str, Any]:
        """Backwards compatibility: Use _review_and_regenerate_lesson."""
        config = user_input.subtopic_quality
        return self._review_and_regenerate_lesson(lesson, user_input, max_attempts, config.quality_threshold)