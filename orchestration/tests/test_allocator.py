from __future__ import annotations

import json
from datetime import date, timedelta
import sqlite3

import pytest

from orchestration.models import (
    AllocationMode,
    REVENUE_AUDIT_ENGINE,
    DeliverabilityRisk,
    NON_TRADING_AGENT,
    TRADING_AGENT,
)
from orchestration.resource_allocator import AllocatorConfig, ResourceAllocator, main
from orchestration.venue_router import SharedRiskBudget, VenueRouteCandidate, route_opportunity


def _allocator(tmp_path, **overrides) -> tuple[ResourceAllocator, AllocatorConfig]:
    config = AllocatorConfig(
        db_path=tmp_path / "allocator.db",
        default_mode=AllocationMode.THREE_LAYER,
        enable_thompson_sampling=True,
        trading_budget_cap_usd=100.0,
        non_trading_send_quota_cap=100,
        non_trading_llm_token_cap=10_000,
        fixed_trading_share=0.80,
        min_non_trading_share=0.10,
        min_observations_per_arm=5,
        prior_alpha=1.0,
        prior_beta=1.0,
        roi_success_threshold=0.0,
        observation_lookback_days=90,
        risk_parity_min_observations=10,
        volatility_floor=0.0001,
        thompson_discount_gamma=0.995,
        thompson_tilt_max_pct=0.35,
        agent_min_share=0.15,
        agent_max_share=0.85,
        cash_reserve_min_share=0.10,
        cash_reserve_yellow_share=0.15,
        cash_reserve_max_share=0.20,
        kelly_bootstrap_observations=5,
        kelly_high_confidence_observations=15,
        kelly_bootstrap_fraction=0.25,
        kelly_medium_fraction=1.0 / 3.0,
        kelly_high_fraction=0.50,
        high_confidence_information_ratio=0.20,
        cusum_threshold_sigma=3.0,
        cusum_drift_sigma=0.25,
    )
    if overrides:
        config = AllocatorConfig(**{**config.__dict__, **overrides})
    return ResourceAllocator(config=config), config


def _seed_observations(
    allocator: ResourceAllocator,
    *,
    base_day: date,
    trading_rois: list[float],
    non_trading_rois: list[float],
) -> None:
    assert len(trading_rois) == len(non_trading_rois)
    for offset, (trading_roi, non_trading_roi) in enumerate(zip(trading_rois, non_trading_rois, strict=True)):
        observed_on = base_day - timedelta(days=offset + 1)
        allocator.record_performance(
            agent_name=TRADING_AGENT,
            observed_on=observed_on,
            roi=trading_roi,
        )
        allocator.record_performance(
            agent_name=NON_TRADING_AGENT,
            observed_on=observed_on,
            roi=non_trading_roi,
        )


def test_store_initializes_expected_tables(tmp_path) -> None:
    allocator, config = _allocator(tmp_path)
    with sqlite3.connect(config.db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "allocation_decisions" in tables
    assert "allocation_observations" in tables
    assert "allocation_strategy_snapshots" in tables


def test_fixed_split_decision_persists_expected_budgets(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)
    decision = allocator.decide(
        decision_date=date(2026, 3, 7),
        mode=AllocationMode.FIXED_SPLIT,
        deliverability_risk=DeliverabilityRisk.GREEN,
    )

    assert decision.mode is AllocationMode.FIXED_SPLIT
    assert decision.trading_share == 0.80
    assert decision.non_trading_share == 0.20
    assert decision.cash_reserve_share == 0.0
    assert decision.trading_budget_usd == 80.0
    assert decision.non_trading_send_quota == 20
    assert decision.non_trading_llm_token_budget == 2000
    latest = allocator.store.latest_decision()
    assert latest is not None
    assert latest.decision_id == decision.decision_id
    assert allocator.store.status()["strategy_snapshots"] == 0


def test_thompson_sampling_is_deterministic_with_seed(tmp_path) -> None:
    allocator, config = _allocator(
        tmp_path,
        default_mode=AllocationMode.THOMPSON_SAMPLING,
        min_observations_per_arm=10,
    )
    base_day = date(2026, 3, 7)

    _seed_observations(
        allocator,
        base_day=base_day,
        trading_rois=[-0.02] * 9 + [0.03] * 3,
        non_trading_rois=[0.04] * 10 + [-0.01] * 2,
    )

    decision_a = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THOMPSON_SAMPLING,
        deliverability_risk=DeliverabilityRisk.GREEN,
        seed=7,
        persist=False,
    )
    decision_b = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THOMPSON_SAMPLING,
        deliverability_risk=DeliverabilityRisk.GREEN,
        seed=7,
        persist=False,
    )

    assert decision_a.mode is AllocationMode.THOMPSON_SAMPLING
    assert decision_a.non_trading_share == decision_b.non_trading_share
    assert decision_a.bandit_sample_non_trading == decision_b.bandit_sample_non_trading
    assert decision_a.non_trading_share > config.fixed_non_trading_share
    assert decision_a.non_trading_share > decision_a.trading_share


def test_three_layer_allocator_applies_bounds_and_persists_strategy_snapshots(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)
    base_day = date(2026, 3, 7)

    _seed_observations(
        allocator,
        base_day=base_day,
        trading_rois=[0.015] * 30,
        non_trading_rois=[0.004 + ((-1) ** offset) * 0.002 for offset in range(30)],
    )

    decision = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THREE_LAYER,
        seed=11,
    )

    assert decision.mode is AllocationMode.THREE_LAYER
    assert decision.cash_reserve_share == 0.10
    assert decision.trading_share == 0.85
    assert decision.non_trading_share == 0.15
    assert decision.trading_budget_usd == 76.5
    assert decision.metadata["layers"]["risk_parity"]["source"] == "recomputed"
    assert decision.metadata["layers"]["thompson_tilt"]["source"] == "recomputed"
    assert allocator.store.status()["strategy_snapshots"] == 2
    latest = allocator.store.latest_decision()
    assert latest is not None
    assert len(latest.strategy_documents) == 2
    assert all(doc["index"] == "elastifund-strategies" for doc in latest.strategy_documents)


def test_three_layer_escalates_cash_reserve_on_cusum_decay(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)
    base_day = date(2026, 3, 7)

    _seed_observations(
        allocator,
        base_day=base_day,
        trading_rois=[0.015] * 60 + [-0.05] * 10,
        non_trading_rois=[0.005] * 70,
    )

    decision = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THREE_LAYER,
        seed=5,
        persist=False,
    )

    assert decision.cash_reserve_share == 0.20
    assert decision.metadata["layers"]["cusum"][TRADING_AGENT]["decay_detected"] is True
    assert decision.metadata["layers"]["kelly"][TRADING_AGENT]["tier"] == "bootstrapping"
    assert any(doc["decay_detected"] is True for doc in decision.strategy_documents)


def test_three_layer_deliverability_risk_clamps_non_trading_increase(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)
    base_day = date(2026, 3, 7)

    baseline = allocator.decide(
        decision_date=base_day - timedelta(days=1),
        mode=AllocationMode.FIXED_SPLIT,
        deliverability_risk=DeliverabilityRisk.GREEN,
    )
    assert baseline.non_trading_share == 0.20

    _seed_observations(
        allocator,
        base_day=base_day,
        trading_rois=[-0.02] * 20,
        non_trading_rois=[0.03] * 20,
    )

    decision = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THREE_LAYER,
        deliverability_risk=DeliverabilityRisk.YELLOW,
        seed=3,
        persist=False,
    )

    assert decision.risk_override_applied is True
    assert decision.non_trading_share == baseline.non_trading_share
    assert decision.trading_share == baseline.trading_share
    assert decision.cash_reserve_share == 0.15
    assert "blocked a non-trading increase" in decision.rationale


def test_three_layer_reuses_monthly_baseline_and_weekly_tilt(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)
    base_day = date(2026, 3, 3)

    _seed_observations(
        allocator,
        base_day=base_day,
        trading_rois=[0.010] * 25,
        non_trading_rois=[0.008] * 25,
    )

    first = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THREE_LAYER,
        seed=11,
    )
    second = allocator.decide(
        decision_date=base_day + timedelta(days=2),
        mode=AllocationMode.THREE_LAYER,
        seed=999,
        persist=False,
    )

    assert first.metadata["periods"]["baseline_month"] == second.metadata["periods"]["baseline_month"]
    assert first.metadata["periods"]["tilt_week"] == second.metadata["periods"]["tilt_week"]
    assert second.metadata["layers"]["risk_parity"]["source"] == "reused"
    assert second.metadata["layers"]["thompson_tilt"]["source"] == "reused"
    assert second.metadata["layers"]["risk_parity"]["shares"] == first.metadata["layers"]["risk_parity"]["shares"]
    assert second.metadata["layers"]["thompson_tilt"]["shares"][TRADING_AGENT] == pytest.approx(
        first.metadata["layers"]["thompson_tilt"]["shares"][TRADING_AGENT]
    )
    assert second.metadata["layers"]["thompson_tilt"]["shares"][NON_TRADING_AGENT] == pytest.approx(
        first.metadata["layers"]["thompson_tilt"]["shares"][NON_TRADING_AGENT]
    )
    assert second.bandit_sample_trading == first.bandit_sample_trading
    assert second.bandit_sample_non_trading == first.bandit_sample_non_trading


def test_venue_router_prefers_higher_net_edge_after_costs() -> None:
    budget = SharedRiskBudget(hourly_cap_usd=50.0, daily_cap_usd=100.0)
    decision = route_opportunity(
        [
            VenueRouteCandidate(
                venue="polymarket",
                market_id="poly-1",
                opportunity_key="op-1",
                gross_edge=0.10,
                fee_rate=0.01,
                fill_probability=0.95,
                latency_penalty=0.002,
                notional_usd=10.0,
            ),
            VenueRouteCandidate(
                venue="kalshi",
                market_id="kalshi-1",
                opportunity_key="op-1",
                gross_edge=0.10,
                fee_rate=0.03,
                fill_probability=0.85,
                latency_penalty=0.004,
                notional_usd=10.0,
            ),
        ],
        budget=budget,
        min_net_edge=0.01,
    )

    assert decision.selected is not None
    assert decision.selected.venue == "polymarket"
    assert decision.selected_reason == "best_net_edge_after_costs"
    assert budget.hourly_used_usd == 10.0
    assert budget.daily_used_usd == 10.0
    assert any(rej.reason == "venue_not_best_net_edge" for rej in decision.rejections)


def test_venue_router_rejects_when_shared_hourly_budget_exhausted() -> None:
    budget = SharedRiskBudget(hourly_cap_usd=5.0, daily_cap_usd=100.0)
    decision = route_opportunity(
        [
            VenueRouteCandidate(
                venue="polymarket",
                market_id="poly-1",
                opportunity_key="op-2",
                gross_edge=0.08,
                fee_rate=0.005,
                fill_probability=0.95,
                latency_penalty=0.001,
                notional_usd=10.0,
            ),
            VenueRouteCandidate(
                venue="kalshi",
                market_id="kalshi-1",
                opportunity_key="op-2",
                gross_edge=0.07,
                fee_rate=0.006,
                fill_probability=0.95,
                latency_penalty=0.001,
                notional_usd=10.0,
            ),
        ],
        budget=budget,
        min_net_edge=0.01,
    )

    assert decision.selected is None
    assert decision.selected_reason == "shared_budget_exhausted_hourly"
    assert all(rej.reason == "shared_budget_exhausted_hourly" for rej in decision.rejections)
    assert budget.hourly_used_usd == 0.0


def test_venue_router_deduplicates_lower_edge_candidates() -> None:
    budget = SharedRiskBudget(hourly_cap_usd=50.0, daily_cap_usd=100.0)
    decision = route_opportunity(
        [
            VenueRouteCandidate(
                venue="polymarket",
                market_id="poly-strong",
                opportunity_key="op-3",
                gross_edge=0.09,
                fee_rate=0.01,
                fill_probability=0.95,
                latency_penalty=0.001,
                notional_usd=5.0,
            ),
            VenueRouteCandidate(
                venue="polymarket",
                market_id="poly-weak",
                opportunity_key="op-3",
                gross_edge=0.07,
                fee_rate=0.01,
                fill_probability=0.95,
                latency_penalty=0.001,
                notional_usd=5.0,
            ),
        ],
        budget=budget,
        min_net_edge=0.01,
    )

    assert decision.selected is not None
    assert decision.selected.market_id == "poly-strong"
    assert any(rej.reason == "duplicate_opportunity_lower_edge" for rej in decision.rejections)


def test_engine_family_overlay_adds_advisory_snapshots(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)
    base_day = date(2026, 3, 7)

    _seed_observations(
        allocator,
        base_day=base_day,
        trading_rois=[0.015] * 30,
        non_trading_rois=[0.004 + ((-1) ** offset) * 0.002 for offset in range(30)],
    )

    decision = allocator.decide(
        decision_date=base_day,
        mode=AllocationMode.THREE_LAYER,
        seed=11,
        engine_inputs={
            TRADING_AGENT: {
                "expected_net_cash_30d": 16.0,
                "confidence": 0.60,
                "required_budget": 60.0,
                "capacity_limits": {"budget_usd": 25.0},
                "refund_penalty": 0.05,
                "fulfillment_penalty": 0.0,
                "domain_health_penalty": 0.0,
                "compliance_status": "pass",
            },
            REVENUE_AUDIT_ENGINE: {
                "expected_net_cash_30d": 24.0,
                "confidence": 0.75,
                "required_budget": 12.0,
                "capacity_limits": {
                    "budget_usd": 10.0,
                    "send_quota": 7,
                    "llm_tokens": 900,
                },
                "refund_penalty": 0.04,
                "fulfillment_penalty": 0.02,
                "domain_health_penalty": 0.01,
                "compliance_status": "pass",
            },
        },
        persist=False,
    )

    overlay = decision.metadata["engine_family_overlay"]
    assert overlay["advisory_only"] is True
    assert overlay["input_families"] == [TRADING_AGENT, REVENUE_AUDIT_ENGINE]

    revenue_rec = next(
        row for row in overlay["recommendations"] if row["engine_family"] == REVENUE_AUDIT_ENGINE
    )
    assert revenue_rec["eligible"] is True
    assert revenue_rec["target_share"] == pytest.approx(0.901746, rel=1e-5)
    assert revenue_rec["recommended_budget_usd"] == 10.0
    assert revenue_rec["recommended_send_quota"] == 7
    assert revenue_rec["recommended_llm_token_budget"] == 900

    engine_docs = [
        doc for doc in decision.strategy_documents if doc["strategy_type"] == "capital_allocator_engine"
    ]
    assert len(engine_docs) == 2
    assert any(
        doc["strategy_key"] == "capital_allocator_engine:revenue_audit" for doc in engine_docs
    )


def test_engine_family_overlay_hard_blocks_failed_compliance(tmp_path) -> None:
    allocator, _ = _allocator(tmp_path)

    decision = allocator.decide(
        decision_date=date(2026, 3, 7),
        mode=AllocationMode.FIXED_SPLIT,
        engine_inputs={
            REVENUE_AUDIT_ENGINE: {
                "expected_net_cash_30d": 42.0,
                "confidence": 0.90,
                "required_budget": 12.0,
                "capacity_limits": {
                    "budget_usd": 8.0,
                    "send_quota": 5,
                    "llm_tokens": 500,
                },
                "refund_penalty": 0.01,
                "fulfillment_penalty": 0.01,
                "domain_health_penalty": 0.01,
                "compliance_status": "fail",
            }
        },
        persist=False,
    )

    overlay = decision.metadata["engine_family_overlay"]
    assert overlay["blocked_families"] == [REVENUE_AUDIT_ENGINE]
    revenue_rec = overlay["recommendations"][0]
    assert revenue_rec["engine_family"] == REVENUE_AUDIT_ENGINE
    assert revenue_rec["eligible"] is False
    assert revenue_rec["blocked_reason"] == "compliance_fail"
    assert revenue_rec["recommended_budget_usd"] == 0.0
    assert revenue_rec["recommended_send_quota"] == 0
    assert revenue_rec["recommended_llm_token_budget"] == 0
    assert "hard-blocked" in " ".join(revenue_rec["explanation"])
    assert "compliance block active" in decision.rationale


def test_cli_json_dry_run_reads_engine_input_file(tmp_path, capsys) -> None:
    engine_input_path = tmp_path / "allocator_inputs.json"
    engine_input_path.write_text(
        json.dumps(
            {
                REVENUE_AUDIT_ENGINE: {
                    "expected_net_cash_30d": 20.0,
                    "confidence": 0.80,
                    "required_budget": 10.0,
                    "capacity_limits": {
                        "budget_usd": 6.0,
                        "send_quota": 4,
                        "llm_tokens": 250,
                    },
                    "refund_penalty": 0.02,
                    "fulfillment_penalty": 0.01,
                    "domain_health_penalty": 0.0,
                    "compliance_status": "pass",
                }
            }
        )
    )

    exit_code = main(
        [
            "--mode",
            "fixed_split",
            "--decision-date",
            "2026-03-07",
            "--engine-input-file",
            str(engine_input_path),
            "--json",
            "--no-persist",
            "--db-path",
            str(tmp_path / "allocator.db"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    decision = payload["decision"]
    overlay = decision["metadata"]["engine_family_overlay"]
    assert overlay["advisory_only"] is True
    assert overlay["recommendations"][0]["engine_family"] == REVENUE_AUDIT_ENGINE
    assert decision["strategy_documents"][0]["strategy_key"] == "capital_allocator_engine:revenue_audit"
