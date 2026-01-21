"""
Recording scheduler module for Radio Show Recorder.

This module manages scheduled recordings using APScheduler.
It supports dynamic schedule updates via Telegram commands
and automatically reloads when the configuration changes.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job

from .config import get_config, Schedule
from .recorder import get_recorder, RecordingResult
from .uploader import get_uploader

logger = logging.getLogger(__name__)

# Day name mappings
DAY_MAP = {
    "mon": "0",
    "tue": "1",
    "wed": "2",
    "thu": "3",
    "fri": "4",
    "sat": "5",
    "sun": "6",
}

DAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


class RecordingScheduler:
    """
    Manages scheduled recordings using APScheduler.
    
    This class handles creating, updating, and removing recording jobs
    based on the configuration. It integrates with the recorder and
    uploader modules to perform the actual recording and upload.
    
    Attributes:
        scheduler: The APScheduler instance
        config: Configuration object
    """

    def __init__(self):
        """Initialize the scheduler with configuration."""
        self.config = get_config()
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._recording_callback: Optional[Callable[[RecordingResult], Awaitable[None]]] = None
        
        # Register config change callback
        self.config.set_on_schedule_change(self._on_schedule_change)

    def set_recording_callback(
        self,
        callback: Callable[[RecordingResult], Awaitable[None]],
    ) -> None:
        """
        Set a callback to be called after each scheduled recording.
        
        Args:
            callback: Async function to call with RecordingResult
        """
        self._recording_callback = callback

    def _on_schedule_change(self) -> None:
        """Handle schedule configuration changes by reloading jobs."""
        if self.scheduler and self.scheduler.running:
            logger.info("Schedule configuration changed, reloading jobs")
            asyncio.create_task(self._reload_jobs())

    async def _reload_jobs(self) -> None:
        """Reload all scheduled jobs from configuration."""
        if not self.scheduler:
            return
        
        # Remove all existing recording jobs
        for job in self.scheduler.get_jobs():
            if job.id.startswith("recording_"):
                job.remove()
        
        # Add jobs from current config
        self._add_jobs_from_config()

    def _add_jobs_from_config(self) -> None:
        """Add all scheduled jobs from the current configuration."""
        if not self.scheduler:
            return
        
        for schedule in self.config.dynamic.schedules:
            if schedule.enabled:
                self._add_job(schedule)

    def _add_job(self, schedule: Schedule) -> Optional[Job]:
        """
        Add a single recording job to the scheduler.
        
        Args:
            schedule: Schedule object with day, time, duration
            
        Returns:
            The created Job, or None if creation failed
        """
        if not self.scheduler:
            return None
        
        try:
            # Parse time
            hour, minute = schedule.time.split(":")
            day_of_week = DAY_MAP.get(schedule.day, schedule.day)
            
            # Get timezone
            tz = ZoneInfo(self.config.timezone)
            
            # Create cron trigger
            trigger = CronTrigger(
                day_of_week=day_of_week,
                hour=int(hour),
                minute=int(minute),
                timezone=tz,
            )
            
            # Add job
            job = self.scheduler.add_job(
                self._run_scheduled_recording,
                trigger=trigger,
                id=f"recording_{schedule.id}",
                args=[schedule],
                replace_existing=True,
            )
            
            logger.info(
                f"Added scheduled recording: {schedule.id} "
                f"({DAY_NAMES.get(schedule.day, schedule.day)} at {schedule.time})"
            )
            
            return job
            
        except Exception as e:
            logger.error(f"Failed to add schedule {schedule.id}: {e}")
            return None

    async def _run_scheduled_recording(self, schedule: Schedule) -> None:
        """
        Execute a scheduled recording.
        
        This method is called by APScheduler when a scheduled time is reached.
        It records the stream and uploads the result to pCloud.
        
        Args:
            schedule: The schedule being executed
        """
        logger.info(f"Starting scheduled recording: {schedule.id}")
        
        recorder = get_recorder()
        uploader = get_uploader()
        
        # Perform the recording
        result = await recorder.record(duration=schedule.duration)
        
        if result.success:
            # Upload the recording
            upload_result = await uploader.upload(result.filepath)
            
            if not upload_result.success:
                logger.error(f"Upload failed for scheduled recording: {schedule.id}")
        else:
            logger.error(f"Scheduled recording failed: {schedule.id}")
        
        # Call the callback if set
        if self._recording_callback:
            try:
                await self._recording_callback(result)
            except Exception as e:
                logger.error(f"Recording callback failed: {e}")

    async def start(self) -> None:
        """
        Start the scheduler.
        
        This initializes the APScheduler instance, adds all configured
        jobs, and starts the scheduler.
        """
        if self.scheduler and self.scheduler.running:
            logger.warning("Scheduler is already running")
            return
        
        # Create scheduler with timezone
        tz = ZoneInfo(self.config.timezone)
        self.scheduler = AsyncIOScheduler(timezone=tz)
        
        # Add jobs from configuration
        self._add_jobs_from_config()
        
        # Start the scheduler
        self.scheduler.start()
        logger.info(f"Scheduler started (timezone: {self.config.timezone})")

    async def stop(self) -> None:
        """
        Stop the scheduler gracefully.
        
        This shuts down the scheduler and waits for any running
        jobs to complete.
        """
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")
        
        self.scheduler = None

    def get_next_runs(self, limit: int = 5) -> list[dict]:
        """
        Get the next scheduled recording times.
        
        Args:
            limit: Maximum number of upcoming runs to return
            
        Returns:
            List of dictionaries with job info (id, schedule, next_run)
        """
        if not self.scheduler:
            return []
        
        jobs = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith("recording_"):
                next_run = job.next_run_time
                if next_run:
                    schedule_id = job.id.replace("recording_", "")
                    
                    # Find the schedule
                    schedule = next(
                        (s for s in self.config.dynamic.schedules if s.id == schedule_id),
                        None,
                    )
                    
                    jobs.append({
                        "id": schedule_id,
                        "next_run": next_run,
                        "day": schedule.day if schedule else "unknown",
                        "time": schedule.time if schedule else "unknown",
                        "duration": schedule.duration if schedule else 0,
                    })
        
        # Sort by next run time
        jobs.sort(key=lambda x: x["next_run"])
        
        return jobs[:limit]

    def get_status(self) -> dict:
        """
        Get the current status of the scheduler.
        
        Returns:
            Dictionary with scheduler status information
        """
        running = self.scheduler.running if self.scheduler else False
        job_count = len(self.scheduler.get_jobs()) if self.scheduler else 0
        
        return {
            "running": running,
            "job_count": job_count,
            "timezone": self.config.timezone,
            "next_runs": self.get_next_runs(3),
        }

    def format_next_runs(self) -> str:
        """
        Get a formatted string of upcoming recordings.
        
        Returns:
            Human-readable string of next scheduled recordings
        """
        next_runs = self.get_next_runs()
        
        if not next_runs:
            return "No scheduled recordings"
        
        lines = ["📅 Upcoming Recordings:\n"]
        
        for run in next_runs:
            next_time = run["next_run"]
            duration_hours = run["duration"] / 3600
            
            # Format the datetime
            time_str = next_time.strftime("%a %b %d, %H:%M")
            
            lines.append(
                f"• {time_str} ({duration_hours:.1f}h)"
            )
        
        return "\n".join(lines)


# Global scheduler instance
_scheduler: Optional[RecordingScheduler] = None


def get_scheduler() -> RecordingScheduler:
    """
    Get the global scheduler instance.
    
    Creates the instance on first call (lazy initialization).
    
    Returns:
        The global RecordingScheduler instance
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = RecordingScheduler()
    return _scheduler
