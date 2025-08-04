#!/usr/bin/env python3
"""
BluRay Converter - File Manager
Handles file operations and directory management
"""

import os
import shutil
import logging
import asyncio
from typing import Optional, List, Tuple
from pathlib import Path
from datetime import datetime


class FileManager:
    """Manages file operations for BluRay conversion process"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Configuration from environment
        self.movies_base_path = os.getenv("MOVIES_BASE_PATH", "/volume1/video/Кино")
        self.bluray_raw_folder = os.getenv("BLURAY_RAW_FOLDER", "BluRayRAW")
        self.bluray_processed_folder = os.getenv("BLURAY_PROCESSED_FOLDER", "BluRayProcessed")
        self.bluray_temp_folder = os.getenv("BLURAY_TEMP_FOLDER", "BluRayTemp")
        
        # Options
        self.delete_source_after_success = os.getenv("DELETE_SOURCE_AFTER_SUCCESS", "true").lower() == "true"
        self.create_movie_subfolders = os.getenv("CREATE_MOVIE_SUBFOLDERS", "false").lower() == "true"
        
        # Mock mode for testing
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
        
        # Construct full paths
        self.raw_path = os.path.join(self.movies_base_path, self.bluray_raw_folder)
        self.processed_path = os.path.join(self.movies_base_path, self.bluray_processed_folder)
        self.temp_path = os.path.join(self.movies_base_path, self.bluray_temp_folder)
        
        # Initialize directories
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure all required directories exist"""
        try:
            for path in [self.raw_path, self.processed_path, self.temp_path]:
                if not self.mock_mode:
                    Path(path).mkdir(parents=True, exist_ok=True)
                    self.logger.debug(f"Ensured directory exists: {path}")
        except Exception as e:
            self.logger.error(f"Error creating directories: {e}")
    
    async def move_to_processed(self, temp_file: str, source_folder: str) -> bool:
        """
        Move completed file from temp to processed folder
        
        Args:
            temp_file: Filename in temp folder
            source_folder: Original source folder name (for subfolder creation)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Construct paths
            temp_file_path = os.path.join(self.temp_path, temp_file)
            
            # Determine destination path
            if self.create_movie_subfolders:
                # Create subfolder for each movie
                dest_folder = os.path.join(self.processed_path, source_folder)
                if not self.mock_mode:
                    Path(dest_folder).mkdir(parents=True, exist_ok=True)
                dest_file_path = os.path.join(dest_folder, temp_file)
            else:
                # Place all files directly in processed folder
                dest_file_path = os.path.join(self.processed_path, temp_file)
            
            self.logger.info(f"Moving file: {temp_file_path} -> {dest_file_path}")
            
            if self.mock_mode:
                self.logger.info(f"[MOCK] File moved successfully")
                return True
            
            # Check if source file exists
            if not os.path.exists(temp_file_path):
                self.logger.error(f"Source file not found: {temp_file_path}")
                return False
            
            # Check if destination already exists
            if os.path.exists(dest_file_path):
                # Rename with timestamp to avoid overwrite
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base, ext = os.path.splitext(temp_file)
                new_filename = f"{base}_{timestamp}{ext}"
                
                if self.create_movie_subfolders:
                    dest_file_path = os.path.join(dest_folder, new_filename)
                else:
                    dest_file_path = os.path.join(self.processed_path, new_filename)
                
                self.logger.warning(f"Destination exists, renaming to: {new_filename}")
            
            # Move file atomically (same filesystem)
            try:
                shutil.move(temp_file_path, dest_file_path)
                self.logger.info(f"File moved successfully: {temp_file} -> {dest_file_path}")
                return True
            except Exception as move_error:
                # If atomic move fails, try copy and delete
                self.logger.warning(f"Atomic move failed: {move_error}, trying copy+delete")
                
                try:
                    shutil.copy2(temp_file_path, dest_file_path)
                    os.remove(temp_file_path)
                    self.logger.info(f"File copied and source deleted successfully")
                    return True
                except Exception as copy_error:
                    self.logger.error(f"Copy+delete also failed: {copy_error}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error moving file to processed: {e}")
            return False
    
    async def delete_source_folder(self, folder_name: str) -> bool:
        """
        Delete source folder from raw directory
        
        Args:
            folder_name: Name of the folder to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            source_path = os.path.join(self.raw_path, folder_name)
            
            self.logger.info(f"Deleting source folder: {source_path}")
            
            if self.mock_mode:
                self.logger.info(f"[MOCK] Source folder deleted")
                return True
            
            if not os.path.exists(source_path):
                self.logger.warning(f"Source folder not found: {source_path}")
                return True  # Consider it success if already gone
            
            # Remove directory and all contents
            shutil.rmtree(source_path)
            self.logger.info(f"Source folder deleted successfully: {folder_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting source folder: {e}")
            return False
    
    async def cleanup_temp_files(self, older_than_hours: int = 24) -> int:
        """
        Clean up old files in temp directory
        
        Args:
            older_than_hours: Delete files older than this many hours
            
        Returns:
            Number of files deleted
        """
        try:
            if self.mock_mode:
                self.logger.info(f"[MOCK] Cleaned up 5 old temp files")
                return 5
            
            import time
            current_time = time.time()
            cutoff_time = current_time - (older_than_hours * 3600)
            
            deleted_count = 0
            temp_dir = Path(self.temp_path)
            
            if not temp_dir.exists():
                return 0
            
            for file_path in temp_dir.glob("*.mkv"):
                try:
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        self.logger.debug(f"Deleted old temp file: {file_path}")
                except Exception as e:
                    self.logger.warning(f"Could not delete {file_path}: {e}")
            
            self.logger.info(f"Cleaned up {deleted_count} old temp files")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error during temp cleanup: {e}")
            return 0
    
    async def get_folder_stats(self) -> dict:
        """Get statistics about folders"""
        try:
            stats = {
                "raw_count": 0,
                "raw_size_gb": 0.0,
                "processed_count": 0,
                "processed_size_gb": 0.0,
                "temp_count": 0,
                "temp_size_gb": 0.0
            }
            
            if self.mock_mode:
                return {
                    "raw_count": 5,
                    "raw_size_gb": 125.5,
                    "processed_count": 42,
                    "processed_size_gb": 950.2,
                    "temp_count": 2,
                    "temp_size_gb": 46.8
                }
            
            # Count and size for each folder
            for folder_type, folder_path in [
                ("raw", self.raw_path),
                ("processed", self.processed_path),
                ("temp", self.temp_path)
            ]:
                if os.path.exists(folder_path):
                    count = 0
                    total_size = 0
                    
                    for item in Path(folder_path).iterdir():
                        if item.is_dir() and folder_type == "raw":
                            # Count folders in raw
                            count += 1
                            # Calculate folder size
                            total_size += sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        elif item.is_file() and item.suffix == ".mkv":
                            # Count MKV files in processed/temp
                            count += 1
                            total_size += item.stat().st_size
                    
                    stats[f"{folder_type}_count"] = count
                    stats[f"{folder_type}_size_gb"] = total_size / (1024 ** 3)
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting folder stats: {e}")
            return {}
    
    async def verify_paths(self) -> dict:
        """Verify all configured paths are accessible"""
        results = {}
        
        for name, path in [
            ("raw", self.raw_path),
            ("processed", self.processed_path),
            ("temp", self.temp_path)
        ]:
            if self.mock_mode:
                results[name] = {"exists": True, "writable": True}
            else:
                exists = os.path.exists(path)
                writable = os.access(path, os.W_OK) if exists else False
                
                results[name] = {
                    "exists": exists,
                    "writable": writable,
                    "path": path
                }
        
        return results
    
    def get_temp_file_path(self, filename: str) -> str:
        """Get full path for a file in temp directory"""
        return os.path.join(self.temp_path, filename)
    
    def get_processed_file_path(self, filename: str, movie_name: Optional[str] = None) -> str:
        """Get full path for a file in processed directory"""
        if self.create_movie_subfolders and movie_name:
            return os.path.join(self.processed_path, movie_name, filename)
        else:
            return os.path.join(self.processed_path, filename)
    
    async def list_raw_folders(self) -> List[str]:
        """List all folders in raw directory"""
        try:
            if self.mock_mode:
                return ["Movie1", "Movie2", "Movie3"]
            
            if not os.path.exists(self.raw_path):
                return []
            
            folders = []
            for item in Path(self.raw_path).iterdir():
                if item.is_dir():
                    folders.append(item.name)
            
            return sorted(folders)
            
        except Exception as e:
            self.logger.error(f"Error listing raw folders: {e}")
            return []
    
    async def get_folder_info(self, folder_name: str) -> Optional[dict]:
        """Get detailed information about a specific folder"""
        try:
            folder_path = os.path.join(self.raw_path, folder_name)
            
            if self.mock_mode:
                return {
                    "name": folder_name,
                    "path": folder_path,
                    "size_gb": 25.5,
                    "has_bdmv": True,
                    "created": datetime.now().isoformat(),
                    "file_count": 1234
                }
            
            if not os.path.exists(folder_path):
                return None
            
            # Get folder statistics
            stat = os.stat(folder_path)
            
            # Check for BDMV structure
            has_bdmv = os.path.exists(os.path.join(folder_path, "BDMV"))
            
            # Calculate total size
            total_size = sum(f.stat().st_size for f in Path(folder_path).rglob("*") if f.is_file())
            file_count = sum(1 for f in Path(folder_path).rglob("*") if f.is_file())
            
            return {
                "name": folder_name,
                "path": folder_path,
                "size_gb": total_size / (1024 ** 3),
                "has_bdmv": has_bdmv,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "file_count": file_count
            }
            
        except Exception as e:
            self.logger.error(f"Error getting folder info: {e}")
            return None


# Factory function
def create_file_manager() -> FileManager:
    """Create and configure file manager instance"""
    return FileManager()


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def test_file_manager():
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Create manager
        manager = create_file_manager()
        
        # Test path verification
        print("Path verification:")
        paths = await manager.verify_paths()
        for name, info in paths.items():
            print(f"  {name}: {info}")
        
        # Test folder stats
        print("\nFolder statistics:")
        stats = await manager.get_folder_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        # Test listing raw folders
        print("\nRaw folders:")
        folders = await manager.list_raw_folders()
        for folder in folders:
            print(f"  - {folder}")
        
        # Test cleanup
        print("\nTemp cleanup:")
        cleaned = await manager.cleanup_temp_files(older_than_hours=24)
        print(f"  Cleaned {cleaned} files")
    
    asyncio.run(test_file_manager())