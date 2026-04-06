# Hans - Swing Trading Assistant

## Overview

Hans is a stock trading assistant centered on the local `swingtrader` repository.
Its primary function is to run and summarize IBD/Minervini screening and support trading-focused analysis via the `ask` CLI, Cursor (MCP), and optionally **Telegram** through the official Claude Code plugin (`deploy/claude-telegram.sh`).

Screening results are persisted in **DuckDB** (`scan_runs` / `scan_rows`). The **SwingTrader MCP** server exposes that database and screener scripts **to the Cursor IDE agent only** (stdio MCP — see `.cursor/mcp.json`). **Prefer MCP tools** in Cursor for queries and runs instead of ad-hoc file reads or guessing paths.

**Tier 1 (`ask`):** By default **`HANS_TIER1_BACKEND=claude_code`** — `router/router.py` runs **`claude --model <LOCAL_MODEL> -p …`** with **`ANTHROPIC_BASE_URL=http://127.0.0.1:11434`** (Ollama’s Anthropic-compatible API), cwd = this repo, so you get **Claude Code’s** runtime (permissions, project context, optional tools where supported in print mode). If `claude` is missing or errors, the router **falls back** to direct **Ollama HTTP** (`HANS_TIER1_FALLBACK=1`, default). Set **`HANS_TIER1_BACKEND=ollama`** to force the old direct-Ollama path only.

**MCP:** Cursor’s stdio MCP is separate. Claude Code may use **its own** MCP/plugins when invoked this way; **`claude -p`** (headless) can be more limited than interactive `ollama launch claude`. For full IDE MCP, use **Cursor chat**; for SwingTrader DB without CC, use **`skills/`** (e.g. `run_ibd_screener.py`, `query_swingtrader_db.py`) or ask Claude Code / **`ask`** to run them.

The router **injects** `router/ollama_context.py` (different text for Claude Code vs direct Ollama). Optional: **`HANS_TIER1_SYSTEM_APPEND`** in `.env`.

Inference is **tiered**, but **Anthropic cloud is never used unless you ask for it**:
- **Tier 1 (default):** **Claude Code CLI → Ollama** (`LOCAL_MODEL`, e.g. **`qwen3.5:9b`**) for normal **`ask`** calls, unless `HANS_TIER1_BACKEND=ollama`. (The official **Telegram** plugin talks to **Claude Code** directly, not `router/router.py`.)
- **Tier 2 (opt-in only):** Claude via Anthropic API — `ask --tier api "…"`, or **`/api `**, **`[api] `**, **`/escalate `**. No automatic escalation on errors/timeouts.

**Two ways to use Claude Code with this stack**

| Goal | What to use |
|------|----------------|
| **Claude Code + local qwen + MCP/plugins** (official Ollama integration) | Point Claude Code at **Ollama’s API** on **`http://127.0.0.1:11434`**, not the Hans proxy. Run **`bash deploy/claude-code-ollama.sh`** (or `ollama launch claude --model qwen3.5:9b` with the env vars below). MCP runs **inside Claude Code**; Ollama only runs the model. See [Ollama: Claude Code](https://docs.ollama.com/integrations/claude-code). |
| **Hans tiered router** (Danish system prompt, `/api` escalation, `X-Hans-Tier: api`) | `deploy/start-mac.sh` starts the **proxy on port 5001**; `setup-mac.sh` can set `ANTHROPIC_BASE_URL=http://127.0.0.1:5001`. This is **not** the same as the official Ollama↔Claude Code integration. |

**`ask` vs interactive Claude Code:** `ask` uses the **router**, which shells to **`claude -p`** (same env as [Ollama + Claude Code](https://docs.ollama.com/integrations/claude-code)). **`deploy/claude-code-ollama.sh`** starts **interactive** `ollama launch claude` — use that when you want the full TUI; use **`ask`** for scripted/telegram-style prompts. One **`ollama serve`** on **11434** backs both.

**Continuous Claude Code session from `ask`:** Set **`HANS_CLAUDE_CODE_SESSION=1`** in `.env`. Tier 1 uses **`claude -p --output-format json`** by default so stdout includes a **`session_id`** (see [headless / structured output](https://code.claude.com/docs/en/headless#get-structured-output)). That ID is stored per project in **`~/.tiered-agent/hans_claude_code_session.json`** and appended to **`~/.tiered-agent/logs/router.jsonl`** as **`type: claude_code_session`** (fields: `session_id`, `project`, `session_ready`). The next **`ask`** prefers **`claude --resume <session_id>`** (then **`--continue`**, then a fresh **`-p`**). Use the logged **`session_id`** with the **Anthropic API** or global **`claude --resume`** as in the docs. Set **`HANS_CLAUDE_CODE_OUTPUT_FORMAT=text`** only if you accept losing JSON (no **`session_id`** in stdout). Start over with **`ask --reset-claude-session`**.

**Manual env (same as Ollama docs)** for direct Ollama + Claude Code:

```bash
export ANTHROPIC_AUTH_TOKEN=ollama
export ANTHROPIC_API_KEY=""
export ANTHROPIC_BASE_URL=http://127.0.0.1:11434
claude --model qwen3.5:9b
```

If **`~/.zprofile`** already sets `ANTHROPIC_BASE_URL` to **`5001`**, override for the session or use **`deploy/claude-code-ollama.sh`**, which forces **11434**.

**Claude Code + Hans proxy** (`deploy/start-mac.sh`): requests go to **local Ollama** by default through the proxy. To hit the real Anthropic API through the proxy, add HTTP header **`X-Hans-Tier: api`** on the message request.

Override `LOCAL_MODEL` in `.env` if you switch Ollama models (keep it aligned with the model name you pass to `ollama launch` / `claude --model`).

**`ask` vs `ollama run`** — `ask` uses the **chat** API with Hans’s **system prompt** (extra tokens). It also used to feel much slower than `ollama run` mainly because **`OLLAMA_THINK` defaulted to on** (hidden reasoning before the visible answer). Default is now **`false`**, matching `ollama run`. Set `OLLAMA_THINK=true` when you want thinking traces (and expect longer latency). Tier 1 no longer **imports Anthropic** until you use `--tier api` / `/api`, which trims cold-start time for local-only runs.

**Thinking parity with `ollama run --think=false`:** `OLLAMA_THINK` and **`ask --no-think` / `ask --think false`** apply only when **`HANS_TIER1_BACKEND=ollama`** (direct `ollama` Python client → `think=` on `/api/chat`). The default **`HANS_TIER1_BACKEND=claude_code`** path runs **`claude -p`** → Ollama’s **Anthropic-compatible API**, where Ollama **defaults thinking on** for supported models; the router cannot pass `--think=false` into that stack. To get **`ask`** behavior aligned with fast **`ollama run --think=false`**, set **`HANS_TIER1_BACKEND=ollama`** (and keep **`OLLAMA_THINK` unset or false**, or use **`ask --no-think`**).

### Latency and warm-up (no true “hot start” for Claude Code)

There is **no separate hot-start daemon** in Hans: each `ask` still invokes the Tier 1 backend. You can **reduce steady-state latency** as follows:

| Knob | Effect |
|------|--------|
| **`HANS_CLAUDE_CODE_BARE=1`** | Adds **`claude -p --bare`** — faster subprocess path; **skips MCP/plugin/hook discovery** in the CLI (use when you don’t need that overhead). |
| **`HANS_TIER1_BACKEND=ollama`** | Bypasses **`claude`** and talks to Ollama directly — usually **lower latency** for plain chat; different system prompt path (`router/ollama_context.py`). |
| **`OLLAMA_KEEP_ALIVE`** (e.g. **`30m`**, **`indefinite`**, or **`-1`**) | Applies to **direct Ollama Tier 1 only** — keeps the model loaded in VRAM after each reply so the **next** ask avoids reload. |
| **`deploy/warm-ollama.sh`** | Cron-friendly one-token ping; keeps the model warm when nothing is calling Ollama for a while. Set **`LOCAL_MODEL`** / **`OLLAMA_HOST`** if needed. |

Cold first byte after idle is still dominated by **loading the model**; pre-warm with `ollama run <model> "hej"` or the script above.

## Core Workflows

### Telegram

**Default (recommended):** [Ollama + Claude Code + official Telegram plugin](https://docs.ollama.com/integrations/claude-code#telegram). Chat goes to **Claude Code** (with local Ollama as the model); full details in [Anthropic’s plugin README](https://github.com/anthropics/claude-plugins-official/blob/main/external_plugins/telegram/README.md) (create a **@BotFather** bot, pairing, access).

**If you see `plugin:telegram@claude-plugins-official · plugin not installed`:** the channel flag only works **after** the plugin is installed inside **Claude Code** once (it is not bundled with `ollama launch`).

1. **Install [Bun](https://bun.sh)** — the Telegram MCP server runs on Bun (`curl -fsSL https://bun.sh/install | bash`).
2. Start **interactive** Claude Code against Ollama (same env as always):  
   `bash deploy/claude-code-ollama.sh` (or `ollama launch claude --model qwen3.5:9b` without `--channels` yet).
3. In that session, run:
   - `/plugin install telegram@claude-plugins-official`
   - `/reload-plugins`  
   If the marketplace does not list it, open **`/plugins`**, go to **Marketplace**, press **`u`** to update the cache, then retry the install ([upstream note](https://github.com/anthropics/claude-plugins-official/issues/770)).
4. `/telegram:configure <your BotFather token>` (writes `~/.claude/channels/telegram/.env`).
5. **Exit**, then start with the channel (e.g. **`bash deploy/claude-telegram.sh`**). Pair in Telegram per the README (`/telegram:access pair …`).

```bash
bash deploy/claude-telegram.sh
```

- **`CLAUDE_OLLAMA_MODEL`** / **`LOCAL_MODEL`** — model name (default `qwen3.5:9b`).
- **`CLAUDE_LAUNCH_YES=1`** — non-interactive `ollama launch` (auto-pull; use after you have run interactively once).
- **macOS auto-start:** `deploy/com.hans.claude-telegram.plist` (edit paths). **Linux (Pi):** `deploy/hans-claude-telegram.service` — **`systemctl enable hans-claude-telegram`** (installs **`deploy/hans-claude-telegram.service`**; requires **`ollama`** and **`claude`** on `PATH`).

Screening and picks are not Telegram slash commands anymore — use **`ask`**, **`skills/run_ibd_screener.py`**, **`skills/query_swingtrader_db.py`**, or **Cursor MCP** as in the rest of this doc.

### CLI

**If you see local timeouts**, the first request after idle often **loads the model into VRAM** and can take **more than 90 seconds** before any bytes arrive. A message like **`Lokal model timeout efter 90.0s`** means either (1) **old router code** that used a single 90s httpx timeout — update `router/router.py` and re-run `ask`, or (2) **`OLLAMA_READ_TIMEOUT_S`** is set too low (remove it, or use `600+`; `0` means unlimited). With current Tier 1, **`OLLAMA_READ_TIMEOUT_S` unset** ⇒ **no limit** on idle time before the first stream chunk. Pre-warm with `ollama run qwen3.5:9b "hej"` so the next `ask` is fast. With **`OLLAMA_THINK=true`**, long gaps between tokens are normal; keep read timeout unset. **Thinking** text is logged to stderr (`hans.router` / `hans.proxy.ollama`) and to `~/.tiered-agent/logs/router.jsonl` when thinking is enabled.

**Quick tests** (from the `hans` repo, venv active):

```bash
# 1) Ollama up?
curl -s http://127.0.0.1:11434/api/tags | head

# 2) Cold vs warm: time a tiny generation (first run may be slow)
time ollama run qwen3.5:9b "sig hej"

# 3) Same path as ask (no API — should print [qwen3.5:9b] …)
time .venv/bin/python router/router.py "Hvordan er det nu?"

# 4) Cap idle time between stream chunks (optional; default = no cap)
OLLAMA_READ_TIMEOUT_S=120 .venv/bin/python router/router.py "Hvordan er det nu?"
```

Then try the same phrase via the wrapper:

```bash
ask "Hvordan er det nu?"
```

Other `ask` examples:

```bash
ask "scan today's setup"
ask --tier api "deep analysis of sector rotation"
ask "/api summarize the last scan"    # same as --tier api
ask --stats
```

## Architecture

- **Telegram:** `deploy/claude-telegram.sh` (official Claude Code plugin + Ollama)
- **Routing:** `router/router.py` + `router/ask`
- **Trading integration skill:** `skills/run_ibd_screener.py`
- **DuckDB read skill (no MCP in `ask`/router):** `skills/query_swingtrader_db.py`
- **Upstream project:** `SWINGTRADER_ROOT` (default `/Users/kasperisme/projects/swingtrader`)

### SwingTrader MCP (Cursor)

Project config: `.cursor/mcp.json` registers the `swingtrader` server (stdio) with `cwd` = `../swingtrader/code/analytics`. Restart Cursor after changing MCP config.

**Agent workflow:** For anything involving latest scans, history, or per-symbol rows, call MCP tools first:

| Tool | Use |
|------|-----|
| `swingtrader_db_path` | Resolve DuckDB file path (`HANS_DUCKDB_PATH` or default under `data/`) |
| `list_scan_runs` | Recent runs (metadata) |
| `get_run_detail` | Full `result_json` / `market_json` for one run |
| `get_scan_rows` | Normalized rows (`trend_template`, `rs_rating`, `quote`, `passed_stocks`) |
| `get_latest_screener_result` | Latest `run_screener` JSON from DB |
| `run_json_screener` | Start `scripts/run_screener.py` in background — returns `job_id` immediately |
| `run_ibd_market_screener` | Start `ibd_screener.py` in background — returns `job_id` immediately |
| `get_scan_jobs` | List recent `scan_jobs` rows: status (running/completed/failed), PID, logs, linked `scan_run_id` |
| `get_scan_job` | Single `scan_jobs` row by `job_id` — poll this to check if a screen finished |

Do **not** bypass MCP for data that already lives in DuckDB unless debugging.

If `../swingtrader/code/analytics/.venv/bin/python` is missing, edit `.cursor/mcp.json` to use `python3` and ensure `mcp` + `duckdb` are installed in that environment.

## Environment Variables

Required in `.env`:
```bash
ANTHROPIC_API_KEY=        # only needed for ask --tier api, /api prefix, or proxy X-Hans-Tier: api
APIKEY=                   # FinancialModelingPrep key used by swingtrader

HANS_DUCKDB_PATH=         # optional; default <SWINGTRADER_ROOT>/data/swingtrader.duckdb

SWINGTRADER_ROOT=         # optional, defaults to /Users/kasperisme/projects/swingtrader
SWINGTRADER_PYTHON=       # optional, defaults to python3
SWINGTRADER_TIMEOUT_SEC=  # optional, defaults to 3600

OLLAMA_READ_TIMEOUT_S=    # optional; max seconds between stream chunks (empty/none = unlimited). Use if you need a hard cap.
OLLAMA_CONNECT_TIMEOUT_S= # optional; TCP connect timeout (default 60)
OLLAMA_THINK=             # optional; true/false or low/medium/high — Ollama thinking mode (default false; true adds latency vs ollama run)
OLLAMA_TIMEOUT_S=         # legacy; mentioned in some timeout error copy only (streaming uses read timeout above)

LOCAL_MODEL=qwen3.5:9b    # optional; Tier 1 model name for both Claude Code and direct Ollama (default)
HANS_TIER1_BACKEND=       # optional; claude_code (default) or ollama
HANS_TIER1_FALLBACK=      # optional; 1 = fall back to direct Ollama if Claude Code fails (default 1)
CLAUDE_CODE_OLLAMA_BASE_URL=  # optional; Ollama Anthropic API (default http://127.0.0.1:11434)
HANS_CLAUDE_CODE_TIMEOUT_S=   # optional; claude -p subprocess timeout sec (empty = no limit)
HANS_CLAUDE_CODE_SESSION=     # optional; 1/true = persist session_id + resume (see ~/.tiered-agent/hans_claude_code_session.json + router.jsonl)
HANS_CLAUDE_CODE_OUTPUT_FORMAT=  # optional; json (default, for session_id) or text
HANS_CLAUDE_CODE_BARE=    # optional; 1 = claude -p --bare (faster; skips MCP/plugin discovery in CLI)
OLLAMA_KEEP_ALIVE=        # optional; e.g. 30m or indefinite — keep model loaded (direct Ollama Tier 1 only)
HANS_TIER1_SYSTEM_APPEND= # optional; extra lines appended to Tier 1 system text (after channel note)
```

## Important Notes

- Hans is analysis-first and trading-focused, not home automation.
- Responses are informational and should not be treated as personalized financial advice.
- Telegram (official plugin): use Anthropic’s pairing and access controls from the plugin README.
- Never expose API keys in logs or responses.
