#!/usr/bin/env python3
"""DISPATCH_109 counterfactual replay over skipped windows."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

DEFAULT_DB_PATHS: tuple[Path, ...] = (
    Path("data/btc_5min_maker.db"),
    Path("data/eth_5min_maker.db"),
    Path("data/sol_5min_maker.db"),
    Path("data/xrp_5min_maker.db"),
    Path("data/doge_5min_maker.db"),
    Path("data/bnb_5min_maker.db"),
)
DEFAULT_OUTPUT_PATH = Path("data/counterfactual_report.json")
NEUTRAL_EPSILON = 1e-9


@dataclass
class SkipAggregate:
    count: int = 0
    wins: int = 0
    pnl_total: float = 0.0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().upper()
    if side in {"UP", "DOWN"}:
        return side
    return None


def _infer_direction(direction: Any, delta: Any) -> str | None:
    normalized = _normalize_side(direction)
    if normalized:
        return normalized
    parsed_delta = _safe_float(delta)
    if parsed_delta is None:
        return None
    if parsed_delta > 0:
        return "UP"
    if parsed_delta < 0:
        return "DOWN"
    return None


def _valid_best_ask(value: Any) -> float | None:
    best_ask = _safe_float(value)
    if best_ask is None:
        return None
    if not (0.0 < best_ask < 1.0):
        return None
    return best_ask


def _verdict(pnl_per_trade: float) -> str:
    # Positive means the guardrail skipped profitable windows.
    if pnl_per_trade > NEUTRAL_EPSILON:
        return "RELAX"
    # Negative means the guardrail avoided losses.
    if pnl_per_trade < -NEUTRAL_EPSILON:
        return "TIGHTEN"
    return "KEEP"


def _analyze_db(
    db_path: Path,
    aggregates: dict[str, SkipAggregate],
    *,
    invalid_rows_by_reason: dict[str, int],
) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT order_status, direction, best_ask, delta, resolved_side
            FROM window_trades
            WHERE resolved_side IS NOT NULL
              AND LOWER(order_status) LIKE 'skip_%'
            """
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        skip_reason = str(row["order_status"] or "").strip().lower()
        direction = _infer_direction(row["direction"], row["delta"])
        resolved_side = _normalize_side(row["resolved_side"])
        best_ask = _valid_best_ask(row["best_ask"])

        if not skip_reason or direction is None or resolved_side is None or best_ask is None:
            invalid_rows_by_reason[skip_reason or "unknown"] = (
                invalid_rows_by_reason.get(skip_reason or "unknown", 0) + 1
            )
            continue

        pnl = (1.0 - best_ask) if direction == resolved_side else -best_ask
        agg = aggregates.setdefault(skip_reason, SkipAggregate())
        agg.count += 1
        agg.wins += int(direction == resolved_side)
        agg.pnl_total += pnl
    return len(rows)


def build_counterfactual_report(db_paths: Sequence[Path]) -> dict[str, Any]:
    aggregates: dict[str, SkipAggregate] = {}
    invalid_rows_by_reason: dict[str, int] = {}
    dbs_found: list[str] = []
    dbs_missing: list[str] = []
    dbs_failed: dict[str, str] = {}
    raw_skip_rows_scanned = 0

    for db_path in db_paths:
        if not db_path.exists():
            dbs_missing.append(str(db_path))
            continue
        dbs_found.append(str(db_path))
        try:
            raw_skip_rows_scanned += _analyze_db(
                db_path,
                aggregates,
                invalid_rows_by_reason=invalid_rows_by_reason,
            )
        except sqlite3.Error as exc:
            dbs_failed[str(db_path)] = exc.__class__.__name__

    table: list[dict[str, Any]] = []
    for skip_reason in sorted(aggregates):
        agg = aggregates[skip_reason]
        wr = (agg.wins / agg.count) if agg.count else 0.0
        pnl_per_trade = (agg.pnl_total / agg.count) if agg.count else 0.0
        table.append(
            {
                "skip_reason": skip_reason,
                "count": agg.count,
                "counterfactual_WR": round(wr, 6),
                "counterfactual_PnL_per_trade": round(pnl_per_trade, 6),
                "verdict": _verdict(pnl_per_trade),
            }
        )

    table.sort(
        key=lambda row: (
            float(row["counterfactual_PnL_per_trade"]),
            int(row["count"]),
            str(row["skip_reason"]),
        ),
        reverse=True,
    )

    analyzed_windows = sum(item["count"] for item in table)
    overall_wins = sum(aggregates[key].wins for key in aggregates)
    overall_pnl = sum(aggregates[key].pnl_total for key in aggregates)
    overall_wr = (overall_wins / analyzed_windows) if analyzed_windows else 0.0
    overall_ppt = (overall_pnl / analyzed_windows) if analyzed_windows else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_paths_requested": [str(path) for path in db_paths],
        "db_paths_found": dbs_found,
        "db_paths_missing": dbs_missing,
        "db_failures": dbs_failed,
        "raw_skip_rows_scanned": raw_skip_rows_scanned,
        "invalid_rows_ignored": sum(invalid_rows_by_reason.values()),
        "invalid_rows_by_reason": invalid_rows_by_reason,
        "overall": {
            "count": analyzed_windows,
            "counterfactual_WR": round(overall_wr, 6),
            "counterfactual_PnL_per_trade": round(overall_ppt, 6),
        },
        "table": table,
    }


def _print_summary(report: dict[str, Any]) -> None:
    print("skip_reason | count | counterfactual_WR | counterfactual_PnL_per_trade | verdict")
    for row in report["table"]:
        print(
            f"{row['skip_reason']} | {row['count']} | "
            f"{row['counterfactual_WR']:.4f} | {row['counterfactual_PnL_per_trade']:.4f} | "
            f"{row['verdict']}"
        )
    if not report["table"]:
        print("no_rows | 0 | 0.0000 | 0.0000 | KEEP")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="append",
        default=[],
        help=(
            "Override DB paths to analyze (repeatable). "
            "Default: six maker DBs in data/."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSON path (default: data/counterfactual_report.json).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = [Path(token) for token in args.db] if args.db else list(DEFAULT_DB_PATHS)
    report = build_counterfactual_report(db_paths=db_paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_summary(report)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
