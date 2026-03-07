# Polymarket Trading Bot - Project Structure

## Directory Layout

```
polymarket-bot/
├── src/
│   ├── __init__.py
│   ├── app/
│   │   └── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py          # Pydantic settings from .env
│   │   ├── logging.py         # Structlog configuration
│   │   └── time_utils.py      # Time utility functions
│   ├── data/
│   │   └── __init__.py        # Data feeds & market data
│   ├── broker/
│   │   └── __init__.py        # Trading order execution
│   ├── risk/
│   │   └── __init__.py        # Risk management
│   ├── strategy/
│   │   └── __init__.py        # Trading strategies
│   ├── engine/
│   │   └── __init__.py        # Main trading engine
│   └── store/
│       ├── __init__.py
│       ├── models.py          # SQLAlchemy ORM models
│       ├── database.py        # Async database setup
│       └── repository.py      # Data access layer
└── tests/
    └── __init__.py
```

## Core Modules Created

### 1. src/core/config.py
**Pydantic BaseSettings for configuration management**

Features:
- Loads all settings from `.env` file
- Polymarket configuration (private key, addresses, URLs)
- Anthropic API key (optional)
- Database URL
- Risk management parameters
- Trading parameters and limits
- Dashboard and Telegram notification settings

Key fields:
- `polymarket_private_key`, `polymarket_funder_address`
- `polymarket_clob_url`, `polymarket_gamma_url`, `polymarket_ws_url`
- `chain_id` (default: 137 for Polygon)
- `signature_type` (default: 1)
- `database_url`
- `live_trading` (bool, default: False)
- `log_level`, `engine_loop_seconds`
- `max_position_usd`, `max_daily_drawdown_usd`, `max_orders_per_hour`
- `slippage_bps`, `fee_bps`
- `dashboard_token`, `telegram_bot_token`, `telegram_chat_id`

### 2. src/core/logging.py
**Structured logging with JSON output**

Features:
- Configures structlog for JSON output
- Includes timestamp, log level, logger name
- `configure_logging()` function for initialization
- `get_logger(name)` function for obtaining logger instances

### 3. src/core/time_utils.py
**Utility functions for time handling**

Functions:
- `utc_now()` - Get current UTC time as timezone-aware datetime
- `ms_to_datetime(ms)` - Convert milliseconds to datetime
- `datetime_to_ms(dt)` - Convert datetime to milliseconds
- `elapsed_seconds(start)` - Calculate elapsed seconds from start time

### 4. src/store/models.py
**SQLAlchemy 2.0 async ORM models**

Models:
- **Order**: market_id, token_id, side, order_type, price, size, filled_size, status, timestamps
- **Fill**: order_id (FK), price, size, fee, timestamp
- **Position**: market_id, token_id, side, size, avg_entry_price, pnl values
- **BotState**: singleton (id=1) for runtime state, kill switch, heartbeat
- **RiskEvent**: event_type, message, JSON data, timestamp

Features:
- Uses `Mapped` and `mapped_column` for type safety
- Proper foreign key relationships with cascade delete
- Server-side timestamp defaults
- Relationship definitions with back_populates

### 5. src/store/database.py
**Async database engine and session management**

DatabaseManager class:
- `initialize()` - Create async engine and session factory
- `init_db()` - Create all database tables
- `get_session()` - Async context manager for sessions
- `close()` - Cleanup database connections

Features:
- Uses SQLAlchemy AsyncSession
- Connection pooling with pre_ping
- Automatic rollback on errors
- Dependency injection support

### 6. src/store/repository.py
**Repository pattern for all database operations**

Repository methods (all async):

**Order Operations:**
- `create_order()` - Create new order
- `update_order_status()` - Update status and filled_size
- `get_open_orders()` - Get all pending/partially filled orders

**Fill Operations:**
- `create_fill()` - Record fill/execution

**Position Operations:**
- `get_position(market_id, token_id)` - Get specific position
- `upsert_position()` - Create or update position
- `get_all_positions()` - Get all open positions

**BotState Operations:**
- `get_or_create_bot_state()` - Singleton state management
- `update_heartbeat()` - Update last heartbeat
- `set_kill_switch()` - Enable/disable kill switch
- `get_kill_switch()` - Check kill switch status

**RiskEvent Operations:**
- `create_risk_event()` - Log risk management events

**Analytics Operations:**
- `get_daily_pnl(date)` - Calculate daily realized PnL
- `get_orders_last_hour_count()` - Count recent orders for rate limiting

## Environment Variables (.env)

Required:
```
POLYMARKET_PRIVATE_KEY=...
POLYMARKET_FUNDER_ADDRESS=...
DATABASE_URL=sqlite+aiosqlite:///bot.db  # or postgresql+asyncpg://...
```

Optional:
```
POLYMARKET_CLOB_URL=https://clob.polymarket.com
POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com
POLYMARKET_WS_URL=wss://ws.polymarket.com
CHAIN_ID=137
SIGNATURE_TYPE=1
ANTHROPIC_API_KEY=...
LIVE_TRADING=false
LOG_LEVEL=INFO
ENGINE_LOOP_SECONDS=60
MAX_POSITION_USD=100.0
MAX_DAILY_DRAWDOWN_USD=50.0
MAX_ORDERS_PER_HOUR=20
SLIPPAGE_BPS=10
FEE_BPS=0
DASHBOARD_TOKEN=change_me
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## Dependencies

### Core Requirements:
- `pydantic` >= 2.0 (settings management)
- `pydantic-settings` (BaseSettings)
- `sqlalchemy` >= 2.0 (ORM)
- `sqlalchemy[asyncio]` (async support)
- `structlog` (structured logging)
- `aiosqlite` (SQLite async driver)

### Optional:
- `asyncpg` (PostgreSQL async driver)
- `anthropic` (Claude API integration)

## Type Hints

All code uses modern Python 3.10+ type hints:
- Full type hints on function parameters and returns
- Use of `Optional`, `Sequence`, `AsyncGenerator`
- Proper Mapped types for SQLAlchemy models
- No `Any` types unless absolutely necessary

## Usage Example

```python
from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.store.database import DatabaseManager
from src.store.repository import Repository

# Initialize
configure_logging()
settings = get_settings()
await DatabaseManager.init_db()

# Use in async context
async with DatabaseManager.get_session() as session:
    order = await Repository.create_order(
        session=session,
        market_id="0x123...",
        token_id="0x456...",
        side="BUY",
        order_type="LIMIT",
        price=0.75,
        size=100.0,
    )
    await session.commit()
    logger.info("Created order", order_id=order.id)
```

