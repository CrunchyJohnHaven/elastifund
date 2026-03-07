# Day 7: February 22, 2026 — Calibration Changes Everything

## What the Agent Did Today

Applied Platt scaling calibration to Claude's probability estimates and re-ran the 532-market backtest.

## The Results

| Metric | Before Calibration | After Calibration |
|--------|-------------------|------------------|
| Win rate | 64.9% | **68.5%** |
| Brier score | 0.2391 | **0.2171** |
| Avg P&L per trade | +$0.60 | **+$0.74** |
| Buy YES win rate | 55.8% | 63.3% |
| Buy NO win rate | 76.2% | 70.2% |

Calibration improved win rate by 3.6 percentage points. The Platt scaling parameters: A=0.5914, B=-0.3977. What this means in practice: when Claude says 90%, we correct it to 71%. When Claude says 80%, we correct it to 60%. The AI is systematically overconfident, and now we have the correction curve.

## What I Built Today

- Platt scaling calibration module (`calibration.py`)
- Category-specific calibration (`category_calibration.py`) — different correction curves for politics vs weather vs economics
- Strategy variant testing framework (`strategy_variants.py`) — tests 10+ strategy configurations automatically
- Out-of-sample validation: 70/30 temporal split ensures we're not overfitting

## What I Learned

Calibration is the single highest-impact improvement we can make. The academic literature says this (Bridgewater's AIA Forecaster used Platt scaling to match superforecasters), and our data proves it. A 3.6% win rate improvement on 372 tradeable signals is significant.

But here's the honest part: we validated on 160 out-of-sample markets. That's enough for directional confidence but not enough for statistical certainty. The OOS Brier improved from 0.2862 to 0.2451 — a real improvement, but the confidence interval is wide. We need more data.

The category-specific calibration is even more promising: overall Brier went from 0.1561 to 0.1329, with a 4.6% improvement on geopolitical markets. Different categories have different bias profiles, and correcting for them individually works better than a single global correction.

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | $0 |
| Strategies tested | 3 (baseline, calibrated, category-calibrated) |
| Tests passing | 34 |
| Research dispatches | 15 |

## Tomorrow's Plan

Implement Kelly criterion position sizing. Our backtest uses flat $2 bets, but Kelly should dynamically size based on edge confidence. The Monte Carlo simulations suggest Kelly could improve returns by 300%+ over flat sizing.

---

*Tags: #strategy-deployed #research-cycle*
