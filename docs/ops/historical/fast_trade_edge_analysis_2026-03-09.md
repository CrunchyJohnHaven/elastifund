# Fast Trade Edge Analysis
**Last Updated:** 2026-03-09T01:34:49+00:00
**System Status:** stopped
**Data Window:** 2026-03-07T14:53:53+00:00 to 2026-03-09T01:35:02+00:00
**Fresh Pull:** 2026-03-09T01:58:34.672967+00:00
**Instance Version:** 2.8.0

## Data Coverage
- Active markets pulled: 7050
- Fast BTC markets discovered: 22
- Threshold sensitivity source: fast_market_discovery
- Threshold-universe markets pulled: 22
- Markets in price window (threshold universe, 0.10-0.90): 7
- Markets <24h in threshold universe: 6
- Markets <48h in threshold universe: 6
- Basic-filter markets in threshold universe (<48h, 0.10-0.90): 6
- Markets passing current category gate in threshold universe: 0
- 15-min markets observed: 30 (21 resolved)
- 5-min markets observed: 38
- 4-hour markets observed: 8
- BTC price data points: 19
- Trade records: 2858
- Unique wallets tracked: 1627

## Threshold Sensitivity
| Threshold Profile | YES | NO | Markets Theoretically Tradeable |
|---|---|---|---|
| Current (conservative) | 0.15 | 0.05 | 0 |
| Aggressive | 0.08 | 0.03 | 6 |
| Wide open | 0.05 | 0.02 | 6 |

## Current Recommendation
REJECT ALL

Reasoning: All active hypotheses failed kill rules or expectancy tests.
Threshold note: YES-side reachability moves 0 -> 6 -> 6 across the current/aggressive/wide-open profiles for the selected threshold universe.
Refresh note: Fast-market discovery surfaced 22 BTC markets; 6 pass the basic <48h and 0.10-0.90 filters. The current profile leaves 0 after the category gate, while aggressive and wide-open expand that to 6 and 6. YES-side trigger reachability within the BTC fast-market universe moves 0 to 6 to 6, but the latest strategy pipeline still reports REJECT ALL. The broad flattened Gamma pull still surfaced 7050 open markets across 500 events, but that feed is not the threshold universe for the BTC fast-market lane. No validated or candidate edges were promoted by the latest research cycle, so lower thresholds do not unlock a real dispatchable trade set. All active hypotheses failed kill rules or expectancy tests.

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
| Time-of-Day Session Effect | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Chainlink vs Binance Basis Lag | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Wallet Flow Momentum | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Informed Flow Convergence (Maker-Only) | 0 | 0.00% | Too few signals (<50); Poor calibration |
| Cross-Timeframe Constraint Violation | 22 | 4.55% | Too few signals (<50); Negative out-of-sample expectancy; Collapses under worse cost assumptions; Poor calibration |
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
- 15m feature rows: 79
- 15m rows with trade-flow data: 7
- 15m rows with wallet-convergence data: 13
- 15m rows using wallet fallback mode: 8
- Avg wallet trades per wallet-signal row: 2.31
- Shadow tracker (variants): total=6, resolved=0, open=6

### Pass/Fail Gates
- Min signals: 25
- Max p-value: 0.25
- Max calibration error: 0.2
- Min EV maker: 0.0
- Min low-fill EV maker: 0.0

| Variant | Raw Signals | Resolved Signals | Win Rate | EV Maker | EV Taker | P-value | Calibration | Fallback Share | Gate | Gate Failures |
|---------|-------------|------------------|----------|----------|----------|---------|-------------|----------------|------|---------------|
| Bootstrap Cohort | 3 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 66.67% | watch | no_resolved_outcomes_for_generated_signals, excess_fallback_signals |
| Bootstrap Fast | 3 | 0 | 0.00% | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 66.67% | watch | no_resolved_outcomes_for_generated_signals, excess_fallback_signals |
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

## Market Universe Snapshot
| Category | Count | Avg YES Price | <24h Resolution |
|---|---|---|---|
| politics | 2882 | 0.7068 | 0 |
| weather | 10 | 0.1173 | 0 |
| economic | 390 | 0.4863 | 0 |
| crypto | 110 | 0.2782 | 0 |
| sports | 3063 | 0.3944 | 0 |
| other | 595 | 0.7993 | 0 |

---

## A-6 Structural Scan
- Status: blocked | allowed events=563 | qualified=57 | executable=0
- Live scanner: status=active | candidate markets=58 | executable=0 | violations=4
- Blockers: maker_fill_proxy_unmeasured, violation_half_life_below_minimum, public_audit_zero_executable_constructions_below_0.95_gate

---

## Wallet-Flow Status
Ready: True, scored wallets=80, status=ready

---

## REALITY CHECK
- Slippage assumption: 0.005
- Spread assumption: 0.02
- Maker fill rate assumption: 0.6
- Maker fill model: trade_through
- Confidence calibration: sequential_bayes_isotonic
- Execution delay assumption: 2
- Data quality issues: binance_fallback_failed, binance_ticker_failed, missing_market_snapshots, missing_market_snapshots, missing_market_snapshots
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
| 2026-03-09T01:34:49+00:00 | Ran collector + feature refresh + full strategy competition cycle. |
| 2026-03-09T01:34:49+00:00 | Updated hypothesis rankings with kill-rule evaluation and cost stress tests. |
| 2026-03-09T01:34:49+00:00 | Executed informed-flow convergence variant explorer with maker-fill sensitivity checks. |
| 2026-03-09T01:34:49+00:00 | Enabled strict trade-through maker fill validation from observed trade tape where available. |
| 2026-03-09T01:34:49+00:00 | Applied sequential confidence calibration in backtest scoring and diagnostics. |
| 2026-03-09T01:34:49+00:00 | Regenerated analysis markdown and run-specific artifacts. |