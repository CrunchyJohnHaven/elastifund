# P0-61: Agentic RAG — Real-Time Web Search in Prediction Pipeline
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Single largest Brier improvement in ALL published research (−0.06 to −0.15)
**Expected ARR Impact:** +30–60% (Brier reduction from ~0.22 → ~0.14 demonstrated in literature)

## Background

Read COMMAND_NODE.md in the selected folder for full project context.

The superforecaster methods playbook (stored in `research/superforecaster_methods_llm_playbook.md`) ranks agentic RAG as the #1 technique by Brier improvement:

| Technique | Brier Δ |
|-----------|---------|
| **Agentic RAG** | **−0.06 to −0.15** |
| Platt scaling | −0.02 to −0.05 |
| Multi-run ensemble | −0.01 to −0.03 |
| Base-rate-first | −0.011 to −0.014 |

Right now Claude estimates probabilities from training data only — no real-time information. For a market like "Will Ukraine and Russia reach a ceasefire by April 2026?", Claude has NO access to today's news. This is the biggest single gap in our system.

## Task

### 1. Web Search Integration

Add a real-time web search step BEFORE Claude's probability estimation. For every market question, search the web and inject the top results as context.

**API options (pick one, prefer cheapest with best quality):**

```python
# Option A: Tavily Search API (built for RAG, $0.01/search, structured output)
# https://tavily.com — Free tier: 1,000 searches/month
class TavilySearchClient:
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Returns title, url, content snippet, relevance score."""
        response = requests.post("https://api.tavily.com/search", json={
            "api_key": os.environ["TAVILY_API_KEY"],
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": True,  # Tavily generates a summary
        })
        return response.json()["results"]

# Option B: Brave Search API (free 2,000 queries/month)
# https://api.search.brave.com

# Option C: SerpAPI (Google results, $50/mo for 5,000 searches)

# Option D: Perplexity API (search + LLM summary in one call)
# Expensive but highest quality — use only for high-edge markets
```

### 2. Query Generation

Don't just search the raw market question. Generate targeted search queries:

```python
class QueryGenerator:
    def generate_queries(self, market_question: str, category: str) -> list[str]:
        """Generate 2-3 targeted search queries per market."""
        # Query 1: Direct question (for news articles)
        # Query 2: Key entities + "latest" (for recent developments)
        # Query 3: Category-specific (e.g., "CPI March 2026 forecast" for economic)

        # Use Claude to generate queries (cheap — 1 Haiku call)
        prompt = f"""Generate exactly 3 web search queries to find the most relevant, recent information for answering this prediction market question:

Question: {market_question}
Category: {category}

Requirements:
- Query 1: Search for the latest news about this topic
- Query 2: Search for expert analysis or forecasts
- Query 3: Search for relevant data or statistics

Output as JSON array of 3 strings. Nothing else."""
```

### 3. Context Injection Pipeline

```python
class AgenticRAGPipeline:
    def __init__(self, search_client, llm_client):
        self.search = search_client
        self.llm = llm_client

    async def enrich_and_estimate(self, market: dict) -> dict:
        # Step 1: Generate search queries
        queries = self.generate_queries(market["question"], market["category"])

        # Step 2: Execute searches (parallel)
        all_results = await asyncio.gather(*[
            self.search.search(q, max_results=3) for q in queries
        ])

        # Step 3: Deduplicate and rank results
        unique_results = self.deduplicate(flatten(all_results))
        top_results = sorted(unique_results, key=lambda r: r["relevance"])[:5]

        # Step 4: Format context for Claude
        context = self.format_search_context(top_results)

        # Step 5: Claude estimates with context (STILL no market price shown)
        estimate = await self.llm.estimate_probability(
            question=market["question"],
            category=market["category"],
            web_context=context,  # NEW — injected search results
            # market_price=NEVER  # Anti-anchoring: still hidden
        )

        return {
            **estimate,
            "search_queries": queries,
            "sources_used": len(top_results),
            "source_urls": [r["url"] for r in top_results],
        }
```

### 4. Prompt Modification in claude_analyzer.py

Add a `WEB CONTEXT` section to the existing prompt. Place it AFTER the question but BEFORE the estimation instructions:

```
You are estimating the probability that this prediction market question resolves YES.

QUESTION: {question}
CATEGORY: {category}

WEB CONTEXT (real-time search results — use these as evidence):
---
{formatted_search_results}
---

IMPORTANT: The web context above is from today's search results. Use this information as evidence alongside your training knowledge. If the web context contains relevant recent developments, weight them appropriately.

[Rest of existing prompt: base-rate-first, structured reasoning, etc.]
```

### 5. Cost Control

At 20 markets/cycle × 3 searches/market × 288 cycles/day = 17,280 searches/day. This exceeds free tiers.

**Solution: Tiered search strategy:**
- **Tier 1 (all markets):** Check if market question contains time-sensitive keywords ("today", "this week", "March 2026", current events). If yes → full RAG pipeline.
- **Tier 2 (top candidates only):** After initial Claude estimate, only run RAG on markets where |edge| > 3% (likely to generate a signal). This cuts searches by ~60%.
- **Tier 3 (cache):** Cache search results for 1 hour per query. Same market question within 1h → reuse results.

```python
# Cost estimate at Tier 2 + caching:
# ~8 markets/cycle get RAG × 3 queries × 288 cycles / 12 (hourly cache reuse)
# ≈ 576 searches/day × $0.01 = $5.76/day = ~$173/month (Tavily)
# Or: use Brave free tier (2,000/month) for Tier 1 + Tavily for Tier 2
```

### 6. Backtest Validation

This is tricky — we can't retroactively search the web as it was when markets were open. But we can:
1. Run the RAG pipeline on 50 currently-open markets
2. Compare Claude's estimate WITH vs WITHOUT web context
3. Measure: does web context increase or decrease divergence from Claude's raw estimate?
4. Track forward: once these markets resolve, compare Brier score with/without RAG

### 7. Files to Create/Modify

- NEW: `src/data/web_search.py` — TavilySearchClient (or Brave)
- NEW: `src/data/query_generator.py` — LLM-powered query generation
- NEW: `src/rag_pipeline.py` — AgenticRAGPipeline orchestrator
- MODIFY: `src/claude_analyzer.py` — add web_context parameter to prompt
- MODIFY: `src/engine/loop.py` — wire RAG pipeline into main loop
- MODIFY: `src/core/config.py` — add TAVILY_API_KEY, RAG_ENABLED, RAG_TIER settings
- ADD to `.env`: `TAVILY_API_KEY=...`, `RAG_ENABLED=true`, `RAG_SEARCH_TIER=2`

## Expected Outcome
- Claude receives real-time web context for every high-value market
- Brier score improvement from 0.22 → 0.14–0.18 (based on published results)
- Win rate improvement to 72–78%
- Source URLs logged for every trade (audit trail)
- Cost: ~$100–175/month at Tier 2 (worth it if Brier improves by even 0.02)

## Success Criteria
- Forward test: run WITH and WITHOUT RAG on 50 markets. Measure Brier difference.
- Target: RAG version has Brier at least 0.02 lower than non-RAG.

## SOP
After completing this task, UPDATE COMMAND_NODE.md (increment version number, add version log entry) and review STRATEGY_REPORT.md, INVESTOR_REPORT.md, and any other affected documents for stale information.
