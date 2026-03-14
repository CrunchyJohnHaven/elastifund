"""Markdown renderer for BTC5 Monte Carlo reports."""

from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def render_monte_carlo_markdown(summary: dict[str, Any]) -> str:
    current_arr_pct = 0.0
    for candidate in summary["candidates"]:
        if candidate["profile"]["name"] == summary["current_live_profile"]["name"]:
            current_arr_pct = _safe_float(candidate["continuation"].get("median_arr_pct"), 0.0)
            break
    lines = [
        "# BTC5 Monte Carlo Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Primary DB: `{summary['db_path']}`",
        f"- Observed decision rows: `{summary['input']['observed_window_rows']}`",
        f"- Observed live-filled rows: `{summary['input']['live_filled_rows']}`",
        f"- Observed realized PnL: `{summary['input']['observed_pnl_usd']:.4f}` USD",
        f"- Monte Carlo paths: `{summary['simulation']['paths']}`",
        f"- Horizon trades per path: `{summary['simulation']['horizon_trades']}`",
        f"- Bootstrap block size: `{summary['simulation']['block_size']}`",
        "",
        "## Baseline",
        "",
        f"- Deduped rows by source: `{summary['baseline']['rows_by_source']}`",
        f"- Window range: `{summary['baseline']['first_window_start_ts']}` to `{summary['baseline']['last_window_start_ts']}`",
        "",
        "## Candidate Ranking",
        "",
        "| Rank | Profile | Hist ARR | MC Median ARR | ARR Delta vs Current | Profit Prob | P95 Drawdown | Loss-Limit Hit |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for index, candidate in enumerate(summary["candidates"], start=1):
        continuation = candidate["continuation"]
        monte_carlo = candidate["monte_carlo"]
        arr_delta_pct = _safe_float(continuation.get("median_arr_pct"), 0.0) - current_arr_pct
        lines.append(
            "| "
            + f"{index} | {candidate['profile']['name']} | "
            + f"{continuation['historical_arr_pct']:.2f}% | "
            + f"{continuation['median_arr_pct']:.2f}% | "
            + f"{arr_delta_pct:.2f}pp | "
            + f"{monte_carlo['profit_probability']:.2%} | "
            + f"{monte_carlo['p95_max_drawdown_usd']:.4f} | "
            + f"{monte_carlo['loss_limit_hit_probability']:.2%} |"
        )

    best = summary["best_candidate"]
    comparison = summary.get("best_vs_current") or {}
    capacity_stress = summary.get("capacity_stress_summary") or {}
    lines.extend(
        [
            "",
            "## Best Candidate",
            "",
            f"- Name: `{best['profile']['name']}`",
            f"- Max abs delta: `{best['profile']['max_abs_delta']}`",
            f"- UP max buy price: `{best['profile']['up_max_buy_price']}`",
            f"- DOWN max buy price: `{best['profile']['down_max_buy_price']}`",
            f"- Historical continuation ARR: `{best['continuation']['historical_arr_pct']:.2f}%`",
            f"- Monte Carlo median continuation ARR: `{best['continuation']['median_arr_pct']:.2f}%`",
            f"- Monte Carlo P05 continuation ARR: `{best['continuation']['p05_arr_pct']:.2f}%`",
            f"- Replay PnL: `{best['historical']['replay_live_filled_pnl_usd']:.4f}` USD on `{best['historical']['replay_live_filled_rows']}` fills",
            f"- Monte Carlo median PnL: `{best['monte_carlo']['median_total_pnl_usd']:.4f}` USD",
            f"- Monte Carlo profit probability: `{best['monte_carlo']['profit_probability']:.2%}`",
            f"- Monte Carlo P95 drawdown: `{best['monte_carlo']['p95_max_drawdown_usd']:.4f}` USD",
            "",
            "## Best vs Current Live",
            "",
            f"- Best candidate: `{comparison.get('best_candidate_name')}`",
            f"- Current live candidate: `{comparison.get('current_candidate_name')}`",
            f"- Historical continuation ARR delta vs current: `{comparison.get('historical_arr_pct_delta', 0.0):.2f}` percentage points",
            f"- Monte Carlo median continuation ARR delta vs current: `{comparison.get('median_arr_pct_delta', 0.0):.2f}` percentage points",
            f"- Monte Carlo P05 continuation ARR delta vs current: `{comparison.get('p05_arr_pct_delta', 0.0):.2f}` percentage points",
            f"- Replay PnL delta vs current: `{comparison.get('replay_pnl_delta_usd', 0.0):.4f}` USD",
            f"- Monte Carlo median PnL delta vs current: `{comparison.get('median_pnl_delta_usd', 0.0):.4f}` USD",
            f"- Profit-probability delta vs current: `{comparison.get('profit_probability_delta', 0.0):.2%}`",
            f"- P95 drawdown delta vs current: `{comparison.get('p95_drawdown_delta_usd', 0.0):.4f}` USD",
            "",
            "## Caveat",
            "",
            "This engine is empirical and bootstrap-based. It ranks guardrail profiles from the live BTC5 fill tape; it does not invent extra alpha beyond the observed distribution.",
        ]
    )
    if isinstance(capacity_stress, dict) and capacity_stress.get("profiles"):
        lines.extend(
            [
                "",
                "## Capacity Stress",
                "",
                f"- Recommended reference profile: `{capacity_stress.get('recommended_reference')}`",
            ]
        )
        for label, payload in (capacity_stress.get("profiles") or {}).items():
            if not isinstance(payload, dict):
                continue
            lines.extend(
                [
                    "",
                    f"### {label}",
                    "",
                    f"- Profile name: `{payload.get('profile_name', 'unknown')}`",
                    f"- Reference trade size: `{_safe_float(payload.get('reference_trade_size_usd'), 0.0):.2f}` USD",
                    "",
                    "| Ticket | Track | Fill Retention | 1-Tick Worse | Retry Fail | Median ARR Delta | P95 Drawdown Impact |",
                    "|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            for sweep in payload.get("size_sweeps") or []:
                lines.append(
                    "| "
                    + f"{_safe_float(sweep.get('trade_size_usd'), 0.0):.2f} | "
                    + f"{str(sweep.get('sizing_track') or 'unknown')} | "
                    + f"{_safe_float(sweep.get('expected_fill_retention_ratio'), 0.0):.2%} | "
                    + f"{_safe_float(sweep.get('expected_one_tick_worse_fill_ratio'), 0.0):.2%} | "
                    + f"{_safe_float(sweep.get('expected_post_only_retry_failure_rate'), 0.0):.2%} | "
                    + f"{_safe_float(sweep.get('expected_median_arr_pct_delta'), 0.0):.2f}pp | "
                    + f"{_safe_float(sweep.get('p95_drawdown_impact_usd'), 0.0):.4f} |"
                )
    capital_ladder = summary.get("capital_ladder_summary") or {}
    if isinstance(capital_ladder, dict) and capital_ladder.get("metric_name") == "capital_ladder_summary":
        live_now = capital_ladder.get("live_now") or {}
        next_notional_gate = capital_ladder.get("next_notional_gate") or {}
        lines.extend(
            [
                "",
                "## Capital Ladder",
                "",
                f"- Recommended reference: `{capital_ladder.get('recommended_reference') or 'unknown'}`",
                f"- Safe live size now: `{_safe_float(live_now.get('safe_trade_size_usd'), 0.0):.2f}` USD",
                f"- Safe live stage now: `{live_now.get('safe_stage_label') or 'none'}`",
                f"- Shadow-ready sizes: `{capital_ladder.get('shadow_ready_trade_sizes_usd') or []}`",
                f"- Next higher-notional gate: `{next_notional_gate.get('trade_size_usd')}`",
                f"- Blocking categories: `{next_notional_gate.get('blocking_categories') or []}`",
            ]
        )
    shadow_trade_size_assessments = summary.get("shadow_trade_size_assessments") or []
    if shadow_trade_size_assessments:
        lines.extend(
            [
                "",
                "## Shadow Size Decisions",
                "",
                "| Ticket | Status | Fill Retention | Order Failed | Retry Fail | P05 ARR | P95 Drawdown | Evidence Verdict |",
                "|---|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for assessment in shadow_trade_size_assessments:
            lines.append(
                "| "
                + f"{_safe_float(assessment.get('trade_size_usd'), 0.0):.2f} | "
                + f"{str(assessment.get('status') or assessment.get('decision_status') or 'unknown')} | "
                + f"{_safe_float(assessment.get('expected_fill_retention_ratio'), 0.0):.2%} | "
                + f"{_safe_float(assessment.get('expected_order_failed_probability'), 0.0):.2%} | "
                + f"{_safe_float(assessment.get('expected_post_only_retry_failure_rate'), 0.0):.2%} | "
                + f"{_safe_float(assessment.get('expected_p05_arr_pct'), 0.0):.2f}% | "
                + f"{_safe_float(assessment.get('expected_p95_max_drawdown_usd'), 0.0):.4f} | "
                + f"{str(assessment.get('evidence_verdict') or 'unknown')} |"
            )
        for assessment in shadow_trade_size_assessments:
            lines.extend(
                [
                    "",
                    f"### Shadow `{_safe_float(assessment.get('trade_size_usd'), 0.0):.0f}`",
                    "",
                    f"- Blocking categories: `{assessment.get('blocking_categories') or []}`",
                    f"- Missing evidence: `{assessment.get('missing_evidence_items') or []}`",
                    f"- True negative evidence: `{assessment.get('true_negative_items') or []}`",
                    f"- Evidence required: `{assessment.get('evidence_required') or []}`",
                ]
            )
    return "\n".join(lines) + "\n"
