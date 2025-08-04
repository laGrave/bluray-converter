#!/usr/bin/env python3
"""
BluRay Converter - API Routes
REST API endpoints for task management and system control
"""

import os
import sys
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.db_manager import DatabaseManager, TaskStatus
from watcher.scanner import BluRayScanner
from telegram_bot import TelegramNotifier, create_telegram_notifier


# Request/Response models
class TaskResponse(BaseModel):
    id: int
    movie_name: str
    source_path: str
    status: str
    priority: int
    attempts: int
    created_at: datetime
    updated_at: datetime
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ScanResponse(BaseModel):
    success: bool
    message: str
    new_movies_found: int = 0
    tasks_created: int = 0


class TaskActionResponse(BaseModel):
    success: bool
    message: str
    task_id: Optional[int] = None


class StatisticsResponse(BaseModel):
    total_tasks: int
    pending_tasks: int
    processing_tasks: int
    completed_tasks: int
    failed_tasks: int
    total_processed_size_gb: float
    average_processing_time_minutes: float
    success_rate: float
    tasks_by_month: List[Dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    version: str
    database_connected: bool
    scanner_configured: bool
    telegram_configured: bool


# Create router
router = APIRouter(prefix="/api", tags=["tasks"])

# Global instances (initialized in setup_routes)
db_manager: Optional[DatabaseManager] = None
scanner: Optional[BluRayScanner] = None
telegram: Optional[TelegramNotifier] = None
logger = logging.getLogger(__name__)


def setup_routes(
    database_manager: DatabaseManager,
    bluray_scanner: BluRayScanner,
    telegram_notifier: Optional[TelegramNotifier] = None
):
    """Initialize route dependencies"""
    global db_manager, scanner, telegram
    db_manager = database_manager
    scanner = bluray_scanner
    telegram = telegram_notifier
    logger.info("API routes initialized")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check"""
    try:
        # Check database connection
        db_connected = False
        if db_manager:
            try:
                await db_manager.get_task_count()
                db_connected = True
            except Exception:
                pass
        
        # Check scanner configuration
        scanner_configured = scanner is not None and scanner.validate_config()
        
        # Check telegram configuration
        telegram_configured = telegram is not None
        
        return HealthResponse(
            status="healthy" if db_connected else "degraded",
            version="1.0.0",
            database_connected=db_connected,
            scanner_configured=scanner_configured,
            telegram_configured=telegram_configured
        )
    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/tasks", response_model=List[TaskResponse])
async def get_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get list of tasks with optional filtering"""
    try:
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Validate status if provided
        if status and status not in [s.value for s in TaskStatus]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Valid values: {[s.value for s in TaskStatus]}"
            )
        
        # Get tasks from database
        if status:
            tasks = await db_manager.get_tasks_by_status(TaskStatus(status), limit=limit)
        else:
            tasks = await db_manager.get_all_tasks(limit=limit, offset=offset)
        
        # Convert to response format
        return [
            TaskResponse(
                id=task["id"],
                movie_name=task["movie_name"],
                source_path=task["source_path"],
                status=task["status"],
                priority=task["priority"],
                attempts=task["attempts"],
                created_at=task["created_at"],
                updated_at=task["updated_at"],
                processing_started_at=task.get("processing_started_at"),
                processing_completed_at=task.get("processing_completed_at"),
                error_message=task.get("error_message")
            )
            for task in tasks
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    """Get specific task details"""
    try:
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        task = await db_manager.get_task_details(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        return TaskResponse(
            id=task["id"],
            movie_name=task["movie_name"],
            source_path=task["source_path"],
            status=task["status"],
            priority=task["priority"],
            attempts=task["attempts"],
            created_at=task["created_at"],
            updated_at=task["updated_at"],
            processing_started_at=task.get("processing_started_at"),
            processing_completed_at=task.get("processing_completed_at"),
            error_message=task.get("error_message")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/scan", response_model=ScanResponse)
async def scan_for_movies(background_tasks: BackgroundTasks):
    """Trigger manual scan for new BluRay movies"""
    try:
        if not scanner:
            raise HTTPException(status_code=503, detail="Scanner not available")
        
        logger.info("Manual scan triggered via API")
        
        # Run scan in background
        background_tasks.add_task(run_scan_task)
        
        return ScanResponse(
            success=True,
            message="Scan started in background"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def run_scan_task():
    """Background task to run directory scan"""
    try:
        logger.info("Starting background scan task")
        
        # Send telegram notification
        if telegram:
            await telegram.send_message("🔍 Manual scan started")
        
        # Run scan
        new_movies = await scanner.scan_for_new_movies()
        
        if new_movies:
            logger.info(f"Scan completed: {len(new_movies)} new movies found")
            
            # Create tasks
            tasks_created = 0
            for movie in new_movies:
                task_id = await db_manager.create_task(
                    movie_name=movie["name"],
                    source_path=movie["path"],
                    priority=movie.get("priority", 0)
                )
                if task_id:
                    tasks_created += 1
            
            # Send notification
            if telegram:
                await telegram.send_message(
                    f"✅ Scan completed\n"
                    f"📀 Found: {len(new_movies)} movies\n"
                    f"📝 Created: {tasks_created} tasks"
                )
        else:
            logger.info("Scan completed: No new movies found")
            if telegram:
                await telegram.send_message("✅ Scan completed - no new movies found")
                
    except Exception as e:
        logger.error(f"Error in background scan: {e}")
        if telegram:
            await telegram.send_message(f"❌ Scan failed: {str(e)}")


@router.post("/tasks/{task_id}/restart", response_model=TaskActionResponse)
async def restart_task(task_id: int):
    """Restart a failed or completed task"""
    try:
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Get task details
        task = await db_manager.get_task_details(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Only allow restart of completed or failed tasks
        if task["status"] not in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot restart task in status: {task['status']}"
            )
        
        # Reset task status
        await db_manager.update_task_status(task_id, TaskStatus.PENDING)
        await db_manager.reset_task_attempts(task_id)
        
        logger.info(f"Task {task_id} restarted")
        
        return TaskActionResponse(
            success=True,
            message=f"Task {task_id} restarted successfully",
            task_id=task_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restarting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}", response_model=TaskActionResponse)
async def delete_task(task_id: int):
    """Delete a task"""
    try:
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Get task details
        task = await db_manager.get_task_details(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Don't allow deletion of processing tasks
        if task["status"] == TaskStatus.PROCESSING.value:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete task that is currently processing"
            )
        
        # Delete task
        await db_manager.delete_task(task_id)
        
        logger.info(f"Task {task_id} deleted")
        
        return TaskActionResponse(
            success=True,
            message=f"Task {task_id} deleted successfully",
            task_id=task_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/priority", response_model=TaskActionResponse)
async def set_task_priority(task_id: int, priority: int = Query(..., ge=0, le=10)):
    """Set task priority (0-10, higher = more priority)"""
    try:
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Get task details
        task = await db_manager.get_task_details(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Update priority
        await db_manager.update_task_priority(task_id, priority)
        
        logger.info(f"Task {task_id} priority set to {priority}")
        
        return TaskActionResponse(
            success=True,
            message=f"Task {task_id} priority updated to {priority}",
            task_id=task_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting task priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics():
    """Get processing statistics"""
    try:
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Get statistics
        stats = await db_manager.get_statistics()
        
        # Get task counts by status
        task_counts = await db_manager.get_task_counts_by_status()
        
        # Calculate derived metrics
        total_tasks = sum(task_counts.values())
        completed_tasks = task_counts.get(TaskStatus.COMPLETED.value, 0)
        failed_tasks = task_counts.get(TaskStatus.FAILED.value, 0)
        
        success_rate = 0.0
        if completed_tasks + failed_tasks > 0:
            success_rate = (completed_tasks / (completed_tasks + failed_tasks)) * 100
        
        return StatisticsResponse(
            total_tasks=total_tasks,
            pending_tasks=task_counts.get(TaskStatus.PENDING.value, 0),
            processing_tasks=task_counts.get(TaskStatus.PROCESSING.value, 0) + 
                           task_counts.get(TaskStatus.SENT.value, 0),
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            total_processed_size_gb=stats.get("total_size_gb", 0.0),
            average_processing_time_minutes=stats.get("avg_time_minutes", 0.0),
            success_rate=success_rate,
            tasks_by_month=stats.get("by_month", [])
        )
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None, description="Log level filter")
):
    """Get system logs"""
    try:
        # This is a placeholder - in production, you'd read from actual log files
        # For now, return basic info
        return {
            "logs": [
                {
                    "timestamp": datetime.now().isoformat(),
                    "level": "INFO",
                    "message": "Log endpoint placeholder"
                }
            ],
            "total": 1,
            "limit": limit,
            "level_filter": level
        }
        
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Export router
__all__ = ['router', 'setup_routes']