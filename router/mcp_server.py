"""
Hans MCP server — exposes Hans as a sub-agent for Claude Code.

Tools:
  ask_hans(query)        Blocking: run Hans and return the finished answer.
  ask_hans_background(query)  Fire-and-forget: Hans runs in background, sends result via Telegram.
  send_telegram(message) Send a Telegram message to the user directly.

Usage (stdio, started by Claude Code via .mcp.json):
  python -m router.mcp_server
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server.fastmcp import FastMCP

from router.router import chat
from skills.telegram_tools import send_telegram as _send_telegram

mcp = FastMCP("hans")


@mcp.tool()
def ask_hans(query: str) -> str:
    """
    Delegate a SwingTrader analytics query to Hans (local Ollama, free) and wait for the answer.
    Use for quick queries where you need the result to continue. For longer tasks use ask_hans_background.
    """
    return chat(query)


@mcp.tool()
def ask_hans_background(query: str) -> str:
    """
    Fire-and-forget: Hans runs the query in the background on local Ollama and sends the result
    to the user via Telegram when done. Returns immediately so Claude Code can continue.
    Use this for screener runs, full analysis, or any task that takes more than a few seconds.
    """
    python  = sys.executable
    script  = str(_REPO_ROOT / "router" / "_background_worker.py")
    try:
        proc = subprocess.Popen(
            [python, script, query],
            cwd=str(_REPO_ROOT),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return json.dumps({"ok": True, "pid": proc.pid,
                           "message": "Hans er i gang — du får besked på Telegram, når det er færdigt."})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def send_telegram(message: str) -> str:
    """
    Send a Telegram message to the user via the configured Hans bot.
    Use this to notify the user when a task starts or finishes.
    """
    return _send_telegram(message)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
