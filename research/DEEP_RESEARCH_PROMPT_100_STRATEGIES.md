# Deep Research Prompt: 100 Strategy Hypotheses for Prediction Market Edge Discovery
**Version:** 2.0.0
**Date:** March 7, 2026
**For:** Claude Deep Research, ChatGPT Deep Research, Gemini Deep Research
**Context:** Elastifund edge discovery pipeline — flywheel cycle 1
**Output:** 100 concrete, testable trading strategy hypotheses ranked by expected viability
**Repo:** github.com/CrunchyJohnHaven/elastifund (PUBLIC — MIT License)

---

## Preamble: What Makes This Research Request Different

This is not a brainstorming exercise. This is the input to an automated hypothesis testing pipeline with stringent kill rules. Every strategy you propose will be:

1. Coded into a Python module with a common interface
2. Fed historical or live data through an 83-feature engineering pipeline
3. Backtested with realistic cost assumptions (maker 0%, taker 1-3.15%, slippage, fill rates)
4. Subjected to 6 automated kill rules (insufficient signals, negative EV, cost stress failure, poor calibration, instability, regime decay)
5. Evaluated with walk-forward temporal cross-validation (no lookahead bias)
6. Stress-tested with +/-20% cost variations
7. If it survives: promoted to paper trading. If paper trading confirms: tiny live capital test.
8. Published as open-source research — both successes and failures — on johnbradleytrading.com

We have already tested 20 hypotheses. All 10 that went through the full pipeline were rejected. This is our base rate: approximately 0% survival. Your strategies need to be good enough to change that number. Be honest about which ones have a real chance and which are educational experiments.

---

## Context for the Researcher

### What We Are

Elastifund is an open-source, AI-directed prediction market trading system. The AI agent (called JJ) autonomously scans markets, estimates probabilities, decides what to trade, sizes positions, places orders, and manages risk. The human (John Bradley) builds and improves the system, sets safety constraints, and documents everything publicly.

We are building the most comprehensive publicly available resource on agentic trading systems. Every strategy we test — success or failure — becomes educational content. The research IS the product. This prompt and its results will be published on our website.

### Platforms We Trade

**Polymarket** — crypto-backed (USDC.e), CLOB order book, YES/NO binary shares priced $0.00–$1.00
- Fee structure: **0% maker**, 1.0–3.15% taker (fee = r × p × (1-p), where r = market fee rate)
- Crypto-collateralized markets: 1.56% taker
- Resolution: UMA oracle (optimistic oracle with dispute mechanism)
- Infrastructure: CLOB WebSocket, RTDS feed, Gamma API (market discovery), Data API (trade/wallet data)
- Settlement: Polygon blockchain, USDC.e

**Kalshi** — USD-denominated, CFTC-regulated, similar binary structure
- Fee structure: taker = 0.07 × p × (1-p), no maker fee
- Resolution: official government/institutional data sources
- Infrastructure: RSA-signed REST API
- Settlement: USD, next-day

### What We've Already Built (Real, Working, 345 Tests Passing)

**4 Signal Sources (all implemented and tested):**
1. LLM Ensemble — Claude Haiku + GPT-4.1-mini + Groq Llama 3.3 run in parallel, anti-anchoring (models never see market price), Platt-calibrated (A=0.5914, B=-0.3977, OOS Brier 0.2451), consensus gating (75%+ agreement), category routing (skip sports/crypto for LLM), 71.2% backtest win rate on 532 markets
2. Smart Wallet Flow Detector — monitors top Polymarket wallets via Data API, 5-factor activity scoring, convergence detection (N of top-K wallets on same side), 76%+ confidence threshold
3. LMSR Bayesian Engine — sequential Bayesian update in log-space with LMSR softmax pricing, blended 60% posterior + 40% flow price, 828ms avg cycle time
4. Cross-Platform Arb Scanner — matches Polymarket to Kalshi markets via title similarity, detects YES_ask + NO_ask < $1.00 after fees

**Edge Discovery Pipeline (src/):**
- 83 features across 7 groups (price state, volatility, microstructure, wallet flow, time structure, cross-timeframe, basis lag)
- 10 strategy family modules in src/strategies/
- 6 automated kill rules with specific thresholds
- Walk-forward temporal cross-validation
- Monte Carlo simulation (10,000 paths)
- Auto-generated reports (FastTradeEdgeAnalysis.md)

**Infrastructure:**
- Dublin AWS Lightsail VPS (eu-west-1), 5-10ms to Polymarket CLOB
- Python 3.12, asyncio, SQLite, systemd
- FastAPI monitoring dashboard (9 endpoints)
- Telegram alerting

### What We've Tested and REJECTED (DO NOT Re-Propose These Exact Strategies)

| # | Strategy | Kill Reason |
|---|----------|-------------|
| R1 | Residual Horizon Fair Value | Insufficient signal count (8 signals) |
| R2 | Volatility Regime Mismatch | 32.35% win rate on 34 signals, negative OOS EV, decays over time |
| R3 | Cross-Timeframe Constraint Violation | Negative EV post-costs |
| R4 | Chainlink vs Binance Basis Lag | 1.56% taker fee exceeds 0.3-0.8% spread |
| R5 | Mean Reversion After Extreme Move | Insufficient signals in prediction markets |
| R6 | Time-of-Day Session Effects | No significant pattern found |
| R7 | Order Book Imbalance (raw) | Partial CLOB data (404s), negative EV |
| R8 | ML Feature Discovery (brute force) | No features survived walk-forward |
| R9 | Latency Arbitrage (Crypto Candles) | 1.56% taker fee kills any speed edge |
| R10 | NOAA Weather Bracket Rounding | NWS rounding creates 27-35% accuracy, insufficient |

**Key lesson from rejections:** The dominant failure mode is that taker fees (1.56%+ on crypto markets) kill edges that look promising pre-cost. Strategies that require fast execution (taker orders) need alpha > 2% to survive. Strategies executable with maker orders have a 1-3% structural advantage.

### What's Already in Our Pipeline (30 Strategies — You May Refine But Don't Repeat)

1. NOAA Multi-Model Weather Consensus (GFS+ECMWF+HRRR)
2. Polling Aggregator Divergence (538/RCP vs PM)
3. Favorite-Longshot Bias (NO-side)
4. Government Data Release Front-Running (FRED/BLS)
5. Multi-Model LLM Ensemble (Claude+GPT+Grok)
6. News Sentiment Spike Detection
7. Google Trends Surge Detector
8. Wikipedia Pageview Anomaly
9. Resolution Rule Misread Arbitrage
10. Time Decay / Theta Harvesting
11. Sentiment/Contrarian Dumb Money Fade
12. Calibration Bin Specialization
13. Opening vs Closing Line Drift
14. ECMWF vs GFS Divergence
15. Congressional Voting Record Predictor
16. Earnings Surprise Momentum
17. Cross-Platform Price Divergence
18. Social Sentiment Cascade (Twitter/X)
19. Order Book Imbalance (enhanced)
20. Expert Forecast Aggregation (Metaculus)
21. Seasonal Weather Pattern
22. Fed Funds Futures Implied Probability
23. Geopolitical Event Escalation Model
24. Insider Wallet Activity (on-chain)
25. Regression to Base Rate (new market overshoot)
26. Liquidity-Weighted Confidence
27. Category Momentum
28. Pre-Resolution Exit (sell at 90%+)
29. Stale Market Detection
30. Prompt A/B Rotation

### Our Constraints

- **Capital:** $247.51 USDC (Polymarket) + $100 USD (Kalshi). Total ~$350.
- **Monthly budget for data:** <$100
- **Team:** One human (John) + AI agents (Claude, ChatGPT, Cowork mode)
- **Implementation time per strategy:** 1-2 weeks max
- **Must be testable** with measurable signal (no "just have better intuition")
- **Must survive realistic cost assumptions** (not just backtested pre-fees)

---

## The Research Request

Generate **100 distinct, concrete, implementable trading strategy hypotheses**. These must be NEW — not restating the 30 already in our pipeline. You may build on or combine elements from existing strategies, but each must be a distinct testable hypothesis.

### For Each Strategy, Provide:

1. **Name** (concise, descriptive)
2. **Category** (from the list below)
3. **Mechanism** (2-3 sentences: WHY would this create edge? What market inefficiency does it exploit? Be specific about the causal mechanism.)
4. **Signal Definition** (pseudocode: how the system detects and acts. Include specific thresholds where possible.)
5. **Data Source** (specific API, dataset, or feed — with URL and cost)
6. **Expected Alpha** (realistic range AFTER fees. Be honest — if it's likely <1%, say so.)
7. **Frequency** (how many tradeable signals per week/month?)
8. **Time Horizon** (signal to resolution: minutes / hours / days / weeks)
9. **Key Risk** (the single most likely reason this fails)
10. **Cost-Feasibility Note** (Maker-compatible? Requires taker? Minimum alpha to survive fees?)
11. **Novelty Assessment** (Known strategy applied to PMs / Novel application / Genuinely novel)
12. **Kill Hypothesis** (one testable sentence: if THIS is true, the strategy is dead)
13. **Composite Score** (1.0–5.0, using our rubric below)

### Composite Scoring Rubric

| Dimension | Weight | Scale |
|-----------|--------|-------|
| Edge Magnitude | 30% | Expected alpha after costs (1=<1%, 5=>15%) |
| Data Availability | 25% | Free + reliable API = 5, paid + unreliable = 1 |
| Implementation Ease | 25% | Weekend hack = 5, month of work = 1 |
| Durability | 20% | Structural (years) = 5, fleeting (weeks) = 1 |

---

## Categories (100 Strategies Distributed Across These)

### Category A: Information Advantage (15-20 strategies)
Strategies where we systematically access or process information faster/better than average participants. Specialized data feeds, domain-specific models, expert forecast aggregation, structured data parsing that humans skip.

### Category B: Behavioral Bias Exploitation (15-20 strategies)
Strategies profiting from documented cognitive biases in PM pricing. Go BEYOND basic favorite-longshot (we have that). Think: anchoring to round numbers, recency bias, availability heuristic, narrative-driven mispricing, confirmation bias in political markets, gambler's fallacy, herding, panic selling, sunk cost effects.

### Category C: Market Microstructure (15-20 strategies)
Edges from how the market mechanism itself creates exploitable patterns. Order flow, spread dynamics, settlement mechanics, cross-platform arbitrage, fee structure exploitation, queue position, market creation patterns, resolution timing.

### Category D: Alternative Data / External Signals (15-20 strategies)
Non-traditional data sources: satellite imagery, shipping data, regulatory filings, social media beyond sentiment, IoT, flight tracking, job postings, domain registrations, app store data, patent filings, corporate insider behavior.

### Category E: Meta-Strategies / System-Level (10-15 strategies)
How to trade rather than what to trade. Portfolio construction, fee optimization, capital velocity, market selection, timing, regime detection, strategy rotation, drawdown management.

### Category F: AI/ML Enhancement (10-15 strategies)
Improve the AI system itself. Better prompts, ensemble techniques, calibration methods, active learning, reinforcement learning from past trades, LLM-as-analyst, automated hypothesis generation, adversarial testing.

---

## Constraints on Your Proposals

1. **Be realistic about fees.** If taker orders required: alpha must exceed 1.56% (crypto) or ~1% (fee-bearing) or ~7bp × p(1-p) (Kalshi). Most fast-trade strategies die here. Flag it.

2. **Be specific about data.** "Use social media" is not a strategy. "Monitor Reddit r/politics daily thread, compute 6-hour rolling comment velocity z-score via Pushshift API, trigger signal when z > 2.5 on markets tagged 'politics'" IS a strategy.

3. **Be honest about novelty.** If this is momentum trading in a prediction market wrapper, say so.

4. **Consider our capital constraint.** $350 total. Strategies needing $10K+ for statistical significance: flag as capital-constrained.

5. **Free data preferred.** If paid, specify cost and justify against expected alpha.

6. **Prefer maker orders.** Strategies using maker orders get +1.56% structural alpha advantage on crypto markets.

7. **Include at least 10 genuinely novel strategies** not documented in PM trading contexts.

8. **Include at least 10 strategies exploiting specific Polymarket/Kalshi mechanics** (UMA oracle, CLOB quirks, fee-free vs fee-bearing, Gamma API features, Polygon settlement).

9. **Include at least 5 strategies per market category:** politics, weather, crypto, economics, geopolitical, sports, science/tech.

10. **For every strategy, include a kill hypothesis** — the testable prediction that would immediately disqualify it.

---

## Output Format

For each strategy:

```
## [Category]-[Number]. [Strategy Name]
**Category:** [A/B/C/D/E/F]
**Market Types:** [politics, weather, crypto, economics, geopolitical, sports, science/tech, all]
**Mechanism:** [2-3 sentences: why this edge exists]
**Signal:** [pseudocode with thresholds]
**Data Source:** [API/feed name, URL, cost]
**Expected Alpha:** [X-Y% after costs] | **Viability:** [Likely / Possible / Unlikely / Educational]
**Frequency:** [N signals per week/month]
**Time Horizon:** [minutes / hours / days / weeks]
**Key Risk:** [1 sentence: primary failure mode]
**Cost Feasibility:** [Maker-only / Requires taker (need >X% alpha) / Mixed]
**Novelty:** [Known adaptation / Novel application / Genuinely novel]
**Kill Hypothesis:** [If X, this strategy is dead]
**Composite Score:** [X.X / 5.0]
```

---

## After Generating All 100, Provide These Analyses

### 1. Top 10 Build Now
The 10 strategies with the best combination of: high expected alpha, low implementation complexity, free data, maker-compatible, and reasonable durability. One-sentence justification each.

### 2. Top 10 Most Novel
Strategies nobody else is likely testing in prediction markets. The ones that would make an experienced quant say "huh, I never thought of that."

### 3. Top 5 Most Capital-Efficient
Work best with <$500 bankroll. High frequency, small edge per trade, compounds over many trades.

### 4. Top 5 Best for Kalshi Specifically
Strategies that exploit Kalshi's specific features (CFTC regulation, government data resolution, cent-based pricing, different fee structure).

### 5. Top 5 Best for Weather Markets
Our weather model consensus strategy was close (R10 was rejected for rounding issues, not for the core mechanism). Which weather strategies have the best chance?

### 6. Category Distribution
How many in each of our 6 categories? Where did you find the most promising strategies?

### 7. Estimated Survival Rate
If we test all 100 through our pipeline (6 automated kill rules, realistic costs, walk-forward validation), how many do you expect to survive? Our historical rate is 0/10. Be honest.

### 8. Blind Spots
What categories or approaches did you NOT cover that might be worth exploring? What would you research next if you had more time?

### 9. The Honest Assessment
Which 10 strategies on this list do you think are most likely to actually generate positive expected value after costs in live prediction market trading? Not "interesting to test" — actually profitable. If the answer is "probably none of them," say that and explain why.

---

## Why This Matters

We are not just generating a strategy list. We are creating the input to the world's most documented public edge discovery process. Every strategy on this list becomes:

- A testable hypothesis in our pipeline
- A page on our website (pass or fail)
- An entry in our strategy encyclopedia
- Educational content for anyone learning about agentic trading
- A contribution to the open-source research record

The strategies that fail are as valuable as the ones that succeed. They map the territory of what doesn't work, which is the real contribution to the field. After this cycle, our website will have 130+ documented strategy hypotheses — the most comprehensive public catalog of prediction market trading strategies ever assembled.

Be thorough. Be specific. Be honest. The honest assessment is what builds credibility with the quant traders and researchers who are our target audience.

---

*This prompt is part of the Elastifund edge discovery flywheel (Cycle 1). Results will be validated through our automated hypothesis testing pipeline, backtested with realistic cost assumptions, and published as open-source research.*

*github.com/CrunchyJohnHaven/elastifund | johnbradleytrading.com*
