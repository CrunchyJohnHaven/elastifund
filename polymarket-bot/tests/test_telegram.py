"""Tests for the Telegram notification client."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.telegram import TelegramNotifier, _escape_html


class TestTelegramNotifier:
    def test_not_configured_no_token(self):
        notifier = TelegramNotifier(bot_token="", chat_id="123")
        assert not notifier.is_configured

    def test_not_configured_no_chat_id(self):
        notifier = TelegramNotifier(bot_token="token123", chat_id="")
        assert not notifier.is_configured

    def test_not_configured_placeholder_values(self):
        notifier = TelegramNotifier(
            bot_token="PASTE_BOT_TOKEN_HERE",
            chat_id="PASTE_CHAT_ID_HERE",
        )
        assert not notifier.is_configured

    def test_configured(self):
        notifier = TelegramNotifier(bot_token="real_token", chat_id="12345")
        assert notifier.is_configured

    @pytest.mark.asyncio
    async def test_send_message_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = await notifier.send_message("test")
        assert result is False

    def test_escape_html(self):
        assert _escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"
        assert _escape_html("normal text") == "normal text"
        assert _escape_html("") == ""

    @pytest.mark.asyncio
    async def test_send_trade_signal_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = await notifier.send_trade_signal(
            market_name="Test Market",
            direction="buy_yes",
            price=0.65,
            size=10.0,
            reasoning="Test reason",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_error_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = await notifier.send_error("Something broke", context="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_daily_summary_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = await notifier.send_daily_summary(
            total_trades=10,
            winning_trades=6,
            total_pnl=15.50,
            current_balance=90.50,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_startup_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = await notifier.send_startup(mode="paper")
        assert result is False
