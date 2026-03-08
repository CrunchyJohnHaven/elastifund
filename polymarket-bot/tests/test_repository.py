"""Tests for repository."""
import pytest

from src.core.time_utils import utc_now_naive
from src.store.repository import Repository


class TestRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_order(self, db_session):
        order = await Repository.create_order(db_session, "mkt1", "tok1", "BUY", "LIMIT", 0.5, 100)
        await db_session.commit()
        assert order.id is not None
        assert order.market_id == "mkt1"
        assert order.side == "BUY"

    @pytest.mark.asyncio
    async def test_update_order_status(self, db_session):
        order = await Repository.create_order(db_session, "mkt1", "tok1", "BUY", "LIMIT", 0.5, 100)
        await db_session.commit()
        updated = await Repository.update_order_status(db_session, order.id, "FILLED", 100.0)
        assert updated.status == "FILLED"
        assert updated.filled_size == 100.0

    @pytest.mark.asyncio
    async def test_position_upsert(self, db_session):
        pos = await Repository.upsert_position(db_session, "mkt1", "tok1", "LONG", 100, 0.5)
        await db_session.commit()
        assert pos.size == 100
        
        # Update
        pos2 = await Repository.upsert_position(db_session, "mkt1", "tok1", "LONG", 200, 0.55)
        await db_session.commit()
        assert pos2.size == 200
        assert pos2.avg_entry_price == 0.55

    @pytest.mark.asyncio
    async def test_bot_state_singleton(self, db_session):
        state1 = await Repository.get_or_create_bot_state(db_session)
        await db_session.commit()
        state2 = await Repository.get_or_create_bot_state(db_session)
        assert state1.id == state2.id == 1

    @pytest.mark.asyncio
    async def test_kill_switch(self, db_session):
        assert await Repository.get_kill_switch(db_session) is False
        await Repository.set_kill_switch(db_session, enabled=True)
        await db_session.commit()
        assert await Repository.get_kill_switch(db_session) is True

    @pytest.mark.asyncio
    async def test_heartbeat(self, db_session):
        state = await Repository.update_heartbeat(db_session)
        await db_session.commit()
        assert state.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_risk_event(self, db_session):
        event = await Repository.create_risk_event(db_session, "test_event", "Test message", {"key": "val"})
        await db_session.commit()
        assert event.event_type == "test_event"

    @pytest.mark.asyncio
    async def test_orders_last_hour_count(self, db_session):
        await Repository.create_order(db_session, "mkt1", "tok1", "BUY", "LIMIT", 0.5, 10)
        await Repository.create_order(db_session, "mkt1", "tok1", "SELL", "LIMIT", 0.6, 10)
        await db_session.commit()
        count = await Repository.get_orders_last_hour_count(db_session)
        assert count == 2

    @pytest.mark.asyncio
    async def test_daily_pnl(self, db_session):
        await Repository.upsert_position(db_session, "mkt1", "tok1", "LONG", 100, 0.5, realized_pnl=10.5)
        await db_session.commit()
        pnl = await Repository.get_daily_pnl(db_session, utc_now_naive())
        assert pnl == 10.5
