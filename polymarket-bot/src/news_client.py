"""News headline fetcher for market analysis enrichment.

Sources:
  1. NewsData.io API (free tier: 200 req/day) — structured news search
  2. Google News RSS (no API key needed) — backup/fallback
"""
import asyncio
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx
import structlog

logger = structlog.get_logger(__name__)

NEWSDATA_API_BASE = "https://newsdata.io/api/1/latest"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

# Free tier: 200 requests/day, 10 results/request
MAX_RESULTS_PER_REQUEST = 10
DEFAULT_TIMEOUT = 15.0


class NewsArticle:
    """Lightweight container for a news article."""

    __slots__ = ("title", "description", "pub_date", "source", "sentiment", "link")

    def __init__(
        self,
        title: str,
        description: str,
        pub_date: Optional[datetime],
        source: str,
        sentiment: Optional[str],
        link: str,
    ):
        self.title = title
        self.description = description
        self.pub_date = pub_date
        self.source = source
        self.sentiment = sentiment  # "positive", "negative", "neutral" or None
        self.link = link

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "pub_date": self.pub_date.isoformat() if self.pub_date else None,
            "source": self.source,
            "sentiment": self.sentiment,
            "link": self.link,
        }


def extract_keywords(question: str, max_keywords: int = 3) -> list[str]:
    """Extract 2-3 search keywords from a market question.

    Strips common filler words and returns the most relevant terms.

    Args:
        question: Market question text
        max_keywords: Maximum keywords to return

    Returns:
        List of keyword strings for news search
    """
    # Remove punctuation and normalize
    text = re.sub(r"[^\w\s]", " ", question.lower())

    stop_words = {
        "will", "the", "be", "is", "are", "was", "were", "a", "an", "of",
        "in", "on", "at", "to", "for", "by", "with", "from", "or", "and",
        "this", "that", "it", "its", "do", "does", "did", "has", "have",
        "had", "been", "being", "would", "could", "should", "may", "might",
        "shall", "can", "yes", "no", "before", "after", "above", "below",
        "between", "during", "than", "more", "less", "over", "under",
        "what", "which", "who", "whom", "where", "when", "how", "not",
        "if", "then", "so", "but", "about", "up", "down", "into",
    }

    words = [w for w in text.split() if w not in stop_words and len(w) > 2]

    # Prefer longer / more specific words (likely proper nouns or key terms)
    words.sort(key=lambda w: len(w), reverse=True)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique[:max_keywords]


class NewsClient:
    """Fetches recent news from NewsData.io for market topic enrichment."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """Initialize news client.

        Args:
            api_key: NewsData.io API key (falls back to NEWSDATA_API_KEY env var)
            timeout: HTTP request timeout in seconds
        """
        self.api_key = api_key or os.getenv("NEWSDATA_API_KEY", "")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._request_count = 0  # track daily usage

    @property
    def is_configured(self) -> bool:
        """Check if an API key is available."""
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def fetch_news(
        self,
        keywords: list[str],
        hours_back: int = 48,
        language: str = "en",
    ) -> list[NewsArticle]:
        """Search for recent news articles matching keywords.

        Args:
            keywords: Search terms (will be joined with AND)
            hours_back: How far back to search (max 48 on free tier)
            language: Language code

        Returns:
            List of NewsArticle objects, newest first
        """
        if not self.is_configured:
            logger.warning("news_client_not_configured")
            return []

        query = " AND ".join(keywords)
        params = {
            "apikey": self.api_key,
            "q": query,
            "language": language,
            "size": MAX_RESULTS_PER_REQUEST,
        }

        client = await self._get_client()
        try:
            response = await client.get(NEWSDATA_API_BASE, params=params)
            response.raise_for_status()
            data = response.json()
            self._request_count += 1
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.error("news_fetch_failed", query=query, error=str(e))
            return []

        status = data.get("status")
        if status != "success":
            logger.warning("news_api_error", status=status, message=data.get("results", {}).get("message"))
            return []

        articles_raw = data.get("results") or []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        articles = []
        for raw in articles_raw:
            pub_str = raw.get("pubDate")
            pub_date = _parse_date(pub_str)

            # Filter by recency
            if pub_date and pub_date < cutoff:
                continue

            articles.append(
                NewsArticle(
                    title=raw.get("title") or "",
                    description=raw.get("description") or "",
                    pub_date=pub_date,
                    source=raw.get("source_id") or raw.get("source_name") or "",
                    sentiment=raw.get("sentiment"),
                    link=raw.get("link") or "",
                )
            )

        # Sort newest first
        articles.sort(key=lambda a: a.pub_date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        logger.info(
            "news_fetched",
            query=query,
            total_results=len(articles_raw),
            recent_results=len(articles),
            hours_back=hours_back,
        )
        return articles

    async def _fetch_google_news_rss(self, keywords: list[str]) -> list[NewsArticle]:
        """Fetch from Google News RSS (no API key required). Backup source."""
        query = " ".join(keywords)
        url = f"{GOOGLE_NEWS_RSS}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        client = await self._get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.warning("google_news_rss_failed", error=str(e))
            return []

        articles = []
        try:
            root = ET.fromstring(resp.text)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                source_el = item.find("source")
                pub_el = item.find("pubDate")

                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                if not title:
                    continue
                source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"
                pub_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
                pub_date = _parse_date(pub_str)

                articles.append(NewsArticle(
                    title=title,
                    description="",
                    pub_date=pub_date,
                    source=source,
                    sentiment=None,
                    link="",
                ))
        except ET.ParseError as e:
            logger.warning("google_news_rss_parse_error", error=str(e))

        logger.info("google_news_rss_fetched", query=query, count=len(articles))
        return articles[:MAX_RESULTS_PER_REQUEST]

    async def fetch_news_for_market(
        self,
        question: str,
        hours_back: int = 48,
    ) -> dict:
        """Fetch news for a market question and return a summary dict.

        This is the main entry point for the integration layer.

        Args:
            question: Market question text
            hours_back: Look-back window in hours

        Returns:
            Dict with keys: headlines, article_count, sentiment_score,
            freshness_hours, keywords_used, raw_articles
        """
        keywords = extract_keywords(question)
        if not keywords:
            return _empty_news_result(keywords)

        articles = await self.fetch_news(keywords, hours_back=hours_back)

        # Fallback to Google News RSS if NewsData.io returned nothing
        if not articles:
            articles = await self._fetch_google_news_rss(keywords)

        if not articles:
            return _empty_news_result(keywords)

        # Compute aggregate sentiment score (-1 to +1)
        sentiment_score = _compute_sentiment_score(articles)

        # Freshness: hours since the newest article
        now = datetime.now(timezone.utc)
        newest = articles[0].pub_date
        freshness_hours = (now - newest).total_seconds() / 3600 if newest else None

        headlines = [a.title for a in articles if a.title]

        return {
            "headlines": headlines,
            "article_count": len(articles),
            "sentiment_score": sentiment_score,
            "freshness_hours": round(freshness_hours, 1) if freshness_hours is not None else None,
            "keywords_used": keywords,
            "raw_articles": [a.to_dict() for a in articles],
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


def _empty_news_result(keywords: list[str]) -> dict:
    """Return a result dict when no news is found."""
    return {
        "headlines": [],
        "article_count": 0,
        "sentiment_score": 0.0,
        "freshness_hours": None,
        "keywords_used": keywords,
        "raw_articles": [],
    }


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string from NewsData.io (format: 2024-01-15 14:30:00)."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _compute_sentiment_score(articles: list[NewsArticle]) -> float:
    """Compute aggregate sentiment score from articles.

    Uses NewsData.io's built-in sentiment field when available,
    otherwise defaults to 0 (neutral).

    Returns:
        Float between -1.0 (all negative) and +1.0 (all positive)
    """
    if not articles:
        return 0.0

    score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    scores = []
    for a in articles:
        if a.sentiment and a.sentiment.lower() in score_map:
            scores.append(score_map[a.sentiment.lower()])

    if not scores:
        return 0.0

    return round(sum(scores) / len(scores), 3)
