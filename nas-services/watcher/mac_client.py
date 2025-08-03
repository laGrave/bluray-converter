#!/usr/bin/env python3
"""
BluRay Converter - Mac Client
Client for sending processing tasks to Mac mini worker
"""

import os
import logging
import asyncio
import httpx
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

class TaskStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"

@dataclass
class ProcessingTask:
    """Task data structure for Mac processing"""
    task_id: int
    movie_name: str
    source_path: str
    priority: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "movie_name": self.movie_name,
            "source_path": self.source_path,
            "priority": self.priority
        }

class MacClient:
    """Client for communicating with Mac mini worker service"""
    
    def __init__(self):
        # Configuration from environment variables
        self.mac_ip = os.getenv("MAC_MINI_IP", "192.168.1.100")
        self.mac_port = int(os.getenv("MAC_MINI_PORT", "8000"))
        self.nas_ip = os.getenv("NAS_IP", "192.168.1.50")
        self.nas_port = int(os.getenv("NAS_PORT", "8080"))
        self.timeout = int(os.getenv("MAC_CLIENT_TIMEOUT", "30"))
        self.retry_attempts = int(os.getenv("MAC_CLIENT_RETRY_ATTEMPTS", "3"))
        self.retry_delay = int(os.getenv("MAC_CLIENT_RETRY_DELAY", "5"))
        
        # Base URLs
        self.mac_base_url = f"http://{self.mac_ip}:{self.mac_port}/api"
        self.nas_webhook_url = f"http://{self.nas_ip}:{self.nas_port}/api/webhook"
        
        # Mock mode for testing
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
    async def health_check(self) -> bool:
        """Check if Mac mini worker is available and healthy"""
        try:
            if self.mock_mode:
                self.logger.info("[MOCK] Mac mini health check - OK")
                return True
                
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.mac_base_url}/health")
                
                if response.status_code == 200:
                    health_data = response.json()
                    self.logger.info(f"Mac mini health check successful: {health_data}")
                    return True
                else:
                    self.logger.warning(f"Mac mini health check failed: HTTP {response.status_code}")
                    return False
                    
        except httpx.ConnectTimeout:
            self.logger.error(f"Mac mini health check timeout after {self.timeout}s")
            return False
        except httpx.ConnectError as e:
            self.logger.error(f"Mac mini connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Mac mini health check error: {e}")
            return False
    
    async def send_task(self, task: ProcessingTask) -> bool:
        """Send processing task to Mac mini worker with retry logic"""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                self.logger.info(f"Sending task {task.task_id} to Mac mini (attempt {attempt}/{self.retry_attempts})")
                
                if self.mock_mode:
                    self.logger.info(f"[MOCK] Sent task {task.task_id} to Mac mini: {task.movie_name}")
                    return True
                
                # First check if Mac is available
                if not await self.health_check():
                    raise Exception("Mac mini is not available")
                
                # Prepare task payload
                payload = {
                    **task.to_dict(),
                    "nas_webhook_url": f"{self.nas_webhook_url}/status",
                    "nas_ip": self.nas_ip,
                    "smb_config": {
                        "username": os.getenv("SMB_USERNAME"),
                        "share_name": os.getenv("SMB_SHARE_NAME", "video"),
                        "movies_base_path": os.getenv("MOVIES_BASE_PATH", "/volume1/video/Кино"),
                        "bluray_raw_folder": os.getenv("BLURAY_RAW_FOLDER", "BluRayRAW"),
                        "bluray_temp_folder": os.getenv("BLURAY_TEMP_FOLDER", "BluRayTemp")
                    }
                }
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.mac_base_url}/process",
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        self.logger.info(f"Task {task.task_id} successfully sent to Mac mini: {result}")
                        return True
                    elif response.status_code == 429:
                        # Mac is busy with another task
                        error_msg = f"Mac mini is busy processing another task"
                        self.logger.warning(error_msg)
                        return False
                    else:
                        error_msg = f"Mac mini returned HTTP {response.status_code}: {response.text}"
                        self.logger.error(error_msg)
                        raise Exception(error_msg)
                        
            except httpx.ConnectTimeout:
                error_msg = f"Timeout connecting to Mac mini (attempt {attempt})"
                self.logger.error(error_msg)
            except httpx.ConnectError as e:
                error_msg = f"Connection error to Mac mini (attempt {attempt}): {e}"
                self.logger.error(error_msg)
            except Exception as e:
                error_msg = f"Error sending task to Mac mini (attempt {attempt}): {e}"
                self.logger.error(error_msg)
            
            # If not the last attempt, wait before retrying
            if attempt < self.retry_attempts:
                self.logger.info(f"Waiting {self.retry_delay}s before retry...")
                await asyncio.sleep(self.retry_delay)
        
        # All retry attempts failed
        self.logger.error(f"Failed to send task {task.task_id} to Mac mini after {self.retry_attempts} attempts")
        return False
    
    async def get_task_status(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get current status of a task being processed on Mac mini"""
        try:
            if self.mock_mode:
                mock_status = {
                    "task_id": task_id,
                    "status": "processing",
                    "progress": 45.0,
                    "estimated_time_remaining": 1800
                }
                self.logger.info(f"[MOCK] Task {task_id} status: {mock_status}")
                return mock_status
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.mac_base_url}/status/{task_id}")
                
                if response.status_code == 200:
                    status_data = response.json()
                    self.logger.debug(f"Task {task_id} status: {status_data}")
                    return status_data
                elif response.status_code == 404:
                    self.logger.warning(f"Task {task_id} not found on Mac mini")
                    return None
                else:
                    self.logger.error(f"Error getting task status: HTTP {response.status_code}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting task {task_id} status: {e}")
            return None
    
    async def cancel_task(self, task_id: int) -> bool:
        """Cancel a task currently being processed on Mac mini"""
        try:
            if self.mock_mode:
                self.logger.info(f"[MOCK] Cancelled task {task_id} on Mac mini")
                return True
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(f"{self.mac_base_url}/process/{task_id}")
                
                if response.status_code == 200:
                    self.logger.info(f"Task {task_id} cancelled on Mac mini")
                    return True
                elif response.status_code == 404:
                    self.logger.warning(f"Task {task_id} not found for cancellation")
                    return False
                else:
                    self.logger.error(f"Error cancelling task: HTTP {response.status_code}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error cancelling task {task_id}: {e}")
            return False
    
    def validate_config(self) -> bool:
        """Validate that all required configuration is present"""
        required_vars = [
            ("MAC_MINI_IP", self.mac_ip),
            ("SMB_USERNAME", os.getenv("SMB_USERNAME")),
            ("MOVIES_BASE_PATH", os.getenv("MOVIES_BASE_PATH"))
        ]
        
        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value:
                missing_vars.append(var_name)
        
        if missing_vars:
            self.logger.error(f"Missing required configuration variables: {missing_vars}")
            return False
        
        self.logger.info("Mac client configuration validated successfully")
        return True


# Factory function for creating MacClient instance
def create_mac_client() -> MacClient:
    """Create and validate Mac client instance"""
    client = MacClient()
    
    if not client.validate_config():
        raise ValueError("Mac client configuration validation failed")
    
    return client


# Example usage for testing
async def main():
    """Example usage of MacClient"""
    import logging
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create client
    try:
        client = create_mac_client()
        
        # Test health check
        is_healthy = await client.health_check()
        print(f"Mac mini health: {is_healthy}")
        
        if is_healthy or client.mock_mode:
            # Test sending a task
            test_task = ProcessingTask(
                task_id=1,
                movie_name="Test Movie",
                source_path="/volume1/video/Кино/BluRayRAW/TestMovie",
                priority=1
            )
            
            success = await client.send_task(test_task)
            print(f"Task sent successfully: {success}")
            
            if success:
                # Test getting status
                status = await client.get_task_status(test_task.task_id)
                print(f"Task status: {status}")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())