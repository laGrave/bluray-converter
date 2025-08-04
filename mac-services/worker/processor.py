#!/usr/bin/env python3
"""
BluRay Converter - Video Processor
Main logic for BluRay to MKV conversion processing
"""

import os
import asyncio
import logging
import shutil
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from bdmv_analyzer import BDMVAnalyzer, BDMVAnalysisResult
from ffmpeg_wrapper import FFmpegWrapper, ConversionResult, ConversionProgress


@dataclass
class ProcessingTask:
    """Task data structure for processing"""
    task_id: int
    movie_name: str
    source_path: str
    priority: int = 0
    nas_webhook_url: Optional[str] = None
    nas_ip: Optional[str] = None
    smb_config: Optional[Dict[str, Any]] = None


@dataclass
class ProcessingResult:
    """Result of processing task"""
    task_id: int
    success: bool
    output_file: Optional[str] = None
    temp_file: Optional[str] = None
    processing_time_seconds: float = 0.0
    input_size_mb: float = 0.0
    output_size_mb: float = 0.0
    error_message: Optional[str] = None
    bdmv_analysis: Optional[BDMVAnalysisResult] = None
    conversion_result: Optional[ConversionResult] = None


class VideoProcessor:
    """Main video processing coordinator"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.mount_point = os.getenv("MOUNT_POINT", "/mnt/nas")
        self.temp_dir = os.getenv("TEMP_DIR", "/tmp/bluray_processing")
        self.smb_username = os.getenv("SMB_USERNAME")
        self.smb_password = os.getenv("SMB_PASSWORD")
        
        # Processing state
        self.current_task: Optional[ProcessingTask] = None
        self.is_processing = False
        self.progress_callback: Optional[Callable[[int, ConversionProgress], None]] = None
        
        # Components
        self.bdmv_analyzer = BDMVAnalyzer()
        self.ffmpeg_wrapper = FFmpegWrapper()
        
        # Mock mode
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
        
        # Setup progress callback for FFmpeg
        self.ffmpeg_wrapper.set_progress_callback(self._on_conversion_progress)
        
        # Ensure temp directory exists
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
    
    def set_progress_callback(self, callback: Callable[[int, ConversionProgress], None]):
        """Set callback for progress updates"""
        self.progress_callback = callback
    
    def _on_conversion_progress(self, progress: ConversionProgress):
        """Handle FFmpeg progress updates"""
        if self.progress_callback and self.current_task:
            self.progress_callback(self.current_task.task_id, progress)
    
    async def process_task(self, task: ProcessingTask) -> ProcessingResult:
        """
        Process a single BluRay conversion task
        
        Args:
            task: Processing task information
            
        Returns:
            ProcessingResult with processing information
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            self.logger.info(f"Starting processing task {task.task_id}: {task.movie_name}")
            
            # Set current task
            self.current_task = task
            self.is_processing = True
            
            if self.mock_mode:
                return await self._mock_processing(task, start_time)
            
            # Step 1: Mount NAS if needed
            if not await self._ensure_nas_mounted(task):
                raise Exception("Failed to mount NAS")
            
            # Step 2: Validate source path
            source_bdmv_path = await self._validate_source_path(task)
            if not source_bdmv_path:
                raise Exception(f"Invalid source path: {task.source_path}")
            
            # Step 3: Analyze BDMV structure
            self.logger.info(f"Analyzing BDMV structure: {source_bdmv_path}")
            bdmv_analysis = self.bdmv_analyzer.analyze_bdmv_structure(source_bdmv_path)
            
            if not bdmv_analysis.is_valid:
                raise Exception(f"Invalid BDMV structure: {bdmv_analysis.error_message}")
            
            self.logger.info(f"BDMV analysis completed: Main playlist {bdmv_analysis.main_playlist.playlist_id} "
                           f"({bdmv_analysis.main_duration_formatted})")
            
            # Step 4: Prepare output paths
            temp_output_path = await self._prepare_output_path(task, bdmv_analysis)
            
            # Step 5: Convert video
            self.logger.info(f"Starting video conversion: {source_bdmv_path} -> {temp_output_path}")
            
            conversion_result = await self.ffmpeg_wrapper.convert_bluray_to_mkv(
                input_path=source_bdmv_path,
                output_path=temp_output_path,
                playlist_path=bdmv_analysis.main_playlist.file_path
            )
            
            if not conversion_result.success:
                raise Exception(f"Video conversion failed: {conversion_result.error_message}")
            
            self.logger.info(f"Video conversion completed: {temp_output_path}")
            self.logger.info(f"Processing time: {conversion_result.processing_time_seconds:.1f}s, "
                           f"Size: {conversion_result.input_size_mb:.1f}MB -> {conversion_result.output_size_mb:.1f}MB")
            
            # Step 6: Verify output file
            if not os.path.exists(temp_output_path):
                raise Exception("Output file was not created")
            
            output_size_mb = os.path.getsize(temp_output_path) / (1024 * 1024)
            if output_size_mb < 100:  # Minimum reasonable size for a movie
                raise Exception(f"Output file too small: {output_size_mb:.1f}MB")
            
            # Step 7: Prepare final result
            processing_time = asyncio.get_event_loop().time() - start_time
            
            result = ProcessingResult(
                task_id=task.task_id,
                success=True,
                output_file=os.path.basename(temp_output_path),
                temp_file=os.path.basename(temp_output_path),
                processing_time_seconds=processing_time,
                input_size_mb=conversion_result.input_size_mb,
                output_size_mb=conversion_result.output_size_mb,
                bdmv_analysis=bdmv_analysis,
                conversion_result=conversion_result
            )
            
            self.logger.info(f"Task {task.task_id} completed successfully")
            return result
            
        except Exception as e:
            processing_time = asyncio.get_event_loop().time() - start_time
            error_msg = str(e)
            
            self.logger.error(f"Task {task.task_id} failed: {error_msg}")
            
            return ProcessingResult(
                task_id=task.task_id,
                success=False,
                processing_time_seconds=processing_time,
                error_message=error_msg
            )
        
        finally:
            # Cleanup
            self.current_task = None
            self.is_processing = False
    
    async def _ensure_nas_mounted(self, task: ProcessingTask) -> bool:
        """Ensure NAS is mounted via SMB"""
        try:
            if self.mock_mode:
                self.logger.info("[MOCK] NAS mounted successfully")
                return True
            
            # Check if already mounted
            if os.path.ismount(self.mount_point):
                self.logger.debug("NAS already mounted")
                return True
            
            # Extract SMB configuration
            smb_config = task.smb_config or {}
            nas_ip = task.nas_ip or smb_config.get("nas_ip")
            username = smb_config.get("username", self.smb_username)
            share_name = smb_config.get("share_name", "video")
            
            if not all([nas_ip, username, self.smb_password]):
                self.logger.error("Missing SMB configuration for mounting")
                return False
            
            # Create mount point
            Path(self.mount_point).mkdir(parents=True, exist_ok=True)
            
            # Mount command for macOS
            mount_cmd = [
                "mount",
                "-t", "smbfs",
                f"//{username}:{self.smb_password}@{nas_ip}/{share_name}",
                self.mount_point
            ]
            
            self.logger.info(f"Mounting NAS: //{username}@{nas_ip}/{share_name} -> {self.mount_point}")
            
            result = await asyncio.create_subprocess_exec(
                *mount_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                self.logger.info("NAS mounted successfully")
                return True
            else:
                error_msg = stderr.decode() if stderr else "Unknown mount error"
                self.logger.error(f"Failed to mount NAS: {error_msg}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error mounting NAS: {e}")
            return False
    
    async def _validate_source_path(self, task: ProcessingTask) -> Optional[str]:
        """Validate and construct source BDMV path"""
        try:
            # Extract path components from task
            smb_config = task.smb_config or {}
            movies_base_path = smb_config.get("movies_base_path", "/volume1/video/Кино")
            bluray_raw_folder = smb_config.get("bluray_raw_folder", "BluRayRAW")
            
            # Construct paths
            if self.mock_mode:
                # In mock mode, use a simulated path
                source_path = f"/mock{movies_base_path}/{bluray_raw_folder}/{task.movie_name}"
                bdmv_path = f"{source_path}/BDMV"
            else:
                # Real path through mount point
                nas_base_path = os.path.join(self.mount_point, movies_base_path.lstrip("/"))
                source_path = os.path.join(nas_base_path, bluray_raw_folder, task.movie_name)
                bdmv_path = os.path.join(source_path, "BDMV")
            
            self.logger.debug(f"Checking source path: {bdmv_path}")
            
            if self.mock_mode or os.path.exists(bdmv_path):
                self.logger.info(f"Source path validated: {bdmv_path}")
                return bdmv_path
            else:
                self.logger.error(f"Source path not found: {bdmv_path}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error validating source path: {e}")
            return None
    
    async def _prepare_output_path(self, task: ProcessingTask, bdmv_analysis: BDMVAnalysisResult) -> str:
        """Prepare output file path in temp directory"""
        try:
            # Sanitize movie name for filename
            safe_name = "".join(c for c in task.movie_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            
            # Add duration info to filename
            duration_info = bdmv_analysis.main_duration_formatted.replace(':', 'h', 1).replace(':', 'm', 1) + 's'
            
            # Construct output filename
            output_filename = f"{safe_name}_{duration_info}.mkv"
            output_path = os.path.join(self.temp_dir, output_filename)
            
            # Remove existing file if present
            if os.path.exists(output_path):
                os.remove(output_path)
            
            self.logger.info(f"Output path prepared: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"Error preparing output path: {e}")
            # Fallback to simple name
            fallback_name = f"movie_{task.task_id}.mkv"
            return os.path.join(self.temp_dir, fallback_name)
    
    async def _mock_processing(self, task: ProcessingTask, start_time: float) -> ProcessingResult:
        """Mock processing for testing"""
        self.logger.info(f"[MOCK] Processing task {task.task_id}: {task.movie_name}")
        
        # Simulate processing time
        await asyncio.sleep(3)
        
        # Create mock output file
        mock_output = f"mock_{task.movie_name.replace(' ', '_')}.mkv"
        mock_temp_path = os.path.join(self.temp_dir, mock_output)
        
        # Create empty file
        Path(mock_temp_path).touch()
        
        processing_time = asyncio.get_event_loop().time() - start_time
        
        return ProcessingResult(
            task_id=task.task_id,
            success=True,
            output_file=mock_output,
            temp_file=mock_output,
            processing_time_seconds=processing_time,
            input_size_mb=25000,  # Mock 25GB
            output_size_mb=23000,  # Mock 23GB
        )
    
    async def cancel_current_task(self) -> bool:
        """Cancel currently running task"""
        if not self.is_processing or not self.current_task:
            return False
        
        self.logger.info(f"Cancelling task {self.current_task.task_id}")
        
        # Cancel FFmpeg conversion
        self.ffmpeg_wrapper.cancel_conversion()
        
        return True
    
    def get_current_task_id(self) -> Optional[int]:
        """Get ID of currently processing task"""
        return self.current_task.task_id if self.current_task else None
    
    def is_busy(self) -> bool:
        """Check if processor is currently busy"""
        return self.is_processing
    
    async def cleanup_temp_files(self, older_than_hours: int = 24):
        """Clean up old temporary files"""
        try:
            import time
            current_time = time.time()
            cutoff_time = current_time - (older_than_hours * 3600)
            
            temp_dir = Path(self.temp_dir)
            if not temp_dir.exists():
                return
            
            cleaned_count = 0
            for file_path in temp_dir.glob("*.mkv"):
                try:
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        cleaned_count += 1
                        self.logger.debug(f"Cleaned up old temp file: {file_path}")
                except Exception as e:
                    self.logger.warning(f"Could not clean up {file_path}: {e}")
            
            if cleaned_count > 0:
                self.logger.info(f"Cleaned up {cleaned_count} old temporary files")
                
        except Exception as e:
            self.logger.error(f"Error during temp file cleanup: {e}")


# Factory function
def create_video_processor() -> VideoProcessor:
    """Create and configure video processor"""
    return VideoProcessor()


# Example usage
if __name__ == "__main__":
    import sys
    
    async def progress_callback(task_id: int, progress: ConversionProgress):
        print(f"Task {task_id}: {progress.progress_percent:.1f}% - "
              f"{progress.status.value} - "
              f"{progress.time_processed}")
    
    async def main():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        if len(sys.argv) < 3:
            print("Usage: python processor.py <task_id> <movie_name> [source_path]")
            print("Example: python processor.py 1 'Test Movie' '/path/to/TestMovie'")
            return
        
        task_id = int(sys.argv[1])
        movie_name = sys.argv[2]
        source_path = sys.argv[3] if len(sys.argv) > 3 else f"/mock/path/{movie_name}"
        
        # Create test task
        test_task = ProcessingTask(
            task_id=task_id,
            movie_name=movie_name,
            source_path=source_path,
            priority=1
        )
        
        # Create processor
        processor = create_video_processor()
        processor.set_progress_callback(progress_callback)
        
        print(f"Processing task: {test_task.movie_name}")
        result = await processor.process_task(test_task)
        
        print(f"\nProcessing Result:")
        print(f"Success: {result.success}")
        print(f"Processing time: {result.processing_time_seconds:.1f}s")
        print(f"Input size: {result.input_size_mb:.1f}MB")
        print(f"Output size: {result.output_size_mb:.1f}MB")
        print(f"Output file: {result.output_file}")
        
        if result.error_message:
            print(f"Error: {result.error_message}")
    
    asyncio.run(main())