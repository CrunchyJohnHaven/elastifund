# BTC5 Market Benchmark v1

| Metadata | Value |
|---|---|
| Canonical file | `benchmarks/btc5_market/v1/README.md` |
| Role | Frozen BTC5 market-model benchmark lane |
| Status | active |
| Last updated | 2026-03-11 |

This package freezes the BTC5 market-model benchmark for one 24-hour epoch at a time.

It exists so simulator and evaluator mutations can be judged against a stable replay slice instead of drifting with fresh market data during the same search wave.

## What Is Frozen

- mutable surface: `btc5_market_model_candidate.py`
- benchmark epoch length target: `24` hours (`288` 5-minute windows when available)
- objective:
  `simulator_loss = 0.40*pnl_window_mae_pct + 0.25*fill_rate_mae_pct + 0.20*side_brier + 0.15*p95_drawdown_mae_pct`
- chart grammar: gray discarded points, green kept points, green running-best step line, angled kept-point annotations
- bootstrap replay: fixed seed list and fixed block size from the manifest

Lower `simulator_loss` is better.

## Data Contract

The benchmark snapshot is built from current BTC5 artifacts:

- cached BTC5 rows from `reports/tmp_remote_btc5_window_rows.json` when the local DB is absent or empty
- local `data/btc_5min_maker.db` rows when present
- DB-only enrichments such as `best_bid`, `best_ask`, `edge_tier`, and `session_policy_name` when available

The epoch snapshot itself is frozen into `benchmarks/btc5_market/v1/frozen_windows.jsonl`, and the manifest records the checksum.
The manifest also freezes the immutable runner paths plus `epoch_started_at_utc` and `epoch_expires_at_utc` so the evaluator contract cannot drift inside the active 24-hour benchmark epoch.

## Run It

```bash
python3 scripts/run_btc5_market_model_autoresearch.py
```

## Interpretation

A benchmark win means the candidate market model improved on the frozen BTC5 benchmark epoch.
It does not imply realized P&L improved, and it does not bypass runtime safety gates.
