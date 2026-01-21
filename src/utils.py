"""
Utility functions for Radio Show Recorder.

This module provides common utility functions including logging setup,
disk space monitoring, and other helper functions used across the application.
"""

import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

from .config import get_config


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure logging for the application.
    
    Sets up formatted logging to stdout with timestamps and module names.
    
    Args:
        level: Logging level (default: INFO)
    """
    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add stdout handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def get_disk_usage(path: Optional[Path] = None) -> dict:
    """
    Get disk usage information for the specified path.
    
    Args:
        path: Path to check. Defaults to recordings directory.
        
    Returns:
        Dictionary with total, used, free space and percentages
    """
    if path is None:
        path = get_config().recordings_dir
    
    usage = shutil.disk_usage(path)
    
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "total_gb": usage.total / (1024 ** 3),
        "used_gb": usage.used / (1024 ** 3),
        "free_gb": usage.free / (1024 ** 3),
        "used_percent": (usage.used / usage.total) * 100,
        "free_percent": (usage.free / usage.total) * 100,
    }


def format_bytes(num_bytes: int) -> str:
    """
    Format bytes into a human-readable string.
    
    Args:
        num_bytes: Number of bytes
        
    Returns:
        Formatted string (e.g., "1.5 GB", "500 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def format_duration(seconds: int) -> str:
    """
    Format seconds into a human-readable duration string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., "2h 30m", "45m 15s")
    """
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not hours:  # Don't show seconds if we have hours
        parts.append(f"{secs}s")
    
    return " ".join(parts) if parts else "0s"


def check_disk_space_warning(threshold_gb: float = 5.0) -> Optional[str]:
    """
    Check if disk space is below a warning threshold.
    
    Args:
        threshold_gb: Warning threshold in gigabytes
        
    Returns:
        Warning message if below threshold, None otherwise
    """
    usage = get_disk_usage()
    
    if usage["free_gb"] < threshold_gb:
        return (
            f"⚠️ Low disk space warning!\n"
            f"Only {usage['free_gb']:.1f} GB free "
            f"({usage['free_percent']:.0f}% of {usage['total_gb']:.0f} GB)"
        )
    
    return None


def clean_old_recordings(max_age_days: int = 7, dry_run: bool = True) -> list[Path]:
    """
    Find recordings older than the specified age.
    
    Args:
        max_age_days: Maximum age in days
        dry_run: If True, only return files without deleting
        
    Returns:
        List of files that are/would be deleted
    """
    import time
    
    config = get_config()
    recordings_dir = config.recordings_dir
    
    if not recordings_dir.exists():
        return []
    
    max_age_seconds = max_age_days * 24 * 60 * 60
    current_time = time.time()
    old_files = []
    
    for filepath in recordings_dir.glob("*.mp3"):
        file_age = current_time - filepath.stat().st_mtime
        if file_age > max_age_seconds:
            old_files.append(filepath)
            if not dry_run:
                filepath.unlink()
    
    return old_files
