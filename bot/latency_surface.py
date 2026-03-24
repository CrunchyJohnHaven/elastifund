"""
Latency Surface — Truth Feed vs Venue Lag Measurement Harness
==============================================================
Dispatch: DISPATCH_107 (Deep Research Integration)

Measures the timing gap between public truth feeds (Binance, FRED, NWS)
and prediction market venue prices (Polymarket, Kalshi). When the gap
exceeds threshold after costs, generates a LatencySignal.

This is Experiment A from the deep research report: the highest ROI
prerequisite for all other edge families.

Architecture:
    Truth Feed (Binance WS / FRED / NWS) → Fair Value Estimate
    Venue Feed (Polymarket WS / Kalshi WS) → Venue Mid Price
    price_error = venue_mid - fair_value
    If |price_error| > threshold → LatencySignal

Signal Source: #7 in jj_live.py

Author: JJ (autonomous)
Date: 2026-03-23
"""

import asyncio
import json
import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("JJ.latency_surface")

try:
    from bot.net_edge_accounting import (
        CostBreakdown,
        FeeSchedule,
        evaluate_edge,
        net_edge,
    )
except ImportError:
    from net_edge_accounting import (  # type: ignore
        CostBreakdown,
        FeeSchedule,
        evaluate_edge,
        net_edge,
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TruthSource(Enum):
    BINANCE_SPOT = "binance_spot"
    FRED_MACRO = "fred_macro"
    NWS_WEATHER = "nws_weather"
    BLS_LABOR = "bls_labor"
    NOAA_FORECAST = "noaa_forecast"


@dataclass
class LatencyConfig:
    """Configuration for latency surface measurement."""
    # Minimum price error (in probability units) to generate signal
    min_price_error: float = 0.03
    # Maximum staleness of truth feed (seconds)
    max_truth_staleness_s: float = 5.0
    # Maximum staleness of venue feed (seconds)
    max_venue_staleness_s: float = 30.0
    # Rolling window size for lag distribution
    lag_window_size: int = 500
    # Minimum observations before generating signals
    min_observations: int = 50
    # Minimum net edge (bps) to consider tradeable
    min_net_edge_bps: float = 15.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TruthTick:
    """A timestamped observation from a truth feed."""
    source: TruthSource
    value: float          # raw value (price, temperature, rate, etc.)
    ts_source: float      # source timestamp (exchange time)
    ts_recv: float        # local receive timestamp
    metadata: dict = field(default_factory=dict)


@dataclass
class VenueTick:
    """A timestamped observation from a prediction market venue."""
    venue: str            # "polymarket" or "kalshi"
    market_id: str
    token_id: str
    bid: float
    ask: float
    ts_recv: float
    ts_venue: Optional[float] = None  # venue timestamp if provided

    @property
    def mid(self) -> float:
        if self.bid <= 0 and self.ask <= 0:
            return 0.0
        if self.bid <= 0:
            return self.ask
        if self.ask <= 0:
            return self.bid
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 1.0  # max spread
        return self.ask - self.bid


@dataclass
class LatencySignal:
    """Generated when truth-feed-to-venue lag creates tradeable mispricing."""
    market_id: str
    token_id: str
    venue: str
    truth_source: TruthSource
    fair_value: float       # probability from truth feed
    venue_mid: float        # current venue midpoint
    price_error: float      # venue_mid - fair_value
    edge_bps: float         # |price_error| * 10000
    net_edge_bps: float     # after costs
    side: str               # "BUY_YES" or "BUY_NO"
    lag_median_ms: float    # median truth-to-venue lag
    lag_p95_ms: float       # 95th percentile lag
    ts: float
    confidence: float = 0.0  # 0-1 confidence in the signal


@dataclass
class LagMeasurement:
    """Single measurement of truth-to-venue timing gap."""
    truth_ts: float
    venue_ts: float
    lag_ms: float          # venue_ts - truth_ts in milliseconds
    price_error: float     # how wrong the venue was at the time


# ---------------------------------------------------------------------------
# Fair value computation (truth feed → probability)
# ---------------------------------------------------------------------------

def compute_fair_probability_crypto(
    truth_price: float,
    strike: float,
    sigma_proxy: float = 0.50,
    time_to_expiry_s: float = 300.0,
) -> float:
    """
    Map a crypto spot price into a probability for a binary contract.

    For BTC 5-minute candle contracts:
        P(price > strike at expiry) ~ Phi((S - K) / (sigma * sqrt(T) * K))

    Uses logistic approximation to normal CDF for speed.
    """
    if time_to_expiry_s <= 0:
        # Already expired: deterministic
        return 1.0 if truth_price > strike else 0.0

    T_years = time_to_expiry_s / (365.25 * 24 * 3600)
    denom = sigma_proxy * math.sqrt(max(T_years, 1e-10)) * max(strike, 1e-10)
    z = (truth_price - strike) / denom

    # Logistic approximation to Phi(z)
    return 1.0 / (1.0 + math.exp(-1.7 * z))


def compute_fair_probability_threshold(
    truth_value: float,
    threshold: float,
    sigma: float,
    direction: str = "above",
) -> float:
    """
    Map a continuous truth value to a probability for threshold contracts.

    For Kalshi-style "Will X be above/below Y?" contracts:
        P(X > threshold) ~ Phi((truth - threshold) / sigma)

    Works for weather, economic data, etc.
    """
    if sigma <= 0:
        if direction == "above":
            return 1.0 if truth_value > threshold else 0.0
        else:
            return 1.0 if truth_value < threshold else 0.0

    z = (truth_value - threshold) / sigma
    prob = 1.0 / (1.0 + math.exp(-1.7 * z))

    if direction == "below":
        prob = 1.0 - prob

    return prob


# ---------------------------------------------------------------------------
# Latency Surface Engine
# ---------------------------------------------------------------------------

class LatencySurface:
    """
    Measures and exploits truth-feed-to-venue timing gaps.

    Maintains rolling statistics on lag distributions per market/truth-source
    pair. Generates LatencySignal when mispricing exceeds threshold.

    Usage:
        surface = LatencySurface()
        surface.on_truth_tick(truth_tick)
        surface.on_venue_tick(venue_tick)
        signals = surface.get_pending_signals()
    """

    def __init__(self, config: Optional[LatencyConfig] = None):
        self.config = config or LatencyConfig()
        # Latest truth value per source
        self._truth_latest: dict[TruthSource, TruthTick] = {}
        # Lag measurements per (market_id, truth_source)
        self._lag_history: dict[tuple[str, TruthSource], deque[LagMeasurement]] = {}
        # Pending signals (consumed by jj_live.py)
        self._pending_signals: list[LatencySignal] = []
        # Market-to-truth-source mapping (configured externally)
        self._market_truth_map: dict[str, tuple[TruthSource, dict]] = {}
        # Statistics cache
        self._stats_cache: dict[tuple[str, TruthSource], dict] = {}

    def register_market(self, market_id: str, truth_source: TruthSource,
                        contract_spec: dict) -> None:
        """Register a market with its truth source and contract specification."""
        self._market_truth_map[market_id] = (truth_source, contract_spec)
        key = (market_id, truth_source)
        if key not in self._lag_history:
            self._lag_history[key] = deque(maxlen=self.config.lag_window_size)

    def on_truth_tick(self, tick: TruthTick) -> None:
        """Process a new truth feed observation."""
        self._truth_latest[tick.source] = tick

    def on_venue_tick(self, tick: VenueTick) -> Optional[LatencySignal]:
        """
        Process a new venue price update. If a registered truth source
        exists for this market and mispricing exceeds threshold, generate
        a LatencySignal.
        """
        if tick.market_id not in self._market_truth_map:
            return None

        truth_source, spec = self._market_truth_map[tick.market_id]
        truth_tick = self._truth_latest.get(truth_source)

        if truth_tick is None:
            return None

        # Staleness checks
        now = time.time()
        if now - truth_tick.ts_recv > self.config.max_truth_staleness_s:
            return None
        if now - tick.ts_recv > self.config.max_venue_staleness_s:
            return None

        # Compute fair value from truth
        fair_value = self._compute_fair_value(truth_tick, spec)
        if fair_value is None:
            return None

        # Measure lag
        lag_ms = (tick.ts_recv - truth_tick.ts_recv) * 1000
        price_error = tick.mid - fair_value

        measurement = LagMeasurement(
            truth_ts=truth_tick.ts_recv,
            venue_ts=tick.ts_recv,
            lag_ms=lag_ms,
            price_error=price_error,
        )

        key = (tick.market_id, truth_source)
        self._lag_history[key].append(measurement)
        self._update_stats(key)

        # Check if price error exceeds threshold
        if abs(price_error) < self.config.min_price_error:
            return None

        # Need minimum observations
        if len(self._lag_history[key]) < self.config.min_observations:
            return None

        # Compute edge
        edge_bps = abs(price_error) * 10_000
        side = "BUY_NO" if price_error > 0 else "BUY_YES"  # venue overpriced → sell YES / buy NO

        # Get lag stats
        stats = self._stats_cache.get(key, {})
        lag_median = stats.get("lag_median_ms", 0.0)
        lag_p95 = stats.get("lag_p95_ms", 0.0)

        # Evaluate net edge
        fee_sched = (FeeSchedule.polymarket() if tick.venue == "polymarket"
                     else FeeSchedule.kalshi())
        edge_result = evaluate_edge(
            gross_edge_bps=edge_bps,
            p_fill=0.80,  # conservative maker fill assumption
            p_win=0.55 + abs(price_error) * 0.5,  # scale confidence with error size
            position_usd=5.0,
            hours_locked=0.5,
            fee_schedule=fee_sched,
            spread_bps=tick.spread * 10_000,
            is_maker=True,
            min_net_edge_bps=self.config.min_net_edge_bps,
        )

        if not edge_result.is_tradeable:
            return None

        signal = LatencySignal(
            market_id=tick.market_id,
            token_id=tick.token_id,
            venue=tick.venue,
            truth_source=truth_source,
            fair_value=fair_value,
            venue_mid=tick.mid,
            price_error=price_error,
            edge_bps=edge_bps,
            net_edge_bps=edge_result.net_edge_bps,
            side=side,
            lag_median_ms=lag_median,
            lag_p95_ms=lag_p95,
            ts=now,
            confidence=min(1.0, edge_bps / 500),
        )

        self._pending_signals.append(signal)
        logger.info(
            "LATENCY_SIGNAL: %s %s fair=%.4f venue=%.4f error=%.4f net_edge=%.1fbps lag_p95=%.0fms",
            signal.side, tick.market_id, fair_value, tick.mid,
            price_error, edge_result.net_edge_bps, lag_p95,
        )

        return signal

    def get_pending_signals(self) -> list[LatencySignal]:
        """Drain and return all pending signals."""
        signals = self._pending_signals.copy()
        self._pending_signals.clear()
        return signals

    def get_lag_stats(self, market_id: str,
                      truth_source: TruthSource) -> dict:
        """Get current lag distribution statistics for a market."""
        key = (market_id, truth_source)
        return self._stats_cache.get(key, {})

    def get_all_stats(self) -> dict[str, dict]:
        """Get lag statistics for all registered markets."""
        result = {}
        for (market_id, source), stats in self._stats_cache.items():
            result[f"{market_id}:{source.value}"] = stats
        return result

    # --- internal ---

    def _compute_fair_value(self, truth: TruthTick,
                            spec: dict) -> Optional[float]:
        """Compute fair probability from truth tick and contract spec."""
        contract_type = spec.get("type", "threshold")

        if contract_type == "crypto_candle":
            return compute_fair_probability_crypto(
                truth_price=truth.value,
                strike=spec.get("strike", truth.value),
                sigma_proxy=spec.get("sigma_proxy", 0.50),
                time_to_expiry_s=spec.get("time_to_expiry_s", 300),
            )
        elif contract_type == "threshold":
            return compute_fair_probability_threshold(
                truth_value=truth.value,
                threshold=spec.get("threshold", 0),
                sigma=spec.get("sigma", 1.0),
                direction=spec.get("direction", "above"),
            )
        else:
            logger.warning("Unknown contract type: %s", contract_type)
            return None

    def _update_stats(self, key: tuple[str, TruthSource]) -> None:
        """Update cached statistics for a market/source pair."""
        history = self._lag_history.get(key, deque())
        if len(history) < 3:
            return

        lags = [m.lag_ms for m in history]
        errors = [abs(m.price_error) for m in history]

        sorted_lags = sorted(lags)
        n = len(sorted_lags)

        self._stats_cache[key] = {
            "lag_median_ms": statistics.median(sorted_lags),
            "lag_mean_ms": statistics.mean(sorted_lags),
            "lag_p95_ms": sorted_lags[int(n * 0.95)] if n >= 20 else sorted_lags[-1],
            "lag_p99_ms": sorted_lags[int(n * 0.99)] if n >= 100 else sorted_lags[-1],
            "error_median": statistics.median(errors),
            "error_mean": statistics.mean(errors),
            "observation_count": n,
            "last_update": time.time(),
        }
