# Hans - Home Automation Assistant

A Raspberry Pi-based home automation hub using Claude Code as the agent orchestration layer. Manages a shared grocery list via Todoist and automates ordering on nemlig.com through a Telegram bot interface.

## Features

- **Telegram Bot Interface** - Control via `/order`, `/list`, `/status` commands
- **Todoist Integration** - Shared "Indkøb" shopping list between users
- **Automated Ordering** - Claude computer use for nemlig.com
- **Claude Code Orchestration** - AI-powered task execution
- **Auto-deployment** - GitHub webhook triggers automatic updates

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Telegram      │────▶│  Raspberry Pi   │
│   (User Input)  │◀────│  (Ubuntu)       │
└─────────────────┘     └────────┬────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
             ┌──────────┐ ┌──────────┐ ┌──────────┐
             │ Claude   │ │ Todoist  │ │ nemlig   │
             │ API      │ │ API      │ │ (Browser)│
             └──────────┘ └──────────┘ └──────────┘
```

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/YOUR_USERNAME/hans.git
cd hans
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the Bot

```bash
python bot.py
```

## Raspberry Pi Setup

Run the automated setup script on your Pi:

```bash
bash deploy/setup-pi.sh
```

This will:
- Install Python 3.11 and Chromium
- Set up the virtual environment
- Install systemd services
- Configure auto-start on boot

### Service Management

```bash
# Start the bot
sudo systemctl start hans-bot

# Check status
sudo systemctl status hans-bot

# View logs
journalctl -u hans-bot -f

# Restart after config changes
sudo systemctl restart hans-bot
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message and available commands |
| `/order` | Read Todoist list and order items on nemlig.com |
| `/list` | Display current shopping list |
| `/status` | Check system health |

## Project Structure

```
hans/
├── bot.py                 # Telegram bot daemon
├── CLAUDE.md              # Instructions for Claude Code
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
├── skills/
│   ├── read_todoist.py    # Fetch shopping list
│   ├── order_nemlig.py    # Prepare order for Claude browser control
│   └── confirm_order.py   # Format order summary
└── deploy/
    ├── setup-pi.sh        # Pi setup script
    ├── hans-bot.service   # Bot systemd service
    ├── hans-webhook.service # Webhook systemd service
    └── update-hook.py     # GitHub webhook listener
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CLAUDE_API_KEY` | Anthropic API key |
| `TODOIST_API_TOKEN` | Todoist REST API token |
| `NEMLIG_EMAIL` | nemlig.com login email |
| `NEMLIG_PASSWORD` | nemlig.com login password |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated whitelisted user IDs |

## Auto-Deployment

The Pi can automatically pull updates when you push to GitHub:

1. Set up the webhook service:
   ```bash
   sudo systemctl enable hans-webhook
   sudo systemctl start hans-webhook
   ```

2. Configure a GitHub webhook pointing to `http://YOUR_PI_IP:9000`

3. Push changes to trigger automatic deployment

## Security

- API keys stored in `.env` (git-ignored)
- SSH: Key-based auth only
- Telegram: Whitelisted user IDs only
- Pi runs on local network (not exposed to internet)

## License

MIT
