# P0-33: Live vs Backtest Performance Scorecard
**Tool:** COWORK
**Status:** READY
**Priority:** P0 — If the backtest doesn't hold live, nothing else matters.
**Expected ARR Impact:** Validation — determines whether to continue or pivot

## Background
The bot has been paper trading on the VPS (161.35.24.142) since March 5. We have 34 open positions ($2 each, $68 deployed). We need to compare whatever resolved trades exist against our backtest predictions.

## Task

1. **Pull live data from VPS:** SSH into the VPS and read:
   - `paper_trades.json` — all paper trade entries and resolutions
   - `metrics_history.json` — cycle-by-cycle metrics
   - `strategy_state.json` — tuning state and parameter history

2. **Build a side-by-side scorecard as a .docx:**

| Metric | Backtest Predicted | Live Actual | Delta | Status |
|--------|-------------------|-------------|-------|--------|
| Win rate | 64.9% | ? | | 🟢/🟡/🔴 |
| Buy YES win rate | 55.8% | ? | | |
| Buy NO win rate | 76.2% | ? | | |
| Avg P&L/trade | $0.60 | ? | | |
| Signals per cycle | 18 | ? | | |
| Trades per cycle | 17 | ? | | |
| Edge distribution | avg 25.7% | ? | | |
| Brier score | 0.239 | ? | | |

3. **Statistical significance test:**
   - How many resolved trades do we have?
   - Binomial confidence interval on live win rate
   - Is the sample large enough to draw conclusions? (need n≥50 for 95% CI within ±14%)
   - If n < 50: state "INSUFFICIENT DATA — cannot validate yet" and estimate date when we'll have enough trades based on current resolution rate

4. **Flag any metric where live deviates >10% from backtest** — explain possible causes (slippage, fill rate, market selection bias, prompt drift)

5. **Clear verdict section:**
   - "BACKTEST HOLDING" — live performance within statistical CI of backtest
   - "BACKTEST DIVERGING — [specific area]" — with root cause analysis
   - "INSUFFICIENT DATA" — with timeline to significance

6. **Actionable recommendations:** What to adjust if diverging. What to monitor if insufficient data.

## Important Notes
- If no trades have resolved yet (many positions are on future events), say so clearly. Calculate expected resolution dates from market end dates.
- Even with zero resolutions, we can analyze: signal generation rate, edge distribution, position diversity, category mix — and compare those to backtest characteristics.
- Do NOT sugarcoat. If we have zero resolved trades after days of trading, that's a data point about market resolution timing that affects our strategy.

## Expected Outcome
- Single-page .docx scorecard suitable for tracking over time
- Honest assessment of where we stand
- Specific next actions based on findings
