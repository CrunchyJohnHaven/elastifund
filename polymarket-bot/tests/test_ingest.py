"""Tests for the data/ingest module."""

import asyncio
import json
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set DATABASE_URL before importing anything that reads config
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_ingest.db")


# ── Repository helper tests (sync, no DB needed) ──────────────────

class TestParseHelpers:
    def test_parse_prices_json_string(self):
        from src.data.ingest.repository import _parse_prices

        market = {"outcomePrices": '["0.65", "0.35"]'}
        yes, no = _parse_prices(market)
        assert yes == 0.65
        assert no == 0.35

    def test_parse_prices_list(self):
        from src.data.ingest.repository import _parse_prices

        market = {"outcomePrices": [0.7, 0.3]}
        yes, no = _parse_prices(market)
        assert yes == 0.7
        assert no == 0.3

    def test_parse_prices_missing(self):
        from src.data.ingest.repository import _parse_prices

        yes, no = _parse_prices({})
        assert yes is None
        assert no is None

    def test_parse_prices_invalid_string(self):
        from src.data.ingest.repository import _parse_prices

        market = {"outcomePrices": "not json"}
        yes, no = _parse_prices(market)
        assert yes is None
        assert no is None

    def test_parse_token_ids_json_string(self):
        from src.data.ingest.repository import _parse_token_ids

        market = {"clobTokenIds": '["token_yes_123", "token_no_456"]'}
        yes, no = _parse_token_ids(market)
        assert yes == "token_yes_123"
        assert no == "token_no_456"

    def test_parse_token_ids_list(self):
        from src.data.ingest.repository import _parse_token_ids

        market = {"clobTokenIds": ["abc", "def"]}
        yes, no = _parse_token_ids(market)
        assert yes == "abc"
        assert no == "def"

    def test_parse_token_ids_single(self):
        from src.data.ingest.repository import _parse_token_ids

        market = {"clobTokenIds": '["only_one"]'}
        yes, no = _parse_token_ids(market)
        assert yes == "only_one"
        assert no is None

    def test_parse_token_ids_missing(self):
        from src.data.ingest.repository import _parse_token_ids

        yes, no = _parse_token_ids({})
        assert yes is None
        assert no is None

    def test_safe_float(self):
        from src.data.ingest.repository import _safe_float

        assert _safe_float("1.5") == 1.5
        assert _safe_float(2) == 2.0
        assert _safe_float(None) is None
        assert _safe_float("bad") is None


# ── Fetcher tests (mocked HTTP) ───────────────────────────────────

class TestMarketDataFetcher:
    @pytest.fixture
    def sample_market(self):
        return {
            "id": "12345",
            "question": "Will it rain?",
            "conditionId": "0xabc",
            "clobTokenIds": '["yes_token", "no_token"]',
            "outcomePrices": '["0.6", "0.4"]',
            "volume": "1000.5",
            "liquidity": "500.0",
            "endDate": "2026-04-01T00:00:00Z",
            "slug": "will-it-rain",
            "active": True,
            "closed": False,
        }

    @pytest.fixture
    def sample_orderbook(self):
        return {
            "market": "0xabc",
            "asset_id": "yes_token",
            "timestamp": "1234567890",
            "bids": [
                {"price": "0.55", "size": "100"},
                {"price": "0.50", "size": "200"},
            ],
            "asks": [
                {"price": "0.65", "size": "100"},
                {"price": "0.70", "size": "150"},
            ],
        }

    @pytest.mark.asyncio
    async def test_fetch_markets_single_page(self, sample_market):
        from src.data.ingest.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher()
        # Mock the _request method
        fetcher._request = AsyncMock(
            return_value=([sample_market] * 50, {"elapsed_ms": 50, "content_length": 1000})
        )

        markets = await fetcher.fetch_markets(max_pages=1)
        assert len(markets) == 50
        assert markets[0]["question"] == "Will it rain?"
        fetcher._request.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_markets_pagination_stops_short_page(self, sample_market):
        from src.data.ingest.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher()
        # First page full (100), second page short (30) -> stops
        fetcher._request = AsyncMock(
            side_effect=[
                ([sample_market] * 100, {"elapsed_ms": 50, "content_length": 1000}),
                ([sample_market] * 30, {"elapsed_ms": 50, "content_length": 1000}),
            ]
        )

        markets = await fetcher.fetch_markets(max_pages=5)
        assert len(markets) == 130
        assert fetcher._request.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_orderbook_computes_top_of_book(self, sample_orderbook):
        from src.data.ingest.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher()
        fetcher._request = AsyncMock(
            return_value=(sample_orderbook, {"elapsed_ms": 30, "content_length": 500})
        )

        ob = await fetcher.fetch_orderbook("yes_token")
        tob = ob["_top_of_book"]
        assert tob["best_bid"] == 0.55
        assert tob["best_ask"] == 0.65
        assert tob["spread"] == pytest.approx(0.10, abs=0.001)
        assert tob["midpoint"] == pytest.approx(0.60, abs=0.001)
        assert tob["bid_depth"] == 2
        assert tob["ask_depth"] == 2

    @pytest.mark.asyncio
    async def test_fetch_orderbook_empty_book(self):
        from src.data.ingest.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher()
        fetcher._request = AsyncMock(
            return_value=(
                {"bids": [], "asks": []},
                {"elapsed_ms": 30, "content_length": 100},
            )
        )

        ob = await fetcher.fetch_orderbook("token")
        tob = ob["_top_of_book"]
        assert tob["best_bid"] is None
        assert tob["best_ask"] is None
        assert tob["spread"] is None
        assert tob["midpoint"] is None

    @pytest.mark.asyncio
    async def test_fetch_trades_last_price_fallback(self):
        from src.data.ingest.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher()
        fetcher._request = AsyncMock(
            return_value=(
                {"price": "0.65", "side": "BUY"},
                {"elapsed_ms": 30, "content_length": 50},
            )
        )

        trades = await fetcher.fetch_trades("token")
        assert len(trades) == 1
        assert trades[0]["price"] == "0.65"
        assert trades[0]["side"] == "BUY"

    @pytest.mark.asyncio
    async def test_fetch_trades_no_endpoint(self):
        from src.data.ingest.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher()
        fetcher._request = AsyncMock(
            side_effect=RuntimeError("Failed")
        )

        trades = await fetcher.fetch_trades("token")
        assert trades == []

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from src.data.ingest.fetcher import MarketDataFetcher

        async with MarketDataFetcher() as fetcher:
            assert fetcher._client is not None
        assert fetcher._client is None


# ── extract_token_ids (standalone helper) ─────────────────────────

class TestExtractTokenIds:
    def test_json_array_string(self):
        from src.data.ingest.fetcher import extract_token_ids

        m = {"clobTokenIds": '["tok1", "tok2"]'}
        assert extract_token_ids(m) == ["tok1", "tok2"]

    def test_native_list(self):
        from src.data.ingest.fetcher import extract_token_ids

        m = {"clobTokenIds": ["tok1", "tok2"]}
        assert extract_token_ids(m) == ["tok1", "tok2"]

    def test_csv_fallback(self):
        from src.data.ingest.fetcher import extract_token_ids

        m = {"clobTokenIds": "tok1,tok2"}
        assert extract_token_ids(m) == ["tok1", "tok2"]

    def test_missing(self):
        from src.data.ingest.fetcher import extract_token_ids

        assert extract_token_ids({}) == []

    def test_empty_string(self):
        from src.data.ingest.fetcher import extract_token_ids

        assert extract_token_ids({"clobTokenIds": ""}) == []


# ── Model tests ───────────────────────────────────────────────────

class TestIngestModels:
    def test_ingest_run_repr(self):
        from src.data.ingest.models import IngestRun

        run = IngestRun(status="running", markets_fetched=10)
        assert "running" in repr(run)
        assert "10" in repr(run)

    def test_market_snapshot_repr(self):
        from src.data.ingest.models import MarketSnapshot

        snap = MarketSnapshot(
            market_id="test",
            outcome_yes_price=0.6,
            outcome_no_price=0.4,
            raw_payload={},
        )
        assert "test" in repr(snap)
        assert "0.6" in repr(snap)

    def test_orderbook_snapshot_repr(self):
        from src.data.ingest.models import OrderbookSnapshot

        snap = OrderbookSnapshot(
            token_id="tok",
            midpoint=0.5,
            spread=0.1,
            raw_payload={},
        )
        assert "tok" in repr(snap)


# ── DB integration tests ──────────────────────────────────────────

class TestIngestRepository:
    @pytest.fixture
    async def db_session(self):
        """Create an in-memory SQLite DB for testing."""
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        from src.store.models import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", echo=False
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            yield session
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_and_finish_run(self, db_session):
        from src.data.ingest.repository import IngestRepository

        run = await IngestRepository.create_run(db_session)
        assert run.id is not None
        assert run.status == "running"

        run = await IngestRepository.finish_run(
            db_session, run, status="success", markets=100, errors=0
        )
        assert run.status == "success"
        assert run.markets_fetched == 100
        assert run.finished_at is not None

    @pytest.mark.asyncio
    async def test_store_markets(self, db_session):
        from src.data.ingest.repository import IngestRepository

        run = await IngestRepository.create_run(db_session)

        markets = [
            {
                "id": "m1",
                "question": "Test market?",
                "conditionId": "0xabc",
                "outcomePrices": '["0.6", "0.4"]',
                "clobTokenIds": '["yes_tok", "no_tok"]',
                "volume": "1000",
                "liquidity": "500",
                "endDate": "2026-04-01",
                "active": True,
            },
            {
                "id": "m2",
                "question": "Another market?",
                "outcomePrices": [0.3, 0.7],
                "clobTokenIds": ["a", "b"],
                "volume": "200",
                "liquidity": "100",
                "active": False,
                "closed": True,
            },
        ]

        count = await IngestRepository.store_markets(db_session, run.id, markets)
        assert count == 2

        mc = await IngestRepository.get_market_count(db_session, run.id)
        assert mc == 2

    @pytest.mark.asyncio
    async def test_store_orderbook(self, db_session):
        from src.data.ingest.repository import IngestRepository

        run = await IngestRepository.create_run(db_session)

        ob_data = {
            "bids": [{"price": "0.5", "size": "100"}],
            "asks": [{"price": "0.6", "size": "100"}],
            "_top_of_book": {
                "best_bid": 0.5,
                "best_ask": 0.6,
                "spread": 0.1,
                "midpoint": 0.55,
                "bid_depth": 1,
                "ask_depth": 1,
            },
        }
        snap = await IngestRepository.store_orderbook(
            db_session, run.id, "m1", "yes_tok", "YES", ob_data
        )
        assert snap.midpoint == 0.55
        assert snap.spread == 0.1
        assert snap.market_id == "m1"

    @pytest.mark.asyncio
    async def test_store_trades_with_data(self, db_session):
        from src.data.ingest.repository import IngestRepository

        run = await IngestRepository.create_run(db_session)

        trades = [{"price": "0.65", "side": "BUY"}]
        count = await IngestRepository.store_trades(
            db_session, run.id, "m1", "yes_tok", "YES", trades
        )
        assert count == 1

    @pytest.mark.asyncio
    async def test_store_trades_empty(self, db_session):
        from src.data.ingest.repository import IngestRepository

        run = await IngestRepository.create_run(db_session)

        count = await IngestRepository.store_trades(
            db_session, run.id, "m1", "yes_tok", "YES", []
        )
        assert count == 1  # Still stores a "no data" record

    @pytest.mark.asyncio
    async def test_get_last_run(self, db_session):
        from src.data.ingest.repository import IngestRepository

        run1 = await IngestRepository.create_run(db_session)
        await IngestRepository.finish_run(db_session, run1, "success")
        run2 = await IngestRepository.create_run(db_session)
        await IngestRepository.finish_run(db_session, run2, "partial")

        last = await IngestRepository.get_last_run(db_session)
        assert last.id == run2.id
        assert last.status == "partial"
