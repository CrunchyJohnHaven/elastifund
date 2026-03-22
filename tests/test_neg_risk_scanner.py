#!/usr/bin/env python3
"""Tests for bot/neg_risk_scanner.py.

All tests use synthetic market data — no live API calls.
"""

from __future__ import annotations

import asyncio
import unittest

from bot.neg_risk_scanner import (
    ArbitrageOpportunity,
    MarketOutcome,
    NegativeRiskScanner,
    btc_price_ladder_scanner,
    extract_threshold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_outcome(
    market_id: str,
    condition_id: str,
    question: str,
    yes_price: float,
    liquidity: float = 500.0,
    yes_token_id: str = "",
    no_token_id: str = "",
    volume_24h: float = 1000.0,
) -> MarketOutcome:
    return MarketOutcome(
        market_id=market_id,
        condition_id=condition_id,
        question=question,
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 6),
        yes_token_id=yes_token_id or f"tok_{market_id}_yes",
        no_token_id=no_token_id or f"tok_{market_id}_no",
        volume_24h=volume_24h,
        liquidity=liquidity,
    )


def _run(coro):
    """Run a coroutine synchronously in tests."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Threshold extraction tests
# ---------------------------------------------------------------------------

class TestExtractThreshold(unittest.TestCase):

    def test_dollar_abbreviation_k(self):
        self.assertEqual(extract_threshold("Bitcoin above $95k"), 95_000.0)

    def test_dollar_abbreviation_K_uppercase(self):
        self.assertEqual(extract_threshold("BTC above $95K"), 95_000.0)

    def test_dollar_comma_format(self):
        self.assertEqual(extract_threshold("Bitcoin above $95,000"), 95_000.0)

    def test_dollar_decimal_comma_format(self):
        self.assertEqual(extract_threshold("Bitcoin price > $95,000.00"), 95_000.0)

    def test_no_dollar_sign(self):
        self.assertEqual(extract_threshold("BTC below 90000"), 90_000.0)

    def test_dollar_100K(self):
        self.assertEqual(extract_threshold("above $100K"), 100_000.0)

    def test_btc_above_90k_lower(self):
        self.assertEqual(extract_threshold("BTC above $90k"), 90_000.0)

    def test_dollar_3_5k(self):
        self.assertAlmostEqual(extract_threshold("ETH above $3.5k"), 3_500.0)

    def test_no_threshold_returns_none(self):
        self.assertIsNone(extract_threshold("Will the Fed raise rates in 2026?"))

    def test_bare_dollar_amount(self):
        self.assertEqual(extract_threshold("Will BTC reach $85,000?"), 85_000.0)

    def test_million_suffix(self):
        self.assertEqual(extract_threshold("Market cap above $1m"), 1_000_000.0)

    def test_gt_symbol(self):
        self.assertEqual(extract_threshold("BTC > $85,000"), 85_000.0)


# ---------------------------------------------------------------------------
# Negative risk detection tests
# ---------------------------------------------------------------------------

class TestScanNegativeRisk(unittest.TestCase):

    def setUp(self):
        self.scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=100.0)

    def _four_outcome_group(self, prices: list[float], condition_id: str = "cond-1") -> dict:
        return {
            condition_id: [
                _make_outcome(f"m{i}", condition_id, f"Candidate {i} wins", p)
                for i, p in enumerate(prices)
            ]
        }

    def test_detects_opportunity_when_sum_below_1(self):
        # 4 outcomes summing to 0.95 → opportunity
        grouped = self._four_outcome_group([0.24, 0.23, 0.25, 0.23])
        opps = self.scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 1)
        opp = opps[0]
        self.assertEqual(opp.opportunity_type, "negative_risk")
        self.assertAlmostEqual(opp.total_cost, 0.95, places=4)
        self.assertAlmostEqual(opp.guaranteed_payout, 1.0)
        self.assertGreater(opp.profit_per_share, 0)

    def test_rejects_opportunity_when_sum_above_1(self):
        # 4 outcomes summing to 1.02 → no opportunity
        grouped = self._four_outcome_group([0.26, 0.26, 0.25, 0.25])
        opps = self.scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 0)

    def test_rejects_single_outcome_group(self):
        grouped = {"cond-single": [_make_outcome("m0", "cond-single", "X wins", 0.4)]}
        opps = self.scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 0)

    def test_rejects_empty_groups(self):
        opps = self.scanner.scan_negative_risk({})
        self.assertEqual(opps, [])

    def test_rejects_low_liquidity(self):
        # Liquidity below threshold → filtered out
        grouped = {
            "cond-liq": [
                _make_outcome(f"m{i}", "cond-liq", f"Cand {i}", 0.2, liquidity=50.0)
                for i in range(5)
            ]
        }
        opps = self.scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 0)

    def test_profit_pct_computed_correctly(self):
        # sum = 0.80, profit = 0.20, pct = 0.20/0.80 = 25%
        grouped = self._four_outcome_group([0.20, 0.20, 0.20, 0.20])
        opps = self.scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 1)
        self.assertAlmostEqual(opps[0].profit_pct, 0.25, places=4)

    def test_sorted_by_profit_pct_descending(self):
        grouped = {
            "cond-a": [
                _make_outcome(f"a{i}", "cond-a", f"A{i}", 0.20) for i in range(4)
            ],
            "cond-b": [
                _make_outcome(f"b{i}", "cond-b", f"B{i}", 0.23) for i in range(4)
            ],
        }
        opps = self.scanner.scan_negative_risk(grouped)
        # cond-a (sum=0.80, profit=25%) should rank above cond-b (sum=0.92, ~8.7%)
        self.assertGreaterEqual(opps[0].profit_pct, opps[-1].profit_pct)

    def test_five_candidate_election_market(self):
        # Realistic 5-candidate election with prices summing to 0.93
        prices = [0.35, 0.25, 0.18, 0.10, 0.05]  # sum = 0.93
        grouped = self._four_outcome_group.__wrapped__(self, prices, "cond-elec") if hasattr(
            self._four_outcome_group, "__wrapped__"
        ) else {
            "cond-elec": [
                _make_outcome(f"e{i}", "cond-elec", f"Candidate {i} wins president", p)
                for i, p in enumerate(prices)
            ]
        }
        opps = self.scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 1)
        self.assertAlmostEqual(opps[0].total_cost, 0.93, places=4)


# ---------------------------------------------------------------------------
# Fee filtering test
# ---------------------------------------------------------------------------

class TestFeeFiltering(unittest.TestCase):

    def test_fee_filter_rejects_marginal_opportunity(self):
        # Profit of 0.003 per share on a 2-leg group.
        # Taker fee = 2 legs * 1.5% * avg_price 0.499 ≈ 0.015 >> 0.003
        scanner = NegativeRiskScanner(min_profit_pct=0.001, min_liquidity=0.0)
        grouped = {
            "cond-fee": [
                _make_outcome("mf0", "cond-fee", "A wins", 0.499, liquidity=1000.0),
                _make_outcome("mf1", "cond-fee", "B wins", 0.499, liquidity=1000.0),
            ]
        }
        opps = scanner.scan_negative_risk(grouped)
        # Profit_per_share = 0.002, fee = 2*0.015*0.499 ≈ 0.015 → should be rejected
        self.assertEqual(opps, [])

    def test_is_profitable_after_fees_property(self):
        opp = ArbitrageOpportunity(
            opportunity_type="negative_risk",
            market_group_id="test",
            markets=[{"market_id": "m1"}, {"market_id": "m2"}, {"market_id": "m3"}],
            total_cost=0.75,
            guaranteed_payout=1.0,
            profit_per_share=0.25,
            profit_pct=0.333,
            required_capital=0.75,
            constraint_violated="sum < 1.0",
        )
        # 3 legs * 1.5% * (0.75/3) = 0.0113, profit 0.25 >> 0.0113
        self.assertTrue(opp.is_profitable_after_fees)

    def test_is_not_profitable_after_fees_property(self):
        opp = ArbitrageOpportunity(
            opportunity_type="negative_risk",
            market_group_id="test",
            markets=[{"market_id": f"m{i}"} for i in range(10)],
            total_cost=0.998,
            guaranteed_payout=1.0,
            profit_per_share=0.002,
            profit_pct=0.002,
            required_capital=0.998,
            constraint_violated="sum < 1.0",
        )
        # 10 legs * 1.5% * (0.998/10) = 0.01497, profit 0.002 << 0.015
        self.assertFalse(opp.is_profitable_after_fees)

    def test_is_profitable_after_fees_empty_markets(self):
        opp = ArbitrageOpportunity(
            opportunity_type="negative_risk",
            market_group_id="test",
            markets=[],
            total_cost=0.5,
            guaranteed_payout=1.0,
            profit_per_share=0.5,
            profit_pct=1.0,
            required_capital=0.5,
            constraint_violated="",
        )
        self.assertFalse(opp.is_profitable_after_fees)


# ---------------------------------------------------------------------------
# Combinatorial constraint violation tests
# ---------------------------------------------------------------------------

class TestScanCombinatorial(unittest.TestCase):

    def setUp(self):
        self.scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=100.0)

    def _btc_ladder(self, prices_by_threshold: dict[int, float]) -> dict[str, list[MarketOutcome]]:
        """Build a BTC price-ladder grouped market."""
        grouped: dict[str, list[MarketOutcome]] = {}
        for thresh, price in sorted(prices_by_threshold.items()):
            cid = f"cond-btc-{thresh}"
            grouped[cid] = [
                _make_outcome(
                    f"btc-{thresh}",
                    cid,
                    f"BTC above ${thresh}k",
                    price,
                )
            ]
        return grouped

    def test_detects_btc_ladder_violation(self):
        # P(>95k) > P(>90k) is impossible
        grouped = self._btc_ladder({85: 0.70, 90: 0.50, 95: 0.60})  # violation at 90/95
        opps = self.scanner.scan_combinatorial(grouped)
        self.assertGreater(len(opps), 0)
        # The opportunity should mention the violation
        opp = opps[0]
        self.assertEqual(opp.opportunity_type, "combinatorial")
        self.assertIn("Monotonicity violation", opp.constraint_violated)

    def test_no_violation_with_correct_ordering(self):
        # Monotonically decreasing — no violation
        grouped = self._btc_ladder({85: 0.70, 90: 0.50, 95: 0.30})
        opps = self.scanner.scan_combinatorial(grouped)
        # Filter to threshold violations only
        threshold_opps = [o for o in opps if "Monotonicity" in o.constraint_violated]
        self.assertEqual(len(threshold_opps), 0)

    def test_violation_profit_direction(self):
        # Higher threshold priced HIGHER than lower threshold by 0.15
        grouped = self._btc_ladder({90: 0.40, 95: 0.55})
        opps = self.scanner.scan_combinatorial(grouped)
        threshold_opps = [o for o in opps if "Monotonicity" in o.constraint_violated]
        self.assertEqual(len(threshold_opps), 1)
        self.assertAlmostEqual(threshold_opps[0].profit_per_share, 0.15, places=4)

    def test_violation_below_min_profit_filtered(self):
        # Only 0.001 violation — below 0.005 min_profit_pct
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=0.0)
        grouped = self._btc_ladder({90: 0.500, 95: 0.501})
        opps = scanner.scan_combinatorial(grouped)
        threshold_opps = [o for o in opps if "Monotonicity" in o.constraint_violated]
        self.assertEqual(len(threshold_opps), 0)

    def test_empty_grouped_markets(self):
        opps = self.scanner.scan_combinatorial({})
        self.assertEqual(opps, [])


# ---------------------------------------------------------------------------
# Time-subset detection tests
# ---------------------------------------------------------------------------

class TestTimeSubsetDetection(unittest.TestCase):

    def setUp(self):
        self.scanner = NegativeRiskScanner(min_profit_pct=0.001, min_liquidity=0.0)

    def test_march_subset_of_q1(self):
        # "Will X happen in March?" ⊂ "Will X happen in Q1?"
        grouped = {
            "cond-mar": [_make_outcome("m-mar", "cond-mar", "X happens in March 2026", 0.40, liquidity=1000.0)],
            "cond-q1":  [_make_outcome("m-q1",  "cond-q1",  "X happens in Q1 2026",   0.30, liquidity=1000.0)],
        }
        opps = self.scanner.scan_combinatorial(grouped)
        subset_opps = [o for o in opps if "Time subset" in o.constraint_violated]
        self.assertEqual(len(subset_opps), 1)
        self.assertGreater(subset_opps[0].profit_per_share, 0)

    def test_no_violation_when_ordering_correct(self):
        # P(Q1) >= P(March) — no violation
        grouped = {
            "cond-mar": [_make_outcome("m-mar", "cond-mar", "X happens in March 2026", 0.20, liquidity=1000.0)],
            "cond-q1":  [_make_outcome("m-q1",  "cond-q1",  "X happens in Q1 2026",   0.40, liquidity=1000.0)],
        }
        opps = self.scanner.scan_combinatorial(grouped)
        subset_opps = [o for o in opps if "Time subset" in o.constraint_violated]
        self.assertEqual(len(subset_opps), 0)

    def test_no_time_reference_no_pair(self):
        grouped = {
            "cond-a": [_make_outcome("ma", "cond-a", "Will inflation rise?", 0.60, liquidity=1000.0)],
            "cond-b": [_make_outcome("mb", "cond-b", "Will markets crash?", 0.40, liquidity=1000.0)],
        }
        opps = self.scanner.scan_combinatorial(grouped)
        subset_opps = [o for o in opps if "Time subset" in o.constraint_violated]
        self.assertEqual(len(subset_opps), 0)


# ---------------------------------------------------------------------------
# calculate_optimal_portfolio tests
# ---------------------------------------------------------------------------

class TestCalculateOptimalPortfolio(unittest.TestCase):

    def setUp(self):
        self.scanner = NegativeRiskScanner()

    def test_neg_risk_portfolio_buys_yes_on_all_legs(self):
        opp = ArbitrageOpportunity(
            opportunity_type="negative_risk",
            market_group_id="cond-1",
            markets=[
                {"market_id": "m1", "yes_price": 0.24, "no_price": 0.76, "token_id": "tok1"},
                {"market_id": "m2", "yes_price": 0.23, "no_price": 0.77, "token_id": "tok2"},
                {"market_id": "m3", "yes_price": 0.25, "no_price": 0.75, "token_id": "tok3"},
            ],
            total_cost=0.72,
            guaranteed_payout=1.0,
            profit_per_share=0.28,
            profit_pct=0.389,
            required_capital=0.72,
            constraint_violated="sum < 1.0",
        )
        orders = self.scanner.calculate_optimal_portfolio(opp)
        self.assertEqual(len(orders), 3)
        for mid, order in orders.items():
            self.assertEqual(order["side"], "YES")
            self.assertEqual(order["size"], 1)
            self.assertIn("price", order)
            self.assertIn("token_id", order)

    def test_neg_risk_prices_match_legs(self):
        opp = ArbitrageOpportunity(
            opportunity_type="negative_risk",
            market_group_id="cond-1",
            markets=[
                {"market_id": "mA", "yes_price": 0.30, "no_price": 0.70, "token_id": "tA"},
                {"market_id": "mB", "yes_price": 0.35, "no_price": 0.65, "token_id": "tB"},
            ],
            total_cost=0.65,
            guaranteed_payout=1.0,
            profit_per_share=0.35,
            profit_pct=0.538,
            required_capital=0.65,
            constraint_violated="sum < 1.0",
        )
        orders = self.scanner.calculate_optimal_portfolio(opp)
        self.assertAlmostEqual(orders["mA"]["price"], 0.30)
        self.assertAlmostEqual(orders["mB"]["price"], 0.35)
        self.assertEqual(orders["mA"]["token_id"], "tA")

    def test_combinatorial_threshold_portfolio(self):
        opp = ArbitrageOpportunity(
            opportunity_type="combinatorial",
            market_group_id="cond-a|cond-b",
            markets=[
                {
                    "market_id": "m-low",
                    "yes_price": 0.40,
                    "no_price": 0.60,
                    "token_id": "tok-low",
                    "no_token_id": "tok-low-no",
                    "role": "lower_threshold",
                },
                {
                    "market_id": "m-high",
                    "yes_price": 0.55,
                    "no_price": 0.45,
                    "token_id": "tok-high",
                    "no_token_id": "tok-high-no",
                    "role": "higher_threshold",
                },
            ],
            total_cost=0.40,
            guaranteed_payout=0.55,
            profit_per_share=0.15,
            profit_pct=0.375,
            required_capital=0.40,
            constraint_violated="Monotonicity violation",
        )
        orders = self.scanner.calculate_optimal_portfolio(opp)
        self.assertEqual(len(orders), 2)
        # Cheap leg bought YES; expensive leg hedged with NO
        self.assertIn("m-low", orders)
        self.assertIn("m-high", orders)

    def test_empty_opportunity_returns_no_orders(self):
        opp = ArbitrageOpportunity(
            opportunity_type="combinatorial",
            market_group_id="cond-x",
            markets=[],
            total_cost=0.0,
            guaranteed_payout=0.0,
            profit_per_share=0.0,
            profit_pct=0.0,
            required_capital=0.0,
            constraint_violated="",
        )
        orders = self.scanner.calculate_optimal_portfolio(opp)
        self.assertEqual(orders, {})


# ---------------------------------------------------------------------------
# format_alert tests
# ---------------------------------------------------------------------------

class TestFormatAlert(unittest.TestCase):

    def setUp(self):
        self.scanner = NegativeRiskScanner()

    def _make_opp(self) -> ArbitrageOpportunity:
        return ArbitrageOpportunity(
            opportunity_type="negative_risk",
            market_group_id="cond-test",
            markets=[
                {"market_id": "m1", "question": "Alice wins", "yes_price": 0.30, "no_price": 0.70, "token_id": "t1"},
                {"market_id": "m2", "question": "Bob wins",   "yes_price": 0.25, "no_price": 0.75, "token_id": "t2"},
                {"market_id": "m3", "question": "Carol wins", "yes_price": 0.30, "no_price": 0.70, "token_id": "t3"},
            ],
            total_cost=0.85,
            guaranteed_payout=1.0,
            profit_per_share=0.15,
            profit_pct=0.1765,
            required_capital=0.85,
            constraint_violated="YES prices sum to 0.85 < 1.00",
        )

    def test_alert_contains_opportunity_type(self):
        alert = self.scanner.format_alert(self._make_opp())
        self.assertIn("NEGATIVE RISK", alert)

    def test_alert_contains_profit_pct(self):
        alert = self.scanner.format_alert(self._make_opp())
        self.assertIn("17.65%", alert)

    def test_alert_contains_group_id(self):
        alert = self.scanner.format_alert(self._make_opp())
        self.assertIn("cond-test", alert)

    def test_alert_contains_all_legs(self):
        alert = self.scanner.format_alert(self._make_opp())
        self.assertIn("m1", alert)
        self.assertIn("m2", alert)
        self.assertIn("m3", alert)

    def test_alert_is_string(self):
        alert = self.scanner.format_alert(self._make_opp())
        self.assertIsInstance(alert, str)

    def test_alert_mentions_after_fee_status(self):
        alert = self.scanner.format_alert(self._make_opp())
        self.assertIn("After-fee profitable", alert)


# ---------------------------------------------------------------------------
# scan_all integration tests (async)
# ---------------------------------------------------------------------------

class TestScanAll(unittest.TestCase):

    def test_scan_all_with_mock_data_returns_sorted_list(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=100.0)
        market_data = {
            "cond-neg": [
                _make_outcome(f"n{i}", "cond-neg", f"Candidate {i} wins", 0.20) for i in range(5)
            ],
            "cond-ok": [
                _make_outcome(f"o{i}", "cond-ok", f"Option {i}", 0.26) for i in range(4)
            ],
        }
        opps = _run(scanner.scan_all(market_data=market_data))
        # Only cond-neg (sum=1.0 → no profit) or cond-ok?
        # cond-neg sum=1.00 → no opp; cond-ok sum=1.04 → no opp
        # All sums ≥ 1.0 → empty
        self.assertIsInstance(opps, list)
        # Verify sorted order
        for i in range(len(opps) - 1):
            self.assertGreaterEqual(opps[i].profit_pct, opps[i + 1].profit_pct)

    def test_scan_all_finds_neg_risk_opp(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=100.0)
        market_data = {
            "cond-arb": [
                _make_outcome(f"a{i}", "cond-arb", f"Candidate {i} wins election", 0.18)
                for i in range(5)
            ]
        }
        opps = _run(scanner.scan_all(market_data=market_data))
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].opportunity_type, "negative_risk")
        self.assertAlmostEqual(opps[0].total_cost, 0.90, places=4)

    def test_scan_all_empty_data(self):
        scanner = NegativeRiskScanner()
        opps = _run(scanner.scan_all(market_data={}))
        self.assertEqual(opps, [])

    def test_scan_all_combines_both_types(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=100.0)
        market_data = {
            # neg-risk opportunity (sum=0.90)
            "cond-neg": [
                _make_outcome(f"n{i}", "cond-neg", f"Candidate {i} wins election", 0.18)
                for i in range(5)
            ],
            # combinatorial violation: P(>90k) > P(>85k) impossible
            "cond-btc-85": [_make_outcome("btc85", "cond-btc-85", "BTC above $85k", 0.40)],
            "cond-btc-90": [_make_outcome("btc90", "cond-btc-90", "BTC above $90k", 0.55)],
        }
        opps = _run(scanner.scan_all(market_data=market_data))
        types = {o.opportunity_type for o in opps}
        self.assertIn("negative_risk", types)
        self.assertIn("combinatorial", types)


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------

class TestBtcPriceLadderScanner(unittest.TestCase):

    def test_factory_returns_scanner(self):
        scanner = btc_price_ladder_scanner()
        self.assertIsInstance(scanner, NegativeRiskScanner)

    def test_factory_has_lower_min_profit(self):
        scanner = btc_price_ladder_scanner()
        # Should be lower than the default 0.5%
        self.assertLessEqual(scanner.min_profit_pct, 0.005)
        self.assertAlmostEqual(scanner.min_profit_pct, 0.003)

    def test_factory_has_lower_liquidity_requirement(self):
        scanner = btc_price_ladder_scanner()
        self.assertLessEqual(scanner.min_liquidity, 100.0)

    def test_factory_scanner_detects_btc_violation(self):
        scanner = btc_price_ladder_scanner()
        market_data = {
            "cond-85": [_make_outcome("b85", "cond-85", "BTC above $85k", 0.60, liquidity=200.0)],
            "cond-90": [_make_outcome("b90", "cond-90", "BTC above $90k", 0.75, liquidity=200.0)],
        }
        opps = _run(scanner.scan_all(market_data=market_data))
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].opportunity_type, "combinatorial")


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_two_outcome_neg_risk(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=0.0)
        grouped = {
            "cond-2": [
                _make_outcome("t1", "cond-2", "Team A wins", 0.40, liquidity=1000.0),
                _make_outcome("t2", "cond-2", "Team B wins", 0.40, liquidity=1000.0),
            ]
        }
        opps = scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 1)
        self.assertAlmostEqual(opps[0].total_cost, 0.80, places=4)

    def test_max_outcomes_cap(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=0.0, max_outcomes=5)
        grouped = {
            "cond-big": [
                _make_outcome(f"m{i}", "cond-big", f"Option {i}", 0.05, liquidity=1000.0)
                for i in range(6)  # 6 > max_outcomes of 5
            ]
        }
        opps = scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 0)

    def test_required_capital_equals_total_cost(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=0.0)
        grouped = {
            "cond-cap": [
                _make_outcome(f"c{i}", "cond-cap", f"Cand {i}", 0.15, liquidity=1000.0)
                for i in range(4)
            ]
        }
        opps = scanner.scan_negative_risk(grouped)
        self.assertEqual(len(opps), 1)
        self.assertAlmostEqual(opps[0].required_capital, opps[0].total_cost, places=6)

    def test_opportunity_timestamp_is_recent(self):
        import time
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=0.0)
        grouped = {
            "cond-ts": [
                _make_outcome(f"ts{i}", "cond-ts", f"Cand {i}", 0.15, liquidity=1000.0)
                for i in range(4)
            ]
        }
        before = time.time()
        opps = scanner.scan_negative_risk(grouped)
        after = time.time()
        self.assertEqual(len(opps), 1)
        self.assertGreaterEqual(opps[0].timestamp, before)
        self.assertLessEqual(opps[0].timestamp, after + 1)

    def test_constraint_violated_field_non_empty(self):
        scanner = NegativeRiskScanner(min_profit_pct=0.005, min_liquidity=0.0)
        grouped = {
            "cond-cv": [
                _make_outcome(f"cv{i}", "cond-cv", f"Cand {i}", 0.15, liquidity=1000.0)
                for i in range(4)
            ]
        }
        opps = scanner.scan_negative_risk(grouped)
        self.assertTrue(opps[0].constraint_violated)


if __name__ == "__main__":
    unittest.main()
