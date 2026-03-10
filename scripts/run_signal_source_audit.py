#!/usr/bin/env python3
"""Audit live trade attribution by signal source and emit a JSON summary."""

from __future__ import annotations

import argparse
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


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


def build_audit_payload(
    *,
    db_path: Path,
    state_path: Path,
    minimum_signal_sample: int = 50,
) -> dict[str, Any]:
    rows, db_columns = _load_trade_rows(db_path)
    state_snapshot = _load_state_snapshot(state_path)

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
    for source_key, meta in SOURCE_DECISION_SCOPE.items():
        if meta["role"] == "gate_only":
            recommendations[source_key] = {
                "recommendation": "keep_as_gate",
                "reason": "VPIN/OFI is a microstructure filter, not an order-originating trade source; audit it from telemetry, not paper-trade attribution.",
                "role": meta["role"],
            }
            continue

        metrics = component_metrics.get(source_key, _finalize_bucket(_empty_bucket()))
        recommendation, reason = _recommend_source(
            source_key,
            metrics,
            wallet_flow_comparison=wallet_flow_comparison,
            minimum_signal_sample=minimum_signal_sample,
        )
        recommendations[source_key] = {
            "recommendation": recommendation,
            "reason": reason,
            "role": meta["role"],
            "metrics": metrics,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "db_path": str(db_path),
            "state_path": str(state_path),
            "minimum_signal_sample": minimum_signal_sample,
            "notes": [
                "Trade attribution is derived from the live bot's source/source_combo/source_components fields.",
                "Wallet flow is compared against LLM-only trades once both cohorts reach the minimum trade sample.",
                "VPIN/OFI is treated as a gate-only lane because it blocks execution rather than originating trades.",
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
            "total_trades": len(rows),
            "resolved_trades": sum(1 for row in rows if str(row.get("outcome") or "").lower() in {"won", "lost"}),
            "observed_primary_sources": sorted(primary_metrics),
            "observed_source_combos": list(combo_metrics.keys())[:10],
        },
        "by_component_source": component_metrics,
        "by_primary_source": primary_metrics,
        "by_source_combo": combo_metrics,
        "observed_extra_sources": extra_metrics,
        "wallet_flow_vs_llm": wallet_flow_comparison,
        "combined_sources_vs_single_source": combined_vs_single,
        "ranking_snapshot": ranking_snapshot,
        "capital_ranking_support": {
            "stale_threshold_hours": 6.0,
            "trade_attribution_ready": all(
                column in set(db_columns)
                for column in ("source", "source_combo", "source_components_json", "source_count")
            )
            and state_snapshot["trade_log_has_source_attribution"],
            "wallet_flow_vs_llm_status": wallet_flow_comparison["status"],
            "combined_sources_vs_single_source_status": combined_vs_single["status"],
            "best_component_source": (ranking_snapshot.get("best_component_source") or {}).get("source"),
            "best_source_combo": (ranking_snapshot.get("best_source_combo") or {}).get("source_combo"),
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_audit_payload(
        db_path=args.db,
        state_path=args.state,
        minimum_signal_sample=max(1, int(args.minimum_signal_sample)),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Wrote signal source audit to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
