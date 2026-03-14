# backtest

Historical validation and replay-evidence surface.

## Scope

- Historical backtest variants and calibration analysis live here.
- Replay-readiness and bankroll scale comparison live here.
- This directory should not contain live runtime orchestration code.

## Canonical Entrypoints

- Replay and lane evidence comparison:
  - `python3 -m backtest.run_scale_comparison`
- Combined historical strategy backtest summary:
  - `python3 -m backtest.run_combined`
- Rolling calibration walk-forward check:
  - `python3 -m backtest.rolling_platt_analysis`

## Naming and Boundary Rules

- `run_*.py` files are CLI entrypoints.
- Non-`run_*.py` files are library modules, analysis utilities, or compatibility scripts.
- New reusable helpers should be imported by a `run_*.py` entrypoint rather than creating additional top-level ad-hoc runners.

## Historical Utility Scripts (Non-Canonical)

These scripts are retained for reproducibility and legacy analysis workflows, but they are not the default operator path:

- `analyze_results.py`
- `fix_portfolio.py`
- `patch_resolution.py`
- `run_expanded_pipeline.py`
- `combined_calibrator.py`
- `monte_carlo_advanced.py`

Prefer the canonical entrypoints above for current replay/backtest work.
These historical utilities are stored under `backtest/historical/` with compatibility shims at their original paths.
