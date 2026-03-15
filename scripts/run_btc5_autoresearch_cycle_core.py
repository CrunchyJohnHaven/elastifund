#!/usr/bin/env python3
"""Run one BTC5 autoresearch cycle and optionally promote a better profile."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    GuardrailProfile,
    _safe_float,
    assemble_observed_rows,
    build_summary as build_global_summary,
)
from scripts.btc5_runtime_helpers import (  # noqa: E402
    delta_bucket as _shared_delta_bucket,
    parse_env_file as _shared_parse_env_file,
    price_bucket as _shared_price_bucket,
)
from scripts.btc5_regime_policy_lab import build_summary as build_regime_policy_summary  # noqa: E402
from scripts.btc5_autoresearch_report import render_cycle_markdown  # noqa: E402
from scripts.btc5_market_policy_frontier import build_frontier_report  # noqa: E402
from scripts.btc5_policy_benchmark import (  # noqa: E402
    DEFAULT_MARKET_LATEST_JSON,
    DEFAULT_MARKET_POLICY_HANDOFF,
    policy_loss_from_candidate,
    runtime_package_hash,
    runtime_package_id,
)
from infra.fast_json import loads as fast_loads  # noqa: E402
from scripts.research_artifacts import (  # noqa: E402
    utc_now as _shared_utc_now,
    utc_stamp as _shared_utc_stamp,
    write_versioned_cycle_reports as _shared_write_versioned_cycle_reports,
)
from scripts.research_cli import add_mode_argument  # noqa: E402
from scripts.research_runtime import cap_for_mode, load_json_dict, normalize_mode  # noqa: E402
from infra.fast_json import write_text_atomic  # noqa: E402


DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_REPORT_DIR = Path("reports/btc5_autoresearch")
DEFAULT_SERVICE_NAME = "btc-5min-maker.service"
DEFAULT_HYPOTHESIS_SUMMARY = Path("reports/btc5_hypothesis_lab/summary.json")
DEFAULT_REGIME_POLICY_SUMMARY = Path("reports/btc5_regime_policy_lab/summary.json")
DEFAULT_CURRENT_PROBE_LATEST = Path("reports/btc5_autoresearch_current_probe/latest.json")
DEFAULT_RUNTIME_TRUTH = Path("reports/runtime_truth_latest.json")
DEFAULT_FRONTIER_LATEST = Path("reports/btc5_market_policy_frontier/latest.json")
DEFAULT_SEMANTIC_DEDUP_INDEX = Path("reports/btc5_autoresearch/semantic_dedup_index.json")
DEFAULT_AUTORESEARCH_CYCLES_JSONL = Path("reports/autoresearch_cycles.jsonl")
DEFAULT_FILL_FEEDBACK_STATE = Path("state/btc5_autoresearch_feedback_state.json")
LIVE_STAGE_MAX_TRADE_USD = {1: 10.0, 2: 20.0, 3: 50.0}
SHADOW_TRADE_SIZES_USD = (100.0, 300.0)
PROBE_STALE_HOURS = 6.0
PROBE_HARD_STALE_HOURS = 12.0
FRONTIER_STALE_HOURS = 6.0
FRESH_PROBE_POLICY_LOSS_PENALTY = 500.0
STALE_PROBE_POLICY_LOSS_PENALTY = 100.0
ANALYZE_MAX_PATHS = 600
ANALYZE_MAX_TOP_GRID_CANDIDATES = 3
ANALYZE_MAX_REGIME_COMPOSED_CANDIDATES = 24


def _now_utc() -> datetime:
    return _shared_utc_now()


def _stamp() -> str:
    return _shared_utc_stamp()


def _load_env_file(path: Path) -> dict[str, str]:
    return _shared_parse_env_file(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    return load_json_dict(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def _parse_iso_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _confidence_rank(label: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(label).strip().lower(), 0)


def _deploy_rank(label: str) -> int:
    return {"promote": 3, "shadow_only": 2, "hold": 1}.get(str(label).strip().lower(), 0)


def _confidence_label_from_rank(rank: int) -> str:
    if rank >= 3:
        return "high"
    if rank == 2:
        return "medium"
    return "low"


def _deploy_label_from_rank(rank: int) -> str:
    if rank >= 3:
        return "promote"
    if rank == 2:
        return "shadow_only"
    return "hold"


def _legacy_candidate_class(label: Any) -> str:
    return {
        "promote": "promote",
        "live_candidate": "promote",
        "hold_current": "hold_current",
        "probe_only": "probe_only",
        "shadow_only": "probe_only",
        "suppress_cluster": "suppress_cluster",
        "suppress": "suppress_cluster",
    }.get(str(label or "").strip().lower(), "")


def _package_set_label(label: Any) -> str:
    return {
        "promote": "live_candidate",
        "live_candidate": "live_candidate",
        "hold_current": "hold_current",
        "probe_only": "shadow_only",
        "shadow_only": "shadow_only",
        "suppress_cluster": "suppress",
        "suppress": "suppress",
    }.get(str(label or "").strip().lower(), "")


def _package_set_rank(label: Any) -> int:
    return {
        "live_candidate": 3,
        "hold_current": 2,
        "shadow_only": 1,
        "suppress": 0,
    }.get(_package_set_label(label), -1)


def _candidate_class_rank(label: Any) -> int:
    return _package_set_rank(label)


def _evidence_band_from_validation_rows(rows: int) -> str:
    if int(rows) >= 16:
        return "validated"
    if int(rows) >= 8:
        return "candidate"
    return "exploratory"


def _price_bucket(order_price: Any) -> str:
    return _shared_price_bucket(order_price)


def _delta_bucket(abs_delta: Any) -> str:
    return _shared_delta_bucket(abs_delta)


def _row_timestamp(row: dict[str, Any]) -> datetime | None:
    for raw in (
        row.get("updated_at"),
        row.get("created_at"),
    ):
        parsed = _parse_iso_timestamp(raw)
        if parsed is not None:
            return parsed
    ts = int(_safe_float(row.get("window_start_ts"), 0.0) or 0)
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _recent_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    predicate: Any = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if callable(predicate) and not predicate(row):
            continue
        filtered.append(row)
    filtered.sort(key=lambda row: _row_timestamp(row) or datetime.fromtimestamp(0, tz=timezone.utc))
    return filtered[-max(1, int(limit)) :]


def _mix_summary(rows: list[dict[str, Any]], *, labeler: Any) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    total = len(rows)
    for row in rows:
        label = str(labeler(row) or "unknown")
        bucket = buckets.setdefault(label, {"label": label, "rows": 0, "pnl_usd": 0.0})
        bucket["rows"] = int(bucket["rows"]) + 1
        bucket["pnl_usd"] = _safe_float(bucket["pnl_usd"], 0.0) + _safe_float(row.get("pnl_usd"), 0.0)
    ranked = sorted(
        (
            {
                "label": label,
                "rows": int(bucket.get("rows") or 0),
                "ratio": round((int(bucket.get("rows") or 0) / float(total)), 4) if total else 0.0,
                "pnl_usd": round(_safe_float(bucket.get("pnl_usd"), 0.0), 4),
            }
            for label, bucket in buckets.items()
        ),
        key=lambda item: (
            int(item.get("rows") or 0),
            _safe_float(item.get("pnl_usd"), 0.0),
            str(item.get("label") or ""),
        ),
        reverse=True,
    )
    return {
        "sample_size_rows": total,
        "buckets": ranked,
        "dominant_label": ranked[0]["label"] if ranked else None,
    }


def _mix_signal_score(
    mix_summary: dict[str, Any] | None,
    *,
    positive_scale: float,
    negative_scale: float,
    reason_prefix: str,
) -> tuple[float, list[str]]:
    summary = mix_summary if isinstance(mix_summary, dict) else {}
    buckets = summary.get("buckets") if isinstance(summary.get("buckets"), list) else []
    if not buckets:
        return 0.0, [f"{reason_prefix}_mix_missing"]
    dominant = buckets[0] if isinstance(buckets[0], dict) else {}
    ratio = max(0.0, min(1.0, _safe_float(dominant.get("ratio"), 0.0)))
    label = str(dominant.get("label") or "unknown")
    pnl_usd = _safe_float(dominant.get("pnl_usd"), 0.0)
    if pnl_usd > 0.0:
        return round(min(positive_scale, positive_scale * max(0.25, ratio)), 4), [
            f"{reason_prefix}_dominant_positive:{label}"
        ]
    if pnl_usd < 0.0:
        return round(-min(negative_scale, negative_scale * max(0.25, ratio)), 4), [
            f"{reason_prefix}_dominant_negative:{label}"
        ]
    return 0.0, [f"{reason_prefix}_dominant_flat:{label}"]


def _normalized_loss_cluster_filters(
    hypothesis_summary: dict[str, Any] | None,
    regime_policy_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for source_name, summary in (
        ("hypothesis_lab", hypothesis_summary or {}),
        ("regime_policy_lab", regime_policy_summary or {}),
    ):
        for item in (summary.get("loss_cluster_filters") or []):
            if not isinstance(item, dict):
                continue
            key = (
                source_name,
                str(item.get("direction") or "UNKNOWN").upper(),
                str(item.get("session_name") or "unknown"),
                str(item.get("price_bucket") or "unknown"),
                str(item.get("delta_bucket") or "unknown"),
            )
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "source": source_name,
                    "filter_name": str(item.get("filter_name") or ""),
                    "direction": key[1],
                    "session_name": key[2],
                    "price_bucket": key[3],
                    "delta_bucket": key[4],
                    "severity": str(item.get("severity") or "medium"),
                    "filter_action": str(item.get("filter_action") or ""),
                    "revalidation_gate": str(item.get("revalidation_gate") or ""),
                }
            )
    return normalized


def _recent_loss_cluster_flags(
    rows: list[dict[str, Any]],
    *,
    loss_filters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for item in loss_filters:
        matched_rows: list[dict[str, Any]] = []
        for row in rows:
            direction = str(row.get("direction") or "UNKNOWN").strip().upper()
            session_name = str(row.get("session_name") or "unknown")
            price_bucket = _price_bucket(row.get("order_price"))
            delta_bucket = _delta_bucket(row.get("abs_delta") or row.get("delta"))
            if (
                direction == str(item.get("direction") or "UNKNOWN").upper()
                and session_name == str(item.get("session_name") or "unknown")
                and price_bucket == str(item.get("price_bucket") or "unknown")
                and delta_bucket == str(item.get("delta_bucket") or "unknown")
            ):
                matched_rows.append(row)
        if not matched_rows:
            continue
        matched_live_fills = [
            row
            for row in matched_rows
            if str(row.get("order_status") or "").strip().lower() == "live_filled"
        ]
        flags.append(
            {
                "source": str(item.get("source") or ""),
                "filter_name": str(item.get("filter_name") or ""),
                "direction": str(item.get("direction") or "UNKNOWN").upper(),
                "session_name": str(item.get("session_name") or "unknown"),
                "price_bucket": str(item.get("price_bucket") or "unknown"),
                "delta_bucket": str(item.get("delta_bucket") or "unknown"),
                "severity": str(item.get("severity") or "medium"),
                "matched_rows": len(matched_rows),
                "matched_live_filled_rows": len(matched_live_fills),
                "matched_negative_live_filled_rows": sum(
                    1 for row in matched_live_fills if _safe_float(row.get("pnl_usd"), 0.0) < 0.0
                ),
                "recent_pnl_usd": round(
                    sum(_safe_float(row.get("pnl_usd"), 0.0) for row in matched_live_fills),
                    4,
                ),
                "filter_action": str(item.get("filter_action") or ""),
                "revalidation_gate": str(item.get("revalidation_gate") or ""),
            }
        )
    flags.sort(
        key=lambda item: (
            int(item.get("matched_negative_live_filled_rows") or 0),
            int(item.get("matched_rows") or 0),
            -_safe_float(item.get("recent_pnl_usd"), 0.0),
        ),
        reverse=True,
    )
    return flags


def _stage_readiness_tags(
    *,
    trailing_windows: dict[str, dict[str, float]],
    live_fill_freshness_hours: float | None,
    recent_order_failed_rate: float,
    recent_loss_cluster_flags: list[dict[str, Any]],
    validation_live_filled_rows_delta: int,
    package_missing_evidence: list[str],
    decision: dict[str, Any],
) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    not_ready: list[str] = []
    trailing_12 = trailing_windows.get("trailing_12") or {}
    trailing_40 = trailing_windows.get("trailing_40") or {}
    trailing_120 = trailing_windows.get("trailing_120") or {}
    if live_fill_freshness_hours is not None and live_fill_freshness_hours <= PROBE_STALE_HOURS:
        ready.append("live_fills_fresh_lte_6h")
    else:
        not_ready.append("live_fills_stale_gt_6h")
    if bool(trailing_12.get("net_positive")):
        ready.append("trailing_12_live_filled_positive")
    else:
        not_ready.append("trailing_12_live_filled_non_positive")
    if bool(trailing_40.get("net_positive")):
        ready.append("trailing_40_live_filled_positive")
    else:
        not_ready.append("trailing_40_live_filled_non_positive")
    if bool(trailing_120.get("net_positive")):
        ready.append("trailing_120_live_filled_positive")
    else:
        not_ready.append("trailing_120_live_filled_non_positive")
    if recent_order_failed_rate < 0.25:
        ready.append("recent_order_failed_rate_below_0.25")
    else:
        not_ready.append("recent_order_failed_rate_above_0.25")
    if validation_live_filled_rows_delta > 0:
        ready.append("validation_rows_growing")
    else:
        not_ready.append("validation_rows_flat")
    if recent_loss_cluster_flags:
        not_ready.append("recent_loss_cluster_flags_present")
    else:
        ready.append("no_recent_loss_cluster_flags")
    if str(decision.get("action") or "").strip().lower() == "promote":
        ready.append("candidate_scoring_promote_ready")
    else:
        not_ready.append("candidate_scoring_not_promote_ready")
    for reason in package_missing_evidence:
        not_ready.append(str(reason))
    return ready, not_ready


def _probe_ranking_inputs(current_probe: dict[str, Any]) -> dict[str, Any]:
    trailing_windows = (
        current_probe.get("trailing_live_filled_windows")
        if isinstance(current_probe.get("trailing_live_filled_windows"), dict)
        else {}
    )
    probe_freshness_hours = _safe_float(current_probe.get("probe_freshness_hours"), 9999.0)
    live_fill_freshness_hours = _safe_float(current_probe.get("live_fill_freshness_hours"), 9999.0)
    validation_delta = int(_safe_float(current_probe.get("validation_live_filled_rows_delta"), 0.0) or 0)
    live_fill_delta = int(_safe_float(current_probe.get("live_filled_rows_delta"), 0.0) or 0)
    order_failed_rate = _safe_float(current_probe.get("recent_order_failed_rate"), 0.0)
    cluster_count = len(current_probe.get("recent_loss_cluster_flags") or [])
    trailing_12 = trailing_windows.get("trailing_12") if isinstance(trailing_windows.get("trailing_12"), dict) else {}
    trailing_40 = trailing_windows.get("trailing_40") if isinstance(trailing_windows.get("trailing_40"), dict) else {}
    trailing_120 = trailing_windows.get("trailing_120") if isinstance(trailing_windows.get("trailing_120"), dict) else {}
    direction_mix = current_probe.get("recent_direction_mix") if isinstance(current_probe.get("recent_direction_mix"), dict) else {}
    price_mix = current_probe.get("recent_price_bucket_mix") if isinstance(current_probe.get("recent_price_bucket_mix"), dict) else {}

    bonus = 0.0
    penalty = 0.0
    reasons: list[str] = []

    if probe_freshness_hours <= 1.0:
        bonus += 12.0
        reasons.append("probe_fresh_lte_1h")
    elif probe_freshness_hours <= PROBE_STALE_HOURS:
        bonus += 6.0
        reasons.append("probe_fresh_lte_6h")
    elif probe_freshness_hours > PROBE_HARD_STALE_HOURS:
        penalty += min(42.0, (probe_freshness_hours - PROBE_HARD_STALE_HOURS) * 4.0 + 18.0)
        reasons.append("probe_stale_gt_12h")
    else:
        penalty += min(24.0, (probe_freshness_hours - PROBE_STALE_HOURS) * 3.0 + 8.0)
        reasons.append("probe_stale_gt_6h")

    if live_fill_freshness_hours <= 1.0:
        bonus += 10.0
        reasons.append("live_fills_fresh_lte_1h")
    elif live_fill_freshness_hours <= PROBE_STALE_HOURS:
        bonus += 5.0
        reasons.append("live_fills_fresh_lte_6h")
    elif live_fill_freshness_hours > PROBE_HARD_STALE_HOURS:
        penalty += min(32.0, (live_fill_freshness_hours - PROBE_HARD_STALE_HOURS) * 3.0 + 12.0)
        reasons.append("live_fills_stale_gt_12h")
    else:
        penalty += min(20.0, (live_fill_freshness_hours - PROBE_STALE_HOURS) * 2.5 + 6.0)
        reasons.append("live_fills_stale_gt_6h")

    if validation_delta > 0:
        bonus += min(24.0, 8.0 + (float(validation_delta) * 4.0))
        reasons.append("validation_rows_growing")
    else:
        penalty += 18.0
        reasons.append("validation_growth_stalled")

    if live_fill_delta > 0:
        bonus += min(15.0, 4.0 + (float(live_fill_delta) * 2.5))
        reasons.append("new_live_fills_arrived")

    if bool(trailing_12.get("net_positive")):
        bonus += 14.0
        reasons.append("trailing_12_positive")
    else:
        penalty += 18.0
        reasons.append("trailing_12_non_positive")
    if bool(trailing_40.get("net_positive")):
        bonus += 10.0
        reasons.append("trailing_40_positive")
    else:
        penalty += 12.0
        reasons.append("trailing_40_non_positive")
    if bool(trailing_120.get("net_positive")):
        bonus += 6.0
        reasons.append("trailing_120_positive")
    else:
        penalty += 6.0
        reasons.append("trailing_120_non_positive")

    if order_failed_rate <= 0.15:
        bonus += 6.0
        reasons.append("order_failed_rate_lte_0.15")
    elif order_failed_rate < 0.25:
        bonus += 2.0
        reasons.append("order_failed_rate_below_0.25")
    elif order_failed_rate >= 0.35:
        penalty += 18.0
        reasons.append("order_failed_rate_gte_0.35")
    else:
        penalty += 10.0
        reasons.append("order_failed_rate_gte_0.25")

    if cluster_count > 0:
        penalty += min(30.0, 10.0 * float(cluster_count))
        reasons.append("recent_loss_cluster_flags_present")
    else:
        bonus += 4.0
        reasons.append("no_recent_loss_cluster_flags")

    direction_signal, direction_reasons = _mix_signal_score(
        direction_mix,
        positive_scale=8.0,
        negative_scale=10.0,
        reason_prefix="direction",
    )
    price_signal, price_reasons = _mix_signal_score(
        price_mix,
        positive_scale=7.0,
        negative_scale=9.0,
        reason_prefix="price_bucket",
    )
    bonus += max(0.0, direction_signal) + max(0.0, price_signal)
    penalty += max(0.0, -direction_signal) + max(0.0, -price_signal)
    reasons.extend(direction_reasons)
    reasons.extend(price_reasons)

    ranking_score = round(bonus - penalty, 4)
    return {
        "trailing_fill_counts": {
            "trailing_12": int(_safe_float(trailing_12.get("fills"), 0.0) or 0),
            "trailing_40": int(_safe_float(trailing_40.get("fills"), 0.0) or 0),
            "trailing_120": int(_safe_float(trailing_120.get("fills"), 0.0) or 0),
        },
        "trailing_net_positive": {
            "trailing_12": bool(trailing_12.get("net_positive")),
            "trailing_40": bool(trailing_40.get("net_positive")),
            "trailing_120": bool(trailing_120.get("net_positive")),
        },
        "probe_freshness_hours": round(probe_freshness_hours, 4) if probe_freshness_hours < 9999.0 else None,
        "live_fill_freshness_hours": round(live_fill_freshness_hours, 4)
        if live_fill_freshness_hours < 9999.0
        else None,
        "validation_live_filled_rows_delta": int(validation_delta),
        "live_filled_rows_delta": int(live_fill_delta),
        "recent_order_failed_rate": round(order_failed_rate, 6),
        "recent_direction_mix": direction_mix,
        "recent_price_bucket_mix": price_mix,
        "recent_loss_cluster_flags": list(current_probe.get("recent_loss_cluster_flags") or []),
        "direction_mix_signal_score": round(direction_signal, 4),
        "price_bucket_mix_signal_score": round(price_signal, 4),
        "ranking_score": ranking_score,
        "selection_score_bonus": round(bonus, 4),
        "selection_score_penalty": round(penalty, 4),
        "ranking_reasons": reasons,
    }


def _current_probe_payload_fields(
    *,
    rows: list[dict[str, Any]],
    prior_probe_payload: dict[str, Any] | None,
    hypothesis_summary: dict[str, Any] | None,
    regime_policy_summary: dict[str, Any] | None,
    validation_live_filled_rows: int,
    package_missing_evidence: list[str],
    decision: dict[str, Any],
) -> dict[str, Any]:
    trailing = _live_fill_windows(rows)
    recent_rows = _recent_rows(rows, limit=40)
    recent_live_fills = _recent_rows(
        rows,
        limit=40,
        predicate=lambda row: str(row.get("order_status") or "").strip().lower() == "live_filled",
    )
    recent_priced_rows = [
        row
        for row in (recent_live_fills or recent_rows)
        if _safe_float(row.get("order_price"), 0.0) > 0.0
    ]
    recent_rows_for_price = recent_priced_rows or list(recent_live_fills or recent_rows)
    recent_drag = _execution_drag_context(recent_rows)
    latest_decision_timestamp = _row_timestamp(recent_rows[-1]) if recent_rows else None
    latest_live_fill_timestamp = _row_timestamp(recent_live_fills[-1]) if recent_live_fills else None
    probe_freshness_hours = (
        round(max(0.0, (_now_utc() - latest_decision_timestamp).total_seconds() / 3600.0), 4)
        if latest_decision_timestamp is not None
        else None
    )
    live_fill_freshness_hours = (
        round(max(0.0, (_now_utc() - latest_live_fill_timestamp).total_seconds() / 3600.0), 4)
        if latest_live_fill_timestamp is not None
        else None
    )
    prior_probe = prior_probe_payload or {}
    prior_current_probe = prior_probe.get("current_probe") if isinstance(prior_probe.get("current_probe"), dict) else {}
    prior_validation_rows = int(
        _safe_float(
            prior_probe.get("validation_live_filled_rows"),
            _safe_float(prior_current_probe.get("validation_live_filled_rows"), 0.0),
        )
        or 0
    )
    live_filled_row_count = sum(
        1
        for row in rows
        if str(row.get("order_status") or "").strip().lower() == "live_filled"
    )
    prior_live_filled_row_count = int(
        _safe_float(
            prior_current_probe.get("live_filled_row_count"),
            _safe_float(
                ((prior_probe.get("simulation_summary") or {}).get("input") or {}).get("live_filled_rows"),
                0.0,
            ),
        )
        or 0
    )
    validation_delta = int(validation_live_filled_rows) - prior_validation_rows
    live_fill_delta = int(live_filled_row_count) - prior_live_filled_row_count
    loss_filters = _normalized_loss_cluster_filters(hypothesis_summary, regime_policy_summary)
    recent_loss_flags = _recent_loss_cluster_flags(recent_rows, loss_filters=loss_filters)
    stage_ready_tags, stage_not_ready_tags = _stage_readiness_tags(
        trailing_windows=trailing,
        live_fill_freshness_hours=live_fill_freshness_hours,
        recent_order_failed_rate=_safe_float(recent_drag.get("order_failure_rate"), 0.0),
        recent_loss_cluster_flags=recent_loss_flags,
        validation_live_filled_rows_delta=validation_delta,
        package_missing_evidence=package_missing_evidence,
        decision=decision,
    )
    current_probe = {
        "contract_version": 3,
        "latest_decision_timestamp": latest_decision_timestamp.isoformat() if latest_decision_timestamp else None,
        "latest_live_fill_timestamp": latest_live_fill_timestamp.isoformat() if latest_live_fill_timestamp else None,
        "probe_freshness_hours": probe_freshness_hours,
        "live_fill_freshness_hours": live_fill_freshness_hours,
        "live_filled_row_count": int(live_filled_row_count),
        "live_filled_rows_delta": int(live_fill_delta),
        "validation_live_filled_rows": int(validation_live_filled_rows),
        "validation_live_filled_rows_delta": int(validation_delta),
        "validation_rows_flat": bool(validation_delta <= 0),
        "trailing_live_filled_windows": {
            key: trailing.get(key) or {}
            for key in ("trailing_12", "trailing_40", "trailing_120")
        },
        "trailing_12_live_filled_rows": int(_safe_float((trailing.get("trailing_12") or {}).get("fills"), 0.0) or 0),
        "trailing_40_live_filled_rows": int(_safe_float((trailing.get("trailing_40") or {}).get("fills"), 0.0) or 0),
        "trailing_120_live_filled_rows": int(_safe_float((trailing.get("trailing_120") or {}).get("fills"), 0.0) or 0),
        "trailing_12_live_filled_pnl_usd": round(_safe_float((trailing.get("trailing_12") or {}).get("pnl_usd"), 0.0), 4),
        "trailing_40_live_filled_pnl_usd": round(_safe_float((trailing.get("trailing_40") or {}).get("pnl_usd"), 0.0), 4),
        "trailing_120_live_filled_pnl_usd": round(_safe_float((trailing.get("trailing_120") or {}).get("pnl_usd"), 0.0), 4),
        "recent_window_rows": len(recent_rows),
        "recent_order_failed_count": int(recent_drag.get("order_failed_count") or 0),
        "recent_order_failed_rate": round(_safe_float(recent_drag.get("order_failure_rate"), 0.0), 6),
        "recent_direction_mix": _mix_summary(
            list(recent_live_fills or recent_rows),
            labeler=lambda row: str(row.get("direction") or "UNKNOWN").upper(),
        ),
        "recent_price_bucket_mix": _mix_summary(
            list(recent_rows_for_price),
            labeler=lambda row: _price_bucket(row.get("order_price")),
        ),
        "recent_loss_cluster_flags": recent_loss_flags,
        "stage_ready_reason_tags": stage_ready_tags,
        "stage_not_ready_reason_tags": stage_not_ready_tags,
    }
    ranking_inputs = _probe_ranking_inputs(current_probe)
    current_probe["ranking_inputs"] = ranking_inputs
    current_probe["ranking_score"] = ranking_inputs.get("ranking_score")
    current_probe["ranking_reasons"] = list(ranking_inputs.get("ranking_reasons") or [])
    return current_probe


def _probe_feedback_adjustment(
    *,
    package_confidence_label: str,
    deploy_recommendation: str,
    current_probe: dict[str, Any],
) -> dict[str, Any]:
    ranking_inputs = (
        current_probe.get("ranking_inputs")
        if isinstance(current_probe.get("ranking_inputs"), dict)
        else _probe_ranking_inputs(current_probe)
    )
    base_conf_rank = _confidence_rank(package_confidence_label)
    base_deploy_rank = _deploy_rank(deploy_recommendation)
    probe_freshness_hours = _safe_float(current_probe.get("probe_freshness_hours"), 9999.0)
    live_fill_freshness_hours = _safe_float(current_probe.get("live_fill_freshness_hours"), 9999.0)
    validation_delta = int(_safe_float(current_probe.get("validation_live_filled_rows_delta"), 0.0) or 0)
    live_fill_delta = int(_safe_float(current_probe.get("live_filled_rows_delta"), 0.0) or 0)
    order_failed_rate = _safe_float(current_probe.get("recent_order_failed_rate"), 0.0)
    loss_cluster_count = len(current_probe.get("recent_loss_cluster_flags") or [])
    stage_not_ready_tags = list(current_probe.get("stage_not_ready_reason_tags") or [])
    confidence_decay_steps = 0
    deploy_rank_penalty = 0
    reasons: list[str] = []
    ranking_score = _safe_float(ranking_inputs.get("ranking_score"), 0.0)
    severe_regression = _probe_severe_regression(
        stage_not_ready_tags=stage_not_ready_tags,
        ranking_score=ranking_score,
    )

    if probe_freshness_hours > PROBE_HARD_STALE_HOURS or live_fill_freshness_hours > PROBE_HARD_STALE_HOURS:
        confidence_decay_steps += 2
        deploy_rank_penalty = max(deploy_rank_penalty, 2)
        reasons.append("probe_stale_gt_12h")
    elif probe_freshness_hours > PROBE_STALE_HOURS or live_fill_freshness_hours > PROBE_STALE_HOURS:
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1)
        reasons.append("probe_stale_gt_6h")

    if validation_delta <= 0:
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1 if base_deploy_rank >= 3 else deploy_rank_penalty)
        reasons.append("validation_rows_flat")
    if order_failed_rate >= 0.35:
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1)
        reasons.append("recent_order_failed_rate_high")
    if loss_cluster_count > 0:
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1)
        reasons.append("recent_loss_cluster_flags_present")
    if any("trailing_12_live_filled_non_positive" == str(tag) for tag in stage_not_ready_tags):
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1)
        reasons.append("trailing_12_non_positive")
    if any("trailing_40_live_filled_non_positive" == str(tag) for tag in stage_not_ready_tags):
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1)
        reasons.append("trailing_40_non_positive")
    if ranking_score <= -20.0:
        confidence_decay_steps += 1
        deploy_rank_penalty = max(deploy_rank_penalty, 1)
        reasons.append("probe_ranking_negative")
    if severe_regression:
        confidence_decay_steps += 2
        deploy_rank_penalty = max(deploy_rank_penalty, 2 if base_deploy_rank >= 2 else 1)
        reasons.append("fresh_probe_severe_regression")

    evidence_growth_bonus = 0
    if validation_delta > 0:
        evidence_growth_bonus += 1
        reasons.append("validation_rows_growing")
    if live_fill_delta > 0:
        evidence_growth_bonus += 1
        reasons.append("fresh_live_fills_arrived")
    if ranking_score >= 18.0 and validation_delta > 0 and loss_cluster_count == 0:
        evidence_growth_bonus += 1
        reasons.append("probe_ranking_supportive")

    effective_conf_rank = max(1, base_conf_rank - confidence_decay_steps + evidence_growth_bonus)
    effective_deploy_rank = max(1, base_deploy_rank - max(0, deploy_rank_penalty - (1 if evidence_growth_bonus >= 2 else 0)))
    if confidence_decay_steps == 0 and evidence_growth_bonus == 0:
        reasons.append("probe_feedback_neutral")

    selection_bonus = _safe_float(ranking_inputs.get("selection_score_bonus"), 0.0) + (float(evidence_growth_bonus) * 8.0)
    selection_penalty = _safe_float(ranking_inputs.get("selection_score_penalty"), 0.0) + (float(confidence_decay_steps) * 6.0)

    return {
        "base_package_confidence_label": package_confidence_label,
        "base_deploy_recommendation": deploy_recommendation,
        "effective_package_confidence_label": _confidence_label_from_rank(effective_conf_rank),
        "effective_deploy_recommendation": _deploy_label_from_rank(effective_deploy_rank),
        "confidence_decay_steps": int(max(0, confidence_decay_steps)),
        "deploy_rank_penalty": int(max(0, deploy_rank_penalty)),
        "evidence_growth_bonus": int(max(0, evidence_growth_bonus)),
        "probe_ranking_score": round(ranking_score, 4),
        "selection_score_bonus": round(selection_bonus, 4),
        "selection_score_penalty": round(selection_penalty, 4),
        "adjustment_reasons": reasons,
    }


def _normalized_candidate_class(label: Any) -> str:
    return _legacy_candidate_class(label)


def _probe_severe_regression(
    *,
    stage_not_ready_tags: list[str] | set[str],
    ranking_score: float,
) -> bool:
    tags = {str(tag).strip() for tag in stage_not_ready_tags if str(tag).strip()}
    short_window_negative = (
        "trailing_12_live_filled_non_positive" in tags
        and "trailing_40_live_filled_non_positive" in tags
    )
    validation_flat = "validation_rows_flat" in tags
    high_order_failure = "recent_order_failed_rate_above_0.25" in tags
    live_fills_stale = "live_fills_stale_gt_6h" in tags
    return bool(
        (short_window_negative and validation_flat)
        or (short_window_negative and ranking_score <= -20.0)
        or (validation_flat and high_order_failure)
        or (live_fills_stale and ranking_score <= -30.0)
    )


def _resolved_candidate_class(
    *,
    source: str,
    candidate_class: Any,
    evidence_band: str,
    validation_live_filled_rows: int,
    generalization_ratio: float,
) -> tuple[str, list[str]]:
    normalized = _normalized_candidate_class(candidate_class)
    if normalized:
        return normalized, []
    if str(source or "").strip().lower() == "active_profile":
        return "hold_current", ["fallback_active_profile_baseline"]
    if (
        str(evidence_band or "").strip().lower() == "validated"
        and int(validation_live_filled_rows) >= 16
        and float(generalization_ratio) >= 0.80
    ):
        return "hold_current", ["fallback_validated_candidate_hold_current"]
    return "probe_only", ["fallback_requires_revalidation"]


def _effective_candidate_class(
    *,
    source: str,
    candidate_class: Any,
    evidence_band: str,
    validation_live_filled_rows: int,
    generalization_ratio: float,
    current_probe: dict[str, Any],
) -> tuple[str, list[str], str]:
    resolved_class, reason_tags = _resolved_candidate_class(
        source=source,
        candidate_class=candidate_class,
        evidence_band=evidence_band,
        validation_live_filled_rows=validation_live_filled_rows,
        generalization_ratio=generalization_ratio,
    )
    stage_not_ready_tags = {
        str(tag)
        for tag in (current_probe.get("stage_not_ready_reason_tags") or [])
        if str(tag).strip()
    }
    ranking_inputs = (
        current_probe.get("ranking_inputs")
        if isinstance(current_probe.get("ranking_inputs"), dict)
        else _probe_ranking_inputs(current_probe)
    )
    ranking_score = _safe_float(ranking_inputs.get("ranking_score"), 0.0)
    probe_freshness_hours = _safe_float(current_probe.get("probe_freshness_hours"), 9999.0)
    live_fill_freshness_hours = _safe_float(current_probe.get("live_fill_freshness_hours"), 9999.0)
    evidence_band_normalized = str(evidence_band or "").strip().lower()
    severe_regression = _probe_severe_regression(
        stage_not_ready_tags=stage_not_ready_tags,
        ranking_score=ranking_score,
    )

    if "recent_loss_cluster_flags_present" in stage_not_ready_tags:
        return "suppress_cluster", reason_tags + ["recent_loss_cluster_flags_present"], "fresh_probe_cluster_suppressed"

    if resolved_class == "promote":
        promote_blockers: list[str] = []
        for tag in (
            "trailing_12_live_filled_non_positive",
            "trailing_40_live_filled_non_positive",
            "validation_rows_flat",
            "recent_order_failed_rate_above_0.25",
            "live_fills_stale_gt_6h",
        ):
            if tag in stage_not_ready_tags:
                promote_blockers.append(tag)
        if probe_freshness_hours > PROBE_HARD_STALE_HOURS or live_fill_freshness_hours > PROBE_HARD_STALE_HOURS:
            promote_blockers.append("probe_stale_gt_12h")
        elif probe_freshness_hours > PROBE_STALE_HOURS or live_fill_freshness_hours > PROBE_STALE_HOURS:
            promote_blockers.append("probe_stale_gt_6h")
        if ranking_score <= -20.0:
            promote_blockers.append("probe_ranking_negative")
        if promote_blockers:
            downgraded_class = "probe_only"
            if (
                not severe_regression
                and evidence_band_normalized == "validated"
                and int(validation_live_filled_rows) >= 16
            ):
                downgraded_class = "hold_current"
            if severe_regression:
                promote_blockers.append("fresh_probe_severe_regression")
            return downgraded_class, reason_tags + promote_blockers, "fresh_probe_blocks_promote"
        supportive_tags: list[str] = []
        if ranking_score >= 18.0:
            supportive_tags.append("fresh_probe_supportive")
        return "promote", reason_tags + supportive_tags, "fresh_probe_confirms_promote"

    if resolved_class == "hold_current" and severe_regression:
        return "probe_only", reason_tags + ["fresh_probe_severe_regression"], "fresh_probe_demotes_hold_current"

    if resolved_class == "hold_current" and evidence_band_normalized != "validated":
        return "probe_only", reason_tags + ["non_validated_hold_demoted_probe_only"], "non_validated_hold_demoted"

    return resolved_class, reason_tags, "class_retained"


def _probe_gated_decision(
    *,
    decision: dict[str, Any],
    current_probe: dict[str, Any],
) -> dict[str, Any]:
    base = dict(decision or {})
    base_action = str(base.get("action") or "hold").strip().lower()
    base_reason = str(base.get("reason") or "missing_decision_reason").strip() or "missing_decision_reason"
    ranking_inputs = (
        current_probe.get("ranking_inputs")
        if isinstance(current_probe.get("ranking_inputs"), dict)
        else _probe_ranking_inputs(current_probe)
    )
    stage_not_ready_tags = {
        str(tag)
        for tag in (current_probe.get("stage_not_ready_reason_tags") or [])
        if str(tag).strip()
    }
    gate_reason_tags: list[str] = []
    if base_action == "promote":
        for tag in (
            "trailing_12_live_filled_non_positive",
            "trailing_40_live_filled_non_positive",
            "validation_rows_flat",
            "recent_order_failed_rate_above_0.25",
            "recent_loss_cluster_flags_present",
            "live_fills_stale_gt_6h",
        ):
            if tag in stage_not_ready_tags:
                gate_reason_tags.append(tag)
        probe_freshness_hours = _safe_float(current_probe.get("probe_freshness_hours"), 9999.0)
        live_fill_freshness_hours = _safe_float(current_probe.get("live_fill_freshness_hours"), 9999.0)
        if probe_freshness_hours > PROBE_HARD_STALE_HOURS or live_fill_freshness_hours > PROBE_HARD_STALE_HOURS:
            gate_reason_tags.append("probe_stale_gt_12h")
        elif probe_freshness_hours > PROBE_STALE_HOURS or live_fill_freshness_hours > PROBE_STALE_HOURS:
            gate_reason_tags.append("probe_stale_gt_6h")
        if _safe_float(ranking_inputs.get("ranking_score"), 0.0) <= -20.0:
            gate_reason_tags.append("probe_ranking_negative")
        if _probe_severe_regression(
            stage_not_ready_tags=stage_not_ready_tags,
            ranking_score=_safe_float(ranking_inputs.get("ranking_score"), 0.0),
        ):
            gate_reason_tags.append("fresh_probe_severe_regression")
    out = dict(base)
    out["lab_action"] = base_action
    out["lab_reason"] = base_reason
    if gate_reason_tags:
        deduped: list[str] = []
        seen: set[str] = set()
        for tag in gate_reason_tags:
            if tag in seen:
                continue
            seen.add(tag)
            deduped.append(tag)
        out["action"] = "hold"
        out["reason"] = "probe_feedback_blocks_promotion"
        out["probe_gate_applied"] = True
        out["probe_gate_reason_tags"] = deduped
        return out
    out["probe_gate_applied"] = False
    out["probe_gate_reason_tags"] = []
    return out


def _build_package_ranking(
    *,
    ranked_packages: list[dict[str, Any]],
    current_probe: dict[str, Any],
    frontier_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ranking_inputs = (
        current_probe.get("ranking_inputs")
        if isinstance(current_probe.get("ranking_inputs"), dict)
        else _probe_ranking_inputs(current_probe)
    )
    probe_ranking_score = _safe_float(ranking_inputs.get("ranking_score"), 0.0)
    frontier_items = (
        frontier_report.get("ranked_policies")
        if isinstance(frontier_report, dict) and isinstance(frontier_report.get("ranked_policies"), list)
        else []
    )
    frontier_by_hash = {
        str(item.get("package_hash") or "").strip(): item
        for item in frontier_items
        if isinstance(item, dict) and str(item.get("package_hash") or "").strip()
    }
    incumbent_hash = str(frontier_report.get("incumbent_package_hash") or "").strip() if isinstance(frontier_report, dict) else ""
    frontier_best_hash = str(frontier_report.get("best_market_package_hash") or "").strip() if isinstance(frontier_report, dict) else ""
    items: list[dict[str, Any]] = []
    for package in ranked_packages:
        source = str(package.get("source") or "")
        evidence_band = str(package.get("evidence_band") or "exploratory").strip().lower()
        validation_rows = int(package.get("validation_live_filled_rows") or 0)
        generalization_ratio = _safe_float(package.get("generalization_ratio"), 0.0)
        explicit_reason_tags = list(package.get("candidate_class_reason_tags") or [])
        base_class, base_reason_tags = _resolved_candidate_class(
            source=source,
            candidate_class=package.get("candidate_class"),
            evidence_band=evidence_band,
            validation_live_filled_rows=validation_rows,
            generalization_ratio=generalization_ratio,
        )
        if explicit_reason_tags:
            base_reason_tags = explicit_reason_tags
        effective_class, effective_reason_tags, effective_reason = _effective_candidate_class(
            source=source,
            candidate_class=base_class,
            evidence_band=evidence_band,
            validation_live_filled_rows=validation_rows,
            generalization_ratio=generalization_ratio,
            current_probe=current_probe,
        )
        base_package_set = _package_set_label(base_class)
        effective_package_set = _package_set_label(effective_class)
        if base_reason_tags:
            merged_reason_tags: list[str] = []
            for tag in [*base_reason_tags, *effective_reason_tags]:
                normalized_tag = str(tag or "").strip()
                if not normalized_tag or normalized_tag in merged_reason_tags:
                    continue
                merged_reason_tags.append(normalized_tag)
            effective_reason_tags = merged_reason_tags
        base_priority = _candidate_class_rank(base_class)
        effective_priority = _candidate_class_rank(effective_class)
        probe_score_adjustment = 0.0
        if effective_priority < base_priority:
            probe_score_adjustment -= float(base_priority - effective_priority) * 40.0
        elif effective_priority > base_priority:
            probe_score_adjustment += float(effective_priority - base_priority) * 20.0
        if effective_priority >= _candidate_class_rank("hold_current"):
            if probe_ranking_score > 0.0:
                probe_score_adjustment += min(20.0, probe_ranking_score * 0.25)
            elif probe_ranking_score < 0.0:
                probe_score_adjustment -= min(25.0, abs(probe_ranking_score) * 0.25)
        probe_aware_live_score = round(
            _safe_float(package.get("live_execution_score"), 0.0) + probe_score_adjustment,
            6,
        )
        runtime_package = package.get("runtime_package") if isinstance(package.get("runtime_package"), dict) else {}
        profile = runtime_package.get("profile") if isinstance(runtime_package.get("profile"), dict) else {}
        package_hash = str(runtime_package_hash(runtime_package) or "").strip()
        frontier_item = frontier_by_hash.get(package_hash) if package_hash else None
        frontier_policy_loss = (
            round(_safe_float((frontier_item or {}).get("policy_loss"), 0.0) or 0.0, 4)
            if frontier_item is not None
            else None
        )
        probe_selection_penalty = 0.0
        if frontier_item is not None:
            if effective_priority < base_priority:
                probe_selection_penalty += float(base_priority - effective_priority) * FRESH_PROBE_POLICY_LOSS_PENALTY
            probe_freshness_hours = _safe_float(ranking_inputs.get("probe_freshness_hours"), 9999.0)
            live_fill_freshness_hours = _safe_float(ranking_inputs.get("live_fill_freshness_hours"), 9999.0)
            if probe_freshness_hours > PROBE_HARD_STALE_HOURS or live_fill_freshness_hours > PROBE_HARD_STALE_HOURS:
                probe_selection_penalty += STALE_PROBE_POLICY_LOSS_PENALTY
            elif probe_freshness_hours > PROBE_STALE_HOURS or live_fill_freshness_hours > PROBE_STALE_HOURS:
                probe_selection_penalty += STALE_PROBE_POLICY_LOSS_PENALTY * 0.4
            if probe_ranking_score < 0.0 and effective_priority >= _candidate_class_rank("hold_current"):
                probe_selection_penalty += min(120.0, abs(probe_ranking_score) * 1.5)
        selection_policy_loss = (
            round(frontier_policy_loss + probe_selection_penalty, 4)
            if frontier_policy_loss is not None
            else None
        )
        item = {
            "source": source,
            "candidate_family": str(package.get("candidate_family") or "unknown"),
            "profile_name": str(profile.get("name") or "unknown"),
            "runtime_package": runtime_package,
            "package_hash": package_hash or None,
            "base_candidate_class": base_class,
            "base_candidate_class_priority": int(base_priority),
            "base_candidate_class_reason_tags": base_reason_tags,
            "base_package_set": base_package_set or None,
            "base_package_set_priority": int(_package_set_rank(base_package_set)),
            "effective_candidate_class": effective_class,
            "effective_candidate_class_priority": int(effective_priority),
            "effective_candidate_class_reason": effective_reason,
            "effective_candidate_class_reason_tags": effective_reason_tags,
            "effective_package_set": effective_package_set or None,
            "effective_package_set_priority": int(_package_set_rank(effective_package_set)),
            "evidence_band": evidence_band,
            "validation_live_filled_rows": validation_rows,
            "generalization_ratio": round(generalization_ratio, 4),
            "fill_retention_ratio": round(_safe_float(package.get("fill_retention_ratio"), 0.0), 4),
            "execution_realism_score": round(_safe_float(package.get("execution_realism_score"), 0.0), 4),
            "raw_research_score": round(_safe_float(package.get("raw_research_score"), 0.0), 6),
            "live_execution_score": round(_safe_float(package.get("live_execution_score"), 0.0), 6),
            "probe_aware_live_score": probe_aware_live_score,
            "frontier_policy_loss": frontier_policy_loss,
            "frontier_market_model_version": (frontier_item or {}).get("market_model_version"),
            "frontier_rank": ((frontier_items.index(frontier_item) + 1) if frontier_item in frontier_items else None),
            "policy_components": dict((frontier_item or {}).get("policy_components") or {}),
            "probe_selection_penalty": round(probe_selection_penalty, 4) if frontier_item is not None else None,
            "selection_policy_loss": selection_policy_loss,
            "selection_source": "frontier_policy_loss" if frontier_item is not None else "probe_aware_live_score",
            "frontier_gap_vs_best": (
                round(frontier_policy_loss - _safe_float(frontier_report.get("best_market_policy_loss"), 0.0), 4)
                if frontier_item is not None and isinstance(frontier_report, dict) and frontier_report.get("best_market_policy_loss") is not None
                else None
            ),
            "frontier_gap_vs_incumbent": (
                round(_safe_float(frontier_report.get("incumbent_policy_loss"), 0.0) - frontier_policy_loss, 4)
                if frontier_item is not None and isinstance(frontier_report, dict) and frontier_report.get("incumbent_policy_loss") is not None
                else None
            ),
            "frontier_is_best": bool(package_hash and package_hash == frontier_best_hash),
            "frontier_matches_incumbent": bool(package_hash and package_hash == incumbent_hash),
        }
        items.append(item)

    items.sort(
        key=lambda item: (
            0 if item.get("selection_policy_loss") is not None else 1,
            float(item.get("selection_policy_loss") or float("inf")),
            float(item.get("frontier_policy_loss") or float("inf")),
            -int(item.get("effective_package_set_priority") or -1),
            -float(item.get("probe_aware_live_score") or 0.0),
            -float(item.get("live_execution_score") or 0.0),
            -float(item.get("execution_realism_score") or 0.0),
            -int(item.get("validation_live_filled_rows") or 0),
            str(item.get("profile_name") or ""),
            str(item.get("source") or ""),
        )
    )
    top_by_class: dict[str, dict[str, Any]] = {}
    top_by_package_set: dict[str, dict[str, Any]] = {}
    class_breakdown = {label: 0 for label in ("promote", "hold_current", "probe_only", "suppress_cluster")}
    package_set_breakdown = {label: 0 for label in ("live_candidate", "shadow_only", "hold_current", "suppress")}
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
        label = str(item.get("effective_candidate_class") or "")
        if label in class_breakdown:
            class_breakdown[label] += 1
            top_by_class.setdefault(
                label,
                {
                    "rank": rank,
                    "source": item.get("source"),
                    "profile_name": item.get("profile_name"),
                    "probe_aware_live_score": item.get("probe_aware_live_score"),
                },
            )
        package_set = str(item.get("effective_package_set") or "")
        if package_set in package_set_breakdown:
            package_set_breakdown[package_set] += 1
            top_by_package_set.setdefault(
                package_set,
                {
                    "rank": rank,
                    "source": item.get("source"),
                    "profile_name": item.get("profile_name"),
                    "effective_candidate_class": item.get("effective_candidate_class"),
                    "probe_aware_live_score": item.get("probe_aware_live_score"),
                },
            )
    return {
        "contract_version": 2,
        "ranking_score_version": 1,
        "package_set_contract_version": 1,
        "frontier_selection_contract_version": 1,
        "probe_inputs": {
            "probe_freshness_hours": ranking_inputs.get("probe_freshness_hours"),
            "live_fill_freshness_hours": ranking_inputs.get("live_fill_freshness_hours"),
            "validation_live_filled_rows_delta": ranking_inputs.get("validation_live_filled_rows_delta"),
            "live_filled_rows_delta": ranking_inputs.get("live_filled_rows_delta"),
            "recent_order_failed_rate": ranking_inputs.get("recent_order_failed_rate"),
            "trailing_fill_counts": ranking_inputs.get("trailing_fill_counts") or {},
            "trailing_net_positive": ranking_inputs.get("trailing_net_positive") or {},
            "recent_direction_mix": ranking_inputs.get("recent_direction_mix") or {},
            "recent_price_bucket_mix": ranking_inputs.get("recent_price_bucket_mix") or {},
            "recent_loss_cluster_flags": ranking_inputs.get("recent_loss_cluster_flags") or [],
            "probe_ranking_score": ranking_inputs.get("ranking_score"),
            "probe_ranking_reasons": ranking_inputs.get("ranking_reasons") or [],
        },
        "frontier": {
            "current_market_model_version": (
                frontier_report.get("current_market_model_version") if isinstance(frontier_report, dict) else None
            ),
            "incumbent_package_hash": incumbent_hash or None,
            "best_market_package_hash": frontier_best_hash or None,
            "best_market_policy_loss": (
                frontier_report.get("best_market_policy_loss") if isinstance(frontier_report, dict) else None
            ),
            "incumbent_policy_loss": (
                frontier_report.get("incumbent_policy_loss") if isinstance(frontier_report, dict) else None
            ),
        },
        "class_breakdown": class_breakdown,
        "package_set_breakdown": package_set_breakdown,
        "top_by_class": top_by_class,
        "top_by_package_set": top_by_package_set,
        "top_package_set": items[0].get("effective_package_set") if items else None,
        "ranked_packages": items,
    }


def _attach_current_probe_fields(payload: dict[str, Any], current_probe: dict[str, Any]) -> dict[str, Any]:
    payload["current_probe"] = current_probe
    payload["latest_decision_timestamp"] = current_probe.get("latest_decision_timestamp")
    payload["latest_live_fill_timestamp"] = current_probe.get("latest_live_fill_timestamp")
    payload["probe_freshness_hours"] = current_probe.get("probe_freshness_hours")
    payload["live_fill_freshness_hours"] = current_probe.get("live_fill_freshness_hours")
    payload["trailing_12_live_filled_pnl_usd"] = current_probe.get("trailing_12_live_filled_pnl_usd")
    payload["trailing_40_live_filled_pnl_usd"] = current_probe.get("trailing_40_live_filled_pnl_usd")
    payload["trailing_120_live_filled_pnl_usd"] = current_probe.get("trailing_120_live_filled_pnl_usd")
    payload["recent_order_failed_rate"] = current_probe.get("recent_order_failed_rate")
    payload["recent_direction_mix"] = current_probe.get("recent_direction_mix") or {}
    payload["recent_price_bucket_mix"] = current_probe.get("recent_price_bucket_mix") or {}
    payload["recent_loss_cluster_flags"] = current_probe.get("recent_loss_cluster_flags") or []
    payload["probe_ranking_score"] = current_probe.get("ranking_score")
    payload["probe_ranking_reasons"] = current_probe.get("ranking_reasons") or []
    payload["stage_ready_reason_tags"] = current_probe.get("stage_ready_reason_tags") or []
    payload["stage_not_ready_reason_tags"] = current_probe.get("stage_not_ready_reason_tags") or []
    return payload


def _extract_forecast_candidate(payload: dict[str, Any] | None, *, source_artifact: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    arr = payload.get("arr_tracking") or {}
    generated_at = _parse_iso_timestamp(payload.get("generated_at"))
    confidence_label = str(payload.get("selected_package_confidence_label") or payload.get("package_confidence_label") or "low")
    deploy_recommendation = str(payload.get("selected_deploy_recommendation") or payload.get("deploy_recommendation") or "hold")
    return {
        "source_artifact": source_artifact,
        "generated_at": generated_at.isoformat() if generated_at else "",
        "forecast_active_arr_pct": _safe_float(arr.get("current_median_arr_pct"), 0.0),
        "forecast_best_arr_pct": _safe_float(arr.get("best_median_arr_pct"), 0.0),
        "forecast_arr_delta_pct": _safe_float(arr.get("median_arr_delta_pct"), 0.0),
        "package_confidence_label": confidence_label,
        "package_confidence_reasons": list(payload.get("package_confidence_reasons") or []),
        "deploy_recommendation": deploy_recommendation,
        "package_class": str(payload.get("selected_package_class") or payload.get("package_class") or ""),
        "package_candidate_class": str(
            payload.get("selected_package_candidate_class") or payload.get("package_candidate_class") or ""
        ),
        "validation_live_filled_rows": int(payload.get("validation_live_filled_rows") or 0),
        "generalization_ratio": _safe_float(payload.get("generalization_ratio"), 0.0),
        "best_runtime_package": payload.get("selected_best_runtime_package") or payload.get("best_runtime_package") or {},
        "active_runtime_package": payload.get("selected_active_runtime_package") or payload.get("active_runtime_package") or {},
        "capital_scale_recommendation": payload.get("capital_scale_recommendation") or {},
        "capital_stage_recommendation": payload.get("capital_stage_recommendation") or {},
        "runtime_load_status": payload.get("runtime_load_status") or {},
        "best_live_package": payload.get("best_live_package") or {},
        "execution_drag_summary": payload.get("execution_drag_summary") or {},
        "size_aware_deployment": payload.get("size_aware_deployment") or {},
        "current_probe": payload.get("current_probe") or {},
        "probe_feedback": payload.get("probe_feedback") or {},
        "probe_freshness_hours": payload.get("probe_freshness_hours"),
        "probe_ranking_score": payload.get("probe_ranking_score"),
        "probe_ranking_reasons": list(payload.get("probe_ranking_reasons") or []),
        "recent_order_failed_rate": payload.get("recent_order_failed_rate"),
        "recent_direction_mix": payload.get("recent_direction_mix") or {},
        "recent_price_bucket_mix": payload.get("recent_price_bucket_mix") or {},
        "recent_loss_cluster_flags": payload.get("recent_loss_cluster_flags") or [],
        "stage_ready_reason_tags": payload.get("stage_ready_reason_tags") or [],
        "stage_not_ready_reason_tags": payload.get("stage_not_ready_reason_tags") or [],
    }


def _forecast_candidate_selection_score(candidate: dict[str, Any]) -> float:
    current_probe = candidate.get("current_probe") if isinstance(candidate.get("current_probe"), dict) else {}
    probe_feedback = candidate.get("probe_feedback") if isinstance(candidate.get("probe_feedback"), dict) else {}
    validation_rows = int(candidate.get("validation_live_filled_rows") or 0)
    generalization_ratio = _safe_float(candidate.get("generalization_ratio"), 0.0)
    base_score = (
        (_confidence_rank(str(candidate.get("package_confidence_label") or "")) * 100.0)
        + (_deploy_rank(str(candidate.get("deploy_recommendation") or "")) * 35.0)
        + min(50.0, float(validation_rows))
        + min(30.0, generalization_ratio * 10.0)
    )
    package_class = str(candidate.get("package_class") or "").strip().lower()
    base_score += {
        "live_candidate": 30.0,
        "hold_current": 10.0,
        "shadow_only": -12.0,
        "suppress": -55.0,
    }.get(package_class, 0.0)
    age_hours = _safe_float(candidate.get("age_hours"), 9999.0)
    freshness_hours = _safe_float(
        current_probe.get("probe_freshness_hours"),
        _safe_float(candidate.get("probe_freshness_hours"), age_hours),
    )
    probe_ranking_score = _safe_float(
        candidate.get("probe_ranking_score"),
        _safe_float(current_probe.get("ranking_score"), 0.0),
    )
    validation_delta = int(
        _safe_float(
            current_probe.get("validation_live_filled_rows_delta"),
            (probe_feedback.get("evidence_growth_bonus") or 0),
        )
        or 0
    )
    live_fill_delta = int(_safe_float(current_probe.get("live_filled_rows_delta"), 0.0) or 0)
    selection_bonus = _safe_float(probe_feedback.get("selection_score_bonus"), 0.0)
    selection_penalty = _safe_float(probe_feedback.get("selection_score_penalty"), 0.0)
    if probe_ranking_score > 0.0:
        selection_bonus += min(30.0, probe_ranking_score * 0.35)
    elif probe_ranking_score < 0.0:
        selection_penalty += min(35.0, abs(probe_ranking_score) * 0.4)
    if freshness_hours > PROBE_STALE_HOURS:
        # Strongly decay stale forecast artifacts so fresh probe feedback can
        # suppress nominally better but outdated packages.
        selection_penalty += min(220.0, (freshness_hours - PROBE_STALE_HOURS) * 6.0)
    elif freshness_hours <= 1.0:
        selection_bonus += 10.0
    if validation_delta > 0:
        selection_bonus += min(30.0, float(validation_delta) * 6.0)
    if live_fill_delta > 0:
        selection_bonus += min(18.0, float(live_fill_delta) * 3.0)
    if validation_delta <= 0:
        selection_penalty += 12.0
    if candidate.get("stage_not_ready_reason_tags"):
        selection_penalty += min(24.0, 4.0 * len(candidate.get("stage_not_ready_reason_tags") or []))
    return round(base_score + selection_bonus - selection_penalty, 4)


def _select_public_forecast(
    *,
    standard_payload: dict[str, Any] | None,
    current_probe_payload: dict[str, Any] | None,
    standard_source: str,
    current_probe_source: str,
) -> dict[str, Any]:
    now = _now_utc()
    candidates: list[dict[str, Any]] = []
    standard = _extract_forecast_candidate(standard_payload, source_artifact=standard_source)
    current_probe = _extract_forecast_candidate(current_probe_payload, source_artifact=current_probe_source)
    if standard:
        candidates.append(standard)
    if current_probe:
        candidates.append(current_probe)
    if not candidates:
        return {
            "selected": None,
            "candidates": [],
            "selection_reason": "no_forecast_artifacts_available",
        }

    for candidate in candidates:
        generated = _parse_iso_timestamp(candidate.get("generated_at"))
        age_hours = ((now - generated).total_seconds() / 3600.0) if generated else 9999.0
        candidate["age_hours"] = round(max(0.0, age_hours), 4)
        candidate["is_fresh_6h"] = bool(generated and age_hours <= 6.0)
        candidate["selection_score"] = _forecast_candidate_selection_score(candidate)

    fresh = [item for item in candidates if item.get("is_fresh_6h")]
    pool = fresh or candidates
    pool.sort(
        key=lambda item: (
            _safe_float(item.get("selection_score"), float("-inf")),
            _confidence_rank(str(item.get("package_confidence_label") or "")),
            _deploy_rank(str(item.get("deploy_recommendation") or "")),
            _parse_iso_timestamp(item.get("generated_at")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    selected = pool[0]
    selection_reason = (
        "selected_from_fresh_pool_by_probe_feedback_then_confidence_then_deploy_then_generated_at"
        if fresh
        else "no_fresh_artifacts_within_6h_selected_best_available_with_probe_feedback"
    )
    return {
        "selected": selected,
        "candidates": candidates,
        "selection_reason": selection_reason,
    }


def _select_runtime_payload(
    *,
    standard_payload: dict[str, Any] | None,
    current_probe_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    probe_payload = current_probe_payload if isinstance(current_probe_payload, dict) else None
    standard = standard_payload if isinstance(standard_payload, dict) else None
    probe_meta = probe_payload.get("current_probe") if isinstance(probe_payload, dict) else None
    probe_freshness_hours = _safe_float(
        (probe_meta or {}).get("probe_freshness_hours"),
        _safe_float((probe_payload or {}).get("probe_freshness_hours"), 9999.0),
    )
    probe_is_fresh = bool(probe_meta) and probe_freshness_hours <= PROBE_STALE_HOURS
    if standard:
        return {
            "source": "standard",
            "selection_reason": (
                "standard_cycle_payload_frontier_authoritative_probe_advisory"
                if probe_payload and probe_is_fresh
                else (
                    "standard_cycle_payload_used_for_runtime_selection_probe_stale"
                    if probe_payload
                    else "standard_cycle_payload_used_for_runtime_selection"
                )
            ),
            "payload": standard,
        }
    if probe_payload:
        return {
            "source": "current_probe",
            "selection_reason": "current_probe_feedback_used_without_standard_fallback_probe_stale",
            "payload": probe_payload,
        }
    return {
        "source": "none",
        "selection_reason": "no_runtime_payload_available",
        "payload": {},
    }


def _frontier_candidate_hashes(cycle_payload: dict[str, Any]) -> set[str]:
    hashes: set[str] = set()

    def record(runtime_package: dict[str, Any] | None) -> None:
        if not isinstance(runtime_package, dict) or not runtime_package.get("profile"):
            return
        package_hash = str(runtime_package_hash(runtime_package) or "").strip()
        if package_hash:
            hashes.add(package_hash)

    record(cycle_payload.get("active_runtime_package"))
    record(cycle_payload.get("selected_active_runtime_package"))
    record(cycle_payload.get("best_runtime_package"))
    record(cycle_payload.get("selected_best_runtime_package"))
    ranked_packages = (cycle_payload.get("package_ranking") or {}).get("ranked_packages") or []
    for item in ranked_packages:
        if not isinstance(item, dict):
            continue
        record(item.get("runtime_package"))
    return hashes


def _frontier_report_is_fresh(
    frontier_payload: dict[str, Any] | None,
    *,
    current_hashes: set[str],
    expected_market_model_version: str | None = None,
) -> bool:
    if not isinstance(frontier_payload, dict):
        return False
    updated_at = _parse_iso_timestamp(frontier_payload.get("updated_at"))
    if updated_at is None:
        return False
    age_hours = (_now_utc() - updated_at).total_seconds() / 3600.0
    if age_hours > FRONTIER_STALE_HOURS:
        return False
    ranked = frontier_payload.get("ranked_policies") if isinstance(frontier_payload.get("ranked_policies"), list) else []
    frontier_hashes = {
        str(item.get("package_hash") or "").strip()
        for item in ranked
        if isinstance(item, dict) and str(item.get("package_hash") or "").strip()
    }
    current_version = str(frontier_payload.get("current_market_model_version") or "").strip() or None
    if expected_market_model_version and current_version not in {None, expected_market_model_version}:
        return False
    return bool(frontier_hashes) and current_hashes.issubset(frontier_hashes)


def _load_or_build_frontier_report(
    *,
    cycle_payload: dict[str, Any],
    frontier_latest_path: Path,
    market_policy_handoff: Path,
    market_latest_json: Path,
) -> dict[str, Any]:
    current_hashes = _frontier_candidate_hashes(cycle_payload)
    latest = _load_json(frontier_latest_path) or {}
    handoff_payload = _load_json(market_policy_handoff) or {}
    expected_market_model_version = str(handoff_payload.get("market_model_version") or "").strip() or None
    if _frontier_report_is_fresh(
        latest,
        current_hashes=current_hashes,
        expected_market_model_version=expected_market_model_version,
    ):
        return latest
    return build_frontier_report(
        cycle_payload=cycle_payload,
        market_policy_handoff=market_policy_handoff,
        market_latest_json=market_latest_json,
    )


def _selected_runtime_contract(
    *,
    runtime_package_selection: dict[str, Any],
    selected_best_runtime_package: dict[str, Any],
    selected_active_runtime_package: dict[str, Any],
    selected_deploy_recommendation: str,
    selected_package_confidence_label: str,
    selected_package_confidence_reasons: list[str],
    selected_size_aware_deployment: dict[str, Any],
    selected_package_class_summary: dict[str, Any],
    promoted_package_selected: bool,
) -> dict[str, Any]:
    return {
        "runtime_package_selection": dict(runtime_package_selection),
        "selected_best_runtime_package": selected_best_runtime_package,
        "selected_active_runtime_package": selected_active_runtime_package,
        "selected_package_hash": runtime_package_hash(selected_best_runtime_package) if selected_best_runtime_package else None,
        "selected_policy_loss": runtime_package_selection.get("selected_policy_loss"),
        "selected_market_model_version": runtime_package_selection.get("selected_market_model_version"),
        "frontier_gap_vs_best": runtime_package_selection.get("frontier_gap_vs_best"),
        "frontier_gap_vs_incumbent": runtime_package_selection.get("frontier_gap_vs_incumbent"),
        "selection_source": runtime_package_selection.get("selection_source"),
        "selected_deploy_recommendation": selected_deploy_recommendation,
        "selected_package_confidence_label": selected_package_confidence_label,
        "selected_package_confidence_reasons": list(selected_package_confidence_reasons),
        "selected_size_aware_deployment": selected_size_aware_deployment,
        "selected_package_class": selected_package_class_summary.get("package_class"),
        "selected_package_candidate_class": selected_package_class_summary.get("candidate_class"),
        "selected_package_class_reason": selected_package_class_summary.get("class_reason"),
        "selected_package_class_reason_tags": list(selected_package_class_summary.get("class_reason_tags") or []),
        "selected_package_class_rank": selected_package_class_summary.get("rank"),
        "selected_package_class_source": selected_package_class_summary.get("source"),
        "selected_package_class_profile_name": selected_package_class_summary.get("profile_name"),
        "selected_package_class_matched_runtime_package": selected_package_class_summary.get(
            "matched_runtime_package"
        ),
        "promoted_package_selected": bool(promoted_package_selected),
    }


def _package_freeze_contract(
    *,
    selected_active_runtime_package: dict[str, Any],
    selected_best_runtime_package: dict[str, Any],
    best_live_package: dict[str, Any],
    best_raw_package: dict[str, Any],
    runtime_package_selection: dict[str, Any],
    selected_deploy_recommendation: str,
) -> dict[str, Any]:
    def _profile_name(runtime_package: dict[str, Any] | None) -> str | None:
        if not isinstance(runtime_package, dict):
            return None
        profile = runtime_package.get("profile")
        if not isinstance(profile, dict):
            return None
        name = str(profile.get("name") or "").strip()
        return name or None

    canonical_live_package = (
        dict(selected_active_runtime_package)
        if isinstance(selected_active_runtime_package, dict)
        else {}
    )
    canonical_signature = _package_signature(canonical_live_package)

    comparator_candidates = [
        ("best_live_package", best_live_package),
        ("best_raw_research_package", best_raw_package),
        ("selected_best_runtime_package", {"runtime_package": selected_best_runtime_package}),
    ]
    shadow_runtime_package: dict[str, Any] = {}
    shadow_source = "none"
    for source_name, record in comparator_candidates:
        runtime_package = (
            record.get("runtime_package")
            if isinstance(record, dict) and isinstance(record.get("runtime_package"), dict)
            else {}
        )
        if not runtime_package:
            continue
        if _package_signature(runtime_package) == canonical_signature:
            continue
        shadow_runtime_package = dict(runtime_package)
        shadow_source = source_name
        break

    canonical_profile_name = _profile_name(canonical_live_package)
    shadow_profile_name = _profile_name(shadow_runtime_package)
    shadow_reason_tags: list[str] = []
    if shadow_runtime_package:
        shadow_reason_tags.append("same_cycle_live_package_frozen")
        if shadow_source == "best_live_package":
            shadow_reason_tags.append("fresh_same_stream_evidence_required")
        if shadow_runtime_package.get("session_policy"):
            shadow_reason_tags.append("session_conditioned_override_shadow_only")
        if str(selected_deploy_recommendation or "").strip().lower() != "promote":
            shadow_reason_tags.append("selected_deploy_recommendation_not_promote")

    return {
        "canonical_live_package": {
            "policy_id": canonical_profile_name,
            "package_hash": runtime_package_hash(canonical_live_package) if canonical_live_package else None,
            "runtime_package": canonical_live_package if canonical_live_package else None,
            "status": "live_current" if canonical_live_package else "missing",
            "selection_source": runtime_package_selection.get("source_artifact")
            or runtime_package_selection.get("source"),
        },
        "shadow_comparator_package": {
            "policy_id": shadow_profile_name,
            "package_hash": runtime_package_hash(shadow_runtime_package) if shadow_runtime_package else None,
            "runtime_package": shadow_runtime_package if shadow_runtime_package else None,
            "status": "shadow_only" if shadow_runtime_package else "none",
            "source": shadow_source,
            "reason_tags": shadow_reason_tags,
        },
        "package_consistency_status": (
            "aligned_one_live_one_shadow"
            if canonical_live_package and (
                not shadow_runtime_package
                or _package_signature(shadow_runtime_package) != canonical_signature
            )
            else "missing_canonical_live_package"
        ),
    }


def _merged_strategy_env(base_env: Path, override_env: Path) -> dict[str, str]:
    merged = _load_env_file(base_env)
    merged.update(_load_env_file(override_env))
    return merged


def _profile_signature(profile: dict[str, Any] | None) -> tuple[float | None, float | None, float | None]:
    if not isinstance(profile, dict):
        return (None, None, None)
    values: list[float | None] = []
    for key in ("max_abs_delta", "up_max_buy_price", "down_max_buy_price"):
        raw = profile.get(key)
        values.append(None if raw is None else _safe_float(raw, 0.0))
    return tuple(values)  # type: ignore[return-value]


def _size_trade_key(value: Any) -> float:
    return round(_safe_float(value, 0.0), 4)


def _candidate_capacity_profile_label(
    candidate: dict[str, Any] | None,
    *,
    current_candidate: dict[str, Any] | None,
    global_best_candidate: dict[str, Any] | None,
) -> tuple[str | None, bool, str]:
    if not isinstance(candidate, dict):
        return None, False, "missing_candidate"
    if _candidate_identity(candidate) == _candidate_identity(current_candidate):
        return "current_live_profile", False, "exact_current_live_profile_match"
    if _candidate_identity(candidate) == _candidate_identity(global_best_candidate):
        return "best_candidate", False, "exact_global_best_candidate_match"

    candidate_base = (
        candidate.get("base_profile")
        if isinstance(candidate.get("base_profile"), dict)
        else candidate.get("profile")
    )
    current_base = (
        (current_candidate or {}).get("base_profile")
        if isinstance((current_candidate or {}).get("base_profile"), dict)
        else (current_candidate or {}).get("profile")
    )
    global_best_base = (
        (global_best_candidate or {}).get("base_profile")
        if isinstance((global_best_candidate or {}).get("base_profile"), dict)
        else (global_best_candidate or {}).get("profile")
    )
    candidate_sig = _profile_signature(candidate_base if isinstance(candidate_base, dict) else None)
    current_sig = _profile_signature(current_base if isinstance(current_base, dict) else None)
    global_best_sig = _profile_signature(global_best_base if isinstance(global_best_base, dict) else None)
    if candidate_sig == current_sig and any(value is not None for value in candidate_sig):
        return "current_live_profile", True, "matched_base_profile_to_current_live_profile"
    if candidate_sig == global_best_sig and any(value is not None for value in candidate_sig):
        return "best_candidate", True, "matched_base_profile_to_global_best_candidate"
    return None, False, "no_capacity_profile_match"


def _capacity_size_index(profile_payload: dict[str, Any] | None) -> dict[float, dict[str, Any]]:
    if not isinstance(profile_payload, dict):
        return {}
    indexed: dict[float, dict[str, Any]] = {}
    for collection_name in ("stage_sweeps", "size_sweeps"):
        for item in profile_payload.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            key = _size_trade_key(item.get("trade_size_usd"))
            if key <= 0.0:
                continue
            indexed[key] = dict(item)
    return indexed


def _size_aware_deployment_summary(
    *,
    candidate: dict[str, Any] | None,
    simulation_summary: dict[str, Any] | None,
    current_candidate: dict[str, Any] | None,
    global_best_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    label, approximate_match, match_reason = _candidate_capacity_profile_label(
        candidate,
        current_candidate=current_candidate,
        global_best_candidate=global_best_candidate,
    )
    profiles = (
        ((simulation_summary or {}).get("capacity_stress_summary") or {}).get("profiles")
        if isinstance((simulation_summary or {}).get("capacity_stress_summary"), dict)
        else {}
    ) or {}
    profile_payload = profiles.get(label) if label else None
    if not isinstance(profile_payload, dict):
        return {
            "available": False,
            "capacity_profile_label": label,
            "capacity_profile_name": None,
            "approximate_match": approximate_match,
            "match_reason": match_reason,
            "recommended_live_stage_cap": 0,
            "recommended_live_trade_size_cap_usd": 0,
            "safe_live_trade_size_usd": 0,
            "safe_live_stage_label": "none",
            "capital_ladder_status": "unavailable",
            "next_notional_gate": {},
            "live_stage_assessments": [],
            "shadow_trade_size_assessments": [],
        }

    sweeps_by_size = _capacity_size_index(profile_payload)
    capital_ladder = profile_payload.get("capital_ladder") if isinstance(profile_payload.get("capital_ladder"), dict) else {}
    live_now = capital_ladder.get("live_now") if isinstance(capital_ladder.get("live_now"), dict) else {}
    next_notional_gate = (
        capital_ladder.get("next_notional_gate")
        if isinstance(capital_ladder.get("next_notional_gate"), dict)
        else {}
    )
    live_stage_decisions = {
        str(item.get("stage_label") or ""): item
        for item in (capital_ladder.get("live_stage_decisions") or [])
        if isinstance(item, dict)
    }
    shadow_decisions = {
        _size_trade_key(item.get("trade_size_usd")): item
        for item in (capital_ladder.get("shadow_only") or [])
        if isinstance(item, dict)
    }
    live_stage_assessments: list[dict[str, Any]] = []
    recommended_live_stage_cap = 0
    for capital_stage, trade_size_usd in LIVE_STAGE_MAX_TRADE_USD.items():
        sweep = sweeps_by_size.get(_size_trade_key(trade_size_usd))
        if not isinstance(sweep, dict):
            live_stage_assessments.append(
                {
                    "capital_stage": int(capital_stage),
                    "trade_size_usd": float(trade_size_usd),
                    "available": False,
                    "gate_passed": False,
                    "gate_reason": "missing_capacity_sweep",
                }
            )
            continue

        expected_fill_retention_ratio = _safe_float(sweep.get("expected_fill_retention_ratio"), 0.0)
        expected_p05_arr_pct = _safe_float(sweep.get("expected_p05_arr_pct"), 0.0)
        expected_loss_limit_hit_probability = _safe_float(
            sweep.get("expected_loss_limit_hit_probability"),
            0.0,
        )
        fill_threshold = {1: 0.45, 2: 0.25, 3: 0.15}.get(int(capital_stage), 0.15)
        loss_limit_ceiling = {1: 0.35, 2: 0.45, 3: 0.55}.get(int(capital_stage), 0.55)
        gate_passed = (
            expected_fill_retention_ratio >= fill_threshold
            and expected_p05_arr_pct > 0.0
            and expected_loss_limit_hit_probability <= loss_limit_ceiling
        )
        gate_reason = "size_ready_for_live_stage" if gate_passed else "size_sweep_blocks_live_stage_upgrade"
        if gate_passed:
            recommended_live_stage_cap = int(capital_stage)
        assessment = {
            "capital_stage": int(capital_stage),
            "trade_size_usd": float(trade_size_usd),
            "available": True,
            "gate_passed": gate_passed,
            "gate_reason": gate_reason,
            "expected_fill_probability": round(_safe_float(sweep.get("expected_fill_probability"), 0.0), 4),
            "expected_fill_retention_ratio": round(expected_fill_retention_ratio, 4),
            "expected_order_failed_probability": round(
                _safe_float(sweep.get("expected_order_failed_probability"), 0.0),
                4,
            ),
            "expected_cancelled_unfilled_probability": round(
                _safe_float(sweep.get("expected_cancelled_unfilled_probability"), 0.0),
                4,
            ),
            "expected_post_only_retry_failure_rate": round(
                _safe_float(sweep.get("expected_post_only_retry_failure_rate"), 0.0),
                4,
            ),
            "expected_p05_arr_pct": round(expected_p05_arr_pct, 4),
            "expected_median_arr_pct": round(_safe_float(sweep.get("expected_median_arr_pct"), 0.0), 4),
            "expected_profit_probability": round(_safe_float(sweep.get("expected_profit_probability"), 0.0), 4),
            "expected_loss_limit_hit_probability": round(expected_loss_limit_hit_probability, 4),
            "expected_p95_max_drawdown_usd": round(
                _safe_float(sweep.get("expected_p95_max_drawdown_usd"), 0.0),
                4,
            ),
        }
        ladder_decision = live_stage_decisions.get(f"stage_{int(capital_stage)}") or {}
        if isinstance(ladder_decision, dict):
            assessment["decision_status"] = str(ladder_decision.get("status") or "")
            assessment["deployment_class"] = str(ladder_decision.get("deployment_class") or "")
            assessment["blocking_categories"] = list(ladder_decision.get("blocking_categories") or [])
            assessment["blocking_reasons"] = list(ladder_decision.get("blocking_reasons") or [])
            assessment["evidence_required"] = list(ladder_decision.get("evidence_required") or [])
            assessment["evidence_verdict"] = str(ladder_decision.get("evidence_verdict") or "inconclusive")
            assessment["missing_evidence_items"] = list(ladder_decision.get("missing_evidence_items") or [])
            assessment["true_negative_items"] = list(ladder_decision.get("true_negative_items") or [])
        live_stage_assessments.append(assessment)

    shadow_trade_size_assessments: list[dict[str, Any]] = []
    for trade_size_usd in SHADOW_TRADE_SIZES_USD:
        sweep = sweeps_by_size.get(_size_trade_key(trade_size_usd))
        assessment = {
            "trade_size_usd": float(trade_size_usd),
            "available": isinstance(sweep, dict),
            "deployment_mode": "shadow_only",
        }
        if isinstance(sweep, dict):
            assessment.update(
                {
                    "expected_fill_probability": round(
                        _safe_float(sweep.get("expected_fill_probability"), 0.0),
                        4,
                    ),
                    "expected_fill_retention_ratio": round(
                        _safe_float(sweep.get("expected_fill_retention_ratio"), 0.0),
                        4,
                    ),
                    "expected_order_failed_probability": round(
                        _safe_float(sweep.get("expected_order_failed_probability"), 0.0),
                        4,
                    ),
                    "expected_cancelled_unfilled_probability": round(
                        _safe_float(sweep.get("expected_cancelled_unfilled_probability"), 0.0),
                        4,
                    ),
                    "expected_post_only_retry_failure_rate": round(
                        _safe_float(sweep.get("expected_post_only_retry_failure_rate"), 0.0),
                        4,
                    ),
                    "expected_p05_arr_pct": round(_safe_float(sweep.get("expected_p05_arr_pct"), 0.0), 4),
                    "expected_median_arr_pct": round(_safe_float(sweep.get("expected_median_arr_pct"), 0.0), 4),
                    "expected_loss_limit_hit_probability": round(
                        _safe_float(sweep.get("expected_loss_limit_hit_probability"), 0.0),
                        4,
                    ),
                    "expected_p95_max_drawdown_usd": round(
                        _safe_float(sweep.get("expected_p95_max_drawdown_usd"), 0.0),
                        4,
                    ),
                }
            )
            ladder_decision = shadow_decisions.get(_size_trade_key(trade_size_usd)) or {}
            if isinstance(ladder_decision, dict):
                assessment["decision_status"] = str(ladder_decision.get("status") or "")
                assessment["deployment_class"] = str(ladder_decision.get("deployment_class") or "shadow_only")
                assessment["gate_passed"] = bool(ladder_decision.get("gate_passed"))
                assessment["blocking_categories"] = list(ladder_decision.get("blocking_categories") or [])
                assessment["blocking_reasons"] = list(ladder_decision.get("blocking_reasons") or [])
                assessment["evidence_required"] = list(ladder_decision.get("evidence_required") or [])
                assessment["evidence_verdict"] = str(ladder_decision.get("evidence_verdict") or "inconclusive")
                assessment["missing_evidence_items"] = list(ladder_decision.get("missing_evidence_items") or [])
                assessment["true_negative_items"] = list(ladder_decision.get("true_negative_items") or [])
        else:
            assessment["gate_reason"] = "missing_capacity_sweep"
        shadow_trade_size_assessments.append(assessment)

    recommended_live_trade_size_cap_usd = int(
        LIVE_STAGE_MAX_TRADE_USD.get(recommended_live_stage_cap, 0.0)
    )
    return {
        "available": True,
        "capacity_profile_label": label,
        "capacity_profile_name": str(profile_payload.get("profile_name") or ""),
        "approximate_match": approximate_match,
        "match_reason": match_reason,
        "capital_ladder_status": str(capital_ladder.get("status") or "unavailable"),
        "safe_live_trade_size_usd": int(round(_safe_float(live_now.get("safe_trade_size_usd"), 0.0))),
        "safe_live_stage_label": str(live_now.get("safe_stage_label") or "none"),
        "next_notional_gate": dict(next_notional_gate),
        "recommended_live_stage_cap": int(recommended_live_stage_cap),
        "recommended_live_trade_size_cap_usd": recommended_live_trade_size_cap_usd,
        "live_stage_assessments": live_stage_assessments,
        "shadow_trade_size_assessments": shadow_trade_size_assessments,
    }


def _profile_from_env(name: str, env: dict[str, str]) -> GuardrailProfile:
    return GuardrailProfile(
        name=name,
        max_abs_delta=_safe_float(env.get("BTC5_MAX_ABS_DELTA"), 0.0) or None,
        up_max_buy_price=_safe_float(env.get("BTC5_UP_MAX_BUY_PRICE"), 0.0) or None,
        down_max_buy_price=_safe_float(env.get("BTC5_DOWN_MAX_BUY_PRICE"), 0.0) or None,
        note="loaded from strategy env",
    )


def _arr_for_candidate(candidate: dict[str, Any] | None) -> dict[str, float]:
    continuation = (candidate or {}).get("continuation") or {}
    return {
        "historical_arr_pct": _safe_float(continuation.get("historical_arr_pct"), 0.0),
        "median_arr_pct": _safe_float(continuation.get("median_arr_pct"), 0.0),
        "p05_arr_pct": _safe_float(continuation.get("p05_arr_pct"), 0.0),
    }


def _arr_tracking(best: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    best_arr = _arr_for_candidate(best)
    current_arr = _arr_for_candidate(current)
    return {
        "metric_name": "continuation_arr_pct",
        "current_historical_arr_pct": round(current_arr["historical_arr_pct"], 4),
        "current_median_arr_pct": round(current_arr["median_arr_pct"], 4),
        "current_p05_arr_pct": round(current_arr["p05_arr_pct"], 4),
        "best_historical_arr_pct": round(best_arr["historical_arr_pct"], 4),
        "best_median_arr_pct": round(best_arr["median_arr_pct"], 4),
        "best_p05_arr_pct": round(best_arr["p05_arr_pct"], 4),
        "historical_arr_delta_pct": round(best_arr["historical_arr_pct"] - current_arr["historical_arr_pct"], 4),
        "median_arr_delta_pct": round(best_arr["median_arr_pct"] - current_arr["median_arr_pct"], 4),
        "p05_arr_delta_pct": round(best_arr["p05_arr_pct"] - current_arr["p05_arr_pct"], 4),
    }


def _find_candidate(summary: dict[str, Any], name: str) -> dict[str, Any] | None:
    for candidate in summary.get("candidates") or []:
        if candidate.get("profile", {}).get("name") == name:
            return candidate
    return None


def _session_override_sort_key(item: dict[str, Any]) -> tuple[int, tuple[int, ...], str]:
    hours = tuple(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int))
    return (len(hours), hours, str(item.get("session_name") or ""))


def _normalized_session_overrides(overrides: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in overrides or []:
        if not isinstance(item, dict):
            continue
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        hours = sorted(
            {
                int(hour)
                for hour in (item.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            }
        )
        if not hours:
            continue
        normalized.append(
            {
                "session_name": str(item.get("session_name") or "").strip(),
                "et_hours": hours,
                "profile": {
                    "name": str(profile.get("name") or "").strip(),
                    "max_abs_delta": _safe_float(profile.get("max_abs_delta"), 0.0) or None,
                    "up_max_buy_price": _safe_float(profile.get("up_max_buy_price"), 0.0) or None,
                    "down_max_buy_price": _safe_float(profile.get("down_max_buy_price"), 0.0) or None,
                },
            }
        )
    normalized.sort(key=_session_override_sort_key)
    return normalized


def _runtime_session_policy_from_overrides(overrides: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    runtime_policy: list[dict[str, Any]] = []
    for item in _normalized_session_overrides(overrides):
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        record: dict[str, Any] = {
            "name": str(item.get("session_name") or profile.get("name") or "session_policy").strip(),
            "et_hours": list(item.get("et_hours") or []),
        }
        max_abs_delta = profile.get("max_abs_delta")
        up_max_buy_price = profile.get("up_max_buy_price")
        down_max_buy_price = profile.get("down_max_buy_price")
        if max_abs_delta is not None:
            record["max_abs_delta"] = _safe_float(max_abs_delta, 0.0) or 0.0
        if up_max_buy_price is not None:
            record["up_max_buy_price"] = _safe_float(up_max_buy_price, 0.0) or 0.0
        if down_max_buy_price is not None:
            record["down_max_buy_price"] = _safe_float(down_max_buy_price, 0.0) or 0.0
        runtime_policy.append(record)
    return runtime_policy


def _runtime_session_policy_from_env(env: dict[str, str]) -> list[dict[str, Any]]:
    raw = str(env.get("BTC5_SESSION_POLICY_JSON") or "").strip()
    if not raw:
        return []
    try:
        payload = fast_loads(raw)
    except ValueError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        hours = item.get("et_hours")
        if not name or not isinstance(hours, list):
            continue
        out.append(dict(item))
    return out


def _normalize_global_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    profile = dict(candidate.get("profile") or {})
    return {
        **candidate,
        "candidate_family": "global_profile",
        "profile": profile,
        "base_profile": dict(profile),
        "session_overrides": [],
        "recommended_session_policy": [],
        "candidate_class": candidate.get("candidate_class"),
        "candidate_class_reason_tags": candidate.get("candidate_class_reason_tags") or [],
        "execution_realism_score": candidate.get("execution_realism_score"),
        "execution_realism_label": candidate.get("execution_realism_label"),
        "evidence_band": candidate.get("evidence_band"),
    }


def _normalize_regime_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    policy = candidate.get("policy") or {}
    base_profile = dict(policy.get("default_profile") or {})
    session_overrides = _normalized_session_overrides((policy.get("overrides") or []))
    profile = dict(base_profile)
    profile["name"] = str(policy.get("name") or base_profile.get("name") or "session_policy")
    return {
        "candidate_family": "regime_policy",
        "profile": profile,
        "base_profile": base_profile,
        "session_overrides": session_overrides,
        "recommended_session_policy": _runtime_session_policy_from_overrides(session_overrides),
        "historical": candidate.get("historical") or {},
        "monte_carlo": candidate.get("monte_carlo") or {},
        "continuation": candidate.get("continuation") or {},
        "scoring": candidate.get("scoring") or {},
        "candidate_class": candidate.get("candidate_class"),
        "candidate_class_reason_tags": candidate.get("candidate_class_reason_tags") or [],
        "execution_realism_score": candidate.get("execution_realism_score"),
        "execution_realism_label": candidate.get("execution_realism_label"),
        "evidence_band": candidate.get("evidence_band"),
        "policy": policy,
    }


def _merge_candidate_metadata(
    candidate: dict[str, Any] | None,
    *,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    meta = metadata if isinstance(metadata, dict) else {}
    if not meta:
        return candidate
    merged = dict(candidate)
    for key in (
        "candidate_class",
        "candidate_class_reason_tags",
        "evidence_band",
        "execution_realism_score",
        "execution_realism_label",
        "generalization_ratio",
    ):
        if merged.get(key) in (None, "", [], {}):
            value = meta.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value
    scoring = dict(merged.get("scoring") or {})
    for key in (
        "candidate_class",
        "candidate_class_reason_tags",
        "evidence_band",
        "execution_realism_score",
        "generalization_ratio",
        "validation_live_filled_rows",
    ):
        if scoring.get(key) in (None, "", [], {}):
            value = meta.get(key)
            if value not in (None, "", [], {}):
                scoring[key] = value
    if scoring:
        merged["scoring"] = scoring
    return merged


def _candidate_identity(candidate: dict[str, Any] | None) -> tuple[Any, ...]:
    if candidate is None:
        return tuple()
    base_profile = (candidate.get("base_profile") or candidate.get("profile") or {})
    return (
        _safe_float(base_profile.get("max_abs_delta"), 0.0) or None,
        _safe_float(base_profile.get("up_max_buy_price"), 0.0) or None,
        _safe_float(base_profile.get("down_max_buy_price"), 0.0) or None,
        tuple(
            (
                item.get("session_name"),
                tuple(item.get("et_hours") or []),
                (item.get("profile") or {}).get("max_abs_delta"),
                (item.get("profile") or {}).get("up_max_buy_price"),
                (item.get("profile") or {}).get("down_max_buy_price"),
            )
            for item in _normalized_session_overrides(candidate.get("session_overrides"))
        ),
    )


def _semantic_candidate_hash(candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict):
        return ""
    signature_payload = {
        "candidate_family": str(candidate.get("candidate_family") or ""),
        "identity": _candidate_identity(candidate),
        "runtime_session_policy": _runtime_session_policy_from_overrides(candidate.get("session_overrides"))
        or list(candidate.get("recommended_session_policy") or []),
    }
    return sha256(repr(signature_payload).encode("utf-8")).hexdigest()


def _load_semantic_dedup_index(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {"version": 1, "seen": {}}
    seen = payload.get("seen") if isinstance(payload.get("seen"), dict) else {}
    return {"version": 1, "seen": seen}


def _save_semantic_dedup_index(path: Path, payload: dict[str, Any]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dedupe_candidate_evaluations(
    candidates: list[tuple[str, dict[str, Any] | None]],
    *,
    dedup_index: dict[str, Any] | None,
    now: datetime | None = None,
) -> tuple[list[tuple[str, dict[str, Any] | None]], list[dict[str, Any]], list[str]]:
    seen_index = (dedup_index or {}).get("seen")
    historical_seen = seen_index if isinstance(seen_index, dict) else {}
    cycle_seen: set[str] = set()
    kept: list[tuple[str, dict[str, Any] | None]] = []
    skipped: list[dict[str, Any]] = []
    kept_hashes: list[str] = []
    generated_at = (now or _now_utc()).isoformat()

    for source, candidate in candidates:
        if candidate is None:
            continue
        semantic_hash = _semantic_candidate_hash(candidate)
        if not semantic_hash:
            kept.append((source, candidate))
            continue
        if semantic_hash in cycle_seen:
            skipped.append(
                {
                    "source": source,
                    "semantic_hash": semantic_hash,
                    "reason": "duplicate_in_cycle",
                }
            )
            continue
        if source != "active_profile" and semantic_hash in historical_seen:
            skipped.append(
                {
                    "source": source,
                    "semantic_hash": semantic_hash,
                    "reason": "duplicate_in_dedup_index",
                    "first_seen_at": historical_seen.get(semantic_hash, {}).get("first_seen_at"),
                }
            )
            continue

        cycle_seen.add(semantic_hash)
        kept_hashes.append(semantic_hash)
        kept.append((source, candidate))
        existing = historical_seen.get(semantic_hash)
        if not isinstance(existing, dict):
            historical_seen[semantic_hash] = {
                "first_seen_at": generated_at,
                "last_seen_at": generated_at,
                "sources": [source],
                "count": 1,
            }
        else:
            sources = [str(item) for item in (existing.get("sources") or []) if str(item)]
            if source not in sources:
                sources.append(source)
            historical_seen[semantic_hash] = {
                "first_seen_at": existing.get("first_seen_at") or generated_at,
                "last_seen_at": generated_at,
                "sources": sources,
                "count": int(_safe_float(existing.get("count"), 0.0) or 0) + 1,
            }
    return kept, skipped, kept_hashes


def _runtime_package(
    *,
    profile: dict[str, Any] | None,
    session_policy: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "profile": dict(profile or {}),
        "session_policy": list(session_policy or []),
    }


def _package_signature(package: dict[str, Any] | None) -> tuple[Any, ...]:
    package = package or {}
    profile = package.get("profile") if isinstance(package.get("profile"), dict) else {}
    policy = package.get("session_policy") if isinstance(package.get("session_policy"), list) else []
    normalized_policy: list[tuple[Any, ...]] = []
    for item in policy:
        if not isinstance(item, dict):
            continue
        hours = tuple(sorted(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int)))
        normalized_policy.append(
            (
                str(item.get("name") or ""),
                hours,
                _safe_float(item.get("max_abs_delta"), None),
                _safe_float(item.get("up_max_buy_price"), None),
                _safe_float(item.get("down_max_buy_price"), None),
            )
        )
    normalized_policy.sort()
    return (
        str(profile.get("name") or ""),
        _safe_float(profile.get("max_abs_delta"), None),
        _safe_float(profile.get("up_max_buy_price"), None),
        _safe_float(profile.get("down_max_buy_price"), None),
        tuple(normalized_policy),
    )


def _package_class_summary(
    package_ranking: dict[str, Any] | None,
    runtime_package: dict[str, Any] | None,
) -> dict[str, Any]:
    ranking = package_ranking if isinstance(package_ranking, dict) else {}
    items = ranking.get("ranked_packages") if isinstance(ranking.get("ranked_packages"), list) else []
    target_signature = _package_signature(runtime_package)
    matched_item: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if _package_signature(item.get("runtime_package")) == target_signature:
            matched_item = item
            break
    fallback_item = matched_item or (items[0] if items and isinstance(items[0], dict) else {})
    return {
        "package_class": str(
            (fallback_item or {}).get("effective_package_set")
            or ranking.get("top_package_set")
            or ""
        ).strip()
        or None,
        "candidate_class": str((fallback_item or {}).get("effective_candidate_class") or "").strip() or None,
        "class_reason": str((fallback_item or {}).get("effective_candidate_class_reason") or "").strip() or None,
        "class_reason_tags": list((fallback_item or {}).get("effective_candidate_class_reason_tags") or []),
        "rank": int(_safe_float((fallback_item or {}).get("rank"), 0.0) or 0),
        "source": str((fallback_item or {}).get("source") or "").strip() or None,
        "profile_name": str((fallback_item or {}).get("profile_name") or "").strip() or None,
        "matched_runtime_package": bool(matched_item),
    }


def _live_fill_windows(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    live = [row for row in rows if str(row.get("order_status") or "").strip().lower() == "live_filled"]
    live.sort(key=lambda row: int(row.get("window_start_ts") or row.get("timestamp") or 0))

    def summarize(count: int) -> dict[str, float]:
        sample = live[-count:] if len(live) >= count else list(live)
        fills = len(sample)
        pnl = sum(_safe_float(row.get("pnl_usd"), 0.0) for row in sample)
        if fills >= 2:
            first_ts = int(sample[0].get("window_start_ts") or sample[0].get("timestamp") or 0)
            last_ts = int(sample[-1].get("window_start_ts") or sample[-1].get("timestamp") or 0)
            hours = max(0.0, (last_ts - first_ts) / 3600.0)
        else:
            hours = 0.0
        return {
            "fills": fills,
            "pnl_usd": round(pnl, 4),
            "hours": round(hours, 4),
            "net_positive": bool(pnl > 0.0),
        }

    return {
        "trailing_5": summarize(5),
        "trailing_12": summarize(12),
        "trailing_20": summarize(20),
        "trailing_40": summarize(40),
        "trailing_120": summarize(120),
    }


def _latest_live_fill_age_hours(rows: list[dict[str, Any]]) -> float | None:
    latest_ts: datetime | None = None
    for row in rows:
        if str(row.get("order_status") or "").strip().lower() != "live_filled":
            continue
        parsed = None
        for raw in (
            row.get("updated_at"),
            row.get("created_at"),
        ):
            if parsed is None:
                parsed = _parse_iso_timestamp(raw)
        if parsed is None:
            ts = int(_safe_float(row.get("window_start_ts"), 0.0) or 0)
            if ts > 0:
                parsed = datetime.fromtimestamp(ts, tz=timezone.utc)
        if parsed is None:
            continue
        if latest_ts is None or parsed > latest_ts:
            latest_ts = parsed
    if latest_ts is None:
        return None
    age_hours = (_now_utc() - latest_ts).total_seconds() / 3600.0
    return round(max(0.0, age_hours), 4)


def _fund_reconciliation_blocked(runtime_truth: dict[str, Any] | None) -> tuple[bool, list[str]]:
    launch = (runtime_truth or {}).get("launch") or {}
    blocked_checks = [str(item) for item in (launch.get("blocked_checks") or []) if item]
    reconciliation_flags = {"accounting_reconciliation_drift", "polymarket_capital_truth_drift"}
    active = sorted([item for item in blocked_checks if item in reconciliation_flags])
    return (len(active) > 0, active)


def _capital_scale_recommendation(
    *,
    deploy_recommendation: str,
    package_confidence_label: str,
    trailing: dict[str, dict[str, float]],
    promoted_package_selected: bool,
    fund_reconciliation_blocked: bool,
    fund_block_reasons: list[str],
    size_aware_deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trailing_5 = trailing.get("trailing_5") or {}
    trailing_12 = trailing.get("trailing_12") or {}
    trailing_20 = trailing.get("trailing_20") or {}
    conf_high = str(package_confidence_label).strip().lower() == "high"
    deploy_label = str(deploy_recommendation).strip().lower()
    size_summary = size_aware_deployment if isinstance(size_aware_deployment, dict) else {}
    size_summary_available = bool(size_summary.get("available"))
    size_aware_live_stage_cap = int(_safe_float(size_summary.get("recommended_live_stage_cap"), 0.0) or 0)
    size_aware_trade_size_cap_usd = int(_safe_float(size_summary.get("recommended_live_trade_size_cap_usd"), 0.0) or 0)
    runtime_load_required = deploy_label in {"promote", "shadow_only"} and not promoted_package_selected
    positive_12 = bool(trailing_12.get("net_positive"))
    positive_20 = bool(trailing_20.get("net_positive"))

    status = "hold"
    tranche = 0
    basis = trailing_5
    reason = "confidence_or_live_fill_window_not_sufficient_for_capital_add"

    if (
        conf_high
        and deploy_label == "promote"
        and positive_12
        and positive_20
        and (not size_summary_available or size_aware_live_stage_cap >= 1)
        and not fund_reconciliation_blocked
    ):
        status = "scale_add"
        tranche = 1000
        basis = trailing_20
        reason = "high_confidence_and_trailing20_12_positive_with_size_ready_package"
        if runtime_load_required:
            reason = f"{reason};runtime_load_required_before_scale_add"
    elif (
        conf_high
        and deploy_label in {"promote", "shadow_only"}
        and positive_12
        and (not size_summary_available or size_aware_live_stage_cap >= 1)
        and fund_reconciliation_blocked
    ):
        status = "test_add"
        tranche = 100
        basis = trailing_12
        reason = "high_confidence_and_trailing12_positive_but_fund_reconciliation_blocks_full_scale"
        if runtime_load_required:
            reason = f"{reason};runtime_load_required_before_test_add"
    elif deploy_label == "hold":
        status = "hold"
        tranche = 0
        basis = trailing_12
        reason = "deploy_recommendation_hold_blocks_capital_add"
    elif size_summary_available and size_aware_live_stage_cap < 1:
        status = "hold"
        tranche = 0
        basis = trailing_12
        reason = "size_aware_stage_cap_below_stage1"

    return {
        "status": status,
        "recommended_tranche_usd": tranche,
        "basis_window_fills": int(basis.get("fills") or 0),
        "basis_window_pnl_usd": round(_safe_float(basis.get("pnl_usd"), 0.0), 4),
        "basis_window_hours": round(_safe_float(basis.get("hours"), 0.0), 4),
        "reason": reason,
        "deploy_recommendation": deploy_label,
        "promoted_package_selected": bool(promoted_package_selected),
        "runtime_package_loaded": bool(promoted_package_selected),
        "runtime_load_required": bool(runtime_load_required),
        "size_aware_summary_available": bool(size_summary_available),
        "size_aware_live_stage_cap": int(size_aware_live_stage_cap),
        "size_aware_trade_size_cap_usd": int(size_aware_trade_size_cap_usd),
        "fund_reconciliation_blocked": bool(fund_reconciliation_blocked),
        "fund_blocking_checks": list(fund_block_reasons),
        "trailing_windows": trailing,
    }


def _capital_stage_recommendation(
    *,
    deploy_recommendation: str,
    package_confidence_label: str,
    trailing: dict[str, dict[str, float]],
    execution_drag_summary: dict[str, Any],
    promoted_package_selected: bool,
    latest_live_fill_age_hours: float | None,
    size_aware_deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    confidence = str(package_confidence_label).strip().lower()
    deploy_label = str(deploy_recommendation).strip().lower()
    order_failed_rate = _safe_float(execution_drag_summary.get("order_failure_rate"), 0.0)
    trailing_12 = trailing.get("trailing_12") or {}
    trailing_40 = trailing.get("trailing_40") or {}
    trailing_120 = trailing.get("trailing_120") or {}
    size_summary = size_aware_deployment if isinstance(size_aware_deployment, dict) else {}
    size_summary_available = bool(size_summary.get("available"))
    size_aware_live_stage_cap = int(_safe_float(size_summary.get("recommended_live_stage_cap"), 0.0) or 0)
    size_aware_trade_size_cap_usd = int(_safe_float(size_summary.get("recommended_live_trade_size_cap_usd"), 0.0) or 0)
    fresh_realized_fills = latest_live_fill_age_hours is not None and latest_live_fill_age_hours <= 6.0
    trailing_12_positive = bool(trailing_12.get("net_positive"))
    trailing_40_positive = bool(trailing_40.get("net_positive"))
    trailing_120_positive = bool(trailing_120.get("net_positive"))
    order_failure_ok = order_failed_rate < 0.25

    recommended_stage = 1
    recommended_max_trade_usd = int(LIVE_STAGE_MAX_TRADE_USD[1])
    stage_reason = "default_stage1_pending_stage_guardrails"

    if deploy_label == "hold":
        recommended_stage = 1
        recommended_max_trade_usd = int(LIVE_STAGE_MAX_TRADE_USD[1])
        stage_reason = "hold_stage1_deploy_recommendation_is_hold"
    elif (
        confidence == "high"
        and fresh_realized_fills
        and trailing_12_positive
        and trailing_120_positive
        and order_failure_ok
        and deploy_label == "promote"
    ):
        recommended_stage = 3
        recommended_max_trade_usd = int(LIVE_STAGE_MAX_TRADE_USD[3])
        stage_reason = "stage3_guardrails_passed_high_confidence_trailing120_positive"
    elif (
        confidence in {"high", "medium"}
        and fresh_realized_fills
        and trailing_12_positive
        and trailing_40_positive
        and order_failure_ok
    ):
        recommended_stage = 2
        recommended_max_trade_usd = int(LIVE_STAGE_MAX_TRADE_USD[2])
        stage_reason = "stage2_guardrails_passed_trailing40_12_positive_and_order_failure_below_25pct"
    elif fresh_realized_fills and trailing_12_positive:
        stage_reason = "stage1_confirmed_fresh_realized_fills_and_trailing12_positive"
    elif not fresh_realized_fills:
        stage_reason = "hold_stage1_realized_fills_not_fresh"
    elif not trailing_12_positive:
        stage_reason = "hold_stage1_trailing12_not_positive"

    if size_summary_available:
        effective_size_stage_cap = max(1, int(size_aware_live_stage_cap))
        if recommended_stage > effective_size_stage_cap:
            recommended_stage = effective_size_stage_cap
            recommended_max_trade_usd = int(LIVE_STAGE_MAX_TRADE_USD[recommended_stage])
            stage_reason = f"{stage_reason};size_aware_stage_cap_{effective_size_stage_cap}"

    promotion_guardrails_passed = bool(
        fresh_realized_fills
        and trailing_12_positive
        and order_failure_ok
        and confidence in {"high", "medium"}
        and (not size_summary_available or max(1, size_aware_live_stage_cap) >= 1)
    )
    return {
        "recommended_stage": int(recommended_stage),
        "recommended_max_trade_usd": int(recommended_max_trade_usd),
        "stage_reason": stage_reason,
        "promotion_guardrails_passed": promotion_guardrails_passed,
        "fresh_realized_fills": bool(fresh_realized_fills),
        "latest_live_fill_age_hours": latest_live_fill_age_hours,
        "order_failed_rate": round(order_failed_rate, 6),
        "deploy_recommendation": deploy_label,
        "confidence_label": confidence,
        "promoted_package_selected": bool(promoted_package_selected),
        "runtime_package_loaded": bool(promoted_package_selected),
        "runtime_load_required": bool(deploy_label in {"promote", "shadow_only"} and not promoted_package_selected),
        "trailing_12_net_positive": trailing_12_positive,
        "trailing_40_net_positive": trailing_40_positive,
        "trailing_120_net_positive": trailing_120_positive,
        "size_aware_summary_available": bool(size_summary_available),
        "size_aware_live_stage_cap": int(size_aware_live_stage_cap),
        "size_aware_trade_size_cap_usd": int(size_aware_trade_size_cap_usd),
        "live_stage_trade_sizes_usd": {
            f"stage_{capital_stage}": int(trade_size_usd)
            for capital_stage, trade_size_usd in LIVE_STAGE_MAX_TRADE_USD.items()
        },
        "shadow_trade_sizes_usd": [int(trade_size_usd) for trade_size_usd in SHADOW_TRADE_SIZES_USD],
    }


def _extract_validation_rows(candidate: dict[str, Any] | None) -> int:
    if not isinstance(candidate, dict):
        return 0
    scoring = candidate.get("scoring") or {}
    historical = candidate.get("historical") or {}
    for source in (scoring, historical):
        for key in ("validation_live_filled_rows", "replay_live_filled_rows", "baseline_live_filled_rows"):
            value = source.get(key)
            if value is None:
                continue
            return max(0, int(_safe_float(value, 0.0) or 0))
    return 0


def _extract_generalization_ratio(
    candidate: dict[str, Any] | None,
    *,
    hypothesis_summary: dict[str, Any] | None,
) -> float:
    if isinstance(candidate, dict):
        scoring = candidate.get("scoring") or {}
        continuation = candidate.get("continuation") or {}
        for source in (scoring, continuation):
            value = _safe_float(source.get("generalization_ratio"), None)
            if value is not None:
                return float(value)

    if isinstance(hypothesis_summary, dict):
        # Prefer best_hypothesis summary from the latest hypothesis lab when available.
        best_hypothesis = hypothesis_summary.get("best_hypothesis") or {}
        summary = best_hypothesis.get("summary") if isinstance(best_hypothesis, dict) else {}
        if isinstance(summary, dict):
            value = _safe_float(summary.get("generalization_ratio"), None)
            if value is not None:
                return float(value)
        value = _safe_float(hypothesis_summary.get("generalization_ratio"), None)
        if value is not None:
            return float(value)
    return 0.0


def _package_confidence(
    *,
    validation_live_filled_rows: int,
    generalization_ratio: float,
) -> tuple[str, list[str]]:
    reasons = [
        f"validation_live_filled_rows={int(validation_live_filled_rows)}",
        f"generalization_ratio={float(generalization_ratio):.4f}",
    ]
    if validation_live_filled_rows >= 12 and generalization_ratio >= 0.80:
        return "high", reasons
    if validation_live_filled_rows >= 6 and generalization_ratio >= 0.70:
        return "medium", reasons
    reasons.append("insufficient_validation_or_generalization")
    return "low", reasons


def _deploy_recommendation(
    *,
    decision_action: str,
    decision: dict[str, Any],
    validation_live_filled_rows: int,
    generalization_ratio: float,
) -> str:
    if decision_action == "promote":
        return "promote"
    policy_loss_delta = _safe_float(decision.get("policy_loss_delta"), 0.0)
    profit_probability_delta = _safe_float(decision.get("profit_probability_delta"), 0.0)
    p95_drawdown_delta_usd = _safe_float(decision.get("p95_drawdown_delta_usd"), 0.0)
    if (
        policy_loss_delta > 0.0
        and validation_live_filled_rows >= 6
        and generalization_ratio >= 0.80
        and profit_probability_delta >= -0.01
        and p95_drawdown_delta_usd <= 3.0
    ):
        return "shadow_only"
    return "hold"


def _select_best_target(
    *,
    candidates: list[tuple[str, dict[str, Any] | None]],
    current: dict[str, Any] | None,
    min_median_arr_improvement_pct: float,
    min_median_pnl_improvement_usd: float,
    min_replay_pnl_improvement_usd: float,
    max_profit_prob_drop: float,
    max_p95_drawdown_increase_usd: float,
    max_loss_hit_prob_increase: float,
    min_fill_lift: int,
    min_fill_retention_ratio: float,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    evaluated: list[dict[str, Any]] = []
    seen_semantic_hashes: set[str] = set()
    for source_name, candidate in candidates:
        if candidate is None:
            continue
        semantic_hash = _semantic_candidate_hash(candidate)
        if semantic_hash and semantic_hash in seen_semantic_hashes:
            continue
        if semantic_hash:
            seen_semantic_hashes.add(semantic_hash)
        decision = _promotion_decision(
            best=candidate,
            current=current,
            min_median_arr_improvement_pct=min_median_arr_improvement_pct,
            min_median_pnl_improvement_usd=min_median_pnl_improvement_usd,
            min_replay_pnl_improvement_usd=min_replay_pnl_improvement_usd,
            max_profit_prob_drop=max_profit_prob_drop,
            max_p95_drawdown_increase_usd=max_p95_drawdown_increase_usd,
            max_loss_hit_prob_increase=max_loss_hit_prob_increase,
            min_fill_lift=min_fill_lift,
            min_fill_retention_ratio=min_fill_retention_ratio,
        )
        evaluated.append(
            {
                "source": source_name,
                "semantic_hash": semantic_hash or None,
                "candidate": candidate,
                "decision": decision,
            }
        )

    if not evaluated:
        return None, {"action": "hold", "reason": "missing_candidate_data"}, []

    evaluated.sort(
        key=lambda item: (
            1 if (item.get("decision") or {}).get("action") == "promote" else 0,
            _safe_float((item.get("decision") or {}).get("policy_loss_delta"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("median_arr_delta_pct"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("replay_pnl_delta_usd"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("median_pnl_delta_usd"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("p05_arr_delta_pct"), float("-inf")),
            -_safe_float((item.get("decision") or {}).get("p95_drawdown_delta_usd"), float("inf")),
            _safe_float(((item.get("candidate") or {}).get("continuation") or {}).get("median_arr_pct"), float("-inf")),
        ),
        reverse=True,
    )
    best_entry = evaluated[0]
    decision = dict(best_entry.get("decision") or {})
    decision["selected_source"] = best_entry.get("source")
    decision["selected_family"] = ((best_entry.get("candidate") or {}).get("candidate_family") or "unknown")
    return best_entry.get("candidate"), decision, evaluated


def _build_hypothesis_candidate(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    best = summary.get("best_candidate")
    best_hypothesis = summary.get("best_hypothesis") or {}
    hypothesis = best_hypothesis.get("hypothesis") if isinstance(best_hypothesis, dict) else {}
    best_summary = best_hypothesis.get("summary") if isinstance(best_hypothesis, dict) else {}
    if not isinstance(best, dict):
        best = {}
    if not isinstance(hypothesis, dict):
        hypothesis = {}
    if not isinstance(best_summary, dict):
        best_summary = {}
    name = str(best.get("name") or hypothesis.get("name") or "").strip()
    if not name:
        return None
    profile = {
        "name": name,
        "max_abs_delta": _safe_float(best.get("max_abs_delta"), _safe_float(hypothesis.get("max_abs_delta"), None)),
        "up_max_buy_price": _safe_float(
            best.get("up_max_buy_price"), _safe_float(hypothesis.get("up_max_buy_price"), None)
        ),
        "down_max_buy_price": _safe_float(
            best.get("down_max_buy_price"), _safe_float(hypothesis.get("down_max_buy_price"), None)
        ),
    }
    session_name = str(best.get("session_name") or hypothesis.get("session_name") or "").strip()
    hours = [int(hour) for hour in (best.get("et_hours") or hypothesis.get("et_hours") or []) if isinstance(hour, int)]
    session_policy: list[dict[str, Any]] = []
    if session_name and hours:
        record: dict[str, Any] = {"name": session_name, "et_hours": sorted(hours)}
        if profile.get("max_abs_delta") is not None:
            record["max_abs_delta"] = profile["max_abs_delta"]
        if profile.get("up_max_buy_price") is not None:
            record["up_max_buy_price"] = profile["up_max_buy_price"]
        if profile.get("down_max_buy_price") is not None:
            record["down_max_buy_price"] = profile["down_max_buy_price"]
        session_policy.append(record)
    validation_rows = int(
        _safe_float(
            best.get("validation_live_filled_rows"),
            _safe_float(best_summary.get("validation_live_filled_rows"), 0.0),
        )
        or 0
    )
    validation_replay_pnl_usd = _safe_float(
        best.get("validation_replay_pnl_usd"),
        _safe_float(best_summary.get("validation_replay_pnl_usd"), 0.0),
    )
    validation_profit_probability = _safe_float(
        best.get("validation_profit_probability"),
        _safe_float(best_summary.get("validation_profit_probability"), 0.0),
    )
    validation_p95_drawdown_usd = _safe_float(
        best.get("validation_p95_drawdown_usd"),
        _safe_float(best_summary.get("validation_p95_drawdown_usd"), 0.0),
    )
    return {
        "candidate_family": "hypothesis",
        "profile": profile,
        "base_profile": dict(profile),
        "session_overrides": [],
        "recommended_session_policy": session_policy,
        "candidate_class": best.get("candidate_class"),
        "candidate_class_reason_tags": list(best.get("candidate_class_reason_tags") or []),
        "execution_realism_score": best.get("execution_realism_score"),
        "execution_realism_label": best.get("execution_realism_label"),
        "evidence_band": best.get("evidence_band") or best_summary.get("evidence_band"),
        "historical": {
            "replay_live_filled_rows": validation_rows,
            "replay_live_filled_pnl_usd": validation_replay_pnl_usd,
        },
        "monte_carlo": {
            "profit_probability": validation_profit_probability,
            "p95_max_drawdown_usd": validation_p95_drawdown_usd,
        },
        "continuation": {
            "median_arr_pct": _safe_float(best.get("validation_median_arr_pct"), _safe_float(best_summary.get("validation_median_arr_pct"), 0.0)),
            "p05_arr_pct": _safe_float(best.get("validation_p05_arr_pct"), _safe_float(best_summary.get("validation_p05_arr_pct"), 0.0)),
            "historical_arr_pct": _safe_float(best.get("validation_median_arr_pct"), _safe_float(best_summary.get("validation_median_arr_pct"), 0.0)),
        },
        "scoring": {
            "generalization_ratio": _safe_float(best.get("generalization_ratio"), _safe_float(best_summary.get("generalization_ratio"), 0.0)),
            "validation_live_filled_rows": validation_rows,
            "evidence_band": str(best.get("evidence_band") or best_summary.get("evidence_band") or ""),
            "candidate_class": str(best.get("candidate_class") or ""),
            "execution_realism_score": _safe_float(
                best.get("execution_realism_score"),
                _safe_float(best_summary.get("execution_realism_score"), 0.0),
            ),
        },
    }


def _execution_drag_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(rows))
    skip_price = 0
    order_failed = 0
    cancelled_unfilled = 0
    direction_stats: dict[str, dict[str, float]] = {}
    for row in rows:
        status = str(row.get("order_status") or "").strip().lower()
        direction = str(row.get("direction") or "UNKNOWN").strip().upper()
        stats = direction_stats.setdefault(
            direction,
            {"filled_rows": 0.0, "filled_pnl_usd": 0.0, "skip_price_count": 0.0, "order_failed_count": 0.0, "cancelled_unfilled_count": 0.0},
        )
        if status == "skip_price_outside_guardrails":
            skip_price += 1
            stats["skip_price_count"] += 1.0
        elif status in {"live_order_failed", "order_failed", "order_placement_failed", "post_only_cross_failure"}:
            order_failed += 1
            stats["order_failed_count"] += 1.0
        elif status in {"live_cancelled_unfilled", "cancelled_unfilled", "cancel_before_fill"}:
            cancelled_unfilled += 1
            stats["cancelled_unfilled_count"] += 1.0
        elif status == "live_filled":
            stats["filled_rows"] += 1.0
            stats["filled_pnl_usd"] += _safe_float(row.get("pnl_usd"), 0.0)
    return {
        "total_rows": len(rows),
        "skip_price_count": skip_price,
        "order_failed_count": order_failed,
        "cancelled_unfilled_count": cancelled_unfilled,
        "skip_rate": skip_price / float(total),
        "order_failure_rate": order_failed / float(total),
        "cancelled_unfilled_rate": cancelled_unfilled / float(total),
        "direction_stats": direction_stats,
    }


def _candidate_package_record(
    *,
    source: str,
    candidate: dict[str, Any] | None,
    active_candidate: dict[str, Any] | None,
    drag_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    profile = candidate.get("profile") if isinstance(candidate.get("profile"), dict) else {}
    if not profile:
        return None
    active_arr = _arr_for_candidate(active_candidate)
    arr = _arr_for_candidate(candidate)
    active_rows = max(1, int(_safe_float((active_candidate or {}).get("historical", {}).get("replay_live_filled_rows"), 1.0) or 1))
    validation_rows = max(0, int(_safe_float(candidate.get("historical", {}).get("replay_live_filled_rows"), 0.0) or 0))
    fill_retention = validation_rows / float(active_rows) if active_rows > 0 else 1.0
    fill_drop = max(0.0, 1.0 - fill_retention)
    arr_delta = arr["median_arr_pct"] - active_arr["median_arr_pct"]
    p05_delta = arr["p05_arr_pct"] - active_arr["p05_arr_pct"]
    current_scale = max(1.0, abs(active_arr["median_arr_pct"]))
    arr_delta_norm = (arr_delta / current_scale) * 100.0
    p05_delta_norm = (p05_delta / current_scale) * 100.0
    sample_bonus = min(20.0, float(validation_rows)) * 0.2
    raw_score = arr_delta_norm + (0.6 * p05_delta_norm) + sample_bonus
    skip_penalty = float(drag_context.get("skip_rate") or 0.0) + fill_drop
    order_failure_penalty = float(drag_context.get("order_failure_rate") or 0.0) + (0.5 * fill_drop)
    scoring = candidate.get("scoring") if isinstance(candidate.get("scoring"), dict) else {}
    evidence_band = str(
        candidate.get("evidence_band")
        or scoring.get("evidence_band")
        or _evidence_band_from_validation_rows(validation_rows)
    ).strip().lower()
    candidate_class = str(
        candidate.get("candidate_class")
        or scoring.get("candidate_class")
        or ("hold_current" if source == "active_profile" else "")
    ).strip().lower()
    candidate_class_reason_tags = list(
        candidate.get("candidate_class_reason_tags")
        or scoring.get("candidate_class_reason_tags")
        or []
    )
    generalization_ratio = _safe_float(
        scoring.get("generalization_ratio"),
        _safe_float(candidate.get("generalization_ratio"), 0.0),
    )
    execution_realism_score = _safe_float(
        candidate.get("execution_realism_score"),
        _safe_float(scoring.get("execution_realism_score"), None),
    )
    if execution_realism_score is None:
        evidence_weight = {"validated": 1.0, "candidate": 0.65, "exploratory": 0.35}.get(evidence_band, 0.35)
        execution_realism_score = min(
            1.0,
            max(
                0.0,
                (0.55 * min(1.0, fill_retention))
                + (0.25 * min(1.0, generalization_ratio))
                + (0.20 * evidence_weight),
            ),
        )
    candidate_priority = _candidate_class_rank(candidate_class)
    if candidate_priority < 0:
        candidate_priority = 1 if evidence_band == "validated" else 0
    validated_baseline_bonus = 0.0
    if source == "active_profile":
        validated_baseline_bonus += 12.0
    elif str(candidate.get("candidate_family") or "") == "regime_policy" and evidence_band == "validated":
        validated_baseline_bonus += 10.0
    elif evidence_band == "validated":
        validated_baseline_bonus += 4.0
    weak_realism_penalty = 0.0
    if candidate_class in {"probe_only", "suppress_cluster"} or evidence_band != "validated":
        weak_realism_penalty += max(0.0, 0.85 - float(execution_realism_score)) * 60.0
    if evidence_band == "exploratory":
        weak_realism_penalty += 8.0
    live_score = (
        raw_score
        - (45.0 * skip_penalty)
        - (45.0 * order_failure_penalty)
        + (candidate_priority * 6.0)
        + (float(execution_realism_score) * 12.0)
        + validated_baseline_bonus
        - weak_realism_penalty
    )
    session_policy = (
        _runtime_session_policy_from_overrides(candidate.get("session_overrides"))
        or list(candidate.get("recommended_session_policy") or [])
    )
    return {
        "source": source,
        "candidate_family": str(candidate.get("candidate_family") or "unknown"),
        "runtime_package": _runtime_package(profile=profile, session_policy=session_policy),
        "candidate": candidate,
        "median_arr_pct": round(arr["median_arr_pct"], 4),
        "p05_arr_pct": round(arr["p05_arr_pct"], 4),
        "median_arr_delta_pct": round(arr_delta, 4),
        "p05_arr_delta_pct": round(p05_delta, 4),
        "validation_live_filled_rows": validation_rows,
        "fill_retention_ratio": round(fill_retention, 4),
        "skip_rate_penalty": round(skip_penalty, 6),
        "order_failure_penalty": round(order_failure_penalty, 6),
        "candidate_class": candidate_class or None,
        "candidate_class_priority": int(candidate_priority),
        "candidate_class_reason_tags": candidate_class_reason_tags,
        "evidence_band": evidence_band,
        "generalization_ratio": round(generalization_ratio, 4),
        "execution_realism_score": round(float(execution_realism_score), 4),
        "validated_baseline_bonus": round(validated_baseline_bonus, 4),
        "weak_realism_penalty": round(weak_realism_penalty, 4),
        "raw_research_score": round(raw_score, 6),
        "live_execution_score": round(live_score, 6),
    }


def _rank_candidate_packages(
    *,
    active_candidate: dict[str, Any] | None,
    candidates: list[tuple[str, dict[str, Any] | None]],
    drag_context: dict[str, Any],
    min_fill_retention_ratio: float,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source, candidate in candidates:
        record = _candidate_package_record(
            source=source,
            candidate=candidate,
            active_candidate=active_candidate,
            drag_context=drag_context,
        )
        if record is None:
            continue
        signature = _package_signature(record.get("runtime_package"))
        if signature in seen:
            continue
        seen.add(signature)
        ranked.append(record)
    if not ranked:
        empty = {
            "source": "none",
            "candidate_family": "unknown",
            "runtime_package": {"profile": {}, "session_policy": []},
            "candidate": None,
            "median_arr_pct": 0.0,
            "p05_arr_pct": 0.0,
            "median_arr_delta_pct": 0.0,
            "p05_arr_delta_pct": 0.0,
            "validation_live_filled_rows": 0,
            "fill_retention_ratio": 0.0,
            "skip_rate_penalty": 0.0,
            "order_failure_penalty": 0.0,
            "candidate_class": None,
            "candidate_class_priority": 0,
            "evidence_band": "exploratory",
            "generalization_ratio": 0.0,
            "execution_realism_score": 0.0,
            "validated_baseline_bonus": 0.0,
            "weak_realism_penalty": 0.0,
            "raw_research_score": 0.0,
            "live_execution_score": 0.0,
        }
        return empty, empty, [], {
            "skip_price_count": int(drag_context.get("skip_price_count") or 0),
            "order_failed_count": int(drag_context.get("order_failed_count") or 0),
            "cancelled_unfilled_count": int(drag_context.get("cancelled_unfilled_count") or 0),
            "skip_rate": round(float(drag_context.get("skip_rate") or 0.0), 6),
            "order_failure_rate": round(float(drag_context.get("order_failure_rate") or 0.0), 6),
            "cancelled_unfilled_rate": round(float(drag_context.get("cancelled_unfilled_rate") or 0.0), 6),
            "sample_size_rows": int(drag_context.get("total_rows") or 0),
        }

    ranked.sort(
        key=lambda item: (
            float(item.get("raw_research_score") or 0.0),
            float(item.get("execution_realism_score") or 0.0),
            float(item.get("candidate_class_priority") or 0.0),
            float(item.get("median_arr_delta_pct") or 0.0),
            int(item.get("validation_live_filled_rows") or 0),
        ),
        reverse=True,
    )
    best_raw = ranked[0]
    live_eligible = [
        item
        for item in ranked
        if float(item.get("fill_retention_ratio") or 0.0) >= float(min_fill_retention_ratio)
    ] or list(ranked)
    live_eligible.sort(
        key=lambda item: (
            float(item.get("live_execution_score") or 0.0),
            float(item.get("execution_realism_score") or 0.0),
            float(item.get("candidate_class_priority") or 0.0),
            float(item.get("raw_research_score") or 0.0),
            int(item.get("validation_live_filled_rows") or 0),
        ),
        reverse=True,
    )
    best_live = live_eligible[0]
    drag_summary = {
        "skip_price_count": int(drag_context.get("skip_price_count") or 0),
        "order_failed_count": int(drag_context.get("order_failed_count") or 0),
        "cancelled_unfilled_count": int(drag_context.get("cancelled_unfilled_count") or 0),
        "skip_rate": round(float(drag_context.get("skip_rate") or 0.0), 6),
        "order_failure_rate": round(float(drag_context.get("order_failure_rate") or 0.0), 6),
        "cancelled_unfilled_rate": round(float(drag_context.get("cancelled_unfilled_rate") or 0.0), 6),
        "sample_size_rows": int(drag_context.get("total_rows") or 0),
        "best_live_fill_retention_ratio": float(best_live.get("fill_retention_ratio") or 0.0),
        "best_raw_fill_retention_ratio": float(best_raw.get("fill_retention_ratio") or 0.0),
        "winner_changed_due_to_execution_drag": bool(
            _package_signature(best_live.get("runtime_package")) != _package_signature(best_raw.get("runtime_package"))
        ),
    }
    return best_live, best_raw, ranked, drag_summary


def _one_sided_bias_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _execution_drag_context(rows)
    stats = summary.get("direction_stats") if isinstance(summary.get("direction_stats"), dict) else {}
    up = stats.get("UP") if isinstance(stats.get("UP"), dict) else {}
    down = stats.get("DOWN") if isinstance(stats.get("DOWN"), dict) else {}
    up_pnl = _safe_float(up.get("filled_pnl_usd"), 0.0)
    down_pnl = _safe_float(down.get("filled_pnl_usd"), 0.0)
    up_fills = int(_safe_float(up.get("filled_rows"), 0.0) or 0)
    down_fills = int(_safe_float(down.get("filled_rows"), 0.0) or 0)
    up_skip = int(_safe_float(up.get("skip_price_count"), 0.0) or 0)
    down_skip = int(_safe_float(down.get("skip_price_count"), 0.0) or 0)
    recommendation = "balanced_directional_bias"
    reason = "directional_performance_mixed"
    if down_pnl > 0.0 and up_pnl <= 0.0 and down_fills >= max(3, up_fills):
        recommendation = "tighten_down_and_suppress_up"
        reason = "down_is_profitable_while_up_is_non_positive"
    elif down_pnl > up_pnl and down_skip <= up_skip:
        recommendation = "suppress_up"
        reason = "up_underperforms_and_absorbs_more_skips"
    elif down_pnl > up_pnl:
        recommendation = "tighten_down"
        reason = "down_outperforms_up"
    return {
        "recommendation": recommendation,
        "reason": reason,
        "up_filled_pnl_usd": round(up_pnl, 4),
        "down_filled_pnl_usd": round(down_pnl, 4),
        "up_filled_rows": up_fills,
        "down_filled_rows": down_fills,
        "up_skip_price_count": up_skip,
        "down_skip_price_count": down_skip,
    }


def _promotion_decision(
    *,
    best: dict[str, Any] | None,
    current: dict[str, Any] | None,
    min_median_arr_improvement_pct: float,
    min_median_pnl_improvement_usd: float,
    min_replay_pnl_improvement_usd: float,
    max_profit_prob_drop: float,
    max_p95_drawdown_increase_usd: float,
    max_loss_hit_prob_increase: float,
    min_fill_lift: int,
    min_fill_retention_ratio: float,
) -> dict[str, Any]:
    if best is None or current is None:
        return {"action": "hold", "reason": "missing_candidate_data"}

    if _candidate_identity(best) == _candidate_identity(current):
        return {"action": "hold", "reason": "current_profile_is_best"}

    best_hist = best.get("historical") or {}
    current_hist = current.get("historical") or {}
    best_mc = best.get("monte_carlo") or {}
    current_mc = current.get("monte_carlo") or {}
    best_arr = _arr_for_candidate(best)
    current_arr = _arr_for_candidate(current)
    best_loss = policy_loss_from_candidate(best)
    current_loss = policy_loss_from_candidate(current)

    median_arr_delta = best_arr["median_arr_pct"] - current_arr["median_arr_pct"]
    median_pnl_delta = _safe_float(best_mc.get("median_total_pnl_usd")) - _safe_float(
        current_mc.get("median_total_pnl_usd")
    )
    replay_pnl_delta = _safe_float(best_hist.get("replay_live_filled_pnl_usd")) - _safe_float(
        current_hist.get("replay_live_filled_pnl_usd")
    )
    profit_prob_delta = _safe_float(best_mc.get("profit_probability")) - _safe_float(
        current_mc.get("profit_probability")
    )
    p95_drawdown_delta = _safe_float(best_mc.get("p95_max_drawdown_usd")) - _safe_float(
        current_mc.get("p95_max_drawdown_usd")
    )
    loss_hit_delta = _safe_float(best_mc.get("loss_limit_hit_probability")) - _safe_float(
        current_mc.get("loss_limit_hit_probability")
    )
    policy_loss_delta = _safe_float(current_loss.get("policy_loss"), 0.0) - _safe_float(
        best_loss.get("policy_loss"),
        0.0,
    )
    current_fill_rows = max(1, int(current_hist.get("replay_live_filled_rows") or 0))
    best_fill_rows = int(best_hist.get("replay_live_filled_rows") or 0)
    fill_lift = best_fill_rows - current_fill_rows
    fill_retention_ratio = best_fill_rows / float(current_fill_rows) if current_fill_rows > 0 else 1.0

    reasons: list[str] = []
    if policy_loss_delta <= 0.0:
        reasons.append(
            "policy_loss_not_improved:"
            f"{_safe_float(best_loss.get('policy_loss'), 0.0):.4f}"
            f">={_safe_float(current_loss.get('policy_loss'), 0.0):.4f}"
        )
    if median_arr_delta < min_median_arr_improvement_pct:
        reasons.append(
            f"median_arr_delta_below_threshold:{median_arr_delta:.4f}<{min_median_arr_improvement_pct:.4f}"
        )
    if median_pnl_delta < min_median_pnl_improvement_usd:
        reasons.append(
            f"median_pnl_delta_below_threshold:{median_pnl_delta:.4f}<{min_median_pnl_improvement_usd:.4f}"
        )
    if replay_pnl_delta < min_replay_pnl_improvement_usd:
        reasons.append(
            f"replay_pnl_delta_below_threshold:{replay_pnl_delta:.4f}<{min_replay_pnl_improvement_usd:.4f}"
        )
    if profit_prob_delta < -abs(max_profit_prob_drop):
        reasons.append(
            f"profit_probability_drop_too_large:{profit_prob_delta:.4f}<-{abs(max_profit_prob_drop):.4f}"
        )
    if p95_drawdown_delta > max_p95_drawdown_increase_usd:
        reasons.append(
            f"drawdown_increase_too_large:{p95_drawdown_delta:.4f}>{max_p95_drawdown_increase_usd:.4f}"
        )
    if loss_hit_delta > max_loss_hit_prob_increase:
        reasons.append(
            f"loss_hit_increase_too_large:{loss_hit_delta:.4f}>{max_loss_hit_prob_increase:.4f}"
        )
    if fill_lift < min_fill_lift and fill_retention_ratio < max(0.0, float(min_fill_retention_ratio)):
        reasons.append(
            "fill_retention_below_threshold:"
            f"{fill_retention_ratio:.4f}<{max(0.0, float(min_fill_retention_ratio)):.4f}"
        )

    decision = {
        "action": "promote" if not reasons else "hold",
        "reason": "promotion_thresholds_met" if not reasons else ";".join(reasons),
        "median_arr_delta_pct": round(median_arr_delta, 4),
        "historical_arr_delta_pct": round(best_arr["historical_arr_pct"] - current_arr["historical_arr_pct"], 4),
        "p05_arr_delta_pct": round(best_arr["p05_arr_pct"] - current_arr["p05_arr_pct"], 4),
        "median_pnl_delta_usd": round(median_pnl_delta, 4),
        "replay_pnl_delta_usd": round(replay_pnl_delta, 4),
        "profit_probability_delta": round(profit_prob_delta, 4),
        "p95_drawdown_delta_usd": round(p95_drawdown_delta, 4),
        "loss_hit_probability_delta": round(loss_hit_delta, 4),
        "current_policy_loss": round(_safe_float(current_loss.get("policy_loss"), 0.0), 4),
        "candidate_policy_loss": round(_safe_float(best_loss.get("policy_loss"), 0.0), 4),
        "policy_loss_delta": round(policy_loss_delta, 4),
        "current_policy_loss_components": current_loss,
        "candidate_policy_loss_components": best_loss,
        "fill_lift": int(fill_lift),
        "fill_retention_ratio": round(fill_retention_ratio, 4),
    }
    return decision


def render_strategy_env(target: dict[str, Any], metadata: dict[str, Any]) -> str:
    base_profile = target.get("base_profile") if isinstance(target.get("base_profile"), dict) else None
    profile = base_profile or (target.get("profile") if isinstance(target.get("profile"), dict) else target)
    candidate_profile = target.get("profile") if isinstance(target.get("profile"), dict) else profile
    session_overrides = _normalized_session_overrides(target.get("session_overrides"))
    session_policy = _runtime_session_policy_from_overrides(session_overrides)

    def _directional_caps() -> list[float]:
        caps: list[float] = []

        def _append_caps(record: dict[str, Any] | None) -> None:
            if not isinstance(record, dict):
                return
            for key in ("up_max_buy_price", "down_max_buy_price"):
                value = _safe_float(record.get(key), None)
                if value is not None and value > 0:
                    caps.append(float(value))

        _append_caps(profile if isinstance(profile, dict) else None)
        for override in session_overrides:
            override_profile = override.get("profile") if isinstance(override, dict) else None
            _append_caps(override_profile if isinstance(override_profile, dict) else None)
        return caps

    current_min_buy_price = _safe_float(metadata.get("current_min_buy_price"), None)
    runtime_min_buy_price = None
    if current_min_buy_price is not None:
        caps = _directional_caps()
        if caps:
            compatible_floor = round(min(caps), 2)
            if current_min_buy_price > compatible_floor:
                runtime_min_buy_price = compatible_floor

    lines = [
        "# Managed by scripts/run_btc5_autoresearch_cycle.py",
        f"# generated_at={metadata['generated_at']}",
        f"# candidate={candidate_profile.get('name')}",
        f"# reason={metadata['reason']}",
        f"BTC5_MAX_ABS_DELTA={profile.get('max_abs_delta')}",
        f"BTC5_UP_MAX_BUY_PRICE={profile.get('up_max_buy_price')}",
        f"BTC5_DOWN_MAX_BUY_PRICE={profile.get('down_max_buy_price')}",
        f"BTC5_PROBE_MAX_ABS_DELTA={profile.get('max_abs_delta')}",
        f"BTC5_PROBE_UP_MAX_BUY_PRICE={profile.get('up_max_buy_price')}",
        f"BTC5_PROBE_DOWN_MAX_BUY_PRICE={profile.get('down_max_buy_price')}",
        f"BTC5_SESSION_OVERRIDES_JSON={json.dumps(session_overrides, separators=(',', ':'))}",
        f"BTC5_SESSION_POLICY_JSON={json.dumps(session_policy, separators=(',', ':'))}",
    ]
    if runtime_min_buy_price is not None:
        lines.append(f"BTC5_MIN_BUY_PRICE={runtime_min_buy_price:.2f}")
    return "\n".join(lines) + "\n"


def _write_override_env(path: Path, *, best_target: dict[str, Any], decision: dict[str, Any]) -> None:
    existing_values = _load_env_file(path)
    write_text_atomic(
        path,
        render_strategy_env(
            best_target,
            {
                "generated_at": _now_utc().isoformat(),
                "reason": decision.get("reason"),
                "current_min_buy_price": existing_values.get("BTC5_MIN_BUY_PRICE")
                or os.environ.get("BTC5_MIN_BUY_PRICE"),
            },
        ),
        encoding="utf-8",
    )


def _restart_service(service_name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    active = subprocess.run(
        ["sudo", "systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "restart_returncode": result.returncode,
        "restart_stderr_tail": (result.stderr or "").strip()[-300:],
        "restart_stdout_tail": (result.stdout or "").strip()[-300:],
        "service_state": (active.stdout or "").strip(),
    }


def _runtime_load_status(
    *,
    override_env_path: Path,
    restart_on_promote: bool,
    decision_action: str,
    restart_result: dict[str, Any] | None,
) -> dict[str, Any]:
    override_values = _load_env_file(override_env_path)
    session_policy_records = len(_runtime_session_policy_from_env(override_values))
    return {
        "override_env_written": bool(override_values),
        "override_env_path": str(override_env_path),
        "session_policy_records": session_policy_records,
        "base_env_changed": False,
        "service_restart_requested": bool(
            str(decision_action or "").strip().lower() == "promote" and restart_on_promote
        ),
        "service_restart_state": (
            str((restart_result or {}).get("service_state") or "").strip() or None
        ),
    }


def _write_reports(report_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    markdown = render_cycle_markdown(payload)
    return _shared_write_versioned_cycle_reports(
        report_dir=report_dir,
        payload=payload,
        markdown=markdown,
    )


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _load_fill_feedback_state(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {
            "last_cycle_completed_at": None,
            "last_window_start_ts": 0,
            "last_updated_at": None,
        }
    return {
        "last_cycle_completed_at": payload.get("last_cycle_completed_at"),
        "last_window_start_ts": int(_safe_float(payload.get("last_window_start_ts"), 0.0) or 0),
        "last_updated_at": payload.get("last_updated_at"),
    }


def _db_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows if len(row) >= 2}


def _db_window_rows_since(db_path: Path, state: dict[str, Any]) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    if not db_path.exists():
        return [], 0, {"status": "db_missing", "db_path": str(db_path)}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='window_trades'"
        ).fetchone()
        if table_exists is None:
            return [], 0, {"status": "table_missing", "table": "window_trades"}

        columns = _db_table_columns(conn, "window_trades")
        if "order_status" not in columns:
            return [], 0, {"status": "order_status_missing", "columns": sorted(columns)}

        since_window_ts = int(_safe_float(state.get("last_window_start_ts"), 0.0) or 0)
        since_updated_at = str(state.get("last_updated_at") or "").strip()
        time_filters: list[str] = []
        params: list[Any] = []
        if since_window_ts > 0 and "window_start_ts" in columns:
            time_filters.append("window_start_ts > ?")
            params.append(since_window_ts)
        if since_updated_at:
            if "updated_at" in columns:
                time_filters.append("updated_at > ?")
                params.append(since_updated_at)
            elif "created_at" in columns:
                time_filters.append("created_at > ?")
                params.append(since_updated_at)

        where_sql = "1=1"
        if time_filters:
            where_sql = "(" + " OR ".join(time_filters) + ")"

        selected_columns = [
            column
            for column in ("window_start_ts", "updated_at", "created_at", "order_status", "direction", "won", "pnl_usd")
            if column in columns
        ]
        if not selected_columns:
            return [], 0, {"status": "no_usable_columns", "columns": sorted(columns)}
        select_sql = ", ".join(selected_columns)

        fill_query = (
            f"SELECT {select_sql} FROM window_trades "
            f"WHERE order_status = 'live_filled' AND {where_sql} "
            "ORDER BY COALESCE(window_start_ts, 0) ASC"
        )
        fill_rows = [dict(row) for row in conn.execute(fill_query, params).fetchall()]

        total_query = f"SELECT COUNT(1) AS row_count FROM window_trades WHERE {where_sql}"
        total_row = conn.execute(total_query, params).fetchone()
        total_rows = int(total_row["row_count"]) if total_row is not None else 0

        diagnostics = {
            "status": "ok",
            "db_path": str(db_path),
            "filters_applied": time_filters,
            "since_window_start_ts": since_window_ts,
            "since_updated_at": since_updated_at or None,
            "selected_columns": selected_columns,
        }
        return fill_rows, total_rows, diagnostics
    finally:
        conn.close()


def _prediction_metrics_from_candidate(
    *,
    best_candidate: dict[str, Any] | None,
    selected_frontier_item: dict[str, Any] | None,
    decision: dict[str, Any],
) -> dict[str, float | None]:
    candidate = best_candidate if isinstance(best_candidate, dict) else {}
    frontier = selected_frontier_item if isinstance(selected_frontier_item, dict) else {}
    historical = candidate.get("historical") if isinstance(candidate.get("historical"), dict) else {}
    monte_carlo = candidate.get("monte_carlo") if isinstance(candidate.get("monte_carlo"), dict) else {}

    replay_rows = int(_safe_float(historical.get("replay_live_filled_rows"), 0.0) or 0)
    replay_pnl = _safe_float(historical.get("replay_live_filled_pnl_usd"), None)
    predicted_pnl_per_fill = (float(replay_pnl) / float(replay_rows)) if replay_rows > 0 and replay_pnl is not None else None

    predicted_fill_rate = _safe_float(
        frontier.get("fill_retention_ratio"),
        _safe_float(decision.get("fill_retention_ratio"), None),
    )
    predicted_direction_accuracy = _safe_float(monte_carlo.get("profit_probability"), None)
    return {
        "fill_rate": float(predicted_fill_rate) if predicted_fill_rate is not None else None,
        "direction_accuracy": float(predicted_direction_accuracy) if predicted_direction_accuracy is not None else None,
        "pnl_per_fill": round(float(predicted_pnl_per_fill), 6) if predicted_pnl_per_fill is not None else None,
    }


def _actual_metrics_from_fill_rows(fill_rows: list[dict[str, Any]], *, total_rows: int) -> dict[str, float | int | None]:
    fills = len(fill_rows)
    pnl_values = [_safe_float(row.get("pnl_usd"), 0.0) for row in fill_rows]
    wins = 0
    resolved = 0
    for row in fill_rows:
        won = row.get("won")
        if isinstance(won, bool):
            resolved += 1
            wins += int(won)
            continue
        pnl = _safe_float(row.get("pnl_usd"), None)
        if pnl is None:
            continue
        resolved += 1
        wins += int(pnl > 0.0)
    fill_rate = (fills / float(total_rows)) if total_rows > 0 else None
    direction_accuracy = (wins / float(resolved)) if resolved > 0 else None
    pnl_per_fill = (sum(pnl_values) / float(fills)) if fills > 0 else None
    return {
        "fills": fills,
        "resolved_fills": resolved,
        "total_rows_considered": int(total_rows),
        "fill_rate": round(float(fill_rate), 6) if fill_rate is not None else None,
        "direction_accuracy": round(float(direction_accuracy), 6) if direction_accuracy is not None else None,
        "pnl_per_fill": round(float(pnl_per_fill), 6) if pnl_per_fill is not None else None,
        "pnl_usd_total": round(float(sum(pnl_values)), 6),
    }


def _delta_series(rows: list[dict[str, Any]], metric_name: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        fill_feedback = row.get("fill_feedback")
        if not isinstance(fill_feedback, dict):
            continue
        metric_deltas = fill_feedback.get("metric_deltas")
        if not isinstance(metric_deltas, dict):
            continue
        value = _safe_float(metric_deltas.get(metric_name), None)
        if value is None:
            continue
        values.append(float(value))
    return values


def _metric_sigma(delta_history: list[float], default_sigma: float) -> float:
    if len(delta_history) >= 2:
        sigma = pstdev(delta_history)
        if sigma > 0.0:
            return float(sigma)
    return float(default_sigma)


def _fill_feedback_summary(
    *,
    db_path: Path,
    feedback_state_path: Path,
    cycles_jsonl_path: Path,
    best_candidate: dict[str, Any] | None,
    selected_frontier_item: dict[str, Any] | None,
    decision: dict[str, Any],
    generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = _load_fill_feedback_state(feedback_state_path)
    fill_rows, total_rows, diagnostics = _db_window_rows_since(db_path, state)
    actual = _actual_metrics_from_fill_rows(fill_rows, total_rows=total_rows)
    predicted = _prediction_metrics_from_candidate(
        best_candidate=best_candidate,
        selected_frontier_item=selected_frontier_item,
        decision=decision,
    )

    metric_deltas: dict[str, float | None] = {}
    for key in ("fill_rate", "direction_accuracy", "pnl_per_fill"):
        actual_value = _safe_float(actual.get(key), None)
        predicted_value = _safe_float(predicted.get(key), None)
        if actual_value is None or predicted_value is None:
            metric_deltas[key] = None
            continue
        metric_deltas[key] = round(float(actual_value) - float(predicted_value), 6)

    history_rows = _load_jsonl_rows(cycles_jsonl_path)
    sigma_defaults = {"fill_rate": 0.03, "direction_accuracy": 0.05, "pnl_per_fill": 0.35}
    sigma_summary: dict[str, float] = {}
    adjustment_flags: list[dict[str, Any]] = []
    for metric_name, default_sigma in sigma_defaults.items():
        delta = _safe_float(metric_deltas.get(metric_name), None)
        if delta is None:
            sigma_summary[metric_name] = float(default_sigma)
            continue
        series = _delta_series(history_rows, metric_name)[-48:]
        sigma = _metric_sigma(series, default_sigma)
        sigma_summary[metric_name] = round(float(sigma), 6)
        if abs(float(delta)) > (2.0 * sigma):
            direction = "upward" if float(delta) > 0 else "downward"
            adjustment_flags.append(
                {
                    "metric": metric_name,
                    "delta": round(float(delta), 6),
                    "sigma": round(float(sigma), 6),
                    "threshold": round(float(2.0 * sigma), 6),
                    "direction": direction,
                    "reason": f"{metric_name}_diverges_beyond_2sigma",
                }
            )

    latest_window_start_ts = max(int(_safe_float(row.get("window_start_ts"), 0.0) or 0) for row in fill_rows) if fill_rows else int(
        _safe_float(state.get("last_window_start_ts"), 0.0) or 0
    )
    latest_updated_raw = state.get("last_updated_at")
    latest_updated_ts = _parse_iso_timestamp(latest_updated_raw)
    for row in fill_rows:
        for raw in (row.get("updated_at"), row.get("created_at")):
            parsed = _parse_iso_timestamp(raw)
            if parsed is None:
                continue
            if latest_updated_ts is None or parsed > latest_updated_ts:
                latest_updated_ts = parsed

    feedback_summary = {
        "generated_at": generated_at,
        "actual_metrics": actual,
        "predicted_metrics": predicted,
        "metric_deltas": metric_deltas,
        "metric_sigma": sigma_summary,
        "parameter_adjustment_flags": adjustment_flags,
        "needs_parameter_adjustment": bool(adjustment_flags),
        "db_diagnostics": diagnostics,
        "state_before": state,
    }
    state_after = {
        "last_cycle_completed_at": generated_at,
        "last_window_start_ts": int(latest_window_start_ts),
        "last_updated_at": latest_updated_ts.isoformat() if latest_updated_ts is not None else latest_updated_raw,
    }
    return feedback_summary, state_after


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_mode_argument(
        parser,
        help_text=(
            "Execution mode: full runs full Monte Carlo/regime sweeps; analyze/quick cap sweep width "
            "for cheap local iteration."
        ),
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--top-grid-candidates", type=int, default=5)
    parser.add_argument("--min-replay-fills", type=int, default=12)
    parser.add_argument("--loss-limit-usd", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--restart-on-promote", action="store_true")
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument("--archive-glob", default="reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv")
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--remote-cache-json", type=Path, default=Path("reports/tmp_remote_btc5_window_rows.json"))
    parser.add_argument("--min-median-arr-improvement-pct", type=float, default=0.0)
    parser.add_argument("--min-median-pnl-improvement-usd", type=float, default=2.0)
    parser.add_argument("--min-replay-pnl-improvement-usd", type=float, default=1.0)
    parser.add_argument("--max-profit-prob-drop", type=float, default=0.01)
    parser.add_argument("--max-p95-drawdown-increase-usd", type=float, default=3.0)
    parser.add_argument("--max-loss-hit-prob-increase", type=float, default=0.03)
    parser.add_argument("--min-fill-lift", type=int, default=0)
    parser.add_argument("--min-fill-retention-ratio", type=float, default=0.85)
    parser.add_argument("--regime-min-session-rows", type=int, default=6)
    parser.add_argument("--regime-max-session-overrides", type=int, default=2)
    parser.add_argument("--regime-top-single-overrides-per-session", type=int, default=2)
    parser.add_argument("--regime-max-composed-candidates", type=int, default=64)
    parser.add_argument("--hypothesis-summary", type=Path, default=DEFAULT_HYPOTHESIS_SUMMARY)
    parser.add_argument("--regime-policy-summary", type=Path, default=DEFAULT_REGIME_POLICY_SUMMARY)
    parser.add_argument("--current-probe-latest", type=Path, default=DEFAULT_CURRENT_PROBE_LATEST)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--frontier-latest", type=Path, default=DEFAULT_FRONTIER_LATEST)
    parser.add_argument("--market-policy-handoff", type=Path, default=DEFAULT_MARKET_POLICY_HANDOFF)
    parser.add_argument("--market-latest-json", type=Path, default=DEFAULT_MARKET_LATEST_JSON)
    parser.add_argument("--semantic-dedup-index", type=Path, default=DEFAULT_SEMANTIC_DEDUP_INDEX)
    parser.add_argument("--cycles-jsonl", type=Path, default=DEFAULT_AUTORESEARCH_CYCLES_JSONL)
    parser.add_argument("--fill-feedback-state", type=Path, default=DEFAULT_FILL_FEEDBACK_STATE)
    return parser.parse_args()


def _effective_mode_limits(args: argparse.Namespace, mode: str) -> tuple[int, int, int]:
    effective_paths = cap_for_mode(int(args.paths), mode=mode, analyze_cap=ANALYZE_MAX_PATHS, floor=1)
    effective_top_grid_candidates = cap_for_mode(
        int(args.top_grid_candidates),
        mode=mode,
        analyze_cap=ANALYZE_MAX_TOP_GRID_CANDIDATES,
        floor=1,
    )
    effective_regime_max_composed_candidates = cap_for_mode(
        int(args.regime_max_composed_candidates),
        mode=mode,
        analyze_cap=ANALYZE_MAX_REGIME_COMPOSED_CANDIDATES,
        floor=0,
    )
    return (
        effective_paths,
        effective_top_grid_candidates,
        effective_regime_max_composed_candidates,
    )


def main() -> int:
    args = parse_args()
    mode = normalize_mode(args.mode)
    (
        effective_paths,
        effective_top_grid_candidates,
        effective_regime_max_composed_candidates,
    ) = _effective_mode_limits(
        args,
        mode,
    )
    base_env = _load_env_file(args.strategy_env)
    merged_env = _merged_strategy_env(args.strategy_env, args.override_env)
    active_profile = _profile_from_env("current_live_profile", merged_env)
    runtime_profile = _profile_from_env("runtime_recommended", merged_env)

    rows, baseline = assemble_observed_rows(
        db_path=args.db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    horizon_trades = max(len(rows), 40)
    global_summary = build_global_summary(
        rows=rows,
        db_path=args.db_path,
        current_live_profile=active_profile,
        runtime_recommended_profile=runtime_profile,
        paths=effective_paths,
        horizon_trades=horizon_trades,
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        top_grid_candidates=effective_top_grid_candidates,
        min_replay_fills=max(1, int(args.min_replay_fills)),
    )
    global_summary["baseline"] = baseline
    regime_policy_summary = build_regime_policy_summary(
        rows=rows,
        db_path=args.db_path,
        current_live_profile=active_profile,
        runtime_recommended_profile=runtime_profile,
        paths=effective_paths,
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        min_replay_fills=max(1, int(args.min_replay_fills)),
        min_session_rows=max(1, int(args.regime_min_session_rows)),
        max_session_overrides=max(1, int(args.regime_max_session_overrides)),
        top_single_overrides_per_session=max(1, int(args.regime_top_single_overrides_per_session)),
        max_composed_candidates=effective_regime_max_composed_candidates,
    )
    regime_policy_summary["baseline"] = baseline
    hypothesis_summary = _load_json(args.hypothesis_summary) or {}
    latest_regime_summary = _load_json(args.regime_policy_summary) or {}
    prior_standard_latest = _load_json(args.report_dir / "latest.json") or {}
    current_probe_latest = _load_json(args.current_probe_latest) or {}
    runtime_truth = _load_json(args.runtime_truth) or {}

    current_candidate = _normalize_global_candidate(_find_candidate(global_summary, "current_live_profile"))
    if current_candidate is None:
        current_candidate = _merge_candidate_metadata(
            _normalize_regime_candidate(regime_policy_summary.get("current_policy")),
            metadata=regime_policy_summary.get("hold_current_candidate"),
        )
    global_best_candidate = _normalize_global_candidate(global_summary.get("best_candidate"))
    regime_best_candidate = _merge_candidate_metadata(
        _normalize_regime_candidate(regime_policy_summary.get("best_policy")),
        metadata=regime_policy_summary.get("best_candidate"),
    )
    hypothesis_best_candidate = _build_hypothesis_candidate(hypothesis_summary)
    semantic_dedup_index = _load_semantic_dedup_index(args.semantic_dedup_index)
    candidate_pool = [
        ("active_profile", current_candidate),
        ("global_best_candidate", global_best_candidate),
        ("regime_best_candidate", regime_best_candidate),
        ("hypothesis_best_candidate", hypothesis_best_candidate),
    ]
    deduped_candidate_pool, dedup_skipped_candidates, dedup_kept_hashes = _dedupe_candidate_evaluations(
        candidate_pool,
        dedup_index=semantic_dedup_index,
        now=_now_utc(),
    )
    if not deduped_candidate_pool and current_candidate is not None:
        deduped_candidate_pool = [("active_profile", current_candidate)]
        dedup_skipped_candidates.append(
            {
                "source": "fallback",
                "reason": "all_candidates_deduped_using_active_profile_fallback",
            }
        )
    deduped_source_candidates = {source: candidate for source, candidate in deduped_candidate_pool}
    drag_context = _execution_drag_context(rows)
    best_live_package_record, best_raw_package_record, ranked_packages, execution_drag_summary = _rank_candidate_packages(
        active_candidate=current_candidate,
        candidates=deduped_candidate_pool,
        drag_context=drag_context,
        min_fill_retention_ratio=float(args.min_fill_retention_ratio),
    )
    best_live_candidate = best_live_package_record.get("candidate") if isinstance(best_live_package_record, dict) else None
    best_candidate, decision, evaluated_targets = _select_best_target(
        candidates=[
            ("best_live_package", best_live_candidate),
            ("global_best_candidate", deduped_source_candidates.get("global_best_candidate")),
            ("regime_best_candidate", deduped_source_candidates.get("regime_best_candidate")),
            ("hypothesis_best_candidate", deduped_source_candidates.get("hypothesis_best_candidate")),
        ],
        current=current_candidate,
        min_median_arr_improvement_pct=float(args.min_median_arr_improvement_pct),
        min_median_pnl_improvement_usd=float(args.min_median_pnl_improvement_usd),
        min_replay_pnl_improvement_usd=float(args.min_replay_pnl_improvement_usd),
        max_profit_prob_drop=float(args.max_profit_prob_drop),
        max_p95_drawdown_increase_usd=float(args.max_p95_drawdown_increase_usd),
        max_loss_hit_prob_increase=float(args.max_loss_hit_prob_increase),
        min_fill_lift=int(args.min_fill_lift),
        min_fill_retention_ratio=float(args.min_fill_retention_ratio),
    )
    validation_live_filled_rows = _extract_validation_rows(best_candidate)
    generalization_ratio = _extract_generalization_ratio(
        best_candidate,
        hypothesis_summary=hypothesis_summary,
    )
    package_missing_evidence: list[str] = []
    if validation_live_filled_rows < 6:
        package_missing_evidence.append("validation_live_filled_rows_below_6")
    if generalization_ratio < 0.80:
        package_missing_evidence.append("generalization_ratio_below_0.80")
    if _safe_float(decision.get("median_arr_delta_pct"), 0.0) <= 0:
        package_missing_evidence.append("median_arr_delta_not_positive")
    if _safe_float(decision.get("profit_probability_delta"), 0.0) < -0.01:
        package_missing_evidence.append("profit_probability_delta_below_-0.01")
    if _safe_float(decision.get("p95_drawdown_delta_usd"), 0.0) > 3.0:
        package_missing_evidence.append("p95_drawdown_delta_above_3.0")

    initial_decision = dict(decision)
    initial_current_probe = _current_probe_payload_fields(
        rows=rows,
        prior_probe_payload=current_probe_latest,
        hypothesis_summary=hypothesis_summary,
        regime_policy_summary=latest_regime_summary,
        validation_live_filled_rows=validation_live_filled_rows,
        package_missing_evidence=package_missing_evidence,
        decision=decision,
    )
    decision = _probe_gated_decision(
        decision=decision,
        current_probe=initial_current_probe,
    )
    if bool(decision.get("probe_gate_applied")):
        for tag in decision.get("probe_gate_reason_tags") or []:
            normalized_tag = str(tag or "").strip()
            if normalized_tag and normalized_tag not in package_missing_evidence:
                package_missing_evidence.append(normalized_tag)
    if (
        str(decision.get("action") or "").strip().lower() != str(initial_decision.get("action") or "").strip().lower()
        or str(decision.get("reason") or "").strip() != str(initial_decision.get("reason") or "").strip()
    ):
        current_probe = _current_probe_payload_fields(
            rows=rows,
            prior_probe_payload=current_probe_latest,
            hypothesis_summary=hypothesis_summary,
            regime_policy_summary=latest_regime_summary,
            validation_live_filled_rows=validation_live_filled_rows,
            package_missing_evidence=package_missing_evidence,
            decision=decision,
        )
    else:
        current_probe = initial_current_probe

    package_confidence_label, package_confidence_reasons = _package_confidence(
        validation_live_filled_rows=validation_live_filled_rows,
        generalization_ratio=generalization_ratio,
    )
    deploy_recommendation = _deploy_recommendation(
        decision_action=str(decision.get("action") or "hold"),
        decision=decision,
        validation_live_filled_rows=validation_live_filled_rows,
        generalization_ratio=generalization_ratio,
    )
    probe_feedback = _probe_feedback_adjustment(
        package_confidence_label=package_confidence_label,
        deploy_recommendation=deploy_recommendation,
        current_probe=current_probe,
    )
    best_session_policy = (
        _runtime_session_policy_from_overrides((best_candidate or {}).get("session_overrides"))
        or list((latest_regime_summary or {}).get("recommended_session_policy") or [])
        or list((hypothesis_summary or {}).get("recommended_session_policy") or [])
    )
    active_session_policy = _runtime_session_policy_from_env(merged_env)
    active_runtime_package = _runtime_package(
        profile={
            "name": active_profile.name,
            "max_abs_delta": active_profile.max_abs_delta,
            "up_max_buy_price": active_profile.up_max_buy_price,
            "down_max_buy_price": active_profile.down_max_buy_price,
        },
        session_policy=active_session_policy,
    )
    best_runtime_package = _runtime_package(
        profile=(best_candidate or {}).get("profile") or {},
        session_policy=best_session_policy,
    )
    frontier_input_payload = {
        "generated_at": _now_utc().isoformat(),
        "active_runtime_package": active_runtime_package,
        "selected_active_runtime_package": active_runtime_package,
        "best_runtime_package": best_runtime_package,
        "selected_best_runtime_package": best_runtime_package,
        "package_ranking": {"ranked_packages": ranked_packages},
    }
    frontier_report = _load_or_build_frontier_report(
        cycle_payload=frontier_input_payload,
        frontier_latest_path=args.frontier_latest,
        market_policy_handoff=args.market_policy_handoff,
        market_latest_json=args.market_latest_json,
    )
    size_aware_deployment = _size_aware_deployment_summary(
        candidate=best_candidate,
        simulation_summary=global_summary,
        current_candidate=current_candidate,
        global_best_candidate=global_best_candidate,
    )
    package_ranking = _build_package_ranking(
        ranked_packages=ranked_packages,
        current_probe=current_probe,
        frontier_report=frontier_report,
    )
    ranked_package_items = (
        package_ranking.get("ranked_packages") if isinstance(package_ranking.get("ranked_packages"), list) else []
    )
    selected_frontier_item = ranked_package_items[0] if ranked_package_items and isinstance(ranked_package_items[0], dict) else {}
    if selected_frontier_item.get("runtime_package"):
        best_runtime_package = dict(selected_frontier_item.get("runtime_package") or {})
    selected_policy_loss = _safe_float(selected_frontier_item.get("frontier_policy_loss"), None)
    incumbent_policy_loss = _safe_float(frontier_report.get("incumbent_policy_loss"), None)
    selected_policy_components = dict(selected_frontier_item.get("policy_components") or {})
    policy_benchmark = {
        "ranking_metric": "frontier_policy_loss_lower_is_better_probe_penalty_bounded",
        "selected_source": str(selected_frontier_item.get("selection_source") or "frontier_policy_loss"),
        "selected_family": str(decision.get("selected_family") or "unknown"),
        "current_policy_id": runtime_package_id(active_runtime_package),
        "candidate_policy_id": runtime_package_id(best_runtime_package),
        "current_policy_loss": round(_safe_float(incumbent_policy_loss, _safe_float(decision.get("current_policy_loss"), 0.0)), 4),
        "candidate_policy_loss": round(_safe_float(selected_policy_loss, _safe_float(decision.get("candidate_policy_loss"), 0.0)), 4),
        "policy_loss_delta": round(
            _safe_float(
                (incumbent_policy_loss - selected_policy_loss)
                if incumbent_policy_loss is not None and selected_policy_loss is not None
                else decision.get("policy_loss_delta"),
                0.0,
            ),
            4,
        ),
        "current_policy_loss_components": dict(decision.get("current_policy_loss_components") or {}),
        "candidate_policy_loss_components": (
            selected_policy_components or dict(decision.get("candidate_policy_loss_components") or {})
        ),
        "current_market_model_version": frontier_report.get("current_market_model_version"),
        "selected_package_hash": selected_frontier_item.get("package_hash"),
        "frontier_gap_vs_best": selected_frontier_item.get("frontier_gap_vs_best"),
        "frontier_gap_vs_incumbent": selected_frontier_item.get("frontier_gap_vs_incumbent"),
    }
    package_class_summary = _package_class_summary(package_ranking, best_runtime_package)
    restart_result: dict[str, Any] | None = None
    if decision["action"] == "promote" and best_candidate is not None:
        _write_override_env(
            args.override_env,
            best_target=best_candidate,
            decision=decision,
        )
        if args.restart_on_promote:
            restart_result = _restart_service(str(args.service_name))

    payload = {
        "generated_at": _now_utc().isoformat(),
        "execution_mode": {
            "requested": str(args.mode),
            "effective": mode,
            "effective_paths": effective_paths,
            "effective_top_grid_candidates": effective_top_grid_candidates,
            "effective_regime_max_composed_candidates": effective_regime_max_composed_candidates,
        },
        "base_strategy_env": str(args.strategy_env),
        "override_env": str(args.override_env),
        "base_strategy_values": base_env,
        "active_profile": {
            "name": active_profile.name,
            "max_abs_delta": active_profile.max_abs_delta,
            "up_max_buy_price": active_profile.up_max_buy_price,
            "down_max_buy_price": active_profile.down_max_buy_price,
        },
        "decision": decision,
        "deploy_recommendation": deploy_recommendation,
        "package_confidence_label": package_confidence_label,
        "package_confidence_reasons": package_confidence_reasons,
        "validation_live_filled_rows": int(validation_live_filled_rows),
        "generalization_ratio": round(float(generalization_ratio), 4),
        "package_missing_evidence": package_missing_evidence,
        "active_runtime_package": active_runtime_package,
        "best_runtime_package": best_runtime_package,
        "arr_tracking": _arr_tracking(best_candidate, current_candidate),
        "recommended_session_policy": best_session_policy,
        "best_candidate": best_candidate,
        "current_candidate": current_candidate,
        "global_best_candidate": global_best_candidate,
        "regime_best_candidate": regime_best_candidate,
        "hypothesis_best_candidate": hypothesis_best_candidate,
        "policy_benchmark": policy_benchmark,
        "frontier_ranking": frontier_report,
        "promotion_candidates": evaluated_targets,
        "best_live_package": {
            "source": best_live_package_record.get("source"),
            "candidate_family": best_live_package_record.get("candidate_family"),
            "runtime_package": best_live_package_record.get("runtime_package"),
            "median_arr_delta_pct": best_live_package_record.get("median_arr_delta_pct"),
            "p05_arr_delta_pct": best_live_package_record.get("p05_arr_delta_pct"),
            "fill_retention_ratio": best_live_package_record.get("fill_retention_ratio"),
            "skip_rate_penalty": best_live_package_record.get("skip_rate_penalty"),
            "order_failure_penalty": best_live_package_record.get("order_failure_penalty"),
            "validation_live_filled_rows": best_live_package_record.get("validation_live_filled_rows"),
            "candidate_class": best_live_package_record.get("candidate_class"),
            "evidence_band": best_live_package_record.get("evidence_band"),
            "execution_realism_score": best_live_package_record.get("execution_realism_score"),
            "validated_baseline_bonus": best_live_package_record.get("validated_baseline_bonus"),
            "weak_realism_penalty": best_live_package_record.get("weak_realism_penalty"),
            "live_execution_score": best_live_package_record.get("live_execution_score"),
        },
        "best_raw_research_package": {
            "source": best_raw_package_record.get("source"),
            "candidate_family": best_raw_package_record.get("candidate_family"),
            "runtime_package": best_raw_package_record.get("runtime_package"),
            "median_arr_delta_pct": best_raw_package_record.get("median_arr_delta_pct"),
            "p05_arr_delta_pct": best_raw_package_record.get("p05_arr_delta_pct"),
            "fill_retention_ratio": best_raw_package_record.get("fill_retention_ratio"),
            "skip_rate_penalty": best_raw_package_record.get("skip_rate_penalty"),
            "order_failure_penalty": best_raw_package_record.get("order_failure_penalty"),
            "validation_live_filled_rows": best_raw_package_record.get("validation_live_filled_rows"),
            "candidate_class": best_raw_package_record.get("candidate_class"),
            "evidence_band": best_raw_package_record.get("evidence_band"),
            "execution_realism_score": best_raw_package_record.get("execution_realism_score"),
            "validated_baseline_bonus": best_raw_package_record.get("validated_baseline_bonus"),
            "weak_realism_penalty": best_raw_package_record.get("weak_realism_penalty"),
            "raw_research_score": best_raw_package_record.get("raw_research_score"),
        },
        "ranked_runtime_packages": ranked_packages,
        "package_ranking": package_ranking,
        "semantic_dedup": {
            "index_path": str(args.semantic_dedup_index),
            "kept_candidate_hashes": dedup_kept_hashes,
            "skipped_candidates": dedup_skipped_candidates,
            "kept_candidates": [source for source, _ in deduped_candidate_pool],
        },
        "package_class": package_class_summary.get("package_class"),
        "package_candidate_class": package_class_summary.get("candidate_class"),
        "package_class_reason": package_class_summary.get("class_reason"),
        "package_class_reason_tags": package_class_summary.get("class_reason_tags"),
        "package_class_rank": package_class_summary.get("rank"),
        "package_class_source": package_class_summary.get("source"),
        "package_class_profile_name": package_class_summary.get("profile_name"),
        "package_class_matched_runtime_package": package_class_summary.get("matched_runtime_package"),
        "execution_drag_summary": execution_drag_summary,
        "one_sided_bias_recommendation": _one_sided_bias_recommendation(rows),
        "size_aware_deployment": size_aware_deployment,
        "simulation_summary": global_summary,
        "regime_policy_summary": regime_policy_summary,
        "service_restart": restart_result,
        "runtime_load_status": _runtime_load_status(
            override_env_path=args.override_env,
            restart_on_promote=bool(args.restart_on_promote),
            decision_action=str(decision.get("action") or ""),
            restart_result=restart_result,
        ),
        "probe_feedback": probe_feedback,
        "current_probe_path": str(args.current_probe_latest),
    }
    payload = _attach_current_probe_fields(payload, current_probe)
    trailing_windows = _live_fill_windows(rows)
    latest_live_fill_age_hours = _latest_live_fill_age_hours(rows)
    fund_blocked, fund_block_reasons = _fund_reconciliation_blocked(runtime_truth)

    current_probe_payload = dict(payload)
    current_probe_payload["package_confidence_label"] = str(
        probe_feedback.get("effective_package_confidence_label") or payload.get("package_confidence_label") or "low"
    )
    current_probe_payload["package_confidence_reasons"] = list(payload.get("package_confidence_reasons") or []) + [
        str(reason) for reason in (probe_feedback.get("adjustment_reasons") or [])
    ]
    current_probe_payload["deploy_recommendation"] = str(
        probe_feedback.get("effective_deploy_recommendation") or payload.get("deploy_recommendation") or "hold"
    )
    current_probe_payload["policy_benchmark"] = dict(payload.get("policy_benchmark") or {})
    current_probe_payload["package_missing_evidence"] = list(payload.get("package_missing_evidence") or []) + [
        str(tag) for tag in (current_probe.get("stage_not_ready_reason_tags") or [])
    ]
    current_probe_payload["package_ranking"] = package_ranking
    current_probe_payload["capital_scale_recommendation"] = _capital_scale_recommendation(
        deploy_recommendation=str(current_probe_payload.get("deploy_recommendation") or "hold"),
        package_confidence_label=str(current_probe_payload.get("package_confidence_label") or "low"),
        trailing=trailing_windows,
        promoted_package_selected=False,
        fund_reconciliation_blocked=fund_blocked,
        fund_block_reasons=fund_block_reasons,
        size_aware_deployment=size_aware_deployment,
    )
    current_probe_payload["capital_stage_recommendation"] = _capital_stage_recommendation(
        deploy_recommendation=str(current_probe_payload.get("deploy_recommendation") or "hold"),
        package_confidence_label=str(current_probe_payload.get("package_confidence_label") or "low"),
        trailing=trailing_windows,
        execution_drag_summary=execution_drag_summary,
        promoted_package_selected=False,
        latest_live_fill_age_hours=latest_live_fill_age_hours,
        size_aware_deployment=size_aware_deployment,
    )
    public_forecast_selection = _select_public_forecast(
        standard_payload=payload,
        current_probe_payload=current_probe_payload,
        standard_source=str(args.report_dir / "latest.json"),
        current_probe_source=str(args.current_probe_latest),
    )
    if not (public_forecast_selection.get("selected")) and prior_standard_latest:
        public_forecast_selection = _select_public_forecast(
            standard_payload=prior_standard_latest,
            current_probe_payload=current_probe_payload,
            standard_source=str(args.report_dir / "latest.json"),
            current_probe_source=str(args.current_probe_latest),
        )
    selected_public = public_forecast_selection.get("selected") or {}
    payload["public_forecast_selection"] = public_forecast_selection
    payload["public_forecast_source_artifact"] = selected_public.get("source_artifact")
    runtime_selection = _select_runtime_payload(
        standard_payload=payload,
        current_probe_payload=current_probe_payload,
    )
    runtime_source = str(runtime_selection.get("source") or "none")
    selected_runtime_payload = runtime_selection.get("payload") if isinstance(runtime_selection.get("payload"), dict) else {}
    selected_package_ranking = (
        (selected_runtime_payload.get("package_ranking") or {}).get("ranked_packages")
        if isinstance(selected_runtime_payload.get("package_ranking"), dict)
        else []
    ) or []
    selected_ranked_item = (
        selected_package_ranking[0] if selected_package_ranking and isinstance(selected_package_ranking[0], dict) else {}
    )
    payload["runtime_package_selection"] = {
        "source": runtime_source,
        "source_artifact": (
            str(args.current_probe_latest)
            if runtime_source == "current_probe"
            else (str(args.report_dir / "latest.json") if runtime_source == "standard" else None)
        ),
        "selection_reason": str(runtime_selection.get("selection_reason") or "no_runtime_payload_available"),
        "selection_source": str(selected_ranked_item.get("selection_source") or "probe_aware_live_score"),
        "selected_package_hash": selected_ranked_item.get("package_hash"),
        "selected_policy_loss": selected_ranked_item.get("frontier_policy_loss"),
        "selected_market_model_version": selected_ranked_item.get("frontier_market_model_version"),
        "frontier_gap_vs_best": selected_ranked_item.get("frontier_gap_vs_best"),
        "frontier_gap_vs_incumbent": selected_ranked_item.get("frontier_gap_vs_incumbent"),
    }
    selected_best_runtime_package = (
        selected_ranked_item.get("runtime_package")
        or selected_runtime_payload.get("best_runtime_package")
        or payload.get("best_runtime_package")
        or {}
    )
    selected_active_runtime_package = selected_runtime_payload.get("active_runtime_package") or payload.get("active_runtime_package") or {}
    selected_deploy_recommendation = str(
        selected_runtime_payload.get("deploy_recommendation") or payload.get("deploy_recommendation") or "hold"
    )
    selected_package_confidence_label = str(
        selected_runtime_payload.get("package_confidence_label") or payload.get("package_confidence_label") or "low"
    )
    selected_package_confidence_reasons = list(
        selected_runtime_payload.get("package_confidence_reasons") or payload.get("package_confidence_reasons") or []
    )
    selected_size_aware_deployment = selected_runtime_payload.get("size_aware_deployment") or payload.get("size_aware_deployment") or {}
    selected_package_class_summary = _package_class_summary(package_ranking, selected_best_runtime_package)
    promoted_package_selected = _package_signature(selected_best_runtime_package) == _package_signature(
        selected_active_runtime_package
    )
    selected_runtime_contract = _selected_runtime_contract(
        runtime_package_selection=payload["runtime_package_selection"],
        selected_best_runtime_package=selected_best_runtime_package,
        selected_active_runtime_package=selected_active_runtime_package,
        selected_deploy_recommendation=selected_deploy_recommendation,
        selected_package_confidence_label=selected_package_confidence_label,
        selected_package_confidence_reasons=selected_package_confidence_reasons,
        selected_size_aware_deployment=selected_size_aware_deployment,
        selected_package_class_summary=selected_package_class_summary,
        promoted_package_selected=promoted_package_selected,
    )
    payload.update(selected_runtime_contract)
    current_probe_payload.update(selected_runtime_contract)
    package_freeze = _package_freeze_contract(
        selected_active_runtime_package=selected_active_runtime_package,
        selected_best_runtime_package=selected_best_runtime_package,
        best_live_package=payload.get("best_live_package") if isinstance(payload.get("best_live_package"), dict) else {},
        best_raw_package=payload.get("best_raw_research_package") if isinstance(payload.get("best_raw_research_package"), dict) else {},
        runtime_package_selection=payload["runtime_package_selection"],
        selected_deploy_recommendation=selected_deploy_recommendation,
    )
    payload["package_freeze"] = package_freeze
    payload["canonical_live_package"] = package_freeze["canonical_live_package"]
    payload["shadow_comparator_package"] = package_freeze["shadow_comparator_package"]
    current_probe_payload["package_freeze"] = package_freeze
    current_probe_payload["canonical_live_package"] = package_freeze["canonical_live_package"]
    current_probe_payload["shadow_comparator_package"] = package_freeze["shadow_comparator_package"]
    best_live_package_payload = (
        payload.get("best_live_package") if isinstance(payload.get("best_live_package"), dict) else {}
    )
    current_probe_best_live_package = (
        current_probe_payload.get("best_live_package")
        if isinstance(current_probe_payload.get("best_live_package"), dict)
        else {}
    )
    best_live_signature = _package_signature(best_live_package_payload.get("runtime_package"))
    canonical_signature = _package_signature(package_freeze["canonical_live_package"].get("runtime_package"))
    best_live_deployment_mode = "shadow_only" if best_live_signature != canonical_signature else "live_current"
    shadow_only_reason_tags = (
        list(package_freeze["shadow_comparator_package"].get("reason_tags") or [])
        if best_live_deployment_mode == "shadow_only"
        else []
    )
    if best_live_package_payload:
        best_live_package_payload["deployment_mode"] = best_live_deployment_mode
        best_live_package_payload["shadow_only_reason_tags"] = shadow_only_reason_tags
    if current_probe_best_live_package:
        current_probe_best_live_package["deployment_mode"] = best_live_deployment_mode
        current_probe_best_live_package["shadow_only_reason_tags"] = shadow_only_reason_tags
    payload["capital_scale_recommendation"] = _capital_scale_recommendation(
        deploy_recommendation=selected_deploy_recommendation,
        package_confidence_label=selected_package_confidence_label,
        trailing=trailing_windows,
        promoted_package_selected=promoted_package_selected,
        fund_reconciliation_blocked=fund_blocked,
        fund_block_reasons=fund_block_reasons,
        size_aware_deployment=selected_size_aware_deployment,
    )
    payload["capital_stage_recommendation"] = _capital_stage_recommendation(
        deploy_recommendation=selected_deploy_recommendation,
        package_confidence_label=selected_package_confidence_label,
        trailing=trailing_windows,
        execution_drag_summary=execution_drag_summary,
        promoted_package_selected=promoted_package_selected,
        latest_live_fill_age_hours=latest_live_fill_age_hours,
        size_aware_deployment=selected_size_aware_deployment,
    )
    fill_feedback_summary: dict[str, Any]
    fill_feedback_state_after: dict[str, Any]
    try:
        fill_feedback_summary, fill_feedback_state_after = _fill_feedback_summary(
            db_path=args.db_path,
            feedback_state_path=args.fill_feedback_state,
            cycles_jsonl_path=args.cycles_jsonl,
            best_candidate=best_candidate,
            selected_frontier_item=selected_frontier_item,
            decision=decision,
            generated_at=str(payload.get("generated_at") or _now_utc().isoformat()),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        fill_feedback_summary = {
            "generated_at": str(payload.get("generated_at") or _now_utc().isoformat()),
            "actual_metrics": {},
            "predicted_metrics": {},
            "metric_deltas": {},
            "metric_sigma": {},
            "parameter_adjustment_flags": [],
            "needs_parameter_adjustment": False,
            "db_diagnostics": {"status": "feedback_error", "error": str(exc)},
        }
        fill_feedback_state_after = _load_fill_feedback_state(args.fill_feedback_state)
    payload["fill_feedback"] = fill_feedback_summary
    current_probe_payload["fill_feedback"] = fill_feedback_summary
    payload["fill_feedback_artifacts"] = {
        "cycles_jsonl": str(args.cycles_jsonl),
        "feedback_state_json": str(args.fill_feedback_state),
    }

    cycle_feedback_record = {
        "generated_at": str(payload.get("generated_at") or _now_utc().isoformat()),
        "decision_action": str(((payload.get("decision") or {}).get("action")) or "hold"),
        "selected_source": str(((payload.get("decision") or {}).get("selected_source")) or "unknown"),
        "fill_feedback": fill_feedback_summary,
        "semantic_dedup": payload.get("semantic_dedup") or {},
    }
    _append_jsonl(args.cycles_jsonl, cycle_feedback_record)
    write_text_atomic(args.fill_feedback_state, json.dumps(fill_feedback_state_after, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _save_semantic_dedup_index(args.semantic_dedup_index, semantic_dedup_index)

    artifacts = _write_reports(args.report_dir, payload)
    payload["artifacts"] = artifacts
    probe_artifacts = _write_reports(args.current_probe_latest.parent, current_probe_payload)
    current_probe_payload["artifacts"] = probe_artifacts
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
