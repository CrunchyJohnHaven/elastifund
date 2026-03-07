"""Tests for B-1 gold set generation logic."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.relation_classifier import RelationResult
from bot.resolution_normalizer import NormalizedMarket, ResolutionProfile
from scripts.build_b1_gold_set import (
    RELATION_TARGETS,
    TOTAL_GOLD_SET,
    build_gold_set_json,
    run_threshold_analysis,
    select_gold_set,
    write_gold_set_json,
    write_gold_set_markdown,
)


def _mk_market(market_id: str, question: str, event_id: str = "evt-1") -> NormalizedMarket:
    return NormalizedMarket(
        market_id=market_id,
        event_id=event_id,
        question=question,
        category="politics",
        outcomes=("Yes", "No"),
        outcome="Yes",
        resolution_text="Test resolution",
        is_multi_outcome=False,
        yes_token_id=f"tok-yes-{market_id}",
        no_token_id=f"tok-no-{market_id}",
        tick_size=0.01,
        min_order_size=1.0,
        accepting_orders=True,
        enable_order_book=True,
        profile=ResolutionProfile(
            source="Associated Press",
            cutoff_ts=1700000000,
            scope_fingerprint=("politics", "election"),
            is_neg_risk=False,
        ),
        resolution_key="test-key",
    )


def _mk_result(
    relation_type: str = "A_implies_B",
    confidence: float = 0.85,
    source: str = "haiku_model",
) -> RelationResult:
    return RelationResult(
        relation_type=relation_type,
        confidence=confidence,
        reason="test",
        ambiguous=False,
        needs_human_review=False,
        short_rationale="Test rationale",
        source=source,
        prompt_version="relation-haiku-v1",
        cache_hit=False,
        model_name="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_usd=0.001,
    )


def _mk_classified_entry(
    idx: int,
    relation_type: str = "A_implies_B",
    confidence: float = 0.85,
) -> dict:
    return {
        "market_a": _mk_market(f"a-{idx}", f"Market A question {idx}"),
        "market_b": _mk_market(f"b-{idx}", f"Market B question {idx}"),
        "pair_signature": f"sig-{idx}",
        "candidate_score": 0.9 - idx * 0.01,
        "sample_bucket": "implication_candidate",
        "classification": _mk_result(relation_type=relation_type, confidence=confidence),
    }


class TestGoldSetSelection(unittest.TestCase):
    def test_select_covers_all_relation_types(self) -> None:
        """Gold set selection should span all target relation types."""
        classified = []
        idx = 0
        for relation, target in RELATION_TARGETS.items():
            for _ in range(target + 5):  # more than needed per type
                classified.append(_mk_classified_entry(idx, relation_type=relation))
                idx += 1

        gold = select_gold_set(classified, target_count=TOTAL_GOLD_SET)
        self.assertEqual(len(gold), TOTAL_GOLD_SET)

        # Should have at least some of each type
        types_present = {e["classification"].relation_type for e in gold}
        for relation in RELATION_TARGETS:
            self.assertIn(relation, types_present, f"Missing relation type: {relation}")

    def test_select_deduplicates_by_signature(self) -> None:
        """Should not include duplicate pair signatures."""
        classified = [_mk_classified_entry(1, relation_type="A_implies_B")]
        classified.append(_mk_classified_entry(1, relation_type="B_implies_A"))  # same sig
        classified[1]["pair_signature"] = classified[0]["pair_signature"]

        for i in range(2, 52):
            classified.append(_mk_classified_entry(i))

        gold = select_gold_set(classified, target_count=50)
        sigs = [e["pair_signature"] for e in gold]
        self.assertEqual(len(sigs), len(set(sigs)), "Duplicate signatures in gold set")

    def test_select_with_fewer_than_target(self) -> None:
        """Should return all available if fewer than target."""
        classified = [_mk_classified_entry(i) for i in range(10)]
        gold = select_gold_set(classified, target_count=50)
        self.assertEqual(len(gold), 10)

    def test_select_sorts_by_confidence(self) -> None:
        """Higher confidence pairs should be preferred within each bucket."""
        classified = [
            _mk_classified_entry(1, relation_type="A_implies_B", confidence=0.50),
            _mk_classified_entry(2, relation_type="A_implies_B", confidence=0.95),
            _mk_classified_entry(3, relation_type="A_implies_B", confidence=0.75),
        ]
        gold = select_gold_set(classified, target_count=3)
        confs = [e["classification"].confidence for e in gold]
        # Should be sorted descending within type
        self.assertEqual(confs[0], 0.95)


class TestGoldSetJSON(unittest.TestCase):
    def test_build_json_structure(self) -> None:
        """JSON output should have correct structure."""
        classified = [_mk_classified_entry(i, relation_type="mutually_exclusive") for i in range(3)]
        gold = select_gold_set(classified, target_count=3)
        records = build_gold_set_json(gold, generated_at="2026-03-07T00:00:00Z")

        self.assertEqual(len(records), 3)
        for record in records:
            self.assertIn("pair_id", record)
            self.assertIn("market_a_id", record)
            self.assertIn("market_b_id", record)
            self.assertIn("market_a_title", record)
            self.assertIn("market_b_title", record)
            self.assertIn("classified_relation", record)
            self.assertIn("confidence", record)
            self.assertIn("human_label_placeholder", record)
            self.assertIn("labeled", record)
            self.assertFalse(record["labeled"])
            self.assertIsNone(record["human_label_placeholder"])
            self.assertEqual(record["classified_relation"], "mutually_exclusive")

    def test_write_json_file(self) -> None:
        """Should write valid JSON file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.json"
            records = [{"pair_id": 1, "labeled": False}]
            write_gold_set_json(records, path)

            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["pair_id"], 1)


class TestGoldSetMarkdown(unittest.TestCase):
    def test_write_markdown(self) -> None:
        """Should write valid markdown with table."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.md"
            records = build_gold_set_json(
                [_mk_classified_entry(1)],
                generated_at="2026-03-07T00:00:00Z",
            )
            write_gold_set_markdown(records, path)

            content = path.read_text(encoding="utf-8")
            self.assertIn("# B-1 Gold Set Candidates", content)
            self.assertIn("| #", content)
            self.assertIn("A_implies_B", content)
            self.assertIn("Instructions for John", content)


class TestThresholdAnalysis(unittest.TestCase):
    def test_threshold_report_generated(self) -> None:
        """Should produce tuning report with threshold table."""
        classified = []
        for i in range(30):
            conf = 0.5 + (i * 0.015)  # range 0.50 to 0.935
            classified.append(_mk_classified_entry(i, confidence=min(conf, 0.99)))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tuning.md"
            run_threshold_analysis(classified, path)

            content = path.read_text(encoding="utf-8")
            self.assertIn("# B-1 Classifier Confidence Threshold Tuning", content)
            self.assertIn("Threshold", content)
            self.assertIn("Recommendation", content)
            self.assertIn("Pairs Retained", content)

    def test_threshold_report_empty(self) -> None:
        """Should handle empty classified list gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tuning.md"
            run_threshold_analysis([], path)

            content = path.read_text(encoding="utf-8")
            self.assertIn("No classified pairs available", content)


if __name__ == "__main__":
    unittest.main()
