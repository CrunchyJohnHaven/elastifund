"""SQLAlchemy 2.0 models — synchronous SQLite data layer.

Tables:
  markets, orderbook_snapshots, trade_ticks, edge_cards,
  experiments, detector_runs, opportunities, system_logs
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Float, Index, Integer, String, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Markets ──────────────────────────────────────────────────────────

class Market(Base):
    """Canonical market record.  One row per Polymarket condition_id."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    condition_id: Mapped[Optional[str]] = mapped_column(String(255))
    question: Mapped[Optional[str]] = mapped_column(Text)
    slug: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    outcome_yes_price: Mapped[Optional[float]] = mapped_column(Float)
    outcome_no_price: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    liquidity: Mapped[Optional[float]] = mapped_column(Float)
    clob_token_id_yes: Mapped[Optional[str]] = mapped_column(String(255))
    clob_token_id_no: Mapped[Optional[str]] = mapped_column(String(255))
    end_date: Mapped[Optional[str]] = mapped_column(String(50))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    resolution: Mapped[Optional[str]] = mapped_column(String(10))  # YES, NO, null
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


# ── Orderbook snapshots ─────────────────────────────────────────────

class OrderbookSnapshot(Base):
    """Point-in-time orderbook snapshot."""

    __tablename__ = "orderbook_snapshots"
    __table_args__ = (
        Index("ix_ob_token_ts", "token_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side_label: Mapped[Optional[str]] = mapped_column(String(10))  # YES / NO
    best_bid: Mapped[Optional[float]] = mapped_column(Float)
    best_ask: Mapped[Optional[float]] = mapped_column(Float)
    spread: Mapped[Optional[float]] = mapped_column(Float)
    midpoint: Mapped[Optional[float]] = mapped_column(Float)
    bid_depth: Mapped[int] = mapped_column(Integer, default=0)
    ask_depth: Mapped[int] = mapped_column(Integer, default=0)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


# ── Trade ticks ──────────────────────────────────────────────────────

class TradeTick(Base):
    """Individual trade tick."""

    __tablename__ = "trade_ticks"
    __table_args__ = (
        Index("ix_tt_token_ts", "token_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side_label: Mapped[Optional[str]] = mapped_column(String(10))
    price: Mapped[Optional[float]] = mapped_column(Float)
    size: Mapped[Optional[float]] = mapped_column(Float)
    side: Mapped[Optional[str]] = mapped_column(String(10))  # BUY / SELL
    trade_ts: Mapped[Optional[str]] = mapped_column(String(50))  # original API ts
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


# ── Detector runs ────────────────────────────────────────────────────

class DetectorRun(Base):
    """One execution of the edge-detection pipeline."""

    __tablename__ = "detector_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="running")
    markets_scanned: Mapped[int] = mapped_column(Integer, default=0)
    edges_found: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_created: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[Optional[dict]] = mapped_column(JSON)
    error_detail: Mapped[Optional[str]] = mapped_column(Text)


# ── Edge cards ───────────────────────────────────────────────────────

class EdgeCard(Base):
    """A single edge signal produced by the detector."""

    __tablename__ = "edge_cards"
    __table_args__ = (
        Index("ix_ec_market_created", "market_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("detector_runs.id"), index=True
    )
    side: Mapped[str] = mapped_column(String(10))  # buy_yes / buy_no
    model_prob: Mapped[float] = mapped_column(Float)
    market_price: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    confidence: Mapped[Optional[str]] = mapped_column(String(20))
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


# ── Opportunities ────────────────────────────────────────────────────

class Opportunity(Base):
    """Actionable trade opportunity derived from an edge card."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    edge_card_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("edge_cards.id"), index=True
    )
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    side: Mapped[str] = mapped_column(String(10))
    entry_price: Mapped[float] = mapped_column(Float)
    model_prob: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")
    outcome: Mapped[Optional[str]] = mapped_column(String(10))  # win / loss
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column()


# ── Experiments ──────────────────────────────────────────────────────

class Experiment(Base):
    """Tracked experiment (prompt variant, threshold change, etc.)."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    result_summary: Mapped[Optional[str]] = mapped_column(Text)
    result_data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column()


# ── System logs ──────────────────────────────────────────────────────

class SystemLog(Base):
    """Structured log entry."""

    __tablename__ = "system_logs"
    __table_args__ = (
        Index("ix_syslog_level_ts", "level", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(10))  # DEBUG..CRITICAL
    component: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
