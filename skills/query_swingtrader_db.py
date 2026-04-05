#!/usr/bin/env python3
"""
Read latest screening results from Swingtrader's DuckDB (same DB as MCP tools).

Uses HANS_DUCKDB_PATH or <SWINGTRADER_ROOT>/data/swingtrader.duckdb.
Does not replace MCP in Cursor — it mirrors read-only access for scripts and CLI use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import setup_logging

load_dotenv()
log = setup_logging("hans.skills.duckdb")

DEFAULT_SWINGTRADER_ROOT = "/Users/kasperisme/projects/swingtrader"


def _db_path() -> Path:
    env = os.getenv("HANS_DUCKDB_PATH")
    if env:
        return Path(env)
    root = os.getenv("SWINGTRADER_ROOT", DEFAULT_SWINGTRADER_ROOT)
    return Path(root) / "data" / "swingtrader.duckdb"


def latest_passed_symbols() -> dict:
    """Return JSON-serializable summary of latest passed tickers."""
    path = _db_path()
    if not path.exists():
        return {"ok": False, "error": f"DuckDB not found: {path}", "symbols": []}

    try:
        import duckdb
    except ImportError:
        return {"ok": False, "error": "duckdb package not installed", "symbols": []}

    conn = None
    try:
        conn = duckdb.connect(str(path))
        row = conn.execute(
            "SELECT id, source FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"ok": True, "symbols": [], "run_id": None, "source": None}

        run_id, source = int(row[0]), str(row[1])
        symbols: list[str] = []

        if source == "run_screener":
            q = """
                SELECT DISTINCT symbol FROM scan_rows
                WHERE run_id = ? AND dataset = 'passed_stocks' AND symbol IS NOT NULL
                ORDER BY symbol
            """
            symbols = [r[0] for r in conn.execute(q, [run_id]).fetchall()]
        elif source == "ibd_screener":
            q = """
                SELECT symbol, row_data FROM scan_rows
                WHERE run_id = ? AND dataset = 'trend_template'
            """
            for sym, raw in conn.execute(q, [run_id]).fetchall():
                try:
                    rec = json.loads(raw) if isinstance(raw, str) else {}
                except json.JSONDecodeError:
                    continue
                if rec.get("Passed") is True:
                    s = sym or rec.get("symbol") or rec.get("ticker")
                    if s:
                        symbols.append(str(s).strip())
            symbols = sorted(set(symbols))
        else:
            return {
                "ok": True,
                "symbols": [],
                "run_id": run_id,
                "source": source,
                "note": "unknown source; use MCP get_scan_rows or list_scan_runs",
            }

        return {
            "ok": True,
            "db_path": str(path),
            "run_id": run_id,
            "source": source,
            "symbols": symbols,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "symbols": []}
    finally:
        if conn is not None:
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Swingtrader DuckDB (latest picks)")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()
    payload = latest_passed_symbols()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not payload.get("ok"):
            print(f"Error: {payload.get('error', 'unknown')}")
            sys.exit(1)
        syms = payload.get("symbols") or []
        print(f"run_id={payload.get('run_id')} source={payload.get('source')}")
        for s in syms:
            print(s)


if __name__ == "__main__":
    main()
