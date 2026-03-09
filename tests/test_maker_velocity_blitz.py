from __future__ import annotations

from datetime import datetime, timezone

from bot.maker_velocity_blitz import (
    InventoryState,
    MarketSnapshot,
    WalletConsensusSignal,
    allocate_hour0_notional,
    build_laddered_quote_intents,
    compute_signal_score,
    deployment_kpis,
    evaluate_blitz_launch_ready,
    rank_wallet_signals,
    validate_contract_payload,
)


def test_compute_signal_score_is_deterministic_formula() -> None:
    score = compute_signal_score(
        edge=0.08,
        fill_prob=0.50,
        velocity_multiplier=1.5,
        wallet_confidence=0.8,
        toxicity_penalty=0.9,
    )
    assert score == 0.0432


def test_rank_wallet_signals_orders_by_score_desc() -> None:
    ranked = rank_wallet_signals(
        [
            WalletConsensusSignal(
                market_id="m1",
                direction="buy_yes",
                edge=0.10,
                fill_prob=0.5,
                velocity_multiplier=1.0,
                wallet_confidence=0.7,
                toxicity_penalty=1.0,
            ),
            WalletConsensusSignal(
                market_id="m2",
                direction="buy_no",
                edge=0.07,
                fill_prob=0.8,
                velocity_multiplier=1.2,
                wallet_confidence=0.8,
                toxicity_penalty=1.0,
            ),
        ]
    )
    assert ranked[0]["market_id"] == "m2"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_allocate_hour0_notional_respects_reserve_and_per_market_cap() -> None:
    allocations = allocate_hour0_notional(
        bankroll_usd=250.0,
        ranked_signals=[
            {"market_id": "m1", "score": 10.0},
            {"market_id": "m2", "score": 8.0},
            {"market_id": "m3", "score": 6.0},
            {"market_id": "m4", "score": 4.0},
            {"market_id": "m5", "score": 2.0},
        ],
    )
    deployable = 250.0 * 0.95
    assert sum(allocations.values()) <= deployable + 1e-6
    assert all(value <= (250.0 * 0.20) + 1e-6 for value in allocations.values())
    assert len(allocations) >= 4


def test_build_laddered_quote_intents_is_post_only_and_three_levels() -> None:
    ranked = [
        {"market_id": "m1", "direction": "buy_yes", "score": 0.12},
    ]
    allocations = {"m1": 30.0}
    snapshots = {
        "m1": MarketSnapshot(
            market_id="m1",
            question="Will BTC be up?",
            yes_price=0.45,
            no_price=0.55,
            resolution_hours=0.5,
            spread=0.02,
            liquidity_usd=900.0,
            toxicity=0.2,
        )
    }
    intents = build_laddered_quote_intents(
        allocations_usd=allocations,
        ranked_signals=ranked,
        market_snapshots=snapshots,
    )
    assert len(intents) == 3
    assert all(intent.post_only for intent in intents)
    assert [intent.level for intent in intents] == [1, 2, 3]
    assert [intent.replace_after_seconds for intent in intents] == [10, 15, 20]
    assert sum(intent.notional_usd for intent in intents) == 30.0


def test_evaluate_blitz_launch_ready_blocks_on_stale_conflict_and_drift() -> None:
    decision = evaluate_blitz_launch_ready(
        remote_cycle_status={
            "wallet_flow": {"ready": True},
            "root_tests": {"status": "passing"},
            "launch": {"fast_flow_restart_ready": True},
            "data_cadence": {"stale": True},
            "service": {"status": "running"},
            "runtime_truth": {"drift_detected": True},
        },
        remote_service_status={"status": "stopped"},
        jj_state={"bankroll": 250.0},
    )
    assert decision.launch_go is False
    assert decision.checks["fresh_pull_required"] is False
    assert decision.checks["service_conflict_reconciled"] is False
    assert "fresh_pull_required" in decision.blocked_reasons
    assert "service_status_conflict" in decision.blocked_reasons
    assert "runtime_drift_detected" in decision.blocked_reasons


def test_evaluate_blitz_launch_ready_passes_when_checks_green() -> None:
    decision = evaluate_blitz_launch_ready(
        remote_cycle_status={
            "wallet_flow": {"ready": True},
            "root_tests": {"status": "passing"},
            "launch": {"fast_flow_restart_ready": True},
            "data_cadence": {"stale": False},
            "service": {"status": "running"},
            "runtime_truth": {"drift_detected": False},
        },
        remote_service_status={"status": "running"},
        jj_state={"bankroll": 250.0},
        now=datetime(2026, 3, 9, 11, 0, tzinfo=timezone.utc),
    )
    assert decision.launch_go is True
    assert all(decision.checks.values())
    assert decision.blocked_reasons == tuple()


def test_validate_contract_payloads_and_kpis() -> None:
    ok, reasons = validate_contract_payload(
        "QuoteIntent",
        {
            "market_id": "m1",
            "side": "buy_yes",
            "price": 0.4,
            "notional_usd": 10.0,
            "post_only": True,
            "level": 1,
            "replace_after_seconds": 10,
            "source_score": 0.1,
        },
    )
    assert ok is True
    assert reasons == tuple()

    ok_missing, reasons_missing = validate_contract_payload("RiskEvent", {"event_type": "toxicity"})
    assert ok_missing is False
    assert "missing:timestamp" in reasons_missing

    metrics = deployment_kpis(
        bankroll_usd=100.0,
        inventory=InventoryState(
            cash_usd=8.0,
            reserved_cash_usd=5.0,
            deployed_usd=87.0,
            positions_usd={"m1": 45.0, "m2": -42.0},
            updated_at="2026-03-09T11:00:00Z",
        ),
        fill_events=[],
    )
    assert metrics["deployment_pct"] == 87.0
    assert metrics["maker_fill_rate"] == 0.0

