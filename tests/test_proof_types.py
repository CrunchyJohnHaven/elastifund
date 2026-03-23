from __future__ import annotations

from bot.proof_types import (
    LearningRecord,
    build_evidence_record,
    build_kernel_cycle_packet,
    build_promotion_ticket,
    build_thesis_record,
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
