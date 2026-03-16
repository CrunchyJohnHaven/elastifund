#!/usr/bin/env python3
"""Cross-asset lead/lag scanner for 5-minute maker bots.

Builds rolling 1-minute return series from per-asset SQLite maker databases,
detects leader/follower relationships, and emits directional confirmation
signals for each asset.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Any

DEFAULT_DB_PATHS: dict[str, Path] = {
    "BTCUSDT": Path("data/btc_5min_maker.db"),
    "ETHUSDT": Path("data/eth_5min_maker.db"),
    "SOLUSDT": Path("data/sol_5min_maker.db"),
    "BNBUSDT": Path("data/bnb_5min_maker.db"),
    "DOGEUSDT": Path("data/doge_5min_maker.db"),
    "XRPUSDT": Path("data/xrp_5min_maker.db"),
}
DEFAULT_OUTPUT_PATH = Path("data/cross_asset_signals.json")
SCHEMA_VERSION = "cross_asset_signals.v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_iso_ts(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp())
    except (TypeError, ValueError):
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _query_recent_prices(
    db_path: Path,
    *,
    since_ts: int,
) -> dict[int, float]:
    if not db_path.exists():
        return {}
    with sqlite3.connect(str(db_path), timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "window_trades"):
            return {}
        rows = conn.execute(
            """
            SELECT decision_ts, current_price
            FROM window_trades
            WHERE current_price IS NOT NULL
              AND decision_ts >= ?
            ORDER BY decision_ts ASC
            """,
            (int(since_ts),),
        ).fetchall()
    minute_prices: dict[int, float] = {}
    for row in rows:
        ts = int(_safe_float(row["decision_ts"], 0.0) or 0)
        px = _safe_float(row["current_price"], None)
        if ts <= 0 or px is None or px <= 0:
            continue
        minute_ts = ts - (ts % 60)
        minute_prices[minute_ts] = float(px)
    return minute_prices


def _forward_fill_prices(
    minute_prices: dict[int, float],
    *,
    start_ts: int,
    end_ts: int,
) -> list[float | None]:
    if end_ts <= start_ts:
        return []
    known = sorted(minute_prices.items())
    if not known:
        return []
    out: list[float | None] = []
    idx = 0
    latest_px: float | None = None
    for ts in range(start_ts, end_ts + 1, 60):
        while idx < len(known) and known[idx][0] <= ts:
            latest_px = float(known[idx][1])
            idx += 1
        out.append(latest_px)
    return out


def _returns_from_prices(prices: list[float | None]) -> list[float | None]:
    if len(prices) < 2:
        return []
    out: list[float | None] = []
    for prev, cur in zip(prices[:-1], prices[1:]):
        if prev is None or cur is None or prev <= 0:
            out.append(None)
            continue
        out.append((cur - prev) / prev)
    return out


def _paired_values(lhs: list[float | None], rhs: list[float | None]) -> tuple[list[float], list[float]]:
    x: list[float] = []
    y: list[float] = []
    for lv, rv in zip(lhs, rhs):
        if lv is None or rv is None:
            continue
        x.append(float(lv))
        y.append(float(rv))
    return x, y


def _pearson_corr(lhs: list[float], rhs: list[float]) -> float | None:
    if len(lhs) != len(rhs) or len(lhs) < 3:
        return None
    n = len(lhs)
    mx = sum(lhs) / n
    my = sum(rhs) / n
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for xv, yv in zip(lhs, rhs):
        dx = xv - mx
        dy = yv - my
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _latest_non_null(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return float(value)
    return None


@dataclass(frozen=True)
class PairMetric:
    leader: str
    follower: str
    lag_minutes: int
    correlation: float
    sample_size: int
    contemporaneous_correlation: float | None
    leader_latest_return: float | None


def _compute_pair_metrics(
    asset_returns: dict[str, list[float | None]],
    *,
    max_lag_minutes: int,
    min_points: int,
    min_correlation: float,
) -> list[PairMetric]:
    assets = sorted(asset_returns.keys())
    metrics: list[PairMetric] = []
    for leader in assets:
        leader_series = asset_returns.get(leader) or []
        if len(leader_series) < min_points:
            continue
        for follower in assets:
            if follower == leader:
                continue
            follower_series = asset_returns.get(follower) or []
            if len(follower_series) < min_points:
                continue
            aligned_len = min(len(leader_series), len(follower_series))
            if aligned_len < min_points:
                continue
            leader_trimmed = leader_series[-aligned_len:]
            follower_trimmed = follower_series[-aligned_len:]
            contemp_x, contemp_y = _paired_values(leader_trimmed, follower_trimmed)
            contemp_corr = _pearson_corr(contemp_x, contemp_y)

            best_corr = None
            best_lag = None
            best_n = 0
            for lag in range(1, max(1, int(max_lag_minutes)) + 1):
                if aligned_len - lag < min_points:
                    continue
                lagged_leader = leader_trimmed[:-lag]
                lagged_follower = follower_trimmed[lag:]
                x, y = _paired_values(lagged_leader, lagged_follower)
                corr = _pearson_corr(x, y)
                if corr is None or len(x) < min_points:
                    continue
                if best_corr is None or corr > best_corr:
                    best_corr = corr
                    best_lag = lag
                    best_n = len(x)
            if best_corr is None or best_lag is None:
                continue
            if best_corr < float(min_correlation):
                continue
            metrics.append(
                PairMetric(
                    leader=leader,
                    follower=follower,
                    lag_minutes=int(best_lag),
                    correlation=float(best_corr),
                    sample_size=int(best_n),
                    contemporaneous_correlation=(
                        None if contemp_corr is None else float(contemp_corr)
                    ),
                    leader_latest_return=_latest_non_null(leader_trimmed),
                )
            )
    metrics.sort(key=lambda item: item.correlation, reverse=True)
    return metrics


def _signals_from_metrics(
    metrics: list[PairMetric],
    *,
    min_signal_confidence: float,
) -> dict[str, dict[str, Any]]:
    direction_votes: dict[str, dict[str, float]] = {}
    supporters: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        leader_ret = metric.leader_latest_return
        if leader_ret is None:
            continue
        if abs(leader_ret) <= 1e-12:
            continue
        direction = "UP" if leader_ret > 0 else "DOWN"
        vote_weight = max(0.0, float(metric.correlation))
        if vote_weight <= 0:
            continue
        votes = direction_votes.setdefault(metric.follower, {"UP": 0.0, "DOWN": 0.0})
        votes[direction] = votes.get(direction, 0.0) + vote_weight
        supporters.setdefault(metric.follower, []).append(
            {
                "leader": metric.leader,
                "lag_minutes": metric.lag_minutes,
                "correlation": round(metric.correlation, 6),
                "sample_size": metric.sample_size,
                "leader_latest_return": round(float(leader_ret), 10),
            }
        )

    output: dict[str, dict[str, Any]] = {}
    for symbol, votes in direction_votes.items():
        up_score = float(votes.get("UP", 0.0))
        down_score = float(votes.get("DOWN", 0.0))
        total = up_score + down_score
        if total <= 0:
            continue
        direction = "UP" if up_score >= down_score else "DOWN"
        dominant = up_score if direction == "UP" else down_score
        confidence = _clamp01(dominant / total)
        if confidence < float(min_signal_confidence):
            continue
        support_rows = sorted(
            supporters.get(symbol, []),
            key=lambda row: float(row.get("correlation", 0.0)),
            reverse=True,
        )
        top_support = support_rows[0] if support_rows else {}
        output[symbol] = {
            "direction": direction,
            "confidence": round(confidence, 6),
            "score": round(dominant, 6),
            "leader": top_support.get("leader"),
            "lag_minutes": top_support.get("lag_minutes"),
            "correlation": top_support.get("correlation"),
            "supporting_leaders": support_rows[:5],
        }
    return output


def generate_cross_asset_signals(
    *,
    db_paths: dict[str, Path] | None = None,
    lookback_minutes: int = 120,
    max_lag_minutes: int = 5,
    min_points: int = 30,
    min_correlation: float = 0.25,
    min_signal_confidence: float = 0.55,
) -> dict[str, Any]:
    db_paths = {k.upper(): Path(v) for k, v in (db_paths or DEFAULT_DB_PATHS).items()}
    now_ts = int(time.time())
    start_ts = now_ts - (max(30, int(lookback_minutes)) * 60)
    raw_prices: dict[str, dict[int, float]] = {
        symbol: _query_recent_prices(path, since_ts=start_ts)
        for symbol, path in db_paths.items()
    }
    available = [symbol for symbol, prices in raw_prices.items() if prices]
    if not available:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now_iso(),
            "lookback_minutes": int(lookback_minutes),
            "max_lag_minutes": int(max_lag_minutes),
            "min_points": int(min_points),
            "min_correlation": float(min_correlation),
            "source_dbs": {symbol: str(path) for symbol, path in db_paths.items()},
            "assets": sorted(db_paths.keys()),
            "available_assets": [],
            "pair_metrics": [],
            "signals": {},
            "summary": {"relations_detected": 0, "active_signals": 0},
        }

    max_seen = max(max(series.keys()) for series in raw_prices.values() if series)
    window_start = max_seen - (max(30, int(lookback_minutes)) * 60)
    asset_returns: dict[str, list[float | None]] = {}
    for symbol in sorted(db_paths.keys()):
        prices = raw_prices.get(symbol) or {}
        price_series = _forward_fill_prices(prices, start_ts=window_start, end_ts=max_seen)
        asset_returns[symbol] = _returns_from_prices(price_series)

    pair_metrics = _compute_pair_metrics(
        asset_returns,
        max_lag_minutes=max_lag_minutes,
        min_points=min_points,
        min_correlation=min_correlation,
    )
    signals = _signals_from_metrics(pair_metrics, min_signal_confidence=min_signal_confidence)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "lookback_minutes": int(lookback_minutes),
        "max_lag_minutes": int(max_lag_minutes),
        "min_points": int(min_points),
        "min_correlation": float(min_correlation),
        "source_dbs": {symbol: str(path) for symbol, path in db_paths.items()},
        "assets": sorted(db_paths.keys()),
        "available_assets": sorted(available),
        "pair_metrics": [
            {
                "leader": metric.leader,
                "follower": metric.follower,
                "lag_minutes": metric.lag_minutes,
                "correlation": round(metric.correlation, 6),
                "sample_size": metric.sample_size,
                "contemporaneous_correlation": (
                    None
                    if metric.contemporaneous_correlation is None
                    else round(metric.contemporaneous_correlation, 6)
                ),
                "leader_latest_return": (
                    None if metric.leader_latest_return is None else round(metric.leader_latest_return, 10)
                ),
            }
            for metric in pair_metrics
        ],
        "signals": signals,
        "summary": {
            "relations_detected": len(pair_metrics),
            "active_signals": len(signals),
        },
    }
    return payload


def write_cross_asset_signals(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_asset_confirmation(
    *,
    signals_path: Path,
    asset_symbol: str,
    direction: str,
    max_age_seconds: int = 900,
    min_confidence: float = 0.55,
) -> dict[str, Any] | None:
    if not signals_path.exists():
        return None
    try:
        payload = json.loads(signals_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    generated_ts = _parse_iso_ts(payload.get("generated_at"))
    if generated_ts is None:
        return None
    if int(time.time()) - generated_ts > max(60, int(max_age_seconds)):
        return None
    signals = payload.get("signals")
    if not isinstance(signals, dict):
        return None
    key = str(asset_symbol or "").strip().upper()
    target_direction = str(direction or "").strip().upper()
    if target_direction not in {"UP", "DOWN"}:
        return None
    signal = signals.get(key)
    if not isinstance(signal, dict):
        return None
    signal_direction = str(signal.get("direction") or "").strip().upper()
    if signal_direction != target_direction:
        return None
    confidence = _safe_float(signal.get("confidence"), 0.0) or 0.0
    if confidence < _clamp01(float(min_confidence)):
        return None
    return {
        "direction": signal_direction,
        "confidence": round(_clamp01(float(confidence)), 6),
        "leader": str(signal.get("leader") or "").strip() or None,
        "lag_minutes": int(_safe_float(signal.get("lag_minutes"), 0.0) or 0) or None,
        "correlation": _safe_float(signal.get("correlation"), None),
        "score": _safe_float(signal.get("score"), None),
        "generated_at": str(payload.get("generated_at") or ""),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--lookback-minutes", type=int, default=120)
    parser.add_argument("--max-lag-minutes", type=int, default=5)
    parser.add_argument("--min-points", type=int, default=30)
    parser.add_argument("--min-correlation", type=float, default=0.25)
    parser.add_argument("--min-signal-confidence", type=float, default=0.55)
    parser.add_argument(
        "--assets",
        type=str,
        default=",".join(DEFAULT_DB_PATHS.keys()),
        help="Comma-separated list of symbols to include (default: all 6).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    requested_assets = [part.strip().upper() for part in str(args.assets).split(",") if part.strip()]
    db_paths = {
        symbol: path
        for symbol, path in DEFAULT_DB_PATHS.items()
        if not requested_assets or symbol in requested_assets
    }
    payload = generate_cross_asset_signals(
        db_paths=db_paths,
        lookback_minutes=args.lookback_minutes,
        max_lag_minutes=args.max_lag_minutes,
        min_points=args.min_points,
        min_correlation=args.min_correlation,
        min_signal_confidence=args.min_signal_confidence,
    )
    write_cross_asset_signals(args.output, payload)
    print(
        "wrote",
        args.output,
        f"relations={payload.get('summary', {}).get('relations_detected', 0)}",
        f"signals={payload.get('summary', {}).get('active_signals', 0)}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

