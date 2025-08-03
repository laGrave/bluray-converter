#!/usr/bin/env python3
"""
BluRay Converter - BDMV Analyzer
Analyzes BluRay disc structure and finds main video content
"""

import os
import re
import struct
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PlaylistInfo:
    """Information about a BluRay playlist"""
    file_path: str
    playlist_id: str
    duration_seconds: int
    video_streams: List[str]
    audio_streams: List[str]
    subtitle_streams: List[str]
    file_size_bytes: int
    
    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0
    
    @property
    def duration_formatted(self) -> str:
        hours = self.duration_seconds // 3600
        minutes = (self.duration_seconds % 3600) // 60
        seconds = self.duration_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass
class BDMVAnalysisResult:
    """Result of BDMV structure analysis"""
    is_valid: bool
    main_playlist: Optional[PlaylistInfo]
    all_playlists: List[PlaylistInfo]
    total_duration_seconds: int
    error_message: Optional[str] = None
    
    @property
    def main_duration_formatted(self) -> str:
        if self.main_playlist:
            return self.main_playlist.duration_formatted
        return "00:00:00"


class BDMVAnalyzer:
    """Analyzer for BluRay disc BDMV structure"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Minimum duration for main feature (in seconds)
        self.min_main_duration = int(os.getenv("MIN_MAIN_DURATION_MINUTES", "60")) * 60
        
        # Mock mode for testing
        self.mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
    
    def analyze_bdmv_structure(self, bdmv_path: str) -> BDMVAnalysisResult:
        """
        Analyze BDMV structure and identify main content
        
        Args:
            bdmv_path: Path to the BDMV directory
            
        Returns:
            BDMVAnalysisResult with analysis information
        """
        try:
            self.logger.info(f"Analyzing BDMV structure: {bdmv_path}")
            
            if self.mock_mode:
                return self._mock_analysis_result(bdmv_path)
            
            # Validate BDMV structure
            if not self._validate_bdmv_structure(bdmv_path):
                return BDMVAnalysisResult(
                    is_valid=False,
                    main_playlist=None,
                    all_playlists=[],
                    total_duration_seconds=0,
                    error_message="Invalid BDMV structure"
                )
            
            # Find and analyze playlists
            playlists = self._find_playlists(bdmv_path)
            
            if not playlists:
                return BDMVAnalysisResult(
                    is_valid=False,
                    main_playlist=None,
                    all_playlists=[],
                    total_duration_seconds=0,
                    error_message="No valid playlists found"
                )
            
            # Identify main playlist (longest duration)
            main_playlist = self._identify_main_playlist(playlists)
            
            if not main_playlist:
                return BDMVAnalysisResult(
                    is_valid=False,
                    main_playlist=None,
                    all_playlists=playlists,
                    total_duration_seconds=sum(p.duration_seconds for p in playlists),
                    error_message=f"No main feature found (minimum {self.min_main_duration//60} minutes required)"
                )
            
            total_duration = sum(p.duration_seconds for p in playlists)
            
            self.logger.info(f"Analysis completed: Main playlist {main_playlist.playlist_id} "
                           f"({main_playlist.duration_formatted})")
            
            return BDMVAnalysisResult(
                is_valid=True,
                main_playlist=main_playlist,
                all_playlists=playlists,
                total_duration_seconds=total_duration
            )
            
        except Exception as e:
            self.logger.error(f"Error analyzing BDMV structure: {e}")
            return BDMVAnalysisResult(
                is_valid=False,
                main_playlist=None,
                all_playlists=[],
                total_duration_seconds=0,
                error_message=str(e)
            )
    
    def _validate_bdmv_structure(self, bdmv_path: str) -> bool:
        """Validate that the path contains a proper BDMV structure"""
        bdmv_dir = Path(bdmv_path)
        
        # Check if BDMV directory exists
        if not bdmv_dir.exists() or not bdmv_dir.is_dir():
            self.logger.error(f"BDMV directory not found: {bdmv_path}")
            return False
        
        # Required subdirectories
        required_dirs = ["PLAYLIST", "STREAM"]
        
        for dir_name in required_dirs:
            dir_path = bdmv_dir / dir_name
            if not dir_path.exists() or not dir_path.is_dir():
                self.logger.error(f"Required BDMV subdirectory missing: {dir_name}")
                return False
        
        # Check for playlist files
        playlist_dir = bdmv_dir / "PLAYLIST"
        playlist_files = list(playlist_dir.glob("*.mpls"))
        
        if not playlist_files:
            self.logger.error("No playlist files (.mpls) found")
            return False
        
        # Check for stream files
        stream_dir = bdmv_dir / "STREAM"
        stream_files = list(stream_dir.glob("*.m2ts"))
        
        if not stream_files:
            self.logger.error("No stream files (.m2ts) found")
            return False
        
        self.logger.info(f"Valid BDMV structure: {len(playlist_files)} playlists, {len(stream_files)} streams")
        return True
    
    def _find_playlists(self, bdmv_path: str) -> List[PlaylistInfo]:
        """Find and analyze all playlist files"""
        playlists = []
        playlist_dir = Path(bdmv_path) / "PLAYLIST"
        
        for mpls_file in playlist_dir.glob("*.mpls"):
            try:
                playlist_info = self._analyze_playlist_file(str(mpls_file))
                if playlist_info:
                    playlists.append(playlist_info)
                    self.logger.debug(f"Found playlist: {playlist_info.playlist_id} "
                                    f"({playlist_info.duration_formatted})")
            except Exception as e:
                self.logger.warning(f"Error analyzing playlist {mpls_file}: {e}")
        
        # Sort by duration (longest first)
        playlists.sort(key=lambda p: p.duration_seconds, reverse=True)
        
        self.logger.info(f"Found {len(playlists)} valid playlists")
        return playlists
    
    def _analyze_playlist_file(self, mpls_path: str) -> Optional[PlaylistInfo]:
        """
        Analyze a single MPLS playlist file
        
        This is a simplified parser that extracts basic information.
        For production, consider using libbluray or similar library.
        """
        try:
            with open(mpls_path, 'rb') as f:
                # Read MPLS header
                header = f.read(8)
                if header[:4] != b'MPLS':
                    self.logger.warning(f"Invalid MPLS header in {mpls_path}")
                    return None
                
                # Skip to playlist mark section
                f.seek(8)
                
                # This is a simplified parser - real MPLS parsing is more complex
                # We'll extract basic duration information
                
                playlist_id = Path(mpls_path).stem
                file_size = os.path.getsize(mpls_path)
                
                # For now, estimate duration based on file patterns
                # In a real implementation, you'd parse the actual MPLS structure
                duration = self._estimate_duration_from_mpls(mpls_path)
                
                return PlaylistInfo(
                    file_path=mpls_path,
                    playlist_id=playlist_id,
                    duration_seconds=duration,
                    video_streams=["Primary Video"],  # Simplified
                    audio_streams=["Primary Audio"],  # Simplified
                    subtitle_streams=["Primary Subtitles"],  # Simplified
                    file_size_bytes=file_size
                )
                
        except Exception as e:
            self.logger.error(f"Error reading MPLS file {mpls_path}: {e}")
            return None
    
    def _estimate_duration_from_mpls(self, mpls_path: str) -> int:
        """
        Estimate duration from MPLS file
        
        This is a simplified approach. In production, you would:
        1. Parse the actual MPLS binary format
        2. Extract PlayItem information
        3. Calculate precise duration from time codes
        """
        try:
            # Use ffprobe as fallback for duration detection
            return self._get_duration_with_ffprobe(mpls_path)
        except Exception as e:
            self.logger.warning(f"Could not determine duration for {mpls_path}: {e}")
            
            # Fallback: estimate based on playlist ID patterns
            playlist_id = Path(mpls_path).stem
            
            # Common patterns in BluRay playlists
            if playlist_id == "00000":
                return 300  # Usually short intro/menu
            elif playlist_id in ["00001", "00800", "00850"]:
                return 7200  # Usually main feature (2 hours estimate)
            else:
                # Try to extract from filename patterns or use file size heuristic
                file_size = os.path.getsize(mpls_path)
                if file_size > 1000:  # Larger playlist files usually mean longer content
                    return 5400  # 1.5 hours estimate
                else:
                    return 600   # 10 minutes estimate for extras
    
    def _get_duration_with_ffprobe(self, mpls_path: str) -> int:
        """Use ffprobe to get accurate duration from playlist"""
        import subprocess
        import json
        
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                f"bluray:{os.path.dirname(os.path.dirname(mpls_path))}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration_str = data.get("format", {}).get("duration", "0")
                return int(float(duration_str))
            else:
                self.logger.warning(f"ffprobe failed for {mpls_path}: {result.stderr}")
                return 0
                
        except subprocess.TimeoutExpired:
            self.logger.warning(f"ffprobe timeout for {mpls_path}")
            return 0
        except Exception as e:
            self.logger.warning(f"ffprobe error for {mpls_path}: {e}")
            return 0
    
    def _identify_main_playlist(self, playlists: List[PlaylistInfo]) -> Optional[PlaylistInfo]:
        """Identify the main feature playlist (longest duration above minimum)"""
        
        # Filter playlists by minimum duration
        main_candidates = [p for p in playlists if p.duration_seconds >= self.min_main_duration]
        
        if not main_candidates:
            self.logger.warning(f"No playlists meet minimum duration requirement ({self.min_main_duration//60} minutes)")
            return None
        
        # Return the longest playlist
        main_playlist = main_candidates[0]  # Already sorted by duration (longest first)
        
        self.logger.info(f"Main playlist identified: {main_playlist.playlist_id} "
                        f"({main_playlist.duration_formatted})")
        
        return main_playlist
    
    def get_main_playlist_path(self, bdmv_path: str) -> Optional[str]:
        """Get the file path of the main playlist for FFmpeg processing"""
        analysis = self.analyze_bdmv_structure(bdmv_path)
        
        if not analysis.is_valid or not analysis.main_playlist:
            return None
        
        return analysis.main_playlist.file_path
    
    def _mock_analysis_result(self, bdmv_path: str) -> BDMVAnalysisResult:
        """Generate mock analysis result for testing"""
        mock_main = PlaylistInfo(
            file_path=f"{bdmv_path}/PLAYLIST/00001.mpls",
            playlist_id="00001",
            duration_seconds=7200,  # 2 hours
            video_streams=["H.264 1080p"],
            audio_streams=["DTS-HD MA 5.1", "AC3 2.0"],
            subtitle_streams=["English", "French"],
            file_size_bytes=2048
        )
        
        mock_extras = [
            PlaylistInfo(
                file_path=f"{bdmv_path}/PLAYLIST/00000.mpls",
                playlist_id="00000",
                duration_seconds=300,  # 5 minutes
                video_streams=["H.264 1080p"],
                audio_streams=["AC3 2.0"],
                subtitle_streams=[],
                file_size_bytes=512
            ),
            PlaylistInfo(
                file_path=f"{bdmv_path}/PLAYLIST/00002.mpls", 
                playlist_id="00002",
                duration_seconds=1800,  # 30 minutes
                video_streams=["H.264 1080p"],
                audio_streams=["AC3 2.0"],
                subtitle_streams=["English"],
                file_size_bytes=1024
            )
        ]
        
        all_playlists = [mock_main] + mock_extras
        
        self.logger.info(f"[MOCK] BDMV analysis completed for {bdmv_path}")
        
        return BDMVAnalysisResult(
            is_valid=True,
            main_playlist=mock_main,
            all_playlists=all_playlists,
            total_duration_seconds=sum(p.duration_seconds for p in all_playlists)
        )


# Utility functions
def analyze_bluray_disc(bdmv_path: str) -> BDMVAnalysisResult:
    """Convenience function to analyze a BluRay disc"""
    analyzer = BDMVAnalyzer()
    return analyzer.analyze_bdmv_structure(bdmv_path)


def get_main_playlist_for_ffmpeg(bdmv_path: str) -> Optional[str]:
    """Get the main playlist path for FFmpeg processing"""
    analyzer = BDMVAnalyzer()
    return analyzer.get_main_playlist_path(bdmv_path)


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) > 1:
        bdmv_path = sys.argv[1]
        
        print(f"Analyzing BDMV structure: {bdmv_path}")
        
        analyzer = BDMVAnalyzer()
        result = analyzer.analyze_bdmv_structure(bdmv_path)
        
        print(f"\nAnalysis Result:")
        print(f"Valid: {result.is_valid}")
        
        if result.error_message:
            print(f"Error: {result.error_message}")
        
        if result.main_playlist:
            print(f"\nMain Playlist:")
            print(f"  ID: {result.main_playlist.playlist_id}")
            print(f"  Duration: {result.main_playlist.duration_formatted}")
            print(f"  Path: {result.main_playlist.file_path}")
        
        print(f"\nAll Playlists ({len(result.all_playlists)}):")
        for playlist in result.all_playlists:
            print(f"  {playlist.playlist_id}: {playlist.duration_formatted}")
        
        print(f"\nTotal Duration: {result.total_duration_seconds // 3600:02d}:"
              f"{(result.total_duration_seconds % 3600) // 60:02d}:"
              f"{result.total_duration_seconds % 60:02d}")
    else:
        print("Usage: python bdmv_analyzer.py <path_to_bdmv_directory>")
        print("Example: python bdmv_analyzer.py /path/to/movie/BDMV")