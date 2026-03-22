#!/usr/bin/env python3
"""
Tests for bot/event_tape.py — Event Tape Writer
================================================
45+ tests covering emission, retrieval, sequence monotonicity, typed helpers,
causal chain traversal, correlation grouping, P&L derivation, wallet divergence,
thread safety, empty tape edge cases, and large payloads.

All tests use temporary directories to prevent pollution.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Allow import from repo root
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from bot.event_tape import EventTapeWriter, TapeEvent  # noqa: E402


class _TapeTestCase(unittest.TestCase):
    """Base class that creates a temp dir and writer for each test."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmpdir, "tape.db")
        self.writer = EventTapeWriter(db_path=self.db_path, session_id="test-session")

    def tearDown(self) -> None:
        self.writer.close()
        # Clean up temp files
        for f in Path(self._tmpdir).glob("*"):
            f.unlink()
        os.rmdir(self._tmpdir)


# =========================================================================
# 1. Event emission and retrieval
# =========================================================================


class TestEmitBasic(_TapeTestCase):

    def test_emit_returns_tape_event(self) -> None:
        evt = self.writer.emit("market.discovered", "jj_live", {"foo": "bar"})
        self.assertIsInstance(evt, TapeEvent)

    def test_emit_assigns_seq(self) -> None:
        evt = self.writer.emit("test.event", "src", {})
        self.assertIsInstance(evt.seq, int)
        self.assertGreaterEqual(evt.seq, 1)

    def test_emit_assigns_ts(self) -> None:
        evt = self.writer.emit("test.event", "src", {})
        self.assertIsInstance(evt.ts, int)
        self.assertGreater(evt.ts, 0)

    def test_emit_preserves_event_type(self) -> None:
        evt = self.writer.emit("decision.trade_proposed", "btc5", {"edge": 0.05})
        self.assertEqual(evt.event_type, "decision.trade_proposed")

    def test_emit_preserves_source(self) -> None:
        evt = self.writer.emit("test.event", "my_source", {})
        self.assertEqual(evt.source, "my_source")

    def test_emit_preserves_session_id(self) -> None:
        evt = self.writer.emit("test.event", "src", {})
        self.assertEqual(evt.session_id, "test-session")

    def test_emit_preserves_payload(self) -> None:
        payload = {"condition_id": "0xabc", "question": "Will BTC go up?"}
        evt = self.writer.emit("market.discovered", "jj_live", payload)
        self.assertEqual(evt.payload, payload)

    def test_emit_preserves_causation_seq(self) -> None:
        e1 = self.writer.emit("test.a", "src", {})
        e2 = self.writer.emit("test.b", "src", {}, causation_seq=e1.seq)
        self.assertEqual(e2.causation_seq, e1.seq)

    def test_emit_preserves_correlation_id(self) -> None:
        evt = self.writer.emit("test.event", "src", {}, correlation_id="corr-123")
        self.assertEqual(evt.correlation_id, "corr-123")

    def test_emit_none_causation_and_correlation(self) -> None:
        evt = self.writer.emit("test.event", "src", {})
        self.assertIsNone(evt.causation_seq)
        self.assertIsNone(evt.correlation_id)

    def test_event_is_frozen(self) -> None:
        evt = self.writer.emit("test.event", "src", {})
        with self.assertRaises(AttributeError):
            evt.seq = 999  # type: ignore[misc]


# =========================================================================
# 2. Sequence monotonicity
# =========================================================================


class TestSequenceMonotonicity(_TapeTestCase):

    def test_seq_increases_by_one(self) -> None:
        events = [self.writer.emit("test.event", "src", {}) for _ in range(10)]
        seqs = [e.seq for e in events]
        for i in range(1, len(seqs)):
            self.assertEqual(seqs[i], seqs[i - 1] + 1)

    def test_seq_starts_at_one(self) -> None:
        evt = self.writer.emit("test.event", "src", {})
        self.assertEqual(evt.seq, 1)

    def test_seq_no_gaps(self) -> None:
        events = [self.writer.emit("test.event", "src", {}) for _ in range(50)]
        expected = list(range(1, 51))
        self.assertEqual([e.seq for e in events], expected)

    def test_seq_recovers_after_reopen(self) -> None:
        """Reopening the DB resumes from the next seq."""
        for _ in range(5):
            self.writer.emit("test.event", "src", {})
        self.writer.close()

        writer2 = EventTapeWriter(db_path=self.db_path, session_id="session-2")
        evt = writer2.emit("test.event", "src", {})
        self.assertEqual(evt.seq, 6)
        writer2.close()


# =========================================================================
# 3. Typed helpers produce correct event_type strings
# =========================================================================


class TestTypedHelpers(_TapeTestCase):

    def test_emit_market_discovered_type(self) -> None:
        evt = self.writer.emit_market_discovered(
            condition_id="0xabc",
            market_id="m-1",
            question="Will BTC hit 100k?",
            slug="btc-100k",
            category="crypto_5min",
            end_date_ts=1700000000,
            tokens=[{"token_id": "t1", "outcome": "YES"}],
            source_api="gamma_markets_api",
        )
        self.assertEqual(evt.event_type, "market.discovered")
        self.assertEqual(evt.payload["condition_id"], "0xabc")
        self.assertEqual(evt.payload["slug"], "btc-100k")

    def test_emit_book_snapshot_type(self) -> None:
        evt = self.writer.emit_book_snapshot(
            market_id="m-1",
            token_id="t1",
            best_bid=0.45,
            best_ask=0.55,
            bid_depth_usd=100.0,
            ask_depth_usd=120.0,
            spread=0.10,
            midpoint=0.50,
            imbalance=-0.09,
            book_levels=5,
        )
        self.assertEqual(evt.event_type, "book.snapshot")
        self.assertEqual(evt.payload["best_bid"], 0.45)
        self.assertEqual(evt.payload["book_levels"], 5)

    def test_emit_book_snapshot_null_bid(self) -> None:
        evt = self.writer.emit_book_snapshot(
            market_id="m-1", token_id="t1",
            best_bid=None, best_ask=0.55,
            bid_depth_usd=0, ask_depth_usd=100,
            spread=0.55, midpoint=0.275,
            imbalance=-1.0, book_levels=1,
        )
        self.assertIsNone(evt.payload["best_bid"])

    def test_emit_decision_trade_proposed(self) -> None:
        evt = self.writer.emit_decision(
            "trade_proposed",
            {"market_id": "m-1", "direction": "buy_yes", "edge": 0.08},
        )
        self.assertEqual(evt.event_type, "decision.trade_proposed")

    def test_emit_decision_trade_approved(self) -> None:
        evt = self.writer.emit_decision(
            "trade_approved",
            {"market_id": "m-1", "direction": "buy_no", "gates_passed": ["daily_loss_ok"]},
        )
        self.assertEqual(evt.event_type, "decision.trade_approved")

    def test_emit_decision_trade_rejected(self) -> None:
        evt = self.writer.emit_decision(
            "trade_rejected",
            {"market_id": "m-1", "rejection_reason": "skip_delta_too_large"},
        )
        self.assertEqual(evt.event_type, "decision.trade_rejected")

    def test_emit_execution_order_placed(self) -> None:
        evt = self.writer.emit_execution(
            "order_placed",
            {"order_id": "o-1", "market_id": "m-1", "side": "BUY", "price": 0.45},
        )
        self.assertEqual(evt.event_type, "execution.order_placed")

    def test_emit_execution_order_filled(self) -> None:
        evt = self.writer.emit_execution(
            "order_filled",
            {"order_id": "o-1", "fill_price": 0.45, "fill_size_usd": 5.0, "market_id": "m-1"},
        )
        self.assertEqual(evt.event_type, "execution.order_filled")

    def test_emit_execution_order_cancelled(self) -> None:
        evt = self.writer.emit_execution(
            "order_cancelled",
            {"order_id": "o-1", "cancel_reason": "timeout_t_minus_2s"},
        )
        self.assertEqual(evt.event_type, "execution.order_cancelled")

    def test_emit_settlement_binance_price(self) -> None:
        evt = self.writer.emit_settlement(
            "binance_price",
            {"symbol": "BTCUSDT", "price": 68000.0},
        )
        self.assertEqual(evt.event_type, "settlement.binance_price")

    def test_emit_settlement_candle_open(self) -> None:
        evt = self.writer.emit_settlement(
            "candle_open",
            {"symbol": "BTCUSDT", "open_price": 67950.0},
        )
        self.assertEqual(evt.event_type, "settlement.candle_open")


# =========================================================================
# 4. Causal chain traversal
# =========================================================================


class TestCausalChain(_TapeTestCase):

    def test_single_event_chain(self) -> None:
        evt = self.writer.emit("test.root", "src", {})
        chain = self.writer.query_causal_chain(evt.seq)
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].seq, evt.seq)

    def test_two_event_chain(self) -> None:
        e1 = self.writer.emit("test.a", "src", {})
        e2 = self.writer.emit("test.b", "src", {}, causation_seq=e1.seq)
        chain = self.writer.query_causal_chain(e2.seq)
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0].seq, e1.seq)
        self.assertEqual(chain[1].seq, e2.seq)

    def test_three_event_chain(self) -> None:
        e1 = self.writer.emit("market.discovered", "src", {})
        e2 = self.writer.emit("book.snapshot", "src", {}, causation_seq=e1.seq)
        e3 = self.writer.emit("decision.trade_proposed", "src", {}, causation_seq=e2.seq)
        chain = self.writer.query_causal_chain(e3.seq)
        self.assertEqual(len(chain), 3)
        self.assertEqual([e.seq for e in chain], [e1.seq, e2.seq, e3.seq])

    def test_chain_for_nonexistent_seq(self) -> None:
        chain = self.writer.query_causal_chain(9999)
        self.assertEqual(chain, [])

    def test_chain_no_infinite_loop(self) -> None:
        """A cycle in causation_seq should not loop forever."""
        # Create events then manually insert a circular reference
        e1 = self.writer.emit("test.a", "src", {})
        e2 = self.writer.emit("test.b", "src", {}, causation_seq=e1.seq)
        # Manually create a circular reference via raw SQL
        self.writer._conn.execute(
            "UPDATE events SET causation_seq = ? WHERE seq = ?",
            (e2.seq, e1.seq),
        )
        self.writer._conn.commit()
        chain = self.writer.query_causal_chain(e2.seq)
        # Should terminate (visited set prevents infinite loop)
        self.assertLessEqual(len(chain), 2)


# =========================================================================
# 5. Correlation grouping
# =========================================================================


class TestCorrelation(_TapeTestCase):

    def test_query_by_correlation(self) -> None:
        cid = "window-12345"
        self.writer.emit("test.a", "src", {}, correlation_id=cid)
        self.writer.emit("test.b", "src", {}, correlation_id=cid)
        self.writer.emit("test.c", "src", {}, correlation_id="other")
        results = self.writer.query_by_correlation(cid)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(e.correlation_id == cid for e in results))

    def test_query_by_correlation_empty(self) -> None:
        results = self.writer.query_by_correlation("nonexistent")
        self.assertEqual(results, [])

    def test_correlation_ordering(self) -> None:
        cid = "seq-test"
        e1 = self.writer.emit("test.a", "src", {}, correlation_id=cid)
        e2 = self.writer.emit("test.b", "src", {}, correlation_id=cid)
        results = self.writer.query_by_correlation(cid)
        self.assertEqual(results[0].seq, e1.seq)
        self.assertEqual(results[1].seq, e2.seq)


# =========================================================================
# 6. query_by_type
# =========================================================================


class TestQueryByType(_TapeTestCase):

    def test_query_by_type_basic(self) -> None:
        self.writer.emit("market.discovered", "src", {})
        self.writer.emit("book.snapshot", "src", {})
        self.writer.emit("market.discovered", "src", {})
        results = self.writer.query_by_type("market.discovered")
        self.assertEqual(len(results), 2)

    def test_query_by_type_with_limit(self) -> None:
        for _ in range(10):
            self.writer.emit("test.event", "src", {})
        results = self.writer.query_by_type("test.event", limit=3)
        self.assertEqual(len(results), 3)

    def test_query_by_type_since_ts(self) -> None:
        e1 = self.writer.emit("test.event", "src", {})
        # Ensure a different ts
        time.sleep(0.001)
        e2 = self.writer.emit("test.event", "src", {})
        results = self.writer.query_by_type("test.event", since_ts=e2.ts)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].seq, e2.seq)

    def test_query_by_type_no_match(self) -> None:
        self.writer.emit("test.event", "src", {})
        results = self.writer.query_by_type("nonexistent.type")
        self.assertEqual(results, [])


# =========================================================================
# 7. P&L derivation
# =========================================================================


class TestPnLDerivation(_TapeTestCase):

    def test_pnl_empty_tape(self) -> None:
        pnl = self.writer.derive_pnl()
        self.assertEqual(pnl["realized_pnl"], 0.0)
        self.assertEqual(pnl["fill_count"], 0)
        self.assertEqual(pnl["redemption_count"], 0)

    def test_pnl_fills_only(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"order_id": "o1", "fill_size_usd": 10.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "order_filled",
            {"order_id": "o2", "fill_size_usd": 5.0, "market_id": "m-1"},
        )
        pnl = self.writer.derive_pnl()
        self.assertAlmostEqual(pnl["total_cost"], 15.0)
        self.assertAlmostEqual(pnl["total_payout"], 0.0)
        self.assertAlmostEqual(pnl["realized_pnl"], -15.0)
        self.assertEqual(pnl["fill_count"], 2)

    def test_pnl_fills_and_redemptions(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"order_id": "o1", "fill_size_usd": 10.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "position_redeemed",
            {"condition_id": "c1", "market_id": "m-1", "payout_usd": 18.0},
        )
        pnl = self.writer.derive_pnl()
        self.assertAlmostEqual(pnl["realized_pnl"], 8.0)
        self.assertEqual(pnl["redemption_count"], 1)

    def test_pnl_per_position(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 5.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 8.0, "market_id": "m-2"},
        )
        self.writer.emit_execution(
            "position_redeemed",
            {"payout_usd": 10.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "position_redeemed",
            {"payout_usd": 3.0, "market_id": "m-2"},
        )
        pnl = self.writer.derive_pnl()
        self.assertAlmostEqual(pnl["positions"]["m-1"]["pnl"], 5.0)
        self.assertAlmostEqual(pnl["positions"]["m-2"]["pnl"], -5.0)
        self.assertAlmostEqual(pnl["realized_pnl"], 0.0)

    def test_pnl_since_ts(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 100.0, "market_id": "m-old"},
        )
        time.sleep(0.002)
        cutoff = time.time_ns() // 1000
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 5.0, "market_id": "m-new"},
        )
        pnl = self.writer.derive_pnl(since_ts=cutoff)
        self.assertAlmostEqual(pnl["total_cost"], 5.0)
        self.assertEqual(pnl["fill_count"], 1)


# =========================================================================
# 8. Wallet divergence detection
# =========================================================================


class TestWalletDivergence(_TapeTestCase):

    def test_no_divergence(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 10.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "position_redeemed",
            {"payout_usd": 15.0, "market_id": "m-1"},
        )
        # tape_derived = 15 - 10 = 5
        result = self.writer.check_wallet_divergence(api_balance=5.0)
        self.assertAlmostEqual(result["tape_derived_balance"], 5.0)
        self.assertAlmostEqual(result["divergence_usd"], 0.0)
        self.assertFalse(result["is_divergent"])

    def test_divergence_detected(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 100.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "position_redeemed",
            {"payout_usd": 200.0, "market_id": "m-1"},
        )
        # tape_derived = 200 - 100 = 100
        # api says 50 => 50% divergence
        result = self.writer.check_wallet_divergence(api_balance=50.0)
        self.assertTrue(result["is_divergent"])
        self.assertAlmostEqual(result["divergence_usd"], 50.0)

    def test_divergence_empty_tape(self) -> None:
        result = self.writer.check_wallet_divergence(api_balance=100.0)
        # tape_derived = 0, api = 100 => divergent
        self.assertTrue(result["is_divergent"])

    def test_small_divergence_not_flagged(self) -> None:
        self.writer.emit_execution(
            "order_filled",
            {"fill_size_usd": 100.0, "market_id": "m-1"},
        )
        self.writer.emit_execution(
            "position_redeemed",
            {"payout_usd": 200.0, "market_id": "m-1"},
        )
        # tape_derived = 100, api = 101 => 1% divergence
        result = self.writer.check_wallet_divergence(api_balance=101.0)
        self.assertFalse(result["is_divergent"])


# =========================================================================
# 9. Thread safety
# =========================================================================


class TestThreadSafety(_TapeTestCase):

    def test_concurrent_writes(self) -> None:
        """Multiple threads writing simultaneously should not lose events."""
        n_threads = 8
        n_per_thread = 50
        errors: list[str] = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(n_per_thread):
                    self.writer.emit(
                        "test.concurrent",
                        f"thread-{thread_id}",
                        {"i": i},
                    )
            except Exception as e:
                errors.append(f"thread-{thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        total = self.writer.count_events()
        self.assertEqual(total, n_threads * n_per_thread)

    def test_concurrent_seq_uniqueness(self) -> None:
        """All sequences should be unique even under contention."""
        n_threads = 4
        n_per_thread = 25
        all_seqs: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(n_per_thread):
                evt = self.writer.emit("test.concurrent", "src", {})
                with lock:
                    all_seqs.append(evt.seq)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(all_seqs), n_threads * n_per_thread)
        self.assertEqual(len(set(all_seqs)), len(all_seqs), "Duplicate seqs found")


# =========================================================================
# 10. Empty tape edge cases
# =========================================================================


class TestEmptyTape(_TapeTestCase):

    def test_get_latest_seq_empty(self) -> None:
        self.assertEqual(self.writer.get_latest_seq(), 0)

    def test_count_events_empty(self) -> None:
        self.assertEqual(self.writer.count_events(), 0)

    def test_count_events_by_type_empty(self) -> None:
        self.assertEqual(self.writer.count_events("market.discovered"), 0)

    def test_query_by_type_empty(self) -> None:
        self.assertEqual(self.writer.query_by_type("test.event"), [])

    def test_query_by_correlation_empty(self) -> None:
        self.assertEqual(self.writer.query_by_correlation("x"), [])

    def test_query_causal_chain_empty(self) -> None:
        self.assertEqual(self.writer.query_causal_chain(1), [])

    def test_derive_pnl_empty(self) -> None:
        pnl = self.writer.derive_pnl()
        self.assertEqual(pnl["realized_pnl"], 0.0)

    def test_check_wallet_divergence_empty(self) -> None:
        result = self.writer.check_wallet_divergence(0.0)
        # Both zero, divergence should be 0
        self.assertAlmostEqual(result["divergence_usd"], 0.0)


# =========================================================================
# 11. Large event payloads
# =========================================================================


class TestLargePayloads(_TapeTestCase):

    def test_large_payload_roundtrip(self) -> None:
        big_payload = {
            "model_details": [
                {"model": f"model_{i}", "estimate": 0.5 + i * 0.001, "latency_ms": i}
                for i in range(100)
            ],
            "description": "x" * 10000,
        }
        evt = self.writer.emit("decision.probability_estimated", "ensemble", big_payload)
        results = self.writer.query_by_type("decision.probability_estimated")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].payload["description"], "x" * 10000)
        self.assertEqual(len(results[0].payload["model_details"]), 100)

    def test_nested_payload(self) -> None:
        payload = {
            "level1": {
                "level2": {
                    "level3": {"data": [1, 2, 3]},
                },
            },
        }
        evt = self.writer.emit("test.nested", "src", payload)
        results = self.writer.query_by_type("test.nested")
        self.assertEqual(results[0].payload["level1"]["level2"]["level3"]["data"], [1, 2, 3])


# =========================================================================
# 12. count_events and get_latest_seq
# =========================================================================


class TestCountAndLatest(_TapeTestCase):

    def test_count_all(self) -> None:
        for _ in range(7):
            self.writer.emit("test.event", "src", {})
        self.assertEqual(self.writer.count_events(), 7)

    def test_count_by_type(self) -> None:
        for _ in range(3):
            self.writer.emit("type.a", "src", {})
        for _ in range(5):
            self.writer.emit("type.b", "src", {})
        self.assertEqual(self.writer.count_events("type.a"), 3)
        self.assertEqual(self.writer.count_events("type.b"), 5)

    def test_get_latest_seq(self) -> None:
        for _ in range(4):
            self.writer.emit("test.event", "src", {})
        self.assertEqual(self.writer.get_latest_seq(), 4)


# =========================================================================
# 13. Session ID
# =========================================================================


class TestSessionId(_TapeTestCase):

    def test_auto_session_id(self) -> None:
        writer = EventTapeWriter(
            db_path=os.path.join(self._tmpdir, "tape2.db"),
        )
        self.assertIsInstance(writer.session_id, str)
        self.assertGreater(len(writer.session_id), 0)
        writer.close()

    def test_custom_session_id(self) -> None:
        self.assertEqual(self.writer.session_id, "test-session")


# =========================================================================
# 14. Typed helper kwargs
# =========================================================================


class TestTypedHelperKwargs(_TapeTestCase):

    def test_market_discovered_with_correlation(self) -> None:
        evt = self.writer.emit_market_discovered(
            condition_id="0x1",
            market_id="m-1",
            question="Q?",
            slug="s",
            category="crypto",
            end_date_ts=0,
            tokens=[],
            source_api="gamma_markets_api",
            correlation_id="corr-1",
        )
        self.assertEqual(evt.correlation_id, "corr-1")

    def test_decision_with_causation(self) -> None:
        e1 = self.writer.emit("book.snapshot", "src", {})
        e2 = self.writer.emit_decision(
            "trade_proposed",
            {"market_id": "m-1"},
            causation_seq=e1.seq,
        )
        self.assertEqual(e2.causation_seq, e1.seq)

    def test_execution_custom_source(self) -> None:
        evt = self.writer.emit_execution(
            "order_placed",
            {"order_id": "o1"},
            source="btc5_maker",
        )
        self.assertEqual(evt.source, "btc5_maker")

    def test_settlement_custom_source(self) -> None:
        evt = self.writer.emit_settlement(
            "binance_price",
            {"symbol": "BTCUSDT", "price": 70000},
            source="custom_feed",
        )
        self.assertEqual(evt.source, "custom_feed")


# =========================================================================
# 15. Persistence / data survives close+reopen
# =========================================================================


class TestPersistence(_TapeTestCase):

    def test_events_survive_reopen(self) -> None:
        self.writer.emit("test.persist", "src", {"val": 42})
        self.writer.close()

        writer2 = EventTapeWriter(db_path=self.db_path, session_id="s2")
        results = writer2.query_by_type("test.persist")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].payload["val"], 42)
        writer2.close()


if __name__ == "__main__":
    unittest.main()
