"""Repository for market data ingestion CRUD operations."""

import json
from datetime import datetime
from src.core.time_utils import utc_now_naive
from typing import Optional, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from src.data.ingest.models import (
    IngestRun,
    MarketSnapshot,
    OrderbookSnapshot,
    TradeSnapshot,
)

logger = structlog.get_logger(__name__)


def _parse_prices(market: dict) -> tuple[Optional[float], Optional[float]]:
    """Extract YES/NO prices from a Gamma API market dict."""
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        try:
            prices = json.loads(raw)
            if len(prices) >= 2:
                return float(prices[0]), float(prices[1])
        except (json.JSONDecodeError, ValueError):
            pass
    if isinstance(raw, list) and len(raw) >= 2:
        return float(raw[0]), float(raw[1])
    return None, None


def _parse_token_ids(market: dict) -> tuple[Optional[str], Optional[str]]:
    """Extract YES/NO CLOB token IDs from a Gamma API market dict."""
    raw = market.get("clobTokenIds")
    tokens: list[str] = []
    if isinstance(raw, str):
        # API returns JSON array as string: '["token1", "token2"]'
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tokens = parsed
            else:
                tokens = [t.strip() for t in raw.split(",") if t.strip()]
        except (json.JSONDecodeError, ValueError):
            tokens = [t.strip() for t in raw.split(",") if t.strip()]
    elif isinstance(raw, list):
        tokens = raw

    yes_token = tokens[0] if len(tokens) > 0 else None
    no_token = tokens[1] if len(tokens) > 1 else None
    return yes_token, no_token


class IngestRepository:
    """CRUD operations for ingestion data."""

    # ── IngestRun ──────────────────────────────────────────────────

    @staticmethod
    async def create_run(session: AsyncSession) -> IngestRun:
        run = IngestRun()
        session.add(run)
        await session.flush()
        return run

    @staticmethod
    async def finish_run(
        session: AsyncSession,
        run: IngestRun,
        status: str,
        markets: int = 0,
        orderbooks: int = 0,
        trades: int = 0,
        errors: int = 0,
        error_detail: Optional[str] = None,
    ) -> IngestRun:
        run.finished_at = utc_now_naive()
        run.status = status
        run.markets_fetched = markets
        run.orderbooks_fetched = orderbooks
        run.trades_fetched = trades
        run.errors = errors
        run.error_detail = error_detail
        await session.flush()
        return run

    @staticmethod
    async def get_last_run(session: AsyncSession) -> Optional[IngestRun]:
        stmt = (
            select(IngestRun)
            .order_by(desc(IngestRun.id))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_recent_runs(
        session: AsyncSession, limit: int = 10
    ) -> Sequence[IngestRun]:
        stmt = (
            select(IngestRun)
            .order_by(desc(IngestRun.id))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    # ── MarketSnapshot ─────────────────────────────────────────────

    @staticmethod
    async def store_markets(
        session: AsyncSession,
        run_id: int,
        markets: list[dict],
    ) -> int:
        """Store a batch of market snapshots. Returns count stored."""
        now = utc_now_naive()
        count = 0
        for m in markets:
            market_id = m.get("id") or m.get("condition_id") or ""
            if not market_id:
                continue

            yes_price, no_price = _parse_prices(m)
            yes_token, no_token = _parse_token_ids(m)

            # API returns conditionId (camelCase), not condition_id
            cond_id = m.get("conditionId") or m.get("condition_id")
            # Determine status from active/closed booleans
            if m.get("active"):
                mstatus = "active"
            elif m.get("closed"):
                mstatus = "closed"
            else:
                mstatus = "unknown"

            snap = MarketSnapshot(
                ingest_run_id=run_id,
                fetched_at=now,
                market_id=market_id,
                condition_id=cond_id,
                question=m.get("question"),
                slug=m.get("slug"),
                status=mstatus,
                outcome_yes_price=yes_price,
                outcome_no_price=no_price,
                volume=float(m.get("volume", 0) or 0),
                liquidity=float(m.get("liquidity", 0) or 0),
                clob_token_id_yes=yes_token,
                clob_token_id_no=no_token,
                end_date=m.get("endDate") or m.get("endDateIso"),
                category=m.get("category"),
                raw_payload=m,
            )
            session.add(snap)
            count += 1

        await session.flush()
        logger.info("stored_market_snapshots", count=count)
        return count

    # ── OrderbookSnapshot ──────────────────────────────────────────

    @staticmethod
    async def store_orderbook(
        session: AsyncSession,
        run_id: int,
        market_id: str,
        token_id: str,
        side_label: str,
        orderbook: dict,
    ) -> OrderbookSnapshot:
        """Store a single orderbook snapshot."""
        tob = orderbook.get("_top_of_book", {})

        snap = OrderbookSnapshot(
            ingest_run_id=run_id,
            fetched_at=utc_now_naive(),
            market_id=market_id,
            token_id=token_id,
            side_label=side_label,
            best_bid=tob.get("best_bid"),
            best_ask=tob.get("best_ask"),
            spread=tob.get("spread"),
            midpoint=tob.get("midpoint"),
            bid_depth=tob.get("bid_depth", 0),
            ask_depth=tob.get("ask_depth", 0),
            raw_payload=orderbook,
        )
        session.add(snap)
        await session.flush()
        return snap

    # ── TradeSnapshot ──────────────────────────────────────────────

    @staticmethod
    async def store_trades(
        session: AsyncSession,
        run_id: int,
        market_id: str,
        token_id: str,
        side_label: str,
        trades: list[dict],
    ) -> int:
        """Store trade snapshots for a token. Returns count stored."""
        now = utc_now_naive()
        count = 0
        for t in trades:
            snap = TradeSnapshot(
                ingest_run_id=run_id,
                fetched_at=now,
                market_id=market_id,
                token_id=token_id,
                side_label=side_label,
                trade_price=_safe_float(t.get("price")),
                trade_size=_safe_float(t.get("size") or t.get("amount")),
                trade_side=t.get("side"),
                trade_timestamp=t.get("timestamp") or t.get("created_at"),
                trade_count=1,
                raw_payload=t,
            )
            session.add(snap)
            count += 1

        if not trades:
            # Store a single record noting no trades available
            snap = TradeSnapshot(
                ingest_run_id=run_id,
                fetched_at=now,
                market_id=market_id,
                token_id=token_id,
                side_label=side_label,
                trade_count=0,
                raw_payload={"_note": "no trades endpoint data"},
            )
            session.add(snap)
            count = 1

        await session.flush()
        return count

    # ── Query helpers ──────────────────────────────────────────────

    @staticmethod
    async def get_market_count(session: AsyncSession, run_id: int) -> int:
        stmt = select(func.count(MarketSnapshot.id)).where(
            MarketSnapshot.ingest_run_id == run_id
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def get_latest_snapshots(
        session: AsyncSession, limit: int = 5
    ) -> Sequence[MarketSnapshot]:
        stmt = (
            select(MarketSnapshot)
            .order_by(desc(MarketSnapshot.fetched_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_unique_markets_count(session: AsyncSession) -> int:
        stmt = select(
            func.count(func.distinct(MarketSnapshot.market_id))
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def get_orderbook_count(session: AsyncSession, run_id: int) -> int:
        stmt = select(func.count(OrderbookSnapshot.id)).where(
            OrderbookSnapshot.ingest_run_id == run_id
        )
        result = await session.execute(stmt)
        return result.scalar() or 0


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
