# P0-66: Monte Carlo v2 — Ensemble Projections + Realistic Assumptions
**Tool:** COWORK
**Status:** READY
**Priority:** P0 — Current Monte Carlo uses assumptions that are too optimistic. Investors will poke holes. Need stress-tested projections.
**Expected ARR Impact:** Confidence (investor-grade projections that survive scrutiny)

## Prompt (paste into Cowork)

```
Read COMMAND_NODE.md in the selected folder for full project context. Also read monte_carlo_simulation_design.md and STRATEGY_REPORT.md.

Our current Monte Carlo simulation shows:
- $75 starting: median +1,124% annual return, 0% probability of loss
- $10,000 starting: median +269% annual return, 0% probability of loss
- 10,000 paths, 12 months

These numbers look too good. Sophisticated investors will ask hard questions. I need a STRESS-TESTED Monte Carlo v2.

BUILD THIS AS A .XLSX WORKBOOK WITH MULTIPLE SHEETS:

SHEET 1: ASSUMPTION AUDIT
List EVERY assumption in the current Monte Carlo model. For each:
- What the model assumes
- Why it might be wrong
- What happens to returns if it's wrong
- Suggested realistic adjustment

Key assumptions to challenge:
- Constant 68.5% win rate (will it hold live? what if it's 60%?)
- 5 trades per day (what if liquidity drops? what if only 2?)
- Independent trades (what about correlated political markets?)
- $0.74 avg P&L per trade (what if slippage cuts this to $0.50?)
- No market impact (what if our orders move the price at $50K+ capital?)
- Taker fees at current rate (what if Polymarket increases fees?)
- Constant edge (what if competition erodes it by 20% per quarter?)
- No black swan events (what if Polymarket gets shut down?)

SHEET 2: SCENARIO MATRIX
Run Monte Carlo (10,000 paths, 12 months) for EACH scenario:

| Scenario | Win Rate | Trades/Day | Avg P&L | Fee Rate | Edge Decay |
|----------|----------|------------|---------|----------|------------|
| Best case | 73% | 8 | $0.90 | 1% | 0% |
| Base case (backtest) | 68.5% | 5 | $0.74 | 2% | 0% |
| Conservative | 63% | 3 | $0.50 | 2% | 10%/qtr |
| Pessimistic | 58% | 2 | $0.30 | 3% | 15%/qtr |
| Worst case | 55% | 1 | $0.15 | 3% | 20%/qtr |

For each scenario at EACH capital level ($2K, $5K, $10K, $25K, $50K):
- Median final capital
- 5th percentile (worst 5%)
- 95th percentile (best 5%)
- Max drawdown (median and 95th percentile)
- P(breakeven) — probability of at least breaking even
- P(double) — probability of doubling capital
- P(ruin) — probability of losing >50%
- Months to double (median)

SHEET 3: EDGE DECAY MODELING
The competitive landscape is intensifying (OpenClaw $1.7M, bots proliferating).
Model what happens if our edge decays over time:
- 0% decay (optimistic — edge is structural like favorite-longshot bias)
- 5% quarterly decay (mild — new competitors gradually enter)
- 10% quarterly decay (moderate — competition + fee increases)
- 20% quarterly decay (aggressive — alpha decay similar to traditional quant)
- When does each scenario cross the breakeven point?
- What's our "edge half-life" under each assumption?

SHEET 4: CAPACITY ANALYSIS
At what capital level does market impact become a problem?
- Model: if we take >10% of a market's liquidity, we move the price
- Average Polymarket liquidity per market: ~$5K–$50K
- At $2K total capital: no impact
- At $10K: might impact thin markets
- At $50K: likely impacting most markets
- At $100K: significant market impact on all but largest markets
- What's the capacity ceiling for our strategy?

SHEET 5: INVESTOR PRESENTATION NUMBERS
The HONEST numbers we present to investors:
- Use the CONSERVATIVE scenario (not base case)
- Show the range (5th to 95th percentile)
- Include max drawdown expectations
- Lead with: "expect to lose money in some months"
- Show: "breakeven expected by month X at Y capital"
- Include the capacity ceiling as a natural AUM limit

FORMAT:
- Each sheet with clean headers, conditional formatting descriptions
- Charts described where relevant (I'll generate them from the data)
- All formulas visible so investors can audit

Be CONSERVATIVE in the presentation numbers. It is much better to underpromise and overdeliver than the reverse. Investors who lose money don't come back.

SOP: After completing this task, UPDATE COMMAND_NODE.md (increment version) and refresh the Monte Carlo numbers in INVESTOR_REPORT.md and STRATEGY_REPORT.md.
```
