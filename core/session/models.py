from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import json


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    RESUMED = "resumed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStage(str, Enum):
    PROMPT_ANALYSIS = "prompt_analysis"
    WEB_SEARCH = "web_search"
    LESSON_GENERATION = "lesson_generation"
    LESSON_REFINEMENT = "lesson_refinement"
    SUBTOPIC_GENERATION = "subtopic_generation"
    SUBTOPIC_ADJUSTMENT = "subtopic_adjustment"
    SUBTOPIC_VALIDATION = "subtopic_validation"
    CONTENT_GENERATION = "content_generation"
    OUTPUT_WRITING = "output_writing"


@dataclass
class Session:
    session_id: str
    prompt: str
    user_input_json: str
    status: SessionStatus = SessionStatus.CREATED
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    current_stage: Optional[PipelineStage] = None
    total_lessons: int = 0
    completed_lessons: int = 0
    error_message: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, prompt: str, user_input_json: str, config: Dict[str, Any]) -> "Session":
        return cls(
            session_id=str(uuid.uuid4()),
            prompt=prompt,
            user_input_json=user_input_json,
            config=config,
            status=SessionStatus.CREATED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "prompt": self.prompt,
            "user_input_json": self.user_input_json,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "current_stage": self.current_stage.value if self.current_stage else None,
            "total_lessons": self.total_lessons,
            "completed_lessons": self.completed_lessons,
            "error_message": self.error_message,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        session = cls(
            session_id=data["session_id"],
            prompt=data["prompt"],
            user_input_json=data["user_input_json"],
            status=SessionStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            current_stage=PipelineStage(data["current_stage"]) if data.get("current_stage") else None,
            total_lessons=data.get("total_lessons", 0),
            completed_lessons=data.get("completed_lessons", 0),
            error_message=data.get("error_message"),
            config=data.get("config", {}),
        )
        return session


@dataclass
class StageCheckpoint:
    session_id: str
    stage: PipelineStage
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stage": self.stage.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StageCheckpoint":
        return cls(
            session_id=data["session_id"],
            stage=PipelineStage(data["stage"]),
            status=StageStatus(data["status"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            input_data=data.get("input_data", {}),
            output_data=data.get("output_data", {}),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
        )


@dataclass
class TaskCheckpoint:
    session_id: str
    stage: PipelineStage
    task_id: str
    task_type: str
    task_key: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stage": self.stage.value,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_key": self.task_key,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCheckpoint":
        return cls(
            session_id=data["session_id"],
            stage=PipelineStage(data["stage"]),
            task_id=data["task_id"],
            task_type=data["task_type"],
            task_key=data["task_key"],
            status=TaskStatus(data["status"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            input_data=data.get("input_data", {}),
            output_data=data.get("output_data", {}),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
        )