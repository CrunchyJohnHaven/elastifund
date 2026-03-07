"""Tests for the Gamma API market scanner."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.scanner import MarketScanner, WEATHER_KEYWORDS


class TestMarketScanner:
    def test_extract_token_ids_string(self):
        market = {"clobTokenIds": "abc123,def456"}
        assert MarketScanner.extract_token_ids(market) == ["abc123", "def456"]

    def test_extract_token_ids_list(self):
        market = {"clobTokenIds": ["abc123", "def456"]}
        assert MarketScanner.extract_token_ids(market) == ["abc123", "def456"]

    def test_extract_token_ids_missing(self):
        market = {}
        assert MarketScanner.extract_token_ids(market) == []

    def test_extract_prices_list(self):
        market = {"outcomePrices": [0.65, 0.35]}
        prices = MarketScanner.extract_prices(market)
        assert prices == {"YES": 0.65, "NO": 0.35}

    def test_extract_prices_json_string(self):
        market = {"outcomePrices": json.dumps([0.72, 0.28])}
        prices = MarketScanner.extract_prices(market)
        assert prices == {"YES": 0.72, "NO": 0.28}

    def test_extract_prices_empty(self):
        market = {}
        prices = MarketScanner.extract_prices(market)
        assert prices == {}

    def test_extract_prices_single_item(self):
        market = {"outcomePrices": [0.5]}
        prices = MarketScanner.extract_prices(market)
        assert prices == {}

    @pytest.mark.asyncio
    async def test_filter_liquid_markets(self):
        scanner = MarketScanner()
        markets = [
            {"volume": 5000, "liquidity": 2000, "question": "High volume"},
            {"volume": 100, "liquidity": 50, "question": "Low volume"},
            {"volume": 3000, "liquidity": 1000, "question": "Medium volume"},
        ]
        result = await scanner.filter_liquid_markets(markets, min_volume=1000, min_liquidity=500)
        assert len(result) == 2
        assert result[0]["question"] == "High volume"
        assert result[1]["question"] == "Medium volume"

    @pytest.mark.asyncio
    async def test_filter_liquid_markets_empty(self):
        scanner = MarketScanner()
        result = await scanner.filter_liquid_markets([], min_volume=1000, min_liquidity=500)
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_all_active_markets_stops_on_short_page(self):
        scanner = MarketScanner()
        scanner.fetch_active_markets = AsyncMock(
            side_effect=[
                [{"id": "1"}] * 100,
                [{"id": "2"}] * 25,
            ]
        )

        result = await scanner.fetch_all_active_markets(max_pages=10, page_size=100)

        assert len(result) == 125
        assert scanner.fetch_active_markets.await_count == 2

    @pytest.mark.asyncio
    async def test_fetch_all_active_markets_respects_max_pages(self):
        scanner = MarketScanner()
        scanner.fetch_active_markets = AsyncMock(return_value=[{"id": "x"}] * 100)

        result = await scanner.fetch_all_active_markets(max_pages=3, page_size=100)

        assert len(result) == 300
        assert scanner.fetch_active_markets.await_count == 3

    def test_weather_keywords_exist(self):
        assert len(WEATHER_KEYWORDS) > 0
        assert "temperature" in WEATHER_KEYWORDS
        assert "weather" in WEATHER_KEYWORDS
