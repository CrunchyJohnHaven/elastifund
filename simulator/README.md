# simulator

Execution simulation surface for cost, fill, and sizing assumptions.

Canonical import surface: `simulator.api`.

## Scope

- Simulates order fill behavior, fees, slippage, spread drag, and position sizing.
- Consumes historical market and cached estimate inputs from backtest data.
- Produces deterministic simulation reports for comparison and audit.

## Canonical Entrypoints

- Baseline deterministic sim run:
  - `python3 -m simulator`
  - Equivalent explicit command: `python3 -m simulator.run_baseline`
- Audit or mode-comparison sim run:
  - `python3 -m simulator.run_sim audit`
  - `python3 -m simulator.run_sim compare`

## Naming and Boundary Rules

- `run_baseline.py` is the simplest baseline workflow.
- `run_sim.py` is the richer CLI for audit/compare workflows.
- `simulator.py` and `engine.py` remain compatibility modules with different report shapes.
- New cross-package imports should use `simulator.api` instead of importing either engine module directly.
