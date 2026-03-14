# Bot Package Map

`bot/` is the trading orchestrator surface. It wires runtime loops, adapters,
and lane-specific modules into a single operational process.

## Canonical Entrypoints

- `bot/jj_live.py`: primary runtime orchestrator and cycle loop.
- `bot/polymarket_runtime.py`: market scanning and analysis runtime helpers.
- `bot/edge_scan_report.py`: operator-facing scan summary and readiness output.

## Ownership Boundaries

- Keep orchestration and runtime wiring in `bot/`.
- Keep reusable signal components in `signals/`.
- Keep strategy policy definitions in `strategies/`.
- Keep execution state machines and leg lifecycle transitions in `execution/`.

## Naming Conventions

- Lane-prefixed modules:
  - `a6_*`: A-6 guaranteed-dollar lane orchestration.
  - `b1_*`: B-1 dependency-template lane orchestration.
- Shared runtime helpers stay descriptive (`runtime_profile.py`,
  `execution_readiness.py`, `fill_tracker.py`) and avoid lane prefixes.

## Safe Edit Guidance

- Treat `jj_live.py` and execution-adjacent modules as live-trading-sensitive.
- If moving logic across boundaries, preserve import compatibility in one pass.
- Prefer adding tests for orchestration behavior changes before promotion.
