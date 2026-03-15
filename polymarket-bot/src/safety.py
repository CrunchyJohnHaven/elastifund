"""Safety rails for live trading — NON-NEGOTIABLE guardrails.

All checks here are additional to the existing risk manager. They enforce:
  1. Daily loss limit (MAX_DAILY_DRAWDOWN_USD, default $10)
  2. Per-trade hard cap (MAX_PER_TRADE_USD, default $5 — overrides Kelly)
  3. Total exposure cap (80% of bankroll — keep 20% cash reserve)
  4. Cooldown after N consecutive losses (default 3 → pause 1 hour)
  5. Gradual rollout limits (trades/day, $/trade — manual escalation only)
"""
import time
from datetime import datetime, timedelta
from src.core.time_utils import utc_now_naive

import structlog

from src.core.config import get_settings

logger = structlog.get_logger(__name__)


class SafetyRails:
    """Stateful safety rail checker for live trading.

    Instantiate once at startup. Tracks consecutive losses and cooldown state
    in memory. Daily trade count resets at midnight UTC.
    """

    def __init__(self):
        self._consecutive_losses: int = 0
        self._cooldown_until: float = 0.0  # unix timestamp
        self._daily_trade_count: int = 0
        self._daily_trade_date: str = ""  # "YYYY-MM-DD"
        self._daily_loss_total: float = 0.0
        self._daily_loss_date: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_pre_trade(
        self,
        trade_size_usd: float,
        bankroll: float,
        total_exposure_usd: float,
        daily_pnl: float,
        open_positions_count: int = 0,
    ) -> tuple[bool, str]:
        """Run all safety checks before placing a trade.

        Args:
            trade_size_usd: Proposed trade size in USD.
            bankroll: Current total bankroll (cash + positions).
            total_exposure_usd: Sum of all open position notional values.
            daily_pnl: Realized P&L for today (negative = losses).
            open_positions_count: Current number of open positions.

        Returns:
            (allowed, reason) — if not allowed, reason explains why.
        """
        settings = get_settings()

        # 0. Cooldown check (consecutive losses)
        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            return False, f"Cooldown active: {remaining}s remaining after {settings.cooldown_consecutive_losses} consecutive losses"

        # 1. Daily loss limit
        if daily_pnl <= -settings.max_daily_drawdown_usd:
            return False, f"Daily loss limit hit: ${daily_pnl:.2f} <= -${settings.max_daily_drawdown_usd:.2f}"

        # 2. Per-trade hard cap (min of global cap and rollout cap)
        effective_max = min(settings.max_per_trade_usd, settings.rollout_max_per_trade_usd)
        if trade_size_usd > effective_max:
            return False, f"Per-trade cap exceeded: ${trade_size_usd:.2f} > ${effective_max:.2f}"

        # 3. Total exposure cap (keep cash reserve)
        max_exposure = bankroll * settings.max_exposure_pct
        if total_exposure_usd + trade_size_usd > max_exposure:
            return False, (
                f"Exposure cap: ${total_exposure_usd + trade_size_usd:.2f} "
                f"> ${max_exposure:.2f} ({settings.max_exposure_pct:.0%} of ${bankroll:.2f})"
            )

        # 4. Rollout: daily trade count
        today = utc_now_naive().strftime("%Y-%m-%d")
        if today != self._daily_trade_date:
            self._daily_trade_count = 0
            self._daily_trade_date = today

        max_daily = settings.rollout_max_trades_per_day
        if max_daily >= 0 and self._daily_trade_count >= max_daily:
            return False, f"Rollout daily limit: {self._daily_trade_count} >= {max_daily} trades/day"

        # 5. Max concurrent open positions
        if open_positions_count >= settings.max_open_positions:
            return False, (
                f"Max open positions reached: {open_positions_count} "
                f">= {settings.max_open_positions}"
            )

        return True, "OK"

    def clamp_size(self, proposed_size: float) -> float:
        """Clamp a proposed trade size to the effective per-trade cap.

        Args:
            proposed_size: Proposed size from Kelly/sizing logic.

        Returns:
            Size clamped to min(MAX_PER_TRADE_USD, ROLLOUT_MAX_PER_TRADE_USD).
        """
        settings = get_settings()
        effective_max = min(settings.max_per_trade_usd, settings.rollout_max_per_trade_usd)
        return min(proposed_size, effective_max)

    def record_trade(self) -> None:
        """Call after a trade is successfully placed."""
        today = utc_now_naive().strftime("%Y-%m-%d")
        if today != self._daily_trade_date:
            self._daily_trade_count = 0
            self._daily_trade_date = today
        self._daily_trade_count += 1
        logger.info("safety_trade_recorded", daily_count=self._daily_trade_count)

    def record_loss(self) -> None:
        """Call when a trade resolves as a loss. Tracks consecutive losses."""
        settings = get_settings()
        self._consecutive_losses += 1
        logger.warning(
            "safety_loss_recorded",
            consecutive=self._consecutive_losses,
            threshold=settings.cooldown_consecutive_losses,
        )

        if self._consecutive_losses >= settings.cooldown_consecutive_losses:
            self._cooldown_until = time.time() + settings.cooldown_seconds
            logger.critical(
                "safety_cooldown_triggered",
                consecutive_losses=self._consecutive_losses,
                cooldown_seconds=settings.cooldown_seconds,
                cooldown_until=datetime.utcfromtimestamp(self._cooldown_until).isoformat(),
            )

    def record_win(self) -> None:
        """Call when a trade resolves as a win. Resets consecutive loss counter."""
        self._consecutive_losses = 0

    def reset_cooldown(self) -> None:
        """Manually reset cooldown (e.g., via /unkill endpoint)."""
        self._cooldown_until = 0.0
        self._consecutive_losses = 0
        logger.info("safety_cooldown_reset")

    def get_status(self) -> dict:
        """Return current safety rail state for monitoring."""
        settings = get_settings()
        now = time.time()
        return {
            "consecutive_losses": self._consecutive_losses,
            "cooldown_active": now < self._cooldown_until,
            "cooldown_remaining_s": max(0, int(self._cooldown_until - now)),
            "daily_trade_count": self._daily_trade_count,
            "daily_trade_date": self._daily_trade_date,
            "config": {
                "max_daily_drawdown_usd": settings.max_daily_drawdown_usd,
                "max_per_trade_usd": settings.max_per_trade_usd,
                "max_exposure_pct": settings.max_exposure_pct,
                "max_open_positions": settings.max_open_positions,
                "cooldown_consecutive_losses": settings.cooldown_consecutive_losses,
                "cooldown_seconds": settings.cooldown_seconds,
                "rollout_max_per_trade_usd": settings.rollout_max_per_trade_usd,
                "rollout_max_trades_per_day": settings.rollout_max_trades_per_day,
                "rollout_kelly_active": settings.rollout_kelly_active,
            },
        }
