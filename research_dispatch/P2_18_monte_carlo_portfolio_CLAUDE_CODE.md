# P2-18: Monte Carlo Portfolio Simulation
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** Confidence intervals on ARR

## Task
Build a proper Monte Carlo simulation that:
1. Samples from our empirical distribution of trade outcomes (532 markets)
2. Simulates 10,000 portfolio paths over 1 year
3. For each path: randomly draw trades, apply Kelly sizing, track cumulative P&L
4. Compute: median ARR, 5th percentile (worst case), 95th percentile (best case)
5. Probability of ruin (capital goes to $0)
6. Probability of doubling capital in 3/6/12 months
7. Generate equity curve charts (matplotlib)
8. Test at different capital levels: $75, $1K, $10K, $100K

This gives investors a realistic range of outcomes, not a single point estimate.
