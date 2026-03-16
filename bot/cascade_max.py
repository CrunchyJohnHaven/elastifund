#!/usr/bin/env python3
"""Cascade Max signal detector and shadow/live promotion gate."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

DELTA_THRESHOLD = 0.002
MIN_DETECTIONS_FOR_LIVE = 10
MIN_RESOLVED_SHADOW_FOR_PROMOTION = 10
SHADOW_WR_PROMOTION_THRESHOLD = 0.90
MIN_BEST_ASK_FOR_BOOST = 0.90

BTC_DB_PATH = Path("data/btc_5min_maker.db")
ETH_DB_PATH = Path("data/eth_5min_maker.db")
SOL_DB_PATH = Path("data/sol_5min_maker.db")
CASCADE_SIGNAL_PATH = Path("data/cascade_signal.json")
CASCADE_LOG_PATH = Path("data/cascade_log.json")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_latest_delta(db_path: Path) -> float | None:
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            for query in (
                "SELECT delta FROM window_trades WHERE delta IS NOT NULL ORDER BY window_start_ts DESC LIMIT 1",
                "SELECT delta FROM window_trades WHERE delta IS NOT NULL ORDER BY decision_ts DESC LIMIT 1",
            ):
                try:
                    row = conn.execute(query).fetchone()
                except sqlite3.Error:
                    continue
                if row is None:
                    continue
                parsed = _safe_float(row["delta"], None)
                if parsed is not None:
                    return float(parsed)
    except sqlite3.Error:
        return None
    return None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def _read_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"events": [], "stats": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"events": [], "stats": {}}
    events = payload.get("events")
    if not isinstance(events, list):
        events = []
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    return {"events": events, "stats": stats}


def _refresh_shadow_outcomes(*, events: list[dict[str, Any]], btc_db_path: Path) -> None:
    if not events or not btc_db_path.exists():
        return
    unresolved_windows = sorted(
        {
            int(_safe_float(event.get("window_start_ts"), 0.0) or 0)
            for event in events
            if event.get("mode") == "shadow"
            and event.get("won") not in (0, 1)
            and _safe_float(event.get("window_start_ts"), None) is not None
        }
    )
    if not unresolved_windows:
        return

    try:
        with sqlite3.connect(str(btc_db_path), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            for window_start_ts in unresolved_windows:
                if window_start_ts <= 0:
                    continue
                row = conn.execute(
                    """
                    SELECT won
                    FROM window_trades
                    WHERE window_start_ts = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (window_start_ts,),
                ).fetchone()
                if row is None:
                    continue
                won_value = _safe_float(row["won"], None)
                if won_value not in (0.0, 1.0):
                    continue
                won = int(won_value)
                for event in events:
                    if (
                        event.get("mode") == "shadow"
                        and int(_safe_float(event.get("window_start_ts"), 0.0) or 0) == window_start_ts
                        and event.get("won") not in (0, 1)
                    ):
                        event["won"] = won
                        event["resolved_at"] = int(time.time())
    except sqlite3.Error:
        return


def _summary_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    detection_count = len(events)
    shadow_events = [event for event in events if event.get("mode") == "shadow"]
    shadow_resolved = [event for event in shadow_events if event.get("won") in (0, 1)]
    shadow_wins = sum(int(event.get("won", 0)) for event in shadow_resolved)
    shadow_resolved_count = len(shadow_resolved)
    shadow_wr = (
        float(shadow_wins) / float(shadow_resolved_count)
        if shadow_resolved_count > 0
        else None
    )
    live_boost_enabled = (
        detection_count >= MIN_DETECTIONS_FOR_LIVE
        and shadow_resolved_count >= MIN_RESOLVED_SHADOW_FOR_PROMOTION
        and shadow_wr is not None
        and shadow_wr >= SHADOW_WR_PROMOTION_THRESHOLD
    )
    return {
        "detection_count": detection_count,
        "shadow_resolved_count": shadow_resolved_count,
        "shadow_wins": shadow_wins,
        "shadow_win_rate": round(shadow_wr, 6) if shadow_wr is not None else None,
        "live_boost_enabled": live_boost_enabled,
    }


def run_cascade_detection(
    *,
    window_start_ts: int | None = None,
    btc_db_path: Path = BTC_DB_PATH,
    eth_db_path: Path = ETH_DB_PATH,
    sol_db_path: Path = SOL_DB_PATH,
    signal_path: Path = CASCADE_SIGNAL_PATH,
) -> dict[str, Any]:
    deltas = {
        "btc": _read_latest_delta(btc_db_path),
        "eth": _read_latest_delta(eth_db_path),
        "sol": _read_latest_delta(sol_db_path),
    }
    values = list(deltas.values())
    all_present = all(value is not None for value in values)
    all_above_threshold = all(abs(float(value)) > DELTA_THRESHOLD for value in values if value is not None)
    all_positive = all(float(value) > 0 for value in values if value is not None)
    all_negative = all(float(value) < 0 for value in values if value is not None)
    active = bool(all_present and all_above_threshold and (all_positive or all_negative))

    if active:
        signal = {
            "active": True,
            "direction": "UP" if all_positive else "DOWN",
            "confidence": 1.0,
            "detected_at": int(window_start_ts or time.time()),
        }
    else:
        signal = {"active": False}
    _write_json(signal_path, signal)
    return {
        **signal,
        "deltas": deltas,
    }


def record_cascade_event(
    *,
    window_start_ts: int,
    cascade_signal: Mapping[str, Any],
    bot_direction: str | None,
    bot_delta: float | None,
    best_ask: float | None,
    btc_db_path: Path = BTC_DB_PATH,
    log_path: Path = CASCADE_LOG_PATH,
    min_best_ask: float = MIN_BEST_ASK_FOR_BOOST,
) -> dict[str, Any]:
    payload = _read_log(log_path)
    events: list[dict[str, Any]] = [dict(item) for item in payload.get("events", []) if isinstance(item, dict)]
    _refresh_shadow_outcomes(events=events, btc_db_path=btc_db_path)
    stats_before = _summary_stats(events)
    live_boost_enabled_now = bool(stats_before.get("live_boost_enabled"))

    signal_active = bool(cascade_signal.get("active"))
    signal_direction = str(cascade_signal.get("direction") or "").strip().upper()
    direction = str(bot_direction or "").strip().upper()
    direction_agrees = signal_active and signal_direction in {"UP", "DOWN"} and direction == signal_direction
    best_ask_value = _safe_float(best_ask, None)
    price_ok = best_ask_value is not None and best_ask_value >= float(min_best_ask)
    candidate = bool(direction_agrees and price_ok)
    mode: str | None = None
    if candidate:
        mode = "live" if live_boost_enabled_now else "shadow"
        events.append(
            {
                "window_start_ts": int(window_start_ts),
                "detected_at": int(time.time()),
                "cascade_direction": signal_direction,
                "bot_direction": direction,
                "bot_delta": _safe_float(bot_delta, None),
                "best_ask": best_ask_value,
                "mode": mode,
                "won": None,
            }
        )

    _refresh_shadow_outcomes(events=events, btc_db_path=btc_db_path)
    stats_after = _summary_stats(events)
    _write_json(
        log_path,
        {
            "events": events,
            "stats": stats_after,
            "updated_at": int(time.time()),
        },
    )
    return {
        "cascade_boost_candidate": candidate,
        "cascade_boost_live_enabled": live_boost_enabled_now,
        "cascade_boost_apply": bool(candidate and live_boost_enabled_now),
        "cascade_mode": mode,
        "detection_count": int(stats_after.get("detection_count", 0) or 0),
        "shadow_resolved_count": int(stats_after.get("shadow_resolved_count", 0) or 0),
        "shadow_win_rate": stats_after.get("shadow_win_rate"),
        "live_boost_enabled_next": bool(stats_after.get("live_boost_enabled")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cascade max signal detection.")
    parser.add_argument("--window-start-ts", type=int, default=None)
    parser.add_argument("--bot-direction", type=str, default=None)
    parser.add_argument("--bot-delta", type=float, default=None)
    parser.add_argument("--best-ask", type=float, default=None)
    args = parser.parse_args()

    detection = run_cascade_detection(window_start_ts=args.window_start_ts)
    payload: dict[str, Any] = {"detection": detection}
    if args.bot_direction is not None and args.best_ask is not None:
        payload["event"] = record_cascade_event(
            window_start_ts=int(args.window_start_ts or time.time()),
            cascade_signal=detection,
            bot_direction=args.bot_direction,
            bot_delta=args.bot_delta,
            best_ask=args.best_ask,
        )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
