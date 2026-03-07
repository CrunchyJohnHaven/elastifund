"""Rule-based sentiment scoring that flags news-driven momentum or low coverage."""
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Thresholds
MIN_ARTICLES_FOR_MOMENTUM = 3
MAX_FRESHNESS_HOURS_FOR_MOMENTUM = 24
STRONG_POSITIVE_THRESHOLD = 0.6
STRONG_NEGATIVE_THRESHOLD = -0.4


@dataclass
class SentimentFlag:
    """Result of rule-based sentiment analysis on news data."""

    flag: str  # "news_driven_momentum", "no_news_coverage", "normal_coverage"
    direction: Optional[str]  # "positive", "negative", or None
    confidence_modifier: float  # -0.1 to +0.1 adjustment suggestion
    summary: str  # Human-readable explanation

    def to_dict(self) -> dict:
        return {
            "flag": self.flag,
            "direction": self.direction,
            "confidence_modifier": self.confidence_modifier,
            "summary": self.summary,
        }


def score_news_data(news_result: dict) -> SentimentFlag:
    """Apply rule-based scoring to news fetch results.

    Rules:
    - If >3 articles in 24h AND sentiment strongly directional (>0.6 or <-0.4),
      flag as "news_driven_momentum"
    - If zero articles, flag as "no_news_coverage" (suggests lower confidence)
    - Otherwise, flag as "normal_coverage"

    Args:
        news_result: Dict from NewsClient.fetch_news_for_market() with keys:
            headlines, article_count, sentiment_score, freshness_hours, etc.

    Returns:
        SentimentFlag with classification and confidence adjustment
    """
    article_count = news_result.get("article_count", 0)
    sentiment_score = news_result.get("sentiment_score", 0.0)
    freshness_hours = news_result.get("freshness_hours")
    headlines = news_result.get("headlines", [])

    # Rule 1: No news coverage at all
    if article_count == 0:
        return SentimentFlag(
            flag="no_news_coverage",
            direction=None,
            confidence_modifier=-0.05,
            summary="No recent news articles found. Lower confidence in estimate.",
        )

    # Rule 2: Strong news-driven momentum
    is_recent = freshness_hours is not None and freshness_hours <= MAX_FRESHNESS_HOURS_FOR_MOMENTUM
    has_volume = article_count >= MIN_ARTICLES_FOR_MOMENTUM
    is_strongly_positive = sentiment_score >= STRONG_POSITIVE_THRESHOLD
    is_strongly_negative = sentiment_score <= STRONG_NEGATIVE_THRESHOLD

    if has_volume and is_recent and (is_strongly_positive or is_strongly_negative):
        direction = "positive" if is_strongly_positive else "negative"
        modifier = 0.05 if is_strongly_positive else -0.05

        top_headlines = headlines[:3]
        headline_str = "; ".join(top_headlines)

        return SentimentFlag(
            flag="news_driven_momentum",
            direction=direction,
            confidence_modifier=modifier,
            summary=(
                f"News-driven {direction} momentum detected: "
                f"{article_count} articles, sentiment={sentiment_score:+.2f}. "
                f"Top headlines: {headline_str}"
            ),
        )

    # Rule 3: Normal coverage — neither extreme
    return SentimentFlag(
        flag="normal_coverage",
        direction=None,
        confidence_modifier=0.0,
        summary=(
            f"Normal news coverage: {article_count} articles, "
            f"sentiment={sentiment_score:+.2f}."
        ),
    )


def format_headlines_for_prompt(news_result: dict, max_headlines: int = 5) -> str:
    """Format news headlines into a string suitable for inclusion in Claude's prompt.

    Args:
        news_result: Dict from NewsClient.fetch_news_for_market()
        max_headlines: Maximum headlines to include

    Returns:
        Formatted string, or empty string if no news
    """
    headlines = news_result.get("headlines", [])
    if not headlines:
        return ""

    lines = []
    for i, headline in enumerate(headlines[:max_headlines], 1):
        lines.append(f"  {i}. {headline}")

    article_count = news_result.get("article_count", 0)
    sentiment_score = news_result.get("sentiment_score", 0.0)
    freshness = news_result.get("freshness_hours")

    meta_parts = [f"{article_count} articles found"]
    if freshness is not None:
        meta_parts.append(f"newest {freshness:.0f}h ago")
    meta_parts.append(f"aggregate sentiment: {sentiment_score:+.2f}")

    header = f"Recent news ({', '.join(meta_parts)}):"
    return header + "\n" + "\n".join(lines)
