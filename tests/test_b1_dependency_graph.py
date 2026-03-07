import tempfile
import time
import unittest
from pathlib import Path

from strategies.b1_dependency_graph import DependencyGraphBuilder, GraphStore, MarketMeta, PairEdge, build_classifier_prompt


class TestB1DependencyGraph(unittest.TestCase):
    def test_prompt_contains_required_structure(self) -> None:
        a = MarketMeta("a", "evt-a", "Will CPI be above 4.0?", "Resolves on official CPI release.", "economics", "inflation", "2026-06-30T00:00:00Z", "ta", "na", False, "ha")
        b = MarketMeta("b", "evt-b", "Will CPI be above 3.0?", "Resolves on official CPI release.", "economics", "inflation", "2026-06-30T00:00:00Z", "tb", "nb", False, "hb")
        prompt = build_classifier_prompt(a, b)
        self.assertIn("\"A_implies_B\"", prompt)
        self.assertIn("risk_flags", prompt)
        self.assertIn("question: Will CPI be above 4.0?", prompt)

    def test_graph_store_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(Path(tmp) / "arb_graph.db")
            market = MarketMeta("a", "evt-a", "Q", "D", "cat", "sub", None, "ta", "na", False, "hash-a")
            store.upsert_market(market, updated_at_ts=100)
            edge = PairEdge("a", "b", "A_implies_B", 0.9, "forced", ("time_mismatch",), "prompt-hash", "haiku-v1", int(time.time()))
            store.upsert_edge(edge)
            loaded = store.load_edges(min_confidence=0.8)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].label, "A_implies_B")

    def test_candidate_pairs_are_pruned_by_bucket(self) -> None:
        builder = DependencyGraphBuilder(graph_store=GraphStore(Path(tempfile.gettempdir()) / "arb_graph_test.db"))
        markets = [
            MarketMeta("a", "evt-a", "Will CPI be above 4.0?", "Official CPI release", "economics", "inflation", "2026-06-30T00:00:00Z", "ta", "na", False, "ha"),
            MarketMeta("b", "evt-b", "Will CPI be above 3.0?", "Official CPI release", "economics", "inflation", "2026-06-30T00:00:00Z", "tb", "nb", False, "hb"),
            MarketMeta("c", "evt-c", "Will it rain in Amsterdam?", "NWS source", "weather", "rain", "2026-06-30T00:00:00Z", "tc", "nc", False, "hc"),
        ]
        pairs = builder.build_candidate_pairs(markets, top_k=5)
        ids = {tuple(sorted((a.market_id, b.market_id))) for a, b in pairs}
        self.assertIn(("a", "b"), ids)
        self.assertNotIn(("a", "c"), ids)


if __name__ == "__main__":
    unittest.main()
