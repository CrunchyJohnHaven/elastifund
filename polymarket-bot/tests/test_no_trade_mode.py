"""Tests for the NO_TRADE_MODE global guardrail.

Verifies that:
1. NO_TRADE_MODE defaults to True (ON)
2. All broker types block order placement when ON
3. The guard fails closed (config error -> blocked)
4. Orders succeed only when explicitly disabled

Note: conftest.py sets NO_TRADE_MODE=false so other tests can place orders.
This test file manages the env var explicitly and restores it in teardown.
"""
import os
import pytest

from src.broker.base import NoTradeModeError, _assert_trading_allowed
from src.broker.paper_broker import PaperBroker
from src.broker.base import OrderSide


# ---------------------------------------------------------------------------
# Fixture to save/restore NO_TRADE_MODE around each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_no_trade_env():
    """Save and restore NO_TRADE_MODE env var around each test."""
    original = os.environ.get("NO_TRADE_MODE")
    yield
    # Restore original value
    if original is None:
        os.environ.pop("NO_TRADE_MODE", None)
    else:
        os.environ["NO_TRADE_MODE"] = original


# ---------------------------------------------------------------------------
# Tests: Config defaults
# ---------------------------------------------------------------------------

class TestNoTradeModeConfig:
    def test_default_is_true(self):
        """NO_TRADE_MODE must default to True (safe default) when env var is unset."""
        os.environ.pop("NO_TRADE_MODE", None)
        from src.core.config import Settings
        settings = Settings(
            polymarket_private_key="test",
            polymarket_funder_address="test",
            database_url="sqlite+aiosqlite:///:memory:",
            _env_file=None,  # Don't read any .env file
        )
        assert settings.no_trade_mode is True

    def test_explicit_false(self):
        """NO_TRADE_MODE can be explicitly disabled."""
        from src.core.config import Settings
        settings = Settings(
            polymarket_private_key="test",
            polymarket_funder_address="test",
            database_url="sqlite+aiosqlite:///:memory:",
            no_trade_mode=False,
        )
        assert settings.no_trade_mode is False


# ---------------------------------------------------------------------------
# Tests: Guard function
# ---------------------------------------------------------------------------

class TestAssertTradingAllowed:
    def test_blocks_when_on(self):
        """_assert_trading_allowed raises when NO_TRADE_MODE=true."""
        os.environ["NO_TRADE_MODE"] = "true"
        with pytest.raises(NoTradeModeError, match="NO_TRADE_MODE is ON"):
            _assert_trading_allowed()

    def test_allows_when_off(self):
        """_assert_trading_allowed does NOT raise when NO_TRADE_MODE=false."""
        os.environ["NO_TRADE_MODE"] = "false"
        _assert_trading_allowed()  # should not raise

    def test_default_blocks(self):
        """If NO_TRADE_MODE is unset, default (True) blocks trading."""
        os.environ.pop("NO_TRADE_MODE", None)
        with pytest.raises(NoTradeModeError):
            _assert_trading_allowed()


# ---------------------------------------------------------------------------
# Tests: PaperBroker blocked by NO_TRADE_MODE
# ---------------------------------------------------------------------------

class TestPaperBrokerNoTradeMode:
    @pytest.fixture
    def broker(self):
        return PaperBroker(initial_cash=1000.0)

    @pytest.mark.asyncio
    async def test_place_order_blocked(self, broker):
        """PaperBroker.place_order is blocked when NO_TRADE_MODE=true."""
        os.environ["NO_TRADE_MODE"] = "true"
        with pytest.raises(NoTradeModeError):
            await broker.place_order("mkt1", "YES", OrderSide.BUY, 0.5, 10.0)

    @pytest.mark.asyncio
    async def test_place_market_order_blocked(self, broker):
        """PaperBroker.place_market_order is blocked when NO_TRADE_MODE=true."""
        os.environ["NO_TRADE_MODE"] = "true"
        with pytest.raises(NoTradeModeError):
            await broker.place_market_order("mkt1", "YES", OrderSide.BUY, 100.0)

    @pytest.mark.asyncio
    async def test_place_order_allowed_when_off(self, broker):
        """PaperBroker.place_order succeeds when NO_TRADE_MODE=false."""
        os.environ["NO_TRADE_MODE"] = "false"
        order = await broker.place_order("mkt1", "YES", OrderSide.BUY, 0.5, 10.0)
        assert order.id  # order was created
        assert order.market_id == "mkt1"

    @pytest.mark.asyncio
    async def test_no_cash_change_when_blocked(self, broker):
        """Cash balance must not change when an order is blocked."""
        initial_cash = broker.get_cash()
        os.environ["NO_TRADE_MODE"] = "true"
        with pytest.raises(NoTradeModeError):
            await broker.place_order("mkt1", "YES", OrderSide.BUY, 0.5, 10.0)
        assert broker.get_cash() == initial_cash


# ---------------------------------------------------------------------------
# Tests: PolymarketBroker blocked by NO_TRADE_MODE
# ---------------------------------------------------------------------------

class TestPolymarketBrokerNoTradeMode:
    @pytest.mark.asyncio
    async def test_place_order_blocked_even_with_live_trading_true(self):
        """Even if live_trading=True, NO_TRADE_MODE still blocks orders."""
        from src.broker.polymarket_broker import PolymarketBroker, PolymarketBrokerConfig

        config = PolymarketBrokerConfig(live_trading=True)
        try:
            broker = PolymarketBroker(config)
        except RuntimeError:
            # py_clob_client not installed — use blocked config
            config_blocked = PolymarketBrokerConfig(live_trading=False)
            broker = PolymarketBroker(config_blocked)

        os.environ["NO_TRADE_MODE"] = "true"
        with pytest.raises(NoTradeModeError):
            await broker.place_order("mkt1", "YES", OrderSide.BUY, 0.5, 10.0)


# ---------------------------------------------------------------------------
# Tests: Fail-closed behavior
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_broken_config_blocks_trading(self, monkeypatch):
        """If get_settings() throws, trading is blocked (fail-closed)."""
        import src.broker.base as base_mod

        def broken_settings():
            raise RuntimeError("config is broken")

        monkeypatch.setattr(base_mod, "get_settings", broken_settings)
        with pytest.raises(NoTradeModeError):
            _assert_trading_allowed()
