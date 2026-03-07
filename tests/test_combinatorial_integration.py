import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.combinatorial_integration import (
    CombinatorialConfig,
    CombinatorialSignalStore,
    attach_signal_source_metadata,
    evaluate_combinatorial_risk,
)
from signals.dep_graph.dep_graph_store import DepEdgeRecord, DepGraphStore, question_hash


class TestCombinatorialIntegration(unittest.TestCase):
    def test_attach_signal_source_metadata_assigns_a6_bypass(self) -> None:
        signal = attach_signal_source_metadata({"source": "a6"})
        self.assertEqual(signal["source_id"], 5)
        self.assertEqual(signal["source_tag"], "Signal 5 / A-6")
        self.assertEqual(signal["confirmation_mode"], "bypass")
        self.assertEqual(signal["strategy_type"], "combinatorial")

    def test_signal_store_maps_a6_and_b1_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint_arb.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE constraint_violations (
                        violation_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        relation_type TEXT NOT NULL,
                        market_ids_json TEXT NOT NULL,
                        semantic_confidence REAL NOT NULL,
                        gross_edge REAL NOT NULL,
                        action TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        detected_at_ts INTEGER NOT NULL
                    )
                    """
                )
                now_ts = int(time.time())
                conn.execute(
                    """
                    INSERT INTO constraint_violations
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a6-1",
                        "evt-a6",
                        "same_event_sum",
                        '["m1","m2","m3"]',
                        0.9,
                        0.041,
                        "buy_yes_basket",
                        '{"complete_basket": true, "legs": 3}',
                        now_ts,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO constraint_violations
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "b1-1",
                        "evt-b1",
                        "A_implies_B",
                        '["ma","mb"]',
                        0.84,
                        0.035,
                        "buy_B_sell_A",
                        '{"classification_accuracy": 0.83}',
                        now_ts,
                    ),
                )
                conn.commit()

            cfg = CombinatorialConfig(
                enable_a6_shadow=True,
                enable_b1_shadow=True,
                stale_book_max_age_seconds=300,
                max_notional_per_leg_usd=5.0,
                constraint_db_path=db_path,
            )
            store = CombinatorialSignalStore(db_path)
            opportunities = store.poll_new_opportunities(
                since_ts=0,
                config=cfg,
                now_ts=int(time.time()),
            )

            self.assertEqual(len(opportunities), 2)
            by_lane = {opp.lane: opp for opp in opportunities}
            self.assertTrue(by_lane["a6"].live_eligible)
            self.assertEqual(by_lane["a6"].estimated_budget_usd, 15.0)
            self.assertEqual(by_lane["b1"].classification_accuracy, 0.83)
            self.assertTrue(by_lane["b1"].live_eligible)

    def test_signal_store_backfills_b1_accuracy_from_dep_graph_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint_arb.db"
            dep_graph_path = Path(tmp) / "dep_graph.sqlite"

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE constraint_violations (
                        violation_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        relation_type TEXT NOT NULL,
                        market_ids_json TEXT NOT NULL,
                        semantic_confidence REAL NOT NULL,
                        gross_edge REAL NOT NULL,
                        action TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        detected_at_ts INTEGER NOT NULL
                    )
                    """
                )
                now_ts = int(time.time())
                conn.execute(
                    """
                    INSERT INTO constraint_violations
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "b1-2",
                        "evt-b1",
                        "A_implies_B",
                        '["ma","mb"]',
                        0.88,
                        0.041,
                        "buy_B_sell_A",
                        "{}",
                        now_ts,
                    ),
                )
                conn.commit()

            dep_store = DepGraphStore(dep_graph_path)
            dep_store.upsert_market_meta(market_id="ma", question="Will CPI be above 4.0?")
            dep_store.upsert_market_meta(market_id="mb", question="Will CPI be above 3.0?")
            dep_store.upsert_edge(
                DepEdgeRecord(
                    edge_id="edge-1",
                    a_market_id="ma",
                    b_market_id="mb",
                    relation="A_implies_B",
                    confidence=0.84,
                    constraint="P(A)<=P(B)",
                    model_version="haiku-json-v1",
                    a_question_hash=question_hash("Will CPI be above 4.0?"),
                    b_question_hash=question_hash("Will CPI be above 3.0?"),
                    reason="manual",
                    metadata={},
                )
            )
            dep_store.record_validation_samples(
                [
                    {
                        "edge_id": "edge-1",
                        "label_human": "A_implies_B",
                        "label_resolved": "A_implies_B",
                        "notes": "confirmed",
                    }
                ]
            )

            cfg = CombinatorialConfig(
                enable_b1_shadow=True,
                stale_book_max_age_seconds=300,
                max_notional_per_leg_usd=5.0,
                constraint_db_path=db_path,
                dep_graph_db_path=dep_graph_path,
            )
            store = CombinatorialSignalStore(db_path, dep_graph_db_path=dep_graph_path)
            opportunities = store.poll_new_opportunities(
                since_ts=0,
                config=cfg,
                now_ts=int(time.time()),
            )

            self.assertEqual(len(opportunities), 1)
            self.assertAlmostEqual(opportunities[0].classification_accuracy, 1.0)

    def test_risk_router_blocks_on_slots_and_budget(self) -> None:
        cfg = CombinatorialConfig(
            enable_a6_shadow=True,
            stale_book_max_age_seconds=300,
            max_notional_per_leg_usd=5.0,
            arb_budget_usd=10.0,
        )
        store_signal = {
            "source": "a6",
            "violation_id": "a6-2",
            "event_id": "evt-risk",
            "relation_type": "same_event_sum",
            "market_ids_json": '["m1","m2","m3"]',
            "semantic_confidence": 0.9,
            "gross_edge": 0.04,
            "action": "buy_yes_basket",
            "details_json": '{"complete_basket": true, "legs": 3}',
            "detected_at_ts": int(time.time()),
        }
        parsed = attach_signal_source_metadata({"source": "a6"})
        self.assertEqual(parsed["source_id"], 5)

        from bot.combinatorial_integration import CombinatorialOpportunity

        opp = CombinatorialOpportunity.from_violation_row(store_signal, cfg)
        assert opp is not None

        budget_block = evaluate_combinatorial_risk(
            opp,
            config=cfg,
            daily_pnl=0.0,
            max_daily_loss_usd=5.0,
            open_positions=0,
            open_baskets=0,
            max_open_positions=5,
            arb_budget_in_use_usd=0.0,
        )
        self.assertFalse(budget_block.allow)
        self.assertEqual(budget_block.reason, "arb_budget_exhausted")

        ok_cfg = CombinatorialConfig(
            enable_a6_shadow=True,
            stale_book_max_age_seconds=300,
            max_notional_per_leg_usd=5.0,
            arb_budget_usd=20.0,
        )
        ok_opp = CombinatorialOpportunity.from_violation_row(store_signal, ok_cfg)
        assert ok_opp is not None
        slot_block = evaluate_combinatorial_risk(
            ok_opp,
            config=ok_cfg,
            daily_pnl=0.0,
            max_daily_loss_usd=5.0,
            open_positions=4,
            open_baskets=1,
            max_open_positions=5,
            arb_budget_in_use_usd=0.0,
        )
        self.assertFalse(slot_block.allow)
        self.assertEqual(slot_block.reason, "max_open_positions")


if __name__ == "__main__":
    unittest.main()
