#!/usr/bin/env python3
"""Build a methodical BTC5 correlation and experiment report from local artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    DEFAULT_ARCHIVE_GLOB,
    DEFAULT_LOCAL_DB,
    DEFAULT_REMOTE_ROWS_JSON,
    assemble_observed_rows,
)


DEFAULT_CURRENT_PROBE_JSON = Path("reports/btc5_autoresearch_current_probe/latest.json")
DEFAULT_RUNTIME_TRUTH_JSON = Path("reports/runtime_truth_latest.json")
DEFAULT_SIGNAL_AUDIT_JSON = Path("reports/runtime/signals/signal_source_audit.json")
DEFAULT_CONFIRMATION_JSON = Path("reports/runtime/signals/btc_fast_window_confirmation.json")
DEFAULT_CONFIRMATION_ARCHIVE_JSON = Path("reports/btc_fast_window_confirmation_archive.json")
DEFAULT_REGIME_SUMMARY_JSON = Path("reports/btc5_regime_policy_lab/summary.json")
DEFAULT_HYPOTHESIS_SUMMARY_JSON = Path("reports/btc5_hypothesis_lab/summary.json")
DEFAULT_OUTPUT_JSON = Path("reports/btc5_correlation_lab/latest.json")
DEFAULT_OUTPUT_MD = Path("reports/btc5_correlation_lab/report.md")
LIVE_FILLED_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_safe_float(value), digits)


def _round_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rounded: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, float):
            rounded[key] = round(value, 4)
        else:
            rounded[key] = value
    return rounded


def _load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Artifact not found: {path}")
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _is_live_filled_row(row: dict[str, Any]) -> bool:
    status = str(row.get("order_status") or "").strip().lower()
    if status in LIVE_FILLED_STATUSES:
        return True
    return status.startswith("live_") and _safe_float(row.get("trade_size_usd")) > 0.0


def _sample_span_hours(rows: list[dict[str, Any]]) -> float:
    timestamps = sorted(
        _safe_int(row.get("window_start_ts"))
        for row in rows
        if _safe_int(row.get("window_start_ts")) > 0
    )
    if not timestamps:
        return 0.0
    return ((timestamps[-1] - timestamps[0]) / 3600.0) + (5.0 / 60.0)


def build_rollup(
    rows: list[dict[str, Any]],
    *,
    fields: tuple[str, ...],
    min_fills: int = 1,
    limit: int = 10,
    sort_key: str = "pnl_usd",
    reverse: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
        lambda: {"fills": 0, "wins": 0, "pnl_usd": 0.0, "trade_notional_usd": 0.0}
    )
    for row in rows:
        key = tuple(str(row.get(field) or "unknown") for field in fields)
        bucket = grouped[key]
        bucket["fills"] += 1
        pnl = _safe_float(row.get("pnl_usd"))
        bucket["pnl_usd"] += pnl
        bucket["trade_notional_usd"] += _safe_float(row.get("trade_size_usd"))
        if pnl > 0.0:
            bucket["wins"] += 1

    rollups: list[dict[str, Any]] = []
    total_fills = max(1, len(rows))
    for key, payload in grouped.items():
        fills = int(payload["fills"])
        if fills < max(1, int(min_fills)):
            continue
        label = " | ".join(f"{field}={value}" for field, value in zip(fields, key, strict=False))
        rollups.append(
            _round_payload(
                {
                    "label": label,
                    "fields": {field: value for field, value in zip(fields, key, strict=False)},
                    "fills": fills,
                    "fill_share": fills / float(total_fills),
                    "pnl_usd": payload["pnl_usd"],
                    "avg_pnl_usd": payload["pnl_usd"] / float(fills),
                    "win_rate": payload["wins"] / float(fills),
                    "trade_notional_usd": payload["trade_notional_usd"],
                    "avg_trade_size_usd": payload["trade_notional_usd"] / float(fills),
                }
            )
        )

    rollups.sort(
        key=lambda item: (
            _safe_float(item.get(sort_key)),
            _safe_int(item.get("fills")),
            str(item.get("label") or ""),
        ),
        reverse=reverse,
    )
    return rollups[: max(1, int(limit))]


def build_empirical_bayes_regime_model(
    rows: list[dict[str, Any]],
    *,
    fields: tuple[str, ...] = ("session_name", "direction", "price_bucket", "delta_bucket"),
    prior_fills: float = 8.0,
    min_fills: int = 2,
    limit: int = 10,
) -> dict[str, Any]:
    if not rows:
        return {
            "model_type": "empirical_bayes_regime_model",
            "features": list(fields),
            "global_avg_pnl_usd": 0.0,
            "global_win_rate": 0.0,
            "positive_regimes": [],
            "negative_regimes": [],
        }

    global_avg_pnl = sum(_safe_float(row.get("pnl_usd")) for row in rows) / float(len(rows))
    global_win_rate = sum(1 for row in rows if _safe_float(row.get("pnl_usd")) > 0.0) / float(len(rows))
    grouped: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
        lambda: {"fills": 0, "wins": 0, "pnl_usd": 0.0}
    )
    for row in rows:
        key = tuple(str(row.get(field) or "unknown") for field in fields)
        bucket = grouped[key]
        bucket["fills"] += 1
        pnl = _safe_float(row.get("pnl_usd"))
        bucket["pnl_usd"] += pnl
        if pnl > 0.0:
            bucket["wins"] += 1

    scored: list[dict[str, Any]] = []
    for key, payload in grouped.items():
        fills = int(payload["fills"])
        if fills < max(1, int(min_fills)):
            continue
        wins = int(payload["wins"])
        pnl = _safe_float(payload["pnl_usd"])
        raw_avg_pnl = pnl / float(fills)
        shrunk_avg_pnl = (pnl + (prior_fills * global_avg_pnl)) / float(fills + prior_fills)
        shrunk_win_rate = (wins + (prior_fills * global_win_rate)) / float(fills + prior_fills)
        score = shrunk_avg_pnl * math.sqrt(float(fills))
        scored.append(
            _round_payload(
                {
                    "label": " | ".join(
                        f"{field}={value}" for field, value in zip(fields, key, strict=False)
                    ),
                    "fields": {field: value for field, value in zip(fields, key, strict=False)},
                    "fills": fills,
                    "pnl_usd": pnl,
                    "raw_avg_pnl_usd": raw_avg_pnl,
                    "shrunk_avg_pnl_usd": shrunk_avg_pnl,
                    "shrunk_win_rate": shrunk_win_rate,
                    "raw_win_rate": wins / float(fills),
                    "score": score,
                }
            )
        )

    positive = sorted(
        [item for item in scored if _safe_float(item.get("shrunk_avg_pnl_usd")) > 0.0],
        key=lambda item: (
            _safe_float(item.get("score")),
            _safe_int(item.get("fills")),
        ),
        reverse=True,
    )[: max(1, int(limit))]
    negative = sorted(
        [item for item in scored if _safe_float(item.get("shrunk_avg_pnl_usd")) < 0.0],
        key=lambda item: (
            _safe_float(item.get("score")),
            -_safe_int(item.get("fills")),
        ),
    )[: max(1, int(limit))]

    return {
        "model_type": "empirical_bayes_regime_model",
        "features": list(fields),
        "global_avg_pnl_usd": round(global_avg_pnl, 4),
        "global_win_rate": round(global_win_rate, 4),
        "prior_fills": float(prior_fills),
        "positive_regimes": positive,
        "negative_regimes": negative,
    }


def build_feed_inventory(
    *,
    signal_audit: dict[str, Any],
    confirmation: dict[str, Any],
    confirmation_archive: dict[str, Any],
    local_db_path: Path,
) -> list[dict[str, Any]]:
    capital_support = signal_audit.get("capital_ranking_support") or {}
    confirmation_by_source = confirmation.get("by_source") or {}
    confirmation_archive_by_source = confirmation_archive.get("by_source") or {}
    local_db_ready = local_db_path.exists() and local_db_path.stat().st_size > 0

    def _source_counts(source: str) -> dict[str, int]:
        current = confirmation_by_source.get(source) or {}
        archive = confirmation_archive_by_source.get(source) or {}
        return {
            "current_source_window_rows": _safe_int(current.get("source_window_rows")),
            "archive_source_window_rows": _safe_int(archive.get("source_window_rows")),
            "current_covered_executed_window_rows": _safe_int(current.get("covered_executed_window_rows")),
            "archive_covered_executed_window_rows": _safe_int(archive.get("covered_executed_window_rows")),
        }

    wallet_flow_counts = _source_counts("wallet_flow")
    lmsr_counts = _source_counts("lmsr")
    wallet_flow_has_any_coverage = any(wallet_flow_counts.values())
    lmsr_has_any_coverage = any(lmsr_counts.values())
    lmsr_blockers = [
        str(item)
        for item in (capital_support.get("confirmation_blocking_checks") or [])
        if str(item).startswith("lmsr:")
    ]

    inventory = [
        {
            "key": "spot_open_delta",
            "feed": "BTC open/current delta",
            "current_status": "ready_now",
            "runtime_available": True,
            "replay_from_cache": True,
            "replay_from_full_db": True,
            "notes": "Core BTC5 predictor already in the cached window tape.",
        },
        {
            "key": "session_time",
            "feed": "Session/time-of-day bucket",
            "current_status": "ready_now",
            "runtime_available": True,
            "replay_from_cache": True,
            "replay_from_full_db": True,
            "notes": "Open/midday/late and hour buckets are derived from window timestamps.",
        },
        {
            "key": "price_band",
            "feed": "Quote price bucket",
            "current_status": "ready_now",
            "runtime_available": True,
            "replay_from_cache": True,
            "replay_from_full_db": True,
            "notes": "Current evidence already shows strong bucket dependence.",
        },
        {
            "key": "best_bid_ask",
            "feed": "Best bid / best ask",
            "current_status": "ready_with_local_db" if local_db_ready else "needs_local_db_copy",
            "runtime_available": True,
            "replay_from_cache": False,
            "replay_from_full_db": True,
            "notes": "Persisted in the full BTC5 DB but absent from the checked-in cache export.",
        },
        {
            "key": "decision_tags",
            "feed": "Decision tags / sizing tags / edge tier / session policy",
            "current_status": "ready_with_local_db" if local_db_ready else "needs_local_db_copy",
            "runtime_available": True,
            "replay_from_cache": False,
            "replay_from_full_db": True,
            "notes": "Critical for attribution and ablations; persisted in DB only.",
        },
        {
            "key": "wallet_flow_confirmation",
            "feed": "Wallet-flow confirmation windows",
            "current_status": "partial_data" if wallet_flow_has_any_coverage else "blocked",
            "runtime_available": True,
            "replay_from_cache": False,
            "replay_from_full_db": False,
            "notes": (
                "Current confirmation has "
                f"{wallet_flow_counts['current_source_window_rows']} signal windows and "
                f"{wallet_flow_counts['current_covered_executed_window_rows']} covered executed windows; "
                "archive has "
                f"{wallet_flow_counts['archive_source_window_rows']} signal windows and "
                f"{wallet_flow_counts['archive_covered_executed_window_rows']} covered executed windows."
            ),
        },
        {
            "key": "lmsr_confirmation",
            "feed": "LMSR confirmation windows",
            "current_status": "partial_data" if lmsr_has_any_coverage else "blocked",
            "runtime_available": True,
            "replay_from_cache": False,
            "replay_from_full_db": False,
            "notes": (
                "Current confirmation has "
                f"{lmsr_counts['current_source_window_rows']} signal windows and "
                f"{lmsr_counts['current_covered_executed_window_rows']} covered executed windows; "
                "archive has "
                f"{lmsr_counts['archive_source_window_rows']} signal windows and "
                f"{lmsr_counts['archive_covered_executed_window_rows']} covered executed windows. "
                + (" ".join(lmsr_blockers) if lmsr_blockers else "No overlapping confirmation windows are ready.")
            ),
        },
        {
            "key": "microstructure_gate",
            "feed": "VPIN / OFI microstructure gate",
            "current_status": "blocked",
            "runtime_available": True,
            "replay_from_cache": False,
            "replay_from_full_db": False,
            "notes": "Gate exists conceptually, but historical per-window VPIN/OFI telemetry is not in the BTC5 replay surface.",
        },
        {
            "key": "volatility_path",
            "feed": "Recent Binance volatility path",
            "current_status": "needs_persistence_upgrade",
            "runtime_available": True,
            "replay_from_cache": False,
            "replay_from_full_db": False,
            "notes": "Volatility guardrail is active at runtime but the lookback path is not persisted for historical joins.",
        },
    ]
    return inventory


def _inventory_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key") or ""): item for item in items}


def build_experiment_catalog(feed_inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory = _inventory_map(feed_inventory)

    def _status(*keys: str) -> str:
        statuses = [str((inventory.get(key) or {}).get("current_status") or "blocked") for key in keys]
        if any(status == "blocked" for status in statuses):
            return "blocked"
        if any(status == "partial_data" for status in statuses):
            return "partial_data"
        if any(status == "needs_persistence_upgrade" for status in statuses):
            return "needs_persistence_upgrade"
        if any(status == "needs_local_db_copy" for status in statuses):
            return "needs_local_db_copy"
        if any(status == "ready_with_local_db" for status in statuses):
            return "ready_with_local_db"
        return "ready_now"

    catalog = [
        {
            "key": "session_direction_price_delta_sweep",
            "priority": 1,
            "status": _status("spot_open_delta", "session_time", "price_band"),
            "objective": "Quantify which session x direction x price x delta regimes are actually positive after fills.",
            "success_metric": "Out-of-sample median pnl and shrunk regime score above global baseline.",
        },
        {
            "key": "loss_cluster_suppression_ablation",
            "priority": 2,
            "status": _status("spot_open_delta", "session_time", "price_band"),
            "objective": "Test whether the currently hard-coded loss clusters should remain blocked, tightened, or re-enabled.",
            "success_metric": "Suppression removes negative expectancy without sacrificing more than 10% of positive pnl.",
        },
        {
            "key": "open_et_vs_hour_11_policy_search",
            "priority": 3,
            "status": _status("spot_open_delta", "session_time", "price_band"),
            "objective": "Methodically compare the current open_et candidate against tighter hour-11 variants.",
            "success_metric": "Higher walk-forward median pnl with no deterioration in p05 tail compared with open_et baseline.",
        },
        {
            "key": "price_band_quote_ablation",
            "priority": 4,
            "status": _status("price_band"),
            "objective": "Separate the economics of quoting at 0.49, 0.50, and 0.51+ instead of blending them.",
            "success_metric": "Clear rank ordering by realized and shrunk avg pnl per fill.",
        },
        {
            "key": "recent_regime_skew_ablation",
            "priority": 5,
            "status": _status("session_time", "price_band"),
            "objective": "Evaluate whether the recent-direction skew and one-sided guardrail improve outcomes or just cut coverage.",
            "success_metric": "Higher pnl per covered window without reducing fill coverage below current baseline.",
        },
        {
            "key": "book_quote_geometry",
            "priority": 6,
            "status": _status("best_bid_ask"),
            "objective": "Test whether spread width, midpoint distance, and bid/ask geometry explain fill quality and losses.",
            "success_metric": "Stable explanatory lift on pnl or fill probability across walk-forward splits.",
        },
        {
            "key": "decision_and_sizing_tag_attribution",
            "priority": 7,
            "status": _status("decision_tags"),
            "objective": "Attribute losses to explicit decision tags, sizing tags, session policies, and edge tiers.",
            "success_metric": "Top 3 tag families explain the majority of negative pnl and retry drag.",
        },
        {
            "key": "wallet_flow_confirmation_join",
            "priority": 8,
            "status": _status("wallet_flow_confirmation"),
            "objective": "Measure whether wallet-flow windows confirm good BTC5 trades and suppress bad ones.",
            "success_metric": "Positive confirmation lift with at least 10 covered executed windows.",
        },
        {
            "key": "lmsr_confirmation_join",
            "priority": 9,
            "status": _status("lmsr_confirmation"),
            "objective": "Test whether LMSR mispricing confirmation improves entry selection on BTC5 windows.",
            "success_metric": "Positive confirmation lift with overlapping source and probe windows.",
        },
        {
            "key": "microstructure_gate_persistence",
            "priority": 10,
            "status": _status("microstructure_gate"),
            "objective": "Persist VPIN/OFI per window so toxicity can be tested as a historical gate rather than a runtime-only concept.",
            "success_metric": "Per-window VPIN/OFI artifact available for at least 200 windows.",
        },
        {
            "key": "hierarchical_regime_model",
            "priority": 11,
            "status": _status("spot_open_delta", "session_time", "price_band"),
            "objective": "Fit a shrinkage-based regime model across session, direction, price bucket, and delta bucket.",
            "success_metric": "Model rankings remain directionally stable across walk-forward slices.",
        },
        {
            "key": "stateful_sequence_model",
            "priority": 12,
            "status": _status("best_bid_ask", "decision_tags", "volatility_path"),
            "objective": "Build a stateful model that conditions on recent fills, book geometry, and volatility regime.",
            "success_metric": "Beats the hierarchical regime model on held-out windows without collapsing sample coverage.",
        },
    ]
    return catalog


def build_current_edge_summary(
    *,
    current_probe: dict[str, Any],
    runtime_truth: dict[str, Any],
) -> dict[str, Any]:
    fill_attribution = ((runtime_truth.get("btc_5min_maker") or {}).get("fill_attribution") or {})
    best_direction = fill_attribution.get("best_direction") or {}
    best_price_bucket = fill_attribution.get("best_price_bucket") or {}
    current_candidate = current_probe.get("current_candidate") or {}
    best_candidate = current_probe.get("best_candidate") or {}
    decision = current_probe.get("decision") or {}

    hypotheses: list[str] = [
        "Implemented BTC5 edge is a late-window maker strategy driven by BTC spot-vs-open delta, then filtered by quote-price caps, session rules, and suppression guards.",
    ]
    if str(best_direction.get("label") or ""):
        hypotheses.append(
            f"Directionally, realized edge has been concentrated in `{best_direction.get('label')}` "
            f"({float(best_direction.get('pnl_usd') or 0.0):.2f} USD) rather than the opposite side."
        )
    if str(best_price_bucket.get("label") or ""):
        hypotheses.append(
            f"Quote economics look bucket-dependent; the strongest realized bucket is `{best_price_bucket.get('label')}` "
            f"with {float(best_price_bucket.get('pnl_usd') or 0.0):.2f} USD."
        )
    session_policy = best_candidate.get("recommended_session_policy") or []
    if session_policy:
        first = session_policy[0]
        hypotheses.append(
            "Research evidence says the strongest current edge is session-conditioned, not global: "
            f"`{first.get('name')}` with hours {first.get('et_hours') or []}."
        )

    contradictions: list[str] = []
    current_mc = current_candidate.get("monte_carlo") or {}
    best_mc = best_candidate.get("monte_carlo") or {}
    if _safe_float((current_candidate.get("historical") or {}).get("replay_live_filled_pnl_usd")) > 0.0 and _safe_float(
        current_mc.get("median_total_pnl_usd")
    ) <= 0.0:
        contradictions.append("Current live profile is historically positive on replay but negative in bootstrap continuation paths.")
    if _safe_float(best_mc.get("p05_total_pnl_usd")) <= 0.0:
        contradictions.append("Best validated candidate still has a negative p05 tail, so the edge is not yet robust enough for size expansion.")
    if str(decision.get("reason") or ""):
        contradictions.append(f"Autoresearch is still blocking promotion because `{decision.get('reason')}`.")

    return {
        "implemented_strategy": "late_window_delta_maker",
        "current_live_profile": current_probe.get("active_profile") or {},
        "best_candidate_profile": (best_candidate.get("profile") or {}),
        "hypotheses": hypotheses,
        "contradictions": contradictions,
        "best_direction": best_direction,
        "best_price_bucket": best_price_bucket,
    }


def build_summary(
    *,
    rows: list[dict[str, Any]],
    current_probe: dict[str, Any],
    runtime_truth: dict[str, Any],
    signal_audit: dict[str, Any],
    confirmation: dict[str, Any],
    confirmation_archive: dict[str, Any],
    regime_summary: dict[str, Any],
    hypothesis_summary: dict[str, Any],
    local_db_path: Path,
) -> dict[str, Any]:
    live_filled_rows = [row for row in rows if _is_live_filled_row(row)]
    sample_hours = _sample_span_hours(rows)

    feed_inventory = build_feed_inventory(
        signal_audit=signal_audit,
        confirmation=confirmation,
        confirmation_archive=confirmation_archive,
        local_db_path=local_db_path,
    )
    experiment_catalog = build_experiment_catalog(feed_inventory)
    factor_model = build_empirical_bayes_regime_model(live_filled_rows)

    worst_clusters = build_rollup(
        live_filled_rows,
        fields=("session_name", "direction", "price_bucket", "delta_bucket"),
        min_fills=2,
        limit=12,
        sort_key="pnl_usd",
        reverse=False,
    )
    best_clusters = build_rollup(
        live_filled_rows,
        fields=("session_name", "direction", "price_bucket", "delta_bucket"),
        min_fills=2,
        limit=12,
        sort_key="pnl_usd",
        reverse=True,
    )

    summary = {
        "metric_name": "btc5_correlation_lab",
        "generated_at": _now_utc(),
        "inputs": {
            "decision_rows": len(rows),
            "live_filled_rows": len(live_filled_rows),
            "sample_span_hours": round(sample_hours, 4),
            "sample_span_days": round(sample_hours / 24.0, 4) if sample_hours > 0.0 else 0.0,
            "local_db_path": str(local_db_path),
            "local_db_ready": bool(local_db_path.exists() and local_db_path.stat().st_size > 0),
        },
        "current_edge": build_current_edge_summary(
            current_probe=current_probe,
            runtime_truth=runtime_truth,
        ),
        "feed_inventory": feed_inventory,
        "historical_characteristics": {
            "by_direction": build_rollup(live_filled_rows, fields=("direction",), limit=8),
            "by_session": build_rollup(live_filled_rows, fields=("session_name",), limit=12),
            "by_price_bucket": build_rollup(live_filled_rows, fields=("price_bucket",), limit=8),
            "by_delta_bucket": build_rollup(live_filled_rows, fields=("delta_bucket",), limit=8),
            "worst_clusters": worst_clusters,
            "best_clusters": best_clusters,
        },
        "factor_model": factor_model,
        "experiments": experiment_catalog,
        "source_confirmation": {
            "signal_audit_generated_at": signal_audit.get("capital_ranking_support", {}).get("audit_generated_at"),
            "wallet_flow_confirmation": (confirmation.get("by_source") or {}).get("wallet_flow") or {},
            "wallet_flow_confirmation_archive": (confirmation_archive.get("by_source") or {}).get("wallet_flow") or {},
            "lmsr_confirmation": (confirmation.get("by_source") or {}).get("lmsr") or {},
            "lmsr_confirmation_archive": (confirmation_archive.get("by_source") or {}).get("lmsr") or {},
        },
        "research_surfaces": {
            "regime_best_candidate": regime_summary.get("best_candidate") or {},
            "hypothesis_best_candidate": hypothesis_summary.get("best_candidate") or {},
        },
    }
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    current_edge = summary["current_edge"]
    characteristics = summary["historical_characteristics"]
    factor_model = summary["factor_model"]
    experiments = summary["experiments"]
    ready_experiments = [item for item in experiments if str(item.get("status")) == "ready_now"][:5]
    local_db_experiments = [item for item in experiments if str(item.get("status")) == "ready_with_local_db"][:5]

    lines = [
        "# BTC5 Correlation Lab",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision rows analyzed: `{summary['inputs']['decision_rows']}`",
        f"- Live-filled rows analyzed: `{summary['inputs']['live_filled_rows']}`",
        f"- Sample span: `{summary['inputs']['sample_span_hours']:.2f}` hours",
        "",
        "## Current Edge",
        "",
    ]
    for item in current_edge.get("hypotheses") or []:
        lines.append(f"- {item}")
    if current_edge.get("contradictions"):
        lines.extend(["", "## Current Contradictions", ""])
        for item in current_edge.get("contradictions") or []:
            lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Where We Have Lost Money",
            "",
        ]
    )
    for item in characteristics.get("worst_clusters") or []:
        lines.append(
            f"- `{item['label']}`: `{item['fills']}` fills, `${item['pnl_usd']:.2f}` pnl, `{item['win_rate']:.1%}` win rate"
        )

    lines.extend(
        [
            "",
            "## Strongest Characteristics",
            "",
        ]
    )
    for item in factor_model.get("positive_regimes") or []:
        lines.append(
            f"- `{item['label']}`: shrunk avg `${item['shrunk_avg_pnl_usd']:.2f}` on `{item['fills']}` fills"
        )

    lines.extend(
        [
            "",
            "## Feed Inventory",
            "",
        ]
    )
    for item in summary.get("feed_inventory") or []:
        lines.append(f"- `{item['feed']}`: `{item['current_status']}` — {item['notes']}")

    lines.extend(
        [
            "",
            "## Next Experiments",
            "",
        ]
    )
    for item in ready_experiments:
        lines.append(f"- `{item['key']}`: {item['objective']}")

    if local_db_experiments:
        lines.extend(
            [
                "",
                "## Local DB Unlocked Experiments",
                "",
            ]
        )
        for item in local_db_experiments:
            lines.append(f"- `{item['key']}`: {item['objective']}")

    blocked = [
        item
        for item in experiments
        if str(item.get("status"))
        in {"blocked", "partial_data", "needs_local_db_copy", "needs_persistence_upgrade"}
    ]
    if blocked:
        lines.extend(["", "## Blocked Or Gated Experiments", ""])
        for item in blocked[:7]:
            lines.append(f"- `{item['key']}` [{item['status']}] — {item['objective']}")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_LOCAL_DB))
    parser.add_argument("--rows-json", default=str(DEFAULT_REMOTE_ROWS_JSON))
    parser.add_argument("--current-probe-json", default=str(DEFAULT_CURRENT_PROBE_JSON))
    parser.add_argument("--runtime-truth-json", default=str(DEFAULT_RUNTIME_TRUTH_JSON))
    parser.add_argument("--signal-audit-json", default=str(DEFAULT_SIGNAL_AUDIT_JSON))
    parser.add_argument("--confirmation-json", default=str(DEFAULT_CONFIRMATION_JSON))
    parser.add_argument("--confirmation-archive-json", default=str(DEFAULT_CONFIRMATION_ARCHIVE_JSON))
    parser.add_argument("--regime-summary-json", default=str(DEFAULT_REGIME_SUMMARY_JSON))
    parser.add_argument("--hypothesis-summary-json", default=str(DEFAULT_HYPOTHESIS_SUMMARY_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    local_db_path = Path(args.db_path)
    rows, _baseline = assemble_observed_rows(
        db_path=local_db_path if local_db_path.exists() else None,
        include_archive_csvs=False,
        archive_glob=DEFAULT_ARCHIVE_GLOB,
        refresh_remote=False,
        remote_cache_json=Path(args.rows_json),
    )
    summary = build_summary(
        rows=rows,
        current_probe=_load_json(Path(args.current_probe_json)),
        runtime_truth=_load_json(Path(args.runtime_truth_json)),
        signal_audit=_load_json(Path(args.signal_audit_json), required=False),
        confirmation=_load_json(Path(args.confirmation_json), required=False),
        confirmation_archive=_load_json(Path(args.confirmation_archive_json), required=False),
        regime_summary=_load_json(Path(args.regime_summary_json), required=False),
        hypothesis_summary=_load_json(Path(args.hypothesis_summary_json), required=False),
        local_db_path=local_db_path,
    )
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, indent=2) + "\n")
    output_md.write_text(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
