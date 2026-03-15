import tempfile
import unittest
from pathlib import Path

from bot.relation_classifier import (
    DEFAULT_DEBATE_PROMPT_VERSION,
    DEFAULT_PROMPT_VERSION,
    ModelCompletion,
    RelationClassifier,
)
from bot.resolution_normalizer import normalize_market


class StubAdapter:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, prompt_version: str) -> ModelCompletion:
        self.calls.append(prompt_version)
        payload = self.responses[prompt_version]
        return ModelCompletion(
            text=payload,
            model_name="stub-haiku",
            input_tokens=90,
            output_tokens=22,
            estimated_cost_usd=0.0009,
            latency_ms=8.0,
        )


class TestRelationClassifierSchema(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        end_date: str = "2026-11-03T23:59:00Z",
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": "Yes",
            "outcomes": ["Yes", "No"],
            "category": "politics",
            "resolutionSource": "Associated Press",
            "endDate": end_date,
            "rules": "Resolves using Associated Press.",
        }

    def test_canonical_cache_reused_for_reversed_pair(self) -> None:
        adapter = StubAdapter(
            {
                DEFAULT_PROMPT_VERSION: (
                    '{"label":"A_implies_B","confidence":0.81,"ambiguous":false,'
                    '"short_rationale":"The broader control market must be YES if the narrower seat-count market is YES.",'
                    '"needs_human_review":false}'
                )
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            classifier = RelationClassifier(
                cache_path=Path(tmp) / "relation_cache.db",
                model_adapter=adapter,
            )
            market_a = normalize_market(
                self._mk_market(
                    market_id="a",
                    event_id="evt-a",
                    question="Will Democrats win at least 220 House seats in 2026?",
                )
            )
            market_b = normalize_market(
                self._mk_market(
                    market_id="b",
                    event_id="evt-b",
                    question="Will Democrats control the House after the 2026 election?",
                )
            )

            forward = classifier.classify(market_a, market_b)
            reverse = classifier.classify(market_b, market_a)

            inverse = {
                "A_implies_B": "B_implies_A",
                "B_implies_A": "A_implies_B",
            }
            self.assertEqual(reverse.relation_type, inverse[forward.relation_type])
            self.assertEqual(adapter.calls, [DEFAULT_PROMPT_VERSION])
            self.assertTrue(reverse.cache_hit)

    def test_low_confidence_base_result_triggers_bounded_debate_prompt(self) -> None:
        adapter = StubAdapter(
            {
                DEFAULT_PROMPT_VERSION: (
                    '{"label":"ambiguous","confidence":0.41,"ambiguous":true,'
                    '"short_rationale":"The pair looks related but the dependency is not clean.",'
                    '"needs_human_review":true}'
                ),
                DEFAULT_DEBATE_PROMPT_VERSION: (
                    '{"label":"mutually_exclusive","confidence":0.76,"ambiguous":false,'
                    '"short_rationale":"Both markets encode opposing winners in the same election scope.",'
                    '"needs_human_review":false}'
                ),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            classifier = RelationClassifier(
                cache_path=Path(tmp) / "relation_cache.db",
                model_adapter=adapter,
                enable_debate_fallback=True,
                low_confidence_threshold=0.7,
                max_debate_calls=1,
            )
            market_a = normalize_market(
                self._mk_market(
                    market_id="a",
                    event_id="evt-a",
                    question="Will Candidate X win the 2026 governor race?",
                )
            )
            market_b = normalize_market(
                self._mk_market(
                    market_id="b",
                    event_id="evt-b",
                    question="Will Candidate Y win the 2026 governor race?",
                )
            )

            result = classifier.classify(market_a, market_b)

            self.assertEqual(result.relation_type, "mutually_exclusive")
            self.assertEqual(adapter.calls, [DEFAULT_PROMPT_VERSION, DEFAULT_DEBATE_PROMPT_VERSION])

    def test_invalid_non_json_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            classifier = RelationClassifier(cache_path=Path(tmp) / "relation_cache.db")
            self.assertIsNone(classifier._parse_model_output("label=A_implies_B confidence=0.9"))


if __name__ == "__main__":
    unittest.main()
