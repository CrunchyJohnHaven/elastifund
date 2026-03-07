# P2-14: Risk Management Framework
**Tool:** COWORK
**Status:** READY
**Expected ARR Impact:** Risk reduction (protects capital)

## Prompt for Cowork

```
Design a comprehensive risk management framework for a prediction market trading bot:

Current setup:
- $75 starting capital (expanding to $10K+ with investors)
- $2 per trade, up to 34 concurrent positions
- 64.9% win rate (backtest)
- 5-8 trades per day

Need:
1. Maximum drawdown limits (daily, weekly, monthly)
2. Position concentration limits (max % in single market, category, timeframe)
3. Stop-loss rules for the portfolio
4. Correlation management (avoid too many correlated positions)
5. Capital reservation (how much to keep as cash buffer)
6. Scaling rules as capital increases ($75 → $1K → $10K → $100K)
7. Circuit breakers (when to stop trading entirely)
8. How to handle investor capital differently from personal capital
9. What happens during extreme events (market crash, API outage)?
10. Stress testing methodology

Provide specific numeric thresholds and Python pseudocode for implementation.
```
