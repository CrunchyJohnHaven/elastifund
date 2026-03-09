"""Mock data feed for testing with synthetic data."""
import random
from typing import Any, Optional

import structlog

from .base import DataFeed

logger = structlog.get_logger(__name__)


class MockDataFeed(DataFeed):
    """Mock data feed that returns synthetic data with oscillating prices."""

    def __init__(self, base_price: float = 0.5, volatility: float = 0.02):
        """
        Initialize the mock data feed.
        
        Args:
            base_price: Base price around which prices oscillate (default 0.5)
            volatility: Random walk volatility parameter (default 0.02)
        """
        self.base_price = base_price
        self.volatility = volatility
        self._current_prices: dict[str, float] = {}
        logger.info(
            "mock_feed_initialized",
            base_price=base_price,
            volatility=volatility,
        )

    async def get_markets(self, filters: Optional[dict[str, Any]] = None) -> list[dict]:
        """Return synthetic market data."""
        logger.debug("get_markets_called", filters=filters)
        
        markets = [
            {
                "id": "market_001",
                "question": "Will ETH reach $5000 by EOY 2026?",
                "tags": ["crypto", "price"],
                "volume": 1_000_000,
                "status": "open",
            },
            {
                "id": "market_002",
                "question": "Will BTC reach $100k by Q2 2026?",
                "tags": ["crypto", "price"],
                "volume": 5_000_000,
                "status": "open",
            },
            {
                "id": "market_003",
                "question": "Will US unemployment rate exceed 5% by Q2 2026?",
                "tags": ["economics", "unemployment"],
                "volume": 500_000,
                "status": "open",
            },
        ]
        
        return markets

    async def get_market(self, market_id: str) -> dict:
        """Return synthetic market data for a specific market."""
        logger.debug("get_market_called", market_id=market_id)
        
        return {
            "id": market_id,
            "question": f"Market {market_id}",
            "tags": ["test"],
            "volume": 1_000_000,
            "status": "open",
        }

    async def get_orderbook(self, token_id: str) -> dict:
        """Return synthetic orderbook data."""
        logger.debug("get_orderbook_called", token_id=token_id)
        
        price = self._update_price(token_id)
        spread = 0.01
        
        return {
            "bids": [
                {"price": price - spread, "size": 1000},
                {"price": price - spread * 1.5, "size": 2000},
            ],
            "asks": [
                {"price": price + spread, "size": 1000},
                {"price": price + spread * 1.5, "size": 2000},
            ],
        }

    async def get_midpoint(self, token_id: str) -> float:
        """Get the midpoint price (oscillating around base_price)."""
        logger.debug("get_midpoint_called", token_id=token_id)
        return self._update_price(token_id)

    async def get_price(self, token_id: str) -> float:
        """Get the best available price."""
        logger.debug("get_price_called", token_id=token_id)
        return self._update_price(token_id)

    def _update_price(self, token_id: str) -> float:
        """
        Update price with a random walk.
        
        Args:
            token_id: Token identifier
            
        Returns:
            Updated price
        """
        if token_id not in self._current_prices:
            self._current_prices[token_id] = self.base_price

        current = self._current_prices[token_id]
        change = random.gauss(0, self.volatility)
        new_price = current + change
        
        # Clamp to reasonable bounds [0.01, 0.99]
        new_price = max(0.01, min(0.99, new_price))
        self._current_prices[token_id] = new_price
        
        return new_price
