# Radio Show Recorder

A Dockerized application for recording internet radio streams with cloud upload and Telegram bot control.

## Features

- **Scheduled Recording** - Automatically record radio shows at specified times
- **Cloud Upload** - Upload recordings to pCloud via rclone
- **Telegram Bot** - Control and monitor via Telegram commands
- **Auto Cleanup** - Automatically delete local files after verified upload
- **Dynamic Config** - Change settings via Telegram without restarting

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- rclone configured with pCloud

### 2. Configure rclone for pCloud

```bash
rclone config
# Select: n (New remote)
# Name: pcloud
# Storage: pcloud
# Follow the OAuth authentication flow
```

### 3. Set Up Environment

```bash
# Clone or download the project
cd Radio-show-recorder

# Copy the example environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

Required settings in `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 4. Run with Docker

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | - | Your Telegram chat ID |
| `STREAM_URL` | No | Yammat FM | Radio stream URL |
| `PCLOUD_REMOTE` | No | `pcloud:Radio recordings` | rclone remote path |
| `TZ` | No | `Europe/Zagreb` | Timezone |
| `DEFAULT_DURATION` | No | `28800` (8h) | Default recording duration |
| `DEFAULT_SCHEDULE` | No | `friday:20:55:28800` | Default schedule |

### Dynamic Settings (via Telegram)

These settings can be changed at runtime and persist across restarts:

- **Schedules** - Recording times and durations
- **Cleanup** - Auto-delete after upload (on/off)
- **Notifications** - Enable/disable alerts (on/off)
- **Test Duration** - Length of test recordings

## Telegram Bot Commands

### Info Commands

| Command | Description |
|---------|-------------|
| `/status` | Show recorder status and disk space |
| `/next` | Show upcoming scheduled recordings |
| `/test` | Run a test recording |

### Schedule Commands

| Command | Description |
|---------|-------------|
| `/schedule list` | Show all configured schedules |
| `/schedule add <day> <time> <duration>` | Add a new schedule |
| `/schedule remove <id>` | Remove a schedule |

**Examples:**
```
/schedule add fri 20:55 8h
/schedule add sun 19:00 30m
/schedule remove user_0
```

### Config Commands

| Command | Description |
|---------|-------------|
| `/cleanup on\|off` | Toggle auto-cleanup |
| `/notify on\|off` | Toggle notifications |
| `/testduration <seconds>` | Set test recording duration |
| `/config` | Show current configuration |

## Project Structure

```
Radio-show-recorder/
├── src/
│   ├── __init__.py      # Package initialization
│   ├── main.py          # Application entry point
│   ├── config.py        # Configuration management
│   ├── recorder.py      # Recording logic (ffmpeg)
│   ├── uploader.py      # Cloud upload (rclone)
│   ├── scheduler.py     # Job scheduling (APScheduler)
│   ├── bot.py           # Telegram bot
│   └── utils.py         # Utility functions
├── data/
│   └── user_config.json # Dynamic settings (auto-generated)
├── recordings/          # Temporary local storage
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Notifications

The bot sends automatic notifications for:

- 🎙️ Recording started
- ✅ Recording completed
- ☁️ Upload completed
- ❌ Errors (recording/upload failures)
- ⚠️ Low disk space warnings

## Troubleshooting

### Bot not responding

1. Check if the container is running: `docker-compose ps`
2. Verify your `TELEGRAM_BOT_TOKEN` is correct
3. Ensure `TELEGRAM_CHAT_ID` matches your chat

### Upload failures

1. Test rclone manually: `rclone ls pcloud:`
2. Check rclone.conf is mounted correctly
3. Verify pCloud remote name matches `PCLOUD_REMOTE`

### Recording failures

1. Check stream URL is accessible: `curl -I <STREAM_URL>`
2. Ensure ffmpeg is working: `docker-compose exec radio-recorder ffmpeg -version`
3. Check disk space: `/status` command

### View logs

```bash
# All logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100
```

## Development

### Run locally (without Docker)

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id

# Run
python -m src.main
```

### Run tests

```bash
# Test recording (15 seconds)
/test

# Check status
/status
```

## License

MIT License - feel free to use and modify.
