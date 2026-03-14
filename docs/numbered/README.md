# Numbered Governance Docs
Version: 1.0.0
Date: 2026-03-11
Purpose: Define the authoritative numbered governance lane and the root compatibility-shim policy.

## Canonical Rule

`docs/numbered/` is the authoritative source for numbered governance and messaging docs (`00` through `12`).
Policy content updates must be made here.

## Root Shim Rule

Root files named `00_MISSION_AND_PRINCIPLES.md` through `12_MANAGED_SERVICE_BOUNDARY.md` are non-authoritative compatibility shims.
They exist to preserve stable root filenames for existing links and workflows.

When a numbered policy doc changes:

1. Edit the canonical file in `docs/numbered/`.
2. Keep the matching root file as a pointer-only shim.
3. Do not duplicate full policy text at root.

## Canonical Mapping

| Root shim | Canonical document |
|---|---|
| `00_MISSION_AND_PRINCIPLES.md` | `docs/numbered/00_MISSION_AND_PRINCIPLES.md` |
| `01_EXECUTIVE_SUMMARY.md` | `docs/numbered/01_EXECUTIVE_SUMMARY.md` |
| `02_ARCHITECTURE.md` | `docs/numbered/02_ARCHITECTURE.md` |
| `03_METRICS_AND_LEADERBOARDS.md` | `docs/numbered/03_METRICS_AND_LEADERBOARDS.md` |
| `04_TRADING_WORKERS.md` | `docs/numbered/04_TRADING_WORKERS.md` |
| `05_NON_TRADING_WORKERS.md` | `docs/numbered/05_NON_TRADING_WORKERS.md` |
| `06_EXPERIMENT_DIARY.md` | `docs/numbered/06_EXPERIMENT_DIARY.md` |
| `07_FORECASTS_AND_CHECKPOINTS.md` | `docs/numbered/07_FORECASTS_AND_CHECKPOINTS.md` |
| `08_PROMPT_LIBRARY.md` | `docs/numbered/08_PROMPT_LIBRARY.md` |
| `09_GOVERNANCE_AND_SAFETY.md` | `docs/numbered/09_GOVERNANCE_AND_SAFETY.md` |
| `10_OPERATIONS_RUNBOOK.md` | `docs/numbered/10_OPERATIONS_RUNBOOK.md` |
| `11_PUBLIC_MESSAGING.md` | `docs/numbered/11_PUBLIC_MESSAGING.md` |
| `12_MANAGED_SERVICE_BOUNDARY.md` | `docs/numbered/12_MANAGED_SERVICE_BOUNDARY.md` |
