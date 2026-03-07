"""Repository pattern implementation for database operations."""
from datetime import datetime, timedelta
from typing import Optional, Sequence
from uuid import uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.store.models import BotState, Fill, Order, Position, RiskEvent

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
        """Set kill switch status.

        Args:
            session: Async database session
            enabled: Kill switch state

        Returns:
            Updated BotState object
        """
        bot_state = await Repository.get_or_create_bot_state(session)
        bot_state.kill_switch = enabled
        await session.flush()
        logger.info("Set kill switch", enabled=enabled)
        return bot_state

    @staticmethod
    async def get_kill_switch(session: AsyncSession) -> bool:
        """Check if kill switch is enabled.

        Args:
            session: Async database session

        Returns:
            Kill switch status
        """
        bot_state = await Repository.get_or_create_bot_state(session)
        return bot_state.kill_switch

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
