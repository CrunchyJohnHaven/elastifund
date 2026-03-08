"""Tests for B-1 shadow monitor (scripts/run_b1_shadow.py)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.b1_monitor import B1LegQuote, B1Monitor, B1MonitorBatch, B1MonitorTrace, B1Opportunity
from bot.constraint_arb_engine import GraphEdge, MarketQuote
from bot.resolution_normalizer import NormalizedMarket, ResolutionProfile, normalize_market
from scripts.run_b1_shadow import B1ShadowMonitor


def _mk_raw_market(
    market_id: str,
    question: str,
    event_id: str = "evt-1",
    source: str = "Associated Press",
    end_date: str = "2026-11-03T23:59:00Z",
) -> dict:
    return {
        "market_id": market_id,
        "event_id": event_id,
        "question": question,
        "outcome": "Yes",
        "outcomes": ["Yes", "No"],
        "category": "politics",
        "resolutionSource": source,
        "endDate": end_date,
        "rules": f"Resolves using {source} at {end_date}.",
    }


def _mk_opportunity(
    *,
    edge_id: str = "edge-1",
    relation_type: str = "A_implies_B",
    trigger_edge: float = 0.08,
    theoretical_edge: float = 0.08,
    now_ts: int = 1_700_000_000,
) -> B1Opportunity:
    return B1Opportunity(
        opportunity_id="opp-test-1",
        edge_id=edge_id,
        relation_type=relation_type,
        basket_action="buy_no_a_buy_yes_b",
        market_ids=("mkt-a", "mkt-b"),
        legs=(
            B1LegQuote(leg_id="mkt-a:NO", market_id="mkt-a", side="NO", best_bid=0.29, best_ask=0.30, updated_ts=now_ts),
            B1LegQuote(leg_id="mkt-b:YES", market_id="mkt-b", side="YES", best_bid=0.60, best_ask=0.61, updated_ts=now_ts),
        ),
        trigger_edge=trigger_edge,
        theoretical_edge=theoretical_edge,
        payoff_floor=1.0,
        relation_confidence=0.92,
        resolution_gate_status="passed",
        resolution_gate_reasons=("source_match",),
        quote_age_seconds=2,
        detected_at_ts=now_ts,
        details={"test": True},
    )


class TestB1ShadowMonitorInit(unittest.TestCase):
    def test_creates_violation_table(self) -> None:
        """Shadow monitor should create b1_violations table on init."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            shadow = B1ShadowMonitor(db_path=db_path, scan_interval=60)

            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='b1_violations'"
            )
            tables = cursor.fetchall()
            conn.close()

            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0][0], "b1_violations")

    def test_min_scan_interval(self) -> None:
        """Scan interval should be at least 60 seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            shadow = B1ShadowMonitor(db_path=Path(tmp) / "test.db", scan_interval=10)
            self.assertEqual(shadow.scan_interval, 60)


class TestB1ShadowViolationLogging(unittest.TestCase):
    def test_log_violation_persists_to_sqlite(self) -> None:
        """Violations should be persisted to SQLite."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            shadow = B1ShadowMonitor(db_path=db_path, scan_interval=60)

            opp = _mk_opportunity(
                edge_id="edge-abc",
                relation_type="mutually_exclusive",
                trigger_edge=0.05,
                theoretical_edge=0.04,
            )
            shadow._log_violation(opp)

            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT * FROM b1_violations").fetchall()
            conn.close()

            self.assertEqual(len(rows), 1)
            row = rows[0]
            # Column order: id, timestamp, timestamp_iso, edge_id, relation_type,
            #   market_a_id, market_b_id, basket_action, trigger_edge,
            #   theoretical_edge, relation_confidence, resolution_gate_status,
            #   quote_age_seconds, details_json, mode
            self.assertEqual(row[3], "edge-abc")  # edge_id
            self.assertEqual(row[4], "mutually_exclusive")  # relation_type
            self.assertEqual(row[5], "mkt-a")  # market_a_id
            self.assertEqual(row[6], "mkt-b")  # market_b_id
            self.assertAlmostEqual(row[8], 0.05, places=4)  # trigger_edge
            self.assertAlmostEqual(row[9], 0.04, places=4)  # theoretical_edge
            self.assertEqual(row[14], "shadow")  # mode

    def test_log_multiple_violations(self) -> None:
        """Multiple violations should all be persisted."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            shadow = B1ShadowMonitor(db_path=db_path, scan_interval=60)

            for i in range(5):
                opp = _mk_opportunity(edge_id=f"edge-{i}", trigger_edge=0.03 + i * 0.01)
                shadow._log_violation(opp)

            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM b1_violations").fetchone()[0]
            conn.close()

            self.assertEqual(count, 5)

    def test_details_stored_as_json(self) -> None:
        """Details field should be valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            shadow = B1ShadowMonitor(db_path=db_path, scan_interval=60)

            opp = _mk_opportunity()
            shadow._log_violation(opp)

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT details_json FROM b1_violations").fetchone()
            conn.close()

            details = json.loads(row[0])
            self.assertIsInstance(details, dict)
            self.assertTrue(details.get("test"))


class TestB1ShadowBatchProcessing(unittest.TestCase):
    def test_process_batch_logs_executable(self) -> None:
        """process_batch should log executable violations."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            shadow = B1ShadowMonitor(db_path=db_path, scan_interval=60)

            opp1 = _mk_opportunity(edge_id="e1", trigger_edge=0.05)
            opp2 = _mk_opportunity(edge_id="e2", trigger_edge=0.08)
            batch = B1MonitorBatch(
                executable=(opp1, opp2),
                log_only=(),
                dropped=(),
            )

            shadow._process_batch(batch)

            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM b1_violations").fetchone()[0]
            conn.close()

            self.assertEqual(count, 2)
            self.assertEqual(shadow._total_violations, 2)

    def test_process_batch_updates_counters(self) -> None:
        """Counters should increment on each batch."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            shadow = B1ShadowMonitor(db_path=db_path, scan_interval=60)

            self.assertEqual(shadow._total_violations, 0)
            self.assertEqual(shadow._hourly_violation_count, 0)

            batch = B1MonitorBatch(
                executable=(_mk_opportunity(),),
                log_only=(),
                dropped=(),
            )
            shadow._process_batch(batch)
            self.assertEqual(shadow._total_violations, 1)
            self.assertEqual(shadow._hourly_violation_count, 1)


class TestB1ShadowStopSignal(unittest.TestCase):
    def test_stop_sets_running_false(self) -> None:
        """stop() should set _running to False."""
        with tempfile.TemporaryDirectory() as tmp:
            shadow = B1ShadowMonitor(db_path=Path(tmp) / "test.db", scan_interval=60)
            self.assertTrue(shadow._running)
            shadow.stop()
            self.assertFalse(shadow._running)


class TestB1MonitorViolationDetection(unittest.TestCase):
    """Integration test: B1Monitor detects violations from engine state."""

    def _mk_market_raw(self, market_id: str, question: str, event_id: str = "evt-1") -> dict:
        return _mk_raw_market(market_id, question, event_id=event_id)

    def test_monitor_detects_violation_and_shadow_logs_it(self) -> None:
        """Full flow: engine -> monitor -> shadow log."""
        with tempfile.TemporaryDirectory() as tmp:
            from bot.constraint_arb_engine import ConstraintArbEngine

            db_path = Path(tmp) / "test.db"
            engine = ConstraintArbEngine(db_path=db_path)
            engine.register_markets([
                self._mk_market_raw("a", "Will CPI be above 4.0 by June 2026?", "evt-a"),
                self._mk_market_raw("b", "Will CPI be above 3.0 by June 2026?", "evt-b"),
            ])
            engine.build_constraint_graph(max_pairs=10)

            now_ts = 1_700_000_000
            engine.update_quote(market_id="a", yes_bid=0.70, yes_ask=0.71, updated_ts=now_ts)
            engine.update_quote(market_id="b", yes_bid=0.60, yes_ask=0.61, updated_ts=now_ts)

            monitor = B1Monitor(relation_threshold=0.03, stale_book_seconds=30)
            batch = monitor.scan_engine(engine, now_ts=now_ts)

            # Create shadow monitor and process
            shadow_db = Path(tmp) / "shadow.db"
            shadow = B1ShadowMonitor(db_path=shadow_db, scan_interval=60)
            shadow._process_batch(batch)

            # Verify violations logged
            conn = sqlite3.connect(shadow_db)
            count = conn.execute("SELECT COUNT(*) FROM b1_violations").fetchone()[0]
            conn.close()

            self.assertEqual(count, len(batch.executable))
            if batch.executable:
                self.assertEqual(shadow._total_violations, len(batch.executable))


if __name__ == "__main__":
    unittest.main()
