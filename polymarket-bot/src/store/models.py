"""SQLAlchemy 2.0 async models for Polymarket trading bot."""
from datetime import datetime
from src.core.time_utils import utc_now_naive
from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Order(Base):
    """Represents a trading order."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side: Mapped[str] = mapped_column(String(10))  # "BUY" or "SELL"
    order_type: Mapped[str] = mapped_column(String(50))  # "LIMIT", "MARKET"
    price: Mapped[float]
    size: Mapped[float]
    filled_size: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        onupdate=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    # Relationships
    fills: Mapped[list["Fill"]] = relationship(
        "Fill",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id}, market_id={self.market_id}, "
            f"side={self.side}, price={self.price}, size={self.size})>"
        )


class Fill(Base):
    """Represents a partial or full execution of an order."""

    __tablename__ = "fills"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
    )
    price: Mapped[float]
    size: Mapped[float]
    fee: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    # Relationships
    order: Mapped[Order] = relationship("Order", back_populates="fills")

    def __repr__(self) -> str:
        return (
            f"<Fill(id={self.id}, order_id={self.order_id}, "
            f"price={self.price}, size={self.size})>"
        )


class Position(Base):
    """Represents an open or closed trading position."""

    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side: Mapped[str] = mapped_column(String(10))  # "LONG" or "SHORT"
    size: Mapped[float]
    avg_entry_price: Mapped[float]
    unrealized_pnl: Mapped[float] = mapped_column(default=0.0)
    realized_pnl: Mapped[float] = mapped_column(default=0.0)
    estimated_days_to_resolution: Mapped[Optional[float]] = mapped_column(default=None)
    velocity_score: Mapped[Optional[float]] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        onupdate=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<Position(id={self.id}, market_id={self.market_id}, "
            f"side={self.side}, size={self.size}, "
            f"est_days={self.estimated_days_to_resolution})>"
        )


class BotState(Base):
    """Singleton model for tracking bot runtime state."""

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    is_running: Mapped[bool] = mapped_column(default=False)
    kill_switch: Mapped[bool] = mapped_column(default=False)
    kill_latched_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    kill_cooldown_until: Mapped[Optional[datetime]] = mapped_column(default=None)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(default=None)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    version: Mapped[str] = mapped_column(String(50), default="0.0.1")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        onupdate=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<BotState(is_running={self.is_running}, "
            f"kill_switch={self.kill_switch})>"
        )


class DetectorOpportunity(Base):
    """A mispricing opportunity found by a detector plugin."""

    __tablename__ = "detector_opportunities"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), index=True)
    detector: Mapped[str] = mapped_column(String(50), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    group_label: Mapped[str] = mapped_column(String(500))
    market_ids: Mapped[dict] = mapped_column(JSON)  # stored as list
    edge_pct: Mapped[float]
    detail: Mapped[str] = mapped_column(String(1000))
    prices: Mapped[dict] = mapped_column(JSON, default=dict)
    meta_data: Mapped[dict] = mapped_column(JSON, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<DetectorOpportunity(detector={self.detector}, "
            f"kind={self.kind}, edge={self.edge_pct:.1f}%)>"
        )


class SizingDecision(Base):
    """Records a Kelly sizing decision for audit trail."""

    __tablename__ = "sizing_decisions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    side: Mapped[str] = mapped_column(String(10))  # "buy_yes" or "buy_no"
    p_estimated: Mapped[float]
    p_market: Mapped[float]
    fee_rate: Mapped[float] = mapped_column(default=0.02)
    edge_raw: Mapped[float] = mapped_column(default=0.0)
    edge_after_fee: Mapped[float] = mapped_column(default=0.0)
    kelly_f: Mapped[float] = mapped_column(default=0.0)
    kelly_mult: Mapped[float] = mapped_column(default=0.25)
    bankroll: Mapped[float] = mapped_column(default=0.0)
    raw_size_usd: Mapped[float] = mapped_column(default=0.0)
    category_haircut: Mapped[bool] = mapped_column(default=False)
    final_size_usd: Mapped[float] = mapped_column(default=0.0)
    decision: Mapped[str] = mapped_column(String(10), default="skip")  # "trade" or "skip"
    skip_reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<SizingDecision(market={self.market_id}, side={self.side}, "
            f"kelly_f={self.kelly_f:.4f}, size=${self.final_size_usd:.2f}, "
            f"decision={self.decision})>"
        )


class ShadowOrder(Base):
    """Records what a live order would have been during paper/shadow trading."""

    __tablename__ = "shadow_orders"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side: Mapped[str] = mapped_column(String(10))  # "BUY" or "SELL"
    price: Mapped[float]
    size: Mapped[float]
    execution_mode: Mapped[str] = mapped_column(String(10))  # "MAKER", "TAKER", "HYBRID"
    would_have_filled: Mapped[bool] = mapped_column(Boolean, default=True)
    estimated_fee: Mapped[float] = mapped_column(default=0.0)
    signal_edge: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<ShadowOrder(market={self.market_id}, side={self.side}, "
            f"price={self.price}, size={self.size}, mode={self.execution_mode})>"
        )


class ExecutionStat(Base):
    """Per-trade execution quality metrics.

    Tracks quoted mid, expected fee/edge, actual fill slippage, fill time,
    and cancel rate — answering 'are taker fees/slippage killing us?'
    """

    __tablename__ = "execution_stats"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(255), index=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255))
    side: Mapped[str] = mapped_column(String(10))  # "BUY" or "SELL"
    quoted_mid: Mapped[float]  # mid-price when signal was generated
    order_price: Mapped[float]  # price we placed the order at
    fill_price: Mapped[Optional[float]] = mapped_column(default=None)
    expected_fee: Mapped[float] = mapped_column(default=0.0)
    actual_fee: Mapped[float] = mapped_column(default=0.0)
    expected_edge: Mapped[float] = mapped_column(default=0.0)
    slippage_vs_mid: Mapped[Optional[float]] = mapped_column(default=None)
    fill_time_seconds: Mapped[Optional[float]] = mapped_column(default=None)
    was_filled: Mapped[bool] = mapped_column(default=False)
    was_cancelled: Mapped[bool] = mapped_column(default=False)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    execution_mode: Mapped[str] = mapped_column(String(20), default="MAKER")
    is_maker_sandbox: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionStat(order={self.order_id}, "
            f"filled={self.was_filled}, slippage={self.slippage_vs_mid})>"
        )


class PortfolioSnapshot(Base):
    """Daily portfolio value snapshot for equity curve tracking."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True, unique=True)
    cash_usd: Mapped[float] = mapped_column(default=0.0)
    positions_value_usd: Mapped[float] = mapped_column(default=0.0)
    total_value_usd: Mapped[float] = mapped_column(default=0.0)
    realized_pnl: Mapped[float] = mapped_column(default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(default=0.0)
    open_positions: Mapped[int] = mapped_column(default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return f"<PortfolioSnapshot(date={self.date}, total=${self.total_value_usd:.2f})>"


class ExitEvent(Base):
    """Records a position exit with reason, P&L, and hold duration."""

    __tablename__ = "exit_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    exit_reason: Mapped[str] = mapped_column(String(50), index=True)
    entry_price: Mapped[float]
    exit_price: Mapped[float]
    size: Mapped[float]
    hold_time_hours: Mapped[float]
    realized_pnl: Mapped[float]
    pnl_pct: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<ExitEvent(market={self.market_id}, reason={self.exit_reason}, "
            f"pnl={self.realized_pnl:+.4f}, held={self.hold_time_hours:.1f}h)>"
        )


class RiskEvent(Base):
    """Represents a risk management event."""

    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<RiskEvent(id={self.id}, event_type={self.event_type}, "
            f"message={self.message})>"
        )
