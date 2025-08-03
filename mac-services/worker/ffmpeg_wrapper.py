#!/usr/bin/env python3
"""
BluRay Converter - FFmpeg Wrapper
Wrapper for FFmpeg video conversion with progress tracking
"""

import os
import re
import asyncio
import logging
import subprocess
import tempfile
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass
from pathlib import Path
from enum import Enum


class ConversionStatus(Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    CONVERTING = "converting" 
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ConversionProgress:
    """Progress information for video conversion"""
    status: ConversionStatus
    progress_percent: float = 0.0
    current_frame: int = 0
    total_frames: int = 0
    fps: float = 0.0
    bitrate: str = "0kbps"
    time_processed: str = "00:00:00"
    time_remaining: str = "00:00:00"
    speed: str = "0x"
    file_size_mb: float = 0.0
    error_message: Optional[str] = None


@dataclass
class ConversionResult:
    """Result of video conversion"""
    success: bool
    output_file: str
    processing_time_seconds: float
    input_size_mb: float
    output_size_mb: float
    compression_ratio: float
    error_message: Optional[str] = None


class FFmpegWrapper:
    """Wrapper for FFmpeg with progress tracking and error handling"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Configuration from environment
        self.ffmpeg_binary = os.getenv("FFMPEG_BINARY", "ffmpeg")
        self.ffprobe_binary = os.getenv("FFPROBE_BINARY", "ffprobe")
        self.threads = int(os.getenv("FFMPEG_THREADS", "0"))  # 0 = auto
        self.preset = os.getenv("FFMPEG_PRESET", "slow")
        self.timeout = int(os.getenv("FFMPEG_TIMEOUT", "14400"))  # 4 hours default
        
        # Progress tracking
        self.current_progress = ConversionProgress(ConversionStatus.PENDING)
        self.progress_callback: Optional[Callable[[ConversionProgress], None]] = None
        self.cancelled = False
        
        # Mock mode for testing
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
        
        # Validate FFmpeg availability
        if not self.mock_mode:
            self._validate_ffmpeg()
    
    def _validate_ffmpeg(self):
        """Validate that FFmpeg is available and working"""
        try:
            result = subprocess.run(
                [self.ffmpeg_binary, "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                raise Exception(f"FFmpeg validation failed: {result.stderr}")
            
            self.logger.info(f"FFmpeg validated: {result.stdout.split()[2]}")
            
        except Exception as e:
            self.logger.error(f"FFmpeg validation error: {e}")
            raise RuntimeError(f"FFmpeg not available or not working: {e}")
    
    def set_progress_callback(self, callback: Callable[[ConversionProgress], None]):
        """Set callback function for progress updates"""
        self.progress_callback = callback
    
    def _update_progress(self, **kwargs):
        """Update progress and call callback if set"""
        for key, value in kwargs.items():
            if hasattr(self.current_progress, key):
                setattr(self.current_progress, key, value)
        
        if self.progress_callback:
            self.progress_callback(self.current_progress)
    
    async def convert_bluray_to_mkv(
        self,
        input_path: str,
        output_path: str,
        playlist_path: Optional[str] = None
    ) -> ConversionResult:
        """
        Convert BluRay to MKV format using remux (no re-encoding)
        
        Args:
            input_path: Path to BluRay directory or BDMV folder
            output_path: Output MKV file path
            playlist_path: Specific playlist file path (optional)
            
        Returns:
            ConversionResult with processing information
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            self.logger.info(f"Starting BluRay to MKV conversion: {input_path} -> {output_path}")
            
            if self.mock_mode:
                return await self._mock_conversion(input_path, output_path, start_time)
            
            # Reset state
            self.cancelled = False
            self._update_progress(
                status=ConversionStatus.ANALYZING,
                progress_percent=0.0
            )
            
            # Analyze input
            input_info = await self._analyze_input(input_path, playlist_path)
            if not input_info:
                raise Exception("Failed to analyze input file")
            
            # Prepare output directory
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Build FFmpeg command
            cmd = self._build_ffmpeg_command(input_path, output_path, playlist_path, input_info)
            
            # Execute conversion
            result = await self._execute_conversion(cmd, input_info, start_time)
            
            # Verify output
            if result.success:
                output_size = self._get_file_size_mb(output_path) if os.path.exists(output_path) else 0
                result.output_size_mb = output_size
                result.compression_ratio = result.input_size_mb / output_size if output_size > 0 else 0
                
                self._update_progress(
                    status=ConversionStatus.COMPLETED,
                    progress_percent=100.0,
                    file_size_mb=output_size
                )
                
                self.logger.info(f"Conversion completed successfully: {output_path}")
                self.logger.info(f"Input: {result.input_size_mb:.1f}MB, Output: {result.output_size_mb:.1f}MB")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Conversion failed: {e}")
            
            self._update_progress(
                status=ConversionStatus.FAILED,
                error_message=str(e)
            )
            
            processing_time = asyncio.get_event_loop().time() - start_time
            return ConversionResult(
                success=False,
                output_file="",
                processing_time_seconds=processing_time,
                input_size_mb=0,
                output_size_mb=0,
                compression_ratio=0,
                error_message=str(e)
            )
    
    async def _analyze_input(self, input_path: str, playlist_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Analyze input file to get duration and stream information"""
        try:
            # Determine the correct input for ffprobe
            if playlist_path and os.path.exists(playlist_path):
                probe_input = playlist_path
            elif os.path.isdir(input_path):
                # Use bluray protocol for directory
                probe_input = f"bluray:{input_path}"
            else:
                probe_input = input_path
            
            cmd = [
                self.ffprobe_binary,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                probe_input
            ]
            
            self.logger.debug(f"Analyzing input with: {' '.join(cmd)}")
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                self.logger.error(f"ffprobe failed: {stderr.decode()}")
                return None
            
            import json
            data = json.loads(stdout.decode())
            
            # Extract relevant information
            format_info = data.get("format", {})
            streams = data.get("streams", [])
            
            duration = float(format_info.get("duration", "0"))
            size_bytes = int(format_info.get("size", "0"))
            
            info = {
                "duration": duration,
                "size_bytes": size_bytes,
                "size_mb": size_bytes / (1024 * 1024),
                "streams": streams,
                "video_streams": [s for s in streams if s.get("codec_type") == "video"],
                "audio_streams": [s for s in streams if s.get("codec_type") == "audio"],
                "subtitle_streams": [s for s in streams if s.get("codec_type") == "subtitle"]
            }
            
            self.logger.info(f"Input analysis: {duration:.0f}s, {info['size_mb']:.1f}MB, "
                           f"{len(info['video_streams'])}V/{len(info['audio_streams'])}A/{len(info['subtitle_streams'])}S")
            
            return info
            
        except Exception as e:
            self.logger.error(f"Error analyzing input: {e}")
            return None
    
    def _build_ffmpeg_command(
        self,
        input_path: str,
        output_path: str,
        playlist_path: Optional[str],
        input_info: Dict[str, Any]
    ) -> List[str]:
        """Build FFmpeg command for BluRay to MKV conversion"""
        
        # Determine input source
        if playlist_path and os.path.exists(playlist_path):
            input_source = playlist_path
        elif os.path.isdir(input_path):
            input_source = f"bluray:{input_path}"
        else:
            input_source = input_path
        
        cmd = [
            self.ffmpeg_binary,
            "-y",  # Overwrite output files
            "-progress", "pipe:1",  # Progress to stdout
            "-i", input_source,
        ]
        
        # Threading
        if self.threads > 0:
            cmd.extend(["-threads", str(self.threads)])
        
        # Copy all streams without re-encoding (remux)
        cmd.extend([
            "-c", "copy",  # Copy all streams
            "-map", "0",   # Include all streams from input
        ])
        
        # Output format
        cmd.extend([
            "-f", "matroska",  # MKV format
            output_path
        ])
        
        self.logger.info(f"FFmpeg command: {' '.join(cmd)}")
        return cmd
    
    async def _execute_conversion(
        self,
        cmd: List[str],
        input_info: Dict[str, Any],
        start_time: float
    ) -> ConversionResult:
        """Execute FFmpeg conversion with progress tracking"""
        
        self._update_progress(
            status=ConversionStatus.CONVERTING,
            progress_percent=0.0
        )
        
        try:
            # Start FFmpeg process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Track progress
            await self._track_progress(process, input_info)
            
            # Wait for completion
            await process.wait()
            
            if self.cancelled:
                self.logger.info("Conversion was cancelled")
                return ConversionResult(
                    success=False,
                    output_file="",
                    processing_time_seconds=asyncio.get_event_loop().time() - start_time,
                    input_size_mb=input_info.get("size_mb", 0),
                    output_size_mb=0,
                    compression_ratio=0,
                    error_message="Conversion cancelled"
                )
            
            if process.returncode == 0:
                processing_time = asyncio.get_event_loop().time() - start_time
                return ConversionResult(
                    success=True,
                    output_file=cmd[-1],  # Last argument is output file
                    processing_time_seconds=processing_time,
                    input_size_mb=input_info.get("size_mb", 0),
                    output_size_mb=0,  # Will be set by caller
                    compression_ratio=0  # Will be calculated by caller
                )
            else:
                stderr_output = await process.stderr.read()
                error_msg = stderr_output.decode() if stderr_output else "Unknown FFmpeg error"
                
                self.logger.error(f"FFmpeg failed with return code {process.returncode}: {error_msg}")
                
                return ConversionResult(
                    success=False,
                    output_file="",
                    processing_time_seconds=asyncio.get_event_loop().time() - start_time,
                    input_size_mb=input_info.get("size_mb", 0),
                    output_size_mb=0,
                    compression_ratio=0,
                    error_message=f"FFmpeg error: {error_msg[:200]}"
                )
                
        except Exception as e:
            self.logger.error(f"Error executing FFmpeg: {e}")
            return ConversionResult(
                success=False,
                output_file="",
                processing_time_seconds=asyncio.get_event_loop().time() - start_time,
                input_size_mb=input_info.get("size_mb", 0),
                output_size_mb=0,
                compression_ratio=0,
                error_message=str(e)
            )
    
    async def _track_progress(self, process: asyncio.subprocess.Process, input_info: Dict[str, Any]):
        """Track FFmpeg progress from stdout"""
        total_duration = input_info.get("duration", 0)
        
        try:
            while process.returncode is None and not self.cancelled:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                
                if not line:
                    break
                
                line_str = line.decode().strip()
                
                if not line_str:
                    continue
                
                # Parse progress information
                progress_data = self._parse_progress_line(line_str)
                
                if progress_data:
                    # Calculate progress percentage
                    if total_duration > 0 and "out_time" in progress_data:
                        time_processed = self._parse_time_to_seconds(progress_data["out_time"])
                        progress_percent = min((time_processed / total_duration) * 100, 100)
                        
                        # Estimate time remaining
                        if progress_percent > 0:
                            elapsed_time = asyncio.get_event_loop().time() - asyncio.get_event_loop().time()
                            estimated_total = elapsed_time * (100 / progress_percent)
                            time_remaining = max(0, estimated_total - elapsed_time)
                            time_remaining_str = self._seconds_to_time_str(time_remaining)
                        else:
                            time_remaining_str = "Unknown"
                        
                        self._update_progress(
                            progress_percent=progress_percent,
                            time_processed=progress_data.get("out_time", "00:00:00"),
                            time_remaining=time_remaining_str,
                            fps=float(progress_data.get("fps", "0")),
                            bitrate=progress_data.get("bitrate", "0kbps"),
                            speed=progress_data.get("speed", "0x")
                        )
                
        except asyncio.TimeoutError:
            # Normal timeout, continue
            pass
        except Exception as e:
            self.logger.warning(f"Error tracking progress: {e}")
    
    def _parse_progress_line(self, line: str) -> Optional[Dict[str, str]]:
        """Parse FFmpeg progress line"""
        if "=" not in line:
            return None
        
        try:
            key, value = line.split("=", 1)
            return {key.strip(): value.strip()}
        except ValueError:
            return None
    
    def _parse_time_to_seconds(self, time_str: str) -> float:
        """Convert time string (HH:MM:SS.mmm) to seconds"""
        try:
            if ":" in time_str:
                parts = time_str.split(":")
                hours = float(parts[0]) if len(parts) > 2 else 0
                minutes = float(parts[-2])
                seconds = float(parts[-1])
                return hours * 3600 + minutes * 60 + seconds
            else:
                return float(time_str)
        except (ValueError, IndexError):
            return 0.0
    
    def _seconds_to_time_str(self, seconds: float) -> str:
        """Convert seconds to HH:MM:SS format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def _get_file_size_mb(self, file_path: str) -> float:
        """Get file size in megabytes"""
        try:
            return os.path.getsize(file_path) / (1024 * 1024)
        except OSError:
            return 0.0
    
    async def _mock_conversion(self, input_path: str, output_path: str, start_time: float) -> ConversionResult:
        """Mock conversion for testing"""
        self.logger.info(f"[MOCK] Starting conversion: {input_path} -> {output_path}")
        
        # Simulate analysis
        self._update_progress(status=ConversionStatus.ANALYZING, progress_percent=0)
        await asyncio.sleep(2)
        
        # Simulate conversion with progress updates
        self._update_progress(status=ConversionStatus.CONVERTING, progress_percent=0)
        
        for i in range(0, 101, 5):
            if self.cancelled:
                break
            
            self._update_progress(
                progress_percent=i,
                fps=25.0,
                bitrate="15000kbps",
                speed="1.2x",
                time_processed=f"00:{i//2:02d}:00"
            )
            
            await asyncio.sleep(0.5)  # Simulate processing time
        
        if self.cancelled:
            return ConversionResult(
                success=False,
                output_file="",
                processing_time_seconds=asyncio.get_event_loop().time() - start_time,
                input_size_mb=25000,  # Mock 25GB input
                output_size_mb=0,
                compression_ratio=0,
                error_message="Conversion cancelled"
            )
        
        # Create mock output file
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).touch()
        
        self._update_progress(status=ConversionStatus.COMPLETED, progress_percent=100)
        
        processing_time = asyncio.get_event_loop().time() - start_time
        
        return ConversionResult(
            success=True,
            output_file=output_path,
            processing_time_seconds=processing_time,
            input_size_mb=25000,  # Mock 25GB input
            output_size_mb=23000,  # Mock 23GB output
            compression_ratio=1.09
        )
    
    def cancel_conversion(self):
        """Cancel ongoing conversion"""
        self.logger.info("Cancelling conversion...")
        self.cancelled = True
        self._update_progress(status=ConversionStatus.CANCELLED)
    
    def get_current_progress(self) -> ConversionProgress:
        """Get current conversion progress"""
        return self.current_progress


# Utility functions
async def convert_bluray_to_mkv(
    input_path: str,
    output_path: str,
    playlist_path: Optional[str] = None,
    progress_callback: Optional[Callable[[ConversionProgress], None]] = None
) -> ConversionResult:
    """Convenience function for BluRay to MKV conversion"""
    wrapper = FFmpegWrapper()
    
    if progress_callback:
        wrapper.set_progress_callback(progress_callback)
    
    return await wrapper.convert_bluray_to_mkv(input_path, output_path, playlist_path)


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    async def progress_callback(progress: ConversionProgress):
        print(f"Progress: {progress.progress_percent:.1f}% - "
              f"{progress.status.value} - "
              f"{progress.time_processed} - "
              f"{progress.fps:.1f}fps - "
              f"{progress.speed}")
    
    async def main():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        if len(sys.argv) < 3:
            print("Usage: python ffmpeg_wrapper.py <input_path> <output_path> [playlist_path]")
            print("Example: python ffmpeg_wrapper.py /path/to/BDMV /path/to/output.mkv")
            return
        
        input_path = sys.argv[1]
        output_path = sys.argv[2]
        playlist_path = sys.argv[3] if len(sys.argv) > 3 else None
        
        wrapper = FFmpegWrapper()
        wrapper.set_progress_callback(progress_callback)
        
        print(f"Converting: {input_path} -> {output_path}")
        result = await wrapper.convert_bluray_to_mkv(input_path, output_path, playlist_path)
        
        print(f"\nConversion Result:")
        print(f"Success: {result.success}")
        print(f"Processing time: {result.processing_time_seconds:.1f}s")
        print(f"Input size: {result.input_size_mb:.1f}MB")
        print(f"Output size: {result.output_size_mb:.1f}MB")
        print(f"Compression ratio: {result.compression_ratio:.2f}")
        
        if result.error_message:
            print(f"Error: {result.error_message}")
    
    asyncio.run(main())