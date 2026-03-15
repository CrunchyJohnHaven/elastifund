import json
import tempfile
import unittest
from pathlib import Path

from bot.dependency_graph import DependencyGraphService
from infra.clob_ws import BestBidAskStore
from signals.dep_graph.dep_candidate_pairs import DepCandidatePairGenerator
from signals.dep_graph.dep_haiku_classifier import HaikuDependencyClassifier


def _mk_market(
    *,
    market_id: str,
    question: str,
    category: str = "politics",
    end_date: str = "2026-11-03T23:59:00Z",
    yes_token: str | None = None,
    no_token: str | None = None,
) -> dict:
    return {
        "id": market_id,
        "question": question,
        "category": category,
        "endDate": end_date,
        "clobTokenIds": json.dumps(
            [
                yes_token or f"{market_id}-yes",
                no_token or f"{market_id}-no",
            ]
        ),
    }


class TestDependencyGraphService(unittest.TestCase):
    def test_build_graph_uses_cache_and_review_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []

            def transport(system_prompt: str, user_prompt: str) -> str:
                del system_prompt
                calls.append(user_prompt)
                return (
                    '{"relation":"A_implies_B","confidence":0.86,'
                    '"reason":"threshold ordering","tradeable_constraint":"P(A)<=P(B)"}'
                )

            service = DependencyGraphService(
                db_path=Path(tmp) / "dep_graph.sqlite",
                candidate_generator=DepCandidatePairGenerator(top_k=5, min_score=0.10),
                classifier=HaikuDependencyClassifier(
                    model_version="test-haiku-v1",
                    transport=transport,
                ),
            )
            markets = [
                _mk_market(market_id="a", question="Will CPI be above 4.0 by June 2026?"),
                _mk_market(market_id="b", question="Will CPI be above 3.0 by June 2026?"),
            ]

            first = service.build_graph(markets, min_confidence=0.7)
            second = service.build_graph(markets, min_confidence=0.7)

            self.assertEqual(first.candidate_count, 1)
            self.assertEqual(first.classified_count, 1)
            self.assertEqual(first.cache_hits, 0)
            self.assertEqual(first.tradable_edge_count, 1)
            self.assertEqual(second.classified_count, 0)
            self.assertEqual(second.cache_hits, 1)
            self.assertEqual(len(calls), 1)

            review_path = Path(tmp) / "review.json"
            labels_path = Path(tmp) / "labels.json"
            service.export_review_batch(review_path, limit=10, min_confidence=0.7)
            labels_path.write_text(
                json.dumps(
                    [
                        {
                            "edge_id": first.edges[0].edge_id,
                            "label_human": "A_implies_B",
                            "label_resolved": "A_implies_B",
                            "notes": "confirmed",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            imported = service.import_review_labels(labels_path)
            summary = service.accuracy_summary(min_confidence=0.7)

            self.assertEqual(imported, 1)
            self.assertEqual(summary["human_labeled"], 1)
            self.assertAlmostEqual(summary["accuracy_human"], 1.0)

    def test_detect_builds_complementary_violation_and_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = DependencyGraphService(
                db_path=Path(tmp) / "dep_graph.sqlite",
                candidate_generator=DepCandidatePairGenerator(top_k=5, min_score=0.10),
                classifier=HaikuDependencyClassifier(
                    model_version="test-haiku-v1",
                    transport=lambda *_args: (
                        '{"relation":"complementary","confidence":0.91,'
                        '"reason":"binary partition","tradeable_constraint":"P(A)+P(B)=1"}'
                    ),
                ),
                leg_usd_cap=5.0,
            )
            markets = [
                _mk_market(market_id="a", question="Will candidate A win the election?"),
                _mk_market(market_id="b", question="Will candidate B win the election?"),
            ]

            labels_path = Path(tmp) / "labels.json"
            build = service.build_graph(markets, min_confidence=0.7)
            labels_path.write_text(
                json.dumps(
                    [
                        {
                            "edge_id": build.edges[0].edge_id,
                            "label_human": "complementary",
                            "label_resolved": "complementary",
                            "notes": "manual review",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            service.import_review_labels(labels_path)

            store = BestBidAskStore()
            store.update("a-yes", best_bid=0.38, best_ask=0.40, updated_ts=1)
            store.update("a-no", best_bid=0.58, best_ask=0.60, updated_ts=1)
            store.update("b-yes", best_bid=0.44, best_ask=0.46, updated_ts=1)
            store.update("b-no", best_bid=0.52, best_ask=0.54, updated_ts=1)

            result = service.detect(markets, store, min_confidence=0.7)

            self.assertEqual(len(result.violations), 1)
            self.assertEqual(result.violations[0].relation, "complementary")
            self.assertEqual(tuple(leg.side for leg in result.violations[0].legs), ("BUY", "BUY"))
            self.assertEqual(tuple(leg.token_id for leg in result.violations[0].legs), ("a-yes", "b-yes"))
            self.assertEqual(len(result.attempts), 1)
            self.assertEqual(result.attempts[0].strategy_id, "B1")
            self.assertAlmostEqual(result.attempts[0].metadata["classification_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
