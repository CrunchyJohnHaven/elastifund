# Polymarket Bot - Deployment Operations Guide

## Overview

This directory contains deployment automation scripts and a lightweight backtesting harness for the Polymarket trading bot.

## Deployment Scripts (ops/)

### 1. ubuntu_setup.sh
Initial VPS setup for Ubuntu 22.04/24.04 (Hetzner CX23 recommended)

**Installs:**
- Docker & Docker Compose
- Tailscale (VPN for secure dashboard access)
- Security hardening (ufw firewall, fail2ban, auto-updates)
- Application directory at `/opt/polymarket-bot`

**Usage:**
```bash
./ops/ubuntu_setup.sh
```

**Post-setup steps:**
1. `sudo tailscale up` - Connect to your tailnet
2. Configure `.env` file with API keys and settings
3. Deploy with `./ops/deploy.sh`

### 2. deploy.sh
Deploy/update the bot with Docker Compose

**Checks:**
- `.env` configuration file exists
- Prerequisites met

**Actions:**
- Pulls latest images
- Builds Docker containers
- Stops old containers
- Starts new containers
- Waits 10 seconds for startup
- Validates API health endpoint
- Displays dashboard URL

**Usage:**
```bash
APP_DIR=/opt/polymarket-bot ./ops/deploy.sh
```

**Environment variables:**
- `APP_DIR` - Application directory (default: `/opt/polymarket-bot`)

### 3. rollback.sh
Rollback deployment to previous version

**Actions:**
- Stops current containers
- Optionally updates to a previous image tag
- Restarts containers
- Validates health check

**Usage:**
```bash
# Simple restart with current images
./ops/rollback.sh

# Rollback to specific tag
./ops/rollback.sh v1.2.3
```

**Manual rollback fallback:**
```bash
docker compose down
git checkout <previous-commit>
docker compose build && docker compose up -d
```

### 4. smoke_test.sh
Post-deployment health checks

**Validates:**
- GET /health (no auth required)
- GET /status (authenticated)
- GET /metrics (authenticated)
- GET /risk (authenticated)
- GET /orders (authenticated)
- Heartbeat freshness

**Usage:**
```bash
# Test local instance
./ops/smoke_test.sh

# Test remote instance
./ops/smoke_test.sh http://your-tailscale-ip:8000

# With custom token
DASHBOARD_TOKEN=your_token ./ops/smoke_test.sh
```

**Exit codes:**
- 0: All tests passed
- 1: Some tests failed

## Backtesting (src/strategy/backtest.py)

Lightweight deterministic backtesting harness for strategy validation.

### Key Features

- **Async/await support** - Compatible with async strategy implementations
- **Paper broker integration** - Uses simulated trading engine
- **Deterministic results** - Reproducible with fixed seeds
- **Realistic simulation** - Includes slippage and fee modeling
- **Metrics calculation** - PnL, drawdown, Sharpe ratio, win rate

### BacktestResult Dataclass

```python
@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    start_date: Optional[str]
    end_date: Optional[str]
    initial_cash: float
    final_cash: float
    total_pnl: float
    total_pnl_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    sharpe_ratio: float
    equity_curve: list[float]
```

### Backtester Class

```python
bt = Backtester(
    strategy=my_strategy,
    initial_cash=1000.0,
    slippage_bps=10,      # 10 basis points
    fee_bps=0,            # 0 basis points
)

result = await bt.run(
    prices=[0.50, 0.51, 0.52, ...],
    market_id="some-market",
    token_id="YES"
)

print(f"Final P&L: {result.total_pnl:.2f} ({result.total_pnl_pct:.1f}%)")
print(f"Max Drawdown: {result.max_drawdown:.2f} ({result.max_drawdown_pct:.1f}%)")
print(f"Trades: {result.trade_count}, Win Rate: {result.win_rate:.1f}%")
```

### Synthetic Price Generation

```python
from src.strategy.backtest import generate_synthetic_prices

# Create 500 price points with geometric random walk
prices = generate_synthetic_prices(
    n=500,
    base_price=0.5,
    trend=0.0001,        # Slight upward drift
    volatility=0.02,     # 2% daily volatility
    seed=42              # Reproducible
)

# All prices clamped to [0.01, 0.99] for prediction markets
```

## Testing (tests/test_backtest.py)

Comprehensive tests ensure deterministic behavior:

```bash
pytest tests/test_backtest.py -v
```

**Test cases:**
- `test_deterministic_backtest` - Basic backtest execution
- `test_deterministic_reproducibility` - Same seed = same results
- `test_synthetic_prices_reproducible` - Price generation reproducibility
- `test_synthetic_prices_clamped` - Price bounds validation

## Deployment Workflow

### Initial Setup
```bash
# 1. Setup VPS
./ops/ubuntu_setup.sh

# 2. Configure (after SSH login)
sudo tailscale up
cp .env.example /opt/polymarket-bot/.env
nano /opt/polymarket-bot/.env

# 3. Deploy
cd /opt/polymarket-bot
./ops/deploy.sh
```

### Validation
```bash
# Check logs
docker compose logs -f api

# Run smoke tests
./ops/smoke_test.sh

# Access dashboard
# Open browser: http://<tailscale-ip>:8000
```

### Updates
```bash
# Pull latest code
git pull origin main

# Deploy with zero downtime
./ops/deploy.sh

# If issues occur
./ops/rollback.sh
```

### Monitoring
```bash
# Watch logs
docker compose logs -f

# View specific service
docker compose logs -f api

# Check health
curl http://localhost:8000/health | jq

# Access metrics
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/metrics
```

## Security Notes

1. **Tailscale VPN** - Dashboard only accessible within private network
2. **Firewall** - UFW allows SSH and Docker only
3. **API Authentication** - Dashboard endpoints require bearer token
4. **Environment Variables** - Store secrets in `.env` (git-ignored)
5. **Fail2ban** - Automatic IP blocking for brute force attempts

## Troubleshooting

### Deployment fails: "ERROR: .env not found"
```bash
cp .env.example /opt/polymarket-bot/.env
# Edit with your API keys
```

### Health check fails after deploy
```bash
# Check logs
docker compose logs --tail=50 api

# Verify port availability
netstat -tlnp | grep 8000

# Restart manually
docker compose down && docker compose up -d
```

### Smoke test fails: "FAIL: GET /status (got 401)"
```bash
# Verify token
echo $DASHBOARD_TOKEN

# Set token for test
DASHBOARD_TOKEN=your_actual_token ./ops/smoke_test.sh
```

### Need to rollback
```bash
# Simple rollback
./ops/rollback.sh

# Rollback to specific version
./ops/rollback.sh v1.2.0

# Manual reset
git log --oneline | head -10
git checkout <commit-hash>
docker compose build && docker compose up -d
```

## Performance Tips

1. **Backtest optimization** - Use smaller price series for quick validation
2. **Slippage tuning** - Adjust `slippage_bps` based on market liquidity
3. **Seed strategy** - Always use fixed seeds for regression testing
4. **Parallel backtests** - Run multiple strategies with asyncio
5. **Memory** - Price series limited to ~10k points for safety

## Architecture

```
polymarket-bot/
├── ops/                          # Deployment automation
│   ├── ubuntu_setup.sh          # Initial VPS setup
│   ├── deploy.sh                # Deploy/update
│   ├── rollback.sh              # Rollback
│   └── smoke_test.sh            # Health checks
├── src/
│   ├── strategy/
│   │   ├── base.py              # Strategy interface
│   │   ├── backtest.py          # Backtester + synthetic data
│   │   └── *.py                 # Strategy implementations
│   └── broker/
│       ├── base.py              # Broker interface
│       ├── paper_broker.py      # Paper trading
│       └── live_broker.py       # Live trading
└── tests/
    ├── test_backtest.py         # Backtest tests
    └── *.py                     # Other tests
```
