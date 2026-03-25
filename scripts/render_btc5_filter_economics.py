#!/usr/bin/env python3
"""
render_btc5_filter_economics.py

Analyzes filter_decisions table and produces reports/btc5_filter_economics_latest.json.

Usage:
    python3 scripts/render_btc5_filter_economics.py [--db-path PATH]
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve project root
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB_PATH = next(
    (p for p in [
        PROJECT_ROOT / "data" / "btc_5min_maker.db",
        PROJECT_ROOT / "bot" / "data" / "btc_5min_maker.db",
        PROJECT_ROOT / "btc_5min_maker.db",
    ] if p.exists()),
    PROJECT_ROOT / "data" / "btc_5min_maker.db",
)
REPORTS_DIR = PROJECT_ROOT / "reports"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def render(db_path: Path) -> dict:
    if not db_path.exists():
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": f"DB not found at {db_path}",
            "total_filter_decisions": 0,
            "by_filter": {},
            "db_path_used": str(db_path),
            "note": "net_filter_value_usd will be populated as windows resolve",
        }

    conn = _connect(db_path)

    if not _table_exists(conn, "filter_decisions"):
        conn.close()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": "filter_decisions table does not exist yet",
            "total_filter_decisions": 0,
            "by_filter": {},
            "db_path_used": str(db_path),
            "note": "net_filter_value_usd will be populated as windows resolve",
        }

    total = conn.execute("SELECT COUNT(*) FROM filter_decisions").fetchone()[0]

    # --- direction_filter ---
    direction_rows = conn.execute(
        """
        SELECT COUNT(*) AS cnt,
               SUM(COALESCE(counterfactual_trade_size_usd, 0)) AS total_cf_usd,
               AVG(COALESCE(counterfactual_entry_price, 0)) AS avg_price
        FROM filter_decisions
        WHERE filter_name = 'direction_filter'
          AND filter_state = 'blocked'
        """
    ).fetchone()

    direction_filter_out = {
        "total_blocked": int(direction_rows["cnt"] or 0),
        "total_counterfactual_usd": round(float(direction_rows["total_cf_usd"] or 0.0), 4),
        "avg_blocked_price": round(float(direction_rows["avg_price"] or 0.0), 6),
    }

    # --- hour_filter by hour ---
    hour_rows = conn.execute(
        """
        SELECT hour_et,
               COUNT(*) AS blocked,
               SUM(COALESCE(counterfactual_trade_size_usd, 0)) AS cf_usd
        FROM filter_decisions
        WHERE filter_name = 'hour_filter'
          AND filter_state = 'blocked'
        GROUP BY hour_et
        ORDER BY hour_et
        """
    ).fetchall()

    hour_filter_out = {
        "by_hour_et": [
            {
                "hour": int(r["hour_et"]) if r["hour_et"] is not None else None,
                "blocked": int(r["blocked"]),
                "counterfactual_usd": round(float(r["cf_usd"] or 0.0), 4),
            }
            for r in hour_rows
        ]
    }

    # --- up_live_mode ---
    up_rows = conn.execute(
        """
        SELECT COUNT(*) AS cnt,
               SUM(COALESCE(counterfactual_trade_size_usd, 0)) AS total_cf_usd
        FROM filter_decisions
        WHERE filter_name = 'up_live_mode'
          AND filter_state = 'shadow_only'
        """
    ).fetchone()

    up_live_mode_out = {
        "total_shadow_only": int(up_rows["cnt"] or 0),
        "total_counterfactual_usd": round(float(up_rows["total_cf_usd"] or 0.0), 4),
    }

    # --- cap_breach ---
    cap_rows = conn.execute(
        """
        SELECT COUNT(*) AS cnt,
               SUM(COALESCE(counterfactual_trade_size_usd, 0)) AS total_cf_usd,
               MAX(COALESCE(counterfactual_trade_size_usd, 0)) AS worst_breach
        FROM filter_decisions
        WHERE filter_name = 'cap_breach'
          AND filter_state = 'blocked'
        """
    ).fetchone()

    cap_breach_out = {
        "total_blocked": int(cap_rows["cnt"] or 0),
        "total_counterfactual_usd": round(float(cap_rows["total_cf_usd"] or 0.0), 4),
        "worst_breach_usd": round(float(cap_rows["worst_breach"] or 0.0), 4),
    }

    conn.close()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_filter_decisions": int(total),
        "by_filter": {
            "direction_filter": direction_filter_out,
            "hour_filter": hour_filter_out,
            "up_live_mode": up_live_mode_out,
            "cap_breach": cap_breach_out,
        },
        "db_path_used": str(db_path),
        "note": "net_filter_value_usd will be populated as windows resolve",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render BTC5 filter economics report")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: reports/btc5_filter_economics_latest.json)",
    )
    args = parser.parse_args()

    db_path: Path = args.db_path
    output_path: Path = args.output or (REPORTS_DIR / "btc5_filter_economics_latest.json")

    result = render(db_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    print(f"\nWritten to: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
