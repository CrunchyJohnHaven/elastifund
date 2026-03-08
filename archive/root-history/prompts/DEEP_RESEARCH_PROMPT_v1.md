# Deep Research Prompt: Systematic Strategy Taxonomy for Agentic Prediction Market Trading

**Dispatch to:** Claude Deep Research
**Priority:** P0
**Estimated time:** 60-90 minutes
**Output:** Comprehensive strategy taxonomy with testability scores

---

## Context

I'm building an open-source agentic trading system that autonomously trades binary prediction markets on Polymarket and Kalshi. The system is live with $247.51 USDC on Polymarket and $100 on Kalshi. An AI agent (Claude) makes all trading decisions — I only design the system architecture and constraints.

**The core problem we've discovered:** On Polymarket, the categories where LLMs have genuine forecasting edge (politics, weather, geopolitics) resolve slowly (12 hours to months). The categories that resolve fast (5-min crypto candles, live sports) are ones where LLMs have no forecasting advantage. We need non-LLM signal sources for fast markets, and better LLM strategies for medium-term markets.

**What we've already built and tested:**
- LLM probability estimation with Platt scaling calibration (Brier 0.217, 68.5% win rate on 532-market backtest)
- Anti-anchoring (Claude doesn't see market price), asymmetric thresholds (YES 15%, NO 5%), category routing
- Quarter-Kelly position sizing, velocity scoring (annualized edge / lockup time)
- Maker-order execution for zero fees on fee-bearing markets
- Smart wallet flow detector (in progress): monitoring top-performing wallets via data-api.polymarket.com/trades
- NOAA weather arbitrage scanner (no active weather markets found)
- Sentiment/contrarian "fade the dumb money" research (not yet implemented)
- Binary option pricing engine (Black-Scholes adapted, Greeks, jump-diffusion)
- Category-specific calibration per Platt parameters

**What we know from academic research:**
- Agentic RAG provides the largest Brier improvement (-0.06 to -0.15)
- 67% market price / 33% AI forecast blend outperforms either alone (Bridgewater)
- NO outperforms YES at 69/99 price levels (favorite-longshot bias)
- Makers earn +1.12% excess return; takers lose -1.12%
- Bayesian reasoning prompts, chain-of-thought, and showing the model its own priors all HURT calibration
- Polymarket political markets are only ~67% correct — room for systematic improvement
- Successful bots primarily use arbitrage and speed, not narrative analysis
- Alpha decay is accelerating (Polymarket adding fees + latency delays)

**Our infrastructure:**
- Dublin VPS (AWS Lightsail eu-west-1), systemd service
- Polymarket: py-clob-client, CLOB limit orders, proxy wallet
- Kalshi: kalshi-python SDK, RSA-PSS auth, integer cent pricing
- Claude API (Haiku for estimation), Telegram for alerts
- SQLite for trade logging, JSON for state
- GitHub repo (going public)

---

## Research Task

Systematically map the complete strategy space for an agentic system trading prediction markets. I need you to identify, categorize, and evaluate every viable trading strategy that could be implemented by an autonomous AI agent on Polymarket and/or Kalshi.

### For each strategy, provide:

1. **Strategy name and one-sentence description**
2. **Category:** Which of these types is it?
   - Forecasting (LLM or statistical model predicts outcomes better than market)
   - Microstructure (exploits order book mechanics, fees, or execution timing)
   - Arbitrage (cross-market, cross-platform, or intra-market price discrepancies)
   - Flow-based (follows smart money, detects informed trading, copy-trading)
   - Event-driven (trades around scheduled events, data releases, news)
   - Structural (exploits systematic biases in how prediction markets price)
   - Hybrid (combines multiple categories)
3. **Resolution speed:** How quickly do target markets resolve? (minutes / hours / days / weeks)
4. **Edge source:** What specific informational or structural advantage does this exploit?
5. **Signal source:** What data feeds or APIs are needed?
6. **Capital requirements:** Minimum viable capital to test ($50? $500? $5K?)
7. **Implementation complexity:** Low (weekend project) / Medium (1-2 weeks) / High (month+)
8. **Testability:** Can we paper-trade this with historical data, or does it require live capital?
9. **Estimated edge:** Basis points or percentage, with confidence level
10. **Known risks and failure modes**
11. **Who else is doing this?** Any known competitors or public implementations?
12. **Relevance to our system:** How does it fit with what we've already built?

### Specific areas to investigate deeply:

**A. Fast-market strategies (resolution < 1 hour)**
- Crypto 5-min/15-min candle markets on Polymarket: What non-LLM signals predict direction?
- Order flow imbalance as a predictor
- Smart wallet convergence signals
- Cross-exchange price leads (Binance/Coinbase spot → Polymarket crypto markets)
- Volatility regime detection for binary crypto markets
- Market microstructure: bid-ask bounce, spread capture, inventory management
- LMSR (Logarithmic Market Scoring Rule) pricing inefficiencies
- Latency arbitrage between data feeds and market prices

**B. Medium-term strategies (resolution 1 hour to 7 days)**
- News event trading: scheduled events (earnings, economic releases, political votes) where timing is known
- Weather market arbitrage using NOAA/ECMWF forecast data
- Polling data → political market pricing gaps
- Sports prop markets where statistical models outperform crowd pricing
- Resolution rule edge: markets where resolution criteria are misunderstood by traders
- Contrarian/sentiment: fading extreme retail positioning

**C. Cross-platform strategies**
- Polymarket vs. Kalshi price discrepancies on identical or equivalent events
- Polymarket vs. traditional betting odds (PredictIt, Betfair, sportsbooks)
- Arbitrage between correlated but not identical markets (e.g., "Trump wins" vs. "Republican wins")

**D. Market making and liquidity provision**
- Two-sided quoting on low-liquidity markets
- Inventory management via split/merge mechanics
- Maker rebate harvesting
- Spread optimization based on informed vs. uninformed flow

**E. Structural bias exploitation**
- Favorite-longshot bias (we already exploit this — what else exists?)
- Recency bias (markets overweight recent events)
- Anchoring to round numbers
- End-of-day/weekend effects
- Expiration-driven price convergence

**F. Advanced AI/ML strategies**
- Agentic RAG (retrieval-augmented generation) for real-time information edge
- Multi-model ensemble (Claude + GPT + Grok + open-source)
- Fine-tuned models on prediction market outcomes
- Reinforcement learning for dynamic position management
- NLP sentiment analysis on social media / news for real-time signal generation

**G. Portfolio-level strategies**
- Correlation-aware position sizing across markets
- Dynamic hedging between correlated positions
- Portfolio rebalancing based on resolution timing
- Risk parity across strategy types

**H. Kalshi-specific strategies**
- Event contracts with known resolution schedules (weather, economic data)
- Higher fee structure exploitation (where Kalshi fees create pricing gaps vs. efficient markets)
- Regulatory arbitrage (Kalshi is CFTC-regulated, different market structure)

### Filtering and ranking criteria:

After cataloging strategies, rank them by a composite score:

**Testability Score (0-10):** Can we validate this strategy's edge with existing data before risking capital? Higher = better.

**Implementation Speed (0-10):** How quickly can we build a working prototype given our existing codebase? Higher = faster.

**Edge Durability (0-10):** Will this edge persist as more bots enter the market, or is it a temporary inefficiency? Higher = more durable.

**Capital Efficiency (0-10):** How much return per dollar of locked capital? Fast-resolving, high-edge strategies score highest.

**Synergy with Existing System (0-10):** Does this integrate cleanly with our Claude analyzer, wallet flow detector, velocity scoring, and execution infrastructure?

**Composite Score = (Testability × 2 + Speed × 2 + Durability × 1.5 + Capital Efficiency × 1.5 + Synergy × 1) / 8**

### Output format:

1. **Executive summary** (1 page): Top 10 strategies we should test immediately, ranked by composite score
2. **Full taxonomy** (organized by category A-H above): Every strategy identified, with all 12 fields
3. **Implementation roadmap:** For the top 10, a suggested testing sequence (what to build first, dependencies, expected validation timeline)
4. **Data sources catalog:** Every API, data feed, and information source referenced, with access details (free/paid, auth requirements, rate limits)
5. **Academic/practitioner references:** Papers, blog posts, public bot code, or documented trader strategies that informed each entry
6. **Risk matrix:** For top 10, a 2×2 of (probability of finding real edge) × (potential impact if edge is real)

### What NOT to include:

- Strategies requiring >$10K minimum capital (we're at $347 total)
- Strategies requiring custom hardware or co-location
- Strategies that are purely theoretical with no testable implementation path
- Strategies that rely on illegal information (insider trading, market manipulation)
- Sports betting strategies that require deep domain expertise we don't have
- Anything requiring real-time data feeds costing >$100/month

---

## Quality bar:

This research will be published on our open-source project website. It should be comprehensive enough that an experienced quantitative trader would learn something new from reading it. It should be specific enough that a developer could start implementing the top strategies based solely on this document. Every claim should cite a source — academic paper, documented bot performance, or publicly verifiable data.

We are building the world's most comprehensive public resource on agentic prediction market trading. This strategy taxonomy is a cornerstone document. Treat it accordingly.
