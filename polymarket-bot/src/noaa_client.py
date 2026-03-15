"""NOAA Weather API client for weather market trading."""
import asyncio
import re
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

NOAA_API_BASE = "https://api.weather.gov"

# City coordinates for NOAA forecast lookups
CITY_COORDINATES = {
    "Chicago": (41.8781, -87.6298),
    "NYC": (40.7128, -74.0060),
    "New York": (40.7128, -74.0060),
    "Dallas": (32.7767, -96.7970),
    "Miami": (25.7617, -80.1918),
    "Seattle": (47.6062, -122.3321),
    "Atlanta": (33.7490, -84.3880),
    "Los Angeles": (34.0522, -118.2437),
    "Denver": (39.7392, -104.9903),
    "Phoenix": (33.4484, -112.0740),
    "Houston": (29.7604, -95.3698),
    "Philadelphia": (39.9526, -75.1652),
    "San Francisco": (37.7749, -122.4194),
    "Boston": (42.3601, -71.0589),
    "Minneapolis": (44.9778, -93.2650),
}

# Common temperature bracket patterns in Polymarket weather markets
TEMP_BRACKET_PATTERN = re.compile(
    r"(\d+)\s*[°]?\s*[fF]?\s*(?:or\s+(?:higher|above|more))|"
    r"(?:above|over|higher\s+than|at\s+least)\s*(\d+)\s*[°]?\s*[fF]?|"
    r"(\d+)\s*[-–]\s*(\d+)\s*[°]?\s*[fF]?|"
    r"(?:below|under|less\s+than)\s*(\d+)\s*[°]?\s*[fF]?",
    re.IGNORECASE,
)


class NOAAClient:
    """Fetches weather forecasts from NOAA and maps to Polymarket outcomes."""

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._grid_cache: dict[str, dict] = {}  # city -> {office, gridX, gridY}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "PolymarketWeatherBot/1.0 (contact@example.com)"},
            )
        return self._client

    async def _request(self, url: str) -> dict:
        """Make a GET request to NOAA API with retries."""
        client = await self._get_client()
        for attempt in range(3):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    logger.warning("noaa_retry", url=url, attempt=attempt + 1, error=str(e))
                else:
                    logger.error("noaa_request_failed", url=url, error=str(e))
                    raise

    async def get_grid_info(self, city: str) -> dict:
        """Get NOAA grid info (forecast office, gridX, gridY) for a city.

        Args:
            city: City name (must be in CITY_COORDINATES)

        Returns:
            Dict with keys: office, gridX, gridY
        """
        if city in self._grid_cache:
            return self._grid_cache[city]

        coords = CITY_COORDINATES.get(city)
        if not coords:
            raise ValueError(f"Unknown city: {city}. Available: {list(CITY_COORDINATES.keys())}")

        lat, lon = coords
        url = f"{NOAA_API_BASE}/points/{lat},{lon}"

        data = await self._request(url)
        properties = data.get("properties", {})

        grid_info = {
            "office": properties.get("gridId", ""),
            "gridX": properties.get("gridX", 0),
            "gridY": properties.get("gridY", 0),
            "forecast_url": properties.get("forecast", ""),
            "forecast_hourly_url": properties.get("forecastHourly", ""),
        }

        self._grid_cache[city] = grid_info
        logger.info("noaa_grid_info", city=city, office=grid_info["office"])
        return grid_info

    async def get_forecast(self, city: str) -> list[dict]:
        """Get 7-day forecast for a city.

        Args:
            city: City name

        Returns:
            List of forecast period dicts with keys:
                name, temperature, temperatureUnit, shortForecast, detailedForecast, etc.
        """
        grid_info = await self.get_grid_info(city)
        url = grid_info.get("forecast_url")

        if not url:
            office = grid_info["office"]
            grid_x = grid_info["gridX"]
            grid_y = grid_info["gridY"]
            url = f"{NOAA_API_BASE}/gridpoints/{office}/{grid_x},{grid_y}/forecast"

        data = await self._request(url)
        periods = data.get("properties", {}).get("periods", [])

        logger.info("noaa_forecast_fetched", city=city, periods=len(periods))
        return periods

    async def get_hourly_forecast(self, city: str) -> list[dict]:
        """Get hourly forecast for a city (next 156 hours).

        Args:
            city: City name

        Returns:
            List of hourly forecast dicts
        """
        grid_info = await self.get_grid_info(city)
        url = grid_info.get("forecast_hourly_url")

        if not url:
            office = grid_info["office"]
            grid_x = grid_info["gridX"]
            grid_y = grid_info["gridY"]
            url = f"{NOAA_API_BASE}/gridpoints/{office}/{grid_x},{grid_y}/forecast/hourly"

        data = await self._request(url)
        periods = data.get("properties", {}).get("periods", [])

        logger.info("noaa_hourly_forecast_fetched", city=city, periods=len(periods))
        return periods

    async def get_48h_high_low(self, city: str) -> dict:
        """Get the forecast high and low temperatures for the next 48 hours.

        Args:
            city: City name

        Returns:
            Dict with keys: high_f, low_f, city, periods_checked
        """
        periods = await self.get_forecast(city)

        # NOAA 7-day forecast alternates day/night periods
        # Take first 4 periods (roughly 48 hours)
        relevant = periods[:4]

        temps = [p.get("temperature", 0) for p in relevant]
        units = [p.get("temperatureUnit", "F") for p in relevant]

        # Convert any Celsius to Fahrenheit
        temps_f = []
        for t, u in zip(temps, units):
            if u == "C":
                temps_f.append(t * 9 / 5 + 32)
            else:
                temps_f.append(t)

        result = {
            "city": city,
            "high_f": max(temps_f) if temps_f else None,
            "low_f": min(temps_f) if temps_f else None,
            "periods_checked": len(relevant),
            "forecasts": [
                {
                    "name": p.get("name", ""),
                    "temp_f": t,
                    "short": p.get("shortForecast", ""),
                }
                for p, t in zip(relevant, temps_f)
            ],
        }

        logger.info(
            "noaa_48h_high_low",
            city=city,
            high=result["high_f"],
            low=result["low_f"],
        )
        return result

    def evaluate_weather_market(
        self,
        forecast_high_f: float,
        forecast_low_f: float,
        market_question: str,
        market_price: float,
    ) -> dict:
        """Evaluate if a weather market is mispriced based on NOAA forecast.

        Args:
            forecast_high_f: Forecasted high temperature in Fahrenheit
            forecast_low_f: Forecasted low temperature in Fahrenheit
            market_question: The Polymarket market question
            market_price: Current market YES price

        Returns:
            Dict with keys: estimated_prob, edge, signal, reasoning
        """
        question_lower = market_question.lower()

        # Try to extract temperature thresholds from the question
        estimated_prob = 0.5  # default
        reasoning = "Could not parse temperature threshold from question"

        # Pattern: "Will the high be above X°F?"
        above_match = re.search(
            r"(?:above|over|higher\s+than|at\s+least|exceed)\s*(\d+)", question_lower
        )
        below_match = re.search(
            r"(?:below|under|less\s+than|at\s+most)\s*(\d+)", question_lower
        )
        range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", question_lower)

        is_high = "high" in question_lower or "max" in question_lower
        ref_temp = forecast_high_f if is_high else forecast_low_f

        if above_match:
            threshold = int(above_match.group(1))
            diff = ref_temp - threshold
            # Simple sigmoid-like probability based on distance from threshold
            # NOAA is ~93% accurate, so we scale accordingly
            if diff > 10:
                estimated_prob = 0.95
            elif diff > 5:
                estimated_prob = 0.85
            elif diff > 2:
                estimated_prob = 0.70
            elif diff > 0:
                estimated_prob = 0.60
            elif diff > -2:
                estimated_prob = 0.40
            elif diff > -5:
                estimated_prob = 0.25
            else:
                estimated_prob = 0.10
            reasoning = f"Forecast {'high' if is_high else 'low'}: {ref_temp:.0f}°F vs threshold {threshold}°F (diff: {diff:+.0f}°F)"

        elif below_match:
            threshold = int(below_match.group(1))
            diff = threshold - ref_temp
            if diff > 10:
                estimated_prob = 0.95
            elif diff > 5:
                estimated_prob = 0.85
            elif diff > 2:
                estimated_prob = 0.70
            elif diff > 0:
                estimated_prob = 0.60
            elif diff > -2:
                estimated_prob = 0.40
            elif diff > -5:
                estimated_prob = 0.25
            else:
                estimated_prob = 0.10
            reasoning = f"Forecast {'high' if is_high else 'low'}: {ref_temp:.0f}°F vs below-threshold {threshold}°F (diff: {diff:+.0f}°F)"

        elif range_match:
            low_bound = int(range_match.group(1))
            high_bound = int(range_match.group(2))
            if low_bound <= ref_temp <= high_bound:
                # Temperature is within range
                margin = min(ref_temp - low_bound, high_bound - ref_temp)
                if margin > 5:
                    estimated_prob = 0.80
                elif margin > 2:
                    estimated_prob = 0.65
                else:
                    estimated_prob = 0.50
            else:
                dist = min(abs(ref_temp - low_bound), abs(ref_temp - high_bound))
                if dist > 10:
                    estimated_prob = 0.05
                elif dist > 5:
                    estimated_prob = 0.15
                else:
                    estimated_prob = 0.30
            reasoning = f"Forecast {'high' if is_high else 'low'}: {ref_temp:.0f}°F vs range {low_bound}-{high_bound}°F"

        edge = estimated_prob - market_price

        if edge > 0.15:
            signal = "buy_yes"
        elif edge < -0.15:
            signal = "buy_no"
        else:
            signal = "hold"

        return {
            "estimated_prob": estimated_prob,
            "edge": edge,
            "signal": signal,
            "reasoning": reasoning,
            "forecast_high_f": forecast_high_f,
            "forecast_low_f": forecast_low_f,
        }

    async def scan_cities(self, cities: list[str]) -> dict[str, dict]:
        """Fetch 48-hour forecasts for multiple cities.

        Args:
            cities: List of city names

        Returns:
            Dict mapping city name to forecast data
        """
        results = {}
        for city in cities:
            try:
                result = await self.get_48h_high_low(city)
                results[city] = result
                await asyncio.sleep(0.3)  # Rate limit: ~3 req/sec
            except Exception as e:
                logger.error("noaa_city_scan_failed", city=city, error=str(e))
                results[city] = {"city": city, "error": str(e)}

        logger.info("noaa_city_scan_complete", cities_scanned=len(results))
        return results

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
