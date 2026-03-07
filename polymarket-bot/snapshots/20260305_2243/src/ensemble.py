"""Multi-model ensemble for probability estimation.

Implements an abstract estimator interface and an aggregator that combines
multiple model outputs. When models agree (stdev < threshold), the signal
is higher confidence. When they disagree, the system abstains.

Current estimators:
- ClaudeEstimator: Uses existing claude_analyzer.py logic (fully implemented)
- GPTEstimator: Placeholder for OpenAI GPT integration
- GrokEstimator: Placeholder for xAI Grok integration

Usage:
    estimators = [ClaudeEstimator(api_key="...")]
    aggregator = EnsembleAggregator(estimators)
    result = await aggregator.estimate("Will X happen?", "politics")
"""
from __future__ import annotations

import os
import statistics
from abc import ABC, abstractmethod
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class EstimatorResult:
    """Result from a single model estimator."""

    __slots__ = ("probability", "confidence", "model", "reasoning")

    def __init__(self, probability: float, confidence: str, model: str, reasoning: str):
        self.probability = max(0.01, min(0.99, probability))
        self.confidence = confidence
        self.model = model
        self.reasoning = reasoning

    def to_dict(self) -> dict:
        return {
            "probability": self.probability,
            "confidence": self.confidence,
            "model": self.model,
            "reasoning": self.reasoning,
        }


class BaseEstimator(ABC):
    """Abstract interface for probability estimators."""

    @abstractmethod
    async def estimate_probability(
        self, market_question: str, category: str
    ) -> EstimatorResult:
        """Estimate the probability that a market resolves YES.

        Args:
            market_question: The full market question text.
            category: Market category (politics, weather, crypto, etc.)

        Returns:
            EstimatorResult with probability, confidence, model name, and reasoning.
        """
        ...


# ---------------------------------------------------------------------------
# Claude Estimator (fully implemented)
# ---------------------------------------------------------------------------

CLAUDE_PROMPT = """Estimate the probability that this event resolves YES.

Question: {question}

Step 1: What is the historical base rate for events like this?
Step 2: What specific evidence adjusts the probability up or down from the base rate?
Step 3: Give your final estimate.

IMPORTANT CALIBRATION NOTE: You have a documented tendency to overestimate YES probabilities by 20-30%. Adjust your estimate downward accordingly.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""


class ClaudeEstimator(BaseEstimator):
    """Probability estimator using Anthropic Claude."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    async def estimate_probability(
        self, market_question: str, category: str
    ) -> EstimatorResult:
        prompt = CLAUDE_PROMPT.format(question=market_question)

        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            return self._parse(text)
        except Exception as e:
            logger.error("claude_estimator_error", error=str(e))
            return EstimatorResult(
                probability=0.5,
                confidence="low",
                model=f"claude:{self.model}",
                reasoning=f"API error: {e}",
            )

    def _parse(self, text: str) -> EstimatorResult:
        prob = 0.5
        confidence = "medium"
        reasoning = text

        for line in text.split("\n"):
            line = line.strip()
            if line.upper().startswith("PROBABILITY:"):
                try:
                    prob = float(line.split(":", 1)[1].strip())
                    prob = max(0.01, min(0.99, prob))
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("CONFIDENCE:"):
                confidence = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        return EstimatorResult(
            probability=prob,
            confidence=confidence,
            model=f"claude:{self.model}",
            reasoning=reasoning,
        )


# ---------------------------------------------------------------------------
# GPT Estimator (placeholder)
# ---------------------------------------------------------------------------

class GPTEstimator(BaseEstimator):
    """Placeholder for OpenAI GPT probability estimator.

    To implement:
    1. pip install openai
    2. Set OPENAI_API_KEY env var
    3. Replace estimate_probability with real API call
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model

    async def estimate_probability(
        self, market_question: str, category: str
    ) -> EstimatorResult:
        # TODO: Implement real OpenAI API call
        logger.warning("gpt_estimator_placeholder", question=market_question[:60])
        return EstimatorResult(
            probability=0.5,
            confidence="low",
            model=f"gpt:{self.model}",
            reasoning="Placeholder — GPT integration not yet implemented",
        )


# ---------------------------------------------------------------------------
# Grok Estimator (placeholder)
# ---------------------------------------------------------------------------

class GrokEstimator(BaseEstimator):
    """Placeholder for xAI Grok probability estimator.

    To implement:
    1. pip install xai-sdk (or use REST API)
    2. Set XAI_API_KEY env var
    3. Replace estimate_probability with real API call
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "grok-2"):
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.model = model

    async def estimate_probability(
        self, market_question: str, category: str
    ) -> EstimatorResult:
        # TODO: Implement real Grok API call
        logger.warning("grok_estimator_placeholder", question=market_question[:60])
        return EstimatorResult(
            probability=0.5,
            confidence="low",
            model=f"grok:{self.model}",
            reasoning="Placeholder — Grok integration not yet implemented",
        )


# ---------------------------------------------------------------------------
# Ensemble Aggregator
# ---------------------------------------------------------------------------

class EnsembleAggregator:
    """Aggregates probability estimates from multiple models.

    Rules:
    - Mean probability across all estimators
    - Standard deviation measures disagreement
    - Signal only when stdev < max_stdev (models agree)
    - Single-model mode: passes through directly (identical to non-ensemble)
    """

    def __init__(
        self,
        estimators: list[BaseEstimator],
        max_stdev: float = 0.15,
    ):
        if not estimators:
            raise ValueError("At least one estimator required")
        self.estimators = estimators
        self.max_stdev = max_stdev

    async def estimate(
        self, market_question: str, category: str
    ) -> dict:
        """Run all estimators and aggregate results.

        Returns:
            {
                "mean_probability": float,
                "stdev": float,
                "models_agree": bool,
                "n_models": int,
                "individual_results": list[dict],
                "signal_valid": bool,
            }
        """
        results: list[EstimatorResult] = []
        for estimator in self.estimators:
            try:
                result = await estimator.estimate_probability(market_question, category)
                results.append(result)
            except Exception as e:
                logger.error("estimator_failed", estimator=type(estimator).__name__, error=str(e))

        if not results:
            return {
                "mean_probability": 0.5,
                "stdev": 1.0,
                "models_agree": False,
                "n_models": 0,
                "individual_results": [],
                "signal_valid": False,
            }

        probs = [r.probability for r in results]
        mean_prob = statistics.mean(probs)

        if len(probs) >= 2:
            stdev = statistics.stdev(probs)
        else:
            # Single model: stdev = 0 (no disagreement possible)
            stdev = 0.0

        models_agree = stdev < self.max_stdev
        signal_valid = models_agree and len(results) > 0

        return {
            "mean_probability": round(mean_prob, 4),
            "stdev": round(stdev, 4),
            "models_agree": models_agree,
            "n_models": len(results),
            "individual_results": [r.to_dict() for r in results],
            "signal_valid": signal_valid,
        }
