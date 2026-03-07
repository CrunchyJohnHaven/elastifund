# P1-38: Polling Data Pipeline for Political Markets
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P1 — Enhances Claude's political market estimates (our best-performing category per research)
**Expected ARR Impact:** +10-20% on political markets specifically

## Background
Research (Lu 2025, RAND) shows politics is LLMs' best forecasting category. Polymarket political markets were only ~67% accurate (Clinton & Huang 2025), leaving room for our system. But Claude is estimating political probabilities with NO current polling data — just training knowledge from 2024/early 2025.

FiveThirtyEight and RealClearPolitics publish polling aggregates that are publicly accessible. Feeding these to Claude alongside the market question should dramatically improve political market estimates.

## Task

1. **Data sources:**
   - FiveThirtyEight: `projects.fivethirtyeight.com/polls/` — scrape or use their data API
   - RealClearPolitics: `realclearpolling.com/polls/` — scrape latest averages
   - Alternative: use `270towin.com` composite averages
   - For approval ratings: `projects.fivethirtyeight.com/biden-approval-rating/` (or current president)

2. **Build a polling client:**
   ```python
   class PollingDataClient:
       def get_latest_polls(self, race: str, state: str = None) -> dict:
           """Fetch latest polling average for a given race/question.
           Returns: {candidate: pct, ...} with date and source."""

       def get_approval_rating(self, figure: str) -> dict:
           """Fetch approval rating for political figure."""

       def get_generic_ballot(self) -> dict:
           """Generic congressional ballot average."""
   ```

3. **Entity matching:** When a market question mentions a political figure, election, or policy vote:
   - Extract the political entity (candidate name, race, bill name)
   - Match to available polling data
   - Format as context block: "Latest polls (as of March 2026): [candidate] leads [state] by [X] points (FiveThirtyEight average)"

4. **Inject into Claude prompt** via the ContextEnricher (P0-37):
   - Only for markets tagged category="politics"
   - Include polling source, date, and margin of error if available
   - STILL do not include market price

5. **Cache strategy:** Poll averages update slowly (daily). Cache for 12 hours.

## Files to Create/Modify
- NEW: `src/data/polling_client.py`
- MODIFY: `src/context_enricher.py` (add polling as data source)
- MODIFY: `src/claude_analyzer.py` (inject polling context)

## Expected Outcome
- Claude makes political estimates informed by actual current polling data
- Measurable improvement on political market Brier score
- Especially valuable for 2026 midterm-related markets
