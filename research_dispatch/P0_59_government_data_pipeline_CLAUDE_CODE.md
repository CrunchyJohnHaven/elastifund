# P0-59: Government Data Feed Pipeline (FRED, BLS, Census)
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Free, authoritative data that most bots don't use for prediction context
**Expected ARR Impact:** +10-20% on economics markets specifically

## Background
For economic prediction markets (Fed rates, inflation, unemployment), Claude currently estimates from training data alone. But real-time government data is FREE and publicly available:
- FRED (Federal Reserve Economic Data): 800,000+ time series
- BLS (Bureau of Labor Statistics): employment, CPI, PPI
- Census Bureau: economic indicators
- Treasury Direct: yield curves, auction results
- NOAA: already partially implemented for weather

## Task

1. **FRED API integration (primary):**
   ```python
   class FREDClient:
       API_KEY = "..."  # Free at fred.stlouisfed.org/docs/api/api_key.html
       BASE_URL = "https://api.stlouisfed.org/fred"

       def get_series(self, series_id: str, limit: int = 10) -> list:
           """Fetch latest observations for a FRED series.

           Key series for prediction markets:
           - FEDFUNDS: Federal funds rate
           - CPIAUCSL: Consumer Price Index
           - UNRATE: Unemployment rate
           - GDP: Gross Domestic Product
           - T10YIE: 10-Year Breakeven Inflation Rate
           - DFF: Daily Federal Funds Rate
           - MORTGAGE30US: 30-Year Fixed Rate Mortgage
           - SP500: S&P 500 (proxy)
           """

       def get_release_calendar(self) -> list:
           """Fetch upcoming data release dates.
           BLS employment report, CPI release, FOMC meetings, etc.
           Markets often move on data releases — knowing the schedule is alpha."""
   ```

2. **Automatic context injection for economic markets:**
   - When a market question mentions "Fed", "rates", "inflation", "unemployment":
     - Fetch latest FRED data for relevant series
     - Fetch upcoming release dates
     - Format: "Latest data: Fed funds rate at 4.25% (as of Feb 2026). CPI: 3.1% YoY. Next FOMC: March 18-19, 2026."
   - Pass to Claude as context alongside market question

3. **Data release event detector:**
   - Many prediction markets resolve around data releases (e.g., "Will CPI come in above 3%?")
   - Build a release calendar monitor
   - When a data release is imminent (<24 hours), flag related markets as HIGH PRIORITY
   - Post-release: immediately re-analyze markets affected by the release (prices may not have adjusted yet)

4. **Treasury yield curve monitor:**
   - Fetch daily yield curve from Treasury Direct
   - Yield curve inversions predict recessions — relevant for economic markets
   - Compare current curve shape to historical patterns
   - Inject as context: "Yield curve: [normal/flat/inverted]. 2Y-10Y spread: [X]bp."

5. **NOAA expansion (from existing noaa_client.py):**
   - Current: 6 cities, NOAA only
   - Add: GFS forecast (via weather.gov API)
   - Add: HRRR (hourly, 3km resolution — best for 24h forecasts)
   - 30+ cities (per P0-26, 357 active weather markets cover 30+ cities)

## API Keys Needed
- FRED API key: Free at https://fred.stlouisfed.org/docs/api/api_key.html
- No key needed for weather.gov, Treasury Direct, or BLS APIs

## Files to Create/Modify
- NEW: `src/data/fred_client.py`
- NEW: `src/data/treasury_client.py`
- NEW: `src/data/release_calendar.py`
- MODIFY: `src/noaa_client.py` → `src/data/weather_client.py` — expand to multi-model
- MODIFY: `src/context_enricher.py` — add government data sources
- Add to `.env`: `FRED_API_KEY=...`

## Expected Outcome
- Claude receives real government data for every economic market
- Data release event detection gives us first-mover advantage
- Weather forecasting expanded from 6 to 30+ cities with multiple models
- All free data — no additional API cost beyond what we already have
