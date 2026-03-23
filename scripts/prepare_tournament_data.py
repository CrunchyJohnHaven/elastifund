#!/usr/bin/env python3
"""
Data Preparation Pipeline — Convert Historical Markets to Tournament Format
============================================================================
Takes historical resolved markets and generates the pre-computed signal
features that the Tournament Engine needs. This runs ONCE to prepare data,
then the Tournament Engine can evaluate thousands of genomes against it.

Input: backtest/data/historical_markets.json (from collector.py)
       + cached Claude probability estimates
       + any available order book / trade tape data

Output: /tmp/tournament_data.json
        Each entry has pre-computed signals from all 11 strategy sources,
        plus market metadata needed for filtering.

This is the bridge between raw market data and the Strategy Genome system.

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("JJ.prepare_tournament_data")

# Repo root
REPO_ROOT = Path(os.environ.get("ELASTIFUND_ROOT", "/Users/johnbradley/Desktop/Elastifund"))


def load_historical_markets(path: Path | None = None) -> list[dict]:
    """Load resolved markets from the backtesting data store."""
    if path is None:
        path = REPO_ROOT / "backtest" / "data" / "historical_markets.json"

    if not path.exists():
        logger.warning("Historical markets not found at %s", path)
        return []

    with open(path) as f:
        data = json.load(f)

    # Handle both list and dict formats
    if isinstance(data, dict):
        markets = data.get("markets", [])
    else:
        markets = data

    logger.info("Loaded %d historical markets from %s", len(markets), path)
    return markets


def load_claude_cache(path: Path | None = None) -> dict[str, float]:
    """Load cached Claude probability estimates."""
    if path is None:
        path = REPO_ROOT / "backtest" / "data" / "claude_cache.json"

    if not path.exists():
        return {}

    with open(path) as f:
        data = json.load(f)

    # Map condition_id -> probability
    cache = {}
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, (int, float)):
                cache[key] = float(val)
            elif isinstance(val, dict):
                cache[key] = float(val.get("probability", val.get("prob", 0.5)))

    logger.info("Loaded %d Claude estimates from cache", len(cache))
    return cache


def compute_signal_features(market: dict, claude_prob: float, rng: random.Random) -> dict:
    """
    Compute synthetic signal features for a market.

    In production, these come from live signal sources. For backtesting,
    we derive them from market characteristics + noise. This is intentionally
    approximate — the goal is to test COMBINATIONS of signals, not to
    perfectly replay history.

    Each signal is in [-1, 1]:
      > 0 = YES signal (buy YES)
      < 0 = NO signal (buy NO)
      magnitude = signal strength
    """
    # Market characteristics
    yes_price = float(market.get("final_yes_price", market.get("yes_price", 0.5)))
    no_price = 1.0 - yes_price
    volume = float(market.get("volume", 0))
    outcome = market.get("actual_outcome", market.get("outcome", ""))

    # Normalize outcome
    if outcome in ("YES_WON", "YES", "yes", "Up", "UP"):
        outcome_str = "YES_WON"
    elif outcome in ("NO_WON", "NO", "no", "Down", "DOWN"):
        outcome_str = "NO_WON"
    else:
        return {}  # Skip unresolved

    # Claude-based directional signal
    claude_direction = 1.0 if claude_prob > 0.5 else -1.0
    claude_strength = abs(claude_prob - 0.5) * 2.0  # Scale to [0, 1]

    # Generate synthetic signals from different "sources"
    # Each adds independent noise to simulate imperfect signal sources
    noise_scale = 0.15  # How noisy each source is

    # Base signal: which way the market actually went (with HEAVY noise)
    # Signal quality is deliberately LOW to simulate realistic conditions
    # where individual signals are barely better than coin flips.
    # The evolution engine must find COMBINATIONS that compound weak signals.
    true_direction = 1.0 if outcome_str == "YES_WON" else -1.0

    def noisy_signal(signal_quality: float, noise_floor: float = 0.50) -> float:
        """
        Signal = true_direction * quality + noise.
        Quality 0.1 with noise 0.5 means the signal is right ~55% of the time.
        This is realistic: individual signals are weak. Combinations win.
        """
        base = true_direction * signal_quality
        noise = rng.gauss(0, noise_floor)
        return max(-1.0, min(1.0, base + noise))

    # Mean reversion: counter-trend (opposite of momentum)
    price_momentum = (yes_price - 0.5) * 2.0
    sig_mean_reversion = noisy_signal(0.08 - price_momentum * 0.15, 0.45)

    # Time of day: weak directional bias
    hour_et = rng.randint(0, 23)
    tod_bias = -0.05 if 3 <= hour_et <= 6 else 0.02 if 8 <= hour_et <= 16 else 0.0
    sig_time_of_day = noisy_signal(0.06 + tod_bias, 0.50)

    # Book imbalance: moderate quality
    sig_book_imbalance = noisy_signal(0.10, 0.45)

    # Wallet flow: weak
    sig_wallet_flow = noisy_signal(0.05, 0.55)

    # Informed flow: moderate
    sig_informed_flow = noisy_signal(0.09, 0.47)

    # Cross-timeframe: good confirmation signal
    sig_cross_timeframe = noisy_signal(0.12, 0.42)

    # Vol regime: contextual, weak individual
    sig_vol_regime = noisy_signal(0.04, 0.52)

    # Residual horizon: time-decay
    sig_residual_horizon = noisy_signal(0.07, 0.48)

    # ML scanner: moderate ensemble
    sig_ml_scanner = noisy_signal(0.08, 0.46)

    # Indicator consensus: moderate
    sig_indicator_consensus = noisy_signal(0.07, 0.48)

    # Chainlink basis: reference price
    sig_chainlink_basis = noisy_signal(0.05, 0.52)

    # Market metadata for filtering
    vpin = rng.uniform(0.2, 0.8)  # Simulated toxicity
    spread = rng.uniform(0.01, 0.20)  # Simulated spread
    book_imbalance = rng.gauss(0, 0.3)  # Simulated imbalance

    # Entry price: use calibrated Claude estimate or market price
    entry_price = max(0.50, min(0.98, claude_prob if claude_prob > 0 else yes_price))

    return {
        "condition_id": market.get("id", market.get("condition_id", "")),
        "outcome": outcome_str,
        "entry_price": round(entry_price, 4),
        "yes_price": round(yes_price, 4),
        "volume": volume,
        "hour_et": hour_et,
        "vpin": round(vpin, 4),
        "spread": round(spread, 4),
        "book_imbalance": round(book_imbalance, 4),
        # Signal features
        "sig_mean_reversion": round(sig_mean_reversion, 4),
        "sig_time_of_day": round(sig_time_of_day, 4),
        "sig_book_imbalance": round(sig_book_imbalance, 4),
        "sig_wallet_flow": round(sig_wallet_flow, 4),
        "sig_informed_flow": round(sig_informed_flow, 4),
        "sig_cross_timeframe": round(sig_cross_timeframe, 4),
        "sig_vol_regime": round(sig_vol_regime, 4),
        "sig_residual_horizon": round(sig_residual_horizon, 4),
        "sig_ml_scanner": round(sig_ml_scanner, 4),
        "sig_indicator_consensus": round(sig_indicator_consensus, 4),
        "sig_chainlink_basis": round(sig_chainlink_basis, 4),
    }


def prepare_tournament_data(
    output_path: str = "/tmp/tournament_data.json",
    min_volume: float = 100.0,
    seed: int = 42,
) -> str:
    """
    Main pipeline: load markets, compute features, write tournament data.

    Returns path to the output file.
    """
    rng = random.Random(seed)

    # Load data
    markets = load_historical_markets()
    claude_cache = load_claude_cache()

    if not markets:
        logger.error("No historical markets found. Run backtest/collector.py first.")
        # Generate synthetic data for development/testing
        logger.info("Generating synthetic tournament data for testing...")
        data = _generate_synthetic_data(500, rng)
    else:
        # Process real markets
        data = []
        for market in markets:
            mid = market.get("id", market.get("condition_id", ""))
            volume = float(market.get("volume", 0))
            if volume < min_volume:
                continue

            claude_prob = claude_cache.get(mid, 0.0)
            if claude_prob <= 0:
                # Use market price as fallback
                claude_prob = float(market.get("final_yes_price", market.get("yes_price", 0.5)))

            features = compute_signal_features(market, claude_prob, rng)
            if features:
                data.append(features)

    # Write output
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Tournament data: %d markets written to %s", len(data), output_path)
    return output_path


def _generate_synthetic_data(n: int, rng: random.Random) -> list[dict]:
    """Generate synthetic market data for development/testing."""
    data = []
    for i in range(n):
        # Random outcome
        outcome = "YES_WON" if rng.random() > 0.48 else "NO_WON"  # Slight NO bias
        true_dir = 1.0 if outcome == "YES_WON" else -1.0

        # Signal quality is deliberately weak (realistic)
        def sig(quality: float) -> float:
            noise = rng.gauss(0, 0.50)
            return max(-1.0, min(1.0, true_dir * quality + noise))

        entry_price = rng.uniform(0.55, 0.95)

        data.append({
            "condition_id": f"synth_{i:05d}",
            "outcome": outcome,
            "entry_price": round(entry_price, 4),
            "yes_price": round(entry_price if outcome == "YES_WON" else 1 - entry_price, 4),
            "volume": rng.uniform(100, 50000),
            "hour_et": rng.randint(0, 23),
            "vpin": round(rng.uniform(0.1, 0.9), 4),
            "spread": round(rng.uniform(0.01, 0.25), 4),
            "book_imbalance": round(rng.gauss(0, 0.3), 4),
            "sig_mean_reversion": round(sig(0.35), 4),
            "sig_time_of_day": round(sig(0.25), 4),
            "sig_book_imbalance": round(sig(0.40), 4),
            "sig_wallet_flow": round(sig(0.20), 4),
            "sig_informed_flow": round(sig(0.30), 4),
            "sig_cross_timeframe": round(sig(0.40), 4),
            "sig_vol_regime": round(sig(0.20), 4),
            "sig_residual_horizon": round(sig(0.25), 4),
            "sig_ml_scanner": round(sig(0.30), 4),
            "sig_indicator_consensus": round(sig(0.25), 4),
            "sig_chainlink_basis": round(sig(0.20), 4),
        })
    return data


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    output = prepare_tournament_data()
    print(f"Tournament data ready: {output}")
