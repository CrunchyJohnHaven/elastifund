"""Repository pattern implementation for database operations."""
from datetime import datetime, timedelta
from typing import Optional, Sequence
from uuid import uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.core.config import get_settings
from src.store.models import BotState, ExecutionStat, Fill, Order, PortfolioSnapshot, Position, RiskEvent, ShadowOrder, SizingDecision

logger = get_logger(__name__)


class Repository:
    """Repository for all database operations."""

    # ========== Order Operations ==========

    @staticmethod
    async def create_order(
        session: AsyncSession,
        market_id: str,
        token_id: str,
        side: str,
        order_type: str,
        price: float,
        size: float,
    ) -> Order:
        """Create a new order in the database.

        Args:
            session: Async database session
            market_id: Market identifier
            token_id: Token identifier
            side: Order side (BUY/SELL)
            order_type: Order type (LIMIT/MARKET)
            price: Order price
            size: Order size

        Returns:
            Created Order object
        """
        order_id = str(uuid4())
        order = Order(
            id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            order_type=order_type,
            price=price,
            size=size,
        )
        session.add(order)
        await session.flush()
        logger.info(
            "Created order",
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
        )
        return order

    @staticmethod
    async def update_order_status(
        session: AsyncSession,
        order_id: str,
        status: str,
        filled_size: Optional[float] = None,
    ) -> Optional[Order]:
        """Update order status and optionally filled size.

        Args:
            session: Async database session
            order_id: Order identifier
            status: New order status
            filled_size: Optional filled size update

        Returns:
            Updated Order object or None if not found
        """
        stmt = select(Order).where(Order.id == order_id)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()

        if order:
            order.status = status
            if filled_size is not None:
                order.filled_size = filled_size
            order.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(
                "Updated order status",
                order_id=order_id,
                status=status,
                filled_size=filled_size,
            )

        return order

    @staticmethod
    async def get_open_orders(session: AsyncSession) -> Sequence[Order]:
        """Get all open orders.

        Args:
            session: Async database session

        Returns:
            List of open Order objects
        """
        stmt = select(Order).where(
            Order.status.in_(["PENDING", "PARTIALLY_FILLED"])
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    # ========== Fill Operations ==========

    @staticmethod
    async def create_fill(
        session: AsyncSession,
        order_id: str,
        price: float,
        size: float,
        fee: float = 0.0,
    ) -> Fill:
        """Create a new fill record for an order.

        Args:
            session: Async database session
            order_id: Parent order identifier
            price: Fill price
            size: Fill size
            fee: Trading fee

        Returns:
            Created Fill object
        """
        fill_id = str(uuid4())
        fill = Fill(
            id=fill_id,
            order_id=order_id,
            price=price,
            size=size,
            fee=fee,
        )
        session.add(fill)
        await session.flush()
        logger.info(
            "Created fill",
            fill_id=fill_id,
            order_id=order_id,
            price=price,
            size=size,
            fee=fee,
        )
        return fill

    # ========== Position Operations ==========

    @staticmethod
    async def get_position(
        session: AsyncSession,
        market_id: str,
        token_id: str,
    ) -> Optional[Position]:
        """Get position for a specific market and token.

        Args:
            session: Async database session
            market_id: Market identifier
            token_id: Token identifier

        Returns:
            Position object or None if not found
        """
        stmt = select(Position).where(
            and_(Position.market_id == market_id, Position.token_id == token_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_position(
        session: AsyncSession,
        market_id: str,
        token_id: str,
        side: str,
        size: float,
        avg_entry_price: float,
        unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0,
    ) -> Position:
        """Create or update a position.

        Args:
            session: Async database session
            market_id: Market identifier
            token_id: Token identifier
            side: Position side (LONG/SHORT)
            size: Position size
            avg_entry_price: Average entry price
            unrealized_pnl: Unrealized profit/loss
            realized_pnl: Realized profit/loss

        Returns:
            Created or updated Position object
        """
        position = await Repository.get_position(session, market_id, token_id)

        if position:
            position.side = side
            position.size = size
            position.avg_entry_price = avg_entry_price
            position.unrealized_pnl = unrealized_pnl
            position.realized_pnl = realized_pnl
            position.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(
                "Updated position",
                market_id=market_id,
                token_id=token_id,
                size=size,
            )
        else:
            position_id = str(uuid4())
            position = Position(
                id=position_id,
                market_id=market_id,
                token_id=token_id,
                side=side,
                size=size,
                avg_entry_price=avg_entry_price,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
            )
            session.add(position)
            await session.flush()
            logger.info(
                "Created position",
                position_id=position_id,
                market_id=market_id,
                token_id=token_id,
                size=size,
            )

        return position

    @staticmethod
    async def get_all_positions(session: AsyncSession) -> Sequence[Position]:
        """Get all positions.

        Args:
            session: Async database session

        Returns:
            List of all Position objects
        """
        stmt = select(Position)
        result = await session.execute(stmt)
        return result.scalars().all()

    # ========== BotState Operations ==========

    @staticmethod
    async def get_or_create_bot_state(session: AsyncSession) -> BotState:
        """Get or create singleton bot state record.

        Args:
            session: Async database session

        Returns:
            BotState object
        """
        stmt = select(BotState).where(BotState.id == 1)
        result = await session.execute(stmt)
        bot_state = result.scalar_one_or_none()

        if not bot_state:
            bot_state = BotState(id=1)
            session.add(bot_state)
            await session.flush()
            logger.info("Created bot state")

        return bot_state

    @staticmethod
    async def update_heartbeat(session: AsyncSession) -> BotState:
        """Update bot heartbeat timestamp.

        Args:
            session: Async database session

        Returns:
            Updated BotState object
        """
        bot_state = await Repository.get_or_create_bot_state(session)
        bot_state.last_heartbeat = datetime.utcnow()
        await session.flush()
        return bot_state

    @staticmethod
    async def set_kill_switch(
        session: AsyncSession,
        enabled: bool,
    ) -> BotState:
        """Set kill switch status with latching.

        When enabled, sets kill_latched_at and kill_cooldown_until so that
        /unkill must wait for the cooldown period before trading resumes.
        """
        bot_state = await Repository.get_or_create_bot_state(session)
        bot_state.kill_switch = enabled
        if enabled:
            now = datetime.utcnow()
            settings = get_settings()
            bot_state.kill_latched_at = now
            bot_state.kill_cooldown_until = now + timedelta(
                seconds=settings.kill_cooldown_seconds
            )
        await session.flush()
        logger.info("Set kill switch", enabled=enabled)
        return bot_state

    @staticmethod
    async def clear_kill_switch(session: AsyncSession) -> tuple[bool, str]:
        """Clear kill switch if cooldown has expired.

        Returns:
            (success, message) — success=False if cooldown still active.
        """
        bot_state = await Repository.get_or_create_bot_state(session)
        if not bot_state.kill_switch:
            return True, "Kill switch already off"

        now = datetime.utcnow()
        if bot_state.kill_cooldown_until and now < bot_state.kill_cooldown_until:
            remaining = (bot_state.kill_cooldown_until - now).total_seconds()
            return False, f"Cooldown active: {remaining:.0f}s remaining"

        bot_state.kill_switch = False
        await session.flush()
        logger.info("Kill switch cleared after cooldown")
        return True, "Kill switch cleared"

    @staticmethod
    async def get_kill_switch(session: AsyncSession) -> bool:
        """Check if kill switch is enabled.

        Returns True if kill_switch is on OR if cooldown is still active.
        """
        bot_state = await Repository.get_or_create_bot_state(session)
        if bot_state.kill_switch:
            return True
        # Also block during cooldown even if someone manually set kill_switch=False
        if bot_state.kill_cooldown_until:
            if datetime.utcnow() < bot_state.kill_cooldown_until:
                return True
        return False

    @staticmethod
    async def is_kill_cooldown_active(session: AsyncSession) -> bool:
        """Check if kill cooldown is still running."""
        bot_state = await Repository.get_or_create_bot_state(session)
        if bot_state.kill_cooldown_until:
            return datetime.utcnow() < bot_state.kill_cooldown_until
        return False

    # ========== ShadowOrder Operations ==========

    @staticmethod
    async def create_shadow_order(
        session: AsyncSession,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        execution_mode: str,
        would_have_filled: bool = True,
        estimated_fee: float = 0.0,
        signal_edge: float = 0.0,
    ) -> ShadowOrder:
        """Record what a live order would have been (shadow-live mode)."""
        shadow = ShadowOrder(
            id=str(uuid4()),
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            execution_mode=execution_mode,
            would_have_filled=would_have_filled,
            estimated_fee=estimated_fee,
            signal_edge=signal_edge,
        )
        session.add(shadow)
        await session.flush()
        logger.info(
            "Shadow order recorded",
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            mode=execution_mode,
        )
        return shadow

    # ========== RiskEvent Operations ==========

    @staticmethod
    async def create_risk_event(
        session: AsyncSession,
        event_type: str,
        message: str,
        data: Optional[dict] = None,
    ) -> RiskEvent:
        """Create a risk event record.

        Args:
            session: Async database session
            event_type: Type of risk event
            message: Event message
            data: Optional event data as dict

        Returns:
            Created RiskEvent object
        """
        event_id = str(uuid4())
        risk_event = RiskEvent(
            id=event_id,
            event_type=event_type,
            message=message,
            data=data or {},
        )
        session.add(risk_event)
        await session.flush()
        logger.warning(
            "Created risk event",
            event_id=event_id,
            event_type=event_type,
            message=message,
        )
        return risk_event

    # ========== SizingDecision Operations ==========

    @staticmethod
    async def create_sizing_decision(
        session: AsyncSession,
        market_id: str,
        side: str,
        p_estimated: float,
        p_market: float,
        fee_rate: float,
        edge_raw: float,
        edge_after_fee: float,
        kelly_f: float,
        kelly_mult: float,
        bankroll: float,
        raw_size_usd: float,
        category_haircut: bool,
        final_size_usd: float,
        decision: str,
        skip_reason: str = "",
    ) -> SizingDecision:
        """Record a sizing decision for audit."""
        sd = SizingDecision(
            id=str(uuid4()),
            market_id=market_id,
            side=side,
            p_estimated=p_estimated,
            p_market=p_market,
            fee_rate=fee_rate,
            edge_raw=edge_raw,
            edge_after_fee=edge_after_fee,
            kelly_f=kelly_f,
            kelly_mult=kelly_mult,
            bankroll=bankroll,
            raw_size_usd=raw_size_usd,
            category_haircut=category_haircut,
            final_size_usd=final_size_usd,
            decision=decision,
            skip_reason=skip_reason,
        )
        session.add(sd)
        await session.flush()
        return sd

    @staticmethod
    async def create_sizing_decision_from_result(
        session: AsyncSession,
        result,  # SizingResult from risk.sizing
    ) -> SizingDecision:
        """Record a SizingResult object directly."""
        return await Repository.create_sizing_decision(
            session=session,
            market_id=result.market_id,
            side=result.side,
            p_estimated=result.p_estimated,
            p_market=result.p_market,
            fee_rate=result.fee_rate,
            edge_raw=result.edge_raw,
            edge_after_fee=result.edge_after_fee,
            kelly_f=result.kelly_f,
            kelly_mult=result.kelly_mult,
            bankroll=result.bankroll,
            raw_size_usd=result.raw_size_usd,
            category_haircut=result.category_haircut,
            final_size_usd=result.final_size_usd,
            decision=result.decision,
            skip_reason=result.skip_reason,
        )

    # ========== Analytics Operations ==========

    @staticmethod
    async def get_daily_pnl(
        session: AsyncSession,
        date: datetime,
    ) -> float:
        """Calculate total PnL for a given day from closed positions.

        Args:
            session: Async database session
            date: Date to calculate PnL for

        Returns:
            Total realized PnL for the day
        """
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        stmt = select(func.sum(Position.realized_pnl)).where(
            and_(
                Position.updated_at >= start_of_day,
                Position.updated_at < end_of_day,
            )
        )
        result = await session.execute(stmt)
        pnl = result.scalar()

        return float(pnl) if pnl is not None else 0.0

    @staticmethod
    async def get_orders_last_hour_count(session: AsyncSession) -> int:
        """Count orders created in the last hour.

        Args:
            session: Async database session

        Returns:
            Number of orders in the last hour
        """
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)

        stmt = select(func.count(Order.id)).where(Order.created_at >= one_hour_ago)
        result = await session.execute(stmt)
        count = result.scalar()

        return count or 0

    # ========== ExecutionStat Operations ==========

    @staticmethod
    async def create_execution_stat(
        session: AsyncSession,
        order_id: str,
        market_id: str,
        token_id: str,
        side: str,
        quoted_mid: float,
        order_price: float,
        expected_fee: float,
        expected_edge: float,
        execution_mode: str = "MAKER",
        is_maker_sandbox: bool = False,
    ) -> ExecutionStat:
        """Create an execution stat record when an order is placed."""
        stat = ExecutionStat(
            id=str(uuid4()),
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            quoted_mid=quoted_mid,
            order_price=order_price,
            expected_fee=expected_fee,
            expected_edge=expected_edge,
            execution_mode=execution_mode,
            is_maker_sandbox=is_maker_sandbox,
        )
        session.add(stat)
        await session.flush()
        return stat

    @staticmethod
    async def update_execution_stat_fill(
        session: AsyncSession,
        order_id: str,
        fill_price: float,
        actual_fee: float,
        fill_time_seconds: float,
    ) -> Optional[ExecutionStat]:
        """Update execution stat when an order fills."""
        stmt = select(ExecutionStat).where(ExecutionStat.order_id == order_id)
        result = await session.execute(stmt)
        stat = result.scalar_one_or_none()
        if stat:
            stat.fill_price = fill_price
            stat.actual_fee = actual_fee
            stat.fill_time_seconds = fill_time_seconds
            stat.slippage_vs_mid = fill_price - stat.quoted_mid
            stat.was_filled = True
            await session.flush()
        return stat

    @staticmethod
    async def update_execution_stat_cancel(
        session: AsyncSession,
        order_id: str,
        reason: str = "timeout",
    ) -> Optional[ExecutionStat]:
        """Update execution stat when an order is cancelled."""
        stmt = select(ExecutionStat).where(ExecutionStat.order_id == order_id)
        result = await session.execute(stmt)
        stat = result.scalar_one_or_none()
        if stat:
            stat.was_cancelled = True
            stat.cancel_reason = reason
            await session.flush()
        return stat

    @staticmethod
    async def get_execution_stats(
        session: AsyncSession,
        limit: int = 100,
        maker_sandbox_only: bool = False,
    ) -> Sequence[ExecutionStat]:
        """Get recent execution stats, optionally filtered to maker sandbox."""
        stmt = select(ExecutionStat).order_by(desc(ExecutionStat.created_at))
        if maker_sandbox_only:
            stmt = stmt.where(ExecutionStat.is_maker_sandbox == True)
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_execution_summary(session: AsyncSession) -> dict:
        """Aggregate execution quality metrics.

        Returns dict answering: 'Are taker fees/slippage killing us, and where?'
        """
        # Total orders tracked
        total_stmt = select(func.count(ExecutionStat.id))
        total = (await session.execute(total_stmt)).scalar() or 0

        # Fill rate
        filled_stmt = select(func.count(ExecutionStat.id)).where(
            ExecutionStat.was_filled == True
        )
        filled = (await session.execute(filled_stmt)).scalar() or 0

        # Cancel rate
        cancelled_stmt = select(func.count(ExecutionStat.id)).where(
            ExecutionStat.was_cancelled == True
        )
        cancelled = (await session.execute(cancelled_stmt)).scalar() or 0

        # Avg slippage (filled orders only)
        avg_slip_stmt = select(func.avg(ExecutionStat.slippage_vs_mid)).where(
            ExecutionStat.was_filled == True
        )
        avg_slippage = (await session.execute(avg_slip_stmt)).scalar()

        # Avg fill time
        avg_fill_time_stmt = select(func.avg(ExecutionStat.fill_time_seconds)).where(
            ExecutionStat.was_filled == True
        )
        avg_fill_time = (await session.execute(avg_fill_time_stmt)).scalar()

        # Avg expected vs actual fee
        avg_expected_fee_stmt = select(func.avg(ExecutionStat.expected_fee)).where(
            ExecutionStat.was_filled == True
        )
        avg_expected_fee = (await session.execute(avg_expected_fee_stmt)).scalar()

        avg_actual_fee_stmt = select(func.avg(ExecutionStat.actual_fee)).where(
            ExecutionStat.was_filled == True
        )
        avg_actual_fee = (await session.execute(avg_actual_fee_stmt)).scalar()

        # Avg expected edge
        avg_edge_stmt = select(func.avg(ExecutionStat.expected_edge))
        avg_expected_edge = (await session.execute(avg_edge_stmt)).scalar()

        # Maker sandbox stats
        sandbox_total_stmt = select(func.count(ExecutionStat.id)).where(
            ExecutionStat.is_maker_sandbox == True
        )
        sandbox_total = (await session.execute(sandbox_total_stmt)).scalar() or 0

        sandbox_filled_stmt = select(func.count(ExecutionStat.id)).where(
            and_(
                ExecutionStat.is_maker_sandbox == True,
                ExecutionStat.was_filled == True,
            )
        )
        sandbox_filled = (await session.execute(sandbox_filled_stmt)).scalar() or 0

        return {
            "total_orders_tracked": total,
            "filled": filled,
            "cancelled": cancelled,
            "fill_rate": round(filled / total, 4) if total > 0 else 0.0,
            "cancel_rate": round(cancelled / total, 4) if total > 0 else 0.0,
            "avg_slippage_vs_mid": round(avg_slippage, 6) if avg_slippage is not None else None,
            "avg_fill_time_seconds": round(avg_fill_time, 2) if avg_fill_time is not None else None,
            "avg_expected_fee": round(avg_expected_fee, 6) if avg_expected_fee is not None else None,
            "avg_actual_fee": round(avg_actual_fee, 6) if avg_actual_fee is not None else None,
            "fee_drag": round((avg_actual_fee or 0) - (avg_expected_fee or 0), 6),
            "avg_expected_edge": round(avg_expected_edge, 6) if avg_expected_edge is not None else None,
            "maker_sandbox": {
                "total": sandbox_total,
                "filled": sandbox_filled,
                "fill_rate": round(sandbox_filled / sandbox_total, 4) if sandbox_total > 0 else 0.0,
            },
        }

    # ========== PortfolioSnapshot Operations ==========

    @staticmethod
    async def create_portfolio_snapshot(
        session: AsyncSession,
        cash_usd: float,
        positions_value_usd: float,
        total_value_usd: float,
        realized_pnl: float,
        unrealized_pnl: float,
        open_positions: int,
        win_rate: Optional[float] = None,
    ) -> PortfolioSnapshot:
        """Create a daily portfolio snapshot (upsert by date)."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        stmt = select(PortfolioSnapshot).where(PortfolioSnapshot.date == today)
        result = await session.execute(stmt)
        snap = result.scalar_one_or_none()

        if snap:
            snap.cash_usd = cash_usd
            snap.positions_value_usd = positions_value_usd
            snap.total_value_usd = total_value_usd
            snap.realized_pnl = realized_pnl
            snap.unrealized_pnl = unrealized_pnl
            snap.open_positions = open_positions
            snap.win_rate = win_rate
        else:
            snap = PortfolioSnapshot(
                id=str(uuid4()),
                date=today,
                cash_usd=cash_usd,
                positions_value_usd=positions_value_usd,
                total_value_usd=total_value_usd,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                open_positions=open_positions,
                win_rate=win_rate,
            )
            session.add(snap)
        await session.flush()
        return snap

    @staticmethod
    async def get_equity_curve(
        session: AsyncSession, limit: int = 365
    ) -> Sequence[PortfolioSnapshot]:
        """Get portfolio snapshots for equity curve, oldest first."""
        stmt = (
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.date.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_recent_orders(
        session: AsyncSession, limit: int = 20
    ) -> Sequence[Order]:
        """Get the most recent orders."""
        stmt = (
            select(Order)
            .order_by(desc(Order.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()
