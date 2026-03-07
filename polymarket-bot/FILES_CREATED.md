# Polymarket Trading Bot - Files Created

## Overview
Complete production-quality Python source files for a Polymarket prediction market trading bot with risk management, multiple trading strategies, and a FastAPI dashboard.

## File Structure

### src/risk/manager.py
**RiskManager class** - Manages all pre-trade risk checks:
- `__init__(config, repository)` - Initialize with config and DB access
- `async check_pre_trade(session, market_id, token_id, side, size, price)` - Check:
  - Kill switch status
  - Max position USD limits
  - Max orders per hour rate limiting
  - Stale price guards (5x engine loop seconds)
  - Daily drawdown limits
  - Returns (allowed: bool, reason: str)
- `async check_volatility_pause(recent_prices, threshold=3.0)` - Pause if std dev of returns exceeds threshold
- `async trigger_kill_switch(session, reason)` - Emergency stop mechanism

### src/strategy/base.py
**Abstract Strategy base class** - Define interface for all strategies:
- `name: str` property (abstract)
- `async generate_signal(market_state: dict)` (abstract)
  - Input: market_state with market_id, token_id, question, current_price, midpoint, orderbook_depth, positions, price_history
  - Output: dict with action, size, confidence (0-1), reason
- `async _log_signal(market_id, signal)` - Helper for logging

### src/strategy/sma_cross.py
**SMACrossStrategy** - Simple Moving Average Crossover strategy:
- `__init__(fast_period=5, slow_period=20)` - Configure SMA periods
- Tracks price history in deque (maxlen = slow_period + 10)
- Signal logic:
  - Fast SMA > Slow SMA → buy_yes
  - Fast SMA < Slow SMA → buy_no
  - Equal → hold
- Position sizing: Half-Kelly criterion based on price gap
- Confidence: Scaled by % gap between SMAs

### src/strategy/claude_sentiment.py
**ClaudeSentimentStrategy** - AI-powered sentiment analysis:
- `__init__(api_key=None, cooldown_minutes=30)` - Optional API key, cooldown between re-analyses
- Uses Claude Haiku (claude-3-5-haiku-20241022) for market question analysis
- Sends question + current price to Claude, asks for calibrated probability
- Compares Claude estimate vs market price for mispricing signals
- Gracefully handles missing API key (returns hold)
- Cooldown prevents over-analyzing same market
- Half-Kelly sizing based on mispricing magnitude

### src/engine/loop.py
**EngineLoop class** - Main trading engine orchestrator:
- `__init__(config, data_feed, broker, risk_manager, strategy, repository)`
- `async run()` - Main loop that:
  1. Updates heartbeat in DB
  2. Checks kill switch
  3. Processes each configured market
  4. Generates strategy signals
  5. Runs pre-trade risk checks
  6. Places orders via broker
  7. Logs all decisions
  8. Sleeps for engine_loop_seconds
  9. Catches exceptions and continues
- `async stop()` - Graceful shutdown (sets running=False)
- `async _process_market(session, market_id)` - Process single market
- `async _build_market_state(session, market_id, market_data)` - Build state dict for strategy

### src/app/dashboard.py
**FastAPI Dashboard API** - REST endpoints for monitoring and control:
- GET `/health` → HealthResponse (status, version, uptime_seconds)
- GET `/status` → StatusResponse (positions, PnL, heartbeat, kill switch state, errors)
- GET `/metrics` → MetricsResponse (order count, fills, positions, uptime, errors)
- GET `/risk` → RiskLimitsResponse (max_position_usd, max_daily_drawdown_usd, max_orders_per_hour)
- PUT `/risk` → Update risk limits
- POST `/kill` → Enable kill switch with reason
- POST `/unkill` → Disable kill switch
- GET `/orders?limit=50` → Recent orders list
- GET `/logs/tail?n=100` → Last N log lines from structured log file
- Token authentication via Authorization header (Bearer token)
- All responses use Pydantic models for validation

### src/app/dependencies.py
**FastAPI Dependency Injection** - Shared dependencies:
- `set_db_factory(factory)` - Initialize DB session factory (called by main.py)
- `set_config(config)` - Initialize config (called by main.py)
- `async get_db_session()` - Dependency for DB access
- `async get_config()` - Dependency for config access
- `async verify_token(authorization, config)` - Token verification middleware
  - Expects: `Authorization: Bearer <token>`
  - Checks against config.dashboard.token
  - Returns True if valid

### src/main.py
**Main Entry Point** - Bot initialization and execution:
- `load_config()` - Load YAML config from CONFIG_FILE env var
- `init_logging()` - Initialize structlog with JSON output to file
- `async initialize_bot(config, enable_api)` - Create all components:
  - Database repository
  - Data feed (Polymarket or Mock based on POLYMARKET_PRIVATE_KEY)
  - Broker (Polymarket or Paper based on POLYMARKET_PRIVATE_KEY)
  - Risk manager
  - Strategy (sma_cross or claude_sentiment from config)
  - Engine loop
  - Optional FastAPI dashboard
- `async run_bot(config)` - Run trading engine loop
- `async run_api(config)` - Run API dashboard with uvicorn
- `main()` - Entry point that:
  - Initializes logging
  - Loads config
  - Runs in bot or api mode based on BOT_MODE env var
- Environment variables:
  - `CONFIG_FILE` - Path to config.yaml (default: config.yaml)
  - `BOT_MODE` - "bot" or "api" (default: bot)
  - `LOG_LEVEL` - DEBUG/INFO/WARNING/ERROR (default: INFO)
  - `LOG_FILE` - Log file path (default: /tmp/polymarket_bot.log)
  - `POLYMARKET_PRIVATE_KEY` - Optional key for live trading

### Module Init Files
- `src/__init__.py` - Package marker, sets __version__
- `src/risk/__init__.py` - Risk module marker
- `src/strategy/__init__.py` - Strategy module marker
- `src/engine/__init__.py` - Engine module marker
- `src/app/__init__.py` - App module marker

## Key Features

### Production Quality
- Full async/await support
- Type hints throughout
- Structured logging with structlog
- Error handling and recovery
- Graceful shutdown mechanisms

### Risk Management
- Multi-layer pre-trade checks
- Position limits per market
- Rate limiting on order frequency
- Daily drawdown tracking
- Stale price protection
- Volatility pause functionality
- Emergency kill switch

### Trading Strategies
- SMA Crossover (technical analysis)
- Claude Sentiment (AI-powered fundamental analysis)
- Extensible base class for new strategies
- Half-Kelly position sizing
- Configurable parameters

### Monitoring & Control
- RESTful API dashboard
- Real-time status monitoring
- Risk limit adjustments
- Kill switch control
- Order history
- Log file access
- Token-based authentication

## Dependencies
- fastapi, uvicorn - API framework
- structlog - Structured logging
- pydantic - Data validation
- anthropic - Claude API (for sentiment strategy)
- sqlalchemy - Database ORM (for repository)
- yaml - Config parsing

## Configuration
Uses YAML config file with sections:
- `engine.loop_seconds` - Engine loop interval
- `markets` - List of markets to trade
- `strategy.name` - Strategy type (sma_cross, claude_sentiment)
- `strategy.fast_period`, `strategy.slow_period` - SMA params
- `strategy.cooldown_minutes` - Sentiment strategy cooldown
- `risk.max_position_usd` - Max position limit
- `risk.max_daily_drawdown_usd` - Daily loss limit
- `risk.max_orders_per_hour` - Rate limit
- `dashboard.host`, `dashboard.port` - API listen address
- `dashboard.token` - Bearer token for API auth
- `data_feed.cache_seconds` - Price cache duration

