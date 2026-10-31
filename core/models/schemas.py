from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid


class ContentQuality(str, Enum):
    TECHNICAL = "technical"
    INTERMEDIATE = "intermediate"
    BEGINNER = "beginner"


class ContentLength(str, Enum):
    EXTREME = "extreme"
    LONG = "long"
    MEDIUM = "medium"
    SIMPLE = "simple"


class QuizDifficulty(str, Enum):
    TECHNICAL = "technical"
    INTERMEDIATE = "intermediate"
    BEGINNER = "beginner"


class SubtopicQualityConfig(BaseModel):
    """Configuration for subtopic quality validation and regeneration."""
    max_title_length: int = Field(default=60, ge=10, le=200, description="Maximum subtopic title length in characters")
    max_regeneration_attempts: int = Field(default=3, ge=1, le=10, description="Maximum regeneration attempts for invalid subtopics")
    # LLM-based quality threshold (0-10), regenerate if below this score
    quality_threshold: int = Field(default=6, ge=1, le=10, description="Minimum quality score (0-10) for subtopic to pass validation")


class UserInput(BaseModel):
    prompt: str = Field(..., description="Main topic/prompt for content generation")
    num_lessons: int = Field(..., ge=1, le=50, description="Number of lessons to generate")
    subtopics_per_lesson: int = Field(..., ge=1, le=20, description="Subtopics per lesson")
    content_quality: ContentQuality = Field(default=ContentQuality.INTERMEDIATE)
    content_length: ContentLength = Field(default=ContentLength.MEDIUM)
    quiz_question_count: int = Field(default=5, ge=1, le=50, description="Quiz questions per lesson")
    quiz_difficulty: QuizDifficulty = Field(default=QuizDifficulty.INTERMEDIATE)
    question_bank_count: int = Field(default=10, ge=1, le=100, description="Question bank questions per lesson")
    web_search_needed: bool = Field(default=False, description="Whether to perform web search for content enrichment")
    subtopic_quality: SubtopicQualityConfig = Field(default_factory=SubtopicQualityConfig, description="Subtopic quality validation config")


class WebSearchResult(BaseModel):
    query: str
    url: str
    title: str
    snippet: str
    is_reputable: bool = False
    reputation_score: float = 0.0
    normalized_content: str = ""
    extracted_at: str = ""
    analysis: str = ""
    facts_verified: bool = False
    # New fields for V4
    is_valid_for_crawling: bool = True
    security_notes: str = ""
    source_quality_score: float = 0.0
    source_quality_notes: str = ""
    fact_check_score: float = 0.0
    fact_check_notes: str = ""
    relevance_score: float = 0.0
    accuracy_score: float = 0.0
    credibility_score: float = 0.0


class WebSearchReport(BaseModel):
    user_prompt: str
    search_queries: List[str]
    results: List[WebSearchResult]
    total_results: int
    valid_sources: int
    quality_sources: int
    search_timestamp: str


class Subtopic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable unique identifier for the subtopic")
    title: str
    description: str
    estimated_chars: int
    validation_status: str = Field(default="pending", description="Validation status: pending, valid, invalid, failed")
    validation_errors: List[str] = Field(default_factory=list, description="List of validation error messages")
    regeneration_attempt: int = Field(default=0, description="Number of regeneration attempts made")
    regeneration_reason: Optional[str] = Field(default=None, description="Reason for last regeneration")
    quality_score: Optional[int] = Field(default=None, description="Quality score from LLM review (0-10)")


class Lesson(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable unique identifier for the lesson")
    title: str
    description: str
    subtopics: List[Subtopic]
    estimated_total_chars: int


class GeneratedContent(BaseModel):
    lesson_title: str
    subtopic_title: str
    content: str
    actual_chars: int


class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_answer: int
    explanation: str
    k_level: str = Field(..., pattern="^K[1-6]$")


class QuestionBankItem(BaseModel):
    question: str
    answer: str
    difficulty: str
    k_level: str = Field(..., pattern="^K[1-6]$")


class LessonOutput(BaseModel):
    lesson: Lesson
    generated_contents: List[GeneratedContent]
    quiz_questions: List[QuizQuestion]
    question_bank: List[QuestionBankItem]


class PipelineConfig(BaseModel):
    user_input: UserInput
    lessons: List[Lesson]
    model_name: str = "qwen2.5:3b"
    ollama_base_url: str = "http://localhost:11434"