# P0-01: Fix Claude Calibration with Post-Hoc Correction
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +30-50% (biggest single improvement)

## Problem
Our backtest shows Claude is systematically overconfident on YES:
- Says 90%+ → actual 63% (off by 32%)
- Says 70-80% → actual 53% (off by 22%)
- buy_no wins 76% vs buy_yes 56%

## Research Update (2026-03-05, from P0-04)
GPT-4.5 research confirms: **Temperature scaling is the best post-hoc method for LLMs** — preserves accuracy, needs little data, significantly reduces ECE. Isotonic regression risks overfitting on our limited 532-market dataset. Platt scaling is less flexible. **Recommendation: Implement temperature scaling first**, fall back to isotonic only if TS underperforms.

## Task
Using the backtest calibration data in `/Users/johnbradley/Desktop/Quant/backtest/data/backtest_results.json`, build a **post-hoc calibration layer** that maps Claude's raw probability to a corrected probability. **Primary method: temperature scaling. Secondary: isotonic regression or Platt scaling.**

Specifically:
1. Read the calibration buckets from backtest results
2. Build a correction function: `corrected_prob = calibrate(raw_prob)`
3. Re-run the backtest with corrected probabilities
4. Measure improvement in Brier score and win rate
5. If improved, integrate into the live trading pipeline

The calibration data:
```
Claude est → actual YES rate:
0.0-0.1: 15.7%
0.1-0.2: 12.0%
0.2-0.3: 22.0%
0.3-0.4: 62.5%
0.4-0.5: 41.7%
0.5-0.6: 46.6%
0.6-0.7: 45.5%
0.7-0.8: 52.8%
0.8-0.9: 63.2%
0.9-1.0: 63.2%
```

Expected outcome: Brier score drops from 0.239 to <0.20, win rate increases to 70%+.
