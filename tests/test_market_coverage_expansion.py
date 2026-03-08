"""Tests for expanded market scanner with diversity and quarantine.

Verifies:
- Category detection from tags and keywords
- Diverse market selection across categories
- CLOB 404 quarantine integration
- Scanner returns 50+ markets with proper filtering
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.expanded_scanner import (
    ExpandedScanner,
    MarketSnapshot,
    detect_category,
    CATEGORY_TARGETS,
)
from bot.market_quarantine import MarketQuarantine


def _make_market(
    market_id: str,
    question: str = "Will X happen?",
    yes_price: float = 0.50,
    volume: float = 5000.0,
    tags: list | None = None,
    token_ids: list | None = None,
):
    """Create a mock Gamma API market dict."""
    if tags is None:
        tags = []
    if token_ids is None:
        token_ids = [f"yes_{market_id}", f"no_{market_id}"]
    return {
        "id": market_id,
        "question": question,
        "outcomePrices": json.dumps([yes_price, 1.0 - yes_price]),
        "volume": str(volume),
        "liquidity": str(volume * 0.3),
        "clobTokenIds": json.dumps(token_ids),
        "tags": tags,
        "endDate": "2026-04-01T00:00:00Z",
    }


class TestCategoryDetection:
    def test_politics_tag(self):
        market = {"tags": ["politics"], "question": "Will the bill pass?"}
        assert detect_category(market) == "politics"

    def test_crypto_keyword(self):
        market = {"tags": [], "question": "Will Bitcoin reach $100k?"}
        assert detect_category(market) == "crypto"

    def test_sports_keyword(self):
        market = {"tags": [], "question": "Will the NBA finals go to game 7?"}
        assert detect_category(market) == "sports"

    def test_weather_keyword(self):
        market = {"tags": [], "question": "Will the temperature exceed 100F?"}
        assert detect_category(market) == "weather"

    def test_business_keyword(self):
        market = {"tags": [], "question": "Will the Fed raise interest rates?"}
        assert detect_category(market) == "business"

    def test_unknown_returns_other(self):
        market = {"tags": [], "question": "Will aliens land on Earth?"}
        assert detect_category(market) == "other"

    def test_tag_string_json(self):
        market = {"tags": '["crypto", "defi"]', "question": "Some question"}
        assert detect_category(market) == "crypto"


class TestMarketParsing:
    @pytest.fixture
    def scanner(self, tmp_path):
        q = MarketQuarantine(db_path=tmp_path / "test.db")
        return ExpandedScanner(quarantine=q)

    def test_parse_valid_market(self, scanner):
        raw = _make_market("m1", "Will Trump win?", yes_price=0.60, tags=["politics"])
        snapshot = scanner._parse_market(raw)
        assert snapshot is not None
        assert snapshot.market_id == "m1"
        assert snapshot.yes_price == pytest.approx(0.60)
        assert snapshot.category == "politics"

    def test_parse_skips_quarantined(self, scanner):
        scanner.quarantine.quarantine("m_quarantined", id_type="market_id")
        raw = _make_market("m_quarantined")
        assert scanner._parse_market(raw) is None

    def test_parse_skips_quarantined_token(self, scanner):
        scanner.quarantine.quarantine("yes_m2", id_type="token_id")
        raw = _make_market("m2", token_ids=["yes_m2"])
        # All tokens quarantined → returns None
        assert scanner._parse_market(raw) is None

    def test_parse_no_prices(self, scanner):
        raw = {"id": "m3", "question": "Test", "volume": "5000", "clobTokenIds": '["a","b"]'}
        assert scanner._parse_market(raw) is None

    def test_parse_zero_price(self, scanner):
        raw = _make_market("m4", yes_price=0.0)
        assert scanner._parse_market(raw) is None


class TestDiverseScanning:
    @pytest.fixture
    def scanner(self, tmp_path):
        q = MarketQuarantine(db_path=tmp_path / "test.db")
        return ExpandedScanner(quarantine=q, target_market_count=50, min_volume=100.0)

    def _generate_mock_markets(self, count_per_category: int = 12) -> list[dict]:
        """Generate a diverse set of mock markets."""
        markets = []
        categories = {
            "politics": "Will the president sign the bill?",
            "crypto": "Will Bitcoin hit $50k?",
            "sports": "Will the NBA team win the championship?",
            "science": "Will NASA launch the rocket?",
            "business": "Will the stock market crash?",
            "other": "Will it happen today?",
        }
        idx = 0
        for cat, question in categories.items():
            for i in range(count_per_category):
                idx += 1
                markets.append(_make_market(
                    f"m_{idx}",
                    question=f"{question} #{i}",
                    yes_price=0.30 + (i % 5) * 0.1,
                    volume=5000 + i * 100,
                    tags=[cat],
                ))
        return markets

    @pytest.mark.asyncio
    async def test_diverse_scan_returns_markets(self, scanner):
        mock_markets = self._generate_mock_markets(count_per_category=12)
        with patch.object(scanner, "fetch_all_markets", new_callable=AsyncMock, return_value=mock_markets):
            results = await scanner.scan_diverse_markets()
            assert len(results) >= 50
            assert all(isinstance(m, MarketSnapshot) for m in results)

    @pytest.mark.asyncio
    async def test_diverse_scan_has_category_diversity(self, scanner):
        mock_markets = self._generate_mock_markets(count_per_category=12)
        with patch.object(scanner, "fetch_all_markets", new_callable=AsyncMock, return_value=mock_markets):
            results = await scanner.scan_diverse_markets()
            categories = {m.category for m in results}
            assert len(categories) >= 3

    @pytest.mark.asyncio
    async def test_scan_filters_low_volume(self, scanner):
        markets = [
            _make_market("low_vol", volume=10.0),
            _make_market("high_vol", volume=5000.0),
        ]
        with patch.object(scanner, "fetch_all_markets", new_callable=AsyncMock, return_value=markets):
            results = await scanner.scan_diverse_markets()
            assert len(results) == 1
            assert results[0].market_id == "high_vol"

    @pytest.mark.asyncio
    async def test_scan_skips_quarantined(self, scanner):
        scanner.quarantine.quarantine("m_blocked", id_type="market_id")
        markets = [
            _make_market("m_blocked", volume=5000.0),
            _make_market("m_ok", volume=5000.0),
        ]
        with patch.object(scanner, "fetch_all_markets", new_callable=AsyncMock, return_value=markets):
            results = await scanner.scan_diverse_markets()
            ids = {m.market_id for m in results}
            assert "m_blocked" not in ids
            assert "m_ok" in ids


class TestCLOBSafeFetch:
    @pytest.fixture
    def scanner(self, tmp_path):
        q = MarketQuarantine(db_path=tmp_path / "test.db")
        return ExpandedScanner(quarantine=q)

    @pytest.mark.asyncio
    async def test_404_triggers_quarantine(self, scanner):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        scanner._client = mock_client

        result = await scanner.fetch_order_book_safe("token_404")
        assert result is None
        assert scanner.quarantine.is_quarantined("token_404")

    @pytest.mark.asyncio
    async def test_quarantined_token_skipped(self, scanner):
        scanner.quarantine.quarantine("token_blocked")
        result = await scanner.fetch_order_book_safe("token_blocked")
        assert result is None

    @pytest.mark.asyncio
    async def test_500_triggers_quarantine(self, scanner):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Internal Server Error", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        scanner._client = mock_client

        result = await scanner.fetch_order_book_safe("token_500")
        assert result is None
        assert scanner.quarantine.is_quarantined("token_500")
