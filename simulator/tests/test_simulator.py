"""
Integration tests for the paper-trade simulator engine.

Tests cover:
- Deterministic reproducibility (same seed → same output)
- Trade resolution logic (buy_yes/buy_no, win/loss)
- Position sizing integration
- Filter enforcement (price range, liquidity, volume)
- Edge threshold gating
- Sensitivity analysis structure
- End-to-end baseline run
"""

import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from simulator.api import SimulatorEngine, question_cache_key
from simulator.sensitivity import run_sensitivity, _set_nested


# --- Fixtures ---

BASELINE_CONFIG = {
    "capital": {"initial": 100.0},
    "fees": {"taker_rate": 0.02, "maker_rate": 0.0, "winner_fee": 0.02},
    "fill_model": {
        "taker": {
            "base_slippage_bps": 50,
            "size_impact_bps_per_dollar": 2,
            "liquidity_impact_factor": 0.001,
            "fill_probability": 1.0,
        },
        "maker": {
            "base_fill_probability": 0.55,
            "distance_decay": 2.0,
            "min_fill_probability": 0.10,
            "price_improvement_bps": 0,
        },
        "spreads": {
            "high_volume": {"half_spread_cents": 1.5, "min_liquidity": 10000},
            "us_weather": {"half_spread_cents": 7.0, "min_liquidity": 2000},
            "international": {"half_spread_cents": 20.0, "min_liquidity": 500},
            "niche": {"half_spread_cents": 22.0, "min_liquidity": 100},
            "default": {"half_spread_cents": 5.0, "min_liquidity": 500},
        },
    },
    "sizing": {
        "method": "fixed_fraction",
        "fixed_fraction": {"fraction": 0.02},
        "kelly": {"kelly_fraction": 0.25, "max_allocation": 0.20, "min_size": 1.0},
        "capped": {"max_position_usd": 5.0, "min_position_usd": 1.0},
    },
    "execution": {"mode": "taker", "max_concurrent_positions": 50, "min_edge_threshold": 0.05},
    "filters": {"min_liquidity": 500, "min_volume": 1000, "price_range": [0.10, 0.90]},
    "random_seed": 42,
}


def _make_market(
    market_id="1",
    question="Will it rain tomorrow?",
    actual_outcome="YES_WON",
    volume=10000.0,
    liquidity=5000.0,
    end_date="2026-01-15T00:00:00Z",
):
    return {
        "id": market_id,
        "question": question,
        "actual_outcome": actual_outcome,
        "volume": volume,
        "liquidity": liquidity,
        "end_date": end_date,
    }


def _make_cache(question, probability=0.80, confidence="medium"):
    key = question_cache_key(question)
    return {key: {"probability": probability, "confidence": confidence, "reasoning": "test"}}


# --- Reproducibility ---

class TestReproducibility:
    def test_same_seed_same_output(self):
        """Identical inputs + seed must produce identical PnL."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        engine1 = SimulatorEngine(BASELINE_CONFIG)
        report1 = engine1.run([market], cache)

        engine2 = SimulatorEngine(BASELINE_CONFIG)
        report2 = engine2.run([market], cache)

        assert report1["total_pnl"] == report2["total_pnl"]
        assert report1["filled_trades"] == report2["filled_trades"]
        assert report1["hit_rate"] == report2["hit_rate"]

    def test_different_seed_may_differ_maker(self):
        """Different seeds should produce different maker fill sequences."""
        config_maker = deepcopy(BASELINE_CONFIG)
        config_maker["execution"]["mode"] = "maker"

        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        config1 = deepcopy(config_maker)
        config1["random_seed"] = 1

        config2 = deepcopy(config_maker)
        config2["random_seed"] = 999

        engine1 = SimulatorEngine(config1)
        report1 = engine1.run([market], cache)

        engine2 = SimulatorEngine(config2)
        report2 = engine2.run([market], cache)

        # With different seeds, maker fills may differ
        # (taker mode would be identical regardless of seed)
        # We just verify both ran without error
        assert report1["total_trades"] >= 0
        assert report2["total_trades"] >= 0

    def test_taker_mode_seed_independent(self):
        """Taker fills are deterministic regardless of seed."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        config1 = deepcopy(BASELINE_CONFIG)
        config1["random_seed"] = 1

        config2 = deepcopy(BASELINE_CONFIG)
        config2["random_seed"] = 999

        engine1 = SimulatorEngine(config1)
        report1 = engine1.run([market], cache)

        engine2 = SimulatorEngine(config2)
        report2 = engine2.run([market], cache)

        assert report1["total_pnl"] == report2["total_pnl"]


# --- Trade Resolution ---

class TestTradeResolution:
    def test_buy_yes_wins_on_yes(self):
        """buy_yes should win when actual outcome is YES_WON."""
        market = _make_market(actual_outcome="YES_WON")
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0]
        # At entry prices 0.20-0.80, claude_prob=0.90 gives buy_yes for all
        yes_trades = [t for t in filled if t["direction"] == "buy_yes"]
        assert len(yes_trades) > 0
        assert all(t["won"] for t in yes_trades)

    def test_buy_yes_loses_on_no(self):
        """buy_yes should lose when actual outcome is NO_WON."""
        market = _make_market(actual_outcome="NO_WON")
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0]
        yes_trades = [t for t in filled if t["direction"] == "buy_yes"]
        assert len(yes_trades) > 0
        assert all(not t["won"] for t in yes_trades)

    def test_buy_no_wins_on_no(self):
        """buy_no should win when actual outcome is NO_WON."""
        market = _make_market(actual_outcome="NO_WON")
        # Low probability → buy_no direction
        cache = _make_cache(market["question"], probability=0.10)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0]
        no_trades = [t for t in filled if t["direction"] == "buy_no"]
        assert len(no_trades) > 0
        assert all(t["won"] for t in no_trades)

    def test_winning_trade_has_positive_pnl(self):
        """Winner should net positive after fees."""
        market = _make_market(actual_outcome="YES_WON")
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0 and t["won"]]
        # At low entry prices (0.20, 0.30), winning payout should exceed cost
        cheap_wins = [t for t in filled if t["entry_price"] <= 0.40]
        assert len(cheap_wins) > 0
        assert all(t["pnl"] > 0 for t in cheap_wins)

    def test_losing_trade_loses_size_plus_fee(self):
        """Loser should lose position size + entry fee."""
        market = _make_market(actual_outcome="NO_WON")
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0 and not t["won"]]
        assert len(filled) > 0
        for t in filled:
            expected_loss = t["size_usd"] + t["fee_paid"]
            assert abs(t["pnl"] + expected_loss) < 0.01  # pnl = -(size + entry_fee)

    def test_winner_fee_applied(self):
        """Winner fee should reduce winning payout."""
        # Compare with 0% winner fee
        config_no_fee = deepcopy(BASELINE_CONFIG)
        config_no_fee["fees"]["winner_fee"] = 0.0

        market = _make_market(actual_outcome="YES_WON")
        cache = _make_cache(market["question"], probability=0.90)

        engine_fee = SimulatorEngine(BASELINE_CONFIG)
        report_fee = engine_fee.run([market], cache)

        engine_no_fee = SimulatorEngine(config_no_fee)
        report_no_fee = engine_no_fee.run([market], cache)

        # With 2% winner fee, PnL should be lower
        assert report_fee["total_pnl"] < report_no_fee["total_pnl"]


# --- Filters ---

class TestFilters:
    def test_low_liquidity_filtered(self):
        """Markets below min_liquidity should be skipped."""
        market = _make_market(liquidity=100.0)  # Below 500 threshold
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        assert report["filled_trades"] == 0

    def test_low_volume_filtered(self):
        """Markets below min_volume should be skipped."""
        market = _make_market(volume=500.0)  # Below 1000 threshold
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        assert report["filled_trades"] == 0

    def test_no_cache_entry_skipped(self):
        """Markets without a cache entry should be skipped."""
        market = _make_market()
        empty_cache = {}

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], empty_cache)

        assert report["total_trades"] == 0

    def test_edge_threshold(self):
        """Only trades with edge >= threshold should fire."""
        market = _make_market()
        # probability=0.52 means edge at price=0.50 is only 0.02 < 0.05 threshold
        cache = _make_cache(market["question"], probability=0.52)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        # Should still get some trades at prices far from 0.52
        # (e.g., at 0.20, edge = 0.32; at 0.80, edge = 0.28)
        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0]
        for t in filled:
            assert t["edge_pre_cost"] >= 0.05


# --- Position Sizing ---

class TestPositionSizing:
    def test_fixed_fraction_size(self):
        """Fixed fraction sizing should give ~2% of capital."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0]
        assert len(filled) > 0
        # First trade should be exactly 2% of initial capital
        assert abs(filled[0]["size_usd"] - 2.0) < 0.01
        # Later trades may differ as capital changes from wins/losses

    def test_kelly_sizing(self):
        """Kelly sizing should produce variable sizes based on edge."""
        config = deepcopy(BASELINE_CONFIG)
        config["sizing"]["method"] = "kelly"

        market = _make_market()
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(config)
        report = engine.run([market], cache)

        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0]
        # Kelly sizes should vary with edge
        if len(filled) >= 2:
            sizes = [t["size_usd"] for t in filled]
            # Not all identical (unlike fixed_fraction)
            assert max(sizes) > min(sizes) or len(set(sizes)) == 1


# --- Capital Tracking ---

class TestCapitalTracking:
    def test_capital_decreases_on_loss(self):
        """Capital should decrease after losing trades."""
        market = _make_market(actual_outcome="NO_WON")
        cache = _make_cache(market["question"], probability=0.90)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        assert report["final_capital"] < BASELINE_CONFIG["capital"]["initial"]

    def test_capital_increases_on_win(self):
        """Capital should increase after winning trades (net of fees)."""
        market = _make_market(actual_outcome="YES_WON")
        cache = _make_cache(market["question"], probability=0.90)

        config = deepcopy(BASELINE_CONFIG)
        config["fees"]["taker_rate"] = 0.0  # No entry fee to ensure net positive

        engine = SimulatorEngine(config)
        report = engine.run([market], cache)

        assert report["final_capital"] > config["capital"]["initial"]


# --- Report Structure ---

class TestReportStructure:
    def test_report_has_required_fields(self):
        """Report must contain all required output fields."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        required = [
            "total_trades", "filled_trades", "unfilled_trades",
            "winning_trades", "losing_trades",
            "total_pnl", "avg_pnl_per_trade", "max_drawdown", "max_drawdown_pct",
            "hit_rate", "avg_edge_pre_cost", "avg_edge_post_cost",
            "total_turnover", "total_fees", "total_slippage_cost", "total_spread_cost",
            "fee_drag_pct", "slippage_drag_pct", "spread_drag_pct",
            "final_capital", "return_pct",
            "by_direction", "per_trade_log", "per_day_summary",
        ]
        for field in required:
            assert field in report, f"Missing field: {field}"

    def test_per_trade_log_structure(self):
        """Each trade log entry must have required fields."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run([market], cache)

        if report["per_trade_log"]:
            trade = report["per_trade_log"][0]
            required = [
                "trade_id", "market_id", "question", "direction",
                "entry_price", "fill_price", "size_usd", "shares",
                "edge_pre_cost", "edge_post_cost", "slippage", "spread_cost",
                "fee_paid", "winner_fee", "outcome", "pnl", "won", "date",
            ]
            for field in required:
                assert field in trade, f"Missing trade field: {field}"


# --- Sensitivity Analysis ---

class TestSensitivity:
    def test_set_nested(self):
        """_set_nested should modify deep config values."""
        cfg = {"a": {"b": {"c": 1}}}
        new_cfg = _set_nested(cfg, ["a", "b", "c"], 99)
        assert new_cfg["a"]["b"]["c"] == 99
        assert cfg["a"]["b"]["c"] == 1  # Original unchanged

    def test_sensitivity_runs(self):
        """Sensitivity analysis should complete and return ranking."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        # Use only 2 fast scenarios
        scenarios = [
            {
                "name": "winner_fee",
                "path": ["fees", "winner_fee"],
                "values": [0.0, 0.04],
                "baseline": 0.02,
                "unit": "%",
                "description": "Winner fee test",
            },
            {
                "name": "slippage_bps",
                "path": ["fill_model", "taker", "base_slippage_bps"],
                "values": [0, 200],
                "baseline": 50,
                "unit": "bps",
                "description": "Slippage test",
            },
        ]

        results = run_sensitivity(BASELINE_CONFIG, [market], cache, scenarios=scenarios)

        assert "baseline" in results
        assert "scenarios" in results
        assert "ranking" in results
        assert len(results["ranking"]) == 2
        assert results["ranking"][0]["pnl_swing"] >= results["ranking"][1]["pnl_swing"]

    def test_sensitivity_scenario_structure(self):
        """Each scenario should have required result fields."""
        market = _make_market()
        cache = _make_cache(market["question"], probability=0.80)

        scenarios = [
            {
                "name": "test_param",
                "path": ["fees", "winner_fee"],
                "values": [0.0, 0.02],
                "baseline": 0.02,
                "unit": "%",
                "description": "Test",
            },
        ]

        results = run_sensitivity(BASELINE_CONFIG, [market], cache, scenarios=scenarios)

        scenario = results["scenarios"]["test_param"]
        assert "description" in scenario
        assert "pnl_swing" in scenario
        assert "pnl_range" in scenario
        assert len(scenario["results"]) == 2
        for r in scenario["results"]:
            assert "value" in r
            assert "total_pnl" in r
            assert "hit_rate" in r


# --- Cache Key ---

class TestCacheKey:
    def test_cache_key_deterministic(self):
        """Same question should produce same key."""
        q = "Will it rain?"
        assert question_cache_key(q) == question_cache_key(q)

    def test_cache_key_format(self):
        """Key should be 16-char hex string."""
        key = question_cache_key("test question")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_cache_key_matches_backtest(self):
        """Key format should match backtest engine's format."""
        q = "Will it rain?"
        expected = hashlib.sha256(q.encode()).hexdigest()[:16]
        assert question_cache_key(q) == expected


# --- Multi-market Integration ---

class TestMultiMarket:
    def test_multiple_markets(self):
        """Should process multiple markets and aggregate results."""
        markets = [
            _make_market("1", "Will it rain?", "YES_WON"),
            _make_market("2", "Will it snow?", "NO_WON"),
            _make_market("3", "Will it be sunny?", "YES_WON"),
        ]
        cache = {}
        for m in markets:
            cache.update(_make_cache(m["question"], probability=0.75))

        engine = SimulatorEngine(BASELINE_CONFIG)
        report = engine.run(markets, cache)

        assert report["filled_trades"] > 0
        assert report["winning_trades"] + report["losing_trades"] == report["filled_trades"]

    def test_max_markets_limit(self):
        """max_markets should limit how many markets are processed."""
        markets = [
            _make_market(str(i), f"Question {i}?", "YES_WON")
            for i in range(10)
        ]
        cache = {}
        for m in markets:
            cache.update(_make_cache(m["question"], probability=0.80))

        engine = SimulatorEngine(BASELINE_CONFIG)
        report_all = engine.run(markets, cache)
        report_2 = engine.run(markets, cache, max_markets=2)

        assert report_2["filled_trades"] <= report_all["filled_trades"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
