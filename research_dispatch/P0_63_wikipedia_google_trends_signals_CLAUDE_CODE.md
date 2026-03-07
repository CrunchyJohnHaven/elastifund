# P0-63: Wikipedia Pageview + Google Trends Signal Pipeline
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Free data, 4–24h leading indicator, zero ongoing cost
**Expected ARR Impact:** +5–15% (supplementary signal that fires before market moves)

## Background

Read COMMAND_NODE.md in the selected folder for full project context. Also read `research/edge_backlog_ranked.md` — this combines Edge #7 (Google Trends, composite 4.1) and Edge #8 (Wikipedia pageviews, composite 4.0).

Both Wikipedia pageview spikes and Google Trends surges precede prediction market price movements by 4–24 hours. When public attention spikes on a topic, it means new information is entering the system — but prediction markets haven't fully priced it yet because retail traders are slow.

Key advantage: **both APIs are free, unlimited, and provide hourly data.**

## Task

### 1. Wikipedia Pageview Monitor

```python
# src/data/wikipedia_client.py
import aiohttp
from datetime import datetime, timedelta

class WikipediaPageviewClient:
    BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

    async def get_pageviews(self, article: str, days: int = 7,
                            granularity: str = "hourly") -> list[dict]:
        """Fetch pageview data for a Wikipedia article.

        Args:
            article: Wikipedia article title (e.g., "Donald_Trump", "Ukraine")
            days: Number of days of history
            granularity: "hourly" or "daily"
        """
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        url = (f"{self.BASE_URL}/en.wikipedia.org/all-access/all-agents/"
               f"{article}/{granularity}/"
               f"{start.strftime('%Y%m%d%H')}/{end.strftime('%Y%m%d%H')}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return data.get("items", [])

    async def detect_spike(self, article: str, spike_threshold: float = 5.0) -> dict:
        """Detect if current pageviews are spiking relative to baseline.

        Returns:
            {
                "article": str,
                "is_spike": bool,
                "current_avg_6h": float,    # avg of last 6 hours
                "baseline_avg": float,       # avg of preceding 7 days
                "spike_ratio": float,        # current / baseline
                "spike_threshold": float,
            }
        """
        views = await self.get_pageviews(article, days=7, granularity="hourly")
        if len(views) < 48:
            return {"article": article, "is_spike": False, "reason": "insufficient_data"}

        hourly_counts = [v["views"] for v in views]
        current_6h = sum(hourly_counts[-6:]) / 6
        baseline = sum(hourly_counts[:-6]) / len(hourly_counts[:-6])

        if baseline < 10:  # Avoid division by tiny numbers
            return {"article": article, "is_spike": False, "reason": "low_baseline"}

        ratio = current_6h / baseline
        return {
            "article": article,
            "is_spike": ratio > spike_threshold,
            "current_avg_6h": current_6h,
            "baseline_avg": baseline,
            "spike_ratio": ratio,
            "spike_threshold": spike_threshold,
        }
```

### 2. Google Trends Monitor

```python
# src/data/google_trends_client.py
from pytrends.request import TrendReq

class GoogleTrendsClient:
    def __init__(self):
        self.pytrends = TrendReq(hl='en-US', tz=360)

    def detect_surge(self, keyword: str, surge_threshold: float = 3.0) -> dict:
        """Detect if search interest is surging for a keyword.

        Uses 7-day window with daily granularity (Google Trends limit).
        """
        self.pytrends.build_payload([keyword], timeframe='now 7-d')
        data = self.pytrends.interest_over_time()

        if data.empty:
            return {"keyword": keyword, "is_surge": False, "reason": "no_data"}

        values = data[keyword].values
        if len(values) < 3:
            return {"keyword": keyword, "is_surge": False, "reason": "insufficient_data"}

        current = values[-1]
        baseline = values[:-1].mean()

        if baseline < 5:  # Google Trends is 0-100 scale
            return {"keyword": keyword, "is_surge": False, "reason": "low_baseline"}

        ratio = current / baseline
        return {
            "keyword": keyword,
            "is_surge": ratio > surge_threshold,
            "current_value": int(current),
            "baseline_avg": float(baseline),
            "surge_ratio": float(ratio),
            "surge_threshold": surge_threshold,
        }
```

### 3. Market-to-Entity Mapper

The hard part: automatically mapping Polymarket questions to Wikipedia articles and search terms.

```python
# src/data/entity_mapper.py
class EntityMapper:
    async def map_market_to_entities(self, market_question: str,
                                      category: str) -> dict:
        """Use Claude Haiku to extract searchable entities from a market question.

        Input: "Will Russia and Ukraine reach a ceasefire agreement by April 2026?"
        Output: {
            "wikipedia_articles": ["Russia–Ukraine_war", "Russo-Ukrainian_War"],
            "google_trends_keywords": ["ukraine ceasefire", "russia ukraine peace"],
        }
        """
        prompt = f"""Extract entities from this prediction market question for monitoring.

Question: {market_question}
Category: {category}

Output ONLY valid JSON:
{{
  "wikipedia_articles": ["Article_Title_1", "Article_Title_2"],
  "google_trends_keywords": ["keyword phrase 1", "keyword phrase 2"]
}}

Rules:
- Wikipedia: Use exact article titles with underscores (check they exist)
- Google Trends: Use 2-3 word phrases a person would search
- Max 3 of each
- For politics: include person names, party names, policy names
- For economics: include indicator names, institution names
- For weather: skip (we have NOAA data)"""

        response = await self.llm.complete(prompt)
        return json.loads(response)
```

### 4. Signal Integration into Engine Loop

```python
# In src/engine/loop.py — add attention signal check
class AttentionSignalMonitor:
    def __init__(self, wiki_client, trends_client, mapper):
        self.wiki = wiki_client
        self.trends = trends_client
        self.mapper = mapper
        self._entity_cache = {}  # market_id → entities (TTL 24h)

    async def check_attention_signals(self, markets: list) -> dict:
        """Check for attention spikes on all open markets.

        Returns market_id → signal dict for markets with spikes.
        Run once per hour (not every 5-min cycle — rate limit friendly).
        """
        signals = {}

        for market in markets:
            entities = await self._get_entities(market)

            # Check Wikipedia
            for article in entities.get("wikipedia_articles", []):
                spike = await self.wiki.detect_spike(article)
                if spike.get("is_spike"):
                    signals[market["id"]] = {
                        "type": "wikipedia_spike",
                        "article": article,
                        "spike_ratio": spike["spike_ratio"],
                        "action": "reanalyze_priority",
                    }

            # Check Google Trends (daily only — rate limited)
            for keyword in entities.get("google_trends_keywords", []):
                surge = self.trends.detect_surge(keyword)
                if surge.get("is_surge"):
                    signals[market["id"]] = {
                        "type": "google_trends_surge",
                        "keyword": keyword,
                        "surge_ratio": surge["surge_ratio"],
                        "action": "reanalyze_priority",
                    }

        return signals
```

**When a spike is detected:**
1. Move the market to the FRONT of the analysis queue (priority re-analysis)
2. If RAG pipeline (P0-61) is active, trigger an immediate web search for this market
3. Log the spike in the audit trail
4. If the spike leads to a position entry, tag the trade with `attention_signal=True` for future analysis

### 5. Rate Limit Management

- **Wikipedia:** No rate limit, but be respectful. Check hourly, not every 5 min.
- **Google Trends:** Aggressive rate limiting. Check daily (once per 24h per keyword). Cache results.
- **Entity mapping:** Cache for 24h per market (market questions don't change).

### 6. Files to Create

- NEW: `src/data/wikipedia_client.py`
- NEW: `src/data/google_trends_client.py`
- NEW: `src/data/entity_mapper.py`
- NEW: `src/attention_monitor.py` — AttentionSignalMonitor
- MODIFY: `src/engine/loop.py` — wire attention monitor (hourly check)
- MODIFY: `requirements.txt` — add `pytrends`

### 7. Dependencies

```bash
pip install pytrends aiohttp --break-system-packages
```

## Expected Outcome
- Hourly Wikipedia monitoring for all open markets
- Daily Google Trends monitoring for all open markets
- Markets with attention spikes get priority re-analysis
- Zero cost (both APIs are free)
- 5–15% win rate improvement on markets where spikes detected

## Success Criteria
- At least 5 attention spikes detected per week across open markets
- Markets flagged by attention spikes have higher win rate than unflagged markets
- No rate limit errors after 1 week of operation

## SOP
After completing this task, UPDATE COMMAND_NODE.md (increment version number, add version log entry) and review all project documents for stale information.
