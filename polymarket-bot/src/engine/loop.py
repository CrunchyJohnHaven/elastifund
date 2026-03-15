"""Main trading engine loop with safety rail integration.

Supports both paper and live trading. When the broker is a PolymarketBroker,
additional live-trading behaviours are active:
  - Buy price adjustment: market_price - 0.01 (get filled or miss, don't overpay)
  - Order timeout: cancel unfilled orders after ORDER_TIMEOUT_SECONDS
  - Safety rails: daily loss, per-trade cap, exposure cap, cooldown, rollout limits
  - Telegram alerts: every trade, daily P&L summary, errors, kill switch
  - Execution instrumentation: per-trade stats (slippage, fee, fill time, cancel rate)
  - Maker sandbox: small conservative limit orders when MAKER_MODE=true
"""
import asyncio
import time as _time
from datetime import datetime
from src.core.time_utils import utc_now_naive
from typing import Optional, TYPE_CHECKING

import structlog

from src.broker.base import Broker, OrderSide
from src.core.config import get_settings
from src.data.base import DataFeed
from src.exit_strategy import ExitStrategy, ExitStrategyConfig
from src.lmsr import detect_inefficiency, InefficiencySignal
from src.bayesian_signal import (
    BayesianSignalProcessor,
    evidence_from_claude,
    evidence_from_price_move,
)
from src.risk.manager import RiskManager
from src.risk.sizing import compute_sizing, SizingCaps
from src.safety import SafetyRails
from src.strategy.base import Strategy
from src.store.database import DatabaseManager
from src.store.repository import Repository
from src.telegram import TelegramNotifier

if TYPE_CHECKING:
    from src.telemetry.elastic import ElasticTelemetry

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
        exit_config: ExitStrategyConfig | None = None,
        telemetry: "ElasticTelemetry | None" = None,
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
            exit_config: ExitStrategyConfig for active position management
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
        self.exit_strategy = ExitStrategy(broker, exit_config or ExitStrategyConfig())
        self.telemetry = telemetry

        # Bayesian signal processor for sequential belief updating
        self.bayesian = BayesianSignalProcessor(
            evidence_decay_hours=24.0,
            max_log_odds=5.0,
        )

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
        await self._emit_elastic_agent_status("running")

        while self._running:
            try:
                # Heartbeat
                async with DatabaseManager.get_session() as session:
                    await Repository.update_heartbeat(session)
                    await session.commit()

                # Kill switch check — also cancel all open orders when killed
                async with DatabaseManager.get_session() as session:
                    if await Repository.get_kill_switch(session):
                        logger.warning("engine_paused_kill_switch")
                        await self._emit_elastic_agent_status(
                            "paused",
                            extra={"kill_switch": True},
                        )
                        await self._kill_switch_cancel_all()
                        await asyncio.sleep(settings.engine_loop_seconds)
                        continue

                # Phase 0: Check open positions for exits (free capital)
                await self._check_position_exits()

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

                await self._emit_elastic_cycle_metrics()
                await asyncio.sleep(settings.engine_loop_seconds)

            except asyncio.CancelledError:
                logger.info("engine_cancelled")
                break
            except Exception as e:
                logger.error("engine_loop_error", error=str(e))
                await self._emit_elastic_agent_status(
                    "error",
                    extra={"last_error": str(e)[:500]},
                )
                if self.notifier and self.notifier.is_configured:
                    await self.notifier.send_error(str(e)[:300], context="engine_loop")
                await asyncio.sleep(settings.engine_loop_seconds)

        logger.info("engine_stopped")

    async def stop(self) -> None:
        """Stop the engine loop. Cancel all open orders if live."""
        logger.info("stopping_engine")
        self._running = False
        await self._emit_elastic_agent_status("stopping")

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
            "timestamp": utc_now_naive(),
        }

        # ── BAYESIAN UPDATE (price action evidence) ──────────────
        price_history = self._price_history.get(token_id, [])
        if len(price_history) >= 2:
            price_change = (price_history[-1] - price_history[-2]) / max(price_history[-2], 0.01)
            if abs(price_change) > 0.005:  # Only update on >0.5% moves
                ev = evidence_from_price_move(price_change, volume_ratio=1.0)
                self.bayesian.update(market_id, ev)

        # Get signal
        signal = await self.strategy.generate_signal(market_state)
        action = signal.get("action", "hold")

        # ── BAYESIAN UPDATE (Claude evidence) ─────────────────────
        estimated_prob_for_bayes = signal.get("estimated_prob", signal.get("confidence", 0.5))
        confidence_for_bayes = signal.get("confidence", 0.5)
        if 0.01 < estimated_prob_for_bayes < 0.99:
            claude_ev = evidence_from_claude(estimated_prob_for_bayes, confidence_for_bayes)
            self.bayesian.update(market_id, claude_ev)
            bayes_signal = self.bayesian.get_signal(market_id, price)
            logger.debug(
                "bayesian_signal",
                market_id=market_id,
                p_bayes=round(bayes_signal["p_bayesian"], 4),
                bayes_edge=round(bayes_signal["edge"], 4),
                bayes_dir=bayes_signal["direction"],
                evidence_count=bayes_signal["evidence_count"],
            )

        # ── LMSR INEFFICIENCY CHECK ───────────────────────────────
        volume_yes = market_config.get("volume_yes", 0)
        volume_no = market_config.get("volume_no", 0)
        if volume_yes > 0 and volume_no > 0:
            lmsr_signal = detect_inefficiency(
                market_id=market_id,
                clob_price_yes=price,
                volume_yes=volume_yes,
                volume_no=volume_no,
            )
            if lmsr_signal.is_inefficient:
                logger.info(
                    "lmsr_inefficiency",
                    market_id=market_id,
                    lmsr_price=round(lmsr_signal.lmsr_price_yes, 4),
                    clob_price=round(lmsr_signal.clob_price_yes, 4),
                    divergence=round(lmsr_signal.divergence, 4),
                    lmsr_direction=lmsr_signal.direction,
                )
                # If both Claude and LMSR agree on direction, boost confidence
                if action != "hold" and lmsr_signal.direction == action:
                    signal["lmsr_confirmed"] = True
                    signal["lmsr_edge"] = lmsr_signal.estimated_edge

        if action == "hold":
            logger.debug("signal_hold", market_id=market_id, reason=signal.get("reason"))
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

        # ── KELLY SIZING ──────────────────────────────────────────
        estimated_prob = signal.get("estimated_prob", signal.get("confidence", 0.5))
        category = market_config.get("category", "Unknown")

        # Calculate bankroll and category counts
        async with DatabaseManager.get_session() as session:
            all_positions = await Repository.get_all_positions(session)
            total_exposure = sum(
                p.size * p.avg_entry_price for p in all_positions
            )
            daily_pnl = await Repository.get_daily_pnl(session, utc_now_naive())

        bankroll = total_exposure + settings.max_position_usd

        category_counts: dict[str, int] = {}
        for p in all_positions:
            cat = getattr(p, "category", "Unknown") or "Unknown"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Time-aware Kelly dampening (QR-PM-2026-0041)
        hours_to_res = market_config.get("hours_to_resolution", None)

        caps = SizingCaps(
            max_position_usd=settings.max_position_usd,
            min_edge_buffer=settings.min_edge_buffer,
            fee_rate=0.02,  # Polymarket winner fee
            fallback_on_missing=settings.sizing_fallback_on_missing,
            safe_fallback_usd=settings.sizing_safe_fallback_usd,
            hours_to_resolution=hours_to_res,
        )

        sizing = compute_sizing(
            market_id=market_id,
            p_estimated=estimated_prob,
            p_market=price,
            side=action,
            bankroll=bankroll,
            category=category,
            category_counts=category_counts,
            caps=caps,
        )

        # Log sizing decision to DB
        async with DatabaseManager.get_session() as session:
            await Repository.create_sizing_decision_from_result(session, sizing)
            await session.commit()

        if sizing.decision != "trade":
            logger.debug(
                "kelly_skip",
                market_id=market_id,
                reason=sizing.skip_reason,
                edge_after_fee=round(sizing.edge_after_fee, 4),
            )
            return

        size = sizing.final_size_usd

        logger.info(
            "kelly_sized",
            market_id=market_id,
            kelly_f=round(sizing.kelly_f, 4),
            kelly_mult=round(sizing.kelly_mult, 2),
            edge_after_fee=round(sizing.edge_after_fee, 4),
            size=round(size, 2),
            bankroll=round(bankroll, 2),
        )

        # ── SAFETY RAILS (pre-trade) ──────────────────────────────
        # Clamp size to rollout/per-trade cap
        size = self.safety_rails.clamp_size(size)
        if size <= 0:
            return

        safe, reason = self.safety_rails.check_pre_trade(
            trade_size_usd=size * price,
            bankroll=bankroll,
            total_exposure_usd=total_exposure,
            daily_pnl=daily_pnl,
            open_positions_count=len(all_positions),
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
        # Compute expected fee for instrumentation
        expected_fee = price * (1 - price) * settings.taker_fee_rate
        place_time = _time.time()

        order = await self.broker.place_order(
            market_id, effective_token, side, order_price, size
        )

        # Set edge on the order for HYBRID taker fallback
        if self._is_live:
            try:
                from src.broker.polymarket_broker import PolymarketBroker
                if isinstance(self.broker, PolymarketBroker):
                    self.broker.set_order_edge(order.id, sizing.edge_after_fee)
            except (ImportError, AttributeError):
                pass

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

        await self._emit_elastic_trade(
            order=order,
            market_config=market_config,
            action=action,
            signal=signal,
            order_price=order_price,
            size=size,
            metadata={
                "mode": "live" if self._is_live else "paper",
                "token_id": effective_token,
                "confidence": signal.get("confidence"),
                "estimated_prob": signal.get("estimated_prob"),
                "reason": signal.get("reason"),
                "execution_mode": settings.execution_mode.upper(),
            },
        )

        # ── EXECUTION INSTRUMENTATION ──────────────────────────────
        try:
            async with DatabaseManager.get_session() as session:
                await Repository.create_execution_stat(
                    session,
                    order_id=order.id,
                    market_id=market_id,
                    token_id=effective_token,
                    side=side.value.upper(),
                    quoted_mid=price,
                    order_price=order_price,
                    expected_fee=expected_fee,
                    expected_edge=sizing.edge_after_fee,
                    execution_mode=settings.execution_mode.upper(),
                    is_maker_sandbox=False,
                )
                # If paper broker fills immediately, record fill stats now
                if order.status.value == "filled":
                    fill_time = _time.time() - place_time
                    actual_fee = order_price * (1 - order_price) * settings.taker_fee_rate
                    await Repository.update_execution_stat_fill(
                        session,
                        order_id=order.id,
                        fill_price=order_price,
                        actual_fee=actual_fee,
                        fill_time_seconds=fill_time,
                    )
                await session.commit()
        except Exception as e:
            logger.warning("execution_stat_write_failed", error=str(e))

        # ── MAKER SANDBOX ──────────────────────────────────────────
        if settings.maker_mode and sizing.edge_after_fee > 0:
            await self._place_maker_sandbox_order(
                market_id=market_id,
                token_id=effective_token,
                side=side,
                mid_price=price,
                normal_size=size,
                edge_after_fee=sizing.edge_after_fee,
            )

        # ── TELEGRAM ALERT ────────────────────────────────────────
        if self.notifier and self.notifier.is_configured:
            await self.notifier.send_trade_signal(
                market_name=market_config.get("question", market_id)[:100],
                direction=action,
                price=order_price,
                size=size,
                reasoning=signal.get("reason", ""),
            )

        # ── REGISTER FOR EXIT MONITORING ──────────────────────────
        if order.status.value == "filled":
            from src.broker.base import Position as BrokerPosition
            broker_pos = BrokerPosition(
                token_id=effective_token,
                size=order.filled_size,
                entry_price=order_price,
                current_price=price,
                pnl=0.0,
                pnl_pct=0.0,
                timestamp=order.timestamp,
            )
            estimated_prob = signal.get("estimated_prob", signal.get("confidence", 0.5))
            self.exit_strategy.track_position(
                position=broker_pos,
                market_id=market_id,
                estimated_prob=estimated_prob,
                entry_side=action,
            )

    async def _check_position_exits(self) -> None:
        """Phase 0: Check all tracked positions for exit conditions.

        Fetches current prices for all tracked positions and runs exit logic.
        Exits free up capital for new entries in the same cycle.
        """
        tracked = self.exit_strategy.get_tracked_positions()
        if not tracked:
            return

        # Gather current prices for all tracked tokens
        current_prices: dict[str, float] = {}
        for key, tp in tracked.items():
            token_id = tp.position.token_id
            if token_id not in current_prices:
                try:
                    price = await self.data_feed.get_price(token_id)
                    current_prices[token_id] = price
                except Exception as e:
                    logger.error("exit_price_fetch_error", token_id=token_id, error=str(e))

        # Run exit checks
        exits = await self.exit_strategy.check_exits(current_prices)

        if exits:
            stats = self.exit_strategy.get_stats()
            logger.info(
                "exit_cycle_summary",
                exits_this_cycle=len(exits),
                total_exits=stats["total_exits"],
                total_exit_pnl=stats["total_pnl"],
                capital_freed=round(sum(e.exit_price * e.size for e in exits), 2),
                remaining_tracked=len(self.exit_strategy.get_tracked_positions()),
            )

            # Telegram alert for exits
            if self.notifier and self.notifier.is_configured:
                for ex in exits:
                    await self.notifier.send_message(
                        f"<b>Position Exited</b>\n"
                        f"Reason: {ex.reason.value}\n"
                        f"Market: {ex.market_id}\n"
                        f"Entry: ${ex.entry_price:.3f} → Exit: ${ex.exit_price:.3f}\n"
                        f"P&L: ${ex.realized_pnl:+.4f} ({ex.pnl_pct:+.1f}%)\n"
                        f"Held: {ex.hold_time_hours:.1f}h"
                    )

    async def _place_maker_sandbox_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        mid_price: float,
        normal_size: float,
        edge_after_fee: float,
    ) -> None:
        """Place a small maker sandbox limit order at conservative price.

        Safety-first: 10-20% of normal size, conservative price improvement,
        auto-cancel on timeout, at most 1 reprice, respects all safety rails + kill switch.
        """
        settings = get_settings()

        # Sandbox size: fraction of normal size
        sandbox_size = round(normal_size * settings.maker_sandbox_size_pct, 2)
        if sandbox_size < 0.50:
            logger.debug("maker_sandbox_skip_too_small", size=sandbox_size)
            return

        # Conservative price: improve on mid by edge_improvement (place deeper in book)
        improvement = settings.maker_sandbox_edge_improvement
        if side == OrderSide.BUY:
            sandbox_price = round(max(0.01, mid_price - improvement), 2)
        else:
            sandbox_price = round(min(0.99, mid_price + improvement), 2)

        logger.info(
            "maker_sandbox_placing",
            market_id=market_id,
            token_id=token_id,
            side=side.value,
            mid_price=mid_price,
            sandbox_price=sandbox_price,
            sandbox_size=sandbox_size,
            improvement=improvement,
        )

        try:
            place_time = _time.time()
            sandbox_order = await self.broker.place_order(
                market_id, token_id, side, sandbox_price, sandbox_size,
            )

            # Record execution stat for sandbox order
            expected_fee = 0.0  # Maker fee is zero
            async with DatabaseManager.get_session() as session:
                await Repository.create_execution_stat(
                    session,
                    order_id=sandbox_order.id,
                    market_id=market_id,
                    token_id=token_id,
                    side=side.value.upper(),
                    quoted_mid=mid_price,
                    order_price=sandbox_price,
                    expected_fee=expected_fee,
                    expected_edge=edge_after_fee,
                    execution_mode="MAKER_SANDBOX",
                    is_maker_sandbox=True,
                )
                # Paper broker fills immediately
                if sandbox_order.status.value == "filled":
                    fill_time = _time.time() - place_time
                    await Repository.update_execution_stat_fill(
                        session,
                        order_id=sandbox_order.id,
                        fill_price=sandbox_price,
                        actual_fee=0.0,
                        fill_time_seconds=fill_time,
                    )
                await session.commit()

            logger.info(
                "maker_sandbox_order_placed",
                order_id=sandbox_order.id,
                market_id=market_id,
                price=sandbox_price,
                size=sandbox_size,
                status=sandbox_order.status.value,
            )
            await self._emit_elastic_trade(
                order=sandbox_order,
                market_config={"market_id": market_id, "question": market_id},
                action=f"{side.value}_maker_sandbox",
                signal={},
                order_price=sandbox_price,
                size=sandbox_size,
                metadata={
                    "mode": "live" if self._is_live else "paper",
                    "token_id": token_id,
                    "execution_mode": "MAKER_SANDBOX",
                    "is_maker_sandbox": True,
                    "expected_edge": edge_after_fee,
                    "mid_price": mid_price,
                },
            )

        except Exception as e:
            logger.warning("maker_sandbox_order_failed", market_id=market_id, error=str(e))

    async def _cancel_timed_out_orders(self) -> None:
        """Cancel or cancel/replace orders that exceeded the timeout (live only).

        Uses maker_replace_timeout_seconds for the cancel/replace cycle,
        passing current prices so the broker can re-place at updated price.
        Also records execution stat cancellations.
        """
        try:
            from src.broker.polymarket_broker import PolymarketBroker
            if isinstance(self.broker, PolymarketBroker):
                settings = get_settings()

                # Gather current prices for open order tokens
                current_prices: dict[str, float] = {}
                for oid, info in self.broker._open_orders.items():
                    tid = info["token_id"]
                    if tid not in current_prices:
                        try:
                            current_prices[tid] = await self.data_feed.get_price(tid)
                        except Exception:
                            pass

                cancelled = await self.broker.check_and_cancel_timed_out_orders(
                    timeout_seconds=settings.maker_replace_timeout_seconds,
                    current_prices=current_prices,
                )
                if cancelled:
                    logger.info("timed_out_orders_cancelled", count=len(cancelled))
                    async with DatabaseManager.get_session() as session:
                        for oid in cancelled:
                            await Repository.update_order_status(session, oid, "CANCELLED")
                            await Repository.update_execution_stat_cancel(
                                session, oid, reason="timeout",
                            )
                        await session.commit()
                    if self.notifier and self.notifier.is_configured:
                        await self.notifier.send_message(
                            f"<b>Order Timeout</b>\n\n"
                            f"{len(cancelled)} order(s) cancelled/replaced after "
                            f"{settings.maker_replace_timeout_seconds}s timeout."
                        )
        except ImportError:
            pass

    async def _kill_switch_cancel_all(self) -> None:
        """When kill switch activates, cancel all open orders immediately."""
        if not self._is_live:
            return
        try:
            from src.broker.polymarket_broker import PolymarketBroker
            if isinstance(self.broker, PolymarketBroker):
                cancelled = await self.broker.cancel_all_open_orders()
                logger.critical("kill_switch_cancelled_all_orders", count=cancelled)
                async with DatabaseManager.get_session() as session:
                    await Repository.create_risk_event(
                        session, "kill_switch_cancel_all",
                        f"Cancelled {cancelled} open orders on kill switch activation",
                    )
                    await session.commit()
        except Exception as e:
            logger.error("kill_cancel_all_failed", error=str(e))

    def _strategy_id(self) -> str:
        strategy_name = getattr(self.strategy, "name", "default")
        if self.telemetry:
            return self.telemetry.resolve_strategy_id(strategy_name)
        return strategy_name

    async def _emit_elastic_agent_status(
        self,
        status: str,
        extra: dict | None = None,
    ) -> None:
        if not self.telemetry or not self.telemetry.enabled:
            return
        settings = get_settings()
        metadata = {
            "mode": "live" if self._is_live else "paper",
            "strategy": getattr(self.strategy, "name", "unknown"),
            "strategy_id": self._strategy_id(),
            "markets": len(self.markets),
            "engine_loop_seconds": settings.engine_loop_seconds,
            "live_trading": settings.live_trading,
            "no_trade_mode": settings.no_trade_mode,
            "notifier_enabled": bool(self.notifier and self.notifier.is_configured),
        }
        if extra:
            metadata.update(extra)
        await self.telemetry.upsert_agent_status(status=status, metadata=metadata)

    async def _emit_elastic_cycle_metrics(self) -> None:
        if not self.telemetry or not self.telemetry.enabled:
            return

        try:
            positions = await self.broker.get_positions()
        except Exception as exc:
            logger.debug("elastic_metrics_positions_unavailable", error=str(exc))
            positions = []

        pnl_usd = round(sum(float(getattr(pos, "pnl", 0.0) or 0.0) for pos in positions), 6)
        settings = get_settings()
        drawdown_pct = 0.0
        if settings.max_daily_drawdown_usd > 0 and pnl_usd < 0:
            drawdown_pct = min(
                100.0,
                abs(pnl_usd) / settings.max_daily_drawdown_usd * 100,
            )

        async with DatabaseManager.get_session() as session:
            summary = await Repository.get_execution_summary(session)
            bot_state = await Repository.get_or_create_bot_state(session)
            open_orders = await Repository.get_open_orders(session)

        total_cost = float(summary.get("avg_actual_fee") or 0.0) * float(
            summary.get("filled") or 0
        )
        await self.telemetry.emit_metrics(
            strategy_id=self._strategy_id(),
            pnl_usd=pnl_usd,
            drawdown_pct=drawdown_pct,
            revenue_usd=pnl_usd,
            sharpe_ratio=0.0,
            cost_usd=total_cost,
        )
        await self._emit_elastic_agent_status(
            "running",
            extra={
                "kill_switch": bot_state.kill_switch,
                "last_error": bot_state.last_error,
                "last_heartbeat": (
                    bot_state.last_heartbeat.isoformat()
                    if bot_state.last_heartbeat
                    else None
                ),
                "open_positions": len(positions),
                "open_orders": len(open_orders),
                "tracked_orders": summary.get("total_orders_tracked", 0),
                "fill_rate": summary.get("fill_rate", 0.0),
                "cancel_rate": summary.get("cancel_rate", 0.0),
                "paper_pnl_usd": pnl_usd,
            },
        )

    async def _emit_elastic_trade(
        self,
        *,
        order,
        market_config: dict,
        action: str,
        signal: dict,
        order_price: float,
        size: float,
        metadata: dict | None = None,
    ) -> None:
        if not self.telemetry or not self.telemetry.enabled:
            return
        side = getattr(order.side, "value", str(order.side)).upper()
        status = getattr(order.status, "value", str(order.status)).upper()
        trade_metadata = {
            "question": market_config.get("question", ""),
            "action": action,
            "reason": signal.get("reason"),
            **(metadata or {}),
        }
        await self.telemetry.emit_trade(
            trade_id=order.id,
            strategy_id=self._strategy_id(),
            market_id=market_config["market_id"],
            side=side,
            order_type="LIMIT",
            status=status,
            price=order_price,
            size=size,
            metadata=trade_metadata,
        )
