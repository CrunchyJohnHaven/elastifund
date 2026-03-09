"""Core data fetching logic for Polymarket APIs.

Provides fetch_markets(), fetch_orderbook(), fetch_trades() with:
- Exponential backoff retries
- Rate-limit awareness (semaphore + courtesy delays)
- Raw payload preservation
"""

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]
MAX_CONCURRENT = 20
PAGE_SIZE = 100
COURTESY_DELAY = 0.25  # seconds between paginated requests


class MarketDataFetcher:
    """Read-only fetcher for Polymarket market data."""

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _request(
        self, url: str, params: Optional[dict] = None
    ) -> tuple[Any, dict]:
        """GET request with retries and rate limiting.

        Returns:
            Tuple of (parsed_json, response_metadata) where metadata includes
            status_code, headers dict, and elapsed_ms.
        """
        async with self._semaphore:
            last_error: Optional[Exception] = None
            for attempt in range(MAX_RETRIES):
                try:
                    client = await self._get_client()
                    t0 = time.monotonic()
                    resp = await client.get(url, params=params)
                    elapsed_ms = round((time.monotonic() - t0) * 1000)

                    # Rate limit detection: back off on 429
                    if resp.status_code == 429:
                        retry_after = float(
                            resp.headers.get("Retry-After", RETRY_DELAYS[attempt])
                        )
                        logger.warning(
                            "rate_limited",
                            url=url,
                            retry_after=retry_after,
                            attempt=attempt + 1,
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    resp.raise_for_status()
                    meta = {
                        "status_code": resp.status_code,
                        "elapsed_ms": elapsed_ms,
                        "content_length": len(resp.content),
                    }
                    return resp.json(), meta

                except httpx.HTTPStatusError as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "request_retry",
                            url=url,
                            status=e.response.status_code,
                            attempt=attempt + 1,
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

                except (httpx.RequestError, asyncio.TimeoutError) as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "request_retry",
                            url=url,
                            error=str(e),
                            attempt=attempt + 1,
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

            raise RuntimeError(
                f"Request failed after {MAX_RETRIES} attempts: {url}"
            ) from last_error

    # ── Market Metadata ────────────────────────────────────────────

    async def fetch_markets(
        self,
        max_pages: int = 10,
        active_only: bool = True,
    ) -> list[dict]:
        """Fetch market metadata from Gamma API with pagination.

        Args:
            max_pages: Maximum pages to fetch (100 markets/page).
            active_only: If True, only fetch non-closed markets.

        Returns:
            List of raw market dicts as received from Gamma API.
        """
        all_markets: list[dict] = []
        for page in range(max_pages):
            params: dict[str, Any] = {
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            }
            if active_only:
                params["closed"] = "false"

            data, meta = await self._request(
                f"{GAMMA_API_BASE}/markets", params=params
            )

            markets = data if isinstance(data, list) else data.get("data", [])
            all_markets.extend(markets)

            logger.debug(
                "fetch_markets_page",
                page=page,
                count=len(markets),
                elapsed_ms=meta["elapsed_ms"],
            )

            if len(markets) < PAGE_SIZE:
                break
            await asyncio.sleep(COURTESY_DELAY)

        logger.info("fetch_markets_complete", total=len(all_markets))
        return all_markets

    # ── Order Book ─────────────────────────────────────────────────

    async def fetch_orderbook(self, token_id: str) -> dict:
        """Fetch full order book snapshot from CLOB API.

        Args:
            token_id: CLOB token ID (e.g., the YES or NO token).

        Returns:
            Raw orderbook dict with 'bids', 'asks', plus computed
            top-of-book fields.
        """
        data, meta = await self._request(
            f"{CLOB_API_BASE}/book",
            params={"token_id": token_id},
        )

        # Compute top-of-book summary
        bids = data.get("bids") or []
        asks = data.get("asks") or []

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
        midpoint = ((best_bid + best_ask) / 2) if spread is not None else None

        data["_top_of_book"] = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "midpoint": midpoint,
            "bid_depth": len(bids),
            "ask_depth": len(asks),
        }
        data["_meta"] = meta

        logger.info(
            "fetch_orderbook_complete",
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            bid_depth=len(bids),
            ask_depth=len(asks),
        )
        return data

    # ── Trades ─────────────────────────────────────────────────────

    async def fetch_trades(self, token_id: str) -> list[dict]:
        """Fetch recent trades from CLOB API.

        The CLOB API may or may not expose a public trades endpoint.
        This method tries multiple known endpoints and returns whatever
        is available, gracefully returning an empty list if none work.

        Args:
            token_id: CLOB token ID.

        Returns:
            List of trade dicts, or empty list if unavailable.
        """
        # /trades requires auth (401), so go straight to last-trade-price
        # which is publicly available
        try:
            data, meta = await self._request(
                f"{CLOB_API_BASE}/last-trade-price",
                params={"token_id": token_id},
            )
            if isinstance(data, dict):
                logger.info(
                    "fetch_trades_last_price",
                    token_id=token_id,
                    data=data,
                )
                return [data]
            if isinstance(data, list):
                logger.info(
                    "fetch_trades_complete",
                    token_id=token_id,
                    count=len(data),
                )
                return data
        except RuntimeError:
            logger.debug(
                "trades_endpoint_unavailable",
                token_id=token_id,
            )

        logger.warning(
            "fetch_trades_no_endpoint",
            token_id=token_id,
            message="No trades endpoint returned data",
        )
        return []

    # ── Batch Operations ───────────────────────────────────────────

    async def fetch_orderbooks_batch(
        self,
        token_ids: list[str],
        max_concurrent: int = 5,
    ) -> dict[str, dict]:
        """Fetch orderbooks for multiple tokens with concurrency control.

        Args:
            token_ids: List of token IDs to fetch.
            max_concurrent: Max concurrent orderbook requests.

        Returns:
            Dict mapping token_id -> orderbook data.
            Failed fetches are logged and excluded.
        """
        sem = asyncio.Semaphore(max_concurrent)
        results: dict[str, dict] = {}

        async def _fetch_one(tid: str):
            async with sem:
                try:
                    results[tid] = await self.fetch_orderbook(tid)
                except RuntimeError as e:
                    logger.error(
                        "orderbook_batch_error",
                        token_id=tid,
                        error=str(e),
                    )

        await asyncio.gather(*[_fetch_one(tid) for tid in token_ids])

        logger.info(
            "fetch_orderbooks_batch_complete",
            requested=len(token_ids),
            succeeded=len(results),
        )
        return results

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


def extract_token_ids(market: dict) -> list[str]:
    """Extract CLOB token IDs from a Gamma API market dict.

    Handles both JSON-encoded strings and native lists.

    Returns:
        List of token ID strings (typically [YES_token, NO_token]).
    """
    import json as _json

    clob_token_ids = market.get("clobTokenIds")
    if isinstance(clob_token_ids, str):
        try:
            parsed = _json.loads(clob_token_ids)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
        except (ValueError, _json.JSONDecodeError):
            pass
        return [tid.strip() for tid in clob_token_ids.split(",") if tid.strip()]
    if isinstance(clob_token_ids, list):
        return [str(t) for t in clob_token_ids]
    return []
