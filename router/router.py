#!/usr/bin/env python3
"""
Hans router — Ollama tool calling agent loop.

Sends tasks to a local Ollama model (default: qwen3.5:9b) with SwingTrader tools.
The model calls tools autonomously in a multi-turn loop until it has a final answer.

Usage:
  python router/router.py "your task here"
  python router/router.py --think true "your task"
  python router/router.py --stats

Environment variables (can be set in .env or shell):
  LOCAL_MODEL              Ollama model name (default: qwen3.5:9b)
  OLLAMA_HOST              Ollama base URL (default: http://127.0.0.1:11434)
  OLLAMA_THINK             true/false or low/medium/high — thinking mode (default: false)
  OLLAMA_KEEP_ALIVE        e.g. 30m or -1 — keep model loaded in VRAM between asks
  OLLAMA_CONNECT_TIMEOUT_S Connect timeout in seconds (default: 60)
  OLLAMA_READ_TIMEOUT_S    Max seconds between response chunks; empty = no limit
  SWINGTRADER_ROOT         Path to swingtrader repo (default: /Users/kasperisme/projects/swingtrader)
  SWINGTRADER_PYTHON       Python binary for swingtrader venv (default: python3)
  SWINGTRADER_TIMEOUT_SEC  Screener run timeout in seconds (default: 3600)
  HANS_SYSTEM_APPEND       Optional extra text appended to the system prompt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import ollama
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# --- Config ---
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "qwen3.5:9b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")

LOG_DIR  = Path.home() / ".tiered-agent" / "logs"
LOG_FILE = LOG_DIR / "router.jsonl"

# Ensure repo root is on sys.path for skill imports
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from logging_config import setup_logging
    router_log = setup_logging("hans.router")
except Exception:
    import logging
    router_log = logging.getLogger("hans.router")
    if not router_log.handlers:
        _h = logging.StreamHandler(sys.stderr)
        _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
        router_log.addHandler(_h)
        router_log.setLevel(logging.INFO)


# --- Logging ---
def _log(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _log_action(model: str, action: str, detail: dict) -> None:
    _log({
        "type": "action",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "action": action,
        **detail,
    })


def _log_tool_call(tc) -> None:
    if hasattr(tc, "function"):
        fn = tc.function
        args = getattr(fn, "arguments", {})
        if hasattr(args, "model_dump"):
            args = args.model_dump()
        _log_action(LOCAL_MODEL, "tool_call", {"tool": fn.name, "input": args})
    elif isinstance(tc, dict):
        fn = tc.get("function", {})
        _log_action(LOCAL_MODEL, "tool_call", {"tool": fn.get("name"), "input": fn.get("arguments", {})})


# --- Ollama client ---
def _ollama_read_timeout() -> float | None:
    raw = os.getenv("OLLAMA_READ_TIMEOUT_S")
    if not raw or raw.strip().lower() in ("none", "unlimited", "off", "0", "-1"):
        return None
    val = float(raw)
    if val < 300:
        router_log.warning(
            "OLLAMA_READ_TIMEOUT_S=%s is low — first chunk after a cold model load can take minutes. "
            "Leave unset for no limit.",
            val,
        )
    return val


def _ollama_client() -> ollama.Client:
    connect = float(os.getenv("OLLAMA_CONNECT_TIMEOUT_S", "60"))
    read = _ollama_read_timeout()
    return ollama.Client(
        host=OLLAMA_HOST,
        timeout=httpx.Timeout(connect=connect, read=read, write=300.0, pool=None),
    )


def _parse_think() -> bool | str:
    raw = os.getenv("OLLAMA_THINK", "false").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("low", "medium", "high"):
        return raw
    return True


def _keep_alive_kw() -> dict:
    raw = os.getenv("OLLAMA_KEEP_ALIVE", "").strip()
    if not raw:
        return {}
    if raw.lower() in ("-1", "indefinite"):
        return {"keep_alive": "-1"}
    try:
        return {"keep_alive": float(raw)}
    except ValueError:
        return {"keep_alive": raw}


# --- System prompt ---
DANISH_SYSTEM = (
    "Du er Hans, en aktie- og swingtrading-assistent med fokus på IBD/Minervini screening. "
    "Svar altid på dansk. Giv kun informations- og analysehjælp (ikke personlig finansiel rådgivning)."
)

TOOL_NOTE = (
    "Du har adgang til SwingTrader-værktøjer og SKAL bruge dem, når brugeren beder om data. "
    "Vigtigste værktøjer: "
    "• get_latest_screener_result — seneste screening-resultat med summary + picks (brug dette først). "
    "• get_passed_stocks(run_id) — alle godkendte aktier for en given kørsel. "
    "• get_near_pivot_stocks(run_id) — aktier tæt på pivot-punkt. "
    "• get_screener_summary(run_id) — aggregerede statistikker for en kørsel. "
    "• list_scan_runs — oversigt over seneste kørsler. "
    "• get_scan_jobs — status på kørende/afsluttede screening-jobs. "
    "• run_ibd_market_screener — start en ny markedsscreening i baggrunden (returner job_id straks). "
    "• run_json_screener — start IBD+Minervini pipeline i baggrunden. "
    "• send_telegram(message) — send en besked til brugeren via Telegram. "
    "Brug send_telegram til at bekræfte opstart og sende resultater, når en opgave er afsluttet. "
    "Brug get_scan_rows og get_run_detail kun ved behov for rå data."
)


def _system_prompt() -> str:
    parts = [DANISH_SYSTEM, TOOL_NOTE]
    extra = os.getenv("HANS_SYSTEM_APPEND", "").strip()
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


# --- Tools ---
# All SwingTrader MCP tools exposed as Ollama tool calling functions.
# Imported lazily from skills/swingtrader_tools.py which delegates to swingtrader_mcp.server.

from skills.swingtrader_tools import (
    swingtrader_db_path,
    get_scan_jobs,
    get_scan_job,
    list_scan_runs,
    get_run_detail,
    get_scan_rows,
    get_screener_summary,
    get_passed_stocks,
    get_near_pivot_stocks,
    get_latest_screener_result,
    run_ibd_market_screener,
    run_json_screener,
)
from skills.telegram_tools import send_telegram

_TOOLS: dict[str, callable] = {
    fn.__name__: fn for fn in [
        # SwingTrader data tools
        swingtrader_db_path,
        get_scan_jobs,
        get_scan_job,
        list_scan_runs,
        get_run_detail,
        get_scan_rows,
        get_screener_summary,
        get_passed_stocks,
        get_near_pivot_stocks,
        get_latest_screener_result,
        run_ibd_market_screener,
        run_json_screener,
        # Notification
        send_telegram,
    ]
}


# --- Agent loop ---
def chat(task: str) -> str:
    """Multi-turn tool calling agent loop against local Ollama."""
    think = _parse_think()
    client = _ollama_client()

    messages: list[dict] = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": task},
    ]

    full_thinking = ""

    while True:
        response = client.chat(
            model=LOCAL_MODEL,
            messages=messages,
            tools=list(_TOOLS.values()),
            think=think,
            **_keep_alive_kw(),
        )
        msg = response.message
        messages.append(msg)

        if msg.thinking:
            full_thinking += msg.thinking
            preview = msg.thinking.replace("\n", " ").strip()[:200]
            router_log.info("[thinking] +%d chars — %s", len(msg.thinking), preview or "(whitespace)")

        if not msg.tool_calls:
            content = msg.content or ""
            if full_thinking:
                _log({
                    "type": "thinking_complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": LOCAL_MODEL,
                    "total_chars": len(full_thinking),
                    "preview": full_thinking[:400],
                })
            if content:
                _log_action(LOCAL_MODEL, "text", {"preview": content[:200]})
            return content

        for tc in msg.tool_calls:
            _log_tool_call(tc)
            fn_name = tc.function.name
            fn_args = tc.function.arguments
            if hasattr(fn_args, "model_dump"):
                fn_args = fn_args.model_dump()
            fn_args = fn_args or {}

            tool_fn = _TOOLS.get(fn_name)
            if tool_fn is None:
                result_str = json.dumps({"error": f"Unknown tool: {fn_name}"})
                router_log.warning("Unknown tool called: %s", fn_name)
            else:
                router_log.info("Calling tool: %s args=%s", fn_name, fn_args)
                try:
                    result_str = tool_fn(**fn_args)
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)})
                    router_log.error("Tool %s raised: %s", fn_name, exc)

            messages.append({"role": "tool", "tool_name": fn_name, "content": result_str})


# --- CLI ---
def main() -> None:
    parser = argparse.ArgumentParser(description="Hans — Ollama tool calling router")
    parser.add_argument("task", nargs="?", help="Task to send to the model")
    parser.add_argument("--json", action="store_true", help="Output full JSON result")
    parser.add_argument("--stats", action="store_true", help="Print request statistics from log")
    think_grp = parser.add_mutually_exclusive_group()
    think_grp.add_argument("--no-think", action="store_true", help="Disable thinking mode (OLLAMA_THINK=false)")
    think_grp.add_argument(
        "--think",
        choices=("false", "true", "low", "medium", "high"),
        metavar="LEVEL",
        help="Set thinking level for this run",
    )
    args = parser.parse_args()

    if args.no_think:
        os.environ["OLLAMA_THINK"] = "false"
    elif args.think is not None:
        os.environ["OLLAMA_THINK"] = args.think

    if args.stats:
        _print_stats()
        return

    task = args.task or sys.stdin.read().strip()
    if not task:
        parser.print_help()
        sys.exit(1)

    start = time.monotonic()
    try:
        response = chat(task)
        error = None
    except httpx.TimeoutException as e:
        response = f"Ollama timeout: {e}. Pre-warm modellen med: ollama run {LOCAL_MODEL} \"hej\""
        error = str(e)
    except Exception as e:
        response = f"Fejl: {e}"
        error = str(e)

    elapsed = round(time.monotonic() - start, 2)

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_preview": task[:120],
        "model": LOCAL_MODEL,
        "elapsed_s": elapsed,
        "error": error,
    }
    _log(meta)

    if args.json:
        print(json.dumps({"response": response, "meta": meta}, indent=2))
    else:
        print(f"[{LOCAL_MODEL}] {response}")


def _print_stats() -> None:
    if not LOG_FILE.exists():
        print("No log found yet.")
        return
    entries = [json.loads(line) for line in LOG_FILE.read_text().splitlines() if line.strip()]
    requests = [e for e in entries if "task_preview" in e]
    total = len(requests)
    errors = sum(1 for e in requests if e.get("error"))
    tool_calls = sum(1 for e in entries if e.get("action") == "tool_call")
    print(f"Total requests : {total}")
    print(f"Errors         : {errors}")
    print(f"Tool calls     : {tool_calls}")
    if requests:
        avg = sum(e.get("elapsed_s", 0) for e in requests) / total
        print(f"Avg latency    : {avg:.1f}s")


if __name__ == "__main__":
    main()
