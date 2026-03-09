"""Abstract base class for market data feeds."""
from abc import ABC, abstractmethod
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class DataFeed(ABC):
    """Abstract base class for market data sources."""

    @abstractmethod
    async def get_markets(self, filters: Optional[dict[str, Any]] = None) -> list[dict]:
        """
        Fetch markets from the data source.
        
        Args:
            filters: Optional dictionary of filter parameters (e.g., search query, status, etc.)
            
        Returns:
            List of market dictionaries with market metadata
        """
        pass

    @abstractmethod
    async def get_market(self, market_id: str) -> dict:
        """
        Fetch a specific market by ID.
        
        Args:
            market_id: The market identifier
            
        Returns:
            Market dictionary with metadata
        """
        pass

    @abstractmethod
    async def get_orderbook(self, token_id: str) -> dict:
        """
        Fetch the orderbook for a specific token.
        
        Args:
            token_id: The token identifier
            
        Returns:
            Orderbook dictionary with bids and asks
        """
        pass

    @abstractmethod
    async def get_midpoint(self, token_id: str) -> float:
        """
        Get the midpoint price for a token.
        
        Args:
            token_id: The token identifier
            
        Returns:
            Midpoint price as a float
        """
        pass

    @abstractmethod
    async def get_price(self, token_id: str) -> float:
        """
        Get the best available price for a token.
        
        Args:
            token_id: The token identifier
            
        Returns:
            Best available price as a float
        """
        pass
