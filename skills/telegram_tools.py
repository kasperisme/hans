"""
Telegram tool for Hans — sends messages via the bot configured in the Claude Code Telegram plugin.

Bot token: ~/.claude/channels/telegram/.env  (TELEGRAM_BOT_TOKEN)
Default chat_id: TELEGRAM_CHAT_ID env var, or first entry in access.json allowFrom list.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

_TELEGRAM_CONFIG_DIR = Path.home() / ".claude" / "channels" / "telegram"


def _bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if token:
        return token
    env_file = _TELEGRAM_CONFIG_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN not found. Set it in env or ~/.claude/channels/telegram/.env"
    )


def _default_chat_id() -> str:
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if chat_id:
        return chat_id
    access_file = _TELEGRAM_CONFIG_DIR / "access.json"
    if access_file.exists():
        try:
            data = json.loads(access_file.read_text())
            allow = data.get("allowFrom", [])
            if allow:
                return str(allow[0])
        except Exception:
            pass
    raise RuntimeError(
        "TELEGRAM_CHAT_ID not set and could not be read from access.json"
    )


def send_telegram(message: str, chat_id: str = None) -> str:
    """
    Send a Telegram message to the user via the configured bot.
    Uses the default chat_id from access.json if not specified.
    Returns a JSON result with ok/message_id or error.
    """
    token   = _bot_token()
    chat_id = chat_id or _default_chat_id()
    url     = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=15.0,
        )
        data = resp.json()
        if data.get("ok"):
            return json.dumps({"ok": True, "message_id": data["result"]["message_id"]})
        return json.dumps({"ok": False, "error": data.get("description", "unknown error")})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
