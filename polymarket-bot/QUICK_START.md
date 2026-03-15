# Polymarket Trading Bot - Quick Start Guide

## Files Created

### Core Trading Components (1,446 lines total)

1. **src/risk/manager.py** (173 lines)
   - RiskManager class with multi-layer pre-trade checks
   - Kill switch, position limits, rate limiting, drawdown tracking
   - Stale price protection, volatility pause

2. **src/strategy/base.py** (54 lines)
   - Abstract Strategy base class
   - Common interface: name property, generate_signal() method
   - Built-in logging helper

3. **src/strategy/sma_cross.py** (125 lines)
   - SMACrossStrategy: Simple Moving Average Crossover
   - Configurable fast/slow periods (default 5/20)
   - Half-Kelly position sizing
   - Price history tracking with deque

4. **src/strategy/claude_sentiment.py** (201 lines)
   - ClaudeSentimentStrategy: AI-powered market analysis
   - Uses Claude Haiku for probability estimation
   - Compares Claude estimate vs market price
   - Built-in cooldown and graceful API degradation

5. **src/engine/loop.py** (241 lines)
   - EngineLoop: Main trading loop orchestrator
   - Coordinates data feeds, strategy, risk checks, broker
   - Heartbeat tracking, error recovery
   - Async/await throughout

6. **src/app/dashboard.py** (335 lines)
   - FastAPI REST API with 8 endpoints
   - /health, /status, /metrics, /risk, /kill, /unkill, /orders, /logs/tail
   - Token-based authentication
   - Pydantic models for request/response validation

7. **src/app/dependencies.py** (89 lines)
   - FastAPI dependency injection setup
   - DB session factory, config, token verification
   - Authorization header parsing (Bearer token)

8. **src/main.py** (228 lines)
   - Entry point for entire application
   - Config loading from YAML
   - Component initialization
   - Bot mode or API mode execution
   - Structured logging setup

## Architecture Overview

```
main.py (entry)
    ├── Config loading (YAML)
    ├── Logging initialization (structlog)
    └── Two modes:
        ├── BOT_MODE=bot → EngineLoop
        │   ├── DataFeed (Mock or Polymarket)
        │   ├── Broker (Paper or Polymarket)
        │   ├── RiskManager
        │   └── Strategy (SMA or Claude)
        └── BOT_MODE=api → FastAPI Dashboard
            ├── /health
            ├── /status
            ├── /metrics
            ├── /risk (GET/PUT)
            ├── /kill, /unkill
            ├── /orders
            └── /logs/tail
```

## Environment Variables

```bash
# Configuration
CONFIG_FILE=config.yaml              # Path to config file (required)
BOT_MODE=bot                          # "bot" or "api" (default: bot)
LOG_LEVEL=INFO                        # DEBUG/INFO/WARNING/ERROR
LOG_FILE=/tmp/polymarket_bot.log      # Log file path

# Credentials
POLYMARKET_PRIVATE_KEY=xxx            # Optional: enables live trading
ANTHROPIC_API_KEY=sk-xxx              # Optional: enables Claude sentiment
```

## Configuration (config.yaml)

```yaml
engine:
  loop_seconds: 5              # Engine update frequency

markets:
  - market_1_id
  - market_2_id

strategy:
  name: sma_cross              # or "claude_sentiment"
  fast_period: 5
  slow_period: 20
  cooldown_minutes: 30         # For Claude strategy

risk:
  max_position_usd: 10000
  max_daily_drawdown_usd: 5000
  max_orders_per_hour: 100

dashboard:
  host: 0.0.0.0
  port: 8000
  token: your-secret-token     # Bearer token for API auth

data_feed:
  cache_seconds: 10
```

## Running the Bot

### Mode 1: Trading Bot (default)
```bash
export CONFIG_FILE=config.yaml
export BOT_MODE=bot
export LOG_LEVEL=INFO
export POLYMARKET_PRIVATE_KEY=your_key  # Optional
python -m src.main
```

### Mode 2: API Dashboard Only
```bash
export CONFIG_FILE=config.yaml
export BOT_MODE=api
export LOG_LEVEL=INFO
python -m src.main
# API available at http://localhost:8000
```

### Mode 3: Both (separate processes)
```bash
# Terminal 1: Bot
BOT_MODE=bot python -m src.main

# Terminal 2: API
BOT_MODE=api python -m src.main
```

## API Examples

### Check Health
```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","uptime_seconds":123}
```

### Get Status (requires token)
```bash
curl -H "Authorization: Bearer your-secret-token" \
  http://localhost:8000/status
# Returns positions, PnL, kill switch state, etc.
```

### Enable Kill Switch
```bash
curl -X POST -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"reason":"High volatility detected"}' \
  http://localhost:8000/kill
```

### Update Risk Limits
```bash
curl -X PUT -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"max_position_usd": 15000}' \
  http://localhost:8000/risk
```

### Get Recent Orders
```bash
curl -H "Authorization: Bearer your-secret-token" \
  "http://localhost:8000/orders?limit=50"
```

### View Logs
```bash
curl -H "Authorization: Bearer your-secret-token" \
  "http://localhost:8000/logs/tail?n=100"
```

## Strategy Details

### SMA Crossover (SMACrossStrategy)
- **When**: Runs every engine loop
- **Logic**: 
  - Fast SMA > Slow SMA → BUY YES signal
  - Fast SMA < Slow SMA → BUY NO signal
  - Gap size determines confidence (0-100%)
- **Sizing**: Half-Kelly criterion on price gap
- **Good for**: Trending markets with clear technical patterns

### Claude Sentiment (ClaudeSentimentStrategy)
- **When**: Every engine loop (but respects cooldown)
- **How**: 
  1. Sends market question + current price to Claude Haiku
  2. Claude returns calibrated probability estimate
  3. Compare Claude estimate vs market price
  4. >5% mispricing triggers signal
- **Sizing**: Half-Kelly based on mispricing magnitude
- **Cooldown**: 30 min between re-analyses (configurable)
- **Fallback**: Returns HOLD if API unavailable

## Risk Management Layers

1. **Kill Switch**: Can be triggered remotely via API
2. **Position Limits**: Max USD exposure per market
3. **Rate Limiting**: Max orders per hour
4. **Drawdown Limits**: Max daily losses
5. **Stale Price Guard**: Reject trades if price data > 5x loop_seconds old
6. **Volatility Pause**: Suspend trading if volatility spikes (std dev > 3x mean return)

## Logging

All events logged as structured JSON to log file. Examples:
```json
{"event": "engine_started", "loop_seconds": 5, "markets": 2}
{"event": "signal_generated", "market_id": "m1", "action": "buy_yes", "size": 50}
{"event": "pre_trade_check_passed", "market_id": "m1", "size": 50}
{"event": "order_placed", "order_id": "o123", "side": "buy", "size": 50}
{"event": "kill_switch_triggered", "reason": "High volatility"}
```

## Key Design Decisions

1. **Async/Await**: All I/O non-blocking for throughput
2. **Structured Logging**: JSON format for easy parsing and monitoring
3. **Half-Kelly Sizing**: Conservative 50% Kelly for risk management
4. **Cooldown on Analysis**: Prevents API spam in sentiment strategy
5. **Graceful Degradation**: Missing API key → returns HOLD signal
6. **Multi-layer Risk**: Defense in depth approach to prevent catastrophic losses
7. **Modular Design**: Easy to add new strategies or risk checks

## Production Checklist

- [ ] Set CONFIG_FILE to proper path
- [ ] Configure markets list
- [ ] Set risk limits appropriately
- [ ] Generate and secure dashboard token
- [ ] Set up log file location
- [ ] Test strategy signals on paper broker first
- [ ] Monitor API health endpoint continuously
- [ ] Have kill switch accessible
- [ ] Set up log aggregation/alerting
- [ ] Test API endpoints with token auth
- [ ] Review risk parameters before going live

