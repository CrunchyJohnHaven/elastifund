# What Is "Edge"? The Honest Math of Prediction Market Trading

*Part of the Elastifund Education Center — [elastifund.io/learn/what-is-edge](https://elastifund.io/learn/what-is-edge)*

---

## TL;DR (30 seconds)

"Edge" means your estimate of probability is systematically more accurate than the market price. If the market says 40% and you correctly estimate 60% over many trades, the difference is your edge. Most traders think they have an edge. The data says only 7.6% of Polymarket wallets are profitable. Less than 0.51% have earned more than $1,000.

Finding edge is hard. Proving you have edge is harder. Not fooling yourself into thinking you have edge when you don't is the hardest part of all.

---

## The Full Explanation (5 minutes)

### Edge in Plain English

Imagine a coin that lands heads 60% of the time, but a casino is offering even-money bets on it (pay $1 to win $1 on heads). You have an edge: you know the true probability is 60% but the "market" (the casino) is pricing it at 50%. Over hundreds of flips, you'll win more than you lose.

Prediction markets work the same way, except instead of a biased coin, you're estimating real-world probabilities — and instead of the casino being wrong, it's the crowd of other traders being wrong.

Your edge = Your estimated probability − Market price

If you think an event has a 70% chance but the market prices it at 55%, your edge is 15 percentage points. If you're right about your 70% estimate, you'll profit over many such trades.

**The catch:** Everyone thinks their estimate is the right one.

### Why Most People Don't Have Edge

An analysis of 72.1 million Polymarket trades (jbecker.dev, 2025-2026) revealed:

- Only **7.6%** of wallets are profitable overall
- Only **0.51%** have earned more than $1,000
- **$40 million** went to arbitrageurs in one year
- Successful bots primarily use **arbitrage and speed**, not narrative analysis

The most common source of imagined edge: "I follow the news closely and have good intuition about politics/crypto/sports." The data doesn't support this. Narrative analysis — the kind of reasoning most humans do — consistently underperforms calibrated statistical approaches.

The most common source of real edge: being faster than other participants to process public information (speed), or exploiting structural features of the market (arbitrage, fee structure, maker rebates).

### Costs Eat Edge

Even if you have a genuine edge, transaction costs can eliminate it:

**Scenario:** You have a 3% edge on crypto candle markets. You buy taker orders at mid-range prices.

- Your 3% edge
- Minus 1.56% taker fee (Polymarket crypto, max)
- = 1.44% net edge

That seems positive. But now add:
- Slippage: the price moves against you between decision and execution: ~0.5%
- Partial fills: your order isn't fully filled, reducing expected profit: ~0.3% effective drag
- Capital lockup: your money is tied up until resolution, opportunity cost: ~0.2%

Net: 1.44% - 0.5% - 0.3% - 0.2% = **0.44% net edge**. Barely positive. One unfavorable market move and you're underwater.

**The maker advantage:** If you use limit orders instead of market orders, your fee drops to 0%. Same 3% edge, same costs:
- 3% edge - 0% maker fee - 0.3% slippage - 0.2% lockup = **2.5% net edge**

This is why the 72.1M trade analysis found makers earn +1.12% excess returns and takers lose -1.12%. The fee structure is the largest determinant of profitability for most strategies.

### How We Measure Edge (and Why It's Harder Than It Sounds)

Our edge discovery pipeline tests strategy hypotheses with six automated "kill rules." A strategy must survive ALL of them:

1. **Sufficient signals (>50):** If a strategy only triggers 8 times in the test period, there isn't enough data to distinguish signal from noise. Our R1 (Residual Horizon Fair Value) was killed by this: 8 signals, 50% win rate — could be random.

2. **Positive out-of-sample expectancy:** We train on historical data and test on FUTURE data (temporal split, not random). If the strategy loses money on the test data, it's rejected — even if it looked great on training data.

3. **Cost stress survival:** Can the strategy survive if fees doubled? If not, it's fragile. Any platform fee change would kill it.

4. **Calibration accuracy (<0.2 deviation):** The strategy's confidence levels must be roughly accurate. If it says "high confidence" but wins the same rate as "low confidence," the confidence signal is noise.

5. **Parameter stability:** The strategy must produce similar results across different time windows. If it only works in February but not March, it's an artifact.

6. **No regime decay:** The strategy must not get worse over time. Alpha that's eroding is alpha that will be gone by the time you deploy it.

Any kill rule triggered = immediate rejection. No exceptions.

---

## Technical Deep Dive (30 minutes)

### Expected Value and the Kelly Connection

Edge alone doesn't tell you how much to bet. For that, you need the Kelly criterion:

```
f* = (bp - q) / b
```

Where:
- f* = optimal fraction of bankroll to bet
- b = the odds (how much you win per dollar risked)
- p = your estimated probability of winning
- q = 1 - p (probability of losing)

Example: Market price $0.40 for YES (you'd win $0.60 per $1 if YES resolves). Your estimate: 55% YES.
- b = 0.60 / 0.40 = 1.5
- p = 0.55, q = 0.45
- f* = (1.5 × 0.55 - 0.45) / 1.5 = (0.825 - 0.45) / 1.5 = 0.25

Kelly says bet 25% of your bankroll. But that's full Kelly, which is wildly aggressive. We use quarter-Kelly (6.25% of bankroll), which sacrifices some growth for much lower drawdown risk.

**The Kelly table (from our Monte Carlo simulations):**

| Kelly Fraction | Median Growth (12mo) | P(50% Drawdown) | Ruin Risk |
|----------------|---------------------|-----------------|-----------|
| Full (1×) | ~10^16× | 100% | 36.9% |
| Half (0.5×) | ~10^11× | 94.7% | ~0% |
| Quarter (0.25×) | ~10^6× | 8.0% | 0% |
| Tenth (0.1×) | ~10^2× | 0% | 0% |

Full Kelly would theoretically grow your bankroll astronomically, but the 36.9% ruin risk means you'd go bankrupt more than a third of the time. Quarter-Kelly keeps ruin at 0% while still capturing meaningful growth.

### The Favorite-Longshot Bias: Our Primary Edge

The single most robust empirical finding in prediction market research: participants overprice low-probability events and underprice high-probability events. This is the "favorite-longshot bias," documented extensively in horse racing, sports betting, and now prediction markets.

Our data confirms it:
- Buy YES win rate: 55.8%
- Buy NO win rate: **76.2%**

Why? Psychology. Humans overweight vivid, exciting, low-probability outcomes ("What if Trump tweets...?" "What if Bitcoin crashes...?"). They buy YES on these scenarios at prices above the true probability. Buying NO against these overpriced longshots has been consistently profitable in our 532-market backtest.

We exploit this with asymmetric thresholds: a 5% edge is enough to trigger a NO trade, but we require 15% edge for YES trades. This isn't theory — it's a direct response to our empirical win rate data.

### Walk-Forward Validation: The Gold Standard

The most common mistake in strategy backtesting: training and testing on the same data. If you optimize parameters on January's data and report January's performance, you've proven nothing. The strategy is guaranteed to look good on data it was optimized for.

Walk-forward validation fixes this:

1. Sort all data chronologically
2. Train on the first 70% (e.g., January-March)
3. Test on the final 30% (e.g., April-May)
4. NEVER use future data to train past estimates

Our 532-market backtest: trained on markets 1-372, validated on markets 373-532. Brier score improved from 0.2862 to 0.2451 on the HELD-OUT data. That's a real improvement, not a data artifact.

The honest caveat: 160 out-of-sample markets is enough for directional confidence but not for statistical certainty. The confidence interval is wide. More data is needed, and we're collecting it daily.

### How Professional Quants Think About Edge

Professional quantitative traders (Renaissance, DE Shaw, Two Sigma) don't look for one big edge. They look for thousands of tiny edges that compound. A single strategy with 2% edge is fragile — one market change and it breaks. A portfolio of 50 strategies each with 0.5% edge is robust — any individual failure barely matters.

This is why we're testing 100+ strategies rather than perfecting one. The flywheel approach — generate hypotheses, test, kill bad ones, compound good ones — is how institutional quant trading actually works, just at a smaller scale.

The numbers from our pipeline: 20 strategies tested, 10 rejected, 6 deployed, 4 building. A 50% rejection rate is normal. Renaissance reportedly tests thousands of hypotheses for every one that reaches production. Our rejection rate will likely increase as we exhaust the easy-to-test ideas and move into more marginal territory.

### The Honest Assessment

Our system has a calibrated Brier score of 0.2171 on 532 resolved markets. That's better than random (0.25) but far from the state of the art. The frontier for LLM forecasting is approximately 0.075-0.10 when blending model estimates with market price (which we deliberately avoid for anti-anchoring reasons).

We have a demonstrated edge on the NO side (76.2% win rate) that's consistent with the well-documented favorite-longshot bias. But this edge has been demonstrated in backtest only, not in live trading. Backtests are unreliable predictors of live performance for many reasons: simulated fills don't capture real slippage, the market price you test against may not have been available when you'd actually trade, and the edge may degrade as more bots exploit it.

We're honest about this because honesty is the credibility moat. Anyone can show a good backtest. Showing a good backtest AND explaining all the reasons it might not work live — that's what serious researchers do.

---

*Last updated: March 7, 2026 | Part of the Elastifund Education Center*
