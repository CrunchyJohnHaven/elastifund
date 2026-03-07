# Edge Discovery System (Polymarket BTC Up/Down)

This is the canonical root-level technical document for the current edge research engine.

## 1. What this system is

This system is a continuous research and validation pipeline focused on Polymarket BTC direction markets in the Chainlink resolution cluster (5m, 15m, 4h), with 15-minute edges as the main target.

Its job is to:
1. Collect real market and spot data.
2. Generate multiple competing edge hypotheses.
3. Backtest with realistic execution/cost assumptions.
4. Reject weak or fake edges quickly.
5. Update `FastTradeEdgeAnalysis.md` automatically.

It is intentionally not a live trading bot.

## 2. Current operational status

At the time of this document update:
1. The full pipeline is implemented.
2. `--run-once` executes end-to-end and writes reports.
3. Continuous mode exists, but it runs only when explicitly started.
4. Current recommendation from latest run is `REJECT ALL` due to insufficient signal count and weak post-cost robustness.

## 3. How to run it

## 3.1 One cycle (collect + evaluate + report)

```bash
cd /Users/johnbradley/Desktop/Elastifund
python3 src/main.py --run-once --log-level INFO
```

## 3.2 Continuous mode (every 30 minutes)

```bash
cd /Users/johnbradley/Desktop/Elastifund
python3 src/main.py --log-level INFO
```

Important: closing the terminal stops the process. For true persistence, run under a supervisor (e.g., `tmux`, `screen`, `launchd`, `systemd`, or a process manager).

## 4. Data pipeline architecture

Code: `src/data_pipeline.py`

Data sources:
1. Gamma API (`/markets`) for market metadata + prices.
2. Data API (`/trades`) for trade tape.
3. CLOB API (`/book`) for order book snapshots when available.
4. Binance spot REST fallback for BTC reference price.

Collection behavior:
1. Discovers candidate slugs from recent trades plus deterministic window probing.
2. Filters to Chainlink-cluster BTC up/down markets.
3. Stores market snapshots, trade rows, and BTC spot points into SQLite.
4. Normalizes timestamps to UTC.
5. Filters bad ticks and logs data-quality events.
6. Writes rolling cache and reproducible database snapshots.

Storage:
1. SQLite DB at `data/edge_discovery.db`.
2. Snapshot artifacts under `data/snapshots/`.
3. Collector logs under `logs/edge_discovery.log`.

Known data caveat:
1. CLOB book endpoint returns many 404 token IDs for some markets, so order-book coverage is partial.
2. Strategy layer falls back to trade-flow imbalance when book snapshots are unavailable.

## 5. Feature engineering

Code: `src/feature_engineering.py`

Feature groups:
1. Price state: return since open, short return, range position.
2. Volatility/drift: realized vol windows (30m/1h/2h), drift estimate.
3. Microstructure: trade count, buy/sell imbalance, optional book imbalance.
4. Wallet flow: early-window wallet cohort bias with historical wallet scoring.
5. Time structure: hour, weekday, prior-window return.
6. Cross-timeframe constraints: inner-window resolved bias for 5m->15m and 15m->4h structure.
7. Basis lag proxy: Binance move vs market repricing proxy.

Target label:
1. `UP`/`DOWN` based on resolved market outcome where available.
2. Unresolved markets are used for live signal generation but not outcome scoring.

## 6. Strategy and model layer

Code:
1. Strategies: `src/strategies/*.py`
2. Models: `src/models/*.py`

Implemented hypothesis families:
1. Residual Horizon Fair Value (closed-form primary model).
2. Volatility Regime Mismatch.
3. Cross-Timeframe Constraint Violation.
4. Chainlink vs Binance Basis Lag.
5. Wallet Flow Momentum.
6. Mean Reversion after Extreme Move.
7. Time-of-Day Session Effect.
8. Order Book / Flow Imbalance.
9. ML Feature Discovery scanner.

Model competition includes:
1. Naive market-probability baseline.
2. Closed-form fair value model.
3. Logistic classifier.
4. Tree baseline.
5. XGBoost wrapper (fallback to tree if unavailable).
6. Monte Carlo GBM.
7. Monte Carlo regime switching.
8. Historical bootstrap resampling.

Monte Carlo engine supports:
1. GBM.
2. Jump diffusion.
3. Regime-conditioned volatility.
4. Historical resampling mode.
5. Deterministic seeding.

## 7. Backtesting and validation rules

Code: `src/backtest.py`, `src/hypothesis_manager.py`

Backtest realism controls:
1. Maker/taker scenario modeling.
2. Taker fee formula.
3. Spread and slippage assumptions.
4. Execution delay assumption.
5. Position sizing baseline.
6. Cost stress testing (+/-20%).
7. Calibration error measurement.
8. Drawdown and regime-decay checks.

Statistical outputs:
1. Signals, win rate, EV maker/taker.
2. Wilson confidence interval.
3. Approximate p-value.
4. Sharpe-like metric.
5. Kelly fraction.

Automated rejection discipline (kill rules):
1. Too few signals.
2. Negative out-of-sample expectancy.
3. Collapse under worse cost assumptions.
4. Poor calibration.
5. Instability under parameter perturbation.
6. Regime decay.

## 8. Reporting and artifacts

Code: `src/reporting.py`

Primary human output:
1. `FastTradeEdgeAnalysis.md` (root-level source of truth).

Run artifacts:
1. `reports/run_<timestamp>_metrics.json`
2. `reports/run_<timestamp>_summary.md`
3. Optional chart files (or chart-unavailable marker if plotting deps are missing)

Audit checkpoints:
1. `logs/Audit_A_DataPipeline.md`
2. `logs/Audit_B_Baselines.md`
3. `logs/Audit_C_MonteCarlo.md`
4. `logs/Audit_D_WalkForward.md`
5. `logs/Audit_E_ReportAutomation.md`

## 9. What “success” means

A strategy is only a real promotion candidate if it demonstrates all of the following:
1. Enough out-of-sample sample size (not a tiny window artifact).
2. Positive expectancy after realistic costs.
3. Stability across time/regime slices.
4. Acceptable calibration.
5. Survival under cost and parameter stress.
6. Better-than-baseline model competition performance.

Practical promotion ladder:
1. Under investigation: low sample or weak stats.
2. Candidate: enough sample + positive post-cost signal.
3. Validated: strong stats and robustness.
4. Tiny live test: only after validated criteria are met repeatedly.

## 10. Expectation of success (realistic)

This system is designed to maximize learning speed and reject false edges quickly.

Realistic expectation:
1. Short term (first days): high likelihood of `REJECT ALL` or `CONTINUE RESEARCH` while data accrues.
2. Medium term (multi-day continuous collection): possible emergence of candidate edges, but many will fail cost/robustness filters.
3. True validated edge discovery is possible but statistically hard; failure to find one is also a valid result.

Important interpretation:
1. “No validated edge found” is not a system failure.
2. It is an evidence-based conclusion that this market/horizon may be efficient for tested strategy classes.

## 11. Known limitations right now

1. Data horizon is still short, so most strategies fail minimum-signal thresholds.
2. CLOB availability is inconsistent for some token IDs.
3. Optional ML/plot dependencies are not fully installed in this environment, so certain outputs use fallbacks.
4. Continuous uptime requires process supervision outside a single terminal session.

## 12. Near-term next steps (recommended)

1. Run continuous mode for at least 5-14 days to accumulate resolved 15m sample size.
2. Install optional dependencies (`numpy`, `pandas`, `scikit-learn`, `xgboost`, `matplotlib`) for richer model competition and charts.
3. Add a supervisor (`tmux`/`launchd`/`systemd`) to guarantee uninterrupted collection.
4. Reassess promotion status only after sample-size thresholds are met.
