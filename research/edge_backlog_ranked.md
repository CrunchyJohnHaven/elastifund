# Edge Strategy Discovery System — Ranked Backlog

**Version:** 1.0.0
**Date:** 2026-03-05
**Purpose:** 30 concrete, implementable edge strategies ranked by expected impact. Top 10 include full one-page deep dives. Claude Code can pick the top 3 and begin implementation immediately.

---

## Ranking Methodology

Each edge scored on four dimensions (1–5 scale):

| Dimension | Weight | Definition |
|-----------|--------|-----------|
| **Edge Magnitude** | 30% | Expected alpha above taker fee breakeven |
| **Data Availability** | 25% | Can we get the data programmatically, cheaply, now? |
| **Implementation Ease** | 25% | Engineer-hours to deploy to production |
| **Durability** | 20% | How long before competition erodes this? |

**Composite Score** = weighted sum, max 5.0.

---

## Full Backlog: 30 Edges Ranked

| Rank | Edge Name | Category | Mechanism | Composite | Data Feed | Est. Alpha |
|------|-----------|----------|-----------|-----------|-----------|------------|
| 1 | NOAA Multi-Model Weather Consensus | Weather | GFS+ECMWF+HRRR ensemble beats single-source NOAA | 4.6 | NWS API (free) | 15–30% |
| 2 | Polling Aggregator Divergence (Political) | Politics | FiveThirtyEight/RCP aggregate vs PM price, lagged | 4.5 | 538 API, RCP scrape | 8–15% |
| 3 | Favorite-Longshot Bias Exploitation (NO-side) | All | Structural: crowd overpays for YES on unlikely events | 4.4 | Internal calibration data | 10–20% |
| 4 | Government Data Release Front-Running | Economic | FRED/BLS releases move markets; pre-position on consensus | 4.3 | FRED API (free) | 10–25% |
| 5 | Multi-Model LLM Ensemble | All | Claude+GPT+Grok median estimate > any single model | 4.3 | OpenAI, xAI APIs | 5–12% |
| 6 | News Sentiment Spike Detection | Politics/Econ | NewsData.io sentiment shift > 2σ from baseline | 4.2 | NewsData.io ($49/mo) | 8–18% |
| 7 | Google Trends Surge Detector | All | Search volume spike > 3× 30d avg correlates with resolution direction | 4.1 | Google Trends API (free) | 5–15% |
| 8 | Wikipedia Pageview Anomaly | Politics/Geopolitical | Pageview spike on entity precedes PM move by 4–12h | 4.0 | Wikimedia API (free) | 5–12% |
| 9 | Resolution Rule Misread Arbitrage | All | Market price ignores exact resolution criteria wording | 4.0 | Gamma API (existing) | 10–40% (rare) |
| 10 | Time Decay / Theta Harvesting | All | Markets near expiry converge; sell premium on far-OTM | 3.9 | Gamma API (existing) | 5–15% |
| 11 | **Sentiment/Contrarian Dumb Money Fade** | **All (best: crypto, meme)** | **Monitor extreme retail sentiment (Reddit, AAII, CNN F&G, put/call) and fade the herd. Boost edge when Claude is contrarian to crowd; reduce when aligned.** | **3.5** | **Reddit API, AAII (free), CNN F&G (free), Twitter ($100/mo)** | **5–15%** |
| 12  | Calibration Bin Specialization | All | Only trade in Claude's best-calibrated bins (10–30%, 40–50%) | 3.8 | Internal | 5–10% |
| 12 | Opening Line vs Closing Line Drift | Politics | Initial price vs 48h-later price reveals systematic overreaction | 3.7 | Gamma historical (scrape) | 5–12% |
| 13 | ECMWF vs GFS Divergence (Weather) | Weather | When weather models disagree, one is usually right | 3.7 | Open-Meteo API (free) | 10–20% |
| 14 | Congressional Voting Record Predictor | Politics | GovTrack vote history predicts legislative outcome markets | 3.6 | GovTrack API (free) | 8–15% |
| 15 | Earnings Surprise Momentum | Economic | Post-earnings estimate revisions predict related PM markets | 3.6 | FRED + Finnhub ($0) | 5–10% |
| 16 | Cross-Platform Price Divergence | All | Polymarket vs Kalshi vs Metaculus spread > 5% | 3.5 | Kalshi API, Metaculus API | 3–8% |
| 17 | Social Sentiment Cascade (Twitter/X) | Politics | Viral tweet → sentiment shift → PM move (4–8h lag) | 3.5 | Twitter API ($100/mo) | 5–15% |
| 18 | Order Book Imbalance Signal | All | Bid/ask depth ratio > 3:1 predicts short-term direction | 3.4 | Polymarket CLOB API | 3–8% |
| 19 | Expert Forecast Aggregation (Metaculus) | Science/Tech | Metaculus community median vs PM price divergence | 3.4 | Metaculus API (free) | 5–10% |
| 20 | Seasonal Weather Pattern | Weather | Historical base rates for temp/precip by city/month | 3.3 | NOAA historical (free) | 5–15% |
| 21 | Fed Funds Futures Implied Probability | Economic | CME FedWatch tool probability vs PM rate-cut markets | 3.3 | CME API / scrape | 3–8% |
| 22 | Geopolitical Event Escalation Model | Geopolitical | ACLED conflict data + diplomatic signals → escalation probability | 3.2 | ACLED API (free for research) | 5–15% |
| 23 | Insider Wallet Activity (On-chain) | All | Large Polymarket wallet clustering → informed trader signal | 3.1 | Polygon blockchain data | 3–10% |
| 24 | Regression to Base Rate (New Markets) | All | New markets overshoot; fade toward historical category base rate | 3.1 | Internal + Gamma API | 3–8% |
| 25 | Liquidity-Weighted Confidence | All | High-liquidity markets are better calibrated; size accordingly | 3.0 | Gamma API (existing) | 2–5% |
| 26 | Category Momentum (Winners Keep Winning) | Politics | If political category has >70% hit rate trailing 2 weeks, increase sizing | 2.9 | Internal data | 2–5% |
| 27 | Pre-Resolution Exit (Sell at 90%+) | All | Exit positions at 90%+ implied probability instead of waiting for resolution | 2.9 | Gamma API (existing) | Capital velocity gain |
| 28 | Stale Market Detection | All | Markets with no volume for 48h+ are likely mispriced | 2.8 | Gamma API (existing) | 3–10% |
| 29 | Deadline Convergence Trading | All | Markets converge to 0/100 as deadline approaches; trade momentum | 2.7 | Gamma API (existing) | 2–5% |
| 30 | Prompt A/B Rotation | All | Rotate prompt variants; track which yields best calibration by category | 2.6 | Internal | 1–3% |

---

## Top 10 Deep Dives

---

### Edge #1: NOAA Multi-Model Weather Consensus

**Mechanism of Edge:** Polymarket weather markets are priced off vibes and single-source data. Retail traders check one weather app. We aggregate GFS (NOAA), ECMWF (European model, gold standard), and HRRR (high-res rapid refresh, 3km resolution, hourly updates) into a consensus probability. When all three models agree and the market disagrees, the edge is enormous. Weather model disagreement itself is also a signal — when models diverge, the market typically misprices uncertainty.

**Required Data Feeds:**
- NWS API (`api.weather.gov`) — free, no key, already partially implemented
- Open-Meteo API (`open-meteo.com`) — free, provides GFS + ECMWF + ICON
- HRRR data via NOAA NOMADS or AWS Open Data (free)

**How to Detect Signal in Code:**
```python
# Pseudocode
gfs_prob = get_gfs_forecast(city, metric, threshold)
ecmwf_prob = get_ecmwf_forecast(city, metric, threshold)
hrrr_prob = get_hrrr_forecast(city, metric, threshold)
consensus = weighted_average(gfs=0.3, ecmwf=0.4, hrrr=0.3)
market_price = get_polymarket_price(market_id)
if abs(consensus - market_price) > 0.15:
    signal = "BUY_YES" if consensus > market_price else "BUY_NO"
```

**Backtest Approach:** Collect 90 days of historical weather market resolutions from Gamma API. For each, reconstruct what GFS/ECMWF/HRRR forecasted 48h before resolution. Compare consensus vs market price at that point. Measure hit rate and P&L.

**Success Criteria:** Win rate > 80% on weather markets. Edge magnitude > 15%. At least 5 tradeable weather markets per week.

**Risk/Failure Modes:** Weather markets may have insufficient liquidity (<$100). Polymarket may not list enough weather markets. ECMWF data access may require paid subscription for real-time. HRRR only covers CONUS.

---

### Edge #2: Polling Aggregator Divergence (Political)

**Mechanism of Edge:** Political prediction markets are driven by narrative and recency bias. Polling aggregators (FiveThirtyEight, RealClearPolitics) mathematically weight hundreds of polls, correcting for house effects and methodology. When the aggregator's implied probability diverges from the Polymarket price by >5%, the aggregator is usually right because it incorporates more information.

**Required Data Feeds:**
- FiveThirtyEight polling averages (public JSON endpoints)
- RealClearPolitics averages (scrape or RSS)
- Polymarket political market prices (Gamma API, existing)

**How to Detect Signal in Code:**
```python
# Map Polymarket political markets to polling topics
polling_avg = get_538_average(topic)  # e.g., presidential approval, generic ballot
implied_prob = polling_to_probability(polling_avg, market_type)
market_price = get_polymarket_price(market_id)
edge = implied_prob - market_price
if abs(edge) > 0.05:
    signal = "BUY_YES" if edge > 0 else "BUY_NO"
```

**Backtest Approach:** Collect all resolved political markets from Gamma API (2024–2026). For each, retrieve the 538/RCP average at the time the market was open. Compare implied probability from polls vs market price. Measure directional accuracy.

**Success Criteria:** Win rate > 70% on political markets where polling diverges > 5%. Minimum 10 applicable markets per month.

**Risk/Failure Modes:** Mapping Polymarket questions to poll questions requires manual curation. Some political markets have no polling equivalent. Polls themselves can be wrong (2016, 2020 polling misses). Markets may already incorporate polling data (efficient market hypothesis for political markets).

---

### Edge #3: Favorite-Longshot Bias Exploitation (NO-side)

**Mechanism of Edge:** This is our existing core edge, documented in the backtest. Prediction market participants systematically overprice low-probability events (longshots) and underprice high-probability events (favorites). The psychological mechanism is well-documented in behavioral finance: people overweight vivid, exciting outcomes. Our 76.2% NO win rate vs 55.8% YES win rate across 532 markets confirms this bias is structural and exploitable.

**Required Data Feeds:**
- Calibration log (internal, already exists)
- Gamma API market prices (existing)

**How to Detect Signal in Code:**
Already implemented in `claude_analyzer.py` with asymmetric thresholds (YES: 15%, NO: 5%). Enhancement: add a pure statistical layer that calculates the historical base rate for the market's category and adjusts Claude's estimate toward the base rate.

**Backtest Approach:** Already done — 532 markets. Enhancement: segment by category, time-to-resolution, and liquidity level to find the sweetest spots within the NO-bias universe.

**Success Criteria:** Maintain >70% NO-side win rate in live trading over 100+ trades. Edge stable across categories.

**Risk/Failure Modes:** As more AI bots exploit this bias, the favorite-longshot effect may shrink. Monitoring: track NO-side win rate weekly; if it drops below 65% for 3 consecutive weeks, reassess sizing.

---

### Edge #4: Government Data Release Front-Running

**Mechanism of Edge:** Markets like "Will unemployment exceed 4.5% in March?" or "Will CPI exceed 3%?" resolve based on official government releases. The market price reflects retail sentiment, which often diverges from the economist consensus (published in FRED/Bloomberg surveys). By ingesting the consensus estimate from FRED and comparing to market price 24–48h before the release, we can pre-position when the market is wrong relative to expert consensus.

**Required Data Feeds:**
- FRED API (`fred.stlouisfed.org`) — free with API key
- BLS release calendar (`bls.gov/schedule`)
- Econoday or Bloomberg consensus survey (may need scraping)

**How to Detect Signal in Code:**
```python
# For each economic market nearing resolution
consensus_estimate = get_fred_consensus(series_id)  # e.g., UNRATE, CPIAUCSL
market_price = get_polymarket_price(market_id)
resolution_threshold = parse_market_question(market)  # e.g., "> 4.5%"
consensus_prob = estimate_probability(consensus_estimate, threshold, historical_std)
if abs(consensus_prob - market_price) > 0.08:
    signal = generate_signal(consensus_prob, market_price)
```

**Backtest Approach:** Collect all resolved economic markets. For each, pull the FRED consensus estimate available 48h before the release date. Convert to implied probability. Compare vs market price at T-48h.

**Success Criteria:** Win rate > 70% on economic release markets. Average edge > 10%.

**Risk/Failure Modes:** Consensus estimate is public — sophisticated traders already trade on it. Edge may only exist when consensus is wrong (which is the surprise element). Limited to ~10–15 economic release events per month.

---

### Edge #5: Multi-Model LLM Ensemble

**Mechanism of Edge:** Academic research (Halawi et al. 2024, NeurIPS) demonstrated that combining multiple LLM probability estimates produces a "wisdom of LLM crowds" effect that matches human crowd accuracy. Individual model biases cancel out: Claude is overconfident on YES; GPT may be overconfident on NO; the median or trimmed mean is closer to truth.

**Required Data Feeds:**
- Anthropic API (existing) — Claude Haiku for speed
- OpenAI API — GPT-4o-mini ($0.15/1M tokens)
- xAI API — Grok-2-mini (competitive pricing)

**How to Detect Signal in Code:**
```python
# Anti-anchoring: all models estimate blind (no market price)
claude_est = get_claude_estimate(market_question, context)
gpt_est = get_gpt_estimate(market_question, context)
grok_est = get_grok_estimate(market_question, context)
# Median is more robust than mean to outlier estimates
ensemble_est = median(claude_est, gpt_est, grok_est)
# Apply calibration to ensemble
calibrated = apply_calibration(ensemble_est)
edge = abs(calibrated - market_price)
```

**Backtest Approach:** Re-run 532-market backtest with all three models. Compare individual Brier scores and ensemble Brier score. Compute edge and P&L for ensemble vs best single model.

**Success Criteria:** Ensemble Brier score < 0.220 (vs Claude alone at 0.239). Win rate improvement > 3% absolute.

**Risk/Failure Modes:** API cost triples (~$60/month). Latency increases (3 API calls per market). Models may agree on wrong answer (correlated failures, especially on novel events). Grok API may have different availability.

---

### Edge #6: News Sentiment Spike Detection

**Mechanism of Edge:** Breaking news moves prediction markets, but with a lag of 1–6 hours for many retail-heavy markets. A real-time news sentiment pipeline can detect significant shifts (> 2 standard deviations from rolling baseline) before they're fully priced in. This is especially powerful for political and economic markets where news is the primary resolution driver.

**Required Data Feeds:**
- NewsData.io ($49/month for 30,000 requests) — real-time news with sentiment
- Alternative: Finnhub news sentiment (free tier: 60 calls/min)
- Alternative: GDELT Project (free, massive, academic)

**How to Detect Signal in Code:**
```python
# Continuous background process
articles = fetch_newsdata(keywords_from_open_markets, last_1h)
for market_id, relevant_articles in group_by_market(articles):
    sentiment_score = compute_aggregate_sentiment(relevant_articles)
    baseline = get_rolling_baseline(market_id, window_days=7)
    z_score = (sentiment_score - baseline.mean) / baseline.std
    if abs(z_score) > 2.0:
        market_price = get_polymarket_price(market_id)
        direction = "YES" if z_score > 0 else "NO"
        trigger_fast_analysis(market_id, direction, articles)
```

**Backtest Approach:** Use GDELT historical data (free) to reconstruct sentiment around resolved markets. Measure: does a sentiment spike >2σ predict resolution direction? What's the lag?

**Success Criteria:** Sentiment signal predicts direction >65% of the time. Signal leads market move by >2 hours on average.

**Risk/Failure Modes:** News sentiment is noisy — many false positives. Sophisticated traders already trade on news (Bloomberg terminal users). Cost scales with number of markets monitored. Sentiment analysis may misinterpret sarcasm or complex narratives.

---

### Edge #7: Google Trends Surge Detector

**Mechanism of Edge:** Search interest spikes precede prediction market price movements. When search volume for a topic triples its 30-day average, it typically means new information is entering the public consciousness that hasn't yet been priced into prediction markets. Research on Wikipedia pageviews and Google Trends shows 4–24 hour leading indicator properties for event markets.

**Required Data Feeds:**
- Google Trends API via `pytrends` library (free, rate-limited)
- Map open markets to search terms (one-time curation + LLM auto-mapping)

**How to Detect Signal in Code:**
```python
# Daily scan (Google Trends data has 24h granularity)
for market in open_markets:
    search_terms = map_market_to_terms(market)  # LLM-assisted
    trend_data = pytrends.get_interest_over_time(search_terms, timeframe='now 7-d')
    current = trend_data.iloc[-1]
    rolling_avg = trend_data.iloc[:-1].mean()
    surge_ratio = current / rolling_avg
    if surge_ratio > 3.0:
        # High surge = new information entering
        trigger_reanalysis(market, surge_context=trend_data)
```

**Backtest Approach:** For 100 resolved markets, retrieve Google Trends data for the 7 days before resolution. Measure: did a >3× surge occur? If so, did the resolution direction align with the surge direction?

**Success Criteria:** Surge detection → correct direction >60% of the time. At least 10 actionable surges per month.

**Risk/Failure Modes:** Google Trends rate limits aggressively. Data is only daily resolution (no intraday). Mapping markets to search terms is imperfect. Not all surges are informative (meme surges vs substantive surges).

---

### Edge #8: Wikipedia Pageview Anomaly

**Mechanism of Edge:** Wikipedia pageview spikes are one of the cleanest leading indicators for event-driven markets. When pageviews for a politician, policy topic, or geopolitical entity spike >5× baseline, it reliably precedes resolution-relevant events by 4–12 hours. Unlike Google Trends, Wikimedia provides hourly granularity and clean API access.

**Required Data Feeds:**
- Wikimedia Pageview API (`wikimedia.org/api/rest_v1/`) — free, no key required
- Mapping: market question → relevant Wikipedia article(s)

**How to Detect Signal in Code:**
```python
# Hourly check
for market in open_markets:
    wiki_articles = map_market_to_wiki(market)  # LLM maps question to article titles
    for article in wiki_articles:
        hourly_views = get_pageviews(article, last_72h, granularity='hourly')
        baseline = hourly_views[:-6].mean()
        current = hourly_views[-6:].mean()  # last 6 hours
        if current / baseline > 5.0:
            trigger_reanalysis(market, wiki_spike=True)
```

**Backtest Approach:** For 200 resolved markets, map to Wikipedia articles. Retrieve pageview data for the week before resolution. Identify spikes. Measure correlation with resolution direction.

**Success Criteria:** Spike detection → correct resolution direction >65%. Lead time > 4 hours.

**Risk/Failure Modes:** Mapping markets to Wikipedia articles requires curation. Some markets have no Wikipedia equivalent. Vandalism or bot traffic can create false spikes. Only useful for markets with identifiable Wikipedia entities.

---

### Edge #9: Resolution Rule Misread Arbitrage

**Mechanism of Edge:** Prediction market questions have specific resolution criteria buried in the fine print. Traders often bet based on the headline question without reading the resolution source, timeframe, or exact conditions. Example: "Will X happen by March 31?" — traders bet on whether X will happen, period, ignoring the March 31 deadline. If X is likely but not by March 31, buying NO is a high-edge trade.

**Required Data Feeds:**
- Gamma API market details (existing) — resolution source, end date, conditions
- LLM analysis of resolution criteria vs market price implied expectations

**How to Detect Signal in Code:**
```python
# Already partially implemented in resolution-rule-edge-playbook.md
for market in open_markets:
    rules = get_resolution_rules(market)
    # LLM analyzes: does the market price reflect the exact rules?
    analysis = claude_analyze_resolution_gap(
        question=market.question,
        rules=rules,
        market_price=market.price,
        end_date=market.end_date
    )
    if analysis.edge_score > 0.15 and analysis.confidence == 'high':
        signal = generate_trade(market, analysis)
```

**Backtest Approach:** Review 50 resolved markets where the resolution was surprising. Identify how many could have been predicted by careful reading of the resolution rules. Score by edge magnitude.

**Success Criteria:** Identify > 5 actionable resolution-rule trades per month. Win rate > 80% on these trades.

**Risk/Failure Modes:** These are rare — high edge but low frequency. Requires careful manual or LLM review of each market. Dispute risk is higher when resolution is ambiguous.

---

### Edge #10: Time Decay / Theta Harvesting

**Mechanism of Edge:** As markets approach their resolution date, prices converge toward 0 or 100. Markets currently trading at extreme prices (5–15% or 85–95%) with near-term resolution dates have embedded time value that can be harvested by selling the unlikely outcome (buying the likely side). This is analogous to selling options premium — you profit as time decays the remaining uncertainty.

**Required Data Feeds:**
- Gamma API (existing) — end_date, current price, volume
- Internal: time-to-resolution estimate per market

**How to Detect Signal in Code:**
```python
for market in open_markets:
    days_to_resolution = (market.end_date - now()).days
    price = market.price  # YES price
    # Sweet spot: near-term (< 7 days), price at extremes
    if days_to_resolution < 7 and (price < 0.15 or price > 0.85):
        # Buy the extreme side (the likely outcome)
        side = "YES" if price > 0.85 else "NO"
        implied_edge = (1.0 - price) if side == "YES" else price
        # Must exceed taker fee
        taker_fee = price * (1 - price) * 0.02  # r=2%
        if implied_edge - taker_fee > 0.03:
            signal = generate_trade(market, side, size="quarter_kelly")
```

**Backtest Approach:** Identify all resolved markets where price was >85% or <15% within 7 days of resolution. Measure how often the extreme side resolved correctly.

**Success Criteria:** Win rate > 85% on theta trades. Avg profit per trade > $0.10 per $1 deployed (small but high frequency).

**Risk/Failure Modes:** Low profit per trade (buying at 90¢ to win $1). Requires high volume to matter. Unexpected resolution (the 10% event happens) can wipe out many small wins. Taker fees erode the thin margins.

---

## Implementation Priority for Claude Code

**Immediate (this sprint):**
1. Edge #3 — Already implemented, optimize calibration bins
2. Edge #5 — Multi-model ensemble (highest academic evidence)
3. Edge #1 — Weather multi-model (already half-built)

**Next sprint:**
4. Edge #4 — FRED government data pipeline
5. Edge #2 — Polling aggregator integration
6. Edge #7 — Google Trends surge detector

**Following sprint:**
7. Edge #6 — News sentiment pipeline
8. Edge #8 — Wikipedia pageview anomaly
9. Edge #10 — Time decay harvesting
10. Edge #9 — Resolution rule enhancement

---

*This backlog is a living document. Re-rank monthly based on live performance data. Edges that fail backtest validation should be deprioritized or removed.*
