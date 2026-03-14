# backtest/historical

Legacy and one-off utilities retained for reproducibility.

Current members:
- `analyze_results.py`
- `fix_portfolio.py`
- `patch_resolution.py`
- `run_expanded_pipeline.py`
- `combined_calibrator.py`
- `monte_carlo_advanced.py`

Rules:
- Keep these scripts out of canonical operator flows.
- Maintain lightweight compatibility shims at prior top-level paths when moved.
- Prefer `python3 -m backtest.run_scale_comparison` and `python3 -m backtest.run_combined` for current workflows.
