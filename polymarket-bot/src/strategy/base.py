"""Abstract base strategy class."""
from abc import ABC, abstractmethod
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class Strategy(ABC):
    """Abstract base class for trading strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return strategy name."""
        pass

    @abstractmethod
    async def generate_signal(self, market_state: dict) -> dict:
        """Generate trading signal based on market state.

        Args:
            market_state: Dict with keys:
                - market_id (str): Market ID
                - token_id (str): Token ID (YES or NO)
                - question (str): Market question
                - current_price (float): Current market price 0-1
                - midpoint (float): Order book midpoint
                - orderbook_depth (dict): Order book structure
                - positions (list): Current positions
                - price_history (list): Recent prices
                - timestamp (datetime): Current timestamp

        Returns:
            Dict with keys:
                - action (str): "buy_yes", "buy_no", "sell", "hold"
                - size (float): Order size in shares
                - confidence (float): Confidence 0.0-1.0
                - reason (str): Explanation of signal
        """
        pass

    async def _log_signal(self, market_id: str, signal: dict) -> None:
        """Log generated signal."""
        await logger.ainfo(
            "signal_generated",
            strategy=self.name,
            market_id=market_id,
            action=signal.get("action"),
            size=signal.get("size"),
            confidence=signal.get("confidence"),
            reason=signal.get("reason"),
        )
