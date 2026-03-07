# P0-57: Category-Specific Model Configuration & Prompt Routing
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Different market categories have wildly different characteristics. One-size-fits-all is suboptimal.
**Expected ARR Impact:** +15-25% (specialized > generalized for each category)

## Background
Research shows our system performs very differently across categories:
- Politics: LLMs' best category (Lu 2025). Favorite-longshot bias exploitable.
- Weather: Structural arbitrage with NOAA/ECMWF data. Pure data play, not forecasting.
- Economics: Tight markets, small edge but reliable. Government data releases are key events.
- Crypto/Sports: Zero LLM forecasting edge. Skip or use different strategy.
- Geopolitics: ~30% worse than experts. Needs more context.

## Task

Build a category-aware routing system that uses different configurations per category:

1. **Category classifier:**
   ```python
   class MarketCategoryClassifier:
       CATEGORIES = {
           "politics": {"keywords": ["election", "president", "senate", "congress", "governor", "party", "democrat", "republican", "vote", "poll", "cabinet", "impeach"], "model_config": "politics"},
           "weather": {"keywords": ["temperature", "rain", "snow", "weather", "degrees", "fahrenheit", "celsius", "wind", "storm", "hurricane"], "model_config": "weather"},
           "economics": {"keywords": ["fed", "rate", "inflation", "gdp", "unemployment", "jobs", "cpi", "fomc", "treasury", "yield", "recession"], "model_config": "economics"},
           "crypto": {"keywords": ["bitcoin", "ethereum", "btc", "eth", "crypto", "blockchain", "token"], "model_config": "skip"},
           "sports": {"keywords": ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball", "game", "match", "championship", "playoff"], "model_config": "skip"},
           "geopolitics": {"keywords": ["war", "sanctions", "nato", "china", "russia", "treaty", "invasion", "military"], "model_config": "geopolitics"},
           "tech": {"keywords": ["apple", "google", "ai", "launch", "release", "feature", "antitrust"], "model_config": "tech"},
           "entertainment": {"keywords": ["oscar", "grammy", "movie", "album", "box office", "streaming", "concert"], "model_config": "entertainment"},
           "science": {"keywords": ["vaccine", "fda", "trial", "disease", "space", "nasa", "climate"], "model_config": "science"},
       }

       def classify(self, question: str) -> str:
           """Classify market question into a category."""
   ```

2. **Category-specific prompt templates:**
   ```python
   CATEGORY_PROMPTS = {
       "politics": """You are estimating the probability of a POLITICAL event.
           Key base rates to consider:
           - Incumbent advantage: ~60% of incumbents win re-election
           - Polling accuracy: polls are ±3-4% in final week
           - Prediction markets tend to OVERESTIMATE exciting political outcomes
           {base_rate_first_instructions}
           {context: polling data if available}""",

       "weather": """You are estimating a WEATHER outcome.
           IMPORTANT: Use the provided forecast data as your primary input.
           NOAA 24-hour accuracy: ~90%. ECMWF: ~92%.
           {context: NOAA forecast + ECMWF if available}
           Base your estimate primarily on the forecast data, not on intuition.""",

       "economics": """You are estimating an ECONOMIC event.
           Key base rates:
           - Fed has cut rates in X of last Y meetings
           - Inflation has been trending [up/down] at [rate]
           {context: latest FRED data if available}
           Economic indicators are mean-reverting. Avoid recency bias.""",

       "geopolitics": """You are estimating a GEOPOLITICAL event.
           CAUTION: LLMs perform ~30% worse than experts on geopolitical forecasting.
           Be conservative. When uncertain, estimate closer to base rates.
           {context: news headlines if available}
           Consider second and third-order effects.""",
   }
   ```

3. **Category-specific edge thresholds:**
   ```python
   CATEGORY_THRESHOLDS = {
       "politics":     {"yes_threshold": 0.12, "no_threshold": 0.05, "kelly_fraction": 0.30},
       "weather":      {"yes_threshold": 0.10, "no_threshold": 0.10, "kelly_fraction": 0.35},  # more symmetric
       "economics":    {"yes_threshold": 0.15, "no_threshold": 0.08, "kelly_fraction": 0.20},  # conservative
       "geopolitics":  {"yes_threshold": 0.20, "no_threshold": 0.10, "kelly_fraction": 0.15},  # very conservative
       "tech":         {"yes_threshold": 0.15, "no_threshold": 0.08, "kelly_fraction": 0.20},
       "entertainment":{"yes_threshold": 0.15, "no_threshold": 0.08, "kelly_fraction": 0.20},
       "science":      {"yes_threshold": 0.15, "no_threshold": 0.08, "kelly_fraction": 0.20},
   }
   ```

4. **Category-specific data enrichment:**
   - Politics → polling data (FiveThirtyEight)
   - Weather → NOAA + ECMWF + HRRR forecasts
   - Economics → FRED data (latest CPI, unemployment, Fed funds rate)
   - Geopolitics → news headlines (NewsData.io)
   - All → Google Trends spike detection

5. **Per-category performance tracking:**
   - Track win rate, Brier score, and P&L separately per category
   - Use this data to dynamically adjust thresholds and Kelly fractions
   - Categories with declining performance get more conservative automatically

## Files to Create/Modify
- NEW: `src/category_classifier.py`
- NEW: `src/category_config.py` — thresholds, prompts, data sources per category
- MODIFY: `src/claude_analyzer.py` — use category-specific prompts
- MODIFY: `src/scanner.py` — classify markets, route to correct config
- MODIFY: `improvement_loop.py` — per-category performance metrics

## Expected Outcome
- Each market category gets a tailored analysis approach
- Conservative on weak categories (geopolitics), aggressive on strong ones (politics, weather)
- Different data sources automatically activated per category
- Per-category performance tracking enables continuous optimization
