#!/usr/bin/env python3
"""
BluRay Converter - Telegram Bot
Telegram notifications and bot commands for system status updates
"""

import os
import sys
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

import httpx
from pydantic import BaseModel


class TelegramConfig(BaseModel):
    """Telegram bot configuration"""
    bot_token: str
    chat_id: str
    enabled: bool = True
    timeout: int = 30
    retry_attempts: int = 3


class TelegramMessage(BaseModel):
    """Telegram message structure"""
    text: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = True


class TelegramNotifier:
    """Handles Telegram notifications for BluRay converter"""
    
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.api_url = f"https://api.telegram.org/bot{config.bot_token}"
        
        # HTTP client for requests
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout),
            limits=httpx.Limits(max_connections=5)
        )
        
        self.logger.info(f"Telegram notifier initialized for chat {config.chat_id}")
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send message to configured chat
        
        Args:
            text: Message text
            parse_mode: Telegram parse mode (HTML, Markdown, None)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.config.enabled:
            self.logger.debug("Telegram notifications disabled")
            return True
        
        try:
            message = TelegramMessage(
                text=text,
                parse_mode=parse_mode
            )
            
            # Attempt to send with retries
            for attempt in range(self.config.retry_attempts):
                try:
                    success = await self._send_message_attempt(message)
                    if success:
                        return True
                    
                    if attempt < self.config.retry_attempts - 1:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        
                except Exception as e:
                    self.logger.warning(f"Send attempt {attempt + 1} failed: {e}")
                    if attempt < self.config.retry_attempts - 1:
                        await asyncio.sleep(2 ** attempt)
            
            self.logger.error(f"Failed to send message after {self.config.retry_attempts} attempts")
            return False
            
        except Exception as e:
            self.logger.error(f"Error sending Telegram message: {e}")
            return False
    
    async def _send_message_attempt(self, message: TelegramMessage) -> bool:
        """Single attempt to send message"""
        try:
            payload = {
                "chat_id": self.config.chat_id,
                "text": message.text,
                "parse_mode": message.parse_mode,
                "disable_web_page_preview": message.disable_web_page_preview
            }
            
            response = await self.client.post(
                f"{self.api_url}/sendMessage",
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    self.logger.debug("Message sent successfully")
                    return True
                else:
                    self.logger.error(f"Telegram API error: {result.get('description')}")
                    return False
            else:
                self.logger.error(f"HTTP error {response.status_code}: {response.text}")
                return False
                
        except httpx.TimeoutException:
            self.logger.warning("Request timeout")
            return False
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            return False
    
    async def send_system_startup(self) -> bool:
        """Send system startup notification"""
        message = (
            "🟢 <b>BluRay Converter Started</b>\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "🏠 System ready for processing"
        )
        return await self.send_message(message)
    
    async def send_system_shutdown(self) -> bool:
        """Send system shutdown notification"""
        message = (
            "🔴 <b>BluRay Converter Shutdown</b>\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "💤 System offline"
        )
        return await self.send_message(message)
    
    async def send_scan_started(self) -> bool:
        """Send scan started notification"""
        message = (
            "🔍 <b>Scan Started</b>\n"
            "Searching for new BluRay movies..."
        )
        return await self.send_message(message)
    
    async def send_scan_completed(self, movies_found: int, tasks_created: int) -> bool:
        """Send scan completion notification"""
        if movies_found > 0:
            message = (
                f"✅ <b>Scan Completed</b>\n"
                f"📀 Found: {movies_found} movies\n"
                f"📝 Created: {tasks_created} tasks\n"
                "🚀 Processing will begin shortly"
            )
        else:
            message = (
                "✅ <b>Scan Completed</b>\n"
                "No new movies found"
            )
        
        return await self.send_message(message)
    
    async def send_task_started(self, movie_name: str, task_id: int) -> bool:
        """Send task processing started notification"""
        message = (
            f"⏳ <b>Processing Started</b>\n"
            f"🎬 Movie: {movie_name}\n"
            f"🆔 Task: {task_id}\n"
            "Converting BluRay to MKV..."
        )
        return await self.send_message(message)
    
    async def send_task_progress(self, movie_name: str, progress_percent: float) -> bool:
        """Send task progress notification (for milestones)"""
        if progress_percent in [25, 50, 75]:
            progress_bar = "█" * int(progress_percent // 10) + "░" * (10 - int(progress_percent // 10))
            message = (
                f"⏳ <b>Processing {movie_name}</b>\n"
                f"📊 Progress: {progress_percent:.0f}%\n"
                f"▓{progress_bar}▓"
            )
            return await self.send_message(message)
        return True
    
    async def send_task_completed(
        self,
        movie_name: str,
        task_id: int,
        processing_time_minutes: float = 0,
        file_size_gb: float = 0
    ) -> bool:
        """Send task completion notification"""
        message = (
            f"✅ <b>Completed: {movie_name}</b>\n"
            f"🆔 Task: {task_id}\n"
        )
        
        if processing_time_minutes > 0:
            message += f"⏱ Time: {processing_time_minutes:.1f} minutes\n"
        
        if file_size_gb > 0:
            message += f"💾 Size: {file_size_gb:.1f} GB\n"
        
        message += "📁 Location: BluRayProcessed"
        
        return await self.send_message(message)
    
    async def send_task_failed(
        self,
        movie_name: str,
        task_id: int,
        error: str,
        will_retry: bool = False
    ) -> bool:
        """Send task failure notification"""
        message = (
            f"❌ <b>Failed: {movie_name}</b>\n"
            f"🆔 Task: {task_id}\n"
            f"⚠️ Error: {error[:100]}{'...' if len(error) > 100 else ''}\n"
        )
        
        if will_retry:
            message += "🔄 Will retry automatically"
        else:
            message += "⛔ No more retries"
        
        return await self.send_message(message)
    
    async def send_worker_status(self, worker_id: str, status: str) -> bool:
        """Send worker status notification"""
        status_emoji = {
            "online": "🟢",
            "offline": "🔴",
            "busy": "🟡",
            "idle": "⚪"
        }.get(status, "⚫")
        
        message = (
            f"{status_emoji} <b>Worker {status.title()}</b>\n"
            f"🖥 ID: {worker_id}\n"
            f"📅 Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        return await self.send_message(message)
    
    async def send_statistics(self, stats: Dict[str, Any]) -> bool:
        """Send system statistics"""
        message = (
            "📊 <b>System Statistics</b>\n"
            f"📋 Total Tasks: {stats.get('total_tasks', 0)}\n"
            f"✅ Completed: {stats.get('completed_tasks', 0)}\n"
            f"❌ Failed: {stats.get('failed_tasks', 0)}\n"
            f"⏳ Pending: {stats.get('pending_tasks', 0)}\n"
            f"📈 Success Rate: {stats.get('success_rate', 0):.1f}%\n"
            f"💾 Processed: {stats.get('total_processed_size_gb', 0):.1f} GB"
        )
        
        return await self.send_message(message)
    
    async def send_error(self, error_type: str, error_message: str) -> bool:
        """Send system error notification"""
        message = (
            f"🚨 <b>System Error</b>\n"
            f"🔴 Type: {error_type}\n"
            f"📝 Message: {error_message[:200]}{'...' if len(error_message) > 200 else ''}\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        return await self.send_message(message)
    
    async def send_disk_space_warning(self, location: str, used_percent: float) -> bool:
        """Send disk space warning"""
        message = (
            f"⚠️ <b>Disk Space Warning</b>\n"
            f"📁 Location: {location}\n"
            f"📊 Used: {used_percent:.1f}%\n"
            "Consider cleaning up old files"
        )
        
        return await self.send_message(message)
    
    async def test_connection(self) -> bool:
        """Test Telegram bot connection"""
        try:
            if not self.config.enabled:
                self.logger.info("Telegram disabled - test skipped")
                return True
            
            response = await self.client.get(f"{self.api_url}/getMe")
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    bot_info = result.get("result", {})
                    self.logger.info(f"Telegram bot connected: {bot_info.get('username')}")
                    return True
            
            self.logger.error("Telegram bot connection test failed")
            return False
            
        except Exception as e:
            self.logger.error(f"Telegram connection test error: {e}")
            return False
    
    async def close(self):
        """Close HTTP client"""
        try:
            await self.client.aclose()
        except Exception as e:
            self.logger.warning(f"Error closing Telegram client: {e}")


def create_telegram_notifier() -> Optional[TelegramNotifier]:
    """
    Create Telegram notifier from environment variables
    
    Returns:
        TelegramNotifier instance or None if not configured
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        logging.getLogger(__name__).info("Telegram not configured (missing token or chat_id)")
        return None
    
    try:
        config = TelegramConfig(
            bot_token=bot_token,
            chat_id=chat_id,
            enabled=os.getenv("TELEGRAM_ENABLED", "true").lower() == "true",
            timeout=int(os.getenv("TELEGRAM_TIMEOUT", "30")),
            retry_attempts=int(os.getenv("TELEGRAM_RETRY_ATTEMPTS", "3"))
        )
        
        return TelegramNotifier(config)
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to create Telegram notifier: {e}")
        return None


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    
    async def test_telegram():
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Create notifier
        notifier = create_telegram_notifier()
        
        if not notifier:
            print("❌ Telegram not configured")
            return
        
        print("Testing Telegram notifications...")
        
        # Test connection
        if await notifier.test_connection():
            print("✅ Connection test passed")
        else:
            print("❌ Connection test failed")
            return
        
        # Test notifications
        await notifier.send_system_startup()
        await asyncio.sleep(1)
        
        await notifier.send_scan_started()
        await asyncio.sleep(1)
        
        await notifier.send_scan_completed(movies_found=3, tasks_created=3)
        await asyncio.sleep(1)
        
        await notifier.send_task_started("Test Movie", 1)
        await asyncio.sleep(1)
        
        await notifier.send_task_progress("Test Movie", 50)
        await asyncio.sleep(1)
        
        await notifier.send_task_completed("Test Movie", 1, 15.5, 8.2)
        await asyncio.sleep(1)
        
        await notifier.send_statistics({
            "total_tasks": 10,
            "completed_tasks": 8,
            "failed_tasks": 2,
            "pending_tasks": 0,
            "success_rate": 80.0,
            "total_processed_size_gb": 85.5
        })
        
        print("✅ Test notifications sent")
        
        # Cleanup
        await notifier.close()
    
    asyncio.run(test_telegram())