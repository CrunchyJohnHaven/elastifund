#!/usr/bin/env python3
"""BTC5 P&L monitoring alert script.

Checks the BTC5 trade database for drawdown breaches and emits
CRITICAL / WARNING alerts to stdout (and optionally Telegram).

Designed to run via cron or systemd timer every 5 minutes on the VPS.

Usage:
    python3 scripts/btc5_pnl_monitor.py [--db PATH] [--alert-threshold -50] [--window-hours 24]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("btc5_pnl_monitor")

DEFAULT_DB = Path("data/btc_5min_maker.db")
DEFAULT_ALERT_THRESHOLD_USD = -50.0
DEFAULT_WINDOW_HOURS = 24
REPORT_DIR = Path("reports")


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        log.error("Database not found: %s", db_path)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def window_pnl(conn: sqlite3.Connection, window_hours: float) -> dict:
    """Compute aggregate P&L over the trailing window."""
    cutoff = time.time() - (window_hours * 3600)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS fills,
            COALESCE(SUM(pnl_usd), 0.0) AS total_pnl,
            COALESCE(MIN(pnl_usd), 0.0) AS worst_fill,
            COALESCE(MAX(pnl_usd), 0.0) AS best_fill,
            COALESCE(SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN won = 0 THEN 1 ELSE 0 END), 0) AS losses
        FROM window_trades
        WHERE filled = 1 AND created_at >= ?
        """,
        (cutoff_iso,),
    ).fetchone()
    return dict(row) if row else {}


def trailing_drawdown(conn: sqlite3.Connection, limit: int = 200) -> float:
    """Compute max drawdown from the last N fills."""
    rows = conn.execute(
        """
        SELECT pnl_usd FROM window_trades
        WHERE filled = 1
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    # Walk in chronological order (rows are newest-first).
    for r in reversed(rows):
        cumulative += float(r["pnl_usd"] or 0)
        if cumulative > peak:
            peak = cumulative
        dd = cumulative - peak
        if dd < max_dd:
            max_dd = dd
    return round(max_dd, 4)


def latest_fill_age_minutes(conn: sqlite3.Connection) -> float | None:
    """Minutes since the most recent fill."""
    row = conn.execute(
        "SELECT MAX(created_at) AS latest FROM window_trades WHERE filled = 1"
    ).fetchone()
    if not row or not row["latest"]:
        return None
    try:
        ts = datetime.strptime(row["latest"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        try:
            ts = datetime.fromisoformat(row["latest"]).replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 60.0, 1)


def check_alerts(
    stats: dict,
    drawdown: float,
    fill_age_min: float | None,
    alert_threshold: float,
) -> list[dict]:
    """Return a list of alert dicts (level, message)."""
    alerts: list[dict] = []

    total_pnl = float(stats.get("total_pnl", 0))
    if total_pnl <= alert_threshold:
        alerts.append(
            {
                "level": "CRITICAL",
                "message": (
                    f"24h P&L breached alert threshold: "
                    f"${total_pnl:.2f} <= ${alert_threshold:.2f}"
                ),
            }
        )

    if drawdown <= alert_threshold:
        alerts.append(
            {
                "level": "CRITICAL",
                "message": (
                    f"Trailing drawdown breached: ${drawdown:.2f} <= ${alert_threshold:.2f}"
                ),
            }
        )

    if total_pnl < 0 and total_pnl > alert_threshold:
        alerts.append(
            {
                "level": "WARNING",
                "message": f"24h P&L negative: ${total_pnl:.2f} (threshold: ${alert_threshold:.2f})",
            }
        )

    if fill_age_min is not None and fill_age_min > 360:
        alerts.append(
            {
                "level": "WARNING",
                "message": f"No fills in {fill_age_min:.0f} minutes ({fill_age_min/60:.1f}h)",
            }
        )

    fills = int(stats.get("fills", 0))
    losses = int(stats.get("losses", 0))
    if fills >= 5 and losses > 0 and (losses / fills) > 0.65:
        alerts.append(
            {
                "level": "WARNING",
                "message": (
                    f"High loss rate: {losses}/{fills} = "
                    f"{100*losses/fills:.0f}% over trailing window"
                ),
            }
        )

    return alerts


def write_report(
    stats: dict,
    drawdown: float,
    fill_age_min: float | None,
    alerts: list[dict],
    report_path: Path,
) -> None:
    """Write JSON monitoring report."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "window_stats": stats,
        "trailing_drawdown_usd": drawdown,
        "latest_fill_age_minutes": fill_age_min,
        "alerts": alerts,
        "alert_count": len(alerts),
        "critical_count": sum(1 for a in alerts if a["level"] == "CRITICAL"),
    }
    report_path.write_text(json.dumps(payload, indent=2, default=str))
    log.info("Report written to %s", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC5 P&L monitor")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="Path to BTC5 SQLite DB"
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=DEFAULT_ALERT_THRESHOLD_USD,
        help="P&L alert threshold in USD (negative)",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=DEFAULT_WINDOW_HOURS,
        help="Lookback window in hours",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=REPORT_DIR, help="Directory for report output"
    )
    args = parser.parse_args()

    conn = _connect(args.db)

    stats = window_pnl(conn, args.window_hours)
    drawdown = trailing_drawdown(conn)
    fill_age = latest_fill_age_minutes(conn)
    alerts = check_alerts(stats, drawdown, fill_age, args.alert_threshold)

    report_path = args.report_dir / "btc5_pnl_monitor_latest.json"
    write_report(stats, drawdown, fill_age, alerts, report_path)

    for alert in alerts:
        if alert["level"] == "CRITICAL":
            log.critical("%s", alert["message"])
        else:
            log.warning("%s", alert["message"])

    if not alerts:
        total_pnl = float(stats.get("total_pnl", 0))
        fills = int(stats.get("fills", 0))
        log.info(
            "OK — %dh window: %d fills, $%.2f P&L, drawdown $%.2f",
            int(args.window_hours),
            fills,
            total_pnl,
            drawdown,
        )

    conn.close()

    # Exit code: 2 for CRITICAL, 0 for WARNING or clean.
    # systemd treats any non-zero exit as failure, so only CRITICAL
    # (actionable drawdown breach) should produce a non-zero exit.
    if any(a["level"] == "CRITICAL" for a in alerts):
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
