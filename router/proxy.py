#!/usr/bin/env python3
"""
router/proxy.py — Ollama-backed Anthropic API proxy.

Accepts requests in Anthropic Messages API format and forwards them to a local
Ollama model. Useful for tools that speak the Anthropic API but should run locally.

Usage:
  python router/proxy.py                            # start on port 5001
  ANTHROPIC_BASE_URL=http://localhost:5001 claude   # point a client at it

Environment variables:
  LOCAL_MODEL              Ollama model name (default: qwen3.5:9b)
  OLLAMA_HOST              Ollama base URL (default: http://127.0.0.1:11434)
  OLLAMA_THINK             true/false or low/medium/high (default: false)
  OLLAMA_CONNECT_TIMEOUT_S Connect timeout in seconds (default: 60)
  OLLAMA_READ_TIMEOUT_S    Max seconds between chunks; empty = no limit
  PROXY_PORT               Port to listen on (default: 5001)
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import ollama
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

PORT        = int(os.getenv("PROXY_PORT", "5001"))
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "qwen3.5:9b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")

LOG_DIR  = Path.home() / ".tiered-agent" / "logs"
LOG_FILE = LOG_DIR / "proxy.jsonl"

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from logging_config import setup_logging
    proxy_log = setup_logging("hans.proxy")
except Exception:
    import logging
    proxy_log = logging.getLogger("hans.proxy")
    if not proxy_log.handlers:
        _h = logging.StreamHandler(sys.stderr)
        _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
        proxy_log.addHandler(_h)
        proxy_log.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _read_timeout() -> float | None:
    raw = os.getenv("OLLAMA_READ_TIMEOUT_S")
    if not raw or raw.strip().lower() in ("none", "unlimited", "off", "0", "-1"):
        return None
    val = float(raw)
    if val < 300:
        proxy_log.warning("OLLAMA_READ_TIMEOUT_S=%s is low — cold model load may exceed this.", val)
    return val


def _ollama_client() -> ollama.Client:
    connect = float(os.getenv("OLLAMA_CONNECT_TIMEOUT_S", "60"))
    return ollama.Client(
        host=OLLAMA_HOST,
        timeout=httpx.Timeout(connect=connect, read=_read_timeout(), write=300.0, pool=None),
    )


def _parse_think() -> bool | str:
    raw = os.getenv("OLLAMA_THINK", "false").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("low", "medium", "high"):
        return raw
    return True


# ---------------------------------------------------------------------------
# Format conversion: Anthropic → Ollama
# ---------------------------------------------------------------------------

def _tools_to_ollama(tools: list) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


def _messages_to_ollama(messages: list, system: str | None) -> list:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})

    for msg in messages:
        role    = msg["role"]
        content = msg.get("content", "")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        text_parts, tool_uses, tool_results = [], [], []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_uses.append(block)
            elif btype == "tool_result":
                tool_results.append(block)

        if tool_uses and role == "assistant":
            out.append({
                "role": "assistant",
                "content": " ".join(text_parts),
                "tool_calls": [
                    {"function": {"name": tu["name"], "arguments": tu.get("input", {})}}
                    for tu in tool_uses
                ],
            })
        elif tool_results and role == "user":
            for tr in tool_results:
                tr_content = tr.get("content", "")
                if isinstance(tr_content, list):
                    tr_content = " ".join(
                        b.get("text", "") for b in tr_content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                out.append({"role": "tool", "content": tr_content})
            if text_parts:
                out.append({"role": "user", "content": " ".join(text_parts)})
        else:
            out.append({"role": role, "content": " ".join(text_parts)})

    return out


# ---------------------------------------------------------------------------
# Format conversion: Ollama → Anthropic
# ---------------------------------------------------------------------------

def _response_to_anthropic(msg: ollama.Message, model: str, msg_id: str, tokens: int) -> dict:
    content_blocks: list[dict] = []
    if msg.content:
        content_blocks.append({"type": "text", "text": msg.content})
    for tc in msg.tool_calls or []:
        fn = tc.function
        args = fn.arguments
        if hasattr(args, "model_dump"):
            args = args.model_dump()
        content_blocks.append({
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex[:12]}",
            "name": fn.name,
            "input": args or {},
        })
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": "tool_use" if msg.tool_calls else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": tokens},
    }


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _stream_ollama(ollama_messages: list, ollama_tools: list, msg_id: str):
    """Yield Anthropic SSE bytes backed by a streaming Ollama response."""
    client = _ollama_client()
    think  = _parse_think()

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant",
            "content": [], "model": LOCAL_MODEL,
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    yield _sse("ping", {"type": "ping"})

    block_index     = 0
    text_started    = False
    full_text       = ""
    full_thinking   = ""
    tool_calls_seen = []
    output_tokens   = 0

    for chunk in client.chat(
        model=LOCAL_MODEL,
        messages=ollama_messages,
        tools=ollama_tools or None,
        stream=True,
        think=think,
    ):
        msg = chunk.message
        output_tokens += 1

        if msg.thinking:
            full_thinking += msg.thinking
            proxy_log.info("[thinking] +%d chars", len(msg.thinking))

        if msg.content:
            if not text_started:
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": block_index,
                    "content_block": {"type": "text", "text": ""},
                })
                text_started = True
            full_text += msg.content
            yield _sse("content_block_delta", {
                "type": "content_block_delta", "index": block_index,
                "delta": {"type": "text_delta", "text": msg.content},
            })

        if msg.tool_calls:
            tool_calls_seen.extend(msg.tool_calls)

    if full_thinking:
        _log({"type": "thinking_complete", "ts": datetime.now(timezone.utc).isoformat(),
              "model": LOCAL_MODEL, "total_chars": len(full_thinking)})

    if text_started:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
        block_index += 1

    stop_reason = "end_turn"
    for tc in tool_calls_seen:
        fn   = tc.function
        args = fn.arguments
        if hasattr(args, "model_dump"):
            args = args.model_dump()
        tool_id    = f"toolu_{uuid.uuid4().hex[:12]}"
        input_json = json.dumps(args or {})
        yield _sse("content_block_start", {
            "type": "content_block_start", "index": block_index,
            "content_block": {"type": "tool_use", "id": tool_id, "name": fn.name, "input": {}},
        })
        yield _sse("content_block_delta", {
            "type": "content_block_delta", "index": block_index,
            "delta": {"type": "input_json_delta", "partial_json": input_json},
        })
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
        block_index += 1
        stop_reason = "tool_use"

    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })
    yield _sse("message_stop", {"type": "message_stop"})

    _log({"type": "request", "ts": datetime.now(timezone.utc).isoformat(),
          "model": LOCAL_MODEL, "stream": True, "stop_reason": stop_reason})


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._json(200, {"status": "ok", "model": LOCAL_MODEL,
                             "ollama": OLLAMA_HOST or "http://127.0.0.1:11434"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/messages":
            self._json(404, {"error": "only /v1/messages is supported"})
            return

        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return

        stream   = data.get("stream", False)
        messages = data.get("messages", [])
        system   = data.get("system")
        tools    = data.get("tools", [])
        msg_id   = f"msg_{uuid.uuid4().hex[:24]}"
        start    = time.monotonic()

        ollama_messages = _messages_to_ollama(messages, system)
        ollama_tools    = _tools_to_ollama(tools) if tools else []

        proxy_log.info("POST /v1/messages stream=%s tools=%d", stream, len(ollama_tools))

        try:
            if stream:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                try:
                    for chunk in _stream_ollama(ollama_messages, ollama_tools, msg_id):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                client = _ollama_client()
                resp   = client.chat(
                    model=LOCAL_MODEL,
                    messages=ollama_messages,
                    tools=ollama_tools or None,
                    think=_parse_think(),
                )
                payload = _response_to_anthropic(
                    resp.message, LOCAL_MODEL, msg_id,
                    tokens=getattr(resp, "eval_count", 0) or 0,
                )
                self._json(200, payload)
                _log({"type": "request", "ts": datetime.now(timezone.utc).isoformat(),
                      "model": LOCAL_MODEL, "stream": False,
                      "elapsed_s": round(time.monotonic() - start, 2)})
        except Exception as e:
            proxy_log.error("Ollama error: %s", e)
            self._json(503, {"type": "error", "error": {"type": "api_error", "message": str(e)}})

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    server = HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    proxy_log.info("Proxy listening on http://127.0.0.1:%d — model: %s", PORT, LOCAL_MODEL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        proxy_log.info("Stopped.")


if __name__ == "__main__":
    main()
