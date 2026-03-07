# Polymarket Trading Bot — S.T.A.R. 2.0

Paper-first, always-on Polymarket trading bot with risk controls, kill switch, REST dashboard, and VPS deployment.

**Default mode: PAPER TRADING.** No real orders until `LIVE_TRADING=true` is explicitly set.

## Quick Start (Local)

```bash
# 1. Copy and edit environment
cp .env.example .env
# Edit .env with your settings (paper mode works without API keys)

# 2. Install dependencies
pip install pydantic pydantic-settings structlog sqlalchemy[asyncio] aiosqlite \
    fastapi uvicorn httpx pytest pytest-asyncio

# 3. Run the engine (paper mode, mock data)
python -m src.main

# 4. Run the API dashboard (separate terminal)
BOT_MODE=api python -m src.main
```

## Quick Start (Docker on VPS)

```bash
# 1. Setup VPS (Ubuntu 22.04/24.04)
bash ops/ubuntu_setup.sh

# 2. Deploy
cp .env.example /opt/polymarket-bot/.env
# Edit /opt/polymarket-bot/.env
bash ops/deploy.sh

# 3. Smoke test
bash ops/smoke_test.sh
```

## Architecture

```
src/
  app/           FastAPI dashboard + admin endpoints
  core/          Config (pydantic-settings), logging, time utils
  data/          Market data adapters (MockDataFeed, PolymarketDataFeed)
  broker/        Execution adapters (PaperBroker, PolymarketBroker)
  risk/          Kill switch, position limits, drawdown, volatility pause
  strategy/      SMA cross, Claude sentiment, backtest harness
  engine/        Main loop (scheduler)
  store/         Postgres/SQLite models + repository
tests/           34 unit tests (all passing)
ops/             Deploy, rollback, smoke test scripts
```

## API Endpoints

| Endpoint       | Method | Auth | Description |
|---------------|--------|------|-------------|
| `/health`      | GET    | No   | Health check + uptime |
| `/status`      | GET    | Yes  | Positions, PnL, kill switch state |
| `/metrics`     | GET    | Yes  | Order/position counts, errors |
| `/risk`        | GET    | Yes  | Current risk limits |
| `/risk`        | PUT    | Yes  | Update risk limits |
| `/kill`        | POST   | Yes  | Enable kill switch (body: `{"reason": "..."}`) |
| `/unkill`      | POST   | Yes  | Disable kill switch |
| `/orders`      | GET    | Yes  | Recent orders |
| `/logs/tail`   | GET    | Yes  | Last N log lines |

Auth: `Authorization: Bearer <DASHBOARD_TOKEN>`

## Risk Controls (6 Layers)

1. **Kill switch** — DB-backed, API-controllable, engine respects immediately
2. **Max position USD** — Blocks orders that would exceed limit
3. **Max orders/hour** — Rate limiting
4. **Max daily drawdown** — Auto-triggers kill switch if exceeded
5. **Stale price guard** — Blocks if price data older than 5× loop interval
6. **Volatility pause** — Pauses if returns std dev exceeds threshold

## Strategies

- **SMACross(5,20)** — SMA crossover with half-Kelly sizing
- **ClaudeSentiment** — Claude Haiku probability estimate vs market price, signals on >5% mispricing
- **Backtest harness** — `src/strategy/backtest.py` with synthetic price generation

## Tests

```bash
python -m pytest tests/ -v -o "addopts="
```

34 tests covering: risk limits, kill switch, paper broker, position math, repository CRUD, backtest determinism, live-trading-blocked-by-default.

## Paper vs Live

| Setting | Value | Behavior |
|---------|-------|----------|
| `LIVE_TRADING` | `false` (default) | Paper broker only. PolymarketBroker raises on any order attempt. |
| `LIVE_TRADING` | `true` | Requires valid `POLYMARKET_PRIVATE_KEY`. Risk controls still enforced. |

## Configuration (.env)

All settings via environment variables / `.env` file. See `.env.example` for complete list.

Key variables: `POLYMARKET_PRIVATE_KEY`, `DATABASE_URL`, `LIVE_TRADING`, `ENGINE_LOOP_SECONDS`, `MAX_POSITION_USD`, `MAX_DAILY_DRAWDOWN_USD`, `MAX_ORDERS_PER_HOUR`, `DASHBOARD_TOKEN`.

## Deployment

- **VPS**: Hetzner CX23 (€3.49/mo), Ubuntu 24.04, Docker Compose
- **Access**: Tailscale VPN only (no public dashboard exposure)
- **Persistence**: PostgreSQL in Docker, restart-safe
- **Rollback**: `ops/rollback.sh [tag]`
