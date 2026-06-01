"""
Radio stream recording module.

This module handles the actual recording of radio streams using ffmpeg.
It provides async recording capabilities with progress tracking and
event emission for notifications.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class RecordingSegmentResult:
    """
    Result of a single recording segment.
    
    Attributes:
        success: Whether the segment was saved successfully
        filename: Name of the recorded file
        filepath: Full path to the recorded file
        duration: Actual duration recorded in seconds
        size_bytes: File size in bytes
        error: Error message if segment failed
        partial: Whether the segment ended due to a stream drop
    """
    success: bool
    filename: str
    filepath: Path
    duration: int
    size_bytes: int = 0
    error: Optional[str] = None
    partial: bool = False


@dataclass
class RecordingSessionResult:
    """
    Result of a recording session that may include multiple segments.
    
    Attributes:
        success: Whether the full requested duration was recorded
        segments: List of segment results recorded in this session
        requested_duration: Requested recording duration in seconds
        recorded_duration: Total duration recorded across segments
        error: Error message if session failed or was incomplete
    """
    success: bool
    segments: list[RecordingSegmentResult]
    requested_duration: int
    recorded_duration: int
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

    def _is_retryable_error(self, error_msg: str) -> bool:
        """
        Check if an ffmpeg error message indicates a retryable stream drop.
        """
        if not error_msg:
            return False
        lowered = error_msg.lower()
        retryable_phrases = [
            "connection refused",
            "connection reset",
            "connection timed out",
            "network is unreachable",
            "temporary failure in name resolution",
            "server returned 404",
            "http error",
            "i/o error",
            "unable to open",
            "end of file",
        ]
        return any(phrase in lowered for phrase in retryable_phrases)

    async def record(
        self,
        duration: Optional[int] = None,
        filename: Optional[str] = None,
        is_test: bool = False,
    ) -> RecordingSessionResult:
        """
        Record the radio stream for the specified duration.
        
        This method spawns an ffmpeg subprocess to record the stream.
        It's async to allow the event loop to continue during recording.
        
        Args:
            duration: Recording duration in seconds. If None, uses config default.
            filename: Custom filename. If None, auto-generates based on timestamp.
            is_test: Whether this is a test recording (uses test_duration if duration is None)
            
        Returns:
            RecordingSessionResult with recording details and status
        """
        if self.is_recording:
            return RecordingSessionResult(
                success=False,
                segments=[],
                requested_duration=0,
                recorded_duration=0,
                error="Recording already in progress",
            )

        # Determine duration
        if duration is None:
            duration = (
                self.config.dynamic.test_duration
                if is_test
                else self.config.default_duration
            )

        self.is_recording = True
        session_segments: list[RecordingSegmentResult] = []
        recorded_duration = 0
        remaining_duration = duration
        retry_deadline: Optional[float] = None
        retry_delay = max(1, int(self.config.dynamic.retry_delay_seconds))
        retry_max_seconds = max(0, int(self.config.dynamic.retry_max_seconds))

        try:
            while remaining_duration > 0:
                # Generate filename if not provided
                if filename is None:
                    prefix = "yammat_test" if is_test else "yammat_recording"
                    segment_filename = self._generate_filename(prefix)
                else:
                    segment_filename = filename
                    filename = None

                seg_hours, seg_remainder = divmod(remaining_duration, 3600)
                seg_minutes, seg_seconds = divmod(seg_remainder, 60)
                segment_duration_str = (
                    f"{seg_hours}h {seg_minutes}m"
                    if seg_hours > 0
                    else f"{seg_minutes}m {seg_seconds}s"
                )

                filepath = self.config.recordings_dir / segment_filename

                logger.info(
                    f"Starting recording segment: {segment_filename} "
                    f"(target: {segment_duration_str})"
                )

                await self._notify(
                    self._on_start,
                    f"🎙️ Recording started\n\nFile: `{segment_filename}`\n"
                    f"Duration: {segment_duration_str}",
                )

                # Build ffmpeg command
                command = [
                    "ffmpeg",
                    "-y",  # Overwrite output file
                    "-i", self.config.stream_url,
                    "-t", str(remaining_duration),
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    str(filepath),
                ]

                segment_start = time.monotonic()
                self.current_process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await self.current_process.communicate()
                elapsed = max(0, int(time.monotonic() - segment_start))
                error_msg = stderr.decode() if stderr else ""

                if self.current_process.returncode == 0:
                    size_bytes = filepath.stat().st_size if filepath.exists() else 0
                    size_mb = size_bytes / (1024 * 1024)
                    segment_duration = elapsed

                    logger.info(
                        f"Recording completed: {segment_filename} ({size_mb:.1f} MB)"
                    )

                    await self._notify(
                        self._on_complete,
                        f"✅ Recording completed\n\nFile: `{segment_filename}`\n"
                        f"Size: {size_mb:.1f} MB",
                    )

                    session_segments.append(
                        RecordingSegmentResult(
                            success=True,
                            filename=segment_filename,
                            filepath=filepath,
                            duration=segment_duration,
                            size_bytes=size_bytes,
                            partial=False,
                        )
                    )

                    recorded_duration += segment_duration
                    remaining_duration = 0
                    retry_deadline = None
                else:
                    size_bytes = filepath.stat().st_size if filepath.exists() else 0
                    segment_duration = min(remaining_duration, elapsed)
                    retryable = self._is_retryable_error(error_msg)

                    if size_bytes > 0:
                        size_mb = size_bytes / (1024 * 1024)
                        logger.warning(
                            f"Recording interrupted: {segment_filename} "
                            f"({size_mb:.1f} MB)"
                        )

                        await self._notify(
                            self._on_complete,
                            f"⚠️ Recording interrupted\n\nFile: `{segment_filename}`\n"
                            f"Size: {size_mb:.1f} MB",
                        )

                        session_segments.append(
                            RecordingSegmentResult(
                                success=True,
                                filename=segment_filename,
                                filepath=filepath,
                                duration=segment_duration,
                                size_bytes=size_bytes,
                                error=error_msg[:200] if error_msg else None,
                                partial=True,
                            )
                        )

                        recorded_duration += segment_duration
                        remaining_duration = max(0, remaining_duration - segment_duration)

                    if size_bytes == 0:
                        remaining_duration = max(0, remaining_duration - elapsed)
                        if remaining_duration == 0:
                            logger.error("No data recorded, stopping")
                            break

                    if not retryable:
                        logger.error(f"Recording failed: {error_msg}")
                        await self._notify(
                            self._on_error,
                            f"❌ Recording failed\n\nFile: `{segment_filename}`\n"
                            f"Error: {error_msg[:200]}",
                        )
                        break

                    if retry_deadline is None:
                        retry_deadline = time.monotonic() + retry_max_seconds

                    now = time.monotonic()
                    if retry_max_seconds == 0 or now >= retry_deadline:
                        logger.error("Retry window exceeded, stopping recording")
                        await self._notify(
                            self._on_error,
                            "❌ Recording stopped\n\nReason: retry window exceeded",
                        )
                        break

                    wait_seconds = min(retry_delay, max(1, int(retry_deadline - now)))
                    logger.warning(
                        f"Stream dropped, retrying in {wait_seconds}s "
                        f"(remaining window: {int(retry_deadline - now)}s)"
                    )
                    await self._notify(
                        self._on_error,
                        f"⚠️ Stream dropped\n\nRetrying in {wait_seconds}s",
                    )
                    await asyncio.sleep(wait_seconds)

            success = remaining_duration == 0
            error = None if success else "Recording incomplete"

            return RecordingSessionResult(
                success=success,
                segments=session_segments,
                requested_duration=duration,
                recorded_duration=recorded_duration,
                error=error,
            )

        except asyncio.CancelledError:
            if self.current_process:
                self.current_process.terminate()
                await self.current_process.wait()

            logger.warning("Recording cancelled")
            return RecordingSessionResult(
                success=False,
                segments=session_segments,
                requested_duration=duration,
                recorded_duration=recorded_duration,
                error="Recording cancelled",
            )

        except Exception as e:
            logger.exception(f"Recording error: {e}")
            await self._notify(
                self._on_error,
                f"❌ Recording error\n\nError: {str(e)}",
            )
            return RecordingSessionResult(
                success=False,
                segments=session_segments,
                requested_duration=duration,
                recorded_duration=recorded_duration,
                error=str(e),
            )

        finally:
            self.is_recording = False
            self.current_process = None

    async def test_record(self) -> RecordingSessionResult:
        """
        Perform a test recording with the configured test duration.
        
        This is a convenience method that calls record() with is_test=True.
        
        Returns:
            RecordingSessionResult with test recording details
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
