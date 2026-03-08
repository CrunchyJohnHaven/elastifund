# Calibration Benchmark v1

This package freezes the first calibration benchmark lane for Elastifund.

It exists so calibration work can be compared on a stable historical slice instead of drifting with every code change.

## What Is Frozen

- candidate variants: `static`, `expanding`, `rolling_100`, `rolling_200`
- warmup slice: first `372` resolved examples
- holdout slice: last `160` resolved examples
- source ordering: `resolved_at`, then `market_id`
- objective: `benchmark_score = -(brier + 0.25 * ece)`

Higher `benchmark_score` is better.

## Mutable Surface

The benchmark is allowed to vary the implementation in:

- [`bot/adaptive_platt.py`](../../bot/adaptive_platt.py)

The historical source data stays fixed:

- `backtest/data/historical_markets_532.json`
- `backtest/data/claude_cache.json`

## Run It

```bash
python3 scripts/run_calibration_benchmark.py
```

## How To Read Results

A benchmark win means the calibration method improved on the frozen historical slice. It does **not** mean the lane is ready for paper or live promotion on its own.

Use the benchmark to narrow candidates. Use the broader validation pipeline to decide whether anything deserves real deployment.
