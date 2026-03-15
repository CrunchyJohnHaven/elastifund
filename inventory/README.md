# Benchmark Inventory

| Metadata | Value |
|---|---|
| Canonical file | `inventory/README.md` |
| Role | Benchmark inventory index and boundary contract |
| Scope | `inventory/` only |
| Last updated | 2026-03-11 |

This package is the benchmark control surface for external-system comparisons. It exists so Elastifund can compare systems with evidence instead of publishing placeholder leaderboard claims.

## Current State

- Methodology is published in code and API payloads.
- System catalog source of truth: `inventory/data/systems.json`.
- Planned run ledger source of truth: `inventory/data/runs.json`.
- Machine-readable taxonomy index: `inventory/index.manifest.json`.
- Rankings remain `methodology_only` until completed runs with evidence exist.

## Surface Index

| Path | Classification | Purpose |
|---|---|---|
| `data/` | canonical machine contract | Versioned benchmark system catalog and run metadata |
| `systems/` | canonical adapter surface | Per-system adapters, lock files, and runbook notes |
| `strategies/` | active build spec | Portable translated strategies for apples-to-apples comparisons |
| `metrics/` | canonical contract | Evidence normalization schema and packet models |
| `results/` | canonical artifact sink | Published benchmark evidence and score artifacts |

## Boundary Rules

- Keep benchmark and comparison contracts here, not in `infra/`.
- `comparison_only` systems must remain allocator-ineligible unless policy is explicitly changed.
- Do not commit placeholder rankings or invented scores.
