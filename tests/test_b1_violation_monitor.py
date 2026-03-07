import tempfile
import time
import unittest
from pathlib import Path

from infra.clob_ws import BestBidAskStore
from strategies.b1_dependency_graph import GraphStore, MarketMeta, PairEdge
from strategies.b1_violation_monitor import B1ViolationMonitor


class TestB1ViolationMonitor(unittest.TestCase):
    def test_implication_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(Path(tmp) / "arb_graph.db")
            store.upsert_market(MarketMeta("a", "evt-a", "Will CPI be above 4.0?", "Official CPI release", "economics", "inflation", "2026-06-30T00:00:00Z", "ta", "na", False, "ha"))
            store.upsert_market(MarketMeta("b", "evt-b", "Will CPI be above 3.0?", "Official CPI release", "economics", "inflation", "2026-06-30T00:00:00Z", "tb", "nb", False, "hb"))
            store.upsert_edge(PairEdge("a", "b", "A_implies_B", 0.9, "forced", tuple(), "prompt", "haiku-v1", int(time.time())))

            quotes = BestBidAskStore()
            now = time.time()
            quotes.update("ta", best_bid=0.70, best_ask=0.71, updated_ts=now)
            quotes.update("tb", best_bid=0.60, best_ask=0.61, updated_ts=now)

            monitor = B1ViolationMonitor(graph_store=store, quote_store=quotes, implication_threshold=0.02)
            signals = monitor.scan(min_confidence=0.8)
            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0].action, "sell_A_buy_B")


if __name__ == "__main__":
    unittest.main()
