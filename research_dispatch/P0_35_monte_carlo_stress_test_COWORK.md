# P0-35: Monte Carlo Stress Test & Investor-Grade Risk Model
**Tool:** COWORK
**Status:** READY
**Priority:** P0 — Current Monte Carlo shows "0% ruin probability" which will destroy credibility with sophisticated investors
**Expected ARR Impact:** Indirect — investor confidence, risk management, prevents blowup

## Background
Our Monte Carlo (10,000 paths) shows median +1,124% at $75 and 0% probability of total loss. These numbers are too optimistic because they assume:
- Constant 64.9% win rate (ignores regime changes, market efficiency improving)
- Independent trades (ignores correlation between political markets, related events)
- Fixed position sizing (we're implementing Kelly which changes the dynamics)
- No slippage or execution failures
- No black swan events (platform outage, regulatory shutdown, liquidity crisis)

A sophisticated investor will immediately question these assumptions. We need stress-tested numbers BEFORE putting this in front of anyone.

## Task

Read `backtest/monte_carlo.py` and the results in `backtest/data/monte_carlo_results.json`. Then:

1. **Assumption audit:** List EVERY assumption in the current Monte Carlo model. For each:
   - Is it realistic? Rate 1-5 (1=unrealistic, 5=solid)
   - What happens if it breaks? Quantify the impact.
   - How likely is it to break in the next 12 months?

2. **Run adverse scenarios** (modify the simulation or calculate analytically):

| Scenario | Win Rate | Trades/Day | Position Size | 12-Mo Median | P(50% DD) | P(Ruin) |
|----------|----------|------------|---------------|--------------|-----------|---------|
| Base case | 64.9% | 5 | $2 flat | ? | ? | ? |
| Win rate regression | 55% | 5 | $2 flat | ? | ? | ? |
| Win rate collapse | 50% | 5 | $2 flat | ? | ? | ? |
| Liquidity crunch | 64.9% | 2 | $2 flat | ? | ? | ? |
| 10-trade losing streak | 64.9% | 5 | $2 flat | ? | ? | ? |
| Correlated losses (3 related markets fail) | 64.9% | 5 | $6 correlated | ? | ? | ? |
| Kelly sizing (quarter) | 64.9% | 5 | dynamic | ? | ? | ? |
| Kelly + win rate drop | 55% | 5 | dynamic | ? | ? | ? |
| Platform fee increase | 64.9% | 5 | $2 (net edge -2%) | ? | ? | ? |
| Combined worst-reasonable | 55% | 2 | dynamic | ? | ? | ? |

3. **Realistic drawdown analysis:**
   - P0-26 research says strategies showing 23% max drawdown may face 50-70% in practice
   - What's our realistic worst-case drawdown at $75? At $10,000?
   - How long could a drawdown last? (recovery time analysis)

4. **Create investor-grade risk metrics:**
   - Value at Risk (95% VaR, monthly)
   - Conditional VaR (Expected Shortfall)
   - Maximum drawdown duration (how many days underwater?)
   - Probability of underperforming a 5% savings account over 12 months
   - Break-even probability (P(ending capital > starting capital + infra costs))

5. **Revised Monte Carlo with realistic assumptions:**
   - Time-varying win rate (add drift term: WR decreases 0.5%/month as market becomes more efficient)
   - Trade correlation: 20% correlation between positions in same category
   - Execution failures: 10% of trades don't fill or fill at worse price
   - Quarterly regime shocks: 5% chance per quarter of 2-week period with 50% win rate
   - Include Kelly sizing dynamics

6. **Output a .docx "Risk Model & Stress Test" appendix** with:
   - Methodology explanation (clear enough for a non-quant investor)
   - All scenario results in clean tables
   - Revised Monte Carlo fan chart (conservative)
   - Clear "what could go wrong" section
   - Honest assessment: "An investor should expect X% annual return with Y% maximum drawdown in a normal year, and Z% drawdown in a bad year"

## Tone
Brutally honest. Overpromising kills credibility. Better to say "we expect 50-150% annual returns with up to 40% drawdowns" than "1,124% median with 0% ruin." The first sounds like a real fund; the second sounds like a scam.

## Expected Outcome
- Stress-tested Monte Carlo that passes the "skeptical investor sniff test"
- Revised return projections for investor materials (lower but credible)
- Clear risk metrics an investor can evaluate
- Appendix document ready to attach to investor report
