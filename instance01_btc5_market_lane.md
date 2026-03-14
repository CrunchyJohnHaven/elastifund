# Instance 01 BTC5 Market Lane

Status: delivered
Date: 2026-03-11
Project: BTC5 Dual Autoresearch

## Frozen Contract

- Benchmark package: `benchmarks/btc5_market/v1/`
- Mutable surface: `btc5_market_model_candidate.py`
- Immutable runner path: `benchmarks/btc5_market/v1/benchmark.py`
- Immutable runner path: `scripts/run_btc5_market_model_autoresearch.py`
- Immutable runner path: `scripts/render_btc5_market_model_progress.py`
- Objective: `simulator_loss = 0.40*pnl_window_mae_pct + 0.25*fill_rate_mae_pct + 0.20*side_brier + 0.15*p95_drawdown_mae_pct`
- Replay contract: fixed `seed_list`, `block_size=4`, `fit_seed=0`
- Frozen epoch control window: `2026-03-11T18:18:50Z` to `2026-03-12T18:18:50Z`

## Data Freeze

- BTC5 correlation surface used for the first freeze: `548` decision rows, `226` live-filled rows
- Frozen snapshot: `benchmarks/btc5_market/v1/frozen_windows.jsonl`
- Snapshot checksum: `d880e751e174450fc9ad2f3bf09f7701480fecc456251d626e06dfe292943838`
- Frozen dataset shape: `548` total rows, `260` warmup rows, `288` benchmark rows
- Source mix: cached rows from `reports/tmp_remote_btc5_window_rows.json`; no local DB replay rows or DB-only enrichments were present in the first freeze

## Output Artifacts

- Ledger: `reports/autoresearch/btc5_market/results.jsonl`
- Champion registry: `reports/autoresearch/btc5_market/champion.json`
- Latest summary: `reports/autoresearch/btc5_market/latest.json`
- Packet baseline: `reports/autoresearch/btc5_market/packets/experiment_0001.json`
- Progress chart: `research/btc5_market_model_progress.svg`

## Current Frontier

- Champion experiment: `1`
- Champion model: `empirical_backoff_v1`
- Champion loss: `5.178301`
- Loss component: `pnl_window_mae_pct = 0.419397`
- Loss component: `fill_rate_mae_pct = 0.477688`
- Loss component: `side_brier = 0.182304`
- Loss component: `p95_drawdown_mae_pct = 32.364399`
- Ledger state at handoff: `1` keep, `2` discard, `0` crash

## Verification

- `verify_manifest()` passes on the frozen manifest and snapshot checksum
- `python3 -m pytest tests/test_btc5_market_model_benchmark.py tests/test_run_btc5_market_model_autoresearch.py tests/test_render_btc5_market_model_progress.py`
- Result: `3 passed`

## Handoff Constraints For The Policy Lane

- Treat `benchmarks/btc5_market/v1/manifest.json` as immutable for the active epoch.
- Treat `btc5_market_model_candidate.py` as the only mutable surface for this lane.
- Read simulator truth from `reports/autoresearch/btc5_market/champion.json` and `reports/autoresearch/btc5_market/latest.json`.
- Rebuild benchmark progress only from `reports/autoresearch/btc5_market/results.jsonl`.
- Benchmark progress is benchmark progress, not live profitability.
