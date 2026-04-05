"""
SwingTrader tools for Hans tool calling.

Read-only DuckDB tools query the database directly (only needs duckdb).
Screener launchers delegate to swingtrader's own venv Python via subprocess
so Hans doesn't need numpy/pandas/etc.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_SWINGTRADER_ROOT = Path(os.getenv("SWINGTRADER_ROOT", "/Users/kasperisme/projects/swingtrader"))


def _db_path() -> str:
    env = os.getenv("HANS_DUCKDB_PATH", "")
    if env:
        return env
    return str(_SWINGTRADER_ROOT / "data" / "swingtrader.duckdb")


def _connect():
    try:
        import duckdb
    except ImportError:
        raise RuntimeError("duckdb not installed in Hans venv")
    return duckdb.connect(_db_path())


def _rows_to_dicts(rows: list[tuple], cols: list[str]) -> list[dict[str, Any]]:
    return [dict(zip(cols, row)) for row in rows]


def _swingtrader_python() -> str:
    """Resolve swingtrader's venv Python, fall back to system python3."""
    candidate = _SWINGTRADER_ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return os.getenv("SWINGTRADER_PYTHON", "python3")


# ---------------------------------------------------------------------------
# Database / path
# ---------------------------------------------------------------------------

def swingtrader_db_path() -> str:
    """Return the resolved DuckDB file path used by SwingTrader."""
    return _db_path()


# ---------------------------------------------------------------------------
# Scan jobs
# ---------------------------------------------------------------------------

def get_scan_jobs(limit: int = 25) -> str:
    """
    Screening process state from DuckDB (scan_jobs): running/completed/failed, PID, logs,
    linked scan_run_id when finished. Use this to check whether a screen is still running.
    """
    limit = max(1, min(int(limit), 200))
    conn = _connect()
    try:
        cur = conn.execute(f"""
            SELECT id, created_at, started_at, finished_at, status, scan_source, script_rel,
                   args_json, pid, exit_code, scan_run_id, stdout_log, stderr_log,
                   error_message, progress_message
            FROM scan_jobs
            ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                     COALESCE(finished_at, started_at) DESC, id DESC
            LIMIT {limit}
        """)
        return json.dumps(_rows_to_dicts(cur.fetchall(), [d[0] for d in cur.description]), default=str)
    finally:
        conn.close()


def get_scan_job(job_id: int) -> str:
    """Single scan_jobs row by id — state of one screening process (poll this after starting a screener)."""
    conn = _connect()
    try:
        cur = conn.execute("""
            SELECT id, created_at, started_at, finished_at, status, scan_source, script_rel,
                   args_json, pid, exit_code, scan_run_id, stdout_log, stderr_log,
                   error_message, progress_message
            FROM scan_jobs WHERE id = ?
        """, [job_id])
        row = cur.fetchone()
        if not row:
            return json.dumps({"error": "job_id not found", "job_id": job_id})
        return json.dumps(dict(zip([d[0] for d in cur.description], row)), default=str)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scan runs
# ---------------------------------------------------------------------------

def list_scan_runs(limit: int = 20) -> str:
    """List recent screening runs: id, scan_date, source, created_at. JSON array."""
    limit = max(1, min(int(limit), 200))
    conn = _connect()
    try:
        cur = conn.execute(f"""
            SELECT id, created_at, scan_date, source,
                   LENGTH(COALESCE(market_json, '')) AS market_json_len,
                   LENGTH(COALESCE(result_json, '')) AS result_json_len
            FROM scan_runs ORDER BY id DESC LIMIT {limit}
        """)
        return json.dumps(_rows_to_dicts(cur.fetchall(), [d[0] for d in cur.description]), default=str)
    finally:
        conn.close()


def get_run_detail(run_id: int) -> str:
    """Return one scan_runs row including full result_json and market_json (may be large)."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT id, created_at, scan_date, source, market_json, result_json FROM scan_runs WHERE id = ?",
            [run_id],
        )
        row = cur.fetchone()
        if not row:
            return json.dumps({"error": "run_id not found", "run_id": run_id})
        return json.dumps(dict(zip([d[0] for d in cur.description], row)), default=str)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scan rows
# ---------------------------------------------------------------------------

def get_scan_rows(
    run_id: int,
    dataset: str = None,
    symbol: str = None,
    limit: int = 500,
    offset: int = 0,
) -> str:
    """
    Rows from scan_rows for a run. dataset filters: trend_template, rs_rating, quote, passed_stocks.
    Use offset for pagination. row_data is parsed JSON per row.
    """
    limit  = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))
    conn   = _connect()
    try:
        where:  list[str] = ["run_id = ?"]
        params: list[Any] = [run_id]
        if dataset:
            where.append("dataset = ?")
            params.append(dataset)
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        clause = " AND ".join(where)
        cur = conn.execute(
            f"SELECT run_id, scan_date, dataset, symbol, row_data FROM scan_rows WHERE {clause} "
            f"ORDER BY symbol LIMIT {limit} OFFSET {offset}",
            params,
        )
        cols = [d[0] for d in cur.description]
        out  = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            raw = rec.get("row_data")
            if isinstance(raw, str):
                try:
                    rec["row_data_parsed"] = json.loads(raw)
                except json.JSONDecodeError:
                    rec["row_data_parsed"] = None
            out.append(rec)
        total = conn.execute(f"SELECT COUNT(*) FROM scan_rows WHERE {clause}", params).fetchone()[0]
        return json.dumps({"total": total, "offset": offset, "limit": limit, "rows": out}, default=str)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers shared by summary / passed / near-pivot
# ---------------------------------------------------------------------------

def _resolve_passed_dataset(conn, run_id: int) -> tuple[str, str | None]:
    datasets = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT dataset FROM scan_rows WHERE run_id = ?", [run_id]
        ).fetchall()
    }
    if "passed_stocks" in datasets:
        return "passed_stocks", None
    if "trend_template" in datasets:
        return "trend_template", "Passed"
    return "", None


def _extract_stock_fields(rd: dict) -> dict:
    return {
        "symbol":          rd.get("symbol") or rd.get("ticker") or rd.get("Symbol"),
        "sector":          rd.get("sector") or rd.get("Sector"),
        "industry":        rd.get("subSector") or rd.get("industry") or rd.get("Industry"),
        "price":           rd.get("price") or rd.get("Price"),
        "pivot":           rd.get("pivot"),
        "extension_pct":   rd.get("extension_pct"),
        "within_buy_range": rd.get("within_buy_range"),
        "extended":        rd.get("extended"),
        "accumulation":    rd.get("accumulation"),
        "rs_line_new_high": rd.get("rs_line_new_high"),
        "rs_over_70":      rd.get("RSOver70"),
        "adr_pct":         rd.get("adr_pct"),
        "vol_ratio_today": rd.get("vol_ratio_today"),
        "up_down_vol_ratio": rd.get("up_down_vol_ratio"),
        "eps_growth_yoy":  rd.get("eps_growth_yoy"),
        "rev_growth_yoy":  rd.get("rev_growth_yoy"),
    }


# ---------------------------------------------------------------------------
# Aggregated / filtered results
# ---------------------------------------------------------------------------

def get_screener_summary(run_id: int) -> str:
    """
    Aggregate stats for a run: total scanned, passed trend template, within buy range,
    near-pivot count, and sector breakdown. Much lighter than downloading all rows.
    """
    conn = _connect()
    try:
        src_row = conn.execute(
            "SELECT source, scan_date, result_json FROM scan_runs WHERE id = ?", [run_id]
        ).fetchone()
        if not src_row:
            return json.dumps({"error": "run_id not found", "run_id": run_id})
        source, scan_date, result_json = src_row

        if source == "run_screener" and result_json:
            try:
                result = json.loads(result_json)
                passed = result.get("passed_stocks") or []
                within_buy  = sum(1 for s in passed if s.get("within_buy_range"))
                near_pivot  = sum(1 for s in passed if not s.get("extended") and
                                  s.get("extension_pct") is not None and s["extension_pct"] <= 5)
                sec_counts: dict[str, int] = {}
                for s in passed:
                    sec = s.get("sector") or "Unknown"
                    sec_counts[sec] = sec_counts.get(sec, 0) + 1
                return json.dumps({
                    "run_id": run_id, "source": source, "scan_date": str(scan_date),
                    "market_condition": (result.get("market") or {}).get("condition"),
                    "distribution_days": (result.get("market") or {}).get("distribution_days"),
                    "total_ibd_tickers": result.get("total_ibd_tickers"),
                    "total_after_liquidity": result.get("total_after_liquidity"),
                    "pre_screened_count": result.get("pre_screened_count"),
                    "passed_trend_template": result.get("passed_count"),
                    "within_buy_range": within_buy,
                    "near_pivot_count": near_pivot,
                    "error_count": result.get("error_count"),
                    "sector_breakdown": dict(sorted(sec_counts.items(), key=lambda x: -x[1])),
                }, default=str)
            except (json.JSONDecodeError, TypeError):
                pass

        dataset, passed_field = _resolve_passed_dataset(conn, run_id)
        if not dataset:
            return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

        total_rows   = conn.execute("SELECT COUNT(*) FROM scan_rows WHERE run_id=? AND dataset=?",
                                    [run_id, dataset]).fetchone()[0]
        passed_count = (
            conn.execute(
                f"SELECT COUNT(*) FROM scan_rows WHERE run_id=? AND dataset=? "
                f"AND json_extract_string(row_data,'$.{passed_field}') IN ('true','True','1')",
                [run_id, dataset],
            ).fetchone()[0]
            if passed_field else total_rows
        )
        within_buy = conn.execute(
            "SELECT COUNT(*) FROM scan_rows WHERE run_id=? AND dataset=? "
            "AND json_extract_string(row_data,'$.within_buy_range') IN ('true','True','1')",
            [run_id, dataset],
        ).fetchone()[0]
        near_pivot = conn.execute(
            "SELECT COUNT(*) FROM scan_rows WHERE run_id=? AND dataset=? "
            "AND TRY_CAST(json_extract_string(row_data,'$.extension_pct') AS DOUBLE) <= 5 "
            "AND TRY_CAST(json_extract_string(row_data,'$.extension_pct') AS DOUBLE) IS NOT NULL "
            "AND COALESCE(json_extract_string(row_data,'$.extended'),'false') NOT IN ('true','True','1')",
            [run_id, dataset],
        ).fetchone()[0]
        sector_rows = conn.execute(
            "SELECT COALESCE(json_extract_string(row_data,'$.sector'),'Unknown') AS sector, COUNT(*) "
            "FROM scan_rows WHERE run_id=? AND dataset=? GROUP BY sector ORDER BY 2 DESC",
            [run_id, dataset],
        ).fetchall()
        return json.dumps({
            "run_id": run_id, "source": source, "scan_date": str(scan_date),
            "dataset": dataset, "total_scanned": total_rows,
            "passed_trend_template": passed_count,
            "within_buy_range": within_buy, "near_pivot_count": near_pivot,
            "sector_breakdown": {r[0]: r[1] for r in sector_rows},
        }, default=str)
    finally:
        conn.close()


def get_passed_stocks(run_id: int, sector: str = None, limit: int = 200) -> str:
    """
    Stocks that passed the full screen for a run with minimal fields: symbol, sector, price, pivot,
    extension_pct, within_buy_range, accumulation, rs_line_new_high, eps/rev growth.
    Optionally filter by sector (case-insensitive substring). Prefer this over get_scan_rows.
    """
    limit = max(1, min(int(limit), 2000))
    conn  = _connect()
    try:
        dataset, passed_field = _resolve_passed_dataset(conn, run_id)
        if not dataset:
            return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

        where:  list[str] = ["run_id = ?", "dataset = ?"]
        params: list[Any] = [run_id, dataset]
        if passed_field:
            where.append(f"json_extract_string(row_data,'$.{passed_field}') IN ('true','True','1')")

        rows = conn.execute(
            f"SELECT symbol, row_data FROM scan_rows WHERE {' AND '.join(where)} ORDER BY symbol LIMIT {limit}",
            params,
        ).fetchall()

        out = []
        for sym, raw in rows:
            try:
                rd = json.loads(raw) if isinstance(raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                rd = {}
            rec = _extract_stock_fields(rd)
            if sector and not (
                sector.lower() in (rec.get("sector") or "").lower()
                or sector.lower() in (rec.get("industry") or "").lower()
            ):
                continue
            out.append(rec)

        return json.dumps({"run_id": run_id, "count": len(out), "stocks": out}, default=str)
    finally:
        conn.close()


def get_near_pivot_stocks(
    run_id: int,
    min_ext_pct: float = -5.0,
    max_ext_pct: float = 5.0,
    require_accumulation: bool = False,
) -> str:
    """
    Passed stocks within a buy range defined by extension_pct bounds (default -5% to +5%).
    Sorted by extension_pct ascending (closest-to-pivot first).
    Set require_accumulation=True to filter to only accumulating names.
    """
    conn = _connect()
    try:
        dataset, passed_field = _resolve_passed_dataset(conn, run_id)
        if not dataset:
            return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

        where:  list[str] = ["run_id = ?", "dataset = ?"]
        params: list[Any] = [run_id, dataset]
        if passed_field:
            where.append(f"json_extract_string(row_data,'$.{passed_field}') IN ('true','True','1')")

        rows = conn.execute(
            f"SELECT symbol, row_data FROM scan_rows WHERE {' AND '.join(where)} ORDER BY symbol",
            params,
        ).fetchall()

        out = []
        for sym, raw in rows:
            try:
                rd = json.loads(raw) if isinstance(raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                rd = {}
            ext = rd.get("extension_pct")
            if ext is None:
                continue
            try:
                ext = float(ext)
            except (TypeError, ValueError):
                continue
            if not (min_ext_pct <= ext <= max_ext_pct):
                continue
            if require_accumulation and not rd.get("accumulation"):
                continue
            rec = _extract_stock_fields(rd)
            rec["extension_pct"] = ext
            out.append(rec)

        out.sort(key=lambda r: r.get("extension_pct") or 0)
        return json.dumps({"run_id": run_id, "count": len(out), "stocks": out}, default=str)
    finally:
        conn.close()


def get_latest_screener_result() -> str:
    """
    Actionable output of the most recent completed screening run: summary stats + passed stocks.
    Shortcut for list_scan_runs → get_screener_summary → get_passed_stocks.
    """
    conn = _connect()
    try:
        job_row = conn.execute(
            "SELECT scan_run_id FROM scan_jobs WHERE status='completed' AND scan_run_id IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        if job_row:
            run_id = int(job_row[0])
        else:
            run_row = conn.execute("SELECT id FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not run_row:
                return json.dumps({"error": "no completed screening runs found"})
            run_id = int(run_row[0])
    finally:
        conn.close()

    summary = json.loads(get_screener_summary(run_id))
    passed  = json.loads(get_passed_stocks(run_id))
    return json.dumps({
        "run_id": run_id,
        "summary": summary,
        "passed_stocks": passed.get("stocks", []),
    }, default=str)


# ---------------------------------------------------------------------------
# Screener launchers (fire-and-forget via swingtrader's own Python)
# ---------------------------------------------------------------------------

def _run_swingtrader_fn(fn_name: str, **kwargs) -> str:
    """
    Call a swingtrader_mcp.server function by running swingtrader's own Python in a subprocess.
    This avoids pulling all swingtrader deps (numpy, pandas, …) into Hans's venv.
    """
    python = _swingtrader_python()
    kwarg_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    code = (
        f"from swingtrader_mcp.server import {fn_name}; "
        f"print({fn_name}({kwarg_str}))"
    )
    try:
        result = subprocess.run(
            [python, "-c", code],
            cwd=str(_SWINGTRADER_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = result.stdout.strip()
        if out:
            return out
        err = result.stderr.strip()
        return json.dumps({"error": err or "no output from swingtrader"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "swingtrader subprocess timed out"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def run_ibd_market_screener() -> str:
    """
    Start ibd_screener.py (NYSE/NASDAQ market-wide Minervini screen) in the background — returns immediately.
    Poll get_scan_job with the returned job_id to check status.
    """
    return _run_swingtrader_fn("run_ibd_market_screener")


def run_json_screener(ibd_file: str = "./input/IBD Data Tables.xlsx", lookback_days: int = 365) -> str:
    """
    Start scripts/run_screener.py (IBD + Minervini pipeline) in the background — returns immediately.
    Poll get_scan_job with the returned job_id to check status.
    """
    return _run_swingtrader_fn("run_json_screener", ibd_file=ibd_file, lookback_days=lookback_days)
