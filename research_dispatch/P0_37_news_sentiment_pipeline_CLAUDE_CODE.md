# P0-37: News Sentiment Data Feed Integration
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Giving Claude real-time context is higher leverage than prompt engineering alone
**Expected ARR Impact:** +15-30% (informed estimates > blind estimates)

## Background (from GPT-4.5 competitive intelligence research)
Current system asks Claude to estimate probabilities with ZERO real-time context — just the market question text. Claude relies entirely on training data (cutoff ~early 2025). For questions about events in Feb-March 2026, Claude is flying blind.

Research shows news APIs and polling data are the fastest movers in prediction markets. Search spikes (Google Trends) and social media sentiment (Twitter/X, Reddit) predate market price moves. Providing Claude with real-time context should substantially improve estimate quality.

## Task

Build a context enrichment pipeline that runs BEFORE Claude analyzes each market:

1. **News API integration (primary — highest signal):**
   - API: NewsData.io (free tier: 200 req/day) or Finnhub News API
   - For each market question, extract key entities (person names, org names, event type)
   - Fetch last 48 hours of headlines mentioning those entities
   - Summarize top 3-5 relevant headlines into a 100-word context block
   - Inject into Claude's prompt: "Recent relevant news: [context]"

2. **Polling data integration (for political markets):**
   - Source: FiveThirtyEight polling averages (publicly accessible JSON endpoints) or RealClearPolitics
   - For political questions: fetch latest polling data
   - Format: "Latest polls: [candidate] at [X]% (FiveThirtyEight average as of [date])"
   - Only inject for markets tagged as "politics" category

3. **Google Trends signal (leading indicator):**
   - Use pytrends library (unofficial Google Trends API)
   - For each market question, check if search interest in key entities has spiked in last 7 days
   - A spike (>2× baseline) indicates news event that may not be priced into market yet
   - Inject: "Google Trends: [entity] search interest [up/down] [X]% in last 7 days"

4. **Architecture:**
   ```python
   class ContextEnricher:
       def __init__(self, news_api_key: str):
           self.news_client = NewsDataClient(api_key=news_api_key)
           self.trends = TrendsClient()

       def enrich(self, market_question: str, category: str) -> str:
           """Build context block for Claude's analysis prompt."""
           context_parts = []

           # News headlines (always)
           entities = self.extract_entities(market_question)
           news = self.news_client.search(entities, last_hours=48, limit=5)
           if news:
               context_parts.append(f"Recent news ({len(news)} articles): " +
                   "; ".join(n.headline for n in news[:3]))

           # Polling data (political markets only)
           if category == "politics":
               polls = self.get_polling_data(entities)
               if polls:
                   context_parts.append(f"Latest polls: {polls}")

           # Google Trends spike detection
           trend = self.trends.interest_over_time(entities, timeframe="now 7-d")
           if trend and trend.spike_ratio > 2.0:
               context_parts.append(
                   f"Google Trends: '{entities[0]}' search interest up {trend.spike_ratio:.0f}x in 7 days")

           return "\n".join(context_parts) if context_parts else ""
   ```

5. **Modify Claude's analysis prompt:**
   ```
   Current: "Question: {question}\nEstimate the probability..."
   New:     "Question: {question}\n\nContext (as of {today}):\n{enriched_context}\n\nEstimate the probability..."
   ```
   CRITICAL: Still do NOT show the market price. Context ≠ anchoring.

6. **Rate limit management:**
   - NewsData.io free tier: 200 req/day → batch entity extraction, cache results for 1 hour
   - Google Trends: unofficial API has aggressive rate limiting → cache for 6 hours
   - Total additional latency per market: <2 seconds (async fetches)

7. **A/B test:** Run enriched vs non-enriched estimates in parallel on the next 100 markets to measure impact. Log both estimates and compare Brier scores.

## API Keys Needed
- NewsData.io: Sign up at newsdata.io (free tier sufficient for now)
- OR Finnhub: Sign up at finnhub.io (free tier: 60 calls/min)
- pytrends: No API key needed (scrapes Google Trends)

## Files to Create/Modify
- NEW: `src/context_enricher.py` — the enrichment pipeline
- MODIFY: `src/claude_analyzer.py` — inject context into prompt
- MODIFY: `src/scanner.py` — pass category info to enricher
- NEW: `.env` additions for NEWS_API_KEY

## Expected Outcome
- Claude receives real-time context for every market analysis
- Measurable improvement in estimate quality (A/B test data)
- Especially impactful for recent events Claude's training data doesn't cover
