from __future__ import annotations

from bot.proof_types import (
    LearningRecord,
    build_mutation_package,
    build_evidence_record,
    build_kernel_cycle_packet,
    build_promotion_ticket,
    build_runtime_truth_contract_snapshot,
    build_thesis_record,
    build_wallet_truth_snapshot,
)


def test_evidence_hash_is_stable():
    record_1 = build_evidence_record(
        source_module="strike_desk",
        evidence_type="lane.resolution",
        timestamp_utc=1_700_000_000.0,
        staleness_limit_s=120.0,
        payload={"market_id": "mkt-1", "edge_estimate": 0.05},
        confidence=0.8,
    )
    record_2 = build_evidence_record(
        source_module="strike_desk",
        evidence_type="lane.resolution",
        timestamp_utc=1_700_000_000.0,
        staleness_limit_s=120.0,
        payload={"market_id": "mkt-1", "edge_estimate": 0.05},
        confidence=0.8,
    )
    assert record_1.hash == record_2.hash


def test_kernel_cycle_packet_serializes_nested_bundles():
    evidence = build_evidence_record(
        source_module="strike_desk",
        evidence_type="lane.whale",
        timestamp_utc=1_700_000_000.0,
        staleness_limit_s=120.0,
        payload={"market_id": "mkt-2"},
        confidence=0.7,
    )
    thesis = build_thesis_record(
        hypothesis="whale:mkt-2:YES",
        strategy_class="whale",
        evidence_refs=[evidence.hash],
        calibrated_probability=0.7,
        confidence_interval=(0.6, 0.8),
        edge_estimate=0.05,
        regime_context="live",
        kill_rule_results={"passed": True},
        created_utc=1_700_000_000.0,
        expires_utc=1_700_000_120.0,
    )
    ticket = build_promotion_ticket(
        thesis_ref=thesis.thesis_id,
        evidence_refs=thesis.evidence_refs,
        constraint_result={"allowed": True},
        stage_gate_result={"registered": False},
        position_size_usd=10.0,
        max_loss_usd=10.0,
        execution_mode="shadow",
        approved_utc=1_700_000_010.0,
        expires_utc=1_700_000_120.0,
        promotion_path="revenue_first_strike_factory",
    )
    learning = LearningRecord(
        trade_id="cycle-1",
        thesis_ref=thesis.thesis_id,
        ticket_ref=ticket.ticket_id,
        outcome="win",
        actual_pnl_usd=0.0,
        predicted_edge=0.0,
        actual_edge=0.0,
        reflection="cycle summary",
        written_utc=1_700_000_015.0,
    )
    packet = build_kernel_cycle_packet(
        cycle_id="cycle-1",
        generated_at="2026-03-22T14:00:00Z",
        source_of_truth_map={"evidence": "reports/evidence_bundle.json"},
        evidence_bundle=[evidence],
        thesis_bundle=[thesis],
        promotion_bundle=[ticket],
        learning_bundle=[learning],
    )

    payload = packet.to_dict()
    assert payload["source_of_truth_map"]["evidence"] == "reports/evidence_bundle.json"
    assert payload["promotion_bundle"][0]["ticket_id"] == ticket.ticket_id
    assert payload["learning_bundle"][0]["thesis_ref"] == thesis.thesis_id


def test_truth_snapshots_and_mutation_package_have_stable_ids():
    wallet_snapshot_1 = build_wallet_truth_snapshot(
        generated_at="2026-03-24T08:00:00Z",
        wallet_address="0xabc",
        control_posture="blocked",
        truth_status="blocked",
        open_positions_count=2,
        closed_positions_count=50,
        estimated_total_value_usd=1106.78,
        available_cash_usd=1059.0,
        capital_live=False,
        source_of_truth={"runtime_truth": "reports/runtime_truth_latest.json"},
        blockers=["runtime_truth_stale"],
        mismatches=["wallet_balance_drift"],
        metadata={"execution_mode": "shadow"},
    )
    wallet_snapshot_2 = build_wallet_truth_snapshot(
        generated_at="2026-03-24T08:00:00Z",
        wallet_address="0xabc",
        control_posture="blocked",
        truth_status="blocked",
        open_positions_count=2,
        closed_positions_count=50,
        estimated_total_value_usd=1106.78,
        available_cash_usd=1059.0,
        capital_live=False,
        source_of_truth={"runtime_truth": "reports/runtime_truth_latest.json"},
        blockers=["runtime_truth_stale"],
        mismatches=["wallet_balance_drift"],
        metadata={"execution_mode": "shadow"},
    )
    runtime_snapshot = build_runtime_truth_contract_snapshot(
        generated_at="2026-03-24T08:00:00Z",
        selected_runtime_profile="maker_velocity_live",
        execution_mode="live",
        agent_run_mode="shadow",
        launch_posture="blocked",
        service_state="unknown",
        allow_order_submission=False,
        truth_gate_status="blocked",
        baseline_live_allowed=False,
        blockers=["paper_mode_consistency"],
        artifacts={"runtime_truth_latest_json": "reports/runtime_truth_latest.json"},
        summary="runtime truth snapshot",
    )
    mutation_package = build_mutation_package(
        created_at="2026-03-24T08:05:00Z",
        mutation_kind="runtime_profile_repair",
        summary="Tighten runtime truth contract",
        change_set={"profile": "maker_velocity_live", "execution_mode": "live"},
        replay_corpus=["march11_btc_win", "march24_btc_loss"],
        acceptance_metrics={"attribution_coverage_min": 0.9},
        selected_runtime_package={"package_hash": "pkg-1"},
        rollback_target={"profile": "blocked_safe"},
    )

    assert wallet_snapshot_1.snapshot_id == wallet_snapshot_2.snapshot_id
    assert runtime_snapshot.to_dict()["execution_mode"] == "live"
    assert mutation_package.to_dict()["rollback_target"]["profile"] == "blocked_safe"
