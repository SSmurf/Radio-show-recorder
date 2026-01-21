"""
Cloud upload module for Radio Show Recorder.

This module handles uploading recordings to pCloud via rclone,
with verification and automatic cleanup of local files after
successful upload.
"""

import asyncio
import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """
    Result of an upload operation.
    
    Attributes:
        success: Whether the upload completed successfully
        filename: Name of the uploaded file
        remote_path: Full path on the remote storage
        verified: Whether the upload was verified on remote
        local_deleted: Whether the local file was deleted after upload
        error: Error message if upload failed
    """
    success: bool
    filename: str
    remote_path: str
    verified: bool = False
    local_deleted: bool = False
    error: Optional[str] = None


# Type alias for notification callbacks
NotifyCallback = Callable[[str], Awaitable[None]]


class Uploader:
    """
    Handles uploading recordings to pCloud via rclone.
    
    This class provides methods to upload files, verify uploads,
    and optionally clean up local files after successful upload.
    
    Attributes:
        config: Configuration object with remote settings
    """

    def __init__(self):
        """Initialize the uploader with configuration."""
        self.config = get_config()
        self._on_complete: Optional[NotifyCallback] = None
        self._on_error: Optional[NotifyCallback] = None

    def set_callbacks(
        self,
        on_complete: Optional[NotifyCallback] = None,
        on_error: Optional[NotifyCallback] = None,
    ) -> None:
        """
        Set notification callbacks for upload events.
        
        Args:
            on_complete: Called when upload completes successfully
            on_error: Called when upload fails
        """
        self._on_complete = on_complete
        self._on_error = on_error

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

    async def _run_rclone(self, *args: str) -> tuple[int, str, str]:
        """
        Run an rclone command asynchronously.
        
        Args:
            *args: Arguments to pass to rclone
            
        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        command = ["rclone", *args]
        logger.debug(f"Running rclone command: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await process.communicate()
        return (
            process.returncode or 0,
            stdout.decode() if stdout else "",
            stderr.decode() if stderr else "",
        )

    async def verify_remote(self, filename: str) -> bool:
        """
        Verify that a file exists on the remote storage.
        
        Args:
            filename: Name of the file to verify
            
        Returns:
            True if file exists on remote, False otherwise
        """
        remote_path = f"{self.config.pcloud_remote}/{filename}"
        
        returncode, stdout, stderr = await self._run_rclone(
            "ls", remote_path
        )
        
        if returncode == 0 and filename in stdout:
            logger.info(f"Verified remote file: {remote_path}")
            return True
        
        logger.warning(f"Remote verification failed for: {remote_path}")
        return False

    async def upload(
        self,
        filepath: Path,
        delete_after: Optional[bool] = None,
    ) -> UploadResult:
        """
        Upload a file to pCloud via rclone.
        
        This method uploads the specified file to the configured remote,
        verifies the upload, and optionally deletes the local file.
        
        Args:
            filepath: Path to the local file to upload
            delete_after: Whether to delete local file after upload.
                         If None, uses config.dynamic.cleanup_enabled.
            
        Returns:
            UploadResult with upload details and status
        """
        if not filepath.exists():
            return UploadResult(
                success=False,
                filename=filepath.name,
                remote_path="",
                error=f"File not found: {filepath}",
            )

        filename = filepath.name
        remote_path = f"{self.config.pcloud_remote}/{filename}"
        
        # Get file size for logging
        size_bytes = filepath.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        logger.info(f"Starting upload: {filename} ({size_mb:.1f} MB)")

        try:
            # Upload using rclone copy
            returncode, stdout, stderr = await self._run_rclone(
                "copy",
                str(filepath),
                self.config.pcloud_remote,
                "--progress",
            )

            if returncode != 0:
                error_msg = stderr or "Upload failed with unknown error"
                logger.error(f"Upload failed: {error_msg}")
                
                await self._notify(
                    self._on_error,
                    f"❌ Upload failed\n\nFile: `{filename}`\nError: {error_msg[:200]}",
                )

                return UploadResult(
                    success=False,
                    filename=filename,
                    remote_path=remote_path,
                    error=error_msg,
                )

            logger.info(f"Upload completed: {filename}")

            # Verify the upload
            verified = await self.verify_remote(filename)

            # Determine if we should delete local file
            should_delete = (
                delete_after
                if delete_after is not None
                else self.config.dynamic.cleanup_enabled
            )

            local_deleted = False
            if should_delete and verified:
                try:
                    filepath.unlink()
                    local_deleted = True
                    logger.info(f"Deleted local file: {filepath}")
                except OSError as e:
                    logger.error(f"Failed to delete local file: {e}")

            # Notify completion
            status_parts = [
                f"☁️ Upload completed",
                f"",
                f"File: `{filename}`",
                f"Size: {size_mb:.1f} MB",
                f"Remote: `{remote_path}`",
                f"Verified: {'✅' if verified else '⚠️'}",
            ]
            
            if local_deleted:
                status_parts.append("Local file: 🗑️ Deleted")

            await self._notify(self._on_complete, "\n".join(status_parts))

            return UploadResult(
                success=True,
                filename=filename,
                remote_path=remote_path,
                verified=verified,
                local_deleted=local_deleted,
            )

        except Exception as e:
            logger.exception(f"Upload error: {e}")
            
            await self._notify(
                self._on_error,
                f"❌ Upload error\n\nFile: `{filename}`\nError: {str(e)}",
            )

            return UploadResult(
                success=False,
                filename=filename,
                remote_path=remote_path,
                error=str(e),
            )

    async def list_remote(self, limit: int = 10) -> list[dict]:
        """
        List recent files on the remote storage.
        
        Args:
            limit: Maximum number of files to return
            
        Returns:
            List of dictionaries with file info (name, size, modified)
        """
        returncode, stdout, stderr = await self._run_rclone(
            "lsjson",
            self.config.pcloud_remote,
            "--files-only",
        )

        if returncode != 0:
            logger.error(f"Failed to list remote: {stderr}")
            return []

        try:
            import json
            files = json.loads(stdout)
            
            # Sort by modification time (newest first)
            files.sort(key=lambda x: x.get("ModTime", ""), reverse=True)
            
            return [
                {
                    "name": f["Name"],
                    "size": f.get("Size", 0),
                    "modified": f.get("ModTime", ""),
                }
                for f in files[:limit]
            ]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse remote listing: {e}")
            return []

    async def get_remote_usage(self) -> Optional[dict]:
        """
        Get storage usage information from the remote.
        
        Returns:
            Dictionary with used/total/free space, or None on error
        """
        returncode, stdout, stderr = await self._run_rclone(
            "about",
            self.config.pcloud_remote,
            "--json",
        )

        if returncode != 0:
            logger.error(f"Failed to get remote usage: {stderr}")
            return None

        try:
            import json
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse remote usage: {e}")
            return None


# Global uploader instance
_uploader: Optional[Uploader] = None


def get_uploader() -> Uploader:
    """
    Get the global uploader instance.
    
    Creates the instance on first call (lazy initialization).
    
    Returns:
        The global Uploader instance
    """
    global _uploader
    if _uploader is None:
        _uploader = Uploader()
    return _uploader
