#!/usr/bin/env python3
"""Audit live trade attribution by signal source and emit a JSON summary."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.combinatorial_integration import canonical_source_key, normalize_source_components
from bot.lmsr_engine import LMSREngine, MIN_TRADES_FOR_SIGNAL, estimate_b_from_volume


EXECUTION_SOURCES = (
    "llm",
    "wallet_flow",
    "lmsr",
    "cross_platform_arb",
    "lead_lag",
)

SOURCE_DECISION_SCOPE = {
    "llm": {"role": "execution"},
    "wallet_flow": {"role": "execution"},
    "lmsr": {"role": "execution"},
    "cross_platform_arb": {"role": "execution"},
    "lead_lag": {"role": "execution"},
    "microstructure_gate": {
        "role": "gate_only",
        "components": ["vpin", "ofi"],
    },
}

BTC_FAST_WINDOW_CONFIRMATION_ARCHIVE_SCHEMA = "btc_fast_window_confirmation_archive.v1"
BTC_FAST_WINDOW_SOURCES = ("wallet_flow", "lmsr")
MIN_CONFIRMATION_SIGNAL_WINDOWS = 3
MIN_CONFIRMATION_EXECUTED_WINDOWS = 2
CONFIRMATION_SOURCE_STALE_HOURS = 6.0
# Use the local BTC5 maker database as the default probe source because it
# carries the freshest resolved window coverage for confirmation joins.
DEFAULT_BTC5_PROBE_DB_PATH = PROJECT_ROOT / "data" / "btc_5min_maker.db"
DEFAULT_EDGE_DISCOVERY_DB_PATH = PROJECT_ROOT / "data" / "edge_discovery_locked.db"
DEFAULT_WALLET_DB_PATH = PROJECT_ROOT / "data" / "wallet_scores.db"
DEFAULT_CONFIRMATION_OUTPUT_PATH = PROJECT_ROOT / "reports" / "btc_fast_window_confirmation_archive.json"
DEFAULT_REMOTE_BTC5_ROWS_PATH = PROJECT_ROOT / "reports" / "tmp_remote_btc5_window_rows.json"
DEFAULT_BTC5_ARCHIVE_GLOB = "reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv"
DEFAULT_RUNTIME_TRUTH_PATH = PROJECT_ROOT / "reports" / "runtime_truth_latest.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _normalize_btc_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"UP", "YES", "BUY_YES", "BUY YES"}:
        return "UP"
    if text in {"DOWN", "NO", "BUY_NO", "BUY NO"}:
        return "DOWN"
    return None


def _effective_outcome_to_direction(value: Any) -> str | None:
    parsed = _safe_int(value, default=-1)
    if parsed == 0:
        return "UP"
    if parsed == 1:
        return "DOWN"
    return None


def _present_metric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _mid_price(*, best_bid: Any, best_ask: Any, fallback_price: Any) -> float | None:
    bid = _present_metric(best_bid)
    ask = _present_metric(best_ask)
    fallback = _present_metric(fallback_price)
    if bid is not None and ask is not None:
        return max(0.0, min(1.0, (bid + ask) / 2.0))
    if fallback is not None:
        return max(0.0, min(1.0, fallback))
    if bid is not None:
        return max(0.0, min(1.0, bid))
    if ask is not None:
        return max(0.0, min(1.0, ask))
    return None


def _btc_yes_price_from_window(row: dict[str, Any]) -> float | None:
    selected_price = _mid_price(
        best_bid=row.get("best_bid"),
        best_ask=row.get("best_ask"),
        fallback_price=row.get("order_price"),
    )
    if selected_price is None:
        return None
    direction = _normalize_btc_direction(row.get("direction"))
    if direction == "UP":
        return selected_price
    if direction == "DOWN":
        return max(0.0, min(1.0, 1.0 - selected_price))
    return None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _timestamp_to_iso_utc(value: Any) -> str | None:
    parsed = _safe_int(value, default=0)
    if parsed <= 0:
        return None
    return datetime.fromtimestamp(parsed, tz=timezone.utc).isoformat()


def _btc5_slug_window_start_ts(slug: Any) -> int | None:
    text = str(slug or "").strip()
    if not text.startswith("btc-updown-5m-"):
        return None
    suffix = text.rsplit("-", 1)[-1]
    if not suffix.isdigit():
        return None
    parsed = _safe_int(suffix, default=0)
    return parsed if parsed > 0 else None


def _slug_window_bounds(slugs: set[str]) -> dict[str, Any]:
    parsed_rows: list[tuple[int, str]] = []
    for slug in slugs:
        ts = _btc5_slug_window_start_ts(slug)
        if ts is None:
            continue
        parsed_rows.append((ts, slug))
    if not parsed_rows:
        return {
            "window_start_ts_min": None,
            "window_start_ts_max": None,
            "window_start_at_min": None,
            "window_start_at_max": None,
            "slug_min": None,
            "slug_max": None,
        }
    parsed_rows.sort(key=lambda item: item[0])
    min_ts, min_slug = parsed_rows[0]
    max_ts, max_slug = parsed_rows[-1]
    return {
        "window_start_ts_min": min_ts,
        "window_start_ts_max": max_ts,
        "window_start_at_min": _timestamp_to_iso_utc(min_ts),
        "window_start_at_max": _timestamp_to_iso_utc(max_ts),
        "slug_min": min_slug,
        "slug_max": max_slug,
    }


def _gap_hours(*, latest_ts: Any, observed_ts: Any) -> float | None:
    latest = _safe_float(latest_ts, default=-1.0)
    observed = _safe_float(observed_ts, default=-1.0)
    if latest < 0.0 or observed < 0.0:
        return None
    return max(0.0, (latest - observed) / 3600.0)


def _freshness_label_for_gap_hours(gap_hours: float | None) -> str:
    if gap_hours is None:
        return "unknown"
    if gap_hours <= max(CONFIRMATION_SOURCE_STALE_HOURS / 2.0, 0.5):
        return "fresh"
    if gap_hours <= CONFIRMATION_SOURCE_STALE_HOURS:
        return "aging"
    return "stale"


def _confirmation_coverage_label(
    *,
    status: str,
    resolved_window_coverage: Any,
    executed_window_coverage: Any,
) -> str:
    if str(status).strip().lower() != "ready":
        return "missing"
    resolved = _safe_float(resolved_window_coverage, 0.0)
    executed = _safe_float(executed_window_coverage, 0.0)
    if resolved >= 0.70 and executed >= 0.50:
        return "strong"
    if resolved >= 0.45 and executed >= 0.30:
        return "moderate"
    return "weak"


def _confirmation_strength_score(
    *,
    status: str,
    resolved_window_coverage: Any,
    executed_window_coverage: Any,
    confirmation_lift_avg_pnl_usd: Any,
    confirmation_lift_win_rate: Any,
    confirmation_contradiction_penalty: Any,
    false_suppression_cost_usd: Any,
    false_confirmation_cost_usd: Any,
) -> float:
    if str(status).strip().lower() != "ready":
        return 0.0

    resolved = _clamp(_safe_float(resolved_window_coverage, 0.0), 0.0, 1.0)
    executed = _clamp(_safe_float(executed_window_coverage, 0.0), 0.0, 1.0)
    lift_avg_pnl = _safe_float(confirmation_lift_avg_pnl_usd, 0.0)
    lift_win_rate = _safe_float(confirmation_lift_win_rate, 0.0)
    contradiction_penalty = _clamp(_safe_float(confirmation_contradiction_penalty, 0.0), 0.0, 1.0)
    false_cost = max(
        0.0,
        _safe_float(false_suppression_cost_usd, 0.0) + _safe_float(false_confirmation_cost_usd, 0.0),
    )

    score = (
        (0.45 * resolved)
        + (0.25 * executed)
        + (0.15 * _clamp(lift_win_rate, 0.0, 0.25) / 0.25)
        + (0.15 * _clamp(lift_avg_pnl, 0.0, 2.0) / 2.0)
        - (0.20 * contradiction_penalty)
        - (0.10 * _clamp(false_cost / 5.0, 0.0, 1.0))
    )
    return round(_clamp(score, 0.0, 1.0), 6)


def _confirmation_strength_label(
    *,
    status: str,
    coverage_label: str,
    strength_score: float,
) -> str:
    if str(status).strip().lower() != "ready":
        return "missing"
    if coverage_label == "weak":
        return "weak"
    if coverage_label == "strong" and strength_score >= 0.65:
        return "strong"
    if strength_score >= 0.40:
        return "moderate"
    return "weak"


def _load_btc_fast_window_rows(probe_db_path: Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    if probe_db_path is None:
        return [], ["btc5_probe_db_not_provided"]
    if not probe_db_path.exists():
        fallback_rows, fallback_requirements = _load_btc_fast_window_rows_from_reports()
        if fallback_rows:
            return fallback_rows, []
        return [], [f"btc5_probe_db_missing:{probe_db_path}", *fallback_requirements]

    conn = sqlite3.connect(str(probe_db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "window_trades"):
            fallback_rows, fallback_requirements = _load_btc_fast_window_rows_from_reports()
            if fallback_rows:
                return fallback_rows, []
            return [], [f"btc5_probe_window_trades_missing:{probe_db_path}", *fallback_requirements]

        columns = {row[1] for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()}
        selected_columns = []
        for column in (
            "slug",
            "window_start_ts",
            "window_end_ts",
            "decision_ts",
            "direction",
            "order_status",
            "order_price",
            "trade_size_usd",
            "filled",
            "resolved_side",
            "won",
            "pnl_usd",
            "best_bid",
            "best_ask",
            "token_id",
            "created_at",
            "updated_at",
        ):
            if column in columns:
                selected_columns.append(column)
            else:
                selected_columns.append(f"NULL AS {column}")

        rows = conn.execute(
            f"""
            SELECT
                {", ".join(selected_columns)}
            FROM window_trades
            WHERE slug LIKE 'btc-updown-5m-%'
            ORDER BY COALESCE(decision_ts, window_end_ts, window_start_ts) ASC
            """
        ).fetchall()
        loaded_rows = [dict(row) for row in rows]
        if loaded_rows:
            return loaded_rows, []
        fallback_rows, fallback_requirements = _load_btc_fast_window_rows_from_reports()
        if fallback_rows:
            return fallback_rows, []
        return [], [f"btc5_probe_window_rows_0:{probe_db_path}", *fallback_requirements]
    finally:
        conn.close()


def _parse_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _latest_existing_path(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _latest_btc5_bundle_dir() -> Path | None:
    candidates = [
        path
        for path in (PROJECT_ROOT / "reports").glob("btc_intraday_llm_bundle_*")
        if path.is_dir()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.name)


def _normalize_remote_probe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": row.get("slug"),
        "window_start_ts": _safe_int(row.get("window_start_ts"), default=0),
        "window_end_ts": _safe_int(row.get("window_end_ts"), default=0),
        "decision_ts": _safe_int(row.get("decision_ts"), default=0),
        "direction": row.get("direction"),
        "order_status": row.get("order_status"),
        "order_price": _present_metric(row.get("order_price")),
        "trade_size_usd": _present_metric(row.get("trade_size_usd")),
        "filled": _safe_int(row.get("filled"), default=1 if str(row.get("order_status") or "").lower() == "live_filled" else 0),
        "resolved_side": row.get("resolved_side") or ("UP" if row.get("won") is True else "DOWN" if row.get("won") is False else None),
        "won": row.get("won"),
        "pnl_usd": _present_metric(row.get("pnl_usd")),
        "best_bid": _present_metric(row.get("best_bid")),
        "best_ask": _present_metric(row.get("best_ask")),
        "token_id": row.get("token_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _load_btc_fast_window_rows_from_reports() -> tuple[list[dict[str, Any]], list[str]]:
    requirements: list[str] = []
    cache_path = DEFAULT_REMOTE_BTC5_ROWS_PATH
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            requirements.append(f"btc5_probe_report_invalid_json:{cache_path}")
        else:
            candidates = payload if isinstance(payload, list) else []
            rows = [
                _normalize_remote_probe_row(dict(item))
                for item in candidates
                if isinstance(item, dict) and str(item.get("slug") or "").startswith("btc-updown-5m-")
            ]
            if rows:
                return rows, [f"btc5_probe_db_missing_local_path_using_report:{cache_path}"]
            requirements.append(f"btc5_probe_report_rows_0:{cache_path}")

    bundle_dir = _latest_btc5_bundle_dir()
    if bundle_dir is None:
        requirements.append("btc5_probe_report_bundle_missing")
        return [], requirements

    csv_path = bundle_dir / "raw" / "remote_btc5_window_trades.csv"
    if not csv_path.exists():
        requirements.append(f"btc5_probe_bundle_csv_missing:{csv_path}")
        return [], requirements

    rows = [
        _normalize_remote_probe_row(row)
        for row in _parse_csv_rows(csv_path)
        if str(row.get("slug") or "").startswith("btc-updown-5m-")
    ]
    if rows:
        return rows, [f"btc5_probe_db_missing_local_path_using_bundle:{csv_path}"]
    requirements.append(f"btc5_probe_bundle_rows_0:{csv_path}")
    return [], requirements


def _load_wallet_flow_confirmation_signals(
    wallet_db_path: Path | None,
    *,
    slugs: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    diagnostics = {
        "available": False,
        "path": str(wallet_db_path) if wallet_db_path is not None else None,
        "missing_requirements": [],
        "candidate_windows": len(slugs),
        "signal_windows": 0,
        "latest_btc5_trade_timestamp": None,
        "latest_btc5_trade_at": None,
        "latest_btc5_slug": None,
        "latest_signal_timestamp": None,
        "latest_signal_at": None,
        "available_btc5_slug_count": 0,
        "overlap_with_probe_slug_count": 0,
    }
    if wallet_db_path is None:
        diagnostics["missing_requirements"].append("wallet_flow_db_not_provided")
        return _load_wallet_flow_confirmation_signals_from_reports(slugs=slugs, diagnostics=diagnostics)
    if not wallet_db_path.exists():
        diagnostics["missing_requirements"].append(f"wallet_flow_db_missing:{wallet_db_path}")
        return _load_wallet_flow_confirmation_signals_from_reports(slugs=slugs, diagnostics=diagnostics)

    conn = sqlite3.connect(str(wallet_db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "wallet_scores") or not _table_exists(conn, "wallet_trades"):
            diagnostics["missing_requirements"].append(f"wallet_flow_tables_missing:{wallet_db_path}")
            return {}, diagnostics

        latest_btc5_row = conn.execute(
            """
            SELECT event_slug, timestamp
            FROM wallet_trades
            WHERE event_slug LIKE 'btc-updown-5m-%'
            ORDER BY timestamp DESC
            LIMIT 1
            """
        ).fetchone()
        if latest_btc5_row is not None:
            latest_btc5_timestamp = _safe_int(latest_btc5_row["timestamp"], default=0)
            if latest_btc5_timestamp > 0:
                diagnostics["latest_btc5_trade_timestamp"] = latest_btc5_timestamp
                diagnostics["latest_btc5_trade_at"] = _timestamp_to_iso_utc(latest_btc5_timestamp)
                diagnostics["latest_btc5_slug"] = str(latest_btc5_row["event_slug"] or "").strip() or None

        available_slug_rows = conn.execute(
            """
            SELECT DISTINCT event_slug
            FROM wallet_trades
            WHERE event_slug LIKE 'btc-updown-5m-%'
            """
        ).fetchall()
        available_slugs = {
            str(row["event_slug"] or "").strip()
            for row in available_slug_rows
            if str(row["event_slug"] or "").strip()
        }
        diagnostics["available_btc5_slug_count"] = len(available_slugs)
        diagnostics["overlap_with_probe_slug_count"] = len(available_slugs & slugs)
        diagnostics.update(_slug_window_bounds(available_slugs))

        if not slugs:
            diagnostics["available"] = True
            return {}, diagnostics

        placeholders = ",".join("?" for _ in slugs)
        rows = conn.execute(
            f"""
            SELECT
                wt.event_slug,
                wt.wallet,
                wt.effective_outcome,
                wt.size,
                wt.price,
                wt.timestamp
            FROM wallet_trades wt
            JOIN wallet_scores ws
              ON ws.wallet = wt.wallet
            WHERE ws.is_smart = 1
              AND wt.event_slug IN ({placeholders})
            ORDER BY wt.timestamp ASC
            """,
            tuple(sorted(slugs)),
        ).fetchall()
    finally:
        conn.close()

    by_slug: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = str(row["event_slug"] or "").strip()
        direction = _effective_outcome_to_direction(row["effective_outcome"])
        if not slug or direction is None:
            continue
        bucket = by_slug.setdefault(
            slug,
            {
                "directions": {
                    "UP": {"volume": 0.0, "trades": 0, "wallets": set()},
                    "DOWN": {"volume": 0.0, "trades": 0, "wallets": set()},
                },
                "total_volume": 0.0,
                "total_trades": 0,
                "wallets": set(),
                "prices": [],
                "first_timestamp": None,
                "last_timestamp": None,
            },
        )
        volume = max(_safe_float(row["size"]), 0.0)
        direction_bucket = bucket["directions"][direction]
        direction_bucket["volume"] += volume
        direction_bucket["trades"] += 1
        direction_bucket["wallets"].add(str(row["wallet"] or ""))
        bucket["total_volume"] += volume
        bucket["total_trades"] += 1
        bucket["wallets"].add(str(row["wallet"] or ""))
        price = _present_metric(row["price"])
        if price is not None:
            bucket["prices"].append(price)
        timestamp = _safe_int(row["timestamp"], default=0)
        if bucket["first_timestamp"] is None or timestamp < bucket["first_timestamp"]:
            bucket["first_timestamp"] = timestamp
        if bucket["last_timestamp"] is None or timestamp > bucket["last_timestamp"]:
            bucket["last_timestamp"] = timestamp

    signals: dict[str, dict[str, Any]] = {}
    for slug, bucket in by_slug.items():
        ranked = []
        for direction, direction_bucket in bucket["directions"].items():
            ranked.append(
                (
                    _safe_float(direction_bucket["volume"], 0.0),
                    int(direction_bucket["trades"]),
                    len(direction_bucket["wallets"]),
                    direction,
                )
            )
        consensus_volume, consensus_trades, consensus_wallets, consensus_direction = max(ranked)
        total_volume = _safe_float(bucket["total_volume"], 0.0)
        signals[slug] = {
            "status": "present",
            "direction": consensus_direction,
            "consensus_share": (consensus_volume / total_volume) if total_volume > 0 else None,
            "consensus_volume": round(consensus_volume, 6),
            "consensus_trades": int(consensus_trades),
            "consensus_unique_wallets": int(consensus_wallets),
            "total_volume": round(total_volume, 6),
            "total_trades": int(bucket["total_trades"]),
            "unique_wallets": len(bucket["wallets"]),
            "avg_price": (
                round(sum(bucket["prices"]) / len(bucket["prices"]), 6)
                if bucket["prices"]
                else None
            ),
            "first_timestamp": bucket["first_timestamp"],
            "last_timestamp": bucket["last_timestamp"],
        }

    diagnostics["available"] = True
    diagnostics["signal_windows"] = len(signals)
    latest_signal_timestamp = max(
        (
            _safe_int(signal.get("last_timestamp"), default=0)
            for signal in signals.values()
            if _safe_int(signal.get("last_timestamp"), default=0) > 0
        ),
        default=0,
    )
    if latest_signal_timestamp > 0:
        diagnostics["latest_signal_timestamp"] = latest_signal_timestamp
        diagnostics["latest_signal_at"] = _timestamp_to_iso_utc(latest_signal_timestamp)
    if not signals:
        diagnostics["missing_requirements"].append("wallet_flow_overlap_windows_0")
    return signals, diagnostics


def _load_wallet_flow_confirmation_signals_from_reports(
    *,
    slugs: set[str],
    diagnostics: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bundle_dir = _latest_btc5_bundle_dir()
    if bundle_dir is None:
        diagnostics["missing_requirements"].append("wallet_flow_bundle_missing")
        return {}, diagnostics

    consensus_path = bundle_dir / "derived" / "wallet_consensus_btc5_windows.csv"
    trades_path = bundle_dir / "raw" / "wallet_wallet_trades.csv"
    if not consensus_path.exists():
        diagnostics["missing_requirements"].append(f"wallet_flow_bundle_consensus_missing:{consensus_path}")
        return {}, diagnostics

    diagnostics["path"] = str(consensus_path)
    consensus_rows = _parse_csv_rows(consensus_path)
    available_slugs = {
        str(row.get("event_slug") or "").strip()
        for row in consensus_rows
        if str(row.get("event_slug") or "").strip()
    }
    diagnostics["available_btc5_slug_count"] = len(available_slugs)
    diagnostics["overlap_with_probe_slug_count"] = len(available_slugs & slugs)
    diagnostics.update(_slug_window_bounds(available_slugs))

    latest_trade_timestamp = 0
    latest_trade_slug: str | None = None
    if trades_path.exists():
        for row in _parse_csv_rows(trades_path):
            slug = str(row.get("event_slug") or "").strip()
            if not slug.startswith("btc-updown-5m-"):
                continue
            timestamp = _safe_int(row.get("timestamp"), default=0)
            if timestamp > latest_trade_timestamp:
                latest_trade_timestamp = timestamp
                latest_trade_slug = slug
    if latest_trade_timestamp > 0:
        diagnostics["latest_btc5_trade_timestamp"] = latest_trade_timestamp
        diagnostics["latest_btc5_trade_at"] = _timestamp_to_iso_utc(latest_trade_timestamp)
        diagnostics["latest_btc5_slug"] = latest_trade_slug

    signals: dict[str, dict[str, Any]] = {}
    for row in consensus_rows:
        slug = str(row.get("event_slug") or "").strip()
        if not slug or (slugs and slug not in slugs):
            continue
        direction = _normalize_btc_direction(row.get("consensus_direction"))
        if direction is None:
            continue
        last_timestamp = _safe_int(row.get("last_timestamp"), default=0)
        signals[slug] = {
            "status": "present",
            "direction": direction,
            "consensus_share": _present_metric(row.get("consensus_share")),
            "consensus_volume": round(_safe_float(row.get("total_volume"), 0.0), 6),
            "consensus_trades": _safe_int(row.get("trades"), default=0),
            "consensus_unique_wallets": _safe_int(row.get("unique_wallets"), default=0),
            "total_volume": round(_safe_float(row.get("window_total_volume"), 0.0), 6),
            "total_trades": _safe_int(row.get("trades"), default=0),
            "unique_wallets": _safe_int(row.get("unique_wallets"), default=0),
            "avg_price": _present_metric(row.get("avg_price")),
            "first_timestamp": _safe_int(row.get("first_timestamp"), default=0),
            "last_timestamp": last_timestamp,
        }

    diagnostics["available"] = True
    diagnostics["signal_windows"] = len(signals)
    latest_signal_timestamp = max(
        (_safe_int(signal.get("last_timestamp"), default=0) for signal in signals.values()),
        default=0,
    )
    if latest_signal_timestamp > 0:
        diagnostics["latest_signal_timestamp"] = latest_signal_timestamp
        diagnostics["latest_signal_at"] = _timestamp_to_iso_utc(latest_signal_timestamp)
    if diagnostics["missing_requirements"]:
        diagnostics["missing_requirements"].append(f"wallet_flow_db_missing_local_path_using_bundle:{consensus_path}")
    if not signals:
        diagnostics["missing_requirements"].append("wallet_flow_overlap_windows_0")
    return signals, diagnostics


def _market_volume_from_raw_json(raw_json: Any) -> float:
    if not isinstance(raw_json, str) or not raw_json.strip():
        return 0.0
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return 0.0
    return _safe_float(payload.get("volume"), 0.0)


def _trade_outcome_index(row: sqlite3.Row | dict[str, Any]) -> int | None:
    outcome = _normalize_btc_direction((row.get("outcome") if isinstance(row, dict) else row["outcome"]))
    if outcome == "UP":
        return 0
    if outcome == "DOWN":
        return 1
    return None


def _build_lmsr_signal_for_window(
    row: dict[str, Any],
    *,
    market_row: sqlite3.Row,
    trade_rows: list[sqlite3.Row],
) -> dict[str, Any] | None:
    yes_price = _btc_yes_price_from_window(row)
    if yes_price is None:
        return None

    decision_ts = _safe_int(row.get("decision_ts") or row.get("window_end_ts"), default=0)
    relevant_trades = [trade for trade in trade_rows if _safe_int(trade["timestamp_ts"], default=0) <= decision_ts]
    if len(relevant_trades) < MIN_TRADES_FOR_SIGNAL:
        return None

    question = str(market_row["question"] or market_row["slug"] or "")
    market_id = str(market_row["condition_id"] or "")
    volume = _market_volume_from_raw_json(market_row["raw_json"])
    engine = LMSREngine()
    state = engine._get_or_create_state(
        market_id,
        question,
        yes_price,
        b=estimate_b_from_volume(volume) if volume > 0 else estimate_b_from_volume(0.0),
    )
    engine.ingest_trades(
        state,
        [
            {
                "timestamp": _safe_int(trade["timestamp_ts"], default=0),
                "side": str(trade["side"] or ""),
                "outcomeIndex": outcome_index,
                "size": _safe_float(trade["size"]),
                "price": _safe_float(trade["price"], default=0.5),
            }
            for trade in relevant_trades
            if (outcome_index := _trade_outcome_index(trade)) is not None
        ],
    )
    signal = engine.compute_signal(state, yes_price)
    if not signal:
        return None

    direction = _normalize_btc_direction(signal.get("direction"))
    if direction is None:
        return None
    return {
        "status": "present",
        "direction": direction,
        "edge": signal.get("edge"),
        "confidence": signal.get("confidence"),
        "market_price_yes": signal.get("market_price"),
        "estimated_prob": signal.get("estimated_prob"),
        "trades_processed": int(state.trades_processed),
        "last_trade_timestamp": _safe_int(relevant_trades[-1]["timestamp_ts"], default=0),
    }


def _load_lmsr_confirmation_signals(
    edge_db_path: Path | None,
    *,
    window_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    diagnostics = {
        "available": False,
        "path": str(edge_db_path) if edge_db_path is not None else None,
        "missing_requirements": [],
        "candidate_windows": len(window_rows),
        "signal_windows": 0,
        "matched_markets": 0,
        "latest_btc5_market_window_end_ts": None,
        "latest_btc5_market_window_end_at": None,
        "latest_btc5_slug": None,
        "latest_signal_timestamp": None,
        "latest_signal_at": None,
        "available_btc5_slug_count": 0,
        "overlap_with_probe_slug_count": 0,
    }
    if edge_db_path is None:
        diagnostics["missing_requirements"].append("edge_discovery_db_not_provided")
        return _load_lmsr_confirmation_signals_from_reports(window_rows=window_rows, diagnostics=diagnostics)
    if not edge_db_path.exists():
        diagnostics["missing_requirements"].append(f"edge_discovery_db_missing:{edge_db_path}")
        return _load_lmsr_confirmation_signals_from_reports(window_rows=window_rows, diagnostics=diagnostics)

    slugs = {str(row.get("slug") or "").strip() for row in window_rows if row.get("slug")}
    diagnostics.update(_slug_window_bounds(slugs))
    if not slugs:
        diagnostics["available"] = True
        return {}, diagnostics

    conn = sqlite3.connect(str(edge_db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "markets") or not _table_exists(conn, "trades"):
            diagnostics["missing_requirements"].append(f"edge_discovery_tables_missing:{edge_db_path}")
            return {}, diagnostics

        latest_btc5_market_row = conn.execute(
            """
            SELECT slug, window_end_ts
            FROM markets
            WHERE slug LIKE 'btc-updown-5m-%'
            ORDER BY COALESCE(window_end_ts, window_start_ts) DESC
            LIMIT 1
            """
        ).fetchone()
        if latest_btc5_market_row is not None:
            latest_market_ts = _safe_int(latest_btc5_market_row["window_end_ts"], default=0)
            if latest_market_ts > 0:
                diagnostics["latest_btc5_market_window_end_ts"] = latest_market_ts
                diagnostics["latest_btc5_market_window_end_at"] = _timestamp_to_iso_utc(latest_market_ts)
                diagnostics["latest_btc5_slug"] = str(latest_btc5_market_row["slug"] or "").strip() or None

        available_slug_rows = conn.execute(
            """
            SELECT DISTINCT slug
            FROM markets
            WHERE slug LIKE 'btc-updown-5m-%'
            """
        ).fetchall()
        available_slugs = {
            str(row["slug"] or "").strip()
            for row in available_slug_rows
            if str(row["slug"] or "").strip()
        }
        diagnostics["available_btc5_slug_count"] = len(available_slugs)
        diagnostics["overlap_with_probe_slug_count"] = len(available_slugs & slugs)
        diagnostics.update(
            {
                f"market_{key}": value
                for key, value in _slug_window_bounds(available_slugs).items()
            }
        )

        placeholders = ",".join("?" for _ in slugs)
        market_rows = conn.execute(
            f"""
            SELECT slug, condition_id, question, raw_json
            FROM markets
            WHERE slug IN ({placeholders})
            """,
            tuple(sorted(slugs)),
        ).fetchall()
        markets_by_slug = {str(row["slug"]): row for row in market_rows}
        diagnostics["matched_markets"] = len(markets_by_slug)
        if not markets_by_slug:
            diagnostics["available"] = True
            diagnostics["missing_requirements"].append("edge_market_overlap_0")
            return {}, diagnostics

        condition_ids = [str(row["condition_id"]) for row in market_rows if row["condition_id"]]
        trade_rows: list[sqlite3.Row] = []
        if condition_ids:
            trade_placeholders = ",".join("?" for _ in condition_ids)
            trade_rows = conn.execute(
                f"""
                SELECT condition_id, timestamp_ts, side, outcome, price, size
                FROM trades
                WHERE condition_id IN ({trade_placeholders})
                ORDER BY timestamp_ts ASC
                """,
                tuple(condition_ids),
            ).fetchall()
    finally:
        conn.close()

    trades_by_condition: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in trade_rows:
        trades_by_condition[str(row["condition_id"])].append(row)

    signals: dict[str, dict[str, Any]] = {}
    for row in window_rows:
        slug = str(row.get("slug") or "").strip()
        market_row = markets_by_slug.get(slug)
        if market_row is None:
            continue
        signal = _build_lmsr_signal_for_window(
            row,
            market_row=market_row,
            trade_rows=trades_by_condition.get(str(market_row["condition_id"]), []),
        )
        if signal is not None:
            signals[slug] = signal

    diagnostics["available"] = True
    diagnostics["signal_windows"] = len(signals)
    latest_signal_timestamp = max(
        (
            _safe_int(signal.get("last_trade_timestamp"), default=0)
            for signal in signals.values()
            if _safe_int(signal.get("last_trade_timestamp"), default=0) > 0
        ),
        default=0,
    )
    if latest_signal_timestamp > 0:
        diagnostics["latest_signal_timestamp"] = latest_signal_timestamp
        diagnostics["latest_signal_at"] = _timestamp_to_iso_utc(latest_signal_timestamp)
    if not signals:
        diagnostics["missing_requirements"].append("lmsr_confirmation_windows_0")
    return signals, diagnostics


def _load_lmsr_confirmation_signals_from_reports(
    *,
    window_rows: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bundle_dir = _latest_btc5_bundle_dir()
    if bundle_dir is None:
        diagnostics["missing_requirements"].append("edge_discovery_bundle_missing")
        return {}, diagnostics

    markets_path = bundle_dir / "raw" / "edge_discovery_markets.csv"
    trades_path = bundle_dir / "raw" / "edge_discovery_trades.csv"
    if not markets_path.exists() or not trades_path.exists():
        missing_path = markets_path if not markets_path.exists() else trades_path
        diagnostics["missing_requirements"].append(f"edge_discovery_bundle_csv_missing:{missing_path}")
        return {}, diagnostics

    diagnostics["path"] = str(markets_path)
    slugs = {str(row.get("slug") or "").strip() for row in window_rows if row.get("slug")}
    diagnostics.update(_slug_window_bounds(slugs))

    market_rows = _parse_csv_rows(markets_path)
    available_slugs = {
        str(row.get("slug") or "").strip()
        for row in market_rows
        if str(row.get("slug") or "").strip().startswith("btc-updown-5m-")
    }
    diagnostics["available_btc5_slug_count"] = len(available_slugs)
    diagnostics["overlap_with_probe_slug_count"] = len(available_slugs & slugs)
    diagnostics.update(
        {f"market_{key}": value for key, value in _slug_window_bounds(available_slugs).items()}
    )

    latest_market = max(
        (
            row
            for row in market_rows
            if str(row.get("slug") or "").strip().startswith("btc-updown-5m-")
        ),
        key=lambda row: _safe_int(row.get("window_end_ts"), default=0),
        default=None,
    )
    if latest_market is not None:
        latest_market_ts = _safe_int(latest_market.get("window_end_ts"), default=0)
        if latest_market_ts > 0:
            diagnostics["latest_btc5_market_window_end_ts"] = latest_market_ts
            diagnostics["latest_btc5_market_window_end_at"] = _timestamp_to_iso_utc(latest_market_ts)
            diagnostics["latest_btc5_slug"] = str(latest_market.get("slug") or "").strip() or None

    markets_by_slug = {
        str(row.get("slug") or "").strip(): row
        for row in market_rows
        if str(row.get("slug") or "").strip() in slugs
    }
    diagnostics["matched_markets"] = len(markets_by_slug)
    if not markets_by_slug:
        diagnostics["available"] = True
        diagnostics["missing_requirements"].append("edge_market_overlap_0")
        return {}, diagnostics

    trade_rows = _parse_csv_rows(trades_path)
    trades_by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trade_rows:
        trades_by_condition[str(row.get("condition_id") or "")].append(row)

    signals: dict[str, dict[str, Any]] = {}
    for row in window_rows:
        slug = str(row.get("slug") or "").strip()
        market_row = markets_by_slug.get(slug)
        if market_row is None:
            continue
        signal = _build_lmsr_signal_for_window(
            row,
            market_row=market_row,
            trade_rows=trades_by_condition.get(str(market_row.get("condition_id") or ""), []),
        )
        if signal is not None:
            signals[slug] = signal

    diagnostics["available"] = True
    diagnostics["signal_windows"] = len(signals)
    latest_signal_timestamp = max(
        (_safe_int(signal.get("last_trade_timestamp"), default=0) for signal in signals.values()),
        default=0,
    )
    if latest_signal_timestamp > 0:
        diagnostics["latest_signal_timestamp"] = latest_signal_timestamp
        diagnostics["latest_signal_at"] = _timestamp_to_iso_utc(latest_signal_timestamp)
    if diagnostics["missing_requirements"]:
        diagnostics["missing_requirements"].append(f"edge_discovery_db_missing_local_path_using_bundle:{markets_path}")
    if not signals:
        diagnostics["missing_requirements"].append("lmsr_confirmation_windows_0")
    return signals, diagnostics


def _summarize_confirmation_source(
    windows: list[dict[str, Any]],
    *,
    source_key: str,
) -> dict[str, Any]:
    resolved_window_rows = len(windows)
    executed_window_rows = sum(1 for window in windows if window.get("base_executed"))
    source_window_rows = 0
    confirmed_window_rows = 0
    contradicted_window_rows = 0
    covered_executed_window_rows = 0
    confirmed_executed_window_rows = 0
    confirmed_good_trade_rows = 0
    confirmed_bad_trade_rows = 0
    suppressed_bad_window_rows = 0
    false_suppression_window_rows = 0
    false_confirmation_window_rows = 0
    covered_pnl = 0.0
    confirmed_pnl = 0.0
    false_suppression_cost_usd = 0.0
    false_confirmation_cost_usd = 0.0

    for window in windows:
        source = (window.get("sources") or {}).get(source_key) or {}
        if source.get("status") != "present":
            continue
        source_window_rows += 1
        relation = str(source.get("relation_to_base") or "unknown")
        if relation == "confirmed":
            confirmed_window_rows += 1
        elif relation == "contradicted":
            contradicted_window_rows += 1

        if not window.get("base_executed"):
            continue
        covered_executed_window_rows += 1
        pnl = _safe_float(window.get("base_pnl_usd"))
        covered_pnl += pnl
        good_trade = bool(window.get("base_good_trade"))
        if relation == "confirmed":
            confirmed_executed_window_rows += 1
            confirmed_pnl += pnl
            if good_trade:
                confirmed_good_trade_rows += 1
            else:
                confirmed_bad_trade_rows += 1
                false_confirmation_window_rows += 1
                false_confirmation_cost_usd += abs(min(pnl, 0.0))
        elif relation == "contradicted":
            if good_trade:
                false_suppression_window_rows += 1
                false_suppression_cost_usd += max(pnl, 0.0)
            else:
                suppressed_bad_window_rows += 1

    covered_base_win_rate = (
        (confirmed_good_trade_rows + suppressed_bad_window_rows) / covered_executed_window_rows
        if covered_executed_window_rows > 0
        else None
    )
    # Recompute from covered executed windows to avoid counting only one relation branch.
    if covered_executed_window_rows > 0:
        covered_good_trade_rows = sum(
            1
            for window in windows
            if window.get("base_executed")
            and (window.get("sources") or {}).get(source_key, {}).get("status") == "present"
            and window.get("base_good_trade") is True
        )
        covered_base_win_rate = covered_good_trade_rows / covered_executed_window_rows
    confirmed_win_rate = (
        confirmed_good_trade_rows / confirmed_executed_window_rows
        if confirmed_executed_window_rows > 0
        else None
    )
    covered_base_avg_pnl_usd = (
        covered_pnl / covered_executed_window_rows
        if covered_executed_window_rows > 0
        else None
    )
    confirmed_avg_pnl_usd = (
        confirmed_pnl / confirmed_executed_window_rows
        if confirmed_executed_window_rows > 0
        else None
    )
    confirmation_lift_win_rate = (
        confirmed_win_rate - covered_base_win_rate
        if confirmed_win_rate is not None and covered_base_win_rate is not None
        else None
    )
    confirmation_lift_avg_pnl_usd = (
        confirmed_avg_pnl_usd - covered_base_avg_pnl_usd
        if confirmed_avg_pnl_usd is not None and covered_base_avg_pnl_usd is not None
        else None
    )
    contradiction_rate = (
        contradicted_window_rows / source_window_rows
        if source_window_rows > 0
        else None
    )
    missing_requirements: list[str] = []
    if source_window_rows < MIN_CONFIRMATION_SIGNAL_WINDOWS:
        missing_requirements.append(
            f"source_window_rows {source_window_rows} < required {MIN_CONFIRMATION_SIGNAL_WINDOWS}"
        )
    if covered_executed_window_rows < MIN_CONFIRMATION_EXECUTED_WINDOWS:
        missing_requirements.append(
            "covered_executed_window_rows "
            f"{covered_executed_window_rows} < required {MIN_CONFIRMATION_EXECUTED_WINDOWS}"
        )

    status = "ready" if not missing_requirements else "insufficient_data"
    resolved_window_coverage = (
        source_window_rows / resolved_window_rows if resolved_window_rows > 0 else None
    )
    executed_window_coverage = (
        covered_executed_window_rows / executed_window_rows if executed_window_rows > 0 else None
    )
    coverage_label = _confirmation_coverage_label(
        status=status,
        resolved_window_coverage=resolved_window_coverage,
        executed_window_coverage=executed_window_coverage,
    )
    strength_score = _confirmation_strength_score(
        status=status,
        resolved_window_coverage=resolved_window_coverage,
        executed_window_coverage=executed_window_coverage,
        confirmation_lift_avg_pnl_usd=confirmation_lift_avg_pnl_usd,
        confirmation_lift_win_rate=confirmation_lift_win_rate,
        confirmation_contradiction_penalty=contradiction_rate,
        false_suppression_cost_usd=false_suppression_cost_usd,
        false_confirmation_cost_usd=false_confirmation_cost_usd,
    )
    strength_label = _confirmation_strength_label(
        status=status,
        coverage_label=coverage_label,
        strength_score=strength_score,
    )

    return {
        "status": status,
        "source_window_rows": int(source_window_rows),
        "resolved_window_rows": int(resolved_window_rows),
        "executed_window_rows": int(executed_window_rows),
        "resolved_window_coverage": resolved_window_coverage,
        "executed_window_coverage": executed_window_coverage,
        "confirmed_window_rows": int(confirmed_window_rows),
        "contradicted_window_rows": int(contradicted_window_rows),
        "covered_executed_window_rows": int(covered_executed_window_rows),
        "confirmed_executed_window_rows": int(confirmed_executed_window_rows),
        "confirmed_good_trade_rows": int(confirmed_good_trade_rows),
        "confirmed_bad_trade_rows": int(confirmed_bad_trade_rows),
        "suppressed_bad_window_rows": int(suppressed_bad_window_rows),
        "false_suppression_window_rows": int(false_suppression_window_rows),
        "false_confirmation_window_rows": int(false_confirmation_window_rows),
        "false_suppression_cost_usd": round(false_suppression_cost_usd, 6),
        "false_confirmation_cost_usd": round(false_confirmation_cost_usd, 6),
        "covered_base_win_rate": covered_base_win_rate,
        "confirmed_win_rate": confirmed_win_rate,
        "confirmation_lift_win_rate": confirmation_lift_win_rate,
        "covered_base_avg_pnl_usd": covered_base_avg_pnl_usd,
        "confirmed_avg_pnl_usd": confirmed_avg_pnl_usd,
        "confirmation_lift_avg_pnl_usd": confirmation_lift_avg_pnl_usd,
        "confirmation_contradiction_penalty": contradiction_rate,
        "confirmation_coverage_label": coverage_label,
        "confirmation_strength_label": strength_label,
        "confirmation_strength_score": strength_score,
        "missing_requirements": missing_requirements,
    }


def build_btc_fast_window_confirmation_archive(
    *,
    btc5_probe_db_path: Path | None,
    wallet_db_path: Path | None,
    edge_db_path: Path | None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    base_rows, base_missing_requirements = _load_btc_fast_window_rows(btc5_probe_db_path)
    resolved_rows = [
        row
        for row in base_rows
        if _normalize_btc_direction(row.get("resolved_side")) is not None
    ]
    wallet_flow_signals, wallet_flow_diagnostics = _load_wallet_flow_confirmation_signals(
        wallet_db_path,
        slugs={str(row.get("slug") or "").strip() for row in resolved_rows if row.get("slug")},
    )
    lmsr_signals, lmsr_diagnostics = _load_lmsr_confirmation_signals(
        edge_db_path,
        window_rows=resolved_rows,
    )
    probe_slug_bounds = _slug_window_bounds(
        {str(row.get("slug") or "").strip() for row in resolved_rows if row.get("slug")}
    )

    windows: list[dict[str, Any]] = []
    for row in resolved_rows:
        slug = str(row.get("slug") or "").strip()
        base_direction = _normalize_btc_direction(row.get("direction"))
        resolved_side = _normalize_btc_direction(row.get("resolved_side"))
        order_status = str(row.get("order_status") or "").strip().lower()
        base_executed = order_status == "live_filled"
        won_value = row.get("won")
        won_flag: bool | None = None
        if won_value not in (None, ""):
            won_flag = bool(_safe_int(won_value))
        pnl_usd = _present_metric(row.get("pnl_usd"))
        if won_flag is None and pnl_usd is not None:
            if pnl_usd > 0:
                won_flag = True
            elif pnl_usd < 0:
                won_flag = False

        window_sources: dict[str, Any] = {}
        for source_key, signal_map in (
            ("wallet_flow", wallet_flow_signals),
            ("lmsr", lmsr_signals),
        ):
            signal = signal_map.get(slug)
            if not signal:
                continue
            relation = None
            if base_direction is not None and signal.get("direction") is not None:
                relation = (
                    "confirmed"
                    if signal["direction"] == base_direction
                    else "contradicted"
                )
            window_sources[source_key] = {
                **signal,
                "relation_to_base": relation,
            }

        windows.append(
            {
                "slug": slug,
                "window_start_ts": _safe_int(row.get("window_start_ts"), default=0),
                "window_end_ts": _safe_int(row.get("window_end_ts"), default=0),
                "decision_ts": _safe_int(row.get("decision_ts"), default=0),
                "base_direction": base_direction,
                "base_order_status": str(row.get("order_status") or ""),
                "base_order_price": _present_metric(row.get("order_price")),
                "base_trade_size_usd": _present_metric(row.get("trade_size_usd")),
                "base_filled": _safe_int(row.get("filled"), default=0),
                "base_executed": base_executed,
                "base_won": won_flag,
                "base_good_trade": won_flag if base_executed else None,
                "base_pnl_usd": pnl_usd,
                "resolved_side": resolved_side,
                "sources": window_sources,
            }
        )

    by_source = {
        source_key: _summarize_confirmation_source(windows, source_key=source_key)
        for source_key in BTC_FAST_WINDOW_SOURCES
    }
    latest_probe_decision_ts = max(
        (
            _safe_int(row.get("decision_ts") or row.get("window_end_ts"), default=0)
            for row in resolved_rows
            if _safe_int(row.get("decision_ts") or row.get("window_end_ts"), default=0) > 0
        ),
        default=0,
    )
    latest_probe_decision_at = _timestamp_to_iso_utc(latest_probe_decision_ts)
    source_diagnostics = {
        "wallet_flow": wallet_flow_diagnostics,
        "lmsr": lmsr_diagnostics,
    }
    fresh_sources: list[str] = []
    aging_sources: list[str] = []
    stale_sources: list[str] = []
    unknown_sources: list[str] = []
    source_gaps_hours: dict[str, float | None] = {}
    source_freshness: dict[str, str] = {}
    source_next_required_artifacts: list[str] = []
    source_input_paths = {
        "wallet_flow": wallet_db_path,
        "lmsr": edge_db_path,
    }
    for source_key in BTC_FAST_WINDOW_SOURCES:
        summary = by_source[source_key]
        diagnostics = source_diagnostics[source_key]
        latest_source_timestamp = _safe_int(diagnostics.get("latest_signal_timestamp"), default=0)
        if latest_source_timestamp <= 0:
            fallback_key = (
                "latest_btc5_trade_timestamp"
                if source_key == "wallet_flow"
                else "latest_btc5_market_window_end_ts"
            )
            latest_source_timestamp = _safe_int(diagnostics.get(fallback_key), default=0)
        latest_source_at = _timestamp_to_iso_utc(latest_source_timestamp)
        overlap_count = _safe_int(diagnostics.get("overlap_with_probe_slug_count"), 0)
        source_window_rows = _safe_int(summary.get("source_window_rows"), 0)
        gap_hours = _gap_hours(
            latest_ts=latest_probe_decision_ts if latest_probe_decision_ts > 0 else None,
            observed_ts=latest_source_timestamp if latest_source_timestamp > 0 else None,
        )
        freshness = (
            _freshness_label_for_gap_hours(gap_hours)
            if source_window_rows > 0 or overlap_count > 0
            else "unknown"
        )
        if freshness == "fresh":
            fresh_sources.append(source_key)
        elif freshness == "aging":
            aging_sources.append(source_key)
        elif freshness == "stale":
            stale_sources.append(source_key)
            source_path = source_input_paths.get(source_key)
            if source_path is not None:
                source_next_required_artifacts.append(str(source_path))
        else:
            unknown_sources.append(source_key)

        source_gaps_hours[source_key] = round(gap_hours, 4) if gap_hours is not None else None
        source_freshness[source_key] = freshness
        summary["latest_source_timestamp"] = latest_source_timestamp if latest_source_timestamp > 0 else None
        summary["latest_source_at"] = latest_source_at
        summary["source_gap_vs_probe_hours"] = source_gaps_hours[source_key]
        summary["source_freshness"] = freshness
        diagnostics["latest_source_timestamp"] = latest_source_timestamp if latest_source_timestamp > 0 else None
        diagnostics["latest_source_at"] = latest_source_at
        diagnostics["source_gap_vs_probe_hours"] = source_gaps_hours[source_key]
        diagnostics["source_freshness"] = freshness
        diagnostics["stale_vs_probe"] = freshness == "stale"

    ready_sources = [
        source_key
        for source_key, summary in by_source.items()
        if summary.get("status") == "ready"
    ]
    best_source_by_confirmation_lift = None
    confirmation_coverage_ratio = None
    confirmation_resolved_window_coverage = None
    confirmation_executed_window_coverage = None
    confirmation_false_suppression_cost_usd = None
    confirmation_false_confirmation_cost_usd = None
    confirmation_lift_avg_pnl_usd = None
    confirmation_lift_win_rate = None
    confirmation_contradiction_penalty = None
    confirmation_coverage_label = "missing"
    confirmation_strength_label = "missing"
    confirmation_strength_score = 0.0
    confirmation_freshness_label = (
        "fresh"
        if fresh_sources
        else "aging"
        if aging_sources
        else "stale"
        if stale_sources
        else "missing"
    )
    confirmation_next_required_artifact = None
    if ready_sources:
        best_source_by_confirmation_lift = max(
            ready_sources,
            key=lambda source_key: (
                _safe_float(
                    (by_source[source_key].get("confirmation_lift_avg_pnl_usd")),
                    float("-inf"),
                ),
                _safe_float(
                    (by_source[source_key].get("confirmation_lift_win_rate")),
                    float("-inf"),
                ),
                -_safe_float(
                    (by_source[source_key].get("confirmation_contradiction_penalty")),
                    1.0,
                ),
            ),
        )
        best_summary = by_source[best_source_by_confirmation_lift]
        # Keep the ranking inputs coherent by carrying metrics from the same
        # source that won the confirmation-lift comparison.
        confirmation_resolved_window_coverage = best_summary.get("resolved_window_coverage")
        confirmation_executed_window_coverage = best_summary.get("executed_window_coverage")
        confirmation_coverage_ratio = confirmation_resolved_window_coverage
        confirmation_false_suppression_cost_usd = best_summary.get("false_suppression_cost_usd")
        confirmation_false_confirmation_cost_usd = best_summary.get("false_confirmation_cost_usd")
        confirmation_lift_avg_pnl_usd = best_summary.get("confirmation_lift_avg_pnl_usd")
        confirmation_lift_win_rate = best_summary.get("confirmation_lift_win_rate")
        confirmation_contradiction_penalty = best_summary.get("confirmation_contradiction_penalty")
        confirmation_coverage_label = str(
            best_summary.get("confirmation_coverage_label") or "missing"
        )
        confirmation_strength_label = str(
            best_summary.get("confirmation_strength_label") or "missing"
        )
        confirmation_strength_score = round(
            _safe_float(best_summary.get("confirmation_strength_score"), 0.0),
            6,
        )
        best_source_freshness = source_freshness.get(best_source_by_confirmation_lift)
        if best_source_freshness in {"fresh", "aging", "stale"}:
            confirmation_freshness_label = best_source_freshness

    if not resolved_rows:
        confirmation_next_required_artifact = (
            str(btc5_probe_db_path) if btc5_probe_db_path is not None else None
        )
    elif source_next_required_artifacts:
        confirmation_next_required_artifact = source_next_required_artifacts[0]
    elif not ready_sources:
        if wallet_db_path is not None:
            confirmation_next_required_artifact = str(wallet_db_path)
        elif edge_db_path is not None:
            confirmation_next_required_artifact = str(edge_db_path)

    missing_requirements = list(base_missing_requirements)
    if not resolved_rows:
        missing_requirements.append("resolved_btc_fast_window_rows_0")
    for source_key in BTC_FAST_WINDOW_SOURCES:
        for item in by_source[source_key].get("missing_requirements", []):
            missing_requirements.append(f"{source_key}:{item}")
        if source_freshness.get(source_key) == "stale":
            gap_hours = source_gaps_hours.get(source_key)
            if gap_hours is not None:
                missing_requirements.append(
                    f"{source_key}:source_stale_vs_probe_gap_hours:{gap_hours:.4f}"
                )
        if source_key == "wallet_flow":
            overlap_count = _safe_int(wallet_flow_diagnostics.get("overlap_with_probe_slug_count"), 0)
            source_min = wallet_flow_diagnostics.get("window_start_ts_min")
            source_max = wallet_flow_diagnostics.get("window_start_ts_max")
        else:
            overlap_count = _safe_int(lmsr_diagnostics.get("overlap_with_probe_slug_count"), 0)
            source_min = lmsr_diagnostics.get("market_window_start_ts_min")
            source_max = lmsr_diagnostics.get("market_window_start_ts_max")
        probe_min = probe_slug_bounds.get("window_start_ts_min")
        probe_max = probe_slug_bounds.get("window_start_ts_max")
        if (
            overlap_count == 0
            and by_source[source_key].get("source_window_rows", 0) == 0
            and probe_min is not None
            and probe_max is not None
            and source_min is not None
            and source_max is not None
        ):
            missing_requirements.append(
                f"{source_key}:join_key_window_mismatch:probe[{probe_min}-{probe_max}]"
                f":source[{source_min}-{source_max}]"
            )

    return {
        "schema": BTC_FAST_WINDOW_CONFIRMATION_ARCHIVE_SCHEMA,
        "generated_at": generated_at,
        "status": "ready" if ready_sources else "insufficient_data",
        "requirements": {
            "min_signal_windows_per_source": MIN_CONFIRMATION_SIGNAL_WINDOWS,
            "min_covered_executed_windows_per_source": MIN_CONFIRMATION_EXECUTED_WINDOWS,
            "supported_sources": list(BTC_FAST_WINDOW_SOURCES),
        },
        "inputs": {
            "btc5_probe_db_path": str(btc5_probe_db_path) if btc5_probe_db_path is not None else None,
            "wallet_db_path": str(wallet_db_path) if wallet_db_path is not None else None,
            "edge_db_path": str(edge_db_path) if edge_db_path is not None else None,
        },
        "counts": {
            "resolved_window_rows": len(windows),
            "executed_window_rows": sum(1 for window in windows if window.get("base_executed")),
            "ready_sources": len(ready_sources),
        },
        "source_diagnostics": source_diagnostics,
        "summary": {
            "ready_sources": ready_sources,
            "best_source_by_confirmation_lift": best_source_by_confirmation_lift,
            "latest_probe_decision_ts": latest_probe_decision_ts if latest_probe_decision_ts > 0 else None,
            "latest_probe_decision_at": latest_probe_decision_at,
            "fresh_sources": fresh_sources,
            "aging_sources": aging_sources,
            "stale_sources": stale_sources,
            "unknown_sources": unknown_sources,
            "source_gap_vs_probe_hours": source_gaps_hours,
            "probe_slug_bounds": probe_slug_bounds,
            "confirmation_freshness_label": confirmation_freshness_label,
            "confirmation_next_required_artifact": confirmation_next_required_artifact,
            "confirmation_coverage_ratio": confirmation_coverage_ratio,
            "confirmation_resolved_window_coverage": confirmation_resolved_window_coverage,
            "confirmation_executed_window_coverage": confirmation_executed_window_coverage,
            "confirmation_false_suppression_cost_usd": confirmation_false_suppression_cost_usd,
            "confirmation_false_confirmation_cost_usd": confirmation_false_confirmation_cost_usd,
            "confirmation_lift_avg_pnl_usd": confirmation_lift_avg_pnl_usd,
            "confirmation_lift_win_rate": confirmation_lift_win_rate,
            "confirmation_contradiction_penalty": confirmation_contradiction_penalty,
            "confirmation_coverage_label": confirmation_coverage_label,
            "confirmation_strength_label": confirmation_strength_label,
            "confirmation_strength_score": confirmation_strength_score,
        },
        "missing_requirements": _dedupe_preserve_order(missing_requirements),
        "by_source": by_source,
        "windows": windows,
    }


def _empty_bucket() -> dict[str, Any]:
    return {
        "total_trades": 0,
        "resolved_trades": 0,
        "wins": 0,
        "losses": 0,
        "unresolved_trades": 0,
        "total_pnl": 0.0,
        "avg_edge": 0.0,
        "avg_confidence": 0.0,
        "solo_trades": 0,
        "confirmed_trades": 0,
        "last_trade_at": None,
        "_edge_sum": 0.0,
        "_confidence_sum": 0.0,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    total = int(bucket["total_trades"])
    resolved = int(bucket["resolved_trades"])
    wins = int(bucket["wins"])
    losses = int(bucket["losses"])
    avg_edge = bucket["_edge_sum"] / total if total > 0 else 0.0
    avg_confidence = bucket["_confidence_sum"] / total if total > 0 else 0.0
    total_pnl = round(_safe_float(bucket["total_pnl"]), 6)
    return {
        "total_trades": total,
        "resolved_trades": resolved,
        "wins": wins,
        "losses": losses,
        "unresolved_trades": int(bucket["unresolved_trades"]),
        "win_rate": (wins / resolved) if resolved > 0 else None,
        "total_pnl": total_pnl,
        "avg_pnl_resolved": (total_pnl / resolved) if resolved > 0 else None,
        "avg_edge": round(avg_edge, 6),
        "avg_confidence": round(avg_confidence, 6),
        "solo_trades": int(bucket["solo_trades"]),
        "confirmed_trades": int(bucket["confirmed_trades"]),
        "last_trade_at": bucket["last_trade_at"],
    }


def _update_bucket(bucket: dict[str, Any], row: dict[str, Any], components: list[str]) -> None:
    bucket["total_trades"] += 1
    bucket["_edge_sum"] += _safe_float(row.get("edge"))
    bucket["_confidence_sum"] += _safe_float(row.get("confidence"))
    if len(components) > 1:
        bucket["confirmed_trades"] += 1
    else:
        bucket["solo_trades"] += 1

    timestamp = str(row.get("timestamp") or "")
    if timestamp and (bucket["last_trade_at"] is None or timestamp > bucket["last_trade_at"]):
        bucket["last_trade_at"] = timestamp

    outcome = str(row.get("outcome") or "").strip().lower()
    if outcome == "won":
        bucket["resolved_trades"] += 1
        bucket["wins"] += 1
    elif outcome == "lost":
        bucket["resolved_trades"] += 1
        bucket["losses"] += 1
    else:
        bucket["unresolved_trades"] += 1

    bucket["total_pnl"] += _safe_float(row.get("pnl"))


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _load_trade_rows(db_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not db_path.exists():
        return [], []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "trades"):
            return [], []

        columns = [row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()]
        selected_columns = []
        for column in (
            "timestamp",
            "market_id",
            "question",
            "direction",
            "edge",
            "confidence",
            "source",
            "source_combo",
            "source_components_json",
            "source_count",
            "outcome",
            "pnl",
        ):
            if column in columns:
                selected_columns.append(column)
            else:
                selected_columns.append(f"NULL AS {column}")

        rows = conn.execute(
            f"""
            SELECT
                {", ".join(selected_columns)}
            FROM trades
            ORDER BY timestamp ASC
            """
        ).fetchall()
        return [dict(row) for row in rows], columns
    finally:
        conn.close()


def _load_state_snapshot(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {
            "state_file_exists": False,
            "cycles_completed": 0,
            "total_trades": 0,
            "open_positions": 0,
            "trade_log_entries": 0,
            "trade_log_has_source_attribution": False,
        }

    payload = json.loads(state_path.read_text())
    trade_log = payload.get("trade_log") or []
    has_source_fields = all(
        isinstance(entry, dict)
        and "source" in entry
        and "source_combo" in entry
        and "source_components" in entry
        for entry in trade_log
    ) if trade_log else True
    return {
        "state_file_exists": True,
        "cycles_completed": int(payload.get("cycles_completed", 0) or 0),
        "total_trades": int(payload.get("total_trades", 0) or 0),
        "open_positions": len(payload.get("open_positions") or {}),
        "trade_log_entries": len(trade_log),
        "trade_log_has_source_attribution": has_source_fields,
    }


def _load_runtime_truth_trade_totals(path: Path | None = None) -> dict[str, Any]:
    runtime_truth_path = path or DEFAULT_RUNTIME_TRUTH_PATH
    if runtime_truth_path is None or not runtime_truth_path.exists():
        return {
            "available": False,
            "path": str(runtime_truth_path) if runtime_truth_path is not None else None,
            "total_trades": 0,
            "live_filled_rows": 0,
        }
    try:
        payload = json.loads(runtime_truth_path.read_text())
    except json.JSONDecodeError:
        return {
            "available": False,
            "path": str(runtime_truth_path),
            "total_trades": 0,
            "live_filled_rows": 0,
        }
    accounting = payload.get("accounting_reconciliation") or {}
    local_ledger = accounting.get("local_ledger_counts") or {}
    btc5_counts = accounting.get("btc_5min_maker_counts") or {}
    total_trades = max(
        _safe_int(local_ledger.get("total_trades"), default=0),
        _safe_int(btc5_counts.get("live_filled_rows"), default=0),
    )
    return {
        "available": True,
        "path": str(runtime_truth_path),
        "total_trades": total_trades,
        "live_filled_rows": _safe_int(btc5_counts.get("live_filled_rows"), default=0),
    }


def _decode_source_fields(row: dict[str, Any]) -> tuple[str, str, list[str], int]:
    raw_components = row.get("source_components_json")
    parsed_components: Any = raw_components
    if isinstance(raw_components, str) and raw_components.strip():
        try:
            parsed_components = json.loads(raw_components)
        except json.JSONDecodeError:
            parsed_components = raw_components

    components = list(
        normalize_source_components(
            parsed_components or row.get("source_combo") or row.get("source")
        )
    )
    primary = canonical_source_key(str(row.get("source") or ""))
    if primary == "unknown" and components:
        primary = components[0]
    if not components and primary != "unknown":
        components = [primary]

    combo = str(row.get("source_combo") or "").strip() or "+".join(components) or primary
    count = max(
        int(_safe_float(row.get("source_count"), 0)),
        len(components),
        1 if primary and primary != "unknown" else 0,
    )
    return primary, combo, components, count


def _recommend_wallet_flow(
    comparison: dict[str, Any],
    *,
    minimum_signal_sample: int,
) -> tuple[str, str]:
    status = comparison.get("status")
    if status != "ready":
        return (
            "collect_more_data",
            f"Need at least {minimum_signal_sample} wallet-flow and LLM trades plus resolved outcomes before comparing hit rate.",
        )

    delta = comparison.get("wallet_flow_any_win_rate_delta_vs_llm_only")
    if delta is None:
        return ("collect_more_data", "Wallet-flow cohort has not resolved enough trades to compare hit rate.")
    if delta > 0.02:
        return ("keep", f"Wallet flow is outperforming LLM-only by {delta:.2%} on resolved hit rate.")
    return (
        "demote_to_tiebreaker",
        f"Wallet flow is not clearing the required +2% hit-rate lift versus LLM-only (delta {delta:.2%}).",
    )


def _recommend_source(
    source_key: str,
    metrics: dict[str, Any],
    *,
    wallet_flow_comparison: dict[str, Any],
    minimum_signal_sample: int,
) -> tuple[str, str]:
    if source_key == "wallet_flow":
        return _recommend_wallet_flow(
            wallet_flow_comparison,
            minimum_signal_sample=minimum_signal_sample,
        )

    total_trades = int(metrics.get("total_trades", 0) or 0)
    resolved_trades = int(metrics.get("resolved_trades", 0) or 0)
    win_rate = metrics.get("win_rate")
    total_pnl = _safe_float(metrics.get("total_pnl"))

    if total_trades < minimum_signal_sample:
        return (
            "collect_more_data",
            f"Observed {total_trades} trades; need at least {minimum_signal_sample} for a source-level decision.",
        )
    if resolved_trades == 0:
        return ("collect_more_data", "Trades exist, but none have resolved yet.")
    if total_pnl > 0 and (win_rate or 0.0) >= 0.5:
        return ("keep", "Positive resolved P&L and non-negative hit rate.")
    if total_pnl < 0 and (win_rate or 0.0) < 0.5:
        return ("kill", "Negative resolved P&L with sub-50% hit rate.")
    return ("demote_to_tiebreaker", "Mixed evidence: keep collecting data without granting primary sizing.")


def _best_win_rate_entry(metrics_map: dict[str, dict[str, Any]], key_name: str) -> dict[str, Any] | None:
    ranked: list[tuple[float, int, float, str, dict[str, Any]]] = []
    for label, metrics in metrics_map.items():
        win_rate = metrics.get("win_rate")
        if win_rate is None:
            continue
        ranked.append(
            (
                _safe_float(win_rate, 0.0),
                int(metrics.get("resolved_trades", 0) or 0),
                _safe_float(metrics.get("total_pnl"), 0.0),
                str(label),
                metrics,
            )
        )
    if not ranked:
        return None
    best_win_rate, resolved_trades, total_pnl, label, metrics = max(ranked)
    return {
        key_name: label,
        "win_rate": best_win_rate,
        "resolved_trades": resolved_trades,
        "total_trades": int(metrics.get("total_trades", 0) or 0),
        "total_pnl": total_pnl,
    }


def _decision_readiness(
    *,
    recommendation: str,
    role: str,
) -> tuple[str, bool]:
    normalized_recommendation = str(recommendation or "").strip().lower()
    normalized_role = str(role or "").strip().lower()
    if normalized_role == "gate_only":
        return ("gate_only", False)
    if normalized_recommendation == "keep":
        return ("decision_eligible", True)
    if normalized_recommendation == "collect_more_data":
        return ("data_collection_only", False)
    if normalized_recommendation == "demote_to_tiebreaker":
        return ("tiebreaker_only", False)
    if normalized_recommendation == "kill":
        return ("disabled", False)
    return ("unknown", False)


def build_audit_payload(
    *,
    db_path: Path,
    state_path: Path,
    minimum_signal_sample: int = 50,
    btc5_probe_db_path: Path | None = None,
    wallet_db_path: Path | None = None,
    edge_db_path: Path | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows, db_columns = _load_trade_rows(db_path)
    state_snapshot = _load_state_snapshot(state_path)
    runtime_truth_trade_totals = _load_runtime_truth_trade_totals()
    attribution_ready = all(
        column in set(db_columns)
        for column in ("source", "source_combo", "source_components_json", "source_count")
    ) and state_snapshot["trade_log_has_source_attribution"]

    component_buckets = {key: _empty_bucket() for key in EXECUTION_SOURCES}
    primary_buckets: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    combo_buckets: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    cohort_buckets = {
        "wallet_flow_any": _empty_bucket(),
        "wallet_flow_only": _empty_bucket(),
        "llm_only": _empty_bucket(),
        "llm_and_wallet_flow": _empty_bucket(),
    }
    extra_sources: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)

    for row in rows:
        primary, combo, components, _count = _decode_source_fields(row)
        _update_bucket(primary_buckets[primary], row, components)
        _update_bucket(combo_buckets[combo], row, components)

        if "wallet_flow" in components:
            _update_bucket(cohort_buckets["wallet_flow_any"], row, components)
        if components == ["wallet_flow"]:
            _update_bucket(cohort_buckets["wallet_flow_only"], row, components)
        if components == ["llm"]:
            _update_bucket(cohort_buckets["llm_only"], row, components)
        if set(components) == {"llm", "wallet_flow"} and len(components) == 2:
            _update_bucket(cohort_buckets["llm_and_wallet_flow"], row, components)

        for component in components:
            if component in component_buckets:
                _update_bucket(component_buckets[component], row, components)
            else:
                _update_bucket(extra_sources[component], row, components)

    component_metrics = {
        key: _finalize_bucket(bucket)
        for key, bucket in component_buckets.items()
    }
    primary_metrics = {
        key: _finalize_bucket(bucket)
        for key, bucket in sorted(primary_buckets.items())
    }
    combo_metrics = {
        key: _finalize_bucket(bucket)
        for key, bucket in sorted(
            combo_buckets.items(),
            key=lambda item: (-int(item[1]["total_trades"]), item[0]),
        )
    }
    extra_metrics = {
        key: _finalize_bucket(bucket)
        for key, bucket in sorted(extra_sources.items())
    }
    cohort_metrics = {
        key: _finalize_bucket(bucket)
        for key, bucket in cohort_buckets.items()
    }

    wallet_flow_any = cohort_metrics["wallet_flow_any"]
    llm_only = cohort_metrics["llm_only"]
    comparison_status = "ready"
    comparison_reason = "comparison_ready"
    if wallet_flow_any["total_trades"] < minimum_signal_sample or llm_only["total_trades"] < minimum_signal_sample:
        comparison_status = "insufficient_data"
        comparison_reason = "minimum_signal_sample_not_met"
    elif wallet_flow_any["resolved_trades"] == 0 or llm_only["resolved_trades"] == 0:
        comparison_status = "awaiting_resolution"
        comparison_reason = "no_resolved_trades"

    wallet_flow_delta = None
    if comparison_status == "ready":
        wallet_flow_delta = (
            _safe_float(wallet_flow_any["win_rate"], 0.0) - _safe_float(llm_only["win_rate"], 0.0)
        )

    wallet_flow_comparison = {
        "status": comparison_status,
        "reason": comparison_reason,
        "minimum_signal_sample": minimum_signal_sample,
        "wallet_flow_any": wallet_flow_any,
        "wallet_flow_only": cohort_metrics["wallet_flow_only"],
        "llm_only": llm_only,
        "llm_and_wallet_flow": cohort_metrics["llm_and_wallet_flow"],
        "wallet_flow_any_win_rate": wallet_flow_any.get("win_rate"),
        "llm_only_win_rate": llm_only.get("win_rate"),
        "wallet_flow_any_win_rate_delta_vs_llm_only": wallet_flow_delta,
        "winner": (
            "wallet_flow"
            if wallet_flow_delta is not None and wallet_flow_delta > 0
            else "llm_only"
            if wallet_flow_delta is not None and wallet_flow_delta < 0
            else "tie"
            if wallet_flow_delta == 0
            else None
        ),
    }
    combined_sources = [value for key, value in combo_metrics.items() if "+" in str(key)]
    single_sources = [value for key, value in combo_metrics.items() if "+" not in str(key)]
    combined_vs_single: dict[str, Any] = {
        "status": "insufficient_data",
        "combined_sources_beat_single_source_lanes": None,
        "combined_best_win_rate": None,
        "single_best_win_rate": None,
        "winner": None,
    }
    combined_win_rates = [metrics.get("win_rate") for metrics in combined_sources if metrics.get("win_rate") is not None]
    single_win_rates = [metrics.get("win_rate") for metrics in single_sources if metrics.get("win_rate") is not None]
    if combined_win_rates and single_win_rates:
        combined_best = max(_safe_float(value, 0.0) for value in combined_win_rates)
        single_best = max(_safe_float(value, 0.0) for value in single_win_rates)
        combined_vs_single = {
            "status": "ready",
            "combined_sources_beat_single_source_lanes": combined_best > single_best,
            "combined_best_win_rate": combined_best,
            "single_best_win_rate": single_best,
            "winner": "combined" if combined_best > single_best else "single_source" if single_best > combined_best else "tie",
        }

    ranking_snapshot = {
        "best_component_source": _best_win_rate_entry(component_metrics, "source"),
        "best_source_combo": _best_win_rate_entry(combo_metrics, "source_combo"),
    }

    recommendations: dict[str, dict[str, Any]] = {}
    source_decision_readiness: dict[str, dict[str, Any]] = {}
    for source_key, meta in SOURCE_DECISION_SCOPE.items():
        if meta["role"] == "gate_only":
            decision_mode, decision_eligible = _decision_readiness(
                recommendation="keep_as_gate",
                role=meta["role"],
            )
            recommendations[source_key] = {
                "recommendation": "keep_as_gate",
                "reason": "VPIN/OFI is a microstructure filter, not an order-originating trade source; audit it from telemetry, not paper-trade attribution.",
                "role": meta["role"],
                "decision_mode": decision_mode,
                "decision_eligible": decision_eligible,
            }
            source_decision_readiness[source_key] = {
                "decision_mode": decision_mode,
                "decision_eligible": decision_eligible,
                "recommendation": "keep_as_gate",
                "role": meta["role"],
                "reason": recommendations[source_key]["reason"],
            }
            continue

        metrics = component_metrics.get(source_key, _finalize_bucket(_empty_bucket()))
        recommendation, reason = _recommend_source(
            source_key,
            metrics,
            wallet_flow_comparison=wallet_flow_comparison,
            minimum_signal_sample=minimum_signal_sample,
        )
        decision_mode, decision_eligible = _decision_readiness(
            recommendation=recommendation,
            role=meta["role"],
        )
        recommendations[source_key] = {
            "recommendation": recommendation,
            "reason": reason,
            "role": meta["role"],
            "metrics": metrics,
            "decision_mode": decision_mode,
            "decision_eligible": decision_eligible,
        }
        source_decision_readiness[source_key] = {
            "decision_mode": decision_mode,
            "decision_eligible": decision_eligible,
            "recommendation": recommendation,
            "role": meta["role"],
            "reason": reason,
        }

    decision_eligible_sources = sorted(
        key for key, value in source_decision_readiness.items() if bool(value.get("decision_eligible"))
    )
    data_collection_only_sources = sorted(
        key
        for key, value in source_decision_readiness.items()
        if str(value.get("decision_mode") or "") == "data_collection_only"
    )

    confirmation_archive = build_btc_fast_window_confirmation_archive(
        btc5_probe_db_path=btc5_probe_db_path,
        wallet_db_path=wallet_db_path,
        edge_db_path=edge_db_path,
    )
    confirmation_summary = confirmation_archive.get("summary") or {}
    wallet_flow_archive_confirmation_ready = (
        ((confirmation_archive.get("by_source") or {}).get("wallet_flow") or {}).get("status") == "ready"
    )
    lmsr_archive_confirmation_ready = (
        ((confirmation_archive.get("by_source") or {}).get("lmsr") or {}).get("status") == "ready"
    )
    wallet_flow_confirmation_ready = attribution_ready and wallet_flow_comparison["status"] == "ready"
    btc_fast_window_confirmation_ready = confirmation_archive.get("status") == "ready"
    stage_upgrade_blocking_checks = [
        check
        for check in (
            None if attribution_ready else "trade_attribution_not_ready",
            None if wallet_flow_comparison["status"] == "ready" else "wallet_flow_vs_llm_not_ready",
        )
        if check is not None
    ]
    stage_upgrade_support_status = "ready" if wallet_flow_confirmation_ready else "limited"
    capital_expansion_support_status = "ready" if attribution_ready else "blocked"
    confirmation_support_status = (
        "ready"
        if btc_fast_window_confirmation_ready
        else "limited"
        if attribution_ready
        else "blocked"
    )

    return {
        "generated_at": generated_at,
        "audit_scope": {
            "db_path": str(db_path),
            "state_path": str(state_path),
            "minimum_signal_sample": minimum_signal_sample,
            "btc5_probe_db_path": str(btc5_probe_db_path) if btc5_probe_db_path is not None else None,
            "wallet_db_path": str(wallet_db_path) if wallet_db_path is not None else None,
            "edge_db_path": str(edge_db_path) if edge_db_path is not None else None,
            "notes": [
                "Trade attribution is derived from the live bot's source/source_combo/source_components fields.",
                "Wallet flow is compared against LLM-only trades once both cohorts reach the minimum trade sample.",
                "VPIN/OFI is treated as a gate-only lane because it blocks execution rather than originating trades.",
                "BTC fast-window confirmation uses replayable BTC5 probe windows plus wallet-flow/LMSR evidence when local artifacts overlap.",
            ],
        },
        "state_snapshot": state_snapshot,
        "attribution_contract": {
            "db_file_exists": db_path.exists(),
            "trades_table_columns": db_columns,
            "db_has_source_attribution_columns": all(
                column in set(db_columns)
                for column in ("source", "source_combo", "source_components_json", "source_count")
            ),
            "trade_log_has_source_attribution": state_snapshot["trade_log_has_source_attribution"],
        },
        "trade_totals": {
            "total_trades": max(len(rows), _safe_int(runtime_truth_trade_totals.get("total_trades"), default=0)),
            "resolved_trades": sum(1 for row in rows if str(row.get("outcome") or "").lower() in {"won", "lost"}),
            "observed_primary_sources": sorted(primary_metrics),
            "observed_source_combos": list(combo_metrics.keys())[:10],
            "runtime_truth_fallback": runtime_truth_trade_totals,
        },
        "by_component_source": component_metrics,
        "by_primary_source": primary_metrics,
        "by_source_combo": combo_metrics,
        "observed_extra_sources": extra_metrics,
        "wallet_flow_vs_llm": wallet_flow_comparison,
        "combined_sources_vs_single_source": combined_vs_single,
        "ranking_snapshot": ranking_snapshot,
        "btc_fast_window_confirmation": confirmation_archive,
        "source_decision_readiness": source_decision_readiness,
        "capital_ranking_support": {
            "stale_threshold_hours": 6.0,
            "audit_generated_at": generated_at,
            "trade_attribution_ready": attribution_ready,
            "wallet_flow_vs_llm_status": wallet_flow_comparison["status"],
            "combined_sources_vs_single_source_status": combined_vs_single["status"],
            "best_component_source": (ranking_snapshot.get("best_component_source") or {}).get("source"),
            "best_source_combo": (ranking_snapshot.get("best_source_combo") or {}).get("source_combo"),
            "supports_capital_allocation": attribution_ready,
            "decision_eligible_sources": decision_eligible_sources,
            "data_collection_only_sources": data_collection_only_sources,
            "wallet_flow_confirmation_ready": wallet_flow_confirmation_ready,
            "wallet_flow_archive_confirmation_ready": wallet_flow_archive_confirmation_ready,
            "lmsr_archive_confirmation_ready": lmsr_archive_confirmation_ready,
            "btc_fast_window_confirmation_ready": btc_fast_window_confirmation_ready,
            "confirmation_support_status": confirmation_support_status,
            "confirmation_sources_ready": confirmation_summary.get("ready_sources") or [],
            "best_confirmation_source": confirmation_summary.get("best_source_by_confirmation_lift"),
            "confirmation_coverage_ratio": confirmation_summary.get("confirmation_coverage_ratio"),
            "confirmation_resolved_window_coverage": confirmation_summary.get(
                "confirmation_resolved_window_coverage"
            ),
            "confirmation_executed_window_coverage": confirmation_summary.get(
                "confirmation_executed_window_coverage"
            ),
            "confirmation_false_suppression_cost_usd": confirmation_summary.get(
                "confirmation_false_suppression_cost_usd"
            ),
            "confirmation_false_confirmation_cost_usd": confirmation_summary.get(
                "confirmation_false_confirmation_cost_usd"
            ),
            "confirmation_lift_avg_pnl_usd": confirmation_summary.get("confirmation_lift_avg_pnl_usd"),
            "confirmation_lift_win_rate": confirmation_summary.get("confirmation_lift_win_rate"),
            "confirmation_contradiction_penalty": confirmation_summary.get("confirmation_contradiction_penalty"),
            "confirmation_coverage_label": confirmation_summary.get("confirmation_coverage_label"),
            "confirmation_freshness_label": confirmation_summary.get("confirmation_freshness_label"),
            "confirmation_fresh_sources": confirmation_summary.get("fresh_sources") or [],
            "confirmation_aging_sources": confirmation_summary.get("aging_sources") or [],
            "confirmation_stale_sources": confirmation_summary.get("stale_sources") or [],
            "confirmation_unknown_sources": confirmation_summary.get("unknown_sources") or [],
            "confirmation_source_gap_vs_probe_hours": confirmation_summary.get(
                "source_gap_vs_probe_hours"
            ),
            "confirmation_latest_probe_decision_at": confirmation_summary.get(
                "latest_probe_decision_at"
            ),
            "confirmation_next_required_artifact": confirmation_summary.get(
                "confirmation_next_required_artifact"
            ),
            "confirmation_strength_label": confirmation_summary.get("confirmation_strength_label"),
            "confirmation_strength_score": confirmation_summary.get("confirmation_strength_score"),
            "confirmation_blocking_checks": confirmation_archive.get("missing_requirements") or [],
            "capital_expansion_support_status": capital_expansion_support_status,
            "stage_upgrade_support_status": stage_upgrade_support_status,
            "stage_upgrade_blocking_checks": stage_upgrade_blocking_checks,
        },
        "recommendations": recommendations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "jj_trades.db",
        help="Path to the live trade SQLite database.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=PROJECT_ROOT / "jj_state.json",
        help="Path to jj_state.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports" / "signal_source_audit.json",
        help="Where to write the JSON audit report.",
    )
    parser.add_argument(
        "--minimum-signal-sample",
        type=int,
        default=50,
        help="Minimum trades per cohort before emitting a keep/demote decision.",
    )
    parser.add_argument(
        "--btc5-probe-db",
        type=Path,
        default=DEFAULT_BTC5_PROBE_DB_PATH,
        help="BTC5 probe SQLite path used for replayable fast-window confirmation analysis.",
    )
    parser.add_argument(
        "--wallet-db",
        type=Path,
        default=DEFAULT_WALLET_DB_PATH,
        help="Wallet-flow SQLite path used to build BTC fast-window confirmation evidence.",
    )
    parser.add_argument(
        "--edge-db",
        type=Path,
        default=DEFAULT_EDGE_DISCOVERY_DB_PATH,
        help="Edge-discovery SQLite path used to build LMSR replayable confirmation evidence.",
    )
    parser.add_argument(
        "--confirmation-output",
        type=Path,
        default=DEFAULT_CONFIRMATION_OUTPUT_PATH,
        help="Where to write the standalone BTC fast-window confirmation archive.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_audit_payload(
        db_path=args.db,
        state_path=args.state,
        minimum_signal_sample=max(1, int(args.minimum_signal_sample)),
        btc5_probe_db_path=args.btc5_probe_db,
        wallet_db_path=args.wallet_db,
        edge_db_path=args.edge_db,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True))
    args.confirmation_output.parent.mkdir(parents=True, exist_ok=True)
    args.confirmation_output.write_text(
        json.dumps(payload["btc_fast_window_confirmation"], indent=2, sort_keys=True)
    )
    print(f"Wrote signal source audit to {args.output}")
    print(f"Wrote BTC fast-window confirmation archive to {args.confirmation_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
