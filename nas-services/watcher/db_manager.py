#!/usr/bin/env python3
"""
BluRay Converter - Database Manager
SQLite database operations for task management
"""

import sqlite3
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from contextlib import contextmanager
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class DatabaseManager:
    """
    Manages SQLite database operations for BluRay converter system.
    Handles tasks, processing history, errors, and statistics.
    """
    
    def __init__(self, db_path: str = "/app/data/bluray_converter.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._ensure_database_directory()
        self._initialize_database()
    
    def _ensure_database_directory(self):
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            self.logger.info(f"Created database directory: {db_dir}")
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections with proper error handling."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row  # Enable column access by name
            conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
            yield conn
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def _initialize_database(self):
        """Initialize database schema with all required tables."""
        try:
            with self.get_connection() as conn:
                self._create_tasks_table(conn)
                self._create_processing_history_table(conn)
                self._create_errors_table(conn)
                self._create_statistics_table(conn)
                conn.commit()
                self.logger.info("Database initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            raise
    
    def _create_tasks_table(self, conn: sqlite3.Connection):
        """Create the main tasks table."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_name TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processing_started_at TIMESTAMP,
                processing_completed_at TIMESTAMP,
                error_message TEXT,
                file_size_bytes INTEGER,
                processing_time_seconds INTEGER,
                mac_worker_id TEXT,
                CHECK (status IN ('pending', 'sent', 'processing', 'completed', 'failed', 'retrying'))
            )
        """)
        
        # Create indexes for better performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC)")
    
    def _create_processing_history_table(self, conn: sqlite3.Connection):
        """Create processing history table for completed tasks."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                movie_name TEXT NOT NULL,
                original_path TEXT NOT NULL,
                output_path TEXT,
                file_size_mb REAL,
                processing_time_minutes REAL,
                compression_ratio REAL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                mac_worker_id TEXT,
                ffmpeg_version TEXT,
                success BOOLEAN DEFAULT 1,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        """)
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_completed_at ON processing_history(completed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_movie_name ON processing_history(movie_name)")
    
    def _create_errors_table(self, conn: sqlite3.Connection):
        """Create errors table for detailed error logging."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                error_details TEXT,
                stack_trace TEXT,
                occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved BOOLEAN DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        """)
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_occurred_at ON errors(occurred_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_resolved ON errors(resolved)")
    
    def _create_statistics_table(self, conn: sqlite3.Connection):
        """Create statistics table for monthly summaries."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                total_processed INTEGER DEFAULT 0,
                total_failed INTEGER DEFAULT 0,
                total_size_gb REAL DEFAULT 0,
                avg_processing_time_minutes REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(year, month)
            )
        """)
    
    def create_task(self, movie_name: str, source_path: str, priority: int = 0) -> int:
        """
        Create a new processing task.
        
        Args:
            movie_name: Name of the movie
            source_path: Path to the source BluRay directory
            priority: Task priority (higher = more important)
            
        Returns:
            Task ID of the created task
            
        Raises:
            ValueError: If task already exists
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    INSERT INTO tasks (movie_name, source_path, priority, status)
                    VALUES (?, ?, ?, ?)
                """, (movie_name, source_path, priority, TaskStatus.PENDING))
                
                task_id = cursor.lastrowid
                conn.commit()
                
                self.logger.info(f"Created task {task_id} for movie: {movie_name}")
                return task_id
                
        except sqlite3.IntegrityError:
            raise ValueError(f"Task for movie '{movie_name}' already exists")
        except Exception as e:
            self.logger.error(f"Failed to create task for {movie_name}: {e}")
            raise
    
    def get_pending_tasks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get pending tasks ordered by priority and creation time.
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of task dictionaries
        """
        try:
            with self.get_connection() as conn:
                query = """
                    SELECT * FROM tasks 
                    WHERE status = 'pending' 
                    ORDER BY priority DESC, created_at ASC
                """
                
                if limit:
                    query += f" LIMIT {limit}"
                
                cursor = conn.execute(query)
                tasks = [dict(row) for row in cursor.fetchall()]
                
                self.logger.debug(f"Retrieved {len(tasks)} pending tasks")
                return tasks
                
        except Exception as e:
            self.logger.error(f"Failed to get pending tasks: {e}")
            raise
    
    def update_task_status(self, task_id: int, status: TaskStatus, 
                          error_message: Optional[str] = None,
                          processing_time: Optional[int] = None,
                          file_size: Optional[int] = None,
                          mac_worker_id: Optional[str] = None) -> bool:
        """
        Update task status and related fields.
        
        Args:
            task_id: Task ID to update
            status: New status
            error_message: Error message if failed
            processing_time: Processing time in seconds
            file_size: File size in bytes
            mac_worker_id: ID of the Mac worker processing this task
            
        Returns:
            True if update was successful
        """
        try:
            with self.get_connection() as conn:
                now = datetime.now()
                
                # Prepare update fields
                fields = ["status = ?", "updated_at = ?"]
                values = [status, now]
                
                if error_message:
                    fields.append("error_message = ?")
                    values.append(error_message)
                
                if processing_time is not None:
                    fields.append("processing_time_seconds = ?")
                    values.append(processing_time)
                
                if file_size is not None:
                    fields.append("file_size_bytes = ?")
                    values.append(file_size)
                
                if mac_worker_id:
                    fields.append("mac_worker_id = ?")
                    values.append(mac_worker_id)
                
                # Set processing timestamps based on status
                if status == TaskStatus.PROCESSING:
                    fields.append("processing_started_at = ?")
                    values.append(now)
                elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    fields.append("processing_completed_at = ?")
                    values.append(now)
                
                # Increment attempts for retry scenarios
                if status == TaskStatus.RETRYING:
                    fields.append("attempts = attempts + 1")
                
                values.append(task_id)
                
                query = f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?"
                cursor = conn.execute(query, values)
                
                if cursor.rowcount == 0:
                    self.logger.warning(f"No task found with ID {task_id}")
                    return False
                
                conn.commit()
                self.logger.info(f"Updated task {task_id} to status: {status}")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to update task {task_id}: {e}")
            raise
    
    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get task by ID."""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
                
        except Exception as e:
            self.logger.error(f"Failed to get task {task_id}: {e}")
            raise
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks for web UI display."""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM tasks 
                    ORDER BY priority DESC, created_at DESC
                """)
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            self.logger.error(f"Failed to get all tasks: {e}")
            raise
    
    def delete_task(self, task_id: int) -> bool:
        """Delete a task and its related records."""
        try:
            with self.get_connection() as conn:
                # Delete related errors first
                conn.execute("DELETE FROM errors WHERE task_id = ?", (task_id,))
                
                # Delete the task
                cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                
                if cursor.rowcount == 0:
                    return False
                
                conn.commit()
                self.logger.info(f"Deleted task {task_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to delete task {task_id}: {e}")
            raise
    
    def log_error(self, task_id: Optional[int], error_type: str, 
                  error_message: str, error_details: Optional[str] = None,
                  stack_trace: Optional[str] = None):
        """Log an error to the errors table."""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO errors (task_id, error_type, error_message, error_details, stack_trace)
                    VALUES (?, ?, ?, ?, ?)
                """, (task_id, error_type, error_message, error_details, stack_trace))
                
                conn.commit()
                self.logger.debug(f"Logged error for task {task_id}: {error_type}")
                
        except Exception as e:
            self.logger.error(f"Failed to log error: {e}")
    
    def add_to_processing_history(self, task_id: int, movie_name: str,
                                 original_path: str, output_path: str,
                                 file_size_mb: float, processing_time_minutes: float,
                                 mac_worker_id: str, success: bool = True):
        """Add completed task to processing history."""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO processing_history 
                    (task_id, movie_name, original_path, output_path, file_size_mb, 
                     processing_time_minutes, mac_worker_id, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (task_id, movie_name, original_path, output_path, file_size_mb,
                      processing_time_minutes, mac_worker_id, success))
                
                conn.commit()
                self.logger.info(f"Added processing history for task {task_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to add processing history: {e}")
    
    def cleanup_old_records(self, days: int = 60):
        """Clean up old records to prevent database bloat."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with self.get_connection() as conn:
                # Clean up old completed/failed tasks
                cursor = conn.execute("""
                    DELETE FROM tasks 
                    WHERE status IN ('completed', 'failed') 
                    AND updated_at < ?
                """, (cutoff_date,))
                
                tasks_deleted = cursor.rowcount
                
                # Clean up old resolved errors
                cursor = conn.execute("""
                    DELETE FROM errors 
                    WHERE resolved = 1 AND occurred_at < ?
                """, (cutoff_date,))
                
                errors_deleted = cursor.rowcount
                
                conn.commit()
                
                self.logger.info(f"Cleanup: deleted {tasks_deleted} old tasks, {errors_deleted} old errors")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup old records: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        try:
            with self.get_connection() as conn:
                # Current task counts
                cursor = conn.execute("""
                    SELECT status, COUNT(*) as count 
                    FROM tasks 
                    GROUP BY status
                """)
                status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
                
                # Processing history stats
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_processed,
                        AVG(processing_time_minutes) as avg_time,
                        SUM(file_size_mb) as total_size
                    FROM processing_history 
                    WHERE completed_at > datetime('now', '-30 days')
                """)
                
                history_stats = dict(cursor.fetchone())
                
                return {
                    'task_counts': status_counts,
                    'recent_stats': history_stats,
                    'last_updated': datetime.now().isoformat()
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get statistics: {e}")
            raise


# Convenience function for getting database manager instance
def get_db_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """Get a DatabaseManager instance with optional custom path."""
    if db_path is None:
        db_path = os.getenv('DATABASE_PATH', '/app/data/bluray_converter.db')
    
    return DatabaseManager(db_path)