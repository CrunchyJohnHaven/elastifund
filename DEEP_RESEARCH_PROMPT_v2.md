# Deep Research Prompt v2: 100 Strategies for Agentic Trading Systems
**Date:** 2026-03-07
**For use with:** Claude Deep Research, ChatGPT Deep Research, Gemini Deep Research
**Owner:** John Bradley | Elastifund
**Context:** This prompt is part of the Elastifund research flywheel. Paste this entire document into a deep research session. Results feed directly into our public research diary, GitHub repo, and the world's most comprehensive open-source resource on agentic trading systems.

---

## Who You Are

You are a senior quantitative research analyst at a prediction market trading firm. You have deep expertise in market microstructure, statistical arbitrage, LLM-based forecasting, and execution optimization. You think like a scientist: every claim needs evidence, every strategy needs a kill criterion, and honesty about what doesn't work is more valuable than optimism about what might.

You are working for Elastifund, a fully open-source, agent-run trading research project. The agent (AI system) makes all trading decisions. The human (John Bradley) builds, improves, and documents the system. The project's dual mission: (1) discover profitable trading edges on prediction markets, and (2) build the world's most comprehensive public resource on agentic trading.

---

## What We Have Already Built and Tested

### Live System (Deployed, Dublin VPS, AWS Lightsail eu-west-1)

**Signal Sources (4 integrated):**
1. **LLM Probability Estimator** — Claude Haiku estimates true probability without seeing market price (anti-anchoring discipline). Platt scaling calibration (A=0.5914, B=-0.3977). Category routing (politics/weather = trade, crypto/sports = skip). Asymmetric thresholds (YES: 15% edge, NO: 5% edge). Maker-only orders (0% fee).
2. **Smart Wallet Flow Detector** — Monitors public Polymarket trade feed for institutional wallet convergence. Scores wallets by 5-factor activity (min 5 trades, 3 markets, $50 volume). Signal when 3+ top wallets converge on same side within 30 min.
3. **LMSR Bayesian Engine** — Sequential Bayesian update in log-space. Blends 60% posterior + 40% LMSR flow price. Target cycle: 828ms avg. 45 unit tests.
4. **Cross-Platform Arb Scanner** — Polymarket vs Kalshi arbitrage detection via title similarity matching. Risk-free arb: YES_ask + NO_ask < $1.00 after fees.

**Confirmation Layer:** 2+ sources agreeing = boosted Kelly sizing. Single source = conservative.

**Backtest Results (532 resolved markets):**
| Metric | Value |
|--------|-------|
| Win rate (best variant) | 71.2% |
| NO-only win rate | 76.2% |
| Brier score (OOS) | 0.217 |
| Monte Carlo ruin prob (10K paths) | 0.0% |
| Estimated ARR (5 trades/day) | +1,692% |

**Capital:** $247 Polymarket USDC (live), $100 Kalshi USD (API connected).

### Edge Discovery Pipeline (Automated, `src/` directory)
- 83-feature engineering across 7 groups (price, vol, microstructure, wallet flow, time, cross-timeframe, basis lag)
- 10 strategy modules, 6 model types (baseline, logistic, tree, Monte Carlo GBM, regime-switching, resampling)
- Automated kill rules: insufficient signals, negative EV, cost stress failure, calibration error, instability, regime decay
- Walk-forward validation with temporal cross-validation
- **Current status: REJECT ALL** — all 9 tested hypotheses failed kill rules (insufficient data or negative expectancy)

### Research Foundation (Verified, Cited)
- **jbecker.dev (72.1M Polymarket trades):** Makers +1.12% excess, takers -1.12%. NO outperforms YES at 69/99 price levels. Category gaps: World Events 7.32pp, Media 7.28pp.
- **Halawi et al. (2024, NeurIPS):** Agentic RAG achieves Brier 0.179 vs human crowd 0.149. System + crowd ensemble = 0.146.
- **Bridgewater AIA (arXiv:2511.07678):** 67% market + 33% AI blend outperforms either alone.
- **Schoenegger et al. (2024, Science Advances):** LLM ensemble statistically indistinguishable from human forecasters.
- **KalshiBench (arXiv:2512.16030):** All frontier models universally overconfident. Extended reasoning worsens calibration.
- **Foresight-32B (2025):** RL fine-tuned for Polymarket, Brier 0.199, only model besides o3 with positive simulated P&L.

### Strategies Explored (Status)
```
DEPLOYED (live):
  1. LLM anti-anchoring probability estimation
  2. Platt scaling calibration
  3. Asymmetric YES/NO thresholds
  4. Category routing
  5. Fee-aware edge gating
  6. Kelly criterion sizing

BUILDING (in progress):
  7. Smart wallet flow copying
  8. LMSR Bayesian pricing
  9. Multi-model ensemble (Claude + GPT + Groq)
  10. Cross-platform Polymarket/Kalshi arb

REJECTED (tested, failed):
  11. Latency arb on crypto candles (killed by 1.56% taker fee)
  12. Residual horizon fair value (insufficient signal, negative EV)
  13. Volatility regime mismatch (32% win rate, decay over time)
  14. Cross-timeframe constraint violation (0% win rate on 21 signals)
  15. Chainlink vs Binance basis lag (killed by fees)
  16. Mean reversion after extreme move (insufficient signal)
  17. Time-of-day session effects (insufficient signal)
  18. Order book imbalance (0% win rate on 5 signals)
  19. Wallet flow momentum (collapses under stress costs)
  20. Kalshi weather bracket rounding (NWS model 27-35% accuracy, negative EV at realistic prices)
```

### Known Constraints
- **Capital:** $350 total across two platforms
- **Competition:** Jump Trading, Susquehanna, Jane Street active with dedicated teams
- **Base rate:** Only 7.6% of Polymarket wallets are profitable, 0.51% with >$1K profit
- **Fees:** Taker fees 0-1.56% depending on market; maker fees 0% + rebate
- **Fill rate:** Maker orders ~60% fill rate
- **Regulation:** CFTC oversight of prediction markets evolving
- **Infrastructure:** One VPS (Dublin), one engineer, AI agents as research force multipliers

---

## What I Need From You

### PART 1: The Complete Strategy Taxonomy (Target: 100 Strategies)

Produce a comprehensive catalog of **100 distinct, concrete trading strategies** applicable to prediction markets (Polymarket, Kalshi, Metaculus) and fast-resolving binary/multi-outcome markets. Organize them into the categories below. Each strategy must be distinct — no duplicates, no vague variations.

For each strategy, provide this exact format:

```
### Strategy [N]: [Name]
- **Category:** [A-H]
- **Mechanism:** [2-3 sentences explaining HOW it generates edge]
- **Signal Definition:** [Precise, programmable definition of when to enter]
- **Data Source:** [Specific API, dataset, or feed with URL if available]
- **Expected Alpha:** [Basis points, with honest confidence level: low/medium/high]
- **Implementation Complexity:** [Hours/days of engineering]
- **Capital Requirement:** [Minimum capital to be viable]
- **Competition Risk:** [Low/Medium/High — can institutions trivially capture this?]
- **Kill Criterion:** [What specific result kills this hypothesis?]
- **Academic Foundation:** [Citation if available, "No published research" if novel]
- **Honest Probability of Working:** [X%]
```

#### Category A — Market Microstructure (Target: 15 strategies)
Strategies exploiting how prediction market order books, matching engines, and fee structures create systematic mispricings.

Cover at minimum:
- Order flow toxicity detection and adverse selection
- Queue position and time priority optimization
- Spread dynamics (when spreads widen/narrow predictably)
- Fee structure arbitrage (maker/taker asymmetry, cross-venue fee differences)
- Market making strategies adapted for binary outcomes
- Liquidity provision timing (when to post vs when to take)
- Fill probability modeling and order type optimization
- Market impact modeling at small and medium scales
- Price impact asymmetry (buying YES vs buying NO)
- Hidden order detection and iceberg order patterns
- Tick size effects on binary markets
- Opening/closing auction dynamics
- Market fragmentation between Polymarket CLOB and AMM
- Multi-leg order strategies (correlated market hedging)
- Rebate optimization and fee tier gaming

#### Category B — Information Edge (Target: 20 strategies)
Strategies exploiting systematic advantages in information acquisition, processing speed, or interpretation.

Cover at minimum:
- Government data release front-running (FRED, BLS, BEA, CPI, NFP)
- Earnings and corporate event anticipation
- Political event forecasting (polls, insider appointment signals)
- Resolution rule misread arbitrage (markets misinterpret settlement criteria)
- Expert network aggregation (Metaculus, Good Judgment Open, INFER)
- Court decision prediction (legal docket analysis)
- Regulatory decision prediction (FDA, SEC, EPA schedules)
- Sports prediction via advanced analytics (ELO, xG, injury reports)
- Weather forecasting superiority (ECMWF vs GFS ensemble vs market)
- Social media early warning (Reddit, Twitter/X surge detection)
- Google Trends surge detection as leading indicator
- Wikipedia pageview anomaly detection
- Congressional voting prediction (bill tracking, whip counts)
- Central bank communication analysis (FOMC minutes, Fedspeak parsing)
- Geopolitical escalation scoring (ACLED, GDELT event databases)
- Breaking news speed advantage (Reuters/AP firehose vs market reaction)
- Earnings call sentiment analysis (NLP on live transcripts)
- Patent filing signals for tech/biotech events
- Lobbying disclosure signals for regulatory outcomes
- Academic preprint signals (arXiv, bioRxiv) for science markets

#### Category C — Statistical / Quantitative (Target: 15 strategies)
Strategies exploiting statistical patterns, calibration advantages, and portfolio construction techniques.

Cover at minimum:
- Category-specific calibration frontier (beyond global Platt scaling)
- Ensemble methods: model stacking, Bayesian model averaging, trimmed mean
- Regime detection and adaptive strategy switching
- Correlation-aware portfolio construction for binary outcomes
- Kelly criterion variants: fractional Kelly, Kelly with estimation error, correlated Kelly
- Time-decay (theta) harvesting near expiry
- Favorite-longshot bias exploitation (quantified)
- Overround / vigorish extraction in multi-outcome markets
- Base-rate anchoring correction (reference class forecasting)
- Calibration transfer learning (train on Metaculus, apply to Polymarket)
- Brier score optimization vs log-score optimization (which is more profitable?)
- Bayesian hierarchical modeling for related markets
- Uncertainty quantification: conformal prediction for binary outcomes
- Mean-variance optimization adapted for binary portfolios
- Historical analogy matching (similar past markets → probability transfer)

#### Category D — Execution Alpha (Target: 10 strategies)
Strategies exploiting how and when orders are placed to improve fills, reduce costs, and capture structural edge.

Cover at minimum:
- Maker/taker dynamic switching based on urgency vs edge magnitude
- Optimal order sizing to minimize market impact on Polymarket CLOB
- Multi-venue execution (Polymarket + Kalshi simultaneous)
- Latency optimization for prediction market APIs
- Time-weighted order placement (TWAP adapted for prediction markets)
- Partial fill management and order amendment strategies
- Pre-resolution exit optimization (sell at 80% edge capture vs hold to resolution)
- Iceberg order strategies for larger positions
- Cross-platform fee arbitrage (maker on one platform, taker on another)
- Inventory management for market making in prediction markets

#### Category E — Alternative Data (Target: 15 strategies)
Strategies using non-traditional data sources to gain information advantage.

Cover at minimum:
- Satellite imagery for weather/agricultural market prediction
- Web scraping pipelines for event detection (schedule changes, cancellations)
- Social media cascade detection (viral momentum as leading indicator)
- Blockchain/on-chain analytics for crypto prediction markets
- Search trend analysis (Google Trends + Wikipedia combined)
- App download data for tech company outcome markets
- Job posting analysis for corporate health signals
- Flight tracking data for geopolitical markets
- Shipping container tracking for trade/tariff markets
- Congressional stock trading disclosure (STOCK Act filings)
- Prediction tournament leaderboard aggregation (top forecasters' positions)
- Academic grant funding signals for science/tech markets
- Real estate listing data for economic markets
- Credit card spending data aggregators for retail/economic markets
- Dark web monitoring for cybersecurity event markets

#### Category F — AI/ML Frontier (Target: 15 strategies)
Strategies at the cutting edge of AI/ML applied to prediction markets.

Cover at minimum:
- Fine-tuned forecasting models (Foresight-32B, domain-specific LoRA)
- Retrieval-augmented generation pipelines for probability estimation
- Reinforcement learning for dynamic position management and exit timing
- Causal inference for event dependency graphs
- Multi-agent debate for probability estimation (agents argue, supervisor decides)
- Chain-of-thought prompting optimization for calibration
- Prompt engineering A/B testing (systematic prompt optimization)
- LLM-as-judge for resolution prediction
- Synthetic data generation for rare event training
- Transfer learning from financial markets to prediction markets
- Graph neural networks for correlated market structure
- Transformer attention analysis (what the model "looks at")
- Active learning for efficient data labeling in prediction markets
- Mixture-of-experts for category-specific forecasting
- Conformal prediction for uncertainty-aware bet sizing

#### Category G — Behavioral / Psychological Edge (Target: 5 strategies)
Strategies exploiting known cognitive biases in prediction market participants.

Cover at minimum:
- Anchoring bias exploitation (markets anchored to round numbers)
- Availability bias (overweighting recent events)
- Contrarian sentiment fading (retail emotional trading as counter-signal)
- Narrative bias (markets overweight compelling stories)
- Disposition effect (traders hold losers, sell winners too early)

#### Category H — Cross-Market / Structural (Target: 5 strategies)
Strategies exploiting relationships between markets or structural features of the platforms.

Cover at minimum:
- Conditional market arbitrage (if market A resolves YES, market B is mispriced)
- Polymarket vs Kalshi price discrepancy trading
- Multi-outcome completeness arbitrage (all outcomes must sum to 100%)
- Calendar spread equivalents in prediction markets
- Related market correlation trading (election + policy markets)

---

### PART 2: Top 30 Prioritized Research Vectors

From the 100 strategies, identify the **30 most promising for our specific situation** (small capital, AI-first, prediction market focus). Rank them by composite score:

**Scoring Criteria (1-5 each):**
1. **Edge Probability:** Realistic chance this strategy produces net-positive returns after costs
2. **Feasibility:** Can we implement it in <2 weeks with our current stack?
3. **Capital Efficiency:** Works with $200-500 bankroll?
4. **Defensibility:** Can Jump Trading trivially replicate it?
5. **Data Access:** Can we get the data free or very cheaply?
6. **Compounding Value:** Does infrastructure built for this enable other strategies?

For each of the top 30, provide the extended specification:

```
## Research Vector #N: [Name]
**Composite Score:** [X.X/5.0]
**Edge Class:** [Microstructure / Information / Statistical / Execution / Alt Data / AI / Behavioral / Structural]

### Core Hypothesis
[One sentence, testable]

### Why Underexploited
[Why hasn't Jump Trading already captured this? Be specific.]

### Data Required
[Specific APIs, datasets, with URLs where available]

### Signal Logic (Pseudocode)
```
[Programmable logic]
```

### Expected Net Impact
[Basis points after all costs, with confidence interval]

### Backtest Design
[How to validate without lookahead bias — specific methodology]

### Implementation Estimate
[Days, dependencies, which existing modules can be reused]

### Kill Criteria
[What specific result kills this hypothesis? Be precise.]

### Academic Foundation
[Full citations — author, title, venue, year, DOI/arXiv ID]

### Honest Assessment
Probability this actually works: [X%]
Probability this is worth the research time even if it doesn't work (i.e., we learn something valuable): [Y%]
```

---

### PART 3: 60-Day Research Sprint Plan

Given our constraints, propose a **60-day research sprint** organized into 4 two-week cycles:

**Cycle 1 (Days 1-15): Foundation Strategies**
- Which 5-7 strategies to test first?
- Why these? (They share infrastructure, they compound, they have highest prior probability)
- What infrastructure gets built that enables future cycles?

**Cycle 2 (Days 16-30): Information Edge**
- Which 5-7 information-edge strategies to test?
- What data pipelines need to be built?
- Go/no-go criteria for the cycle

**Cycle 3 (Days 31-45): AI/ML Frontier**
- Which 5-7 AI/ML strategies to test?
- What model training/fine-tuning is required?
- Go/no-go criteria for the cycle

**Cycle 4 (Days 46-60): Portfolio Optimization**
- Which strategies survived from previous cycles?
- How do they combine in a portfolio?
- What's the projected performance of the combined system?

**For each cycle, specify:**
- Exact strategies being tested (by number from Part 1)
- Data collection setup required (day 1 of each cycle)
- Paper trading criteria (minimum sample size before go/no-go)
- Kill rules (what kills the entire cycle?)
- Deep Research prompts to generate for the NEXT cycle
- Diary entries to publish (minimum 3 per cycle for the website)

---

### PART 4: Literature Deep Dive

Search comprehensively for:

1. **Prediction market efficiency studies (2024-2026):** Is there new evidence on whether Polymarket/Kalshi are efficient? Papers measuring market accuracy vs experts, models, or alternative forecasting methods.

2. **LLM forecasting improvements (2025-2026):** Any new papers showing LLM forecasting accuracy improvements with Claude 4/4.5, GPT-5, Gemini 2.5, Llama 4? New prompting techniques? New calibration methods?

3. **Small-capital algorithmic trading:** Case studies of traders who scaled from <$1K to significant AUM using systematic strategies. What worked? What failed? What was the typical timeline?

4. **Prediction market maker/taker dynamics post-fee changes:** How did Polymarket's fee structure changes (Sept 2024, Jan 2025, Feb 2026) affect market efficiency and trading strategies?

5. **Agentic AI for finance (2025-2026):** Research on autonomous AI agents making trading decisions. Multi-agent systems, tool-use agents, RAG-enabled trading systems.

6. **Conference papers (NeurIPS, ICML, AAAI 2024-2026):** Forecasting, calibration, prediction markets, LLM decision-making.

7. **Open-source trading systems:** GitHub repos for prediction market bots. What exists? How does our system compare?

8. **Market microstructure of blockchain-based prediction markets:** How do Polymarket's CLOB mechanics differ from traditional exchange microstructure?

For each paper/source found, provide: full citation, key finding relevant to us, and whether it changes our strategy.

---

### PART 5: Meta-Strategy Assessment

Answer these questions with radical honesty:

1. **Realistic probability of success:** Given everything known about prediction market efficiency, competition, and our constraints, what is the realistic probability that a small, AI-powered trader can sustainably generate alpha? Distinguish between: (a) finding any edge at all, (b) finding an edge that survives costs, (c) finding an edge that scales past $1K, (d) finding an edge that persists for 6+ months.

2. **Failure modes:** What are the 5 most likely ways our current approach fails? For each, what's the probability and what would we do about it?

3. **Institutional perspective:** Write a 500-word review of our system as if you were a quant researcher at Jump Trading evaluating whether to hire John Bradley. What impresses you? What concerns you? What would you change first?

4. **Blind spots:** Is there a strategy class, data source, or market dynamic we're completely blind to that institutional players are known to exploit? What are the "unknown unknowns" in our research?

5. **Single best investment:** If we could only do ONE thing in the next 7 days to maximize our probability of finding a real edge, what would it be? Why?

6. **Open-source strategy:** We plan to make our entire system public — code, research, results, diary. Does this help or hurt our ability to find and maintain edges? How do we balance openness with alpha preservation?

7. **The education play:** We want our website to be the definitive resource on agentic trading. What content would make an experienced quant trader say "this is the best resource I've ever seen on this topic"? What would make a layperson say "I understand this and it's impressive"? Be specific about content types, depth levels, and presentation.

---

### PART 6: Next Research Prompts

Generate **5 follow-up deep research prompts** that we should run AFTER processing the results of this one. Each prompt should:
- Target a specific strategy cluster from Part 2
- Build on what we expect to learn from this research
- Be self-contained (pasteable into a new deep research session)
- Be 500-1000 words each

---

## Output Format

Structure your response as a single comprehensive research report:

1. **Executive Summary** (1,000 words) — Key findings, top 5 recommendations, honest assessment
2. **Part 1: Strategy Taxonomy** (100 strategies, ~200 words each = ~20,000 words)
3. **Part 2: Top 30 Research Vectors** (detailed specifications)
4. **Part 3: 60-Day Sprint Plan** (week-by-week schedule)
5. **Part 4: Literature Deep Dive** (all papers found with relevance assessment)
6. **Part 5: Meta-Strategy Assessment** (radical honesty section)
7. **Part 6: Next Research Prompts** (5 follow-up prompts)
8. **Appendix A:** All citations with URLs/DOIs
9. **Appendix B:** Data source directory (every API/dataset referenced with access details)
10. **Appendix C:** Glossary of terms (for the layperson reader)

---

## Guardrails

- Do not claim guaranteed returns. Every strategy has failure modes.
- Distinguish clearly between "theoretically possible" and "empirically demonstrated on prediction markets."
- If a strategy requires $100K+ capital, mark it explicitly as NOT FEASIBLE FOR US.
- If a strategy is likely already captured by institutional players, say so and explain why we might still find a variant that works.
- Prefer robustness and repeatability over headline returns.
- Cite specific papers with full bibliographic details, not vague references to "research shows."
- Include negative results: strategies that look promising but are known to fail, with citations.
- Every strategy must have a kill criterion. No "keep testing indefinitely."

---

## Why This Matters

This research feeds directly into the Elastifund flywheel: Research → Implement → Test → Record → Publish → Repeat. Every strategy you identify becomes a diary entry on our website. Every failure you flag saves us days of wasted effort. Every citation you surface becomes educational content.

The output of this prompt will be processed by Claude Code, which will:
1. Add each strategy to `research/edge_backlog_ranked.md`
2. Create implementation tasks for top strategies
3. Update `COMMAND_NODE_v1.0.2.md` with new research findings
4. Generate diary entries for the website
5. Commit everything to the public GitHub repo

The entire process — including this prompt, your response, our analysis of your response, and the trading results that follow — will be published publicly as part of the most comprehensive open-source resource on agentic trading systems ever created.

*This is Cycle 2 of the Elastifund research flywheel. Cycle 1 tested 20 strategies (11 rejected, 6 deployed, 3 building). Your job is to give us the next 100.*
