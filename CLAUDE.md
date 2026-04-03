# Hans - Home Automation Assistant

## Overview

Hans is a home automation system running on a Raspberry Pi with Ubuntu Server.
Claude Code runs as the agent orchestration layer, with all LLM inference via Claude API.

## Architecture

- **Telegram Bot** (`bot.py`) - User interface, listens for commands
- **Skills** (`skills/`) - Python scripts Claude Code can invoke
- **Nemlig basket** - `nemlig_api` + `skills/order_nemlig.py` add lines from Todoist to the web basket (unofficial API; checkout still on the site)

## Commands

When invoked via Telegram:
- `/order` - Read Todoist "Indkøb" list, order items on nemlig.com
- `/list` - Show current shopping list from Todoist
- `/status` - Check system status

## Skills Directory

Skills are standalone Python scripts in `skills/`:
- `read_todoist.py` - Fetches open tasks from Todoist project "Indkøb"
- `order_nemlig.py` - Search nemlig.com and add matched products to basket (REST API)
- `confirm_order.py` - Formats order confirmation summary

## Environment Variables

Required in `.env`:
```
CLAUDE_API_KEY=           # Claude API key
TODOIST_API_TOKEN=        # Todoist REST API token
NEMLIG_EMAIL=             # nemlig.com login email
NEMLIG_PASSWORD=          # nemlig.com login password
TELEGRAM_BOT_TOKEN=       # Telegram Bot API token
TELEGRAM_ALLOWED_USER_IDS=id1,id2  # Comma-separated whitelisted user IDs
```

## Running Skills

When asked to order groceries:
1. Run `python skills/read_todoist.py` to get the shopping list
2. Pipe the JSON into `python skills/order_nemlig.py` — it logs in, searches each line, adds quantities to the basket, prints JSON (stdout)
3. Optionally `python skills/order_nemlig.py --dry-run` to preview matches without changing the basket
4. Run `python skills/confirm_order.py` on that JSON to format the summary; use computer use only if you need to complete checkout in the browser

## Important Notes

- Always check `.env` is loaded before running skills
- Basket fills use the API; full checkout may still require the browser on nemlig.com
- Never expose API keys in output or logs
- Only respond to whitelisted Telegram user IDs
