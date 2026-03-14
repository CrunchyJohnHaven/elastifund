# src

Research-code package for feature generation, hypothesis evaluation, and replay-ready signal production.

## Scope

- `src/` owns shared experiment primitives and research-loop orchestration.
- `backtest/` owns historical evaluation and replay evidence reports.
- `simulator/` owns execution-cost and fill-model simulation runs.

If code does not need live runtime integration and is reused by more than one experiment, put it in `src/`.

## Placement Rules For New Experiment Code

- Add shared feature transforms in `feature_engineering.py` or `models/`.
- Add new signal families under `strategies/` with strategy-specific logic only.
- Add orchestration and reporting glue in `research_loop.py`, `hypothesis_manager.py`, or `reporting.py`.
- Put one-off analysis runners in `backtest/` or `simulator/`, not in `src/`.

## Canonical Entrypoint

- Research loop daemon or single-cycle replay:
  - `python3 -m src.main --run-once`

`src.main` is the canonical `src/` entrypoint for cycle orchestration.
