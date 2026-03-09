# Performance

Everything in this file is labeled as backtest, simulation, or live. If a number is not backed by realized live trading data, it is not presented as realized live performance.

## Backtest Reference

Primary public benchmark: [backtest/results/combined_results.md](../backtest/results/combined_results.md)

Dataset:
- 532 resolved markets
- generated March 5, 2026

Key variants:

| Variant | Trades | Win rate | Brier | Notes |
| --- | --- | --- | --- | --- |
| Baseline (5% symmetric) | 470 | 64.9% | 0.2391 | raw reference point |
| Legacy calibrated reference | 372 | 68.5% | 0.2171 | older broad calibrated benchmark |
| Calibrated + asymmetric | 354 | 68.6% | 0.2171 | stricter YES logic, looser NO logic |
| Current calibrated selective benchmark | 264 | 71.2% | 0.2138 | fewer trades, strongest filtered result |
| Calibrated + NO-only | 282 | 70.2% | 0.2171 | clearest favorite-longshot evidence |

Interpretation:
- Calibration improved both win rate and Brier score versus the raw baseline.
- Current public-safe framing is: `71.2%` strongest calibrated selective result, `68.5%` older calibrated broad reference, `64.9%` raw uncalibrated baseline.
- The filtered variants look better, but they trade less often.
- NO-side strength is persistent enough to shape the live signal policy.

## Monte Carlo Snapshot

Source: `backtest/data/monte_carlo_results.json`

Assumptions in that run:
- starting capital: $75
- 5 trades per day
- 365 days
- 10,000 simulated paths
- $2 position size
- edge persistence inherited from the backtest assumptions

Selected outputs:
- median ending capital: $917.67
- 5th percentile ending capital: $785.67
- average max drawdown: 10.4%
- 95th percentile max drawdown: 19.6%
- simulated ruin under the model: 0.0%

This is not a forecast. It is a scenario engine built on backtest assumptions. If fill rates, slippage, regime stability, or signal quality degrade in live trading, these outputs become too optimistic immediately.

## Live Results

The public repo does not yet contain a sanitized live scorecard.

Current state of the included local bot snapshot:
- `reports/remote_service_status.json` shows `jj-live.service` `running` at `2026-03-09T00:06:56Z`
- launch posture is still `blocked`, so the running service is treated as operational drift until the remote mode is reconciled
- runtime cycles completed: `294`
- orders recorded: 0
- fills recorded: 0
- deployed capital: `$0.00`
- wallet-flow readiness: `not_ready`
- resolved live trade history: not available in this public snapshot

Why the live section is still empty:
- raw live SQLite data can expose wallet and counterparty information
- the project is still building the reporting path for safe public aggregation
- a live result with too few resolved trades would be noisy and easy to misread

Until enough real trades resolve and a sanitized report is available, live performance is a placeholder rather than a marketing number.

## Fast-Trade Research Status

`FAST_TRADE_EDGE_ANALYSIS.md` currently reports `REJECT ALL` for the monitored short-horizon strategy set. The latest checked-in artifact is still the March 7, 2026 run.

Current structural-alpha gate status:
- A-6 March 9 edge scan: `0` executable opportunities below the `0.95` gate
- B-1 March 9 audit: `0` deterministic template pairs in the first `1,000` allowed markets
- Promotion status: none

That result belongs in the performance section because rejected strategies are also performance evidence. They show where the edge did not survive cost, calibration, or sample-size scrutiny.

## Disclaimers

- Backtests are not live performance.
- Simulations are not live performance.
- A high backtest win rate can still fail live because of fill quality, fee drag, data lag, or regime shift.
- The public docs deliberately avoid spinning the numbers. If a section is blank, it is blank for a reason.
