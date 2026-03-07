# What Predictive Alpha Is, In Plain English

## The Problem We're Solving

Prediction markets let people bet real money on whether events will happen. "Will it rain in London on March 15?" "Will the Fed raise rates this quarter?" "Will Trump win the 2024 election?" These markets have a price for each outcome. That price is supposed to represent the crowd's belief about the probability.

**Here's the problem:** The crowd isn't always right. In fact, crowds often systematically misprice things. They love favorites and hate long shots (the "favorite-longshot bias"). They anchor on recent news. They panic-sell when markets drop.

When the crowd misprices something, there's an edge—a gap between what something is actually worth and what people are paying for it.

## What Predictive Alpha Does

Predictive Alpha uses Claude AI to estimate the true probability of events without looking at what the market is paying.

1. **Claude reads the question.** No market prices, no anchoring. Just the facts: "Will it rain in London on March 15?"

2. **Claude estimates the true probability.** Using reasoning about base rates, historical data, relevant forecasts, and logic. Outputs: "I estimate 38%."

3. **The system compares to market.** The market is asking 52% for "Yes, it will rain."

4. **The system spots the gap.** The market is offering 52% but Claude thinks it's only 38%. That's a 14-percentage-point gap. If Claude is right, you should bet against rain.

5. **The system calculates position size.** Uses Kelly criterion (a math formula for optimal bet sizing) with a quarter leverage (conservative).

6. **The system trades.** Places a small bet at the market price.

7. **The market resolves.** Days or weeks later, the real outcome is known. The system collects wins or learns from losses.

8. **Over time, statistically.**  If Claude's estimates are better than the market's, the system makes money. If not, it loses.

## Where the Edge Comes From

Prediction markets are crowded with smart people now. So edges are small and narrow. Predictive Alpha's edge comes from:

**1. Anti-anchoring:** Claude never sees market prices, so it can't anchor on the "wrong" number the crowd settled on. It thinks from first principles.

**2. Systematic reasoning:** Claude uses structured prompts that force it to:
   - Start with base rates (what's the historical frequency?)
   - Break down the question into sub-components
   - Avoid common cognitive biases
   - Express uncertainty honestly

**3. Calibration:** The system learns. It measures how often Claude says "60%" and the outcome is actually true. If Claude says "60%" but outcomes are only 50% true, the system adjusts. This is done via Platt scaling, a machine learning calibration technique.

**4. Asymmetric NO-bias:** Data shows the crowd loves favorites. So when Claude thinks "No" is underpriced, the system takes slightly larger positions. [Live-tested on real market data in backtest]

**5. Category routing:** The system only trades categories where Claude has historically been accurate (Politics, Weather). It skips categories where the edge is weak or vanishes (Crypto, Sports).

**6. Capital velocity:** The system prioritizes fast-resolving markets. If a market resolves in 2 days, you can recycle capital 180 times per year instead of 3 times. Faster resolution = more iteration = more learning.

## What Success Looks Like

If this system works:
- Claude's probability estimates are systematically better than market prices
- The system makes money on average per trade
- As the system trades more, it gets more data, calibrates better, improves
- Capital compounds as wins exceed losses
- Profits fund veteran suicide prevention

## What's Been Proven vs. Not Proven

**[Historical backtest]** The system was trained on 532 resolved markets. On those markets:
- Win rate: 64.9% uncalibrated, 68.5% after calibration
- P&L: +$276 simulated on 372 trades (accounting for Polymarket fees)
- Risk of ruin: 0% (across 10,000 Monte Carlo simulations)

This is strong. But it's backtest. Backtests can be optimistic.

**[Live-tested, early stage]** The system is currently running on a VPS in production, trading with real market data. After a calibration fix:
- 2 cycles completed (March 4-6, 2026)
- 17 trades entered
- $68 deployed
- $0 realized P&L (waiting for markets to resolve)

This is real. But it's tiny. 17 trades is not statistically significant.

**Not yet proven:**
- Will Claude's edge hold once competitors know about it?
- Will Polymarket remain legal and functional?
- Will the system scale to larger capital without market impact?
- Will live performance match backtested performance?

## The Business Model

**Revenue:** Profit from winning trades on Polymarket.

**Costs:**
- Server: ~$20/month
- Claude API calls: ~$10-20/month (currently)
- Time investment: Significant research, engineering, optimization

**Capital:** Starting with $75 seed, adding $1,000/week as trades resolve and compound.

**Impact:** All profits fund veteran suicide prevention (the reason this system was built in the first place).

## What Makes This Different from Existing Approaches

**vs. Naive ML models:** Claude's reasoning can change based on new information. It's not just curve-fitting. It actually thinks about the problem.

**vs. Crowd-only betting:** Prediction markets are already using crowd wisdom. We're using AI wisdom. If AI estimates are better, we win.

**vs. Sentiment analysis:** The system doesn't try to guess sentiment or predict human behavior. It estimates ground truth probabilities, and bets when the crowd is wrong about them.

**vs. Other prediction market bots:** Competitors exist (OpenClaw reportedly made $1.7M; Fredi9999 reportedly made $16.62M). Those systems use different models, different market selection, different calibration. We don't know their exact methods, but our edge is Claude's reasoning + our prompt engineering.

## The Realistic Risks

1. **Regulatory:** CFTC may crack down. States may ban Polymarket. This changes everything.

2. **Competition:** As more teams enter prediction markets, edges compress. We might be in a 6-month window before edges disappear.

3. **Model risk:** Claude might not be the right model for this. GPT-4 might be better. We're testing other models next.

4. **Execution risk:** One bug in the trading system could blow capital. We have safety rails (daily loss limits, position caps, cooldowns) but they might not catch everything.

5. **Calibration drift:** The system calibrated on history. If the future is different, calibration will drift. We're monitoring this.

6. **Market impact:** As we scale capital, we might move market prices. Our positions might cause the very mispricing we exploit to disappear.

## The Reasonable Question: Why Should I Care?

If you're building the next version:
- You're not starting from zero. You have research, prompts, a working system, backtest evidence, and early live data.
- You understand where the edge comes from and how to test it.
- You can focus on scaling, optimization, and risk management instead of figuring out the first principles.
- You have a clear roadmap of what's next.

If you're evaluating whether this is real:
- The backtest evidence is strong but not bulletproof.
- The live test is real but tiny.
- The system is running and tradeable right now.
- The regulations are a real risk.
- The business logic is sound, but success is not guaranteed.

---

**Read next:** `WHAT_WE_HAVE_PROVEN_VS_NOT_PROVEN.md` →
