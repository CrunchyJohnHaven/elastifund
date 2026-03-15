"""Claude sentiment analysis strategy using Anthropic API, enriched with news data."""
from datetime import datetime, timedelta
from src.core.time_utils import utc_now_naive
from typing import Optional

import structlog

from .base import Strategy

logger = structlog.get_logger(__name__)


class ClaudeSentimentStrategy(Strategy):
    """Strategy that uses Claude Haiku for market sentiment analysis.

    Optionally enriches Claude's prompt with recent news headlines
    fetched via NewsClient + SentimentScorer.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cooldown_minutes: int = 30,
        enable_news: bool = True,
        newsdata_api_key: Optional[str] = None,
    ):
        """Initialize Claude sentiment strategy.

        Args:
            api_key: Anthropic API key (uses env var if not provided)
            cooldown_minutes: Cooldown between re-analyzing same market
            enable_news: Whether to fetch news context for Claude's prompt
            newsdata_api_key: NewsData.io API key (uses env var if not provided)
        """
        self.api_key = api_key
        self.cooldown_minutes = cooldown_minutes
        self.enable_news = enable_news
        self.last_analysis = {}  # market_id -> datetime
        self._client = None
        self._news_client = None

        if self.api_key or self._check_env_api_key():
            try:
                from anthropic import Anthropic

                self._client = Anthropic(api_key=self.api_key) if self.api_key else Anthropic()
            except ImportError:
                logger.error("anthropic package not installed")
                self._client = None

        # Initialize news client if enabled
        if self.enable_news:
            try:
                from src.news_client import NewsClient

                self._news_client = NewsClient(api_key=newsdata_api_key)
                if not self._news_client.is_configured:
                    logger.warning("news_client_no_api_key, news enrichment disabled")
                    self._news_client = None
            except ImportError:
                logger.warning("news_client_import_failed")
                self._news_client = None

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "ClaudeSentiment"

    async def generate_signal(self, market_state: dict) -> dict:
        """Generate signal using Claude sentiment analysis.

        Args:
            market_state: Market state dict with question, current_price, etc.

        Returns:
            Signal dict with action, size, confidence, reason
        """
        market_id = market_state.get("market_id", "unknown")
        question = market_state.get("question", "")
        current_price = market_state.get("current_price")

        # Check if API key is available
        if not self._client or not self.api_key:
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": "Claude API not configured",
            }

        # Check cooldown
        if not self._should_analyze(market_id):
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": f"Cooldown active ({self.cooldown_minutes}min)",
            }

        if not question or current_price is None:
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": "Missing question or price data",
            }

        try:
            # Fetch news context (non-blocking; degrades gracefully)
            news_result = None
            sentiment_flag = None
            if self._news_client:
                news_result, sentiment_flag = await self._fetch_news_context(question)

            # Get Claude's probability estimate (with optional news context)
            claude_estimate = await self._get_claude_estimate(
                question, current_price, news_result=news_result
            )

            if claude_estimate is None:
                return {
                    "action": "hold",
                    "size": 0,
                    "confidence": 0,
                    "reason": "Failed to get Claude estimate",
                }

            # Record analysis time
            self.last_analysis[market_id] = utc_now_naive()

            # Compare Claude estimate vs market price
            market_estimate = current_price
            mispricing = claude_estimate - market_estimate
            mispricing_pct = (mispricing / market_estimate * 100) if market_estimate > 0 else 0

            # Generate signal if mispricing is significant (>5%)
            confidence = min(1.0, abs(mispricing_pct) / 20)

            # Apply sentiment confidence modifier if available
            if sentiment_flag:
                confidence = max(0.0, min(1.0, confidence + sentiment_flag.confidence_modifier))

            if mispricing > 0.05:  # Claude bullish
                action = "buy_yes"
            elif mispricing < -0.05:  # Claude bearish
                action = "buy_no"
            else:
                action = "hold"

            # Calculate size using half-Kelly
            size = 0
            if action != "hold":
                p_est = claude_estimate
                p_market = market_estimate if action == "buy_yes" else (1 - market_estimate)

                if p_market > 0 and p_market < 1 and p_est > 0 and p_est < 1:
                    p_est_adjusted = p_est if action == "buy_yes" else (1 - p_est)
                    kelly_fraction = (p_est_adjusted - p_market) / (1 - p_market) * 0.5
                    size = max(0, kelly_fraction * 100)

            reason = (
                f"Claude est: {claude_estimate:.1%} vs Market: {market_estimate:.1%} "
                f"(mispricing: {mispricing_pct:+.1f}%)"
            )
            if sentiment_flag and sentiment_flag.flag != "normal_coverage":
                reason += f" [{sentiment_flag.flag}]"

            signal = {
                "action": action,
                "size": size,
                "confidence": confidence,
                "estimated_prob": claude_estimate,
                "reason": reason,
            }

            # Attach news metadata for logging / downstream use
            if news_result:
                signal["news_article_count"] = news_result.get("article_count", 0)
                signal["news_sentiment_score"] = news_result.get("sentiment_score", 0.0)
            if sentiment_flag:
                signal["news_flag"] = sentiment_flag.flag

            await self._log_signal(market_id, signal)
            return signal

        except Exception as e:
            await logger.aerror("claude_sentiment_error", market_id=market_id, error=str(e))
            return {
                "action": "hold",
                "size": 0,
                "confidence": 0,
                "reason": f"Error: {str(e)}",
            }

    async def _fetch_news_context(self, question: str) -> tuple:
        """Fetch and score news for a market question.

        Returns:
            Tuple of (news_result dict, SentimentFlag) or (None, None) on failure
        """
        try:
            from src.sentiment_scorer import score_news_data

            news_result = await self._news_client.fetch_news_for_market(question)
            sentiment_flag = score_news_data(news_result)

            await logger.ainfo(
                "news_context_fetched",
                question_short=question[:80],
                article_count=news_result.get("article_count", 0),
                sentiment_score=news_result.get("sentiment_score", 0.0),
                flag=sentiment_flag.flag,
            )
            return news_result, sentiment_flag

        except Exception as e:
            await logger.awarning("news_context_failed", error=str(e))
            return None, None

    async def _get_claude_estimate(
        self,
        question: str,
        current_price: float,
        news_result: Optional[dict] = None,
    ) -> Optional[float]:
        """Get probability estimate from Claude.

        Args:
            question: Market question
            current_price: Current market price
            news_result: Optional news data to include as context

        Returns:
            Probability estimate 0-1, or None if error
        """
        # Build the news context block
        news_context = ""
        if news_result and news_result.get("article_count", 0) > 0:
            from src.sentiment_scorer import format_headlines_for_prompt

            formatted = format_headlines_for_prompt(news_result, max_headlines=5)
            if formatted:
                news_context = f"""

{formatted}

Use these headlines as additional context but form your estimate independently based on first-principles reasoning. The news may be incomplete or biased."""

        prompt = f"""You are a prediction market analyst. Analyze this question and provide a calibrated probability estimate.

Question: {question}

Current market price: {current_price:.1%}{news_context}

Provide your probability estimate (0.0-1.0) for YES, then estimate how many days until this event resolves.

Respond in EXACTLY this format (two lines):
0.65
DAYS: 7"""

        try:
            message = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text.strip()
            lines = response_text.split("\n")
            estimate = float(lines[0].strip())

            # Clamp to valid range
            estimate = max(0.0, min(1.0, estimate))

            # Parse optional DAYS estimate from Claude
            claude_days = None
            for line in lines[1:]:
                line = line.strip().upper()
                if line.startswith("DAYS:"):
                    try:
                        claude_days = float(line.split(":", 1)[1].strip())
                    except (ValueError, IndexError):
                        pass

            await logger.ainfo(
                "claude_estimate_received",
                question_short=question[:100],
                estimate=estimate,
                current_price=current_price,
                news_enriched=bool(news_context),
                claude_days_estimate=claude_days,
            )
            return estimate

        except (ValueError, IndexError, AttributeError) as e:
            await logger.aerror("claude_parse_error", error=str(e))
            return None

    def _should_analyze(self, market_id: str) -> bool:
        """Check if we should analyze this market now (respecting cooldown)."""
        if market_id not in self.last_analysis:
            return True

        time_since_last = utc_now_naive() - self.last_analysis[market_id]
        return time_since_last >= timedelta(minutes=self.cooldown_minutes)

    def _check_env_api_key(self) -> bool:
        """Check if ANTHROPIC_API_KEY is set in environment."""
        import os

        return bool(os.getenv("ANTHROPIC_API_KEY"))
