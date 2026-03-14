# Infrastructure Surface

| Metadata | Value |
|---|---|
| Canonical file | `infra/README.md` |
| Role | Index for infrastructure helpers and observability assets |
| Scope | `infra/` only |
| Last updated | 2026-03-11 |

## What Is Canonical Here

| Path | Classification | Purpose |
|---|---|---|
| `clob_ws.py`, `ws_market_cache.py`, `ws_user_orders.py` | canonical runtime helper | Shared websocket and quote-state infrastructure for trading lanes |
| `fast_json.py` | canonical runtime helper | Fast JSON parsing shim used by websocket and stream paths |
| `cross_asset_data_plane.py`, `cross_asset_artifact_paths.py` | canonical runtime helper | Cross-asset rollout artifact and data-plane contract helpers |
| `index_templates/` | canonical observability asset | Elastic index templates consumed by bootstrap/telemetry flows |
| `kibana_dashboards/` | canonical observability asset | Kibana dashboard exports for operator observability |
| `apm-server.yml`, `filebeat.yml`, `docker-compose.elastic.yml` | canonical stack config | Local/remote observability stack config templates |
| `setup.sh` | checklist utility | Bootstrap helper for local Elastic stack setup |

## Boundary Rules

- `infra/` is an implementation surface, not a benchmark-policy surface.
- Benchmark system policy and adapter-specific contracts live under `inventory/`.
- Any change to cross-asset artifact contracts must stay aligned with `docs/ops/cross_asset_lane.md` and related tests.
- Avoid adding one-off scripts here. Reusable command entrypoints belong in `scripts/`.

## Comparison Lane Note

OpenClaw and other external-system benchmark adapters are isolated under `inventory/systems/` and are comparison-only unless explicitly promoted by policy.
