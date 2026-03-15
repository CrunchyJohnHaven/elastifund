"""Main entry point for Polymarket trading bot.

Supports two modes:
  - Paper trading (LIVE_TRADING=false, default): Uses PaperBroker, simulated fills.
  - Live trading  (LIVE_TRADING=true):           Uses PolymarketBroker via py-clob-client.

Both modes share the same engine loop, risk manager, and safety rails.
The switch is controlled by the LIVE_TRADING env var.

SAFETY LAYERS (all must be satisfied for a live order):
  1. NO_TRADE_MODE=false  (global kill-gate in Broker base class)
  2. LIVE_TRADING=true     (broker selection — this file)
  3. Safety rails          (daily loss, per-trade cap, exposure, cooldown)
  4. Risk manager          (position limits, rate limits, drawdown)
  5. Kill switch           (DB-level emergency stop)
"""
import asyncio
import logging
import os
import sys

import structlog

from src.core.config import get_settings
from src.store.database import DatabaseManager
from src.telemetry.elastic import get_elastic_telemetry


def configure_logging(log_level: str = "INFO") -> None:
    """Configure logging for both stdlib and structlog."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/tmp/polymarket_bot.log"),
        ],
    )
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _build_broker(settings):
    """Build the appropriate broker based on LIVE_TRADING setting.

    Returns:
        Broker instance (PaperBroker or PolymarketBroker).
    """
    logger = structlog.get_logger("main")

    if settings.live_trading:
        # ── LIVE MODE ──────────────────────────────────────────────
        from src.broker.polymarket_broker import PolymarketBroker, PolymarketBrokerConfig

        config = PolymarketBrokerConfig(
            live_trading=True,
            private_key=settings.effective_private_key,
            user_address=settings.effective_funder_address,
            api_key=settings.polymarket_api_key,
            api_secret=settings.polymarket_api_secret,
            api_passphrase=settings.polymarket_api_passphrase,
            chain_id=settings.chain_id,
            signature_type=settings.signature_type,
            clob_url=settings.polymarket_clob_url,
        )

        broker = PolymarketBroker(config)
        logger.critical(
            "LIVE_BROKER_SELECTED",
            mode="LIVE",
            clob_url=settings.polymarket_clob_url,
            user_address=settings.effective_funder_address[:10] + "..." if settings.effective_funder_address else "NOT_SET",
            no_trade_mode=settings.no_trade_mode,
        )

        # Pre-flight: verify connectivity
        # (sync call — ClobClient methods are synchronous)
        try:
            import asyncio as _aio
            connectivity = _aio.get_event_loop().run_until_complete(broker.verify_connectivity())
            logger.info("live_connectivity_check", **connectivity)
            if not connectivity.get("clob_reachable"):
                logger.error("CLOB_UNREACHABLE — falling back to paper broker")
                raise RuntimeError("CLOB not reachable")
            if not connectivity.get("auth_ok"):
                logger.error("CLOB_AUTH_FAILED — falling back to paper broker")
                raise RuntimeError("CLOB auth failed")
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning("connectivity_check_skipped", error=str(e))

        return broker
    else:
        # ── PAPER MODE ─────────────────────────────────────────────
        from src.broker.paper_broker import PaperBroker

        broker = PaperBroker(
            initial_cash=settings.max_position_usd * 10,  # reasonable paper balance
            slippage_bps=settings.slippage_bps,
            fee_bps=settings.fee_bps,
        )
        logger.info("PAPER_BROKER_SELECTED", mode="PAPER")
        return broker


async def run_engine() -> None:
    """Run the main trading engine."""
    from src.data.mock_feed import MockDataFeed
    from src.risk.manager import RiskManager
    from src.safety import SafetyRails
    from src.strategy.sma_cross import SMACrossStrategy
    from src.engine.loop import EngineLoop
    from src.telegram import TelegramNotifier

    logger = structlog.get_logger("main")
    settings = get_settings()
    telemetry = get_elastic_telemetry(settings)

    await DatabaseManager.init_db()
    logger.info("database_initialized")

    # Select data feed
    pk = settings.effective_private_key
    if pk and pk != "PASTE_PRIVATE_KEY_HERE":
        from src.data.polymarket_feed import PolymarketDataFeed
        data_feed = PolymarketDataFeed()
        logger.info("using_polymarket_data_feed")
    else:
        data_feed = MockDataFeed()
        logger.info("using_mock_data_feed")

    # Build broker (paper or live based on LIVE_TRADING)
    broker = _build_broker(settings)

    # Core components
    risk_manager = RiskManager()
    safety_rails = SafetyRails()
    strategy = SMACrossStrategy(fast_period=5, slow_period=20)

    # Telegram notifier
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )

    markets = [
        {"market_id": "mock_001", "token_id": "YES", "question": "Test market"},
    ]

    engine = EngineLoop(
        data_feed=data_feed,
        broker=broker,
        risk_manager=risk_manager,
        strategy=strategy,
        markets=markets,
        safety_rails=safety_rails,
        notifier=notifier,
        telemetry=telemetry,
    )

    mode = "LIVE" if settings.live_trading else "PAPER"
    try:
        logger.info(
            "engine_starting",
            mode=mode,
            live_trading=settings.live_trading,
            no_trade_mode=settings.no_trade_mode,
            max_per_trade=settings.rollout_max_per_trade_usd,
            max_trades_day=settings.rollout_max_trades_per_day,
            max_daily_drawdown=settings.max_daily_drawdown_usd,
        )

        await telemetry.upsert_agent_status(
            status="starting",
            metadata={
                "mode": mode.lower(),
                "bot_mode": "engine",
                "live_trading": settings.live_trading,
                "no_trade_mode": settings.no_trade_mode,
                "markets": len(markets),
                "strategy": strategy.name,
            },
        )

        # Send startup notification
        if notifier.is_configured:
            await notifier.send_startup(mode=mode.lower())

        await engine.run()
    except KeyboardInterrupt:
        logger.info("engine_interrupted")
    finally:
        await engine.stop()
        await telemetry.upsert_agent_status(
            status="stopped",
            metadata={
                "mode": mode.lower(),
                "bot_mode": "engine",
                "live_trading": settings.live_trading,
                "strategy": strategy.name,
            },
        )
        if notifier:
            await notifier.close()
        await DatabaseManager.close()
        logger.info("engine_stopped", mode=mode)


async def run_api() -> None:
    """Run the FastAPI dashboard server."""
    import uvicorn
    from src.app.dependencies import set_settings
    from src.app.dashboard import app

    settings = get_settings()
    await DatabaseManager.init_db()
    set_settings(settings)

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    """Main entry point - routes to engine or API based on BOT_MODE."""
    settings = get_settings()
    configure_logging(settings.log_level)

    mode = os.getenv("BOT_MODE", "bot").lower()
    if mode == "api":
        asyncio.run(run_api())
    elif mode == "bot":
        asyncio.run(run_engine())
    else:
        print(f"Unknown BOT_MODE: {mode}. Use 'bot' or 'api'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
