"""Tests for news_client and sentiment_scorer modules."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.news_client import (
    NewsArticle,
    NewsClient,
    _compute_sentiment_score,
    _empty_news_result,
    _parse_date,
    extract_keywords,
)
from src.sentiment_scorer import SentimentFlag, format_headlines_for_prompt, score_news_data


# ──────────────────────────────────────────────
# extract_keywords
# ──────────────────────────────────────────────
class TestExtractKeywords:
    def test_basic_extraction(self):
        q = "Will Bitcoin reach $100,000 by December 2025?"
        kws = extract_keywords(q)
        assert len(kws) <= 3
        assert "bitcoin" in kws

    def test_strips_stop_words(self):
        q = "Will the price of gold be above 2000?"
        kws = extract_keywords(q)
        assert "will" not in kws
        assert "the" not in kws

    def test_empty_question(self):
        assert extract_keywords("") == []

    def test_max_keywords_respected(self):
        q = "Climate change policy economic growth renewable energy carbon emissions"
        kws = extract_keywords(q, max_keywords=2)
        assert len(kws) == 2

    def test_short_words_excluded(self):
        q = "Is AI ok to use?"
        kws = extract_keywords(q)
        # "is", "ai", "ok", "to" are <= 2 chars or stop words
        assert "is" not in kws
        assert "to" not in kws


# ──────────────────────────────────────────────
# _parse_date
# ──────────────────────────────────────────────
class TestParseDate:
    def test_standard_format(self):
        dt = _parse_date("2024-06-15 14:30:00")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 6
        assert dt.tzinfo == timezone.utc

    def test_iso_format(self):
        dt = _parse_date("2024-06-15T14:30:00Z")
        assert dt is not None

    def test_none_input(self):
        assert _parse_date(None) is None

    def test_bad_format(self):
        assert _parse_date("not-a-date") is None


# ──────────────────────────────────────────────
# _compute_sentiment_score
# ──────────────────────────────────────────────
class TestComputeSentiment:
    def test_all_positive(self):
        articles = [
            NewsArticle("A", "", None, "", "positive", ""),
            NewsArticle("B", "", None, "", "positive", ""),
        ]
        assert _compute_sentiment_score(articles) == 1.0

    def test_all_negative(self):
        articles = [
            NewsArticle("A", "", None, "", "negative", ""),
            NewsArticle("B", "", None, "", "negative", ""),
        ]
        assert _compute_sentiment_score(articles) == -1.0

    def test_mixed(self):
        articles = [
            NewsArticle("A", "", None, "", "positive", ""),
            NewsArticle("B", "", None, "", "negative", ""),
        ]
        assert _compute_sentiment_score(articles) == 0.0

    def test_no_sentiment_data(self):
        articles = [
            NewsArticle("A", "", None, "", None, ""),
        ]
        assert _compute_sentiment_score(articles) == 0.0

    def test_empty_list(self):
        assert _compute_sentiment_score([]) == 0.0


# ──────────────────────────────────────────────
# _empty_news_result
# ──────────────────────────────────────────────
class TestEmptyResult:
    def test_structure(self):
        result = _empty_news_result(["bitcoin", "price"])
        assert result["article_count"] == 0
        assert result["headlines"] == []
        assert result["sentiment_score"] == 0.0
        assert result["freshness_hours"] is None
        assert result["keywords_used"] == ["bitcoin", "price"]


# ──────────────────────────────────────────────
# NewsClient
# ──────────────────────────────────────────────
class TestNewsClient:
    def test_not_configured_without_key(self):
        client = NewsClient(api_key="")
        assert not client.is_configured

    def test_configured_with_key(self):
        client = NewsClient(api_key="test_key_123")
        assert client.is_configured

    @pytest.mark.asyncio
    async def test_fetch_news_no_key_returns_empty(self):
        client = NewsClient(api_key="")
        result = await client.fetch_news(["bitcoin"])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_news_for_market_no_key(self):
        client = NewsClient(api_key="")
        result = await client.fetch_news_for_market("Will Bitcoin hit 100k?")
        assert result["article_count"] == 0

    @pytest.mark.asyncio
    async def test_fetch_news_success(self):
        """Test successful API response parsing."""
        client = NewsClient(api_key="test_key")

        now = datetime.now(timezone.utc)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "results": [
                {
                    "title": "Bitcoin surges past 90k",
                    "description": "Crypto markets rally",
                    "pubDate": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_id": "reuters",
                    "sentiment": "positive",
                    "link": "https://example.com/1",
                },
                {
                    "title": "Regulation fears mount",
                    "description": "SEC review upcoming",
                    "pubDate": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_id": "bloomberg",
                    "sentiment": "negative",
                    "link": "https://example.com/2",
                },
            ],
        }

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        client._client = mock_http_client

        articles = await client.fetch_news(["bitcoin", "price"])
        assert len(articles) == 2
        assert articles[0].title == "Bitcoin surges past 90k"

    @pytest.mark.asyncio
    async def test_fetch_news_for_market_integration(self):
        """Test the full fetch_news_for_market pipeline with mocked HTTP."""
        client = NewsClient(api_key="test_key")

        now = datetime.now(timezone.utc)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "results": [
                {
                    "title": "SpaceX launch success",
                    "description": "Starship reaches orbit",
                    "pubDate": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_id": "spacenews",
                    "sentiment": "positive",
                    "link": "https://example.com/spacex",
                },
            ],
        }

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        client._client = mock_http_client

        result = await client.fetch_news_for_market("Will SpaceX launch Starship successfully?")
        assert result["article_count"] == 1
        assert "SpaceX launch success" in result["headlines"]
        assert result["sentiment_score"] == 1.0
        assert result["freshness_hours"] is not None


# ──────────────────────────────────────────────
# score_news_data (sentiment_scorer)
# ──────────────────────────────────────────────
class TestScoreNewsData:
    def test_no_coverage(self):
        result = _empty_news_result(["test"])
        flag = score_news_data(result)
        assert flag.flag == "no_news_coverage"
        assert flag.confidence_modifier == -0.05

    def test_positive_momentum(self):
        result = {
            "headlines": ["Good news 1", "Good news 2", "Good news 3", "Good news 4"],
            "article_count": 4,
            "sentiment_score": 0.75,
            "freshness_hours": 2.0,
            "keywords_used": ["test"],
            "raw_articles": [],
        }
        flag = score_news_data(result)
        assert flag.flag == "news_driven_momentum"
        assert flag.direction == "positive"
        assert flag.confidence_modifier == 0.05

    def test_negative_momentum(self):
        result = {
            "headlines": ["Bad news 1", "Bad news 2", "Bad news 3"],
            "article_count": 3,
            "sentiment_score": -0.6,
            "freshness_hours": 1.0,
            "keywords_used": ["test"],
            "raw_articles": [],
        }
        flag = score_news_data(result)
        assert flag.flag == "news_driven_momentum"
        assert flag.direction == "negative"
        assert flag.confidence_modifier == -0.05

    def test_normal_coverage(self):
        result = {
            "headlines": ["Some news"],
            "article_count": 1,
            "sentiment_score": 0.2,
            "freshness_hours": 12.0,
            "keywords_used": ["test"],
            "raw_articles": [],
        }
        flag = score_news_data(result)
        assert flag.flag == "normal_coverage"
        assert flag.confidence_modifier == 0.0

    def test_high_volume_but_neutral_sentiment(self):
        """Many articles but neutral — should be normal, not momentum."""
        result = {
            "headlines": ["A", "B", "C", "D", "E"],
            "article_count": 5,
            "sentiment_score": 0.1,
            "freshness_hours": 3.0,
            "keywords_used": ["test"],
            "raw_articles": [],
        }
        flag = score_news_data(result)
        assert flag.flag == "normal_coverage"

    def test_stale_news_not_momentum(self):
        """Old articles shouldn't trigger momentum even with strong sentiment."""
        result = {
            "headlines": ["A", "B", "C", "D"],
            "article_count": 4,
            "sentiment_score": 0.9,
            "freshness_hours": 36.0,  # > 24h threshold
            "keywords_used": ["test"],
            "raw_articles": [],
        }
        flag = score_news_data(result)
        assert flag.flag == "normal_coverage"


# ──────────────────────────────────────────────
# format_headlines_for_prompt
# ──────────────────────────────────────────────
class TestFormatHeadlines:
    def test_empty(self):
        result = _empty_news_result(["x"])
        assert format_headlines_for_prompt(result) == ""

    def test_formats_headlines(self):
        result = {
            "headlines": ["Headline A", "Headline B"],
            "article_count": 2,
            "sentiment_score": 0.5,
            "freshness_hours": 3.0,
        }
        output = format_headlines_for_prompt(result)
        assert "Headline A" in output
        assert "Headline B" in output
        assert "2 articles found" in output
        assert "sentiment: +0.50" in output

    def test_max_headlines_respected(self):
        result = {
            "headlines": [f"H{i}" for i in range(10)],
            "article_count": 10,
            "sentiment_score": 0.0,
            "freshness_hours": 1.0,
        }
        output = format_headlines_for_prompt(result, max_headlines=3)
        assert "H0" in output
        assert "H2" in output
        assert "H3" not in output
