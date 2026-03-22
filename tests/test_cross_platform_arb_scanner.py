"""
Tests for bot/cross_platform_arb_scanner.py

Run:
    pytest tests/test_cross_platform_arb_scanner.py -v
"""

import asyncio
import math
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path fixup so tests can be run from any working directory
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.cross_platform_arb_scanner import (
    CrossPlatformArbScanner,
    CrossPlatformOpportunity,
    MatchedPair,
    PlatformMarket,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _scanner(**kwargs) -> CrossPlatformArbScanner:
    """Build a scanner with test-friendly defaults."""
    defaults = dict(
        min_profit_pct=0.02,
        min_similarity=0.6,
        polymarket_taker_fee=0.015,
        kalshi_taker_fee=0.012,
    )
    defaults.update(kwargs)
    return CrossPlatformArbScanner(**defaults)


def _pm(
    market_id: str = "pm-1",
    question: str = "Will Bitcoin exceed $100k by March 31?",
    yes_price: float = 0.55,
    no_price: float = 0.45,
    resolution_source: str = "CoinGecko",
    resolution_date: str = "2026-03-31",
    volume_24h: float = 50_000.0,
) -> PlatformMarket:
    return PlatformMarket(
        platform="polymarket",
        market_id=market_id,
        question=question,
        yes_price=yes_price,
        no_price=no_price,
        volume_24h=volume_24h,
        resolution_source=resolution_source,
        resolution_date=resolution_date,
        fees={"taker_fee": 0.015, "maker_fee": 0.0},
    )


def _km(
    market_id: str = "km-1",
    question: str = "Will Bitcoin exceed $100,000 by March 31?",
    yes_price: float = 0.58,
    no_price: float = 0.42,
    resolution_source: str = "CoinGecko",
    resolution_date: str = "2026-03-31",
    volume_24h: float = 20_000.0,
) -> PlatformMarket:
    return PlatformMarket(
        platform="kalshi",
        market_id=market_id,
        question=question,
        yes_price=yes_price,
        no_price=no_price,
        volume_24h=volume_24h,
        resolution_source=resolution_source,
        resolution_date=resolution_date,
        fees={"taker_fee": 0.012, "maker_fee": 0.0},
    )


# ---------------------------------------------------------------------------
# 1. Question normalisation
# ---------------------------------------------------------------------------

class TestNormalizeQuestion:
    def setup_method(self):
        self.scanner = _scanner()

    def test_lowercase(self):
        result = self.scanner._normalize_question("Will Bitcoin EXCEED $100k?")
        assert result == result.lower()

    def test_removes_punctuation(self):
        result = self.scanner._normalize_question("Will it rain? (source: NWS).")
        assert "?" not in result
        assert "." not in result
        assert "(" not in result

    def test_normalises_currency_k(self):
        result = self.scanner._normalize_question("Will Bitcoin exceed $100k?")
        assert "100000" in result

    def test_normalises_currency_m(self):
        result = self.scanner._normalize_question("GDP above $1.5m?")
        assert "1500000" in result

    def test_normalises_date_written_month(self):
        result = self.scanner._normalize_question("Will it happen by March 31?")
        assert "2026-03-31" in result

    def test_normalises_date_with_year(self):
        result = self.scanner._normalize_question("By March 31, 2026?")
        assert "2026-03-31" in result

    def test_normalises_date_numeric(self):
        result = self.scanner._normalize_question("Before 3/31/2026?")
        assert "2026-03-31" in result

    def test_collapses_whitespace(self):
        result = self.scanner._normalize_question("Will   Bitcoin    hit $100k  ?")
        assert "  " not in result

    def test_strips_kalshi_prefix(self):
        result = self.scanner._normalize_question("Kalshi: Will Bitcoin exceed $100k?")
        assert not result.startswith("kalshi")

    def test_strips_polymarket_prefix(self):
        result = self.scanner._normalize_question("Polymarket | Will Bitcoin exceed $100k?")
        assert not result.startswith("polymarket")

    def test_empty_string(self):
        result = self.scanner._normalize_question("")
        assert result == ""

    def test_whitespace_only(self):
        result = self.scanner._normalize_question("   ")
        assert result.strip() == ""


# ---------------------------------------------------------------------------
# 2. Similarity computation
# ---------------------------------------------------------------------------

class TestComputeSimilarity:
    def setup_method(self):
        self.scanner = _scanner()
        self._n = self.scanner._normalize_question

    def test_identical_questions_score_one(self):
        q = self._n("Will Bitcoin exceed $100,000 by March 31, 2026?")
        score = self.scanner._compute_similarity(q, q)
        assert abs(score - 1.0) < 1e-6

    def test_near_identical_questions_high_score(self):
        q1 = self._n("Will Bitcoin exceed $100k by March 31?")
        q2 = self._n("Will Bitcoin exceed $100,000 by March 31?")
        score = self.scanner._compute_similarity(q1, q2)
        assert score >= 0.7, f"Expected ≥0.7, got {score:.4f}"

    def test_completely_different_questions_low_score(self):
        q1 = self._n("Will Bitcoin exceed $100k by March 31?")
        q2 = self._n("Will the Democrats win the 2026 midterms?")
        score = self.scanner._compute_similarity(q1, q2)
        assert score < 0.3, f"Expected <0.3, got {score:.4f}"

    def test_partially_related_questions_medium_score(self):
        q1 = self._n("Will Ethereum exceed $5000 by June 30?")
        q2 = self._n("Will Bitcoin exceed $100k by March 31?")
        score = self.scanner._compute_similarity(q1, q2)
        assert 0.1 < score < 0.8, f"Expected medium score, got {score:.4f}"

    def test_empty_question_returns_zero(self):
        q1 = self._n("Will Bitcoin exceed $100k?")
        q2 = ""
        score = self.scanner._compute_similarity(q1, q2)
        assert score == 0.0

    def test_symmetry(self):
        q1 = self._n("Will Bitcoin exceed $100k by March 31?")
        q2 = self._n("Will Bitcoin hit $100,000 before March 31?")
        assert abs(
            self.scanner._compute_similarity(q1, q2) -
            self.scanner._compute_similarity(q2, q1)
        ) < 1e-9

    def test_score_bounded_zero_to_one(self):
        pairs = [
            ("bitcoin price above 100k", "ethereum price above 5000"),
            ("will trump win 2026", "will biden resign"),
            ("rain today", "rain today"),
        ]
        for a, b in pairs:
            score = self.scanner._compute_similarity(a, b)
            assert 0.0 <= score <= 1.0, f"Score out of bounds: {score}"


# ---------------------------------------------------------------------------
# 3. Market matching
# ---------------------------------------------------------------------------

class TestMatchMarkets:
    def setup_method(self):
        self.scanner = _scanner(min_similarity=0.5)

    def _make_markets(self):
        """5 Polymarket + 5 Kalshi with 2 obvious matches."""
        poly = [
            _pm("pm-1", "Will Bitcoin exceed $100k by March 31?"),
            _pm("pm-2", "Will Trump sign the tax bill in 2026?"),
            _pm("pm-3", "Will the Fed cut rates in March 2026?"),
            _pm("pm-4", "Will SpaceX land on Mars by 2030?"),
            _pm("pm-5", "Will Ethereum exceed $5000 by June 2026?"),
        ]
        kal = [
            _km("km-1", "Will Bitcoin exceed $100,000 before March 31?"),
            _km("km-2", "Will the Fed lower interest rates at the March 2026 meeting?"),
            _km("km-3", "Will Elon Musk resign from DOGE by April 2026?"),
            _km("km-4", "Will Spain win the 2026 World Cup?"),
            _km("km-5", "Will Ethereum hit $5000 by June 30, 2026?"),
        ]
        return poly, kal

    def test_finds_two_obvious_matches(self):
        poly, kal = self._make_markets()
        pairs = self.scanner.match_markets(poly, kal)
        matched_poly_ids = {p.polymarket.market_id for p in pairs}
        matched_kal_ids  = {p.kalshi.market_id    for p in pairs}
        # Bitcoin match
        assert "pm-1" in matched_poly_ids
        assert "km-1" in matched_kal_ids
        # Fed match
        assert "pm-3" in matched_poly_ids
        assert "km-2" in matched_kal_ids

    def test_no_false_match_on_completely_different_events(self):
        poly = [_pm("pm-4", "Will SpaceX land on Mars by 2030?")]
        kal  = [_km("km-4", "Will Spain win the 2026 World Cup?")]
        pairs = self.scanner.match_markets(poly, kal)
        assert len(pairs) == 0, "Different events should not match"

    def test_market_on_only_one_platform_returns_no_match(self):
        poly = [_pm("pm-1", "Will Bitcoin exceed $100k by March 31?")]
        kal  = []
        pairs = self.scanner.match_markets(poly, kal)
        assert len(pairs) == 0

    def test_each_market_used_at_most_once(self):
        # Two Polymarket clones matched to one Kalshi market — only one pair
        q_btc = "Will Bitcoin exceed $100k by March 31?"
        poly = [
            _pm("pm-1", q_btc),
            _pm("pm-2", q_btc),  # identical clone
        ]
        kal  = [_km("km-1", "Will Bitcoin exceed $100,000 before March 31?")]
        pairs = self.scanner.match_markets(poly, kal)
        kal_ids = [p.kalshi.market_id for p in pairs]
        assert kal_ids.count("km-1") <= 1, "Same Kalshi market matched twice"

    def test_pairs_sorted_by_similarity_descending(self):
        poly, kal = self._make_markets()
        pairs = self.scanner.match_markets(poly, kal)
        scores = [p.similarity_score for p in pairs]
        assert scores == sorted(scores, reverse=True)

    def test_resolution_match_flagged_correctly(self):
        poly = [_pm("pm-1", resolution_date="2026-03-31")]
        kal  = [_km("km-1", resolution_date="2026-03-31")]
        pairs = self.scanner.match_markets(poly, kal)
        assert len(pairs) == 1
        assert pairs[0].resolution_match is True

    def test_resolution_mismatch_flagged(self):
        poly = [_pm("pm-1", resolution_date="2026-03-31")]
        kal  = [_km("km-1", resolution_date="2026-05-01")]
        pairs = self.scanner.match_markets(poly, kal)
        # They may still match on text; just verify the flag is correct
        if pairs:
            assert pairs[0].resolution_match is False


# ---------------------------------------------------------------------------
# 4. Opportunity detection
# ---------------------------------------------------------------------------

class TestScanOpportunities:
    def setup_method(self):
        self.scanner = _scanner(min_profit_pct=0.02)

    def _make_pair(
        self,
        pm_yes: float,
        pm_no: float,
        km_yes: float,
        km_no: float,
        resolution_source: str = "CoinGecko",
    ) -> MatchedPair:
        poly = _pm(yes_price=pm_yes, no_price=pm_no, resolution_source=resolution_source)
        kal  = _km(yes_price=km_yes, no_price=km_no, resolution_source=resolution_source)
        pair = MatchedPair(
            polymarket=poly,
            kalshi=kal,
            similarity_score=0.9,
            resolution_match=True,
            resolution_risk="",
        )
        pair.resolution_risk = self.scanner.assess_resolution_risk(pair)
        return pair

    def test_detects_5pct_spread_opportunity(self):
        # YES on Polymarket @ 0.55, NO on Kalshi @ 0.38
        # gross = 0.93, fees ≈ 0.55*0.015 + 0.38*0.012 = 0.00825 + 0.00456 = 0.01281
        # net ≈ 0.9428, profit ≈ 5.8%
        pair = self._make_pair(pm_yes=0.55, pm_no=0.45, km_yes=0.60, km_no=0.38)
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        opp = opps[0]
        assert opp.net_profit > 0
        assert opp.profit_pct >= 0.02

    def test_rejects_1pct_spread_below_fee_threshold(self):
        # Very thin spread: gross = 0.99 → after fees still ~0.01 net, but
        # profit_pct = 0.01/0.99 ≈ 1%, below min_profit_pct=2%
        pair = self._make_pair(pm_yes=0.50, pm_no=0.49, km_yes=0.52, km_no=0.49)
        # best option: YES on PM @ 0.50, NO on Kalshi @ 0.49
        # gross = 0.99, fees = 0.50*0.015 + 0.49*0.012 = 0.0075+0.00588 = 0.01338
        # net = 0.99 + 0.01338 = 1.00338 → already ≥ 1.0, no opp
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 0

    def test_rejects_when_net_cost_exceeds_1(self):
        pair = self._make_pair(pm_yes=0.65, pm_no=0.40, km_yes=0.70, km_no=0.35)
        # best: YES on PM @ 0.65, NO on Kal @ 0.35, gross=1.00 → net>1
        opps = self.scanner.scan_opportunities([pair])
        # If net > 1.0 it should be rejected
        for opp in opps:
            assert opp.net_cost < 1.0

    def test_picks_best_direction(self):
        # Option A (PM YES, KAL NO): 0.55 + 0.38 = 0.93
        # Option B (KAL YES, PM NO): 0.60 + 0.45 = 1.05 → worse
        pair = self._make_pair(pm_yes=0.55, pm_no=0.45, km_yes=0.60, km_no=0.38)
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        opp = opps[0]
        assert opp.buy_yes_platform == "polymarket"
        assert opp.buy_no_platform  == "kalshi"
        assert abs(opp.yes_price - 0.55) < 1e-9
        assert abs(opp.no_price  - 0.38) < 1e-9

    def test_opportunities_sorted_by_profit_descending(self):
        pair_big   = self._make_pair(pm_yes=0.50, pm_no=0.45, km_yes=0.55, km_no=0.37)
        pair_small = self._make_pair(pm_yes=0.53, pm_no=0.45, km_yes=0.56, km_no=0.40)
        opps = self.scanner.scan_opportunities([pair_small, pair_big])
        if len(opps) >= 2:
            assert opps[0].profit_pct >= opps[1].profit_pct

    def test_empty_pairs_returns_empty_list(self):
        assert self.scanner.scan_opportunities([]) == []


# ---------------------------------------------------------------------------
# 5. Fee calculation
# ---------------------------------------------------------------------------

class TestFeeCalculation:
    def setup_method(self):
        self.scanner = _scanner(
            polymarket_taker_fee=0.015,
            kalshi_taker_fee=0.012,
        )

    def test_polymarket_fee_correct(self):
        fee = self.scanner._calc_fee("polymarket", 0.60)
        assert abs(fee - 0.60 * 0.015) < 1e-9

    def test_kalshi_fee_correct(self):
        fee = self.scanner._calc_fee("kalshi", 0.40)
        assert abs(fee - 0.40 * 0.012) < 1e-9

    def test_fees_conservative_taker_not_maker(self):
        # Taker fee should be >= maker fee (0.0 on Polymarket)
        poly_fee  = self.scanner._calc_fee("polymarket", 1.0)
        assert poly_fee >= 0.0  # taker > 0
        assert poly_fee == 0.015

    def test_total_fees_in_opportunity_correct(self):
        # YES on PM @ 0.55, NO on KAL @ 0.38
        # Expected fees: 0.55*0.015 + 0.38*0.012 = 0.00825 + 0.00456 = 0.01281
        pair = MatchedPair(
            polymarket=_pm(yes_price=0.55, no_price=0.45),
            kalshi=_km(yes_price=0.60, no_price=0.38),
            similarity_score=0.9,
            resolution_match=True,
            resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        expected_fees = 0.55 * 0.015 + 0.38 * 0.012
        assert abs(opps[0].total_fees - expected_fees) < 1e-9

    def test_net_cost_equals_gross_plus_fees(self):
        pair = MatchedPair(
            polymarket=_pm(yes_price=0.55, no_price=0.45),
            kalshi=_km(yes_price=0.60, no_price=0.38),
            similarity_score=0.9,
            resolution_match=True,
            resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        opp = opps[0]
        assert abs(opp.net_cost - (opp.gross_cost + opp.total_fees)) < 1e-9


# ---------------------------------------------------------------------------
# 6. Resolution risk assessment
# ---------------------------------------------------------------------------

class TestAssessResolutionRisk:
    def setup_method(self):
        self.scanner = _scanner()

    def _pair(
        self,
        pm_source: str = "CoinGecko",
        km_source: str = "CoinGecko",
        pm_date:   str = "2026-03-31",
        km_date:   str = "2026-03-31",
        pm_q:      str = "Will Bitcoin exceed $100k by March 31?",
        km_q:      str = "Will Bitcoin exceed $100,000 by March 31?",
    ) -> MatchedPair:
        return MatchedPair(
            polymarket=_pm(
                question=pm_q,
                resolution_source=pm_source,
                resolution_date=pm_date,
            ),
            kalshi=_km(
                question=km_q,
                resolution_source=km_source,
                resolution_date=km_date,
            ),
            similarity_score=0.9,
            resolution_match=(pm_date == km_date),
            resolution_risk="",
        )

    def test_same_source_same_date_is_low(self):
        pair = self._pair()
        risk = self.scanner.assess_resolution_risk(pair)
        assert risk == "LOW"

    def test_different_source_is_at_least_medium(self):
        pair = self._pair(pm_source="CoinGecko", km_source="Coinbase")
        risk = self.scanner.assess_resolution_risk(pair)
        assert risk in {"MEDIUM", "HIGH"}

    def test_different_dates_is_high(self):
        pair = self._pair(pm_date="2026-03-31", km_date="2026-05-01")
        risk = self.scanner.assess_resolution_risk(pair)
        assert risk == "HIGH"

    def test_by_vs_before_is_at_least_medium(self):
        pair = self._pair(
            pm_q="Will Bitcoin exceed $100k by March 31?",
            km_q="Will Bitcoin exceed $100k before March 31?",
        )
        risk = self.scanner.assess_resolution_risk(pair)
        assert risk in {"MEDIUM", "HIGH"}

    def test_risk_values_are_valid(self):
        valid = {"LOW", "MEDIUM", "HIGH"}
        for combo in [
            self._pair(),
            self._pair(pm_source="A", km_source="B"),
            self._pair(pm_date="2026-03-31", km_date="2026-05-01"),
        ]:
            assert self.scanner.assess_resolution_risk(combo) in valid


# ---------------------------------------------------------------------------
# 7. format_alert
# ---------------------------------------------------------------------------

class TestFormatAlert:
    def setup_method(self):
        self.scanner = _scanner()

    def _make_opp(self) -> CrossPlatformOpportunity:
        pair = MatchedPair(
            polymarket=_pm(yes_price=0.55, no_price=0.45),
            kalshi=_km(yes_price=0.60, no_price=0.38),
            similarity_score=0.9,
            resolution_match=True,
            resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert opps, "Setup failed: no opportunity generated"
        return opps[0]

    def test_alert_contains_profit_percentage(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp)
        assert "%" in alert

    def test_alert_mentions_both_platforms(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp).lower()
        assert "polymarket" in alert
        assert "kalshi" in alert

    def test_alert_contains_yes_buy_instruction(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp).lower()
        assert "buy yes" in alert

    def test_alert_contains_no_buy_instruction(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp).lower()
        assert "buy no" in alert

    def test_alert_contains_cost_line(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp)
        assert "Cost:" in alert

    def test_alert_contains_profit_line(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp)
        assert "Profit:" in alert

    def test_alert_contains_risk_line(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp)
        assert "Risk:" in alert

    def test_alert_is_readable_string(self):
        opp = self._make_opp()
        alert = self.scanner.format_alert(opp)
        assert isinstance(alert, str)
        assert len(alert) > 50


# ---------------------------------------------------------------------------
# 8. Realistic election market scenario
# ---------------------------------------------------------------------------

class TestElectionMarkets:
    def setup_method(self):
        self.scanner = _scanner(min_similarity=0.5, min_profit_pct=0.02)

    def test_us_election_markets_match(self):
        poly = [
            PlatformMarket(
                platform="polymarket",
                market_id="pm-election-1",
                question="Will the Democrats win the 2026 US House elections?",
                yes_price=0.45,
                no_price=0.55,
                volume_24h=200_000.0,
                resolution_source="AP",
                resolution_date="2026-11-04",
                fees={"taker_fee": 0.015, "maker_fee": 0.0},
            )
        ]
        kal = [
            PlatformMarket(
                platform="kalshi",
                market_id="km-election-1",
                question="Will Democrats win control of the House in 2026?",
                yes_price=0.47,
                no_price=0.53,
                volume_24h=80_000.0,
                resolution_source="AP",
                resolution_date="2026-11-04",
                fees={"taker_fee": 0.012, "maker_fee": 0.0},
            )
        ]
        pairs = self.scanner.match_markets(poly, kal)
        assert len(pairs) >= 1, "Election markets should match"

    def test_different_election_events_do_not_match(self):
        poly = [
            PlatformMarket(
                platform="polymarket",
                market_id="pm-1",
                question="Will Democrats win the 2026 US House elections?",
                yes_price=0.45, no_price=0.55, volume_24h=10_000.0,
                resolution_source="AP", resolution_date="2026-11-04",
                fees={},
            )
        ]
        kal = [
            PlatformMarket(
                platform="kalshi",
                market_id="km-1",
                question="Will the Fed raise interest rates in November 2026?",
                yes_price=0.30, no_price=0.70, volume_24h=5_000.0,
                resolution_source="Fed", resolution_date="2026-11-04",
                fees={},
            )
        ]
        pairs = self.scanner.match_markets(poly, kal)
        assert len(pairs) == 0, "Completely different events must not match"

    def test_election_arb_with_spread(self):
        """If same election priced differently enough, detect opportunity."""
        poly_market = PlatformMarket(
            platform="polymarket",
            market_id="pm-election-arb",
            question="Will Democrats win the 2026 US House elections?",
            yes_price=0.40,
            no_price=0.60,
            volume_24h=200_000.0,
            resolution_source="AP",
            resolution_date="2026-11-04",
            fees={"taker_fee": 0.015, "maker_fee": 0.0},
        )
        kal_market = PlatformMarket(
            platform="kalshi",
            market_id="km-election-arb",
            question="Will Democrats win control of the House in 2026?",
            yes_price=0.45,
            no_price=0.35,    # mispriced NO — arb: YES@0.40 + NO@0.35 = 0.75 gross
            volume_24h=80_000.0,
            resolution_source="AP",
            resolution_date="2026-11-04",
            fees={"taker_fee": 0.012, "maker_fee": 0.0},
        )
        pair = MatchedPair(
            polymarket=poly_market,
            kalshi=kal_market,
            similarity_score=0.85,
            resolution_match=True,
            resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        assert opps[0].profit_pct >= 0.02


# ---------------------------------------------------------------------------
# 9. historical_spread_analysis
# ---------------------------------------------------------------------------

class TestHistoricalSpreadAnalysis:
    def setup_method(self):
        self.scanner = _scanner()

    def _make_history(self, n: int = 100, spread_pct: float = 0.05) -> list[dict]:
        """Synthetic history where spread oscillates around spread_pct."""
        base_time = 1_000_000.0
        history = []
        for i in range(n):
            # Oscillate YES/NO prices so spread alternates above/below threshold
            amplitude = spread_pct * (1.0 if i % 2 == 0 else 0.5)
            history.append({
                "timestamp": base_time + i * 60.0,  # 1 min apart
                "poly_yes": 0.50 + amplitude / 2,
                "poly_no":  0.50 - amplitude / 2,
                "kalshi_yes": 0.55 - amplitude / 2,
                "kalshi_no":  0.40 - amplitude / 2,
            })
        return history

    def test_returns_all_required_keys(self):
        history = self._make_history(50)
        result = self.scanner.historical_spread_analysis(history)
        required = {
            "avg_spread", "max_spread", "min_spread",
            "volatility", "mean_reversion_time", "profitable_windows_per_day",
        }
        assert required <= set(result.keys())

    def test_empty_history_returns_zeros(self):
        result = self.scanner.historical_spread_analysis([])
        assert result["avg_spread"] == 0.0
        assert result["max_spread"] == 0.0
        assert result["profitable_windows_per_day"] == 0

    def test_max_spread_gte_avg_spread(self):
        history = self._make_history(100)
        result = self.scanner.historical_spread_analysis(history)
        assert result["max_spread"] >= result["avg_spread"]

    def test_min_spread_lte_avg_spread(self):
        history = self._make_history(100)
        result = self.scanner.historical_spread_analysis(history)
        assert result["min_spread"] <= result["avg_spread"]

    def test_volatility_non_negative(self):
        history = self._make_history(50)
        result = self.scanner.historical_spread_analysis(history)
        assert result["volatility"] >= 0.0

    def test_profitable_windows_count_is_non_negative(self):
        history = self._make_history(100)
        result = self.scanner.historical_spread_analysis(history)
        assert result["profitable_windows_per_day"] >= 0

    def test_constant_spread_zero_volatility(self):
        # All entries the same → zero std
        entry = {
            "timestamp": 1_000_000.0,
            "poly_yes": 0.55,
            "poly_no":  0.45,
            "kalshi_yes": 0.60,
            "kalshi_no":  0.38,
        }
        history = [dict(entry, timestamp=1_000_000.0 + i * 60) for i in range(20)]
        result = self.scanner.historical_spread_analysis(history)
        assert abs(result["volatility"]) < 1e-9

    def test_single_entry_history(self):
        history = [{"timestamp": 1_000_000.0, "poly_yes": 0.55, "poly_no": 0.45,
                    "kalshi_yes": 0.60, "kalshi_no": 0.38}]
        result = self.scanner.historical_spread_analysis(history)
        assert result["max_spread"] == result["min_spread"] == result["avg_spread"]


# ---------------------------------------------------------------------------
# 10. scan_all (async, with injected data)
# ---------------------------------------------------------------------------

class TestScanAll:
    def setup_method(self):
        self.scanner = _scanner(min_similarity=0.5, min_profit_pct=0.02)

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_scan_all_with_injected_arb(self):
        poly = [_pm("pm-1", yes_price=0.55, no_price=0.45)]
        kal  = [_km("km-1", yes_price=0.60, no_price=0.38)]
        opps = self._run(self.scanner.scan_all(
            polymarket_data=poly,
            kalshi_data=kal,
        ))
        assert len(opps) >= 1
        assert opps[0].profit_pct >= 0.02

    def test_scan_all_no_data_returns_empty(self):
        opps = self._run(self.scanner.scan_all(
            polymarket_data=[],
            kalshi_data=[_km()],
        ))
        assert opps == []

    def test_scan_all_no_matches_returns_empty(self):
        poly = [_pm("pm-1", question="Will it rain in London today?")]
        kal  = [_km("km-1", question="Will SpaceX land on Mars by 2030?")]
        opps = self._run(self.scanner.scan_all(
            polymarket_data=poly,
            kalshi_data=kal,
        ))
        assert opps == []

    def test_scan_all_returns_list(self):
        poly = [_pm("pm-1", yes_price=0.55, no_price=0.45)]
        kal  = [_km("km-1", yes_price=0.60, no_price=0.38)]
        result = self._run(self.scanner.scan_all(
            polymarket_data=poly, kalshi_data=kal
        ))
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 11. Edge-case / integration
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def setup_method(self):
        self.scanner = _scanner(min_similarity=0.5, min_profit_pct=0.02)

    def test_zero_volume_market_still_processed(self):
        poly = [_pm("pm-1", question="Will Bitcoin exceed $100k by March 31?",
                    volume_24h=0.0, yes_price=0.55, no_price=0.45)]
        kal  = [_km("km-1", question="Will Bitcoin exceed $100k by March 31?",
                    volume_24h=0.0, yes_price=0.60, no_price=0.38)]
        pairs = self.scanner.match_markets(poly, kal)
        assert len(pairs) >= 1

    def test_prices_at_extremes(self):
        # yes=0.01, no=0.99 — extreme low-probability market
        poly = [_pm("pm-1", yes_price=0.01, no_price=0.99)]
        kal  = [_km("km-1", yes_price=0.02, no_price=0.97)]
        pair = MatchedPair(
            polymarket=poly[0], kalshi=kal[0],
            similarity_score=0.9, resolution_match=True, resolution_risk="LOW",
        )
        # Just verify no exception and net_cost makes sense
        opps = self.scanner.scan_opportunities([pair])
        for opp in opps:
            assert 0.0 < opp.net_cost
            assert opp.net_profit == pytest.approx(1.0 - opp.net_cost, abs=1e-9)

    def test_profit_pct_formula(self):
        # Direct arithmetic check
        poly = _pm("pm-1", yes_price=0.55, no_price=0.45)
        kal  = _km("km-1", yes_price=0.60, no_price=0.38)
        pair = MatchedPair(
            polymarket=poly, kalshi=kal,
            similarity_score=0.9, resolution_match=True, resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        opp = opps[0]
        expected_profit_pct = opp.net_profit / opp.net_cost
        assert abs(opp.profit_pct - expected_profit_pct) < 1e-9

    def test_opportunity_has_timestamp(self):
        poly = [_pm("pm-1", yes_price=0.55, no_price=0.45)]
        kal  = [_km("km-1", yes_price=0.60, no_price=0.38)]
        pair = MatchedPair(
            polymarket=poly[0], kalshi=kal[0],
            similarity_score=0.9, resolution_match=True, resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        assert opps[0].timestamp > 0

    def test_required_capital_equals_net_cost(self):
        poly = _pm("pm-1", yes_price=0.55, no_price=0.45)
        kal  = _km("km-1", yes_price=0.60, no_price=0.38)
        pair = MatchedPair(
            polymarket=poly, kalshi=kal,
            similarity_score=0.9, resolution_match=True, resolution_risk="LOW",
        )
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        assert abs(opps[0].required_capital - opps[0].net_cost) < 1e-9

    def test_risk_level_propagated_to_opportunity(self):
        # Different resolution sources → MEDIUM or HIGH risk
        poly = _pm("pm-1", resolution_source="CoinGecko", yes_price=0.55, no_price=0.45)
        kal  = _km("km-1", resolution_source="Coinbase", yes_price=0.60, no_price=0.38)
        pair = MatchedPair(
            polymarket=poly, kalshi=kal,
            similarity_score=0.9, resolution_match=True, resolution_risk="",
        )
        pair.resolution_risk = self.scanner.assess_resolution_risk(pair)
        opps = self.scanner.scan_opportunities([pair])
        assert len(opps) == 1
        assert opps[0].risk_level in {"LOW", "MEDIUM", "HIGH"}
        assert opps[0].risk_level != "LOW"  # different sources → not LOW
