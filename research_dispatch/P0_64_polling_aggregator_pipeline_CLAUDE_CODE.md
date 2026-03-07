# P0-64: Polling Aggregator Integration (FiveThirtyEight + RCP)
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Edge #2 in backlog (composite score 4.5). Politics is Claude's best category. Polls are free, authoritative, and systematically underweighted by PM traders.
**Expected ARR Impact:** +8–15% on political markets specifically

## Background

Read COMMAND_NODE.md in the selected folder for full project context. Also read `research/edge_backlog_ranked.md` — Edge #2.

Political prediction markets are driven by narrative and recency bias. Polling aggregators like FiveThirtyEight and RealClearPolitics mathematically weight hundreds of polls, correcting for house effects and methodology. When the aggregator's implied probability diverges from the Polymarket price by >5%, the aggregator is usually right.

Our backtest shows politics is Claude's best category. Adding polling data as context gives Claude grounded, quantitative baselines instead of relying on training data alone.

## Task

### 1. FiveThirtyEight Data Client

```python
# src/data/polling_client.py
import aiohttp

class FiveThirtyEightClient:
    """Fetch polling averages from FiveThirtyEight public data.

    538 publishes polling data as public CSV/JSON files.
    Key endpoints (verify current URLs — they change):
    - Presidential approval: https://projects.fivethirtyeight.com/polls/...
    - Generic ballot: https://projects.fivethirtyeight.com/polls/generic-ballot/
    - State-level polls: varies by cycle

    As of March 2026, 538 (now under ABC News) publishes data at:
    https://projects.fivethirtyeight.com/polls/
    JSON data available at the /data/ subdirectory.
    """

    async def get_approval_average(self) -> dict:
        """Get current presidential approval polling average."""
        # 538 publishes as public data — no API key needed
        pass

    async def get_generic_ballot(self) -> dict:
        """Get generic congressional ballot average."""
        pass

    async def get_poll_average_for_topic(self, topic: str) -> dict:
        """Map a prediction market topic to relevant polling data."""
        # This requires a mapping layer — see section 3
        pass


class RealClearPoliticsClient:
    """Fetch RCP polling averages.

    RCP doesn't have a formal API. Data available via:
    - RSS feeds
    - Scraping the averages page (fragile)
    - Third-party mirrors

    Prefer 538 when available. Use RCP as secondary confirmation.
    """

    async def get_rcp_average(self, race_id: str) -> dict:
        pass
```

### 2. Polling-to-Probability Converter

Polling averages need to be converted to probabilities. A candidate at 52% in polls doesn't have a 52% chance of winning — historical accuracy data is needed.

```python
class PollingProbabilityConverter:
    """Convert polling averages to win probabilities using historical accuracy.

    Based on 538's own methodology and academic research:
    - Polls at 50% → ~50% win probability
    - Each 1% polling lead ≈ 2-4% increase in win probability (varies by time to election)
    - Closer to election → polls more predictive
    - State-level polls less accurate than national
    """

    def polling_lead_to_probability(self, lead_pct: float,
                                      days_to_election: int,
                                      poll_type: str = "national") -> float:
        """Convert a polling lead to an estimated win probability.

        Uses sigmoid approximation calibrated to historical data:
        - 538 found that a 5-point national lead at 30 days out ≈ 85% win prob
        - A 2-point lead at 30 days ≈ 70%
        - A 5-point lead at 180 days ≈ 72%
        """
        # Time factor: polls matter more as election approaches
        time_factor = max(0.5, 1.0 - (days_to_election / 365))

        # Sensitivity: each polling point worth more closer to election
        sensitivity = 0.3 * time_factor  # ~0.15 at 6mo, ~0.30 at election day

        # Sigmoid: probability = 1 / (1 + exp(-sensitivity * lead))
        import math
        logit = sensitivity * lead_pct
        return 1 / (1 + math.exp(-logit))
```

### 3. Market-to-Poll Mapper

```python
class PollMarketMapper:
    """Map Polymarket political questions to relevant polling data.

    This is the critical integration layer. Uses Claude Haiku for mapping.
    """

    # Manual mappings for common market types
    KNOWN_MAPPINGS = {
        "presidential_approval": {
            "keywords": ["approval", "approve", "disapprove", "favorability"],
            "polling_source": "538_approval",
        },
        "election_winner": {
            "keywords": ["win", "elected", "president", "governor", "senator"],
            "polling_source": "538_polls",
        },
        "generic_ballot": {
            "keywords": ["midterm", "congress", "house", "senate majority"],
            "polling_source": "538_generic_ballot",
        },
    }

    async def map_market_to_polls(self, market_question: str) -> dict | None:
        """Attempt to map a market question to polling data.

        Returns None if no applicable polling data exists.
        """
        # Step 1: Check keyword matches
        for map_type, config in self.KNOWN_MAPPINGS.items():
            if any(kw in market_question.lower() for kw in config["keywords"]):
                return {"type": map_type, "source": config["polling_source"]}

        # Step 2: LLM mapping for edge cases
        # Only call this if no keyword match (save API cost)
        return await self._llm_map(market_question)
```

### 4. Context Injection

When a political market has relevant polling data, inject it as context for Claude:

```python
# In claude_analyzer.py — add to prompt for political markets
POLLING_CONTEXT_TEMPLATE = """
POLLING DATA (from FiveThirtyEight/RCP, as of today):
{polling_summary}

IMPORTANT: Polling averages are mathematically weighted across hundreds of polls, correcting for house effects. They are more reliable than any single poll or narrative. Use this data as a strong prior, then adjust based on specific factors in the question.
"""
```

### 5. Standalone Polling Signal (No LLM Needed)

For some markets, polling data alone can generate a signal — no Claude needed:

```python
class PollingSignalGenerator:
    def check_polling_divergence(self, market: dict, polling_prob: float,
                                   min_edge: float = 0.05) -> dict | None:
        """Generate a trading signal when polls diverge from market price.

        If polling-implied probability differs from market price by >5%,
        generate a signal. This is INDEPENDENT of Claude's estimate.
        """
        market_price = market["yes_price"]
        edge = polling_prob - market_price

        if abs(edge) > min_edge:
            return {
                "source": "polling_divergence",
                "polling_prob": polling_prob,
                "market_price": market_price,
                "edge": edge,
                "side": "BUY_YES" if edge > 0 else "BUY_NO",
                "confidence": "high" if abs(edge) > 0.10 else "medium",
            }
        return None
```

### 6. Files to Create/Modify

- NEW: `src/data/polling_client.py` — FiveThirtyEightClient, RealClearPoliticsClient
- NEW: `src/data/polling_probability.py` — PollingProbabilityConverter
- NEW: `src/data/poll_market_mapper.py` — PollMarketMapper
- NEW: `src/signals/polling_signal.py` — PollingSignalGenerator
- MODIFY: `src/claude_analyzer.py` — inject polling context for political markets
- MODIFY: `src/engine/loop.py` — add polling signal as supplementary source

## Expected Outcome
- All political markets receive polling context in Claude's prompt
- Standalone polling divergence signals fire when polls disagree with market by >5%
- Win rate on political markets improves from ~68% to ~75%
- Zero additional cost (polling data is public)

## Success Criteria
- At least 10 political markets per month receive polling context
- Polling divergence signal has >70% win rate over 30+ trades
- Political market Brier score improves relative to non-political markets

## SOP
After completing this task, UPDATE COMMAND_NODE.md (increment version number) and review all project documents for stale information.
