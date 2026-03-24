#!/usr/bin/env python3
"""Build a canonical local feedback artifact across Alpaca, Kalshi, and Polymarket.

The local twin already knows whether a venue is allowed to trade live. This
script answers the next question for the self-improvement kernel:

What did each venue actually do locally, how fresh is that feedback, and what
should mutate next?
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi.weather_arb import reconcile_decisions_with_settlements
from scripts.report_envelope import write_report

REPORT_PATH = REPO_ROOT / "reports" / "local_feedback_loop.json"
LOCAL_LIVE_STATUS_PATH = REPO_ROOT / "reports" / "local_live_status.json"

ALPACA_LANE_PATH = REPO_ROOT / "reports" / "parallel" / "alpaca_crypto_lane.json"
ALPACA_EXECUTION_PATH = REPO_ROOT / "reports" / "alpaca_first_trade" / "latest.json"
ALPACA_HISTORY_PATH = REPO_ROOT / "reports" / "alpaca_first_trade" / "history.jsonl"
ALPACA_STATE_PATH = REPO_ROOT / "state" / "alpaca_first_trade_state.json"

KALSHI_SIGNALS_PATH = REPO_ROOT / "data" / "kalshi_weather_signals.jsonl"
KALSHI_ORDERS_PATH = REPO_ROOT / "data" / "kalshi_weather_orders.jsonl"
KALSHI_DECISIONS_PATH = REPO_ROOT / "data" / "kalshi_weather_decisions.jsonl"
KALSHI_SETTLEMENTS_PATH = REPO_ROOT / "data" / "kalshi_weather_settlements.jsonl"

POLYMARKET_DB_PATH = REPO_ROOT / "data" / "local_btc_5min_maker.db"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime | None = None) -> str:
    stamp = dt or _utc_now()
    return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _parse_timestamp(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(raw: Any) -> float | None:
    parsed = _parse_timestamp(raw)
    if parsed is None:
        return None
    return max(0.0, (_utc_now() - parsed).total_seconds())


def _recent_rows(rows: list[dict[str, Any]], *, horizon: timedelta) -> list[dict[str, Any]]:
    cutoff = _utc_now() - horizon
    recent: list[dict[str, Any]] = []
    for row in rows:
        ts = (
            _parse_timestamp(row.get("generated_at"))
            or _parse_timestamp(row.get("timestamp"))
            or _parse_timestamp(row.get("captured_at"))
            or _parse_timestamp(row.get("checked_at"))
        )
        if ts is not None and ts >= cutoff:
            recent.append(row)
    return recent


def _flatten_variant_returns(payload: dict[str, Any]) -> list[float]:
    variant_map = payload.get("variant_live_returns") or {}
    if not isinstance(variant_map, dict):
        return []
    values: list[float] = []
    for series in variant_map.values():
        if not isinstance(series, list):
            continue
        for item in series:
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                continue
    return values


def _make_hint(
    *,
    venue: str,
    lane: str,
    code: str,
    severity: str,
    summary: str,
    rationale: str,
) -> dict[str, Any]:
    return {
        "hint_id": f"{venue}:{code}",
        "venue": venue,
        "lane": lane,
        "code": code,
        "severity": severity,
        "summary": summary,
        "rationale": rationale,
    }


def _alpaca_feedback(root: Path, live_status: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    venue_status = dict((live_status.get("venues") or {}).get("alpaca") or {})
    lane = _read_json(root / ALPACA_LANE_PATH.relative_to(REPO_ROOT))
    latest = _read_json(root / ALPACA_EXECUTION_PATH.relative_to(REPO_ROOT))
    state = _read_json(root / ALPACA_STATE_PATH.relative_to(REPO_ROOT))
    history_rows = _iter_jsonl(root / ALPACA_HISTORY_PATH.relative_to(REPO_ROOT))
    recent_history = _recent_rows(history_rows, horizon=timedelta(hours=24))
    action_counts = Counter(str(row.get("action") or "unknown") for row in recent_history)
    realized_returns = _flatten_variant_returns(state)
    candidate_rows = lane.get("candidate_rows") or []
    latest_blockers = list(latest.get("blockers") or [])
    hints: list[dict[str, Any]] = []
    blockers = list(dict.fromkeys([*list(venue_status.get("blockers") or []), *latest_blockers]))

    candidate_count = _safe_int(lane.get("candidate_count"), len(candidate_rows) if isinstance(candidate_rows, list) else 0)
    if candidate_count <= 0:
        hints.append(
            _make_hint(
                venue="alpaca",
                lane="alpaca",
                code="candidate_density_zero",
                severity="medium",
                summary="Alpaca produced no local candidates in the latest cycle.",
                rationale="Momentum thresholds or market-data freshness may be too restrictive for the local lane.",
            )
        )
    avg_realized_log_return = (
        round(sum(realized_returns) / len(realized_returns), 6) if realized_returns else None
    )
    if realized_returns and avg_realized_log_return is not None and avg_realized_log_return <= 0:
        hints.append(
            _make_hint(
                venue="alpaca",
                lane="alpaca",
                code="live_returns_non_positive",
                severity="high",
                summary="Alpaca realized-return memory is non-positive.",
                rationale="The live return map is feeding back weak or negative outcomes and needs parameter repair before scaling.",
            )
        )
    if venue_status.get("requested_live") and blockers:
        hints.append(
            _make_hint(
                venue="alpaca",
                lane="alpaca",
                code="live_gate_blocked",
                severity="high",
                summary="Alpaca local live is requested but blocked by control-plane or credential gates.",
                rationale=", ".join(blockers[:4]) or "alpaca_local_live_blocked",
            )
        )

    payload = {
        "venue": "alpaca",
        "lane": "alpaca",
        "effective_mode": venue_status.get("effective_mode") or "paper",
        "requested_live": bool(venue_status.get("requested_live")),
        "feedback_ready": bool(venue_status.get("feedback_loop_ready")) and bool(lane or latest or history_rows),
        "blockers": blockers,
        "latest_lane_generated_at": lane.get("generated_at"),
        "latest_execution_generated_at": latest.get("generated_at"),
        "latest_execution_status": latest.get("status"),
        "latest_action": latest.get("action"),
        "candidate_count": candidate_count,
        "recent_activity_count_24h": len(recent_history),
        "entry_count_24h": int(action_counts.get("entry", 0)),
        "exit_count_24h": int(action_counts.get("exit", 0)),
        "blocked_count_24h": int(action_counts.get("blocked", 0)),
        "open_trade": bool(state.get("open_trade")),
        "variant_live_return_count": len(realized_returns),
        "avg_realized_log_return": avg_realized_log_return,
        "artifact_age_seconds": {
            "lane": _age_seconds(lane.get("generated_at")),
            "execution": _age_seconds(latest.get("generated_at")),
        },
        "hints": hints,
    }
    return payload, hints


def _kalshi_feedback(root: Path, live_status: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    venue_status = dict((live_status.get("venues") or {}).get("kalshi") or {})
    signal_rows = _iter_jsonl(root / KALSHI_SIGNALS_PATH.relative_to(REPO_ROOT))
    order_rows = _iter_jsonl(root / KALSHI_ORDERS_PATH.relative_to(REPO_ROOT))
    decision_rows = _iter_jsonl(root / KALSHI_DECISIONS_PATH.relative_to(REPO_ROOT))
    settlement_rows = _iter_jsonl(root / KALSHI_SETTLEMENTS_PATH.relative_to(REPO_ROOT))

    recent_signals = _recent_rows(signal_rows, horizon=timedelta(hours=24))
    recent_orders = _recent_rows(order_rows, horizon=timedelta(hours=24))
    recent_decisions = _recent_rows(decision_rows, horizon=timedelta(hours=24))

    reconciliation = reconcile_decisions_with_settlements(
        decisions_log=root / KALSHI_DECISIONS_PATH.relative_to(REPO_ROOT),
        settlement_log=root / KALSHI_SETTLEMENTS_PATH.relative_to(REPO_ROOT),
        orders_log=root / KALSHI_ORDERS_PATH.relative_to(REPO_ROOT),
    )

    hints: list[dict[str, Any]] = []
    blockers = list(venue_status.get("blockers") or [])
    total_executed = _safe_int(reconciliation.get("total_executed_decisions"))
    match_rate = _safe_float(reconciliation.get("match_rate"))
    if total_executed > 0 and match_rate < 1.0:
        hints.append(
            _make_hint(
                venue="kalshi",
                lane="weather",
                code="settlement_reconciliation_incomplete",
                severity="high",
                summary="Kalshi decisions and settlements are not fully reconciled.",
                rationale=reconciliation.get("reconciliation_summary") or "kalshi_settlement_match_rate_below_one",
            )
        )
    if not recent_decisions and not blockers:
        hints.append(
            _make_hint(
                venue="kalshi",
                lane="weather",
                code="recent_decision_density_zero",
                severity="medium",
                summary="Kalshi weather lane produced no executed local decisions in the last 24 hours.",
                rationale="Either opportunity density is low or the current edge thresholds are suppressing the lane.",
            )
        )
    if venue_status.get("requested_live") and blockers:
        hints.append(
            _make_hint(
                venue="kalshi",
                lane="weather",
                code="live_gate_blocked",
                severity="high",
                summary="Kalshi local live is requested but blocked by auth or control-plane requirements.",
                rationale=", ".join(blockers[:4]) or "kalshi_local_live_blocked",
            )
        )

    latest_decision = decision_rows[-1] if decision_rows else {}
    payload = {
        "venue": "kalshi",
        "lane": "weather",
        "effective_mode": venue_status.get("effective_mode") or "paper",
        "requested_live": bool(venue_status.get("requested_live")),
        "feedback_ready": bool(venue_status.get("feedback_loop_ready")) and (
            bool(signal_rows) or bool(order_rows) or bool(decision_rows) or bool(settlement_rows)
        ),
        "blockers": blockers,
        "recent_activity_count_24h": len(recent_decisions),
        "recent_signal_count_24h": len(recent_signals),
        "recent_order_count_24h": len(recent_orders),
        "decision_count_total": len(decision_rows),
        "settlement_count_total": len(settlement_rows),
        "latest_decision_at": latest_decision.get("timestamp"),
        "latest_decision_reason_code": latest_decision.get("reason_code"),
        "latest_decision_mode": latest_decision.get("execution_mode") or latest_decision.get("execution_result"),
        "settlement_match_rate": round(match_rate, 4),
        "matched_settlements": _safe_int(reconciliation.get("matched_settlements")),
        "unmatched_settlements": _safe_int(reconciliation.get("unmatched_settlements")),
        "total_executed_decisions": total_executed,
        "reconciliation_summary": reconciliation.get("reconciliation_summary"),
        "hints": hints,
    }
    return payload, hints


def _load_polymarket_metrics(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "db_present": False,
            "feedback_ready": False,
            "blockers": ["local_btc5_db_missing"],
        }

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_rows,
                    COALESCE(SUM(CASE WHEN filled = 1 THEN 1 ELSE 0 END), 0) AS filled_rows,
                    COALESCE(SUM(CASE WHEN order_status = 'live_filled' THEN 1 ELSE 0 END), 0) AS live_filled_rows,
                    COALESCE(SUM(CASE WHEN won IS NOT NULL THEN 1 ELSE 0 END), 0) AS resolved_rows,
                    COALESCE(SUM(CASE WHEN decision_ts >= ? AND pnl_usd IS NOT NULL THEN pnl_usd ELSE 0 END), 0.0) AS today_realized_pnl_usd,
                    MAX(decision_ts) AS latest_decision_ts
                FROM window_trades
                """,
                (day_start_ts,),
            ).fetchone()
            trailing_rows = conn.execute(
                """
                SELECT COALESCE(pnl_usd, 0.0) AS pnl_usd
                FROM window_trades
                WHERE order_status = 'live_filled'
                ORDER BY id DESC
                LIMIT 12
                """
            ).fetchall()
            open_live_row = conn.execute(
                """
                SELECT COUNT(*) AS open_live_positions
                FROM window_trades
                WHERE resolved_side IS NULL
                  AND filled = 1
                  AND shares > 0
                  AND token_id IS NOT NULL
                  AND order_price IS NOT NULL
                  AND direction IN ('UP', 'DOWN')
                """
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        return {
            "db_present": True,
            "feedback_ready": False,
            "blockers": [f"polymarket_db_error:{type(exc).__name__}"],
        }

    latest_decision_ts = totals["latest_decision_ts"] if totals is not None else None
    latest_age_minutes = None
    if latest_decision_ts is not None:
        latest_age_minutes = round(max(0.0, (int(_utc_now().timestamp()) - int(latest_decision_ts)) / 60.0), 2)
    trailing_12_pnl = round(sum(_safe_float(row["pnl_usd"]) for row in trailing_rows), 4)
    return {
        "db_present": True,
        "feedback_ready": True,
        "blockers": [],
        "total_rows": _safe_int(totals["total_rows"] if totals is not None else 0),
        "filled_rows": _safe_int(totals["filled_rows"] if totals is not None else 0),
        "live_filled_rows": _safe_int(totals["live_filled_rows"] if totals is not None else 0),
        "resolved_rows": _safe_int(totals["resolved_rows"] if totals is not None else 0),
        "today_realized_pnl_usd": round(_safe_float(totals["today_realized_pnl_usd"] if totals is not None else 0.0), 4),
        "latest_decision_age_minutes": latest_age_minutes,
        "open_live_positions": _safe_int(open_live_row["open_live_positions"] if open_live_row is not None else 0),
        "trailing_12_live_filled_pnl_usd": trailing_12_pnl,
        "trailing_12_live_filled_count": len(trailing_rows),
    }


def _polymarket_feedback(root: Path, live_status: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    venue_status = dict((live_status.get("venues") or {}).get("polymarket") or {})
    db_metrics = _load_polymarket_metrics(root / POLYMARKET_DB_PATH.relative_to(REPO_ROOT))
    blockers = list(dict.fromkeys([*list(venue_status.get("blockers") or []), *list(db_metrics.get("blockers") or [])]))
    hints: list[dict[str, Any]] = []

    live_filled_rows = _safe_int(db_metrics.get("live_filled_rows"))
    trailing_pnl = _safe_float(db_metrics.get("trailing_12_live_filled_pnl_usd"))
    if live_filled_rows <= 0:
        hints.append(
            _make_hint(
                venue="polymarket",
                lane="btc5",
                code="no_live_fills_captured",
                severity="medium",
                summary="Polymarket local BTC5 has not captured any live-filled rows yet.",
                rationale="The local maker loop is running, but there is still no dense live outcome stream to learn from.",
            )
        )
    elif _safe_int(db_metrics.get("trailing_12_live_filled_count")) >= 12 and trailing_pnl <= 0:
        hints.append(
            _make_hint(
                venue="polymarket",
                lane="btc5",
                code="trailing_live_window_non_positive",
                severity="high",
                summary="Polymarket trailing 12 local live-filled window is non-positive.",
                rationale="BTC5 should stay bounded until the local live-filled trailing window turns positive again.",
            )
        )
    if venue_status.get("requested_live") and blockers:
        hints.append(
            _make_hint(
                venue="polymarket",
                lane="btc5",
                code="live_gate_blocked",
                severity="high",
                summary="Polymarket local live is requested but the canonical launch/BTC5 gates remain blocked.",
                rationale=", ".join(blockers[:6]) or "polymarket_local_live_blocked",
            )
        )

    payload = {
        "venue": "polymarket",
        "lane": "btc5",
        "effective_mode": venue_status.get("effective_mode") or "paper",
        "requested_live": bool(venue_status.get("requested_live")),
        "feedback_ready": bool(venue_status.get("feedback_loop_ready")) and bool(db_metrics.get("feedback_ready")),
        "blockers": blockers,
        "db_path": str((root / POLYMARKET_DB_PATH.relative_to(REPO_ROOT)).relative_to(root)),
        "recent_activity_count_24h": _safe_int(db_metrics.get("filled_rows")),
        "total_rows": _safe_int(db_metrics.get("total_rows")),
        "live_filled_rows": live_filled_rows,
        "resolved_rows": _safe_int(db_metrics.get("resolved_rows")),
        "open_live_positions": _safe_int(db_metrics.get("open_live_positions")),
        "today_realized_pnl_usd": db_metrics.get("today_realized_pnl_usd"),
        "trailing_12_live_filled_count": _safe_int(db_metrics.get("trailing_12_live_filled_count")),
        "trailing_12_live_filled_pnl_usd": trailing_pnl,
        "latest_decision_age_minutes": db_metrics.get("latest_decision_age_minutes"),
        "hints": hints,
    }
    return payload, hints


def build_local_feedback_loop(*, root: Path = REPO_ROOT) -> dict[str, Any]:
    live_status = _read_json(root / LOCAL_LIVE_STATUS_PATH.relative_to(REPO_ROOT))

    alpaca, alpaca_hints = _alpaca_feedback(root, live_status)
    kalshi, kalshi_hints = _kalshi_feedback(root, live_status)
    polymarket, polymarket_hints = _polymarket_feedback(root, live_status)

    venues = {
        "alpaca": alpaca,
        "kalshi": kalshi,
        "polymarket": polymarket,
    }
    hint_rows = [*alpaca_hints, *kalshi_hints, *polymarket_hints]
    feedback_ready_count = sum(1 for payload in venues.values() if payload.get("feedback_ready"))
    live_enabled_count = sum(1 for payload in venues.values() if payload.get("effective_mode") == "live")

    return {
        "artifact": "local_feedback_loop.v1",
        "generated_at": _iso_z(),
        "requested_live_venues": list(live_status.get("requested_live_venues") or []),
        "overall": {
            "venue_count": len(venues),
            "feedback_ready_count": feedback_ready_count,
            "live_enabled_count": live_enabled_count,
            "mutation_hint_count": len(hint_rows),
        },
        "venues": venues,
        "mutation_hints": hint_rows,
        "summary": (
            f"local feedback compiled for {len(venues)} venues; "
            f"feedback_ready={feedback_ready_count}/{len(venues)} "
            f"live_enabled={live_enabled_count} hints={len(hint_rows)}"
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.repo_root.resolve()
    artifact = build_local_feedback_loop(root=root)

    if args.check_only:
        print(json.dumps(artifact, indent=2, sort_keys=True))
        return 0

    status = "fresh" if artifact.get("venues") else "blocked"
    blockers = [] if artifact["overall"]["feedback_ready_count"] > 0 else ["no_feedback_ready_venues"]
    report = write_report(
        args.output.resolve(),
        artifact="local_feedback_loop",
        payload=artifact,
        status=status,
        source_of_truth=(
            "reports/local_live_status.json; reports/alpaca_first_trade/latest.json; "
            "reports/alpaca_first_trade/history.jsonl; data/kalshi_weather_decisions.jsonl; "
            "data/kalshi_weather_settlements.jsonl; data/local_btc_5min_maker.db#window_trades"
        ),
        freshness_sla_seconds=900,
        blockers=blockers,
        summary=artifact["summary"],
    )
    print(
        f"[local-feedback] venues={report['overall']['venue_count']} "
        f"feedback_ready={report['overall']['feedback_ready_count']} "
        f"hints={report['overall']['mutation_hint_count']} "
        f"-> {args.output.resolve().relative_to(root)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
