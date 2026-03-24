"""Tests for semantic_alignment.py — Cross-platform event matching."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.semantic_alignment import (
    AlignedPair,
    AlignmentConfig,
    AlignmentStatus,
    ContractInfo,
    RuleComparison,
    SemanticAlignmentEngine,
    SemanticArbSignal,
    compare_resolution_rules,
    compute_similarity,
    extract_entities,
    generate_pair_id,
    normalize_event_text,
)


class TestTextNormalization:
    def test_basic_normalization(self):
        assert normalize_event_text("Will the Fed raise rates?") == "fed raise rates"

    def test_strip_question_mark(self):
        assert normalize_event_text("Is it raining?") == "it raining"

    def test_whitespace_normalization(self):
        assert normalize_event_text("Will  the   rate   be  high?") == "the rate be high"


class TestEntityExtraction:
    def test_extract_numbers(self):
        ents = extract_entities("Will CPI be above 3.5% in March 2026?")
        assert "3.5" in ents["numbers"]
        assert "2026" in ents["numbers"]

    def test_extract_direction(self):
        ents = extract_entities("Will temperature exceed 80 degrees?")
        assert ents["direction"] == "above"

        ents2 = extract_entities("Will GDP fall below 2%?")
        assert ents2["direction"] == "below"

    def test_no_direction(self):
        ents = extract_entities("Will it rain tomorrow?")
        assert ents["direction"] is None

    def test_extract_dates(self):
        ents = extract_entities("Before March 15, 2026")
        assert len(ents["dates"]) >= 1


class TestSimilarity:
    def test_identical_texts(self):
        sim = compute_similarity("Will the Fed raise rates?", "Will the Fed raise rates?")
        assert sim > 0.95

    def test_similar_texts(self):
        sim = compute_similarity(
            "Will the Federal Reserve raise interest rates?",
            "Will the Fed raise rates?",
        )
        assert sim > 0.50

    def test_different_texts(self):
        sim = compute_similarity(
            "Will it rain in New York?",
            "Will Bitcoin reach $100,000?",
        )
        assert sim < 0.40

    def test_number_overlap_boost(self):
        sim_with = compute_similarity(
            "Will CPI exceed 3.5% in March?",
            "Will CPI be above 3.5%?",
        )
        sim_without = compute_similarity(
            "Will CPI exceed a certain level?",
            "Will CPI be above that threshold?",
        )
        assert sim_with >= sim_without

    def test_direction_mismatch_penalty(self):
        sim_match = compute_similarity(
            "Will temperature be above 80F?",
            "Will temperature exceed 80F?",
        )
        sim_mismatch = compute_similarity(
            "Will temperature be above 80F?",
            "Will temperature drop below 80F?",
        )
        assert sim_match > sim_mismatch


class TestRuleComparison:
    def _make_contract(self, question: str, source: str = "",
                       rules: str = "") -> ContractInfo:
        return ContractInfo(
            venue="polymarket", market_id="m1", token_id="t1",
            question=question, category="politics",
            resolution_source=source, resolution_rules=rules,
            end_date_iso="2026-04-01", yes_price=0.60,
            no_price=0.40, bid=0.59, ask=0.61,
        )

    def test_matching_rules(self):
        a = self._make_contract("Will CPI exceed 3.5%?", "BLS", "above 3.5%")
        b = self._make_contract("CPI above 3.5%?", "BLS", "above 3.5%")
        cmp = compare_resolution_rules(a, b)
        assert cmp.same_source
        assert cmp.same_direction
        assert cmp.compatibility_score > 0.7

    def test_mismatched_source(self):
        a = self._make_contract("Rate above 5%?", "Fed Reserve", "above 5%")
        b = self._make_contract("Rate above 5%?", "Reuters", "above 5%")
        cmp = compare_resolution_rules(a, b)
        assert not cmp.same_source
        assert cmp.compatibility_score < 0.8

    def test_mismatched_direction(self):
        a = self._make_contract("Temperature above 80?", "", "above 80")
        b = self._make_contract("Temperature below 80?", "", "below 80")
        cmp = compare_resolution_rules(a, b)
        assert not cmp.same_direction


class TestSemanticAlignmentEngine:
    def _make_poly(self, mid: float, question: str = "Fed rate above 5%?",
                   market_id: str = "pm1") -> ContractInfo:
        return ContractInfo(
            venue="polymarket", market_id=market_id, token_id=f"t_{market_id}",
            question=question, category="macro",
            resolution_source="Federal Reserve", resolution_rules="above 5%",
            end_date_iso="2026-04-01",
            yes_price=mid, no_price=1 - mid,
            bid=mid - 0.01, ask=mid + 0.01,
        )

    def _make_kalshi(self, mid: float, question: str = "Will the Fed rate exceed 5%?",
                     market_id: str = "k1") -> ContractInfo:
        return ContractInfo(
            venue="kalshi", market_id=market_id, token_id=f"t_{market_id}",
            question=question, category="macro",
            resolution_source="Federal Reserve", resolution_rules="above 5%",
            end_date_iso="2026-04-01",
            yes_price=mid, no_price=1 - mid,
            bid=mid - 0.02, ask=mid + 0.02,
        )

    def test_find_aligned_pair(self):
        engine = SemanticAlignmentEngine()
        engine.add_contracts(
            [self._make_poly(0.50)],
            [self._make_kalshi(0.55)],
        )
        pairs = engine.find_aligned_pairs()
        assert len(pairs) == 1
        assert pairs[0].text_similarity > 0.5

    def test_no_match_different_events(self):
        engine = SemanticAlignmentEngine()
        engine.add_contracts(
            [self._make_poly(0.50, "Will it rain in NYC?")],
            [self._make_kalshi(0.55, "Will Bitcoin hit 200K?")],
        )
        pairs = engine.find_aligned_pairs()
        assert len(pairs) == 0

    def test_divergence_measurement(self):
        engine = SemanticAlignmentEngine()
        poly = self._make_poly(0.50)
        kalshi = self._make_kalshi(0.60)  # 10% divergence
        engine.add_contracts([poly], [kalshi])
        pairs = engine.find_aligned_pairs()
        assert len(pairs) == 1
        assert abs(pairs[0].divergence - 0.10) < 0.02

    def test_evaluate_divergence_needs_verification(self):
        config = AlignmentConfig(require_llm_verification=True)
        engine = SemanticAlignmentEngine(config)
        engine.add_contracts(
            [self._make_poly(0.50)],
            [self._make_kalshi(0.60)],
        )
        pairs = engine.find_aligned_pairs()
        # Without verification, no signals
        signals = engine.evaluate_divergences()
        assert len(signals) == 0

    def test_evaluate_after_verification(self):
        config = AlignmentConfig(
            require_llm_verification=True,
            min_divergence=0.02,
            min_net_edge_bps=5.0,
        )
        engine = SemanticAlignmentEngine(config)
        engine.add_contracts(
            [self._make_poly(0.50)],
            [self._make_kalshi(0.60)],
        )
        pairs = engine.find_aligned_pairs()
        assert len(pairs) == 1

        engine.verify_pair(pairs[0].pair_id, is_aligned=True, notes="Same event")
        signals = engine.evaluate_divergences()
        assert len(signals) >= 1
        assert signals[0].divergence > 0.05

    def test_false_parity_logging(self):
        config = AlignmentConfig(require_llm_verification=True)
        engine = SemanticAlignmentEngine(config)
        engine.add_contracts(
            [self._make_poly(0.50)],
            [self._make_kalshi(0.60)],
        )
        pairs = engine.find_aligned_pairs()
        engine.verify_pair(pairs[0].pair_id, is_aligned=False, notes="Different rules")

        stats = engine.get_pair_stats()
        assert stats["status_counts"].get("false_parity", 0) == 1

    def test_signal_direction(self):
        config = AlignmentConfig(
            require_llm_verification=False,
            min_divergence=0.02,
            min_net_edge_bps=5.0,
        )
        engine = SemanticAlignmentEngine(config)
        engine.add_contracts(
            [self._make_poly(0.40)],   # Poly cheaper
            [self._make_kalshi(0.55)], # Kalshi expensive
        )
        engine.find_aligned_pairs()
        signals = engine.evaluate_divergences()
        if signals:
            assert signals[0].long_venue == "polymarket"  # buy cheap
            assert signals[0].short_venue == "kalshi"      # sell expensive

    def test_pair_stats(self):
        engine = SemanticAlignmentEngine()
        stats = engine.get_pair_stats()
        assert stats["total_pairs"] == 0
        assert stats["poly_contracts"] == 0

    def test_get_pending_signals_drains(self):
        config = AlignmentConfig(
            require_llm_verification=False,
            min_divergence=0.02,
            min_net_edge_bps=5.0,
        )
        engine = SemanticAlignmentEngine(config)
        engine.add_contracts(
            [self._make_poly(0.40)],
            [self._make_kalshi(0.60)],
        )
        engine.find_aligned_pairs()
        engine.evaluate_divergences()

        signals = engine.get_pending_signals()
        # Second call should be empty
        signals2 = engine.get_pending_signals()
        assert len(signals2) == 0
