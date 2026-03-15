import tempfile
import unittest
from pathlib import Path

from infra.clob_ws import BestBidAskStore
from signals.dep_graph.dep_candidate_pairs import DepCandidatePairGenerator
from signals.dep_graph.dep_executor import DepExecutionPlanner
from signals.dep_graph.dep_graph_store import DepEdgeRecord, DepGraphStore, question_hash
from signals.dep_graph.dep_haiku_classifier import build_prompt, parse_response
from signals.dep_graph.dep_monitor import DepViolationMonitor
from signals.dep_graph.dep_validation import DepValidationHarness


class TestDepGraphComponents(unittest.TestCase):
    def test_store_cache_and_validation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DepGraphStore(Path(tmp) / "dep_graph.sqlite")
            store.upsert_market_meta(market_id="m1", question="Will Alice win?", category="politics", end_date="2026-01-01")
            store.upsert_market_meta(market_id="m2", question="Will Bob lose?", category="politics", end_date="2026-01-01")
            edge = DepEdgeRecord(
                edge_id="edge-1",
                a_market_id="m1",
                b_market_id="m2",
                relation="mutually_exclusive",
                confidence=0.82,
                constraint="P(A)+P(B)<=1",
                model_version="haiku-json-v1",
                a_question_hash=question_hash("Will Alice win?"),
                b_question_hash=question_hash("Will Bob lose?"),
                reason="manual",
                metadata={"kind": "test"},
            )
            store.upsert_edge(edge)
            cached = store.get_cached_edge(
                a_market_id="m1",
                b_market_id="m2",
                model_version="haiku-json-v1",
                a_question_hash=question_hash("Will Alice win?"),
                b_question_hash=question_hash("Will Bob lose?"),
            )
            self.assertIsNotNone(cached)
            self.assertEqual(cached.relation, "mutually_exclusive")

            harness = DepValidationHarness(store)
            labels_path = Path(tmp) / "labels.json"
            labels_path.write_text(
                '[{"edge_id":"edge-1","label_human":"mutually_exclusive","label_resolved":"mutually_exclusive","notes":"ok"}]',
                encoding="utf-8",
            )
            imported = harness.import_review_labels(labels_path)
            summary = harness.accuracy_summary(min_confidence=0.7)

            self.assertEqual(imported, 1)
            self.assertEqual(summary["human_labeled"], 1)
            self.assertAlmostEqual(summary["accuracy_human"], 1.0)

    def test_candidate_pair_generator_prunes_cross_category_noise(self) -> None:
        generator = DepCandidatePairGenerator(top_k=5, resolution_window_days=90)
        markets = [
            {
                "id": "m1",
                "question": "Will Alice win the mayor race?",
                "category": "politics",
                "endDate": "2026-11-03T23:59:00Z",
                "tags": [{"id": "election"}],
            },
            {
                "id": "m2",
                "question": "Will Bob win the mayor race?",
                "category": "politics",
                "endDate": "2026-11-04T23:59:00Z",
                "tags": [{"id": "election"}],
            },
            {
                "id": "m3",
                "question": "Will BTC be above 100k?",
                "category": "crypto",
                "endDate": "2026-11-03T23:59:00Z",
            },
        ]
        pairs = generator.generate(markets)
        ids = {tuple(sorted((pair.a_market["id"], pair.b_market["id"]))) for pair in pairs}
        self.assertIn(("m1", "m2"), ids)
        self.assertNotIn(("m1", "m3"), ids)

    def test_prompt_and_parser_contract(self) -> None:
        prompt = build_prompt(
            {"question": "Will Alice win?", "description": "", "endDate": "2026-01-01"},
            {"question": "Will Bob lose?", "description": "", "endDate": "2026-01-01"},
        )
        parsed = parse_response(
            '{"relation":"mutually_exclusive","confidence":0.83,"reason":"same race","tradeable_constraint":"P(A)+P(B)<=1"}'
        )
        malformed = parse_response("not-json")

        self.assertIn("Return ONLY JSON", prompt)
        self.assertEqual(parsed.relation, "mutually_exclusive")
        self.assertEqual(parsed.tradeable_constraint, "P(A)+P(B)<=1")
        self.assertEqual(malformed.relation, "independent")

    def test_monitor_detects_implication_violation_and_executor_builds_attempt(self) -> None:
        token_map = {
            "mA": {"yes_token_id": "yes-a", "no_token_id": "no-a"},
            "mB": {"yes_token_id": "yes-b", "no_token_id": "no-b"},
        }
        store = BestBidAskStore()
        store.update("yes-a", best_bid=0.60, best_ask=0.62, updated_ts=1)
        store.update("no-a", best_bid=0.36, best_ask=0.38, updated_ts=1)
        store.update("yes-b", best_bid=0.42, best_ask=0.44, updated_ts=1)
        store.update("no-b", best_bid=0.54, best_ask=0.56, updated_ts=1)

        monitor = DepViolationMonitor(token_map=token_map, c1=1.0, nonatomic_penalty=0.01)
        violation = monitor.compute_violation(
            {
                "edge_id": "edge-1",
                "a_market_id": "mA",
                "b_market_id": "mB",
                "relation": "A_implies_B",
                "confidence": 0.9,
            },
            store,
        )

        self.assertIsNotNone(violation)
        self.assertEqual(len(violation.legs), 2)
        self.assertEqual(violation.legs[0].token_id, "yes-b")

        planner = DepExecutionPlanner(leg_usd_cap=5.0)
        attempt = planner.build_attempt(violation, now_ts=5.0)
        self.assertEqual(attempt.strategy_id, "B1")
        self.assertEqual(len(attempt.legs), 2)


if __name__ == "__main__":
    unittest.main()
