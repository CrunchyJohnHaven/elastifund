# P0-53: Position Deduplication & Correlation Detection
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Correlated positions = hidden leverage = ruin risk
**Expected ARR Impact:** Risk reduction — prevents catastrophic correlated losses

## Problem
The bot currently treats every market independently. But many markets are correlated:
- "Will Trump win the election?" and "Will the Republican candidate win?" are ~95% correlated
- "Will the Fed cut rates in June?" and "Will 10Y yield drop below 4%?" are highly correlated
- Multiple weather markets for the same city on the same day are perfectly correlated

Taking $2 positions on 5 correlated markets is secretly a $10 position on one outcome. This violates our risk limits and can cause catastrophic losses.

## Task

1. **Build a correlation detector:**
   ```python
   class CorrelationDetector:
       def detect_correlated_markets(self, positions: list[dict]) -> list[list[dict]]:
           """Group positions that are likely correlated.

           Methods (in order of reliability):
           1. Exact entity match: same person, team, or event in question text
           2. Category + timeframe: same category, resolution within same week
           3. Semantic similarity: use sentence embeddings to detect similar questions
           4. Historical price correlation: if we have price history, compute actual correlation
           """

       def compute_aggregate_exposure(self, correlated_group: list[dict]) -> dict:
           """For a group of correlated positions, compute effective exposure.
           Returns: {total_usd, effective_usd, correlation_estimate, risk_level}"""
   ```

2. **Entity extraction from market questions:**
   - Extract person names, organizations, dates, locations from question text
   - Use simple NLP (spaCy or regex) — don't need LLM for this
   - Build entity → market_id mapping
   - Flag when multiple open positions share the same primary entity

3. **Deduplication rules:**
   - If 2+ positions share primary entity AND same direction: block new position, alert
   - If 3+ positions in same category: apply 50% Kelly haircut (from Kelly research)
   - If total correlated exposure > 25% of bankroll: block new positions in that cluster
   - Log all correlation detections for analysis

4. **Portfolio-level risk view:**
   ```python
   def portfolio_risk_summary(positions: list[dict]) -> dict:
       """Generate a portfolio-level risk summary.
       Returns:
       {
           "total_positions": 34,
           "unique_clusters": 18,  # groups of correlated positions
           "largest_cluster": {"entity": "Trump", "positions": 5, "exposure": "$10"},
           "category_breakdown": {"politics": 40%, "weather": 30%, ...},
           "effective_diversification_ratio": 0.53,  # 1.0 = fully diversified
           "risk_alerts": ["5 correlated Trump positions = $10 effective exposure"]
       }
       """
   ```

5. **Wire into the trading pipeline:**
   - Before entering any new trade, check correlation with existing positions
   - If correlated cluster would exceed limits, skip the trade
   - Include portfolio risk summary in daily Telegram digest

## Files to Create/Modify
- NEW: `src/correlation_detector.py`
- NEW: `src/portfolio_risk.py`
- MODIFY: `src/paper_trader.py` — add pre-trade correlation check
- MODIFY: `improvement_loop.py` — add portfolio risk to cycle metrics

## Expected Outcome
- No more hidden correlated exposure
- Portfolio diversification enforced automatically
- Ruin risk reduced from >0% to ~0% even with Kelly sizing
- Portfolio risk summary available at all times
