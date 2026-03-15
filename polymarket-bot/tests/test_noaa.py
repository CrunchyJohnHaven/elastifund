"""Tests for the NOAA weather client."""
import pytest

from src.noaa_client import NOAAClient, CITY_COORDINATES


class TestNOAAClient:
    def test_city_coordinates_exist(self):
        assert len(CITY_COORDINATES) > 0
        assert "Chicago" in CITY_COORDINATES
        assert "NYC" in CITY_COORDINATES
        assert "Miami" in CITY_COORDINATES

    def test_city_coordinates_valid(self):
        for city, (lat, lon) in CITY_COORDINATES.items():
            assert -90 <= lat <= 90, f"{city} lat out of range"
            assert -180 <= lon <= 180, f"{city} lon out of range"

    def test_evaluate_weather_above_threshold_likely(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=95.0,
            forecast_low_f=75.0,
            market_question="Will the high temperature be above 80°F?",
            market_price=0.30,
        )
        assert result["estimated_prob"] > 0.50
        assert result["edge"] > 0
        assert result["signal"] == "buy_yes"

    def test_evaluate_weather_above_threshold_unlikely(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=70.0,
            forecast_low_f=55.0,
            market_question="Will the high temperature be above 90°F?",
            market_price=0.80,
        )
        assert result["estimated_prob"] < 0.50
        assert result["edge"] < 0
        assert result["signal"] == "buy_no"

    def test_evaluate_weather_below_threshold(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=65.0,
            forecast_low_f=50.0,
            market_question="Will the high temperature be below 70°F?",
            market_price=0.30,
        )
        assert result["estimated_prob"] > 0.50
        assert result["signal"] == "buy_yes"

    def test_evaluate_weather_range(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=82.0,
            forecast_low_f=68.0,
            market_question="Will the high temperature be 75-85°F?",
            market_price=0.50,
        )
        # 82 is within 75-85 range
        assert result["estimated_prob"] > 0.50

    def test_evaluate_weather_range_outside(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=95.0,
            forecast_low_f=78.0,
            market_question="Will the high temperature be 60-70°F?",
            market_price=0.50,
        )
        # 95 is well outside 60-70
        assert result["estimated_prob"] < 0.30

    def test_evaluate_weather_hold_when_close(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=81.0,
            forecast_low_f=65.0,
            market_question="Will the high temperature be above 80°F?",
            market_price=0.60,
        )
        # Forecast is barely above threshold, market at 0.60 is reasonable
        assert result["signal"] == "hold"

    def test_evaluate_weather_unparseable_question(self):
        client = NOAAClient()
        result = client.evaluate_weather_market(
            forecast_high_f=85.0,
            forecast_low_f=70.0,
            market_question="Will something happen?",
            market_price=0.50,
        )
        # Can't parse temperature threshold, defaults to hold
        assert result["estimated_prob"] == 0.50

    @pytest.mark.asyncio
    async def test_get_grid_info_unknown_city(self):
        client = NOAAClient()
        with pytest.raises(ValueError, match="Unknown city"):
            await client.get_grid_info("Atlantis")
