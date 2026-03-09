"""
Polymarket L2 orderbook recorder via WebSocket feed.

Records live orderbook snapshots at configurable intervals and stores them
as JSON Lines files. Includes depth-based slippage calculator and REST API
fallback for market discovery.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import logging

import httpx
import structlog
import websockets
from websockets.exceptions import WebSocketException

logger = structlog.get_logger(__name__)

# API endpoints
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/"

# Default configuration
DEFAULT_RECORDER_INTERVAL_SEC = 60
DEFAULT_OUTPUT_DIR = "orderbook_data"
DEFAULT_MARKETS = "auto"

# WebSocket configuration
WS_RECONNECT_BACKOFF_BASE = 1.0
WS_RECONNECT_BACKOFF_MAX = 60.0
WS_RECONNECT_JITTER = 0.1

# REST API rate limits (requests per 10 seconds)
RATE_LIMIT_BOOK = 1500
RATE_LIMIT_PRICE = 1000
RATE_LIMIT_WINDOW_SEC = 10

# Gamma API for weather markets
GAMMA_WEATHER_FILTER = "title:weather"
MIN_LIQUIDITY_USDC = 500.0


def walk_book(book_side: list[list[float]], order_size: float) -> float:
    """
    Walk the orderbook levels to compute volume-weighted average fill price.

    Args:
        book_side: List of [price, size] tuples representing one side of the book
        order_size: Total size to walk through

    Returns:
        Volume-weighted average execution price (VWAP) for the order size

    Raises:
        ValueError: If order_size exceeds available liquidity
    """
    if not book_side or order_size <= 0:
        raise ValueError("Invalid orderbook or order size")

    total_volume = 0.0
    total_notional = 0.0
    remaining_order = order_size

    for level in book_side:
        if remaining_order <= 0:
            break

        level_price = float(level[0])
        level_size = float(level[1])

        fill_size = min(remaining_order, level_size)
        total_volume += fill_size
        total_notional += fill_size * level_price
        remaining_order -= fill_size

    if total_volume < order_size:
        raise ValueError(
            f"Insufficient liquidity: only {total_volume} available, "
            f"requested {order_size}"
        )

    vwap = total_notional / total_volume if total_volume > 0 else 0.0
    return vwap


def calculate_depth_1pct(bids: list[list[float]], asks: list[list[float]]) -> float:
    """
    Calculate total liquidity within 1% of midpoint.

    Args:
        bids: List of [price, size] tuples for bid side
        asks: List of [price, size] tuples for ask side

    Returns:
        Total liquidity (in base currency units) within 1% of midpoint
    """
    if not bids or not asks:
        return 0.0

    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    midpoint = (best_bid + best_ask) / 2.0

    lower_bound = midpoint * 0.99
    upper_bound = midpoint * 1.01

    liquidity = 0.0

    # Sum bid liquidity within 1% of midpoint
    for price, size in bids:
        price = float(price)
        if price >= lower_bound:
            liquidity += float(size)

    # Sum ask liquidity within 1% of midpoint
    for price, size in asks:
        price = float(price)
        if price <= upper_bound:
            liquidity += float(size)

    return liquidity


class OrderbookRecorder:
    """Records live Polymarket L2 orderbook data via WebSocket."""

    def __init__(
        self,
        interval_sec: float = DEFAULT_RECORDER_INTERVAL_SEC,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        markets: Optional[list[str]] = None,
        auto_discover: bool = False,
        http_timeout: float = 10.0,
    ):
        """
        Initialize the orderbook recorder.

        Args:
            interval_sec: Interval between snapshots in seconds
            output_dir: Directory for storing JSONL files
            markets: List of token IDs to record (if None, uses auto_discover)
            auto_discover: If True, auto-discover weather markets from Gamma API
            http_timeout: HTTP request timeout in seconds
        """
        self.interval_sec = interval_sec
        self.output_dir = Path(output_dir)
        self.markets = markets or []
        self.auto_discover = auto_discover
        self.http_timeout = http_timeout

        self._http_client: Optional[httpx.AsyncClient] = None
        self._ws = None
        self._running = False
        self._current_orderbooks: dict[str, dict[str, Any]] = {}
        self._last_snapshot_time: dict[str, float] = {}

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "orderbook_recorder_initialized",
            interval_sec=interval_sec,
            output_dir=str(self.output_dir),
            markets=len(self.markets),
            auto_discover=auto_discover,
        )

    async def __aenter__(self):
        """Async context manager entry."""
        self._http_client = httpx.AsyncClient(timeout=self.http_timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.http_timeout)
        return self._http_client

    async def _http_request(
        self, method: str, url: str, **kwargs
    ) -> dict[str, Any]:
        """
        Make an HTTP request with error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL
            **kwargs: Additional arguments for httpx

        Returns:
            Response JSON as dictionary

        Raises:
            RuntimeError: If request fails
        """
        try:
            client = await self._get_http_client()
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.error("http_request_failed", url=url, error=str(e))
            raise RuntimeError(f"HTTP request failed: {url}") from e

    async def discover_weather_markets(self) -> list[str]:
        """
        Discover active weather markets from Gamma API.

        Returns:
            List of token IDs for weather markets with > $500 liquidity
        """
        try:
            logger.info("discovering_weather_markets")
            url = f"{GAMMA_API_BASE}/markets"
            params = {
                "search": "weather",
                "active": "true",
            }

            response = await self._http_request("GET", url, params=params)
            markets = response if isinstance(response, list) else response.get("data", [])

            # Filter for weather markets with sufficient liquidity
            weather_tokens = []
            for market in markets:
                if "weather" in market.get("title", "").lower():
                    # Try to get liquidity info
                    try:
                        token_id = market.get("token_id") or market.get("id")
                        liquidity = market.get("liquidity", 0)

                        if liquidity >= MIN_LIQUIDITY_USDC:
                            weather_tokens.append(token_id)
                    except (KeyError, TypeError):
                        continue

            logger.info(
                "weather_markets_discovered",
                count=len(weather_tokens),
                markets=weather_tokens,
            )
            return weather_tokens

        except RuntimeError as e:
            logger.error("weather_market_discovery_failed", error=str(e))
            return []

    async def get_initial_snapshot(self, token_id: str) -> dict[str, Any]:
        """
        Fetch initial orderbook snapshot via REST API.

        Args:
            token_id: Token identifier

        Returns:
            Formatted orderbook snapshot dictionary
        """
        try:
            url = f"{CLOB_API_BASE}/book"
            params = {"token_id": token_id}

            response = await self._http_request("GET", url, params=params)

            bids = response.get("bids", [])
            asks = response.get("asks", [])

            # Normalize to [price, size] format
            bids = [[float(b.get("price", 0)), float(b.get("size", 0))] for b in bids]
            asks = [[float(a.get("price", 0)), float(a.get("size", 0))] for a in asks]

            best_bid = float(bids[0][0]) if bids else 0.0
            best_ask = float(asks[0][0]) if asks else 0.0
            midpoint = (best_bid + best_ask) / 2.0 if bids and asks else 0.0
            spread = best_ask - best_bid if bids and asks else 0.0
            depth_1pct = calculate_depth_1pct(bids, asks)

            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "token_id": token_id,
                "bids": bids,
                "asks": asks,
                "midpoint": midpoint,
                "spread": spread,
                "depth_1pct": depth_1pct,
            }

            logger.info(
                "initial_snapshot_fetched",
                token_id=token_id,
                bid_levels=len(bids),
                ask_levels=len(asks),
            )

            return snapshot

        except RuntimeError as e:
            logger.error("initial_snapshot_failed", token_id=token_id, error=str(e))
            raise

    async def _ws_connect_with_backoff(self):
        """
        Connect to WebSocket with exponential backoff.

        Yields:
            WebSocket connection once established
        """
        backoff = WS_RECONNECT_BACKOFF_BASE
        jitter = WS_RECONNECT_JITTER

        while self._running:
            try:
                logger.info("ws_connecting", endpoint=WS_ENDPOINT)
                async with websockets.connect(WS_ENDPOINT) as ws:
                    logger.info("ws_connected")
                    backoff = WS_RECONNECT_BACKOFF_BASE  # Reset backoff on success
                    self._ws = ws
                    yield ws
            except WebSocketException as e:
                if not self._running:
                    break
                logger.warning(
                    "ws_connection_failed",
                    error=str(e),
                    backoff=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_BACKOFF_MAX)
            except Exception as e:
                if not self._running:
                    break
                logger.error("ws_unexpected_error", error=str(e), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_BACKOFF_MAX)

    async def _subscribe_markets(self, ws):
        """
        Subscribe to L2 orderbook updates for all markets.

        Args:
            ws: WebSocket connection
        """
        for token_id in self.markets:
            subscription = {
                "type": "subscribe",
                "market": token_id,
                "depth": 2,  # Request L2 data
            }
            try:
                await ws.send(json.dumps(subscription))
                logger.info("subscribed_to_market", token_id=token_id)
            except WebSocketException as e:
                logger.error("subscription_failed", token_id=token_id, error=str(e))

    async def _handle_ws_message(self, message: str) -> None:
        """
        Handle incoming WebSocket message and update orderbooks.

        Args:
            message: Raw message string from WebSocket
        """
        try:
            data = json.loads(message)

            token_id = data.get("market") or data.get("token_id")
            if not token_id:
                return

            # Update current orderbooks
            if "bids" in data and "asks" in data:
                bids = data.get("bids", [])
                asks = data.get("asks", [])

                # Normalize to [price, size] format if needed
                if bids and isinstance(bids[0], dict):
                    bids = [[float(b.get("price", 0)), float(b.get("size", 0))] for b in bids]
                else:
                    bids = [[float(b[0]), float(b[1])] for b in bids]

                if asks and isinstance(asks[0], dict):
                    asks = [[float(a.get("price", 0)), float(a.get("size", 0))] for a in asks]
                else:
                    asks = [[float(a[0]), float(a[1])] for a in asks]

                best_bid = float(bids[0][0]) if bids else 0.0
                best_ask = float(asks[0][0]) if asks else 0.0
                midpoint = (best_bid + best_ask) / 2.0 if bids and asks else 0.0
                spread = best_ask - best_bid if bids and asks else 0.0
                depth_1pct = calculate_depth_1pct(bids, asks)

                self._current_orderbooks[token_id] = {
                    "bids": bids,
                    "asks": asks,
                    "midpoint": midpoint,
                    "spread": spread,
                    "depth_1pct": depth_1pct,
                }

                logger.debug(
                    "orderbook_updated",
                    token_id=token_id,
                    midpoint=midpoint,
                    spread=spread,
                )

        except json.JSONDecodeError as e:
            logger.warning("invalid_ws_message", error=str(e))
        except Exception as e:
            logger.error("ws_message_handling_error", error=str(e))

    async def _snapshot_loop(self) -> None:
        """
        Periodically snapshot current orderbooks and write to files.

        This runs independently of the WebSocket listener.
        """
        while self._running:
            try:
                await asyncio.sleep(self.interval_sec)

                if not self._current_orderbooks:
                    continue

                timestamp = datetime.now(timezone.utc)
                date_str = timestamp.strftime("%Y-%m-%d")
                output_file = self.output_dir / f"{date_str}.jsonl"

                records = []
                for token_id, orderbook in self._current_orderbooks.items():
                    record = {
                        "timestamp": timestamp.isoformat(),
                        "token_id": token_id,
                        "bids": orderbook["bids"],
                        "asks": orderbook["asks"],
                        "midpoint": orderbook["midpoint"],
                        "spread": orderbook["spread"],
                        "depth_1pct": orderbook["depth_1pct"],
                    }
                    records.append(record)

                # Append records to file (create if needed)
                with open(output_file, "a") as f:
                    for record in records:
                        f.write(json.dumps(record) + "\n")

                logger.info(
                    "snapshot_written",
                    file=str(output_file),
                    record_count=len(records),
                )

            except Exception as e:
                logger.error("snapshot_loop_error", error=str(e))

    async def start(self) -> None:
        """
        Start recording orderbook data.

        Connects to WebSocket, discovers markets if needed, and begins recording.
        """
        self._running = True

        try:
            # Discover markets if auto_discover is enabled
            if self.auto_discover and not self.markets:
                self.markets = await self.discover_weather_markets()

            if not self.markets:
                logger.warning("no_markets_to_record")
                return

            # Fetch initial snapshots via REST to populate orderbooks
            logger.info("fetching_initial_snapshots", market_count=len(self.markets))
            for token_id in self.markets:
                try:
                    snapshot = await self.get_initial_snapshot(token_id)
                    self._current_orderbooks[token_id] = {
                        "bids": snapshot["bids"],
                        "asks": snapshot["asks"],
                        "midpoint": snapshot["midpoint"],
                        "spread": snapshot["spread"],
                        "depth_1pct": snapshot["depth_1pct"],
                    }
                except RuntimeError:
                    logger.warning(
                        "initial_snapshot_failed_continuing",
                        token_id=token_id,
                    )

            # Start snapshot loop
            snapshot_task = asyncio.create_task(self._snapshot_loop())

            # Connect to WebSocket and listen for updates
            try:
                async for ws in self._ws_connect_with_backoff():
                    try:
                        await self._subscribe_markets(ws)

                        # Listen for messages
                        async for message in ws:
                            await self._handle_ws_message(message)

                    except WebSocketException as e:
                        if self._running:
                            logger.warning("ws_error_reconnecting", error=str(e))
            finally:
                snapshot_task.cancel()
                try:
                    await snapshot_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error("start_failed", error=str(e))
            self._running = False
            raise

    async def close(self) -> None:
        """Close recorder and cleanup resources."""
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
        logger.info("orderbook_recorder_closed")


async def main():
    """
    Run the orderbook recorder as a standalone service.

    Configuration via environment variables:
    - RECORDER_INTERVAL_SEC: Snapshot interval (default 60)
    - RECORDER_OUTPUT_DIR: Output directory (default "orderbook_data")
    - RECORDER_MARKETS: Comma-separated token IDs, or "auto" for auto-discovery
    """
    # Load configuration from environment
    interval = float(os.getenv("RECORDER_INTERVAL_SEC", DEFAULT_RECORDER_INTERVAL_SEC))
    output_dir = os.getenv("RECORDER_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    markets_str = os.getenv("RECORDER_MARKETS", DEFAULT_MARKETS)

    # Parse markets
    markets = None
    auto_discover = False

    if markets_str.lower() == "auto":
        auto_discover = True
    elif markets_str:
        markets = [m.strip() for m in markets_str.split(",") if m.strip()]

    # Configure logging
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if os.getenv("DEBUG") else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    logger.info(
        "starting_orderbook_recorder",
        interval=interval,
        output_dir=output_dir,
        markets=markets,
        auto_discover=auto_discover,
    )

    async with OrderbookRecorder(
        interval_sec=interval,
        output_dir=output_dir,
        markets=markets,
        auto_discover=auto_discover,
    ) as recorder:
        try:
            await recorder.start()
        except KeyboardInterrupt:
            logger.info("keyboard_interrupt_received")


if __name__ == "__main__":
    asyncio.run(main())
