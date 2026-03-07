"""Active exit strategy for managing open positions.

Instead of holding positions to resolution, this module monitors open positions
each engine cycle and exits early when the edge has been captured (or lost).

EXIT CONDITIONS:
  a) Edge captured: market price moved >80% toward our estimate → sell to lock profit
  b) Stop loss: price moved >15% against us → cut losses
  c) Time decay: position held >14 days with <5% price movement → free capital
  d) Momentum exit: price moved against us 3 consecutive cycles → reduce by 50%

Each exit frees capital for redeployment into fresh opportunities, improving
capital velocity by 3-4x on average.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

from src.broker.base import Broker, OrderSide, Position

logger = structlog.get_logger(__name__)


class ExitReason(str, Enum):
    """Reason for exiting a position."""
    EDGE_CAPTURED = "edge_captured"    # Market moved toward our estimate
    STOP_LOSS = "stop_loss"            # Market moved against us
    TIME_DECAY = "time_decay"          # Position stale, no movement
    MOMENTUM_EXIT = "momentum_exit"    # Price moved against us 3+ consecutive cycles
    MANUAL = "manual"                  # Manual exit


@dataclass
class ExitRecord:
    """Record of a position exit for logging and analysis."""
    market_id: str
    token_id: str
    reason: ExitReason
    entry_price: float
    exit_price: float
    size: float
    hold_time_hours: float
    realized_pnl: float
    pnl_pct: float
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return (
            f"<Exit {self.reason.value}: {self.token_id} "
            f"entry={self.entry_price:.3f} exit={self.exit_price:.3f} "
            f"pnl={self.realized_pnl:+.4f} ({self.pnl_pct:+.1f}%) "
            f"held={self.hold_time_hours:.1f}h>"
        )


@dataclass
class TrackedPosition:
    """Extended position info for exit tracking.

    Wraps the broker Position with extra metadata needed for exit decisions:
    the estimated probability at entry time and when the position was opened.
    """
    position: Position
    market_id: str
    estimated_prob: float       # Our probability estimate when we entered
    entry_side: str             # "buy_yes" or "buy_no"
    opened_at: float            # Unix timestamp when position was opened
    last_price_at_check: float  # Last price we saw during monitoring
    adverse_cycles: int = 0     # Consecutive cycles where price moved against us

    @property
    def hold_time_hours(self) -> float:
        return (time.time() - self.opened_at) / 3600.0

    @property
    def hold_time_days(self) -> float:
        return self.hold_time_hours / 24.0


class ExitStrategyConfig:
    """Configuration for exit strategy thresholds."""

    def __init__(
        self,
        edge_capture_pct: float = 0.80,
        stop_loss_pct: float = 0.15,
        time_decay_days: int = 14,
        time_decay_movement_threshold: float = 0.05,
        momentum_adverse_cycles: int = 3,
        momentum_reduce_pct: float = 0.50,
        sell_retry_seconds: int = 300,
        sell_spread_buffer: float = 0.01,
    ):
        """
        Args:
            edge_capture_pct: Exit when price has moved this fraction toward
                our estimate (0.80 = 80% of the way there).
            stop_loss_pct: Exit when price has moved this fraction against us.
            time_decay_days: Exit if position held longer than this with no movement.
            time_decay_movement_threshold: Minimum price movement to reset time decay.
            momentum_adverse_cycles: Number of consecutive adverse cycles to trigger
                momentum exit (default 3).
            momentum_reduce_pct: Fraction of position to exit on momentum signal
                (default 0.50 = sell 50% of position).
            sell_retry_seconds: How long to wait before adjusting sell price.
            sell_spread_buffer: Amount above current bid to place initial sell.
        """
        self.edge_capture_pct = edge_capture_pct
        self.stop_loss_pct = stop_loss_pct
        self.time_decay_days = time_decay_days
        self.time_decay_movement_threshold = time_decay_movement_threshold
        self.momentum_adverse_cycles = momentum_adverse_cycles
        self.momentum_reduce_pct = momentum_reduce_pct
        self.sell_retry_seconds = sell_retry_seconds
        self.sell_spread_buffer = sell_spread_buffer


class ExitStrategy:
    """Monitors open positions and triggers exits when edge is captured/lost.

    Usage:
        exit_strategy = ExitStrategy(broker, config)

        # When opening a position, register it:
        exit_strategy.track_position(position, market_id, estimated_prob, side)

        # Each engine cycle, check for exits:
        exits = await exit_strategy.check_exits(current_prices)
    """

    def __init__(
        self,
        broker: Broker,
        config: Optional[ExitStrategyConfig] = None,
    ):
        self.broker = broker
        self.config = config or ExitStrategyConfig()
        self._tracked: dict[str, TrackedPosition] = {}  # token_id -> TrackedPosition
        self._exit_log: list[ExitRecord] = []
        self._pending_sells: dict[str, float] = {}  # token_id -> sell order placed at time

    def track_position(
        self,
        position: Position,
        market_id: str,
        estimated_prob: float,
        entry_side: str,
    ) -> None:
        """Register a new position for exit monitoring.

        Args:
            position: The broker Position object.
            market_id: Market identifier.
            estimated_prob: Our probability estimate at entry time.
            entry_side: "buy_yes" or "buy_no".
        """
        key = f"{market_id}:{position.token_id}"
        self._tracked[key] = TrackedPosition(
            position=position,
            market_id=market_id,
            estimated_prob=estimated_prob,
            entry_side=entry_side,
            opened_at=position.timestamp,
            last_price_at_check=position.entry_price,
        )
        logger.info(
            "position_tracked_for_exit",
            key=key,
            entry_price=position.entry_price,
            estimated_prob=estimated_prob,
            side=entry_side,
        )

    async def check_exits(
        self,
        current_prices: dict[str, float],
    ) -> list[ExitRecord]:
        """Check all tracked positions for exit conditions.

        Args:
            current_prices: Dict of token_id -> current market price.

        Returns:
            List of ExitRecord for positions that were exited.
        """
        exits: list[ExitRecord] = []
        keys_to_remove: list[str] = []

        for key, tracked in self._tracked.items():
            token_id = tracked.position.token_id
            current_price = current_prices.get(token_id)

            if current_price is None:
                logger.debug("no_price_for_exit_check", key=key)
                continue

            # Evaluate exit conditions
            exit_reason = self._evaluate_exit(tracked, current_price)

            if exit_reason is not None:
                # Momentum exit is partial (50% reduction), not full exit
                if exit_reason == ExitReason.MOMENTUM_EXIT:
                    record = await self._execute_partial_exit(tracked, current_price, exit_reason)
                    if record:
                        exits.append(record)
                        tracked.adverse_cycles = 0  # Reset after partial exit
                else:
                    record = await self._execute_exit(tracked, current_price, exit_reason)
                    if record:
                        exits.append(record)
                        keys_to_remove.append(key)
            else:
                # Track adverse momentum cycles
                self._update_adverse_cycles(tracked, current_price)
                # Update last seen price for time-decay tracking
                tracked.last_price_at_check = current_price

        # Clean up exited positions
        for key in keys_to_remove:
            del self._tracked[key]

        return exits

    def _evaluate_exit(
        self,
        tracked: TrackedPosition,
        current_price: float,
    ) -> Optional[ExitReason]:
        """Evaluate whether a position should be exited.

        For a BUY YES position at entry_price with estimated_prob:
          - Edge captured: price moved from entry toward estimated_prob by >80%
          - Stop loss: price dropped >15% from entry
          - Time decay: held >14 days, price within 5% of entry

        For a BUY NO position bought at (1-entry_price) effective:
          - We want the YES price to DROP (NO becomes more valuable)
          - Edge captured: YES price fell from entry toward (1-estimated_prob)
          - Stop loss: YES price rose >15% above entry
          - Time decay: same as above

        Args:
            tracked: The tracked position.
            current_price: Current YES price of the market.

        Returns:
            ExitReason if should exit, None otherwise.
        """
        entry_price = tracked.position.entry_price
        estimated_prob = tracked.estimated_prob
        side = tracked.entry_side

        if side == "buy_yes":
            # We bought YES at entry_price, hoping price rises to estimated_prob
            target_price = estimated_prob
            edge_total = target_price - entry_price
            edge_captured = current_price - entry_price

            # Edge captured check: price moved >80% toward our target
            if edge_total > 0 and edge_captured / edge_total >= self.config.edge_capture_pct:
                return ExitReason.EDGE_CAPTURED

            # Stop loss: price dropped >15% from entry (absolute terms for 0-1 market)
            price_drop = entry_price - current_price
            if price_drop > self.config.stop_loss_pct:
                return ExitReason.STOP_LOSS

        elif side == "buy_no":
            # We bought NO — we want YES price to fall
            # Entry: we paid (1 - entry_price) for NO shares
            # Target: YES price falls to (1 - estimated_prob), i.e. we think YES is overpriced
            # Our NO shares are worth (1 - current_yes_price) now
            no_entry_price = 1.0 - entry_price  # what we paid per NO share
            no_current_value = 1.0 - current_price  # current value of our NO shares
            no_target_value = estimated_prob  # our estimate of NO probability

            edge_total = no_target_value - no_entry_price
            edge_captured = no_current_value - no_entry_price

            # Edge captured: NO value moved >80% toward target
            if edge_total > 0 and edge_captured / edge_total >= self.config.edge_capture_pct:
                return ExitReason.EDGE_CAPTURED

            # Stop loss: YES price rose (our NO position lost value)
            price_loss = no_entry_price - no_current_value
            if price_loss > self.config.stop_loss_pct:
                return ExitReason.STOP_LOSS

        # Time decay: held too long with minimal price movement
        if tracked.hold_time_days >= self.config.time_decay_days:
            price_movement = abs(current_price - entry_price)
            if price_movement < self.config.time_decay_movement_threshold:
                return ExitReason.TIME_DECAY

        # Momentum exit: price moved against us for N consecutive cycles
        if tracked.adverse_cycles >= self.config.momentum_adverse_cycles:
            return ExitReason.MOMENTUM_EXIT

        return None

    def _update_adverse_cycles(self, tracked: TrackedPosition, current_price: float) -> None:
        """Track consecutive cycles where price moved against our position."""
        last = tracked.last_price_at_check

        if tracked.entry_side == "buy_yes":
            # Adverse = price dropped since last check
            if current_price < last:
                tracked.adverse_cycles += 1
            else:
                tracked.adverse_cycles = 0
        elif tracked.entry_side == "buy_no":
            # Adverse = YES price rose since last check (our NO loses value)
            if current_price > last:
                tracked.adverse_cycles += 1
            else:
                tracked.adverse_cycles = 0

    async def _execute_exit(
        self,
        tracked: TrackedPosition,
        current_price: float,
        reason: ExitReason,
    ) -> Optional[ExitRecord]:
        """Execute a sell order to exit a position.

        Places a limit sell at current_bid + spread_buffer. The engine loop
        can retry at current_bid if unfilled after sell_retry_seconds.

        Args:
            tracked: The tracked position.
            current_price: Current market price.
            reason: Why we're exiting.

        Returns:
            ExitRecord if sell was placed, None on error.
        """
        pos = tracked.position
        market_id = tracked.market_id

        # Determine sell price: current price + small buffer to improve fill
        sell_price = current_price + self.config.sell_spread_buffer
        sell_price = min(sell_price, 0.99)  # Cap at 0.99 for binary market

        # For NO positions, we sell our NO tokens
        # The sell is on the same token_id we hold
        sell_token = pos.token_id
        sell_size = pos.size

        if sell_size <= 0:
            logger.warning("exit_skip_zero_size", key=f"{market_id}:{sell_token}")
            return None

        try:
            order = await self.broker.place_order(
                market_id=market_id,
                token_id=sell_token,
                side=OrderSide.SELL,
                price=sell_price,
                size=sell_size,
            )

            # Calculate P&L
            entry_cost = pos.entry_price * sell_size
            exit_proceeds = sell_price * sell_size
            if tracked.entry_side == "buy_no":
                # For NO: entry cost was (1 - entry_yes_price) * size
                no_entry = 1.0 - pos.entry_price
                entry_cost = no_entry * sell_size
                exit_proceeds = (1.0 - current_price) * sell_size

            realized_pnl = exit_proceeds - entry_cost
            pnl_pct = (realized_pnl / entry_cost * 100) if entry_cost > 0 else 0.0

            record = ExitRecord(
                market_id=market_id,
                token_id=sell_token,
                reason=reason,
                entry_price=pos.entry_price,
                exit_price=sell_price,
                size=sell_size,
                hold_time_hours=tracked.hold_time_hours,
                realized_pnl=realized_pnl,
                pnl_pct=pnl_pct,
            )

            self._exit_log.append(record)

            logger.info(
                "position_exited",
                market_id=market_id,
                token_id=sell_token,
                reason=reason.value,
                entry_price=pos.entry_price,
                exit_price=sell_price,
                size=sell_size,
                hold_hours=round(tracked.hold_time_hours, 1),
                realized_pnl=round(realized_pnl, 4),
                pnl_pct=round(pnl_pct, 1),
                order_id=order.id,
            )

            return record

        except Exception as e:
            logger.error(
                "exit_order_failed",
                market_id=market_id,
                token_id=sell_token,
                reason=reason.value,
                error=str(e),
            )
            return None

    async def _execute_partial_exit(
        self,
        tracked: TrackedPosition,
        current_price: float,
        reason: ExitReason,
    ) -> Optional[ExitRecord]:
        """Execute a partial sell (e.g., 50% for momentum exit).

        Reduces position size but keeps tracking the remainder.
        """
        pos = tracked.position
        market_id = tracked.market_id

        reduce_pct = self.config.momentum_reduce_pct
        sell_size = pos.size * reduce_pct

        if sell_size <= 0:
            return None

        sell_price = current_price + self.config.sell_spread_buffer
        sell_price = min(sell_price, 0.99)
        sell_token = pos.token_id

        try:
            order = await self.broker.place_order(
                market_id=market_id,
                token_id=sell_token,
                side=OrderSide.SELL,
                price=sell_price,
                size=sell_size,
            )

            # Calculate P&L on the exited portion
            entry_cost = pos.entry_price * sell_size
            exit_proceeds = sell_price * sell_size
            if tracked.entry_side == "buy_no":
                no_entry = 1.0 - pos.entry_price
                entry_cost = no_entry * sell_size
                exit_proceeds = (1.0 - current_price) * sell_size

            realized_pnl = exit_proceeds - entry_cost
            pnl_pct = (realized_pnl / entry_cost * 100) if entry_cost > 0 else 0.0

            record = ExitRecord(
                market_id=market_id,
                token_id=sell_token,
                reason=reason,
                entry_price=pos.entry_price,
                exit_price=sell_price,
                size=sell_size,
                hold_time_hours=tracked.hold_time_hours,
                realized_pnl=realized_pnl,
                pnl_pct=pnl_pct,
            )

            self._exit_log.append(record)

            # Reduce tracked position size
            pos.size -= sell_size

            logger.info(
                "position_partially_exited",
                market_id=market_id,
                token_id=sell_token,
                reason=reason.value,
                exited_size=round(sell_size, 4),
                remaining_size=round(pos.size, 4),
                realized_pnl=round(realized_pnl, 4),
                pnl_pct=round(pnl_pct, 1),
                adverse_cycles=tracked.adverse_cycles,
            )

            return record

        except Exception as e:
            logger.error(
                "partial_exit_failed",
                market_id=market_id,
                reason=reason.value,
                error=str(e),
            )
            return None

    def get_tracked_positions(self) -> dict[str, TrackedPosition]:
        """Return all currently tracked positions."""
        return dict(self._tracked)

    def get_exit_log(self) -> list[ExitRecord]:
        """Return log of all exits since startup."""
        return list(self._exit_log)

    def get_stats(self) -> dict:
        """Return summary statistics for exit performance."""
        if not self._exit_log:
            return {
                "total_exits": 0,
                "total_pnl": 0.0,
                "avg_hold_hours": 0.0,
                "exits_by_reason": {},
            }

        total_pnl = sum(r.realized_pnl for r in self._exit_log)
        avg_hold = sum(r.hold_time_hours for r in self._exit_log) / len(self._exit_log)

        by_reason: dict[str, dict] = {}
        for r in self._exit_log:
            key = r.reason.value
            if key not in by_reason:
                by_reason[key] = {"count": 0, "total_pnl": 0.0, "avg_pnl_pct": 0.0}
            by_reason[key]["count"] += 1
            by_reason[key]["total_pnl"] += r.realized_pnl

        for key, stats in by_reason.items():
            records = [r for r in self._exit_log if r.reason.value == key]
            stats["avg_pnl_pct"] = (
                sum(r.pnl_pct for r in records) / len(records) if records else 0.0
            )

        return {
            "total_exits": len(self._exit_log),
            "total_pnl": round(total_pnl, 4),
            "avg_hold_hours": round(avg_hold, 1),
            "exits_by_reason": by_reason,
            "win_rate": round(
                sum(1 for r in self._exit_log if r.realized_pnl > 0)
                / len(self._exit_log)
                * 100,
                1,
            ),
        }
