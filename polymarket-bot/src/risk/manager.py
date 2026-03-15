"""Risk management for trading bot."""
import statistics
from datetime import datetime
from src.core.time_utils import utc_now_naive

import structlog

from src.core.config import get_settings
from src.store.repository import Repository

logger = structlog.get_logger(__name__)


class RiskManager:
    """Manages risk checks and position limits."""

    def __init__(self, settings=None):
        self._settings = settings
        self.last_price_times: dict[str, datetime] = {}

    def record_price_time(self, token_id: str) -> None:
        """Record when we last got a valid price for a token."""
        self.last_price_times[token_id] = utc_now_naive()

    async def check_pre_trade(
        self,
        session,
        market_id: str,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> tuple[bool, str]:
        """Check if a trade is allowed before placing order.
        
        Args:
            session: AsyncSession database connection
            market_id: Market identifier
            token_id: Token identifier
            side: Order side (BUY/SELL)
            size: Order size
            price: Order price
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        settings = self._settings or get_settings()
        
        # 1. Kill switch
        if await Repository.get_kill_switch(session):
            return False, "Kill switch is enabled"

        # 2. Max position USD
        position = await Repository.get_position(session, market_id, token_id)
        current_notional = (position.size * position.avg_entry_price) if position else 0.0
        proposed_notional = size * price
        if current_notional + proposed_notional > settings.max_position_usd:
            return False, f"Position limit: {current_notional + proposed_notional:.2f} > {settings.max_position_usd:.2f}"

        # 3. Max orders per hour
        orders_count = await Repository.get_orders_last_hour_count(session)
        if orders_count >= settings.max_orders_per_hour:
            return False, f"Rate limit: {orders_count} >= {settings.max_orders_per_hour}/hr"

        # 4. Stale price guard
        last_price_time = self.last_price_times.get(token_id)
        if last_price_time:
            staleness = (utc_now_naive() - last_price_time).total_seconds()
            threshold = 5 * settings.engine_loop_seconds
            if staleness > threshold:
                return False, f"Stale price: {staleness:.0f}s > {threshold}s"

        # 5. Max daily drawdown
        daily_pnl = await Repository.get_daily_pnl(session, utc_now_naive())
        if daily_pnl < -settings.max_daily_drawdown_usd:
            await self.trigger_kill_switch(session, f"Daily drawdown exceeded: {daily_pnl:.2f}")
            return False, f"Drawdown limit: {daily_pnl:.2f} < {-settings.max_daily_drawdown_usd:.2f}"

        logger.info("pre_trade_check_passed", market_id=market_id, side=side, size=size, price=price)
        return True, "OK"

    @staticmethod
    def check_volatility_pause(recent_prices: list[float], threshold: float = 3.0) -> bool:
        """Check if volatility is too high and trading should pause.
        
        Args:
            recent_prices: List of recent prices
            threshold: Volatility threshold multiplier
            
        Returns:
            True if volatility is high and trading should pause
        """
        if len(recent_prices) < 3:
            return False
        returns = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                    for i in range(1, len(recent_prices)) if recent_prices[i-1] != 0]
        if len(returns) < 2:
            return False
        mean_abs = statistics.mean([abs(r) for r in returns])
        if mean_abs == 0:
            return False
        std_dev = statistics.stdev(returns)
        return (std_dev / mean_abs) > threshold

    async def trigger_kill_switch(self, session, reason: str) -> None:
        """Trigger the kill switch due to risk event.
        
        Args:
            session: AsyncSession database connection
            reason: Reason for triggering kill switch
        """
        await Repository.set_kill_switch(session, enabled=True)
        await Repository.create_risk_event(session, "kill_switch", reason, {"reason": reason})
        logger.critical("kill_switch_triggered", reason=reason)
