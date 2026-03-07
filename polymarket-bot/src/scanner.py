"""Gamma API market scanner for discovering tradeable markets."""
import asyncio
from typing import Any, Optional

import httpx
import structlog

from src.resolution_estimator import estimate_resolution_days

logger = structlog.get_logger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# Keywords that indicate weather markets
WEATHER_KEYWORDS = [
    "temperature", "weather", "degrees", "fahrenheit", "celsius",
    "rain", "snow", "wind", "humidity", "forecast", "high temp",
    "low temp", "precipitation", "heat", "cold", "storm",
]


class MarketScanner:
    """Scans Polymarket Gamma API for tradeable markets."""

    def __init__(self, timeout: float = 15.0, max_concurrent: int = 10):
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _request(self, url: str, params: Optional[dict] = None) -> Any:
        """Make a GET request with rate limiting."""
        async with self._semaphore:
            client = await self._get_client()
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error("scanner_request_failed", url=url, status=e.response.status_code)
                raise
            except httpx.RequestError as e:
                logger.error("scanner_request_error", url=url, error=str(e))
                raise

    async def fetch_active_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        tag: Optional[str] = None,
    ) -> list[dict]:
        """Fetch active markets from Gamma API.

        Args:
            limit: Max markets to return (max 100 per page)
            offset: Pagination offset
            tag: Optional tag filter (e.g., "weather", "politics")

        Returns:
            List of market dicts with keys: id, question, clobTokenIds,
            outcomePrices, volume, liquidity, etc.
        """
        params: dict[str, Any] = {
            "closed": "false",
            "limit": min(limit, 100),
            "offset": offset,
        }
        if tag:
            params["tag"] = tag

        url = f"{GAMMA_API_BASE}/markets"
        markets = await self._request(url, params)

        if not isinstance(markets, list):
            markets = markets.get("data", [])

        logger.info(
            "fetched_active_markets",
            count=len(markets),
            tag=tag,
            offset=offset,
        )
        return markets

    async def fetch_all_active_markets(self, max_pages: int = 5) -> list[dict]:
        """Fetch all active markets across multiple pages.

        Args:
            max_pages: Maximum number of pages to fetch

        Returns:
            Combined list of all active markets
        """
        all_markets = []
        for page in range(max_pages):
            offset = page * 100
            markets = await self.fetch_active_markets(limit=100, offset=offset)
            all_markets.extend(markets)
            if len(markets) < 100:
                break
            await asyncio.sleep(0.2)  # Rate limit courtesy

        logger.info("fetched_all_active_markets", total=len(all_markets))
        return all_markets

    async def fetch_weather_markets(self) -> list[dict]:
        """Fetch weather-specific markets using tag and keyword filtering.

        Returns:
            List of weather market dicts
        """
        # Try tag-based filtering first
        weather_markets = []
        try:
            tagged = await self.fetch_active_markets(tag="weather")
            weather_markets.extend(tagged)
        except Exception:
            logger.warning("weather_tag_fetch_failed, falling back to keyword search")

        # Also do keyword-based filtering on all markets
        all_markets = await self.fetch_all_active_markets()
        for market in all_markets:
            question = (market.get("question") or "").lower()
            if any(kw in question for kw in WEATHER_KEYWORDS):
                # Avoid duplicates
                market_id = market.get("id") or market.get("condition_id")
                existing_ids = {
                    m.get("id") or m.get("condition_id") for m in weather_markets
                }
                if market_id not in existing_ids:
                    weather_markets.append(market)

        logger.info("weather_markets_found", count=len(weather_markets))
        return weather_markets

    async def filter_liquid_markets(
        self,
        markets: list[dict],
        min_volume: float = 1000.0,
        min_liquidity: float = 500.0,
    ) -> list[dict]:
        """Filter markets by volume and liquidity thresholds.

        Args:
            markets: List of market dicts to filter
            min_volume: Minimum trading volume in USD
            min_liquidity: Minimum liquidity in USD

        Returns:
            Filtered list of liquid markets
        """
        liquid = []
        for market in markets:
            volume = float(market.get("volume", 0) or 0)
            liquidity = float(market.get("liquidity", 0) or 0)

            if volume >= min_volume and liquidity >= min_liquidity:
                liquid.append(market)

        logger.info(
            "filtered_liquid_markets",
            input_count=len(markets),
            output_count=len(liquid),
            min_volume=min_volume,
            min_liquidity=min_liquidity,
        )
        return liquid

    @staticmethod
    def extract_token_ids(market: dict) -> list[str]:
        """Extract CLOB token IDs from a market dict.

        Args:
            market: Market dict from Gamma API

        Returns:
            List of token ID strings (typically [YES_token, NO_token])
        """
        clob_token_ids = market.get("clobTokenIds")
        if isinstance(clob_token_ids, str):
            return [tid.strip() for tid in clob_token_ids.split(",") if tid.strip()]
        if isinstance(clob_token_ids, list):
            return clob_token_ids
        return []

    @staticmethod
    def extract_prices(market: dict) -> dict[str, float]:
        """Extract outcome prices from a market dict.

        Returns:
            Dict like {"YES": 0.65, "NO": 0.35}
        """
        prices_raw = market.get("outcomePrices")
        if isinstance(prices_raw, str):
            try:
                import json
                prices_list = json.loads(prices_raw)
                if len(prices_list) >= 2:
                    return {"YES": float(prices_list[0]), "NO": float(prices_list[1])}
            except (json.JSONDecodeError, ValueError):
                pass
        if isinstance(prices_raw, list) and len(prices_raw) >= 2:
            return {"YES": float(prices_raw[0]), "NO": float(prices_raw[1])}
        return {}

    async def scan_for_opportunities(
        self,
        min_volume: float = 1000.0,
        min_liquidity: float = 500.0,
    ) -> list[dict]:
        """Full scan: fetch markets, filter for liquidity, extract trading info.

        Returns:
            List of opportunity dicts with market info and token IDs
        """
        all_markets = await self.fetch_all_active_markets()
        liquid_markets = await self.filter_liquid_markets(
            all_markets, min_volume, min_liquidity
        )

        opportunities = []
        for market in liquid_markets:
            token_ids = self.extract_token_ids(market)
            prices = self.extract_prices(market)

            if not token_ids:
                continue

            # Estimate resolution time
            question = market.get("question", "")
            end_date = market.get("endDate") or market.get("end_date_iso")
            created_at = market.get("createdAt")
            category = None
            tags = market.get("tags") or []
            if isinstance(tags, list) and tags:
                category = tags[0] if isinstance(tags[0], str) else None

            resolution_est = estimate_resolution_days(
                question=question,
                end_date=end_date,
                created_at=created_at,
                category=category,
            )

            # Compute hours_to_resolution for Kelly dampener
            estimated_days = resolution_est["estimated_days"]
            hours_to_resolution = estimated_days * 24.0

            # Approximate per-outcome volume from total volume and prices
            total_volume = float(market.get("volume", 0) or 0)
            yes_price = prices.get("YES", 0.5)
            no_price = prices.get("NO", 0.5)
            price_sum = max(yes_price + no_price, 0.01)
            volume_yes = total_volume * (yes_price / price_sum)
            volume_no = total_volume * (no_price / price_sum)

            opportunities.append({
                "market_id": market.get("id") or market.get("condition_id", ""),
                "question": question,
                "token_ids": token_ids,
                "prices": prices,
                "volume": total_volume,
                "volume_yes": volume_yes,
                "volume_no": volume_no,
                "liquidity": float(market.get("liquidity", 0) or 0),
                "end_date": end_date,
                "tags": tags,
                "estimated_days": estimated_days,
                "hours_to_resolution": hours_to_resolution,
                "resolution_bucket": resolution_est["bucket"],
                "resolution_method": resolution_est["method"],
            })

        logger.info("scan_complete", opportunities=len(opportunities))
        return opportunities

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
