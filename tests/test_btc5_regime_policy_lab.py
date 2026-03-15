from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.btc5_monte_carlo import GuardrailProfile
from scripts.btc5_regime_policy_lab import build_session_filters, build_summary, enrich_rows


ET = ZoneInfo("America/New_York")


def _ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp())


def _row(
    *,
    row_id: int,
    ts: int,
    direction: str,
    order_price: float,
    pnl_usd: float,
    order_status: str = "live_filled",
    delta: float = 0.0001,
) -> dict[str, object]:
    return {
        "id": row_id,
        "window_start_ts": ts,
        "slug": f"btc-updown-5m-{ts}",
        "direction": direction,
        "delta": delta,
        "abs_delta": abs(delta),
        "order_price": order_price,
        "trade_size_usd": 5.0,
        "won": pnl_usd > 0,
        "pnl_usd": pnl_usd,
        "realized_pnl_usd": pnl_usd if order_status == "live_filled" else 0.0,
        "order_status": order_status,
        "updated_at": "2026-03-09T00:00:00+00:00",
    }


def test_build_session_filters_includes_dense_hours() -> None:
    rows = enrich_rows(
        [
            _row(row_id=idx, ts=_ts(2026, 3, 9, 10, idx * 5), direction="DOWN", order_price=0.49, pnl_usd=5.0)
            for idx in range(6)
        ]
    )
    filters = build_session_filters(rows, min_session_rows=4)
    assert ("open_et", (9, 10, 11)) in filters
    assert ("hour_et_10", (10,)) in filters


def test_build_summary_finds_session_override_that_beats_current() -> None:
    rows: list[dict[str, object]] = []
    row_id = 1
    for minute in range(0, 40, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 10, minute),
                direction="DOWN",
                order_price=0.50,
                pnl_usd=-5.0,
            )
        )
        row_id += 1
    for minute in range(40, 60, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 10, minute),
                direction="DOWN",
                order_price=0.49,
                pnl_usd=5.2,
            )
        )
        row_id += 1
    for minute in range(0, 30, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 12, minute),
                direction="DOWN",
                order_price=0.49,
                pnl_usd=5.1,
            )
        )
        row_id += 1

    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    summary = build_summary(
        rows=rows,
        db_path=Path("reports/tmp_remote_btc_5min_maker.db"),
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        paths=250,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
        min_replay_fills=6,
        min_session_rows=4,
        max_session_overrides=2,
        top_single_overrides_per_session=2,
        max_composed_candidates=16,
    )

    best = summary["best_policy"]
    assert best is not None
    assert best["policy"]["name"] == "policy_current_live_profile"
    assert not best["policy"]["overrides"]
    assert "recommended_session_policy" in summary
    assert isinstance(summary["recommended_session_policy"], list)
    assert summary["recommended_session_policy"] == []
    assert summary["best_vs_current"]["median_arr_pct_delta"] == 0.0
    assert summary["best_vs_current"]["replay_pnl_delta_usd"] == 0.0
    assert summary["best_candidate"]["name"] == summary["hold_current_candidate"]["name"]
    assert summary["best_validated_candidate"]["name"] == summary["best_candidate"]["name"]
    assert summary["best_candidate"]["candidate_class"] == "hold_current"
    assert summary["deployment_recommendation"] == "hold_current"
    assert summary["best_promote_ready_candidate"] is None
    assert summary["best_probe_only_candidate"] is not None
    assert summary["best_cluster_suppressor"] == summary["loss_cluster_suppression_candidates"][0]
    assert summary["best_ranked_policy"]["policy"]["name"] != "policy_current_live_profile"
    assert summary["best_ranked_candidate"]["candidate_class"] == "probe_only"
    assert "arr_delta_vs_active_pct" in summary
    assert "p05_arr_delta_vs_active_pct" in summary
    assert "validation_live_filled_rows" in summary
    assert "generalization_ratio" in summary
    assert "evidence_band" in summary
    assert "candidate_class_breakdown" in summary
    assert summary["candidate_class_breakdown"]["probe_only"] >= 1
    assert "last_improvement_at" in summary
    assert "hours_since_last_improvement" in summary
    assert summary["last_improvement_at"] is None or summary["last_improvement_at"].endswith("Z")
    assert summary["hours_since_last_improvement"] is None or summary["hours_since_last_improvement"] >= 0.0
    stress = summary["capacity_stress_candidates"]
    assert isinstance(stress, list)
    assert not stress
    follow_ups = summary["follow_up_candidates"]
    assert isinstance(follow_ups, list)
    assert 1 <= len(follow_ups) <= 5
    assert {
        "name",
        "session_name",
        "et_hours",
        "max_abs_delta",
        "up_max_buy_price",
        "down_max_buy_price",
        "ranking_score",
        "evidence_band",
        "validation_live_filled_rows",
        "generalization_ratio",
        "validation_median_arr_pct",
        "validation_p05_arr_pct",
        "validation_profit_probability",
        "validation_p95_drawdown_usd",
        "arr_improvement_vs_active_pct",
        "p05_arr_improvement_vs_active_pct",
        "fill_retention_vs_active",
        "execution_realism_score",
        "execution_realism_label",
        "follow_up_families",
        "frontier_focus_tags",
        "frontier_bias_score",
        "high_conviction_score",
        "frontier_selection_score",
        "candidate_class",
        "candidate_class_reason_tags",
        "research_status",
        "promotion_gate",
    }.issubset(follow_ups[0].keys())
    priorities = {"promote": 3, "hold_current": 2, "probe_only": 1, "suppress_cluster": 0}
    assert priorities[follow_ups[0]["candidate_class"]] >= priorities[follow_ups[-1]["candidate_class"]]
    assert "best_live_followups" in summary
    assert "best_one_sided_followups" in summary
    assert "high_conviction_followups" in summary
    assert "size_ready_followups" in summary
    assert isinstance(summary["best_live_followups"], list)
    assert isinstance(summary["best_one_sided_followups"], list)
    assert isinstance(summary["high_conviction_followups"], list)
    assert isinstance(summary["size_ready_followups"], list)
    assert summary["high_conviction_followups"]
    assert summary["size_ready_followups"]
    assert {
        "frontier_focus_tags",
        "high_conviction_score",
        "candidate_class",
        "candidate_class_reason_tags",
        "research_status",
        "promotion_gate",
    }.issubset(summary["high_conviction_followups"][0].keys())
    assert {
        "size_sweep_reference_trade_size_usd",
        "shadow_trade_sizes_usd",
        "max_shadow_trade_size_usd",
        "size_stress_sweeps",
        "size_readiness_score",
        "size_readiness_status",
        "candidate_class",
        "research_status",
        "promotion_gate",
    }.issubset(summary["size_ready_followups"][0].keys())
    assert "loss_cluster_suppression_candidates" in summary
    assert "loss_cluster_filters" in summary
    assert isinstance(summary["loss_cluster_suppression_candidates"], list)
    assert isinstance(summary["loss_cluster_filters"], list)
    assert summary["loss_cluster_suppression_candidates"]
    assert summary["loss_cluster_filters"]
    assert {
        "direction",
        "session_name",
        "price_bucket",
        "delta_bucket",
        "loss_rows",
        "total_loss_usd",
        "suggested_action",
        "follow_up_families",
        "candidate_class",
    }.issubset(summary["loss_cluster_suppression_candidates"][0].keys())
    assert summary["loss_cluster_suppression_candidates"][0]["candidate_class"] == "suppress_cluster"
    assert "loss_cluster_suppression" in summary["loss_cluster_suppression_candidates"][0]["follow_up_families"]
    assert {
        "filter_name",
        "direction",
        "session_name",
        "price_bucket",
        "delta_bucket",
        "loss_rows",
        "total_loss_usd",
        "severity",
        "filter_action",
        "revalidation_gate",
        "research_status",
    }.issubset(summary["loss_cluster_filters"][0].keys())


def test_build_summary_can_promote_two_session_policy() -> None:
    rows: list[dict[str, object]] = []
    row_id = 1
    for hour in (9, 14):
        for minute in (0,):
            rows.append(
                _row(
                    row_id=row_id,
                    ts=_ts(2026, 3, 9, hour, minute),
                    direction="DOWN",
                    order_price=0.50,
                    pnl_usd=-5.0,
                )
            )
            row_id += 1
        for minute in range(5, 55, 5):
            rows.append(
                _row(
                    row_id=row_id,
                    ts=_ts(2026, 3, 9, hour, minute),
                    direction="DOWN",
                    order_price=0.49 if hour == 9 else 0.48,
                    pnl_usd=5.2 if hour == 9 else 5.4,
                )
            )
            row_id += 1

    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    summary = build_summary(
        rows=rows,
        db_path=Path("reports/tmp_remote_btc_5min_maker.db"),
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        paths=250,
        block_size=3,
        loss_limit_usd=10.0,
        seed=11,
        min_replay_fills=8,
        min_session_rows=4,
        max_session_overrides=2,
        top_single_overrides_per_session=2,
        max_composed_candidates=16,
    )

    best = summary["best_policy"]
    assert best is not None
    assert len(best["policy"]["overrides"]) == 2
    assert summary["best_candidate"]["session_count"] == 2
    assert summary["best_candidate"]["candidate_class"] == "promote"
    assert summary["best_validated_candidate"]["candidate_class"] == "promote"
    assert summary["deployment_recommendation"] == "promote"
    assert len(summary["recommended_session_policy"]) == 2
    assert summary["best_vs_current"]["replay_pnl_delta_usd"] > 0
    assert summary["input"]["generated_composed_policies"] > 0
    assert summary["capacity_stress_candidates"]
    assert summary["capacity_stress_candidates"][0]["candidate_class"] == "probe_only"


def test_build_summary_uses_live_profile_baseline_when_no_policies_score() -> None:
    rows = [
        _row(
            row_id=1,
            ts=_ts(2026, 3, 9, 10, 0),
            direction="DOWN",
            order_price=0.0,
            pnl_usd=0.0,
            order_status="skip_price_outside_guardrails",
        )
    ]
    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    summary = build_summary(
        rows=rows,
        db_path=Path("reports/tmp_remote_btc_5min_maker.db"),
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        paths=50,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        min_replay_fills=6,
        min_session_rows=4,
        max_session_overrides=2,
        top_single_overrides_per_session=2,
        max_composed_candidates=8,
    )

    assert summary["best_policy"] is None
    assert summary["current_policy"] is None
    assert summary["active_profile"]["name"] == "current_live_profile"
    assert summary["best_candidate"]["name"] == "current_live_profile"
    assert summary["best_ranked_candidate"]["name"] == "current_live_profile"
    assert summary["best_candidate"]["max_abs_delta"] == current.max_abs_delta
    assert summary["best_candidate"]["up_max_buy_price"] == current.up_max_buy_price
    assert summary["best_candidate"]["down_max_buy_price"] == current.down_max_buy_price
    assert summary["best_candidate"]["candidate_class"] == "hold_current"
    assert summary["best_validated_candidate"]["candidate_class"] == "hold_current"
    assert summary["candidate_class_breakdown"] == {
        "promote": 0,
        "hold_current": 1,
        "probe_only": 0,
        "suppress_cluster": 0,
    }
