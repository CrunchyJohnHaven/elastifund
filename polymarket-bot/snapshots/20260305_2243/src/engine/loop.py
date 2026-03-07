"""Main trading engine loop with safety rail integration.

Supports both paper and live trading. When the broker is a PolymarketBroker,
additional live-trading behaviours are active:
  - Buy price adjustment: market_price - 0.01 (get filled or miss, don't overpay)
  - Order timeout: cancel unfilled orders after ORDER_TIMEOUT_SECONDS
  - Safety rails: daily loss, per-trade cap, exposure cap, cooldown, rollout limits
  - Telegram alerts: every trade, daily P&L summary, errors, kill switch
"""
import asyncio
from datetime import datetime
from typing import Optional

import structlog

from src.broker.base import Broker, OrderSide
from src.core.config import get_settings
from src.data.base import DataFeed
from src.risk.manager import RiskManager
from src.safety import SafetyRails
from src.strategy.base import Strategy
from src.store.database import DatabaseManager
from src.store.repository import Repository
from src.telegram import TelegramNotifier

logger = structlog.get_logger(__name__)

# Price offset for limit buys (get filled or miss, never overpay)
BUY_PRICE_OFFSET = 0.01


class EngineLoop:
    """Main trading engine loop that processes markets and generates trades."""

    def __init__(
        self,
        data_feed: DataFeed,
        broker: Broker,
        risk_manager: RiskManager,
        strategy: Strategy,
        markets: list[dict] | None = None,
        safety_rails: SafetyRails | None = None,
        notifier: TelegramNotifier | None = None,
    ):
        """Initialize the engine loop.

        Args:
            data_feed: DataFeed instance for price data
            broker: Broker instance for order execution (Paper or Live)
            risk_manager: RiskManager instance for risk checks
            strategy: Strategy instance for signal generation
            markets: List of market configurations
            safety_rails: SafetyRails instance (live trading guardrails)
            notifier: TelegramNotifier for alerts
        """
        self.data_feed = data_feed
        self.broker = broker
        self.risk_manager = risk_manager
        self.strategy = strategy
        self.markets = markets or [{"market_id": "mock_001", "token_id": "YES"}]
        self.safety_rails = safety_rails or SafetyRails()
        self.notifier = notifier
        self._running = False
        self._price_history: dict[str, list[float]] = {}
        self._is_live = self._check_is_live()

    def _check_is_live(self) -> bool:
        """Check if we're using a live broker."""
        try:
            from src.broker.polymarket_broker import PolymarketBroker
            return isinstance(self.broker, PolymarketBroker)
        except ImportError:
            return False

    async def run(self) -> None:
        """Start the main engine loop."""
        settings = get_settings()
        self._running = True
        mode = "LIVE" if self._is_live else "PAPER"
        logger.info(
            "engine_started",
            mode=mode,
            loop_seconds=settings.engine_loop_seconds,
            markets=len(self.markets),
        )

        while self._running:
            try:
                # Heartbeat
                async with DatabaseManager.get_session() as session:
                    await Repository.update_heartbeat(session)
                    await session.commit()

                # Kill switch check
                async with DatabaseManager.get_session() as session:
                    if await Repository.get_kill_switch(session):
                        logger.warning("engine_paused_kill_switch")
                        await asyncio.sleep(settings.engine_loop_seconds)
                        continue

                # Process markets
                for market_config in self.markets:
                    try:
                        await self._process_market(market_config)
                    except Exception as e:
                        logger.error(
                            "market_processing_error",
                            market_id=market_config.get("market_id"),
                            error=str(e),
                        )
                        async with DatabaseManager.get_session() as session:
                            bot_state = await Repository.get_or_create_bot_state(session)
                            bot_state.last_error = str(e)[:500]
                            await session.commit()

                        # Alert on error
                        if self.notifier and self.notifier.is_configured:
                            await self.notifier.send_error(
                                str(e)[:300],
                                context=f"market={market_config.get('market_id', '?')}",
                            )

                # Order timeout cancellation (live only)
                if self._is_live:
                    await self._cancel_timed_out_orders()

                await asyncio.sleep(settings.engine_loop_seconds)

            except asyncio.CancelledError:
                logger.info("engine_cancelled")
                break
            except Exception as e:
                logger.error("engine_loop_error", error=str(e))
                if self.notifier and self.notifier.is_configured:
                    await self.notifier.send_error(str(e)[:300], context="engine_loop")
                await asyncio.sleep(settings.engine_loop_seconds)

        logger.info("engine_stopped")

    async def stop(self) -> None:
        """Stop the engine loop. Cancel all open orders if live."""
        logger.info("stopping_engine")
        self._running = False

        # Cancel all open orders on shutdown (live safety)
        if self._is_live:
            try:
                from src.broker.polymarket_broker import PolymarketBroker
                if isinstance(self.broker, PolymarketBroker):
                    cancelled = await self.broker.cancel_all_open_orders()
                    logger.info("shutdown_orders_cancelled", count=cancelled)
            except Exception as e:
                logger.error("shutdown_cancel_failed", error=str(e))

    async def _process_market(self, market_config: dict) -> None:
        """Process a single market: get price, generate signal, place order if needed.

        Args:
            market_config: Market configuration dict with market_id, token_id, etc.
        """
        settings = get_settings()
        market_id = market_config["market_id"]
        token_id = market_config.get("token_id", "YES")

        # Fetch price
        price = await self.data_feed.get_price(token_id)
        self.risk_manager.record_price_time(token_id)

        # Track price history
        if token_id not in self._price_history:
            self._price_history[token_id] = []
        self._price_history[token_id].append(price)
        if len(self._price_history[token_id]) > 100:
            self._price_history[token_id] = self._price_history[token_id][-100:]

        # Build market state
        async with DatabaseManager.get_session() as session:
            positions = await Repository.get_all_positions(session)

        market_state = {
            "market_id": market_id,
            "token_id": token_id,
            "question": market_config.get("question", ""),
            "current_price": price,
            "midpoint": price,
            "orderbook_depth": {},
            "positions": positions,
            "price_history": self._price_history.get(token_id, []),
            "timestamp": datetime.utcnow(),
        }

        # Get signal
        signal = await self.strategy.generate_signal(market_state)
        action = signal.get("action", "hold")

        if action == "hold":
            logger.debug("signal_hold", market_id=market_id, reason=signal.get("reason"))
            return

        size = signal.get("size", 0)
        if size <= 0:
            return

        # Map action to side and token
        side = OrderSide.BUY
        effective_token = token_id
        if action == "buy_no":
            effective_token = "NO"

        # Volatility check
        if RiskManager.check_volatility_pause(self._price_history.get(token_id, [])):
            logger.warning("volatility_pause", market_id=market_id)
            return

        # ── SAFETY RAILS (pre-trade) ──────────────────────────────
        # Clamp size to rollout/per-trade cap
        size = self.safety_rails.clamp_size(size)
        if size <= 0:
            return

        # Calculate exposure for safety check
        async with DatabaseManager.get_session() as session:
            all_positions = await Repository.get_all_positions(session)
            total_exposure = sum(
                p.size * p.avg_entry_price for p in all_positions
            )
            daily_pnl = await Repository.get_daily_pnl(session, datetime.utcnow())

        # Estimate bankroll (exposure + configured max as proxy)
        bankroll = total_exposure + settings.max_position_usd

        safe, reason = self.safety_rails.check_pre_trade(
            trade_size_usd=size * price,
            bankroll=bankroll,
            total_exposure_usd=total_exposure,
            daily_pnl=daily_pnl,
        )
        if not safe:
            logger.warning("safety_rail_blocked", market_id=market_id, reason=reason)
            if self.notifier and self.notifier.is_configured:
                await self.notifier.send_error(
                    f"Safety rail blocked trade: {reason}",
                    context=f"market={market_id}",
                )
            return

        # ── RISK MANAGER (pre-trade) ─────────────────────────────
        async with DatabaseManager.get_session() as session:
            allowed, reason = await self.risk_manager.check_pre_trade(
                session, market_id, effective_token, side.value, size, price
            )
            if not allowed:
                logger.warning("trade_rejected", market_id=market_id, reason=reason)
                return

        # ── PRICE ADJUSTMENT (live only) ──────────────────────────
        order_price = price
        if self._is_live and side == OrderSide.BUY:
            # Limit buy at market_price - 0.01: get filled or miss, don't overpay
            order_price = round(max(0.01, price - BUY_PRICE_OFFSET), 2)
            logger.info(
                "buy_price_adjusted",
                market_price=price,
                order_price=order_price,
                offset=BUY_PRICE_OFFSET,
            )

        # ── PLACE ORDER ──────────────────────────────────────────
        order = await self.broker.place_order(
            market_id, effective_token, side, order_price, size
        )

        logger.info(
            "order_placed",
            mode="LIVE" if self._is_live else "PAPER",
            market_id=market_id,
            order_id=order.id,
            action=action,
            price=order_price,
            size=size,
            status=order.status,
        )

        # Record in safety rails
        self.safety_rails.record_trade()

        # Log to database
        async with DatabaseManager.get_session() as session:
            await Repository.create_order(
                session,
                market_id=market_id,
                token_id=effective_token,
                side=side.value.upper(),
                order_type="LIMIT",
                price=order_price,
                size=size,
            )
            await session.commit()

        # ── TELEGRAM ALERT ────────────────────────────────────────
        if self.notifier and self.notifier.is_configured:
            await self.notifier.send_trade_signal(
                market_name=market_config.get("question", market_id)[:100],
                direction=action,
                price=order_price,
                size=size,
                reasoning=signal.get("reason", ""),
            )

    async def _cancel_timed_out_orders(self) -> None:
        """Cancel orders that exceeded the timeout (live only)."""
        try:
            from src.broker.polymarket_broker import PolymarketBroker
            if isinstance(self.broker, PolymarketBroker):
                settings = get_settings()
                cancelled = await self.broker.check_and_cancel_timed_out_orders(
                    timeout_seconds=settings.order_timeout_seconds
                )
                if cancelled:
                    logger.info("timed_out_orders_cancelled", count=len(cancelled))
                    # Update DB status
                    async with DatabaseManager.get_session() as session:
                        for oid in cancelled:
                            await Repository.update_order_status(session, oid, "CANCELLED")
                        await session.commit()
                    # Telegram alert
                    if self.notifier and self.notifier.is_configured:
                        await self.notifier.send_message(
                            f"⏰ <b>Order Timeout</b>\n\n"
                            f"{len(cancelled)} order(s) cancelled after "
                            f"{settings.order_timeout_seconds}s timeout."
                        )
        except ImportError:
            pass
