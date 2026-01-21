"""
Configuration management for Radio Show Recorder.

This module implements a two-tier configuration system:
1. Static settings from environment variables (.env file)
2. Dynamic settings from user_config.json (changeable via Telegram)

Static settings are security-sensitive and cannot be changed at runtime.
Dynamic settings can be modified through Telegram commands and persist across restarts.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
USER_CONFIG_PATH = DATA_DIR / "user_config.json"


@dataclass
class Schedule:
    """Represents a single recording schedule."""
    id: str
    day: str  # mon, tue, wed, thu, fri, sat, sun
    time: str  # HH:MM format
    duration: int  # seconds
    enabled: bool = True

    def to_dict(self) -> dict:
        """Convert schedule to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        """Create schedule from dictionary."""
        return cls(**data)


@dataclass
class DynamicConfig:
    """
    Dynamic configuration that can be changed via Telegram.
    
    These settings are persisted to user_config.json and can be modified
    at runtime through bot commands.
    """
    schedules: list[Schedule] = field(default_factory=list)
    cleanup_enabled: bool = True
    notifications_enabled: bool = True
    test_duration: int = 15  # seconds

    def to_dict(self) -> dict:
        """Convert config to dictionary for JSON serialization."""
        return {
            "schedules": [s.to_dict() for s in self.schedules],
            "cleanup_enabled": self.cleanup_enabled,
            "notifications_enabled": self.notifications_enabled,
            "test_duration": self.test_duration,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DynamicConfig":
        """Create config from dictionary."""
        schedules = [Schedule.from_dict(s) for s in data.get("schedules", [])]
        return cls(
            schedules=schedules,
            cleanup_enabled=data.get("cleanup_enabled", True),
            notifications_enabled=data.get("notifications_enabled", True),
            test_duration=data.get("test_duration", 15),
        )


class Config:
    """
    Main configuration class combining static and dynamic settings.
    
    Static settings are loaded from environment variables once at startup.
    Dynamic settings can be modified and are auto-saved to user_config.json.
    
    Attributes:
        stream_url: URL of the radio stream to record
        pcloud_remote: rclone remote path for uploads
        telegram_bot_token: Telegram bot API token
        telegram_chat_id: Chat ID for notifications
        timezone: Timezone for scheduling (e.g., Europe/Zagreb)
        default_duration: Default recording duration in seconds
        default_schedule: Default schedule string (fallback)
        dynamic: Dynamic configuration object
    """

    def __init__(self):
        """Initialize configuration from environment and user config file."""
        # Static settings from environment
        self.stream_url: str = os.getenv(
            "STREAM_URL", 
            "https://stream.yammat.fm/radio/8000/yammat.mp3"
        )
        self.pcloud_remote: str = os.getenv(
            "PCLOUD_REMOTE", 
            "pcloud:Radio recordings"
        )
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
        self.timezone: str = os.getenv("TZ", "Europe/Zagreb")
        self.default_duration: int = int(os.getenv("DEFAULT_DURATION", "28800"))
        self.default_schedule: str = os.getenv("DEFAULT_SCHEDULE", "friday:20:55:28800")
        
        # Recording output directory
        self.recordings_dir: Path = BASE_DIR / "recordings"
        self.recordings_dir.mkdir(exist_ok=True)
        
        # Ensure data directory exists
        DATA_DIR.mkdir(exist_ok=True)
        
        # Load dynamic settings
        self.dynamic = self._load_dynamic_config()
        
        # Callbacks for config changes
        self._on_schedule_change: Optional[Callable] = None
        
        logger.info("Configuration loaded successfully")

    def _load_dynamic_config(self) -> DynamicConfig:
        """
        Load dynamic configuration from user_config.json.
        
        If the file doesn't exist or is invalid, creates default config
        with schedules parsed from DEFAULT_SCHEDULE environment variable.
        
        Returns:
            DynamicConfig object with loaded or default settings
        """
        if USER_CONFIG_PATH.exists():
            try:
                with open(USER_CONFIG_PATH, "r") as f:
                    data = json.load(f)
                logger.info(f"Loaded dynamic config from {USER_CONFIG_PATH}")
                return DynamicConfig.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid user config file, using defaults: {e}")
        
        # Create default config from DEFAULT_SCHEDULE
        config = DynamicConfig()
        if self.default_schedule:
            schedules = self._parse_default_schedule(self.default_schedule)
            config.schedules = schedules
        
        # Save the default config
        self._save_dynamic_config(config)
        return config

    def _parse_default_schedule(self, schedule_str: str) -> list[Schedule]:
        """
        Parse DEFAULT_SCHEDULE environment variable into Schedule objects.
        
        Format: day:time:duration (comma-separated for multiple)
        Example: "friday:20:55:28800,sunday:19:00:1800"
        
        Args:
            schedule_str: Schedule string in the specified format
            
        Returns:
            List of Schedule objects
        """
        schedules = []
        for i, part in enumerate(schedule_str.split(",")):
            try:
                parts = part.strip().split(":")
                if len(parts) >= 3:
                    day = parts[0].lower()[:3]  # Normalize to 3-letter day
                    time = f"{parts[1]}:{parts[2]}"
                    duration = int(parts[3]) if len(parts) > 3 else self.default_duration
                    
                    schedules.append(Schedule(
                        id=f"default_{i}",
                        day=day,
                        time=time,
                        duration=duration,
                    ))
            except (ValueError, IndexError) as e:
                logger.warning(f"Failed to parse schedule '{part}': {e}")
        
        return schedules

    def _save_dynamic_config(self, config: Optional[DynamicConfig] = None) -> None:
        """
        Save dynamic configuration to user_config.json.
        
        Args:
            config: Config to save, defaults to self.dynamic
        """
        config = config or self.dynamic
        try:
            with open(USER_CONFIG_PATH, "w") as f:
                json.dump(config.to_dict(), f, indent=2)
            logger.info(f"Saved dynamic config to {USER_CONFIG_PATH}")
        except IOError as e:
            logger.error(f"Failed to save config: {e}")

    def set_on_schedule_change(self, callback: Callable) -> None:
        """
        Register a callback to be called when schedules change.
        
        Args:
            callback: Function to call when schedules are modified
        """
        self._on_schedule_change = callback

    def add_schedule(self, day: str, time: str, duration: int) -> Schedule:
        """
        Add a new recording schedule.
        
        Args:
            day: Day of week (mon, tue, wed, thu, fri, sat, sun)
            time: Time in HH:MM format
            duration: Recording duration in seconds
            
        Returns:
            The newly created Schedule object
        """
        schedule_id = f"user_{len(self.dynamic.schedules)}"
        schedule = Schedule(id=schedule_id, day=day.lower()[:3], time=time, duration=duration)
        self.dynamic.schedules.append(schedule)
        self._save_dynamic_config()
        
        if self._on_schedule_change:
            self._on_schedule_change()
        
        logger.info(f"Added schedule: {schedule}")
        return schedule

    def remove_schedule(self, schedule_id: str) -> bool:
        """
        Remove a schedule by ID.
        
        Args:
            schedule_id: ID of the schedule to remove
            
        Returns:
            True if schedule was removed, False if not found
        """
        for i, schedule in enumerate(self.dynamic.schedules):
            if schedule.id == schedule_id:
                self.dynamic.schedules.pop(i)
                self._save_dynamic_config()
                
                if self._on_schedule_change:
                    self._on_schedule_change()
                
                logger.info(f"Removed schedule: {schedule_id}")
                return True
        return False

    def set_cleanup_enabled(self, enabled: bool) -> None:
        """
        Enable or disable automatic cleanup after upload.
        
        Args:
            enabled: Whether to auto-delete local files after upload
        """
        self.dynamic.cleanup_enabled = enabled
        self._save_dynamic_config()
        logger.info(f"Cleanup enabled: {enabled}")

    def set_notifications_enabled(self, enabled: bool) -> None:
        """
        Enable or disable Telegram notifications.
        
        Args:
            enabled: Whether to send notifications
        """
        self.dynamic.notifications_enabled = enabled
        self._save_dynamic_config()
        logger.info(f"Notifications enabled: {enabled}")

    def set_test_duration(self, seconds: int) -> None:
        """
        Set the duration for test recordings.
        
        Args:
            seconds: Duration in seconds (must be positive)
        """
        if seconds > 0:
            self.dynamic.test_duration = seconds
            self._save_dynamic_config()
            logger.info(f"Test duration set to: {seconds}s")

    def get_config_summary(self) -> str:
        """
        Get a human-readable summary of current configuration.
        
        Returns:
            Formatted string with current settings
        """
        schedules_str = "\n".join(
            f"  - [{s.id}] {s.day} {s.time} ({s.duration}s)"
            for s in self.dynamic.schedules
        ) or "  No schedules configured"
        
        return f"""📻 Radio Recorder Configuration

Stream: {self.stream_url}
Upload to: {self.pcloud_remote}
Timezone: {self.timezone}

Schedules:
{schedules_str}

Settings:
  - Cleanup after upload: {'✅' if self.dynamic.cleanup_enabled else '❌'}
  - Notifications: {'✅' if self.dynamic.notifications_enabled else '❌'}
  - Test duration: {self.dynamic.test_duration}s"""


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance.
    
    Creates the instance on first call (lazy initialization).
    
    Returns:
        The global Config instance
    """
    global _config
    if _config is None:
        _config = Config()
    return _config
