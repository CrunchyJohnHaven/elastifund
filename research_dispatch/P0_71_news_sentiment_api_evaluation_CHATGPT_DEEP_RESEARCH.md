# P0-71: News Sentiment API Evaluation + Social Signal Research
**Tool:** CHATGPT_DEEP_RESEARCH
**Status:** READY
**Priority:** P0 — Need to select the right news API before building the sentiment pipeline (P0-37). Wrong choice = wasted implementation time.
**Expected ARR Impact:** Informs P0-37 (news sentiment pipeline, +15–30%)

## Prompt (paste into ChatGPT with Deep Research enabled)

```
Deep research on real-time news sentiment APIs and social media signal detection for prediction market trading:

CONTEXT:
I'm building an automated prediction market trading system. I need real-time news sentiment to detect when breaking news moves market probabilities. The system scans markets every 5 minutes and needs to detect sentiment shifts within 1-6 hours of a news event.

Current data feeds: NOAA weather (partial), FRED economic data (planned).
Missing: real-time news, social media sentiment, expert forecasts.

RESEARCH QUESTIONS:

1. NEWS SENTIMENT API COMPARISON (as of March 2026):
   Compare ALL available real-time news APIs:

   - NewsData.io (mentions $49/mo for 30K requests)
   - Finnhub (free tier: 60 calls/min)
   - GDELT Project (free, massive)
   - Event Registry
   - Bloomberg Terminal API (expensive but gold standard)
   - Reuters/Refinitiv (Eikon API)
   - Alpha Vantage News Sentiment
   - Benzinga
   - IEX Cloud
   - Aylien News API
   - MediaStack
   - NewsCatcher

   For EACH:
   a. Pricing (free tier + paid tiers)
   b. Sentiment analysis included? (built-in vs need to add our own NLP)
   c. Latency: how quickly after a news event does it appear?
   d. Coverage: how many sources? International or US-only?
   e. API quality: structured JSON? Rate limits? Uptime?
   f. Relevance filtering: can you search by topic/entity?
   g. Historical data available? (for backtesting)
   h. Best for prediction markets specifically?

   RANK the top 5 for our use case (real-time, entity-focused, sentiment-included, affordable).

2. SOCIAL MEDIA SENTIMENT SIGNALS:
   Research which social signals predict prediction market moves:

   a. Twitter/X:
      - Current API pricing (as of 2026)
      - Academic evidence: do tweet surges predict market moves?
      - Lag time: how far ahead of market price moves?
      - Tools: Tweepy, snscrape (still working?), official API

   b. Reddit:
      - Which subreddits matter? (r/polymarket, r/wallstreetbets, r/politics, r/economics)
      - Reddit API pricing and rate limits
      - Evidence: does Reddit sentiment predict outcomes?
      - Tools: PRAW, Pushshift (still available?)

   c. StockTwits:
      - API availability
      - Relevant to prediction markets?

   d. Telegram:
      - Polymarket-specific channels
      - Can we monitor public channels for signal?

   e. Discord:
      - Prediction market communities
      - Signal quality?

   For each social platform: cite academic papers showing prediction/correlation with market outcomes. If no evidence exists, say so.

3. SENTIMENT ANALYSIS APPROACHES:
   If the news API doesn't include sentiment, what's the best approach?

   - FinBERT (financial sentiment, free, open-source)
   - VADER (simple, fast, good for social media)
   - Claude/GPT as sentiment classifier (expensive but flexible)
   - TextBlob (basic)
   - Which approach gives best accuracy for prediction market-relevant news?
   - What's the latency and cost of each?

4. SIGNAL DETECTION METHODOLOGY:
   How to detect that sentiment has shifted meaningfully:

   - Z-score approach: flag when sentiment deviates >2σ from rolling 7-day baseline
   - Volume spike: flag when article count > 3× baseline
   - Entity co-occurrence: flag when new entities appear alongside a market's entities
   - Sentiment reversal: flag when previously positive topic turns negative (or vice versa)
   - What thresholds minimize false positives while catching real moves?

5. CROSS-PLATFORM EXPERT FORECASTS:
   Other prediction platforms as signal sources:

   - Metaculus community predictions (free API?)
   - Manifold Markets prices
   - Kalshi prices
   - Good Judgment Open (superforecaster aggregates)
   - When these platforms disagree with Polymarket, who's usually right?
   - Cite any research comparing platform accuracy.

6. CONTRARIAN/DUMB MONEY INDICATORS:
   From our recent research (sentiment_contrarian_dumb_money_fade.md):
   - AAII Investor Sentiment Survey — free, weekly
   - CNN Fear & Greed Index — free
   - Put/Call ratios — free from CBOE
   - How reliably do these indicators work as contrarian signals?
   - Which are most applicable to prediction markets (vs equity markets)?
   - Implementation complexity: can they be automatically ingested?

7. SPECIFIC RECOMMENDATION:
   Given our constraints:
   - Budget: $50-100/month for data feeds
   - 20 markets per 5-min cycle, 288 cycles/day
   - Need sentiment + breaking news + social signals
   - Python implementation

   Recommend an EXACT stack:
   - Primary news API: [name, plan, cost]
   - Social signal source: [name, approach, cost]
   - Sentiment model: [name, approach]
   - Expert forecast source: [name, API]
   - Total monthly cost: $X
   - Implementation order (what to build first)

OUTPUT: Structured comparison tables with clear rankings. Include API endpoints and pricing URLs where possible. Cite academic evidence for every signal source.
```

## Expected Outcome
- Ranked comparison of 10+ news APIs with pricing
- Social media signal evaluation with academic evidence
- Recommended stack within $50-100/month budget
- Implementation order for the sentiment pipeline

## SOP
Store results in `research/news_sentiment_api_evaluation_deep_research.md`. Feed into P0-37 (news sentiment pipeline) and P0-63 (Wikipedia/Google Trends). Update COMMAND_NODE.md.
