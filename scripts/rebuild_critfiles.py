#!/usr/bin/env python3
"""Auto-rebuild critfiles.txt — complete system context for LLM sessions.

Runs every 3 hours via cron. Concatenates all critical files with headers.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path("/home/ubuntu/polymarket-trading-bot")
OUTPUT = BOT_DIR / "critfiles.txt"
DB_PATH = BOT_DIR / "data" / "btc_5min_maker.db"

SECTIONS = [
    ("bot/btc_5min_maker.py", "TRADING BOT"),
    ("bot/polymarket_clob.py", "CLOB CLIENT"),
    ("bot/autoresearch_loop.py", "AUTORESEARCH LOOP"),
    ("bot/adaptive_floor.py", "ADAPTIVE FLOOR (DISABLED)"),
    ("bot/auto_promote.py", "AUTO PROMOTE (DISABLED)"),
    ("config/btc5_strategy.env", "STRATEGY CONFIG"),
    ("state/btc5_capital_stage.env", "CAPITAL STAGE CONFIG"),
    ("config/autoresearch_overrides.json", "AUTORESEARCH OVERRIDES"),
    ("scripts/replay_simulator.py", "REPLAY SIMULATOR"),
    ("scripts/realtime_monitor.py", "REALTIME MONITOR"),
    ("scripts/autoresearch_trigger.py", "AUTORESEARCH TRIGGER"),
    ("scripts/backfill_resolutions.py", "BACKFILL RESOLUTIONS"),
    ("scripts/build_frontier.py", "FRONTIER BUILDER"),
    ("scripts/cost_ledger.py", "COST LEDGER"),
]

REPORT_FILES = [
    "reports/h1_decision_grade_report.md",
    "reports/h1_h2_test_results.md",
    "reports/system_audit.md",
    "reports/research_hypotheses.md",
    "reports/realtime_monitor.json",
]

DATA_FILES = [
    "data/exact_actionable_frontier.json",
    "data/signal_only_frontier.json",
    "data/ev_consistency_audit.json",
    "data/h_dir_down_diagnosis.json",
    "data/baseline_snapshot.json",
    "data/btc5_wallet_analysis.json",
    "data/h1_decomposition_090.json",
]

DEPLOY_FILES = [
    "deploy/btc-5min-maker.service",
    "deploy/autoresearch-trigger.service",
    "deploy/autoresearch-trigger.timer",
    "deploy/realtime-monitor.service",
    "deploy/realtime-monitor.timer",
    "deploy/btc5-autoresearch-v3.service",
    "deploy/btc5-autoresearch-v3.timer",
]

DOC_FILES = [
    "CLAUDE.md",
    "COMMAND_NODE.md",
    "PROJECT_INSTRUCTIONS.md",
]


def _header(title: str) -> str:
    return f"\n{'#' * 10} {title} {'#' * 10}\n"


def _read_file(rel_path: str) -> str:
    full = BOT_DIR / rel_path
    if not full.exists():
        return f"[FILE NOT FOUND: {rel_path}]"
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[READ ERROR: {e}]"


def _db_summary() -> str:
    if not DB_PATH.exists():
        return "[DB NOT FOUND]"
    try:
        conn = sqlite3.connect(str(DB_PATH))
        lines = []

        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='window_trades'"
        ).fetchone()
        lines.append("--- Schema ---")
        lines.append(schema[0] if schema else "[no schema]")

        lines.append("\n--- Recent 50 windows ---")
        rows = conn.execute("""
            SELECT datetime(window_start_ts,'unixepoch'), direction, order_status,
                   best_ask, order_price, trade_size_usd, pnl_usd, delta,
                   sizing_reason_tags
            FROM window_trades ORDER BY window_start_ts DESC LIMIT 50
        """).fetchall()
        for r in rows:
            lines.append("|".join("" if x is None else str(x) for x in r))

        lines.append("\n--- Fill summary ---")
        rows = conn.execute("""
            SELECT order_status, COUNT(*),
                   ROUND(SUM(pnl_usd),4), ROUND(AVG(pnl_usd),4)
            FROM window_trades
            GROUP BY order_status ORDER BY COUNT(*) DESC
        """).fetchall()
        for r in rows:
            lines.append("|".join("" if x is None else str(x) for x in r))

        lines.append("\n--- Direction performance ---")
        rows = conn.execute("""
            SELECT direction, COUNT(*), SUM(CASE WHEN won=1 THEN 1 ELSE 0 END),
                   ROUND(1.0*SUM(CASE WHEN won=1 THEN 1 ELSE 0 END)/COUNT(*),3),
                   ROUND(SUM(pnl_usd),4), ROUND(AVG(order_price),3)
            FROM window_trades WHERE filled=1
            GROUP BY direction
        """).fetchall()
        for r in rows:
            lines.append("|".join("" if x is None else str(x) for x in r))

        conn.close()
        return "\n".join(lines)
    except Exception as e:
        return f"[DB ERROR: {e}]"


def _crontab() -> str:
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        return result.stdout
    except Exception:
        return "[crontab unavailable]"


def _live_env() -> str:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "btc_5min_maker.py"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return "[bot not running]"
        pid = pids[0]
        env_path = Path(f"/proc/{pid}/environ")
        if not env_path.exists():
            return f"[/proc/{pid}/environ not found]"
        raw = env_path.read_bytes()
        lines = []
        for entry in raw.split(b"\x00"):
            try:
                decoded = entry.decode("utf-8", errors="replace")
                if "=" in decoded:
                    k, v = decoded.split("=", 1)
                    if k.startswith("BTC5_") or k in {"POLY_SIGNATURE_TYPE", "JJ_RUNTIME_PROFILE"}:
                        lines.append(f"{k}={v}")
            except Exception:
                pass
        return "\n".join(sorted(lines))
    except Exception as e:
        return f"[error: {e}]"


def _systemd_live() -> str:
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "cat", "btc-5min-maker.service"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout
    except Exception:
        return "[systemctl unavailable]"


def build() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = []

    parts.append("=" * 42)
    parts.append("CRITFILES.TXT — Elastifund Critical Files")
    parts.append(f"Generated: {now}")
    parts.append("Purpose: Complete system context for LLM evaluation")
    parts.append("=" * 42)

    # Source files
    for rel_path, title in SECTIONS:
        parts.append(_header(title))
        parts.append(f"--- {rel_path} ---")
        parts.append(_read_file(rel_path))

    # Deploy files
    parts.append(_header("SYSTEMD SERVICE FILES"))
    for rel_path in DEPLOY_FILES:
        parts.append(f"--- {rel_path} ---")
        parts.append(_read_file(rel_path))
    parts.append("\n--- /etc/systemd/system/btc-5min-maker.service (live) ---")
    parts.append(_systemd_live())

    # Crontab
    parts.append(_header("CRONTAB"))
    parts.append(_crontab())

    # Reports
    parts.append(_header("REPORTS"))
    for rel_path in REPORT_FILES:
        parts.append(f"--- {rel_path} ---")
        parts.append(_read_file(rel_path))

    # Data artifacts (truncate large JSON)
    parts.append(_header("DATA ARTIFACTS"))
    for rel_path in DATA_FILES:
        parts.append(f"--- {rel_path} ---")
        content = _read_file(rel_path)
        lines = content.splitlines()
        if len(lines) > 200:
            parts.append("\n".join(lines[:200]))
            parts.append(f"\n[... truncated {len(lines)-200} lines ...]")
        else:
            parts.append(content)

    # Docs
    parts.append(_header("DOCS"))
    for rel_path in DOC_FILES:
        parts.append(f"--- {rel_path} ---")
        parts.append(_read_file(rel_path))

    # DB summary
    parts.append(_header("DATABASE STATE"))
    parts.append(_db_summary())

    # Live process environ
    parts.append(_header("LIVE BOT ENVIRON"))
    parts.append(_live_env())

    text = "\n".join(parts)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"[rebuild_critfiles] Written {len(text):,} bytes ({OUTPUT})")
    return text


if __name__ == "__main__":
    build()
