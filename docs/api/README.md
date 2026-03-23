# API Documentation

- Status: canonical
- Last reviewed: 2026-03-22
- Scope: HTTP API index for the current Elastifund services

This directory packages the HTTP APIs that currently exist in the Elastifund repo.

## Covered Services

- `hub/app/main.py`: the Elastifund hub gateway scaffold
- `polymarket-bot/src/app/dashboard.py`: the Polymarket dashboard and control API

## Not Covered

- CLI-only surfaces in `data_layer/`, `nontrading/`, and `orchestration/`
- direct SQLite schemas
- future registration, vector-search, or federated-learning endpoints that are only design-stage today

## Start Here

If you want to inspect the machine-readable specs, use:

- `elastifund-hub.openapi.json`
- `polymarket-dashboard.openapi.json`

Regenerate them from the repo root:

```bash
make api-specs
```

If you are not using the root env, the direct command is:

```bash
python3 scripts/export_openapi_specs.py
```

## Auth Model

### Hub Gateway

The current hub scaffold does not yet apply an app-layer auth wrapper of its own. Treat it as a trusted-network service.

Operational notes:

- `POST /v1/auth/api-keys` uses the gateway’s configured Elasticsearch credentials to mint downstream API keys.
- The benchmark catalog and methodology endpoints are read-only, but they still inherit the same trusted-network assumption.
- Do not expose the gateway directly to the public internet in its current form.

### Polymarket Dashboard

The dashboard currently has two auth behaviors:

1. HTML and UI helper endpoints can use HTTP Basic auth or a bearer token.
2. Control endpoints require `Authorization: Bearer <DASHBOARD_TOKEN>` when the token is configured away from the default sentinel.

Set a real `DASHBOARD_TOKEN` before using the dashboard anywhere outside a local sandbox.

## Endpoint Summary

### Hub Gateway

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | basic service identity and caveat text |
| `GET` | `/healthz` | dependency health for Elasticsearch, Kafka, and Redis |
| `GET` | `/v1/topology` | public topology, indices, topics, privacy tiers |
| `POST` | `/v1/auth/api-keys` | mint Elasticsearch API keys for agents or services |
| `GET` | `/api/v1/benchmark/methodology` | benchmark methodology and scoring rubric |
| `GET` | `/api/v1/bots` | normalized benchmark catalog entries |
| `GET` | `/api/v1/bots/{bot_id}` | single system record plus latest run |
| `GET` | `/api/v1/rankings` | benchmark leaderboard output |
| `GET` | `/api/v1/runs` | planned or completed benchmark runs |
| `GET` | `/api/v1/runs/{run_id}/artifacts` | published artifact pointers |
| `GET` | `/api/v1/paper-status` | current paper-run state by system |

### Polymarket Dashboard

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | static dashboard HTML |
| `GET` | `/api/dashboard-data` | aggregated value, P&L, exposure, kill-switch state |
| `GET` | `/api/equity-curve` | daily portfolio snapshots |
| `GET` | `/api/recent-trades` | recent orders for the UI table |
| `GET` | `/health` | liveness and version info |
| `GET` | `/status` | bot status and estimated P&L |
| `GET` | `/metrics` | runtime counters and telemetry reachability |
| `GET` | `/risk` | current in-process risk limits |
| `PUT` | `/risk` | update in-process risk limits |
| `POST` | `/kill` | enable kill switch and attempt to cancel live orders |
| `POST` | `/unkill` | clear kill switch after cooldown |
| `GET` | `/orders` | open orders snapshot |
| `GET` | `/execution` | execution-quality summary and recent fills/cancels |
| `GET` | `/logs/tail` | tail lines from the runtime log file |

## Example Calls

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/v1/topology
curl http://localhost:8001/health
curl -H "Authorization: Bearer $DASHBOARD_TOKEN" http://localhost:8001/status
```

## Known Gaps

- The dashboard OpenAPI spec does not encode auth requirements directly because the runtime uses custom FastAPI dependencies instead of OpenAPI security helpers.
- The hub gateway responses are intentionally broad JSON objects today; response schemas will become more specific as the API expands.
- The benchmark API is methodology-first by design. Empty rankings are the correct output until completed clean-room runs exist.
