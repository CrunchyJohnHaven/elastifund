# System Adapters

| Metadata | Value |
|---|---|
| Canonical file | `inventory/systems/README.md` |
| Role | Adapter index and adapter-boundary rules |
| Scope | `inventory/systems/` only |
| Last updated | 2026-03-11 |

Each benchmarked external system gets a subdirectory here once adapter scaffolding exists.

## Adapter Registry

| System | Directory status | Comparison mode | Allocator eligible |
|---|---|---|---|
| OpenClaw | implemented (`openclaw/`) | `comparison_only` | `false` |
| Freqtrade | planned | benchmark cohort | pending |
| Hummingbot | planned | benchmark cohort | pending |
| NautilusTrader | planned | benchmark cohort | pending |

Planned systems are tracked in `inventory/data/systems.json` and `inventory/data/runs.json` even when adapter directories are not created yet.

## Required Adapter Contents

- Install and launch notes.
- Sanitized config templates.
- Adapter glue for the generic harness lifecycle.
- Runbook notes for failure injection and quarantine rules.
- Upstream lock metadata (commit/version/runtime floor).

Keep adapters reproducible so another operator can rerun the same clean-room benchmark without folklore.
