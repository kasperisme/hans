# Hans

Swing-trading assistant repo: tiered **`ask`** router, Ollama, Claude Code, and SwingTrader-related **skills**. See **CLAUDE.md** for the full picture.

## Features

- **Tiered routing** — `router/ask` → local Ollama / Claude Code, optional Anthropic API (`--tier api`)
- **Skills** — IBD screener wrappers, DuckDB reads, optional Todoist helper (`skills/read_todoist.py`)
- **Telegram (optional)** — official Claude Code plugin: `deploy/claude-telegram.sh`
- **Deploy** — Mac/Pi scripts under `deploy/`

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/hans.git
cd hans
cp .env.example .env
# Edit .env — see CLAUDE.md
```

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Telegram (optional)

See **CLAUDE.md** — Telegram.

```bash
bash deploy/claude-telegram.sh
```

## Raspberry Pi

```bash
bash deploy/setup-pi.sh
```

### Service management

```bash
sudo systemctl start hans-claude-telegram
sudo systemctl status hans-claude-telegram
journalctl -u hans-claude-telegram -f
```

## Project structure

```
hans/
├── router/            # ask CLI + tiered routing
├── skills/            # Trading scripts (screener, DuckDB, etc.)
├── deploy/            # claude-telegram.sh, setup-*.sh, systemd units
├── CLAUDE.md          # Main documentation
└── requirements.txt
```

## Environment variables

See **CLAUDE.md** — Environment Variables. Common entries: `ANTHROPIC_API_KEY` (API tier), `APIKEY` / `SWINGTRADER_ROOT` (screener), `LOCAL_MODEL`, optional `TODOIST_API_TOKEN` for `skills/read_todoist.py`.

## Auto-deployment (Pi)

Webhook listener can pull and restart services — see `deploy/update-hook.py` and `deploy/hans-webhook.service`.

## Security

- Keep secrets in `.env` (git-ignored)
- Telegram: use the official plugin’s access controls (CLAUDE.md)

## License

MIT
