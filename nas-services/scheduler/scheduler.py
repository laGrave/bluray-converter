#!/usr/bin/env python3
"""
BluRay Converter - Планировщик задач
Управление cron задачами на основе APScheduler для автоматического сканирования
"""

import os
import sys
import logging
import asyncio
from datetime import datetime
from typing import Optional

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/logs/scheduler.log')
    ]
)
logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Сервис для управления запланированными задачами, такими как автоматическое сканирование директорий
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.api_base_url = f"http://{os.getenv('NAS_IP', 'localhost')}:{os.getenv('NAS_PORT', '8080')}/api"
        self.scan_schedule = os.getenv('SCAN_SCHEDULE', '0 3 * * *')  # По умолчанию: 3 утра ежедневно
        self.enabled = os.getenv('SCHEDULER_ENABLED', 'true').lower() == 'true'
        
    async def scan_directory_task(self):
        """
        Запланированная задача для запуска сканирования директорий
        """
        try:
            logger.info("Запуск запланированного сканирования директорий")
            
            # Вызов API NAS для запуска сканирования
            response = requests.post(
                f"{self.api_base_url}/tasks/scan",
                json={"source": "scheduler", "priority": 0},
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Сканирование завершено успешно: {result.get('message', 'Нет сообщения')}")
                if result.get('new_tasks'):
                    logger.info(f"Найдено {result['new_tasks']} новых BluRay фильмов для обработки")
            else:
                logger.error(f"Сканирование завершилось с ошибкой {response.status_code}: {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Не удалось запустить сканирование - API недоступен: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка во время запланированного сканирования: {e}")
    
    async def cleanup_database_task(self):
        """
        Запланированная задача для очистки старых записей базы данных
        """
        try:
            logger.info("Starting scheduled database cleanup")
            
            # Call the NAS API to trigger database cleanup
            response = requests.post(
                f"{self.api_base_url}/maintenance/cleanup",
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Database cleanup completed: {result.get('message', 'No message')}")
            else:
                logger.warning(f"Database cleanup failed with status {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to trigger database cleanup - API not available: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during database cleanup: {e}")
    
    async def health_check_task(self):
        """
        Regular health check of all system components
        """
        try:
            # Check NAS API health
            nas_response = requests.get(f"{self.api_base_url}/health", timeout=10)
            nas_healthy = nas_response.status_code == 200
            
            # Check Mac mini health
            mac_ip = os.getenv('MAC_MINI_IP', 'localhost')
            mac_port = os.getenv('MAC_MINI_PORT', '8000')
            try:
                mac_response = requests.get(f"http://{mac_ip}:{mac_port}/api/health", timeout=10)
                mac_healthy = mac_response.status_code == 200
            except:
                mac_healthy = False
            
            if nas_healthy and mac_healthy:
                logger.debug("Health check passed - all services healthy")
            else:
                logger.warning(f"Health check issues - NAS: {'OK' if nas_healthy else 'FAIL'}, Mac: {'OK' if mac_healthy else 'FAIL'}")
                
        except Exception as e:
            logger.error(f"Health check failed: {e}")
    
    def job_listener(self, event):
        """
        Event listener for job execution events
        """
        if event.exception:
            logger.error(f"Job {event.job_id} crashed: {event.exception}")
        else:
            logger.debug(f"Job {event.job_id} executed successfully")
    
    async def start(self):
        """
        Start the scheduler with all configured jobs
        """
        if not self.enabled:
            logger.info("Scheduler is disabled via configuration")
            return
        
        logger.info("Starting BluRay Converter Scheduler")
        logger.info(f"Scan schedule: {self.scan_schedule}")
        logger.info(f"API endpoint: {self.api_base_url}")
        
        # Add job event listener
        self.scheduler.add_listener(self.job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        
        # Add scheduled jobs
        self.scheduler.add_job(
            self.scan_directory_task,
            CronTrigger.from_crontab(self.scan_schedule),
            id='directory_scan',
            name='BluRay Directory Scanner',
            replace_existing=True,
            max_instances=1
        )
        
        # Database cleanup - weekly at 2 AM on Sunday
        self.scheduler.add_job(
            self.cleanup_database_task,
            CronTrigger(day_of_week=0, hour=2, minute=0),
            id='database_cleanup',
            name='Database Cleanup',
            replace_existing=True,
            max_instances=1
        )
        
        # Health check - every 15 minutes
        self.scheduler.add_job(
            self.health_check_task,
            CronTrigger(minute='*/15'),
            id='health_check',
            name='System Health Check',
            replace_existing=True
        )
        
        # Start the scheduler
        self.scheduler.start()
        logger.info("Scheduler started successfully")
        
        # Print next run times
        for job in self.scheduler.get_jobs():
            logger.info(f"Job '{job.name}' next run: {job.next_run_time}")
    
    async def stop(self):
        """
        Stop the scheduler gracefully
        """
        logger.info("Stopping scheduler...")
        self.scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")


async def main():
    """
    Main entry point for the scheduler service
    """
    # Validate environment variables
    required_env_vars = ['NAS_IP', 'NAS_PORT']
    missing_vars = []
    
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)
    
    # Create and start scheduler
    scheduler_service = SchedulerService()
    
    try:
        await scheduler_service.start()
        
        # Keep the service running
        logger.info("Scheduler is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(60)  # Check every minute
            
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
    finally:
        await scheduler_service.stop()


if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    os.makedirs('/app/logs', exist_ok=True)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scheduler terminated by user")