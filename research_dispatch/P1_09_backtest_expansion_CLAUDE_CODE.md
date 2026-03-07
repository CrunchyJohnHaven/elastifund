# P1-09: Expand Backtest to 2000+ Markets with Category Tagging
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +5-10% (more data = better calibration)

## Task
1. Expand the collector to fetch 2000+ resolved markets from Gamma API
2. Tag each market by category (politics, sports, crypto, entertainment, science, weather, economics, etc.) using keyword matching
3. Run backtest on each category separately
4. Identify which categories have highest win rate and P&L
5. Build a "category filter" that only trades in profitable categories
6. Re-compute ARR with category-selective trading

## Implementation
- Add `categorize_market(question, description)` function
- Use keyword matching + optional Claude classification for ambiguous markets
- Save category in `historical_markets.json`
- Add `--category` flag to CLI for category-specific backtests

## Expected Outcome
- 2000+ market dataset with category tags
- Win rate by category breakdown
- Category-selective strategy with higher ARR
