# The Plain English Sales Pitch

## The Elevator Pitch (30 seconds)

We built a system that uses Claude AI to estimate the true probability of events in prediction markets. When Claude's estimate differs from the market price, we trade. Backtests show 68.5% win rate over 532 markets. We're currently live paper trading, with 17 trades pending resolution. All profits fund veteran suicide prevention.

## The 5-Minute Pitch

### What's the problem?

Prediction markets are places where people bet real money on whether events will happen. "Will it rain tomorrow?" "Will the Fed raise rates?" "Will Trump win in 2024?" The market price for each outcome is supposed to represent what the crowd thinks the probability is.

But crowds are often wrong. They get anchored to bad information. They overweight recent news. They systematically favor popular outcomes over unlikely ones (the "favorite-longshot bias").

**When the crowd is wrong, there's money on the table.**

### What's the solution?

We use Claude AI to estimate the true probability of events, independently of what the crowd is paying. Claude reads the question, thinks through the base rates and structural factors, and gives us a probability.

Then we compare: What does Claude think? What is the market paying? If there's a gap, we bet on Claude.

**Claude's advantage:** It reasons from first principles without being biased by price action or crowd narrative. It can think clearly about base rates. It doesn't anchor on wrong numbers.

### Why would this work?

1. **Prediction markets have real mispricings.** This isn't theoretical—researchers have documented it.

2. **Claude is a sophisticated reasoner.** It's better at base-rate reasoning than the median person. It's probably better than crowds.

3. **We've proven it on historical data.** We backtested on 532 resolved markets. Win rate: 68.5%. P&L: +$276 on 372 simulated trades.

4. **We've built a working system.** It's running now on a VPS in Frankfurt. It finds trades, executes them, tracks everything.

5. **We have early live data.** 17 trades placed. Perfect execution. Waiting for markets to resolve.

### Why is this different?

**vs. Traditional trading bots:**
- We're not just pattern-matching. We're using AI reasoning.
- We're not using sentiment analysis or social media. We're using structural thinking.

**vs. Betting with your gut:**
- We're systematic, not emotional.
- We size positions using Kelly criterion (math-backed optimal sizing).
- We measure everything and improve continuously.

**vs. Other AI approaches:**
- We use anti-anchoring prompts (Claude doesn't see the market price, so it can't anchor on wrong numbers).
- We calibrate Claude's outputs against historical accuracy.
- We route capital to categories where Claude has edge (Politics, Weather), and skip categories where it doesn't (Crypto, Sports).

### What's the evidence?

**Backtested Performance:** [Historical backtest, 532 markets]
- 68.5% win rate (vs. 50% random)
- +$276 simulated P&L on 372 trades
- 70.2% win rate on "NO" trades (favorite-longshot bias exploited)
- 0% ruin probability across 10K Monte Carlo simulations

**Live Performance (current):** [Live-tested, 17 trades]
- 2 cycles completed
- 17 trades entered
- $68 deployed
- Execution: perfect, 0 errors
- Realized P&L: $0 (waiting for markets to resolve)

**Critical caveat:** All the big numbers are from backtests or simulations. The live data is real but too small (17 trades) to be statistically significant. We need 50+ resolved trades to confirm the hypothesis works in real markets.

### What are the risks?

**1. Regulatory risk (existential):** CFTC is investigating Polymarket. States are considering bans. Polymarket could be shut down in weeks or months.
- **Mitigation:** Building on alternative platforms (Kalshi, Metaculus) in parallel

**2. Competition risk (existential):** Other teams are also using Claude (or will start soon). Once many traders use Claude, market prices will reflect Claude's estimates. The edge disappears.
- **Likelihood:** 50%+ chance within 12 months
- **Mitigation:** Building multi-model ensemble, testing GPT and Grok

**3. Live performance risk (high):** Backtests can overfit. Real markets have slippage, latency, partial fills. Live performance might be 50-80% of backtest.
- **Mitigation:** Accumulating 50+ live trades to validate

**4. Scale risk (high):** At $75 capital, our positions don't move the market. At $10K+, our positions might move prices. Market impact destroys the edge.
- **Mitigation:** Route through multiple accounts, cap position sizes

**5. Model risk (medium):** Claude might not be the best model. GPT-4 or some other model might be better.
- **Mitigation:** Testing alternatives in next 2 weeks

**6. Calibration drift (medium):** Our calibration trained on past data. Future markets might have different distributions. The system might get worse over time.
- **Mitigation:** Building live calibration drift detection

### What's the business model?

**Revenue:** Profit from winning trades on Polymarket

**Costs:**
- Server: ~$20/month
- Claude API: ~$10-20/month
- Polymarket fees: 2% per trade

**Capital model:**
- Start: $75 seed
- Weekly addition: $1,000 (as trades resolve and compound)
- Scaling if live results are positive

**Impact:** 100% of profits fund veteran suicide prevention

### What's the realistic upside?

If the system works:
- Conservative strategy: +124% ARR
- Moderate strategy: +403% ARR
- Aggressive strategy: +872% ARR
- Velocity-optimized (fastest-resolving markets): +6,007% backtested ARR

But these are projections based on historical backtest. Real results will likely be lower. And edges compress as competition enters.

Realistic scenario: 50-150% ARR in year 1, then declining as edge compresses.

### What's needed to make this real?

1. **Accumulate 50+ live resolved trades** (2-4 weeks)
   - Validate that live performance ≈ backtest
   - Build statistical confidence

2. **Evaluate GPT and Grok** (2 weeks)
   - Benchmark against Claude
   - Build ensemble if they add value

3. **Implement live calibration monitoring** (2 weeks)
   - Catch model degradation early
   - Trigger re-training if needed

4. **Scale capital responsibly** (ongoing)
   - Start at $68, grow to $1K, then to $10K
   - Monitor for market impact
   - Route through multiple accounts if needed

5. **Build platform diversity** (ongoing)
   - Kalshi (regulated alternative)
   - Metaculus (longer-term forecasts)
   - Reduce regulatory risk

### Who is this for?

**This system works for:**
- Someone who understands prediction markets and how prices represent probabilities
- Someone who's comfortable with high uncertainty and wants to place a bet on a hypothesis
- Someone who values systematic, data-driven approaches over intuition
- Someone who can handle regulatory risk and is ready to pivot if needed

**This system doesn't work for:**
- Someone who needs certainty before investing
- Someone who can't tolerate the idea of Polymarket being shut down
- Someone who needs immediate returns (capital is tied up in pending trades for weeks/months)
- Someone who wants passive income (this requires active management)

### The Honest Truth

We believe in this system. The backtest evidence is strong. The operational system works. The hypothesis is sound.

But we haven't proven it yet. Until we have 50+ live resolved trades, it's a theory backed by simulation. The next 4 weeks will tell us if it's real.

**We're asking you to fund the next phase of validation.** If live results are positive, we scale aggressively. If they're negative, we pivot to alternatives (ensemble models, market-making, arbitrage, other platforms).

This is a high-risk, high-reward opportunity in an emerging market. Regulatory risk is real. Competition risk is real. But so is the opportunity.

Are you in?

---

**Read next:** `02_CURRENT_SYSTEM/SYSTEM_OVERVIEW.md` for technical details →
