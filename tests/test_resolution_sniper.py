#!/usr/bin/env python3
"""
Tests for bot/resolution_sniper.py
===================================
All tests are fully offline — no external API calls.

Run with:
    pytest tests/test_resolution_sniper.py -v
"""

from __future__ import annotations

import math
import sys
import os
import importlib
import types

import pytest

# ---------------------------------------------------------------------------
# Import resolution_sniper regardless of package layout
# ---------------------------------------------------------------------------

def _import_module():
    """Import bot.resolution_sniper, falling back to direct path if needed."""
    try:
        from bot import resolution_sniper as m
        return m
    except ImportError:
        pass
    # Direct path fallback (script-style execution)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    bot_path = os.path.join(repo_root, "bot", "resolution_sniper.py")
    spec = importlib.util.spec_from_file_location("resolution_sniper", bot_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rs_mod = _import_module()

ResolutionSniper = rs_mod.ResolutionSniper
ResolutionTarget = rs_mod.ResolutionTarget
StaleQuote = rs_mod.StaleQuote
hours_until_resolution = rs_mod.hours_until_resolution
is_market_hours = rs_mod.is_market_hours


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sniper():
    """Default sniper instance with standard parameters."""
    return ResolutionSniper(
        min_confidence=0.90,
        min_profit_per_share=0.02,
        max_resolution_hours=48.0,
        dispute_risk_threshold=0.10,
        stale_edge_threshold=0.05,
    )


@pytest.fixture
def lenient_sniper():
    """Sniper with relaxed dispute threshold for testing dispute gate explicitly."""
    return ResolutionSniper(
        min_confidence=0.85,
        min_profit_per_share=0.01,
        max_resolution_hours=96.0,
        dispute_risk_threshold=0.50,  # very permissive
        stale_edge_threshold=0.05,
    )


# ---------------------------------------------------------------------------
# classify_resolution_state tests
# ---------------------------------------------------------------------------


class TestClassifyResolutionState:
    def test_effectively_resolved_yes(self, sniper):
        """Price 0.99 → effectively_resolved, outcome YES."""
        result = sniper.classify_resolution_state(yes_price=0.99, no_price=0.01)
        assert result["state"] == "effectively_resolved"
        assert result["expected_outcome"] == "YES"
        assert result["confidence"] >= 0.97

    def test_effectively_resolved_very_high(self, sniper):
        """Price 0.99 → effectively_resolved."""
        result = sniper.classify_resolution_state(yes_price=0.99, no_price=0.01)
        assert result["state"] == "effectively_resolved"
        assert result["confidence"] >= 0.98

    def test_effectively_resolved_no_side(self, sniper):
        """yes_price=0.01 → effectively_resolved, outcome NO."""
        result = sniper.classify_resolution_state(yes_price=0.01, no_price=0.99)
        assert result["state"] == "effectively_resolved"
        assert result["expected_outcome"] == "NO"

    def test_near_certain_yes(self, sniper):
        """Price 0.96 → near_certain."""
        result = sniper.classify_resolution_state(yes_price=0.96, no_price=0.04)
        assert result["state"] == "near_certain"
        assert result["expected_outcome"] == "YES"
        assert 0.90 <= result["confidence"] < 0.98

    def test_near_certain_low_boundary(self, sniper):
        """Price 0.945 → near_certain."""
        result = sniper.classify_resolution_state(yes_price=0.945, no_price=0.055)
        assert result["state"] == "near_certain"

    def test_leaning_yes(self, sniper):
        """Price 0.88 → leaning, outcome YES."""
        result = sniper.classify_resolution_state(yes_price=0.88, no_price=0.12)
        assert result["state"] == "leaning"
        assert result["expected_outcome"] == "YES"
        assert 0.70 <= result["confidence"] < 0.90

    def test_leaning_no_side(self, sniper):
        """yes_price=0.15 → leaning, outcome NO."""
        result = sniper.classify_resolution_state(yes_price=0.15, no_price=0.85)
        assert result["state"] == "leaning"
        assert result["expected_outcome"] == "NO"

    def test_pre_event_even(self, sniper):
        """Price 0.50 → pre_event."""
        result = sniper.classify_resolution_state(yes_price=0.50, no_price=0.50)
        assert result["state"] == "pre_event"
        assert result["expected_outcome"] in ("YES", "NO")

    def test_pre_event_slight_lean(self, sniper):
        """Price 0.60 → still pre_event (below 0.80 leaning threshold)."""
        result = sniper.classify_resolution_state(yes_price=0.60, no_price=0.40)
        assert result["state"] == "pre_event"

    def test_profit_if_correct_yes(self, sniper):
        """profit_if_correct = 1 - yes_price when outcome is YES."""
        result = sniper.classify_resolution_state(yes_price=0.95, no_price=0.05)
        assert result["expected_outcome"] == "YES"
        assert abs(result["profit_if_correct"] - 0.05) < 1e-6

    def test_profit_if_correct_no(self, sniper):
        """profit_if_correct = 1 - no_price when outcome is NO."""
        result = sniper.classify_resolution_state(yes_price=0.04, no_price=0.96)
        assert result["expected_outcome"] == "NO"
        assert abs(result["profit_if_correct"] - 0.04) < 1e-6

    def test_confidence_capped_at_0_99(self, sniper):
        """Confidence never exceeds 0.99."""
        result = sniper.classify_resolution_state(yes_price=1.0, no_price=0.0)
        assert result["confidence"] <= 0.99


# ---------------------------------------------------------------------------
# analyze_market tests
# ---------------------------------------------------------------------------


class TestAnalyzeMarket:
    def test_high_confidence_yes_returns_target(self, sniper):
        """yes_price=0.96 with clear resolution source → ResolutionTarget."""
        target = sniper.analyze_market(
            market_id="mkt-001",
            question="Did the Federal Reserve raise rates in March 2026?",
            yes_price=0.96,
            no_price=0.04,
            resolution_source="federal reserve official statement",
            market_metadata={"volume_24h": 10000, "resolution_eta_hours": 12.0},
        )
        assert target is not None
        assert isinstance(target, ResolutionTarget)
        assert target.expected_outcome == "YES"
        assert target.confidence >= 0.90
        assert target.expected_profit_per_share > 0.02

    def test_pre_event_returns_none(self, sniper):
        """yes_price=0.50 → None (market not resolved)."""
        target = sniper.analyze_market(
            market_id="mkt-002",
            question="Will BTC reach $100k in Q2 2026?",
            yes_price=0.50,
            no_price=0.50,
        )
        assert target is None

    def test_leaning_price_returns_none(self, sniper):
        """yes_price=0.85 → None (below near_certain threshold)."""
        target = sniper.analyze_market(
            market_id="mkt-003",
            question="Will the EU raise tariffs?",
            yes_price=0.85,
            no_price=0.15,
        )
        assert target is None

    def test_near_certain_yes_accepted(self, sniper):
        """yes_price=0.95 with non-controversial question → target found."""
        target = sniper.analyze_market(
            market_id="mkt-004",
            question="Did SpaceX launch Starship in March 2026?",
            yes_price=0.95,
            no_price=0.05,
            resolution_source="spacex.com official press release",
            market_metadata={"resolution_eta_hours": 8.0, "volume_24h": 5000},
        )
        assert target is not None
        assert target.market_id == "mkt-004"

    def test_high_dispute_risk_rejected(self, sniper):
        """Politically charged + no source + subjective criteria → rejected."""
        # This question will score high on dispute risk:
        # political keywords + no source + subjective keywords
        target = sniper.analyze_market(
            market_id="mkt-005",
            question="Did Trump primarily win the election largely through conservative voters?",
            yes_price=0.97,
            no_price=0.03,
            resolution_source="",  # no source → +0.10
        )
        # With dispute_risk_threshold=0.10, this should be rejected
        assert target is None

    def test_eta_too_long_rejected(self, sniper):
        """resolution_eta_hours > 48 → rejected."""
        target = sniper.analyze_market(
            market_id="mkt-006",
            question="Will interest rates rise in 2026?",
            yes_price=0.97,
            no_price=0.03,
            resolution_source="federal reserve",
            market_metadata={"resolution_eta_hours": 72.0},
        )
        assert target is None

    def test_insufficient_profit_rejected(self):
        """min_profit_per_share=0.10 — yes_price=0.95 profit=0.05 → rejected."""
        strict_sniper = ResolutionSniper(
            min_confidence=0.85,
            min_profit_per_share=0.10,  # 10 cents minimum
            max_resolution_hours=48.0,
            dispute_risk_threshold=0.50,
        )
        target = strict_sniper.analyze_market(
            market_id="mkt-007",
            question="Did the court rule in favour of plaintiff?",
            yes_price=0.95,
            no_price=0.05,
            resolution_source="court docket",
            market_metadata={"resolution_eta_hours": 6.0},
        )
        assert target is None

    def test_no_outcome_target(self, lenient_sniper):
        """yes_price=0.03 → expected_outcome=NO, positive profit."""
        target = lenient_sniper.analyze_market(
            market_id="mkt-008",
            question="Will the ETH merge happen in January 2026?",
            yes_price=0.03,
            no_price=0.97,
            resolution_source="coinbase price feed",
            market_metadata={"resolution_eta_hours": 10.0},
        )
        assert target is not None
        assert target.expected_outcome == "NO"
        assert target.expected_profit_per_share > 0

    def test_risk_factors_populated(self, lenient_sniper):
        """Risk factors list is populated when dispute risk is elevated."""
        target = lenient_sniper.analyze_market(
            market_id="mkt-009",
            question="Did the Federal Reserve raise rates?",
            yes_price=0.97,
            no_price=0.03,
            resolution_source="",  # no source adds "resolution_source_unknown"
            market_metadata={"resolution_eta_hours": 6.0},
        )
        assert target is not None
        assert "resolution_source_unknown" in target.risk_factors

    def test_metadata_volume_propagated(self, sniper):
        """volume_24h from metadata is propagated into ResolutionTarget."""
        target = sniper.analyze_market(
            market_id="mkt-010",
            question="Did SpaceX land Starship successfully?",
            yes_price=0.97,
            no_price=0.03,
            resolution_source="spacex.com",
            market_metadata={"volume_24h": 99999.0, "resolution_eta_hours": 5.0},
        )
        assert target is not None
        assert target.volume_24h == 99999.0


# ---------------------------------------------------------------------------
# detect_stale_quotes tests
# ---------------------------------------------------------------------------


class TestDetectStaleQuotes:
    def test_stale_ask_detected(self, sniper):
        """Ask at 0.30 when fair price is 0.95 → stale quote detected."""
        order_book = {
            "bids": [{"price": 0.90, "size": 10.0}],
            "asks": [{"price": 0.30, "size": 50.0}],  # way below fair
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-001",
            question="Will the Fed raise rates?",
            order_book=order_book,
            fair_price_estimate=0.95,
        )
        assert len(quotes) >= 1
        stale = quotes[0]
        assert isinstance(stale, StaleQuote)
        assert stale.side == "YES"
        assert stale.stale_price == pytest.approx(0.30, abs=1e-6)
        assert stale.fair_price == pytest.approx(0.95, abs=1e-6)
        assert stale.edge == pytest.approx(0.65, abs=1e-4)
        assert stale.likely_reason == "pre_news_quote"  # gap >= 0.30

    def test_no_stale_quotes_near_fair(self, sniper):
        """All quotes close to fair price → no stale quotes."""
        order_book = {
            "bids": [{"price": 0.92, "size": 20.0}],
            "asks": [{"price": 0.94, "size": 15.0}],
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-002",
            question="Will SpaceX launch?",
            order_book=order_book,
            fair_price_estimate=0.93,
        )
        assert len(quotes) == 0

    def test_stale_bid_above_fair(self, sniper):
        """Bid at 0.98 when fair is 0.20 → stale bid (someone over-paying)."""
        order_book = {
            "bids": [{"price": 0.98, "size": 100.0}],
            "asks": [],
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-003",
            question="Will Bitcoin hit $50k?",
            order_book=order_book,
            fair_price_estimate=0.20,
        )
        assert len(quotes) >= 1
        assert quotes[0].edge >= 0.05

    def test_thin_book_reason(self, sniper):
        """Ask 0.08 above fair → thin_book reason (gap < 0.15)."""
        order_book = {
            "bids": [],
            "asks": [{"price": 0.80, "size": 5.0}],
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-004",
            question="Will GDP grow?",
            order_book=order_book,
            fair_price_estimate=0.87,
        )
        assert len(quotes) >= 1
        assert quotes[0].likely_reason == "thin_book"

    def test_bot_malfunction_reason(self, sniper):
        """Ask 0.20 below fair → bot_malfunction reason (0.15 <= gap < 0.30)."""
        order_book = {
            "bids": [],
            "asks": [{"price": 0.70, "size": 20.0}],
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-005",
            question="Will inflation exceed 3%?",
            order_book=order_book,
            fair_price_estimate=0.90,
        )
        assert len(quotes) >= 1
        assert quotes[0].likely_reason == "bot_malfunction"

    def test_empty_order_book(self, sniper):
        """Empty order book → no stale quotes."""
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-006",
            question="Empty book?",
            order_book={"bids": [], "asks": []},
            fair_price_estimate=0.95,
        )
        assert quotes == []

    def test_tiny_size_ignored(self, sniper):
        """Orders below minimum size are ignored."""
        order_book = {
            "bids": [],
            "asks": [{"price": 0.10, "size": 0.5}],  # tiny — below _MIN_STALE_SIZE=1.0
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-007",
            question="Tiny order?",
            order_book=order_book,
            fair_price_estimate=0.95,
        )
        assert len(quotes) == 0

    def test_multiple_stale_asks(self, sniper):
        """Multiple stale asks at different levels all detected."""
        order_book = {
            "bids": [],
            "asks": [
                {"price": 0.20, "size": 100.0},
                {"price": 0.30, "size": 50.0},
                {"price": 0.91, "size": 10.0},  # not stale (within 0.04 of fair)
            ],
        }
        quotes = sniper.detect_stale_quotes(
            market_id="mkt-stale-008",
            question="Multiple stale levels?",
            order_book=order_book,
            fair_price_estimate=0.95,
        )
        # 0.20 and 0.30 are stale (edge 0.75 and 0.65); 0.91 is not (edge 0.04 < 0.05)
        assert len(quotes) == 2


# ---------------------------------------------------------------------------
# estimate_dispute_risk tests
# ---------------------------------------------------------------------------


class TestEstimateDisputeRisk:
    def test_politically_charged_no_source(self, sniper):
        """Political keywords + no source → high dispute risk."""
        risk = sniper.estimate_dispute_risk(
            question="Did Trump win the election through conservative voters?",
            yes_price=0.95,
            resolution_source="",
        )
        # Base 0.02 + political 0.05 + no source 0.10 + possible subjective boost
        assert risk >= 0.15

    def test_clear_source_non_controversial(self, sniper):
        """Non-controversial question + clear official source → low risk."""
        risk = sniper.estimate_dispute_risk(
            question="Did the Federal Reserve announce a rate decision on March 20?",
            yes_price=0.97,
            resolution_source="federal reserve official statement",
        )
        # Base 0.02 only (no political, no subjective, source present, no UMA)
        assert risk < 0.10

    def test_uma_oracle_boosts_risk(self, sniper):
        """UMA oracle mention adds 0.05."""
        risk_base = sniper.estimate_dispute_risk(
            question="Will ETH price rise?",
            yes_price=0.90,
            resolution_source="coinbase",
        )
        risk_uma = sniper.estimate_dispute_risk(
            question="Will ETH price rise?",
            yes_price=0.90,
            resolution_source="uma oracle",
        )
        assert risk_uma - risk_base == pytest.approx(0.05, abs=1e-6)

    def test_subjective_criteria_boost(self, sniper):
        """Subjective wording adds 0.10."""
        risk = sniper.estimate_dispute_risk(
            question="Will inflation primarily remain below 3%?",
            yes_price=0.90,
            resolution_source="bls official stats",
        )
        # subjective keyword "primarily" → +0.10
        assert risk >= 0.10

    def test_risk_capped_at_1(self, sniper):
        """Dispute risk never exceeds 1.0."""
        risk = sniper.estimate_dispute_risk(
            question=(
                "Did Trump primarily win the election largely through "
                "conservative Republican voters approximately?"
            ),
            yes_price=0.88,
            resolution_source="",
        )
        assert risk <= 1.0

    def test_risk_non_negative(self, sniper):
        """Dispute risk is always non-negative."""
        risk = sniper.estimate_dispute_risk("Simple question?", 0.99, "official source")
        assert risk >= 0.0


# ---------------------------------------------------------------------------
# calculate_expected_value tests
# ---------------------------------------------------------------------------


class TestCalculateExpectedValue:
    def _make_target(self, confidence, yes_price, no_price, outcome, profit, eta_hours):
        return ResolutionTarget(
            market_id="ev-test",
            question="Test question",
            current_yes_price=yes_price,
            current_no_price=no_price,
            expected_outcome=outcome,
            confidence=confidence,
            evidence="test",
            expected_profit_per_share=profit,
            resolution_eta_hours=eta_hours,
            volume_24h=1000.0,
        )

    def test_high_confidence_positive_ev(self, sniper):
        """0.99 confidence, 5c profit, 12h eta → positive EV."""
        target = self._make_target(
            confidence=0.99, yes_price=0.95, no_price=0.05,
            outcome="YES", profit=0.05, eta_hours=12.0
        )
        ev = sniper.calculate_expected_value(target)
        assert ev > 0.0

    def test_low_confidence_negative_ev(self, sniper):
        """0.50 confidence, tiny profit → negative EV."""
        target = self._make_target(
            confidence=0.50, yes_price=0.95, no_price=0.05,
            outcome="YES", profit=0.05, eta_hours=24.0
        )
        ev = sniper.calculate_expected_value(target)
        assert ev < 0.0

    def test_ev_formula_exact(self, sniper):
        """Verify EV formula with exact values."""
        c = 0.95
        profit = 0.05
        yes_price = 0.95
        purchase_price = yes_price
        loss = purchase_price
        eta = 24.0
        time_cost = purchase_price * 0.05 * eta / 8760.0
        expected_ev = c * profit - (1.0 - c) * loss - time_cost

        target = self._make_target(
            confidence=c, yes_price=yes_price, no_price=0.05,
            outcome="YES", profit=profit, eta_hours=eta
        )
        ev = sniper.calculate_expected_value(target)
        assert ev == pytest.approx(expected_ev, abs=1e-8)

    def test_ev_no_outcome_uses_no_price(self, sniper):
        """For NO outcome, purchase price is no_price."""
        target = self._make_target(
            confidence=0.97, yes_price=0.05, no_price=0.95,
            outcome="NO", profit=0.05, eta_hours=6.0
        )
        ev = sniper.calculate_expected_value(target)
        # Manual: 0.97*0.05 - 0.03*0.95 - 0.95*0.05*6/8760
        manual = 0.97 * 0.05 - 0.03 * 0.95 - 0.95 * 0.05 * 6 / 8760
        assert ev == pytest.approx(manual, abs=1e-8)

    def test_ev_decreases_with_longer_wait(self, sniper):
        """Longer resolution wait reduces EV due to time cost."""
        target_short = self._make_target(
            confidence=0.95, yes_price=0.95, no_price=0.05,
            outcome="YES", profit=0.05, eta_hours=1.0
        )
        target_long = self._make_target(
            confidence=0.95, yes_price=0.95, no_price=0.05,
            outcome="YES", profit=0.05, eta_hours=48.0
        )
        ev_short = sniper.calculate_expected_value(target_short)
        ev_long = sniper.calculate_expected_value(target_long)
        assert ev_short > ev_long


# ---------------------------------------------------------------------------
# scan_markets tests
# ---------------------------------------------------------------------------


class TestScanMarkets:
    def _market(self, mid, question, yes_price, no_price,
                source="official source", eta=12.0, volume=1000.0):
        return {
            "market_id": mid,
            "question": question,
            "yes_price": yes_price,
            "no_price": no_price,
            "resolution_source": source,
            "resolution_eta_hours": eta,
            "volume_24h": volume,
        }

    def test_filters_below_confidence(self, sniper):
        """Markets below confidence threshold are excluded."""
        markets = [
            self._market("a", "Will SpaceX launch?", 0.50, 0.50),  # pre_event
            self._market("b", "Did Fed raise rates?", 0.97, 0.03),  # passes
        ]
        results = sniper.scan_markets(markets)
        ids = [r.market_id for r in results]
        assert "a" not in ids
        assert "b" in ids

    def test_filters_by_profit_threshold(self):
        """Markets with insufficient profit are excluded."""
        strict = ResolutionSniper(
            min_confidence=0.85,
            min_profit_per_share=0.10,  # 10c minimum
            dispute_risk_threshold=0.50,
            max_resolution_hours=48.0,
        )
        markets = [
            {
                "market_id": "low-profit",
                "question": "Did Coinbase list a new token?",
                "yes_price": 0.97,  # only 3c profit
                "no_price": 0.03,
                "resolution_source": "coinbase",
                "resolution_eta_hours": 6.0,
            }
        ]
        results = strict.scan_markets(markets)
        assert len(results) == 0

    def test_sorted_by_ev_descending(self, sniper):
        """Results are sorted by EV descending."""
        markets = [
            # Lower EV: 0.95 yes (5c profit, lower confidence)
            self._market("low-ev", "Did SpaceX launch?", 0.95, 0.05, eta=40.0),
            # Higher EV: 0.99 yes (1c profit but very high confidence, short wait)
            self._market("high-ev", "Did Fed raise rates?", 0.99, 0.01, eta=2.0),
        ]
        results = sniper.scan_markets(markets)
        if len(results) >= 2:
            evs = [sniper.calculate_expected_value(r) for r in results]
            assert evs[0] >= evs[1]

    def test_empty_market_list(self, sniper):
        """Empty list → empty results."""
        assert sniper.scan_markets([]) == []

    def test_all_rejected_returns_empty(self, sniper):
        """All pre-event markets → empty."""
        markets = [
            self._market(f"m{i}", f"Question {i}?", 0.50, 0.50)
            for i in range(5)
        ]
        assert sniper.scan_markets(markets) == []

    def test_multiple_opportunities_returned(self, sniper):
        """Multiple valid markets → all returned."""
        markets = [
            self._market("a", "Did Fed raise rates?", 0.97, 0.03, eta=8.0),
            self._market("b", "Did SpaceX launch?", 0.98, 0.02, eta=4.0),
            self._market("c", "Will BTC hit 100k?", 0.55, 0.45),  # filtered out
        ]
        results = sniper.scan_markets(markets)
        ids = {r.market_id for r in results}
        assert "a" in ids
        assert "b" in ids
        assert "c" not in ids


# ---------------------------------------------------------------------------
# format_alert tests
# ---------------------------------------------------------------------------


class TestFormatAlert:
    def _sample_target(self):
        return ResolutionTarget(
            market_id="alert-001",
            question="Did the Federal Reserve raise rates in March 2026?",
            current_yes_price=0.97,
            current_no_price=0.03,
            expected_outcome="YES",
            confidence=0.97,
            evidence="Price 0.970 > 0.98 — market effectively resolved",
            expected_profit_per_share=0.03,
            resolution_eta_hours=12.0,
            volume_24h=50000.0,
            risk_factors=["dispute_possible"],
        )

    def test_format_alert_contains_market_id(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert "alert-001" in alert

    def test_format_alert_contains_outcome(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert "YES" in alert

    def test_format_alert_contains_confidence(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert "97.0%" in alert

    def test_format_alert_contains_risk_factors(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert "dispute_possible" in alert

    def test_format_alert_no_risk_factors_message(self, sniper):
        target = self._sample_target()
        target.risk_factors = []
        alert = sniper.format_alert(target)
        assert "none flagged" in alert

    def test_format_alert_contains_eta(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert "12.0h" in alert

    def test_format_alert_contains_evidence(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert "Price" in alert or "effectively" in alert

    def test_format_alert_is_string(self, sniper):
        target = self._sample_target()
        alert = sniper.format_alert(target)
        assert isinstance(alert, str)
        assert len(alert) > 50


# ---------------------------------------------------------------------------
# hours_until_resolution tests
# ---------------------------------------------------------------------------


class TestHoursUntilResolution:
    def test_future_date_iso(self):
        """ISO 8601 future date returns positive hours."""
        from datetime import datetime, timezone, timedelta
        future = datetime.now(tz=timezone.utc) + timedelta(hours=24)
        date_str = future.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        hours = hours_until_resolution(date_str)
        assert 23.0 <= hours <= 25.0

    def test_past_date_returns_zero(self):
        """Past date returns 0.0."""
        hours = hours_until_resolution("2020-01-01T00:00:00+00:00")
        assert hours == 0.0

    def test_z_suffix_accepted(self):
        """ISO date with Z suffix is accepted."""
        from datetime import datetime, timezone, timedelta
        future = datetime.now(tz=timezone.utc) + timedelta(hours=12)
        date_str = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        hours = hours_until_resolution(date_str)
        assert hours > 0.0

    def test_date_only_string(self):
        """Date-only string (YYYY-MM-DD far in future) returns positive hours."""
        hours = hours_until_resolution("2099-12-31")
        assert hours > 0.0

    def test_empty_string_returns_zero(self):
        """Empty string → 0.0."""
        assert hours_until_resolution("") == 0.0

    def test_invalid_string_returns_zero(self):
        """Invalid string → 0.0."""
        assert hours_until_resolution("not-a-date") == 0.0

    def test_spaced_datetime(self):
        """Space-separated datetime is handled."""
        from datetime import datetime, timezone, timedelta
        future = datetime.now(tz=timezone.utc) + timedelta(hours=6)
        date_str = future.strftime("%Y-%m-%d %H:%M:%S")
        hours = hours_until_resolution(date_str)
        assert hours > 0.0


# ---------------------------------------------------------------------------
# is_market_hours tests
# ---------------------------------------------------------------------------


class TestIsMarketHours:
    def test_midday_utc_is_market_hours(self):
        assert is_market_hours(12) is True

    def test_9_utc_boundary_included(self):
        assert is_market_hours(9) is True

    def test_17_utc_boundary_included(self):
        assert is_market_hours(17) is True

    def test_midnight_not_market_hours(self):
        assert is_market_hours(0) is False

    def test_3am_not_market_hours(self):
        assert is_market_hours(3) is False

    def test_18_utc_not_market_hours(self):
        assert is_market_hours(18) is False


# ---------------------------------------------------------------------------
# Integration smoke test
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_scan_pipeline(self):
        """End-to-end scan from market list to formatted alerts."""
        sniper = ResolutionSniper(
            min_confidence=0.90,
            min_profit_per_share=0.02,
            max_resolution_hours=24.0,
            dispute_risk_threshold=0.20,
        )
        markets = [
            {
                "market_id": "integ-001",
                "question": "Did the Federal Reserve announce a rate hike on March 20, 2026?",
                "yes_price": 0.97,
                "no_price": 0.03,
                "resolution_source": "federal reserve official press release",
                "resolution_eta_hours": 6.0,
                "volume_24h": 75000.0,
            },
            {
                "market_id": "integ-002",
                "question": "Will BTC reach $200k in 2026?",
                "yes_price": 0.40,
                "no_price": 0.60,
                "resolution_source": "coinbase",
                "resolution_eta_hours": 100.0,
                "volume_24h": 10000.0,
            },
        ]
        results = sniper.scan_markets(markets)
        assert len(results) == 1
        assert results[0].market_id == "integ-001"

        alert = sniper.format_alert(results[0])
        assert "integ-001" in alert
        assert "YES" in alert
        assert isinstance(alert, str)

    def test_stale_quote_and_resolution_combined(self):
        """Stale quote detection works alongside resolution sniping."""
        sniper = ResolutionSniper(stale_edge_threshold=0.05)

        # Known-outcome market
        target = sniper.analyze_market(
            market_id="combo-001",
            question="Did SpaceX land Starship on March 21, 2026?",
            yes_price=0.97,
            no_price=0.03,
            resolution_source="spacex official statement",
            market_metadata={"resolution_eta_hours": 4.0, "volume_24h": 30000},
        )
        assert target is not None

        # Stale quote on same market (book not yet updated)
        order_book = {
            "bids": [{"price": 0.55, "size": 200.0}],  # stale pre-news bid
            "asks": [{"price": 0.60, "size": 100.0}],  # stale pre-news ask
        }
        stale = sniper.detect_stale_quotes(
            market_id="combo-001",
            question="Did SpaceX land Starship on March 21, 2026?",
            order_book=order_book,
            fair_price_estimate=0.97,
        )
        # Both bid and ask are stale (ask 0.60 vs fair 0.97 → edge 0.37)
        assert len(stale) >= 1
        edges = [q.edge for q in stale]
        assert all(e >= 0.05 for e in edges)
