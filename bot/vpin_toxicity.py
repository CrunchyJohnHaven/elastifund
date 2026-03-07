#!/usr/bin/env python3
"""
VPIN (Volume-Synchronized Probability of Informed Trading) Toxicity Detector
============================================================================
Dispatch #75 — Strategy A-1: VPIN-Guided Order Flow Toxicity Fade

Calculates real-time VPIN on Polymarket CLOB trade data to detect when
order flow becomes toxic (informed traders front-running your maker quotes).

Signal Logic:
  - Group volume into equal-sized buckets (default: 500 shares)
  - Calculate absolute buy/sell imbalance per bucket
  - Rolling window of N buckets (default: 10)
  - VPIN > 0.75 → PULL all resting maker orders (toxic flow incoming)
  - VPIN < 0.25 → TIGHTEN spread to capture 20% maker rebate (safe flow)

Kill Criterion: OOS EV negative after 100 simulated fills.

Author: JJ (autonomous)
Date: 2026-03-07
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class FlowRegime(Enum):
    """Current order flow toxicity regime."""
    TOXIC = "toxic"           # VPIN > 0.75 — pull quotes
    NEUTRAL = "neutral"       # 0.25 <= VPIN <= 0.75 — normal quoting
    SAFE = "safe"             # VPIN < 0.25 — tighten spread, farm rebates


@dataclass
class TradeTick:
    """A single trade from the CLOB WebSocket."""
    timestamp: float         # Unix timestamp
    price: float             # Execution price (0-1)
    size: float              # Number of shares
    side: str                # "buy" or "sell" (aggressor side)
    market_id: str = ""


@dataclass
class VolumeBucket:
    """Equal-volume bucket for VPIN calculation."""
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    total_volume: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    trade_count: int = 0

    @property
    def imbalance(self) -> float:
        """Absolute volume imbalance as fraction of total."""
        if self.total_volume == 0:
            return 0.0
        return abs(self.buy_volume - self.sell_volume) / self.total_volume


@dataclass
class VPINState:
    """VPIN calculation state for a single market."""
    market_id: str
    bucket_size: float = 500.0       # Shares per bucket
    window_size: int = 10            # Rolling window of buckets
    toxic_threshold: float = 0.75    # Pull quotes above this
    safe_threshold: float = 0.25     # Tighten spread below this

    # Internal state
    completed_buckets: deque = field(default_factory=lambda: deque(maxlen=50))
    current_bucket: VolumeBucket = field(default_factory=VolumeBucket)
    _accumulated_volume: float = 0.0
    _last_vpin: float = 0.5
    _last_regime: FlowRegime = FlowRegime.NEUTRAL
    _last_update: float = 0.0
    _total_trades_processed: int = 0

    def process_trade(self, trade: TradeTick) -> Optional[float]:
        """
        Process a new trade tick and return VPIN if a bucket was completed.

        Returns:
            VPIN value if a new bucket was completed, None otherwise.
        """
        self._total_trades_processed += 1

        # Initialize bucket timestamp
        if self.current_bucket.start_time == 0:
            self.current_bucket.start_time = trade.timestamp

        # Accumulate volume
        remaining = trade.size
        vpin_result = None

        while remaining > 0:
            space_in_bucket = self.bucket_size - self.current_bucket.total_volume
            fill = min(remaining, space_in_bucket)

            if trade.side == "buy":
                self.current_bucket.buy_volume += fill
            else:
                self.current_bucket.sell_volume += fill

            self.current_bucket.total_volume += fill
            self.current_bucket.trade_count += 1
            self.current_bucket.end_time = trade.timestamp
            remaining -= fill

            # Bucket complete
            if self.current_bucket.total_volume >= self.bucket_size:
                self.completed_buckets.append(self.current_bucket)
                self.current_bucket = VolumeBucket(start_time=trade.timestamp)

                # Calculate VPIN if we have enough buckets
                if len(self.completed_buckets) >= self.window_size:
                    vpin_result = self._calculate_vpin()

        return vpin_result

    def _calculate_vpin(self) -> float:
        """Calculate VPIN over the rolling window of completed buckets."""
        window = list(self.completed_buckets)[-self.window_size:]
        total_imbalance = sum(b.imbalance for b in window)
        vpin = total_imbalance / len(window)

        self._last_vpin = vpin
        self._last_update = time.time()
        self._last_regime = self._classify_regime(vpin)

        return vpin

    def _classify_regime(self, vpin: float) -> FlowRegime:
        """Classify VPIN into a flow regime."""
        if vpin > self.toxic_threshold:
            return FlowRegime.TOXIC
        elif vpin < self.safe_threshold:
            return FlowRegime.SAFE
        return FlowRegime.NEUTRAL

    @property
    def regime(self) -> FlowRegime:
        """Current flow regime."""
        return self._last_regime

    @property
    def vpin(self) -> float:
        """Last calculated VPIN value."""
        return self._last_vpin

    @property
    def is_ready(self) -> bool:
        """Whether enough data has been collected to produce VPIN."""
        return len(self.completed_buckets) >= self.window_size

    @property
    def buckets_filled(self) -> int:
        """Number of completed buckets."""
        return len(self.completed_buckets)

    def get_status(self) -> dict:
        """Return current VPIN status for logging/monitoring."""
        return {
            "market_id": self.market_id,
            "vpin": round(self._last_vpin, 4),
            "regime": self._last_regime.value,
            "buckets_filled": len(self.completed_buckets),
            "buckets_needed": self.window_size,
            "is_ready": self.is_ready,
            "total_trades": self._total_trades_processed,
            "last_update": self._last_update,
        }


class VPINManager:
    """
    Manages VPIN state across multiple markets.

    Usage:
        manager = VPINManager(bucket_size=500, window_size=10)
        # On each WebSocket trade event:
        regime = manager.on_trade(market_id, price, size, side, timestamp)
        if regime == FlowRegime.TOXIC:
            cancel_all_maker_orders(market_id)
        elif regime == FlowRegime.SAFE:
            post_tight_maker_orders(market_id)
    """

    def __init__(
        self,
        bucket_size: float = 500.0,
        window_size: int = 10,
        toxic_threshold: float = 0.75,
        safe_threshold: float = 0.25,
    ):
        self.bucket_size = bucket_size
        self.window_size = window_size
        self.toxic_threshold = toxic_threshold
        self.safe_threshold = safe_threshold
        self._states: dict[str, VPINState] = {}

    def _get_or_create_state(self, market_id: str) -> VPINState:
        """Get or create VPIN state for a market."""
        if market_id not in self._states:
            self._states[market_id] = VPINState(
                market_id=market_id,
                bucket_size=self.bucket_size,
                window_size=self.window_size,
                toxic_threshold=self.toxic_threshold,
                safe_threshold=self.safe_threshold,
            )
        return self._states[market_id]

    def on_trade(
        self,
        market_id: str,
        price: float,
        size: float,
        side: str,
        timestamp: float = 0.0,
    ) -> FlowRegime:
        """
        Process a trade and return the current flow regime for that market.

        Args:
            market_id: The Polymarket condition ID
            price: Execution price (0-1)
            size: Number of shares traded
            side: "buy" or "sell" (aggressor side)
            timestamp: Unix timestamp (defaults to now)

        Returns:
            Current FlowRegime for this market
        """
        if timestamp == 0.0:
            timestamp = time.time()

        state = self._get_or_create_state(market_id)
        trade = TradeTick(
            timestamp=timestamp,
            price=price,
            size=size,
            side=side,
            market_id=market_id,
        )

        vpin = state.process_trade(trade)

        if vpin is not None:
            regime = state.regime
            if regime == FlowRegime.TOXIC:
                logger.warning(
                    f"VPIN TOXIC [{market_id[:8]}]: {vpin:.3f} > {self.toxic_threshold} "
                    f"— PULL QUOTES"
                )
            elif regime == FlowRegime.SAFE:
                logger.info(
                    f"VPIN SAFE [{market_id[:8]}]: {vpin:.3f} < {self.safe_threshold} "
                    f"— TIGHTEN SPREAD"
                )

        return state.regime

    def get_regime(self, market_id: str) -> FlowRegime:
        """Get current regime for a market (without processing a trade)."""
        if market_id in self._states:
            return self._states[market_id].regime
        return FlowRegime.NEUTRAL

    def get_vpin(self, market_id: str) -> float:
        """Get current VPIN value for a market."""
        if market_id in self._states:
            return self._states[market_id].vpin
        return 0.5  # Unknown = neutral

    def is_ready(self, market_id: str) -> bool:
        """Check if enough data to produce reliable VPIN for a market."""
        if market_id in self._states:
            return self._states[market_id].is_ready
        return False

    def get_all_status(self) -> list[dict]:
        """Get status of all tracked markets."""
        return [state.get_status() for state in self._states.values()]

    def should_quote(self, market_id: str) -> bool:
        """
        Should we have resting maker orders on this market?

        Returns True if flow is safe/neutral, False if toxic.
        """
        regime = self.get_regime(market_id)
        return regime != FlowRegime.TOXIC

    def get_spread_adjustment(self, market_id: str) -> float:
        """
        Get spread adjustment factor based on VPIN.

        Returns:
            Multiplier for spread width:
            - 0.5 when VPIN is very low (safe, tighten spread)
            - 1.0 when neutral
            - 2.0+ when approaching toxic (widen spread before pulling)
        """
        vpin = self.get_vpin(market_id)

        if vpin < self.safe_threshold:
            # Safe: tighten spread to capture more flow
            return 0.5
        elif vpin < 0.5:
            # Below average: slightly tight
            return 0.75
        elif vpin < self.toxic_threshold:
            # Above average but not toxic: widen defensively
            return 1.0 + (vpin - 0.5) * 4.0  # Linear ramp 1.0 → 2.0
        else:
            # Toxic: should not be quoting at all
            return float('inf')
