"""Expanded market scanner for edge discovery data collection.

Wraps the existing MarketScanner to fetch 50+ diverse markets across
categories, handle CLOB errors gracefully with quarantine, and provide
a clean interface for the edge collector daemon.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from bot.market_quarantine import MarketQuarantine

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

# Category diversity targets (approximate, not strict quotas)
CATEGORY_TARGETS = {
    "politics": 15,
    "crypto": 8,
    "sports": 5,
    "pop-culture": 5,
    "science": 5,
    "business": 5,
    "world-events": 5,
    "other": 10,
}

# Keywords for category detection when tags are missing
CATEGORY_KEYWORDS = {
    "politics": ["president", "election", "congress", "senate", "governor", "vote", "trump", "biden", "political", "democrat", "republican"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "token", "blockchain", "solana", "dogecoin"],
    "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball", "baseball", "match", "game score", "championship"],
    "weather": ["temperature", "weather", "degrees", "fahrenheit", "celsius", "rain", "snow", "storm"],
    "science": ["nasa", "spacex", "launch", "scientific", "study", "research", "climate", "earthquake"],
    "business": ["stock", "s&p", "nasdaq", "gdp", "fed", "interest rate", "inflation", "earnings", "ipo"],
}


@dataclass
class MarketSnapshot:
    """Lightweight market data for edge collection."""
    market_id: str
    question: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    category: str
    token_ids: list[str]
    end_date: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)


def detect_category(market: dict) -> str:
    """Detect market category from tags or question keywords."""
    tags = market.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, ValueError):
            tags = [tags]

    # Check tags first
    tag_str = " ".join(str(t).lower() for t in tags)
    for cat in CATEGORY_TARGETS:
        if cat in tag_str:
            return cat

    # Fall back to keyword detection
    question = (market.get("question") or "").lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in question for kw in keywords):
            return cat

    return "other"


class ExpandedScanner:
    """Fetches 50+ diverse markets with CLOB error handling."""

    def __init__(
        self,
        quarantine: Optional[MarketQuarantine] = None,
        target_market_count: int = 50,
        min_volume: float = 1000.0,
        max_pages: int = 25,
        timeout: float = 15.0,
    ):
        self.quarantine = quarantine or MarketQuarantine()
        self.target_count = target_market_count
        self.min_volume = min_volume
        self.max_pages = max_pages
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def fetch_all_markets(self) -> list[dict]:
        """Fetch all active markets from Gamma API with pagination."""
        client = await self._get_client()
        all_markets: list[dict] = []

        for page in range(self.max_pages):
            try:
                resp = await client.get(
                    f"{GAMMA_API_BASE}/markets",
                    params={
                        "closed": "false",
                        "limit": 100,
                        "offset": page * 100,
                    },
                )
                resp.raise_for_status()
                batch = resp.json()
                if not isinstance(batch, list):
                    batch = batch.get("data", [])
                all_markets.extend(batch)
                if len(batch) < 100:
                    break
                await asyncio.sleep(0.2)
            except httpx.HTTPStatusError as e:
                logger.warning("gamma_page_error page=%d status=%d", page, e.response.status_code)
                break
            except httpx.RequestError as e:
                logger.warning("gamma_request_error page=%d error=%s", page, e)
                break

        logger.info("fetched_all_markets total=%d", len(all_markets))
        return all_markets

    def _parse_market(self, raw: dict) -> Optional[MarketSnapshot]:
        """Parse a raw Gamma market dict into a MarketSnapshot."""
        market_id = raw.get("id") or raw.get("condition_id") or ""
        if not market_id:
            return None

        # Skip quarantined markets
        if self.quarantine.is_quarantined(market_id):
            return None

        # Extract prices
        yes_price = None
        no_price = None

        prices_raw = raw.get("outcomePrices")
        if isinstance(prices_raw, str) and prices_raw:
            try:
                parsed = json.loads(prices_raw)
                if isinstance(parsed, list) and len(parsed) >= 2:
                    yes_price = float(parsed[0])
                    no_price = float(parsed[1])
            except (json.JSONDecodeError, ValueError):
                pass
        elif isinstance(prices_raw, list) and len(prices_raw) >= 2:
            yes_price = float(prices_raw[0])
            no_price = float(prices_raw[1])

        if yes_price is None:
            yes_price = float(raw.get("price", 0) or 0)
            no_price = 1.0 - yes_price if yes_price > 0 else 0.0

        if yes_price <= 0:
            return None

        # Extract token IDs
        token_ids = []
        clob_tokens = raw.get("clobTokenIds")
        if isinstance(clob_tokens, str) and clob_tokens:
            try:
                token_ids = json.loads(clob_tokens)
            except (json.JSONDecodeError, ValueError):
                token_ids = [t.strip() for t in clob_tokens.split(",") if t.strip()]
        elif isinstance(clob_tokens, list):
            token_ids = clob_tokens

        # Skip quarantined tokens
        token_ids = [t for t in token_ids if not self.quarantine.is_quarantined(t)]
        if not token_ids:
            return None

        volume = float(raw.get("volume", 0) or 0)
        liquidity = float(raw.get("liquidity", 0) or 0)
        category = detect_category(raw)

        tags = raw.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, ValueError):
                tags = [tags]

        return MarketSnapshot(
            market_id=market_id,
            question=raw.get("question", ""),
            yes_price=yes_price,
            no_price=no_price,
            volume=volume,
            liquidity=liquidity,
            category=category,
            token_ids=token_ids,
            end_date=raw.get("endDate") or raw.get("end_date_iso"),
            tags=tags,
        )

    async def scan_diverse_markets(self) -> list[MarketSnapshot]:
        """Scan for 50+ markets with category diversity.

        Fetches all active markets, filters for volume and valid pricing,
        then selects a diverse subset across categories.
        """
        raw_markets = await self.fetch_all_markets()

        # Parse and filter
        parsed: list[MarketSnapshot] = []
        for raw in raw_markets:
            snapshot = self._parse_market(raw)
            if snapshot is None:
                continue
            if snapshot.volume < self.min_volume:
                continue
            if not (0.02 <= snapshot.yes_price <= 0.98):
                continue
            parsed.append(snapshot)

        # Group by category
        by_category: dict[str, list[MarketSnapshot]] = {}
        for m in parsed:
            by_category.setdefault(m.category, []).append(m)

        # Sort each category by volume (descending) for quality selection
        for cat in by_category:
            by_category[cat].sort(key=lambda x: x.volume, reverse=True)

        # Select diverse set: fill category targets, then top up with highest volume
        selected: list[MarketSnapshot] = []
        selected_ids: set[str] = set()

        for cat, target in CATEGORY_TARGETS.items():
            available = by_category.get(cat, [])
            for m in available[:target]:
                if m.market_id not in selected_ids:
                    selected.append(m)
                    selected_ids.add(m.market_id)

        # Fill remaining slots with highest-volume unselected markets
        remaining = sorted(
            [m for m in parsed if m.market_id not in selected_ids],
            key=lambda x: x.volume,
            reverse=True,
        )
        for m in remaining:
            if len(selected) >= self.target_count:
                break
            selected.append(m)
            selected_ids.add(m.market_id)

        cat_counts = {
            cat: sum(1 for m in selected if m.category == cat)
            for cat in set(m.category for m in selected)
        } if selected else {}
        logger.info(
            "diverse_scan_complete raw=%d filtered=%d selected=%d categories=%s quarantined=%d",
            len(raw_markets), len(parsed), len(selected), cat_counts,
            len(self.quarantine.get_quarantined_ids()),
        )
        return selected

    async def fetch_order_book_safe(
        self, token_id: str
    ) -> Optional[dict[str, Any]]:
        """Fetch order book with 404 quarantine handling.

        Returns order book dict or None if unavailable/quarantined.
        """
        if self.quarantine.is_quarantined(token_id):
            return None

        client = await self._get_client()
        try:
            resp = await client.get(
                f"{CLOB_API_BASE}/book",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 404:
                self.quarantine.quarantine(
                    token_id, id_type="token_id", reason="clob_404"
                )
                logger.warning("clob_404_quarantined token_id=%s", token_id[:16])
            elif status >= 500:
                self.quarantine.quarantine(
                    token_id, id_type="token_id", reason=f"clob_{status}"
                )
                logger.warning("clob_5xx_quarantined token_id=%s status=%d", token_id[:16], status)
            else:
                logger.warning("clob_http_error token_id=%s status=%d", token_id[:16], status)
            return None
        except httpx.RequestError as e:
            logger.warning("clob_request_error token_id=%s error=%s", token_id[:16], e)
            return None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
