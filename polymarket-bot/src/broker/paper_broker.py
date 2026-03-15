"""Paper trading broker for simulation."""
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import structlog

from .base import Broker, Order, OrderSide, OrderStatus, Position

logger = structlog.get_logger(__name__)


@dataclass
class Fill:
    """Represents a trade execution."""
    order_id: str
    timestamp: float
    price: float
    size: float
    fee: float


@dataclass
class TradePosition:
    """Internal position tracking."""
    token_id: str
    total_size: float
    total_cost: float  # sum of (size * price) for buys, used for avg entry


class PaperBroker(Broker):
    """Paper trading broker that simulates order fills."""

    def __init__(self, initial_cash: float = 100_000, slippage_bps: int = 5, fee_bps: int = 2):
        """
        Initialize the paper broker.
        
        Args:
            initial_cash: Starting cash balance
            slippage_bps: Slippage in basis points (1 bp = 0.01%)
            fee_bps: Trading fee in basis points
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.slippage_bps = slippage_bps
        self.fee_bps = fee_bps
        
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._positions: dict[str, TradePosition] = {}
        self._last_prices: dict[str, float] = {}
        
        logger.info(
            "paper_broker_initialized",
            initial_cash=initial_cash,
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
        )

    async def _do_place_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
    ) -> Order:
        """
        Place a limit order and simulate immediate fill.

        Args:
            market_id: Market identifier
            token_id: Token identifier
            side: Buy or sell
            price: Limit price
            size: Order size

        Returns:
            Order object (immediately filled)
        """
        order_id = str(uuid.uuid4())
        timestamp = time.time()
        
        # Simulate fill at market price with slippage
        slippage_multiplier = 1 + (self.slippage_bps / 10_000)
        if side == OrderSide.BUY:
            fill_price = price * slippage_multiplier
        else:  # SELL
            fill_price = price / slippage_multiplier
        
        # Calculate fee
        fill_cost = fill_price * size
        fee = fill_cost * (self.fee_bps / 10_000)
        
        # Update cash and positions
        if side == OrderSide.BUY:
            total_cost = fill_cost + fee
            if self.cash < total_cost:
                logger.error(
                    "insufficient_cash",
                    order_id=order_id,
                    required=total_cost,
                    available=self.cash,
                )
                status = OrderStatus.REJECTED
                filled_size = 0.0
            else:
                self.cash -= total_cost
                self._update_position(token_id, size, fill_price, is_buy=True)
                status = OrderStatus.FILLED
                filled_size = size
        else:  # SELL
            self.cash += fill_cost - fee
            self._update_position(token_id, size, fill_price, is_buy=False)
            status = OrderStatus.FILLED
            filled_size = size
        
        # Record order and fill
        order = Order(
            id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            filled_size=filled_size,
            status=status,
            timestamp=timestamp,
        )
        self._orders[order_id] = order
        
        if status == OrderStatus.FILLED:
            fill = Fill(
                order_id=order_id,
                timestamp=timestamp,
                price=fill_price,
                size=filled_size,
                fee=fee,
            )
            self._fills.append(fill)
            self._last_prices[token_id] = fill_price
        
        logger.info(
            "paper_order_placed",
            order_id=order_id,
            side=side,
            price=price,
            size=size,
            filled_size=filled_size,
            status=status,
            fill_price=fill_price if status == OrderStatus.FILLED else None,
            cash_remaining=self.cash,
        )

        # Shadow-live: record what a live order would have been
        if status == OrderStatus.FILLED:
            try:
                from src.core.config import get_settings
                from src.store.database import DatabaseManager
                from src.store.repository import Repository

                settings = get_settings()
                exec_mode = settings.execution_mode.upper()
                est_fee = 0.0
                if exec_mode == "TAKER":
                    est_fee = price * (1 - price) * settings.taker_fee_rate

                async with DatabaseManager.get_session() as session:
                    await Repository.create_shadow_order(
                        session,
                        market_id=market_id,
                        token_id=token_id,
                        side=side.value.upper(),
                        price=price,
                        size=size,
                        execution_mode=exec_mode,
                        would_have_filled=True,
                        estimated_fee=est_fee,
                    )
                    await session.commit()
            except Exception as e:
                logger.warning("shadow_order_write_failed", error=str(e))

        return order

    async def _do_place_market_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        amount: float,
    ) -> Order:
        """
        Place a market order.

        Args:
            market_id: Market identifier
            token_id: Token identifier
            side: Buy or sell
            amount: Amount to trade

        Returns:
            Order object
        """
        # Use last known price, or estimate at 0.5
        price = self._last_prices.get(token_id, 0.5)
        size = amount / price if price > 0 else 0.0

        logger.debug(
            "market_order_converted_to_limit",
            amount=amount,
            estimated_price=price,
            estimated_size=size,
        )

        return await self._do_place_order(market_id, token_id, side, price, size)

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order (if not already filled).
        
        Args:
            order_id: Order identifier
            
        Returns:
            True if cancelled, False if already filled or not found
        """
        order = self._orders.get(order_id)
        if not order:
            logger.warning("cancel_order_not_found", order_id=order_id)
            return False
        
        if order.status == OrderStatus.FILLED:
            logger.warning("cancel_order_already_filled", order_id=order_id)
            return False
        
        order.status = OrderStatus.CANCELLED
        logger.info("cancel_order_success", order_id=order_id)
        return True

    async def get_positions(self) -> list[Position]:
        """
        Get current positions.
        
        Returns:
            List of Position objects
        """
        positions = []
        for token_id, pos in self._positions.items():
            price = self._last_prices.get(token_id, 0.0)
            entry_price = (pos.total_cost / pos.total_size) if pos.total_size > 0 else 0.0
            pnl = pos.total_size * (price - entry_price)
            pnl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
            
            position = Position(
                token_id=token_id,
                size=pos.total_size,
                entry_price=entry_price,
                current_price=price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                timestamp=time.time(),
            )
            positions.append(position)
        
        logger.debug("get_positions", count=len(positions))
        return positions

    async def sync_positions(self) -> None:
        """
        Sync positions (no-op for paper broker).
        
        Returns:
            None
        """
        logger.debug("sync_positions_paper_broker")
        pass

    def _update_position(self, token_id: str, size: float, price: float, is_buy: bool) -> None:
        """
        Update position for a trade.
        
        Args:
            token_id: Token identifier
            size: Trade size
            price: Trade price
            is_buy: True for buy, False for sell
        """
        if token_id not in self._positions:
            self._positions[token_id] = TradePosition(
                token_id=token_id,
                total_size=0.0,
                total_cost=0.0,
            )
        
        pos = self._positions[token_id]
        
        if is_buy:
            pos.total_cost += size * price
            pos.total_size += size
        else:
            # For sells, reduce position
            # Simplified: assume FIFO exit
            if pos.total_size >= size:
                cost_reduction = (pos.total_cost / pos.total_size * size) if pos.total_size > 0 else 0
                pos.total_cost -= cost_reduction
                pos.total_size -= size
            else:
                # Selling more than held (short position)
                pos.total_cost = -(size - pos.total_size) * price
                pos.total_size = -(size - pos.total_size)
        
        logger.debug(
            "position_updated",
            token_id=token_id,
            size=pos.total_size,
            avg_price=(pos.total_cost / pos.total_size) if pos.total_size != 0 else 0,
        )

    def get_cash(self) -> float:
        """Get current cash balance."""
        return self.cash

    def get_all_orders(self) -> list[Order]:
        """Get all orders."""
        return list(self._orders.values())

    def get_all_fills(self) -> list[Fill]:
        """Get all fills."""
        return self._fills
