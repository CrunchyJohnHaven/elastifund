# Fast Trade Edge Analysis
**Last Updated:** 2026-03-09T00:20:02+00:00
**System Status:** running
**Data Window:** 2026-03-07T14:53:53+00:00 to 2026-03-07T19:08:13+00:00

## Data Coverage
- 15-min markets observed: 29 (22 resolved)
- 5-min markets observed: 40
- 4-hour markets observed: 7
- BTC price data points: 18
- Trade records: 2882
- Unique wallets tracked: 1607

## Current Recommendation
REJECT ALL

Reasoning: All active hypotheses failed kill rules or expectancy tests.

---

## VALIDATED EDGES (p < 0.01, n > 300)
None currently validated.

---

## CANDIDATE EDGES (p < 0.05, n > 100)
No candidate edges currently meet thresholds.

---

## UNDER INVESTIGATION (n < 100)
No hypotheses in investigation bucket.

---

## REJECTED
| Strategy | Signals | Win Rate | Reason for Rejection |
|----------|---------|----------|----------------------|
| Residual Horizon Fair Value | 8 | 50.00% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions; Poor calibration |
| Chainlink vs Binance Basis Lag | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Wallet Flow Momentum | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Informed Flow Convergence (Maker-Only) | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Time-of-Day Session Effect | 12 | 66.67% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions |
| Cross-Timeframe Constraint Violation | 25 | 8.00% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions; Poor calibration |
| Post-Extreme Mean Reversion | 1 | 0.00% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions; Poor calibration |
| Order Book / Flow Imbalance | 5 | 0.00% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions; Poor calibration |
| Volatility Regime Mismatch | 34 | 32.35% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions; Poor calibration; Monotonic or recent performance decay |

---

## NEXT BEST HYPOTHESIS EXPLORATION
- Hypothesis: Early Informed-Flow Convergence + Stale Price Filter (Maker-Only)
- Verdict: CONTINUE_DATA_COLLECTION
- Summary: Best variant is close but not validated yet (Bootstrap Cohort). Keep in paper mode while increasing resolved sample.
- Variants tested: 10
- Variants passing strict gates: 0
- Best variant: Bootstrap Cohort
- 15m feature rows: 87
- 15m rows with trade-flow data: 8
- 15m rows with wallet-convergence data: 16
- 15m rows using wallet fallback mode: 8
- Avg wallet trades per wallet-signal row: 2.94
- Shadow tracker (variants): total=10, resolved=0, open=10

### Pass/Fail Gates
- Min signals: 25
- Max p-value: 0.25
- Max calibration error: 0.2
- Min EV maker: 0.0
- Min low-fill EV maker: 0.0

| Variant | Raw Signals | Resolved Signals | Win Rate | EV Maker | EV Taker | P-value | Calibration | Fallback Share | Gate | Gate Failures |
|---------|-------------|------------------|----------|----------|----------|---------|-------------|----------------|------|---------------|
| Bootstrap Cohort | 5 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 40.00% | watch | no_resolved_outcomes_for_generated_signals |
| Bootstrap Fast | 5 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 40.00% | watch | no_resolved_outcomes_for_generated_signals |
| Balanced | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| Fast/Strict Consensus | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| Fast/Low Threshold | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| High Quality Wallets | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| More Signals | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| Conservative Gap | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| Ultra-Early | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |
| Quality + Gap | 0 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.00% | fail | resolved_signals<25, ev_maker<=0, p_value>0.25, calibration>0.2, maker_edge_not_robust_at_low_fill |

---

## MODEL COMPETITION TABLE
| Model | OOS Expectancy | Sharpe | Calibration Error | Beats Baseline? |
|-------|---------------|--------|-------------------|-----------------|
| No model comparison available | 0.0 | 0.0 | 0.0 | False |

---

## ML-DISCOVERED FEATURE CANDIDATES
No new feature candidates flagged.

---

## REALITY CHECK
- Slippage assumption: 0.005
- Spread assumption: 0.02
- Maker fill rate assumption: 0.6
- Maker fill model: trade_through
- Confidence calibration: sequential_bayes_isotonic
- Execution delay assumption: 2
- Data quality issues: binance_fallback_failed, binance_ticker_failed, binance_fallback_failed, binance_ticker_failed, missing_market_snapshots
- Reasons apparent edge may be fake: data leakage from timestamp alignment, execution delay underestimation, selection bias from low-liquidity windows, regime instability

---

## NEXT ACTIONS
- Increase data collection horizon to reach >=100 signals for top strategy.
- Tighten entry thresholds or drop low-confidence signals for top strategy.
- Retune confidence calibration bins/prior and re-evaluate top strategy calibration drift.
- Promote top informed-flow convergence variant to focused shadow tracking until it clears signal-count and p-value gates.
- Run ML scanner on next 6-hour interval for new feature proposals.
- Kill conditions: reject if OOS expectancy <= 0 or cost-stress flips sign
- Promotion conditions: n>=300, p<0.01, positive taker EV under stress

---

## CHANGE LOG
| Timestamp | Change |
|-----------|--------|
| 2026-03-09T00:20:02+00:00 | Ran collector + feature refresh + full strategy competition cycle. |
| 2026-03-09T00:20:02+00:00 | Updated hypothesis rankings with kill-rule evaluation and cost stress tests. |
| 2026-03-09T00:20:02+00:00 | Executed informed-flow convergence variant explorer with maker-fill sensitivity checks. |
| 2026-03-09T00:20:02+00:00 | Enabled strict trade-through maker fill validation from observed trade tape where available. |
| 2026-03-09T00:20:02+00:00 | Applied sequential confidence calibration in backtest scoring and diagnostics. |
| 2026-03-09T00:20:02+00:00 | Regenerated analysis markdown and run-specific artifacts. |