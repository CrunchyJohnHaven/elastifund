import json
import tempfile
import unittest
from pathlib import Path

from bot.relation_classifier import ModelCompletion, RelationClassifier


class ValidationAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, prompt_version: str) -> ModelCompletion:
        self.calls.append(prompt_version)
        if "partition the same outcome space" in prompt and "Fed hold rates" in prompt:
            payload = {
                "label": "complementary",
                "confidence": 0.79,
                "ambiguous": False,
                "short_rationale": "The pair partitions the same event into hold versus cut outcomes.",
                "needs_human_review": False,
            }
        else:
            payload = {
                "label": "independent",
                "confidence": 0.82,
                "ambiguous": False,
                "short_rationale": "No direct logical constraint is present.",
                "needs_human_review": False,
            }
        return ModelCompletion(
            text=json.dumps(payload),
            model_name="validation-stub",
            input_tokens=70,
            output_tokens=18,
            estimated_cost_usd=0.0007,
            latency_ms=5.5,
        )


class TestRelationClassifierValidation(unittest.TestCase):
    def test_validation_report_builds_confusion_matrix_and_failures(self) -> None:
        rows = [
            {
                "example_id": "threshold",
                "label": "A_implies_B",
                "question_a": "Will CPI be above 4.0 by June 2026?",
                "question_b": "Will CPI be above 3.0 by June 2026?",
                "category": "economics",
                "resolution_source": "BLS",
                "end_date": "2026-06-01T12:00:00Z",
            },
            {
                "example_id": "prefilter-independent",
                "label": "independent",
                "question_a": "Will the Mariners win on opening day 2026?",
                "question_b": "Will France approve a 2026 budget by July?",
                "category_a": "sports",
                "category_b": "politics",
                "resolution_source_a": "Associated Press",
                "resolution_source_b": "Official Source",
                "end_date_a": "2026-03-28T20:00:00Z",
                "end_date_b": "2026-07-15T20:00:00Z",
            },
            {
                "example_id": "llm-complementary",
                "label": "complementary",
                "question_a": "Will the Fed hold rates in July 2026?",
                "question_b": "Will the Fed cut rates in July 2026?",
                "category": "economics",
                "resolution_source": "Federal Reserve",
                "end_date": "2026-07-29T18:00:00Z",
            },
            {
                "example_id": "intentional-failure",
                "label": "ambiguous",
                "question_a": "Will turnout exceed 60% in the 2026 Italy referendum?",
                "question_b": "Will turnout exceed 55% in the 2026 Italy referendum?",
                "category": "politics",
                "resolution_source": "Official Source",
                "end_date": "2026-09-01T18:00:00Z",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            gold_set = Path(tmp) / "gold.jsonl"
            gold_set.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            classifier = RelationClassifier(
                cache_path=Path(tmp) / "relation_cache.db",
                model_adapter=ValidationAdapter(),
            )

            report = classifier.validate_gold_set(gold_set, failure_limit=5)

            self.assertEqual(report.total_examples, 4)
            self.assertEqual(report.correct_examples, 3)
            self.assertAlmostEqual(report.accuracy, 0.75, places=6)
            self.assertEqual(report.confusion_matrix["A_implies_B"]["A_implies_B"], 1)
            self.assertEqual(report.confusion_matrix["independent"]["independent"], 1)
            self.assertEqual(report.confusion_matrix["complementary"]["complementary"], 1)
            self.assertEqual(report.confusion_matrix["ambiguous"]["A_implies_B"], 1)
            self.assertEqual(len(report.failure_examples), 1)
            self.assertEqual(report.failure_examples[0]["example_id"], "intentional-failure")


if __name__ == "__main__":
    unittest.main()
