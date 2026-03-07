"""Multi-model ensemble for probability estimation.

Implements an abstract estimator interface and an aggregator that combines
multiple model outputs. When models agree (stdev < threshold), the signal
is higher confidence. When they disagree, the system abstains.

Estimators:
- ClaudeEstimator: Anthropic Claude (fully implemented)
- GPTEstimator: OpenAI GPT-4o via openai SDK
- GrokEstimator: xAI Grok-3 via OpenAI-compatible API

Usage:
    estimators = build_available_estimators()
    aggregator = EnsembleAggregator(estimators)
    result = await aggregator.estimate("Will X happen?", "politics")
"""
from __future__ import annotations

import asyncio
import math
import os
import statistics
from abc import ABC, abstractmethod
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# CalibrationV2 Platt scaling parameters (same as claude_analyzer.py)
PLATT_A = 0.5914
PLATT_B = -0.3977

# Anti-anchoring prompt — identical structure across all models.
# Market price NOT shown. Base-rate-first. Explicit debiasing.
ENSEMBLE_PROMPT = """Estimate the probability that this event resolves YES.

Question: {question}

Step 1: What is the historical base rate for events like this? (What fraction of similar events in the past resolved YES?)
Step 2: What specific evidence adjusts the probability up or down from the base rate?
Step 3: Give your final estimate.

IMPORTANT CALIBRATION NOTE: LLMs have a documented tendency to overestimate YES probabilities by 20-30%. When you feel 70-80% confident in YES, the true rate is closer to 50-55%. When you feel 90%+ confident in YES, the true rate is closer to 63%. Adjust your estimate downward accordingly.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""


def platt_calibrate(raw_prob: float) -> float:
    """Apply Platt scaling calibration to a raw probability estimate."""
    raw_prob = max(0.001, min(0.999, raw_prob))
    logit_input = math.log(raw_prob / (1 - raw_prob))
    logit_output = PLATT_A * logit_input + PLATT_B
    logit_output = max(-30, min(30, logit_output))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def _parse_response(text: str, model_name: str) -> "EstimatorResult":
    """Parse a PROBABILITY/CONFIDENCE/REASONING response from any model."""
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
        model=model_name,
        reasoning=reasoning,
    )


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
        ...


# ---------------------------------------------------------------------------
# Claude Estimator
# ---------------------------------------------------------------------------

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
        prompt = ENSEMBLE_PROMPT.format(question=market_question)
        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            return _parse_response(text, f"claude:{self.model}")
        except Exception as e:
            logger.error("claude_estimator_error", error=str(e))
            return EstimatorResult(0.5, "low", f"claude:{self.model}", f"API error: {e}")


# ---------------------------------------------------------------------------
# GPT Estimator (OpenAI API)
# ---------------------------------------------------------------------------

class GPTEstimator(BaseEstimator):
    """Probability estimator using OpenAI GPT-4o.

    Uses the same anti-anchoring, base-rate-first prompt as ClaudeEstimator.
    Requires: pip install openai, OPENAI_API_KEY env var.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    async def estimate_probability(
        self, market_question: str, category: str
    ) -> EstimatorResult:
        prompt = ENSEMBLE_PROMPT.format(question=market_question)
        try:
            client = self._get_client()
            # Run sync OpenAI call in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=self.model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            text = response.choices[0].message.content.strip()
            return _parse_response(text, f"gpt:{self.model}")
        except Exception as e:
            logger.error("gpt_estimator_error", error=str(e))
            return EstimatorResult(0.5, "low", f"gpt:{self.model}", f"API error: {e}")


# ---------------------------------------------------------------------------
# Grok Estimator (xAI API — OpenAI-compatible)
# ---------------------------------------------------------------------------

class GrokEstimator(BaseEstimator):
    """Probability estimator using xAI Grok-3.

    xAI exposes an OpenAI-compatible API at https://api.x.ai/v1.
    Uses the same anti-anchoring, base-rate-first prompt as other estimators.
    Requires: pip install openai, XAI_API_KEY env var.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "grok-3"):
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.x.ai/v1",
            )
        return self._client

    async def estimate_probability(
        self, market_question: str, category: str
    ) -> EstimatorResult:
        prompt = ENSEMBLE_PROMPT.format(question=market_question)
        try:
            client = self._get_client()
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=self.model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            text = response.choices[0].message.content.strip()
            return _parse_response(text, f"grok:{self.model}")
        except Exception as e:
            logger.error("grok_estimator_error", error=str(e))
            return EstimatorResult(0.5, "low", f"grok:{self.model}", f"API error: {e}")


# ---------------------------------------------------------------------------
# Ensemble Aggregator
# ---------------------------------------------------------------------------

class EnsembleAggregator:
    """Aggregates probability estimates from multiple models.

    Rules:
    - Runs all estimators in parallel (asyncio.gather)
    - Falls back gracefully if any API fails (uses whichever succeed)
    - Mean probability across all successful estimators
    - Signal only when stdev < max_stdev (models agree)
    - Applies CalibrationV2 Platt scaling to the ensemble average
    """

    def __init__(
        self,
        estimators: list[BaseEstimator],
        max_stdev: float = 0.15,
        apply_calibration: bool = True,
    ):
        if not estimators:
            raise ValueError("At least one estimator required")
        self.estimators = estimators
        self.max_stdev = max_stdev
        self.apply_calibration = apply_calibration

    async def estimate(
        self, market_question: str, category: str
    ) -> dict:
        """Run all estimators in parallel and aggregate results.

        Returns:
            {
                "mean_probability": float (raw ensemble mean),
                "calibrated_probability": float (after Platt scaling),
                "stdev": float,
                "models_agree": bool,
                "n_models": int,
                "individual_results": list[dict],
                "signal_valid": bool,
            }
        """
        # Run all estimators in parallel with graceful failure
        tasks = [
            self._safe_estimate(est, market_question, category)
            for est in self.estimators
        ]
        raw_results = await asyncio.gather(*tasks)

        # Filter out failures (None)
        results: list[EstimatorResult] = [r for r in raw_results if r is not None]

        if not results:
            return {
                "mean_probability": 0.5,
                "calibrated_probability": 0.5,
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
            stdev = 0.0

        models_agree = stdev < self.max_stdev
        signal_valid = models_agree and len(results) > 0

        # Apply Platt calibration to ensemble average
        calibrated = platt_calibrate(mean_prob) if self.apply_calibration else mean_prob

        logger.info(
            "ensemble_estimate",
            n_models=len(results),
            models=[r.model for r in results],
            probs=[round(p, 3) for p in probs],
            mean=round(mean_prob, 4),
            calibrated=round(calibrated, 4),
            stdev=round(stdev, 4),
            agree=models_agree,
        )

        return {
            "mean_probability": round(mean_prob, 4),
            "calibrated_probability": round(calibrated, 4),
            "stdev": round(stdev, 4),
            "models_agree": models_agree,
            "n_models": len(results),
            "individual_results": [r.to_dict() for r in results],
            "signal_valid": signal_valid,
        }

    @staticmethod
    async def _safe_estimate(
        estimator: BaseEstimator, question: str, category: str
    ) -> Optional[EstimatorResult]:
        """Run a single estimator with error handling."""
        try:
            return await estimator.estimate_probability(question, category)
        except Exception as e:
            logger.error(
                "estimator_failed",
                estimator=type(estimator).__name__,
                error=str(e),
            )
            return None


# ---------------------------------------------------------------------------
# Factory: build estimators from available API keys
# ---------------------------------------------------------------------------

def build_available_estimators() -> list[BaseEstimator]:
    """Build list of estimators based on which API keys are available.

    Always includes Claude (required). GPT and Grok are added if their
    respective API keys are set. Missing keys are silently skipped.
    """
    estimators: list[BaseEstimator] = []

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        estimators.append(ClaudeEstimator(api_key=anthropic_key))
        logger.info("ensemble_estimator_added", model="claude")

    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        estimators.append(GPTEstimator(api_key=openai_key))
        logger.info("ensemble_estimator_added", model="gpt-4o")

    xai_key = os.getenv("XAI_API_KEY", "")
    if xai_key:
        estimators.append(GrokEstimator(api_key=xai_key))
        logger.info("ensemble_estimator_added", model="grok-3")

    if not estimators:
        logger.warning("no_estimators_available", hint="Set ANTHROPIC_API_KEY")

    return estimators
