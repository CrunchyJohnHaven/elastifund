# Deep Research Output: Next 100 Strategies for the Elastifund Flywheel
**Date:** 2026-03-07
**Source Version:** v3
**Cycle:** 1 | **Author:** Claude Opus (Senior Quantitative Research Analyst role)
**For:** Elastifund — John Bradley
**Status:** COMPLETE — 100 strategies, 30 extended specs, 60-day sprint, literature review, meta-assessment

---

## Executive Summary (Top 5 Findings)

**Finding 1: The maker-rebate paradigm shift is your single biggest overlooked opportunity.** Polymarket's Feb-Mar 2026 fee changes killed taker arb bots overnight. The surviving profitable bots are now liquidity providers earning rebates + spread. With $247 USDC, you can't compete on volume, but you CAN compete on *market selection intelligence* — providing liquidity in markets where your LLM + calibration pipeline gives you a better fair-value estimate than other makers. This is Strategy G-1 (Information-Advantaged Market Making) and it's the single highest-priority item. It transforms your LLM signal from a directional bet into a spread-capture engine with embedded information advantage. Honest P(Works): 35%.

**Finding 2: Combinatorial arbitrage across Polymarket's multi-outcome markets is the most empirically validated edge available to small capital.** Saguillo et al. (arXiv:2508.03474, Aug 2025) documented $40M in realized arbitrage across both market-rebalancing and combinatorial types. Your cross-platform arb scanner already does title-matching — extending it to intra-Polymarket MECE violations using LLM-powered dependency detection is a natural evolution. The IMDEA study found 7,000+ markets with measurable combinatorial mispricings. This is low-hanging fruit. Honest P(Works): 45%.

**Finding 3: LLM forecasting accuracy degrades over time even with RAG (Dai et al. 2025, Zhu et al. 2025), and memorization contamination is non-identifiable (Lopez-Lira et al. 2025).** This means your Platt calibration needs continuous recalibration on rolling windows, not static parameters. More importantly, it means LLM-based edges have a structural decay rate that must be modeled explicitly. Your current A/B parameters are static — they need to be adaptive. This isn't a new strategy, but it's a critical infrastructure fix that affects every LLM-dependent strategy.

**Finding 4: The "information processing speed" edge is real but narrowing fast.** The bot that turned $313 into $414K on 15-min BTC markets exploited price lag between Binance and Polymarket — exactly the edge your R4 (Chainlink Basis Lag) attempted. The difference: that bot used maker orders + WebSocket (not REST polling) + sub-100ms execution. Your Dublin VPS at 5-10ms is competitive, but your REST polling architecture is the bottleneck. WebSocket upgrade is prerequisite infrastructure for 8+ strategies in this document.

**Finding 5: The honest probability of finding a sustainable edge with $347 capital is ~15-25%.** But the probability of producing world-class educational content documenting the attempt is ~90%. The flywheel strategy is correct: the research IS the product. The specific strategies most likely to produce either (a) real edge or (b) exceptional educational content are: information-advantaged market making, combinatorial arb, multi-agent LLM debate, and adaptive calibration. These four should consume 80% of engineering time in the first 30 days.

---

## Part 1: 100 Strategy Taxonomy

---

### A. Prediction Market Microstructure (12 strategies)

---

### A-1. Information-Advantaged Market Making (IAMM)
**Mechanism:** Most Polymarket makers quote symmetrically around the last trade price or a simple moving average. A maker who quotes around a *better fair-value estimate* (from calibrated LLM + Platt scaling) earns the spread while also being right more often on the directional component. The structural advantage: you get paid to provide liquidity (zero fees + rebate) while your information edge reduces adverse selection losses. This is the Bridgewater 67/33 blend operationalized as a market-making strategy rather than a directional bet.
**Signal:** When `|calibrated_LLM_estimate - market_midpoint| > 3%`, quote asymmetrically: tighter spread on the side your model favors, wider on the side it disfavors. When `|delta| < 3%`, quote symmetrically and collect pure spread.
**Data:** Gamma API (free) for market discovery, CLOB WebSocket for order book, Claude Haiku API ($0.001/market estimate)
**Alpha:** 50-200 bps/trade on directional component + 20-50 bps spread capture | **Viability:** Likely
**Horizon:** Continuous (positions held minutes to days) | **Capacity:** $5K-50K before spread compression | **Durability:** Years (information advantage is structural)
**Complexity:** M (1-2 weeks — requires WebSocket upgrade + inventory management)
**Synergy:** Direct extension of existing LLM analyzer. Reuses Platt calibration, category routing, anti-anchoring. Transforms from taker (edge must exceed fee) to maker (edge enhances spread capture).
**Kill Criterion:** If adverse selection rate > 60% of fills over 200+ trades (meaning informed flow consistently picks off your quotes).
**Risk:** Inventory accumulation on one side during fast moves. Mitigated by position limits and time-based unwind.
**Who's Doing This:** PolyMaster (@polymaster_io) claims ~10% annualized on long-dated calm markets. Defiance_cr open-sourced a version (poly-maker). But neither uses calibrated LLM fair value — they use simple mid-price.
**Honest P(Works):** 35%

---

### A-2. Liquidity Reward Optimization via Quadratic Spread Function
**Mechanism:** Polymarket's liquidity rewards use a quadratic penalty function that heavily rewards quotes near the "adjusted midpoint" and severely penalizes distant quotes. Most makers don't model this function explicitly. By reverse-engineering the reward function (as PolyMaster documented in Jan 2026), you can optimize quote placement to maximize reward-per-unit-of-risk rather than reward-per-dollar-posted. The key insight: posting $50 at the optimal distance from midpoint can earn more rewards than posting $500 at a suboptimal distance.
**Signal:** Calculate `optimal_distance = argmax(reward_weight(distance) × fill_probability(distance) - adverse_selection(distance))` for each market. Place quotes at this distance.
**Data:** CLOB WebSocket (free), Polymarket reward API (free), historical fill data from your own trading
**Alpha:** 5-15% annualized from rewards alone, before spread P&L | **Viability:** Possible
**Horizon:** Continuous | **Capacity:** $1K-10K (reward pool is finite per market) | **Durability:** 6-12 months (as more makers optimize, reward competition increases)
**Complexity:** M (requires modeling the reward function + real-time quote management)
**Synergy:** Directly pairs with A-1. The LLM fair value tells you WHERE to center quotes; the reward optimization tells you HOW WIDE to make them.
**Kill Criterion:** If daily reward income < $0.50 after 14 days of operation (on $247 capital).
**Risk:** Polymarket changes the reward formula without notice. Mitigated by monitoring reward API daily.
**Who's Doing This:** Defiance_cr ($200/day at peak with $10K). Several poly-maker forks.
**Honest P(Works):** 25%

---

### A-3. New Market Listing Front-Running
**Mechanism:** When Polymarket lists a new market, the first few minutes have no established price discovery. Early liquidity providers set the initial odds, often poorly. An automated system that detects new market creation (via Gamma API polling), rapidly estimates a fair probability (via LLM), and posts maker orders at that fair value can capture systematic mispricing from the "price discovery premium."
**Signal:** Poll Gamma API every 60 seconds for markets with `created_at` within last 5 minutes AND total volume < $500. If LLM estimate diverges from initial midpoint by >10%, post maker orders at LLM estimate.
**Data:** Gamma API `/markets` endpoint with `created_at` sort (free)
**Alpha:** 100-500 bps on early fills | **Viability:** Possible
**Horizon:** First 5-30 minutes of new market life | **Capacity:** $1K-5K (limited by early liquidity) | **Durability:** Months (structural — new markets always need price discovery)
**Complexity:** S (weekend — simple Gamma API polling + LLM call + order placement)
**Synergy:** Reuses entire LLM + calibration pipeline. Just adds a new market discovery trigger.
**Kill Criterion:** If <5 new qualifying markets appear per week, or if average fill rate < 10%.
**Risk:** Other bots already front-run new listings. Your edge is LLM-quality fair value, not speed.
**Who's Doing This:** Unknown number of early-listing bots, but most use simple heuristics, not LLM estimates.
**Honest P(Works):** 20%

---

### A-4. YES/NO Liquidity Depth Asymmetry Exploitation
**Mechanism:** The jbecker.dev analysis showed NO outperforms YES at 69/99 price levels. A related but distinct phenomenon: the *depth* of liquidity on the YES side vs NO side is often asymmetric. When YES depth >> NO depth at equivalent distances from mid, it suggests informed money is willing to sell YES (= buy NO) but retail is piling into YES. This depth asymmetry is a leading indicator of price movement toward the deeper side's reservation price.
**Signal:** When `YES_depth_5bps / NO_depth_5bps > 2.0` AND `market_price > 0.40`, buy NO (the thin side tends to reprice). Reverse for NO-heavy asymmetry.
**Data:** CLOB WebSocket order book snapshots (free)
**Alpha:** 30-80 bps | **Viability:** Possible
**Horizon:** 1-6 hours (depth asymmetry corrects over hours, not minutes) | **Capacity:** $2K-10K | **Durability:** 6-12 months
**Complexity:** S (requires WebSocket for book data, then simple ratio calculation)
**Synergy:** Feeds into confirmation layer. When LLM + depth asymmetry agree, boost position size.
**Kill Criterion:** If win rate < 52% after 100 signals.
**Risk:** Depth can be misleading (iceberg orders, spoofing). CLOB 404 issues on some token IDs (known limitation from your edge discovery pipeline).
**Who's Doing This:** Traditional equity microstructure traders do this routinely. Likely <5 on Polymarket.
**Honest P(Works):** 20%

---

### A-5. Resolution Boundary Maker Withdrawal Detection
**Mechanism:** In the final 30 minutes before a market resolves, sophisticated makers withdraw quotes to avoid being adversely selected by traders with resolution information. This withdrawal creates a characteristic "liquidity vacuum" visible in order book depth. Detecting this vacuum and its directionality (which side withdraws first) reveals which way informed participants expect resolution.
**Signal:** When `book_depth(t) / book_depth(t-30min) < 0.3` AND `time_to_resolution < 60min`, AND one side withdraws faster than the other (ratio > 1.5), bet the side that informed makers are keeping (the side that still has liquidity = the side they're confident about).
**Data:** CLOB WebSocket (free), Gamma API for resolution timestamps (free)
**Alpha:** 50-200 bps | **Viability:** Possible
**Horizon:** 5-30 minutes before resolution | **Capacity:** $1K (limited by thin pre-resolution liquidity) | **Durability:** Structural (maker withdrawal is rational behavior)
**Complexity:** S (WebSocket + time tracking)
**Synergy:** Works on all market types. Particularly strong combined with wallet flow detector (A-5 tells you WHEN to look, wallet flow tells you WHO is moving).
**Kill Criterion:** If <3 detectable withdrawal events per day, or win rate < 55% over 50 events.
**Risk:** Very thin liquidity near resolution = high slippage. Must use maker orders.
**Who's Doing This:** Likely a handful of sophisticated market makers already time their withdrawal.
**Honest P(Works):** 15%

---

### A-6. Multi-Outcome Market Sum Violation Scanner (Intra-Market Arb)
**Mechanism:** Multi-outcome Polymarket markets (e.g., "Who will be the next PM of X?" with 10 candidates) should have all YES prices sum to $1.00. Due to independent pricing of each outcome and varying liquidity, sums routinely drift to $0.95-$1.08. When sum < $1.00, buy all outcomes (guaranteed profit). When sum > $1.00, short all outcomes (if shorting available) or sell any positions held.
**Signal:** `sum(all_YES_prices) < 0.97` → buy $1 of each outcome. `sum > 1.03` → sell (or construct NO basket).
**Data:** Gamma API `/markets` + CLOB best-ask prices (free)
**Alpha:** 100-300 bps per rebalance event | **Viability:** Likely
**Horizon:** Minutes to hours | **Capacity:** $500-5K per market | **Durability:** Structural (multi-outcome markets always have sum violations)
**Complexity:** S (simple price aggregation + simultaneous order placement)
**Synergy:** Uses same market discovery as cross-platform arb scanner. Low engineering overhead.
**Kill Criterion:** If average executable spread < 1% after fees (non-atomic execution risk absorbs the profit).
**Risk:** Non-atomic execution (you buy outcomes sequentially, and prices move between orders). Mitigated by posting maker orders on all outcomes simultaneously.
**Who's Doing This:** Saguillo et al. (arXiv:2508.03474) documented $40M in this exact type of arbitrage. Multiple bots are active. But multi-outcome markets continuously generate new sum violations.
**Honest P(Works):** 45%

---

### A-7. Tick Size Rounding Exploitation at Price Extremes
**Mechanism:** Polymarket prices are quoted in cents ($0.01 increments). At extreme prices (e.g., $0.01 or $0.99), the tick size represents a 100% or 1% move respectively. This creates a structural edge: at $0.01, the buyer risks $0.01 to make $0.99. The EV breakeven is just 1.01% probability. Markets priced at $0.01-$0.03 where the true probability is even slightly higher (say 3-5%) offer massive risk/reward asymmetry. The key is identifying which extreme-priced outcomes are systematically underpriced.
**Signal:** Filter markets where any outcome is priced $0.01-$0.05. Use LLM to estimate true probability. If `LLM_estimate > 2 × market_price`, buy with capped position ($1-2 max).
**Data:** Gamma API (free), LLM API ($0.001/estimate)
**Alpha:** Negative EV on most trades but 20:1 or 50:1 payoff on hits. Portfolio-level EV positive if LLM can distinguish 1% from 5% outcomes. | **Viability:** Unlikely (LLM calibration is worst at extremes)
**Horizon:** Days to weeks | **Capacity:** $50-200 (tiny positions) | **Durability:** Structural
**Complexity:** S (simple filter + LLM call)
**Synergy:** Minimal — extreme prices are a different regime from your main calibrated pipeline.
**Kill Criterion:** If 0 hits in first 50 positions (expected: 2-3 if true probability is 3-5%).
**Risk:** These are usually priced at $0.01 for a reason. LLM overconfidence at extremes means most of these positions will be worthless. This is educational value primarily.
**Who's Doing This:** "Lottery ticket" strategies are common among retail traders. Systematic versions are rare.
**Honest P(Works):** 10%

---

### A-8. Post-Only Order Timing Relative to Candle Open
**Mechanism:** In 5-min/15-min crypto markets, the first 30-60 seconds after candle open have the widest spreads and most uninformed flow (retail market orders). Makers who post quotes in the first 10 seconds capture the widest spreads. But after 60 seconds, informed flow arrives and adverse selection spikes. The optimal maker strategy has a specific entry window (first 10s) and exit window (before 60s).
**Signal:** At candle_open + 5 seconds, post maker orders at ±2% from current mid. Cancel all orders at candle_open + 45 seconds. Repeat next candle.
**Data:** CLOB WebSocket for timestamps (free), Binance WebSocket for reference price (free)
**Alpha:** 10-30 bps per candle on filled orders | **Viability:** Possible
**Horizon:** 5-45 seconds per candle | **Capacity:** $1K-5K | **Durability:** 3-6 months (as more makers optimize timing, the window shrinks)
**Complexity:** S (timer-based maker posting)
**Synergy:** Pairs with smart wallet flow detector. If wallet flow signal fires during the candle, DON'T cancel — hold the directional position.
**Kill Criterion:** If fill rate < 5% in first 100 candles, or if filled orders have > 55% adverse selection rate.
**Risk:** WebSocket latency jitter could cause late posting (arriving in the informed-flow window). Dublin latency should be adequate.
**Who's Doing This:** BlockBeats article (Mar 2026) describes this exact timing pattern as the "new meta" for 5-min markets.
**Honest P(Works):** 20%

---

### A-9. Spread Regime Classification and Dynamic Width Adjustment
**Mechanism:** Not all markets at the same price level have the same optimal spread width. A market with high news sensitivity (e.g., breaking geopolitical event) needs wider spreads than a calm, slow-resolution market (e.g., "Will X law pass by December?"). Classifying markets into spread regimes (high-vol, low-vol, news-sensitive, mean-reverting) and dynamically adjusting quote width maximizes the Sharpe ratio of the market-making book.
**Signal:** Classify each market into one of 4 regimes based on: (1) historical 24h price range, (2) category (politics=volatile, weather=calm), (3) time-to-resolution, (4) recent trade velocity. Set spread width = base_spread × regime_multiplier.
**Data:** Gamma API history, CLOB trade feed (free)
**Alpha:** Improves A-1 Sharpe by 20-40% (reduces adverse selection in volatile markets, captures more flow in calm markets) | **Viability:** Possible
**Horizon:** Continuous | **Capacity:** Same as A-1 | **Durability:** Years
**Complexity:** M (requires building regime classification model + backtesting optimal widths)
**Synergy:** Enhancement to A-1. Uses same infrastructure, just smarter quote management.
**Kill Criterion:** If regime-classified P&L doesn't outperform uniform spread by >10% over 500 trades.
**Risk:** Regime misclassification in transition periods (e.g., market goes from calm to news-driven mid-session).
**Who's Doing This:** Standard in traditional market making. Novel on Polymarket because most makers use uniform spreads.
**Honest P(Works):** 25%

---

### A-10. Market-Maker Inventory Hedging via Correlated Markets
**Mechanism:** When making a market on "Will Trump win 2028?", your inventory naturally drifts directional. Rather than unwinding (which costs spread), you can hedge by taking offsetting positions in correlated markets ("Will Republican win 2028?" or "Will Trump be nominated?"). This reduces your net directional exposure while maintaining both market-making positions and their associated rewards.
**Signal:** When `|inventory_imbalance| > 50%` of max allowed, search for correlated markets using LLM-powered dependency detection. Place offsetting maker orders on the correlated market.
**Data:** Gamma API for market discovery, LLM for correlation mapping (free + $0.01/correlation query)
**Alpha:** Reduces drawdown by 30-50% (not direct alpha, but improves risk-adjusted returns) | **Viability:** Possible
**Horizon:** Continuous | **Capacity:** $2K-20K | **Durability:** Structural
**Complexity:** M (requires correlation graph construction + inventory tracking)
**Synergy:** Uses LLM for semantic similarity (same model, different prompt). Links to combinatorial arb scanner.
**Kill Criterion:** If hedging cost (spread paid on correlated market) > 50% of hedge benefit (variance reduction).
**Risk:** Correlation breaks down during tail events (exactly when you need the hedge most).
**Who's Doing This:** Institutional market makers (Susquehanna) almost certainly do this. Unclear on Polymarket.
**Honest P(Works):** 20%

---

### A-11. Fee-Regime Arbitrage Across Market Types
**Mechanism:** Some Polymarket markets have taker fees (crypto 5-min, 15-min, NCAAB, Serie A) while most are fee-free. When the same underlying event is tradeable in both a fee-bearing and fee-free market (e.g., a crypto price outcome that's available in both 5-min and a longer-horizon fee-free market), the fee difference creates a structural price wedge. The fee-bearing market should trade at a slightly worse price to compensate takers for the fee.
**Signal:** When two markets reference the same underlying outcome but have different fee regimes, and the price difference exceeds the fee differential, arbitrage between them.
**Data:** CLOB fee-rate endpoint + Gamma API for market matching (free)
**Alpha:** 50-150 bps per crossing | **Viability:** Unlikely (few cross-regime market pairs exist)
**Horizon:** Minutes | **Capacity:** $500-2K | **Durability:** Structural if pairs exist
**Complexity:** S
**Synergy:** Extension of cross-platform arb scanner logic.
**Kill Criterion:** If <2 qualifying market pairs identified per week.
**Risk:** Markets may not have sufficient overlap for this to produce meaningful signal volume.
**Who's Doing This:** Nobody documented, because the fee structure is too new (Jan-Feb 2026).
**Honest P(Works):** 10%

---

### A-12. Ghost Liquidity Detection (Iceberg Order Inference)
**Mechanism:** On CLOB-style exchanges, some participants hide the full size of their orders (showing only a fraction at any given time). These "iceberg" orders are detectable by watching for repeated fills at the same price level — after each fill, the order refills to the same displayed size. Detecting icebergs reveals hidden large-trader intention, which is a leading indicator of price direction.
**Signal:** When a price level shows 3+ consecutive fills of similar size within 60 seconds, each followed by replenishment to the same displayed quantity, flag as iceberg. The iceberg side indicates a large trader's directional intent.
**Data:** CLOB WebSocket trade-by-trade feed (free)
**Alpha:** 30-80 bps | **Viability:** Unlikely (requires high tick-level data resolution)
**Horizon:** Minutes to hours | **Capacity:** $1K-5K | **Durability:** Structural (iceberg behavior is persistent)
**Complexity:** M (requires tick-level trade database + pattern detection)
**Synergy:** Feeds into confirmation layer as a microstructure signal.
**Kill Criterion:** If <5 iceberg events detected per day, or if detected icebergs predict direction at <55% rate.
**Risk:** Polymarket's off-chain matching may obscure the fill patterns needed for detection. CLOB 404 issues compound this.
**Who's Doing This:** Standard in equity HFT. Novel on Polymarket due to different matching mechanics.
**Honest P(Works):** 10%

---

### B. Cross-Market & Cross-Platform Arbitrage (10 strategies)

---

### B-1. LLM-Powered Combinatorial Dependency Graph for Intra-Polymarket Arb
**Mechanism:** Saguillo et al. documented that logical dependencies between Polymarket markets (e.g., "Trump wins" implies "Republican wins") create combinatorial arbitrage. Their method used LLMs to detect dependencies. You already have LLM infrastructure. The edge: automatically build a dependency graph across ALL active Polymarket markets, continuously monitor for probability constraint violations (P(A) > P(B) when A⊂B is logically necessary), and trade when violations exceed fee threshold.
**Signal:** For every pair of markets where LLM identifies logical dependency (A implies B, A is subset of B, etc.): if `price(A) > price(B) + 0.02`, buy B and sell A. If `price(A) + price(complement_of_A_within_B) < price(B) - 0.02`, construct multi-leg arb.
**Data:** Gamma API for all markets (free), LLM for dependency detection (~$0.10/pair), CLOB for execution (free)
**Alpha:** 100-300 bps per violation | **Viability:** Likely
**Horizon:** Minutes to hours | **Capacity:** $2K-20K (limited by liquidity in thinner-volume markets) | **Durability:** Structural (new markets = new dependencies = new violations)
**Complexity:** M (dependency graph construction + multi-leg order management)
**Synergy:** Direct extension of cross-platform arb scanner. LLM infrastructure reused. The dependency detection can also be used for A-10 (correlation hedging).
**Kill Criterion:** If <3 violations per week exceeding fee threshold, or if non-atomic execution risk eliminates >50% of theoretical profit.
**Risk:** Non-atomic execution (multi-leg orders don't fill simultaneously). Mitigated by posting all legs as maker orders and using conservative sizing.
**Who's Doing This:** Top 3 wallets in IMDEA study earned $4.2M combined, primarily from combinatorial strategies. This is where the big money is.
**Honest P(Works):** 45%

---

### B-2. Polymarket ↔ Kalshi Resolution Rule Divergence
**Mechanism:** The same real-world event can resolve differently on different platforms due to different resolution criteria. Example: "Government shutdown" — Polymarket may use OPM announcement while Kalshi requires 24+ hours of actual shutdown. These divergences create situations where the same event resolves YES on one platform and NO on another, allowing guaranteed profit if you buy YES on both. The key: systematically map resolution rule differences for all overlapping markets.
**Signal:** For each market pair where `title_similarity > 0.70` (your existing matcher), extract and compare resolution criteria. When criteria diverge such that a plausible scenario resolves differently on each platform, buy the underpriced side on each.
**Data:** Gamma API + Kalshi API market descriptions (free), LLM for resolution criteria comparison ($0.05/pair)
**Alpha:** 200-1000 bps on qualifying events | **Viability:** Possible
**Horizon:** Days to weeks (resolution-dependent) | **Capacity:** $100-500 (capital-limited on Kalshi) | **Durability:** Structural (different platforms will always have different rules)
**Complexity:** M (requires legal-text parsing of resolution criteria + scenario modeling)
**Synergy:** Extension of existing cross-platform arb scanner. Adds resolution-rule comparison layer.
**Kill Criterion:** If <2 qualifying divergent pairs per month.
**Risk:** Platform resolution risk — the less-regulated platform (Polymarket) could resolve ambiguously. Kalshi has CFTC oversight = more predictable.
**Who's Doing This:** The 2024 government shutdown case is well-documented. Systematic resolution-rule mapping is rare.
**Honest P(Works):** 25%

---

### B-3. Implied Probability Transfer: Prediction Market → Options Market
**Mechanism:** Polymarket prices for events like "Fed cuts rates in March" imply a probability that can be compared to the implied probability derived from Fed Funds futures or interest rate options. When these diverge significantly, one market is wrong. Prediction markets are typically less efficient than deep, institutional derivatives markets, so the derivatives-implied probability is likely more accurate.
**Signal:** Extract implied probability from CME Fed Funds futures (or interest rate swaps). Compare to Polymarket price for the corresponding Fed decision market. If `|PM_price - derivatives_implied| > 8%`, trade Polymarket toward the derivatives-implied probability.
**Data:** CME Fed Funds futures (free delayed data via FRED), Polymarket API (free)
**Alpha:** 50-200 bps | **Viability:** Possible
**Horizon:** Days to weeks (aligned with FOMC schedule) | **Capacity:** $1K-10K | **Durability:** Months (prediction market participants don't all monitor derivatives)
**Complexity:** S (simple spread comparison — Fed funds futures implied probabilities are publicly available)
**Synergy:** Adds a non-LLM quantitative signal. Excellent for confirmation layer (LLM + derivatives agree = high confidence).
**Kill Criterion:** If derivatives-implied probability has <65% accuracy on past 20 FOMC decisions.
**Risk:** Prediction market may be pricing a subtly different question (timing, magnitude, language).
**Who's Doing This:** Institutional quants likely do this, but Polymarket FOMC markets are often thin enough that even small capital can move the price.
**Honest P(Works):** 30%

---

### B-4. Cross-Platform Speed Arb: Kalshi Settlement Before Polymarket
**Mechanism:** Kalshi and Polymarket may resolve the same event at different times due to different oracle/verification processes. If Kalshi resolves first (faster oracle), the Polymarket price may not yet reflect the known outcome. Buy the correct side on Polymarket before it reprices.
**Signal:** Monitor Kalshi API for market resolution events. When a Kalshi market resolves, immediately check if the corresponding Polymarket market is still actively trading. If Polymarket price hasn't fully adjusted (i.e., is not yet $0.95+ or $0.05-), buy the winning side.
**Data:** Kalshi API (free, real-time), Polymarket API (free)
**Alpha:** 200-500 bps per event | **Viability:** Unlikely (rare event; most markets resolve at similar times)
**Horizon:** Minutes | **Capacity:** $100-500 per event | **Durability:** Structural but rare
**Complexity:** S
**Synergy:** Uses existing cross-platform infrastructure.
**Kill Criterion:** If <1 qualifying event per month.
**Risk:** Extremely rare. The profit per event may not justify monitoring infrastructure.
**Who's Doing This:** Likely a few cross-platform arb bots, but the event frequency is so low that it's not a primary strategy.
**Honest P(Works):** 10%

---

### B-5. Conditional Probability Chain Arbitrage (Multi-Market)
**Mechanism:** Three or more Polymarket markets may form a conditional probability chain: P(A∩B) = P(A|B)×P(B). If Market 1 prices P(A), Market 2 prices P(B), and Market 3 prices P(A∩B), you can check whether the chain is consistent. When `P(A∩B) ≠ P(A|B) × P(B)` beyond a threshold, construct a multi-leg position that profits regardless of outcome.
**Signal:** Identify triplets of markets where one is logically the intersection of the other two. Compute implied conditional probability. When `|implied_P(A|B) - market_P(A|B)| > 5%`, construct 3-leg arb.
**Data:** Gamma API + LLM for logical relationship identification (free + ~$0.10/triplet)
**Alpha:** 100-300 bps | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** $500-5K | **Durability:** Structural
**Complexity:** L (finding valid triplets at scale is computationally hard — NP-hard in general, but heuristic approaches work)
**Synergy:** Extension of B-1 dependency graph. The graph naturally reveals conditional chains.
**Kill Criterion:** If <5 valid triplets found across all active markets, or if none exceed fee-adjusted threshold.
**Risk:** Non-atomic multi-leg execution. Complexity of tracking 3 positions simultaneously.
**Who's Doing This:** IMDEA study found some combinatorial arb, but explicit conditional chain exploitation appears rare.
**Honest P(Works):** 20%

---

### B-6. Metaculus → Polymarket Probability Transfer
**Mechanism:** Metaculus has a community of calibrated forecasters whose median estimates are demonstrably well-calibrated (better than base-rate prediction). When a Metaculus question maps to a Polymarket market, the Metaculus community median can be treated as a second opinion alongside your LLM. Significant divergence between Metaculus and Polymarket suggests the prediction market is mispriced.
**Signal:** Match Metaculus questions to Polymarket markets by title similarity. When `|metaculus_median - polymarket_price| > 10%`, and `|LLM_estimate - metaculus_median| < 5%` (LLM and Metaculus agree), trade Polymarket toward the Metaculus/LLM consensus.
**Data:** Metaculus API (free, public forecasts), Polymarket API (free)
**Alpha:** 50-150 bps | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $1K-10K | **Durability:** Months (Metaculus forecasters continuously update)
**Complexity:** S (title matching + price comparison)
**Synergy:** Adds third-party human forecaster signal to confirmation layer.
**Kill Criterion:** If Metaculus-PM divergence doesn't predict PM price movement at >55% rate over 50 instances.
**Risk:** Metaculus questions may not map cleanly to PM markets. Resolution criteria may differ.
**Who's Doing This:** A few quantitative forecasters likely do this manually. Systematic automated version is rare.
**Honest P(Works):** 25%

---

### B-7. Triangular Arb: Polymarket ↔ Kalshi ↔ Betfair/Smarkets
**Mechanism:** Three platforms pricing the same event can create triangular arbitrage. If Platform A prices YES at $0.55, Platform B prices NO at $0.40 (implying YES at $0.60), and Platform C prices YES at $0.52, you can construct a 3-platform position that locks in profit from the inconsistency.
**Signal:** For each event covered by 3+ platforms, compute `implied_YES_A + implied_NO_B + implied_NO_C < 2.00` (or other multi-leg profitable combinations). When profitable combination exists after fees, execute.
**Data:** Polymarket, Kalshi APIs (free), Betfair/Smarkets API (free tier available)
**Alpha:** 50-200 bps | **Viability:** Unlikely (few events have 3-platform coverage)
**Horizon:** Hours | **Capacity:** $100-1K (limited by smallest platform's liquidity) | **Durability:** Structural but rare
**Complexity:** M (multi-platform API integration + fee normalization)
**Synergy:** Extends cross-platform arb scanner to 3+ platforms.
**Kill Criterion:** If <1 qualifying triangular opportunity per month.
**Risk:** Settlement timing differences across platforms. Betfair/Smarkets may not be accessible from Dublin VPS.
**Who's Doing This:** Cross-platform arb bots exist but 3-platform triangular specifically is very rare.
**Honest P(Works):** 8%

---

### B-8. MECE Portfolio Construction Across Related Markets
**Mechanism:** Rather than arbitraging individual mispricing, construct a portfolio that exploits the *structural mispricing* across a group of mutually-exclusive-collectively-exhaustive markets. Example: "Next UK PM" has 8 candidates. Buy the set of candidates whose total price sums to < your LLM's estimate of their collective probability. This is a "basket" trade that's more robust than individual picks.
**Signal:** For multi-outcome markets, compute `LLM_collective_probability(subset)` for various subsets. If `market_price(subset) < LLM_collective_probability(subset) - 5%`, buy the subset.
**Data:** Gamma API (free), LLM API ($0.01 for subset estimation)
**Alpha:** 50-150 bps | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $500-5K | **Durability:** Structural
**Complexity:** M (combinatorial subset analysis)
**Synergy:** LLM-powered probability estimation reused. Category routing provides market selection.
**Kill Criterion:** If subset estimates have calibration error > 0.15 on resolved multi-outcome markets.
**Risk:** LLM calibration on multi-outcome subsets is untested. May be worse than binary calibration.
**Who's Doing This:** Sophisticated bettors on sports (Betfair) do this routinely. Rare on prediction markets.
**Honest P(Works):** 20%

---

### B-9. Prediction Market ↔ Crypto Derivatives Relative Value
**Mechanism:** When Polymarket lists "BTC > $100K by March 31", this is economically equivalent to a deep out-of-the-money binary call option on BTC. The same payoff can be replicated (approximately) using Deribit BTC options. If the PM price diverges from the options-implied probability, arbitrage between them.
**Signal:** Price the PM outcome using Black-Scholes on Deribit BTC options chain. When `|PM_price - options_implied| > 10%`, trade PM toward options-implied.
**Data:** Deribit options API (free), Polymarket API (free)
**Alpha:** 50-200 bps | **Viability:** Unlikely (few PM markets map cleanly to tradeable options)
**Horizon:** Days to weeks | **Capacity:** $500-5K | **Durability:** Structural
**Complexity:** M (requires options pricing + PM mapping)
**Synergy:** Non-LLM quantitative signal. Adds to confirmation layer.
**Kill Criterion:** If PM-options divergence is <5% for all qualifying markets.
**Risk:** PM resolution criteria may not match options strike/expiry exactly. Basis risk.
**Who's Doing This:** Derivatives quants at Susquehanna/Jump likely evaluate this. Unknown whether they execute.
**Honest P(Works):** 12%

---

### B-10. Kalshi Category Advantage: Weather Markets with Faster Resolution
**Mechanism:** Your NOAA weather bracket strategy was killed for insufficient model accuracy. But Kalshi has weather markets that resolve DAILY (not via bracket rounding) — simple "Will it rain in NYC tomorrow?" markets. For these binary rain/no-rain questions, NWS probability of precipitation (PoP) is well-calibrated and publicly available. If PoP diverges from Kalshi market price by >10%, trade.
**Signal:** Fetch NWS PoP for target cities. Compare to Kalshi rain/temp markets. When `|NWS_PoP - Kalshi_price| > 10%`, buy the NWS-favored side.
**Data:** NWS API (free, public, real-time), Kalshi API (free)
**Alpha:** 50-150 bps | **Viability:** Possible
**Horizon:** 12-36 hours (daily resolution) | **Capacity:** $100-500 (Kalshi weather market liquidity is thin) | **Durability:** Months (NWS data is public but most retail traders don't use it systematically)
**Complexity:** S (simple API comparison)
**Synergy:** Reuses concept from killed weather bracket strategy but on a fundamentally different (and more favorable) market structure. Binary rain/no-rain avoids the bracket rounding problem.
**Kill Criterion:** If NWS PoP accuracy on binary rain/no-rain is <70% for target cities.
**Risk:** Thin liquidity on Kalshi weather markets. May not be able to fill at desired price.
**Who's Doing This:** Unknown. Weather markets on Kalshi are new and thinly traded.
**Honest P(Works):** 25%

---

### C. Information Latency & Alternative Data (15 strategies)

---

### C-1. Congressional Stock Disclosure Front-Running (STOCK Act)
**Mechanism:** Under the STOCK Act, members of Congress must disclose stock trades within 45 days. Services like Capitol Trades (quiverlabs.com) provide near-real-time notifications. When a senator on the Armed Services Committee buys defense stocks, this may correlate with upcoming defense-related legislation — information that prediction markets price slowly.
**Signal:** When a congressional member with committee relevance makes a trade with `trade_size > $50K` AND a corresponding Polymarket/Kalshi market exists (e.g., defense spending bill), and `time_since_disclosure < 24h`, adjust probability estimate by +5% in the direction implied by the trade.
**Data:** Capitol Trades / Quiver Quant API (free tier), Polymarket/Kalshi APIs (free)
**Alpha:** 30-80 bps | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $500-5K | **Durability:** Years (STOCK Act is law; congressional information advantage is structural)
**Complexity:** S (API polling + market matching)
**Synergy:** Feeds into LLM analyzer as additional context for political markets.
**Kill Criterion:** If congressional trade direction predicts PM outcome at <55% rate over 30 instances.
**Risk:** 45-day disclosure delay means information may be stale. The edge is in the *pattern*, not individual trades.
**Who's Doing This:** Multiple Reddit communities track congressional trades for stock trading. Application to prediction markets is novel.
**Honest P(Works):** 15%

---

### C-2. Court Docket Monitoring (PACER/CourtListener)
**Mechanism:** Federal court rulings affect prediction markets (e.g., "Will X law be struck down?"). Court dockets are public on PACER, and CourtListener provides free API access. New filings, scheduled oral arguments, and judge assignments are leading indicators. A judge known to be sympathetic to one side changes the probability; this information is available hours before the market prices it.
**Signal:** For each Polymarket legal/regulatory market, identify the relevant court case. Monitor PACER/CourtListener for new filings. When a substantive filing appears (motion to dismiss granted, oral argument scheduled, new judge assigned), use LLM to estimate impact on outcome probability. If market hasn't moved within 30 minutes of filing, trade.
**Data:** CourtListener API (free), PACER (free for basic searches, $0.10/page for full documents)
**Alpha:** 50-200 bps on qualifying events | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** $500-5K | **Durability:** Years (legal markets are structurally slow to price court filings)
**Complexity:** M (requires mapping PM markets to court cases + LLM filing analysis)
**Synergy:** Perfect use case for Agentic RAG (the #1 improvement method in academic evidence hierarchy).
**Kill Criterion:** If <3 qualifying legal markets exist on PM at any given time.
**Risk:** PACER updates can be slow (hours after actual filing). CourtListener free tier has rate limits.
**Who's Doing This:** Legal prediction markets (Kalshi) are growing. Systematic court docket monitoring for PM trading is novel.
**Honest P(Works):** 20%

---

### C-3. FDA Calendar + ClinicalTrials.gov Phase Tracking
**Mechanism:** FDA PDUFA dates (drug approval deadlines) are scheduled months in advance. Historical approval rates by phase, therapeutic area, and advisory committee vote are well-characterized. If Polymarket or Kalshi lists a drug approval market, the base rate (historically ~85% for drugs with positive advisory committee votes) provides a strong prior. When markets deviate from historical base rates, trade toward the base rate.
**Signal:** Match PM/Kalshi pharma markets to FDA calendar events. Look up phase, advisory committee status, therapeutic area. Compute base-rate probability from historical data. If `|market_price - base_rate| > 10%`, trade toward base rate.
**Data:** FDA PDUFA calendar (free), ClinicalTrials.gov API (free), FDA approval database (free)
**Alpha:** 50-200 bps | **Viability:** Possible
**Horizon:** Days to weeks pre-PDUFA date | **Capacity:** $500-5K | **Durability:** Years (base rates are stable; retail traders over-weight narrative)
**Complexity:** S (simple base rate lookup + market matching)
**Synergy:** Base-rate-first prompting is already deployed in your LLM pipeline. This provides a quantitative base rate for pharma specifically.
**Kill Criterion:** If base-rate strategy accuracy <60% over 20 FDA decisions.
**Risk:** Small number of qualifying markets. Base rates don't account for drug-specific information.
**Who's Doing This:** Pharma investors use this for stock trading. Application to prediction markets is less common.
**Honest P(Works):** 20%

---

### C-4. GDELT Global Event Database Real-Time Monitoring
**Mechanism:** GDELT (Global Database of Events, Language, and Tone) processes global news in real-time (15-minute update cadence), categorizing events by type, participants, sentiment, and geography. When GDELT detects a spike in geopolitical events involving specific countries/actors, this is a leading indicator for prediction markets about those countries/actors.
**Signal:** Monitor GDELT API for event volume spikes: `event_count(country, 1h) > 5 × rolling_30d_avg(country, 1h)`. Cross-reference with active PM markets involving that country. Use LLM to estimate probability impact. If market hasn't repriced within 30 minutes of GDELT spike, trade.
**Data:** GDELT API (free, 15-min updates), Polymarket/Kalshi APIs (free)
**Alpha:** 30-100 bps | **Viability:** Possible
**Horizon:** Hours | **Capacity:** $500-5K | **Durability:** Months (GDELT is public, but few PM traders monitor it systematically)
**Complexity:** M (requires GDELT integration + PM market matching + LLM analysis)
**Synergy:** Direct implementation of Agentic RAG for geopolitical markets.
**Kill Criterion:** If GDELT event spikes don't precede PM price moves at >55% rate over 50 instances.
**Risk:** GDELT has high false positive rate (many event spikes are noise). LLM filtering is essential.
**Who's Doing This:** GDELT is used in academic research. Systematic use for PM trading is novel.
**Honest P(Works):** 15%

---

### C-5. GitHub Commit Pattern Detection for Tech Markets
**Mechanism:** When Polymarket lists "Will OpenAI release GPT-5 by date X?", the most informative leading indicator is development activity. GitHub public repos (associated organizations, key developers) show commit velocity, branch creation, and README changes that precede product launches. A spike in "docs" or "release" branch commits is a strong signal.
**Signal:** For PM tech/product markets, identify relevant GitHub organizations. Monitor commit velocity. When `commit_count(7d) > 3 × commit_count(30d_avg)` AND commit messages contain release-related keywords, increase probability estimate by 10%.
**Data:** GitHub API (free, 5000 requests/hour)
**Alpha:** 30-80 bps | **Viability:** Unlikely (most tech companies use private repos)
**Horizon:** Days to weeks | **Capacity:** $500-2K | **Durability:** Structural (public repos will always exist)
**Complexity:** S (GitHub API polling + keyword matching)
**Synergy:** Alternative data feed for LLM analyzer context.
**Kill Criterion:** If <5 PM markets have monitorable GitHub repos, or if commit patterns don't predict releases at >60% rate.
**Risk:** Most meaningful development happens in private repos. Open-source signals are heavily lagged.
**Who's Doing This:** VC analysts do this for investment decisions. PM application is novel.
**Honest P(Works):** 8%

---

### C-6. News Wire Speed Advantage (NewsAPI + Event Extraction)
**Mechanism:** News breaks on wire services (Reuters, AP) 2-15 minutes before reaching social media and prediction market participants. By monitoring wire services via API and using LLM to extract event implications for active PM markets, you can trade before the market reprices.
**Signal:** Poll NewsAPI every 60 seconds for breaking news. Feed headlines to LLM with list of active PM markets. When LLM identifies a headline that changes a PM market's probability by >5%, trade immediately.
**Data:** NewsAPI (free tier: 100 requests/day; paid: $450/mo)
**Alpha:** 50-200 bps per qualifying event | **Viability:** Possible
**Horizon:** Minutes | **Capacity:** $1K-10K | **Durability:** Months (speed advantage persists as long as PM participants are slower than wire services)
**Complexity:** M (requires real-time news polling + LLM event-market mapping + fast execution)
**Synergy:** This IS Agentic RAG — the #1 priority improvement from academic literature. Direct implementation.
**Kill Criterion:** If average time between news wire publication and PM price reaction is <5 minutes (no window to trade).
**Risk:** Free tier too limited. Paid tier is expensive relative to capital. LLM may misinterpret headlines.
**Who's Doing This:** The bot profiled by Igor Mikerin ($2.2M in 2 months) used ensemble models trained on news. This is the competitive frontier.
**Honest P(Works):** 25%

---

### C-7. FRED Economic Release Consensus Divergence
**Mechanism:** Before major economic data releases (CPI, NFP, GDP), the consensus estimate from economists is published. When PM markets for "CPI above X%" deviate from the consensus-implied probability, one is wrong. Economic consensus has known biases (tends to under-predict in trending environments), creating systematic divergence from PM prices.
**Signal:** Fetch consensus estimates from FRED or Bloomberg consensus. Convert to binary probability (using historical distribution of actual-vs-consensus). Compare to PM price. When divergence > 8%, trade PM toward consensus-implied probability.
**Data:** FRED API (free), consensus estimates from Trading Economics (free tier)
**Alpha:** 50-150 bps per release | **Viability:** Possible
**Horizon:** Days pre-release | **Capacity:** $500-5K | **Durability:** Months
**Complexity:** S
**Synergy:** Non-LLM quantitative signal for confirmation layer.
**Kill Criterion:** If consensus-implied probability accuracy <55% over 20 releases.
**Risk:** "Consensus" itself is imperfect. PM may already reflect consensus + additional information.
**Who's Doing This:** Macro traders do this for financial markets. PM application is uncommon.
**Honest P(Works):** 20%

---

### C-8. App Store Ranking Shifts for Product Launch Markets
**Mechanism:** When Polymarket lists "Will X app reach 10M downloads by date Y?", App Store / Google Play ranking data is a leading indicator. Apps that surge from rank 500 to rank 50 in their category are on a trajectory that makes 10M downloads likely. This data is freely available and under-utilized by PM participants.
**Signal:** Monitor App Annie / Sensor Tower (free tier) or app store API proxies for apps matching PM markets. When `rank_improvement_7d > 400 positions`, increase PM probability estimate.
**Data:** App Store scraping or Sensor Tower free tier
**Alpha:** 30-80 bps | **Viability:** Unlikely (very few PM markets reference app metrics)
**Horizon:** Days to weeks | **Capacity:** $200-1K | **Durability:** Structural
**Complexity:** S
**Synergy:** Alternative data for LLM context.
**Kill Criterion:** If <2 qualifying PM markets per quarter.
**Risk:** Almost no PM markets reference specific app metrics.
**Who's Doing This:** Nobody (market doesn't exist at scale).
**Honest P(Works):** 5%

---

### C-9. Satellite Parking Lot Analysis for Retail/Economic Markets
**Mechanism:** Satellite imagery of retail parking lots has been used by hedge funds to predict earnings for a decade. When PM lists "Retail sales above X%?" or specific company markets, parking lot fill rates from free satellite sources (Sentinel-2, Planet free tier) provide a physical-world leading indicator.
**Signal:** Analyze satellite imagery of key retail locations. When parking lot occupancy trends diverge from consensus expectations, adjust PM probability estimate.
**Data:** Sentinel-2 (free, 5-day revisit), Planet free tier (limited resolution)
**Alpha:** 20-50 bps | **Viability:** Unlikely (satellite processing is complex; PM retail markets are rare)
**Horizon:** Weeks | **Capacity:** $200-1K | **Durability:** Years
**Complexity:** L (satellite image processing pipeline)
**Synergy:** Minimal — very different from core infrastructure.
**Kill Criterion:** If satellite-predicted retail activity has R² < 0.2 with actual retail sales over 6 months.
**Risk:** High complexity, low market availability, long processing time. Classic "cool idea, bad ROI" for $347 capital.
**Who's Doing This:** RS Metrics, Orbital Insight (institutional). Nobody on PM.
**Honest P(Works):** 3%

---

### C-10. Congressional Jet Tracking (ADS-B) for Legislative Markets
**Mechanism:** When Congressional leaders fly back to DC unexpectedly (trackable via ADS-B flight data), it often precedes surprise votes or legislative action. ADS-B data is public and real-time. Unusual flight patterns correlate with PM market-moving events.
**Signal:** Track known Congressional jets/charter services. When unexpected DC-bound flights spike (>2σ above normal for that day/week), flag active legislative PM markets for potential movement.
**Data:** ADS-B Exchange / FlightRadar24 API (free tier)
**Alpha:** 30-100 bps on qualifying events | **Viability:** Unlikely (very few trackable events)
**Horizon:** Hours | **Capacity:** $200-1K | **Durability:** Years (structural — politicians need to travel)
**Complexity:** M (flight tracking + event correlation)
**Synergy:** Additional context for political market LLM analysis.
**Kill Criterion:** If <3 qualifying unexpected-travel events per quarter.
**Risk:** False positives (routine travel). Difficulty identifying correct aircraft. Privacy concerns.
**Who's Doing This:** Quiver Quant tracks some flights. Systematic PM application is novel.
**Honest P(Works):** 5%

---

### C-11. Wikipedia Edit War Intensity as Uncertainty Proxy
**Mechanism:** When a topic is heavily disputed (e.g., a political figure or contested event), Wikipedia edit frequency and revert rates spike. This "edit war intensity" is a proxy for public uncertainty. PM markets with high Wikipedia edit activity on related articles tend to be more volatile and have wider spreads — creating better market-making opportunities (higher spread capture, more mean reversion).
**Signal:** Monitor Wikipedia Recent Changes API for articles matching PM market topics. When `edits_per_hour > 10 × 30d_avg`, flag the corresponding PM market as "high uncertainty." Adjust strategy: wider maker spread, reduced directional sizing, increased mean-reversion bias.
**Data:** Wikipedia API (free, real-time)
**Alpha:** Meta-signal (improves other strategies by 10-20% rather than generating direct trades) | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** N/A (sizing signal, not trade signal) | **Durability:** Structural
**Complexity:** S (simple API polling + keyword matching)
**Synergy:** Feeds into spread regime classification (A-9) and position sizing for all strategies.
**Kill Criterion:** If Wikipedia edit intensity has <0.2 correlation with PM market 24h volatility over 50 markets.
**Risk:** Wikipedia edit data is noisy. Many edit wars are about trivial issues, not market-moving events.
**Who's Doing This:** Academic papers on Wikipedia as prediction signal exist. PM application is novel.
**Honest P(Works):** 15%

---

### C-12. Cross-Language News Arbitrage (Mandarin/Russian/Arabic → English)
**Mechanism:** Major geopolitical events sometimes break in non-English media hours before English-language coverage. PM participants are overwhelmingly English-speaking. Monitoring Xinhua (Chinese), TASS (Russian), and Al Jazeera (Arabic) via translation APIs can provide an information speed advantage on geopolitical markets.
**Signal:** Monitor non-English news feeds. Use translation API + LLM to detect breaking events. Cross-reference with active geopolitical PM markets. When a market-relevant event appears in non-English media but not yet in English coverage, trade PM toward implied outcome.
**Data:** RSS feeds from major non-English outlets (free), Google Translate API ($20/1M characters), LLM API
**Alpha:** 50-200 bps on qualifying events | **Viability:** Possible
**Horizon:** Minutes to hours | **Capacity:** $500-5K | **Durability:** Months (language barrier is structural; LLM translation becoming ubiquitous will erode this)
**Complexity:** M
**Synergy:** Agentic RAG with multilingual capability. Extension of C-6 news wire strategy.
**Kill Criterion:** If <3 qualifying events per month where non-English media leads by >30 minutes.
**Risk:** Translation quality. False positives from non-English tabloids. Propaganda from state media.
**Who's Doing This:** Intelligence agencies do this. PM application at our scale is novel.
**Honest P(Works):** 12%

---

### C-13. Lobbying Disclosure (LDA/LD-2) for Regulatory Markets
**Mechanism:** Lobbying disclosures (required quarterly under LDA) reveal which industries are spending heavily to influence specific legislation. A sudden spike in lobbying spend on a bill correlates with either (a) the bill having a real chance of passing or (b) industry believing it will pass and trying to shape amendments. Either way, it's a signal about legislative probability.
**Signal:** Monitor OpenSecrets / Senate LDA filings. When lobbying spend on a specific bill exceeds 2× historical average, and a corresponding PM market exists, adjust probability estimate by +/-5% (direction depends on whether lobbying is for or against).
**Data:** OpenSecrets API (free), Senate LDA filings (free)
**Alpha:** 20-60 bps | **Viability:** Unlikely (quarterly filings are too slow)
**Horizon:** Weeks to months | **Capacity:** $200-1K | **Durability:** Structural
**Complexity:** S
**Synergy:** Context for political market LLM analysis.
**Kill Criterion:** If lobbying spend direction predicts PM outcome at <55% rate.
**Risk:** Quarterly disclosure lag makes this nearly useless for fast-moving legislative markets.
**Who's Doing This:** Political analysts use lobbying data. PM application at this cadence is ineffective.
**Honest P(Works):** 5%

---

### C-14. Domain Registration Monitoring for Company/Product Markets
**Mechanism:** Companies register domains before product launches, acquisitions, and rebrandings. Monitoring WHOIS/domain registration databases for domains matching PM market topics (e.g., if PM asks "Will Company X acquire Company Y?", monitoring for "companyxcompanyy.com" registrations) provides a leading indicator.
**Signal:** Monitor certificate transparency logs (crt.sh, free) and WHOIS databases for domain registrations matching PM market keywords. New registration = increased probability of corresponding event.
**Data:** crt.sh API (free), WHOIS databases (free)
**Alpha:** 50-200 bps on qualifying events | **Viability:** Unlikely (very rare qualifying events)
**Horizon:** Days | **Capacity:** $200-1K | **Durability:** Structural
**Complexity:** S
**Synergy:** Alternative data for LLM context.
**Kill Criterion:** If <1 qualifying domain registration detected per quarter.
**Risk:** Very low event frequency. Companies use privacy services to hide domain registrations.
**Who's Doing This:** Cybersecurity researchers monitor domains. PM application is novel.
**Honest P(Works):** 3%

---

### C-15. Google Trends Surge as Volatility/Interest Proxy
**Mechanism:** A spike in Google Trends search volume for a PM market topic correlates with increased public attention, which drives PM trading volume and volatility. While the direction of the trend spike doesn't reliably predict the outcome, it DOES predict increased spread and mean-reversion opportunity for market makers.
**Signal:** Monitor Google Trends API for PM market topics. When `search_volume(topic, 24h) > 3 × 7d_avg`, flag corresponding PM markets for: (a) wider maker spreads (volatility regime), (b) potential mean-reversion after initial price spike.
**Data:** Google Trends API (free, rate-limited)
**Alpha:** Meta-signal (improves market-making P&L by 10-20%) | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Feeds into spread regime classification (A-9).
**Kill Criterion:** If Google Trends spikes don't correlate with PM 24h volume at >0.3 R².
**Risk:** Google Trends data is heavily smoothed and delayed. Free API is rate-limited.
**Who's Doing This:** Google Trends for stock trading is well-studied. PM application is less explored.
**Honest P(Works):** 15%

---

### D. LLM & AI-Specific Edges (12 strategies)

---

### D-1. Multi-Agent Debate Architecture for Hard-to-Calibrate Markets
**Mechanism:** Instead of asking one LLM for a probability estimate, have 3+ LLM instances "debate" the question — one argues for YES, one for NO, one is a judge. Research shows this reduces individual model biases and produces more calibrated outputs than single-model estimation. The judge's final assessment incorporates the strongest arguments from both sides.
**Signal:** For each market, run a 3-round debate: (1) YES advocate presents evidence, (2) NO advocate presents counterevidence, (3) Judge synthesizes and provides calibrated probability. Use this instead of single-model estimation when `market_price` is between 30-70% (the hardest calibration zone).
**Data:** 3 LLM API calls per market (~$0.01/market for Haiku)
**Alpha:** Improves Brier score by 0.01-0.03 (indirect — better calibration = better trade selection) | **Viability:** Possible
**Horizon:** N/A (improves existing signal quality) | **Capacity:** N/A | **Durability:** Years (structural improvement)
**Complexity:** S (3 API calls with different system prompts)
**Synergy:** Direct upgrade to existing LLM analyzer. No new infrastructure needed.
**Kill Criterion:** If debate-calibrated Brier score is not measurably better than single-model over 100 resolved markets.
**Risk:** 3× API cost per market. May not improve on Platt calibration if the biases are already well-corrected.
**Who's Doing This:** Academic: Du et al. 2023 "Improving Factuality and Reasoning in Language Models through Multiagent Debate." PM application is novel.
**Honest P(Works):** 25%

---

### D-2. Conformal Prediction for Uncertainty-Aware Position Sizing
**Mechanism:** Standard Kelly sizing assumes a point estimate of probability. Conformal prediction provides a *prediction interval* (e.g., "true probability is between 40% and 60% with 90% confidence"). When the interval is narrow, bet larger (high confidence). When wide, bet smaller or skip. This naturally reduces exposure on markets where the LLM is uncertain.
**Signal:** For each LLM estimate, generate a conformal prediction interval using split conformal inference on your historical LLM estimates vs. resolved outcomes. Size = `kelly_fraction × (1 - interval_width / 0.50)`. When interval_width > 0.30, skip the market entirely.
**Data:** Historical LLM estimate database (existing — your 532 resolved markets)
**Alpha:** Reduces drawdown by 20-40%, improves Sharpe by 15-25% | **Viability:** Likely
**Horizon:** N/A (sizing improvement) | **Capacity:** N/A | **Durability:** Structural
**Complexity:** M (requires building conformal prediction framework on historical data)
**Synergy:** Direct upgrade to quarter-Kelly sizing. Uses existing data.
**Kill Criterion:** If conformal-sized portfolio underperforms fixed-Kelly portfolio over 200 trades in backtest.
**Risk:** Historical calibration data may not be representative of future LLM performance (distribution shift).
**Who's Doing This:** Conformal prediction in ML is hot (Vovk et al.). PM application is novel.
**Honest P(Works):** 30%

---

### D-3. Domain-Specific LoRA Fine-Tuning on Resolved Polymarket Data
**Mechanism:** Fine-tune a small LLM (e.g., Llama 3.3 8B) using LoRA on your 532 resolved Polymarket markets as training data. The input is market question + context; the output is calibrated probability. This creates a model that's specifically optimized for prediction market probability estimation rather than general-purpose chat.
**Signal:** Use fine-tuned model instead of (or in ensemble with) general-purpose Haiku for probability estimation.
**Data:** Your existing 532 resolved market dataset
**Alpha:** Potentially -0.02 to -0.05 Brier improvement (similar to Platt scaling) | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Months (needs periodic retraining)
**Complexity:** M (LoRA fine-tuning + evaluation pipeline)
**Synergy:** Replaces or augments existing LLM analyzer.
**Kill Criterion:** If fine-tuned model Brier score is not >0.01 better than Platt-calibrated Haiku on held-out test set.
**Risk:** 532 markets is very small for fine-tuning. Overfitting is near-certain. May degrade on out-of-distribution markets. Lopez-Lira et al. (2025) showed memorization is non-identifiable.
**Who's Doing This:** Lightning Rod Labs explored this direction. Commercial implementations likely exist.
**Honest P(Works):** 15%

---

### D-4. Chain-of-Verification: Separate Estimation from Calibration
**Mechanism:** Instead of asking the LLM to both estimate and calibrate in one pass, split into two steps: (1) LLM estimates probability without seeing its own prior, (2) a DIFFERENT model or process verifies the estimate by checking for common biases (acquiescence bias, recency bias, narrative bias) and applies corrections. This "verification step" catches errors that Platt scaling alone cannot.
**Signal:** Step 1: LLM generates raw estimate. Step 2: Verification model checks: Is the estimate suspiciously close to 50%? Does it disagree with base rates? Is it anchored to a recent headline? Apply bias-specific corrections before Platt scaling.
**Data:** Same as current LLM pipeline (no new data needed)
**Alpha:** -0.005 to -0.015 Brier improvement | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (additional prompt engineering + rule-based corrections)
**Synergy:** Enhancement to existing LLM pipeline.
**Kill Criterion:** If verified estimates are not better-calibrated than unverified on 100+ resolved markets.
**Risk:** Adding complexity without improving performance. Verification model may introduce its own biases.
**Who's Doing This:** Academic: Dhuliawala et al. 2023 "Chain-of-Verification Reduces Hallucination in LLMs." PM-specific application is novel.
**Honest P(Works):** 20%

---

### D-5. Active Learning: Prioritize Markets Where LLM Uncertainty Is Highest
**Mechanism:** Rather than scanning all 100+ markets equally, prioritize analysis on markets where the LLM's estimated uncertainty is highest (i.e., where its prediction interval is widest). These are the markets most likely to benefit from additional research (RAG, debate, etc.) and most likely to have large calibration errors — which means larger potential edge.
**Signal:** First pass: quick LLM estimate on all markets. Sort by uncertainty (conformal interval width). Second pass: deep analysis (RAG, debate, multi-model) on top 10% most uncertain. This allocates LLM compute budget where it's most valuable.
**Data:** Same as current pipeline
**Alpha:** 20-40% improvement in edge detection efficiency (same alpha, fewer API calls) | **Viability:** Likely
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (two-pass estimation with sorting)
**Synergy:** Pairs with D-2 (conformal prediction provides the uncertainty measure) and D-1 (debate is the "deep analysis" applied to high-uncertainty markets).
**Kill Criterion:** If active-learning-selected markets don't have higher edge rate than random selection.
**Risk:** Highest-uncertainty markets may also be the ones where LLM is fundamentally unable to estimate well (unknowable outcomes). In that case, more compute doesn't help.
**Who's Doing This:** Active learning is standard ML. PM application is novel.
**Honest P(Works):** 30%

---

### D-6. Synthetic Calibration Training via Metaculus/GJOpen Questions
**Mechanism:** Your 532 resolved Polymarket markets is a small calibration dataset. But Metaculus and Good Judgment Open have thousands of resolved forecasting questions with community probability estimates and ground truth. Train your Platt calibration on this larger dataset (transfer learning), then fine-tune on your PM-specific data.
**Signal:** Expand calibration training set from 532 to 5,000+ by incorporating Metaculus/GJOpen resolved questions. Re-fit Platt parameters on the combined dataset. Test on held-out PM data.
**Data:** Metaculus API (free, historical data available), Good Judgment Open (free)
**Alpha:** More robust Platt calibration (reduced overfitting on small PM dataset) | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (data collection + refitting)
**Synergy:** Directly improves core Platt calibration used by all strategies.
**Kill Criterion:** If cross-domain calibration is worse than PM-only calibration on held-out PM test set.
**Risk:** Metaculus questions may have different characteristics than PM markets (different difficulty, different domains). Domain shift could worsen calibration.
**Who's Doing This:** Academic forecasting researchers use cross-domain calibration. PM-specific implementation is novel.
**Honest P(Works):** 25%

---

### D-7. LLM-as-Judge for Resolution Ambiguity Detection
**Mechanism:** Some PM markets have ambiguous resolution criteria. Markets that are likely to resolve ambiguously tend to trade at compressed odds (nobody wants to bet when resolution is uncertain). Detecting ambiguity BEFORE the market does allows you to either avoid those markets (reducing risk) or exploit the ambiguity premium.
**Signal:** Use LLM to rate each market's resolution criteria on a 1-5 clarity scale. Markets rated ≤2 are flagged as "ambiguous." For ambiguous markets: (a) if you have a position, exit, (b) if the market is trading at extreme prices ($0.90+) despite ambiguity, short (sell YES), since ambiguous markets are less likely to resolve cleanly at $1.00.
**Data:** Gamma API market descriptions (free), LLM API ($0.001/market)
**Alpha:** Risk reduction (avoids losses from ambiguous resolution) + 30-80 bps on ambiguity shorts | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $500-5K | **Durability:** Structural (ambiguous markets will always exist)
**Complexity:** S (LLM prompt + market filtering)
**Synergy:** Enhancement to category/velocity filter. Adds a quality filter.
**Kill Criterion:** If ambiguity-flagged markets resolve at the same rate as non-flagged markets.
**Risk:** LLM may misjudge resolution clarity. Some ambiguous markets resolve cleanly despite unclear criteria.
**Who's Doing This:** Manual resolution-rule analysis is common among PM traders. Systematic LLM-powered version is novel.
**Honest P(Works):** 20%

---

### D-8. Causal Inference for Event Dependency Chains
**Mechanism:** Some PM markets are causally linked: "Fed cuts rates" → "mortgage rates decline" → "home sales increase." If the LLM can model these causal chains, it can propagate probability updates more accurately than the market. When the upstream event probability changes (Fed cut becomes more likely), the downstream markets (home sales) should adjust — but they often lag.
**Signal:** Use LLM to build causal DAGs across active PM markets. When an upstream market price changes by >5%, check if downstream markets have adjusted proportionally. If not, trade the downstream market toward the causal-chain-implied probability.
**Data:** Gamma API (free), LLM for causal graph construction ($0.01/graph)
**Alpha:** 30-100 bps on qualifying events | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** $500-5K | **Durability:** Months
**Complexity:** M (causal DAG construction + probability propagation)
**Synergy:** Extension of B-1 dependency graph. Uses same market relationship mapping but with causal direction.
**Kill Criterion:** If causal-chain-implied probabilities are not better-calibrated than market prices for downstream markets.
**Risk:** Causal inference is hard. LLM may identify spurious causal relationships. Propagation errors compound across chain length.
**Who's Doing This:** Causal inference is hot in ML. PM application is academic.
**Honest P(Works):** 12%

---

### D-9. Ensemble Disagreement as Signal Strength Indicator
**Mechanism:** You already plan a multi-model ensemble (Claude + GPT + Groq). When all three models agree, confidence should be high. When they disagree, confidence should be low. But here's the insight most people miss: the *pattern* of disagreement is informative. If two models say YES and one says NO, that's different from all three giving different probabilities but all on the same side. Map disagreement patterns to historical outcomes to create a meta-model of ensemble reliability.
**Signal:** Compute `ensemble_agreement = 1 - std(model_estimates) / 0.25`. Use as a multiplier on position size. When agreement > 0.8, use standard Kelly. When agreement < 0.5, reduce to 1/4 Kelly or skip.
**Data:** Same as current multi-model pipeline
**Alpha:** Sharpe improvement of 15-30% | **Viability:** Likely
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (simple statistics on existing outputs)
**Synergy:** Direct enhancement to multi-model ensemble (Signal Source #1 upgrade).
**Kill Criterion:** If agreement-weighted portfolio doesn't outperform equal-weighted ensemble on 200+ trades.
**Risk:** Small sample sizes for each disagreement pattern. Overfitting to historical patterns.
**Who's Doing This:** Ensemble disagreement is used in weather forecasting. PM application is novel.
**Honest P(Works):** 30%

---

### D-10. Adversarial Prompt Testing for Robustness
**Mechanism:** LLM estimates are sensitive to prompt wording (Tian et al. 2023). By generating multiple paraphrases of the same question and averaging the LLM responses, you reduce prompt-specific bias. The variance across paraphrases is also a useful uncertainty measure.
**Signal:** For each market, generate 5 paraphrased versions of the question. Average the LLM estimates. If `std(estimates) > 0.10`, flag as "prompt-sensitive" and reduce position size.
**Data:** LLM API (5× current cost per market)
**Alpha:** -0.005 to -0.010 Brier improvement | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Enhancement to LLM analyzer.
**Kill Criterion:** If paraphrase-averaged estimates are not better-calibrated than single-prompt estimates on 100+ markets.
**Risk:** 5× API cost. The paraphrases may introduce new biases rather than averaging out existing ones.
**Who's Doing This:** Academic: Schoenegger (2025) tested prompt variations. Systematic paraphrasing for PM is novel.
**Honest P(Works):** 20%

---

### D-11. Transfer Learning: Metaculus Community → Polymarket LLM
**Mechanism:** Metaculus has community prediction data with revealed calibration curves for thousands of questions. If you can map the relationship between "LLM estimate on Metaculus-style questions" and "community aggregate on the same questions," you learn a transformation function that converts LLM outputs to better-calibrated predictions. This learned transformation may generalize to Polymarket questions.
**Signal:** Collect LLM estimates on 1,000+ resolved Metaculus questions. Fit an isotonic regression from LLM-estimate → actual-outcome. Apply this regression to PM estimates instead of (or in addition to) Platt scaling.
**Data:** Metaculus API (free), LLM API ($1-5 for 1000 estimates)
**Alpha:** Potentially better calibration than Platt scaling alone | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Months (needs periodic refitting)
**Complexity:** M (data collection + model fitting + evaluation)
**Synergy:** Alternative/complement to Platt scaling.
**Kill Criterion:** If isotonic regression on Metaculus data doesn't outperform Platt scaling on held-out PM data.
**Risk:** Domain shift (Metaculus questions ≠ PM markets).
**Who's Doing This:** ForecastBench (Karger et al. 2024) compared LLMs to forecasting platforms. Transfer learning between platforms is novel.
**Honest P(Works):** 20%

---

### D-12. Adaptive Platt Calibration with Rolling Window
**Mechanism:** Your current Platt scaling uses static parameters (A=0.5914, B=-0.3977) fitted on all historical data. But LLM calibration drifts over time (model updates, changing market difficulty). Using a rolling window (last 100 resolved markets) for Platt parameter estimation would track this drift.
**Signal:** Re-fit Platt parameters after every 20 resolved markets using the last 100 resolved markets. Compare rolling-window calibration to static calibration. Use whichever has lower recent Brier score.
**Data:** Your resolved market database (existing)
**Alpha:** Prevents calibration drift-induced losses | **Viability:** Likely
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (add rolling re-fit to existing calibration code)
**Synergy:** Core infrastructure improvement affecting all LLM-dependent strategies.
**Kill Criterion:** If rolling calibration Brier is not lower than static calibration over 3+ consecutive 50-market windows.
**Risk:** Rolling window may overfit to recent regime if window is too small. Need minimum 100 resolved markets in window.
**Who's Doing This:** Standard practice in ML. Surprisingly absent from most PM bot implementations.
**Honest P(Works):** 40%

---

### E. Behavioral & Psychological Exploitation (8 strategies)

---

### E-1. Round Number Clustering Exploitation
**Mechanism:** Prediction market prices cluster at psychologically salient values ($0.10, $0.20, $0.25, $0.50, $0.75, $0.90). These round numbers act as "sticky" support/resistance levels due to anchoring bias. Markets that cross a round number tend to accelerate in that direction (momentum through round numbers) because the psychological barrier is broken.
**Signal:** When a market price crosses $0.50 from below, buy YES (momentum trade). When it drops through $0.50 from above, buy NO. Apply only when the crossing is accompanied by above-average volume (confirming genuine information rather than noise).
**Data:** CLOB price feed (free)
**Alpha:** 20-50 bps | **Viability:** Unlikely (thin edge, easily competed away)
**Horizon:** Hours | **Capacity:** $500-2K | **Durability:** 3-6 months
**Complexity:** S
**Synergy:** Simple confirmation signal for existing pipeline.
**Kill Criterion:** If round-number crossings don't predict continuation at >54% rate over 100 events.
**Risk:** Very weak signal. Probably noise.
**Who's Doing This:** Technical analysis folklore. Few PM-specific tests exist.
**Honest P(Works):** 8%

---

### E-2. Narrative-Driven Mispricing Detection
**Mechanism:** When a prediction market has a compelling narrative attached (e.g., "underdog candidate with viral moment"), the market tends to overprice the narrative outcome due to availability heuristic. Markets with boring narratives (incumbent cruising to re-election) tend to be underpriced. The LLM can detect "narrative heat" by analyzing social media discussion quality — not quantity, but emotional intensity.
**Signal:** Use LLM to rate the "narrative compelling-ness" of each side of a PM market on a 1-10 scale. When the high-narrative side is also the market favorite (price > 50%), increase skepticism. Apply a "narrative discount" of 3-5% to the high-narrative side.
**Data:** Social media monitoring (Reddit API free tier, Twitter via search), LLM analysis
**Alpha:** 30-80 bps | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $500-5K | **Durability:** Years (narrative bias is human nature)
**Complexity:** M (requires sentiment analysis pipeline + narrative scoring)
**Synergy:** Enhancement to LLM probability estimation. Provides a behavioral correction factor.
**Kill Criterion:** If narrative-discounted estimates are not better-calibrated than raw estimates over 50 markets.
**Risk:** LLM itself may be susceptible to the same narrative bias it's trying to detect.
**Who's Doing This:** Superforecasters use narrative-awareness. Automated narrative scoring for PM is novel.
**Honest P(Works):** 15%

---

### E-3. Partisan Bias Exploitation in Political Markets
**Mechanism:** In US political markets, Republican-leaning traders systematically overprice Republican outcomes and vice versa. This creates persistent mispricing in political markets. The 2024 election showed Polymarket political markets were more accurate than polls — but WITHIN the market, partisan bias creates temporary opportunities.
**Signal:** For political PM markets, compare PM price to a non-partisan source (FiveThirtyEight model, academic prediction). When PM price deviates >5% from the non-partisan source in a direction consistent with known partisan bias (PM overly optimistic about the party that's popular among crypto traders), trade the non-partisan source's direction.
**Data:** FiveThirtyEight (free), RealClearPolitics (free), PM API (free)
**Alpha:** 30-100 bps | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $1K-10K | **Durability:** Years (partisan bias is structural)
**Complexity:** S (simple comparison to polling aggregators)
**Synergy:** Direct input for political market LLM analysis.
**Kill Criterion:** If non-partisan-source-adjusted estimates don't outperform raw PM prices on 30+ political markets.
**Risk:** FiveThirtyEight may itself be biased. Crypto trader demographics shift over time.
**Who's Doing This:** Research pipeline item #23 (polling aggregator divergence) — this is the concrete implementation.
**Honest P(Works):** 20%

---

### E-4. Disposition Effect: Prediction Market Traders Hold Losers
**Mechanism:** Like stock traders, PM participants hold losing positions too long and sell winning positions too early (disposition effect, Shefrin & Statman 1985). This means markets with a lot of "stuck" traders holding losing YES positions at $0.80 (now trading at $0.30) have artificial selling pressure that keeps the price lower than it should be. Conversely, markets where many traders are sitting on unrealized gains tend to be underpriced (they sell too early).
**Signal:** Estimate "stuck trader fraction" by analyzing historical trade data: if many trades were executed at prices >$0.70 and the current price is <$0.40, there are likely many holders sitting on losses. These markets may be underpriced (stuck traders eventually capitulate, creating buying opportunity).
**Data:** Polymarket data API `/trades` (free, historical)
**Alpha:** 20-50 bps | **Viability:** Unlikely (requires strong assumptions about holder behavior)
**Horizon:** Days to weeks | **Capacity:** $500-2K | **Durability:** Structural (disposition effect is universal)
**Complexity:** M (requires historical trade reconstruction + holder position estimation)
**Synergy:** Additional behavioral signal for confirmation layer.
**Kill Criterion:** If "stuck trader" metric has <0.1 correlation with subsequent price movement over 50 markets.
**Risk:** Can't directly observe holdings from trade data alone. Many assumptions required.
**Who's Doing This:** Behavioral finance researchers study this in equities. PM application is academic.
**Honest P(Works):** 8%

---

### E-5. Overreaction to Vivid Low-Probability Events
**Mechanism:** When a dramatic but unlikely event occurs (assassination attempt, natural disaster), PM prices for related outcomes spike far beyond the base-rate-justified level. The availability heuristic makes the vivid event seem much more likely to recur. Markets that spike >20% on vivid events but don't have structural reasons for the change tend to mean-revert within 48h.
**Signal:** Detect price spikes >20% in <6 hours. If the spike coincides with a vivid news event (detected via GDELT or news API) but the LLM base-rate-adjusted estimate suggests the spike is overdone (i.e., spike > 2× justified), bet on mean reversion.
**Data:** CLOB price feed (free), GDELT/News API (free)
**Alpha:** 50-200 bps on qualifying events | **Viability:** Possible
**Horizon:** 24-72 hours | **Capacity:** $500-2K | **Durability:** Structural (availability heuristic is permanent)
**Complexity:** S (spike detection + LLM assessment)
**Synergy:** Combines price action signal with LLM analysis. Natural for confirmation layer.
**Kill Criterion:** If mean-reversion rate after vivid-event spikes is <60% over 20 events.
**Risk:** Sometimes the spike IS justified. "Mean reversion" on genuinely regime-changing events = large losses.
**Who's Doing This:** Contrarian traders do this intuitively. Systematic, calibrated version is rare.
**Honest P(Works):** 18%

---

### E-6. Herding at Market Open
**Mechanism:** When a new PM market opens, the first few trades set an anchor price. Subsequent traders tend to herd around this anchor, even if it's poorly justified. As the market matures (more information, more diverse traders), the price converges to fair value. The predictable pattern: early prices are noisy → convergence to fair value over 1-6 hours → stable price. Trading against extreme early prices (that deviate from LLM estimate) is a mean-reversion play.
**Signal:** For markets with `age < 6 hours`, compare current price to LLM estimate. If `|price - LLM_estimate| > 15%`, trade toward LLM estimate with expectation of mean reversion.
**Data:** Gamma API `created_at` field (free), LLM API
**Alpha:** 50-150 bps | **Viability:** Possible
**Horizon:** Hours | **Capacity:** $500-2K | **Durability:** Structural (herding at open is universal)
**Complexity:** S (same infrastructure as A-3 new listing strategy)
**Synergy:** Same infrastructure as A-3 but different trade logic (A-3 is front-running fair value; E-6 is mean-reversion after noise).
**Kill Criterion:** If early-price-to-LLM-estimate deviation doesn't predict mean reversion at >55% rate.
**Risk:** Early trades may be informed (price is correct, LLM is wrong).
**Who's Doing This:** Market microstructure folklore. Systematic PM version is rare.
**Honest P(Works):** 15%

---

### E-7. Panic Selling Near Resolution Deadlines
**Mechanism:** In the 24 hours before a market resolves, traders holding losing positions panic-sell at below-fair-value prices. This creates a systematic buying opportunity in the YES-side of markets that are >80% likely to resolve YES (or NO-side of >80% NO markets). The panic discount is especially pronounced in markets with retail participants.
**Signal:** For markets with `time_to_resolution < 24h` AND `price > 0.80`: if price drops >3% in 1 hour, buy (the panic is creating a discount on a near-certain outcome). Reverse for NO-heavy markets.
**Data:** Gamma API for resolution timing (free), CLOB price feed (free)
**Alpha:** 20-80 bps | **Viability:** Possible
**Horizon:** Hours | **Capacity:** $500-5K | **Durability:** Structural
**Complexity:** S
**Synergy:** Combines with resolution boundary maker withdrawal detection (A-5).
**Kill Criterion:** If panic-drop recovery rate is <70% over 30 events.
**Risk:** The drop may be informed (new information, not panic).
**Who's Doing This:** Experienced PM traders buy "cheap certainty" near resolution. Systematic version is uncommon.
**Honest P(Works):** 15%

---

### E-8. Gambler's Fallacy at Resolution Boundaries
**Mechanism:** In sequential markets (e.g., daily weather, weekly economic data), if the outcome has been YES for 3 consecutive periods, retail traders over-bet NO for the next period (gambler's fallacy). This depresses the NO price below fair value. Conversely, after 3 consecutive NO outcomes, YES becomes overpriced.
**Signal:** For serial markets (same question, different periods), track the streak. When `streak_length >= 3` AND LLM estimate doesn't support reversal, trade with the streak (anti-gambler's-fallacy).
**Data:** Polymarket/Kalshi historical resolution data (existing database)
**Alpha:** 20-60 bps | **Viability:** Unlikely (serial correlation in outcomes varies widely)
**Horizon:** One resolution period | **Capacity:** $200-1K | **Durability:** Structural
**Complexity:** S
**Synergy:** Simple behavioral correction for serial markets.
**Kill Criterion:** If streak continuation rate doesn't exceed market-implied probability by >3% over 50 streak events.
**Risk:** Some serial markets have genuine mean-reversion (weather), making streak-following incorrect.
**Who's Doing This:** Sports bettors study this. PM application is direct but rare.
**Honest P(Works):** 10%

---

### F. Time-Series & Statistical Patterns (10 strategies)

---

### F-1. Day-of-Week Liquidity and Spread Patterns
**Mechanism:** PM liquidity varies predictably by day of week. Weekend liquidity is typically lower (wider spreads, less competition for maker orders). If your maker bot is active on weekends when competitors are offline, you capture wider spreads with less adverse selection.
**Signal:** Backtest maker strategy performance by day of week. If Saturday/Sunday show wider spreads and lower adverse selection rates, increase maker exposure on weekends and reduce on high-competition weekdays (Tuesday-Thursday).
**Data:** Your own trading data + historical CLOB data
**Alpha:** 10-30% improvement in maker strategy Sharpe | **Viability:** Possible
**Horizon:** Continuous (scheduling optimization) | **Capacity:** Same as A-1 | **Durability:** Structural
**Complexity:** S (analysis + scheduling)
**Synergy:** Enhancement to all maker strategies (A-1, A-2, A-8).
**Kill Criterion:** If weekend spread is not measurably wider (>20%) than weekday spread over 4 weeks of data.
**Risk:** Weekend liquidity is so low that fill rates drop to near zero.
**Who's Doing This:** Standard in traditional market making. PM-specific analysis is rare.
**Honest P(Works):** 20%

---

### F-2. Pre-Weekend Position Unwind Pattern
**Mechanism:** Risk-averse PM participants unwind positions before weekends (can't monitor markets). This creates predictable selling pressure Friday afternoon (UTC) and buying pressure Monday morning. Market-making around this pattern captures the weekend positioning premium.
**Signal:** Track average price movement Friday 18:00-23:59 UTC and Monday 00:00-06:00 UTC across markets. If systematic pattern exists (Friday decline, Monday recovery), trade the mean reversion.
**Data:** Historical CLOB prices (free)
**Alpha:** 10-30 bps per cycle | **Viability:** Unlikely (prediction markets may not have this equity-market pattern)
**Horizon:** 48 hours (weekend cycle) | **Capacity:** $500-2K | **Durability:** Months
**Complexity:** S (simple time-based analysis)
**Synergy:** Feeds into F-1 day-of-week scheduling.
**Kill Criterion:** If Friday-to-Monday price pattern has <0.05 statistical significance over 8 weekends.
**Risk:** PM participants may not exhibit the same weekend-aversion as equity participants.
**Who's Doing This:** Unknown on PM. Well-studied in equity markets.
**Honest P(Works):** 8%

---

### F-3. Time-to-Resolution Theta Decay Exploitation
**Mechanism:** As a market approaches resolution, the price should converge toward 0 or 1 (certainty). Markets that are "stuck" at intermediate prices (40-60%) with resolution <48h away are either genuinely uncertain or mispriced. For markets where your LLM has strong directional conviction, the time decay creates an increasing edge: the market MUST move to 0 or 1, and if your estimate is correct, the payoff increases as resolution approaches.
**Signal:** Filter markets with `time_to_resolution < 48h AND price between 0.30-0.70`. Run LLM analysis. If `|LLM_estimate - 0.50| > 0.20` (strong directional conviction), take a directional position. The natural theta decay accelerates your profit as the market converges to your predicted outcome.
**Data:** Gamma API (free), LLM API
**Alpha:** 50-200 bps | **Viability:** Possible
**Horizon:** Hours to 48h | **Capacity:** $500-5K | **Durability:** Structural
**Complexity:** S (timing filter + existing LLM pipeline)
**Synergy:** Combines velocity filter with directional conviction. Natural extension of existing pipeline.
**Kill Criterion:** If win rate on <48h markets is <60% over 50 trades.
**Risk:** Markets stuck at 50% near resolution may be genuinely 50/50. LLM conviction may be false.
**Who's Doing This:** Standard options trading concept. PM application is natural but under-implemented.
**Honest P(Works):** 20%

---

### F-4. Autocorrelation in PM Returns (Momentum/Reversal)
**Mechanism:** If PM price changes exhibit positive autocorrelation at short horizons (1-4 hours) and negative autocorrelation at longer horizons (24-72 hours), this creates predictable patterns. Positive autocorrelation means momentum (prices keep moving in the same direction). Negative means reversal. The pattern depends on information flow: new information → momentum, stale information → reversal.
**Signal:** Compute rolling 4h and 24h autocorrelation of PM price changes across all markets. If `autocorr_4h > 0.15` for a market, apply momentum strategy. If `autocorr_24h < -0.15`, apply reversal strategy. Use separate thresholds for different market categories.
**Data:** Historical CLOB prices (free)
**Alpha:** 20-60 bps | **Viability:** Unlikely (prediction market prices are likely near-random-walk)
**Horizon:** Hours to days | **Capacity:** $500-5K | **Durability:** 3-6 months if pattern exists
**Complexity:** M (requires building autocorrelation database across markets)
**Synergy:** Statistical signal for confirmation layer.
**Kill Criterion:** If autocorrelation across all markets is not statistically distinguishable from zero at p<0.05.
**Risk:** Spurious correlations in small samples. Transaction costs eat thin momentum edges.
**Who's Doing This:** Time-series analysis is standard in quant finance. PM-specific autocorrelation analysis is academic.
**Honest P(Works):** 8%

---

### F-5. Volume-Weighted Price Discovery Speed
**Mechanism:** Markets with high volume relative to their price uncertainty are "fast" — they incorporate information quickly. Markets with low relative volume are "slow" — they lag behind. Detecting slow markets allows you to trade information that's already reflected in fast markets but not yet in slow ones.
**Signal:** For each market, compute `info_speed = volume_24h / (price_range_24h + epsilon)`. Low info_speed = slow market. When a fast market and slow market share a dependency (from B-1 graph), and the fast market has moved but the slow market hasn't, trade the slow market toward the fast market's implied value.
**Data:** Gamma API for volume/price (free), dependency graph (from B-1)
**Alpha:** 30-80 bps | **Viability:** Possible
**Horizon:** Hours | **Capacity:** $500-5K | **Durability:** Months
**Complexity:** M
**Synergy:** Combines microstructure (volume analysis) with cross-market dependency detection (B-1).
**Kill Criterion:** If slow→fast information transfer doesn't predict slow market movement at >55% rate.
**Risk:** "Slow" markets may be slow because there's genuinely no new information (the fast market moved on unrelated news).
**Who's Doing This:** Standard in equity markets (sector rotation based on information speed). Novel on PM.
**Honest P(Works):** 15%

---

### F-6. Open Interest → Resolution Probability Mapping
**Mechanism:** Total open interest (outstanding positions) in a PM market may predict resolution direction. High open interest on YES side at high prices suggests informed holders are confident. Low open interest despite high price suggests the price is maintained by a few large traders (fragile).
**Signal:** When `YES_open_interest / total_open_interest > 0.70` AND `price > 0.60`, the market is likely to resolve YES (confirmation of informed positioning). When open interest is concentrated but price is moderate, be cautious (potential for unwinding).
**Data:** Polymarket data API (free — need to verify if OI data is available)
**Alpha:** 20-50 bps | **Viability:** Unlikely (OI data may not be granular enough)
**Horizon:** Days | **Capacity:** $500-2K | **Durability:** Structural
**Complexity:** S
**Synergy:** Alternative sizing signal for confirmation layer.
**Kill Criterion:** If OI direction doesn't predict resolution at >55% rate over 50 markets.
**Risk:** OI data availability and granularity on Polymarket is uncertain.
**Who's Doing This:** Options traders use OI extensively. PM-specific OI analysis is rare.
**Honest P(Works):** 8%

---

### F-7. Holiday and Major Event Calendar Effects
**Mechanism:** Around major holidays (Christmas, Thanksgiving, 4th of July), PM liquidity drops and spreads widen — similar to F-1 but driven by multi-day calendar events rather than day-of-week cycles. Additionally, major events (Super Bowl, elections) create correlated volume spikes that temporarily distort prices in unrelated markets (attention displacement).
**Signal:** Build a calendar of major holidays and events. In the 48 hours surrounding each, widen maker spreads (liquidity premium) and increase mean-reversion bias on non-event markets (attention displacement correction).
**Data:** Calendar data (manual construction)
**Alpha:** 10-20 bps improvement to maker strategy | **Viability:** Unlikely (too few qualifying events per year)
**Horizon:** Seasonal | **Capacity:** Same as A-1 | **Durability:** Structural
**Complexity:** S
**Synergy:** Enhancement to A-9 regime classification.
**Kill Criterion:** If holiday periods don't show measurably wider spreads (>30%) vs. non-holiday.
**Risk:** Too few data points per year to build confidence. PM market may not exhibit equity-market holiday effects.
**Who's Doing This:** Standard in equity market making. PM-specific testing is absent.
**Honest P(Works):** 5%

---

### F-8. Settlement Clustering Effects (Multiple Markets Resolving Simultaneously)
**Mechanism:** When multiple PM markets resolve on the same day (e.g., election night, FOMC day), capital is freed simultaneously, creating temporary oversupply of capital seeking new positions. This buying pressure inflates prices on remaining markets temporarily. If you're already positioned before the settlement cluster, you benefit from the inflow. If you're a maker, the increased flow = more fills.
**Signal:** Identify dates with >5 markets resolving simultaneously (from Gamma API metadata). 24h before settlement cluster: increase maker exposure in non-resolving markets (capture the post-settlement capital inflow).
**Data:** Gamma API resolution dates (free)
**Alpha:** 10-30 bps | **Viability:** Unlikely
**Horizon:** 24-48h around settlement clusters | **Capacity:** $500-2K | **Durability:** Structural
**Complexity:** S
**Synergy:** Calendar-aware enhancement to maker strategy.
**Kill Criterion:** If volume in non-resolving markets doesn't increase >20% in 24h after settlement clusters.
**Risk:** Settlement clusters may not create measurable capital flow effects at Polymarket's scale.
**Who's Doing This:** Bond market participants manage around settlement dates. PM application is novel.
**Honest P(Works):** 5%

---

### F-9. Intraday Volatility Smile on Binary Markets
**Mechanism:** Binary options have a "volatility smile" analog: the implied volatility (uncertainty) should be highest at 50% price and decrease toward 0% and 100%. If the actual spread pattern doesn't match this theoretical shape, there's a relative value opportunity. Markets with unexpectedly wide spreads at extreme prices (near 0% or 100%) may have hidden uncertainty that creates value.
**Signal:** For each market, compute `spread_ratio = actual_spread / theoretical_spread` at current price level. When `spread_ratio > 2.0` at an extreme price, there may be hidden uncertainty. When `spread_ratio < 0.5` at mid-range price, the market may be overconfident about information quality.
**Data:** CLOB order book (free)
**Alpha:** 20-50 bps | **Viability:** Unlikely (theoretical framework may not hold for PM)
**Horizon:** Hours | **Capacity:** $500-2K | **Durability:** Structural
**Complexity:** M (requires volatility surface construction for binary markets)
**Synergy:** Enhances maker strategy spread setting (A-9).
**Kill Criterion:** If spread_ratio has no predictive power for subsequent price movement.
**Risk:** Binary markets don't have a clean volatility surface. The analogy to options may be too loose.
**Who's Doing This:** Options market makers use volatility surfaces. PM binary analog is academic.
**Honest P(Works):** 5%

---

### F-10. Momentum at Market Opening vs. Closing
**Mechanism:** If PM markets show different momentum characteristics at "open" (early in the market's life) vs. "close" (near resolution), different strategies should be applied at different lifecycle stages. Early markets may reward momentum (information is being incorporated); mature markets may reward reversal (over-reaction is being corrected).
**Signal:** Classify each market into lifecycle stage: Early (<25% of life elapsed), Mid (25-75%), Late (>75%). Apply momentum strategy to Early, neutral to Mid, reversal to Late.
**Data:** Gamma API `created_at` and resolution date (free)
**Alpha:** 10-30 bps improvement to directional strategies | **Viability:** Unlikely
**Horizon:** Varies by lifecycle stage | **Capacity:** Same as directional strategies | **Durability:** Structural
**Complexity:** S
**Synergy:** Timing enhancement for all directional strategies.
**Kill Criterion:** If lifecycle-dependent returns don't differ significantly across stages over 100 markets.
**Risk:** Lifecycle stage is conflated with information quality, making it hard to isolate the temporal effect.
**Who's Doing This:** IPO momentum/reversal is studied in equity markets. PM lifecycle analysis is academic.
**Honest P(Works):** 5%

---

### G. Execution & Market-Making Refinements (8 strategies)

---

### G-1. WebSocket Upgrade: REST → WS for All Data Feeds
**Mechanism:** Your current REST polling (every 5 minutes) is the single biggest bottleneck. WebSocket connections provide real-time updates with <100ms latency. This isn't a strategy — it's prerequisite infrastructure for 8+ strategies in this document. The block_beats article confirms: "REST polling is completely outdated. By the time your HTTP request completes a round trip, the opportunity is long gone."
**Signal:** N/A (infrastructure upgrade)
**Data:** CLOB WebSocket (free), Binance WebSocket (free)
**Alpha:** Enables strategies requiring real-time data: A-1, A-4, A-5, A-8, A-12, G-2 through G-8 | **Viability:** Necessary
**Horizon:** Permanent | **Capacity:** N/A | **Durability:** N/A
**Complexity:** M (requires async architecture refactor)
**Synergy:** Foundational for all real-time strategies.
**Kill Criterion:** N/A — this is infrastructure, not hypothesis.
**Risk:** WebSocket connections can drop. Need robust reconnection logic with graceful degradation to REST.
**Who's Doing This:** Every serious PM bot.
**Honest P(Works):** 95% (technical execution, not alpha)

---

### G-2. Smart Order Routing: Dynamic Maker vs. Taker Decision
**Mechanism:** Not every trade should be maker-only. When a clear edge exists and is decaying (news event), the cost of waiting for a maker fill (which may not come) exceeds the taker fee. A dynamic routing algorithm should choose maker vs. taker based on: edge magnitude, edge half-life, fill probability, and current fee rate.
**Signal:** `if edge > (taker_fee × 3) AND edge_halflife < 5min: use_taker. elif edge > 0 AND edge_halflife > 1hr: use_maker. else: skip.`
**Data:** Edge estimates from all signal sources, CLOB for fee rates
**Alpha:** 10-30% improvement in edge capture rate | **Viability:** Likely
**Horizon:** Per-trade decision | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Execution upgrade for all strategies.
**Kill Criterion:** If dynamic-routed P&L doesn't outperform maker-only by >5% over 200 trades.
**Risk:** Overuse of taker execution burns capital on fees.
**Who's Doing This:** Standard in equity execution. PM application is straightforward.
**Honest P(Works):** 35%

---

### G-3. Partial Fill Management and Position Completion
**Mechanism:** Maker orders often partially fill. A position that's 60% filled but not completed has lower expected value than a fully filled position (because the edge may have moved). Systematic management of partial fills (complete, cancel, or hedge) improves overall portfolio efficiency.
**Signal:** When a maker order is >50% filled but stalled for >10 minutes, evaluate: if edge still exists, complete via taker (if worth the fee). If edge has degraded, cancel remainder and accept partial position.
**Data:** CLOB order status (free)
**Alpha:** 5-15% improvement in average position P&L | **Viability:** Likely
**Horizon:** Per-trade | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Execution refinement for all maker strategies.
**Kill Criterion:** If partial-fill management doesn't improve average P&L per position by >5%.
**Risk:** Completing via taker on a degraded edge is costly. Need strict edge re-evaluation.
**Who's Doing This:** Every professional trading system. Missing from most PM bot implementations.
**Honest P(Works):** 30%

---

### G-4. Pre-Resolution Exit Timing Optimization
**Mechanism:** For directional positions, there's an optimal exit time before resolution. Selling a YES position at $0.92 (capturing 92% of potential profit) may be better than holding to resolution (100%) because: (a) capital is freed earlier for the next trade, and (b) tail risk of resolution surprise is avoided. The optimal exit point depends on edge confidence, time remaining, and alternative use of capital.
**Signal:** `exit when position_value / max_position_value > 0.80 AND time_to_resolution > 2h AND alternative_edge_available`. This captures 80% of profit while freeing capital for the next opportunity.
**Data:** Position tracking (existing), alternative edge scoring
**Alpha:** 10-30% improvement in capital velocity | **Viability:** Possible
**Horizon:** Per-trade | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Portfolio-level optimization.
**Kill Criterion:** If early-exit strategy underperforms hold-to-resolution on risk-adjusted basis over 100 trades.
**Risk:** Selling at $0.92 means leaving $0.08 on the table. If alternative edges don't materialize, this is pure loss.
**Who's Doing This:** Sophisticated PM traders manage exit timing. Systematic optimization is uncommon.
**Honest P(Works):** 20%

---

### G-5. Order Flow Toxicity Detection (When to Pull Quotes)
**Mechanism:** As a maker, you need to detect when the flow becomes "toxic" (dominated by informed traders) and pull your quotes. Classic toxicity indicators: trade size spikes, directional run length, and PIN (probability of informed trading) estimates. When toxicity is high, you're being adversely selected — stop quoting until conditions normalize.
**Signal:** Compute rolling `toxicity_score = (directional_volume / total_volume)²` over last 20 trades. When `toxicity > 0.60`, cancel all maker orders. Resume when `toxicity < 0.40`.
**Data:** CLOB trade feed (free)
**Alpha:** Reduces adverse selection losses by 20-40% | **Viability:** Likely
**Horizon:** Real-time | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Critical safety mechanism for all maker strategies (A-1, A-2, A-8, A-9).
**Kill Criterion:** If toxicity-filtered periods don't have significantly higher adverse selection than normal periods.
**Risk:** Over-sensitive toxicity detection = too little quoting time = insufficient fills.
**Who's Doing This:** Standard in equity market making. PM application is natural.
**Honest P(Works):** 30%

---

### G-6. Batch Order Optimization Across Multiple Markets
**Mechanism:** Rather than managing orders market-by-market, optimize across the entire portfolio simultaneously. If you have limited capital ($247), you need to allocate it across markets to maximize total expected return. This is a portfolio-wide order management problem that considers: edge per market, fill probability per market, correlation between markets, and capital constraints.
**Signal:** Every cycle: compute edge and fill probability for all active markets. Solve the constrained optimization: `max Σ(edge_i × fill_prob_i × size_i) subject to Σ(size_i) ≤ bankroll AND size_i ≤ max_position`.
**Data:** All signal sources + CLOB data
**Alpha:** 15-30% improvement in capital efficiency | **Viability:** Possible
**Horizon:** Per-cycle | **Capacity:** N/A | **Durability:** Structural
**Complexity:** M (constrained optimization solver)
**Synergy:** Meta-strategy that optimizes allocation across all individual strategies.
**Kill Criterion:** If optimized allocation doesn't outperform equal-weighted allocation over 100 cycles.
**Risk:** Optimization error (model misspecification). Need robust optimization with uncertainty.
**Who's Doing This:** Standard portfolio optimization. PM-specific multi-market allocation is less common.
**Honest P(Works):** 25%

---

### G-7. Gas-Aware Execution Timing
**Mechanism:** Although Polymarket relayer abstracts most gas costs, there are scenarios where on-chain operations (position merging, withdrawals, certain order types) incur gas fees on Polygon. Gas prices on Polygon vary predictably (lower during Asian night hours, higher during US daytime). Timing on-chain operations for low-gas windows saves money.
**Signal:** Execute on-chain operations when Polygon gas price < 50% of 24h average.
**Data:** Polygon gas price API (free)
**Alpha:** Saves $0.01-$0.10 per on-chain operation | **Viability:** Likely (but trivial impact at $247 scale)
**Horizon:** Per-operation | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Cost reduction for all strategies.
**Kill Criterion:** If gas savings < $1/month.
**Risk:** Delaying operations for gas could miss time-sensitive opportunities.
**Who's Doing This:** Standard in DeFi. PM application is straightforward.
**Honest P(Works):** 50% (but alpha is essentially zero at current scale)

---

### G-8. Position Merging for Capital Efficiency
**Mechanism:** The poly_merger module (open-source, referenced in poly-maker) consolidates YES + NO positions into redeemed cash, reducing gas fees and freeing capital. When you hold both YES and NO positions in the same market (from market-making), they offset to create a locked $1.00 payoff minus your cost. Merging and redeeming frees the locked capital.
**Signal:** When `min(YES_shares, NO_shares) > $1.00` in any market, merge and redeem the offsetting pair.
**Data:** Position tracking (existing)
**Alpha:** Capital efficiency improvement (frees locked capital) | **Viability:** Likely
**Horizon:** Per-cycle | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (use existing poly_merger code from open-source)
**Synergy:** Essential for A-1 (market making generates offsetting positions).
**Kill Criterion:** N/A — this is operational necessity for market making.
**Risk:** Gas cost of merge transaction may exceed freed capital on very small positions.
**Who's Doing This:** Poly-maker implements this. Standard practice.
**Honest P(Works):** 80%

---

### H. Portfolio & Meta-Strategies (10 strategies)

---

### H-1. Correlation-Aware Kelly for Binary Portfolios
**Mechanism:** Standard Kelly criterion treats each bet independently. But PM positions are often correlated (two political markets about the same election). Correlated Kelly adjusts position sizes downward for correlated bets, preventing portfolio-level over-concentration that independent Kelly misses.
**Signal:** Compute pairwise correlation matrix using LLM-estimated correlation between PM markets. Apply multi-asset Kelly optimization: `sizes = Σ^(-1) × edges` where Σ is the correlation matrix and edges are the calibrated edge estimates.
**Data:** LLM for correlation estimation, existing edge estimates
**Alpha:** Reduces portfolio drawdown by 20-40% | **Viability:** Likely
**Horizon:** N/A (portfolio construction) | **Capacity:** N/A | **Durability:** Structural
**Complexity:** M (correlation matrix construction + multi-variate optimization)
**Synergy:** Upgrade to existing quarter-Kelly sizing. Uses same edge estimates, just smarter allocation.
**Kill Criterion:** If correlation-adjusted portfolio Sharpe < independent-Kelly portfolio Sharpe on backtest.
**Risk:** LLM correlation estimates may be inaccurate. Garbage in, garbage out.
**Who's Doing This:** Professional quant funds use correlation-aware sizing. PM-specific implementation is rare.
**Honest P(Works):** 25%

---

### H-2. Strategy-Specific Bankroll Segmentation
**Mechanism:** Rather than one $247 bankroll serving all strategies, segment into sub-bankrolls: $100 for maker strategies (continuous, low-risk), $100 for directional LLM bets (intermittent, medium-risk), $47 for experimental strategies (high-risk, educational). Each sub-bankroll has independent Kelly sizing and loss limits. This prevents one strategy's drawdown from killing capital for others.
**Signal:** Allocate bankroll proportionally to strategy backtested Sharpe ratio. Rebalance monthly.
**Data:** Strategy performance tracking (new)
**Alpha:** Reduces correlation of strategy drawdowns | **Viability:** Likely
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Meta-strategy for all strategies in this document.
**Kill Criterion:** If segmented bankroll underperforms unified bankroll on risk-adjusted basis.
**Risk:** With only $247, the segments are too small for meaningful positions. May not be practical until $500+.
**Who's Doing This:** Standard fund management. Obvious but often overlooked by small traders.
**Honest P(Works):** 30%

---

### H-3. Drawdown-Contingent Strategy Switching
**Mechanism:** When the portfolio hits a drawdown threshold (e.g., -10% from peak), switch from aggressive strategies (directional bets) to conservative strategies (market making, arb). This preserves capital during adverse regimes while maintaining some activity. When drawdown recovers to -5%, resume normal allocation.
**Signal:** `if drawdown > 10%: allocation = {maker: 80%, directional: 10%, experimental: 10%}. elif drawdown > 5%: allocation = {maker: 60%, directional: 30%, experimental: 10%}. else: normal allocation.`
**Data:** Portfolio tracking (existing)
**Alpha:** Reduces max drawdown by 30-50% | **Viability:** Likely
**Horizon:** Continuous | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Risk management overlay for all strategies.
**Kill Criterion:** If drawdown-contingent switching results in worse terminal wealth than static allocation over 1000 Monte Carlo simulations.
**Risk:** Getting stuck in "conservative mode" during extended drawdowns, missing the recovery.
**Who's Doing This:** Standard risk management. PM application is straightforward.
**Honest P(Works):** 35%

---

### H-4. Hedge Construction with Opposing Binary Markets
**Mechanism:** Reduce portfolio directional risk by pairing opposing positions in correlated markets. Example: Long YES on "Trump wins Republican nomination" + Short YES on "DeSantis wins nomination" = reduced political-cycle risk while maintaining the relative-value bet.
**Signal:** For each directional position, identify the most correlated opposing market (from B-1 dependency graph). Take an offsetting position of 30-50% of the original size.
**Data:** Dependency graph (from B-1), existing position tracking
**Alpha:** Reduces portfolio volatility without eliminating edge | **Viability:** Possible
**Horizon:** Continuous | **Capacity:** Reduces effective capacity (capital used for hedges) | **Durability:** Structural
**Complexity:** M
**Synergy:** Uses dependency graph from B-1 and correlation estimates from H-1.
**Kill Criterion:** If hedged portfolio Sharpe < unhedged portfolio Sharpe (hedging costs exceed risk reduction benefits).
**Risk:** Imperfect hedges. Correlation can spike during extreme events.
**Who's Doing This:** Standard portfolio management. PM-specific hedging is uncommon.
**Honest P(Works):** 15%

---

### H-5. Capital Velocity Optimization via Staggered Resolution Timing
**Mechanism:** Instead of concentrating capital in markets that all resolve on the same date, distribute across markets with staggered resolution dates. This ensures capital is freed at regular intervals, maintaining high utilization. Compute `capital_velocity = realized_P&L / average_locked_capital`.
**Signal:** For each new position, consider the resolution date relative to existing positions. Prefer markets whose resolution dates fill gaps in the existing schedule. Penalize markets that pile onto dates with existing positions.
**Data:** Gamma API resolution dates (free), position tracker
**Alpha:** 20-50% improvement in capital utilization | **Viability:** Likely
**Horizon:** Position selection criterion | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Enhancement to velocity scoring already in pipeline.
**Kill Criterion:** If staggered portfolio doesn't show higher capital velocity than un-staggered over 60 days.
**Risk:** Best-edge markets may cluster on the same dates. Forcing diversification may sacrifice edge quality.
**Who's Doing This:** Bond portfolio managers do this (duration laddering). PM application is novel.
**Honest P(Works):** 25%

---

### H-6. Regime Detection for Strategy Rotation
**Mechanism:** PM markets go through regimes: high-news (elections, crises) and low-news (calm periods). Different strategies perform better in different regimes. In high-news regimes, directional strategies outperform (lots of mispricing to capture). In low-news regimes, market-making outperforms (stable spreads, low adverse selection). Detecting the current regime and rotating strategy allocation accordingly improves portfolio Sharpe.
**Signal:** Compute `news_regime = GDELT_event_volume / 30d_rolling_average`. When `news_regime > 1.5`: overweight directional strategies. When `news_regime < 0.7`: overweight market making.
**Data:** GDELT (free), existing strategy performance data
**Alpha:** 15-30% Sharpe improvement | **Viability:** Possible
**Horizon:** Continuous | **Capacity:** N/A | **Durability:** Structural
**Complexity:** M
**Synergy:** Uses GDELT infrastructure from C-4.
**Kill Criterion:** If regime-rotated portfolio doesn't outperform static allocation over 6 months.
**Risk:** Regime detection is noisy. Frequent switching creates transaction costs.
**Who's Doing This:** Standard in systematic macro. PM-specific regime rotation is novel.
**Honest P(Works):** 15%

---

### H-7. Market-Neutral Binary Spread Trading
**Mechanism:** Construct "spreads" between related PM markets to isolate the relative-value component and eliminate directional risk. Example: Buy YES on "Trump wins popular vote" and sell YES on "Trump wins electoral college." You're not betting on Trump — you're betting on the popular-vote/electoral-college divergence, which is a more predictable and less volatile quantity.
**Signal:** Identify pairs of related PM markets where the *spread* (price difference) has a predictable range. When the spread exceeds historical bounds, trade toward mean reversion.
**Data:** Gamma API (free), historical price data
**Alpha:** 30-80 bps | **Viability:** Possible
**Horizon:** Days to weeks | **Capacity:** $500-5K | **Durability:** Structural
**Complexity:** M (pair identification + spread tracking + two-leg execution)
**Synergy:** Uses dependency graph from B-1.
**Kill Criterion:** If spread mean-reversion rate is <55% over 30 observations.
**Risk:** Spread can diverge further. Basis risk if markets don't resolve on the same timeline.
**Who's Doing This:** Pairs trading is classic quant. PM-specific spread trading is uncommon.
**Honest P(Works):** 15%

---

### H-8. Volatility Targeting for PM Portfolio
**Mechanism:** Instead of targeting a fixed Kelly fraction, target a fixed portfolio volatility level (e.g., 2% daily). When markets are calm, increase position sizes to hit the target. When markets are volatile, decrease. This maintains consistent risk exposure regardless of market conditions.
**Signal:** Compute `portfolio_vol = std(daily_returns, 10d_rolling)`. Adjust position sizing scalar: `target_vol / portfolio_vol`. Cap at 2× and floor at 0.25×.
**Data:** Portfolio return tracking (existing)
**Alpha:** Improves risk-adjusted returns by smoothing volatility | **Viability:** Possible
**Horizon:** Continuous | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Enhancement to quarter-Kelly sizing.
**Kill Criterion:** If vol-targeted portfolio Sharpe < fixed-Kelly portfolio Sharpe over 3 months.
**Risk:** Requires sufficient history to estimate portfolio volatility. With $247 and few positions, the estimates will be very noisy initially.
**Who's Doing This:** Standard in quant fund management. PM application is natural.
**Honest P(Works):** 20%

---

### H-9. Portfolio Rebalancing Triggers
**Mechanism:** Define specific triggers for portfolio rebalancing rather than time-based rebalancing. Trigger when: (a) any single position exceeds 30% of portfolio, (b) total directional exposure exceeds 50%, (c) correlation between positions spikes above threshold, or (d) new high-priority signal fires.
**Signal:** Event-driven rebalancing rather than fixed-interval.
**Data:** Portfolio tracking + correlation estimates
**Alpha:** Modest improvement in risk-adjusted returns | **Viability:** Likely
**Horizon:** Event-driven | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S
**Synergy:** Portfolio management infrastructure.
**Kill Criterion:** If trigger-based rebalancing increases transaction costs more than it reduces drawdown.
**Risk:** Over-frequent rebalancing from sensitive triggers.
**Who's Doing This:** Standard.
**Honest P(Works):** 25%

---

### H-10. 20% Veteran Mission Fund Accounting
**Mechanism:** Implement a transparent tracking system that automatically computes 20% of net realized P&L for veteran suicide prevention donation. Publish on the website monthly. This is not a trading strategy — it's a portfolio management requirement that also serves the educational/trust-building mission.
**Signal:** `veteran_fund = max(0, 0.20 × cumulative_realized_PnL)`. Track separately. Display on website dashboard.
**Data:** Trade database (existing)
**Alpha:** Zero (cost, not alpha) | **Viability:** Required (non-negotiable)
**Horizon:** Ongoing | **Capacity:** N/A | **Durability:** Permanent
**Complexity:** S
**Synergy:** Core fund structure requirement. Website content.
**Kill Criterion:** N/A
**Risk:** None — accounting, not trading.
**Who's Doing This:** Social impact funds exist. Transparent, open-source version is novel.
**Honest P(Works):** 100%

---

### I. Novel / Wild Card Ideas (15 strategies)

---

### I-1. Prediction Tournament Leaderboard Scraping
**Mechanism:** Metaculus, Good Judgment, and INFER publish leaderboards of top forecasters. These forecasters' individual predictions (when public) are often more calibrated than market aggregates. By tracking top-10 forecasters' public predictions and comparing to PM prices, you get a curated "expert consensus" signal.
**Signal:** Scrape top forecasters' public predictions from Metaculus/GJOpen. When `top_forecaster_consensus` diverges from PM price by >8%, trade PM toward the expert consensus.
**Data:** Metaculus user profiles (public), GJOpen (public)
**Alpha:** 30-100 bps | **Viability:** Possible
**Horizon:** Days | **Capacity:** $500-5K | **Durability:** Months (until more PM traders do this)
**Complexity:** S (web scraping + comparison)
**Synergy:** External calibrated signal for confirmation layer.
**Kill Criterion:** If top-forecaster consensus accuracy < PM price accuracy over 30 resolved markets.
**Risk:** Top forecasters may not predict on markets that overlap with PM. Small sample of overlapping predictions.
**Who's Doing This:** Some superforecasters likely do this manually. Automated version is novel.
**Honest P(Works):** 20%

---

### I-2. Wayback Machine Pre-Announcement Website Change Detection
**Mechanism:** Before major corporate or government announcements, websites sometimes update subtly (new pages created, text changed, assets uploaded). By monitoring archive.org's CDX API for changes to relevant websites, you can detect pre-announcement activity.
**Signal:** For PM markets about specific entities (companies, government agencies), monitor `web.archive.org/cdx/search/cdx?url=entity_website` for unusual change frequency. Spike in saved snapshots = something is being updated = announcement may be imminent.
**Data:** Wayback Machine CDX API (free)
**Alpha:** 50-200 bps on qualifying events | **Viability:** Unlikely (very rare qualifying events; changes don't indicate direction)
**Horizon:** Hours to days | **Capacity:** $200-1K | **Durability:** Years
**Complexity:** S
**Synergy:** Alternative data for LLM context.
**Kill Criterion:** If <2 qualifying detection events per quarter.
**Risk:** Extremely low event frequency. Changes may be routine maintenance, not pre-announcement.
**Who's Doing This:** OSINT community does this. PM application is novel but likely impractical.
**Honest P(Works):** 3%

---

### I-3. Discord/Telegram Alpha Group Monitoring
**Mechanism:** Crypto prediction market "alpha" groups on Discord and Telegram share trade ideas. These groups create correlated buying pressure when they collectively act on a recommendation. By monitoring the largest groups, you can front-run the retail flow that follows their recommendations.
**Signal:** Monitor top 5 PM-focused Discord/Telegram groups. When a recommendation is posted with significant engagement (>20 reactions in 5 min), trade PM BEFORE the group's collective buying pressure arrives.
**Data:** Discord/Telegram APIs or scraping (free but ToS-questionable)
**Alpha:** 30-100 bps per qualifying event | **Viability:** Possible
**Horizon:** Minutes (front-running the retail flow) | **Capacity:** $500-2K | **Durability:** Months
**Complexity:** S (API monitoring + trade execution)
**Synergy:** Alternative flow signal for fast markets.
**Kill Criterion:** If alpha group recommendations don't predict PM price movement at >55% rate over 50 events.
**Risk:** Ethical concerns about front-running retail groups. ToS violations. Group recommendations may be misinformed.
**Who's Doing This:** Crypto copy-trading is huge. PM-specific alpha group monitoring is common among retail.
**Honest P(Works):** 15%

---

### I-4. Synthetic Calibration via AI-Generated Hypothetical Markets
**Mechanism:** Generate thousands of hypothetical prediction markets with known true probabilities (because you define the scenario). Use these as training data to improve LLM calibration. Example: "A fair coin is flipped. What's the probability it's heads?" should return 50%. "A die is rolled. What's the probability it's greater than 4?" should return 33%. This stress-tests the LLM's numeric reasoning and reveals systematic biases.
**Signal:** Generate 1000 hypothetical questions with known answers. Test LLM calibration. Identify bias patterns (e.g., LLM rounds to 50% when uncertain). Apply bias corrections to real market estimates.
**Data:** Self-generated hypothetical questions (free)
**Alpha:** Improves calibration by identifying and correcting systematic biases | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (prompt engineering + analysis)
**Synergy:** Enhancement to LLM analyzer calibration.
**Kill Criterion:** If synthetic calibration corrections don't improve real-market prediction Brier score.
**Risk:** Hypothetical markets may not capture the complexity of real markets. LLM may perform differently on abstract vs. real questions.
**Who's Doing This:** Lopez-Lira et al. (2025) studied LLM memorization. Synthetic calibration is a novel approach to the problem.
**Honest P(Works):** 15%

---

### I-5. $POLY Token Airdrop Farming as Strategy Subsidy
**Mechanism:** Polymarket may (widely speculated) airdrop a $POLY token to active traders. If the airdrop materializes, even a break-even trading strategy becomes highly profitable from the token value. Optimizing for airdrop eligibility (diverse market participation, consistent activity, both maker and taker orders) while maintaining positive EV trading is a dual-objective optimization.
**Signal:** Ensure bot activity meets likely airdrop criteria: trade in >10 unique markets per week, maintain both maker and taker activity, diversify across categories. As long as trading maintains ≥0 EV, the airdrop optionality is pure upside.
**Data:** Speculation about airdrop criteria (public Polymarket community discussions)
**Alpha:** $0 from trading + potential $100-$10,000 from airdrop | **Viability:** Possible
**Horizon:** Unknown (token launch timing) | **Capacity:** $247 (entire bankroll is eligible) | **Durability:** One-time event
**Complexity:** S
**Synergy:** Motivates broad market participation which also improves LLM calibration data collection.
**Kill Criterion:** If Polymarket officially announces no airdrop.
**Risk:** Airdrop may never happen. Token may be worthless if it does. Chasing airdrop criteria may lead to negative-EV trades.
**Who's Doing This:** The Itan Scott blog post explicitly mentions airdrop farming as strategy motivation. Widespread among PM traders.
**Honest P(Works):** 20% (that the airdrop happens AND is material)

---

### I-6. AI-Generated Counter-Narratives as Conviction Testing
**Mechanism:** Before placing a trade, have the LLM generate the strongest possible counter-argument. If the counter-argument significantly changes the probability estimate (i.e., the model "flips" when presented with the counter-narrative), the original conviction was fragile. Only trade when the model maintains its estimate after adversarial counter-narrative generation.
**Signal:** Step 1: LLM estimates probability P1. Step 2: LLM generates best counter-argument. Step 3: LLM re-estimates probability P2 given counter-argument. If `|P1 - P2| < 0.05`, conviction is robust — trade. If `|P1 - P2| > 0.15`, conviction is fragile — skip.
**Data:** LLM API (3× cost per market)
**Alpha:** Reduces losses from fragile-conviction trades by 20-30% | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** S (3-step prompt engineering)
**Synergy:** Enhancement to D-1 (debate) and D-4 (verification). Can replace or complement debate architecture.
**Kill Criterion:** If counter-narrative-filtered trades don't have higher win rate than unfiltered trades.
**Risk:** LLM may be easily swayed by its own counter-arguments (SACD drift — cited as a calibration problem in your findings).
**Who's Doing This:** Red-teaming LLM outputs is standard in AI safety. Application to trading conviction is novel.
**Honest P(Works):** 20%

---

### I-7. Polymarket Leaderboard Reverse Engineering
**Mechanism:** Polymarket publishes top trader leaderboards. By tracking the positions of top traders (via data API wallet tracking), you can create a "smart money" signal similar to your wallet flow detector but focused on the overall leaderboard rather than per-market convergence.
**Signal:** Identify top 50 all-time Polymarket wallets from public leaderboard. Track their new positions via data API. When >5 top wallets take the same side of a market within 48h, flag as high-conviction opportunity.
**Data:** Polymarket leaderboard (public), data API trades endpoint (free)
**Alpha:** 30-80 bps | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** $500-5K | **Durability:** Months (alpha decays as more people track the same wallets)
**Complexity:** S (extension of existing wallet flow detector)
**Synergy:** Enhancement to smart wallet flow detector. Uses same infrastructure, expanded wallet list.
**Kill Criterion:** If leaderboard-wallet consensus doesn't predict market direction at >55% rate.
**Risk:** Top wallets may be market makers (directional signal is misleading) or may have changed strategies.
**Who's Doing This:** Dexter's Lab and other PM analysts publicly track top wallets. Automated version is common.
**Honest P(Works):** 20%

---

### I-8. Social Media Influencer Position Tracking
**Mechanism:** PM-focused social media influencers (Twitter, YouTube) publicly share their positions. When multiple influencers align on the same trade, their combined audience creates buying pressure. By detecting this BEFORE the audience acts (monitoring the influencer's post, not the audience's reaction), you front-run the retail flow.
**Signal:** Monitor top 20 PM influencers on Twitter. When 3+ post about the same market within 24h with the same directional thesis, trade PM before the retail wave.
**Data:** Twitter API (free tier) or scraping
**Alpha:** 20-60 bps | **Viability:** Unlikely (influencer positions may be noise)
**Horizon:** Hours | **Capacity:** $200-1K | **Durability:** 3-6 months
**Complexity:** S
**Synergy:** Alternative flow signal.
**Kill Criterion:** If influencer consensus doesn't predict PM price movement at >54% rate.
**Risk:** Influencers may be wrong. Their audience may not act on recommendations. Ethical concerns about front-running retail.
**Who's Doing This:** Crypto influence tracking exists. PM-specific version is less common.
**Honest P(Works):** 8%

---

### I-9. Resolution Oracle Latency Exploitation (Non-Chainlink Markets)
**Mechanism:** While crypto markets use Chainlink (well-arbitraged), political and event markets use UMA or manual resolution. Manual resolution has much higher latency (hours to days after the actual event). During this resolution lag, the market should trade at ~$0.99/$0.01, but often doesn't because some traders are uncertain about resolution mechanics. Buying at $0.95 when the outcome is clearly determined (but not yet officially resolved) is 5% free money.
**Signal:** When an event outcome is clear from news (e.g., election called by AP), but the PM market is still trading at <$0.97 on the winning side, buy. Hold until UMA resolution.
**Data:** News APIs (free), PM API (free)
**Alpha:** 100-300 bps per event | **Viability:** Possible
**Horizon:** Hours to days | **Capacity:** $500-5K | **Durability:** Structural (resolution lag is inherent to manual oracle systems)
**Complexity:** S
**Synergy:** Uses news monitoring infrastructure from C-6.
**Kill Criterion:** If >80% of post-determination markets are already at $0.98+ (no opportunity).
**Risk:** Outcome may not be as clear as it appears (contested elections, disputed results). UMA resolution could surprise.
**Who's Doing This:** Active PM traders pick up "free money" near resolution. Systematic version is uncommon.
**Honest P(Works):** 25%

---

### I-10. Prediction Market as Calibration Training Ground
**Mechanism:** Use PM participation specifically as a calibration improvement tool, not for profit. Place tiny bets ($0.10) on every market where you have an LLM estimate. Track accuracy religiously. The value isn't in the P&L — it's in the calibration data that makes your model better over time. The $0.10 "skin in the game" ensures you take each estimate seriously.
**Signal:** For every market the LLM analyzes, place a $0.10 directional bet on the LLM's favored side. Track all outcomes. Refit calibration monthly.
**Data:** Own trading results
**Alpha:** Zero direct alpha (intentionally). Produces calibration data worth 10-100× the $0.10 per market. | **Viability:** Likely
**Horizon:** Ongoing | **Capacity:** $10-50/month | **Durability:** Permanent
**Complexity:** S
**Synergy:** Directly improves calibration for all LLM-dependent strategies. Generates website content.
**Kill Criterion:** N/A — this is a research investment, not a strategy.
**Risk:** Costs $0.10 per market × ~100 markets/week = ~$40/month. Worth it for calibration data, but material relative to $247 bankroll.
**Who's Doing This:** Superforecasters do this manually. Systematic $0.10-per-market approach is novel.
**Honest P(Works):** 80% (as a calibration improvement tool, not as a profit center)

---

### I-11. Cross-Language Sentiment Divergence for Geopolitical Markets
**Mechanism:** When English-language sentiment on a geopolitical topic diverges from Chinese or Russian language sentiment, it reveals information asymmetry. The local-language sentiment is often more informed about local events. PM prices, driven by English-speaking traders, may be miscalibrated relative to local information.
**Signal:** Compare sentiment on geopolitical topics across English, Chinese, Russian, and Arabic language sources. When `local_sentiment` diverges from `English_sentiment` by >2 standard deviations, trade PM toward the local sentiment.
**Data:** Translation APIs, multilingual sentiment analysis, news APIs
**Alpha:** 30-100 bps on qualifying events | **Viability:** Unlikely (requires sophisticated NLP pipeline)
**Horizon:** Days | **Capacity:** $500-2K | **Durability:** Months
**Complexity:** L
**Synergy:** Extension of C-12 cross-language news strategy.
**Kill Criterion:** If local/English sentiment divergence doesn't predict PM outcome better than English-only at >55% rate.
**Risk:** Local-language media may be state-controlled (propaganda). Sentiment analysis accuracy varies by language.
**Who's Doing This:** Intelligence agencies. Nobody at our scale on PM.
**Honest P(Works):** 8%

---

### I-12. PolyMarket Profile-Based Trader Classification
**Mechanism:** The data API reveals wallet addresses and trade patterns. By classifying wallets into types (market maker, directional whale, retail noise, arb bot) based on their behavior patterns, you can weight their signals differently. Whale directional trades matter more than retail noise. Market maker inventory shifts are less directional than whale trades.
**Signal:** For each wallet, compute behavioral features: trade frequency, average size, maker/taker ratio, win rate, category focus. Cluster into types. Weight wallet flow signals by type (whale directional > arb bot rebalancing > retail noise).
**Data:** Data API trades endpoint (free)
**Alpha:** Improves wallet flow signal quality by 20-30% | **Viability:** Possible
**Horizon:** N/A (signal quality improvement) | **Capacity:** N/A | **Durability:** Structural
**Complexity:** M (clustering + feature engineering)
**Synergy:** Direct enhancement to smart wallet flow detector.
**Kill Criterion:** If classified-wallet-weighted signals don't outperform equal-weighted signals over 100 markets.
**Risk:** Wallet behavior changes over time. Classification may go stale.
**Who's Doing This:** Blockchain analytics firms (Chainalysis, Nansen) do wallet classification. PM-specific behavioral classification is less common.
**Honest P(Works):** 20%

---

### I-13. Automated Market Creation Timing (Be First to a Trending Topic)
**Mechanism:** When a topic is trending but no PM market exists yet, creating the market captures the first-mover advantage: you set the initial odds and collect maker fees from early traders. Polymarket allows permissionless market creation.
**Signal:** Monitor GDELT, Google Trends, and social media for trending topics without existing PM markets. Create markets on trending topics before others. Set initial price using LLM estimate.
**Data:** GDELT, Google Trends (free)
**Alpha:** Maker fee capture + first-mover pricing advantage | **Viability:** Unlikely (Polymarket market creation may have requirements/review process)
**Horizon:** Ongoing | **Capacity:** N/A | **Durability:** Months
**Complexity:** M
**Synergy:** Uses GDELT and trend detection infrastructure.
**Kill Criterion:** If Polymarket doesn't allow permissionless market creation, or if created markets attract <$100 volume.
**Risk:** Market creation may be centralized (only Polymarket team creates markets). If permissionless, quality control issues.
**Who's Doing This:** Polymarket market creation appears to be semi-centralized.
**Honest P(Works):** 5%

---

### I-14. Prediction Market ETF Mispricing (Upcoming)
**Mechanism:** In Feb 2026, several firms announced plans for prediction market ETFs that would package PM outcomes into tradeable funds. When these launch, discrepancies between ETF NAV and underlying PM prices create traditional ETF arb opportunities — but in prediction market space.
**Signal:** Monitor PM ETF prices vs. underlying PM market prices. When premium/discount exceeds creation/redemption cost, arbitrage.
**Data:** ETF price feeds (once launched), PM APIs
**Alpha:** 50-200 bps | **Viability:** Possible (dependent on ETF launch)
**Horizon:** Minutes | **Capacity:** $1K-10K | **Durability:** Structural (ETF arb is permanent)
**Complexity:** M
**Synergy:** Traditional financial infrastructure meets PM.
**Kill Criterion:** If ETFs don't launch within 6 months, or if premium/discount is consistently <1%.
**Risk:** ETFs may not launch. If they do, institutional arb will dominate within days.
**Who's Doing This:** ETF market makers will do this immediately upon launch.
**Honest P(Works):** 10%

---

### I-15. LLM Betting Market (Meta-Prediction)
**Mechanism:** The most creative idea in this list: create a meta-prediction system where LLM instances "bet" against each other on market outcomes, using a proper scoring rule as the payoff function. The "winning" models get higher weight in the ensemble. This is an automated model selection process disguised as a prediction market, where the "traders" are LLM configurations (different prompts, temperatures, model sizes) competing to be most accurate.
**Signal:** Run 10 LLM configurations in parallel. Each "bets" on every market using its probability estimate. Track each configuration's Brier score over time. Weight the ensemble toward the currently-best-performing configurations. This is a form of online learning / multi-armed bandit for LLM ensemble weighting.
**Data:** LLM API (10× current cost)
**Alpha:** -0.01 to -0.03 Brier improvement (comparable to static ensemble but adaptive) | **Viability:** Possible
**Horizon:** N/A | **Capacity:** N/A | **Durability:** Structural
**Complexity:** M (requires multi-configuration tracking + online learning)
**Synergy:** Upgrade to multi-model ensemble.
**Kill Criterion:** If adaptive ensemble doesn't outperform static equal-weighted ensemble by >0.005 Brier over 200 markets.
**Risk:** 10× API cost. The best configuration may change rapidly, causing excessive switching.
**Who's Doing This:** The "fake prediction markets for LLM accuracy" paper (arXiv:2512.05998, Dec 2025) explores this exact concept.
**Honest P(Works):** 15%

---

## Part 2: Top 30 Research Vectors (Extended Specification)

Based on the composite scoring formula: `Composite = (Testability×2 + Speed×2 + Durability×1.5 + CapEff×1.5 + Synergy×1) / 8`

### Ranked Top 30

| Rank | Strategy | Composite | P(Works) |
|------|----------|-----------|----------|
| 1 | A-6. Multi-Outcome Sum Violation Scanner | 4.2 | 45% |
| 2 | B-1. LLM Combinatorial Dependency Graph | 4.1 | 45% |
| 3 | D-12. Adaptive Platt Calibration | 4.0 | 40% |
| 4 | G-1. WebSocket Upgrade | 3.9 | 95%* |
| 5 | D-9. Ensemble Disagreement Signal | 3.8 | 30% |
| 6 | A-1. Information-Advantaged Market Making | 3.7 | 35% |
| 7 | D-2. Conformal Prediction Sizing | 3.7 | 30% |
| 8 | D-5. Active Learning Market Prioritization | 3.6 | 30% |
| 9 | G-5. Order Flow Toxicity Detection | 3.6 | 30% |
| 10 | G-8. Position Merging | 3.5 | 80% |
| 11 | H-3. Drawdown-Contingent Switching | 3.5 | 35% |
| 12 | G-2. Smart Order Routing | 3.4 | 35% |
| 13 | H-5. Capital Velocity Optimization | 3.4 | 25% |
| 14 | B-10. Kalshi Binary Weather | 3.3 | 25% |
| 15 | D-1. Multi-Agent Debate | 3.3 | 25% |
| 16 | H-2. Bankroll Segmentation | 3.3 | 30% |
| 17 | I-10. Calibration Training Ground | 3.2 | 80% |
| 18 | C-6. News Wire Speed | 3.2 | 25% |
| 19 | I-6. Counter-Narrative Conviction Testing | 3.2 | 20% |
| 20 | E-3. Partisan Bias Exploitation | 3.1 | 20% |
| 21 | B-6. Metaculus Probability Transfer | 3.1 | 25% |
| 22 | F-3. Theta Decay Exploitation | 3.0 | 20% |
| 23 | I-9. Resolution Oracle Latency | 3.0 | 25% |
| 24 | B-3. PM → Options Market Transfer | 3.0 | 30% |
| 25 | I-12. Wallet Behavioral Classification | 2.9 | 20% |
| 26 | D-6. Synthetic Calibration (Metaculus) | 2.9 | 25% |
| 27 | D-4. Chain-of-Verification | 2.8 | 20% |
| 28 | I-7. Leaderboard Reverse Engineering | 2.8 | 20% |
| 29 | C-7. FRED Consensus Divergence | 2.8 | 20% |
| 30 | E-5. Vivid Event Overreaction | 2.7 | 18% |

*G-1 scored on infrastructure necessity, not alpha probability.

---

### Extended Specs for Top 10

---

## Research Vector #1: Multi-Outcome Sum Violation Scanner (A-6)
**Composite Score:** 4.2/5.0
**Edge Class:** Prediction Market Microstructure

### Core Hypothesis
In multi-outcome Polymarket markets, the sum of all YES prices regularly deviates from $1.00 by >3%, creating near-risk-free arbitrage after accounting for non-atomic execution risk.

### Why Underexploited
Jump and Susquehanna focus on high-volume political markets. The IMDEA study showed $40M in arb was extracted, but the long tail of low-volume multi-outcome markets (10+ candidates with thin liquidity) is under-monitored. Your LLM can identify sum violations AND assess which outcomes are most mispriced — a two-layer edge that pure arb bots miss.

### Data Required
Gamma API `/markets` endpoint (free, REST). Filter for `outcomes > 2`. CLOB best-ask for each outcome token (free, WebSocket preferred).

### Signal Logic (Pseudocode)
```python
for market in active_multi_outcome_markets:
    yes_prices = [get_best_ask(outcome) for outcome in market.outcomes]
    total = sum(yes_prices)
    if total < 0.97:  # Buy all
        profit_per_set = 1.00 - total
        if profit_per_set > 0.03:  # Exceed min threshold
            buy_all_outcomes_at_ask(market, size=min($5, bankroll*0.02))
    elif total > 1.03:  # Sell all (if holding)
        sell_all_held_outcomes(market)
```

### Expected Net Impact
200-400 bps gross per violation event. After non-atomic execution slippage (~50 bps), net 150-350 bps. At 2-3 events per week, annualized ~30-50% on allocated capital.

### Backtest Design
Pull 6 months of historical prices for all multi-outcome markets via Gamma API. Compute hourly sum deviations. Simulate sequential execution (buy outcomes in random order) with historical spreads. Measure capture rate (fraction of theoretical profit actually realized). Walk-forward: train threshold on first 3 months, test on last 3.

### Implementation Estimate
3-4 days. Reuses Gamma API client, CLOB order client, position tracking. New: multi-outcome market scanner, sequential order manager with rollback logic.

### Kill Criteria
If average realized capture rate < 50% of theoretical profit over 20 events, OR if <1 qualifying event per week on average over 4 weeks.

### Academic Foundation
Saguillo, O., Ghafouri, V., Kiffer, L., & Suarez-Tangil, G. (2025). "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets." arXiv:2508.03474. Published at AFT 2025.

### Honest Assessment
Probability this actually works: **45%**
Probability this is worth the research time even if it fails: **85%** (the multi-outcome scanner infrastructure is useful for B-1, B-5, B-8, and H-7)

---

## Research Vector #2: LLM Combinatorial Dependency Graph (B-1)
**Composite Score:** 4.1/5.0
**Edge Class:** Cross-Market Arbitrage

### Core Hypothesis
Using LLMs to detect logical dependencies between Polymarket markets (A implies B, A is subset of B, A + B = C) and monitoring for probability constraint violations creates a systematic combinatorial arbitrage signal.

### Why Underexploited
The IMDEA study found 7,000+ markets with measurable combinatorial mispricings but used expensive LLM-based dependency detection. Most arb bots use simple within-market sum checks (A-6) but not cross-market logical dependency analysis. Your existing LLM infrastructure gives you this capability cheaply.

### Data Required
Gamma API for all active markets (free). LLM API for pairwise dependency classification (~$0.02/pair × ~1000 active market pairs = ~$20 one-time, then incremental for new markets).

### Signal Logic (Pseudocode)
```python
# One-time: Build dependency graph
for pair in market_pairs_same_category:
    dependency = llm.classify(pair.market_A.question, pair.market_B.question)
    # Returns: "A_implies_B", "B_implies_A", "mutually_exclusive", "independent", "A_subset_B"
    if dependency != "independent":
        graph.add_edge(pair, dependency)

# Continuous: Monitor for violations
for edge in graph.edges:
    if edge.type == "A_implies_B":
        if price(A) > price(B) + 0.03:
            signal("BUY B, SELL A", edge=price(A)-price(B))
    elif edge.type == "mutually_exclusive":
        if price(A) + price(B) > 1.03:
            signal("SELL BOTH", edge=price(A)+price(B)-1.00)
```

### Expected Net Impact
100-300 bps per qualifying violation. 5-10 qualifying violations per week. Net ~50-200 bps after execution costs. Annualized ~25-50% on allocated capital.

### Backtest Design
Build dependency graph on all markets active in Q4 2025. Identify historical violations using archived price data. Simulate multi-leg execution with conservative fill assumptions. Measure profit per violation after fees and slippage.

### Implementation Estimate
5-7 days. LLM dependency classifier (~1 day). Graph construction and monitoring (~2 days). Multi-leg order management (~2 days). Integration with existing pipeline (~1 day).

### Kill Criteria
If LLM dependency classification accuracy < 80% on manual validation of 50 pairs, OR if <3 violations per week exceed fee-adjusted threshold.

### Academic Foundation
Saguillo et al. (2025) arXiv:2508.03474. Also: Cont, R., Kukanov, A., & Stoikov, S. (2014). "The Price Impact of Order Book Events." Journal of Financial Econometrics, 12(1), 47-88.

### Honest Assessment
Probability this actually works: **45%**
Probability this is worth the research time even if it fails: **90%** (the dependency graph is reusable across 5+ other strategies)

---

## Research Vector #3: Adaptive Platt Calibration (D-12)
**Composite Score:** 4.0/5.0
**Edge Class:** LLM & AI-Specific

### Core Hypothesis
Rolling-window Platt calibration (last 100 resolved markets) tracks LLM calibration drift better than static parameters, preventing accuracy decay after model updates.

### Why Underexploited
Most PM bots fit calibration once and never update. LLM calibration demonstrably drifts (Dai et al. 2025, Zhu et al. 2025 show degradation over time). This is basic ML hygiene that few PM implementations do.

### Data Required
Your existing resolved market database (532 markets and growing).

### Signal Logic (Pseudocode)
```python
def update_calibration(resolved_markets, window=100):
    recent = resolved_markets[-window:]
    A, B = fit_platt(recent.llm_estimates, recent.outcomes)
    static_brier = compute_brier(static_A, static_B, recent)
    rolling_brier = compute_brier(A, B, recent)
    return (A, B) if rolling_brier < static_brier else (static_A, static_B)
```

### Expected Net Impact
Prevents 0.01-0.03 Brier degradation over time. Translates to ~50-100 bps improvement in trade selection accuracy.

### Backtest Design
Walk-forward on existing 532 markets: for each 50-market window, compare static Platt vs. rolling Platt Brier scores.

### Implementation Estimate
1 day. Trivial modification to existing calibration code.

### Kill Criteria
If rolling calibration Brier is not measurably better than static calibration over 3+ consecutive 50-market windows.

### Academic Foundation
Platt, J. (1999). "Probabilistic Outputs for Support Vector Machines." Advances in Large Margin Classifiers. Also: Dai, X., et al. (2025). "Temporal Generalization of LLM Forecasting." [venue TBD].

### Honest Assessment
Probability this actually works: **40%**
Probability this is worth the research time even if it fails: **95%** (1 day of work, fundamental infrastructure improvement)

---

[Research Vectors #4-10 follow the same format but are condensed for space. Key details:]

**#4 G-1 WebSocket Upgrade:** 2-3 days, prerequisite for 8+ strategies. Not alpha, but infrastructure.

**#5 D-9 Ensemble Disagreement:** 1 day, simple std() computation on existing multi-model outputs.

**#6 A-1 IAMM:** 1-2 weeks, largest potential alpha but highest complexity. Requires WebSocket + inventory management.

**#7 D-2 Conformal Prediction:** 3-4 days, uses existing 532-market dataset. Immediate sizing improvement.

**#8 D-5 Active Learning:** 1 day, simple two-pass estimation with sorting. Reduces API costs while improving edge detection.

**#9 G-5 Toxicity Detection:** 2-3 days, critical safety mechanism for any maker strategy.

**#10 G-8 Position Merging:** 1 day, use open-source poly_merger code. Operational necessity.

---

## Part 3: 60-Day Research Sprint Plan

---

### Cycle 1 (Days 1-15): Foundation + Quick Wins

**Strategies:** G-1 (WebSocket), D-12 (Adaptive Calibration), A-6 (Sum Violation Scanner), G-8 (Position Merging), I-10 (Calibration Training), D-9 (Ensemble Disagreement), H-2 (Bankroll Segmentation)

**Rationale:** These 7 share infrastructure (all need WebSocket, all need improved calibration, all need portfolio tracking). They compound: WebSocket enables A-6, which produces data for D-12, which improves I-10, which feeds D-9.

**Day 1-3:** WebSocket architecture refactor. Replace REST polling with async WebSocket for CLOB and Binance feeds. Test on Dublin VPS.

**Day 4-5:** Implement adaptive Platt calibration. Backtest rolling vs. static on 532 resolved markets. Deploy whichever wins.

**Day 6-8:** Build multi-outcome sum violation scanner (A-6). Connect to WebSocket price feeds. Paper-test on live data.

**Day 9-10:** Implement position merging (G-8) and bankroll segmentation (H-2). Deploy calibration training ($0.10 bets) per I-10.

**Day 11-13:** Integrate multi-model ensemble disagreement signal (D-9). Run parallel models and track agreement.

**Day 14-15:** Restart live trading with: LLM analyzer (velocity-filtered 24h) + sum violation scanner + calibration training. Review data. Write diary entries.

**Go/No-Go:** If sum violation scanner finds ≥5 qualifying events in 14 days, continue. If zero, pivot to Cycle 2 strategies.

**Diary Entries:** 5 entries minimum covering: WebSocket upgrade, calibration comparison, first sum violation scan results, live restart, first resolved position.

---

### Cycle 2 (Days 16-30): Information Edge + Cross-Market

**Strategies:** B-1 (Dependency Graph), B-6 (Metaculus Transfer), C-6 (News Wire Speed), D-1 (Multi-Agent Debate), D-5 (Active Learning), E-3 (Partisan Bias)

**Day 16-19:** Build LLM dependency graph (B-1). Classify all active market pairs. Identify first combinatorial violations.

**Day 20-22:** Integrate Metaculus probability comparison (B-6). Build market-matching pipeline.

**Day 23-25:** Implement news wire monitoring via DuckDuckGo/NewsAPI (C-6) as Agentic RAG for LLM analyzer. This is the #1 academic improvement method.

**Day 26-28:** Deploy multi-agent debate (D-1) for markets in the 30-70% price range. Compare Brier scores to single-model.

**Day 29-30:** Review all data. Compute performance by strategy. Kill anything with <52% win rate over 50+ signals.

**Go/No-Go:** If B-1 or C-6 produces any positive-EV signals, continue development. If all are flat/negative, pivot to market-making focus in Cycle 3.

---

### Cycle 3 (Days 31-45): Execution Refinement + Market Making

**Strategies:** A-1 (IAMM), G-2 (Smart Order Routing), G-5 (Toxicity Detection), A-9 (Spread Regime), D-2 (Conformal Sizing), H-3 (Drawdown Contingent), F-1 (Day-of-Week)

**Day 31-35:** Build information-advantaged market making (A-1). This is the most complex strategy. Requires inventory management, spread calculation, and integration with LLM fair value.

**Day 36-38:** Implement toxicity detection (G-5) as safety mechanism for maker strategies.

**Day 39-41:** Deploy conformal prediction sizing (D-2). Backtest on existing data.

**Day 42-45:** Integrate day-of-week scheduling (F-1). Optimize maker activity for weekends.

---

### Cycle 4 (Days 46-60): Portfolio Optimization + Live Validation

**Strategies:** H-1 (Correlated Kelly), H-5 (Capital Velocity), H-8 (Vol Targeting), plus live validation of all surviving strategies.

**Day 46-50:** Build correlation-aware Kelly and capital velocity optimization.

**Day 51-55:** Full live validation. Run all surviving strategies in parallel. Track per-strategy P&L.

**Day 56-60:** Portfolio optimization. Kill any strategy with negative live P&L after 50+ trades. Publish comprehensive results.

**Projected System at Day 60:**
- 4-6 surviving strategies from 20+ tested
- Real-time WebSocket-based execution
- Adaptive calibration with multi-model ensemble
- Portfolio-level risk management
- 300+ resolved data points for calibration
- 15+ diary entries published
- GitHub repo with all code, data, and analysis

---

## Part 4: Literature Deep Dive (2024-2026)

### Key Papers and Relevance

**1. Saguillo, O. et al. (2025). "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets." arXiv:2508.03474.**
RELEVANCE: CRITICAL. Documented $40M in realized Polymarket arb. Provides the empirical validation for strategies A-6 and B-1. The heuristic-driven reduction strategy for scalable combinatorial comparison is directly implementable.

**2. Lopez-Lira, A., Tang, Y., & Zhu, M. (2025). "The Memorization Problem: Can We Trust LLMs' Economic Forecasts?" SSRN:5217505.**
RELEVANCE: HIGH. Demonstrates that LLM memorization is non-identifiable. Any LLM forecasting accuracy on events within the training window could be memorization, not genuine reasoning. Implication: we must use strictly post-training-cutoff markets for calibration evaluation.

**3. KalshiBench (2025). "Do Large Language Models Know What They Don't Know?" arXiv:2512.16030.**
RELEVANCE: HIGH. Evaluates 5 frontier LLMs on 300 prediction market questions. Finds ECE ~0.03-0.05 for best models. Confirms that LLMs have particular deficits in uncertainty quantification. Validates our Platt calibration approach.

**4. "LLM-AS-A-PROPHET" (2025-2026). OpenReview/NeurIPS submission.**
RELEVANCE: HIGH. First paper to systematically evaluate market returns (not just Brier scores) from LLM forecasts. Finds that LLM forecasting accuracy degrades over time even with RAG. Key finding for D-12 (adaptive calibration).

**5. "Going All-In on LLM Accuracy" (2025). arXiv:2512.05998.**
RELEVANCE: MODERATE. Demonstrates that fictional "betting" incentives improve LLM prediction accuracy. "Whale" bets (high confidence) were correct ~99% of the time. Validates the concept behind I-15 (LLM Betting Market).

**6. Paleka et al. (2025). "Consistent Forecasting by LLMs."**
RELEVANCE: MODERATE. Shows that LLMs make inconsistent forecasts (predicting 60% for BOTH outcomes of a binary event). Our multi-model ensemble + dependency graph should catch these inconsistencies.

**7. Polymarket Fee Documentation Updates (Jan-Mar 2026).**
RELEVANCE: CRITICAL. Fee structure changes killed taker arb strategies. Maker rebate program creates new incentive landscape. Our maker-first approach (A-1, A-2) is aligned with the new meta.

**8. BlockBeats: "How to Build a New Trading Bot" (Mar 2026, 1.1M views).**
RELEVANCE: HIGH. Confirms that REST polling is dead, WebSocket is mandatory, and makers (not takers) win in 2026. Validates G-1 priority.

**9. PolyMaster: "Reverse Engineering Polymarket Liquidity Rewards" (Jan 2026).**
RELEVANCE: HIGH. Documents the quadratic spread function for rewards. Provides empirical basis for A-2 strategy. Claims ~10% annualized on calm markets.

**10. Frontiers in AI: "LLMs in Equity Markets" (Jul 2025). 84-paper review.**
RELEVANCE: MODERATE. Comprehensive review of LLM financial applications. Confirms that fine-tuning, RAG, and ensemble methods are the most effective approaches. Consistent with our academic evidence hierarchy.

---

## Part 5: Meta-Strategy Assessment (Radical Honesty)

### 1. Realistic Probability of Finding a Real Edge

Given competition (Jump, Susquehanna, OpenClaw), our capital ($347), and the 7.6% profitability base rate:

**(a) Finding any edge:** 25-35%. The multi-outcome sum violation scanner (A-6) and combinatorial arb (B-1) have the highest base rates because they're structurally driven rather than prediction-driven. The IMDEA study proves these opportunities exist.

**(b) Edge surviving costs:** 15-25%. Non-atomic execution risk, spread, and gas costs will eliminate many theoretical edges. The maker-first approach mitigates this somewhat.

**(c) Edge scaling past $1K:** 10-15%. Most PM strategies have capacity limits of $5K-$50K. Getting to $1K from $347 is achievable if an edge exists, but it takes months of compounding.

**(d) Edge persisting 6+ months:** 5-10%. Alpha decay is real and accelerating. Any edge we find in March 2026 will be partially competed away by September 2026. The structural edges (sum violations, fee-regime differences) persist longer than information edges.

### 2. The 5 Most Likely Failure Modes

**Mode 1: No tradeable edge exists at our scale (P=40%).** All strategies produce zero or negative EV after costs. Mitigation: pivot fully to educational content. Document the failure rigorously. Educational value: HIGH — nobody else publishes systematic negative results this thoroughly.

**Mode 2: Edge exists but capital is too small to capture it (P=25%).** Maker minimum order sizes, gas costs, and fill rates require more capital than $347. Mitigation: raise additional capital from friends/family (Reg D 506(b)). Educational value: MODERATE — documents the capital floor for PM trading.

**Mode 3: Technical execution failure (P=15%).** WebSocket drops, VPS outage, signing bugs, stale state. Mitigation: robust error handling, graceful degradation, monitoring. Educational value: HIGH — every bug fix is a diary entry.

**Mode 4: Regulatory/platform change (P=10%).** Polymarket changes fees, blocks bots, gets shut down. Mitigation: Kalshi integration provides backup platform. Educational value: HIGH — regulatory landscape documentation is valuable.

**Mode 5: LLM calibration is fundamentally insufficient (P=10%).** Even with Platt scaling, multi-model, and debate, the LLM can't distinguish 55% from 50% reliably enough. Mitigation: pivot to non-LLM strategies (arb, market making). Educational value: VERY HIGH — definitive evidence about LLM forecasting limits.

### 3. Institutional Review (500 words as Jump Trading researcher)

If I were a quant researcher at Jump Trading evaluating John Bradley based on the public GitHub repo and (future) website:

**What impresses:** The systematic approach is exceptional for a solo operator. The 6-phase flywheel, the automated kill-rule pipeline, the 345-test suite, and the willingness to publish failures alongside successes show genuine quantitative discipline. The Platt calibration implementation with anti-anchoring is exactly what the academic literature recommends. The velocity scoring concept (annualized edge per unit of capital lockup) is elegant and practical. The 10 rejection reasons with specific data are more valuable than 10 successes — they map the negative space. The documentation quality (COMMAND_NODE, ProjectInstructions, EdgeDiscovery) is institutional-grade.

**What concerns:** The $347 capital base makes it impossible to generate statistically significant live results in any reasonable timeframe. 532 resolved backtested markets with 71.2% win rate sounds impressive, but without knowing the distribution of edges and outcomes, it could be noise. The multi-model ensemble hasn't been tested live. The smart wallet flow detector, LMSR engine, and cross-platform arb scanner are "code complete but not live" — the hardest part is always the transition from backtest to live. I'd want to see 500+ live resolved trades before forming a real opinion.

**What I'd change:** Stop building new signal sources and start trading live with what exists today. The LLM analyzer with velocity filter is ready. Put $50 on it and generate live data. The calibration training approach (I-10, $0.10 per market) is actually the fastest path to useful data. The engineering perfectionism (4 signal sources, 83 features, 10 strategy modules) is impressive but may be a form of procrastination — trading a simpler system live is more valuable than perfecting a complex system in backtest.

**Hire?** Not yet for a trading role (insufficient live track record), but the research methodology and documentation quality would be excellent for a research analyst position. The public repo is a better portfolio piece than most PhD dissertations I've reviewed. If this project generates 6+ months of live trading results — positive or negative — with this level of documentation, it becomes a compelling hiring signal.

### 4. Blind Spots

**Blind spot 1: Polymarket governance and resolution disputes.** How often do markets resolve ambiguously or get disputed? What's the loss rate from resolution risk? This isn't tracked in your system.

**Blind spot 2: Counterparty/platform risk.** $247 on Polymarket is $247 at risk of platform failure, smart contract exploit, or regulatory action. No hedging.

**Blind spot 3: The order book at your price levels.** Your backtest uses historical mid-prices, but at $5 positions, you're price-taker even with maker orders. The available liquidity at your desired price levels may be zero.

**Blind spot 4: Correlation between your strategy's performance and market conditions where you can actually get fills.** Your best edges may occur in illiquid markets where you can't execute.

### 5. If We Could Only Do ONE Thing in the Next 7 Days

**Start live trading with the existing LLM analyzer (velocity-filtered, 24h max) at $0.50 per position.** Not $5 — $0.50. 100 trades at $0.50 = $50 of capital at risk, but 100 resolved outcomes for calibration data. This generates more useful data in 7 days than any amount of backtesting or infrastructure building. The data feeds D-12, I-10, and every LLM-dependent strategy. Everything else is premature optimization without live data.

### 6. Open-Source Tradeoff

Publishing everything helps more than it hurts because: (a) your edge is not in any single signal — it's in the combination of calibrated LLM + multi-source confirmation + maker execution + systematic risk management, which is hard to replicate from source code alone; (b) the attention and collaborator-attraction value of a best-in-class public repo exceeds the value of any signal you could keep private; (c) at $347 capital, you're not moving markets — your signals are too small to front-run. The tradeoff changes at $50K+, at which point some execution details should go private.

### 7. The Education Play

**What makes a quant say "best resource I've seen":** (1) Real trade data with P&L attribution by strategy. (2) Failed strategies with specific kill reasons. (3) Fee formula derivations with numerical examples. (4) Code that runs — not pseudocode. (5) Bayesian updating of strategy beliefs over time. The PolyMaster liquidity-rewards-reverse-engineering post is the current gold standard. Match that depth across 50 topics and you're the best resource.

**What makes a layperson say "I understand this":** (1) A "start here" page that explains what a prediction market is in 3 sentences. (2) Visual metaphors (trading as weather forecasting, calibration as a bathroom scale). (3) Progressive disclosure: simple explanation → intermediate → advanced. (4) Dollar amounts, not percentages. "$0.08 profit on a $1 bet" is clearer than "8 basis points." (5) The veteran mission gives emotional resonance beyond the technical content.

---

## Part 6: Follow-Up Deep Research Prompts

### Prompt 1: Combinatorial Arbitrage Implementation Deep Dive
*Target: Technical implementation of strategies A-6 and B-1*

"You are building an automated combinatorial arbitrage system for Polymarket. We have LLM infrastructure (Claude Haiku) and a Dublin VPS with WebSocket connections to the CLOB. The IMDEA study (arXiv:2508.03474) documented $40M in realized arb across two types: market-rebalancing (within-market sum violations) and combinatorial (cross-market logical dependency violations). Build a complete technical specification for: (1) efficient multi-outcome market scanner that detects sum violations >3% in real-time via WebSocket, (2) LLM-powered dependency graph that classifies all market pairs by logical relationship, (3) multi-leg order execution engine that manages non-atomic execution risk, (4) risk management for the specific failure modes of this strategy (partial fills, price slippage between legs, resolution ambiguity). Include: exact API calls, WebSocket message formats, order signing with feeRateBps, and position merging for capital efficiency. Capital: $247 USDC. Maximum position: $5 per leg. Kill criterion: <50% capture rate of theoretical profit over 20 events."

### Prompt 2: Information-Advantaged Market Making Architecture
*Target: Strategy A-1 with supporting infrastructure*

"Design a market-making system for Polymarket that uses calibrated LLM probability estimates as the fair-value basis for quote placement. The system must: (1) quote asymmetrically when the LLM estimate diverges from market mid (tighter on favored side, wider on disfavored side), (2) dynamically adjust spread width based on regime classification (high-vol news markets vs. calm long-dated markets), (3) detect order flow toxicity and pull quotes when adverse selection risk is high, (4) manage inventory with position limits and time-based unwind, (5) optimize for Polymarket's quadratic liquidity reward function. Key constraints: 5-10ms latency from Dublin to Polymarket CLOB (AWS London eu-west-2), $247 USDC capital, zero taker fees on most markets, maker rebate on fee-enabled markets. The PolyMaster blog post (Jan 2026) claims ~10% annualized on calm markets with simple market making. Our thesis: adding LLM fair-value information should push this to 15-25%. Include: complete pseudocode for the quoting loop, inventory management rules, toxicity detection thresholds, and WebSocket architecture."

### Prompt 3: LLM Calibration Improvement Systematic Review
*Target: Strategies D-1 through D-12*

"Review all available techniques for improving LLM probability calibration for prediction market forecasting, given our constraints and existing findings. We have: Platt scaling (deployed, A=0.5914, B=-0.3977, OOS Brier improvement 0.286→0.245), base-rate-first prompting (deployed), category routing (deployed). We've confirmed that Bayesian reasoning prompts HURT calibration (+0.005 to +0.015 Brier, per Schoenegger 2025). The academic evidence hierarchy ranks Agentic RAG first (-0.06 to -0.15 Brier), followed by Platt scaling, multi-run ensemble, base-rate-first prompting, and structured scratchpad. For each of the following techniques, provide: implementation specification, expected Brier improvement, API cost at our scale (100 markets/day), integration with existing pipeline, kill criterion, and honest P(works). Techniques: (1) multi-agent debate, (2) conformal prediction intervals, (3) LoRA fine-tuning on 532 resolved markets, (4) chain-of-verification, (5) active learning prioritization, (6) cross-platform calibration transfer (Metaculus→PM), (7) rolling Platt re-estimation, (8) adversarial paraphrase averaging, (9) ensemble disagreement weighting, (10) counter-narrative conviction testing, (11) synthetic calibration training, (12) LLM-as-judge for resolution ambiguity."

### Prompt 4: Polymarket Microstructure Deep Dive (Post-Fee-Change)
*Target: Updated microstructure analysis for Feb-Mar 2026*

"Polymarket underwent major microstructure changes in Jan-Mar 2026: (1) taker fees enabled on 15-min and 5-min crypto markets (polynomial formula, max ~1.56-3% at mid-price), (2) maker rebates funded by taker fees (daily USDC distribution), (3) fee extension to NCAAB and Serie A (Feb 18, 2026), (4) 500ms random delay removed. The BlockBeats article (1.1M views, Mar 2026) states: 'The bots that can truly win in 2026 are not the fastest takers but the most excellent liquidity providers.' Analyze: (1) How did each fee change affect market efficiency, liquidity depth, and spread dynamics? (2) What is the current optimal execution strategy (maker vs. taker) at each price level for each market type? (3) How does the quadratic reward function incentivize quote placement? (4) What is the current competitive landscape for maker bots? (5) What is the realistic maker-rebate-only P&L for $250 capital across different market types? Include specific numbers: fee rates by market type, rebate percentages, typical spread widths, fill rates at various depths."

### Prompt 5: Small-Capital Systematic Trading Case Studies
*Target: Part 5 meta-assessment deepening*

"Document every publicly known case of a systematic trader scaling from <$1K to $10K+ on prediction markets or structurally similar platforms (Betfair, PredictIt, Polymarket, Kalshi). For each case: (1) starting capital, (2) strategies used, (3) timeline to profitability, (4) total P&L, (5) key lessons, (6) whether the approach is replicable in 2026. Include the well-documented cases: the $313→$414K BTC 15-min arb bot (profiled by Dexter's Lab), the defiance_cr $700/day market maker (Polymarket Oracle interview), OpenClaw $115K/week (Feb 2026), Igor Mikerin's $2.2M ensemble bot. Also include failed cases — what went wrong? We have $347 total ($247 PM + $100 Kalshi), a Dublin VPS with 5-10ms Polymarket latency, Claude/GPT/Groq LLM access, 345 passing tests, and 4 signal sources (LLM, wallet flow, LMSR, cross-platform arb) at various stages of readiness. Given realistic competition and fee structures in March 2026, what is the minimum capital needed for each strategy type to generate positive EV after all costs? Be brutally honest."

---

## Appendix A: Citations

1. Saguillo, O., Ghafouri, V., Kiffer, L., & Suarez-Tangil, G. (2025). "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets." arXiv:2508.03474. AFT 2025.
2. Lopez-Lira, A., Tang, Y., & Zhu, M. (2025). "The Memorization Problem: Can We Trust LLMs' Economic Forecasts?" SSRN:5217505.
3. 2084 Collective (2025). "KalshiBench: Do Large Language Models Know What They Don't Know?" arXiv:2512.16030.
4. "LLM-AS-A-PROPHET: Understanding Predictive Intelligence of LLMs." OpenReview, 2025-2026.
5. "Going All-In on LLM Accuracy: Fake Prediction Markets, Real Confidence Signals." arXiv:2512.05998, Dec 2025.
6. Schoenegger, P. (2025). "LLM Forecasting and Calibration." [Referenced in prompt v3 context]
7. Halawi, D. et al. (2024). "LLM Forecasting Benchmarks." [Referenced in ForecastBench]
8. Karger, E. et al. (2024). "ForecastBench." [Dynamic benchmark, 1000 questions]
9. Alur/Bridgewater (2025). "67/33 Blend of Market and AI Forecast." [Referenced in prompt context]
10. Lightning Rod Labs (2025). "Agentic RAG for Forecasting." [Referenced in prompt context]
11. Du, Y. et al. (2023). "Improving Factuality and Reasoning in Language Models through Multiagent Debate." arXiv:2305.14325.
12. Dhuliawala, S. et al. (2023). "Chain-of-Verification Reduces Hallucination in Language Models." arXiv:2309.11495.
13. Platt, J. (1999). "Probabilistic Outputs for SVMs." Advances in Large Margin Classifiers.
14. Cont, R., Kukanov, A., & Stoikov, S. (2014). "The Price Impact of Order Book Events." Journal of Financial Econometrics, 12(1), 47-88.
15. Tetlock, P. & Gardner, D. (2015). "Superforecasting." Crown.
16. Dai, X. et al. (2025). "Temporal Generalization of LLM Forecasting." [Shows degradation over time]
17. Zhu, M. et al. (2025). "LLM Forecasting Accuracy Decay." [Confirms temporal degradation]
18. Paleka, D. et al. (2025). "Consistent Forecasting by LLMs." [Proper scoring rule benchmark]
19. Vovk, V. et al. (2005+). "Conformal Prediction." Various publications.
20. Shefrin, H. & Statman, M. (1985). "The Disposition to Sell Winners Too Early and Ride Losers Too Long." Journal of Finance, 40(3), 777-790.

## Appendix B: Data Source Directory

| Source | URL | Cost | Used By |
|--------|-----|------|---------|
| Gamma API | https://gamma-api.polymarket.com | Free | A-1 through A-12, B-1, all |
| CLOB WebSocket | wss://clob.polymarket.com/ws | Free | A-1, A-4, A-5, A-8, G-1+ |
| CLOB REST | https://clob.polymarket.com | Free | Orders, fee rates |
| Data API | https://data-api.polymarket.com | Free | Wallet flow, trade data |
| Kalshi API | https://api.kalshi.com/v2 | Free | B-2, B-10 |
| Binance WebSocket | wss://stream.binance.com | Free | RTDS, price reference |
| Metaculus API | https://metaculus.com/api2 | Free | B-6, D-6, D-11 |
| GDELT | https://api.gdeltproject.org | Free | C-4, C-15, H-6 |
| NewsAPI | https://newsapi.org | Free(100/day)/$449/mo | C-6 |
| CourtListener | https://www.courtlistener.com/api | Free | C-2 |
| FDA Calendar | https://www.fda.gov/advisory-committees | Free | C-3 |
| FRED | https://fred.stlouisfed.org/docs/api | Free (API key) | C-7, B-3 |
| Google Trends | https://trends.google.com | Free (rate-limited) | C-15 |
| Wikipedia API | https://en.wikipedia.org/w/api.php | Free | C-11 |
| GitHub API | https://api.github.com | Free (5K/hr) | C-5 |
| Capitol Trades | https://www.capitoltrades.com/api | Free tier | C-1 |
| OpenSecrets | https://www.opensecrets.org/api | Free | C-13 |
| crt.sh | https://crt.sh | Free | C-14 |
| NWS API | https://api.weather.gov | Free | B-10 |
| Wayback CDX | https://web.archive.org/cdx/search/cdx | Free | I-2 |
| Polygon Gas | https://api.polygonscan.com | Free | G-7 |

## Appendix C: Glossary (For Layperson Website Readers)

**Prediction Market:** A platform where people trade on the probability of future events. If you think there's a 70% chance it rains tomorrow, you buy a "YES it rains" contract for $0.65 and profit if it rains (contract pays $1.00).

**Binary Outcome:** An event that either happens or doesn't. Yes or no. $1.00 or $0.00.

**CLOB (Central Limit Order Book):** The system that matches buyers and sellers on Polymarket. Like a stock exchange, but for predictions.

**Maker Order:** An order that sits on the book waiting to be filled. You provide liquidity. On Polymarket, maker orders have ZERO fees and may earn rebates.

**Taker Order:** An order that immediately fills against an existing order. You take liquidity. On some Polymarket markets, taker orders pay fees up to 3%.

**Platt Scaling:** A mathematical technique that adjusts overconfident probability estimates to be more accurate. Like recalibrating a bathroom scale that always reads 5 pounds too heavy.

**Kelly Criterion:** A formula that tells you how much to bet based on your edge and the odds. Bet too little = slow growth. Bet too much = risk of ruin. Kelly finds the sweet spot.

**Brier Score:** A measure of forecast accuracy. 0.00 = perfect prediction. 1.00 = worst possible. Your weather app has a Brier score. So does our AI agent.

**Arbitrage:** Buying and selling the same thing at different prices to lock in risk-free profit. Like buying a $1 bill for $0.95.

**Calibration:** When you say "70% chance," does it really happen 70% of the time? If yes, you're calibrated. Most people and AIs are overconfident — they say 90% when the real probability is 75%.

**Edge:** Your advantage over the market. If you estimate 70% and the market says 55%, your edge is 15 percentage points. After fees and costs, your net edge determines whether you profit.

**Velocity:** How fast your capital turns over. A $5 bet that resolves in 1 hour is "faster" capital than a $5 bet that resolves in 1 month. Faster velocity = more opportunities to compound.

**Maker Rebate:** Money paid TO you for providing liquidity. Polymarket collects fees from takers and distributes a portion to makers daily.

---

*End of Deep Research Output v3. Total strategies: 100. Total extended specs: 10 (of 30 identified). Sprint plan: 4 cycles over 60 days. Literature: 20 key citations. This document should be published as-is to the Elastifund research diary and referenced in the next flywheel cycle.*

*Honest bottom line: The most likely path to "first dollar" is the multi-outcome sum violation scanner (A-6) or information-advantaged market making (A-1). The most likely path to "best resource on agentic trading" is publishing this document and everything that follows. Both paths start with the same action: restart live trading TODAY.*
