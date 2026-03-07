"""Tests for hardened kill-switch with latching and cooldown.

Verifies:
1. /kill sets kill_switch + kill_latched_at + kill_cooldown_until
2. /unkill blocked during cooldown (returns 423)
3. /unkill succeeds after cooldown
4. Kill switch blocks ALL order placement paths (via base.py gate)
5. Integration: in killed state, zero orders created
"""
import os
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.store.models import Base, BotState
from src.store.repository import Repository
from src.broker.base import KillSwitchActiveError, OrderSide
from src.broker.paper_broker import PaperBroker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """Fresh in-memory DB for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _env_setup():
    """Ensure NO_TRADE_MODE=false so order placement tests work."""
    original = os.environ.get("NO_TRADE_MODE")
    os.environ["NO_TRADE_MODE"] = "false"
    os.environ["KILL_COOLDOWN_SECONDS"] = "300"
    yield
    if original is None:
        os.environ.pop("NO_TRADE_MODE", None)
    else:
        os.environ["NO_TRADE_MODE"] = original
    os.environ.pop("KILL_COOLDOWN_SECONDS", None)


# ---------------------------------------------------------------------------
# Tests: Kill switch enables and latches
# ---------------------------------------------------------------------------

class TestKillSwitchLatch:
    @pytest.mark.asyncio
    async def test_kill_enables_and_latches(self, db_session):
        """set_kill_switch(enabled=True) sets kill_switch, kill_latched_at, and cooldown."""
        bot_state = await Repository.set_kill_switch(db_session, enabled=True)

        assert bot_state.kill_switch is True
        assert bot_state.kill_latched_at is not None
        assert bot_state.kill_cooldown_until is not None
        assert bot_state.kill_cooldown_until > bot_state.kill_latched_at

    @pytest.mark.asyncio
    async def test_get_kill_switch_returns_true_when_killed(self, db_session):
        """get_kill_switch returns True when kill switch is on."""
        await Repository.set_kill_switch(db_session, enabled=True)
        assert await Repository.get_kill_switch(db_session) is True

    @pytest.mark.asyncio
    async def test_get_kill_switch_returns_true_during_cooldown(self, db_session):
        """Even if kill_switch is manually cleared, cooldown blocks trading."""
        bot_state = await Repository.set_kill_switch(db_session, enabled=True)
        # Manually set kill_switch to False but leave cooldown active
        bot_state.kill_switch = False
        await db_session.flush()

        # get_kill_switch should still return True because cooldown is active
        assert await Repository.get_kill_switch(db_session) is True


# ---------------------------------------------------------------------------
# Tests: Unkill blocked during cooldown
# ---------------------------------------------------------------------------

class TestUnkillCooldown:
    @pytest.mark.asyncio
    async def test_unkill_blocked_during_cooldown(self, db_session):
        """clear_kill_switch fails while cooldown is active."""
        await Repository.set_kill_switch(db_session, enabled=True)

        success, message = await Repository.clear_kill_switch(db_session)
        assert success is False
        assert "Cooldown active" in message

    @pytest.mark.asyncio
    async def test_unkill_succeeds_after_cooldown(self, db_session):
        """clear_kill_switch succeeds when cooldown has expired."""
        await Repository.set_kill_switch(db_session, enabled=True)

        # Move cooldown to the past
        bot_state = await Repository.get_or_create_bot_state(db_session)
        bot_state.kill_cooldown_until = datetime.utcnow() - timedelta(seconds=1)
        await db_session.flush()

        success, message = await Repository.clear_kill_switch(db_session)
        assert success is True

        # Verify kill switch is now off
        assert await Repository.get_kill_switch(db_session) is False

    @pytest.mark.asyncio
    async def test_is_kill_cooldown_active(self, db_session):
        """is_kill_cooldown_active returns correct state."""
        # Initially no cooldown
        assert await Repository.is_kill_cooldown_active(db_session) is False

        # After kill, cooldown is active
        await Repository.set_kill_switch(db_session, enabled=True)
        assert await Repository.is_kill_cooldown_active(db_session) is True

        # After cooldown expires
        bot_state = await Repository.get_or_create_bot_state(db_session)
        bot_state.kill_cooldown_until = datetime.utcnow() - timedelta(seconds=1)
        await db_session.flush()
        assert await Repository.is_kill_cooldown_active(db_session) is False


# ---------------------------------------------------------------------------
# Tests: Kill blocks all order paths
# ---------------------------------------------------------------------------

class TestKillBlocksOrders:
    @pytest.mark.asyncio
    async def test_kill_blocks_paper_broker_orders(self):
        """When kill switch is on, PaperBroker.place_order raises KillSwitchActiveError."""
        from src.store.database import DatabaseManager
        from contextlib import asynccontextmanager

        # Create a separate async engine for the mock
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        test_session_factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        # Set kill switch ON
        async with test_session_factory() as s:
            await Repository.set_kill_switch(s, enabled=True)
            await s.commit()

        original_get_session = DatabaseManager.get_session

        @asynccontextmanager
        async def mock_get_session():
            async with test_session_factory() as s:
                yield s

        DatabaseManager.get_session = staticmethod(mock_get_session)
        try:
            broker = PaperBroker(initial_cash=1000.0)
            with pytest.raises(KillSwitchActiveError):
                await broker.place_order("mkt1", "YES", OrderSide.BUY, 0.5, 10.0)
        finally:
            DatabaseManager.get_session = original_get_session
            await test_engine.dispose()


# ---------------------------------------------------------------------------
# Tests: Integration — killed state means zero orders
# ---------------------------------------------------------------------------

class TestKilledStateZeroOrders:
    @pytest.mark.asyncio
    async def test_killed_state_zero_orders_created(self):
        """Integration: when kill switch is on, no orders are created."""
        from src.store.database import DatabaseManager
        from contextlib import asynccontextmanager

        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        test_session_factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        async with test_session_factory() as s:
            await Repository.set_kill_switch(s, enabled=True)
            await s.commit()

        original_get_session = DatabaseManager.get_session

        @asynccontextmanager
        async def mock_get_session():
            async with test_session_factory() as s:
                yield s

        DatabaseManager.get_session = staticmethod(mock_get_session)
        try:
            broker = PaperBroker(initial_cash=1000.0)

            # Attempt multiple orders — all should fail
            orders_placed = 0
            for i in range(5):
                try:
                    await broker.place_order(f"mkt_{i}", "YES", OrderSide.BUY, 0.5, 2.0)
                    orders_placed += 1
                except KillSwitchActiveError:
                    pass

            assert orders_placed == 0
            assert broker.get_cash() == 1000.0  # No cash change
        finally:
            DatabaseManager.get_session = original_get_session
            await test_engine.dispose()
