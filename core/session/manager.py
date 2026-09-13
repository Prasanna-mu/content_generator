import sqlite3
import json
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager

from core.session.models import (
    Session, SessionStatus, StageStatus, TaskStatus,
    PipelineStage, StageCheckpoint, TaskCheckpoint
)


class SessionManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _transaction(self):
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self):
        with self._transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    user_input_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    current_stage TEXT,
                    total_lessons INTEGER DEFAULT 0,
                    completed_lessons INTEGER DEFAULT 0,
                    error_message TEXT,
                    config TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stage_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    input_data TEXT NOT NULL,
                    output_data TEXT NOT NULL,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
                    UNIQUE(session_id, stage)
                );

                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    task_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    input_data TEXT NOT NULL,
                    output_data TEXT NOT NULL,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
                    UNIQUE(session_id, stage, task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_stage_session ON stage_checkpoints(session_id);
                CREATE INDEX IF NOT EXISTS idx_task_session_stage ON task_checkpoints(session_id, stage);
            """)

    def create_session(self, prompt: str, user_input_json: str, config: Dict[str, Any]) -> Session:
        session = Session.create(prompt, user_input_json, config)
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO sessions (session_id, prompt, user_input_json, status, created_at, updated_at, config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session.session_id, session.prompt, session.user_input_json,
                session.status.value, session.created_at.isoformat(),
                session.updated_at.isoformat(), json.dumps(session.config)
            ))
            self._create_stage_checkpoints(conn, session.session_id)
        return session

    def _create_stage_checkpoints(self, conn: sqlite3.Connection, session_id: str):
        stages = [
            PipelineStage.PROMPT_ANALYSIS,
            PipelineStage.WEB_SEARCH,
            PipelineStage.LESSON_GENERATION,
            PipelineStage.LESSON_REFINEMENT,
            PipelineStage.SUBTOPIC_GENERATION,
            PipelineStage.SUBTOPIC_ADJUSTMENT,
            PipelineStage.SUBTOPIC_VALIDATION,
            PipelineStage.CONTENT_GENERATION,
            PipelineStage.OUTPUT_WRITING,
        ]
        for stage in stages:
            conn.execute("""
                INSERT INTO stage_checkpoints (session_id, stage, status, input_data, output_data)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, stage.value, StageStatus.PENDING.value, '{}', '{}'))

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row:
                return Session.from_dict(dict(row))
        return None

    def list_sessions(self, limit: int = 50) -> List[Session]:
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [Session.from_dict(dict(row)) for row in rows]

    def update_session_status(self, session_id: str, status: SessionStatus, 
                              current_stage: Optional[PipelineStage] = None,
                              error_message: Optional[str] = None,
                              completed_lessons: Optional[int] = None):
        with self._transaction() as conn:
            updates = ["status = ?", "updated_at = ?"]
            params = [status.value, datetime.utcnow().isoformat()]
            if current_stage:
                updates.append("current_stage = ?")
                params.append(current_stage.value)
            if error_message:
                updates.append("error_message = ?")
                params.append(error_message)
            if completed_lessons is not None:
                updates.append("completed_lessons = ?")
                params.append(completed_lessons)
            if status == SessionStatus.COMPLETED:
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())
            params.append(session_id)
            conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?", params)

    def start_stage(self, session_id: str, stage: PipelineStage, input_data: Dict[str, Any]):
        with self._transaction() as conn:
            conn.execute("""
                UPDATE stage_checkpoints 
                SET status = ?, started_at = ?, input_data = ?
                WHERE session_id = ? AND stage = ?
            """, (StageStatus.RUNNING.value, datetime.utcnow().isoformat(), 
                  json.dumps(input_data), session_id, stage.value))
            self.update_session_status(session_id, SessionStatus.RUNNING, current_stage=stage)

    def complete_stage(self, session_id: str, stage: PipelineStage, output_data: Dict[str, Any]):
        with self._transaction() as conn:
            conn.execute("""
                UPDATE stage_checkpoints 
                SET status = ?, completed_at = ?, output_data = ?
                WHERE session_id = ? AND stage = ?
            """, (StageStatus.COMPLETED.value, datetime.utcnow().isoformat(),
                  json.dumps(output_data), session_id, stage.value))

    def fail_stage(self, session_id: str, stage: PipelineStage, error_message: str):
        with self._transaction() as conn:
            conn.execute("""
                UPDATE stage_checkpoints 
                SET status = ?, error_message = ?, retry_count = retry_count + 1
                WHERE session_id = ? AND stage = ?
            """, (StageStatus.FAILED.value, error_message, session_id, stage.value))
            self.update_session_status(session_id, SessionStatus.FAILED, error_message=error_message)

    def get_stage_checkpoint(self, session_id: str, stage: PipelineStage) -> Optional[StageCheckpoint]:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM stage_checkpoints WHERE session_id = ? AND stage = ?",
                (session_id, stage.value)
            ).fetchone()
            if row:
                return StageCheckpoint.from_dict(dict(row))
        return None

    def get_stage_status(self, session_id: str, stage: PipelineStage) -> StageStatus:
        cp = self.get_stage_checkpoint(session_id, stage)
        return cp.status if cp else StageStatus.PENDING

    def start_task(self, session_id: str, stage: PipelineStage, task_id: str, 
                   task_type: str, task_key: str, input_data: Dict[str, Any]):
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO task_checkpoints 
                (session_id, stage, task_id, task_type, task_key, status, started_at, input_data, output_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session_id, stage.value, task_id, task_type, task_key,
                  TaskStatus.RUNNING.value, datetime.utcnow().isoformat(),
                  json.dumps(input_data), '{}'))

    def complete_task(self, session_id: str, stage: PipelineStage, task_id: str, output_data: Dict[str, Any]):
        with self._transaction() as conn:
            conn.execute("""
                UPDATE task_checkpoints 
                SET status = ?, completed_at = ?, output_data = ?
                WHERE session_id = ? AND stage = ? AND task_id = ?
            """, (TaskStatus.COMPLETED.value, datetime.utcnow().isoformat(),
                  json.dumps(output_data), session_id, stage.value, task_id))

    def fail_task(self, session_id: str, stage: PipelineStage, task_id: str, error_message: str):
        with self._transaction() as conn:
            conn.execute("""
                UPDATE task_checkpoints 
                SET status = ?, error_message = ?, retry_count = retry_count + 1
                WHERE session_id = ? AND stage = ? AND task_id = ?
            """, (TaskStatus.FAILED.value, error_message, session_id, stage.value, task_id))

    def get_task_checkpoint(self, session_id: str, stage: PipelineStage, task_id: str) -> Optional[TaskCheckpoint]:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM task_checkpoints WHERE session_id = ? AND stage = ? AND task_id = ?",
                (session_id, stage.value, task_id)
            ).fetchone()
            if row:
                return TaskCheckpoint.from_dict(dict(row))
        return None

    def get_pending_tasks(self, session_id: str, stage: PipelineStage) -> List[TaskCheckpoint]:
        with self._transaction() as conn:
            rows = conn.execute("""
                SELECT * FROM task_checkpoints 
                WHERE session_id = ? AND stage = ? AND status IN (?, ?)
                ORDER BY id
            """, (session_id, stage.value, TaskStatus.PENDING.value, TaskStatus.RUNNING.value)).fetchall()
            return [TaskCheckpoint.from_dict(dict(row)) for row in rows]

    def get_completed_tasks(self, session_id: str, stage: PipelineStage) -> List[TaskCheckpoint]:
        with self._transaction() as conn:
            rows = conn.execute("""
                SELECT * FROM task_checkpoints 
                WHERE session_id = ? AND stage = ? AND status = ?
                ORDER BY id
            """, (session_id, stage.value, TaskStatus.COMPLETED.value)).fetchall()
            return [TaskCheckpoint.from_dict(dict(row)) for row in rows]

    def recover_interrupted_tasks(self, session_id: str) -> int:
        """Mark RUNNING tasks as PENDING for recovery on resume."""
        with self._transaction() as conn:
            cursor = conn.execute("""
                UPDATE task_checkpoints 
                SET status = ? 
                WHERE session_id = ? AND status = ?
            """, (TaskStatus.PENDING.value, session_id, TaskStatus.RUNNING.value))
            return cursor.rowcount

    def recover_interrupted_stages(self, session_id: str) -> int:
        """Mark RUNNING stages as PENDING for recovery on resume."""
        with self._transaction() as conn:
            cursor = conn.execute("""
                UPDATE stage_checkpoints 
                SET status = ? 
                WHERE session_id = ? AND status = ?
            """, (StageStatus.PENDING.value, session_id, StageStatus.RUNNING.value))
            return cursor.rowcount

    def get_resume_point(self, session_id: str) -> Optional[PipelineStage]:
        """Find the first incomplete stage to resume from."""
        with self._transaction() as conn:
            rows = conn.execute("""
                SELECT stage, status FROM stage_checkpoints 
                WHERE session_id = ? 
                ORDER BY id
            """, (session_id,)).fetchall()
            for row in rows:
                if row["status"] in (StageStatus.PENDING.value, StageStatus.RUNNING.value, StageStatus.FAILED.value):
                    return PipelineStage(row["stage"])
        return None

    def get_all_stage_statuses(self, session_id: str) -> Dict[PipelineStage, StageStatus]:
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT stage, status FROM stage_checkpoints WHERE session_id = ? ORDER BY id",
                (session_id,)
            ).fetchall()
            return {PipelineStage(row["stage"]): StageStatus(row["status"]) for row in rows}

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None