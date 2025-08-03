#!/usr/bin/env python3
"""
BluRay Converter - Watcher Service Main Entry Point
Scans directories for new BluRay movies and creates processing tasks
"""

import os
import sys
import asyncio
import logging
import signal
from typing import Optional
from pathlib import Path

from scanner import BluRayScanner
from db_manager import DatabaseManager, TaskStatus
from mac_client import MacClient, ProcessingTask, create_mac_client


class WatcherService:
    """Main watcher service that coordinates scanning and task management"""
    
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.scan_interval = int(os.getenv("SCAN_INTERVAL", "3600"))  # 1 hour default
        self.max_concurrent_tasks = int(os.getenv("MAX_CONCURRENT_TASKS", "1"))
        self.retry_failed_interval = int(os.getenv("RETRY_FAILED_INTERVAL", "1800"))  # 30 min
        
        # Components
        self.db_manager: Optional[DatabaseManager] = None
        self.scanner: Optional[BluRayScanner] = None
        self.mac_client: Optional[MacClient] = None
        
        # Mock mode
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
        
    async def initialize(self) -> bool:
        """Initialize all service components"""
        try:
            self.logger.info("Initializing Watcher Service...")
            
            # Initialize database
            self.db_manager = DatabaseManager()
            await self.db_manager.initialize()
            self.logger.info("Database manager initialized")
            
            # Initialize scanner
            self.scanner = BluRayScanner(self.db_manager)
            if not self.scanner.validate_config():
                self.logger.error("Scanner configuration validation failed")
                return False
            self.logger.info("BluRay scanner initialized")
            
            # Initialize Mac client
            self.mac_client = create_mac_client()
            self.logger.info("Mac client initialized")
            
            # Setup signal handlers
            self._setup_signal_handlers()
            
            self.logger.info("Watcher Service initialization completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Watcher Service: {e}")
            return False
    
    def _setup_signal_handlers(self):
        """Setup graceful shutdown signal handlers"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def scan_and_process(self) -> int:
        """Scan for new movies and create processing tasks"""
        try:
            self.logger.info("Starting directory scan...")
            
            # Scan for new movies
            new_movies = await self.scanner.scan_for_new_movies()
            
            if not new_movies:
                self.logger.info("No new movies found")
                return 0
            
            self.logger.info(f"Found {len(new_movies)} new movies: {[m['name'] for m in new_movies]}")
            
            # Create tasks for new movies
            tasks_created = 0
            for movie in new_movies:
                try:
                    task_id = await self.db_manager.create_task(
                        movie_name=movie["name"],
                        source_path=movie["path"],
                        priority=movie.get("priority", 0)
                    )
                    
                    if task_id:
                        tasks_created += 1
                        self.logger.info(f"Created task {task_id} for movie: {movie['name']}")
                    else:
                        self.logger.warning(f"Failed to create task for movie: {movie['name']}")
                
                except Exception as e:
                    self.logger.error(f"Error creating task for {movie['name']}: {e}")
            
            self.logger.info(f"Created {tasks_created} new processing tasks")
            return tasks_created
            
        except Exception as e:
            self.logger.error(f"Error during scan and process: {e}")
            return 0
    
    async def process_pending_tasks(self) -> int:
        """Send pending tasks to Mac mini for processing"""
        try:
            # Get pending tasks (limited by max concurrent)
            pending_tasks = await self.db_manager.get_pending_tasks(limit=self.max_concurrent_tasks)
            
            if not pending_tasks:
                return 0
            
            self.logger.info(f"Processing {len(pending_tasks)} pending tasks")
            
            tasks_sent = 0
            for task_data in pending_tasks:
                try:
                    # Create processing task
                    task = ProcessingTask(
                        task_id=task_data["id"],
                        movie_name=task_data["movie_name"],
                        source_path=task_data["source_path"],
                        priority=task_data["priority"]
                    )
                    
                    # Update task status to 'sent' before sending
                    await self.db_manager.update_task_status(task.task_id, TaskStatus.SENT)
                    
                    # Send to Mac mini
                    success = await self.mac_client.send_task(task)
                    
                    if success:
                        # Task successfully sent to Mac
                        tasks_sent += 1
                        self.logger.info(f"Task {task.task_id} sent to Mac mini successfully")
                    else:
                        # Failed to send, revert to pending with attempt count
                        await self.db_manager.increment_task_attempts(task.task_id)
                        await self.db_manager.update_task_status(task.task_id, TaskStatus.PENDING)
                        self.logger.warning(f"Failed to send task {task.task_id}, reverted to pending")
                
                except Exception as e:
                    self.logger.error(f"Error processing task {task_data['id']}: {e}")
                    # Revert task status on error
                    await self.db_manager.update_task_status(task_data["id"], TaskStatus.PENDING)
            
            if tasks_sent > 0:
                self.logger.info(f"Successfully sent {tasks_sent} tasks to Mac mini")
            
            return tasks_sent
            
        except Exception as e:
            self.logger.error(f"Error processing pending tasks: {e}")
            return 0
    
    async def retry_failed_tasks(self) -> int:
        """Retry failed tasks that are eligible for retry"""
        try:
            # Get failed tasks that can be retried
            failed_tasks = await self.db_manager.get_failed_tasks_for_retry()
            
            if not failed_tasks:
                return 0
            
            self.logger.info(f"Retrying {len(failed_tasks)} failed tasks")
            
            retries_attempted = 0
            for task_data in failed_tasks:
                try:
                    # Reset task to pending for retry
                    await self.db_manager.update_task_status(task_data["id"], TaskStatus.RETRYING)
                    await self.db_manager.increment_task_attempts(task_data["id"])
                    await self.db_manager.update_task_status(task_data["id"], TaskStatus.PENDING)
                    
                    retries_attempted += 1
                    self.logger.info(f"Task {task_data['id']} ({task_data['movie_name']}) set for retry")
                
                except Exception as e:
                    self.logger.error(f"Error retrying task {task_data['id']}: {e}")
            
            return retries_attempted
            
        except Exception as e:
            self.logger.error(f"Error retrying failed tasks: {e}")
            return 0
    
    async def maintenance_tasks(self):
        """Perform periodic maintenance tasks"""
        try:
            self.logger.debug("Running maintenance tasks...")
            
            # Clean up old database records
            cleaned_count = await self.db_manager.cleanup_old_records()
            if cleaned_count > 0:
                self.logger.info(f"Cleaned up {cleaned_count} old database records")
            
            # Check Mac mini health
            is_healthy = await self.mac_client.health_check()
            if not is_healthy and not self.mock_mode:
                self.logger.warning("Mac mini health check failed")
            else:
                self.logger.debug("Mac mini health check passed")
            
        except Exception as e:
            self.logger.error(f"Error during maintenance tasks: {e}")
    
    async def run_single_cycle(self) -> dict:
        """Run a single processing cycle and return statistics"""
        cycle_stats = {
            "new_movies_found": 0,
            "tasks_created": 0,
            "tasks_sent": 0,
            "tasks_retried": 0
        }
        
        try:
            # 1. Scan for new movies and create tasks
            cycle_stats["tasks_created"] = await self.scan_and_process()
            cycle_stats["new_movies_found"] = cycle_stats["tasks_created"]  # 1:1 ratio
            
            # 2. Process pending tasks
            cycle_stats["tasks_sent"] = await self.process_pending_tasks()
            
            # 3. Retry failed tasks (less frequently)
            cycle_stats["tasks_retried"] = await self.retry_failed_tasks()
            
            # 4. Maintenance
            await self.maintenance_tasks()
            
            # Log cycle summary
            if any(cycle_stats.values()):
                self.logger.info(f"Cycle completed: {cycle_stats}")
            else:
                self.logger.debug("Cycle completed: no activity")
            
        except Exception as e:
            self.logger.error(f"Error during processing cycle: {e}")
        
        return cycle_stats
    
    async def run_service(self):
        """Main service loop"""
        self.logger.info("Starting Watcher Service main loop...")
        
        cycle_count = 0
        while not self.shutdown_event.is_set():
            try:
                cycle_count += 1
                self.logger.debug(f"Starting processing cycle {cycle_count}")
                
                # Run processing cycle
                stats = await self.run_single_cycle()
                
                # Wait for next cycle or shutdown
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=self.scan_interval
                    )
                    # If we get here, shutdown was requested
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue to next cycle
                    continue
                    
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {e}")
                # Wait a bit before retrying to avoid tight error loops
                await asyncio.sleep(60)
        
        self.logger.info("Watcher Service main loop stopped")
    
    async def shutdown(self):
        """Graceful shutdown of the service"""
        self.logger.info("Shutting down Watcher Service...")
        
        try:
            if self.db_manager:
                await self.db_manager.close()
                self.logger.info("Database connection closed")
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
        
        self.logger.info("Watcher Service shutdown completed")


async def main():
    """Main entry point"""
    # Setup logging
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper())
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/app/logs/watcher.log') if os.path.exists('/app/logs') else logging.NullHandler()
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Starting BluRay Converter Watcher Service")
    
    # Check if this is a one-time scan or service mode
    run_once = os.getenv("RUN_ONCE", "false").lower() == "true"
    
    # Create and initialize service
    service = WatcherService()
    
    try:
        # Initialize service
        if not await service.initialize():
            logger.error("Failed to initialize service")
            sys.exit(1)
        
        if run_once:
            # Run single cycle and exit
            logger.info("Running in one-time scan mode")
            stats = await service.run_single_cycle()
            logger.info(f"One-time scan completed: {stats}")
        else:
            # Run as continuous service
            logger.info("Running in service mode")
            await service.run_service()
    
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        # Cleanup
        await service.shutdown()
        logger.info("BluRay Converter Watcher Service stopped")


if __name__ == "__main__":
    asyncio.run(main())