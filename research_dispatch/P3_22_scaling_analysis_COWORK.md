# P3-22: Scaling Analysis — $75 → $10K → $100K → $1M
**Tool:** COWORK
**Status:** READY

## Prompt

```
Analyze how our prediction market trading strategy scales with capital:

Current performance at $75 capital:
- 64.9% win rate, $2 per trade, 5 trades/day
- ARR: +264% (base case)

Questions:
1. At $10K: Can we still get filled on $50 trades? $200 trades? What's Polymarket's typical order book depth?
2. At $100K: Do we move the market with our orders? What's the market impact?
3. At $1M: Is Polymarket even liquid enough? Or do we need to expand to Kalshi, Metaculus, PredictIt?
4. How do fees scale? Any volume discounts on Polymarket?
5. Does our edge decrease with more capital? (standard for quant strategies)
6. What's the maximum capital this strategy can absorb before returns degrade?
7. If we have investors, what's the optimal fund structure? (LP/GP, management fee + carry)
8. Comparison to typical hedge fund returns at different AUM levels
```
