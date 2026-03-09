"""Polymarket data feed using Gamma and CLOB APIs."""
import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from .base import DataFeed

logger = structlog.get_logger(__name__)

# API endpoints
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

# Rate limiting and retry configuration
MAX_CONCURRENT_REQUESTS = 100
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]  # exponential backoff in seconds
PRICE_CACHE_TTL = 60  # seconds


class PolymarketDataFeed(DataFeed):
    """Market data feed using Polymarket Gamma and CLOB APIs."""

    def __init__(self, timeout: float = 10.0):
        """
        Initialize the Polymarket data feed.
        
        Args:
            timeout: HTTP request timeout in seconds
        """
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout
        self._price_cache: dict[str, tuple[float, float]] = {}  # token_id -> (price, timestamp)
        logger.info("polymarket_feed_initialized", timeout=timeout, max_concurrent=MAX_CONCURRENT_REQUESTS)

    async def __aenter__(self):
        """Async context manager entry."""
        self._http_client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._http_client:
            await self._http_client.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout)
        return self._http_client

    async def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        """
        Make an HTTP request with rate limiting, retries, and error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            **kwargs: Additional arguments for httpx
            
        Returns:
            Response JSON as dictionary
            
        Raises:
            RuntimeError: If all retries fail
        """
        async with self._semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    client = await self._get_client()
                    response = await client.request(method, url, **kwargs)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as e:
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "request_retry",
                            url=url,
                            attempt=attempt + 1,
                            status=e.response.status_code,
                            delay=delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "request_failed",
                            url=url,
                            status=e.response.status_code,
                            attempts=MAX_RETRIES,
                        )
                        raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {url}") from e
                except (httpx.RequestError, asyncio.TimeoutError) as e:
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "request_retry",
                            url=url,
                            attempt=attempt + 1,
                            error=str(e),
                            delay=delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "request_failed",
                            url=url,
                            error=str(e),
                            attempts=MAX_RETRIES,
                        )
                        raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {url}") from e

    async def get_markets(self, filters: Optional[dict[str, Any]] = None) -> list[dict]:
        """
        Fetch markets from Gamma API.
        
        Args:
            filters: Optional filter parameters (search, status, etc.)
            
        Returns:
            List of market dictionaries
        """
        logger.debug("get_markets_called", filters=filters)
        
        url = f"{GAMMA_API_BASE}/markets"
        params = filters or {}
        
        try:
            response = await self._request("GET", url, params=params)
            markets = response if isinstance(response, list) else response.get("data", [])
            logger.info("get_markets_success", count=len(markets))
            return markets
        except RuntimeError as e:
            logger.error("get_markets_failed", error=str(e))
            raise

    async def get_market(self, market_id: str) -> dict:
        """
        Fetch a specific market from Gamma API.
        
        Args:
            market_id: Market identifier
            
        Returns:
            Market dictionary
        """
        logger.debug("get_market_called", market_id=market_id)
        
        url = f"{GAMMA_API_BASE}/markets/{market_id}"
        
        try:
            response = await self._request("GET", url)
            logger.info("get_market_success", market_id=market_id)
            return response
        except RuntimeError as e:
            logger.error("get_market_failed", market_id=market_id, error=str(e))
            raise

    async def get_orderbook(self, token_id: str) -> dict:
        """
        Fetch orderbook from CLOB API.
        
        Args:
            token_id: Token identifier
            
        Returns:
            Orderbook dictionary with bids and asks
        """
        logger.debug("get_orderbook_called", token_id=token_id)
        
        url = f"{CLOB_API_BASE}/book"
        params = {"token_id": token_id}
        
        try:
            response = await self._request("GET", url, params=params)
            logger.info("get_orderbook_success", token_id=token_id)
            return response
        except RuntimeError as e:
            logger.error("get_orderbook_failed", token_id=token_id, error=str(e))
            raise

    async def get_midpoint(self, token_id: str) -> float:
        """
        Get midpoint price from CLOB API.
        
        Args:
            token_id: Token identifier
            
        Returns:
            Midpoint price as float
        """
        logger.debug("get_midpoint_called", token_id=token_id)
        
        url = f"{CLOB_API_BASE}/midpoint"
        params = {"token_id": token_id}
        
        try:
            response = await self._request("GET", url, params=params)
            midpoint = float(response.get("mid", 0.0))
            self._update_price_cache(token_id, midpoint)
            logger.info("get_midpoint_success", token_id=token_id, midpoint=midpoint)
            return midpoint
        except RuntimeError as e:
            logger.error("get_midpoint_failed", token_id=token_id, error=str(e))
            raise

    async def get_price(self, token_id: str) -> float:
        """
        Get the best available price for a token.
        
        Try to get midpoint from cache first, fall back to orderbook.
        
        Args:
            token_id: Token identifier
            
        Returns:
            Best available price as float
        """
        logger.debug("get_price_called", token_id=token_id)
        
        # Check cache first
        cached_price, cached_time = self._price_cache.get(token_id, (None, 0))
        if cached_price is not None and (time.time() - cached_time) < PRICE_CACHE_TTL:
            logger.debug("price_cache_hit", token_id=token_id, price=cached_price)
            return cached_price
        
        try:
            # Try to get midpoint
            try:
                price = await self.get_midpoint(token_id)
                return price
            except RuntimeError:
                # Fall back to orderbook midpoint
                logger.debug("midpoint_failed_fallback_to_orderbook", token_id=token_id)
                orderbook = await self.get_orderbook(token_id)
                
                bids = orderbook.get("bids", [])
                asks = orderbook.get("asks", [])
                
                if bids and asks:
                    best_bid = float(bids[0].get("price", 0.0))
                    best_ask = float(asks[0].get("price", 1.0))
                    price = (best_bid + best_ask) / 2.0
                    self._update_price_cache(token_id, price)
                    logger.info("get_price_success", token_id=token_id, price=price, source="orderbook")
                    return price
                else:
                    raise RuntimeError(f"No bids or asks in orderbook for {token_id}")
        except RuntimeError as e:
            logger.error("get_price_failed", token_id=token_id, error=str(e))
            raise

    def _update_price_cache(self, token_id: str, price: float) -> None:
        """Update the price cache with timestamp."""
        self._price_cache[token_id] = (price, time.time())

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
