# API Docs

- Status: Active index
- Last reviewed: 2026-03-11
- Scope: machine-readable HTTP API contracts for current FastAPI services

## Current State (30 seconds)

This directory contains the canonical OpenAPI exports for the two active HTTP services:

- `hub/app/main.py` (hub gateway scaffold)
- `polymarket-bot/src/app/dashboard.py` (dashboard/control API)

## Canonical Files

| File | Class | Status | Purpose |
|---|---|---|---|
| `elastifund-hub.openapi.json` | canonical spec | active | hub gateway routes and schemas |
| `polymarket-dashboard.openapi.json` | canonical spec | active | dashboard/control routes and schemas |

## Regeneration

From repo root:

```bash
make api-specs
```

Direct script path:

```bash
python3 scripts/export_openapi_specs.py
```

## Auth Notes

- Hub gateway is trusted-network only in current scaffold form.
- Dashboard control endpoints require `Authorization: Bearer <DASHBOARD_TOKEN>` when token auth is enabled.
- OpenAPI files intentionally do not fully encode custom runtime auth dependencies.

## Out Of Scope

- CLI-only interfaces in `data_layer/`, `nontrading/`, and `orchestration/`
- raw SQLite schemas
- design-stage APIs that are not exported yet

## Naming Convention

- Stable spec filenames use lowercase kebab-case plus `.openapi.json`.
- Keep this README as the index; avoid adding long prose docs in this folder.
