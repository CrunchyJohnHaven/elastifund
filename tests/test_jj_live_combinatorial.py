import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.jj_live import JJState, TradeDatabase


class TestJJLiveCombinatorialState(unittest.TestCase):
    def test_state_load_backfills_linked_legs_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "jj_state.json"
            state_path.write_text(json.dumps({"bankroll": 12.5, "open_positions": {}}))

            state = JJState(state_file=state_path)

            self.assertEqual(state.state["bankroll"], 12.5)
            self.assertIn("linked_legs", state.state)
            self.assertEqual(state.count_active_linked_baskets(), 0)

    def test_upsert_linked_legs_tracks_active_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = JJState(state_file=Path(tmp) / "jj_state.json")
            state.upsert_linked_legs(
                "basket-1",
                {
                    "state": "QUOTING",
                    "reserved_budget_usd": 15.0,
                },
            )

            self.assertEqual(state.count_active_linked_baskets(), 1)
            self.assertEqual(state.get_arb_budget_in_use_usd(), 15.0)

            state.upsert_linked_legs(
                "basket-1",
                {
                    "state": "SHADOW_LOGGED",
                    "reserved_budget_usd": 15.0,
                },
            )
            self.assertEqual(state.count_active_linked_baskets(), 0)
            self.assertEqual(state.get_arb_budget_in_use_usd(), 0.0)

    def test_record_trade_aggregates_multiple_fills_on_same_market_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = JJState(state_file=Path(tmp) / "jj_state.json")

            state.record_trade(
                market_id="mkt-1",
                question="Will the bill pass?",
                direction="buy_yes",
                price=0.40,
                size_usd=0.50,
                edge=0.12,
                confidence=0.70,
                order_id="ord-1",
                source="llm",
                source_combo="llm",
                source_components=["llm"],
                source_count=1,
            )
            state.record_trade(
                market_id="mkt-1",
                question="Will the bill pass?",
                direction="buy_yes",
                price=0.50,
                size_usd=0.50,
                edge=0.15,
                confidence=0.80,
                order_id="ord-2",
                source="wallet_flow",
                source_combo="wallet_flow",
                source_components=["wallet_flow"],
                source_count=1,
            )

            pos = state.state["open_positions"]["mkt-1"]
            self.assertAlmostEqual(pos["size_usd"], 1.0)
            self.assertAlmostEqual(pos["shares"], 2.25)
            self.assertAlmostEqual(pos["entry_price"], 1.0 / 2.25)
            self.assertEqual(pos["order_ids"], ["ord-1", "ord-2"])
            self.assertEqual(pos["source"], "llm")
            self.assertEqual(pos["source_combo"], "llm+wallet_flow")
            self.assertEqual(pos["source_components"], ["llm", "wallet_flow"])
            self.assertEqual(pos["source_count"], 2)

    def test_open_notional_for_market_respects_direction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = JJState(state_file=Path(tmp) / "jj_state.json")
            state.record_trade(
                market_id="mkt-1",
                question="Will the bill pass?",
                direction="buy_yes",
                price=0.40,
                size_usd=1.25,
                edge=0.12,
                confidence=0.70,
                order_id="ord-1",
                source="llm",
                source_combo="llm",
                source_components=["llm"],
                source_count=1,
            )

            self.assertAlmostEqual(state.open_notional_for_market("mkt-1"), 1.25)
            self.assertAlmostEqual(state.open_notional_for_market("mkt-1", "buy_yes"), 1.25)
            self.assertAlmostEqual(state.open_notional_for_market("mkt-1", "buy_no"), 0.0)
            self.assertAlmostEqual(state.open_notional_for_market("missing"), 0.0)


class TestJJLiveCombinatorialDatabase(unittest.TestCase):
    def test_trade_database_summarizes_combinatorial_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = TradeDatabase(db_path=Path(tmp) / "jj_trades.db")
            db.upsert_combinatorial_basket(
                {
                    "basket_id": "a6-1",
                    "violation_id": "a6-1",
                    "lane": "a6",
                    "source_id": 5,
                    "source_tag": "Signal 5 / A-6",
                    "relation_type": "same_event_sum",
                    "confirmation_mode": "bypass",
                    "execution_mode": "shadow",
                    "state": "SHADOW_LOGGED",
                    "state_reason": "shadow_mode",
                    "event_id": "evt-a6",
                    "market_ids": ["m1", "m2", "m3"],
                    "theoretical_edge": 0.04,
                    "capture_rate": 0.52,
                    "classification_accuracy": None,
                    "resolution_gate_status": "passed",
                    "budget_usd": 0.0,
                    "metadata": {"false_positive": False},
                }
            )
            db.upsert_combinatorial_basket(
                {
                    "basket_id": "b1-1",
                    "violation_id": "b1-1",
                    "lane": "b1",
                    "source_id": 6,
                    "source_tag": "Signal 6 / B-1",
                    "relation_type": "A_implies_B",
                    "confirmation_mode": "bypass",
                    "execution_mode": "blocked",
                    "state": "ROLLED_BACK",
                    "state_reason": "stale_book",
                    "event_id": "evt-b1",
                    "market_ids": ["ma", "mb"],
                    "theoretical_edge": 0.03,
                    "capture_rate": 0.30,
                    "partial_fill_loss": 0.02,
                    "classification_accuracy": 0.82,
                    "resolution_gate_status": "passed",
                    "budget_usd": 0.0,
                    "kill_rule_trigger": "stale_book",
                    "metadata": {"false_positive": True},
                }
            )

            summary = db.get_combinatorial_summary(hours=24)
            self.assertEqual(summary["lanes"]["a6"]["detected"], 1)
            self.assertEqual(summary["lanes"]["b1"]["blocked"], 1)
            self.assertAlmostEqual(summary["lanes"]["a6"]["avg_capture_rate"], 0.52)
            self.assertAlmostEqual(summary["lanes"]["b1"]["avg_classification_accuracy"], 0.82)
            self.assertAlmostEqual(summary["lanes"]["b1"]["false_positive_rate"], 1.0)
            self.assertIn("stale_book", summary["kill_triggers"])
            db.close()


if __name__ == "__main__":
    unittest.main()
