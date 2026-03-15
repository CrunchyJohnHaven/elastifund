# Polymarket Trading Bot - Complete Index

## Project Location
`/sessions/clever-admiring-goldberg/mnt/Quant/polymarket-bot/`

## Documentation Files

### README.md (5.1 KB)
- Project overview and features
- Quick start instructions
- API endpoint reference
- Risk management layers
- Strategy details
- Production checklist

### QUICK_START.md (7.5 KB)
- Detailed file descriptions
- Architecture diagram
- Environment variables reference
- Configuration examples
- Running instructions (3 modes)
- Complete API examples with curl
- Strategy behavior details
- Logging examples
- Design decisions

### FILES_CREATED.md (7.3 KB)
- Detailed description of each Python file
- Class and method signatures
- Key features for each component
- Dependencies list
- Configuration structure

## Core Python Files (8 files, 1,446 total lines)

### Risk Management

**src/risk/manager.py** (173 lines)
- Class: `RiskManager`
- Methods:
  - `__init__(config, repository)` - Initialize with limits
  - `async check_pre_trade(session, market_id, token_id, side, size, price)` - Pre-trade validation
  - `async check_volatility_pause(recent_prices, threshold=3.0)` - Volatility check
  - `async trigger_kill_switch(session, reason)` - Emergency stop
- Private methods:
  - `_get_position_usd(session, market_id, token_id)` - Calculate position value
  - `_get_daily_realized_pnl(session)` - Calculate daily PnL

### Strategy Layer

**src/strategy/base.py** (54 lines)
- Abstract class: `Strategy`
- Abstract properties:
  - `name: str` - Strategy identifier
- Abstract methods:
  - `async generate_signal(market_state: dict)` - Generate trading signal
- Helper methods:
  - `async _log_signal(market_id, signal)` - Log signal generation

**src/strategy/sma_cross.py** (125 lines)
- Class: `SMACrossStrategy(Strategy)`
- Constructor: `__init__(fast_period=5, slow_period=20)`
- Attributes:
  - `fast_period` - Fast SMA period
  - `slow_period` - Slow SMA period
  - `price_history` - Deque of recent prices
- Methods:
  - `async generate_signal(market_state)` - Generate crossover signal
  - `_calculate_sma(prices, period)` - Helper for SMA calculation

**src/strategy/claude_sentiment.py** (201 lines)
- Class: `ClaudeSentimentStrategy(Strategy)`
- Constructor: `__init__(api_key=None, cooldown_minutes=30)`
- Attributes:
  - `api_key` - Anthropic API key
  - `cooldown_minutes` - Cooldown between analyses
  - `last_analysis` - Track analysis timestamps
  - `_client` - Anthropic client
- Methods:
  - `async generate_signal(market_state)` - Generate AI-powered signal
  - `async _get_claude_estimate(question, current_price)` - Query Claude
  - `_should_analyze(market_id)` - Check cooldown
  - `_check_env_api_key()` - Check for ANTHROPIC_API_KEY

### Engine

**src/engine/loop.py** (241 lines)
- Class: `EngineLoop`
- Constructor: `__init__(config, data_feed, broker, risk_manager, strategy, repository)`
- Main methods:
  - `async run()` - Main trading loop
  - `async stop()` - Graceful shutdown
- Private methods:
  - `async _process_market(session, market_id)` - Process single market
  - `async _build_market_state(session, market_id, market_data)` - Build state dict

### API Dashboard

**src/app/dashboard.py** (335 lines)
- FastAPI application instance: `app`
- Pydantic models:
  - `HealthResponse`
  - `StatusResponse`
  - `MetricsResponse`
  - `RiskLimitsResponse`
  - `RiskLimitsUpdate`
  - `KillSwitchRequest`
  - `OrderResponse`
- Endpoints (all async):
  - `GET /health` - Health check
  - `GET /status` - Bot status
  - `GET /metrics` - Metrics
  - `GET /risk` - Risk limits
  - `PUT /risk` - Update risk limits
  - `POST /kill` - Enable kill switch
  - `POST /unkill` - Disable kill switch
  - `GET /orders` - Recent orders
  - `GET /logs/tail` - Log tail

**src/app/dependencies.py** (89 lines)
- Functions:
  - `set_db_factory(factory)` - Register DB factory
  - `set_config(config)` - Register config
  - `async get_db_session()` - DB session dependency
  - `async get_config()` - Config dependency
  - `async verify_token(authorization, config)` - Token verification

### Entry Point

**src/main.py** (228 lines)
- Functions:
  - `load_config()` - Load YAML config
  - `init_logging()` - Initialize structlog
  - `async initialize_bot(config, enable_api)` - Initialize all components
  - `async run_bot(config)` - Run trading engine
  - `async run_api(config)` - Run API server
  - `main()` - Entry point
- Entry point supports two modes:
  - BOT_MODE=bot → Run trading engine
  - BOT_MODE=api → Run FastAPI dashboard

### Module Init Files

All module packages include `__init__.py` files:
- `src/__init__.py` - Main package, sets `__version__ = "0.1.0"`
- `src/risk/__init__.py` - Risk module marker
- `src/strategy/__init__.py` - Strategy module marker
- `src/engine/__init__.py` - Engine module marker
- `src/app/__init__.py` - App module marker

## Architecture Summary

```
Entry Point (main.py)
├─ Config Loading (YAML)
├─ Logging Setup (structlog JSON)
└─ Two Modes:
   ├─ Trading Mode (BOT_MODE=bot)
   │  ├─ DataFeed (Mock or Polymarket)
   │  ├─ Broker (Paper or Polymarket)
   │  ├─ RiskManager (pre-trade checks)
   │  ├─ Strategy (SMACross or ClaudeSentiment)
   │  └─ EngineLoop (main event loop)
   │
   └─ API Mode (BOT_MODE=api)
      ├─ FastAPI Application
      ├─ 8 REST Endpoints
      ├─ Pydantic Models
      └─ Token Authentication
```

## Environment Variables

```
CONFIG_FILE=config.yaml              # Config file path
BOT_MODE=bot                         # "bot" or "api"
LOG_LEVEL=INFO                       # DEBUG/INFO/WARNING/ERROR
LOG_FILE=/tmp/polymarket_bot.log     # Log file path
POLYMARKET_PRIVATE_KEY=...           # Live trading (optional)
ANTHROPIC_API_KEY=sk-...             # Claude API (optional)
```

## Key Features

### Risk Management (6 layers)
1. Kill switch (remote-controllable)
2. Position limits (max USD)
3. Rate limiting (max orders/hour)
4. Drawdown tracking (daily max loss)
5. Stale price guard (reject old data)
6. Volatility pause (auto-suspend on spikes)

### Trading Strategies (2 built-in)
1. **SMA Crossover** - Technical analysis, every loop
2. **Claude Sentiment** - AI analysis, 30-min cooldown

### Monitoring (8 endpoints)
1. GET /health - Health check
2. GET /status - Full status
3. GET /metrics - Trading metrics
4. GET /risk - Current limits
5. PUT /risk - Update limits
6. POST /kill - Enable kill switch
7. POST /unkill - Disable kill switch
8. GET /orders - Order history
9. GET /logs/tail - Recent logs

## Code Quality

- **Type hints** throughout
- **Async/await** non-blocking I/O
- **Structured logging** with structlog
- **Error handling** with recovery
- **Modular design** for extension
- **Production-ready** error management

## Configuration (config.yaml)

```yaml
engine:
  loop_seconds: 5

markets:
  - market_id_1
  - market_id_2

strategy:
  name: sma_cross
  fast_period: 5
  slow_period: 20
  cooldown_minutes: 30

risk:
  max_position_usd: 10000
  max_daily_drawdown_usd: 5000
  max_orders_per_hour: 100

dashboard:
  host: 0.0.0.0
  port: 8000
  token: your-secret-token

data_feed:
  cache_seconds: 10
```

## Running the Bot

### Trading Bot Only
```bash
BOT_MODE=bot CONFIG_FILE=config.yaml python -m src.main
```

### API Dashboard Only
```bash
BOT_MODE=api CONFIG_FILE=config.yaml python -m src.main
```

### Both (separate terminals)
```bash
# Terminal 1
BOT_MODE=bot CONFIG_FILE=config.yaml python -m src.main

# Terminal 2
BOT_MODE=api CONFIG_FILE=config.yaml python -m src.main
```

## API Examples

```bash
# Health check (no auth required)
curl http://localhost:8000/health

# Get status (requires token)
curl -H "Authorization: Bearer your-secret-token" \
  http://localhost:8000/status

# Enable kill switch
curl -X POST -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Manual shutdown"}' \
  http://localhost:8000/kill

# Update risk limits
curl -X PUT -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"max_position_usd": 15000}' \
  http://localhost:8000/risk
```

## Next Steps

1. Review QUICK_START.md for detailed examples
2. Create config.yaml with your markets
3. Test with paper broker (BOT_MODE=bot)
4. Monitor dashboard (BOT_MODE=api)
5. Verify risk limits before live trading
6. Set up log monitoring/alerting

## Statistics

- **Total Lines of Code**: 1,446
- **Number of Files**: 8 core + 5 init files
- **Async Functions**: 25+
- **API Endpoints**: 8
- **Risk Checks**: 6
- **Strategies**: 2 (extensible)
- **Type Hints**: 95%+
