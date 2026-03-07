# P0-65: Live vs Backtest Scorecard with Statistical Significance Testing
**Tool:** COWORK
**Status:** READY
**Priority:** P0 — If the backtest doesn't hold live, nothing else matters. This is the single most important confidence metric.
**Expected ARR Impact:** Confidence validation (determines if all other ARR projections are real)

## Prompt (paste into Cowork)

```
Read COMMAND_NODE.md in the selected folder for full project context. Then read STRATEGY_REPORT.md and the backtest results.

I need you to build a LIVE VS BACKTEST SCORECARD as a .docx. This is the most important document in the entire project — it determines whether our backtest projections are real.

CURRENT STATE:
- 532-market backtest completed with CalibrationV2 (Platt scaling)
- Paper trading live on VPS (161.35.24.142)
- Paper trades stored in paper_trades.json
- Backtest metrics: 68.5% win rate (calibrated), Brier 0.217, avg P&L +$0.74/trade

BUILD THIS DOCUMENT:

1. SIDE-BY-SIDE COMPARISON TABLE:
   | Metric | Backtest | Live (Paper) | Δ | Within Tolerance? |
   For every key metric:
   - Win rate (overall, YES, NO)
   - Brier score
   - Avg P&L per trade
   - Signal generation rate (signals/cycle)
   - Edge distribution (mean, median, std of |estimated - market|)
   - Category breakdown (win rate per category)
   - Resolution time distribution
   - Capital velocity

2. STATISTICAL SIGNIFICANCE TESTING:
   For each metric, answer: "Do we have enough trades to trust this number?"
   - Use binomial confidence intervals for win rate
   - Use bootstrap confidence intervals for Brier and P&L
   - Calculate: "We need N more trades to detect a 5% win rate difference at 95% confidence"
   - If we have <30 closed trades: explicitly state that NO metric is statistically significant yet

3. DIVERGENCE ALERTS:
   Flag any metric where live deviates >10% from backtest in RED
   Flag any metric where live is BETTER than backtest in GREEN (possible overfit in the other direction)
   For each flagged metric: diagnose potential cause + recommended action

4. BACKTEST OVERFIT ASSESSMENT:
   Honestly answer:
   - Is CalibrationV2 (Platt scaling) overfit to the 532-market dataset?
   - What's the gap between in-sample and out-of-sample Brier? (We have this: 0.205 vs 0.245)
   - Is the 0.040 gap concerning? What does it imply about live performance?
   - What's the minimum number of live trades we need before we can trust the numbers?

5. GO/NO-GO TRAFFIC LIGHT:
   Based on available data, give a clear verdict:
   🟢 GREEN = Backtest is holding, proceed to live trading
   🟡 YELLOW = Inconclusive, need more data (specify how much)
   🔴 RED = Backtest is diverging, investigate before going live

6. INVESTOR READINESS ASSESSMENT:
   - Can we credibly share these numbers with investors right now?
   - What numbers need to improve before investor conversations?
   - Draft a 2-paragraph "performance update" suitable for investor communication

OUTPUT: Professional .docx with tables, conditional formatting descriptions, and clear actionable recommendations. This goes to investors — it needs to look credible and honest.

Be brutally honest. Overpromising kills credibility. If the data says we don't know yet, say that clearly.

SOP: After completing this task, review COMMAND_NODE.md, STRATEGY_REPORT.md, and INVESTOR_REPORT.md for any numbers that need updating based on your findings.
```
