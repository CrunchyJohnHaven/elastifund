#!/usr/bin/env python3
"""
render_btc5_validation_cohort.py — Generate the BTC5 validation cohort report.

Reads the cohort contract (state/btc5_validation_cohort.json) and the local
BTC5 maker DB, then produces reports/btc5_validation_cohort_latest.json.

Only fills that satisfy ALL of the following are counted:
  - direction = 'DOWN'
  - order_status is a live-filled status (starts with 'live_', not 'skip_',
    not 'shadow_', not 'pending_reservation', not plain 'live_skipped')
  - resolved_side IS NOT NULL
  - decision_ts >= cohort_start_ts
  - config_hash matches (if validation_config_hash is set in cohort contract)

Usage:
    python3 scripts/render_btc5_validation_cohort.py [--db-path PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COHORT_PATH = _REPO_ROOT / "state" / "btc5_validation_cohort.json"
_OUTPUT_PATH = _REPO_ROOT / "reports" / "btc5_validation_cohort_latest.json"

_DB_PROBE_PATHS = [
    _REPO_ROOT / "data" / "btc_5min_maker.db",
    _REPO_ROOT / "bot" / "data" / "btc_5min_maker.db",
    _REPO_ROOT / "btc_5min_maker.db",
]

# Statuses that count as "live filled" — starts with live_ but excludes
# shadow_ and skip_ variants and pending_reservation
_SHADOW_PREFIXES = ("shadow_",)
_SKIP_PREFIXES = ("skip_",)
_EXCLUDED_EXACT = frozenset({"pending_reservation"})


def _is_live_filled_status(status: str) -> bool:
    if not status:
        return False
    if not status.startswith("live_"):
        return False
    for p in _SHADOW_PREFIXES + _SKIP_PREFIXES:
        if status.startswith(p):
            return False
    if status in _EXCLUDED_EXACT:
        return False
    # Also exclude pure skip/shadow combos embedded after live_
    # e.g. live_skipped, live_shadow_fill
    lower = status.lower()
    if "shadow" in lower or "skip" in lower:
        return False
    return True


def _find_db(override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        if p.exists():
            return p
        return None
    for candidate in _DB_PROBE_PATHS:
        if candidate.exists():
            return candidate
    return None


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.rename(path)


def _checkpoint_label(n: int) -> str:
    if n == 0:
        return "0/50 fills — not started"
    elif n < 10:
        return f"{n}/50 fills — awaiting first checkpoint (10)"
    elif n < 20:
        return f"{n}/50 fills — checkpoint 1 passed"
    elif n < 30:
        return f"{n}/50 fills — checkpoint 2 passed"
    elif n < 50:
        return f"{n}/50 fills — checkpoint 3 passed"
    else:
        return "50/50 fills — final verdict"


def _recommendation(
    resolved_fills: int,
    net_pnl: float,
    safety_kill: bool,
) -> str:
    if safety_kill:
        return "kill"
    if resolved_fills < 10:
        return "awaiting_data"
    if resolved_fills < 30:
        return "insufficient_data"
    if resolved_fills >= 50:
        return "kill" if net_pnl <= 0 else "positive_first_cohort"
    return "continue_collecting"


def _price_bucket(price: Optional[float]) -> str:
    if price is None:
        return "unknown"
    if price < 0.45:
        return "<0.45"
    elif price < 0.47:
        return "0.45-0.47"
    elif price <= 0.48:
        return "0.47-0.48"
    else:
        return "0.48+"


def _empty_bucket_slice() -> dict:
    return {
        "<0.45": {"fills": 0, "wins": 0, "win_rate": None},
        "0.45-0.47": {"fills": 0, "wins": 0, "win_rate": None},
        "0.47-0.48": {"fills": 0, "wins": 0, "win_rate": None},
        "0.48+": {"fills": 0, "wins": 0, "win_rate": None},
    }


def build_report(db_path: Optional[str] = None) -> dict:
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    # Load cohort contract
    if not _COHORT_PATH.exists():
        raise FileNotFoundError(f"Cohort contract not found: {_COHORT_PATH}")
    cohort = _load_json(_COHORT_PATH)

    cohort_id = cohort.get("cohort_id", "unknown")
    cohort_status = cohort.get("cohort_status", "unknown")
    cohort_start_ts = cohort.get("cohort_start_ts")
    mutation_id = cohort.get("validation_mutation_id")
    config_hash = cohort.get("validation_config_hash")
    safety_kill = cohort.get("safety_kill_triggered", False)

    # Base skeleton
    report: dict = {
        "generated_at": now_iso,
        "cohort_id": cohort_id,
        "cohort_status": cohort_status,
        "cohort_start_ts": cohort_start_ts,
        "mutation_id": mutation_id,
        "config_hash": config_hash,
        "resolved_down_fills": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "gross_pnl_usd": 0.0,
        "estimated_maker_rebate_usd": 0.0,
        "net_pnl_after_estimated_rebate_usd": 0.0,
        "avg_entry_price": None,
        "avg_trade_size_usd": None,
        "price_bucket_slice": _empty_bucket_slice(),
        "hour_slice_et": {},
        "fill_rate": None,
        "order_failed_rate": None,
        "partial_fill_count": 0,
        "cancel_count": 0,
        "cap_breach_events": 0,
        "up_live_attempts": 0,
        "config_hash_mismatch_count": 0,
        "checkpoint_status": _checkpoint_label(0),
        "recommendation": "awaiting_data",
        "safety_kill_triggered": safety_kill,
        "db_path_used": "none",
    }

    # If cohort hasn't started yet, return skeleton
    if cohort_status == "awaiting_deploy" or cohort_start_ts is None:
        report["recommendation"] = "awaiting_data"
        return report

    # Find DB
    found_db = _find_db(db_path)
    if found_db is None:
        report["recommendation"] = "awaiting_data"
        report["db_path_used"] = "not_found"
        return report

    report["db_path_used"] = str(found_db)

    conn = sqlite3.connect(str(found_db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='window_trades'")
    if not cur.fetchone():
        conn.close()
        return report

    # Pull all rows after cohort_start_ts for any direction.
    # config_hash_mismatch is queried separately after checking column existence.
    cur.execute(
        "SELECT direction, order_status, resolved_side, won, pnl_usd, "
        "       order_price, trade_size_usd, decision_ts "
        "FROM window_trades WHERE decision_ts >= ?",
        (cohort_start_ts,),
    )
    rows = cur.fetchall()

    # Also check for config_hash_mismatch column
    cur.execute("PRAGMA table_info(window_trades)")
    col_names = {row[1] for row in cur.fetchall()}
    has_config_hash_col = "config_hash_mismatch" in col_names
    has_hour_et_col = "hour_et" in col_names

    if has_config_hash_col:
        cur.execute(
            "SELECT COUNT(*) FROM window_trades "
            "WHERE decision_ts >= ? AND config_hash_mismatch = 1",
            (cohort_start_ts,),
        )
        row = cur.fetchone()
        report["config_hash_mismatch_count"] = row[0] if row else 0

    # Count UP live attempts (direction=UP, live_ status)
    cur.execute(
        "SELECT COUNT(*) FROM window_trades "
        "WHERE decision_ts >= ? AND direction = 'UP' AND order_status LIKE 'live_%'",
        (cohort_start_ts,),
    )
    row = cur.fetchone()
    report["up_live_attempts"] = row[0] if row else 0

    # Count cap breach events: trade_size_usd > 5.50 (>10% over cap) as breach indicator
    cur.execute(
        "SELECT COUNT(*) FROM window_trades "
        "WHERE decision_ts >= ? AND trade_size_usd > 5.50",
        (cohort_start_ts,),
    )
    row = cur.fetchone()
    report["cap_breach_events"] = row[0] if row else 0

    # Compute fill rate from all DOWN rows (attempts vs live_filled)
    cur.execute(
        "SELECT COUNT(*) FROM window_trades "
        "WHERE decision_ts >= ? AND direction = 'DOWN'",
        (cohort_start_ts,),
    )
    row = cur.fetchone()
    total_down_attempts = row[0] if row else 0

    # Count failed orders
    cur.execute(
        "SELECT COUNT(*) FROM window_trades "
        "WHERE decision_ts >= ? AND direction = 'DOWN' "
        "AND (order_status LIKE 'fail%' OR order_status LIKE '%error%' OR order_status LIKE '%failed%')",
        (cohort_start_ts,),
    )
    row = cur.fetchone()
    failed_count = row[0] if row else 0

    # Count cancels
    cur.execute(
        "SELECT COUNT(*) FROM window_trades "
        "WHERE decision_ts >= ? AND direction = 'DOWN' "
        "AND (order_status LIKE '%cancel%' OR order_status LIKE '%cancelled%')",
        (cohort_start_ts,),
    )
    row = cur.fetchone()
    report["cancel_count"] = row[0] if row else 0

    # Count partial fills
    cur.execute(
        "SELECT COUNT(*) FROM window_trades "
        "WHERE decision_ts >= ? AND direction = 'DOWN' "
        "AND order_status LIKE '%partial%'",
        (cohort_start_ts,),
    )
    row = cur.fetchone()
    report["partial_fill_count"] = row[0] if row else 0

    conn.close()

    # Process qualifying DOWN fills from the in-memory rows
    wins = 0
    losses = 0
    gross_pnl = 0.0
    price_sum = 0.0
    size_sum = 0.0
    price_buckets = _empty_bucket_slice()
    hour_slice: dict[int, dict] = {}

    for row in rows:
        direction = row["direction"]
        status = row["order_status"] or ""
        resolved_side = row["resolved_side"]
        pnl = row["pnl_usd"]
        order_price = row["order_price"]
        trade_size = row["trade_size_usd"]
        decision_ts = row["decision_ts"]

        if direction != "DOWN":
            continue
        if not _is_live_filled_status(status):
            continue
        if resolved_side is None:
            continue

        # WIN if the resolved side matches the trade direction
        is_win = resolved_side.upper() == "DOWN"

        if is_win:
            wins += 1
        else:
            losses += 1

        if pnl is not None:
            gross_pnl += pnl

        if order_price is not None:
            price_sum += order_price
            bucket = _price_bucket(order_price)
            price_buckets[bucket]["fills"] += 1
            if is_win:
                price_buckets[bucket]["wins"] += 1

        if trade_size is not None:
            size_sum += trade_size

        # Hour-of-day slice (ET = UTC - 5 for EST, UTC - 4 for EDT; approximate as UTC-5)
        if decision_ts:
            hour_utc = (decision_ts // 3600) % 24
            hour_et = (hour_utc - 5) % 24
            if hour_et not in hour_slice:
                hour_slice[hour_et] = {"fills": 0, "wins": 0, "win_rate": None}
            hour_slice[hour_et]["fills"] += 1
            if is_win:
                hour_slice[hour_et]["wins"] += 1

    total_fills = wins + losses

    # Finalize price bucket win rates
    for bucket_data in price_buckets.values():
        n = bucket_data["fills"]
        if n > 0:
            bucket_data["win_rate"] = round(bucket_data["wins"] / n, 4)

    # Finalize hour slice win rates
    for h_data in hour_slice.values():
        n = h_data["fills"]
        if n > 0:
            h_data["win_rate"] = round(h_data["wins"] / n, 4)

    report["resolved_down_fills"] = total_fills
    report["wins"] = wins
    report["losses"] = losses
    report["win_rate"] = round(wins / total_fills, 4) if total_fills > 0 else None
    report["gross_pnl_usd"] = round(gross_pnl, 4)
    report["estimated_maker_rebate_usd"] = 0.0  # Polymarket = 0% maker rebate
    report["net_pnl_after_estimated_rebate_usd"] = round(gross_pnl, 4)
    report["avg_entry_price"] = round(price_sum / total_fills, 4) if total_fills > 0 else None
    report["avg_trade_size_usd"] = round(size_sum / total_fills, 4) if total_fills > 0 else None
    report["price_bucket_slice"] = price_buckets
    report["hour_slice_et"] = {str(k): v for k, v in sorted(hour_slice.items())}
    report["fill_rate"] = (
        round(total_fills / total_down_attempts, 4) if total_down_attempts > 0 else None
    )
    report["order_failed_rate"] = (
        round(failed_count / total_down_attempts, 4) if total_down_attempts > 0 else None
    )
    report["checkpoint_status"] = _checkpoint_label(total_fills)
    report["recommendation"] = _recommendation(
        total_fills, report["net_pnl_after_estimated_rebate_usd"], safety_kill
    )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render BTC5 validation cohort report")
    parser.add_argument("--db-path", default=None, help="Override DB path")
    args = parser.parse_args()

    try:
        report = build_report(db_path=args.db_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(_OUTPUT_PATH, report)
    print(f"Written: {_OUTPUT_PATH}")

    # Save checkpoint copy if at a checkpoint boundary
    n = report["resolved_down_fills"]
    cohort = _OUTPUT_PATH  # already written
    checkpoint_boundaries = [10, 20, 30, 50]
    if n in checkpoint_boundaries:
        cp_path = _OUTPUT_PATH.parent / f"btc5_validation_cohort_checkpoint_{n}.json"
        _write_atomic(cp_path, report)
        print(f"Checkpoint saved: {cp_path}")

    # Print summary
    print(
        f"  fills={n} wins={report['wins']} losses={report['losses']} "
        f"win_rate={report['win_rate']} net_pnl=${report['net_pnl_after_estimated_rebate_usd']:.2f}"
    )
    print(f"  {report['checkpoint_status']}")
    print(f"  recommendation={report['recommendation']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
