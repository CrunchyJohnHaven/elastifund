"""Unit tests for the combined backtest runner.

Tests:
1. Fee function correctness
2. Calibrated probabilities remain in [0, 1]
3. Regression: run outputs all expected keys
"""
from __future__ import annotations

import json
import os
import sys
import unittest

# Ensure backtest/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from run_combined import (
    taker_fee,
    classify_market,
    simulate_variant,
    VariantConfig,
    load_data,
    _cache_key,
    build_variants,
    generate_json,
    generate_markdown,
    RANDOM_SEED,
)


# ---------------------------------------------------------------------------
# 1. Fee function
# ---------------------------------------------------------------------------

class TestTakerFee(unittest.TestCase):
    """Unit tests for fee(p) = p * (1-p) * r."""

    def test_fee_at_50_percent(self):
        """Maximum fee occurs at p=0.50."""
        fee = taker_fee(0.50, 0.02)
        self.assertAlmostEqual(fee, 0.50 * 0.50 * 0.02, places=10)
        self.assertAlmostEqual(fee, 0.005, places=10)

    def test_fee_at_zero(self):
        """Fee is zero when p=0."""
        self.assertAlmostEqual(taker_fee(0.0, 0.02), 0.0, places=10)

    def test_fee_at_one(self):
        """Fee is zero when p=1."""
        self.assertAlmostEqual(taker_fee(1.0, 0.02), 0.0, places=10)

    def test_fee_symmetric(self):
        """fee(p) == fee(1-p) for any p."""
        for p in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            self.assertAlmostEqual(taker_fee(p, 0.02), taker_fee(1 - p, 0.02), places=10)

    def test_fee_zero_rate(self):
        """Fee is zero when r=0."""
        self.assertAlmostEqual(taker_fee(0.50, 0.0), 0.0, places=10)

    def test_fee_scales_with_rate(self):
        """Fee doubles when r doubles."""
        f1 = taker_fee(0.50, 0.01)
        f2 = taker_fee(0.50, 0.02)
        self.assertAlmostEqual(f2, f1 * 2, places=10)

    def test_fee_always_non_negative(self):
        """Fee is non-negative for all valid p in [0,1]."""
        for p in [i / 100 for i in range(101)]:
            self.assertGreaterEqual(taker_fee(p, 0.02), 0.0)

    def test_fee_maximum_at_midpoint(self):
        """Fee is maximized at p=0.50 for any positive r."""
        max_fee = taker_fee(0.50, 0.02)
        for p in [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]:
            self.assertLessEqual(taker_fee(p, 0.02), max_fee + 1e-10)


# ---------------------------------------------------------------------------
# 2. Calibrated probabilities in [0, 1]
# ---------------------------------------------------------------------------

class TestCalibrationBounds(unittest.TestCase):
    """Ensure calibrated probabilities stay within [0, 1]."""

    @classmethod
    def setUpClass(cls):
        """Build calibrator once for all tests in this class."""
        try:
            from calibration import CalibrationV2, load_calibration_samples
            samples = load_calibration_samples()
            cls.calibrator = CalibrationV2(method="auto", seed=RANDOM_SEED)
            cls.calibrator.fit_from_data(samples)
            cls.has_data = True
        except (FileNotFoundError, ImportError):
            cls.has_data = False
            cls.calibrator = None

    def test_calibrated_in_bounds(self):
        """All calibrated outputs must be in [0, 1]."""
        if not self.has_data:
            self.skipTest("No calibration data available")
        for p_raw in [i / 100 for i in range(1, 100)]:
            cal_p = self.calibrator.correct(p_raw)
            self.assertGreaterEqual(cal_p, 0.0, f"Calibrated {p_raw} → {cal_p} < 0")
            self.assertLessEqual(cal_p, 1.0, f"Calibrated {p_raw} → {cal_p} > 1")

    def test_calibrated_not_degenerate(self):
        """Calibration should not collapse everything to a single value."""
        if not self.has_data:
            self.skipTest("No calibration data available")
        outputs = [self.calibrator.correct(p / 100) for p in range(5, 96, 5)]
        unique = len(set(round(o, 4) for o in outputs))
        self.assertGreater(unique, 3, "Calibration collapsed to too few distinct values")


# ---------------------------------------------------------------------------
# 3. Regression: output keys
# ---------------------------------------------------------------------------

EXPECTED_VARIANT_KEYS = {
    "variant", "markets_eligible", "markets_filtered_by_category",
    "trades", "wins", "win_rate",
    "total_gross_pnl", "total_fees", "total_net_pnl", "avg_net_pnl",
    "max_drawdown", "sharpe", "brier",
    "yes_trades", "yes_win_rate", "no_trades", "no_win_rate",
    "arr_3", "arr_5", "arr_8",
}

EXPECTED_PAYLOAD_KEYS = {"run_at", "seed", "parameters", "variants"}


class TestOutputKeys(unittest.TestCase):
    """Regression test: run outputs contain all expected keys."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.markets, cls.cache, cls.hashes = load_data()
            cls.has_data = True
        except FileNotFoundError:
            cls.has_data = False

    def test_variant_result_keys(self):
        """Each variant result dict has all expected keys."""
        if not self.has_data:
            self.skipTest("No market data available")
        cfg = VariantConfig(name="test", entry_price=0.50, fee_rate=0.02)
        result = simulate_variant(self.markets, self.cache, cfg)
        missing = EXPECTED_VARIANT_KEYS - set(result.keys())
        self.assertEqual(missing, set(), f"Missing keys: {missing}")

    def test_empty_variant_keys(self):
        """Empty result (no trades) still has all expected keys."""
        if not self.has_data:
            self.skipTest("No market data available")
        cfg = VariantConfig(name="impossible", entry_price=0.50, fee_rate=0.02,
                            yes_threshold=999.0, no_threshold=999.0)
        result = simulate_variant(self.markets, self.cache, cfg)
        missing = EXPECTED_VARIANT_KEYS - set(result.keys())
        self.assertEqual(missing, set(), f"Missing keys in empty result: {missing}")
        self.assertEqual(result["trades"], 0)

    def test_payload_keys(self):
        """generate_json output has all expected top-level keys."""
        dummy_results = [{"variant": "test", **{k: 0 for k in EXPECTED_VARIANT_KEYS if k != "variant"}}]
        payload = generate_json(dummy_results, {"entry_price": 0.5, "fee_rate": 0.02,
                                                 "total_markets": 0, "total_cache_entries": 0,
                                                 "hashes": {}})
        missing = EXPECTED_PAYLOAD_KEYS - set(payload.keys())
        self.assertEqual(missing, set(), f"Missing payload keys: {missing}")

    def test_markdown_not_empty(self):
        """generate_markdown produces non-empty output."""
        dummy_results = [{k: 0 for k in EXPECTED_VARIANT_KEYS}]
        dummy_results[0]["variant"] = "test"
        dummy_results[0]["win_rate"] = 0.65
        payload = generate_json(dummy_results, {"entry_price": 0.5, "fee_rate": 0.02,
                                                 "total_markets": 0, "total_cache_entries": 0,
                                                 "hashes": {"historical_markets.json": "abc",
                                                            "claude_cache.json": "def"}})
        md = generate_markdown(payload)
        self.assertGreater(len(md), 100)
        self.assertIn("Combined Backtest Results", md)


# ---------------------------------------------------------------------------
# 4. Category classifier
# ---------------------------------------------------------------------------

class TestCategoryClassifier(unittest.TestCase):
    def test_crypto(self):
        self.assertEqual(classify_market("Will Bitcoin reach $100k?"), "crypto")

    def test_sports(self):
        self.assertEqual(classify_market("Will the NBA finals go to 7 games?"), "sports")

    def test_politics(self):
        self.assertEqual(classify_market("Will the president sign the bill?"), "politics")

    def test_weather(self):
        self.assertEqual(classify_market("Will it snow in NYC tomorrow?"), "weather")

    def test_other(self):
        self.assertEqual(classify_market("Will aliens be discovered?"), "other")

    def test_fed_rates(self):
        self.assertEqual(classify_market("Will the Federal Reserve cut rates?"), "fed_rates")


# ---------------------------------------------------------------------------
# 5. Fee impact test
# ---------------------------------------------------------------------------

class TestFeeImpact(unittest.TestCase):
    """Verify that fees reduce net P&L vs gross P&L."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.markets, cls.cache, _ = load_data()
            cls.has_data = True
        except FileNotFoundError:
            cls.has_data = False

    def test_fees_reduce_pnl(self):
        """Net P&L should be less than gross P&L when fee_rate > 0."""
        if not self.has_data:
            self.skipTest("No market data available")
        cfg = VariantConfig(name="fee_test", entry_price=0.50, fee_rate=0.02)
        r = simulate_variant(self.markets, self.cache, cfg)
        if r["trades"] > 0:
            self.assertGreater(r["total_fees"], 0)
            self.assertLess(r["total_net_pnl"], r["total_gross_pnl"])

    def test_zero_fee_no_impact(self):
        """With fee_rate=0, net P&L equals gross P&L."""
        if not self.has_data:
            self.skipTest("No market data available")
        cfg = VariantConfig(name="nofee_test", entry_price=0.50, fee_rate=0.0)
        r = simulate_variant(self.markets, self.cache, cfg)
        self.assertAlmostEqual(r["total_fees"], 0.0, places=10)
        self.assertAlmostEqual(r["total_net_pnl"], r["total_gross_pnl"], places=10)


if __name__ == "__main__":
    unittest.main()
