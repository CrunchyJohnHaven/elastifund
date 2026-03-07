"""Polymarket broker for live trading on the CLOB.

Uses py-clob-client for all Polymarket interactions.
Supports MAKER (limit-only, zero fees), TAKER (cross spread), and HYBRID
(maker first, taker fallback if edge survives after fee).
Cancel/replace: unfilled maker orders are re-placed at updated price up to
maker_max_retries times before giving up (MAKER) or falling back (HYBRID).
Every order attempt, fill, cancel, and error is logged to bot.db.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

from src.core.config import get_settings
from .base import Broker, Order, OrderSide, OrderStatus, Position

logger = structlog.get_logger(__name__)

# Polymarket CLOB constants
BUY = "BUY"
SELL = "SELL"
GTC = "GTC"  # Good-til-cancelled


@dataclass
class PolymarketBrokerConfig:
    """Configuration for Polymarket broker."""
    live_trading: bool = False
    private_key: str = ""
    user_address: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    chain_id: int = 137  # Polygon mainnet
    signature_type: int = 2
    clob_url: str = "https://clob.polymarket.com"


class PolymarketBroker(Broker):
    """Polymarket broker using the CLOB API for live trading.

    SAFETY: Market orders are BLOCKED. Only limit orders (maker, zero fees).
    """

    def __init__(self, config: PolymarketBrokerConfig):
        """Initialize the Polymarket broker.

        Uses pre-existing API key/secret/passphrase (builder credentials)
        from .env rather than deriving new L2 credentials on each startup.

        CRITICAL: If config.live_trading is False, the broker is blocked
        and will raise RuntimeError on any order placement attempt.
        """
        self.config = config
        self._blocked = not config.live_trading
        self._client = None
        self._open_orders: dict[str, dict] = {}  # order_id -> {clob_order_id, placed_at, ...}

        if self._blocked:
            logger.warning("polymarket_broker_initialized_blocked", live_trading=False)
        else:
            self._init_client()

    def _init_client(self) -> None:
        """Initialize the ClobClient with API credentials."""
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            host = self.config.clob_url
            key = self.config.private_key
            chain_id = self.config.chain_id

            self._client = ClobClient(
                host,
                key=key,
                chain_id=chain_id,
                signature_type=self.config.signature_type,
                funder=self.config.user_address,
            )

            # Set pre-existing API credentials (builder creds from .env)
            if self.config.api_key and self.config.api_secret and self.config.api_passphrase:
                creds = ApiCreds(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    api_passphrase=self.config.api_passphrase,
                )
                self._client.set_api_creds(creds)
                logger.info(
                    "polymarket_broker_initialized_with_api_creds",
                    user_address=self.config.user_address,
                    chain_id=chain_id,
                    api_key=self.config.api_key[:8] + "...",
                )
            else:
                logger.warning(
                    "polymarket_broker_no_api_creds",
                    msg="No API key/secret/passphrase provided. "
                        "Authenticated endpoints will fail with 401.",
                )

        except ImportError:
            logger.error("py_clob_client_not_installed")
            raise RuntimeError(
                "py-clob-client is required for live trading. "
                "Install: pip install py-clob-client"
            )
        except Exception as e:
            logger.error("clob_client_initialization_failed", error=str(e))
            raise

    def _assert_live(self) -> None:
        """Raise if live trading is not enabled."""
        if self._blocked:
            raise RuntimeError("LIVE_TRADING is not enabled — order blocked")
        if self._client is None:
            raise RuntimeError("CLOB client not initialized")

    async def _do_place_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
    ) -> Order:
        """Place a LIMIT order on Polymarket CLOB.

        SAFETY: Only limit orders. Price is passed as-is (caller should
        apply the -0.01 adjustment for buys). Order is GTC and tracked
        for timeout cancellation.
        """
        self._assert_live()

        order_id = str(uuid.uuid4())
        timestamp = time.time()

        clob_side = BUY if side == OrderSide.BUY else SELL

        logger.info(
            "live_order_attempting",
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=clob_side,
            price=price,
            size=size,
        )

        try:
            from py_clob_client.order_builder.constants import BUY as CLOB_BUY, SELL as CLOB_SELL

            clob_side_const = CLOB_BUY if side == OrderSide.BUY else CLOB_SELL

            # Build the order via py-clob-client
            order_args = {
                "token_id": token_id,
                "price": round(price, 2),
                "size": round(size, 2),
                "side": clob_side_const,
            }

            signed_order = self._client.create_order(order_args)
            resp = self._client.post_order(signed_order, "GTC")

            # Extract CLOB order ID from response
            clob_order_id = None
            if isinstance(resp, dict):
                clob_order_id = resp.get("orderID") or resp.get("id")
            elif hasattr(resp, "orderID"):
                clob_order_id = resp.orderID

            # Track for timeout cancellation / cancel-replace
            self._open_orders[order_id] = {
                "clob_order_id": clob_order_id,
                "placed_at": timestamp,
                "market_id": market_id,
                "token_id": token_id,
                "side": clob_side,
                "side_enum": side,
                "price": price,
                "size": size,
                "retries": 0,
                "edge": 0.0,  # populated by caller via set_order_edge
            }

            status = OrderStatus.PENDING
            logger.info(
                "live_order_placed",
                order_id=order_id,
                clob_order_id=clob_order_id,
                market_id=market_id,
                token_id=token_id,
                side=clob_side,
                price=price,
                size=size,
            )

            return Order(
                id=order_id,
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                filled_size=0.0,
                status=status,
                timestamp=timestamp,
                metadata={"clob_order_id": clob_order_id},
            )

        except Exception as e:
            logger.error(
                "live_order_failed",
                order_id=order_id,
                market_id=market_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return Order(
                id=order_id,
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                filled_size=0.0,
                status=OrderStatus.REJECTED,
                timestamp=timestamp,
                metadata={"error": str(e)},
            )

    async def _do_place_market_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        amount: float,
    ) -> Order:
        """BLOCKED: Market orders are not allowed.

        SAFETY: We only use limit orders (maker, zero fees).
        This method always raises RuntimeError.
        """
        logger.error(
            "market_order_blocked",
            market_id=market_id,
            token_id=token_id,
            side=side,
            amount=amount,
            reason="Market orders are permanently disabled for safety. Use limit orders only.",
        )
        raise RuntimeError(
            "SAFETY: Market orders are disabled. Only limit orders allowed "
            "(maker orders = zero fees, no overpaying)."
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order on Polymarket CLOB.

        Args:
            order_id: Internal order ID (maps to CLOB order ID).

        Returns:
            True if cancelled, False otherwise.
        """
        self._assert_live()

        tracked = self._open_orders.get(order_id)
        clob_order_id = tracked["clob_order_id"] if tracked else None

        if not clob_order_id:
            logger.warning("cancel_no_clob_id", order_id=order_id)
            return False

        try:
            resp = self._client.cancel(clob_order_id)

            # Clean up tracking
            self._open_orders.pop(order_id, None)

            logger.info(
                "live_order_cancelled",
                order_id=order_id,
                clob_order_id=clob_order_id,
                response=str(resp)[:200] if resp else None,
            )
            return True

        except Exception as e:
            logger.error(
                "live_cancel_failed",
                order_id=order_id,
                clob_order_id=clob_order_id,
                error=str(e),
            )
            return False

    async def cancel_all_open_orders(self) -> int:
        """Cancel ALL open orders — used by kill switch.

        Returns:
            Number of orders successfully cancelled.
        """
        self._assert_live()

        cancelled = 0
        order_ids = list(self._open_orders.keys())

        for oid in order_ids:
            try:
                if await self.cancel_order(oid):
                    cancelled += 1
            except Exception as e:
                logger.error("cancel_all_error", order_id=oid, error=str(e))

        # Also try the CLOB's cancel-all endpoint as a safety net
        try:
            self._client.cancel_all()
            logger.info("clob_cancel_all_sent")
        except Exception as e:
            logger.error("clob_cancel_all_failed", error=str(e))

        self._open_orders.clear()
        logger.critical("kill_all_orders_complete", cancelled=cancelled, total=len(order_ids))
        return cancelled

    def set_order_edge(self, order_id: str, edge: float) -> None:
        """Set the signal edge for an open order (used by HYBRID fallback)."""
        if order_id in self._open_orders:
            self._open_orders[order_id]["edge"] = edge

    async def check_and_cancel_timed_out_orders(
        self, timeout_seconds: int = 60, current_prices: Optional[dict] = None,
    ) -> list[str]:
        """Cancel or cancel/replace orders that have been open longer than timeout.

        In MAKER mode: cancel/replace at current price up to maker_max_retries,
        then cancel outright.
        In HYBRID mode: same as MAKER but falls back to taker if edge survives fee.
        In TAKER mode: cancel outright (taker orders shouldn't stay open).

        Args:
            timeout_seconds: Max seconds an order can stay open.
            current_prices: Dict of token_id -> current_price for replacement pricing.

        Returns:
            List of cancelled (not replaced) order IDs.
        """
        settings = get_settings()
        mode = settings.execution_mode.upper()
        max_retries = settings.maker_max_retries
        now = time.time()
        cancelled = []

        for oid, info in list(self._open_orders.items()):
            age = now - info["placed_at"]
            if age <= timeout_seconds:
                continue

            retries = info.get("retries", 0)

            # MAKER/HYBRID: attempt cancel/replace if under max retries
            if mode in ("MAKER", "HYBRID") and retries < max_retries:
                new_price = None
                if current_prices:
                    new_price = current_prices.get(info["token_id"])

                if new_price and new_price != info["price"]:
                    replacement = await self.cancel_and_replace_order(
                        oid, new_price, info,
                    )
                    if replacement:
                        logger.info(
                            "maker_cancel_replace",
                            old_order=oid,
                            new_order=replacement.id,
                            old_price=info["price"],
                            new_price=new_price,
                            retry=retries + 1,
                        )
                        continue  # replaced, don't add to cancelled
                    # replace failed — fall through to cancel

            # HYBRID fallback: try taker if edge survives fee
            if mode == "HYBRID" and retries >= max_retries:
                edge = info.get("edge", 0.0)
                fallback = await self._do_taker_fallback(
                    info["market_id"], info["token_id"],
                    info["side_enum"], info["price"], info["size"], edge,
                )
                if fallback:
                    # Cancel the original maker order
                    await self.cancel_order(oid)
                    cancelled.append(oid)
                    logger.info("hybrid_taker_fallback_placed", order_id=fallback.id)
                    continue

            # Final: cancel outright
            logger.info(
                "order_timeout",
                order_id=oid,
                age_seconds=int(age),
                timeout=timeout_seconds,
                retries=retries,
                mode=mode,
            )
            try:
                if await self.cancel_order(oid):
                    cancelled.append(oid)
            except Exception as e:
                logger.error("timeout_cancel_error", order_id=oid, error=str(e))

        return cancelled

    async def cancel_and_replace_order(
        self, order_id: str, new_price: float, info: dict,
    ) -> Optional[Order]:
        """Cancel existing order and place a new one at updated price.

        Returns the new Order on success, None on failure.
        """
        try:
            cancelled = await self.cancel_order(order_id)
            if not cancelled:
                return None

            # Place replacement at new price
            new_order = await self._do_place_order(
                info["market_id"], info["token_id"],
                info["side_enum"], new_price, info["size"],
            )

            # Carry forward retry count + edge
            if new_order.id in self._open_orders:
                self._open_orders[new_order.id]["retries"] = info.get("retries", 0) + 1
                self._open_orders[new_order.id]["edge"] = info.get("edge", 0.0)

            return new_order
        except Exception as e:
            logger.error(
                "cancel_replace_failed",
                order_id=order_id,
                new_price=new_price,
                error=str(e),
            )
            return None

    async def _do_taker_fallback(
        self, market_id: str, token_id: str, side: OrderSide,
        price: float, size: float, edge: float,
    ) -> Optional[Order]:
        """HYBRID only: fall back to taker if edge survives after fee.

        Places an aggressively-priced limit order that crosses the spread
        (pseudo-taker). Only if edge - fee > 0.
        """
        settings = get_settings()
        fee = price * (1 - price) * settings.taker_fee_rate
        net_edge = edge - fee

        if net_edge <= 0:
            logger.info(
                "hybrid_taker_skip_no_edge",
                market_id=market_id,
                edge=round(edge, 4),
                fee=round(fee, 4),
            )
            return None

        # Cross the spread: move price aggressively
        if side == OrderSide.BUY:
            aggressive_price = min(price + 0.02, 0.99)
        else:
            aggressive_price = max(price - 0.02, 0.01)

        logger.info(
            "hybrid_taker_fallback",
            market_id=market_id,
            original_price=price,
            aggressive_price=aggressive_price,
            edge=round(edge, 4),
            fee=round(fee, 4),
            net_edge=round(net_edge, 4),
        )

        try:
            return await self._do_place_order(
                market_id, token_id, side, aggressive_price, size,
            )
        except Exception as e:
            logger.error("taker_fallback_failed", error=str(e))
            return None

    async def get_positions(self) -> list[Position]:
        """Get current positions from Polymarket."""
        self._assert_live()
        logger.debug("fetching_positions_from_clob")
        # Positions are tracked in bot.db, not fetched from CLOB
        return []

    async def sync_positions(self) -> None:
        """Sync positions with Polymarket CLOB."""
        self._assert_live()
        logger.debug("syncing_positions_with_clob")

    async def verify_connectivity(self) -> dict:
        """Verify API connectivity and return status info."""
        status = {
            "clob_url": self.config.clob_url,
            "has_private_key": bool(self.config.private_key),
            "has_api_creds": bool(
                self.config.api_key and self.config.api_secret and self.config.api_passphrase
            ),
            "live_trading": self.config.live_trading,
            "blocked": self._blocked,
            "open_orders_tracked": len(self._open_orders),
        }

        if self._client is not None:
            try:
                server_time = self._client.get_server_time()
                status["server_time"] = server_time
                status["clob_reachable"] = True
            except Exception as e:
                status["clob_reachable"] = False
                status["clob_error"] = str(e)

            if status.get("has_api_creds"):
                try:
                    api_keys = self._client.get_api_keys()
                    status["auth_ok"] = True
                    status["api_keys_count"] = len(api_keys) if api_keys else 0
                except Exception as e:
                    status["auth_ok"] = False
                    status["auth_error"] = str(e)

        return status

    def get_open_order_count(self) -> int:
        """Return number of tracked open orders."""
        return len(self._open_orders)
