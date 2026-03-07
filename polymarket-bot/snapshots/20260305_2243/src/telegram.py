"""Telegram notification client for trading alerts."""
import os
from datetime import datetime
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    """Sends trading alerts and summaries via Telegram."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 10.0,
    ):
        """Initialize the Telegram notifier.

        Args:
            bot_token: Telegram bot token (falls back to TELEGRAM_BOT_TOKEN env var)
            chat_id: Telegram chat ID (falls back to TELEGRAM_CHAT_ID env var)
            timeout: HTTP request timeout
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

        if self.is_configured:
            logger.info("telegram_notifier_initialized")
        else:
            logger.warning(
                "telegram_notifier_not_configured",
                has_token=bool(self.bot_token),
                has_chat_id=bool(self.chat_id),
            )

    @property
    def is_configured(self) -> bool:
        """Check if Telegram credentials are set."""
        return bool(
            self.bot_token
            and self.chat_id
            and self.bot_token != "PASTE_BOT_TOKEN_HERE"
            and self.chat_id != "PASTE_CHAT_ID_HERE"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message via Telegram.

        Args:
            text: Message text (supports HTML formatting)
            parse_mode: Parse mode ("HTML" or "Markdown")

        Returns:
            True if sent successfully
        """
        if not self.is_configured:
            logger.debug("telegram_skip_not_configured")
            return False

        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            client = await self._get_client()
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.debug("telegram_message_sent", length=len(text))
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "telegram_send_failed",
                status=e.response.status_code,
                detail=e.response.text[:200],
            )
            return False
        except httpx.RequestError as e:
            logger.error("telegram_request_error", error=str(e))
            return False

    async def send_trade_signal(
        self,
        market_name: str,
        direction: str,
        price: float,
        size: float,
        reasoning: str = "",
    ) -> bool:
        """Send a formatted trade signal alert.

        Args:
            market_name: Market question or name
            direction: "buy_yes", "buy_no", "sell"
            price: Current market price
            size: Position size in USD
            reasoning: Why the trade was signaled
        """
        emoji = {"buy_yes": "🟢", "buy_no": "🔴", "sell": "🟡"}.get(direction, "⚪")
        direction_label = direction.upper().replace("_", " ")

        msg = (
            f"{emoji} <b>Trade Signal</b>\n\n"
            f"<b>Market:</b> {_escape_html(market_name[:100])}\n"
            f"<b>Direction:</b> {direction_label}\n"
            f"<b>Price:</b> ${price:.4f}\n"
            f"<b>Size:</b> ${size:.2f}\n"
        )
        if reasoning:
            msg += f"<b>Reason:</b> {_escape_html(reasoning[:200])}\n"
        msg += f"\n<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"

        return await self.send_message(msg)

    async def send_order_fill(
        self,
        market_name: str,
        side: str,
        fill_price: float,
        size: float,
        pnl: Optional[float] = None,
    ) -> bool:
        """Send an order fill notification."""
        msg = (
            f"✅ <b>Order Filled</b>\n\n"
            f"<b>Market:</b> {_escape_html(market_name[:100])}\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Price:</b> ${fill_price:.4f}\n"
            f"<b>Size:</b> ${size:.2f}\n"
        )
        if pnl is not None:
            emoji = "📈" if pnl >= 0 else "📉"
            msg += f"<b>P&L:</b> {emoji} ${pnl:+.2f}\n"
        msg += f"\n<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"

        return await self.send_message(msg)

    async def send_error(self, error_msg: str, context: str = "") -> bool:
        """Send an error alert."""
        msg = (
            f"🚨 <b>Error Alert</b>\n\n"
            f"<b>Error:</b> {_escape_html(error_msg[:300])}\n"
        )
        if context:
            msg += f"<b>Context:</b> {_escape_html(context[:200])}\n"
        msg += f"\n<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"

        return await self.send_message(msg)

    async def send_daily_summary(
        self,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        current_balance: float,
        top_markets: Optional[list[dict]] = None,
    ) -> bool:
        """Send a daily trading summary."""
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"

        msg = (
            f"📊 <b>Daily Summary</b>\n\n"
            f"<b>Trades:</b> {total_trades}\n"
            f"<b>Win Rate:</b> {win_rate:.0f}% ({winning_trades}/{total_trades})\n"
            f"<b>P&L:</b> {pnl_emoji} ${total_pnl:+.2f}\n"
            f"<b>Balance:</b> ${current_balance:.2f}\n"
        )

        if top_markets:
            msg += "\n<b>Top Markets:</b>\n"
            for m in top_markets[:5]:
                name = _escape_html(m.get("name", "Unknown")[:50])
                m_pnl = m.get("pnl", 0)
                msg += f"  • {name}: ${m_pnl:+.2f}\n"

        msg += f"\n<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"

        return await self.send_message(msg)

    async def send_startup(self, mode: str = "paper") -> bool:
        """Send bot startup notification."""
        msg = (
            f"🤖 <b>Bot Started</b>\n\n"
            f"<b>Mode:</b> {'📝 Paper Trading' if mode == 'paper' else '💰 Live Trading'}\n"
            f"<b>Time:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        )
        return await self.send_message(msg)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
