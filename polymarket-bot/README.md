# Polymarket Trading Bot

This is the standalone trading-bot subproject inside the broader Elastifund monorepo.

It provides:

- a paper-first and live-capable trading loop
- a FastAPI dashboard and control surface
- risk controls and kill-switch behavior
- optional Elastic telemetry into the shared Elastifund hub

**Default mode is paper trading.** Nothing should hit live order flow unless the runtime is explicitly configured for it.

## Which Path Should You Use?

| If you want to... | Use this path |
|---|---|
| work from the full monorepo | go back to the repo root and use `make bootstrap` + `make test-polymarket` |
| work on this subproject in isolation | create a local env here and install via Poetry |
| understand dashboard and API behavior | read [../docs/api/README.md](../docs/api/README.md) |

## Fastest Path From The Repo Root

```bash
cd elastifund
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
make test-polymarket
cd polymarket-bot
python3 -m src.main
```

## Standalone Subproject Setup

```bash
cd elastifund/polymarket-bot
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install
poetry run python -m pytest tests -q
```

## Quick Start

### Paper Mode

```bash
cp .env.example .env
python -m src.main
```

### Dashboard Mode

```bash
BOT_MODE=api python -m src.main
```

### Full Test Pass

```bash
python -m pytest tests -q
```

See [TESTING_GUIDE.md](TESTING_GUIDE.md) for targeted suites and debugging tricks.

## Optional Elastic Telemetry

The bot can publish directly into the shared Elastic hub.

What gets written:

- `elastifund-agents`: heartbeat and runtime status
- `elastifund-metrics`: per-cycle P&L, cost, and drawdown-budget consumption
- `elastifund-trades`: paper/live order snapshots with strategy and execution metadata

Why it matters:

- it removes the “tail logs and hope” operator loop
- it gives Kibana a shared view of bot health, trade flow, and paper-vs-live behavior
- it turns this bot into a real spoke in the broader Elastifund control plane

Bootstrap the shared stack from the repo root:

```bash
cd elastifund
cp .env.example .env
docker compose up -d elasticsearch kibana
python3 -m hub.elastic.bootstrap apply
```

Then enable telemetry in `polymarket-bot/.env`:

```bash
ELASTIC_TELEMETRY_ENABLED=true
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_USERNAME=elastic
ELASTIC_PASSWORD=changeme
ELASTICSEARCH_VERIFY_CERTS=false
ELASTIC_AGENT_ID=polymarket-bot
```

The bot is fail-open: if Elastic is unavailable or the aliases have not been bootstrapped yet, trading continues and the dashboard surfaces the telemetry error state.

## Architecture

| Path | Purpose |
|---|---|
| `src/app/` | FastAPI dashboard and admin endpoints |
| `src/core/` | config, logging, time utilities |
| `src/data/` | market-data adapters |
| `src/broker/` | paper and live execution adapters |
| `src/risk/` | kill switch, limits, drawdown, volatility pause |
| `src/strategy/` | strategies and backtest harness |
| `src/engine/` | scheduler and main loop |
| `src/store/` | persistence models and repository |
| `tests/` | regression suite |
| `ops/` | deploy, rollback, and smoke-test scripts |

Historical snapshots live under `snapshots/` as local archive artifacts and are ignored by default in git.

## Main API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | `GET` | liveness and version info |
| `/status` | `GET` | positions, P&L, kill-switch state |
| `/metrics` | `GET` | runtime counters and telemetry status |
| `/risk` | `GET`/`PUT` | inspect or update in-process risk limits |
| `/kill` | `POST` | enable kill switch |
| `/unkill` | `POST` | clear kill switch after cooldown |
| `/orders` | `GET` | open orders snapshot |
| `/execution` | `GET` | execution-quality summary |
| `/logs/tail` | `GET` | recent runtime log lines |

Auth for control endpoints is bearer-token based: `Authorization: Bearer <DASHBOARD_TOKEN>`.

## Risk Controls

The bot keeps multiple rails in front of live behavior:

1. kill switch
2. max position size
3. max orders per hour
4. max daily drawdown
5. stale-price guard
6. volatility pause

## Deployment Notes

- the subproject can run on its own
- the wider repo adds shared Elastic observability and hub coordination
- do not claim live readiness just because the dashboard boots

For deployment details, see `ops/` and the repo-level [deploy docs](../deploy/README.md).
