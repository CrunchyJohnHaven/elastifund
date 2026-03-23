#!/usr/bin/env python3
"""Capital Lab: multi-lane capital aggregator and proving-ground runner.

Reads:
- data/btc_5min_maker.db           (BTC5 live fill metrics)
- data/kalshi_weather_decisions.jsonl  (weather lane real decisions)

Produces:
- reports/capital_lab/latest.json

This is the bridge from "self-improvement reports" to "self-improvement that
governs dollars." The proving ground accumulates real evidence from each lane
and updates doctrine candidates and promotion gates based on that evidence.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.report_envelope import write_report
from scripts.btc5_daily_pnl import compute_btc5_daily_pnl, load_live_fills

DEFAULT_WEATHER_DECISIONS_PATH = REPO_ROOT / "data" / "kalshi_weather_decisions.jsonl"
DEFAULT_BTC5_DB_PATH = REPO_ROOT / "data" / "btc_5min_maker.db"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "capital_lab" / "latest.json"

# Promotion gate thresholds
WEATHER_MIN_SHADOW_DECISIONS = 50
WEATHER_MIN_SHADOW_DAYS = 7
BTC5_MIN_FILLS = 20
BTC5_MIN_WIN_RATE = 0.55
BTC5_MIN_PROFIT_FACTOR = 1.10

# Daily PnL expansion gate thresholds
BTC5_DAILY_PNL_EXPANSION_BLOCK_USD = -5.0   # block expansion if ET-day PnL below this
BTC5_ROLLING_PNL_EXPANSION_BLOCK_USD = -10.0  # block expansion if rolling-24h PnL below this


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _analyze_weather_decisions(path: Path) -> dict[str, Any]:
    """Read kalshi_weather_decisions.jsonl and compute lane metrics."""
    base: dict[str, Any] = {
        "path": str(path),
        "decision_count": 0,
        "executed_count": 0,
        "rejected_count": 0,
        "shadow_count": 0,
        "total_notional_usd": 0.0,
        "cities_seen": [],
        "date_range": None,
        "unique_days": 0,
        "doctrine_candidate": False,
        "promotion_gate": {
            "pass": False,
            "criteria": {
                "min_decisions": WEATHER_MIN_SHADOW_DECISIONS,
                "min_days": WEATHER_MIN_SHADOW_DAYS,
            },
        },
    }
    if not path.exists():
        return {"status": "missing", **base}

    decisions: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        decisions.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        return {"status": f"read_error:{exc}", **base}

    executed = [
        d for d in decisions
        if d.get("execution_result") not in ("rejected", None)
        and float(d.get("notional_usd") or 0.0) > 0
    ]
    rejected = [d for d in decisions if d.get("execution_result") == "rejected"]
    shadow = [d for d in decisions if d.get("execution_mode") == "shadow"]
    total_notional = sum(float(d.get("notional_usd") or 0.0) for d in executed)
    cities = sorted({str(d.get("city") or "") for d in decisions if d.get("city")})

    timestamps: list[datetime] = []
    for d in decisions:
        ts = d.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
            except Exception:
                pass

    date_range = None
    unique_days = 0
    if timestamps:
        timestamps.sort()
        date_range = {"earliest": _iso_z(timestamps[0]), "latest": _iso_z(timestamps[-1])}
        unique_days = len({t.date() for t in timestamps})

    doctrine_candidate = (
        len(decisions) >= WEATHER_MIN_SHADOW_DECISIONS
        and unique_days >= WEATHER_MIN_SHADOW_DAYS
    )
    promotion_gate = {
        "pass": doctrine_candidate,
        "criteria": {
            "min_decisions": WEATHER_MIN_SHADOW_DECISIONS,
            "min_days": WEATHER_MIN_SHADOW_DAYS,
            "current_decisions": len(decisions),
            "current_days": unique_days,
        },
    }

    return {
        "status": "ok",
        "path": str(path),
        "decision_count": len(decisions),
        "executed_count": len(executed),
        "rejected_count": len(rejected),
        "shadow_count": len(shadow),
        "total_notional_usd": round(total_notional, 4),
        "cities_seen": cities,
        "date_range": date_range,
        "unique_days": unique_days,
        "doctrine_candidate": doctrine_candidate,
        "promotion_gate": promotion_gate,
    }


def _analyze_btc5_fills(db_path: Path) -> dict[str, Any]:
    """Read BTC5 fill metrics from window_trades table."""
    base: dict[str, Any] = {
        "path": str(db_path),
        "fills": 0,
        "wins": 0,
        "win_rate": None,
        "profit_factor": None,
        "gross_profit_usd": 0.0,
        "gross_loss_usd": 0.0,
        "cumulative_pnl_usd": 0.0,
        "doctrine_candidate": False,
        "promotion_gate": {
            "pass": False,
            "criteria": {
                "min_fills": BTC5_MIN_FILLS,
                "min_win_rate": BTC5_MIN_WIN_RATE,
                "min_profit_factor": BTC5_MIN_PROFIT_FACTOR,
            },
        },
    }
    if not db_path.exists():
        return {"status": "missing", **base}

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT CAST(COALESCE(pnl_usd, 0) AS REAL) AS pnl_usd, won
                FROM window_trades
                WHERE LOWER(COALESCE(order_status, '')) LIKE '%filled%'
                """
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"status": f"db_error:{exc}", **base}

    fills = len(rows)
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    pnl_total = 0.0

    for row in rows:
        pnl = float(_safe_float(row["pnl_usd"]) or 0.0)
        won_val = row["won"]
        if isinstance(won_val, bool):
            won = won_val
        elif isinstance(won_val, (int, float)):
            won = float(won_val) > 0
        else:
            won = pnl > 0

        if won:
            wins += 1
            gross_profit += abs(pnl)
        else:
            gross_loss += abs(pnl)
        pnl_total += pnl

    win_rate = (wins / fills) if fills > 0 else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else None

    doctrine_candidate = fills >= BTC5_MIN_FILLS and (win_rate or 0.0) >= BTC5_MIN_WIN_RATE
    promotion_gate_pass = doctrine_candidate and (profit_factor or 0.0) >= BTC5_MIN_PROFIT_FACTOR

    return {
        "status": "ok",
        "path": str(db_path),
        "fills": fills,
        "wins": wins,
        "win_rate": round(win_rate, 6) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "cumulative_pnl_usd": round(pnl_total, 4),
        "doctrine_candidate": doctrine_candidate,
        "promotion_gate": {
            "pass": promotion_gate_pass,
            "criteria": {
                "min_fills": BTC5_MIN_FILLS,
                "min_win_rate": BTC5_MIN_WIN_RATE,
                "min_profit_factor": BTC5_MIN_PROFIT_FACTOR,
                "current_fills": fills,
                "current_win_rate": round(win_rate, 4) if win_rate is not None else None,
                "current_profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            },
        },
    }


def _check_btc5_daily_pnl_gate(
    db_path: Path,
    now: datetime,
) -> dict[str, Any]:
    """Check whether BTC5 daily PnL allows expansion.

    Returns a gate dict with pass/fail and the underlying metrics.
    Blocks expansion when:
      - ET-day realized PnL is materially negative, OR
      - Rolling-24h realized PnL is materially negative.
    """
    fills = load_live_fills(db_path) if db_path.exists() else []
    packet = compute_btc5_daily_pnl(
        fills=fills,
        now_utc=now,
    )
    et_day_pnl = packet.et_day.gross_realized_pnl_usd
    rolling_pnl = packet.rolling_24h.gross_realized_pnl_usd

    et_day_ok = et_day_pnl >= BTC5_DAILY_PNL_EXPANSION_BLOCK_USD
    rolling_ok = rolling_pnl >= BTC5_ROLLING_PNL_EXPANSION_BLOCK_USD
    gate_pass = et_day_ok and rolling_ok

    blockers: list[str] = []
    if not et_day_ok:
        blockers.append(
            f"et_day_pnl={et_day_pnl:.2f} < threshold={BTC5_DAILY_PNL_EXPANSION_BLOCK_USD}"
        )
    if not rolling_ok:
        blockers.append(
            f"rolling_24h_pnl={rolling_pnl:.2f} < threshold={BTC5_ROLLING_PNL_EXPANSION_BLOCK_USD}"
        )

    return {
        "pass": gate_pass,
        "et_day_pnl_usd": round(et_day_pnl, 4),
        "rolling_24h_pnl_usd": round(rolling_pnl, 4),
        "et_day_fills": packet.et_day.fill_count,
        "rolling_24h_fills": packet.rolling_24h.fill_count,
        "thresholds": {
            "et_day_block_usd": BTC5_DAILY_PNL_EXPANSION_BLOCK_USD,
            "rolling_24h_block_usd": BTC5_ROLLING_PNL_EXPANSION_BLOCK_USD,
        },
        "blockers": blockers,
        "daily_pnl_packet": packet.to_dict(),
    }


def _build_proving_ground(
    lane_metrics: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Synthesize multi-lane proving ground state."""
    lanes_active: list[str] = []
    lanes_shadow: list[str] = []
    lanes_blocked: list[str] = []
    doctrine_candidates: list[str] = []
    promotion_gates_passing: list[str] = []

    for lane, metrics in lane_metrics.items():
        status = metrics.get("status", "ok")
        if "error" in status or status == "missing":
            lanes_blocked.append(lane)
            continue

        if metrics.get("doctrine_candidate"):
            doctrine_candidates.append(lane)

        gate = metrics.get("promotion_gate") or {}
        if gate.get("pass"):
            promotion_gates_passing.append(lane)

        if lane == "weather":
            if metrics.get("executed_count", 0) > 0:
                lanes_active.append(lane)
            else:
                lanes_shadow.append(lane)
        elif lane == "btc5":
            if metrics.get("fills", 0) > 0:
                lanes_active.append(lane)
            else:
                lanes_blocked.append(lane)

    return {
        "generated_at": _iso_z(now),
        "lanes_active": sorted(set(lanes_active)),
        "lanes_shadow": sorted(set(lanes_shadow)),
        "lanes_blocked": sorted(set(lanes_blocked)),
        "doctrine_candidates": sorted(doctrine_candidates),
        "promotion_gates_passing": sorted(promotion_gates_passing),
        "self_improving": len(doctrine_candidates) > 0,
    }


def run_capital_lab(
    *,
    weather_decisions_path: Path = DEFAULT_WEATHER_DECISIONS_PATH,
    btc5_db_path: Path = DEFAULT_BTC5_DB_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    weather_metrics = _analyze_weather_decisions(weather_decisions_path)
    btc5_metrics = _analyze_btc5_fills(btc5_db_path)

    # Daily PnL expansion gate
    btc5_daily_pnl_gate = _check_btc5_daily_pnl_gate(btc5_db_path, now)
    btc5_metrics["daily_pnl_gate"] = btc5_daily_pnl_gate

    # If daily PnL gate fails, block promotion even if other gates pass
    if not btc5_daily_pnl_gate["pass"]:
        btc5_metrics["promotion_gate"]["pass"] = False
        btc5_metrics["promotion_gate"]["daily_pnl_block"] = btc5_daily_pnl_gate["blockers"]

    lane_metrics = {"weather": weather_metrics, "btc5": btc5_metrics}
    proving_ground = _build_proving_ground(lane_metrics, now)
    lane_statuses = [str(metrics.get("status") or "") for metrics in lane_metrics.values()]
    if all(status == "missing" for status in lane_statuses):
        report_status = "blocked"
    elif any(status != "ok" for status in lane_statuses):
        report_status = "stale"
    else:
        report_status = "fresh"
    blockers: list[str] = []
    for lane, metrics in lane_metrics.items():
        if metrics.get("status") != "ok":
            blockers.append(f"{lane}:{metrics.get('status')}")

    result: dict[str, Any] = {
        "artifact": "capital_lab.v1",
        "generated_at": _iso_z(now),
        "proving_ground": proving_ground,
        "lane_metrics": lane_metrics,
        "btc5_daily_pnl_gate": btc5_daily_pnl_gate,
        "status": report_status,
        "blockers": blockers,
    }

    write_report(
        output_path,
        artifact="capital_lab.v1",
        payload=result,
        status=report_status,
        source_of_truth=(
            "reports/parallel/instance04_weather_divergence_shadow.json; "
            "data/btc_5min_maker.db"
        ),
        freshness_sla_seconds=1800,
        blockers=blockers,
        summary=(
            f"proving_ground active={proving_ground['lanes_active']} "
            f"shadow={proving_ground['lanes_shadow']} blocked={proving_ground['lanes_blocked']}"
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-decisions", type=Path, default=DEFAULT_WEATHER_DECISIONS_PATH)
    parser.add_argument("--btc5-db", type=Path, default=DEFAULT_BTC5_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    result = run_capital_lab(
        weather_decisions_path=args.weather_decisions,
        btc5_db_path=args.btc5_db,
        output_path=args.output,
    )

    pg = result["proving_ground"]
    print(f"Wrote {args.output}")
    print(
        f"proving_ground: "
        f"active={pg['lanes_active']} "
        f"shadow={pg['lanes_shadow']} "
        f"blocked={pg['lanes_blocked']}"
    )
    print(
        f"doctrine_candidates={pg['doctrine_candidates']} "
        f"promotion_gates_passing={pg['promotion_gates_passing']} "
        f"self_improving={pg['self_improving']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
