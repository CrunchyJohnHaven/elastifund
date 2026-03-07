"""Multi-model ensemble for probability estimation.

Implements an abstract estimator interface and an aggregator that combines
multiple model outputs. When models agree (stdev < threshold), the signal
is higher confidence. When they disagree, the system abstains.

Estimators:
- ClaudeEstimator: Anthropic Claude (fully implemented)
- GPTEstimator: OpenAI GPT-4o via openai SDK
- GrokEstimator: xAI Grok-3 via OpenAI-compatible API
- GroqEstimator: Groq free-tier models (Llama 3.3 70B, Llama 3.1 8B)

Aggregation:
- Trimmed mean (drop highest + lowest, average rest) — more robust than mean
- Bridgewater blending: 67% market price / 33% AI forecast
- Consensus gating: require 75%+ models to agree on direction

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
PLATT_A = float(os.environ.get("PLATT_A", "0.55"))
PLATT_B = float(os.environ.get("PLATT_B", "-0.40"))

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
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - platt_calibrate(1.0 - raw_prob)
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
        model: str = "claude-sonnet-4-6",
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
# Groq Estimator (free tier — Llama + Qwen models via OpenAI-compatible API)
# ---------------------------------------------------------------------------

class GroqEstimator(BaseEstimator):
    """Probability estimator using Groq free tier.

    Groq exposes an OpenAI-compatible API at https://api.groq.com/openai/v1.
    Free tier: Llama 3.3 70B = 1,000 req/day, Llama 3.1 8B = 14,400 req/day.
    Requires: GROQ_API_KEY env var (free signup at console.groq.com).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "llama-3.3-70b-versatile",
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1",
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
                    temperature=0.3,  # Low temp for calibrated estimates
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            text = response.choices[0].message.content.strip()
            return _parse_response(text, f"groq:{self.model}")
        except Exception as e:
            logger.error("groq_estimator_error", model=self.model, error=str(e))
            return EstimatorResult(0.5, "low", f"groq:{self.model}", f"API error: {e}")


# ---------------------------------------------------------------------------
# Aggregation Utilities
# ---------------------------------------------------------------------------

def trimmed_mean(values: list[float]) -> float:
    """Drop highest and lowest, average the rest.

    With 4 models: drops 1 highest + 1 lowest, averages remaining 2.
    With 2-3 models: standard mean (no trimming possible).
    With 5+ models: drops top/bottom 20%.
    """
    if not values:
        return 0.5
    n = len(values)
    if n <= 3:
        return statistics.mean(values)
    sorted_vals = sorted(values)
    trim = max(1, n // 5)  # 20% trim
    trimmed = sorted_vals[trim:-trim] if trim > 0 else sorted_vals
    return statistics.mean(trimmed)


def consensus_score(probabilities: list[float], threshold: float = 0.5) -> float:
    """What fraction of models agree on direction (YES vs NO)?

    Returns 0.0-1.0. 1.0 = all models agree. 0.5 = split.
    """
    if not probabilities:
        return 0.0
    above = sum(1 for p in probabilities if p > threshold)
    return max(above, len(probabilities) - above) / len(probabilities)


def bridgewater_blend(ai_forecast: float, market_price: float,
                      ai_weight: float = 0.33) -> float:
    """Blend AI forecast with market price.

    Bridgewater AIA finding: 67% market / 33% AI is optimal.
    Even when AI trails market accuracy, it adds independent information.
    """
    return (1 - ai_weight) * market_price + ai_weight * ai_forecast


# ---------------------------------------------------------------------------
# Ensemble Aggregator
# ---------------------------------------------------------------------------

class EnsembleAggregator:
    """Aggregates probability estimates from multiple models.

    Upgraded pipeline (March 7, 2026):
    - Runs all estimators in parallel (asyncio.gather)
    - Falls back gracefully if any API fails (uses whichever succeed)
    - Trimmed mean aggregation (drops highest + lowest outliers)
    - Consensus gating: require 75%+ models to agree on direction
    - Platt scaling calibration on ensemble average
    - Bridgewater blending: 67% market price / 33% AI forecast
    """

    def __init__(
        self,
        estimators: list[BaseEstimator],
        max_stdev: float = 0.15,
        min_consensus: float = 0.75,
        apply_calibration: bool = True,
        bridgewater_ai_weight: float = 0.33,
    ):
        if not estimators:
            raise ValueError("At least one estimator required")
        self.estimators = estimators
        self.max_stdev = max_stdev
        self.min_consensus = min_consensus
        self.apply_calibration = apply_calibration
        self.bridgewater_ai_weight = bridgewater_ai_weight

    async def estimate(
        self, market_question: str, category: str,
        market_price: Optional[float] = None,
    ) -> dict:
        """Run all estimators in parallel and aggregate results.

        Args:
            market_question: The market question (no price shown to models).
            category: Market category for fee/priority routing.
            market_price: Current YES price. If provided, Bridgewater
                          blending is applied.

        Returns:
            {
                "mean_probability": float (raw trimmed mean),
                "calibrated_probability": float (after Platt scaling),
                "blended_probability": float (after Bridgewater blend, if market_price given),
                "stdev": float,
                "spread": float (max - min model estimate),
                "consensus": float (fraction of models agreeing on direction),
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
                "blended_probability": 0.5,
                "stdev": 1.0,
                "spread": 1.0,
                "consensus": 0.0,
                "models_agree": False,
                "n_models": 0,
                "individual_results": [],
                "signal_valid": False,
            }

        probs = [r.probability for r in results]

        # Trimmed mean (robust to outliers)
        mean_prob = trimmed_mean(probs)

        if len(probs) >= 2:
            stdev = statistics.stdev(probs)
        else:
            stdev = 0.0

        spread = max(probs) - min(probs)
        consensus = consensus_score(probs)
        models_agree = stdev < self.max_stdev and consensus >= self.min_consensus
        signal_valid = models_agree and len(results) > 0

        # Apply Platt calibration to ensemble average
        calibrated = platt_calibrate(mean_prob) if self.apply_calibration else mean_prob

        # Apply Bridgewater blending if market price available
        if market_price is not None and 0 < market_price < 1:
            blended = bridgewater_blend(calibrated, market_price,
                                         self.bridgewater_ai_weight)
        else:
            blended = calibrated

        logger.info(
            "ensemble_estimate",
            n_models=len(results),
            models=[r.model for r in results],
            probs=[round(p, 3) for p in probs],
            trimmed_mean=round(mean_prob, 4),
            calibrated=round(calibrated, 4),
            blended=round(blended, 4),
            stdev=round(stdev, 4),
            spread=round(spread, 4),
            consensus=round(consensus, 3),
            agree=models_agree,
        )

        return {
            "mean_probability": round(mean_prob, 4),
            "calibrated_probability": round(calibrated, 4),
            "blended_probability": round(blended, 4),
            "stdev": round(stdev, 4),
            "spread": round(spread, 4),
            "consensus": round(consensus, 3),
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

    Priority order:
    1. Groq Llama 3.3 70B (free, primary workhorse)
    2. Groq Llama 3.1 8B (free, fast, high daily limit)
    3. Claude Haiku (Anthropic reasoning style)
    4. GPT-4o Mini (OpenAI perspective)
    5. Grok-3 (xAI, if key available)

    Missing keys are silently skipped. At minimum, Claude is expected.
    """
    estimators: list[BaseEstimator] = []

    # Groq free tier (highest priority — $0 cost)
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        estimators.append(GroqEstimator(api_key=groq_key, model="llama-3.3-70b-versatile"))
        logger.info("ensemble_estimator_added", model="groq:llama-3.3-70b")
        estimators.append(GroqEstimator(api_key=groq_key, model="llama-3.1-8b-instant"))
        logger.info("ensemble_estimator_added", model="groq:llama-3.1-8b")

    # Anthropic Claude
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        estimators.append(ClaudeEstimator(api_key=anthropic_key))
        logger.info("ensemble_estimator_added", model="claude")

    # OpenAI GPT-4o Mini (cheap diversity)
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        estimators.append(GPTEstimator(api_key=openai_key, model="gpt-4o-mini"))
        logger.info("ensemble_estimator_added", model="gpt-4o-mini")

    # xAI Grok (if available)
    xai_key = os.getenv("XAI_API_KEY", "")
    if xai_key:
        estimators.append(GrokEstimator(api_key=xai_key))
        logger.info("ensemble_estimator_added", model="grok-3")

    if not estimators:
        logger.warning("no_estimators_available",
                        hint="Set GROQ_API_KEY (free) or ANTHROPIC_API_KEY")

    logger.info("ensemble_built", n_estimators=len(estimators),
                models=[type(e).__name__ for e in estimators])

    return estimators


class LLMEnsemble:
    """Multi-model probability estimator with trimmed-mean aggregation."""

    models = [
        ("claude-sonnet-4-6", "anthropic", 3.00, 15.00),
        ("llama-3.3-70b-versatile", "groq", 0.59, 0.79),
        ("qwen-qwq-32b", "groq", 0.29, 0.59),
        ("gpt-4o-mini", "openai", 0.15, 0.60),
    ]

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds
        self.total_cost_usd = 0.0

    @staticmethod
    def _estimate_cost_usd(prompt: str, completion: str, in_per_m: float, out_per_m: float) -> float:
        # Fast token estimate for budget tracking.
        in_tokens = max(1, len(prompt) // 4)
        out_tokens = max(1, len(completion) // 4)
        return (in_tokens / 1_000_000.0) * in_per_m + (out_tokens / 1_000_000.0) * out_per_m

    @staticmethod
    def _build_prompt(question: str, context: str) -> str:
        return (
            "Estimate the probability this event resolves YES.\n\n"
            f"Question: {question}\n"
            f"Context: {context or 'None provided'}\n\n"
            "1) First give the historical/base rate for similar events.\n"
            "2) List factors for and against YES.\n"
            "3) Give one final probability between 0.01 and 0.99.\n"
            "4) Do not use or assume a market price.\n\n"
            "Format:\n"
            "PROBABILITY: <0.01 to 0.99>\n"
            "CONFIDENCE: <low|medium|high>\n"
            "REASONING: <brief>"
        )

    def _build_estimator_specs(self) -> list[tuple[str, BaseEstimator, float, float]]:
        specs: list[tuple[str, BaseEstimator, float, float]] = []
        keys = {
            "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
            "groq": os.getenv("GROQ_API_KEY", ""),
            "openai": os.getenv("OPENAI_API_KEY", ""),
        }
        groq_free_available = os.getenv("GROQ_FREE_TIER_AVAILABLE", "true").lower() in ("1", "true", "yes")

        for model_name, provider, in_price, out_price in self.models:
            if provider == "anthropic" and keys["anthropic"]:
                specs.append((model_name, ClaudeEstimator(model= model_name, api_key=keys["anthropic"]), in_price, out_price))
            elif provider == "openai" and keys["openai"]:
                specs.append((model_name, GPTEstimator(model=model_name, api_key=keys["openai"]), in_price, out_price))
            elif provider == "groq" and keys["groq"] and groq_free_available:
                specs.append((model_name, GroqEstimator(model=model_name, api_key=keys["groq"]), 0.0, 0.0))
            elif provider == "groq" and keys["groq"]:
                specs.append((model_name, GroqEstimator(model=model_name, api_key=keys["groq"]), in_price, out_price))

        return specs

    async def estimate_probability(self, question: str, context: str, category: str) -> dict:
        prompt = self._build_prompt(question, context)
        specs = self._build_estimator_specs()
        if not specs:
            raise RuntimeError("No ensemble model credentials configured")

        async def _one(model_name: str, est: BaseEstimator, in_price: float, out_price: float):
            try:
                result = await asyncio.wait_for(
                    est.estimate_probability(question, category),
                    timeout=self.timeout_seconds,
                )
                calibrated = platt_calibrate(result.probability)
                cost = self._estimate_cost_usd(prompt, result.reasoning, in_price, out_price)
                return {
                    "model": model_name,
                    "raw_prob": result.probability,
                    "calibrated_prob": calibrated,
                    "reasoning": result.reasoning,
                    "cost": cost,
                }
            except asyncio.TimeoutError:
                logger.warning("ensemble_model_timeout", model=model_name)
                return None
            except Exception as exc:
                logger.warning("ensemble_model_failed", model=model_name, error=str(exc))
                return None

        results = await asyncio.gather(*[_one(name, est, in_price, out_price) for name, est, in_price, out_price in specs])
        valid = [r for r in results if r is not None]
        if len(valid) < 3:
            raise RuntimeError(f"Need at least 3 model responses, got {len(valid)}")

        calibrated_probs = [r["calibrated_prob"] for r in valid]
        ensemble_prob = trimmed_mean(calibrated_probs)
        agreement = consensus_score(calibrated_probs)
        cost_usd = sum(r["cost"] for r in valid)
        self.total_cost_usd += cost_usd

        return {
            "ensemble_prob": round(ensemble_prob, 4),
            "model_probs": {r["model"]: round(r["raw_prob"], 4) for r in valid},
            "calibrated_probs": {r["model"]: round(r["calibrated_prob"], 4) for r in valid},
            "agreement_score": round(agreement, 4),
            "cost_usd": round(cost_usd, 6),
            "reasoning": {r["model"]: r["reasoning"] for r in valid},
            "needs_human_review": agreement < 0.5,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


async def _run_standalone_test() -> int:
    ensemble = LLMEnsemble()
    question = "Will US CPI year-over-year be below 3.0% in the next release?"
    context = "Focus on macro trend, labor market cooling, and energy base effects."
    try:
        result = await ensemble.estimate_probability(question, context, category="economic")
    except Exception as exc:
        print(f"Ensemble test failed: {exc}")
        return 1

    print("LLM Ensemble Test")
    print(f"Question: {question}")
    print(f"Ensemble probability: {result['ensemble_prob']}")
    print(f"Agreement: {result['agreement_score']}")
    print(f"Estimate cost (USD): {result['cost_usd']}")
    print(f"Needs human review: {result['needs_human_review']}")
    print("Model probabilities:")
    for model, prob in result["calibrated_probs"].items():
        print(f"  - {model}: {prob}")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM ensemble utility")
    parser.add_argument("--test", action="store_true", help="Run one ensemble estimate")
    args = parser.parse_args()

    if args.test:
        raise SystemExit(asyncio.run(_run_standalone_test()))
