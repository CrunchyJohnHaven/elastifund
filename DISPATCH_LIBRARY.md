# PREDICTIVE ALPHA FUND — Master Dispatch Library
## Ready-to-Paste Prompts for All AI Resources

**Generated:** 2026-03-05
**Total Prompts:** 42
**Goal:** Maximize simulated ARR → Build investor evidence → Attract capital

---

## DISPATCH ORDER (Run These in Parallel)

### WAVE 1 — Run NOW (P0, highest ARR impact)
| # | Prompt | Tool | Est. Time | ARR Impact |
|---|--------|------|-----------|------------|
| 1 | Combined Backtest Re-run | Claude Code | 30 min | Determines real number |
| 2 | Ensemble API Integration | Claude Code | 45 min | +20-40% |
| 3 | Systematic Edge Discovery | Claude Deep Research | 20 min | Potentially massive |
| 4 | Superforecaster Techniques | Claude Deep Research | 20 min | +15-30% |
| 5 | Advanced Monte Carlo Simulation | Claude Code | 30 min | Investor confidence |
| 6 | News Sentiment Pipeline | Claude Code | 45 min | +15-30% |

### WAVE 2 — Run When Wave 1 Is Cooking (P1)
| # | Prompt | Tool | Est. Time | ARR Impact |
|---|--------|------|-----------|------------|
| 7 | Market Making Strategy | ChatGPT Deep Research | 15 min | +30-60% |
| 8 | Cross-Platform Arbitrage | ChatGPT Deep Research | 15 min | +20-40% |
| 9 | Social Sentiment Integration | ChatGPT Deep Research | 15 min | +15-30% |
| 10 | Investor Report v2 | Cowork | 20 min | Capital attraction |
| 11 | Monthly Performance Dashboard | Cowork | 20 min | Investor retention |
| 12 | Legal Structure Finalization | ChatGPT Deep Research | 15 min | Regulatory compliance |

### WAVE 3 — Background (P2)
| # | Prompt | Tool | Est. Time | ARR Impact |
|---|--------|------|-----------|------------|
| 13-42 | See below | Mixed | Ongoing | Compounding |

---

## ═══════════════════════════════════════
## WAVE 1 PROMPTS — PASTE THESE NOW
## ═══════════════════════════════════════

---

### PROMPT 1: Combined Backtest Re-run with ALL Improvements
**Tool: CLAUDE CODE**
**Priority: P0 — This determines our real number**

```
Read COMMAND_NODE.md in the project folder for full context.

TASK: Run a comprehensive backtest that combines ALL improvements made to date. This is the single most important task — it determines our real ARR number for investor materials.

The backtest must include:
1. CalibrationV2 (Platt scaling: A=0.5914, B=-0.3977)
2. Asymmetric thresholds (YES 15%, NO 5%)
3. Quarter-Kelly position sizing from src/sizing.py
4. Category routing (Politics/Weather priority 3, Crypto/Sports/Fed skip)
5. Capital velocity sorting (top-5 per cycle by edge/days_to_resolution)
6. Confidence-weighted sizing (0.5x for buckets with <10 training samples)
7. Taker fee deduction: fee(p) = p*(1-p)*0.0625 on applicable markets

Run against the full 532-market dataset. Calculate:
- Win rate (overall, YES, NO)
- Brier score (raw and calibrated)
- Total P&L with compounding from $75 starting capital
- ARR at 3, 5, and 10 trades/day
- Maximum drawdown
- Sharpe ratio (daily returns)
- Category-level breakdown

Compare results: Flat $2 vs Quarter-Kelly vs Half-Kelly
Generate charts: equity curve, drawdown, category performance, calibration reliability diagram

OUTPUT: Updated backtest results in backtest/results/, charts in backtest/charts/, summary in BACKTEST_RESULTS.md

DONE WHEN: We have a single, definitive ARR number that includes every improvement. This number goes into the investor report.

SOP: After completing, update COMMAND_NODE.md Section 4 and Section 11 with new numbers. Update STRATEGY_REPORT.md and INVESTOR_REPORT.md.
```

---

### PROMPT 2: Ensemble API Integration (GPT + Grok)
**Tool: CLAUDE CODE**
**Priority: P0 — Multi-model ensemble is proven to improve accuracy**

```
Read COMMAND_NODE.md for full context. Read src/ensemble.py for the existing skeleton.

TASK: Implement the multi-model ensemble for probability estimation. Currently only ClaudeEstimator works. Wire up GPT and Grok.

IMPLEMENTATION:
1. GPTEstimator (src/ensemble.py):
   - Use OpenAI API (gpt-4o or gpt-4.5-preview)
   - Same anti-anchoring prompt structure as Claude (no market price shown)
   - Parse probability from response
   - Handle rate limits and errors gracefully

2. GrokEstimator (src/ensemble.py):
   - Use xAI API (grok-2 or grok-3)
   - Same prompt structure
   - Parse probability from response

3. EnsembleAggregator improvements:
   - Weighted average (weight by historical Brier score per model)
   - Signal only when stdev < 0.15 across models (high agreement)
   - Log individual model estimates for performance tracking
   - Track per-model accuracy over time to auto-adjust weights

4. Configuration:
   - Add OPENAI_API_KEY and XAI_API_KEY to .env template
   - Add ensemble config to core/config.py: enable/disable per model, weights
   - Fallback: if only Claude available, use single-model mode

5. Cost management:
   - GPT-4o: ~$2.50/$10 per MTok — budget ~$15/month
   - Grok-2: ~$2/$10 per MTok — budget ~$15/month  
   - Total ensemble cost: ~$50/month (Claude + GPT + Grok)
   - Only call ensemble on high-edge candidates (>10% raw edge)

TESTING:
- Run ensemble against 50 sample markets from backtest data
- Compare: Claude-only Brier vs Ensemble Brier
- Log: agreement rate, divergence cases, individual model accuracy

OUTPUT: Updated src/ensemble.py, updated .env.example, test results in ensemble_test_results.md

DONE WHEN: `python -m src.ensemble --test` runs 50 markets through all 3 models and reports comparative Brier scores. Ensemble integrated into engine/loop.py with config toggle.

SOP: Update COMMAND_NODE.md Section 2 (architecture) and Section 3 (strategy) with ensemble details.
```

---

### PROMPT 3: Systematic Edge Discovery
**Tool: CLAUDE DEEP RESEARCH**
**Priority: P0 — Finding new edges is the highest-leverage activity**

```
TASK: Identify every possible systematic edge in prediction market trading that an automated system could exploit.

Context: I run a Polymarket trading bot that uses LLM probability estimation. Current edges: favorite-longshot bias (markets overprice YES), category-specific accuracy (politics best, crypto worst), calibration improvement via Platt scaling. Current Brier score: 0.217 (calibrated, out-of-sample).

Research these potential edges:
1. TIME-BASED: Do markets become more efficient as resolution approaches? Is there an optimal entry window (e.g., 2-7 days before resolution)?
2. LIQUIDITY-BASED: Do low-liquidity markets have larger mispricings? What's the optimal liquidity range?
3. VOLUME SPIKES: Do sudden volume increases predict direction? Can we front-run informed money?
4. CORRELATION: Can we exploit correlated markets (e.g., "Will X happen by March" and "Will X happen by June")?
5. RESOLUTION RULE EDGES: How often do markets resolve differently than traders expect due to technical resolution criteria?
6. CROSS-PLATFORM: What arbitrage exists between Polymarket, Kalshi, Metaculus, and sports books?
7. CALENDAR EFFECTS: Are there day-of-week, time-of-day, or event-driven patterns?
8. PSYCHOLOGICAL: What cognitive biases create systematic mispricings beyond favorite-longshot? (anchoring, recency, narrative, availability)
9. MARKET MICROSTRUCTURE: Bid-ask spread patterns, order flow toxicity, informed trader detection

For each edge, assess: magnitude (% improvement), reliability (how consistent), decay (how fast others copy it), implementation difficulty.

OUTPUT: Ranked list of edges with estimated impact, reliability, and implementation plan.
```

---

### PROMPT 4: Superforecaster Techniques for LLM Pipeline
**Tool: CLAUDE DEEP RESEARCH**
**Priority: P0 — Directly improves calibration**

```
TASK: Research how superforecasters (Tetlock's Good Judgment Project) make predictions, and identify which techniques can be programmatically integrated into an LLM prediction pipeline.

Context: I have an LLM-based prediction system with Brier score 0.217. I want to incorporate superforecaster methods to push this lower (closer to 0.15, which is superforecaster-level).

Research specifically:
1. BASE RATE REASONING: How do superforecasters find and apply base rates? Can we automate base rate lookup for different question categories?
2. FERMI ESTIMATION: Breaking questions into sub-components — can LLMs do this systematically?
3. UPDATE DISCIPLINE: How do superforecasters update beliefs incrementally vs. anchoring? Can we implement Bayesian updating in our pipeline?
4. INSIDE-OUTSIDE VIEW: Explicitly prompting for both reference class (outside) and specific case (inside) reasoning
5. DIALECTICAL BOOTSTRAPPING: Having the LLM argue both sides, then reconcile
6. EXTREMIZING: When ensemble members agree, push the probability further toward 0 or 1 (Ungar et al.)
7. QUESTION DECOMPOSITION: Breaking complex questions into simpler sub-questions
8. RECENCY CORRECTION: Superforecasters weight recent information more but avoid recency bias — how to balance this?
9. PREMORTEM ANALYSIS: "Imagine this resolved NO — what happened?" as a debiasing technique

For each technique: (a) evidence it works, (b) how to implement in an LLM prompt or code, (c) expected Brier improvement.

Also research: What is the theoretical floor for Brier score on prediction markets? Is 0.15 achievable with LLMs? What's the gap between best LLM systems and human superforecasters as of 2025-2026?

OUTPUT: Ranked list of techniques by expected improvement, with implementation blueprints I can hand to Claude Code.
```

---

### PROMPT 5: Advanced Monte Carlo Simulation Engine
**Tool: CLAUDE CODE**
**Priority: P0 — Investor confidence requires rigorous simulation**

```
Read COMMAND_NODE.md for context. Read backtest/monte_carlo.py for current implementation.

TASK: Build a production-grade Monte Carlo simulation that models realistic trading conditions. Current simulation is basic (10K paths, fixed parameters). We need investor-grade modeling.

BUILD THIS:

1. REALISTIC MARKET CONDITIONS:
   - Variable trade frequency (Poisson process, avg 3-10/day, seasonal variation)
   - Slippage model: 0.5-2% depending on liquidity
   - Fill rate model: not all orders fill (80-95% based on market depth)
   - Fee model: taker fees on applicable markets
   - Resolution timing: realistic distribution (1 day to 6 months)
   - Capital lockup: money tied in open positions unavailable for new trades

2. STRATEGY PARAMETER SENSITIVITY:
   - Sweep edge thresholds: 3%, 5%, 7%, 10%, 15%
   - Sweep Kelly fractions: 0.1, 0.25, 0.35, 0.5
   - Sweep category allocations
   - Sweep max positions: 5, 10, 20, 50
   - Output: heatmap of ARR vs max drawdown for each parameter combo

3. SCENARIO ANALYSIS:
   - Bull case: 70% win rate, 5 trades/day, $75 start
   - Base case: 65% win rate, 3 trades/day, $75 start  
   - Bear case: 58% win rate, 2 trades/day, $75 start
   - Catastrophe: 52% win rate (barely above random), 2 trades/day
   - For each: P&L distribution, max drawdown, time to double, P(ruin)

4. SCALING ANALYSIS (for investors):
   - At $1K, $5K, $10K, $25K, $50K, $100K starting capital
   - Does the edge degrade with size? Model liquidity constraints
   - At what capital level do we hit Polymarket's liquidity ceiling?
   - Market impact model: large orders move prices

5. CHARTS (publication quality):
   - Fan chart: median + 5th/25th/75th/95th percentile paths
   - Drawdown distribution histogram
   - Time-to-double probability curve
   - Parameter sensitivity heatmaps
   - Scaling analysis: ARR vs starting capital

6. STATISTICAL RIGOR:
   - 50,000 paths minimum (not 10K)
   - Bootstrap confidence intervals on all metrics
   - Report: "95% CI for 12-month return: [X%, Y%]"
   - Kolmogorov-Smirnov test on return distribution

OUTPUT: 
- backtest/monte_carlo_v2.py (new simulation engine)
- backtest/charts/monte_carlo/ (all charts as PNG)
- MONTE_CARLO_RESULTS.md (formatted results for investor report)

DONE WHEN: Running `python backtest/monte_carlo_v2.py` produces all scenarios, charts, and the formatted results document. Results are investor-presentable.

SOP: Update COMMAND_NODE.md Section 4, INVESTOR_REPORT.md with new simulation results.
```

---

### PROMPT 6: News Sentiment Pipeline
**Tool: CLAUDE CODE**
**Priority: P0 — News is the fastest-moving edge source**

```
Read COMMAND_NODE.md for context.

TASK: Build a news sentiment pipeline that feeds real-time information to the trading bot, improving prediction accuracy.

IMPLEMENTATION:

1. DATA SOURCES (free tier first, upgrade later):
   - NewsAPI.org (free: 100 req/day) — headline scanning
   - Google News RSS feeds — category-specific news
   - Reddit API (free) — r/politics, r/worldnews, r/economics sentiment
   - Wikipedia Recent Changes API (free) — article edit velocity as attention proxy
   - Google Trends (pytrends, free) — search interest spikes

2. PIPELINE ARCHITECTURE:
   src/data/news_sentiment.py:
   - fetch_headlines(category, hours=24) → list of headlines + snippets
   - fetch_reddit_sentiment(subreddit, query, hours=24) → sentiment score
   - fetch_wiki_attention(topic) → edit velocity score
   - fetch_google_trends(keywords) → trend score
   
   src/data/news_enricher.py:
   - enrich_market(market_question, category) → news_context dict
   - Matches market keywords to relevant news
   - Returns: headline summary, sentiment score, attention level, key facts

3. INTEGRATION WITH CLAUDE ANALYZER:
   - Modify claude_analyzer.py prompt to include news context
   - Format: "Recent relevant news: [headlines]. Sentiment: [score]. Attention level: [high/medium/low]"
   - Claude uses this as additional input for probability estimation
   - Track: does news context improve or degrade accuracy?

4. RATE LIMITING & CACHING:
   - Cache news results for 30 minutes (avoid redundant API calls)
   - Respect all API rate limits
   - Fallback: if news API fails, proceed without news context

5. BACKTEST VALIDATION:
   - Can we retroactively get news context for our 532 resolved markets?
   - Compare: Claude accuracy WITH vs WITHOUT news context
   - This is the key question: does news actually help?

OUTPUT: src/data/news_sentiment.py, src/data/news_enricher.py, modified claude_analyzer.py, validation results

DONE WHEN: Bot enriches each market analysis with relevant news context. Backtest comparison shows whether news helps.

SOP: Update COMMAND_NODE.md Section 2 and Section 5 with news pipeline details.
```

---

## ═══════════════════════════════════════
## WAVE 2 PROMPTS — PASTE WHEN WAVE 1 IS RUNNING  
## ═══════════════════════════════════════

---

### PROMPT 7: Market Making Strategy Research
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P1 — Market making may be more profitable than taking**

```
TASK: Research market making strategies on Polymarket specifically.

Context: I currently run a "taker" strategy (buying underpriced outcomes). Research from Feb 2026 shows taker fees eat 1-3% of edge. Market makers (limit orders) pay ZERO fees on Polymarket. This could be a superior strategy.

Research:
1. How does market making work on Polymarket's CLOB (Central Limit Order Book)?
2. What spread should a market maker quote? How does optimal spread depend on volatility, time to resolution, and information flow?
3. How do existing market makers on Polymarket operate? (OpenClaw, institutional desks)
4. What's the inventory risk? How do you hedge a market making position?
5. Can we combine market making with our LLM forecasting? (Quote tighter on the side we believe in)
6. What's the realistic return profile of a market making strategy vs pure forecasting?
7. What capital is needed to market make effectively?
8. How does Polymarket's orderbook depth and bid-ask spread compare across market categories?
9. What are the risks? (adverse selection, inventory blowup, API downtime)
10. Are there any open-source market making bots for prediction markets?

Provide specific numbers where possible: typical spreads, fill rates, daily P&L ranges, capital requirements.

OUTPUT: Comprehensive strategy document with implementation roadmap.
```

---

### PROMPT 8: Cross-Platform Arbitrage Research
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P1 — Risk-free profit if it exists**

```
TASK: Research cross-platform prediction market arbitrage opportunities.

Context: Polymarket, Kalshi, Metaculus, PredictIt (closing), and sports books all offer overlapping event markets. If the same event is priced differently across platforms, we can lock in risk-free profit.

Research:
1. Which platforms have the most overlapping markets with Polymarket?
2. What are typical price discrepancies between Polymarket and Kalshi on the same events?
3. How fast do arbitrage windows close? (seconds, minutes, hours?)
4. What are the execution challenges? (different settlement, different rules, withdrawal times)
5. Can we automate cross-platform arbitrage? What APIs exist for Kalshi, Metaculus?
6. What capital is needed per platform to execute arb trades?
7. Are there regulatory issues with trading on multiple platforms simultaneously?
8. What's the realistic annual return from pure cross-platform arbitrage?
9. Has anyone published academic research on prediction market arbitrage efficiency?
10. Within Polymarket itself: are there intra-platform arbitrage opportunities? (correlated markets, NegRisk markets where probabilities don't sum to 100%)

OUTPUT: Arbitrage opportunity assessment with specific platform pairs, typical spreads, and implementation plan.
```

---

### PROMPT 9: Social Sentiment Integration Research
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P1 — Social signals precede market moves**

```
TASK: Research how social media sentiment can be used to predict prediction market outcomes.

Context: Our bot uses LLM probability estimation on Polymarket. We want to add social sentiment as an additional signal. Academic research suggests social media activity precedes prediction market price moves.

Research:
1. Which social platforms have the strongest signal for prediction markets? (X/Twitter, Reddit, Telegram, Discord, YouTube comments)
2. What NLP/sentiment tools work best for political and event prediction? (FinBERT, VADER, Claude sentiment analysis)
3. How much lead time does social sentiment have over prediction market prices? (minutes, hours, days?)
4. Are there specific patterns? (e.g., Twitter volume spikes 24h before Polymarket moves)
5. How do you filter noise from signal in social media? (bots, spam, astroturfing)
6. What free APIs exist for social sentiment data?
7. Has anyone published research on social media → prediction market alpha specifically?
8. Can we use Google Trends search volume as a proxy for attention/sentiment?
9. What about Polymarket-specific signals? (large wallet tracking, whale alerts, order flow)
10. How do we backtest a social sentiment signal against historical prediction market data?

OUTPUT: Implementation plan with specific APIs, NLP tools, and integration architecture.
```

---

### PROMPT 10: Investor Report v2 — Comprehensive & Layperson-Friendly
**Tool: COWORK**
**Priority: P1 — This is what investors see**

```
Read COMMAND_NODE.md for full project context. Read INVESTOR_REPORT.md for the current version.

TASK: Create a completely revised investor report that is:
1. Understandable by someone with NO trading or AI background
2. Visually compelling (charts, tables, clear formatting)
3. Honest about risks (this builds trust, not destroys it)
4. Shows a clear path from $75 → $10K → $100K

STRUCTURE:
1. EXECUTIVE SUMMARY (1 page)
   - What we do in 3 sentences
   - Key performance numbers
   - What we're raising and why

2. THE OPPORTUNITY (1 page)
   - What are prediction markets? (explain like I'm 12)
   - Why are they inefficient? (use analogies)
   - How big is this market? ($1B+ traded on Polymarket in 2025)

3. OUR EDGE (2 pages)
   - How AI beats humans at probability estimation
   - Our specific advantages: calibration, category routing, ensemble
   - Comparison to other approaches (pure arb, manual trading)
   - Be honest: "This is what our backtest shows. Backtests are not live results."

4. PERFORMANCE DATA (2 pages)
   - Backtest results (clearly labeled as backtest)
   - Monte Carlo simulation results with confidence intervals
   - Live paper trading results (when available)
   - Historical comparison: what would $1,000 invested 6 months ago be worth?

5. RISK FACTORS (1 page)
   - Every risk, stated plainly
   - What we're doing to mitigate each one
   - "You should only invest money you can afford to lose"

6. FUND TERMS (1 page)
   - How profits are split
   - When you can withdraw
   - Legal structure

7. TEAM (half page)
   - Your background
   - AI capabilities being leveraged

8. APPENDIX
   - Technical details for sophisticated investors
   - Glossary of terms

FORMAT: Professional .docx with:
- Clean typography (no walls of text)
- Charts embedded where possible
- Color scheme: dark blue (#1B365D) and gold (#C5A572)
- Headers clearly demarcated
- Page numbers and table of contents

OUTPUT: AI_Prediction_Market_Fund_Investor_Report_v2.docx

DONE WHEN: A non-technical person can read this in 15 minutes and understand what we do, how we make money, and what the risks are.

SOP: Cross-reference all numbers against COMMAND_NODE.md Section 4 and Section 11. Flag any discrepancies.
```

---

### PROMPT 11: Monthly Performance Dashboard Template
**Tool: COWORK**
**Priority: P1 — Ongoing investor communication**

```
Read COMMAND_NODE.md for full project context.

TASK: Create a monthly performance report template that we send to investors every month. This should be polished, professional, and build confidence over time.

TEMPLATE SECTIONS:
1. PERFORMANCE SNAPSHOT
   - Month return (%)
   - YTD return (%)
   - Total fund value
   - Comparison to S&P 500, Bitcoin, and "random coin flip" baseline

2. TRADING ACTIVITY
   - Total trades executed
   - Win rate this month
   - Average edge captured
   - Best and worst trades (anonymized market descriptions)
   - Category breakdown (pie chart)

3. RISK METRICS
   - Maximum drawdown this month
   - Sharpe ratio (rolling 30 day)
   - Current exposure level
   - Number of open positions

4. SYSTEM IMPROVEMENTS
   - What we improved this month (calibration, new data sources, etc.)
   - Impact on expected performance
   - Upcoming improvements planned

5. MARKET COMMENTARY
   - Notable prediction market trends
   - New market categories or opportunities
   - Regulatory updates

6. FUND OPERATIONS
   - Current AUM
   - New subscriptions/redemptions
   - Infrastructure status

OUTPUT: Quarterly_Report_Template_v2.docx — designed to be filled in monthly with actual data. Include placeholder text that shows exactly what goes where.

DONE WHEN: Template is ready to fill in with real data as soon as live trading begins.
```

---

### PROMPT 12: Legal Structure Finalization
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P1 — Must be compliant before taking investor money**

```
TASK: Research the exact legal requirements for launching a small prediction market fund under Reg D 506(b).

Context: I'm starting a fund that trades Polymarket. Initial capital from friends and family ($10K-$100K). I'm based in the US. The fund will be an LLC taxed as a partnership.

Research:
1. EXACT FILING REQUIREMENTS:
   - SEC Form D: when to file, what it costs, how to file electronically
   - State blue sky filing requirements (which states require notice filing?)
   - NFA/CFTC: Is CFTC Rule 4.13 exemption still available? What's the filing process?

2. INVESTOR AGREEMENTS:
   - What must a Reg D 506(b) subscription agreement contain?
   - What risk disclosures are legally required?
   - Do I need an accredited investor verification process?
   - Can I accept non-accredited friends/family? What additional requirements?

3. OPERATING AGREEMENT:
   - Standard terms for investment LLC operating agreement
   - Management fee + carry structure (0% mgmt, 30% carry, high water mark)
   - Withdrawal provisions (90-day lock, 30-day notice, quarterly windows)
   - What happens if the manager wants to close the fund?

4. TAX OBLIGATIONS:
   - Prediction market gains classification: gambling income vs capital gains vs Section 1256?
   - Any IRS guidance on binary event contracts?
   - K-1 reporting requirements
   - Quarterly estimated tax obligations

5. ONGOING COMPLIANCE:
   - Annual SEC filing requirements
   - Anti-money laundering (AML) requirements
   - Know Your Customer (KYC) for investors
   - Record keeping requirements

6. COST ESTIMATE:
   - Can I do this without a lawyer? What's the minimum legal cost?
   - DIY filing costs vs lawyer-assisted
   - Annual compliance costs

OUTPUT: Complete legal checklist with specific forms, filing deadlines, costs, and step-by-step process. Include links to actual filing portals.
```

---

## ═══════════════════════════════════════
## WAVE 3 — BACKGROUND & ONGOING IMPROVEMENT
## ═══════════════════════════════════════

---

### PROMPT 13: Calibration Deep Dive — Push Brier Below 0.20
**Tool: CLAUDE CODE**
**Priority: P2**

```
Read COMMAND_NODE.md. Read backtest/calibration.py.

TASK: Explore advanced calibration techniques to push Brier score from 0.217 toward 0.15-0.18.

IMPLEMENT AND TEST:
1. Isotonic regression (compare to Platt scaling)
2. Beta calibration (Kull et al. 2017)
3. Temperature scaling with learnable temperature per category
4. Histogram binning calibration
5. Venn-Abers calibration (distribution-free, guaranteed validity)
6. Ensemble calibration: calibrate each model separately, then ensemble

For each: train on 70% of 532 markets, test on 30%. Report test-set Brier.

OUTPUT: calibration_comparison.md with results, recommendation for production calibration method.
```

---

### PROMPT 14: Resolution Time Optimizer
**Tool: CLAUDE CODE**
**Priority: P2**

```
Read COMMAND_NODE.md. Read src/resolution_estimator.py.

TASK: Build a resolution time prediction model that maximizes capital velocity.

Capital velocity = edge / days_to_resolution. A 5% edge on a market resolving tomorrow is worth 10x more than a 5% edge on a market resolving in 3 months.

IMPLEMENT:
1. Feature engineering: keywords in market question, category, current volume trend, historical similar markets
2. Resolution time buckets: <1 day, 1-3 days, 3-7 days, 1-4 weeks, 1-3 months, >3 months
3. Simple classifier (logistic regression or random forest)
4. Integration: sort all candidates by velocity, take top-N per cycle
5. Backtest: compare velocity-sorted vs random selection

OUTPUT: Updated resolution_estimator.py, backtest comparison results.
```

---

### PROMPT 15: Pre-Resolution Exit Strategy
**Tool: CLAUDE CODE**
**Priority: P2**

```
TASK: Build a system that exits positions BEFORE resolution when the edge has been captured.

Example: We buy YES at $0.40 (estimating 60% true probability). The market moves to $0.58. We've captured most of the edge — we should sell and redeploy capital rather than wait for resolution.

IMPLEMENT:
1. Monitor open positions every cycle
2. Calculate: current_price - entry_price vs estimated_edge
3. Exit rules:
   - If captured >70% of estimated edge → sell
   - If position held >14 days and captured >50% of edge → sell
   - If new information suggests edge has eroded → sell
4. Reinvestment: freed capital immediately available for new trades
5. Track: exit P&L vs hold-to-resolution P&L (which is better?)

OUTPUT: src/exit_strategy.py, integrated into engine/loop.py
```

---

### PROMPT 16: Polymarket Orderbook Analysis
**Tool: CLAUDE CODE**
**Priority: P2**

```
TASK: Build an orderbook analyzer that extracts trading signals from Polymarket's CLOB data.

IMPLEMENT:
1. WebSocket connection to Polymarket orderbook
2. Track: bid-ask spread, depth, imbalance, large order detection
3. Signals:
   - Spread compression → imminent resolution or information event
   - Order imbalance → informed trading direction
   - Large orders → whale activity
   - Depth reduction → liquidity withdrawal (danger signal)
4. Feed signals to trading decisions (additional input alongside Claude estimate)

OUTPUT: src/data/orderbook_analyzer.py with signal generation
```

---

### PROMPT 17: Whale Wallet Tracking
**Tool: CLAUDE CODE**
**Priority: P2**

```
TASK: Build a system to track large Polymarket wallets and their trading patterns.

IMPLEMENT:
1. Identify top wallets by historical volume (Polygonscan/Dune Analytics)
2. Monitor their positions via Polymarket API or on-chain data
3. Signal: when a known-profitable wallet takes a large position
4. Copytrade signal: if top-5 wallets agree on direction, add to our confidence
5. Anti-signal: if we're opposite to whale consensus, reduce position size

OUTPUT: src/data/whale_tracker.py
```

---

### PROMPT 18: Automated Self-Improving Architecture
**Tool: CLAUDE CODE**
**Priority: P2**

```
Read COMMAND_NODE.md.

TASK: Build a system where the bot automatically improves itself based on trading results.

IMPLEMENT:
1. PERFORMANCE TRACKING:
   - Track every prediction: estimated prob, market price, actual outcome
   - Compute rolling Brier score (7-day, 30-day, all-time)
   - Track per-category accuracy

2. AUTOMATIC CALIBRATION UPDATES:
   - Every 50 resolved trades: re-fit Platt scaling parameters
   - If Brier score degrades by >0.02 from baseline: alert + auto-adjust

3. CATEGORY ROUTING UPDATES:
   - If a category's win rate drops below 55%: auto-downgrade priority
   - If a category's win rate exceeds 70%: auto-upgrade priority

4. THRESHOLD ADJUSTMENT:
   - If too few signals (<2/day): lower edge threshold
   - If too many signals (>10/day): raise edge threshold
   - Target: 3-7 signals per day

5. PROMPT EVOLUTION:
   - Store prompt versions with their Brier scores
   - A/B test prompt variations (10% of trades use experimental prompt)
   - Promote winning prompts automatically

OUTPUT: src/self_improve.py, integrated into engine/loop.py
```

---

### PROMPT 19: Competitor Intelligence Dashboard
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P2**

```
TASK: Build a comprehensive competitive intelligence report on all known Polymarket trading bots and strategies.

Research:
1. What public bots exist? (GitHub repos, Twitter accounts, Telegram groups)
2. What strategies do they use? (arbitrage, sentiment, LLM-based, copy trading)
3. What are their claimed returns?
4. Which wallets on Polymarket are known to be bots?
5. How is the competitive landscape evolving? (more bots = more efficient markets)
6. What institutional players are entering? (Susquehanna, Jump, etc.)
7. What's the total bot trading volume on Polymarket?
8. How do our claimed performance metrics compare to public benchmarks?

OUTPUT: Competitive landscape document with specific competitors, their approaches, and our differentiation.
```

---

### PROMPT 20: Political Market Deep Dive
**Tool: CLAUDE DEEP RESEARCH**
**Priority: P2 — Politics is our best category**

```
TASK: Research how to maximize prediction accuracy on political markets specifically.

Context: Political markets are our highest-performing category (backtest). But we need to understand the specific dynamics to maintain this edge.

Research:
1. What polling sources are most predictive of political outcomes?
2. How do prediction markets and polls compare in accuracy historically?
3. What are the systematic biases in political prediction markets? (party affiliation of traders, media narrative effects)
4. How do political markets behave around key events? (debates, primaries, scandals, endorsements)
5. What's the optimal time to trade political markets? (how far before elections/events?)
6. Are there specific political question types where LLMs excel or fail?
7. How did Polymarket political markets perform in 2024 vs polls?
8. What data sources should we integrate? (FiveThirtyEight, RCP, primary results, approval ratings)
9. Are there patterns in how political markets resolve? (e.g., do "Will X resign?" markets have predictable dynamics?)

OUTPUT: Political market playbook with specific data sources, trading rules, and timing strategy.
```

---

### PROMPT 21: Position Deduplication & Correlation Management
**Tool: CLAUDE CODE**
**Priority: P2**

```
Read COMMAND_NODE.md.

TASK: Build a correlation detection system that prevents overexposure to related markets.

PROBLEM: If we have positions in "Will Biden drop out?", "Will Harris be nominee?", and "Will Democrats win?" — these are all correlated. A single event could cause all three to move against us simultaneously.

IMPLEMENT:
1. KEYWORD CLUSTERING:
   - Extract key entities from each market question
   - Cluster markets by shared entities (people, events, countries)
   
2. CORRELATION RULES:
   - Max 2 positions in same entity cluster
   - If adding 3rd position in cluster: require 2x edge threshold
   - Track implied correlation from historical co-movement

3. PORTFOLIO EXPOSURE:
   - Max 30% of portfolio in any single category
   - Max 15% of portfolio in any single entity cluster
   - Alert if exposure rules violated

OUTPUT: src/risk/correlation.py, integrated into safety.py
```

---

### PROMPT 22: Fee Optimization Research
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P2**

```
TASK: Research every way to minimize fees on Polymarket.

Context: Taker fees = p*(1-p)*0.0625, which peaks at 1.56% at p=0.50. This significantly eats into our edge. Maker orders (limit orders) are free.

Research:
1. Can we convert our taker strategy to maker? (post limit orders instead of market orders)
2. What's the fill rate for limit orders at various distances from mid?
3. Does Polymarket have any maker rebate programs?
4. Can we qualify for the Builder Program for gasless trading?
5. Are there volume-based fee discounts?
6. What about post-only order types? (guaranteed maker)
7. Can we save on gas fees by batching orders?
8. What are the withdrawal costs? (Polygon → fiat)
9. Total cost of doing business: fees + gas + slippage + API costs

OUTPUT: Fee optimization plan with estimated savings per month.
```

---

### PROMPT 23: Subscription Agreement Draft
**Tool: COWORK**
**Priority: P2**

```
Read COMMAND_NODE.md Section 6 for fund structure details.

TASK: Draft a subscription agreement for the Predictive Alpha Fund.

This is for a Reg D 506(b) offering, friends and family round. LLC taxed as partnership.

INCLUDE:
1. Subscriber information (name, address, investment amount)
2. Accredited investor representation (or non-accredited disclosure)
3. Investment terms:
   - Minimum investment: $1,000
   - No management fee
   - 30% performance fee above high-water mark
   - 90-day initial lock-up
   - 30-day written notice for withdrawals
   - Quarterly withdrawal windows
4. Risk acknowledgments (comprehensive — everything from COMMAND_NODE.md Section 7)
5. Representations and warranties
6. Confidentiality provisions
7. Dispute resolution
8. Signature blocks

OUTPUT: Investor_Subscription_Agreement_v2.docx

DISCLAIMER: Include note that this is a template and should be reviewed by an attorney before use.
```

---

### PROMPT 24: One-Pager for Quick Pitches
**Tool: COWORK**
**Priority: P2**

```
Read COMMAND_NODE.md for context.

TASK: Create a single-page fund overview that can be shared casually — texted to a friend, slipped across a dinner table, or attached to an email.

ONE PAGE, FRONT ONLY:
- Fund name and tagline
- "What we do" in 2 sentences
- Key performance metric (with "backtest" disclaimer)
- How the AI works (3-step visual: Scan → Analyze → Trade)
- Risk/return profile
- Investment terms (minimum, fees, liquidity)
- Contact information

DESIGN: Clean, minimal, professional. Not a wall of text. Think Y Combinator demo day slides meets hedge fund fact sheet.

OUTPUT: Fund_One_Pager_v2.docx (or .pdf)
```

---

### PROMPT 25: Private Placement Memorandum
**Tool: COWORK**
**Priority: P2**

```
Read COMMAND_NODE.md Section 6 for legal details.

TASK: Draft a Private Placement Memorandum (PPM) for the Predictive Alpha Fund.

This is the formal legal offering document for Reg D 506(b). It must include:

1. Cover page with "CONFIDENTIAL" marking
2. Summary of terms
3. Description of the fund and strategy
4. Risk factors (comprehensive — at least 20 risks)
5. Use of proceeds
6. Management and compensation
7. Conflicts of interest
8. Tax considerations
9. ERISA considerations
10. Regulatory considerations (CFTC, SEC)
11. Subscription procedures
12. Definitions

TONE: Formal legal language but still readable. This protects you legally.

OUTPUT: Private_Placement_Memorandum_v2.docx

DISCLAIMER: Include note that this should be reviewed by a securities attorney.
```

---

### PROMPT 26: Fee Structure Analysis for Investors
**Tool: COWORK**
**Priority: P2**

```
TASK: Create a clear document explaining the fund's fee structure and how it compares to alternatives.

INCLUDE:
1. Our fees: 0% management, 30% carry above HWM
2. Comparison to:
   - Typical hedge fund: 2% management + 20% carry
   - Typical crypto fund: 2% + 25%
   - Index funds: 0.03-0.50% expense ratio
   - Doing it yourself on Polymarket

3. Worked examples:
   - "If you invest $10K and the fund returns 100% in year 1..."
   - Show the math clearly for each fee scenario
   - Show high-water mark protection: "If year 2 is -10%, you pay $0 in fees"

4. Why our structure: aligned incentives — we only make money when you make money

OUTPUT: Fee_Structure_Analysis_v2.docx
```

---

### PROMPT 27: Weather Arbitrage Strategy Enhancement
**Tool: CLAUDE CODE**
**Priority: P3**

```
Read COMMAND_NODE.md Section 3 (Strategy B).

TASK: Enhance the NOAA weather arbitrage system.

Currently: basic 48-hour forecast comparison. No active weather markets detected recently.

IMPROVE:
1. Expand city coverage: top 20 US cities
2. Add weather models: ECMWF (European model), GFS, NAM
3. Consensus scoring: when models agree = high confidence
4. Expand beyond temperature: precipitation, severe weather, snowfall
5. Monitor for new weather markets on Polymarket (they appear seasonally)
6. Add Kalshi weather markets as additional venue
7. Historical backtest: get historical NOAA forecasts vs weather market outcomes

OUTPUT: Enhanced src/noaa_client.py, new src/weather_strategy.py
```

---

### PROMPT 28: Google Trends Integration
**Tool: CLAUDE CODE**
**Priority: P3**

```
TASK: Build a Google Trends integration that detects attention spikes relevant to prediction markets.

IMPLEMENT:
1. For each active market: extract key search terms
2. Query Google Trends (pytrends) for relative interest
3. Detect spikes: >2x normal interest = "attention event"
4. Signal: attention spikes often precede price moves
5. Integration: feed attention score to Claude analyzer
6. Backtest: correlate historical Google Trends spikes with market outcomes

OUTPUT: src/data/google_trends.py
```

---

### PROMPT 29: Dashboard UI for Investors
**Tool: CLAUDE CODE**
**Priority: P3**

```
Read COMMAND_NODE.md Section 2 (dashboard already exists as FastAPI).

TASK: Build a web dashboard that investors can view to track fund performance in real-time.

CURRENT: FastAPI REST API at /health, /status, /metrics, /risk, etc.

BUILD:
1. Frontend: React/Next.js or simple HTML + Chart.js
2. Pages:
   - Overview: current AUM, total return, active positions count
   - Performance: equity curve chart, monthly returns table
   - Risk: drawdown chart, exposure breakdown
   - Activity: recent trades log (anonymized market names)
3. Authentication: simple password protection
4. Auto-refresh: update every 5 minutes
5. Mobile-friendly responsive design
6. Deploy alongside bot on VPS

OUTPUT: src/app/dashboard_ui/ with all frontend code
```

---

### PROMPT 30: Polymarket API Rate Limit Optimization
**Tool: CLAUDE CODE**
**Priority: P3**

```
TASK: Optimize our Polymarket API usage for maximum efficiency.

CURRENT: Scanning 100 markets every 5 minutes = 288 API calls/day just for scanning.

OPTIMIZE:
1. WebSocket subscriptions instead of polling (real-time, fewer API calls)
2. Cache market data: only re-fetch changed markets
3. Batch API requests where possible
4. Priority queue: scan high-opportunity categories more often
5. Rate limit tracking: stay under 15,000 req/10s limit
6. Failover: if rate limited, gracefully degrade to cached data

OUTPUT: Updated src/scanner.py with optimized API usage
```

---

### PROMPT 31: Backtest Data Expansion
**Tool: CLAUDE CODE**
**Priority: P3**

```
TASK: Expand our backtest dataset from 532 to 2,000+ resolved markets.

CURRENT: 532 markets collected. More resolved markets exist on Polymarket.

IMPLEMENT:
1. Paginate through Gamma API for ALL resolved markets (not just recent)
2. Filter: minimum $100 volume, clear resolution
3. Store in structured format with: question, category, resolution date, outcome, prices over time
4. Re-run full backtest with expanded dataset
5. Check: does our edge hold on the larger dataset? Or was 532 markets lucky?

OUTPUT: Expanded dataset in backtest/data/, re-run results
```

---

### PROMPT 32: Limit Order Strategy
**Tool: CLAUDE CODE**
**Priority: P2**

```
TASK: Convert our taker strategy to a maker/limit order strategy.

CURRENT: We execute market orders (taker) → pay fees up to 1.56%.
TARGET: Execute limit orders (maker) → pay ZERO fees.

IMPLEMENT:
1. Instead of market buying at current price, post limit order at our target price
2. Order management:
   - Place order → monitor fill status → cancel/replace after timeout
   - Partial fills: accept partial, monitor remainder
   - Price improvement: if market moves toward us, we get better fill
3. Fill rate tracking: what % of our limit orders actually fill?
4. Timeout rules: cancel unfilled orders after 1 hour (configurable)
5. Fallback: if market is moving fast and we're missing fills, switch to market order (accept fee)

BENEFIT: Even if only 70% of orders fill as maker, the fee savings compound enormously.

OUTPUT: Updated src/paper_trader.py and engine/loop.py with limit order mode
```

---

### PROMPT 33: Live Trading Scorecard
**Tool: COWORK**
**Priority: P1 (needed when we go live March 10)**

```
Read COMMAND_NODE.md for context.

TASK: Create a live trading scorecard that we update daily once live trading begins March 10.

This is the PRIMARY EVIDENCE we show investors. It must be:
1. Simple: anyone can read it in 30 seconds
2. Honest: show losses as clearly as wins
3. Cumulative: running total from day 1

COLUMNS:
- Date
- Trades Executed
- Wins / Losses
- Day P&L ($)
- Cumulative P&L ($)
- Fund Value ($)
- Cumulative Return (%)
- Win Rate (rolling 7-day)
- Notes (any significant events)

FORMAT: Excel spreadsheet that auto-calculates cumulative columns. Pre-formatted for 90 days.

OUTPUT: Live_Trading_Scorecard.xlsx

DONE WHEN: Ready to fill in starting March 10.
```

---

### PROMPT 34: Investor FAQ Document
**Tool: COWORK**
**Priority: P2**

```
TASK: Create a comprehensive FAQ document for potential investors.

Questions to answer:
1. What is a prediction market?
2. How does AI trading work?
3. What is your track record? (honest: backtest only, going live March 10)
4. How much can I invest?
5. When can I withdraw my money?
6. How do you make money? How do I make money?
7. What are the fees?
8. What are the risks?
9. Is this legal?
10. What happens if the AI is wrong?
11. What is Polymarket? Is it safe?
12. How is this different from crypto trading?
13. What's your competitive advantage?
14. Can I lose all my money?
15. How do I track my investment?
16. What reports will I receive?
17. What if I want to invest more later?
18. How are taxes handled?
19. Who else is investing?
20. What's your background?

TONE: Conversational, honest, no jargon. Like explaining to a smart friend over coffee.

OUTPUT: Investor_FAQ.docx
```

---

### PROMPT 35: Monte Carlo Stress Testing
**Tool: COWORK**
**Priority: P1**

```
Read COMMAND_NODE.md Section 4 for current Monte Carlo results.

TASK: Create a Monte Carlo stress test analysis document that shows what happens under extreme scenarios.

SCENARIOS TO MODEL:
1. "The AI breaks" — win rate drops to 52% for 3 months
2. "Market efficiency" — edge halves over 6 months as more bots enter
3. "Black swan" — 5 correlated positions all lose simultaneously
4. "Liquidity crisis" — Polymarket volume drops 80%
5. "Regulatory shutdown" — Polymarket closes in 3 months, all positions frozen
6. "Fat finger" — single catastrophic trade loses 50% of bankroll
7. "API outage" — bot offline for 48 hours during critical resolution period
8. "Fee increase" — Polymarket doubles taker fees

For each: model the portfolio impact, recovery time, and mitigation strategy.

FORMAT: Professional document with charts showing each scenario's equity curve.

OUTPUT: Stress_Test_Analysis.docx (investor-facing quality)
```

---

### PROMPT 36: Google Drive Folder Structure
**Tool: COWORK**
**Priority: P1 — Investors need a clean folder to review**

```
TASK: Propose and create the complete Google Drive folder structure for the investor portal.

STRUCTURE:
📁 Predictive Alpha Fund
├── 📁 1. Overview
│   ├── Fund_One_Pager.pdf
│   ├── Investor_Report.pdf
│   └── Investor_FAQ.pdf
├── 📁 2. Performance
│   ├── Live_Trading_Scorecard.xlsx (updated daily)
│   ├── Monthly_Report_[Month].pdf
│   ├── Backtest_Results.pdf
│   └── Monte_Carlo_Analysis.pdf
├── 📁 3. Legal
│   ├── Private_Placement_Memorandum.pdf
│   ├── Subscription_Agreement.pdf
│   └── Fee_Structure.pdf
├── 📁 4. Research
│   ├── Strategy_Report.pdf
│   ├── Competitive_Landscape.pdf
│   └── Stress_Test_Analysis.pdf
└── 📁 5. Updates
    └── [Monthly updates posted here]

Create an INDEX.md that describes what each document is and who should read it first.

OUTPUT: INDEX.md for the Google Drive root, ready to share.
```

---

### PROMPT 37: Automated Report Generation
**Tool: CLAUDE CODE**
**Priority: P3**

```
TASK: Build a system that auto-generates monthly performance reports from bot trading data.

IMPLEMENT:
1. Pull data from bot.db (SQLite): trades, P&L, positions, risk events
2. Calculate: monthly return, win rate, Sharpe, drawdown, category breakdown
3. Generate charts: equity curve, monthly returns bar chart, category pie chart
4. Fill in the monthly report template (from Prompt 11)
5. Export as PDF
6. Send via Telegram notification: "Monthly report ready"
7. Optionally: auto-upload to Google Drive

OUTPUT: src/reporting/monthly_report.py
```

---

### PROMPT 38: Ensemble Prompt A/B Testing Framework
**Tool: CLAUDE CODE**
**Priority: P3**

```
TASK: Build a system to continuously A/B test different Claude prompts.

IMPLEMENT:
1. Prompt registry: store multiple prompt variants with version numbers
2. Traffic splitting: 80% production prompt, 20% experimental
3. Track per-prompt: Brier score, win rate, avg edge captured
4. Statistical significance: only promote a new prompt if p < 0.05 improvement
5. Automatic promotion: if experimental prompt beats production for 50+ trades at p<0.05, swap
6. Logging: full audit trail of which prompt produced which prediction

OUTPUT: src/prompt_ab_test.py
```

---

### PROMPT 39: Capital Deployment Optimizer
**Tool: CLAUDE CODE**
**Priority: P2**

```
TASK: Build a smart capital deployment system that optimizes how bankroll is allocated.

CURRENT: Simple quarter-Kelly sizing per trade, no portfolio-level optimization.

IMPLEMENT:
1. PORTFOLIO OPTIMIZATION:
   - Given N candidate trades, find optimal allocation across all of them
   - Constraint: total allocation ≤ 80% of bankroll (keep 20% reserve)
   - Objective: maximize expected log-return (Kelly criterion, multi-asset)

2. OPPORTUNITY COST:
   - If capital is locked in low-edge positions, release capital for high-edge new ones
   - "Should I exit this 3% edge position to enter a 10% edge position?"

3. REBALANCING:
   - Daily check: are current allocations still optimal given updated estimates?
   - If a position's edge has changed (price moved), resize

OUTPUT: src/portfolio_optimizer.py
```

---

### PROMPT 40: Academic Paper Tracker
**Tool: CHATGPT DEEP RESEARCH**
**Priority: P3**

```
TASK: Find and summarize all academic papers published in 2024-2026 on the topic of LLMs and prediction markets / forecasting.

Research:
1. Papers on LLM probability calibration
2. Papers on ensemble forecasting methods
3. Papers on prediction market efficiency and mispricing
4. Papers on automated trading in prediction markets
5. Papers comparing LLM forecasts to human forecasters
6. Papers on the Kelly criterion in binary markets
7. Any new calibration techniques for neural networks

For each paper: title, authors, date, key finding, relevance to our system, Brier score reported (if any).

OUTPUT: Academic literature review organized by topic, with implementation recommendations.
```

---

### PROMPT 41: Telegram Bot Enhancement
**Tool: CLAUDE CODE**
**Priority: P3**

```
TASK: Enhance the Telegram bot to be a full portfolio management interface.

CURRENT: Basic notifications of trades and errors.

ADD:
1. /status — current portfolio value, open positions, today's P&L
2. /trades — last 10 trades with outcomes
3. /performance — 7-day and 30-day metrics
4. /risk — current risk metrics, exposure level
5. /kill — emergency kill switch (require confirmation)
6. /pause — pause trading for N hours
7. /resume — resume trading
8. /set threshold=X — change edge threshold
9. /report — generate and send quick performance summary

OUTPUT: Enhanced src/telegram.py with command handler
```

---

### PROMPT 42: Continuous Improvement SOP
**Tool: COWORK**
**Priority: P2**

```
TASK: Create a Standard Operating Procedure document for how we continuously improve the system.

SECTIONS:
1. DAILY CHECKLIST
   - Check bot is running (Telegram heartbeat)
   - Review yesterday's trades
   - Check rolling win rate
   - Note any anomalies

2. WEEKLY REVIEW
   - Compare actual vs expected performance
   - Identify worst-performing categories
   - Check calibration drift
   - Review open positions for stuck capital
   - Update investor scorecard

3. MONTHLY DEEP DIVE
   - Re-run calibration fit on all resolved trades
   - Performance attribution: what drove returns?
   - Cost analysis: API, VPS, fees
   - Generate monthly investor report
   - Review and update all project documents

4. QUARTERLY STRATEGIC REVIEW
   - Competitive landscape update
   - Strategy review: are edges eroding?
   - Capital allocation review
   - Investor communication

5. RESEARCH PIPELINE
   - How to prioritize new research
   - How to dispatch to AI tools
   - How to integrate research findings
   - How to update COMMAND_NODE.md

OUTPUT: Continuous_Improvement_SOP.docx
```

---

## EXECUTION NOTES

### Parallel Capacity
You have these tools available simultaneously:
- **Claude Code:** 1 task at a time (implementation)
- **Claude Deep Research:** 1-2 tasks at a time
- **ChatGPT Deep Research:** 1-2 tasks at a time
- **Cowork:** 1-2 tasks at a time

**Maximum parallel tasks: 5-6**

### Dispatch Strategy
1. Start Claude Code on Prompt 1 (Combined Backtest)
2. Start Claude Deep Research on Prompt 3 (Edge Discovery)
3. Start ChatGPT Deep Research on Prompt 7 (Market Making)
4. Start Cowork on Prompt 10 (Investor Report v2)
5. While those run: start Prompt 4 (Superforecaster) on Claude Deep Research
6. As tasks complete: dispatch next in priority order

### After Each Completion
1. Review output for quality
2. Paste into relevant project files
3. If it changes any numbers: update COMMAND_NODE.md
4. If it changes strategy: update STRATEGY_REPORT.md
5. If it changes investor data: update INVESTOR_REPORT.md
6. Queue the next prompt from the dispatch library

### Investor Folder Timeline
- **March 5-9:** Complete Waves 1-2, have investor materials draft-ready
- **March 10:** Go live. Start filling in Live Trading Scorecard
- **March 10-31:** First 3 weeks of live data. Update scorecard daily.
- **April 1:** First monthly report. Update all investor materials with live data.
- **April 1+:** Share Google Drive folder with first potential investors

---

*This dispatch library is a living document. Add new prompts as research reveals new opportunities. Bump completed prompts to "DONE" status.*
