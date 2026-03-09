"""SQLAlchemy models for market data ingestion.

Stores both raw JSON payloads (for reprocessing) and normalized columns
(for fast queries).
"""

from datetime import datetime
from src.core.time_utils import utc_now_naive
from typing import Optional

from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.store.models import Base


class IngestRun(Base):
    """Metadata about each ingestion run."""

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(
        String(20), default="running"
    )  # running, success, partial, failed
    markets_fetched: Mapped[int] = mapped_column(default=0)
    orderbooks_fetched: Mapped[int] = mapped_column(default=0)
    trades_fetched: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, default=None)

    def __repr__(self) -> str:
        return (
            f"<IngestRun(id={self.id}, status={self.status}, "
            f"markets={self.markets_fetched})>"
        )


class MarketSnapshot(Base):
    """Raw + normalized market metadata snapshot from Gamma API."""

    __tablename__ = "market_snapshots"
    __table_args__ = (
        Index("ix_market_snap_market_ts", "market_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ingest_run_id: Mapped[int] = mapped_column(index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(), index=True
    )

    # Normalized fields
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    condition_id: Mapped[Optional[str]] = mapped_column(String(255))
    question: Mapped[Optional[str]] = mapped_column(Text)
    slug: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    outcome_yes_price: Mapped[Optional[float]] = mapped_column(default=None)
    outcome_no_price: Mapped[Optional[float]] = mapped_column(default=None)
    volume: Mapped[Optional[float]] = mapped_column(default=None)
    liquidity: Mapped[Optional[float]] = mapped_column(default=None)
    clob_token_id_yes: Mapped[Optional[str]] = mapped_column(String(255))
    clob_token_id_no: Mapped[Optional[str]] = mapped_column(String(255))
    end_date: Mapped[Optional[str]] = mapped_column(String(50))
    category: Mapped[Optional[str]] = mapped_column(String(100))

    # Raw payload for reprocessing
    raw_payload: Mapped[dict] = mapped_column(JSON)

    def __repr__(self) -> str:
        return (
            f"<MarketSnapshot(market_id={self.market_id}, "
            f"yes={self.outcome_yes_price}, no={self.outcome_no_price})>"
        )


class OrderbookSnapshot(Base):
    """Raw + normalized order book snapshot from CLOB API."""

    __tablename__ = "orderbook_snapshots"
    __table_args__ = (
        Index("ix_ob_snap_token_ts", "token_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ingest_run_id: Mapped[int] = mapped_column(index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(), index=True
    )

    # Normalized fields
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side_label: Mapped[Optional[str]] = mapped_column(
        String(10)
    )  # YES or NO

    best_bid: Mapped[Optional[float]] = mapped_column(default=None)
    best_ask: Mapped[Optional[float]] = mapped_column(default=None)
    spread: Mapped[Optional[float]] = mapped_column(default=None)
    midpoint: Mapped[Optional[float]] = mapped_column(default=None)
    bid_depth: Mapped[int] = mapped_column(default=0)
    ask_depth: Mapped[int] = mapped_column(default=0)

    # Raw payload for reprocessing
    raw_payload: Mapped[dict] = mapped_column(JSON)

    def __repr__(self) -> str:
        return (
            f"<OrderbookSnapshot(token_id={self.token_id}, "
            f"mid={self.midpoint}, spread={self.spread})>"
        )


class TradeSnapshot(Base):
    """Raw + normalized recent trade data from CLOB API."""

    __tablename__ = "trade_snapshots"
    __table_args__ = (
        Index("ix_trade_snap_token_ts", "token_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ingest_run_id: Mapped[int] = mapped_column(index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        default=lambda: utc_now_naive(), index=True
    )

    # Normalized fields
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side_label: Mapped[Optional[str]] = mapped_column(String(10))
    trade_price: Mapped[Optional[float]] = mapped_column(default=None)
    trade_size: Mapped[Optional[float]] = mapped_column(default=None)
    trade_side: Mapped[Optional[str]] = mapped_column(
        String(10)
    )  # BUY or SELL
    trade_timestamp: Mapped[Optional[str]] = mapped_column(String(50))
    trade_count: Mapped[int] = mapped_column(default=0)

    # Raw payload for reprocessing
    raw_payload: Mapped[dict] = mapped_column(JSON)

    def __repr__(self) -> str:
        return (
            f"<TradeSnapshot(token_id={self.token_id}, "
            f"price={self.trade_price}, count={self.trade_count})>"
        )
