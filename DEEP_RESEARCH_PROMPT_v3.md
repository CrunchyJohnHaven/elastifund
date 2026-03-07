# Deep Research Prompt v3: Next 100 Strategies for the Elastifund Flywheel
**Date:** 2026-03-07
**For use with:** Claude Deep Research, ChatGPT Deep Research, Gemini Deep Research
**Owner:** John Bradley | Elastifund
**Context:** This prompt is Phase 1 of the Elastifund research flywheel (Cycle 1). Results feed directly into our public research diary, GitHub repo, and the world's most comprehensive open-source resource on agentic trading systems at johnbradleytrading.com.

---

## Who You Are

You are a senior quantitative research analyst at a prediction market trading firm. You think like a scientist: every claim needs evidence, every strategy needs a kill criterion, and honesty about what doesn't work is more valuable than optimism about what might.

You are working for Elastifund, a fully open-source, agent-run trading research project. The AI agent (JJ) makes all trading decisions within safety boundaries set by the human infrastructure engineer (John Bradley). The project has a dual mission: (1) discover profitable trading edges on prediction markets, and (2) build the world's most comprehensive public educational resource on agentic trading systems.

**Critical instruction: Be radically honest.** If a strategy has a 5% chance of working, say 5%. If our approach has a fundamental flaw, say so. The research diary publishes failures as thoroughly as successes. Cherry-picked optimism is worse than useless — it wastes our limited capital and engineering time.

---

## What We Have Already Built and Tested (Don't Repeat These)

### The System (Real, Working, Deployed)

**Infrastructure:**
- Dublin VPS (AWS Lightsail eu-west-1), 5-10ms latency to Polymarket CLOB (AWS London eu-west-2)
- Python 3.12, py-clob-client, asyncio, SQLite
- Polymarket: CLOB WebSocket, RTDS feed (Binance + Chainlink streams), Gamma API, Data API
- Kalshi: RSA-signed API, connected ($100 USD)
- Binance: WebSocket kline feeds
- 345 unit tests passing across all modules
- Public GitHub: github.com/CrunchyJohnHaven/elastifund (MIT)

**4 Signal Sources (integrated, tested):**
1. **LLM Probability Estimator** — Claude Haiku + GPT-4.1-mini + Groq Llama 3.3 in parallel. Anti-anchoring (AI never sees market price). Platt scaling (A=0.5914, B=-0.3977). Category routing. Asymmetric thresholds (YES 15%, NO 5%). Agentic RAG via DuckDuckGo. Consensus gating (75%+ model agreement). 34 tests.
2. **Smart Wallet Flow Detector** — Monitors Polymarket trade feed for institutional wallet convergence. 5-factor wallet scoring. Signal when 3+ top wallets converge on same side within 30 min. 1/16 Kelly sizing.
3. **LMSR Bayesian Engine** — Sequential Bayesian update in log-space. 60% posterior + 40% LMSR flow price blend. 828ms avg cycle. 45 tests.
4. **Cross-Platform Arb Scanner** — Polymarket ↔ Kalshi title matching (SequenceMatcher + Jaccard, 70% threshold). Fee-aware: YES_ask + NO_ask < $1.00 after all fees. 29 tests.

**Edge Discovery Pipeline (automated, `src/`):**
- 83 features across 7 groups (price, vol, microstructure, wallet flow, time, cross-timeframe, basis lag)
- 10 strategy hypothesis modules, 6 model types (baseline, logistic, tree, MC GBM, regime-switching, resampling)
- 6 automated kill rules: insufficient signals (<50), negative OOS expectancy, cost stress failure, calibration error >0.2, parameter instability, regime decay
- Walk-forward temporal cross-validation
- Current status: **REJECT ALL** — all tested hypotheses failed kill rules

**Capital:** $247.51 USDC on Polymarket + $100 on Kalshi = $347.51 total.

### What We've Tested and the Specific Results (30 Strategies — Do NOT Repeat These)

```
DEPLOYED (6 — integrated into jj_live.py):
  1. LLM anti-anchoring probability estimation (71.2% backtest win rate, 532 markets)
  2. Platt scaling calibration (Brier 0.286→0.245 OOS improvement)
  3. Asymmetric YES/NO thresholds (76.2% NO win rate, favorite-longshot bias)
  4. Category routing (politics/weather=trade, crypto/sports=skip)
  5. Fee-aware edge gating (maker-only on fee-bearing markets)
  6. Quarter-Kelly position sizing (+309% outperformance vs flat sizing in backtest)

BUILDING (5 — code complete, not yet live):
  7. Smart wallet flow consensus copying
  8. LMSR Bayesian pricing engine
  9. Multi-model LLM ensemble (Claude+GPT+Groq median)
  10. Cross-platform Polymarket↔Kalshi arb
  11. Multi-source confirmation layer (2+ sources = boosted sizing)

TESTED & REJECTED (10 — with specific kill reasons):
  12. Oracle latency arb (Binance vs Chainlink) → KILLED: 1.56% taker fee at p=0.50 exceeds 0.3-0.8% spread
  13. Residual horizon fair value → KILLED: 8 signals, 50% win rate, insufficient data + negative OOS EV
  14. Volatility regime mismatch → KILLED: 34 signals, 32.35% win rate, negative EV, decays over time
  15. Cross-timeframe constraint violation → KILLED: 21 signals, 0% win rate, complete failure
  16. Chainlink vs Binance basis lag → KILLED: taker fee exceeds any capturable spread
  17. Mean reversion after extreme move → KILLED: 0 signals generated, insufficient data
  18. Time-of-day session effects → KILLED: 0 signals, no significant pattern found
  19. Order book / flow imbalance → KILLED: 5 signals, 0% win rate, CLOB 404 issues
  20. ML feature discovery scanner → KILLED: no features survived walk-forward validation
  21. NOAA weather bracket arb (Kalshi) → KILLED: NWS model only 27-35% accurate, rounding destroys edge

IN RESEARCH PIPELINE (9 — evaluated, not yet coded):
  22. NOAA multi-model weather consensus (GFS+ECMWF+HRRR)
  23. Polling aggregator divergence (FiveThirtyEight/RCP vs market)
  24. Government data release front-running (FRED/BLS consensus)
  25. News sentiment spike detection (NewsData.io / GDELT)
  26. Google Trends surge detector
  27. Wikipedia pageview anomaly
  28. Resolution rule misread arbitrage
  29. Time decay / theta harvesting near expiry
  30. Sentiment/contrarian dumb money fade (Reddit, AAII, CNN F&G)
```

### Key Research Findings That Constrain the Search Space

**DO NOT propose strategies that violate these empirically established constraints:**

1. **Taker fees kill taker-only strategies at mid-range prices.** Polymarket crypto markets: feeRate=0.25, exponent=2, polynomial formula Fee = C × p × 0.25 × (p(1-p))². Max effective fee 1.56% at p=0.50. Breakeven edge vs taker: ~0.78% at p=0.50 on crypto, ~0.35% on sports. Any strategy requiring taker execution at mid-range prices needs >1.56% raw edge to survive. (Source: Polymarket fee docs, jbecker.dev analysis, our RTDS research)

2. **Makers win, takers lose.** Across 72.1M Polymarket trades analyzed by jbecker.dev: makers +1.12% excess return, takers -1.12%. Maker fee = 0% + 20% rebate pool from taker fees. Any viable strategy should default to maker execution. (Source: jbecker.dev)

3. **Only 7.6% of Polymarket wallets are profitable.** 0.51% earned >$1K. Successful bots primarily use arbitrage and speed, not narrative analysis. (Source: jbecker.dev, Polymarket analytics)

4. **LLM calibration is fragile.** Most prompt engineering techniques HURT calibration. Only base-rate-first prompting helps (−0.014 Brier). Chain-of-thought, Bayesian reasoning prompts, elaborate prompts all worsen performance. Acquiescence bias: Claude skews YES. Never show LLM its own priors when re-estimating. (Source: Schoenegger 2025, KalshiBench arXiv:2512.16030)

5. **Competition is real and accelerating.** OpenClaw: ~$1.7M profit. Fredi9999: $16.62M all-time. Susquehanna recruiting prediction market traders. Open-source bots proliferating (Poly-Maker, Discountry, Polymarket Agents SDK). Alpha decay accelerating — Polymarket added fees + random latency delays specifically to curb arb bots.

6. **Dublin is in the competitive latency band.** Polymarket CLOB is AWS London (eu-west-2). Dublin = 5-10ms. London colocation = <1ms. New York = 70-80ms. The bottleneck for us is stale REST polling → WebSocket upgrade matters more than geographic relocation. (Source: our LatencyEdgeResearch.md)

7. **The Chainlink tie-band edge is theoretically interesting but practically thin.** At 8-decimal BTC/USD precision, exact-tie probability is minuscule except in extremely low-vol micro-windows in the final seconds. Our R13 (Residual Horizon Fair Value) was a simpler version of this and produced only 8 signals. The maker-first variant deserves further investigation but the raw tie-band alpha is insufficient alone. (Source: our R1 test results, Gemini structural analysis)

8. **Fast-market (5m/15m) crypto markets have specific microstructure.** RTDS provides simultaneous Binance + Chainlink feeds. Resolution is strictly Chainlink-based. Market participants over-anchor to Binance. The basis divergence between feeds is real but narrow. Maker-only post-only orders + rebate capture is the viable execution mode. (Source: research/RTDS_MAKER_EDGE_IMPLEMENTATION.md, Gemini structural analysis)

9. **Academic evidence hierarchy for LLM forecasting improvement (ranked by Brier delta):**
   - Agentic RAG: −0.06 to −0.15 (largest impact)
   - Platt scaling: −0.02 to −0.05
   - Multi-run ensemble (3-7 runs): −0.01 to −0.03
   - Base-rate-first prompting: −0.011 to −0.014
   - Structured scratchpad: −0.005 to −0.010
   - Two-step confidence elicitation: −0.005 to −0.010
   - HARMFUL: Bayesian reasoning prompts (+0.005 to +0.015 worse)
   (Source: Schoenegger 2025, Alur/Bridgewater 2025, Halawi 2024, Lightning Rod Labs 2025)

10. **Market making realistic returns:** $50-200/mo on $1-5K capital, $200-$1K/mo on $5-25K, $1-5K/mo on $25-100K. Requires active volume + liquidity incentives. (Source: our competitive landscape deep research)

---

## What I Need From You: 100 NEW Strategies

Produce **100 distinct, concrete, implementable trading strategy hypotheses** that we have NOT already explored. Each must be genuinely new — not a rephrasing of our existing 30.

### For Each Strategy, Provide This Exact Format:

```
### [Category]-[Number]. [Strategy Name]
**Mechanism:** [2-3 sentences: WHY does this edge exist? What structural, behavioral, or informational asymmetry creates it?]
**Signal:** [Precise, programmable definition. "Use sentiment analysis" is not a signal. "When 6h Reddit comment count on mapped tickers exceeds 3× 30d rolling average AND Claude estimate diverges from market by >10%" IS a signal.]
**Data:** [Specific API/feed with URL. Cost: free/$X/mo]
**Alpha:** [Realistic bps range after costs] | **Viability:** [Likely / Possible / Unlikely / Educational]
**Horizon:** [Signal resolution time] | **Capacity:** [$X before edge degrades] | **Durability:** [Months/years/structural]
**Complexity:** [S = weekend / M = 1-2 weeks / L = month+]
**Synergy:** [How it integrates with our existing 4 signal sources + pipeline]
**Kill Criterion:** [What specific, measurable result kills this hypothesis?]
**Risk:** [Primary failure mode]
**Who's Doing This:** [Known competitors or public implementations]
**Honest P(Works):** [X%]
```

### Categories (100 Total, Roughly These Counts)

**A. Prediction Market Microstructure (12 strategies)**
Order book dynamics, fee structure exploitation, resolution mechanics, market maker behavior, liquidity patterns. Focus on Polymarket CLOB mechanics and the maker rebate paradigm. Do NOT repeat basic spread capture or taker latency arb (we've tested those).

Include: queue position optimization, inventory-neutral binary market making, dynamic spread adjustment based on information flow, new market listing patterns, volume/liquidity seasonality on CLOB, price impact asymmetry (YES vs NO liquidity depth differences), iceberg order detection, market creation timing arbitrage, CLOB vs AMM fragmentation, tick size effects, multi-leg correlated market hedging.

**B. Cross-Market & Cross-Platform Arbitrage (10 strategies)**
Polymarket ↔ Kalshi ↔ Metaculus ↔ Betfair ↔ PredictIt ↔ traditional financial instruments. Do NOT repeat basic same-question arb (we have that). Focus on: conditional probability violations between related markets, mutually-exclusive-collectively-exhaustive portfolio mispricing, prediction market ↔ options market relative value, implied correlation extraction, triangular arb across 3+ correlated binary outcomes.

**C. Information Latency & Alternative Data (15 strategies)**
Being faster to process public information. Focus on data sources we haven't explored: satellite imagery, flight tracking (ADS-B), shipping data (AIS), court dockets (PACER), FDA calendars, patent filings, congressional stock disclosures (STOCK Act), lobbying disclosures, job posting patterns, domain registrations, app store rankings, GitHub commit patterns, Glassdoor reviews, dark pool activity signals, central bank communication parsing (FOMC minutes word frequency).

**D. LLM & AI-Specific Edges (12 strategies)**
Edges that ONLY work because we have AI agents. Focus on novel approaches we haven't tried: multi-agent debate architectures, LLM-as-judge for resolution ambiguity, domain-specific fine-tuning (LoRA on Polymarket resolved markets), retrieval-augmented probability estimation with structured knowledge bases, chain-of-verification (separate estimation from calibration), synthetic data generation for rare events, transfer learning (train on Metaculus community, apply to Polymarket), conformal prediction for uncertainty-aware sizing, causal inference for event dependency chains, active learning for optimal data labeling.

**E. Behavioral & Psychological Exploitation (8 strategies)**
Go BEYOND favorite-longshot bias (we've captured that). Include: anchoring to round numbers (markets cluster at 5% increments), availability heuristic after dramatic events, narrative-driven mispricing (compelling story ≠ likely outcome), confirmation bias in political markets (partisan traders systematically wrong), disposition effect (prediction market traders hold losers), gambler's fallacy at resolution boundaries, herding at market open, panic selling near resolution deadlines, overreaction to vivid low-probability events, under-reaction to base rate changes.

**F. Time-Series & Statistical Patterns (10 strategies)**
Temporal patterns we haven't tested: day-of-week liquidity effects, pre-weekend positioning, holiday effects, end-of-month rebalancing, political cycle seasonality, intraday volatility smile on binary markets, autocorrelation in prediction market returns, momentum and reversal at different horizons, open interest → resolution probability mapping, settlement clustering effects.

**G. Execution & Market-Making Refinements (8 strategies)**
HOW to trade better with what we have. Focus on: optimal maker order placement timing relative to candle boundaries, spread capture with inventory management for binary outcomes, dynamic spread adjustment based on time-to-resolution, batch order optimization across multiple markets, smart order routing between Polymarket and Kalshi, partial fill management, pre-resolution exit timing optimization (sell at 80% edge capture vs hold), order flow toxicity detection (when to pull quotes).

**H. Portfolio & Meta-Strategies (10 strategies)**
Edge from portfolio construction: correlation-aware position sizing for binary portfolios, Kelly refinements for correlated bets, volatility targeting across prediction market positions, drawdown-contingent strategy switching, regime detection for strategy rotation, bankroll segmentation by strategy type, hedge construction with opposing binary markets, capital velocity optimization via staggered resolution timing, portfolio rebalancing triggers, market-neutral binary spreads.

**I. Novel / Wild Card Ideas (15 strategies)**
The creative section. At least 10 should make an experienced quant say "I never thought of that." Include ideas that are speculative but testable. Satellite parking lot counts for retail earnings markets. Wayback Machine for detecting pre-announcement website changes. Congressional jet tracking for legislative outcome markets. Wikipedia edit patterns (edit wars correlate with market uncertainty). Social media influencer position tracking. Prediction tournament leaderboard scraping. AI-generated counter-narratives to test market conviction. Synthetic prediction markets as calibration training grounds. Cross-language news arbitrage (Chinese/Russian media breaking stories before English). Discord alpha group monitoring. Twitch stream viewership for esports markets.

---

## Composite Scoring (Rank All 100)

| Dimension | Weight | Definition |
|-----------|--------|-----------|
| **Testability** | 2× | Can we validate with existing data before risking capital? (0-10) |
| **Implementation Speed** | 2× | How quickly to working prototype given our codebase? (0-10) |
| **Edge Durability** | 1.5× | Will this persist as more bots enter? (0-10) |
| **Capital Efficiency** | 1.5× | Return per dollar of locked capital? (0-10) |
| **Synergy** | 1× | Integrates with our existing signal sources, execution infra, pipeline? (0-10) |

**Composite = (Testability×2 + Speed×2 + Durability×1.5 + CapEff×1.5 + Synergy×1) / 8**

---

## Part 2: Top 30 Research Vectors (Extended Specification)

From the 100 strategies, identify the 30 most promising for our specific situation. For each, provide the extended spec:

```
## Research Vector #N: [Name]
**Composite Score:** [X.X/5.0]
**Edge Class:** [Category from above]

### Core Hypothesis
[One sentence, testable, falsifiable]

### Why Underexploited
[Specifically: why hasn't Jump Trading already captured this?]

### Data Required
[API, dataset, URL, cost]

### Signal Logic (Pseudocode)
[Programmable, concrete]

### Expected Net Impact
[Basis points after ALL costs, with confidence interval]

### Backtest Design
[How to validate without lookahead bias — specific methodology]

### Implementation Estimate
[Days, dependencies, which existing modules can be reused]

### Kill Criteria
[Precise: what p-value, win rate, or EV threshold kills this?]

### Academic Foundation
[Full citations — author, title, venue, year, DOI/arXiv ID]

### Honest Assessment
Probability this actually works: [X%]
Probability this is worth the research time even if it fails (we learn something valuable): [Y%]
```

---

## Part 3: 60-Day Research Sprint Plan

Given our constraints ($347.51 capital, 1 engineer + AI agents, existing pipeline), propose a 60-day sprint in 4 two-week cycles:

**Cycle 1 (Days 1-15): Foundation + Quick Wins**
- Which 5-7 strategies share infrastructure and compound?
- What data collection starts on Day 1?
- Paper trading criteria before go/no-go

**Cycle 2 (Days 16-30): Information Edge Blitz**
- Which 5-7 information-edge strategies?
- What data pipelines get built?
- Go/no-go criteria

**Cycle 3 (Days 31-45): AI/ML Frontier**
- Which 5-7 AI/ML strategies?
- Model training/fine-tuning required?
- Go/no-go criteria

**Cycle 4 (Days 46-60): Portfolio Optimization + Live Validation**
- Which strategies survived?
- How do they combine?
- Projected performance of the combined system?

For each cycle: exact strategies (by number from Part 1), data setup required, minimum sample sizes, kill rules for the entire cycle, diary entries to publish, and Deep Research prompts for the NEXT cycle.

---

## Part 4: Literature Deep Dive (2024-2026)

Search comprehensively for:

1. **Prediction market efficiency post-fee-changes.** How did Polymarket's fee structure changes (Sept 2024, Jan 2025, Feb 2026, Mar 2026) affect market efficiency? New papers measuring accuracy vs alternatives?

2. **LLM forecasting 2025-2026.** Any improvements with Claude 4/4.5, GPT-5, Gemini 2.5, Llama 4? New calibration methods? New prompting techniques that actually improve Brier scores?

3. **Small-capital systematic trading.** Case studies of traders scaling from <$1K. What worked? Timeline?

4. **Agentic AI for finance.** Autonomous trading agents, multi-agent systems, tool-use agents in production. What's working?

5. **Prediction market microstructure.** CLOB dynamics, oracle mechanics, fee structures, market making on binary outcomes.

6. **Conference papers (NeurIPS, ICML, AAAI 2024-2026):** Forecasting, calibration, LLM decision-making, prediction markets.

7. **Open-source prediction market bots.** GitHub landscape. What exists? How does our system compare?

For each source: full citation, key finding relevant to us, and whether it changes our strategy or not.

---

## Part 5: Meta-Strategy Assessment (Radical Honesty)

1. **Realistic probability of finding a real edge.** Given competition (Jump, Susquehanna, OpenClaw), our capital ($347), and the 7.6% profitability base rate — what's the realistic probability of: (a) finding any edge, (b) edge surviving costs, (c) edge scaling past $1K, (d) edge persisting 6+ months?

2. **The 5 most likely failure modes.** For each: probability, what we'd do about it, and the educational value of documenting the failure.

3. **Institutional review.** Write 500 words as a quant researcher at Jump Trading evaluating whether to hire John Bradley based solely on the public GitHub repo and website. What impresses? What concerns? What would you change?

4. **Blind spots.** What strategy class, data source, or market dynamic are we completely missing that institutional players exploit?

5. **If we could only do ONE thing in the next 7 days.** What maximizes P(finding real edge)? Why?

6. **Open-source tradeoff.** Publishing everything: does this help or hurt alpha discovery? How to balance?

7. **The education play.** Specifically what content makes a quant say "best resource I've seen"? What makes a layperson say "I understand this"? Be concrete about content types, depth, and presentation.

---

## Part 6: 5 Follow-Up Deep Research Prompts

Generate 5 self-contained follow-up prompts (500-1000 words each) targeting specific strategy clusters from Part 2. Each should be pasteable into a fresh deep research session.

---

## Output Format

1. **Executive Summary** (1,000 words) — Top 5 findings, honest assessment
2. **Part 1: 100 Strategy Taxonomy** (~200 words each = ~20,000 words)
3. **Part 2: Top 30 Research Vectors** (extended specifications)
4. **Part 3: 60-Day Sprint Plan** (week-by-week)
5. **Part 4: Literature Deep Dive** (all papers with relevance assessment)
6. **Part 5: Meta-Strategy Assessment** (radical honesty)
7. **Part 6: Follow-Up Prompts** (5 prompts)
8. **Appendix A:** All citations with DOIs/URLs
9. **Appendix B:** Data source directory (every API referenced)
10. **Appendix C:** Glossary (for layperson readers of the website)

---

## Guardrails

- No guaranteed returns. Every strategy has failure modes.
- Distinguish "theoretically possible" from "empirically demonstrated on prediction markets."
- If a strategy requires >$10K capital, mark NOT FEASIBLE FOR US.
- If institutional players have already captured it, say so. Explain if a variant might still work for us.
- Prefer robustness and repeatability over headline returns.
- Full bibliographic citations, not vague "research shows."
- Include negative results: strategies known to fail, with citations.
- Every strategy MUST have a kill criterion. No "keep testing indefinitely."

---

## What Makes This Prompt Different From v2

This is v3. v2 produced our existing 30-strategy pipeline. v3 incorporates:
- 10 specific rejection reasons from strategies we actually tested (not theoretical — real data)
- Polymarket polynomial fee formula with exact parameters (feeRate=0.25, exponent=2)
- jbecker.dev 72.1M trade analysis (maker/taker asymmetry quantified)
- Latency geography correction (Dublin is competitive, WebSocket > location)
- Chainlink barrier mispricing analysis (tie-band convexity validated as thin but real)
- RTDS dual-stream architecture now understood (Binance + Chainlink simultaneous feeds)
- Maker rebate paradigm shift (taker → maker-first execution as dominant mode)
- Academic evidence hierarchy (which LLM techniques help vs hurt, ranked by Brier delta)
- Weather bracket failure data (NWS rounding makes model accuracy insufficient)
- Competitive landscape with specific numbers (OpenClaw $1.7M, Fredi9999 $16.62M)

The researcher should NOT waste output on territory we've already mapped. We need genuinely new ideas that account for what we've learned.

---

*This is Cycle 1 of the Elastifund research flywheel. Cycle 0 tested 20+ strategies (10 rejected, 6 deployed, 5 building). Your job is to give us the next 100 — accounting for everything we've learned so far. The entire process, including your response and our analysis of it, will be published openly as part of the most comprehensive public resource on agentic trading systems ever created.*
