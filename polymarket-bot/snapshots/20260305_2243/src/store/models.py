"""SQLAlchemy 2.0 async models for Polymarket trading bot."""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
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
        default=lambda: datetime.utcnow(),
        server_default="CURRENT_TIMESTAMP",
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
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
        default=lambda: datetime.utcnow(),
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
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<Position(id={self.id}, market_id={self.market_id}, "
            f"side={self.side}, size={self.size})>"
        )


class BotState(Base):
    """Singleton model for tracking bot runtime state."""

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    is_running: Mapped[bool] = mapped_column(default=False)
    kill_switch: Mapped[bool] = mapped_column(default=False)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(default=None)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    version: Mapped[str] = mapped_column(String(50), default="0.0.1")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.utcnow(),
        server_default="CURRENT_TIMESTAMP",
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
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
        default=lambda: datetime.utcnow(),
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
        default=lambda: datetime.utcnow(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<SizingDecision(market={self.market_id}, side={self.side}, "
            f"kelly_f={self.kelly_f:.4f}, size=${self.final_size_usd:.2f}, "
            f"decision={self.decision})>"
        )


class RiskEvent(Base):
    """Represents a risk management event."""

    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.utcnow(),
        server_default="CURRENT_TIMESTAMP",
    )

    def __repr__(self) -> str:
        return (
            f"<RiskEvent(id={self.id}, event_type={self.event_type}, "
            f"message={self.message})>"
        )
