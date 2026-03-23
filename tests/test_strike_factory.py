from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bot.event_tape import EventTapeWriter
from bot.promotion_manager import PromotionManager
from bot.strike_desk import ExecutionPacket, StrikeDesk
from bot.strike_factory import (
    DEFAULT_RESOLUTION_MARKETS_PATH,
    build_default_strike_factory_packets,
    run_strike_factory_cycle,
)


def _packet(strategy_id: str, market_id: str, priority: int, edge: float, size: float = 10.0) -> ExecutionPacket:
    return ExecutionPacket(
        strategy_id=strategy_id,
        market_id=market_id,
        platform="polymarket",
        direction="YES",
        token_id="token-1",
        size_usd=size,
        edge_estimate=edge,
        confidence=0.8,
        evidence_hash=f"{strategy_id}-{market_id}",
        max_slippage=0.02,
        ttl_seconds=120,
        order_type="maker",
        priority=priority,
    )


def test_launch_order_prefers_revenue_first_queue(tmp_path: Path):
    tape = EventTapeWriter(db_path=str(tmp_path / "tape.db"), session_id="strike-factory")
    desk = StrikeDesk(config={"capital": 100.0}, tape_writer=tape)
    packets = [
        _packet("neg_risk", "shared-market", priority=0, edge=0.09, size=8.0),
        _packet("resolution", "shared-market", priority=2, edge=0.04, size=8.0),
        _packet("whale", "whale-market", priority=4, edge=0.03, size=5.0),
    ]

    approved = desk.generate_packets(
        packets,
        launch_order=["resolution", "whale", "neg_risk"],
    )

    assert [pkt.strategy_id for pkt in approved] == ["resolution", "whale"]
    assert all(pkt.market_id != "shared-market" or pkt.strategy_id == "resolution" for pkt in approved)
    tape.close()


def test_strike_factory_cycle_builds_proof_and_executes(tmp_path: Path):
    tape = EventTapeWriter(db_path=str(tmp_path / "tape.db"), session_id="strike-factory")
    promo_db = tmp_path / "promotion.db"
    pm = PromotionManager(str(promo_db))
    desk = StrikeDesk(config={"capital": 100.0}, tape_writer=tape)

    raw_packets = [
        _packet("resolution", "resolution-market", priority=2, edge=0.05, size=8.0),
        _packet("whale", "whale-market", priority=4, edge=0.03, size=8.0),
    ]

    calls: list[dict[str, object]] = []

    @dataclass
    class _Executor:
        def place_order(self, **payload):  # type: ignore[no-untyped-def]
            calls.append(payload)
            return {"status": "filled", "filled": True}

    report = run_strike_factory_cycle(
        desk=desk,
        raw_packets=raw_packets,
        executor=_Executor(),
        tape_writer=tape,
        promotion_manager=pm,
        output_path=tmp_path / "latest.json",
        markdown_path=tmp_path / "latest.md",
        tape_db_path=tmp_path / "tape.db",
        launch_order=["resolution", "whale", "neg_risk"],
    )

    assert report.raw_packet_count == 2
    assert report.approved_packet_count == 2
    assert report.execution_summary["submitted"] == 2
    assert report.execution_summary["filled"] == 2
    assert [item["strategy_id"] for item in report.queue] == ["resolution", "whale"]
    assert len(report.promotion_tickets) == 2
    assert report.status == "fresh"
    assert report.blockers == []
    assert report.promotion_tickets[0]["stage_gate_result"]["registered"] is True
    assert report.promotion_tickets[0]["stage_gate_result"]["promotion_check"]["eligible"] is True
    assert report.proof_chain[0]["ticket_id"]
    assert report.kernel_cycle["source_of_truth_map"]["promotion"] == "reports/promotion_bundle.json"
    assert len(calls) == 2
    assert calls[0]["signal"]["source"] == "resolution"

    ticket_events = tape.query_by_type("decision.promotion_ticket_issued")
    assert len(ticket_events) == 2
    assert ticket_events[0].payload["ticket_id"] == report.promotion_tickets[0]["ticket_id"]

    output = json.loads((tmp_path / "latest.json").read_text())
    assert output["artifact"] == "strike_factory.v1"
    assert output["status"] == "fresh"
    assert output["summary"].startswith("approved=2 rejected=0")
    assert "source_of_truth" in output
    assert output["launch_order"][0] == "resolution"
    tape.close()
    pm.close()


def test_default_resolution_fixture_turns_into_packets() -> None:
    desk = StrikeDesk(config={"capital": 1000.0})
    packets, source_info = build_default_strike_factory_packets(
        desk=desk,
        markets_path=DEFAULT_RESOLUTION_MARKETS_PATH,
    )

    assert source_info["loaded"] is True
    assert source_info["reason"] == "fixture"
    assert source_info["count"] == 6
    assert source_info["raw_packet_count"] >= 1
    assert any(pkt.strategy_id == "resolution" for pkt in packets)
