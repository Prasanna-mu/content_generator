import os
import sys
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline.orchestrator import PipelineOrchestrator
from core.models.schemas import UserInput
from core.session.models import SessionStatus, PipelineStage, StageStatus
from core.session.manager import SessionManager

# In-memory store for active generations (in production, use Redis)
active_generations: Dict[str, Dict[str, Any]] = {}


class GenerationRequest(BaseModel):
    prompt: str = Field(..., description="Main topic/prompt for content generation")
    num_lessons: int = Field(default=5, ge=1, le=50)
    subtopics_per_lesson: int = Field(default=4, ge=1, le=20)
    content_quality: str = Field(default="intermediate")
    content_length: str = Field(default="medium")
    quiz_question_count: int = Field(default=5, ge=1, le=50)
    quiz_difficulty: str = Field(default="intermediate")
    question_bank_count: int = Field(default=10, ge=1, le=100)
    web_search_needed: bool = Field(default=False)
    model_name: str = Field(default="qwen2.5:3b")
    provider: str = Field(default="ollama")
    base_url: str = Field(default="http://localhost:11434")
    output_dir: str = Field(default="output")
    worker_count: int = Field(default=4)
    processing_dir: str = Field(default="processing")
    session_id: Optional[str] = None
    resume: bool = Field(default=False)


class GenerationResponse(BaseModel):
    generation_id: str
    session_id: str
    status: str
    message: str


class GenerationStatus(BaseModel):
    generation_id: str
    session_id: str
    status: str
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    stage_progress: Optional[Dict[str, Any]] = None
    total_lessons: int = 0
    completed_lessons: int = 0
    error_message: Optional[str] = None
    stages: Dict[str, str] = {}


def get_orchestrator(request: GenerationRequest) -> PipelineOrchestrator:
    return PipelineOrchestrator(
        model_name=request.model_name,
        provider=request.provider,
        base_url=request.base_url,
        output_dir=Path(request.output_dir),
        worker_count=request.worker_count,
        processing_dir=Path(request.processing_dir),
        session_id=request.session_id,
        resume=request.resume
    )


def user_input_from_request(request: GenerationRequest) -> UserInput:
    return UserInput(
        prompt=request.prompt,
        num_lessons=request.num_lessons,
        subtopics_per_lesson=request.subtopics_per_lesson,
        content_quality=request.content_quality,
        content_length=request.content_length,
        quiz_question_count=request.quiz_question_count,
        quiz_difficulty=request.quiz_difficulty,
        question_bank_count=request.question_bank_count,
        web_search_needed=request.web_search_needed
    )


async def run_pipeline_async(generation_id: str, request: GenerationRequest):
    """Run the pipeline asynchronously and update status."""
    orchestrator = None
    try:
        orchestrator = get_orchestrator(request)
        orchestrator.initialize()
        
        user_input = user_input_from_request(request)
        
        # Create session
        session = orchestrator._load_or_create_session(user_input)
        session_id = session.session_id
        
        active_generations[generation_id].update({
            "session_id": session_id,
            "status": "running",
            "current_stage": None,
            "stage_status": None,
            "stage_progress": {},
            "total_lessons": 0,
            "completed_lessons": 0,
            "stages": {}
        })
        
        # Get all stages
        all_stages = [
            (PipelineStage.PROMPT_ANALYSIS, "Prompt Analysis"),
            (PipelineStage.WEB_SEARCH, "Web Search"),
            (PipelineStage.LESSON_GENERATION, "Lesson Generation"),
            (PipelineStage.LESSON_REFINEMENT, "Lesson Refinement"),
            (PipelineStage.SUBTOPIC_GENERATION, "Subtopic Generation"),
            (PipelineStage.SUBTOPIC_ADJUSTMENT, "Subtopic Adjustment"),
            (PipelineStage.SUBTOPIC_VALIDATION, "Subtopic Validation"),
            (PipelineStage.CONTENT_GENERATION, "Content Generation"),
            (PipelineStage.OUTPUT_WRITING, "Output Writing"),
        ]
        
        stages = [(s, f) for s, f in all_stages if user_input.web_search_needed or s != PipelineStage.WEB_SEARCH]
        
        # Initialize stages in status
        for stage, stage_name in stages:
            active_generations[generation_id]["stages"][stage.value] = "pending"
        
        # Run each stage
        for stage, stage_name in stages:
            active_generations[generation_id]["current_stage"] = stage.value
            active_generations[generation_id]["stage_status"] = "running"
            active_generations[generation_id]["stages"][stage.value] = "running"
            
            # Start stage in session manager
            orchestrator.session_manager.start_stage(session_id, stage, {})
            
            try:
                # Run the stage
                if stage == PipelineStage.PROMPT_ANALYSIS:
                    output_data = orchestrator._run_prompt_analysis()
                elif stage == PipelineStage.WEB_SEARCH:
                    output_data = orchestrator._run_web_search()
                elif stage == PipelineStage.LESSON_GENERATION:
                    output_data = orchestrator._run_lesson_generation()
                    active_generations[generation_id]["total_lessons"] = len(orchestrator.lessons)
                elif stage == PipelineStage.LESSON_REFINEMENT:
                    output_data = orchestrator._run_lesson_refinement()
                elif stage == PipelineStage.SUBTOPIC_GENERATION:
                    output_data = orchestrator._run_subtopic_generation()
                elif stage == PipelineStage.SUBTOPIC_ADJUSTMENT:
                    output_data = orchestrator._run_subtopic_adjustment()
                elif stage == PipelineStage.SUBTOPIC_VALIDATION:
                    output_data = orchestrator._run_subtopic_validation()
                elif stage == PipelineStage.CONTENT_GENERATION:
                    output_data = orchestrator._run_content_generation()
                elif stage == PipelineStage.OUTPUT_WRITING:
                    output_data = orchestrator._run_output_writing()
                else:
                    continue
                
                orchestrator.session_manager.complete_stage(session_id, stage, output_data)
                active_generations[generation_id]["stages"][stage.value] = "completed"
                active_generations[generation_id]["stage_status"] = "completed"
                
                # Update lesson progress
                if stage == PipelineStage.LESSON_GENERATION:
                    active_generations[generation_id]["total_lessons"] = len(orchestrator.lessons)
                
                # Update completed lessons from session
                session = orchestrator.session_manager.get_session(session_id)
                if session:
                    active_generations[generation_id]["completed_lessons"] = session.completed_lessons
                
                # Small delay to allow status polling
                await asyncio.sleep(0.1)
                
            except Exception as e:
                orchestrator.session_manager.fail_stage(session_id, stage, str(e))
                active_generations[generation_id]["stages"][stage.value] = "failed"
                active_generations[generation_id]["stage_status"] = "failed"
                active_generations[generation_id]["error_message"] = str(e)
                active_generations[generation_id]["status"] = "failed"
                raise
        
        # Run DOCX export
        active_generations[generation_id]["current_stage"] = "docx_export"
        active_generations[generation_id]["stage_status"] = "running"
        active_generations[generation_id]["stages"]["docx_export"] = "running"
        
        try:
            orchestrator._run_docx_export()
            active_generations[generation_id]["stages"]["docx_export"] = "completed"
        except Exception as e:
            active_generations[generation_id]["stages"]["docx_export"] = "failed"
            active_generations[generation_id]["error_message"] = str(e)
            active_generations[generation_id]["status"] = "failed"
            raise
        
        # Mark as completed
        orchestrator.session_manager.update_session_status(
            session_id, SessionStatus.COMPLETED
        )
        active_generations[generation_id]["status"] = "completed"
        active_generations[generation_id]["current_stage"] = None
        active_generations[generation_id]["stage_status"] = "completed"
        
    except Exception as e:
        active_generations[generation_id]["status"] = "failed"
        active_generations[generation_id]["error_message"] = str(e)
        if orchestrator and orchestrator.session_id:
            orchestrator.session_manager.update_session_status(
                orchestrator.session_id, SessionStatus.FAILED, error_message=str(e)
            )
    finally:
        if orchestrator:
            try:
                orchestrator.close()
            except:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    for gen_id, gen_data in active_generations.items():
        if gen_data["status"] == "running":
            gen_data["status"] = "cancelled"
            gen_data["error_message"] = "Server shutdown"


app = FastAPI(
    title="AI Agent Content Generator API",
    description="FastAPI server for running the content generation pipeline",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "active_generations": len(active_generations)}


@app.post("/api/generate", response_model=GenerationResponse)
async def start_generation(request: GenerationRequest, background_tasks: BackgroundTasks):
    """Start a new content generation."""
    generation_id = str(uuid.uuid4())
    
    # Validate request
    try:
        user_input = user_input_from_request(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {e}")
    
    # Initialize generation status
    active_generations[generation_id] = {
        "generation_id": generation_id,
        "session_id": None,
        "status": "initializing",
        "current_stage": None,
        "stage_status": None,
        "stage_progress": {},
        "total_lessons": 0,
        "completed_lessons": 0,
        "error_message": None,
        "stages": {}
    }
    
    # Run pipeline in background
    background_tasks.add_task(run_pipeline_async, generation_id, request)
    
    return GenerationResponse(
        generation_id=generation_id,
        session_id="pending",
        status="initializing",
        message="Generation started. Use /api/generate/{generation_id}/status to track progress."
    )


@app.get("/api/generate/{generation_id}/status", response_model=GenerationStatus)
async def get_generation_status(generation_id: str):
    """Get the status of a generation."""
    if generation_id not in active_generations:
        raise HTTPException(status_code=404, detail="Generation not found")
    
    gen = active_generations[generation_id]
    return GenerationStatus(**gen)


@app.get("/api/generate/{generation_id}/events")
async def generation_events(generation_id: str):
    """Server-Sent Events endpoint for real-time updates."""
    from fastapi.responses import StreamingResponse
    import json
    
    async def event_generator():
        last_status = None
        while True:
            if generation_id not in active_generations:
                yield f"data: {json.dumps({'error': 'Generation not found'})}\n\n"
                break
            
            gen = active_generations[generation_id]
            current_status = gen.get("status")
            
            if current_status != last_status or gen.get("current_stage"):
                yield f"data: {json.dumps(gen)}\n\n"
                last_status = current_status
            
            if current_status in ("completed", "failed", "cancelled"):
                break
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/sessions")
async def list_sessions(processing_dir: str = "processing"):
    """List all sessions."""
    session_manager = SessionManager(Path(processing_dir) / "sessions.db")
    sessions = session_manager.list_sessions()
    session_manager.close()
    
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "prompt": s.prompt,
                "status": s.status.value,
                "created_at": s.created_at.isoformat(),
                "total_lessons": s.total_lessons,
                "completed_lessons": s.completed_lessons
            }
            for s in sessions
        ]
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, processing_dir: str = "processing"):
    """Get session details."""
    session_manager = SessionManager(Path(processing_dir) / "sessions.db")
    session = session_manager.get_session(session_id)
    session_manager.close()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session.session_id,
        "prompt": session.prompt,
        "status": session.status.value,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "current_stage": session.current_stage.value if session.current_stage else None,
        "total_lessons": session.total_lessons,
        "completed_lessons": session.completed_lessons,
        "error_message": session.error_message,
        "config": session.config,
        "stage_statuses": {
            stage.value: status.value 
            for stage, status in session_manager.get_all_stage_statuses(session_id).items()
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)