# What This Project Is

## Start Here: Prediction Markets, Explained

Imagine a marketplace where people buy and sell shares based on whether real-world events will happen.

**Example:** Will it rain in New York tomorrow?

- If 40% of traders think it will rain, the price of a "YES rain" share is $0.40.
- If you buy at $0.40 and it does rain, your share pays out $1.00 tomorrow. You made $0.60.
- If it doesn't rain, your share expires worthless.

This is a **prediction market**. The price is literally what the crowd thinks the probability is.

Real markets exist on platforms like **Polymarket**, where people are trading real money on thousands of events: Will Trump win 2024? Will AI AGI happen by 2026? Will there be a recession this year? Will specific weather events happen?

---

## The Core Insight

Prediction market prices reveal crowd belief. But crowds are not always right.

**Why might a crowd misprice an event?**

1. **Anchoring bias:** If everyone hears a rumor first, they anchor to that number, even if new data says otherwise.
2. **Herding:** Traders see the price move, assume it's based on smart information, and follow it without thinking.
3. **Favorite-longshot bias:** People overpay for unlikely outcomes they *want* to happen (like a lottery ticket). They underpay for boring, likely outcomes.
4. **Information asymmetry:** Some traders have better data than others. Some have worse.
5. **Volatility:** Market makers need profit margins, so prices drift from true probability.

If a crowd misprice an event—say they think there's a 40% chance when it's really 70%—then someone who can figure out the true probability can make money by betting against the mispricing.

---

## What This Project Does

We built an **AI system that:**

1. **Reads public information** about upcoming events (news, historical data, expert consensus).
2. **Estimates a probability** for what will actually happen, without knowing what the market crowd thinks the price is.
3. **Compares** its estimate to the market price.
4. **Bets** when it finds a gap big enough to make money after fees and risk.

### The Anti-Anchoring Shield

Here's the key twist: **The AI never sees the market price while it's thinking.**

The system works like this:
- Trader gives the AI system the event description: "Will the ECB raise rates in March 2024?"
- AI reads the event, researches the question, and outputs a probability. Say: 72%.
- *Then* we check the market price. Say: $0.55 (market thinks 55% chance).
- If there's a meaningful gap (72% vs 55%), we consider a bet.

This prevents the AI from being anchored or influenced by what other traders think.

---

## The Four Decision Layers

### Layer 1: Event Understanding
Does the AI understand what's being asked? Is the event binary (yes/no)? Is there historical data? What matters?

### Layer 2: Probability Estimation
The AI reads available information—news, historical frequency, expert consensus, base rates—and outputs a single number: its best estimate of true probability.

### Layer 3: Calibration Adjustment
Raw AI confidence is often overconfident. We use statistical methods (temperature scaling, then Platt scaling) to adjust the AI's estimate based on how often it was actually right in the past.

Example: If the AI says 75% but is actually right only 60% of the time in that category, we lower its estimate.

### Layer 4: Risk Sizing
Even if we're confident, we don't bet the farm. We use the **Kelly criterion**—a math formula that says: "Given your edge and bankroll, how much should you bet on this?"

If we're 72% sure but the market is 55%, the Kelly formula might say: "Bet 4% of your bankroll." Not 50%. Not 1%. Exactly the amount that maximizes long-term wealth without risking ruin.

---

## What Bets Look Like

### Example 1: Underpriced NO
- **Event:** "Will USD/JPY exceed 155 by end of Q1 2024?"
- **Market price:** $0.62 (crowd thinks 62% yes)
- **AI estimate:** 48% (thinks it's actually less likely)
- **Action:** Buy NO at $0.38, expecting to profit if the dollar weakens

### Example 2: Overpriced YES
- **Event:** "Will Meta stock hit $200 by Dec 2024?"
- **Market price:** $0.68 (crowd very bullish)
- **AI estimate:** 41% (market is over-optimistic)
- **Action:** Buy NO at $0.32, expecting profit if Meta underperforms

### Example 3: No Trade
- **Event:** "Will CPI be below 3% in March 2024?"
- **Market price:** $0.51
- **AI estimate:** 53%
- **Gap:** Only 2 percentage points
- **Action:** Skip the trade. Gap is too small to justify the risk.

---

## The Edge: Three Specific Bets

### Edge 1: NO Bias
People love to speculate on unlikely upside. They'll overpay for a small chance at a big win (like a lottery ticket).

We exploit this by systematically being more aggressive on NO when others are over-excited about YES.

**Historical example:** Early 2024 crypto rallies. Market priced some altcoin rallies at 65-70%. We estimated 35-40%. We bought NO, and when the enthusiasm faded, we won.

### Edge 2: Fast Resolution
In fast-resolving markets (resolving within 1-2 weeks), information markets are efficient. Mispricing closes quickly.

In slow-resolution markets (3-6 months), the crowd is more uncertain, and there's more time for herding and sentiment swings. Our AI has more edge there.

### Edge 3: Category Routing
Some event categories the AI is better at:

- **Weather/climate:** Historical data + seasonal patterns. AI can do this well.
- **Macroeconomic forecasts:** Data-driven. Repeatable patterns.
- **Sports outcomes:** Historical stats, injury reports, recent form—all public.

Other categories we avoid or down-weight:

- **Geopolitical shocks:** Limited historical precedent. Hard to forecast.
- **Insider news:** Crowd often knows before we do.
- **Regulatory surprises:** True randomness.

---

## The Technology Stack (Simple Version)

- **Event scanner:** Every 5 minutes, checks 100+ active markets on Polymarket.
- **AI reasoning engine:** Claude AI reads event description, reasons through factors, outputs probability.
- **Calibration layer:** Adjusts raw confidence based on historical accuracy.
- **Bet sizing engine:** Kelly criterion to decide trade size.
- **Paper trading:** Simulates bets using fake money. No real cash at risk yet.
- **Cloud server:** Runs 24/7 on a cheap VPS. Monitors positions, logs trades.

---

## What Success Looks Like

Short term (30 days):
- Paper trading runs cleanly. No crashes, no logic errors.
- 20-30 trades accumulate. First markets begin resolving.

Medium term (90 days):
- 50+ resolved trades. We can measure if we're actually beating a coin flip.
- Live data validates or invalidates the edge.

Long term (6+ months):
- Consistent profitability on real money. Edge is proven.
- Scale capital and infrastructure.
- Profits fund veteran suicide prevention work.

---

## What a Smart Non-Technical Parent Should Know

**The basic idea:** We built a betting system that tries to spot when crowds misprice real-world events. It uses AI to estimate true probability, hides that estimate so it's not influenced by crowd bias, and only bets when the gap is big enough to justify the risk.

**Why it might work:** Crowds do misprice things. AI might be better at estimating some probabilities than crowds are.

**Why it might not work:** Competitors are far ahead. The edge might be tiny. Regulation could shut it down. The system could have bugs.

**Where we are now:** We've backtested on 532 historical events and the math looks good. But we've only placed 17 real bets with fake money. That's not proof yet.

**What happens next:** Let the system run for a few months on real markets. If it wins more than 50% of the time, the edge is real. If not, we've learned something valuable and will iterate.

**The mission:** If this works, profits go to veteran suicide prevention.
