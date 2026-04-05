# Agent notes (Hans)

- **SwingTrader MCP** is configured in `.cursor/mcp.json` for the **Cursor** agent only. Use the SwingTrader MCP tools for DuckDB-backed scans, run history, and screener execution — do not rely on guessing paths into a sibling `swingtrader` checkout unless MCP is unavailable.
- **Tier 1** (`router/router.py`, used by **`ask`**): default **`HANS_TIER1_BACKEND=claude_code`** runs **`claude --model … -p`** with **`ANTHROPIC_BASE_URL=http://127.0.0.1:11434`**, cwd Hans repo — Claude Code + local Ollama. Set **`HANS_TIER1_BACKEND=ollama`** for direct HTTP only. Fallback to Ollama if `claude` is missing.
- **Claude Code + Ollama** (see [Ollama docs](https://docs.ollama.com/integrations/claude-code), `deploy/claude-code-ollama.sh`): interactive launcher; **`ask`** uses the same Ollama URL but headless **`claude -p`**. Hans proxy **5001** is separate.
- Full tool list and workflows: `CLAUDE.md` (SwingTrader MCP section).
