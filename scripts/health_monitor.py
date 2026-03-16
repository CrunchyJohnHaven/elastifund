#!/usr/bin/env python3
"""Overnight health monitor — runs every 15 min via cron.

Checks all 6 bots are alive, fills are flowing, balance is stable,
and DBs are growing. Writes alerts to /tmp/elastifund_alerts.log.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SERVICES = [
    "btc-5min-maker",
    "eth-5min-maker",
    "sol-5min-maker",
    "bnb-5min-maker",
    "doge-5min-maker",
    "xrp-5min-maker",
]

DBS = {
    "btc": DATA / "btc_5min_maker.db",
    "eth": DATA / "eth_5min_maker.db",
    "sol": DATA / "sol_5min_maker.db",
    "bnb": DATA / "bnb_5min_maker.db",
    "doge": DATA / "doge_5min_maker.db",
    "xrp": DATA / "xrp_5min_maker.db",
}


def check_bots_running() -> tuple[bool, str]:
    """Check all 6 bot services are active."""
    dead = []
    for svc in SERVICES:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=5
            )
            if r.stdout.strip() != "active":
                dead.append(svc)
        except Exception as e:
            dead.append(f"{svc}({e})")
    if dead:
        return False, f"Dead services: {dead}"
    return True, f"All {len(SERVICES)} services active"


def check_recent_fills(hours: int = 4) -> tuple[bool, str]:
    """Check if any fill occurred in the last N hours across all DBs."""
    cutoff = time.time() - hours * 3600
    total_fills = 0
    for asset, db_path in DBS.items():
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT COUNT(*) FROM window_trades WHERE order_status='live_filled' AND window_start_ts > ?",
                (cutoff,)
            ).fetchone()
            total_fills += row[0] if row else 0
            conn.close()
        except Exception:
            pass
    if total_fills == 0:
        return False, f"No fills in last {hours}h across all assets"
    return True, f"{total_fills} fills in last {hours}h"


def check_db_growing() -> tuple[bool, str]:
    """Check that at least one DB has new rows in last 30 min."""
    cutoff = time.time() - 1800
    any_new = False
    details = {}
    for asset, db_path in DBS.items():
        if not db_path.exists():
            details[asset] = "no_db"
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ?",
                (cutoff,)
            ).fetchone()
            count = row[0] if row else 0
            details[asset] = count
            if count > 0:
                any_new = True
            conn.close()
        except Exception as e:
            details[asset] = str(e)
    if not any_new:
        return False, f"No new rows in 30min: {details}"
    return True, f"Recent rows: {details}"


def check_balance() -> tuple[bool, str]:
    """Check CLOB balance hasn't crashed by reading compound log."""
    log_path = DATA / "compound_log.json"
    if not log_path.exists():
        return True, "No compound log yet"
    try:
        entries = json.loads(log_path.read_text())
        if len(entries) < 2:
            return True, "Too few entries to compare"
        latest = entries[-1]
        prev = entries[-2]
        balance = latest.get("clob_balance", 0)
        prev_balance = prev.get("clob_balance", 0)
        if prev_balance > 0:
            change_pct = (balance - prev_balance) / prev_balance * 100
            if change_pct < -20:
                return False, f"Balance dropped {change_pct:.1f}%: ${prev_balance:.0f} -> ${balance:.0f}"
        return True, f"Balance: ${balance:.2f}"
    except Exception as e:
        return True, f"Could not read compound log: {e}"


def check_win_rate() -> tuple[bool, str]:
    """Check trailing win rate hasn't collapsed."""
    total_wins, total_fills = 0, 0
    for asset, db_path in DBS.items():
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT won FROM window_trades WHERE order_status='live_filled' ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            total_fills += len(rows)
            total_wins += sum(1 for r in rows if r[0])
            conn.close()
        except Exception:
            pass
    if total_fills < 5:
        return True, f"Only {total_fills} fills — too few to judge"
    wr = total_wins / total_fills
    if wr < 0.40:
        return False, f"Win rate collapsed: {wr:.1%} ({total_wins}/{total_fills})"
    return True, f"Win rate: {wr:.1%} ({total_wins}/{total_fills})"


def main():
    now = datetime.now(timezone.utc).isoformat()
    checks = {
        "bots_running": check_bots_running(),
        "recent_fills": check_recent_fills(),
        "db_growing": check_db_growing(),
        "balance_stable": check_balance(),
        "win_rate_ok": check_win_rate(),
    }

    report = {
        "timestamp": now,
        "checks": {k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()},
    }

    # Write report
    report_path = DATA / "health_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    # Print summary
    failures = [k for k, v in checks.items() if not v[0]]
    if failures:
        msg = f"[{now}] ALERT: {failures} — {'; '.join(checks[f][1] for f in failures)}"
        print(msg)
        # Append to alerts log
        with open("/tmp/elastifund_alerts.log", "a") as f:
            f.write(msg + "\n")
    else:
        print(f"[{now}] All checks OK — {'; '.join(v[1] for v in checks.values())}")


if __name__ == "__main__":
    main()
