# P0-28: Weather Multi-Model Consensus (GFS + ECMWF + HRRR)
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +15-25% on weather trades (our structural edge)

## Background (from P0-26 research)
Weather arbitrage is the most viable LLM-adjacent strategy because:
- NOAA 24h accuracy: 95-96%, MAE 2-3°F (within 2°F Polymarket bucket width)
- Retail bettors lag professional forecast updates by minutes to hours
- Systematic favorite-longshot bias confirmed in weather markets (Whelan 2025)

Current system uses NOAA only. Research recommends multi-model consensus:
- **GFS:** Global Forecast System, 4× daily updates, 13km resolution
- **ECMWF:** European model, ~1 day accuracy advantage for medium-range
- **HRRR:** High-Resolution Rapid Refresh, HOURLY updates, 3km US resolution (best short-range)

## Task
1. **Add HRRR integration:** HRRR updates hourly via NOAA's NOMADS. Parse GRIB2 data or use the NWS API (api.weather.gov, free, no key needed) which already incorporates HRRR.
2. **Add ECMWF integration:** Use ECMWF's open data API or Weather API alternatives. May need API key.
3. **Multi-model consensus:** For each city/timeframe, average across models. Weight by historical accuracy at that forecast horizon.
4. **Entry timing optimization:** GFS updates at 00/06/12/18 UTC. HRRR updates hourly. Build a system that triggers market scans immediately after fresh model runs when Polymarket prices haven't yet adjusted.
5. **Expand city coverage:** Current: 6 cities. Research which cities have the most active Polymarket weather markets and add them.

## Architecture
```python
class WeatherConsensus:
    def get_forecast(self, city, horizon_hours):
        gfs = self.gfs_client.get_temp(city, horizon_hours)
        hrrr = self.hrrr_client.get_temp(city, horizon_hours)
        ecmwf = self.ecmwf_client.get_temp(city, horizon_hours)
        # Weight by accuracy at this horizon
        weights = self.get_weights(horizon_hours)
        return weighted_average([gfs, hrrr, ecmwf], weights)
```

## Expected Outcome
- Weather forecast accuracy improvement from single-model to consensus
- Better entry timing by monitoring model update cycles
- More weather markets covered
