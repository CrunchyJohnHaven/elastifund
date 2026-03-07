# P1-42: Social Sentiment Monitoring (Twitter/X + Reddit)
**Tool:** CHATGPT_DEEP_RESEARCH
**Status:** READY
**Priority:** P1 — Research shows social media sentiment precedes prediction market price moves
**Expected ARR Impact:** +10-20% (leading indicator for market movements)

## Background
GPT-4.5 competitive intelligence research identified social media as a leading indicator for prediction market price movements. Search spikes and sentiment shifts on Twitter/X and Reddit often predate Polymarket price changes by hours. This gives us an informational edge if we can detect the signal.

## Research Questions

```
Research the current state of social media sentiment analysis for prediction market trading, specifically:

1. DATA ACCESS (March 2026 landscape):
   - What does Twitter/X API access cost now? Has Elon changed the pricing again?
   - Is there a free tier sufficient for monitoring 50-100 keywords?
   - Reddit API: current pricing and rate limits for read-only access
   - Alternative: Can we use Nitter, snscrape, or other scraping tools reliably?
   - Are there pre-built sentiment APIs (e.g., Brandwatch, Sprout Social, Social Searcher) with free tiers?

2. SENTIMENT ANALYSIS METHODS:
   - What's the best approach for real-time political/event sentiment from social media?
   - VADER vs TextBlob vs FinBERT vs LLM-based sentiment — what works best for prediction market topics?
   - How do you filter signal from noise? (bots, trolls, sarcasm, coordination campaigns)
   - Volume vs sentiment: is raw mention volume a better signal than sentiment polarity?

3. PROVEN STRATEGIES:
   - Any academic papers on using social media sentiment to trade prediction markets specifically?
   - How do hedge funds and quant firms use Twitter/Reddit data? (Two Sigma, DE Shaw approaches)
   - What lead time does social media have over prediction market prices? (hours? minutes?)
   - Are there documented cases of Reddit/Twitter driving Polymarket price moves?

4. IMPLEMENTATION:
   - Minimum viable social sentiment pipeline: what's the simplest thing that works?
   - How to map social media topics to specific Polymarket markets?
   - Entity extraction from tweets → match to market questions
   - How to handle market-specific sentiment (e.g., "Trump" appears in 50+ markets — which one?)

5. RISKS:
   - Manipulation risk: Can social media sentiment be gamed to move prediction markets?
   - Lag risk: By the time we detect sentiment shift, has the market already moved?
   - Noise risk: Is social media signal actually useful, or is it just noise for prediction markets?
   - Regulatory: Any concerns about using social media data for trading decisions?

6. COST-BENEFIT:
   - What's the minimum monthly cost for a useful social sentiment pipeline?
   - At our scale ($75 capital, $20/month infra budget), is this worth the cost?
   - What capital level makes social sentiment monitoring ROI-positive?
```

## Expected Outcome
- Decision: implement social sentiment monitoring now, or defer until larger scale
- If implement: architecture spec with specific APIs, costs, and implementation plan
- If defer: what capital threshold makes it worthwhile, and what to build in the meantime
