from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import scripts.btc5_hypothesis_lab as hypothesis_lab
from scripts.btc5_hypothesis_lab import (
    HypothesisSpec,
    _best_live_followups,
    _best_one_sided_followups,
    _capacity_stress_candidates,
    _candidate_from_profile_result,
    _follow_up_candidates,
    _follow_up_candidates_with_tradeoffs,
    _high_conviction_followups,
    _loss_cluster_filters,
    _loss_cluster_suppression_candidates,
    _last_improvement_for_hypothesis,
    _recommended_session_policy,
    _size_ready_followups,
    build_hypothesis_specs,
    evaluate_hypothesis_walk_forward,
    priced_rows,
    rank_hypothesis_pool,
    summarize_hypothesis_history,
)
from scripts.btc5_monte_carlo import GuardrailProfile


ET_ZONE = ZoneInfo("America/New_York")


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    base = datetime(2026, 3, 1, 10, 0, tzinfo=ET_ZONE)
    row_id = 1
    for day in range(15):
        down_dt = (base + timedelta(days=day)).astimezone(timezone.utc)
        up_dt = (base + timedelta(days=day, hours=2)).astimezone(timezone.utc)
        rows.append(
            {
                "id": row_id,
                "window_start_ts": int(down_dt.timestamp()),
                "slug": f"btc-updown-5m-{row_id}",
                "direction": "DOWN",
                "delta": -0.00008,
                "abs_delta": 0.00008,
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "won": True,
                "pnl_usd": 5.2,
                "realized_pnl_usd": 5.2,
                "order_status": "live_filled",
                "updated_at": down_dt.isoformat(),
            }
        )
        row_id += 1
        rows.append(
            {
                "id": row_id,
                "window_start_ts": int(up_dt.timestamp()),
                "slug": f"btc-updown-5m-{row_id}",
                "direction": "UP",
                "delta": 0.00011,
                "abs_delta": 0.00011,
                "order_price": 0.50,
                "trade_size_usd": 5.0,
                "won": False,
                "pnl_usd": -5.0,
                "realized_pnl_usd": -5.0,
                "order_status": "live_filled",
                "updated_at": up_dt.isoformat(),
            }
        )
        row_id += 1
    rows.append(
        {
            "id": row_id,
            "window_start_ts": int((base + timedelta(days=20)).astimezone(timezone.utc).timestamp()),
            "slug": f"btc-updown-5m-{row_id}",
            "direction": "UP",
            "delta": 0.00020,
            "abs_delta": 0.00020,
            "order_price": None,
            "trade_size_usd": 0.0,
            "won": False,
            "pnl_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "order_status": "skip_price_outside_guardrails",
            "updated_at": (base + timedelta(days=20)).astimezone(timezone.utc).isoformat(),
        }
    )
    return rows


def test_priced_rows_filters_unpriced_observations() -> None:
    rows = priced_rows(_synthetic_rows())
    assert len(rows) == 30
    assert all(row["priced_observation"] for row in rows)


def test_build_hypothesis_specs_includes_hour_specific_variants() -> None:
    rows = priced_rows(_synthetic_rows())
    specs = build_hypothesis_specs(rows, min_rows_per_hour=4)
    names = {spec.name for spec in specs}
    assert any("hour_et_10" in name for name in names)
    assert any("down" in name for name in names)


def test_summarize_hypothesis_history_matches_directional_hour_edge() -> None:
    rows = priced_rows(_synthetic_rows())
    spec = HypothesisSpec(
        name="down_hour_10",
        direction="DOWN",
        max_abs_delta=0.00010,
        up_max_buy_price=None,
        down_max_buy_price=0.49,
        et_hours=(10,),
        session_name="hour_et_10",
    )
    history = summarize_hypothesis_history(rows, spec)
    assert history["replay_live_filled_rows"] == 15
    assert history["replay_live_filled_pnl_usd"] > 70.0


def test_evaluate_hypothesis_walk_forward_finds_persistent_edge() -> None:
    rows = priced_rows(_synthetic_rows())
    spec = HypothesisSpec(
        name="down_hour_10",
        direction="DOWN",
        max_abs_delta=0.00010,
        up_max_buy_price=None,
        down_max_buy_price=0.49,
        et_hours=(10,),
        session_name="hour_et_10",
    )
    result = evaluate_hypothesis_walk_forward(
        rows,
        spec,
        paths=100,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        min_train_rows=8,
        min_validate_rows=4,
        min_train_fills=2,
        min_validate_fills=1,
    )
    assert result is not None
    assert result["summary"]["splits_evaluated"] >= 2
    assert result["summary"]["validation_replay_pnl_usd"] > 0.0
    assert result["summary"]["validation_median_arr_pct"] > 0.0


def test_recommended_session_policy_matches_runtime_contract() -> None:
    candidate = {
        "hypothesis": {
            "name": "hyp_down_d0.00010_open_et",
            "session_name": "open_et",
            "et_hours": [9, 10, 11],
            "max_abs_delta": 0.0001,
            "up_max_buy_price": None,
            "down_max_buy_price": 0.49,
        }
    }
    policy = _recommended_session_policy(candidate)
    assert len(policy) == 1
    record = policy[0]
    assert set(record.keys()) == {"name", "et_hours", "max_abs_delta", "down_max_buy_price"}
    assert record["name"] == "open_et"
    assert record["et_hours"] == [9, 10, 11]


def test_follow_up_candidates_are_deterministic_and_runtime_ready() -> None:
    ranked = _follow_up_candidates(
        [
            {
                "hypothesis": {
                    "name": "zzz",
                    "session_name": "open_et",
                    "et_hours": [9, 10, 11],
                    "max_abs_delta": 0.0001,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.50,
                },
                "summary": {"ranking_score": 2.0, "evidence_band": "candidate"},
            },
            {
                "hypothesis": {
                    "name": "aaa",
                    "session_name": "midday_et",
                    "et_hours": [12, 13],
                    "max_abs_delta": 0.00008,
                    "up_max_buy_price": 0.48,
                    "down_max_buy_price": 0.49,
                },
                "summary": {"ranking_score": 2.0, "evidence_band": "validated"},
            },
        ]
    )
    assert [item["name"] for item in ranked] == ["aaa", "zzz"]
    assert {
        "name",
        "direction",
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
        "arr_improvement_vs_active_pct",
        "p05_arr_improvement_vs_active_pct",
        "fill_retention_vs_active",
        "execution_realism_score",
        "execution_realism_label",
        "follow_up_families",
        "frontier_focus_tags",
        "frontier_bias_score",
        "high_conviction_score",
        "candidate_class",
        "candidate_class_reason_tags",
        "research_status",
        "promotion_gate",
    }.issubset(set(ranked[0].keys()))


def test_low_retention_down_only_candidate_stays_probe_only() -> None:
    active_candidate = {
        "name": "active_profile",
        "validation_median_arr_pct": 100.0,
        "validation_p05_arr_pct": 50.0,
        "validation_live_filled_rows": 17,
    }
    follow_ups = _follow_up_candidates_with_tradeoffs(
        [
            {
                "hypothesis": {
                    "name": "hyp_down_probe",
                    "direction": "DOWN",
                    "session_name": "hour_et_11",
                    "et_hours": [11],
                    "max_abs_delta": 0.00010,
                    "up_max_buy_price": None,
                    "down_max_buy_price": 0.50,
                },
                "summary": {
                    "ranking_score": 500.0,
                    "evidence_band": "validated",
                    "validation_live_filled_rows": 5,
                    "generalization_ratio": 0.6,
                    "validation_median_arr_pct": 250.0,
                    "validation_p05_arr_pct": 120.0,
                },
            }
        ],
        active_candidate=active_candidate,
        limit=None,
    )
    assert len(follow_ups) == 1
    candidate = follow_ups[0]
    assert candidate["candidate_class"] == "probe_only"
    assert "down_only" in candidate["follow_up_families"]
    assert "probe_only_exploratory" in candidate["follow_up_families"]
    assert "fill_retention_below_0.85" in candidate["candidate_class_reason_tags"]


def test_candidate_from_profile_result_exposes_standard_summary_fields() -> None:
    profile = GuardrailProfile(
        "active_profile",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )
    candidate = _candidate_from_profile_result(
        profile=profile,
        evaluated={
            "hypothesis": {
                "name": "candidate_a",
                "session_name": "open_et",
                "et_hours": [9, 10, 11],
                "max_abs_delta": 0.0001,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.50,
            },
            "summary": {
                "ranking_score": 5.0,
                "evidence_band": "validated",
                "validation_live_filled_rows": 12,
                "generalization_ratio": 0.85,
                "validation_median_arr_pct": 50.0,
                "validation_p05_arr_pct": 30.0,
            },
        },
    )
    assert candidate["name"] == "candidate_a"
    assert candidate["validation_live_filled_rows"] == 12
    assert candidate["generalization_ratio"] == 0.85
    assert candidate["validation_median_arr_pct"] == 50.0
    assert candidate["validation_p05_arr_pct"] == 30.0


def test_hypothesis_summary_staleness_fields_are_present() -> None:
    rows = priced_rows(_synthetic_rows())
    last_ts = _last_improvement_for_hypothesis(
        rows,
        {
            "name": "down_hour_10",
            "direction": "DOWN",
            "max_abs_delta": 0.00010,
            "up_max_buy_price": None,
            "down_max_buy_price": 0.49,
            "et_hours": [10],
            "session_name": "hour_et_10",
        },
    )
    assert last_ts is not None
    now = datetime.now(timezone.utc)
    hours_since = (now - last_ts).total_seconds() / 3600.0
    assert isinstance(hours_since, float)


def test_rank_hypothesis_pool_biases_down_open_quote_bucket() -> None:
    rows = priced_rows(_synthetic_rows())
    focused = HypothesisSpec(
        name="focused_down_open",
        direction="DOWN",
        max_abs_delta=0.00010,
        up_max_buy_price=None,
        down_max_buy_price=0.48,
        et_hours=(9, 10, 11),
        session_name="open_et",
    )
    broad = HypothesisSpec(
        name="broad_up",
        direction="UP",
        max_abs_delta=0.00010,
        up_max_buy_price=0.50,
        down_max_buy_price=None,
        et_hours=(12, 13),
        session_name="midday_et",
    )
    ranked = rank_hypothesis_pool(
        rows,
        [broad, focused],
        max_candidates=2,
        min_live_fills=3,
    )
    assert ranked
    assert ranked[0].name == "focused_down_open"


def test_capacity_stress_candidates_emit_scaling_fields() -> None:
    rows = priced_rows(_synthetic_rows())
    spec = HypothesisSpec(
        name="down_hour_10",
        direction="DOWN",
        max_abs_delta=0.00010,
        up_max_buy_price=None,
        down_max_buy_price=0.49,
        et_hours=(10,),
        session_name="hour_et_10",
    )
    evaluated = evaluate_hypothesis_walk_forward(
        rows,
        spec,
        paths=100,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        min_train_rows=8,
        min_validate_rows=4,
        min_train_fills=2,
        min_validate_fills=1,
    )
    stress = _capacity_stress_candidates(
        rows,
        evaluated,
        paths=90,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        min_train_rows=8,
        min_validate_rows=4,
        min_train_fills=2,
        min_validate_fills=1,
    )
    assert stress
    assert {
        "name",
        "variant",
        "expected_fill_lift",
        "expected_median_pnl_delta_usd",
        "expected_p05_arr_delta_pct",
        "evidence_band",
    }.issubset(stress[0].keys())


def test_hypothesis_summary_emits_live_and_one_sided_followups() -> None:
    rows = priced_rows(_synthetic_rows())
    specs = build_hypothesis_specs(rows, min_rows_per_hour=4)
    ranked = rank_hypothesis_pool(rows, specs, max_candidates=6, min_live_fills=3)
    evaluated = [
        result
        for spec in ranked
        if (
            result := evaluate_hypothesis_walk_forward(
                rows,
                spec,
                paths=60,
                block_size=2,
                loss_limit_usd=10.0,
                seed=9,
                min_train_rows=8,
                min_validate_rows=4,
                min_train_fills=2,
                min_validate_fills=1,
            )
        )
    ]
    follow_ups = _follow_up_candidates(evaluated)
    assert len(follow_ups) <= 5
    assert all(isinstance(item.get("follow_up_families"), list) for item in follow_ups)
    best_live = _best_live_followups(follow_ups)
    assert len(best_live) <= 5
    one_sided = _best_one_sided_followups(follow_ups)
    assert len(one_sided) <= 5
    high_conviction = _high_conviction_followups(follow_ups)
    assert len(high_conviction) <= 5
    assert high_conviction
    assert {
        "frontier_focus_tags",
        "high_conviction_score",
        "candidate_class",
        "candidate_class_reason_tags",
        "research_status",
        "promotion_gate",
    }.issubset(high_conviction[0].keys())
    size_ready = _size_ready_followups(
        rows,
        follow_ups,
        paths=60,
        block_size=2,
        loss_limit_usd=10.0,
        seed=9,
    )
    assert size_ready
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
    }.issubset(size_ready[0].keys())


def test_loss_cluster_suppression_candidates_identify_negative_clusters() -> None:
    rows = priced_rows(_synthetic_rows())
    spec = HypothesisSpec(
        name="active_any",
        direction=None,
        max_abs_delta=0.00015,
        up_max_buy_price=0.51,
        down_max_buy_price=0.51,
        et_hours=tuple(),
        session_name="any",
    )
    evaluated = evaluate_hypothesis_walk_forward(
        rows,
        spec,
        paths=80,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        min_train_rows=8,
        min_validate_rows=4,
        min_train_fills=2,
        min_validate_fills=1,
    )
    clusters = _loss_cluster_suppression_candidates(rows, evaluated)
    assert isinstance(clusters, list)
    assert clusters
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
    }.issubset(clusters[0].keys())
    assert clusters[0]["candidate_class"] == "suppress_cluster"
    assert "loss_cluster_suppression" in clusters[0]["follow_up_families"]
    filters = _loss_cluster_filters(clusters)
    assert filters
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
    }.issubset(filters[0].keys())


def test_main_writes_empty_summary_when_no_priced_rows(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "hypothesis_lab"
    args = argparse.Namespace(
        db_path=Path("data/btc_5min_maker.db"),
        output_dir=output_dir,
        strategy_env=Path("config/btc5_strategy.env"),
        override_env=Path("state/btc5_autoresearch.env"),
        include_archive_csvs=False,
        archive_glob="unused",
        refresh_remote=False,
        remote_cache_json=Path("reports/btc5_remote_rows.json"),
        paths=50,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        max_candidates=10,
        top_hypotheses=5,
        min_full_history_fills=3,
        min_train_rows=8,
        min_validate_rows=4,
        min_train_fills=1,
        min_validate_fills=1,
        min_rows_per_hour=4,
        write_latest=False,
    )
    rows = [
        {
            "id": 1,
            "window_start_ts": int(datetime(2026, 3, 9, 10, 0, tzinfo=timezone.utc).timestamp()),
            "slug": "btc-updown-5m-empty",
            "direction": "DOWN",
            "delta": -0.00008,
            "abs_delta": 0.00008,
            "order_price": None,
            "trade_size_usd": 0.0,
            "won": False,
            "pnl_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "order_status": "skip_price_outside_guardrails",
            "updated_at": datetime(2026, 3, 9, 10, 0, tzinfo=timezone.utc).isoformat(),
        }
    ]

    monkeypatch.setattr(hypothesis_lab, "parse_args", lambda: args)
    monkeypatch.setattr(hypothesis_lab, "assemble_observed_rows", lambda **_: (rows, {"source": "test"}))

    assert hypothesis_lab.main() == 0

    summary = json.loads((output_dir / "summary.json").read_text())
    assert summary["input"]["priced_window_rows"] == 0
    assert summary["best_hypothesis"] is None
    assert summary["best_candidate"]["name"] == "active_profile"
    assert summary["best_candidate"]["candidate_class"] == "hold_current"
    assert summary["best_candidate"]["max_abs_delta"] == 0.00015
    assert summary["deployment_recommendation"] == "hold_current"
    assert summary["candidate_class_breakdown"] == {
        "promote": 0,
        "hold_current": 1,
        "probe_only": 0,
        "suppress_cluster": 0,
    }
