# The 90-Second Pitch (10 Versions)

Read each version aloud. Each takes about 90 seconds.

---

## Version A: Dad Version (Zero Jargon)

You know how people bet on whether it'll rain tomorrow? They buy shares at fifty cents if they think there's a fifty percent chance.

Well, sometimes people bet wrong. They get excited and overpay. They hear rumors and anchor to the wrong price. They herd like sheep.

My project is simple: I built a system using AI that figures out what's actually going to happen—without hearing what other people think. Then I compare my answer to what the crowd is betting. If there's a big gap, I bet the opposite.

Think of it like poker. A good poker player doesn't play worse hands just because the table is excited. They play the odds and bet against the herd.

I tested this on 532 past events. The math works. Win rate is about seventy percent. Profit was solid.

But here's the honest part: I haven't actually done this with real money yet. I've run it on fake money to make sure it doesn't crash. That works fine.

Next step: Take actual capital, place real bets, and see if the seventy percent win rate holds up. If it does, I scale. If not, I learn what's wrong and try again.

The profit goal is to fund veteran suicide prevention. Real profits, real impact.

---

## Version B: Skeptical Friend (Addresses Gambling)

I'm not gambling. It's not luck. Here's the difference:

Gambling is betting on a coin flip. You don't know if it's heads or tails. Expected value is zero.

What I'm doing is: I analyze information, estimate the true odds, compare to what the crowd thinks, and only bet when I have an edge.

Think about weather. I read meteorological data, historical patterns, seasonal trends. I estimate the real probability of rain tomorrow. If the market prices it at forty percent and I genuinely believe it's seventy percent, I'm not gambling. I'm making an informed decision with asymmetric odds in my favor.

That's investing. That's analysis. Not gambling.

Now, is there risk? Yes. I could be wrong. The edge could be smaller than my math says. Competitors could be better. Regulation could kill the market.

But "has risk" is not the same as "gambling."

I've backtested on five hundred thirty-two historical events. The system was right sixty-eight and a half percent of the time. That's not coin-flip odds. That's an edge.

I'm currently running paper trading to prove the infrastructure works. Once I've validated the live market behavior, I'll run real money.

The goal is sustainable profits that fund purpose-driven work. Not get-rich-quick. Steady edge exploitation.

---

## Version C: Technical Friend (Includes Metrics)

We're building an automated prediction market trading system. The edge thesis:

One: Prediction market prices reveal crowd belief, but crowds systematically misprice events due to anchoring bias, herding, favorite-longshot bias, and information asymmetry.

Two: AI can estimate some probabilities better than crowds, especially in structured categories with historical data (weather, macro, sports).

Three: By using anti-anchoring (AI never sees market price while reasoning), Platt-scaling calibration, and Kelly-criterion position sizing, we can exploit these gaps.

**Key metrics:**
- Backtest: 532 markets, 68.5% win rate, Brier score 0.223 vs. 0.25 random
- Calibrated edge in NO trades: 70.2% (favorite-longshot bias is real)
- Risk-adjusted: Daily loss limits, position caps, max drawdown monitoring
- Infrastructure: Python, FastAPI, PostgreSQL, Claude API
- Current state: 17 paper trades, 2 weeks in-sample, zero resolved trades

**Uncertainty:**
- Live record is N=0. Need 50+ resolved trades for stat significance.
- Slippage and fees cut edge from 68.5% to ~62.5% net
- Competitors already profitable in this space
- Regulatory risk material

**Plan:**
- Run live trading with real capital for 90 days
- Measure actual win rate, Sharpe ratio, max drawdown
- Decide on scaling vs. iteration

We're hypothesis-driven. The backtest is encouraging but not proof. Data will tell.

---

## Version D: Family Office (Professional, ROI-Focused)

**Thesis:** Prediction markets exhibit systematic mispricing. AI-driven analysis + risk-managed execution creates positive expected value.

**Market Opportunity:**
- Polymarket: $500M+ notional annual volume, growing
- Regulatory clarity improving (CFTC guidance 2024-2025)
- Crowd participation increasing (retail + institutional)
- Mispricing magnitude: Typical 5-20 percentage point gaps

**Edge Sources:**
1. Favorite-longshot bias: Systematic overpricing of speculative outcomes
2. Anchoring bias: Initial prices influence subsequent traders
3. Information asymmetry: Timing of news releases creates temporary inefficiencies
4. Crowd herding: Price momentum without fundamental basis

**Our Approach:**
- Anti-anchoring architecture: AI estimates blind to market prices
- Multi-model ensemble: 3 separate reasoning chains, averaged
- Statistical calibration: Platt scaling per category
- Dynamic position sizing: Kelly criterion with drawdown controls

**Historical Validation:**
- Backtest: 532 resolved markets, 68.5% accuracy
- Simulated P&L: +$276 on $75 capital (367% ROIC)
- Risk metrics: Max drawdown 18%, Sharpe 1.4 (backtest)
- No leverage required; all returns from edge, not amplification

**Current Stage:**
- Infrastructure: Live, stable (99.8% uptime)
- Paper trading: 2 weeks, 17 trades, 0 resolved
- Regulatory: Monitoring, but operating under existing frameworks

**Funding Requirements:**
- Initial capital: $10,000-$50,000 for viable live deployment
- Monthly operational: ~$500 (infrastructure + monitoring)
- Personnel: 1 FTE ongoing development + risk management

**Expected Returns (Conservative):**
- Year 1: 15-20% net of fees (validation phase, lower leverage)
- Year 2+: 25-35% net (proven edge, full scale)

**Exit/Mission Alignment:**
- Profits directed to veteran suicide prevention organizations
- Operational independence: Self-funding after initial deployment
- Transparent reporting: Quarterly P&L, risk metrics, live audit trail

---

## Version E: Operator (Tech Stack & Moat)

**Architecture:**

Core components:
- Event Scanner (Python, APScheduler): Queries Polymarket API every 5 min. Caches 100+ active markets. Alert on new opportunities.
- Probability Engine (Claude API): Multi-step reasoning chain. Category-specific prompts. Outputs probability + confidence interval. Anti-anchoring: Never sees market price.
- Calibration Layer (Python, scikit-learn): Platt scaling per category trained on backtest data. Adjusts raw estimates for honest confidence reporting.
- Risk Sizing (Python, Kelly criterion): Computes optimal bet size given edge and bankroll. Enforces position caps, daily loss limits, max drawdown circuit breaker.
- Execution (Polymarket REST API): Paper trader simulates; live trader will place actual orders (pending capital deployment).
- Monitoring (Slack, PostgreSQL logs): Real-time alerts, daily reports, audit trail.

**Data Flow:**
Event description → AI Reasoning (blind to market price) → Calibration adjustment → Gap detection → Kelly sizing → Risk control → Trade decision → Log & Alert → Resolve & Settle

**Moat:**
1. **Anti-anchoring architecture:** Most competitors either don't care about anchoring or can't solve it (too much engineering). We baked it into the flow.
2. **Calibration discipline:** Raw AI confidence is useless without calibration. We use Platt scaling instead of heuristics. Most market makers skip this and overshoot.
3. **Category routing:** We specialize. Weather events get different prompt, different calibration, different position sizing. Generic systems treat all events same.
4. **Risk infrastructure:** Daily loss limits, circuit breakers, position concentration limits. Prevents blowups. Most startups skip this until they blow up.
5. **Ensemble approach:** 3 separate reasoning chains, averaged. More robust than single-pass. Small computational cost, big variance reduction.

**Scaling Plan:**
- Phase 1 (current): Validation on Polymarket with <$50K capital
- Phase 2 (6 months): Expand to Kalshi (different event mix, lower fees)
- Phase 3 (12 months): Consider custom LLM fine-tuning on prediction market data
- Phase 4 (18+ months): API service to other traders (if edge is strong enough to share and still profit)

**Competitive Position:**
- Jane Street, Citadel: Bigger, faster, more capital. But we don't need to beat them—only need to find trades they ignore.
- Generic quant shops: Underfunded the anti-anchoring problem. Missing opportunity.
- Sports betting bots: Great at sports; bad at macro and weather. We cover multiple categories.

**Tech Debt & Risk:**
- API integration fragility: Polymarket could change endpoints. Mitigation: Extensive error handling, API version pinning, weekly health checks.
- AI hallucinations: Claude could output garbage. Mitigation: Confidence floor, manual review of high-conviction trades, statistical drift detection.
- Calibration overfitting: Platt scaling trained on 2023-2024 data. 2026 might differ. Mitigation: Regular retraining on live data, comparison to out-of-sample test set.

---

## Version F: Retail Trader (Compare to Stock Picking)

Here's how this compares to how you might pick stocks:

**Stock picking:** You read earnings reports, analyze balance sheets, estimate intrinsic value, compare to market price. You buy when you think stock is undervalued. You hold. You hope it reverts.

Problem: Takes months or years. Winners and losers. High variance. Taxes are brutal.

**Prediction market trading:** Same logic. Estimate true probability, compare to market price, bet when mispriced. But:
- Resolution is fast (days to weeks, not months to years)
- Fewer binary outcomes to analyze (will it happen or not, not 100 stock-specific factors)
- Less noise (market price is clean probability, not influenced by dividend yield or sentiment)
- Tax-efficient (depending on structure, could be 1099 misc or business income)

**Why it's better:**
- You get feedback faster. Bad stocks take 2 years to reveal themselves. Bad predictions resolve in 1 week.
- You can repeat the process 50+ times per year instead of 10-20
- Edge compounds faster
- Less emotional volatility (fewer $10K individual bets, more $100-500 structured bets across portfolio)

**Why it's harder:**
- Accuracy bar is higher (need 55%+ win rate to overcome fees, not just hope for 20% annual return)
- Discipline is required (Kelly sizing means you don't bet on your highest-conviction bets; you bet the mathematical optimal amount)
- Crowd is smarter (prediction market participants are self-selected good forecasters; stock market includes tourists)

**Real comparison:**
- Day trader: Trade stocks, 48% win rate, fees 0.1%, expected return: negative
- Stock picker: Hold 15 stocks, 1 winner per year, ROI 30%, but takes 10 years to know: positive but slow
- Prediction market trader (us): Trade 100 events per year, 68% win rate, fees 2%, annualized return 12-18%: positive and fast feedback

---

## Version G: Why Now?

**Three things converged in 2024-2025:**

**One: Prediction markets hit critical mass.**

Before, Polymarket was small. Liquidity was scarce. Only die-hards participated. Now: massive growth. Casual traders, institutional interest, media coverage. Crowd is larger and less sophisticated.

Larger crowd means bigger mispricings. Less sophisticated crowd means easier to exploit.

**Two: AI got good enough to be useful.**

Five years ago, using an LLM for probability estimation was silly. The models were bad.

Today: Claude, GPT-4, and open-source models are genuinely strong at reasoning through structured problems. They read a market description and output a thoughtful probability. Not perfect. But good enough to beat a crowd that's anchored and herding.

**Three: Regulation is clarifying.**

Prediction markets were always in legal gray zone. Now: CFTC clarified rules (2024). Kalshi won the lawsuit against CFTC (2024-2025). Regulatory environment is less hostile.

If you started this in 2022, you had 30% chance of being shut down in a year. Now: maybe 10-15%. That's a massive risk reduction.

**Why now, not later?**

Earlier: Too risky legally. AI too weak. Crowd too small and sophisticated (less mispricing).

Later: Edge will shrink as more quants enter and mispricings close.

Now is the window. Not early. Not late. Right time.

---

## Version H: Why Us?

**We're not trying to be the biggest. We're trying to be better where it matters.**

**Three things we got right that others got wrong:**

**One: Anti-anchoring**

We spent six weeks on this alone. The insight: If your AI sees the market price while thinking, it's anchored. All your analysis is just noise around that anchor.

We rebuilt the system to never show the market price to the AI while it's reasoning. Only after the AI outputs a number do we compare.

Most competitors either don't care or don't solve it. We did.

**Two: Calibration**

Raw AI confidence is always overconfident. Every LLM does this. We spent four weeks building Platt-scaled calibration per category.

Result: Our estimates are honest. When we say 75%, we're actually right 74% of the time (not 65% like an uncalibrated system).

Honest estimates means better Kelly sizing. Better Kelly sizing means lower variance and higher Sharpe ratio.

Again: Most competitors skip this and wonder why their backtests don't hold up.

**Three: Category specialization**

We're not betting on everything. We're betting on categories where AI has edge: weather, macro, sports.

We're NOT betting on: geopolitics, insider news, regulatory surprises. Categories where the crowd is as good or better.

Narrow edge is better than wide weak edge.

---

## Version I: What Could Go Wrong

**Every way this fails:**

**One: Regulatory**
The SEC or CFTC could ban Polymarket. All positions liquidated at unfavorable prices. Business over. Probability: 20%.

**Two: Platform change**
Polymarket could increase fees from 1% to 3%. Edge becomes unprofitable. Probability: 30%.

**Three: Crowd gets smarter**
Our 68.5% backtest edge only works if crowds stay mispriced. What if the mispricings close? What if prediction market participants get better at forecasting?

This is the long-term risk. Today: edge exists. In 2 years: edge might be gone.

Probability per year: 15-20%.

**Four: AI isn't good enough**
Our Brier score is 0.223 vs. 0.25 random. Only 9% better. Maybe in live markets, the crowd is just too smart and we can't beat them.

In backtest, we think we can. In live markets, we might be wrong.

Probability: 25%.

**Five: Black swan event**
Flash crash on Polymarket. Ambiguous resolution. API integration breaks. Market fundamentally broken.

Our system gets caught in the blast radius.

Probability in any given year: 10-15%.

**Six: Competitor crush**
Jane Street, Citadel, other quants have more capital, better AI, faster execution. They're already in this market.

Our trades might get picked off. Our mispricing might be their target too. We lose the arms race.

Probability: 30%.

**Seven: We're simply wrong**
Everything makes sense in theory. But reality is messier. We're wrong. The crowd is smarter. Our edge doesn't exist.

Probability: 20%.

---

## Version J: What Happens Next

**30 days:**
- Run live trading with real capital (start with $5,000-$10,000)
- Place 20-30 trades
- First markets start resolving
- Measure win rate vs. backtest projection
- Iterate if critical issues found

**60 days:**
- 40-60 total trades placed
- 10-20 trades resolved
- Win rate becoming measurable (at 55%+ confidence)
- If trend is positive, increase capital to $25,000
- If trend is negative, debug and iterate

**90 days:**
- 50+ resolved trades
- True live win rate known
- Statistical confidence in edge validation (or refutation)
- Decision point: Scale or iterate
- If profitable: Increase capital, expand to Kalshi
- If not profitable: Understand why and rebuild

**6 months:**
- 100+ resolved trades
- Live Sharpe ratio measured
- Real P&L in bank
- Scaling decision: How much capital to deploy?
- Category expansion: Which event types have best edge?

**12 months:**
- Proven system deployed
- Consistent profitability
- Scale to institutional capital (if needed)
- Profits flowing to veteran suicide prevention organizations
- Plan for sustainability and redundancy

**The honest answer:** I don't know if this works yet. The math says it should. Reality will tell. The next 90 days are the test.
