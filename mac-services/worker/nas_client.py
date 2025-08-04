#!/usr/bin/env python3
"""
BluRay Converter - NAS Client
Client for sending status updates back to NAS API
"""

import os
import asyncio
import logging
import httpx
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class StatusUpdate:
    """Status update payload for NAS"""
    task_id: int
    status: str
    source_folder: Optional[str] = None
    temp_file: Optional[str] = None
    processing_time: Optional[float] = None
    file_size_mb: Optional[float] = None
    error: Optional[str] = None
    progress_percent: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Remove None values
        return {k: v for k, v in data.items() if v is not None}


class NASClient:
    """Client for communicating with NAS API webhooks"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Configuration from environment
        self.nas_ip = os.getenv("NAS_IP", "192.168.1.50")
        self.nas_port = int(os.getenv("NAS_API_PORT", "8080"))
        self.timeout = int(os.getenv("NAS_CLIENT_TIMEOUT", "30"))
        self.retry_attempts = int(os.getenv("NAS_CLIENT_RETRY_ATTEMPTS", "3"))
        self.retry_delay = int(os.getenv("NAS_CLIENT_RETRY_DELAY", "5"))
        
        # Base URL for NAS API
        self.base_url = f"http://{self.nas_ip}:{self.nas_port}/api"
        self.webhook_url = f"{self.base_url}/webhook/status"
        
        # Mock mode for testing
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
        
    async def send_status_update(self, update: StatusUpdate) -> bool:
        """
        Send status update to NAS webhook
        
        Args:
            update: Status update information
            
        Returns:
            True if successfully sent, False otherwise
        """
        for attempt in range(1, self.retry_attempts + 1):
            try:
                self.logger.info(f"Sending status update for task {update.task_id}: {update.status} "
                               f"(attempt {attempt}/{self.retry_attempts})")
                
                if self.mock_mode:
                    self.logger.info(f"[MOCK] Status update sent: {update.to_dict()}")
                    return True
                
                # Prepare payload
                payload = update.to_dict()
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.webhook_url,
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 200:
                        self.logger.info(f"Status update sent successfully for task {update.task_id}")
                        return True
                    else:
                        error_msg = f"NAS returned HTTP {response.status_code}: {response.text}"
                        self.logger.error(error_msg)
                        
                        # Don't retry on client errors (4xx)
                        if 400 <= response.status_code < 500:
                            self.logger.error(f"Client error, not retrying: {error_msg}")
                            return False
                        
                        raise Exception(error_msg)
                        
            except httpx.ConnectTimeout:
                error_msg = f"Timeout connecting to NAS (attempt {attempt})"
                self.logger.error(error_msg)
            except httpx.ConnectError as e:
                error_msg = f"Connection error to NAS (attempt {attempt}): {e}"
                self.logger.error(error_msg)
            except Exception as e:
                error_msg = f"Error sending status update (attempt {attempt}): {e}"
                self.logger.error(error_msg)
            
            # If not the last attempt, wait before retrying
            if attempt < self.retry_attempts:
                self.logger.info(f"Waiting {self.retry_delay}s before retry...")
                await asyncio.sleep(self.retry_delay)
        
        # All retry attempts failed
        self.logger.error(f"Failed to send status update for task {update.task_id} after {self.retry_attempts} attempts")
        return False
    
    async def send_task_started(self, task_id: int, source_folder: str) -> bool:
        """Send task started notification"""
        update = StatusUpdate(
            task_id=task_id,
            status=TaskStatus.PROCESSING.value,
            source_folder=source_folder
        )
        return await self.send_status_update(update)
    
    async def send_task_progress(self, task_id: int, progress_percent: float) -> bool:
        """Send task progress update"""
        update = StatusUpdate(
            task_id=task_id,
            status=TaskStatus.PROCESSING.value,
            progress_percent=progress_percent
        )
        return await self.send_status_update(update)
    
    async def send_task_completed(
        self,
        task_id: int,
        source_folder: str,
        temp_file: str,
        processing_time: float,
        file_size_mb: float
    ) -> bool:
        """Send task completion notification"""
        update = StatusUpdate(
            task_id=task_id,
            status=TaskStatus.COMPLETED.value,
            source_folder=source_folder,
            temp_file=temp_file,
            processing_time=processing_time,
            file_size_mb=file_size_mb
        )
        return await self.send_status_update(update)
    
    async def send_task_failed(
        self,
        task_id: int,
        source_folder: str,
        error: str,
        processing_time: Optional[float] = None
    ) -> bool:
        """Send task failure notification"""
        update = StatusUpdate(
            task_id=task_id,
            status=TaskStatus.FAILED.value,
            source_folder=source_folder,
            error=error,
            processing_time=processing_time
        )
        return await self.send_status_update(update)
    
    async def health_check(self) -> bool:
        """Check if NAS API is reachable"""
        try:
            if self.mock_mode:
                self.logger.info("[MOCK] NAS health check - OK")
                return True
            
            health_url = f"{self.base_url}/health"
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(health_url)
                
                if response.status_code == 200:
                    self.logger.debug("NAS health check successful")
                    return True
                else:
                    self.logger.warning(f"NAS health check failed: HTTP {response.status_code}")
                    return False
                    
        except httpx.ConnectTimeout:
            self.logger.error(f"NAS health check timeout after {self.timeout}s")
            return False
        except httpx.ConnectError as e:
            self.logger.error(f"NAS connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"NAS health check error: {e}")
            return False
    
    async def notify_worker_startup(self) -> bool:
        """Notify NAS that worker is starting up"""
        try:
            if self.mock_mode:
                self.logger.info("[MOCK] Worker startup notification sent")
                return True
            
            startup_url = f"{self.base_url}/worker/startup"
            payload = {
                "worker_id": os.getenv("HOSTNAME", "mac-worker"),
                "timestamp": asyncio.get_event_loop().time()
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(startup_url, json=payload)
                
                if response.status_code in [200, 201, 204]:
                    self.logger.info("Worker startup notification sent successfully")
                    return True
                else:
                    self.logger.warning(f"Worker startup notification failed: HTTP {response.status_code}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error sending worker startup notification: {e}")
            return False
    
    async def notify_worker_shutdown(self) -> bool:
        """Notify NAS that worker is shutting down"""
        try:
            if self.mock_mode:
                self.logger.info("[MOCK] Worker shutdown notification sent")
                return True
            
            shutdown_url = f"{self.base_url}/worker/shutdown"
            payload = {
                "worker_id": os.getenv("HOSTNAME", "mac-worker"),
                "timestamp": asyncio.get_event_loop().time()
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(shutdown_url, json=payload)
                
                if response.status_code in [200, 201, 204]:
                    self.logger.info("Worker shutdown notification sent successfully")
                    return True
                else:
                    self.logger.warning(f"Worker shutdown notification failed: HTTP {response.status_code}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error sending worker shutdown notification: {e}")
            return False
    
    def validate_config(self) -> bool:
        """Validate that all required configuration is present"""
        required_vars = [
            ("NAS_IP", self.nas_ip),
        ]
        
        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value:
                missing_vars.append(var_name)
        
        if missing_vars:
            self.logger.error(f"Missing required configuration variables: {missing_vars}")
            return False
        
        self.logger.info("NAS client configuration validated successfully")
        return True


# Factory function for creating NASClient instance
def create_nas_client() -> NASClient:
    """Create and validate NAS client instance"""
    client = NASClient()
    
    if not client.validate_config():
        raise ValueError("NAS client configuration validation failed")
    
    return client


# Integration helper class
class TaskStatusReporter:
    """Helper class to simplify task status reporting"""
    
    def __init__(self, nas_client: NASClient):
        self.nas_client = nas_client
        self.logger = logging.getLogger(__name__)
    
    async def report_task_lifecycle(
        self,
        task_id: int,
        source_folder: str,
        success: bool,
        processing_time: float,
        temp_file: Optional[str] = None,
        file_size_mb: Optional[float] = None,
        error: Optional[str] = None
    ) -> bool:
        """Report complete task lifecycle in one call"""
        
        # Send started notification
        started_ok = await self.nas_client.send_task_started(task_id, source_folder)
        
        if not started_ok:
            self.logger.warning(f"Failed to send task started notification for {task_id}")
        
        # Send completion or failure notification
        if success and temp_file and file_size_mb:
            completed_ok = await self.nas_client.send_task_completed(
                task_id, source_folder, temp_file, processing_time, file_size_mb
            )
            return started_ok and completed_ok
        else:
            failed_ok = await self.nas_client.send_task_failed(
                task_id, source_folder, error or "Unknown error", processing_time
            )
            return started_ok and failed_ok


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    async def main():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        try:
            # Create client
            client = create_nas_client()
            
            # Test health check
            is_healthy = await client.health_check()
            print(f"NAS health: {is_healthy}")
            
            if len(sys.argv) > 1:
                task_id = int(sys.argv[1])
                
                # Test status updates
                print("Testing status updates...")
                
                # Start processing
                await client.send_task_started(task_id, "TestMovie")
                await asyncio.sleep(1)
                
                # Progress updates
                for progress in [25, 50, 75]:
                    await client.send_task_progress(task_id, progress)
                    await asyncio.sleep(0.5)
                
                # Complete
                await client.send_task_completed(
                    task_id=task_id,
                    source_folder="TestMovie",
                    temp_file="TestMovie_02h15m30s.mkv",
                    processing_time=2700.5,
                    file_size_mb=23000.0
                )
                
                print("Status updates completed")
            else:
                print("Usage: python nas_client.py [task_id]")
                print("Example: python nas_client.py 123")
        
        except Exception as e:
            print(f"Error: {e}")
    
    asyncio.run(main())