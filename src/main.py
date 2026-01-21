"""
Main entry point for Radio Show Recorder.

This module initializes and coordinates all components of the application:
- Configuration loading
- Telegram bot startup
- Recording scheduler
- Signal handling for graceful shutdown
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

from .config import get_config
from .recorder import get_recorder
from .uploader import get_uploader
from .scheduler import get_scheduler
from .bot import get_bot
from .utils import setup_logging, check_disk_space_warning

logger = logging.getLogger(__name__)


class RadioRecorderApp:
    """
    Main application class that coordinates all components.
    
    This class handles the lifecycle of the recorder, scheduler,
    and Telegram bot, including graceful shutdown on signals.
    
    Attributes:
        config: Application configuration
        bot: Telegram bot instance
        scheduler: Recording scheduler instance
        recorder: Recorder instance
        uploader: Uploader instance
    """

    def __init__(self):
        """Initialize the application components."""
        self.config = get_config()
        self.bot = get_bot()
        self.scheduler = get_scheduler()
        self.recorder = get_recorder()
        self.uploader = get_uploader()
        self._shutdown_event: Optional[asyncio.Event] = None
        self._is_shutting_down: bool = False

    def _setup_callbacks(self) -> None:
        """Set up notification callbacks between components."""
        # Recorder callbacks -> Bot notifications
        self.recorder.set_callbacks(
            on_start=self.bot.notify,
            on_complete=self.bot.notify,
            on_error=self.bot.notify,
        )
        
        # Uploader callbacks -> Bot notifications
        self.uploader.set_callbacks(
            on_complete=self.bot.notify,
            on_error=self.bot.notify,
        )

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(self._handle_signal(s)),
            )
        
        logger.info("Signal handlers registered (SIGTERM, SIGINT)")

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """
        Handle shutdown signals gracefully.
        
        Args:
            sig: The signal received
        """
        if self._is_shutting_down:
            logger.warning("Shutdown already in progress, forcing exit...")
            sys.exit(1)
        
        self._is_shutting_down = True
        logger.info(f"Received signal {sig.name}, initiating graceful shutdown...")
        
        if self._shutdown_event:
            self._shutdown_event.set()

    async def _check_disk_space_periodic(self) -> None:
        """Periodically check disk space and send warnings."""
        while not self._shutdown_event.is_set():
            try:
                warning = check_disk_space_warning(threshold_gb=5.0)
                if warning:
                    await self.bot.notify(warning)
            except Exception as e:
                logger.error(f"Disk space check failed: {e}")
            
            # Check every hour
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=3600,
                )
                break  # Event was set, exit loop
            except asyncio.TimeoutError:
                pass  # Continue checking

    async def start(self) -> None:
        """
        Start all application components.
        
        This starts the Telegram bot, recording scheduler,
        and begins the main event loop.
        """
        logger.info("=" * 50)
        logger.info("Radio Show Recorder starting...")
        logger.info("=" * 50)
        
        # Log configuration
        logger.info(f"Stream URL: {self.config.stream_url}")
        logger.info(f"Upload to: {self.config.pcloud_remote}")
        logger.info(f"Timezone: {self.config.timezone}")
        logger.info(f"Schedules: {len(self.config.dynamic.schedules)}")
        
        # Set up callbacks
        self._setup_callbacks()
        
        # Create shutdown event
        self._shutdown_event = asyncio.Event()
        
        # Set up signal handlers
        self._setup_signal_handlers()
        
        try:
            # Start Telegram bot
            await self.bot.start()
            
            # Start scheduler
            await self.scheduler.start()
            
            # Start disk space monitor
            disk_check_task = asyncio.create_task(
                self._check_disk_space_periodic()
            )
            
            logger.info("All components started successfully")
            logger.info("=" * 50)
            
            # Log next scheduled recordings
            next_runs = self.scheduler.get_next_runs(3)
            if next_runs:
                logger.info("Upcoming recordings:")
                for run in next_runs:
                    logger.info(f"  - {run['next_run'].strftime('%a %b %d %H:%M')}")
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
            # Cancel disk check task
            disk_check_task.cancel()
            try:
                await disk_check_task
            except asyncio.CancelledError:
                pass
            
        except Exception as e:
            logger.exception(f"Fatal error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        """
        Stop all application components gracefully.
        
        This stops the scheduler, bot, and waits for any
        in-progress operations to complete.
        """
        logger.info("Shutting down...")
        
        # Check if recording in progress
        if self.recorder.is_recording:
            logger.warning("Recording in progress, waiting for completion...")
            await self.bot.notify("⚠️ Shutdown requested, waiting for recording to complete...")
            
            # Wait up to 30 seconds for recording to complete
            for _ in range(30):
                if not self.recorder.is_recording:
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("Recording still in progress, stopping forcefully")
                await self.recorder.stop()
        
        # Stop scheduler
        await self.scheduler.stop()
        
        # Stop bot (this sends shutdown notification)
        await self.bot.stop()
        
        logger.info("Shutdown complete")


async def main() -> None:
    """
    Main entry point for the application.
    
    This function sets up logging and runs the application.
    """
    # Set up logging
    setup_logging(level=logging.INFO)
    
    # Create and run the application
    app = RadioRecorderApp()
    
    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Application error: {e}")
        sys.exit(1)


def run() -> None:
    """
    Synchronous entry point for the application.
    
    This function runs the async main() in an event loop.
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
