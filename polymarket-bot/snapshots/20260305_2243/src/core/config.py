"""Configuration management for Polymarket trading bot."""
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # Polymarket configuration
    polymarket_private_key: str = Field(
        default="", description="Private key for Polymarket (no 0x prefix)"
    )
    polymarket_pk: str = Field(
        default="", description="Alias for private key (POLYMARKET_PK env var)"
    )
    polymarket_funder_address: str = Field(
        default="", description="Funder address for Polymarket"
    )
    polymarket_funder: str = Field(
        default="", description="Alias for funder address (POLYMARKET_FUNDER env var)"
    )
    polymarket_api_key: str = Field(
        default="", description="Polymarket CLOB API key (L2 / builder key)"
    )
    polymarket_api_secret: str = Field(
        default="", description="Polymarket CLOB API secret"
    )
    polymarket_api_passphrase: str = Field(
        default="", description="Polymarket CLOB API passphrase"
    )
    polymarket_clob_url: str = Field(
        default="https://clob.polymarket.com",
        description="Polymarket CLOB API URL",
    )
    polymarket_gamma_url: str = Field(
        default="https://gamma-api.polymarket.com",
        description="Polymarket Gamma API URL",
    )
    polymarket_ws_url: str = Field(
        default="wss://ws.polymarket.com",
        description="Polymarket WebSocket URL",
    )
    chain_id: int = Field(default=137, description="Blockchain chain ID (Polygon)")
    signature_type: int = Field(default=2, description="Signature type for orders")
    polygon_rpc_url: str = Field(
        default="", description="Polygon RPC URL (Alchemy)"
    )

    # Anthropic configuration
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic API key for Claude integration",
    )

    # Database configuration
    database_url: str = Field(..., description="Database connection URL")

    # Trading configuration
    live_trading: bool = Field(
        default=False,
        description="Enable live trading mode",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    engine_loop_seconds: int = Field(
        default=60,
        description="Engine loop interval in seconds",
    )

    # Risk management
    max_position_usd: float = Field(
        default=100.0,
        description="Maximum position size in USD",
    )
    max_daily_drawdown_usd: float = Field(
        default=10.0,
        description="Maximum daily drawdown in USD (safety rail: $10 initial)",
    )
    max_orders_per_hour: int = Field(
        default=20,
        description="Maximum number of orders per hour",
    )

    # Safety rails — per-trade and exposure
    max_per_trade_usd: float = Field(
        default=5.0,
        description="Hard cap per individual trade in USD",
    )
    max_exposure_pct: float = Field(
        default=0.80,
        description="Maximum exposure as fraction of bankroll (keep 20% cash reserve)",
    )
    cooldown_consecutive_losses: int = Field(
        default=3,
        description="Number of consecutive losses before cooldown triggers",
    )
    cooldown_seconds: int = Field(
        default=3600,
        description="Cooldown duration in seconds after consecutive losses",
    )
    order_timeout_seconds: int = Field(
        default=60,
        description="Cancel unfilled limit orders after this many seconds",
    )

    # Gradual rollout tiers (manual escalation via config change)
    rollout_max_per_trade_usd: float = Field(
        default=1.0,
        description="Rollout: max USD per trade (Week1=$1, Week2=$2, Week3=$5)",
    )
    rollout_max_trades_per_day: int = Field(
        default=3,
        description="Rollout: max trades per day (Week1=3, Week2=5, Week3=unlimited=-1)",
    )
    rollout_kelly_active: bool = Field(
        default=False,
        description="Rollout: enable Kelly sizing (only in Week3+)",
    )

    # Trading parameters
    slippage_bps: int = Field(
        default=10,
        description="Slippage tolerance in basis points",
    )
    fee_bps: int = Field(
        default=0,
        description="Trading fee in basis points",
    )

    # Dashboard and notifications
    dashboard_token: str = Field(
        default="change_me",
        description="Dashboard authentication token",
    )
    telegram_bot_token: str = Field(
        default="",
        description="Telegram bot token for notifications",
    )
    telegram_chat_id: str = Field(
        default="",
        description="Telegram chat ID for notifications",
    )

    # NO-TRADE MODE: global kill-gate. When True (default), ALL order placement
    # is blocked at the Broker base class level, regardless of broker type.
    # This is the outermost safety layer. Must be explicitly set to False AND
    # live_trading must be True before any real orders can be placed.
    no_trade_mode: bool = Field(
        default=True,
        description="Global no-trade guardrail. Blocks ALL order placement when True (default ON).",
    )

    # Paper trading
    paper_trading: bool = Field(default=True, description="Enable paper trading mode")
    check_interval_seconds: int = Field(
        default=300, description="Interval between market scans"
    )
    max_position_size_usd: float = Field(
        default=25.0, description="Max position size in USD"
    )
    kelly_fraction: float = Field(default=0.5, description="Kelly fraction for sizing")

    # Claude model
    claude_model: str = Field(
        default="claude-haiku-4-5-20241022", description="Claude model for analysis"
    )

    # News sentiment enrichment (NewsData.io)
    newsdata_api_key: str = Field(
        default="", description="NewsData.io API key for news sentiment"
    )
    news_enrichment_enabled: bool = Field(
        default=True, description="Enable news headline enrichment for Claude analysis"
    )

    # NOAA weather settings
    noaa_cities: str = Field(
        default="Chicago,NYC,Dallas,Miami,Seattle,Atlanta",
        description="Comma-separated cities for NOAA weather",
    )
    noaa_buy_below: float = Field(default=0.15, description="Buy below this price")
    noaa_sell_above: float = Field(default=0.45, description="Sell above this price")
    noaa_max_per_position: float = Field(
        default=2.00, description="Max USD per weather position"
    )
    noaa_scan_interval_seconds: int = Field(
        default=120, description="NOAA scan interval"
    )

    model_config = {"env_file": ".env", "case_sensitive": False}

    @property
    def effective_private_key(self) -> str:
        """Get the effective private key (supports both env var names)."""
        pk = self.polymarket_private_key or self.polymarket_pk
        return pk.removeprefix("0x") if pk else ""

    @property
    def effective_funder_address(self) -> str:
        """Get the effective funder address (supports both env var names)."""
        return self.polymarket_funder_address or self.polymarket_funder

    @property
    def has_api_credentials(self) -> bool:
        """Check if CLOB API credentials are configured."""
        return bool(
            self.polymarket_api_key
            and self.polymarket_api_secret
            and self.polymarket_api_passphrase
        )


def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
