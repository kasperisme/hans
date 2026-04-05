Use the SwingTrader MCP tools to answer the following query about screening results, scan history, or stock picks:

$ARGUMENTS

## How to use the tools

- `list_scan_runs` — list recent scan runs with metadata (id, source, timestamp)
- `get_latest_screener_result` — full output from the most recent run
- `get_scan_rows` — per-symbol rows for a run (dataset: trend_template, passed_stocks, etc.)
- `get_run_detail` — raw result_json / market_json for a specific run_id
- `swingtrader_db_path` — resolve the DuckDB file path
- `run_json_screener` — run scripts/run_screener.py (IBD file + lookback); only if explicitly asked
- `run_ibd_market_screener` — run ibd_screener.py (heavy market-wide screen); only if explicitly asked

Start with `get_latest_screener_result` for general queries. Use `list_scan_runs` + `get_scan_rows` when you need history or per-symbol detail. Never run a new screen unless the user explicitly requests it.

Respond concisely: include run date, passed symbol count, and the top picks list where relevant.
