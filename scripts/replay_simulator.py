#!/usr/bin/env python3
"""Lightweight BTC5 replay filter on recorded fills."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FILLED_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
    "paper_filled",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _load_config(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("--config-json must decode to an object")
    return payload


def _direction_allowed(direction: str, mode: str) -> bool:
    normalized = mode.strip().lower()
    if normalized in {"two_sided", "both", "all"}:
        return direction in {"UP", "DOWN"}
    if normalized in {"up_only", "up"}:
        return direction == "UP"
    if normalized in {"down_only", "down"}:
        return direction == "DOWN"
    raise SystemExit(f"Unsupported directional_mode={mode!r}")


def _row_passes_price(row: sqlite3.Row, cfg: dict[str, Any]) -> bool:
    order_price = _safe_float(row["order_price"], -1.0)
    if order_price <= 0:
        return False
    min_buy = _safe_float(cfg.get("min_buy_price"), 0.0)
    if order_price < min_buy:
        return False
    direction = str(row["direction"] or "").strip().upper()
    if direction == "UP":
        cap = cfg.get("up_max_buy_price")
    elif direction == "DOWN":
        cap = cfg.get("down_max_buy_price")
    else:
        return False
    if cap is not None and order_price > _safe_float(cap, 1.0):
        return False
    return True


def run_replay(*, db_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    if not db_path.exists():
        raise SystemExit(f"Replay DB not found: {db_path}")

    mode = str(cfg.get("directional_mode") or "two_sided")
    matched: list[sqlite3.Row] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT window_start_ts, direction, order_price, order_status, won, pnl_usd
            FROM window_trades
            WHERE filled = 1
              AND order_status IS NOT NULL
            """
        ).fetchall()
    for row in rows:
        if str(row["order_status"] or "").strip().lower() not in FILLED_STATUSES:
            continue
        direction = str(row["direction"] or "").strip().upper()
        if not _direction_allowed(direction, mode):
            continue
        if not _row_passes_price(row, cfg):
            continue
        matched.append(row)

    settled = [r for r in matched if r["won"] is not None]
    wins = sum(1 for r in settled if _safe_int(r["won"], 0) == 1)
    losses = sum(1 for r in settled if _safe_int(r["won"], 0) == 0)
    pnl = round(sum(_safe_float(r["pnl_usd"], 0.0) for r in settled), 4)
    band_085_089 = [
        r for r in settled if 0.85 <= _safe_float(r["order_price"], 0.0) <= 0.89
    ]
    band_wins = sum(1 for r in band_085_089 if _safe_int(r["won"], 0) == 1)
    band_losses = sum(1 for r in band_085_089 if _safe_int(r["won"], 0) == 0)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "name": str(cfg.get("name") or "replay"),
        "db_path": str(db_path),
        "config": {
            "min_buy_price": _safe_float(cfg.get("min_buy_price"), 0.0),
            "up_max_buy_price": cfg.get("up_max_buy_price"),
            "down_max_buy_price": cfg.get("down_max_buy_price"),
            "directional_mode": mode,
        },
        "metrics": {
            "matched_fills": len(matched),
            "settled_fills": len(settled),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(settled)) if settled else None,
            "pnl_usd": pnl,
            "avg_pnl_usd": (pnl / len(settled)) if settled else None,
        },
        "band_0_85_to_0_89": {
            "fills": len(band_085_089),
            "wins": band_wins,
            "losses": band_losses,
            "win_rate": (band_wins / len(band_085_089)) if band_085_089 else None,
            "pnl_usd": round(sum(_safe_float(r["pnl_usd"], 0.0) for r in band_085_089), 4),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-json", required=True, help="JSON object with replay parameters.")
    parser.add_argument("--db-path", type=Path, default=Path("data/btc_5min_maker.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/replay_simulator_latest.json"),
        help="Path to write replay summary JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = _load_config(args.config_json)
    summary = run_replay(db_path=args.db_path, cfg=cfg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote replay summary: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
