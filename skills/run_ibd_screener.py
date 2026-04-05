#!/usr/bin/env python3
"""
Run Swingtrader's IBD screener from Hans.

This wrapper keeps Swingtrader isolated in its own repo while giving Hans a
stable JSON output for Claude prompts, scripts, and automation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add Hans repo root for logging_config import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logging_config import setup_logging

load_dotenv()

log = setup_logging("hans.skills.swingtrader")

DEFAULT_SWINGTRADER_ROOT = "/Users/kasperisme/projects/swingtrader"


def _read_top_picks(output_dir: Path, limit: int = 20) -> list[str]:
    picks_file = output_dir / "IBD_trend_template.txt"
    if not picks_file.exists():
        return []
    try:
        lines = [
            line.strip()
            for line in picks_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return lines[:limit]
    except Exception:
        return []


def run_ibd_screener(
    swingtrader_root: Path,
    python_bin: str,
    timeout_sec: int,
) -> dict:
    script_path = swingtrader_root / "ibd_screener.py"
    output_dir = swingtrader_root / "output"

    if not swingtrader_root.exists():
        return {"ok": False, "error": f"Swingtrader root not found: {swingtrader_root}"}
    if not script_path.exists():
        return {"ok": False, "error": f"Entry point not found: {script_path}"}

    env = os.environ.copy()
    if not env.get("APIKEY"):
        return {
            "ok": False,
            "error": "Missing APIKEY in environment (.env) for Financial Modeling Prep",
        }

    cmd = [python_bin, str(script_path)]
    log.info("Running IBD screener: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            cwd=str(swingtrader_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"IBD screener timed out after {timeout_sec}s",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Failed to run IBD screener: {exc}"}

    top_picks = _read_top_picks(output_dir)
    excel_path = output_dir / "IBD_trend_template.xlsx"
    txt_path = output_dir / "IBD_trend_template.txt"

    payload = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "top_picks": top_picks,
        "top_picks_count": len(top_picks),
        "output_files": {
            "excel": str(excel_path) if excel_path.exists() else None,
            "txt": str(txt_path) if txt_path.exists() else None,
        },
    }

    if result.stdout.strip():
        payload["stdout_tail"] = result.stdout.strip()[-2000:]
    if result.stderr.strip():
        payload["stderr_tail"] = result.stderr.strip()[-2000:]

    if result.returncode != 0 and "error" not in payload:
        payload["error"] = "IBD screener exited with non-zero status"

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run swingtrader IBD screener")
    parser.add_argument(
        "--swingtrader-root",
        default=os.getenv("SWINGTRADER_ROOT", DEFAULT_SWINGTRADER_ROOT),
        help="Path to swingtrader repository",
    )
    parser.add_argument(
        "--python-bin",
        default=os.getenv("SWINGTRADER_PYTHON", "python3"),
        help="Python executable for swingtrader environment",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=int(os.getenv("SWINGTRADER_TIMEOUT_SEC", "3600")),
        help="Max seconds to allow screener run",
    )
    args = parser.parse_args()

    payload = run_ibd_screener(
        swingtrader_root=Path(args.swingtrader_root),
        python_bin=args.python_bin,
        timeout_sec=args.timeout_sec,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
