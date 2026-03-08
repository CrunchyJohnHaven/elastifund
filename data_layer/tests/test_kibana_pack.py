"""Tests for the Phase 6 Kibana pack generator."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data_layer import crud
from data_layer.schema import Base
from flywheel.kibana_pack import build_phase6_dashboard_pack, write_phase6_dashboard_pack
from nontrading.models import Campaign, Lead
from nontrading.store import RevenueStore
from orchestration.models import (
    AllocationDecision,
    AllocationMode,
    DeliverabilityRisk,
    NON_TRADING_AGENT,
    PerformanceObservation,
    TRADING_AGENT,
)
from orchestration.store import AllocatorStore


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
        engine.dispose()


def test_build_and_write_phase6_kibana_pack(session, tmp_path):
    _seed_strategy(
        session,
        strategy_key="wallet-flow",
        version_label="wf-v1",
        lane="fast_flow",
        day_one_pnl=10.0,
        day_two_pnl=5.0,
        day_two_drawdown=0.08,
    )
    _seed_strategy(
        session,
        strategy_key="constraint-arb",
        version_label="a6-v1",
        lane="structural_arb",
        day_one_pnl=4.0,
        day_two_pnl=-1.0,
        day_two_drawdown=0.18,
    )

    cycle = crud.create_flywheel_cycle(
        session,
        cycle_key="bulletin-alpha-20260307",
        status="completed",
        summary="Imported peer bulletin from alpha-fork",
    )
    crud.create_flywheel_task(
        session,
        cycle_id=cycle.id,
        strategy_version_id=None,
        action="recommend",
        title="Review imported peer finding",
        details="Check the peer promotion claim.",
        priority=15,
        status="open",
    )
    crud.create_peer_improvement_bundle(
        session,
        bundle_id="bundle-1",
        peer_name="alpha-fork",
        strategy_key="constraint-arb",
        version_label="a6-v1",
        lane="structural_arb",
        outcome="mixed",
        direction="imported",
        verification_status="verified",
        status="recorded",
        summary="Peer shared a structural-arb tweak.",
        hypothesis="More structure yields cleaner entries.",
        bundle_sha256="deadbeef",
        raw_bundle={},
    )
    session.commit()

    allocator_db = tmp_path / "allocator.db"
    allocator_store = AllocatorStore(allocator_db)
    allocator_store.init_db()
    allocator_store.record_observation(
        PerformanceObservation(
            agent_name=TRADING_AGENT,
            observed_on=date(2026, 3, 6),
            roi=0.12,
        )
    )
    allocator_store.record_observation(
        PerformanceObservation(
            agent_name=NON_TRADING_AGENT,
            observed_on=date(2026, 3, 6),
            roi=0.04,
        )
    )
    allocator_store.record_decision(
        AllocationDecision(
            decision_date=date(2026, 3, 7),
            mode=AllocationMode.THOMPSON_SAMPLING,
            trading_share=0.65,
            non_trading_share=0.35,
            trading_budget_usd=80.0,
            non_trading_send_quota=60,
            non_trading_llm_token_budget=25_000,
            deliverability_risk=DeliverabilityRisk.GREEN,
            rationale="Structural alpha is being funded, but revenue stays online.",
        )
    )

    revenue_db = tmp_path / "revenue_agent.db"
    revenue_store = RevenueStore(revenue_db)
    campaign = revenue_store.create_campaign(
        Campaign(
            name="launch-sequence",
            subject_template="Elastifund for {company_name}",
            body_template="Hello {company_name}",
            daily_send_quota=20,
        )
    )
    lead, _ = revenue_store.upsert_lead(
        Lead(email="ops@example.com", company_name="Example Co", explicit_opt_in=True)
    )
    message = revenue_store.queue_outbox_message(
        campaign=campaign,
        lead=lead,
        subject="Elastifund for Example Co",
        body="Hello Example Co",
        headers={"List-Unsubscribe": "<mailto:unsubscribe@example.com>"},
        from_email="ops@elastifund.io",
        provider="dry_run",
    )
    revenue_store.update_outbox_message_status(message.id or 0, "sent", detail="dry run sent")

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    guaranteed_dollar_path = reports_dir / "guaranteed_dollar_audit.json"
    guaranteed_dollar_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "evt-1",
                    "title": "Example Event 1",
                    "best_construction": {
                        "construction_type": "two_leg_straddle",
                        "executable": False,
                        "maker_gross_edge": 0.01,
                        "readiness": {"ready": False},
                    },
                },
                {
                    "event_id": "evt-2",
                    "title": "Example Event 2",
                    "best_construction": {
                        "construction_type": "neg_risk_conversion",
                        "executable": True,
                        "maker_gross_edge": 0.03,
                        "readiness": {"ready": True},
                    },
                },
            ]
        )
    )

    b1_template_path = reports_dir / "b1_template_audit.json"
    b1_template_path.write_text(
        json.dumps(
            {
                "template_markets": {"winner_margin": 12, "winner_balance_of_power": 5},
                "template_pairs": [{"a": "mkt-1", "b": "mkt-2"}],
            }
        )
    )

    metrics_path = reports_dir / "run_20260307_190738_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "recommendation": "REJECT ALL",
                "reasoning": "All active hypotheses failed expectancy tests.",
                "results": {
                    "vol_regime": {
                        "strategy": "Volatility Regime Mismatch",
                        "signals": 34,
                        "win_rate": 0.32,
                        "ev_maker": -2.49,
                        "sharpe": -0.59,
                        "regime_decay": True,
                        "notes": ["Recent sample shows regime decay."],
                    },
                    "wallet_flow": {
                        "strategy": "Wallet Flow",
                        "signals": 18,
                        "win_rate": 0.56,
                        "ev_maker": 0.22,
                        "sharpe": 0.41,
                        "regime_decay": False,
                    },
                },
                "next_actions": [
                    "Focus on structural alpha.",
                    "Keep maker-only execution intact.",
                ],
            }
        )
    )

    pack = build_phase6_dashboard_pack(
        session,
        allocator_db_path=allocator_db,
        revenue_db_path=revenue_db,
        guaranteed_dollar_audit_path=guaranteed_dollar_path,
        b1_template_audit_path=b1_template_path,
        research_metrics_glob=str(reports_dir / "run_*_metrics.json"),
    )

    assert pack["collective_health"]["agent_totals"]["total_agents"] == 3
    assert pack["market_regime"]["current_regime"] == "unstable"
    assert pack["strategy_diversity"]["a6_audit"]["events_scanned"] == 2
    assert pack["knowledge_flow"]["allocator"]["latest_decision"]["mode"] == "thompson_sampling"
    assert pack["alert_rules"]["rules"][0]["status"] == "firing"
    assert pack["alert_rules"]["rules"][1]["status"] == "firing"
    assert pack["alert_rules"]["rules"][2]["status"] == "firing"
    assert len(pack["dashboards"]) == 6
    assert pack["charitable_impact"]["reserved_total_usd"] == pytest.approx(1.0)

    output_dir = tmp_path / "deploy" / "kibana" / "phase6"
    written = write_phase6_dashboard_pack(output_dir, pack)

    for value in written.values():
        assert Path(value).exists()

    saved_objects = Path(written["saved_objects_ndjson"]).read_text()
    assert saved_objects.count('"type": "dashboard"') == 6
    assert "Collective Health" in saved_objects

    canvas_spec = json.loads(Path(written["canvas_workpad_json"]).read_text())
    assert canvas_spec["pages"][0]["name"] == "Collective Health"


def _seed_strategy(
    session,
    *,
    strategy_key: str,
    version_label: str,
    lane: str,
    day_one_pnl: float,
    day_two_pnl: float,
    day_two_drawdown: float,
) -> None:
    version = crud.create_strategy_version(
        session,
        strategy_key=strategy_key,
        version_label=version_label,
        lane=lane,
    )
    deployment = crud.create_deployment(
        session,
        strategy_version_id=version.id,
        environment="paper",
        capital_cap_usd=25.0,
        status="active",
    )
    crud.create_daily_snapshot(
        session,
        strategy_version_id=version.id,
        deployment_id=deployment.id,
        environment="paper",
        snapshot_date="2026-03-06",
        starting_bankroll=100.0,
        ending_bankroll=110.0,
        realized_pnl=day_one_pnl,
        unrealized_pnl=0.0,
        open_positions=1,
        closed_trades=10,
        win_rate=0.60,
        fill_rate=0.70,
        avg_slippage_bps=10.0,
        rolling_brier=0.21,
        rolling_ece=0.05,
        max_drawdown_pct=0.05,
        kill_events=0,
    )
    latest = crud.create_daily_snapshot(
        session,
        strategy_version_id=version.id,
        deployment_id=deployment.id,
        environment="paper",
        snapshot_date="2026-03-07",
        starting_bankroll=110.0,
        ending_bankroll=111.0,
        realized_pnl=day_two_pnl,
        unrealized_pnl=1.0,
        open_positions=2,
        closed_trades=12,
        win_rate=0.55,
        fill_rate=0.75,
        avg_slippage_bps=11.0,
        rolling_brier=0.22,
        rolling_ece=0.06,
        max_drawdown_pct=day_two_drawdown,
        kill_events=0,
    )
    crud.create_promotion_decision(
        session,
        strategy_version_id=version.id,
        deployment_id=deployment.id,
        from_stage="paper",
        to_stage="paper",
        decision="hold",
        reason_code="collecting_evidence",
        metrics={"snapshot_id": latest.id},
        notes="Phase 6 dashboard seed data.",
    )
