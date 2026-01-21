"""
Telegram bot module for Radio Show Recorder.

This module provides a Telegram bot interface for controlling and
monitoring the radio recorder. It supports info commands, configuration
commands, and sends automatic notifications for recording events.
"""

import asyncio
import logging
import shutil
from typing import Optional

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import get_config
from .recorder import get_recorder
from .uploader import get_uploader
from .scheduler import get_scheduler

logger = logging.getLogger(__name__)


def parse_duration(duration_str: str) -> int:
    """
    Parse a duration string into seconds.
    
    Supports formats like: 30, 30s, 5m, 2h, 1h30m
    
    Args:
        duration_str: Duration string to parse
        
    Returns:
        Duration in seconds
        
    Raises:
        ValueError: If the format is invalid
    """
    duration_str = duration_str.lower().strip()
    
    # Pure number = seconds
    if duration_str.isdigit():
        return int(duration_str)
    
    total_seconds = 0
    current_num = ""
    
    for char in duration_str:
        if char.isdigit():
            current_num += char
        elif char == "h" and current_num:
            total_seconds += int(current_num) * 3600
            current_num = ""
        elif char == "m" and current_num:
            total_seconds += int(current_num) * 60
            current_num = ""
        elif char == "s" and current_num:
            total_seconds += int(current_num)
            current_num = ""
    
    # Handle trailing number (assumed seconds)
    if current_num:
        total_seconds += int(current_num)
    
    if total_seconds == 0:
        raise ValueError(f"Invalid duration format: {duration_str}")
    
    return total_seconds


class RadioBot:
    """
    Telegram bot for controlling the Radio Show Recorder.
    
    This class handles all bot commands and provides notification
    methods for recording events.
    
    Attributes:
        config: Configuration object
        app: Telegram Application instance
    """

    def __init__(self):
        """Initialize the bot with configuration."""
        self.config = get_config()
        self.app: Optional[Application] = None
        self._authorized_chat_id: str = self.config.telegram_chat_id

    def _is_authorized(self, update: Update) -> bool:
        """
        Check if the message is from an authorized chat.
        
        Args:
            update: Telegram update object
            
        Returns:
            True if authorized, False otherwise
        """
        if not self._authorized_chat_id:
            return True  # No restriction if chat ID not configured
        
        chat_id = str(update.effective_chat.id)
        return chat_id == self._authorized_chat_id

    async def _check_auth(self, update: Update) -> bool:
        """
        Check authorization and send error if not authorized.
        
        Args:
            update: Telegram update object
            
        Returns:
            True if authorized
        """
        if not self._is_authorized(update):
            await update.message.reply_text("⛔ Unauthorized")
            return False
        return True

    # ========== Info Commands ==========

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command - show welcome message."""
        if not await self._check_auth(update):
            return
        
        await update.message.reply_text(
            "🎙️ *Radio Show Recorder Bot*\n\n"
            "Use /help to see available commands.",
            parse_mode="Markdown",
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command - show available commands."""
        if not await self._check_auth(update):
            return
        
        help_text = """📻 *Radio Show Recorder Commands*

*Info Commands:*
/status - Show recorder status
/next - Show upcoming recordings
/test - Run a test recording

*Schedule Commands:*
/schedule list - Show all schedules
/schedule add <day> <time> <duration> - Add schedule
/schedule remove <id> - Remove schedule

*Config Commands:*
/cleanup on|off - Toggle auto-cleanup
/notify on|off - Toggle notifications
/testduration <seconds> - Set test duration
/config - Show current configuration

*Examples:*
`/schedule add fri 20:55 8h`
`/schedule add sun 19:00 30m`
`/testduration 30`"""
        
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command - show recorder status."""
        if not await self._check_auth(update):
            return
        
        recorder = get_recorder()
        scheduler = get_scheduler()
        
        # Get disk usage
        disk = shutil.disk_usage(self.config.recordings_dir)
        disk_free_gb = disk.free / (1024 ** 3)
        disk_total_gb = disk.total / (1024 ** 3)
        disk_percent = (disk.used / disk.total) * 100
        
        # Get scheduler status
        sched_status = scheduler.get_status()
        
        status_parts = [
            "📊 *Recorder Status*\n",
            f"Recording: {'🔴 Active' if recorder.is_recording else '⚪ Idle'}",
            f"Scheduler: {'✅ Running' if sched_status['running'] else '❌ Stopped'}",
            f"Scheduled jobs: {sched_status['job_count']}",
            f"\n💾 *Disk Space*",
            f"Free: {disk_free_gb:.1f} GB / {disk_total_gb:.1f} GB ({100-disk_percent:.0f}% free)",
        ]
        
        # Add next run info
        if sched_status["next_runs"]:
            next_run = sched_status["next_runs"][0]
            next_time = next_run["next_run"].strftime("%a %H:%M")
            status_parts.append(f"\n⏰ *Next Recording*")
            status_parts.append(f"{next_time}")
        
        await update.message.reply_text("\n".join(status_parts), parse_mode="Markdown")

    async def cmd_next(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /next command - show upcoming recordings."""
        if not await self._check_auth(update):
            return
        
        scheduler = get_scheduler()
        text = scheduler.format_next_runs()
        await update.message.reply_text(text)

    async def cmd_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /test command - run a test recording."""
        if not await self._check_auth(update):
            return
        
        recorder = get_recorder()
        
        if recorder.is_recording:
            await update.message.reply_text("⚠️ A recording is already in progress")
            return
        
        await update.message.reply_text(
            f"🎙️ Starting test recording ({self.config.dynamic.test_duration}s)..."
        )
        
        # Run test recording in background
        asyncio.create_task(self._run_test_recording())

    async def _run_test_recording(self) -> None:
        """Run a test recording and upload."""
        recorder = get_recorder()
        uploader = get_uploader()
        
        result = await recorder.test_record()
        
        if result.success:
            await uploader.upload(result.filepath)

    # ========== Schedule Commands ==========

    async def cmd_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /schedule command - manage recording schedules."""
        if not await self._check_auth(update):
            return
        
        args = context.args or []
        
        if not args:
            await update.message.reply_text(
                "Usage:\n"
                "/schedule list\n"
                "/schedule add <day> <time> <duration>\n"
                "/schedule remove <id>"
            )
            return
        
        subcommand = args[0].lower()
        
        if subcommand == "list":
            await self._schedule_list(update)
        elif subcommand == "add" and len(args) >= 4:
            await self._schedule_add(update, args[1], args[2], args[3])
        elif subcommand == "remove" and len(args) >= 2:
            await self._schedule_remove(update, args[1])
        else:
            await update.message.reply_text("Invalid command. Use /schedule for help.")

    async def _schedule_list(self, update: Update) -> None:
        """List all configured schedules."""
        schedules = self.config.dynamic.schedules
        
        if not schedules:
            await update.message.reply_text("No schedules configured.")
            return
        
        lines = ["📋 *Configured Schedules*\n"]
        
        for s in schedules:
            duration_h = s.duration / 3600
            status = "✅" if s.enabled else "❌"
            lines.append(f"{status} `{s.id}`: {s.day} {s.time} ({duration_h:.1f}h)")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _schedule_add(self, update: Update, day: str, time: str, duration_str: str) -> None:
        """Add a new schedule."""
        # Validate day
        day = day.lower()[:3]
        valid_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        
        if day not in valid_days:
            await update.message.reply_text(
                f"Invalid day: {day}\nUse: {', '.join(valid_days)}"
            )
            return
        
        # Validate time format
        try:
            parts = time.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
            time = f"{hour:02d}:{minute:02d}"
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid time format. Use HH:MM (e.g., 20:55)")
            return
        
        # Parse duration
        try:
            duration = parse_duration(duration_str)
        except ValueError:
            await update.message.reply_text(
                "Invalid duration. Use formats like: 30, 30s, 5m, 2h, 1h30m"
            )
            return
        
        # Add the schedule
        schedule = self.config.add_schedule(day, time, duration)
        
        duration_h = duration / 3600
        await update.message.reply_text(
            f"✅ Schedule added: `{schedule.id}`\n"
            f"📅 {day.capitalize()} at {time} ({duration_h:.1f}h)",
            parse_mode="Markdown",
        )

    async def _schedule_remove(self, update: Update, schedule_id: str) -> None:
        """Remove a schedule by ID."""
        if self.config.remove_schedule(schedule_id):
            await update.message.reply_text(f"✅ Schedule `{schedule_id}` removed", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Schedule `{schedule_id}` not found", parse_mode="Markdown")

    # ========== Config Commands ==========

    async def cmd_cleanup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cleanup command - toggle auto-cleanup."""
        if not await self._check_auth(update):
            return
        
        args = context.args or []
        
        if not args:
            status = "on" if self.config.dynamic.cleanup_enabled else "off"
            await update.message.reply_text(f"Cleanup is currently: {status}\nUse /cleanup on|off")
            return
        
        value = args[0].lower()
        
        if value in ("on", "true", "1", "yes"):
            self.config.set_cleanup_enabled(True)
            await update.message.reply_text("✅ Auto-cleanup enabled")
        elif value in ("off", "false", "0", "no"):
            self.config.set_cleanup_enabled(False)
            await update.message.reply_text("❌ Auto-cleanup disabled")
        else:
            await update.message.reply_text("Use /cleanup on|off")

    async def cmd_notify(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /notify command - toggle notifications."""
        if not await self._check_auth(update):
            return
        
        args = context.args or []
        
        if not args:
            status = "on" if self.config.dynamic.notifications_enabled else "off"
            await update.message.reply_text(f"Notifications are currently: {status}\nUse /notify on|off")
            return
        
        value = args[0].lower()
        
        if value in ("on", "true", "1", "yes"):
            self.config.set_notifications_enabled(True)
            await update.message.reply_text("✅ Notifications enabled")
        elif value in ("off", "false", "0", "no"):
            self.config.set_notifications_enabled(False)
            await update.message.reply_text("❌ Notifications disabled")
        else:
            await update.message.reply_text("Use /notify on|off")

    async def cmd_testduration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /testduration command - set test recording duration."""
        if not await self._check_auth(update):
            return
        
        args = context.args or []
        
        if not args:
            await update.message.reply_text(
                f"Test duration is: {self.config.dynamic.test_duration}s\n"
                "Use /testduration <seconds>"
            )
            return
        
        try:
            seconds = int(args[0])
            if seconds <= 0:
                raise ValueError()
            
            self.config.set_test_duration(seconds)
            await update.message.reply_text(f"✅ Test duration set to {seconds}s")
        except ValueError:
            await update.message.reply_text("Invalid duration. Use a positive number.")

    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /config command - show current configuration."""
        if not await self._check_auth(update):
            return
        
        summary = self.config.get_config_summary()
        await update.message.reply_text(summary)

    # ========== Notification Methods ==========

    async def notify(self, message: str) -> None:
        """
        Send a notification message to the configured chat.
        
        Args:
            message: Message to send
        """
        if not self.app or not self._authorized_chat_id:
            logger.warning("Cannot send notification: bot not configured")
            return
        
        if not self.config.dynamic.notifications_enabled:
            return
        
        try:
            await self.app.bot.send_message(
                chat_id=self._authorized_chat_id,
                text=message,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    # ========== Bot Lifecycle ==========

    async def start(self) -> None:
        """
        Start the Telegram bot.
        
        This initializes the bot, registers command handlers,
        and starts polling for updates.
        """
        if not self.config.telegram_bot_token:
            logger.warning("Telegram bot token not configured, bot disabled")
            return
        
        # Create application
        self.app = Application.builder().token(self.config.telegram_bot_token).build()
        
        # Register command handlers
        handlers = [
            CommandHandler("start", self.cmd_start),
            CommandHandler("help", self.cmd_help),
            CommandHandler("status", self.cmd_status),
            CommandHandler("next", self.cmd_next),
            CommandHandler("test", self.cmd_test),
            CommandHandler("schedule", self.cmd_schedule),
            CommandHandler("cleanup", self.cmd_cleanup),
            CommandHandler("notify", self.cmd_notify),
            CommandHandler("testduration", self.cmd_testduration),
            CommandHandler("config", self.cmd_config),
        ]
        
        for handler in handlers:
            self.app.add_handler(handler)
        
        # Set up bot commands for the menu
        commands = [
            BotCommand("status", "Show recorder status"),
            BotCommand("next", "Show upcoming recordings"),
            BotCommand("test", "Run test recording"),
            BotCommand("schedule", "Manage schedules"),
            BotCommand("config", "Show configuration"),
            BotCommand("help", "Show all commands"),
        ]
        
        await self.app.bot.set_my_commands(commands)
        
        # Initialize and start
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        
        logger.info("Telegram bot started")
        
        # Send startup notification
        await self.notify("🟢 Radio Recorder started")

    async def stop(self) -> None:
        """
        Stop the Telegram bot gracefully.
        
        This sends a shutdown notification and stops the bot.
        """
        if self.app:
            # Send shutdown notification
            await self.notify("🔴 Radio Recorder stopping...")
            
            # Stop the bot
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            
            logger.info("Telegram bot stopped")
        
        self.app = None


# Global bot instance
_bot: Optional[RadioBot] = None


def get_bot() -> RadioBot:
    """
    Get the global bot instance.
    
    Creates the instance on first call (lazy initialization).
    
    Returns:
        The global RadioBot instance
    """
    global _bot
    if _bot is None:
        _bot = RadioBot()
    return _bot
