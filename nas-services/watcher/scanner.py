#!/usr/bin/env python3
"""
BluRay Converter - Directory Scanner
Logic for scanning BluRay directories and detecting new movies
"""

import os
import logging
from typing import List, Dict, Optional, Set
from pathlib import Path
from db_manager import DatabaseManager, TaskStatus
import hashlib


class BluRayScanner:
    """
    Scans directories for BluRay movies and manages processing tasks.
    
    This scanner looks for BDMV directory structures that indicate
    a BluRay disc has been copied to the file system.
    """
    
    def __init__(self, db_manager: DatabaseManager, movies_base_path: str):
        self.db_manager = db_manager
        self.movies_base_path = movies_base_path
        self.logger = logging.getLogger(__name__)
        
        # Get folder names from environment or use defaults
        self.raw_folder = os.getenv('BLURAY_RAW_FOLDER', 'BluRayRAW')
        self.processed_folder = os.getenv('BLURAY_PROCESSED_FOLDER', 'BluRayProcessed')
        self.temp_folder = os.getenv('BLURAY_TEMP_FOLDER', 'BluRayTemp')
        
        # Construct full paths
        self.raw_path = os.path.join(movies_base_path, self.raw_folder)
        self.processed_path = os.path.join(movies_base_path, self.processed_folder)
        self.temp_path = os.path.join(movies_base_path, self.temp_folder)
        
        self.mock_mode = os.getenv('MOCK_MODE', 'false').lower() == 'true'
        self.dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
        
        self._ensure_directories_exist()
    
    def _ensure_directories_exist(self):
        """Ensure all required directories exist."""
        directories = [self.raw_path, self.processed_path, self.temp_path]
        
        for directory in directories:
            if not os.path.exists(directory):
                if not self.dry_run:
                    try:
                        os.makedirs(directory, exist_ok=True)
                        self.logger.info(f"Created directory: {directory}")
                    except OSError as e:
                        self.logger.error(f"Failed to create directory {directory}: {e}")
                        raise
                else:
                    self.logger.info(f"DRY RUN: Would create directory: {directory}")
    
    def is_valid_bluray_structure(self, movie_path: str) -> bool:
        """
        Check if a directory contains a valid BluRay structure.
        
        Args:
            movie_path: Path to the movie directory
            
        Returns:
            True if valid BluRay structure is found
        """
        try:
            bdmv_path = os.path.join(movie_path, 'BDMV')
            if not os.path.isdir(bdmv_path):
                return False
            
            # Check for required subdirectories
            required_dirs = ['PLAYLIST', 'STREAM']
            for req_dir in required_dirs:
                if not os.path.isdir(os.path.join(bdmv_path, req_dir)):
                    self.logger.debug(f"Missing required directory: {req_dir} in {movie_path}")
                    return False
            
            # Check for playlist files
            playlist_dir = os.path.join(bdmv_path, 'PLAYLIST')
            playlist_files = [f for f in os.listdir(playlist_dir) if f.endswith('.mpls')]
            
            if not playlist_files:
                self.logger.debug(f"No playlist files found in {playlist_dir}")
                return False
            
            # Check for stream files
            stream_dir = os.path.join(bdmv_path, 'STREAM')
            stream_files = [f for f in os.listdir(stream_dir) if f.endswith('.m2ts')]
            
            if not stream_files:
                self.logger.debug(f"No stream files found in {stream_dir}")
                return False
            
            self.logger.debug(f"Valid BluRay structure found: {movie_path}")
            return True
            
        except OSError as e:
            self.logger.error(f"Error checking BluRay structure for {movie_path}: {e}")
            return False
    
    def get_movie_info(self, movie_path: str) -> Dict[str, any]:
        """
        Extract basic information about a BluRay movie.
        
        Args:
            movie_path: Path to the movie directory
            
        Returns:
            Dictionary with movie information
        """
        movie_name = os.path.basename(movie_path)
        
        info = {
            'name': movie_name,
            'path': movie_path,
            'size_bytes': 0,
            'playlist_count': 0,
            'stream_count': 0,
            'estimated_duration': 0
        }
        
        try:
            # Calculate total size
            total_size = 0
            for root, dirs, files in os.walk(movie_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)
                    except OSError:
                        pass  # Skip files we can't access
            
            info['size_bytes'] = total_size
            
            # Count playlists and streams
            bdmv_path = os.path.join(movie_path, 'BDMV')
            
            playlist_dir = os.path.join(bdmv_path, 'PLAYLIST')
            if os.path.exists(playlist_dir):
                playlist_files = [f for f in os.listdir(playlist_dir) if f.endswith('.mpls')]
                info['playlist_count'] = len(playlist_files)
            
            stream_dir = os.path.join(bdmv_path, 'STREAM')
            if os.path.exists(stream_dir):
                stream_files = [f for f in os.listdir(stream_dir) if f.endswith('.m2ts')]
                info['stream_count'] = len(stream_files)
            
            self.logger.debug(f"Movie info for {movie_name}: {info}")
            
        except OSError as e:
            self.logger.error(f"Error getting movie info for {movie_path}: {e}")
        
        return info
    
    def is_movie_already_processed(self, movie_name: str) -> bool:
        """
        Check if a movie has already been processed or is in progress.
        
        Args:
            movie_name: Name of the movie
            
        Returns:
            True if movie should be skipped
        """
        try:
            # Check if task already exists in database
            all_tasks = self.db_manager.get_all_tasks()
            for task in all_tasks:
                if task['movie_name'] == movie_name:
                    status = task['status']
                    if status in [TaskStatus.COMPLETED, TaskStatus.PROCESSING, TaskStatus.SENT]:
                        self.logger.debug(f"Movie {movie_name} already processed or in progress: {status}")
                        return True
                    elif status == TaskStatus.FAILED:
                        attempts = task.get('attempts', 0)
                        max_attempts = int(os.getenv('MAX_RETRY_ATTEMPTS', '3'))
                        if attempts >= max_attempts:
                            self.logger.debug(f"Movie {movie_name} failed too many times ({attempts})")
                            return True
                        else:
                            self.logger.debug(f"Movie {movie_name} can be retried ({attempts}/{max_attempts})")
                            return False
            
            # Check if processed file already exists
            processed_file_candidates = [
                os.path.join(self.processed_path, f"{movie_name}.mkv"),
                os.path.join(self.processed_path, f"{movie_name}.mp4"),  # Alternative format
            ]
            
            for processed_file in processed_file_candidates:
                if os.path.exists(processed_file):
                    self.logger.debug(f"Processed file already exists: {processed_file}")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking if movie is processed: {e}")
            return False  # Err on the side of processing if we can't determine
    
    def scan_for_new_movies(self) -> List[Dict[str, any]]:
        """
        Scan the raw directory for new BluRay movies.
        
        Returns:
            List of new movie information dictionaries
        """
        new_movies = []
        
        if not os.path.exists(self.raw_path):
            self.logger.warning(f"Raw movies directory does not exist: {self.raw_path}")
            return new_movies
        
        try:
            self.logger.info(f"Scanning for new movies in: {self.raw_path}")
            
            # List all items in the raw directory
            items = os.listdir(self.raw_path)
            self.logger.debug(f"Found {len(items)} items in raw directory")
            
            for item in items:
                item_path = os.path.join(self.raw_path, item)
                
                # Skip non-directories
                if not os.path.isdir(item_path):
                    self.logger.debug(f"Skipping non-directory: {item}")
                    continue
                
                # Skip hidden directories
                if item.startswith('.'):
                    self.logger.debug(f"Skipping hidden directory: {item}")
                    continue
                
                # Check if it's a valid BluRay structure
                if not self.is_valid_bluray_structure(item_path):
                    self.logger.debug(f"Not a valid BluRay structure: {item}")
                    continue
                
                # Check if already processed
                if self.is_movie_already_processed(item):
                    self.logger.debug(f"Movie already processed: {item}")
                    continue
                
                # Get movie information
                movie_info = self.get_movie_info(item_path)
                new_movies.append(movie_info)
                
                self.logger.info(f"Found new movie: {item} ({movie_info['size_bytes'] / 1024 / 1024 / 1024:.1f} GB)")
            
            self.logger.info(f"Scan complete: found {len(new_movies)} new movies")
            return new_movies
            
        except OSError as e:
            self.logger.error(f"Error scanning directory {self.raw_path}: {e}")
            return []
    
    def create_tasks_for_movies(self, movies: List[Dict[str, any]]) -> int:
        """
        Create database tasks for new movies.
        
        Args:
            movies: List of movie information dictionaries
            
        Returns:
            Number of tasks created
        """
        tasks_created = 0
        
        for movie in movies:
            try:
                movie_name = movie['name']
                movie_path = movie['path']
                
                # Determine priority based on file size (larger files get lower priority)
                size_gb = movie['size_bytes'] / (1024 ** 3)
                if size_gb > 50:
                    priority = 1  # Large files - lower priority
                elif size_gb > 25:
                    priority = 5  # Medium files - normal priority
                else:
                    priority = 10  # Small files - higher priority
                
                if self.dry_run:
                    self.logger.info(f"DRY RUN: Would create task for {movie_name} (priority: {priority})")
                    tasks_created += 1
                else:
                    task_id = self.db_manager.create_task(
                        movie_name=movie_name,
                        source_path=movie_path,
                        priority=priority
                    )
                    tasks_created += 1
                    self.logger.info(f"Created task {task_id} for movie: {movie_name}")
                
            except ValueError as e:
                self.logger.warning(f"Task creation failed for {movie['name']}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error creating task for {movie['name']}: {e}")
        
        return tasks_created
    
    def full_scan(self) -> Dict[str, any]:
        """
        Perform a complete scan and create tasks for new movies.
        
        Returns:
            Scan results summary
        """
        self.logger.info("Starting full directory scan")
        
        try:
            # Scan for new movies
            new_movies = self.scan_for_new_movies()
            
            # Create tasks for new movies
            tasks_created = self.create_tasks_for_movies(new_movies)
            
            # Get current statistics
            stats = self.db_manager.get_statistics()
            
            scan_results = {
                'movies_found': len(new_movies),
                'tasks_created': tasks_created,
                'scan_timestamp': os.path.getmtime(__file__),  # Use current time approximation
                'raw_directory': self.raw_path,
                'current_stats': stats,
                'dry_run': self.dry_run,
                'mock_mode': self.mock_mode
            }
            
            self.logger.info(f"Scan complete: {tasks_created} new tasks created from {len(new_movies)} movies")
            return scan_results
            
        except Exception as e:
            self.logger.error(f"Error during full scan: {e}")
            raise


def create_scanner(db_manager: DatabaseManager) -> BluRayScanner:
    """
    Factory function to create a BluRayScanner instance.
    
    Args:
        db_manager: Database manager instance
        
    Returns:
        Configured BluRayScanner instance
    """
    movies_base_path = os.getenv('MOVIES_BASE_PATH', '/movies')
    
    if not os.path.exists(movies_base_path):
        logging.warning(f"Movies base path does not exist: {movies_base_path}")
    
    return BluRayScanner(db_manager, movies_base_path)