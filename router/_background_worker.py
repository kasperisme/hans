#!/usr/bin/env python3
"""
Background worker for ask_hans_background.
Spawned by the Hans MCP server as a detached process.
Runs the Hans agent loop and sends the result to the user via Telegram.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from router.router import chat
from skills.telegram_tools import send_telegram


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    send_telegram(f"Hans er i gang:\n_{query}_")

    try:
        result = chat(query)
    except Exception as exc:
        send_telegram(f"Hans fejlede: {exc}")
        sys.exit(1)

    # Telegram has a 4096 char limit per message; split if needed
    max_len = 4000
    if len(result) <= max_len:
        send_telegram(result)
    else:
        chunks = [result[i:i + max_len] for i in range(0, len(result), max_len)]
        for i, chunk in enumerate(chunks, 1):
            send_telegram(f"({i}/{len(chunks)})\n{chunk}")


if __name__ == "__main__":
    main()
