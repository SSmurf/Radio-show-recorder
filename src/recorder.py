"""
Radio stream recording module.

This module handles the actual recording of radio streams using ffmpeg.
It provides async recording capabilities with progress tracking and
event emission for notifications.
"""

import asyncio
import os
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class RecordingResult:
    """
    Result of a recording operation.
    
    Attributes:
        success: Whether the recording completed successfully
        filename: Name of the recorded file
        filepath: Full path to the recorded file
        duration: Actual duration recorded in seconds
        size_bytes: File size in bytes
        error: Error message if recording failed
    """
    success: bool
    filename: str
    filepath: Path
    duration: int
    size_bytes: int = 0
    error: Optional[str] = None


# Type alias for notification callbacks
NotifyCallback = Callable[[str], Awaitable[None]]


class Recorder:
    """
    Handles recording of radio streams using ffmpeg.
    
    This class provides methods to record radio streams with configurable
    duration and quality settings. It supports async operation to avoid
    blocking the main event loop during long recordings.
    
    Attributes:
        config: Configuration object with stream URL and settings
        is_recording: Whether a recording is currently in progress
        current_process: The ffmpeg subprocess if recording
    """

    def __init__(self):
        """Initialize the recorder with configuration."""
        self.config = get_config()
        self.is_recording: bool = False
        self.current_process: Optional[asyncio.subprocess.Process] = None
        self._on_start: Optional[NotifyCallback] = None
        self._on_complete: Optional[NotifyCallback] = None
        self._on_error: Optional[NotifyCallback] = None

    def set_callbacks(
        self,
        on_start: Optional[NotifyCallback] = None,
        on_complete: Optional[NotifyCallback] = None,
        on_error: Optional[NotifyCallback] = None,
    ) -> None:
        """
        Set notification callbacks for recording events.
        
        Args:
            on_start: Called when recording starts
            on_complete: Called when recording completes successfully
            on_error: Called when recording fails
        """
        self._on_start = on_start
        self._on_complete = on_complete
        self._on_error = on_error

    def _generate_filename(self, prefix: str = "yammat_recording") -> str:
        """
        Generate a unique filename for the recording.
        
        Args:
            prefix: Prefix for the filename
            
        Returns:
            Filename with timestamp in format: prefix_YYYY-MM-DD_HH-MM-SS.mp3
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{prefix}_{timestamp}.mp3"

    async def _notify(self, callback: Optional[NotifyCallback], message: str) -> None:
        """
        Send a notification if callback is set and notifications are enabled.
        
        Args:
            callback: The callback function to call
            message: Message to send
        """
        if callback and self.config.dynamic.notifications_enabled:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"Notification callback failed: {e}")

    async def record(
        self,
        duration: Optional[int] = None,
        filename: Optional[str] = None,
        is_test: bool = False,
    ) -> RecordingResult:
        """
        Record the radio stream for the specified duration.
        
        This method spawns an ffmpeg subprocess to record the stream.
        It's async to allow the event loop to continue during recording.
        
        Args:
            duration: Recording duration in seconds. If None, uses config default.
            filename: Custom filename. If None, auto-generates based on timestamp.
            is_test: Whether this is a test recording (uses test_duration if duration is None)
            
        Returns:
            RecordingResult with recording details and status
        """
        if self.is_recording:
            return RecordingResult(
                success=False,
                filename="",
                filepath=Path(),
                duration=0,
                error="Recording already in progress",
            )

        # Determine duration
        if duration is None:
            duration = (
                self.config.dynamic.test_duration
                if is_test
                else self.config.default_duration
            )

        # Generate filename if not provided
        if filename is None:
            prefix = "yammat_test" if is_test else "yammat_recording"
            filename = self._generate_filename(prefix)

        filepath = self.config.recordings_dir / filename
        
        # Format duration for display
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = (
            f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s"
        )

        logger.info(f"Starting recording: {filename} (duration: {duration_str})")
        
        # Notify start
        await self._notify(
            self._on_start,
            f"🎙️ Recording started\n\nFile: `{filename}`\nDuration: {duration_str}",
        )

        self.is_recording = True
        
        # Build ffmpeg command
        command = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-i", self.config.stream_url,
            "-t", str(duration),
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(filepath),
        ]

        try:
            # Create subprocess
            self.current_process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for completion
            stdout, stderr = await self.current_process.communicate()

            if self.current_process.returncode == 0:
                # Get file size
                size_bytes = filepath.stat().st_size if filepath.exists() else 0
                size_mb = size_bytes / (1024 * 1024)

                logger.info(f"Recording completed: {filename} ({size_mb:.1f} MB)")
                
                # Notify completion
                await self._notify(
                    self._on_complete,
                    f"✅ Recording completed\n\nFile: `{filename}`\nSize: {size_mb:.1f} MB",
                )

                return RecordingResult(
                    success=True,
                    filename=filename,
                    filepath=filepath,
                    duration=duration,
                    size_bytes=size_bytes,
                )
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"Recording failed: {error_msg}")
                
                # Notify error
                await self._notify(
                    self._on_error,
                    f"❌ Recording failed\n\nFile: `{filename}`\nError: {error_msg[:200]}",
                )

                return RecordingResult(
                    success=False,
                    filename=filename,
                    filepath=filepath,
                    duration=duration,
                    error=error_msg,
                )

        except asyncio.CancelledError:
            # Recording was cancelled (e.g., shutdown)
            if self.current_process:
                self.current_process.terminate()
                await self.current_process.wait()
            
            logger.warning(f"Recording cancelled: {filename}")
            
            return RecordingResult(
                success=False,
                filename=filename,
                filepath=filepath,
                duration=duration,
                error="Recording cancelled",
            )

        except Exception as e:
            logger.exception(f"Recording error: {e}")
            
            # Notify error
            await self._notify(
                self._on_error,
                f"❌ Recording error\n\nFile: `{filename}`\nError: {str(e)}",
            )

            return RecordingResult(
                success=False,
                filename=filename,
                filepath=filepath,
                duration=duration,
                error=str(e),
            )

        finally:
            self.is_recording = False
            self.current_process = None

    async def test_record(self) -> RecordingResult:
        """
        Perform a test recording with the configured test duration.
        
        This is a convenience method that calls record() with is_test=True.
        
        Returns:
            RecordingResult with test recording details
        """
        return await self.record(is_test=True)

    def get_status(self) -> dict:
        """
        Get the current status of the recorder.
        
        Returns:
            Dictionary with recording status information
        """
        return {
            "is_recording": self.is_recording,
            "stream_url": self.config.stream_url,
            "recordings_dir": str(self.config.recordings_dir),
        }

    async def stop(self) -> bool:
        """
        Stop the current recording if one is in progress.
        
        Returns:
            True if a recording was stopped, False otherwise
        """
        if self.current_process and self.is_recording:
            self.current_process.terminate()
            try:
                await asyncio.wait_for(self.current_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.current_process.kill()
            
            logger.info("Recording stopped by user")
            return True
        return False


# Global recorder instance
_recorder: Optional[Recorder] = None


def get_recorder() -> Recorder:
    """
    Get the global recorder instance.
    
    Creates the instance on first call (lazy initialization).
    
    Returns:
        The global Recorder instance
    """
    global _recorder
    if _recorder is None:
        _recorder = Recorder()
    return _recorder
