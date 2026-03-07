# P0-32: Combined Backtest Re-Run (All Improvements Stacked)
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — This is the #1 most important task. Nothing else matters until we know the combined impact.
**Expected ARR Impact:** Determines real expected performance — could be +50-100% over baseline

## Background
Since the original 532-market backtest (64.9% win rate, Brier 0.239), we've implemented SIX improvements:
1. Temperature-scaling calibration layer (maps raw Claude estimates to corrected probabilities)
2. Asymmetric edge thresholds (YES: 15%, NO: 5%)
3. Category-based market routing (skip crypto/sports/fed_rates)
4. Taker fee subtraction from edge calculations
5. Base-rate-first prompt with explicit debiasing
6. LLM + market consensus ensemble weighting (Bridgewater approach)

We tested some variants individually ("Calibrated + Selective" hit 83.1%), but we've NEVER run the full stack together. We don't know if improvements compound or cancel each other.

## Task

Re-run the 532-market backtest with ALL six improvements applied simultaneously:

```bash
cd /Users/johnbradley/Desktop/Quant/backtest
```

1. **Load existing data:** Read `data/backtest_results.json` and `data/calibrated_backtest.json` — do NOT re-query Claude API. Use cached predictions.

2. **Apply full improvement stack in order:**
   a. Take raw Claude probability estimate from cache
   b. Apply temperature-scaling calibration correction (from `calibration.py`)
   c. Apply category routing filter (exclude crypto/sports/fed_rates markets — check market question text for keywords)
   d. Compute ensemble probability: `ensemble = 0.3 * calibrated_claude + 0.7 * market_price` (use original market price from historical data)
   e. Compute edge: `edge = ensemble_prob - market_price`
   f. Apply asymmetric thresholds: trade only if edge > 15% for buy_yes OR edge > 5% for buy_no
   g. Subtract taker fees from edge: `net_edge = edge - fee(market_price)` where `fee(p) = p*(1-p)*0.025` for crypto, 0.007 for sports, 0 for politics/weather
   h. Apply quarter-Kelly position sizing: `position = 0.25 * bankroll * (b*p - q) / b` where b = (1-price)/price, p = ensemble_prob, q = 1-p. Min $1, max 25% of bankroll per position.

3. **Output a comprehensive comparison table:**

| Metric | Original Baseline | Calibrated Only | Full Stack (NEW) |
|--------|-------------------|-----------------|------------------|
| Markets eligible | | | |
| Trades taken | | | |
| Win rate | | | |
| Brier score | | | |
| Total P&L ($) | | | |
| Avg P&L/trade | | | |
| Max drawdown | | | |
| Sharpe ratio | | | |
| Buy YES win rate | | | |
| Buy NO win rate | | | |

4. **Sensitivity analysis:** Also run with ensemble weights 0.2/0.4/0.5 for Claude to find optimal.

5. **Save results** to `data/full_stack_backtest.json` and update `STRATEGY_REPORT.md` with new numbers.

6. **Generate updated charts** — at minimum: new equity curve, new calibration plot, new strategy comparison bar chart.

## Critical Check
If the full-stack win rate is LOWER than baseline (64.9%), something is wrong — the improvements may be conflicting. Report this immediately with diagnostic breakdown of where the signal is being lost.

## Expected Outcome
- Single authoritative number for "what is our real expected performance with all improvements"
- Updated ARR projections for investor materials
- Definitive answer on whether improvements compound or conflict
