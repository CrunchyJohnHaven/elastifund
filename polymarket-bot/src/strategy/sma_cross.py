"""Simple moving average crossover strategy."""
from collections import deque
from typing import Optional

import structlog

from .base import Strategy

logger = structlog.get_logger(__name__)


class SMACrossStrategy(Strategy):
    """Simple moving average crossover strategy."""

    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        """Initialize SMA cross strategy.

        Args:
            fast_period: Fast SMA period (default 5)
            slow_period: Slow SMA period (default 20)
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.price_history = deque(maxlen=slow_period + 10)

    @property
    def name(self) -> str:
        """Return strategy name."""
        return f"SMACross({self.fast_period},{self.slow_period})"

    async def generate_signal(self, market_state: dict) -> dict:
        """Generate SMA crossover signal.

        Args:
            market_state: Market state dict with current_price, price_history, etc.

        Returns:
            Signal dict with action, size, confidence, reason
        """
        market_id = market_state.get("market_id", "unknown")
        current_price = market_state.get("current_price")
        token_id = market_state.get("token_id", "YES")
        positions = market_state.get("positions", [])

        if current_price is None:
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": "No price data available",
            }

        # Update price history
        self.price_history.append(current_price)

        # Need enough history for slow SMA
        if len(self.price_history) < self.slow_period:
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": f"Insufficient history: {len(self.price_history)}/{self.slow_period}",
            }

        # Calculate SMAs
        fast_sma = self._calculate_sma(list(self.price_history), self.fast_period)
        slow_sma = self._calculate_sma(list(self.price_history), self.slow_period)

        if fast_sma is None or slow_sma is None:
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": "Could not calculate SMAs",
            }

        # Generate signal
        sma_diff = fast_sma - slow_sma
        sma_diff_pct = (sma_diff / slow_sma * 100) if slow_sma > 0 else 0

        if sma_diff > 0:  # Fast SMA above slow SMA - bullish
            action = "buy_yes"
            confidence = min(1.0, abs(sma_diff_pct) / 10)  # Confidence based on gap size
        elif sma_diff < 0:  # Fast SMA below slow SMA - bearish
            action = "buy_no"
            confidence = min(1.0, abs(sma_diff_pct) / 10)
        else:
            action = "hold"
            confidence = 0

        # Calculate size using half-Kelly criterion
        size = 0
        if action != "hold":
            p_est = 0.55 if action == "buy_yes" else 0.45
            p_market = current_price if action == "buy_yes" else (1 - current_price)

            if p_market > 0 and p_market < 1:
                kelly_fraction = (p_est - p_market) / (1 - p_market) * 0.5
                size = max(0, kelly_fraction * 100)  # Scale to shares

        reason = f"Fast SMA {fast_sma:.4f} vs Slow SMA {slow_sma:.4f} (diff: {sma_diff_pct:.2f}%)"

        signal = {
            "action": action,
            "size": size,
            "confidence": confidence,
            "reason": reason,
        }

        await self._log_signal(market_id, signal)
        return signal

    def _calculate_sma(self, prices: list[float], period: int) -> Optional[float]:
        """Calculate simple moving average.

        Args:
            prices: List of prices
            period: SMA period

        Returns:
            SMA value or None if insufficient data
        """
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
