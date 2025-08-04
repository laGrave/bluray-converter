#!/usr/bin/env python3
"""
BluRay Converter - Worker Service Main Entry Point
FastAPI server for receiving and processing conversion tasks
"""

import os
import sys
import asyncio
import logging
import signal
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from processor import VideoProcessor, ProcessingTask, ProcessingResult, create_video_processor
from nas_client import NASClient, create_nas_client, TaskStatusReporter
from ffmpeg_wrapper import ConversionProgress


# Request/Response models
class ProcessingRequest(BaseModel):
    task_id: int
    movie_name: str
    source_path: str
    priority: int = 0
    nas_webhook_url: Optional[str] = None
    nas_ip: Optional[str] = None
    smb_config: Optional[Dict[str, Any]] = None


class ProcessingResponse(BaseModel):
    success: bool
    message: str
    task_id: int


class StatusResponse(BaseModel):
    task_id: Optional[int] = None
    is_processing: bool = False
    progress_percent: float = 0.0
    status: str = "idle"
    current_movie: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    current_task: Optional[int] = None


# Global application state
class AppState:
    def __init__(self):
        self.video_processor: Optional[VideoProcessor] = None
        self.nas_client: Optional[NASClient] = None
        self.status_reporter: Optional[TaskStatusReporter] = None
        self.start_time = asyncio.get_event_loop().time()
        self.current_progress: Optional[ConversionProgress] = None
        self.shutdown_event = asyncio.Event()


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger = logging.getLogger(__name__)
    
    try:
        # Startup
        logger.info("Starting BluRay Converter Worker Service")
        
        # Initialize components
        app_state.video_processor = create_video_processor()
        app_state.nas_client = create_nas_client()
        app_state.status_reporter = TaskStatusReporter(app_state.nas_client)
        
        # Set up progress callback
        app_state.video_processor.set_progress_callback(on_processing_progress)
        
        # Notify NAS of startup
        await app_state.nas_client.notify_worker_startup()
        
        # Setup signal handlers
        setup_signal_handlers()
        
        logger.info("Worker Service startup completed")
        
        yield
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    finally:
        # Shutdown
        logger.info("Shutting down Worker Service")
        
        # Cancel any running task
        if app_state.video_processor and app_state.video_processor.is_busy():
            await app_state.video_processor.cancel_current_task()
        
        # Notify NAS of shutdown
        if app_state.nas_client:
            await app_state.nas_client.notify_worker_shutdown()
        
        # Cleanup temp files
        if app_state.video_processor:
            await app_state.video_processor.cleanup_temp_files(older_than_hours=0)
        
        logger.info("Worker Service shutdown completed")


# Initialize FastAPI app
app = FastAPI(
    title="BluRay Converter Worker",
    description="Mac mini worker service for BluRay to MKV conversion",
    version="1.0.0",
    lifespan=lifespan
)


def setup_signal_handlers():
    """Setup graceful shutdown signal handlers"""
    def signal_handler(signum, frame):
        logger = logging.getLogger(__name__)
        logger.info(f"Received signal {signum}, initiating shutdown...")
        app_state.shutdown_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def on_processing_progress(task_id: int, progress: ConversionProgress):
    """Handle processing progress updates"""
    app_state.current_progress = progress
    
    # Send progress updates to NAS (throttled)
    if progress.progress_percent % 10 == 0:  # Every 10%
        asyncio.create_task(
            app_state.nas_client.send_task_progress(task_id, progress.progress_percent)
        )


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    uptime = asyncio.get_event_loop().time() - app_state.start_time
    current_task = None
    
    if app_state.video_processor:
        current_task = app_state.video_processor.get_current_task_id()
    
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        uptime_seconds=uptime,
        current_task=current_task
    )


@app.post("/api/process", response_model=ProcessingResponse)
async def process_video(
    request: ProcessingRequest, 
    background_tasks: BackgroundTasks
):
    """Start video processing task"""
    logger = logging.getLogger(__name__)
    
    try:
        # Check if already processing
        if app_state.video_processor.is_busy():
            raise HTTPException(
                status_code=429,
                detail="Worker is already processing a task"
            )
        
        logger.info(f"Received processing request for task {request.task_id}: {request.movie_name}")
        
        # Create processing task
        task = ProcessingTask(
            task_id=request.task_id,
            movie_name=request.movie_name,
            source_path=request.source_path,
            priority=request.priority,
            nas_webhook_url=request.nas_webhook_url,
            nas_ip=request.nas_ip,
            smb_config=request.smb_config
        )
        
        # Start processing in background
        background_tasks.add_task(process_task_background, task)
        
        return ProcessingResponse(
            success=True,
            message=f"Processing started for task {request.task_id}",
            task_id=request.task_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting processing: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start processing: {str(e)}"
        )


async def process_task_background(task: ProcessingTask):
    """Background task processing with status reporting"""
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Starting background processing for task {task.task_id}")
        
        # Process the task
        result = await app_state.video_processor.process_task(task)
        
        # Report result to NAS
        await app_state.status_reporter.report_task_lifecycle(
            task_id=result.task_id,
            source_folder=task.movie_name,
            success=result.success,
            processing_time=result.processing_time_seconds,
            temp_file=result.temp_file,
            file_size_mb=result.output_size_mb,
            error=result.error_message
        )
        
        if result.success:
            logger.info(f"Task {task.task_id} completed successfully")
        else:
            logger.error(f"Task {task.task_id} failed: {result.error_message}")
            
    except Exception as e:
        logger.error(f"Unexpected error in background processing: {e}")
        
        # Try to report failure
        try:
            await app_state.nas_client.send_task_failed(
                task_id=task.task_id,
                source_folder=task.movie_name,
                error=f"Background processing error: {str(e)}"
            )
        except Exception as report_error:
            logger.error(f"Failed to report task failure: {report_error}")


@app.get("/api/status/{task_id}")
async def get_task_status(task_id: int):
    """Get status of specific task"""
    current_task_id = app_state.video_processor.get_current_task_id()
    
    if current_task_id != task_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found or not currently processing"
        )
    
    progress = app_state.current_progress
    
    return {
        "task_id": task_id,
        "is_processing": True,
        "progress_percent": progress.progress_percent if progress else 0.0,
        "status": progress.status.value if progress else "processing",
        "fps": progress.fps if progress else 0.0,
        "bitrate": progress.bitrate if progress else "0kbps",
        "time_processed": progress.time_processed if progress else "00:00:00",
        "time_remaining": progress.time_remaining if progress else "Unknown"
    }


@app.get("/api/status", response_model=StatusResponse)
async def get_worker_status():
    """Get overall worker status"""
    current_task_id = None
    current_movie = None
    progress_percent = 0.0
    status = "idle"
    
    if app_state.video_processor.is_busy():
        current_task_id = app_state.video_processor.get_current_task_id()
        
        if app_state.current_progress:
            progress_percent = app_state.current_progress.progress_percent
            status = app_state.current_progress.status.value
            
        # Get current movie name from processor if available
        if hasattr(app_state.video_processor, 'current_task') and app_state.video_processor.current_task:
            current_movie = app_state.video_processor.current_task.movie_name
    
    return StatusResponse(
        task_id=current_task_id,
        is_processing=app_state.video_processor.is_busy(),
        progress_percent=progress_percent,
        status=status,
        current_movie=current_movie
    )


@app.delete("/api/process/{task_id}")
async def cancel_task(task_id: int):
    """Cancel a processing task"""
    logger = logging.getLogger(__name__)
    
    current_task_id = app_state.video_processor.get_current_task_id()
    
    if current_task_id != task_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found or not currently processing"
        )
    
    success = await app_state.video_processor.cancel_current_task()
    
    if success:
        logger.info(f"Task {task_id} cancelled successfully")
        
        # Notify NAS of cancellation
        await app_state.nas_client.send_task_failed(
            task_id=task_id,
            source_folder="Unknown",
            error="Task cancelled by user request"
        )
        
        return {"message": f"Task {task_id} cancelled successfully"}
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to cancel task {task_id}"
        )


@app.post("/api/cleanup")
async def cleanup_temp_files(older_than_hours: int = 24):
    """Clean up old temporary files"""
    if not app_state.video_processor:
        raise HTTPException(status_code=503, detail="Video processor not available")
    
    await app_state.video_processor.cleanup_temp_files(older_than_hours)
    
    return {"message": f"Cleanup completed for files older than {older_than_hours} hours"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"}
    )


def setup_logging():
    """Setup application logging"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper())
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/app/logs/worker.log') if os.path.exists('/app/logs') else logging.NullHandler()
        ]
    )
    
    # Reduce verbosity of some loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)


if __name__ == "__main__":
    # This will only run when called directly (not with uvicorn)
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("Starting BluRay Converter Worker Service (direct mode)")
    
    import uvicorn
    
    # Configuration
    host = os.getenv("WORKER_HOST", "0.0.0.0")
    port = int(os.getenv("WORKER_PORT", "8000"))
    workers = 1  # Single worker for video processing
    
    # Run server
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=workers,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=True
    )