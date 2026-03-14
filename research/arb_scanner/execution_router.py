"""
Order routing and position management.

Handles execution strategies across different arb types, position state tracking,
risk management, and emergency unwind logic.

Position lifecycle:
DISCOVERED -> ENTERING -> PARTIALLY_FILLED -> LOCKED -> UNWINDING -> HELD_TO_RESOLUTION -> REDEEMED -> CLOSED
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import List, Dict, Optional
import uuid


class PositionState(Enum):
    """Position state machine."""
    DISCOVERED = "discovered"  # Found but not yet sent
    ENTERING = "entering"  # Orders sent, awaiting fills
    PARTIALLY_FILLED = "partially_filled"  # Some legs filled
    LOCKED = "locked"  # All legs filled, position secured
    UNWINDING = "unwinding"  # Closing before resolution
    HELD_TO_RESOLUTION = "held_to_resolution"  # Waiting for market resolution
    REDEEMED = "redeemed"  # Markets resolved, tokens redeemed to cash
    CLOSED = "closed"  # Final state, position settled


class TIF(Enum):
    """Time-in-force options."""
    FOK = "fill_or_kill"  # Entire order must fill immediately or cancel
    FAK = "fill_and_kill"  # Fill all possible shares, cancel remainder
    GTC = "good_til_cancel"  # Resting order until filled or cancelled


@dataclass
class ExecutionLeg:
    """
    Single leg of an arbitrage position.

    Represents one token on one venue: buy or sell, at market or limit.
    """
    venue: str  # "polymarket" or "kalshi"
    token_id: str
    side: str  # "BUY" or "SELL"
    size: float  # Number of shares
    price: Optional[float] = None  # Limit price; None = market order
    tif: TIF = TIF.FOK  # Fill strategy
    filled: float = 0.0  # Shares actually filled
    avg_fill_price: float = 0.0  # Volume-weighted average fill price
    order_id: Optional[str] = None  # Venue order ID
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def is_filled(self) -> bool:
        """Check if entire leg is filled."""
        return abs(self.filled - self.size) < 1e-8

    def fill_fraction(self) -> float:
        """Return fill percentage (0.0 to 1.0)."""
        return self.filled / self.size if self.size > 0 else 0.0


@dataclass
class ArbPosition:
    """
    Complete arbitrage position with state tracking and risk management.

    Tracks all legs, fills, P&L, and state transitions.
    """
    position_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    opportunity_route: str = ""  # "ComplementBox[market_123]", etc.
    state: PositionState = PositionState.DISCOVERED
    legs: List[ExecutionLeg] = field(default_factory=list)
    target_edge: float = 0.0  # Expected profit
    execution_cost: float = 0.0  # All-in cost
    guaranteed_payout: float = 0.0  # Minimum payout at resolution

    created_at: datetime = field(default_factory=datetime.utcnow)
    locked_at: Optional[datetime] = None
    resolution_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    # Risk tracking
    kill_switch: bool = False  # Emergency stop
    max_loss_tolerance: float = float('inf')  # Per-position max loss
    partial_fill_timeout_sec: float = 30.0  # Unwind if not filled after N seconds

    # P&L tracking
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    def add_leg(self, leg: ExecutionLeg) -> None:
        """Add a leg to this position."""
        self.legs.append(leg)

    def all_legs_locked(self) -> bool:
        """Check if all legs are fully filled."""
        if not self.legs:
            return False
        return all(leg.is_filled() for leg in self.legs)

    def any_leg_locked(self) -> bool:
        """Check if any leg has begun filling."""
        return any(leg.filled > 0 for leg in self.legs)

    def fill_fraction(self) -> float:
        """Return average fill fraction across legs (0.0 to 1.0)."""
        if not self.legs:
            return 0.0
        return sum(leg.fill_fraction() for leg in self.legs) / len(self.legs)

    def transition_to(self, new_state: PositionState) -> None:
        """
        Transition to a new state with validation.

        Enforces valid state transitions.
        """
        valid_transitions = {
            PositionState.DISCOVERED: [PositionState.ENTERING, PositionState.CLOSED],
            PositionState.ENTERING: [PositionState.PARTIALLY_FILLED, PositionState.LOCKED, PositionState.UNWINDING, PositionState.CLOSED],
            PositionState.PARTIALLY_FILLED: [PositionState.LOCKED, PositionState.UNWINDING, PositionState.CLOSED],
            PositionState.LOCKED: [PositionState.UNWINDING, PositionState.HELD_TO_RESOLUTION, PositionState.CLOSED],
            PositionState.UNWINDING: [PositionState.CLOSED],
            PositionState.HELD_TO_RESOLUTION: [PositionState.REDEEMED, PositionState.CLOSED],
            PositionState.REDEEMED: [PositionState.CLOSED],
            PositionState.CLOSED: [],
        }

        if new_state not in valid_transitions.get(self.state, []):
            raise ValueError(f"Invalid transition {self.state.value} -> {new_state.value}")

        self.state = new_state
        if new_state == PositionState.LOCKED:
            self.locked_at = datetime.utcnow()
        elif new_state == PositionState.REDEEMED:
            self.resolution_at = datetime.utcnow()
        elif new_state == PositionState.CLOSED:
            self.closed_at = datetime.utcnow()

    def compute_pnl(self) -> float:
        """
        Estimate current P&L.

        For locked/resolved positions: realized_pnl
        For partial fills: estimated based on execution_cost and guaranteed_payout
        """
        if self.state in (PositionState.REDEEMED, PositionState.CLOSED):
            return self.realized_pnl

        # Estimate based on fills
        if self.all_legs_locked():
            # All legs filled; expect to realize guaranteed_payout
            total_cost = sum(
                leg.filled * leg.avg_fill_price if leg.side == "BUY" else -leg.filled * leg.avg_fill_price
                for leg in self.legs
            )
            return self.guaranteed_payout - abs(total_cost)

        return self.unrealized_pnl


class ExecutionRouter:
    """
    Orchestrates order routing and position lifecycle.

    Handles:
    - Immediate transform routes (merge/convert/split)
    - Cross-platform hedging (thin leg first, thick leg second)
    - Hold-to-resolution baskets
    - Emergency unwind
    - Monitoring and closure
    """

    def __init__(
        self,
        max_concurrent_exposure: float = 10000.0,
        daily_loss_cap: float = 500.0,
        position_timeout_sec: float = 60.0,
    ):
        self.positions: Dict[str, ArbPosition] = {}
        self.max_concurrent_exposure = max_concurrent_exposure
        self.daily_loss_cap = daily_loss_cap
        self.position_timeout_sec = position_timeout_sec
        self.daily_realized_pnl = 0.0

    def execute_immediate_transform(self, arb_opp, quantity: float) -> ArbPosition:
        """
        Execute complement box or neg-risk conversion immediately.

        Strategy:
        1. Send both legs as market orders (FOK)
        2. If either leg fails, unwind immediately
        3. If both fill, merge/convert immediately
        4. P&L locked within seconds

        Args:
            arb_opp: ArbOpportunity object
            quantity: Number of shares to transact

        Returns:
            ArbPosition with state LOCKED or CLOSED (if failed)
        """
        position = ArbPosition(
            opportunity_route=arb_opp.route,
            state=PositionState.DISCOVERED,
            target_edge=arb_opp.net_locked_edge * quantity,
            execution_cost=arb_opp.executable_cost * quantity,
            guaranteed_payout=arb_opp.guaranteed_payout * quantity,
        )

        # Create legs from opportunity
        for leg_dict in arb_opp.legs:
            leg = ExecutionLeg(
                venue=leg_dict["venue"],
                token_id=leg_dict["token_id"],
                side=leg_dict["side"],
                size=quantity,
                price=None,  # Market order
                tif=TIF.FOK,  # Immediate or fail
            )
            position.add_leg(leg)

        self.positions[position.position_id] = position
        position.transition_to(PositionState.ENTERING)

        # Attempt to fill both legs
        # In production: dispatch to venue connectors, await fills
        # For now: stub with assumed fills
        for leg in position.legs:
            leg.filled = leg.size
            leg.avg_fill_price = 0.5  # Stub: assume mid-price

        if position.all_legs_locked():
            position.transition_to(PositionState.LOCKED)
            # Immediate transform: merge/convert, transition to held-to-resolution
            position.transition_to(PositionState.HELD_TO_RESOLUTION)
        else:
            # Partial fill: unwind
            position.transition_to(PositionState.UNWINDING)
            self.emergency_unwind(position)

        return position

    def execute_cross_platform(self, arb_opp, quantity: float) -> ArbPosition:
        """
        Execute cross-platform arb with thin leg first, thick leg second.

        Strategy:
        1. Send thin leg (smaller liquidity) as limit order
        2. Once filled, send thick leg (larger liquidity) to hedge
        3. Both settle same-day; minimal overnight exposure

        Args:
            arb_opp: ArbOpportunity object
            quantity: Number of shares

        Returns:
            ArbPosition
        """
        position = ArbPosition(
            opportunity_route=arb_opp.route,
            state=PositionState.DISCOVERED,
            target_edge=arb_opp.net_locked_edge * quantity,
            execution_cost=arb_opp.executable_cost * quantity,
            guaranteed_payout=arb_opp.guaranteed_payout * quantity,
        )

        # Identify thin and thick legs
        legs_data = arb_opp.legs
        thin_leg = legs_data[0]  # Assume first is Kalshi (smaller)
        thick_leg = legs_data[1]  # Polymarket (larger)

        # Add thin leg with limit order
        thin = ExecutionLeg(
            venue=thin_leg["venue"],
            token_id=thin_leg["token_id"],
            side=thin_leg["side"],
            size=quantity,
            price=0.62,  # Stub: ask price
            tif=TIF.GTC,  # Resting order
        )
        position.add_leg(thin)

        # Wait for thin leg fill (in production: async monitoring)
        # Then add thick leg
        thick = ExecutionLeg(
            venue=thick_leg["venue"],
            token_id=thick_leg["token_id"],
            side=thick_leg["side"],
            size=quantity,
            price=0.65,  # Stub: bid price
            tif=TIF.FOK,  # Immediate market
        )
        position.add_leg(thick)

        self.positions[position.position_id] = position
        position.transition_to(PositionState.ENTERING)

        # Stub fills
        for leg in position.legs:
            leg.filled = leg.size
            leg.avg_fill_price = 0.63

        if position.all_legs_locked():
            position.transition_to(PositionState.LOCKED)
            position.transition_to(PositionState.HELD_TO_RESOLUTION)

        return position

    def execute_hold_to_resolution(self, arb_opp, quantity: float) -> ArbPosition:
        """
        Execute implication or mutual-exclusion arb held to resolution.

        Strategy:
        1. Send all legs as limit orders at mid-price
        2. Fill gradually as volume permits (FAK strategy)
        3. Hold locked position until markets resolve
        4. Redeem and collect P&L

        Args:
            arb_opp: ArbOpportunity object
            quantity: Number of shares

        Returns:
            ArbPosition
        """
        position = ArbPosition(
            opportunity_route=arb_opp.route,
            state=PositionState.DISCOVERED,
            target_edge=arb_opp.net_locked_edge * quantity,
            execution_cost=arb_opp.executable_cost * quantity,
            guaranteed_payout=arb_opp.guaranteed_payout * quantity,
        )

        for leg_dict in arb_opp.legs:
            leg = ExecutionLeg(
                venue=leg_dict["venue"],
                token_id=leg_dict["token_id"],
                side=leg_dict["side"],
                size=quantity,
                price=0.50,  # Stub mid-price
                tif=TIF.FAK,  # Fill what's available, cancel rest
            )
            position.add_leg(leg)

        self.positions[position.position_id] = position
        position.transition_to(PositionState.ENTERING)

        return position

    def emergency_unwind(self, position: ArbPosition) -> None:
        """
        Close a position immediately at any price.

        Used for:
        - Partial fill recovery (cancel remaining legs, sell any filled legs)
        - Kill switch triggered
        - Daily loss cap exceeded
        - Timeout on hold-to-resolution

        Args:
            position: ArbPosition to unwind
        """
        if position.state == PositionState.CLOSED:
            return

        position.transition_to(PositionState.UNWINDING)

        # For each leg with positive fill, create a reverse order (market, FOK)
        for leg in position.legs:
            if leg.filled > 0:
                # Market sell (or buy if originally SELL)
                reverse_side = "SELL" if leg.side == "BUY" else "BUY"
                unwind_leg = ExecutionLeg(
                    venue=leg.venue,
                    token_id=leg.token_id,
                    side=reverse_side,
                    size=leg.filled,
                    price=None,  # Market
                    tif=TIF.FOK,
                )
                # In production: dispatch to venue
                # Stub: assume market fill at 0.5
                unwind_leg.filled = unwind_leg.size
                unwind_leg.avg_fill_price = 0.5

        position.transition_to(PositionState.CLOSED)
        position.realized_pnl = -position.execution_cost * 0.1  # Stub: 10% loss on unwind

    def monitor_and_close(self) -> None:
        """
        Monitor all positions and close when:
        - Markets resolve (transition to REDEEMED)
        - Hold timeout expires (emergency unwind)
        - Daily loss exceeds cap (emergency unwind)
        """
        now = datetime.utcnow()

        for position in self.positions.values():
            if position.state == PositionState.CLOSED:
                continue

            # Check daily loss cap
            if self.daily_realized_pnl < -self.daily_loss_cap:
                self.emergency_unwind(position)
                continue

            # Check kill switch
            if position.kill_switch:
                self.emergency_unwind(position)
                continue

            # Check hold timeout
            if position.state == PositionState.HELD_TO_RESOLUTION:
                if position.locked_at and (now - position.locked_at).total_seconds() > 86400 * 30:
                    # Held for 30 days, force close
                    self.emergency_unwind(position)
                    continue

            # Check market resolution (stub: would query markets)
            # If market resolved, transition to REDEEMED, then CLOSED

    def get_position(self, position_id: str) -> Optional[ArbPosition]:
        """Retrieve a position by ID."""
        return self.positions.get(position_id)

    def list_positions(self, state: Optional[PositionState] = None) -> List[ArbPosition]:
        """List all positions, optionally filtered by state."""
        if state is None:
            return list(self.positions.values())
        return [p for p in self.positions.values() if p.state == state]

    def total_exposure(self) -> float:
        """Calculate total capital currently locked in active positions."""
        total = 0.0
        for position in self.positions.values():
            if position.state in (PositionState.LOCKED, PositionState.HELD_TO_RESOLUTION):
                total += position.execution_cost
        return total

    def total_pnl(self) -> float:
        """Calculate total realized P&L across closed positions."""
        return sum(p.realized_pnl for p in self.positions.values() if p.state == PositionState.CLOSED)
