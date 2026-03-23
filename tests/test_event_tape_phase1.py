#!/usr/bin/env python3
"""Phase 1 regression tests for the append-only event tape."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from bot.event_tape import EventTapeWriter


class TestEventTapePhase1(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "tape.db")
        self.jsonl_path = os.path.join(self.tmpdir, "tape.jsonl")
        self.writer = EventTapeWriter(
            db_path=self.db_path,
            jsonl_path=self.jsonl_path,
            session_id="phase-1",
        )

    def tearDown(self) -> None:
        self.writer.close()
        for path in Path(self.tmpdir).glob("*"):
            path.unlink()
        os.rmdir(self.tmpdir)

    def test_jsonl_segment_writer_and_sqlite_index(self) -> None:
        lifecycle = self.writer.emit_market_lifecycle(
            venue="polymarket",
            market_id="mkt-1",
            lifecycle_phase="new_market",
            listed_ts=1711111111,
            updated_ts=1711112222,
            rule_source="official_docs",
            time_to_resolution_seconds=7200,
            confidence=0.94,
            metadata={"question": "Will BTC rise?"},
        )
        tape = self.writer.emit_orderbook_tape(
            venue="polymarket",
            market_id="mkt-1",
            token_id="tok-1",
            best_bid=0.44,
            best_ask=0.46,
            last_trade_price=0.45,
            rtds_spot=0.451,
            oracle_value=0.449,
            liquidity_usd=1234.0,
            spread_bps=45.0,
            trade_prints=[{"price": 0.45, "size": 12.0}],
        )
        settlement = self.writer.emit_settlement_source(
            venue="polymarket",
            market_id="mkt-1",
            rule_source="venue_docs",
            official_source="nws",
            truth_anchor="weather.gov",
            parsed_rule="resolve on official alert",
            confidence=0.88,
        )
        self.writer.emit_shadow_alternative(
            chosen_action="pkt-123",
            rejected_actions=[{"packet_id": "pkt-999", "reason": "lower_priority_suppressed"}],
            metadata={"market_id": "mkt-1"},
        )
        self.writer.emit_wallet_truth(
            tape_derived_balance=-152.0,
            api_balance=-151.5,
            divergence_usd=0.5,
            divergence_pct=0.0033,
            threshold_pct=0.05,
            is_divergent=False,
        )

        self.assertEqual(lifecycle.event_type, "market.lifecycle")
        self.assertEqual(tape.event_type, "orderbook.tape")
        self.assertEqual(settlement.event_type, "settlement.source")

        jsonl = Path(self.jsonl_path).read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(jsonl), 5)
        first = json.loads(jsonl[0])
        self.assertEqual(first["event_type"], "market.lifecycle")
        self.assertEqual(first["payload"]["market_id"], "mkt-1")

        lifecycle_rows = self.writer.query_by_type("market.lifecycle")
        self.assertEqual(len(lifecycle_rows), 1)
        self.assertEqual(lifecycle_rows[0].payload["lifecycle_phase"], "new_market")

        window_rows = self.writer.query_seq_range(lifecycle.seq, settlement.seq)
        self.assertEqual([row.seq for row in window_rows], [lifecycle.seq, tape.seq, settlement.seq])

    def test_wallet_truth_event_records_circuit_breaker_fields(self) -> None:
        evt = self.writer.emit_wallet_truth(
            tape_derived_balance=100.0,
            api_balance=88.0,
            divergence_usd=12.0,
            divergence_pct=0.12,
            threshold_pct=0.05,
            is_divergent=True,
        )
        self.assertEqual(evt.event_type, "wallet.truth")
        self.assertTrue(evt.payload["is_divergent"])
        self.assertEqual(self.writer.query_by_type("wallet.truth")[0].payload["divergence_usd"], 12.0)


if __name__ == "__main__":
    unittest.main()
