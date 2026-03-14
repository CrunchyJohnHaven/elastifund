#!/usr/bin/env python3
"""Render a wallet-scaled BTC5 expectation report from local Monte Carlo artifacts."""

from __future__ import annotations

import argparse
import json
import sys
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
    GuardrailProfile,
    assemble_observed_rows,
)
from scripts.btc5_regime_policy_lab import (  # noqa: E402
    PolicyCandidate,
    PolicyOverride,
    order_policy_overrides,
)
from scripts.btc5_policy_benchmark import policy_loss_from_projection  # noqa: E402


DEFAULT_CURRENT_PROBE_JSON = Path("reports/btc5_autoresearch_current_probe/latest.json")
DEFAULT_REGIME_SUMMARY_JSON = Path("reports/btc5_regime_policy_lab/summary.json")
DEFAULT_HYPOTHESIS_SUMMARY_JSON = Path("reports/btc5_hypothesis_lab/summary.json")
DEFAULT_RUNTIME_TRUTH_JSON = Path("reports/runtime_truth_latest.json")
DEFAULT_OUTPUT_JSON = Path("reports/btc5_portfolio_expectation/latest.json")
DEFAULT_OUTPUT_MD = Path("reports/btc5_portfolio_expectation/report.md")
WINDOW_MINUTES = 5
DAYS_PER_MONTH = 30.0
DAYS_PER_YEAR = 365.0


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
            raise FileNotFoundError(f"JSON artifact not found: {path}")
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _profile_from_payload(payload: dict[str, Any], *, fallback_name: str) -> GuardrailProfile:
    return GuardrailProfile(
        name=str(payload.get("name") or fallback_name),
        max_abs_delta=(
            _safe_float(payload.get("max_abs_delta"))
            if payload.get("max_abs_delta") is not None
            else None
        ),
        up_max_buy_price=(
            _safe_float(payload.get("up_max_buy_price"))
            if payload.get("up_max_buy_price") is not None
            else None
        ),
        down_max_buy_price=(
            _safe_float(payload.get("down_max_buy_price"))
            if payload.get("down_max_buy_price") is not None
            else None
        ),
        note=str(payload.get("note") or ""),
    )


def _policy_from_payload(payload: dict[str, Any]) -> PolicyCandidate | None:
    policy_payload = payload.get("policy")
    if not isinstance(policy_payload, dict):
        return None
    default_profile_payload = policy_payload.get("default_profile")
    if not isinstance(default_profile_payload, dict):
        return None
    default_profile = _profile_from_payload(
        default_profile_payload,
        fallback_name=str(default_profile_payload.get("name") or "current_live_profile"),
    )
    overrides: list[PolicyOverride] = []
    for item in policy_payload.get("overrides") or []:
        if not isinstance(item, dict):
            continue
        profile_payload = item.get("profile")
        if not isinstance(profile_payload, dict):
            continue
        hours = tuple(
            int(hour)
            for hour in (item.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        )
        if not hours:
            continue
        overrides.append(
            PolicyOverride(
                session_name=str(item.get("session_name") or "session").strip(),
                et_hours=hours,
                profile=_profile_from_payload(
                    profile_payload,
                    fallback_name=str(profile_payload.get("name") or "override_profile"),
                ),
            )
        )
    ordered_overrides = order_policy_overrides(overrides)
    return PolicyCandidate(
        name=str(policy_payload.get("name") or default_profile.name),
        default_profile=default_profile,
        overrides=ordered_overrides,
        note=str(policy_payload.get("note") or ""),
    )


def _sample_span_hours(
    *,
    baseline: dict[str, Any],
    current_probe: dict[str, Any],
) -> float:
    first_ts = _safe_int(baseline.get("first_window_start_ts"))
    last_ts = _safe_int(baseline.get("last_window_start_ts"))
    if first_ts > 0 and last_ts >= first_ts:
        return ((last_ts - first_ts) / 3600.0) + (WINDOW_MINUTES / 60.0)
    baseline_windows = _safe_int(
        ((current_probe.get("current_candidate") or {}).get("historical") or {}).get("baseline_window_rows")
    )
    if baseline_windows > 0:
        return baseline_windows * (WINDOW_MINUTES / 60.0)
    return 0.0


def _per_day(value: Any, *, span_days: float) -> float:
    if span_days <= 0.0:
        return 0.0
    return _safe_float(value) / span_days


def _edge_status(
    *,
    candidate: dict[str, Any],
    probe_decision: dict[str, Any],
    is_best_variant: bool,
) -> dict[str, Any]:
    monte_carlo = candidate.get("monte_carlo") or {}
    historical = candidate.get("historical") or {}
    profit_probability = _safe_float(monte_carlo.get("profit_probability"))
    median_pnl = _safe_float(monte_carlo.get("median_total_pnl_usd"))
    p05_pnl = _safe_float(monte_carlo.get("p05_total_pnl_usd"))
    historical_pnl = _safe_float(historical.get("replay_live_filled_pnl_usd"))
    if median_pnl > 0.0 and p05_pnl > 0.0 and profit_probability >= 0.6:
        return {"status": "validated_positive", "reason": "median_and_tail_paths_positive"}
    if median_pnl > 0.0 and profit_probability >= 0.55:
        return {"status": "positive_but_tail_risky", "reason": "median_positive_but_tail_still_negative"}
    if historical_pnl > 0.0 and median_pnl <= 0.0:
        return {
            "status": "historical_positive_but_mc_negative",
            "reason": "historical_replay_positive_but_bootstrap_paths_fail",
        }
    if is_best_variant and probe_decision:
        return {
            "status": "candidate_blocked",
            "reason": str(probe_decision.get("reason") or "probe_feedback_blocks_promotion"),
        }
    return {"status": "negative", "reason": "historical_and_bootstrap_do_not_support_edge"}


def _projection_block(
    *,
    label: str,
    candidate: dict[str, Any],
    span_hours: float,
    wallet_value_usd: float,
    free_collateral_usd: float,
    probe_decision: dict[str, Any],
    deploy_recommendation: str,
    is_best_variant: bool,
) -> dict[str, Any]:
    historical = candidate.get("historical") or {}
    monte_carlo = candidate.get("monte_carlo") or {}
    continuation = candidate.get("continuation") or {}
    span_days = span_hours / 24.0 if span_hours > 0.0 else 0.0
    avg_trade_size_usd = _safe_float(continuation.get("avg_trade_size_usd"))
    historical_fills = _safe_int(historical.get("replay_live_filled_rows"))
    expected_fills = _safe_float(monte_carlo.get("avg_active_trades"), historical_fills)
    historical_turnover = _safe_float(historical.get("trade_notional_usd"))
    expected_turnover = avg_trade_size_usd * expected_fills
    median_daily_pnl = _per_day(monte_carlo.get("median_total_pnl_usd"), span_days=span_days)
    mean_daily_pnl = _per_day(monte_carlo.get("mean_total_pnl_usd"), span_days=span_days)
    p05_daily_pnl = _per_day(monte_carlo.get("p05_total_pnl_usd"), span_days=span_days)
    p95_daily_pnl = _per_day(monte_carlo.get("p95_total_pnl_usd"), span_days=span_days)
    historical_daily_pnl = _per_day(historical.get("replay_live_filled_pnl_usd"), span_days=span_days)

    projection = _round_payload(
        {
            "label": label,
            "profile_name": str((candidate.get("profile") or {}).get("name") or label),
            "candidate_class": candidate.get("candidate_class"),
            "deploy_recommendation": deploy_recommendation,
            "sample_span_hours": span_hours,
            "sample_span_days": span_days,
            "historical_live_filled_rows": historical_fills,
            "historical_live_attempt_rows": _safe_int(historical.get("replay_attempt_rows")),
            "historical_fill_rate": (
                historical_fills / float(max(1, _safe_int(historical.get("replay_attempt_rows"))))
                if _safe_int(historical.get("replay_attempt_rows")) > 0
                else 0.0
            ),
            "historical_fills_per_day": _per_day(historical_fills, span_days=span_days),
            "expected_fills_per_day": _per_day(expected_fills, span_days=span_days),
            "avg_trade_size_usd": avg_trade_size_usd,
            "historical_turnover_per_day_usd": _per_day(historical_turnover, span_days=span_days),
            "expected_turnover_per_day_usd": _per_day(expected_turnover, span_days=span_days),
            "historical_pnl_per_day_usd": historical_daily_pnl,
            "historical_pnl_30d_usd": historical_daily_pnl * DAYS_PER_MONTH,
            "historical_pnl_annualized_usd": historical_daily_pnl * DAYS_PER_YEAR,
            "expected_pnl_per_day_usd": median_daily_pnl,
            "expected_pnl_30d_usd": median_daily_pnl * DAYS_PER_MONTH,
            "expected_pnl_annualized_usd": median_daily_pnl * DAYS_PER_YEAR,
            "expected_mean_pnl_30d_usd": mean_daily_pnl * DAYS_PER_MONTH,
            "p05_pnl_30d_usd": p05_daily_pnl * DAYS_PER_MONTH,
            "p95_pnl_30d_usd": p95_daily_pnl * DAYS_PER_MONTH,
            "expected_pnl_pct_of_wallet_annualized": (
                (median_daily_pnl * DAYS_PER_YEAR / wallet_value_usd) * 100.0
                if wallet_value_usd > 0.0
                else 0.0
            ),
            "expected_pnl_pct_of_free_collateral_annualized": (
                (median_daily_pnl * DAYS_PER_YEAR / free_collateral_usd) * 100.0
                if free_collateral_usd > 0.0
                else 0.0
            ),
            "profit_probability": _safe_float(monte_carlo.get("profit_probability")),
            "loss_limit_hit_probability": _safe_float(monte_carlo.get("loss_limit_hit_probability")),
            "p95_drawdown_usd": _safe_float(monte_carlo.get("p95_max_drawdown_usd")),
            "p95_drawdown_pct_of_wallet": (
                (_safe_float(monte_carlo.get("p95_max_drawdown_usd")) / wallet_value_usd) * 100.0
                if wallet_value_usd > 0.0
                else 0.0
            ),
            "generalization_ratio": _safe_float(candidate.get("generalization_ratio")),
            "recommended_session_policy": candidate.get("recommended_session_policy") or [],
        }
    )
    projection["edge_status"] = _edge_status(
        candidate=candidate,
        probe_decision=probe_decision,
        is_best_variant=is_best_variant,
    )
    projection["policy_benchmark"] = policy_loss_from_projection(projection)
    projection["policy_loss"] = projection["policy_benchmark"]["policy_loss"]
    return projection


def _candidate_name(candidate: dict[str, Any]) -> str:
    profile = candidate.get("profile") or {}
    return str(profile.get("name") or candidate.get("name") or "candidate")


def _next_simulations(
    *,
    regime_summary: dict[str, Any],
    hypothesis_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for item in regime_summary.get("high_conviction_followups") or []:
        if not isinstance(item, dict):
            continue
        title = _candidate_name(item)
        key = ("regime_policy_followup", title)
        if key in seen_keys:
            continue
        suggestions.append(
            _round_payload(
                {
                    "title": title,
                    "category": "regime_policy_followup",
                    "why": "Highest-conviction validated session-conditioned upgrade in the regime lab.",
                    "session_names": item.get("session_names") or [],
                    "validation_live_filled_rows": _safe_int(item.get("validation_live_filled_rows")),
                    "validation_profit_probability": _safe_float(item.get("validation_profit_probability")),
                    "validation_p05_arr_pct": _safe_float(item.get("validation_p05_arr_pct")),
                    "frontier_focus_tags": item.get("frontier_focus_tags") or [],
                }
            )
        )
        seen_keys.add(key)
        if len(suggestions) >= 1:
            break

    loss_cluster = None
    regime_clusters = regime_summary.get("loss_cluster_filters") or []
    if regime_clusters:
        loss_cluster = regime_clusters[0]
    elif hypothesis_summary.get("loss_cluster_filters"):
        loss_cluster = (hypothesis_summary.get("loss_cluster_filters") or [None])[0]
    if isinstance(loss_cluster, dict):
        title = str(loss_cluster.get("filter_name") or "loss_cluster_revalidation")
        key = ("loss_cluster_revalidation", title)
        if key not in seen_keys:
            suggestions.append(
                _round_payload(
                    {
                        "title": title,
                        "category": "loss_cluster_revalidation",
                        "why": "Largest recurring loss bucket on the current tape; this should be suppressed or revalidated before size expansion.",
                        "session_name": str(loss_cluster.get("session_name") or ""),
                        "direction": str(loss_cluster.get("direction") or ""),
                        "price_bucket": str(loss_cluster.get("price_bucket") or ""),
                        "delta_bucket": str(loss_cluster.get("delta_bucket") or ""),
                        "historical_loss_usd": _safe_float(loss_cluster.get("total_loss_usd")),
                    }
                )
            )
            seen_keys.add(key)

    for item in regime_summary.get("size_ready_followups") or []:
        if not isinstance(item, dict):
            continue
        title = _candidate_name(item)
        key = ("capacity_revalidation", title)
        if key in seen_keys:
            continue
        suggestions.append(
            _round_payload(
                {
                    "title": title,
                    "category": "capacity_revalidation",
                    "why": "Validated policy edge exists, but size stress still fails; rerun size-aware Monte Carlo at $10/$20/$50 before promotion.",
                    "size_readiness_status": str(item.get("size_readiness_status") or ""),
                    "validation_live_filled_rows": _safe_int(item.get("validation_live_filled_rows")),
                    "shadow_trade_sizes_usd": item.get("shadow_trade_sizes_usd") or [],
                }
            )
        )
        seen_keys.add(key)
        break

    return suggestions[:3]


def build_expectation_summary(
    *,
    current_probe: dict[str, Any],
    runtime_truth: dict[str, Any],
    baseline: dict[str, Any],
    regime_summary: dict[str, Any],
    hypothesis_summary: dict[str, Any],
) -> dict[str, Any]:
    current_candidate = current_probe.get("current_candidate") or {}
    best_candidate = current_probe.get("best_candidate") or {}
    if not isinstance(current_candidate, dict) or not isinstance(best_candidate, dict):
        raise ValueError("Current probe artifact is missing candidate payloads.")

    wallet_counts = ((runtime_truth.get("accounting_reconciliation") or {}).get("remote_wallet_counts") or {})
    wallet_value_usd = _safe_float(wallet_counts.get("total_wallet_value_usd"))
    free_collateral_usd = _safe_float(wallet_counts.get("free_collateral_usd"))
    decision = current_probe.get("decision") or {}
    deploy_recommendation = str(current_probe.get("deploy_recommendation") or "unknown")
    span_hours = _sample_span_hours(baseline=baseline, current_probe=current_probe)
    current_live_projection = _projection_block(
        label="current_live",
        candidate=current_candidate,
        span_hours=span_hours,
        wallet_value_usd=wallet_value_usd,
        free_collateral_usd=free_collateral_usd,
        probe_decision=decision,
        deploy_recommendation=deploy_recommendation,
        is_best_variant=False,
    )
    best_projection = _projection_block(
        label="best_validated_variant",
        candidate=best_candidate,
        span_hours=span_hours,
        wallet_value_usd=wallet_value_usd,
        free_collateral_usd=free_collateral_usd,
        probe_decision=decision,
        deploy_recommendation=deploy_recommendation,
        is_best_variant=True,
    )

    summary = {
        "metric_name": "btc5_portfolio_expectation",
        "generated_at": _now_utc(),
        "portfolio": _round_payload(
            {
                "wallet_value_usd": wallet_value_usd,
                "free_collateral_usd": free_collateral_usd,
            }
        ),
        "observed_window": _round_payload(
            {
                "decision_rows": _safe_int(baseline.get("deduped_rows")),
                "live_filled_rows": _safe_int(baseline.get("deduped_live_filled_rows")),
                "sample_span_hours": span_hours,
                "sample_span_days": span_hours / 24.0 if span_hours > 0.0 else 0.0,
                "rows_by_source": baseline.get("rows_by_source") or {},
            }
        ),
        "current_live": current_live_projection,
        "best_validated_variant": best_projection,
        "validation_state": {
            "deploy_recommendation": deploy_recommendation,
            "decision": decision,
            "capital_stage_recommendation": current_probe.get("capital_stage_recommendation") or {},
            "capital_scale_recommendation": current_probe.get("capital_scale_recommendation") or {},
            "execution_drag_summary": current_probe.get("execution_drag_summary") or {},
            "simulator_policy_loss": {
                "ranking_metric": "simulator_policy_loss_lower_is_better",
                "current_live": _safe_float(current_live_projection.get("policy_loss")),
                "best_validated_variant": _safe_float(best_projection.get("policy_loss")),
                "delta": _safe_float(current_live_projection.get("policy_loss"))
                - _safe_float(best_projection.get("policy_loss")),
            },
        },
        "next_simulations": _next_simulations(
            regime_summary=regime_summary,
            hypothesis_summary=hypothesis_summary,
        ),
    }
    current_expected = _safe_float(summary["current_live"].get("expected_pnl_annualized_usd"))
    best_expected = _safe_float(summary["best_validated_variant"].get("expected_pnl_annualized_usd"))
    summary["delta_vs_current"] = _round_payload(
        {
            "expected_pnl_30d_usd": _safe_float(summary["best_validated_variant"].get("expected_pnl_30d_usd"))
            - _safe_float(summary["current_live"].get("expected_pnl_30d_usd")),
            "expected_pnl_annualized_usd": best_expected - current_expected,
            "profit_probability": _safe_float(summary["best_validated_variant"].get("profit_probability"))
            - _safe_float(summary["current_live"].get("profit_probability")),
            "expected_fills_per_day": _safe_float(summary["best_validated_variant"].get("expected_fills_per_day"))
            - _safe_float(summary["current_live"].get("expected_fills_per_day")),
        }
    )
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    current_live = summary["current_live"]
    best = summary["best_validated_variant"]
    validation = summary["validation_state"]
    lines = [
        "# BTC5 Portfolio Expectation",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Wallet value: `${summary['portfolio']['wallet_value_usd']:.2f}`",
        f"- Free collateral: `${summary['portfolio']['free_collateral_usd']:.2f}`",
        f"- Observed sample span: `{summary['observed_window']['sample_span_hours']:.2f}` hours",
        f"- Decision rows: `{summary['observed_window']['decision_rows']}`",
        f"- Live-filled rows: `{summary['observed_window']['live_filled_rows']}`",
        "",
        "## Current Live",
        "",
        f"- Expected PnL over next 30d at current cadence: `${current_live['expected_pnl_30d_usd']:.2f}`",
        f"- Expected annualized PnL on current wallet: `${current_live['expected_pnl_annualized_usd']:.2f}`",
        f"- Expected fills per day: `{current_live['expected_fills_per_day']:.2f}`",
        f"- Profit probability over one sample window: `{current_live['profit_probability']:.2%}`",
        f"- P95 drawdown: `${current_live['p95_drawdown_usd']:.2f}` ({current_live['p95_drawdown_pct_of_wallet']:.1f}% of wallet)",
        f"- Edge status: `{current_live['edge_status']['status']}` ({current_live['edge_status']['reason']})",
        "",
        "## Best Validated Variant",
        "",
        f"- Profile: `{best['profile_name']}`",
        f"- Expected PnL over next 30d at current cadence: `${best['expected_pnl_30d_usd']:.2f}`",
        f"- Expected annualized PnL on current wallet: `${best['expected_pnl_annualized_usd']:.2f}`",
        f"- Expected fills per day: `{best['expected_fills_per_day']:.2f}`",
        f"- Profit probability over one sample window: `{best['profit_probability']:.2%}`",
        f"- P95 drawdown: `${best['p95_drawdown_usd']:.2f}` ({best['p95_drawdown_pct_of_wallet']:.1f}% of wallet)",
        f"- Edge status: `{best['edge_status']['status']}` ({best['edge_status']['reason']})",
        "",
        "## Validation State",
        "",
        f"- Deploy recommendation: `{validation['deploy_recommendation']}`",
        f"- Probe gate reason: `{(validation['decision'] or {}).get('reason')}`",
        f"- Probe gate tags: `{(validation['decision'] or {}).get('probe_gate_reason_tags') or []}`",
        f"- Stage reason: `{(validation['capital_stage_recommendation'] or {}).get('stage_reason')}`",
        "",
        "## Next Simulations",
        "",
    ]
    for item in summary.get("next_simulations") or []:
        lines.append(f"- `{item['title']}` [{item['category']}] — {item['why']}")
    if not summary.get("next_simulations"):
        lines.append("- No follow-up simulations found in the current regime or hypothesis lab artifacts.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_LOCAL_DB), help="Optional local BTC5 sqlite path.")
    parser.add_argument(
        "--rows-json",
        default=str(DEFAULT_REMOTE_ROWS_JSON),
        help="Checked-in row cache used when the local DB is empty.",
    )
    parser.add_argument(
        "--current-probe-json",
        default=str(DEFAULT_CURRENT_PROBE_JSON),
        help="Current BTC5 autoresearch probe artifact.",
    )
    parser.add_argument(
        "--regime-summary-json",
        default=str(DEFAULT_REGIME_SUMMARY_JSON),
        help="BTC5 regime policy lab summary artifact.",
    )
    parser.add_argument(
        "--hypothesis-summary-json",
        default=str(DEFAULT_HYPOTHESIS_SUMMARY_JSON),
        help="BTC5 hypothesis lab summary artifact.",
    )
    parser.add_argument(
        "--runtime-truth-json",
        default=str(DEFAULT_RUNTIME_TRUTH_JSON),
        help="Runtime truth artifact for wallet and deployment state.",
    )
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON path.")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output markdown path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    rows_json = Path(args.rows_json)
    rows, baseline = assemble_observed_rows(
        db_path=db_path if db_path.exists() else None,
        include_archive_csvs=False,
        archive_glob=DEFAULT_ARCHIVE_GLOB,
        refresh_remote=False,
        remote_cache_json=rows_json,
    )
    baseline["deduped_rows"] = len(rows)

    current_probe = _load_json(Path(args.current_probe_json))
    regime_summary = _load_json(Path(args.regime_summary_json), required=False)
    hypothesis_summary = _load_json(Path(args.hypothesis_summary_json), required=False)
    runtime_truth = _load_json(Path(args.runtime_truth_json))
    summary = build_expectation_summary(
        current_probe=current_probe,
        runtime_truth=runtime_truth,
        baseline=baseline,
        regime_summary=regime_summary,
        hypothesis_summary=hypothesis_summary,
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
