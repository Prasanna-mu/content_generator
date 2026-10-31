from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


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


class WebSearchReport(BaseModel):
    user_prompt: str
    search_queries: List[str]
    results: List[WebSearchResult]
    total_results: int
    reputable_results: int
    search_timestamp: str


class Subtopic(BaseModel):
    title: str
    description: str
    estimated_chars: int


class Lesson(BaseModel):
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