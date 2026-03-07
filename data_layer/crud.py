"""Clean CRUD access layer for all tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .schema import (
    DetectorRun,
    EdgeCard,
    Experiment,
    Market,
    Opportunity,
    OrderbookSnapshot,
    SystemLog,
    TradeTick,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Markets ──────────────────────────────────────────────────────────

def upsert_market(session: Session, market_id: str, **kwargs) -> Market:
    """Insert or update a market by market_id."""
    row = session.execute(
        select(Market).where(Market.market_id == market_id)
    ).scalar_one_or_none()
    if row is None:
        row = Market(market_id=market_id, **kwargs)
        session.add(row)
    else:
        for k, v in kwargs.items():
            setattr(row, k, v)
        row.updated_at = _utcnow()
    session.flush()
    return row


def get_market(session: Session, market_id: str) -> Market | None:
    return session.execute(
        select(Market).where(Market.market_id == market_id)
    ).scalar_one_or_none()


def list_markets(
    session: Session,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Market]:
    q = select(Market)
    if status:
        q = q.where(Market.status == status)
    q = q.order_by(Market.updated_at.desc()).limit(limit).offset(offset)
    return list(session.execute(q).scalars().all())


# ── Orderbook snapshots ─────────────────────────────────────────────

def add_orderbook_snapshot(session: Session, **kwargs) -> OrderbookSnapshot:
    row = OrderbookSnapshot(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_orderbook_snapshots(
    session: Session,
    token_id: str,
    limit: int = 50,
) -> list[OrderbookSnapshot]:
    q = (
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.token_id == token_id)
        .order_by(OrderbookSnapshot.fetched_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Trade ticks ──────────────────────────────────────────────────────

def add_trade_tick(session: Session, **kwargs) -> TradeTick:
    row = TradeTick(**kwargs)
    session.add(row)
    session.flush()
    return row


def add_trade_ticks_bulk(session: Session, rows: list[dict]) -> int:
    objects = [TradeTick(**r) for r in rows]
    session.add_all(objects)
    session.flush()
    return len(objects)


def get_trade_ticks(
    session: Session,
    token_id: str,
    limit: int = 100,
) -> list[TradeTick]:
    q = (
        select(TradeTick)
        .where(TradeTick.token_id == token_id)
        .order_by(TradeTick.fetched_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Detector runs ────────────────────────────────────────────────────

def create_detector_run(session: Session, **kwargs) -> DetectorRun:
    row = DetectorRun(**kwargs)
    session.add(row)
    session.flush()
    return row


def finish_detector_run(
    session: Session,
    run_id: int,
    *,
    status: str = "success",
    markets_scanned: int = 0,
    edges_found: int = 0,
    opportunities_created: int = 0,
    error_detail: str | None = None,
) -> None:
    session.execute(
        update(DetectorRun)
        .where(DetectorRun.id == run_id)
        .values(
            finished_at=_utcnow(),
            status=status,
            markets_scanned=markets_scanned,
            edges_found=edges_found,
            opportunities_created=opportunities_created,
            error_detail=error_detail,
        )
    )
    session.flush()
    session.expire_all()


def get_detector_run(session: Session, run_id: int) -> DetectorRun | None:
    return session.get(DetectorRun, run_id)


def list_detector_runs(
    session: Session, limit: int = 20
) -> list[DetectorRun]:
    q = (
        select(DetectorRun)
        .order_by(DetectorRun.started_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Edge cards ───────────────────────────────────────────────────────

def add_edge_card(session: Session, **kwargs) -> EdgeCard:
    row = EdgeCard(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_edge_cards_for_run(
    session: Session, run_id: int
) -> list[EdgeCard]:
    q = (
        select(EdgeCard)
        .where(EdgeCard.run_id == run_id)
        .order_by(EdgeCard.edge.desc())
    )
    return list(session.execute(q).scalars().all())


def get_edge_cards_for_market(
    session: Session, market_id: str, limit: int = 20
) -> list[EdgeCard]:
    q = (
        select(EdgeCard)
        .where(EdgeCard.market_id == market_id)
        .order_by(EdgeCard.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Opportunities ────────────────────────────────────────────────────

def create_opportunity(session: Session, **kwargs) -> Opportunity:
    row = Opportunity(**kwargs)
    session.add(row)
    session.flush()
    return row


def resolve_opportunity(
    session: Session,
    opp_id: int,
    *,
    outcome: str,
    pnl: float,
) -> None:
    session.execute(
        update(Opportunity)
        .where(Opportunity.id == opp_id)
        .values(
            status="resolved",
            outcome=outcome,
            pnl=pnl,
            resolved_at=_utcnow(),
        )
    )
    session.flush()
    session.expire_all()


def list_opportunities(
    session: Session,
    status: str | None = None,
    limit: int = 50,
) -> list[Opportunity]:
    q = select(Opportunity)
    if status:
        q = q.where(Opportunity.status == status)
    q = q.order_by(Opportunity.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Experiments ──────────────────────────────────────────────────────

def create_experiment(session: Session, **kwargs) -> Experiment:
    row = Experiment(**kwargs)
    session.add(row)
    session.flush()
    return row


def complete_experiment(
    session: Session,
    exp_id: int,
    *,
    status: str = "completed",
    result_summary: str | None = None,
    result_data: dict | None = None,
) -> None:
    session.execute(
        update(Experiment)
        .where(Experiment.id == exp_id)
        .values(
            status=status,
            result_summary=result_summary,
            result_data=result_data,
            completed_at=_utcnow(),
        )
    )
    session.flush()
    session.expire_all()


def get_experiment(session: Session, name: str) -> Experiment | None:
    return session.execute(
        select(Experiment).where(Experiment.name == name)
    ).scalar_one_or_none()


def list_experiments(session: Session, limit: int = 20) -> list[Experiment]:
    q = (
        select(Experiment)
        .order_by(Experiment.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── System logs ──────────────────────────────────────────────────────

def log(
    session: Session,
    level: str,
    component: str,
    message: str,
    data: dict | None = None,
) -> SystemLog:
    row = SystemLog(level=level, component=component, message=message, data=data)
    session.add(row)
    session.flush()
    return row


def get_logs(
    session: Session,
    level: str | None = None,
    component: str | None = None,
    limit: int = 100,
) -> list[SystemLog]:
    q = select(SystemLog)
    if level:
        q = q.where(SystemLog.level == level)
    if component:
        q = q.where(SystemLog.component == component)
    q = q.order_by(SystemLog.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())
