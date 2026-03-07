"""Abstract base class for order brokers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

from src.core.config import get_settings

logger = structlog.get_logger(__name__)


class NoTradeModeError(RuntimeError):
    """Raised when an order is attempted while NO_TRADE_MODE is active."""
    pass


class KillSwitchActiveError(RuntimeError):
    """Raised when an order is attempted while the kill switch is latched."""
    pass


def _assert_trading_allowed() -> None:
    """Global guardrail: fail-closed assertion that blocks ALL order placement.

    Checks the NO_TRADE_MODE env/config flag. If True (default) or if the
    setting cannot be read for any reason, raises NoTradeModeError.
    This runs at the Broker base class level — every broker subclass is gated.
    """
    try:
        settings = get_settings()
        no_trade = settings.no_trade_mode
    except Exception:
        # Fail closed: if we can't read config, assume no-trade
        no_trade = True

    if no_trade:
        raise NoTradeModeError(
            "NO_TRADE_MODE is ON (default). All order placement is blocked. "
            "Set NO_TRADE_MODE=false in .env to allow trading."
        )


async def _assert_kill_switch_clear() -> None:
    """Check DB kill-switch + cooldown. Blocks ALL order paths.

    This is the innermost safety layer after NO_TRADE_MODE. It catches
    retries, background loops, and any code path that calls place_order.
    """
    try:
        from src.store.database import DatabaseManager
        from src.store.repository import Repository

        async with DatabaseManager.get_session() as session:
            if await Repository.get_kill_switch(session):
                raise KillSwitchActiveError(
                    "Kill switch is active (latched). Trading blocked until "
                    "explicit /unkill after cooldown expires."
                )
    except KillSwitchActiveError:
        raise
    except Exception as e:
        # Fail open here — kill-switch check is best-effort at broker level.
        # The engine loop and risk manager also check independently.
        logger.warning("kill_switch_check_failed_open", error=str(e))


class OrderSide(str, Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order status enumeration."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Represents a single order."""
    id: str
    market_id: str
    token_id: str
    side: OrderSide
    price: float
    size: float
    filled_size: float
    status: OrderStatus
    timestamp: float
    metadata: Optional[dict] = None


@dataclass
class Position:
    """Represents a trading position."""
    token_id: str
    size: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_pct: float
    timestamp: float


class Broker(ABC):
    """Abstract base class for order brokers.

    All order placement goes through the NO_TRADE_MODE guardrail defined in
    _assert_trading_allowed(). Subclasses implement _do_place_order and
    _do_place_market_order; the public methods enforce the gate.
    """

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
    ) -> Order:
        """Place a limit order (guarded by NO_TRADE_MODE + kill switch).

        Raises NoTradeModeError if NO_TRADE_MODE is active.
        Raises KillSwitchActiveError if kill switch is latched.
        """
        _assert_trading_allowed()
        await _assert_kill_switch_clear()
        return await self._do_place_order(market_id, token_id, side, price, size)

    async def place_market_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        amount: float,
    ) -> Order:
        """Place a market order (guarded by NO_TRADE_MODE + kill switch).

        Raises NoTradeModeError if NO_TRADE_MODE is active.
        Raises KillSwitchActiveError if kill switch is latched.
        """
        _assert_trading_allowed()
        await _assert_kill_switch_clear()
        return await self._do_place_market_order(market_id, token_id, side, amount)

    @abstractmethod
    async def _do_place_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
    ) -> Order:
        """Subclass implementation of limit order placement."""
        pass

    @abstractmethod
    async def _do_place_market_order(
        self,
        market_id: str,
        token_id: str,
        side: OrderSide,
        amount: float,
    ) -> Order:
        """Subclass implementation of market order placement."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order identifier
            
        Returns:
            True if cancelled successfully, False otherwise
        """
        pass

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """
        Get current positions.
        
        Returns:
            List of Position objects
        """
        pass

    @abstractmethod
    async def sync_positions(self) -> None:
        """
        Sync positions with broker (fetch from API/DB).
        
        Returns:
            None
        """
        pass
