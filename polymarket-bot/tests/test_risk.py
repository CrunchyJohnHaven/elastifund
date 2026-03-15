"""Tests for risk management."""
import pytest
import pytest_asyncio
from datetime import datetime
from src.risk.manager import RiskManager
from src.store.repository import Repository
from src.core.config import Settings


def make_settings(**overrides) -> Settings:
    defaults = {
        "polymarket_private_key": "test",
        "polymarket_funder_address": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "max_position_usd": 100.0,
        "max_daily_drawdown_usd": 50.0,
        "max_orders_per_hour": 10,
        "engine_loop_seconds": 60,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestRiskManager:
    def test_volatility_pause_insufficient_data(self):
        assert RiskManager.check_volatility_pause([0.5]) is False
        assert RiskManager.check_volatility_pause([0.5, 0.51]) is False

    def test_volatility_pause_normal(self):
        # Stable prices should not trigger pause
        prices = [0.50, 0.501, 0.502, 0.501, 0.500, 0.501]
        assert RiskManager.check_volatility_pause(prices) is False

    def test_volatility_pause_high_vol(self):
        # Wild swings should trigger
        prices = [0.50, 0.70, 0.30, 0.80, 0.20]
        assert RiskManager.check_volatility_pause(prices, threshold=1.0) is True

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_trade(self, db_session):
        settings = make_settings()
        rm = RiskManager(settings)
        # Enable kill switch
        await Repository.set_kill_switch(db_session, enabled=True)
        await db_session.commit()
        
        allowed, reason = await rm.check_pre_trade(db_session, "mkt1", "tok1", "buy", 10, 0.5)
        assert allowed is False
        assert "kill switch" in reason.lower()

    @pytest.mark.asyncio
    async def test_position_limit_blocks(self, db_session):
        settings = make_settings(max_position_usd=50.0)
        rm = RiskManager(settings)
        rm.record_price_time("tok1")
        
        # Create a position already at $40
        await Repository.upsert_position(db_session, "mkt1", "tok1", "LONG", 80.0, 0.5)
        await db_session.commit()
        
        # Try to add $20 more (total $60 > $50 limit)
        allowed, reason = await rm.check_pre_trade(db_session, "mkt1", "tok1", "buy", 40, 0.5)
        assert allowed is False
        assert "limit" in reason.lower()

    @pytest.mark.asyncio
    async def test_rate_limit_blocks(self, db_session):
        settings = make_settings(max_orders_per_hour=2)
        rm = RiskManager(settings)
        rm.record_price_time("tok1")
        
        # Create 2 orders
        await Repository.create_order(db_session, "mkt1", "tok1", "BUY", "LIMIT", 0.5, 10)
        await Repository.create_order(db_session, "mkt1", "tok1", "BUY", "LIMIT", 0.5, 10)
        await db_session.commit()
        
        allowed, reason = await rm.check_pre_trade(db_session, "mkt1", "tok1", "buy", 10, 0.5)
        assert allowed is False
        assert "rate" in reason.lower()

    @pytest.mark.asyncio
    async def test_trade_allowed_when_clean(self, db_session):
        settings = make_settings()
        rm = RiskManager(settings)
        rm.record_price_time("tok1")
        
        allowed, reason = await rm.check_pre_trade(db_session, "mkt1", "tok1", "buy", 10, 0.5)
        assert allowed is True
        assert reason == "OK"

    @pytest.mark.asyncio
    async def test_trigger_kill_switch(self, db_session):
        settings = make_settings()
        rm = RiskManager(settings)
        
        await rm.trigger_kill_switch(db_session, "test reason")
        await db_session.commit()
        
        assert await Repository.get_kill_switch(db_session) is True
