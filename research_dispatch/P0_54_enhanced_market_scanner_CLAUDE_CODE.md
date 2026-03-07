# P0-54: Enhanced Market Scanner — Find Higher-Quality Opportunities
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Better market selection = higher win rate without any model improvement
**Expected ARR Impact:** +10-20% (garbage in = garbage out; better inputs = better outputs)

## Problem
Current scanner uses a simple filter: binary Yes/No, price 10-90%, min $100 liquidity, scored by proximity to 50/50. This misses opportunities and includes bad markets.

## Task

1. **Multi-factor market scoring system:**
   ```python
   class MarketScorer:
       def score(self, market: dict) -> float:
           """Score a market on 0-100 scale for trading opportunity quality."""
           score = 0

           # Factor 1: Liquidity (higher = better fills)
           score += self.liquidity_score(market["volume_24h"], market["depth"])  # 0-20

           # Factor 2: Time to resolution (sweet spot: 1-14 days)
           score += self.time_score(market["end_date"])  # 0-20

           # Factor 3: Category quality (politics > weather > econ > other)
           score += self.category_score(market["category"])  # 0-15

           # Factor 4: Price range (near 50% = more edge opportunity)
           score += self.price_score(market["price"])  # 0-15

           # Factor 5: Information availability (can Claude reason about this?)
           score += self.info_score(market["question"])  # 0-15

           # Factor 6: Competition (fewer bots trading = more edge)
           score += self.competition_score(market["num_traders"], market["volume_24h"])  # 0-15

           return score
   ```

2. **Time-to-resolution optimizer:**
   - Markets resolving in <24 hours: HIGH priority (quick feedback loop, less uncertainty)
   - Markets resolving in 1-7 days: MEDIUM priority (good balance)
   - Markets resolving in 7-30 days: LOW priority (capital tied up too long at our scale)
   - Markets resolving in >30 days: SKIP (opportunity cost too high for $75 capital)

3. **Information availability classifier:**
   - Markets about publicly verifiable facts (weather, sports scores, data releases): HIGH info
   - Markets about observable events (elections, policy decisions): MEDIUM info
   - Markets about opinions or subjective outcomes: LOW info
   - Markets about private/unpredictable events (celebrity actions, crypto prices): SKIP

4. **Competition estimator:**
   - Few traders + low volume = less competition = potentially more edge
   - Many traders + high volume = well-arbitraged = less edge but better fills
   - Sweet spot: moderate volume ($1K-$50K) with few large traders

5. **Dynamic market pool management:**
   - Maintain a ranked list of top 50 markets (updated every cycle)
   - Claude only analyzes the top 20 by score (saves API costs)
   - Rotate through the next 30 to catch emerging opportunities
   - Track which markets were analyzed but skipped (avoid re-analyzing)

6. **Market freshness detection:**
   - Newly created markets (< 6 hours old) get a freshness bonus: they're more likely mispriced
   - Monitor for new market creation via Gamma API
   - Fast-track new markets to Claude analysis (before other bots catch them)

## Files to Modify
- MODIFY: `src/scanner.py` — replace simple filter with multi-factor scorer
- NEW: `src/market_scorer.py` — scoring logic
- MODIFY: `improvement_loop.py` — use scored market list

## Expected Outcome
- Higher quality opportunities fed to Claude
- Less API spend on unanalyzable markets
- Faster capital turnover (shorter resolution times)
- First-mover advantage on new markets
