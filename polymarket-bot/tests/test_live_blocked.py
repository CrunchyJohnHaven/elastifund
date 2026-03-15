"""Tests that live trading is blocked by default."""
import os
import pytest


class TestLiveBlocked:
    def test_live_trading_default_false(self):
        from src.core.config import Settings
        settings = Settings(
            polymarket_private_key="test",
            polymarket_funder_address="test",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        assert settings.live_trading is False

    def test_env_override(self):
        from src.core.config import Settings
        settings = Settings(
            polymarket_private_key="test",
            polymarket_funder_address="test",
            database_url="sqlite+aiosqlite:///:memory:",
            live_trading=True,
        )
        assert settings.live_trading is True
