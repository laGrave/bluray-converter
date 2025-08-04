#!/usr/bin/env python3
"""
BluRay Converter - NAS API Service Main Entry Point
FastAPI server for task management and system control
"""

import os
import sys
import asyncio
import logging
import signal
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.db_manager import DatabaseManager, create_database_manager
from watcher.scanner import BluRayScanner, create_bluray_scanner
from routes import router as api_router, setup_routes
from webhook import router as webhook_router, setup_webhook
from file_manager import create_file_manager
from telegram_bot import create_telegram_notifier


# Global application state
class AppState:
    def __init__(self):
        self.db_manager: Optional[DatabaseManager] = None
        self.scanner: Optional[BluRayScanner] = None
        self.file_manager = None
        self.telegram = None
        self.shutdown_event = asyncio.Event()


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger = logging.getLogger(__name__)
    
    try:
        # Startup
        logger.info("Starting BluRay Converter NAS API Service")
        
        # Initialize database
        app_state.db_manager = create_database_manager()
        await app_state.db_manager.initialize()
        logger.info("Database initialized")
        
        # Initialize scanner
        app_state.scanner = create_bluray_scanner(app_state.db_manager)
        logger.info("Scanner initialized")
        
        # Initialize file manager
        app_state.file_manager = create_file_manager()
        logger.info("File manager initialized")
        
        # Initialize Telegram notifier (optional)
        try:
            app_state.telegram = create_telegram_notifier()
            if app_state.telegram:
                logger.info("Telegram notifier initialized")
        except Exception as telegram_error:
            logger.warning(f"Telegram initialization failed: {telegram_error}")
            app_state.telegram = None
        
        # Setup route dependencies
        setup_routes(
            database_manager=app_state.db_manager,
            bluray_scanner=app_state.scanner,
            telegram_notifier=app_state.telegram
        )
        
        # Setup webhook dependencies
        setup_webhook(
            database_manager=app_state.db_manager,
            file_manager_instance=app_state.file_manager,
            telegram_notifier=app_state.telegram
        )
        
        # Setup signal handlers
        setup_signal_handlers()
        
        logger.info("NAS API Service startup completed")
        
        yield
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    finally:
        # Shutdown
        logger.info("Shutting down NAS API Service")
        
        # Close database connections
        if app_state.db_manager:
            await app_state.db_manager.close()
        
        logger.info("NAS API Service shutdown completed")


# Initialize FastAPI app
app = FastAPI(
    title="BluRay Converter API",
    description="NAS API service for BluRay to MKV conversion management",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router)
app.include_router(webhook_router)


def setup_signal_handlers():
    """Setup graceful shutdown signal handlers"""
    def signal_handler(signum, frame):
        logger = logging.getLogger(__name__)
        logger.info(f"Received signal {signum}, initiating shutdown...")
        app_state.shutdown_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint - redirect to web UI or API docs"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>BluRay Converter API</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 50px; }
            .container { max-width: 600px; margin: 0 auto; }
            .link { display: block; margin: 10px 0; padding: 10px; 
                   background: #f0f0f0; text-decoration: none; color: #333; 
                   border-radius: 5px; }
            .link:hover { background: #e0e0e0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>BluRay Converter API</h1>
            <p>Welcome to the BluRay Converter management system.</p>
            
            <h2>Available Services:</h2>
            <a href="/docs" class="link">📖 API Documentation (Swagger)</a>
            <a href="/redoc" class="link">📚 API Documentation (ReDoc)</a>
            <a href="/api/health" class="link">💚 Health Check</a>
            <a href="/api/tasks" class="link">📋 Task List</a>
            <a href="/api/statistics" class="link">📊 Statistics</a>
            
            <h2>Quick Actions:</h2>
            <p>To scan for new movies: <code>POST /api/tasks/scan</code></p>
            <p>To view system logs: <code>GET /api/logs</code></p>
            
            <h2>System Information:</h2>
            <p><strong>Version:</strong> 1.0.0</p>
            <p><strong>Environment:</strong> NAS API Service</p>
        </div>
    </body>
    </html>
    """


@app.get("/api/info")
async def get_system_info():
    """Get system information"""
    return {
        "service": "BluRay Converter NAS API",
        "version": "1.0.0",
        "environment": {
            "python_version": sys.version,
            "working_directory": os.getcwd(),
            "platform": sys.platform
        },
        "configuration": {
            "mock_mode": os.getenv("MOCK_MODE", "false").lower() == "true",
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "movies_base_path": os.getenv("MOVIES_BASE_PATH", "/volume1/video/Кино"),
            "telegram_enabled": app_state.telegram is not None,
            "database_path": os.getenv("DATABASE_PATH", "/app/data/bluray_converter.db")
        },
        "endpoints": {
            "api_docs": "/docs",
            "health_check": "/api/health",
            "tasks": "/api/tasks",
            "statistics": "/api/statistics",
            "webhooks": "/api/webhook"
        }
    }


# Mount static files for web UI (if directory exists)
static_dir = os.path.join(os.path.dirname(__file__), "..", "web-ui")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return {
        "detail": f"Internal server error: {str(exc)}",
        "type": "internal_error"
    }


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
            logging.FileHandler('/app/logs/api.log') if os.path.exists('/app/logs') else logging.NullHandler()
        ]
    )
    
    # Reduce verbosity of some loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


if __name__ == "__main__":
    # This will only run when called directly (not with uvicorn)
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("Starting BluRay Converter NAS API Service (direct mode)")
    
    import uvicorn
    
    # Configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))
    workers = int(os.getenv("API_WORKERS", "1"))
    
    # Run server
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=workers,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=True,
        reload=os.getenv("RELOAD", "false").lower() == "true"
    )