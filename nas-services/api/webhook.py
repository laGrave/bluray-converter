#!/usr/bin/env python3
"""
BluRay Converter - Webhook Handler
Processes status updates from Mac mini worker
"""

import os
import sys
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.db_manager import DatabaseManager, TaskStatus
from file_manager import FileManager, create_file_manager
from telegram_bot import TelegramNotifier


# Webhook request models
class StatusUpdateRequest(BaseModel):
    task_id: int
    status: str
    source_folder: Optional[str] = None
    temp_file: Optional[str] = None
    processing_time: Optional[float] = None
    file_size_mb: Optional[float] = None
    error: Optional[str] = None
    progress_percent: Optional[float] = None


class WorkerNotificationRequest(BaseModel):
    worker_id: str
    timestamp: float
    event_type: Optional[str] = None


# Response models
class WebhookResponse(BaseModel):
    success: bool
    message: str


# Create router
router = APIRouter(prefix="/api/webhook", tags=["webhook"])

# Global instances (initialized in setup_webhook)
db_manager: Optional[DatabaseManager] = None
file_manager: Optional[FileManager] = None
telegram: Optional[TelegramNotifier] = None
logger = logging.getLogger(__name__)


def setup_webhook(
    database_manager: DatabaseManager,
    file_manager_instance: Optional[FileManager] = None,
    telegram_notifier: Optional[TelegramNotifier] = None
):
    """Initialize webhook dependencies"""
    global db_manager, file_manager, telegram
    db_manager = database_manager
    file_manager = file_manager_instance or create_file_manager()
    telegram = telegram_notifier
    logger.info("Webhook handler initialized")


@router.post("/status", response_model=WebhookResponse)
async def receive_status_update(
    update: StatusUpdateRequest,
    background_tasks: BackgroundTasks
):
    """Receive status update from Mac mini worker"""
    try:
        logger.info(f"Received status update for task {update.task_id}: {update.status}")
        
        if not db_manager:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Validate task exists
        task = await db_manager.get_task_details(update.task_id)
        if not task:
            logger.warning(f"Received update for unknown task {update.task_id}")
            raise HTTPException(status_code=404, detail=f"Task {update.task_id} not found")
        
        # Handle different status updates
        if update.status == TaskStatus.PROCESSING.value:
            await handle_processing_status(task, update)
            
        elif update.status == TaskStatus.COMPLETED.value:
            # Process completion in background
            background_tasks.add_task(
                handle_completion_status,
                task, update
            )
            
        elif update.status == TaskStatus.FAILED.value:
            await handle_failed_status(task, update)
            
        else:
            logger.warning(f"Unknown status received: {update.status}")
            raise HTTPException(status_code=400, detail=f"Unknown status: {update.status}")
        
        return WebhookResponse(
            success=True,
            message=f"Status update processed for task {update.task_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing status update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_processing_status(task: Dict[str, Any], update: StatusUpdateRequest):
    """Handle task processing status update"""
    try:
        # Update task status
        await db_manager.update_task_status(update.task_id, TaskStatus.PROCESSING)
        
        # Update processing started time if not already set
        if not task.get("processing_started_at"):
            await db_manager.set_processing_started(update.task_id)
        
        # Update progress if provided
        if update.progress_percent is not None:
            await db_manager.update_task_progress(update.task_id, update.progress_percent)
            
            # Send telegram update for significant progress milestones
            if telegram and update.progress_percent in [25, 50, 75]:
                await telegram.send_message(
                    f"⏳ Processing {task['movie_name']}: {update.progress_percent:.0f}%"
                )
        
        logger.info(f"Task {update.task_id} processing status updated")
        
    except Exception as e:
        logger.error(f"Error handling processing status: {e}")
        raise


async def handle_completion_status(task: Dict[str, Any], update: StatusUpdateRequest):
    """Handle task completion - move files and update status"""
    try:
        logger.info(f"Processing completion for task {update.task_id}")
        
        # Validate required fields
        if not update.temp_file:
            raise ValueError("No temp_file provided in completion update")
        
        # Move file from temp to processed folder
        if file_manager:
            success = await file_manager.move_to_processed(
                temp_file=update.temp_file,
                source_folder=update.source_folder or task['movie_name']
            )
            
            if success:
                # Delete source folder if configured
                if file_manager.delete_source_after_success:
                    deleted = await file_manager.delete_source_folder(
                        update.source_folder or task['movie_name']
                    )
                    if deleted:
                        logger.info(f"Source folder deleted: {update.source_folder}")
            else:
                raise Exception("Failed to move processed file")
        
        # Update task status in database
        await db_manager.update_task_status(update.task_id, TaskStatus.COMPLETED)
        await db_manager.set_processing_completed(update.task_id)
        
        # Record processing history
        if update.processing_time and update.file_size_mb:
            await db_manager.record_processing_history(
                task_id=update.task_id,
                movie_name=task['movie_name'],
                processing_time_seconds=update.processing_time,
                file_size_mb=update.file_size_mb,
                success=True
            )
        
        # Send success notification
        if telegram:
            processing_time_min = update.processing_time / 60 if update.processing_time else 0
            file_size_gb = update.file_size_mb / 1024 if update.file_size_mb else 0
            
            await telegram.send_message(
                f"✅ Completed: {task['movie_name']}\n"
                f"⏱ Time: {processing_time_min:.1f} minutes\n"
                f"💾 Size: {file_size_gb:.1f} GB\n"
                f"📁 Location: BluRayProcessed"
            )
        
        logger.info(f"Task {update.task_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Error handling completion status: {e}")
        
        # Update task as failed
        await db_manager.update_task_status(update.task_id, TaskStatus.FAILED)
        await db_manager.record_error(
            update.task_id,
            f"Post-processing error: {str(e)}"
        )
        
        # Send failure notification
        if telegram:
            await telegram.send_message(
                f"❌ Post-processing failed: {task['movie_name']}\n"
                f"Error: {str(e)}"
            )
        
        raise


async def handle_failed_status(task: Dict[str, Any], update: StatusUpdateRequest):
    """Handle task failure status update"""
    try:
        # Update task status
        await db_manager.update_task_status(update.task_id, TaskStatus.FAILED)
        
        # Record error
        error_message = update.error or "Unknown error"
        await db_manager.record_error(update.task_id, error_message)
        
        # Increment attempts
        await db_manager.increment_task_attempts(update.task_id)
        
        # Record processing history
        if update.processing_time:
            await db_manager.record_processing_history(
                task_id=update.task_id,
                movie_name=task['movie_name'],
                processing_time_seconds=update.processing_time,
                file_size_mb=0,
                success=False,
                error_message=error_message
            )
        
        # Check if should retry
        if task['attempts'] < 2:  # Max 3 attempts total
            # Schedule for retry
            await db_manager.update_task_status(update.task_id, TaskStatus.RETRYING)
            logger.info(f"Task {update.task_id} scheduled for retry (attempt {task['attempts'] + 1})")
            
            # Update to pending for next processing cycle
            await db_manager.update_task_status(update.task_id, TaskStatus.PENDING)
        
        # Send failure notification
        if telegram:
            retry_info = f"\n🔄 Will retry (attempt {task['attempts'] + 1}/3)" if task['attempts'] < 2 else ""
            await telegram.send_message(
                f"❌ Failed: {task['movie_name']}\n"
                f"Error: {error_message}{retry_info}"
            )
        
        logger.info(f"Task {update.task_id} marked as failed")
        
    except Exception as e:
        logger.error(f"Error handling failed status: {e}")
        raise


@router.post("/worker/startup", response_model=WebhookResponse)
async def worker_startup_notification(request: WorkerNotificationRequest):
    """Handle worker startup notification"""
    try:
        logger.info(f"Worker {request.worker_id} started at {datetime.fromtimestamp(request.timestamp)}")
        
        # Send notification
        if telegram:
            await telegram.send_message(
                f"🟢 Worker online: {request.worker_id}\n"
                f"Ready to process tasks"
            )
        
        return WebhookResponse(
            success=True,
            message=f"Worker {request.worker_id} startup acknowledged"
        )
        
    except Exception as e:
        logger.error(f"Error handling worker startup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/worker/shutdown", response_model=WebhookResponse)
async def worker_shutdown_notification(request: WorkerNotificationRequest):
    """Handle worker shutdown notification"""
    try:
        logger.info(f"Worker {request.worker_id} shutting down at {datetime.fromtimestamp(request.timestamp)}")
        
        # Check for any tasks that were processing
        if db_manager:
            processing_tasks = await db_manager.get_tasks_by_status(TaskStatus.PROCESSING)
            
            # Reset processing tasks to pending
            for task in processing_tasks:
                await db_manager.update_task_status(task['id'], TaskStatus.PENDING)
                logger.warning(f"Task {task['id']} reset to pending due to worker shutdown")
        
        # Send notification
        if telegram:
            await telegram.send_message(
                f"🔴 Worker offline: {request.worker_id}\n"
                f"Tasks will resume when worker restarts"
            )
        
        return WebhookResponse(
            success=True,
            message=f"Worker {request.worker_id} shutdown acknowledged"
        )
        
    except Exception as e:
        logger.error(f"Error handling worker shutdown: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Additional utility endpoints

@router.post("/test", response_model=WebhookResponse)
async def test_webhook():
    """Test webhook endpoint"""
    try:
        logger.info("Webhook test called")
        
        # Test telegram if available
        if telegram:
            await telegram.send_message("🧪 Webhook test successful")
        
        return WebhookResponse(
            success=True,
            message="Webhook test successful"
        )
        
    except Exception as e:
        logger.error(f"Webhook test error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Export router
__all__ = ['router', 'setup_webhook']