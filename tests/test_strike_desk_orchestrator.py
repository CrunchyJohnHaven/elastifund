#!/usr/bin/env python3
"""Focused regression tests for strike desk orchestration and tape coupling."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot.event_tape import EventTapeWriter
import bot.strike_desk as strike_desk_module
from bot.strike_desk import (
    ExecutionPacket,
    PRIORITY_RESOLUTION,
    StrikeDesk,
)


def _packet(
    *,
    packet_id: str | None = None,
    strategy_id: str = "resolution",
    market_id: str = "mkt-1",
    priority: int = PRIORITY_RESOLUTION,
    direction: str = "YES",
    size_usd: float = 10.0,
    edge_estimate: float = 0.05,
    order_type: str = "maker",
    metadata: dict | None = None,
) -> ExecutionPacket:
    pkt = ExecutionPacket(
        strategy_id=strategy_id,
        market_id=market_id,
        platform="polymarket",
        direction=direction,
        token_id="tok-1",
        size_usd=size_usd,
        edge_estimate=edge_estimate,
        confidence=0.9,
        evidence_hash="abcdef1234567890",
        max_slippage=0.02,
        ttl_seconds=120,
        order_type=order_type,
        priority=priority,
        metadata=metadata or {"question": "Will it resolve?"},
    )
    if packet_id is not None:
        pkt.packet_id = packet_id
    return pkt


class _RecordingExecutor:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
        return False


class TestStrikeDeskOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "tape.db")
        self.jsonl_path = os.path.join(self.tmpdir, "tape.jsonl")
        self._scanner_patches = [
            patch.object(strike_desk_module, "NegativeRiskScanner", None),
            patch.object(strike_desk_module, "WhaleTracker", None),
            patch.object(strike_desk_module, "ResolutionSniper", None),
            patch.object(strike_desk_module, "CrossPlatformArbScanner", None),
            patch.object(strike_desk_module, "LLMTournament", None),
            patch.object(strike_desk_module, "SemanticLeaderFollower", None),
        ]
        for p in self._scanner_patches:
            p.start()
        self.writer = EventTapeWriter(
            db_path=self.db_path,
            jsonl_path=self.jsonl_path,
            session_id="strike-orchestrator",
        )

    def tearDown(self) -> None:
        for p in reversed(self._scanner_patches):
            p.stop()
        self.writer.close()
        for path in Path(self.tmpdir).glob("*"):
            path.unlink()
        os.rmdir(self.tmpdir)

    def _desk(self) -> StrikeDesk:
        return StrikeDesk(config={"capital": 1000.0}, tape_writer=self.writer)

    def test_run_cycle_emits_queue_and_executes_whale_lane(self) -> None:
        desk = self._desk()
        desk._whale = object()
        executor = _RecordingExecutor([
            {"status": "filled", "filled": True, "fill_price": 0.51},
        ])
        signal = SimpleNamespace(
            market_id="whale-1",
            market_question="Will BTC rise?",
            direction="YES",
            agreeing_wallets=4,
            total_tracked=5,
            consensus_pct=0.8,
            recommended_size_usd=10.0,
            confidence=0.9,
        )

        report = asyncio.run(desk.run_cycle(executor=executor, whale_signals=[signal]))

        self.assertEqual(len(report["raw_packets"]), 1)
        self.assertEqual(len(report["approved_packets"]), 1)
        self.assertEqual(report["execution_summary"]["filled"], 1)
        self.assertEqual(report["diagnostics"]["total_fills"], 1)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(self.writer.count_events("decision.trade_proposed"), 1)
        self.assertEqual(self.writer.count_events("decision.trade_approved"), 1)
        self.assertEqual(self.writer.count_events("execution.order_placed"), 1)
        self.assertEqual(self.writer.count_events("execution.order_filled"), 1)

    def test_execute_queue_allows_taker_fallback_only_for_high_priority(self) -> None:
        desk = self._desk()
        packet = _packet()
        desk.generate_packets([packet])
        executor = _RecordingExecutor([
            False,
            {"status": "filled", "filled": True, "fill_price": 0.49},
        ])

        summary = asyncio.run(
            desk.execute_queue([packet], executor=executor, allow_taker_fallback=True)
        )

        self.assertEqual(len(executor.calls), 2)
        self.assertEqual(summary["filled"], 1)
        self.assertGreater(desk._total_exposure, 0.0)
        self.assertEqual(self.writer.count_events("execution.order_placed"), 2)
        self.assertEqual(self.writer.count_events("execution.order_filled"), 1)

    def test_generate_packets_writes_shadow_alternative(self) -> None:
        desk = self._desk()
        p1 = _packet(strategy_id="a", market_id="same", priority=2, direction="YES")
        p2 = _packet(strategy_id="b", market_id="same", priority=2, direction="NO")

        approved = desk.generate_packets([p1, p2])

        self.assertEqual(len(approved), 0)
        self.assertEqual(self.writer.count_events("shadow.alternative"), 1)
        shadow = self.writer.query_by_type("shadow.alternative")[0]
        self.assertEqual(shadow.payload["reason"], "same_score_opposing")


if __name__ == "__main__":
    unittest.main()
