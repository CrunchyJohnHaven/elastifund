"""Unit tests for the fill model."""

import sys
import random
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fill_model import (
    classify_market_tier,
    get_half_spread,
    compute_taker_slippage,
    compute_maker_fill_probability,
    simulate_taker_fill,
    simulate_maker_fill,
    simulate_fill,
    FillResult,
)

SPREAD_CONFIG = {
    "high_volume": {"half_spread_cents": 1.5, "min_liquidity": 10000},
    "us_weather": {"half_spread_cents": 7.0, "min_liquidity": 2000},
    "international": {"half_spread_cents": 20.0, "min_liquidity": 500},
    "niche": {"half_spread_cents": 22.0, "min_liquidity": 100},
    "default": {"half_spread_cents": 5.0, "min_liquidity": 500},
}

TAKER_CONFIG = {
    "base_slippage_bps": 50,
    "size_impact_bps_per_dollar": 2,
    "liquidity_impact_factor": 0.001,
    "fill_probability": 1.0,
}

MAKER_CONFIG = {
    "base_fill_probability": 0.55,
    "distance_decay": 2.0,
    "min_fill_probability": 0.10,
    "price_improvement_bps": 0,
}

FULL_CONFIG = {
    "execution": {"mode": "taker", "min_edge_threshold": 0.05, "max_concurrent_positions": 50},
    "fees": {"taker_rate": 0.02, "maker_rate": 0.0, "winner_fee": 0.02},
    "fill_model": {
        "taker": TAKER_CONFIG,
        "maker": MAKER_CONFIG,
        "spreads": SPREAD_CONFIG,
    },
    "sizing": {"method": "fixed_fraction", "fixed_fraction": {"fraction": 0.027}},
    "capital": {"initial": 75.0},
    "filters": {"min_liquidity": 500, "min_volume": 1000, "price_range": [0.10, 0.90]},
    "random_seed": 42,
}


# --- Market tier classification ---

def test_classify_high_volume():
    assert classify_market_tier(100000, 15000) == "high_volume"

def test_classify_us_weather():
    assert classify_market_tier(10000, 3000) == "us_weather"

def test_classify_international():
    assert classify_market_tier(2000, 600) == "international"

def test_classify_niche():
    assert classify_market_tier(50, 50) == "niche"


# --- Half-spread ---

def test_half_spread_high_volume():
    spread = get_half_spread("high_volume", SPREAD_CONFIG)
    assert abs(spread - 0.015) < 1e-6

def test_half_spread_niche():
    spread = get_half_spread("niche", SPREAD_CONFIG)
    assert abs(spread - 0.22) < 1e-6

def test_half_spread_default_fallback():
    spread = get_half_spread("unknown_tier", SPREAD_CONFIG)
    assert abs(spread - 0.05) < 1e-6


# --- Taker slippage ---

def test_taker_slippage_small_order():
    slip = compute_taker_slippage(2.0, 10000, TAKER_CONFIG)
    # base: 50/10000=0.005, size: 2*2/10000=0.0004, liq: 0.001*2/10000=0.0000002
    expected = 0.005 + 0.0004 + 0.0000002
    assert abs(slip - expected) < 1e-7

def test_taker_slippage_large_order():
    slip = compute_taker_slippage(100.0, 500, TAKER_CONFIG)
    # Should be larger due to size and low liquidity
    assert slip > 0.01

def test_taker_slippage_increases_with_size():
    slip_small = compute_taker_slippage(1.0, 5000, TAKER_CONFIG)
    slip_large = compute_taker_slippage(50.0, 5000, TAKER_CONFIG)
    assert slip_large > slip_small


# --- Maker fill probability ---

def test_maker_fill_prob_zero_edge():
    prob = compute_maker_fill_probability(0.0, MAKER_CONFIG)
    assert abs(prob - 0.55) < 1e-6

def test_maker_fill_prob_high_edge():
    prob = compute_maker_fill_probability(0.5, MAKER_CONFIG)
    assert prob < 0.55  # Should decay
    assert prob >= 0.10  # Floor

def test_maker_fill_prob_floor():
    prob = compute_maker_fill_probability(10.0, MAKER_CONFIG)
    assert abs(prob - 0.10) < 1e-6  # Should hit floor

def test_maker_fill_prob_moderate_edge():
    prob = compute_maker_fill_probability(0.10, MAKER_CONFIG)
    # 0.55 * exp(-2 * 0.10) = 0.55 * exp(-0.2) ≈ 0.55 * 0.8187 ≈ 0.4503
    assert 0.44 < prob < 0.46


# --- Taker fill simulation ---

def test_taker_fill_always_fills():
    result = simulate_taker_fill(
        market_price=0.50, direction="buy_yes", edge=0.10,
        order_size_usd=2.0, volume=10000, liquidity=5000,
        taker_config=TAKER_CONFIG, spread_config=SPREAD_CONFIG,
        fee_rate=0.02, winner_fee_rate=0.02,
    )
    assert result.filled is True

def test_taker_fill_buy_yes_price_higher_than_mid():
    result = simulate_taker_fill(
        market_price=0.50, direction="buy_yes", edge=0.10,
        order_size_usd=2.0, volume=10000, liquidity=5000,
        taker_config=TAKER_CONFIG, spread_config=SPREAD_CONFIG,
        fee_rate=0.02, winner_fee_rate=0.02,
    )
    assert result.fill_price > 0.50  # Should be above mid due to spread+slippage

def test_taker_fill_buy_no():
    result = simulate_taker_fill(
        market_price=0.70, direction="buy_no", edge=0.15,
        order_size_usd=2.0, volume=50000, liquidity=12000,
        taker_config=TAKER_CONFIG, spread_config=SPREAD_CONFIG,
        fee_rate=0.02, winner_fee_rate=0.02,
    )
    assert result.filled is True
    # buy_no base = 1 - 0.70 = 0.30, should be > 0.30
    assert result.fill_price > 0.30

def test_taker_fill_has_fee():
    result = simulate_taker_fill(
        market_price=0.50, direction="buy_yes", edge=0.10,
        order_size_usd=10.0, volume=10000, liquidity=5000,
        taker_config=TAKER_CONFIG, spread_config=SPREAD_CONFIG,
        fee_rate=0.02, winner_fee_rate=0.02,
    )
    assert abs(result.fee - 0.20) < 1e-6  # 2% of $10

def test_taker_fill_price_capped():
    result = simulate_taker_fill(
        market_price=0.98, direction="buy_yes", edge=0.01,
        order_size_usd=2.0, volume=100, liquidity=100,
        taker_config=TAKER_CONFIG, spread_config=SPREAD_CONFIG,
        fee_rate=0.02, winner_fee_rate=0.02,
    )
    assert result.fill_price <= 0.99


# --- Maker fill simulation ---

def test_maker_fill_probabilistic():
    rng = random.Random(42)
    filled_count = 0
    total = 1000
    for _ in range(total):
        result = simulate_maker_fill(
            market_price=0.50, direction="buy_yes", edge=0.10,
            order_size_usd=2.0, volume=10000, liquidity=5000,
            maker_config=MAKER_CONFIG, spread_config=SPREAD_CONFIG,
            fee_rate=0.0, winner_fee_rate=0.02, rng=rng,
        )
        if result.filled:
            filled_count += 1
    # Expected fill rate ≈ 0.55 * exp(-2 * 0.10) ≈ 0.45
    fill_rate = filled_count / total
    assert 0.35 < fill_rate < 0.55

def test_maker_fill_no_spread_cost():
    rng = random.Random(1)  # Seed that produces fill
    # Run until we get a fill
    for _ in range(100):
        result = simulate_maker_fill(
            market_price=0.50, direction="buy_yes", edge=0.05,
            order_size_usd=2.0, volume=10000, liquidity=5000,
            maker_config=MAKER_CONFIG, spread_config=SPREAD_CONFIG,
            fee_rate=0.0, winner_fee_rate=0.02, rng=rng,
        )
        if result.filled:
            assert result.spread_cost == 0.0
            assert result.slippage == 0.0
            break

def test_maker_unfilled_zero_cost():
    # Force unfilled with very high edge → very low fill prob
    high_edge_maker = {**MAKER_CONFIG, "base_fill_probability": 0.01, "min_fill_probability": 0.01}
    rng = random.Random(42)
    result = simulate_maker_fill(
        market_price=0.50, direction="buy_yes", edge=5.0,
        order_size_usd=2.0, volume=10000, liquidity=5000,
        maker_config=high_edge_maker, spread_config=SPREAD_CONFIG,
        fee_rate=0.0, winner_fee_rate=0.02, rng=rng,
    )
    if not result.filled:
        assert result.total_cost == 0.0
        assert result.fee == 0.0


# --- Top-level dispatch ---

def test_simulate_fill_taker_mode():
    result = simulate_fill(
        market_price=0.50, direction="buy_yes", edge=0.10,
        order_size_usd=2.0, volume=10000, liquidity=5000,
        config=FULL_CONFIG,
    )
    assert result.filled is True

def test_simulate_fill_maker_mode():
    maker_config = {**FULL_CONFIG, "execution": {**FULL_CONFIG["execution"], "mode": "maker"}}
    rng = random.Random(42)
    # Run multiple times to test both fill and no-fill paths
    results = []
    for _ in range(20):
        r = simulate_fill(
            market_price=0.50, direction="buy_yes", edge=0.10,
            order_size_usd=2.0, volume=10000, liquidity=5000,
            config=maker_config, rng=rng,
        )
        results.append(r)
    # Should have a mix of fills and non-fills
    filled = sum(1 for r in results if r.filled)
    assert 0 < filled < 20

def test_simulate_fill_invalid_mode():
    bad_config = {**FULL_CONFIG, "execution": {**FULL_CONFIG["execution"], "mode": "invalid"}}
    try:
        simulate_fill(
            market_price=0.50, direction="buy_yes", edge=0.10,
            order_size_usd=2.0, volume=10000, liquidity=5000,
            config=bad_config,
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# --- Reproducibility ---

def test_reproducibility_with_seed():
    """Same seed → same results for maker fills."""
    maker_config = {**FULL_CONFIG, "execution": {**FULL_CONFIG["execution"], "mode": "maker"}}

    def run_sequence():
        rng = random.Random(42)
        return [
            simulate_fill(
                market_price=0.50, direction="buy_yes", edge=0.10,
                order_size_usd=2.0, volume=10000, liquidity=5000,
                config=maker_config, rng=rng,
            ).filled
            for _ in range(50)
        ]

    seq1 = run_sequence()
    seq2 = run_sequence()
    assert seq1 == seq2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
