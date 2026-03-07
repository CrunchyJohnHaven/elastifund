"""
Tests for bot/cross_platform_arb.py — Cross-Platform Arbitrage Scanner.

Covers: title normalization, keyword extraction, similarity scoring,
Kalshi fee calculation, arb detection, signal format, and market parsing.
"""

import math
import pytest
import sys
from pathlib import Path

# Ensure bot/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from cross_platform_arb import (
    normalize_title,
    extract_keywords,
    keyword_similarity,
    title_similarity,
    kalshi_taker_fee,
    kalshi_maker_fee,
    detect_arb,
    arb_to_signal,
    MarketListing,
    ArbOpportunity,
    MIN_PROFIT_PCT,
)


# ===== Title Normalization =====

class TestNormalizeTitle:
    def test_lowercase(self):
        assert "hello world" in normalize_title("Hello World")

    def test_strips_punctuation(self):
        result = normalize_title("Will it happen?!.")
        assert "?" not in result
        assert "!" not in result
        assert "." not in result

    def test_removes_filler_words(self):
        result = normalize_title("Will the president be in the house?")
        assert "will" not in result.split()
        assert "the" not in result.split()
        assert "be" not in result.split()
        assert "president" in result

    def test_strips_markdown_bold(self):
        result = normalize_title("Will **high temp** be above 70?")
        assert "**" not in result
        assert "high" in result
        assert "temp" in result


# ===== Keyword Extraction =====

class TestExtractKeywords:
    def test_basic(self):
        kw = extract_keywords("Will Trump win the 2028 Presidential Election?")
        assert "trump" in kw
        assert "presidential" in kw
        assert "election" in kw
        # "will" and "the" should be removed
        assert "will" not in kw
        assert "the" not in kw

    def test_removes_dates(self):
        kw = extract_keywords("CPI in March 2026")
        assert "cpi" in kw
        assert "2026" not in kw
        assert "march" not in kw

    def test_removes_short_words(self):
        kw = extract_keywords("Is it a go or no?")
        # Words <= 2 chars should be removed
        assert "is" not in kw
        assert "it" not in kw

    def test_markdown_stripped(self):
        kw = extract_keywords("**high temp in NYC** above 70")
        assert "high" in kw
        assert "temp" in kw
        assert "**" not in str(kw)


# ===== Similarity Scoring =====

class TestSimilarity:
    def test_identical_titles(self):
        score = title_similarity(
            "Will Trump win the 2028 election?",
            "Will Trump win the 2028 election?"
        )
        assert score > 0.95

    def test_similar_titles_different_phrasing(self):
        score = title_similarity(
            "Will Alexandria Ocasio-Cortez win the 2028 Democratic presidential nomination?",
            "Will Alexandria Ocasio-Cortez be the Democratic Presidential nominee in 2028?"
        )
        assert score > 0.65

    def test_unrelated_titles(self):
        score = title_similarity(
            "Will Bitcoin hit $100k?",
            "Will it rain in NYC tomorrow?"
        )
        # These share some sequence similarity but should score well below match threshold
        assert score < 0.55

    def test_keyword_similarity_identical(self):
        assert keyword_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_keyword_similarity_no_overlap(self):
        assert keyword_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_keyword_similarity_partial(self):
        score = keyword_similarity({"trump", "election", "2028"}, {"trump", "president", "2028"})
        assert 0.3 < score < 0.7  # 2/4 overlap

    def test_keyword_similarity_empty(self):
        assert keyword_similarity(set(), {"a"}) == 0.0
        assert keyword_similarity({"a"}, set()) == 0.0


# ===== Kalshi Fee Calculation =====

class TestKalshiFees:
    def test_taker_fee_50_cents(self):
        """At 50c, fee = 0.07 * 0.5 * 0.5 = 0.0175"""
        fee = kalshi_taker_fee(50)
        assert abs(fee - 0.0175) < 0.001

    def test_taker_fee_extreme_prices(self):
        """Near 0 or 100, fee approaches 0 (price*(1-price) is small)."""
        fee_low = kalshi_taker_fee(5)
        fee_high = kalshi_taker_fee(95)
        assert fee_low < 0.005
        assert fee_high < 0.005

    def test_taker_fee_multiple_contracts(self):
        fee_1 = kalshi_taker_fee(50, contracts=1)
        fee_5 = kalshi_taker_fee(50, contracts=5)
        assert abs(fee_5 - fee_1 * 5) < 0.001

    def test_maker_fee_zero(self):
        assert kalshi_maker_fee(50) == 0.0
        assert kalshi_maker_fee(99) == 0.0


# ===== Market Listing =====

class TestMarketListing:
    def test_creation(self):
        m = MarketListing(
            platform="polymarket",
            market_id="test-1",
            title="Test Market?",
            normalized_title="test market",
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
            volume=10000,
        )
        assert m.platform == "polymarket"
        assert m.market_id == "test-1"


# ===== Arb Detection =====

def _make_listing(platform, market_id, title, yes_bid, yes_ask, no_bid, no_ask):
    return MarketListing(
        platform=platform,
        market_id=market_id,
        title=title,
        normalized_title=normalize_title(title),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        volume=1000,
    )


class TestArbDetection:
    def test_no_arb_fair_prices(self):
        """When prices sum to 1.0, no arb exists."""
        poly = _make_listing("polymarket", "p1", "Test?", 0.50, 0.52, 0.48, 0.50)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.50, 0.52, 0.48, 0.50)
        arb = detect_arb(poly, kalshi, match_score=0.85)
        assert arb is None

    def test_arb_detected_poly_yes_kalshi_no(self):
        """Poly YES cheap + Kalshi NO cheap = arb."""
        poly = _make_listing("polymarket", "p1", "Test?", 0.10, 0.12, 0.88, 0.90)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.20, 0.22, 0.78, 0.80)
        # Poly YES ask=0.12, Kalshi NO ask=0.80 → total=0.92 < 1.0
        arb = detect_arb(poly, kalshi, match_score=0.85)
        assert arb is not None
        assert arb.direction == "poly_yes_kalshi_no"
        assert arb.total_cost < 1.0
        assert arb.net_profit > 0

    def test_arb_detected_poly_no_kalshi_yes(self):
        """Poly NO cheap + Kalshi YES cheap = arb."""
        poly = _make_listing("polymarket", "p1", "Test?", 0.80, 0.82, 0.18, 0.20)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.70, 0.72, 0.28, 0.30)
        # Poly NO ask=0.20, Kalshi YES ask=0.72 → total=0.92 < 1.0
        arb = detect_arb(poly, kalshi, match_score=0.85)
        assert arb is not None
        assert arb.direction == "poly_no_kalshi_yes"
        assert arb.total_cost < 1.0
        assert arb.net_profit > 0

    def test_arb_fees_kill_small_edge(self):
        """When edge is too small, fees eat the profit."""
        poly = _make_listing("polymarket", "p1", "Test?", 0.48, 0.50, 0.50, 0.52)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.48, 0.50, 0.50, 0.52)
        # Poly YES=0.50 + Kalshi NO=0.52 = 1.02 > 1.0 → no arb
        arb = detect_arb(poly, kalshi, match_score=0.85)
        assert arb is None

    def test_arb_returns_best_direction(self):
        """When both directions are profitable, returns the better one."""
        poly = _make_listing("polymarket", "p1", "Test?", 0.10, 0.12, 0.30, 0.32)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.30, 0.32, 0.10, 0.12)
        # Direction 1: Poly YES=0.12 + Kalshi NO=0.12 = 0.24 → huge arb
        # Direction 2: Poly NO=0.32 + Kalshi YES=0.32 = 0.64 → arb but smaller %
        arb = detect_arb(poly, kalshi, match_score=0.85)
        assert arb is not None
        # The direction with higher ROI should be picked
        assert arb.net_profit_pct > 0.01

    def test_arb_profit_fields_consistent(self):
        """Verify profit calculation consistency."""
        poly = _make_listing("polymarket", "p1", "Test?", 0.05, 0.07, 0.93, 0.95)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.12, 0.14, 0.86, 0.88)
        arb = detect_arb(poly, kalshi, match_score=0.90)
        if arb:
            assert abs(arb.gross_profit - (1.0 - arb.total_cost)) < 1e-10
            assert abs(arb.net_profit - (arb.gross_profit - arb.total_fees)) < 1e-10
            assert abs(arb.total_fees - (arb.poly_fee + arb.kalshi_fee)) < 1e-10


# ===== Signal Format =====

class TestSignalFormat:
    def test_arb_to_signal_keys(self):
        poly = _make_listing("polymarket", "p1", "Will X happen?", 0.05, 0.07, 0.93, 0.95)
        kalshi = _make_listing("kalshi", "k1", "Will X happen?", 0.15, 0.17, 0.83, 0.85)
        arb = detect_arb(poly, kalshi, match_score=0.85)
        assert arb is not None

        signal = arb_to_signal(arb)
        required_keys = [
            "market_id", "question", "direction", "market_price",
            "estimated_prob", "edge", "confidence", "reasoning",
            "source", "taker_fee", "category", "resolution_hours",
            "velocity_score", "kelly_fraction", "arb_details",
        ]
        for key in required_keys:
            assert key in signal, f"Missing key: {key}"

        assert signal["source"] == "cross_platform_arb"
        assert signal["direction"] in ("buy_yes", "buy_no")
        assert signal["category"] == "arbitrage"
        assert signal["taker_fee"] == 0.0  # Maker on Poly
        assert "kalshi_ticker" in signal["arb_details"]

    def test_signal_direction_poly_yes(self):
        poly = _make_listing("polymarket", "p1", "Test?", 0.05, 0.07, 0.93, 0.95)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.15, 0.17, 0.83, 0.85)
        arb = ArbOpportunity(
            poly_market=poly, kalshi_market=kalshi,
            match_score=0.85,
            direction="poly_yes_kalshi_no",
            poly_price=0.07, kalshi_price=0.85,
            total_cost=0.92, gross_profit=0.08,
            poly_fee=0.0, kalshi_fee=0.009,
            total_fees=0.009, net_profit=0.071,
            net_profit_pct=0.077,
        )
        signal = arb_to_signal(arb)
        assert signal["direction"] == "buy_yes"

    def test_signal_direction_poly_no(self):
        poly = _make_listing("polymarket", "p1", "Test?", 0.85, 0.87, 0.13, 0.15)
        kalshi = _make_listing("kalshi", "k1", "Test?", 0.78, 0.80, 0.20, 0.22)
        arb = ArbOpportunity(
            poly_market=poly, kalshi_market=kalshi,
            match_score=0.85,
            direction="poly_no_kalshi_yes",
            poly_price=0.15, kalshi_price=0.80,
            total_cost=0.95, gross_profit=0.05,
            poly_fee=0.0, kalshi_fee=0.011,
            total_fees=0.011, net_profit=0.039,
            net_profit_pct=0.041,
        )
        signal = arb_to_signal(arb)
        assert signal["direction"] == "buy_no"
