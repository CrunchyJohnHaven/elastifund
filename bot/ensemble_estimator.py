#!/usr/bin/env python3
"""Multi-model ensemble estimator for the JJ live trading loop."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
import math
import os
from pathlib import Path
import sqlite3
import statistics
import time
from typing import Callable, Optional

from bot.disagreement_signal import build_disagreement_signal
try:
    from bot.apm_setup import capture_external_span, get_apm_runtime
    from bot.latency_tracker import track_latency
except ImportError:  # pragma: no cover - direct script execution fallback
    from apm_setup import capture_external_span, get_apm_runtime  # type: ignore
    from latency_tracker import track_latency  # type: ignore

logger = logging.getLogger("JJ.ensemble")


def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


PLATT_A = _float_env("PLATT_A", "0.5914")
PLATT_B = _float_env("PLATT_B", "-0.3977")
CLAUDE_MODEL_DEFAULT = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20241022")
OPENAI_MODEL_DEFAULT = os.environ.get("JJ_OPENAI_ENSEMBLE_MODEL", "gpt-4o-mini")
OPENAI_INPUT_COST_PER_M = float(os.environ.get("JJ_OPENAI_INPUT_COST_PER_M", "0.15"))
OPENAI_OUTPUT_COST_PER_M = float(os.environ.get("JJ_OPENAI_OUTPUT_COST_PER_M", "0.60"))
ANTHROPIC_INPUT_COST_PER_M = float(os.environ.get("JJ_ANTHROPIC_INPUT_COST_PER_M", "0.0"))
ANTHROPIC_OUTPUT_COST_PER_M = float(os.environ.get("JJ_ANTHROPIC_OUTPUT_COST_PER_M", "0.0"))
DEFAULT_DAILY_COST_CAP_USD = float(os.environ.get("JJ_ENSEMBLE_DAILY_COST_CAP_USD", "2.0"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("JJ_ENSEMBLE_TIMEOUT_SECONDS", "30"))
DEFAULT_ENABLE_SECOND_CLAUDE = os.environ.get(
    "JJ_ENSEMBLE_ENABLE_SECOND_CLAUDE",
    "false",
).lower() in ("1", "true", "yes")

ANTI_ANCHORING_PROMPT = """Estimate the probability that this event resolves YES.

Today's date: {current_date}

Question: {question}
{context_section}{news_section}
Step 1: What is the historical base rate for events like this? (What fraction of similar events in the past resolved YES?)
Step 2: What specific evidence adjusts the probability up or down from the base rate?
Step 3: Give your final estimate.

IMPORTANT CALIBRATION NOTE: You have a documented tendency to overestimate YES probabilities by 20-30%. When you feel 70-80% confident in YES, the true rate is closer to 50-55%. When you feel 90%+ confident in YES, the true rate is closer to 63%. Adjust your estimate downward accordingly.

IMPORTANT DATE NOTE: Use today's date above to ground your reasoning. Do NOT rely on training-data assumptions about future events. If an event's deadline has already passed, account for that. If a product has already launched, that changes the probability.

If recent news headlines are provided above, weight them appropriately - breaking developments may shift probabilities meaningfully, but do not anchor solely on headlines.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""

SECOND_CLAUDE_PROMPT = """Estimate the probability that this event resolves YES.

Today's date: {current_date}

Question: {question}
{context_section}{news_section}
Step 1: State the strongest case for YES in 1-2 sentences.
Step 2: State the strongest case for NO in 1-2 sentences.
Step 3: What is the historical base rate for events like this?
Step 4: Give your final estimate.

IMPORTANT CALIBRATION NOTE: You have a documented tendency to overestimate YES probabilities by 20-30%. When you feel 70-80% confident in YES, the true rate is closer to 50-55%. When you feel 90%+ confident in YES, the true rate is closer to 63%. Adjust your estimate downward accordingly.

IMPORTANT DATE NOTE: Use today's date above to ground your reasoning. Do NOT rely on training-data assumptions about future events. If an event's deadline has already passed, account for that. If a product has already launched, that changes the probability.

If recent news headlines are provided above, weight them appropriately - breaking developments may shift probabilities meaningfully, but do not anchor solely on headlines.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""


def calibrate_probability(raw_prob: float) -> float:
    """Apply the repository's static Platt calibration."""
    raw_prob = max(0.001, min(0.999, float(raw_prob)))
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability(1.0 - raw_prob)
    logit_input = math.log(raw_prob / (1.0 - raw_prob))
    logit_output = max(-30.0, min(30.0, PLATT_A * logit_input + PLATT_B))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def _token_estimate(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _estimate_cost_usd(prompt: str, completion: str, input_cost_per_m: float, output_cost_per_m: float) -> float:
    input_tokens = _token_estimate(prompt)
    output_tokens = _token_estimate(completion)
    return (input_tokens / 1_000_000.0) * input_cost_per_m + (output_tokens / 1_000_000.0) * output_cost_per_m


def _build_context_section(context: str) -> str:
    if not context:
        return ""
    return f"\nRelevant context:\n{context}\n"


def _build_news_section(news_section: str) -> str:
    if not news_section:
        return ""
    return f"\n{news_section}\n"


def _current_date_str() -> str:
    """Return current date in a clear format for the LLM prompt."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_prompt(question: str, context: str = "", news_section: str = "") -> str:
    """Use the exact anti-anchoring structure currently used for Claude."""
    return ANTI_ANCHORING_PROMPT.format(
        question=question,
        current_date=_current_date_str(),
        context_section=_build_context_section(context),
        news_section=_build_news_section(news_section),
    )


def build_second_claude_prompt(question: str, context: str = "", news_section: str = "") -> str:
    """Alternative Claude structure that still preserves anti-anchoring."""
    return SECOND_CLAUDE_PROMPT.format(
        question=question,
        current_date=_current_date_str(),
        context_section=_build_context_section(context),
        news_section=_build_news_section(news_section),
    )


@dataclass
class ModelEstimate:
    """Single-model probability estimate."""

    model_name: str
    provider: str
    raw_probability: float
    confidence: str
    reasoning: str
    latency_ms: float = 0.0
    prompt_variant: str = "base_rate_first"
    estimated_cost_usd: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnsembleEstimate:
    """Aggregate output returned to the live trading loop."""

    question: str
    market_id: str
    category: str
    market_price: float
    mean_estimate: float
    calibrated_mean: float
    median_estimate: float
    range_estimate: float
    std_estimate: float
    confidence: str
    reasoning: str
    confidence_multiplier: float
    disagreement_signal: dict
    call_cost_usd: float
    daily_cost_usd: float
    cost_cap_triggered: bool
    fallback_mode: str
    model_estimates: list[ModelEstimate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["model_estimates"] = [estimate.to_dict() for estimate in self.model_estimates]
        return payload


def parse_llm_response(text: str, *, model_name: str, provider: str, prompt_variant: str) -> ModelEstimate:
    """Parse the shared PROBABILITY/CONFIDENCE/REASONING response format."""
    probability = None
    confidence = "medium"
    reasoning = ""

    for line in text.strip().splitlines():
        normalized = line.strip()
        upper = normalized.upper()

        if upper.startswith("PROBABILITY:"):
            value = normalized.split(":", 1)[1].strip()
            value = value.replace("%", "").split()[0]
            try:
                probability = float(value)
                if probability > 1.0:
                    probability /= 100.0
                probability = max(0.01, min(0.99, probability))
            except (ValueError, IndexError):
                probability = None
        elif upper.startswith("CONFIDENCE:"):
            parsed = normalized.split(":", 1)[1].strip().lower()
            if "high" in parsed:
                confidence = "high"
            elif "low" in parsed:
                confidence = "low"
            else:
                confidence = "medium"
        elif upper.startswith("REASONING:"):
            reasoning = normalized.split(":", 1)[1].strip()

    if probability is None:
        return ModelEstimate(
            model_name=model_name,
            provider=provider,
            raw_probability=0.5,
            confidence="low",
            reasoning="Failed to parse model response",
            prompt_variant=prompt_variant,
            error="parse_failure",
        )

    return ModelEstimate(
        model_name=model_name,
        provider=provider,
        raw_probability=probability,
        confidence=confidence,
        reasoning=reasoning,
        prompt_variant=prompt_variant,
    )


async def call_claude(
    prompt: str,
    *,
    model_name: str = CLAUDE_MODEL_DEFAULT,
    prompt_variant: str = "base_rate_first",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ModelEstimate:
    """Call Claude Haiku through the Anthropic async SDK."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ModelEstimate(model_name, "anthropic", 0.5, "low", "", prompt_variant=prompt_variant, error="no_api_key")

    try:
        import anthropic
    except ImportError:
        return ModelEstimate(model_name, "anthropic", 0.5, "low", "", prompt_variant=prompt_variant, error="sdk_not_installed")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    t0 = time.monotonic()
    try:
        with capture_external_span(
            "anthropic.messages.create",
            system="llm",
            action="anthropic",
            labels={
                "provider": "anthropic",
                "model": model_name,
                "prompt_variant": prompt_variant,
            },
            context={"prompt_tokens": _token_estimate(prompt)},
        ):
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model_name,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout,
            )
        text = response.content[0].text if response.content else ""
        estimate = parse_llm_response(text, model_name=model_name, provider="anthropic", prompt_variant=prompt_variant)
        estimate.latency_ms = (time.monotonic() - t0) * 1000.0
        estimate.estimated_cost_usd = _estimate_cost_usd(
            prompt,
            text,
            ANTHROPIC_INPUT_COST_PER_M,
            ANTHROPIC_OUTPUT_COST_PER_M,
        )
        get_apm_runtime().record_metric(
            "llm_response_ms",
            estimate.latency_ms,
            labels={"provider": "anthropic", "model": model_name},
        )
        return estimate
    except asyncio.TimeoutError:
        return ModelEstimate(
            model_name,
            "anthropic",
            0.5,
            "low",
            "",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            prompt_variant=prompt_variant,
            error="timeout",
        )
    except Exception as exc:
        return ModelEstimate(
            model_name,
            "anthropic",
            0.5,
            "low",
            "",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            prompt_variant=prompt_variant,
            error=str(exc),
        )


async def call_openai(
    prompt: str,
    *,
    model_name: str = OPENAI_MODEL_DEFAULT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ModelEstimate:
    """Call GPT-4o-mini using the OpenAI async SDK."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ModelEstimate(model_name, "openai", 0.5, "low", "", error="no_api_key")

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return ModelEstimate(model_name, "openai", 0.5, "low", "", error="sdk_not_installed")

    client = AsyncOpenAI(api_key=api_key)
    t0 = time.monotonic()
    try:
        with capture_external_span(
            "openai.chat.completions.create",
            system="llm",
            action="openai",
            labels={"provider": "openai", "model": model_name},
            context={"prompt_tokens": _token_estimate(prompt)},
        ):
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a calibrated probability estimator. Use the exact response format requested.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=300,
                    temperature=0.2,
                ),
                timeout=timeout,
            )
        text = response.choices[0].message.content or ""
        estimate = parse_llm_response(text, model_name=model_name, provider="openai", prompt_variant="base_rate_first")
        estimate.latency_ms = (time.monotonic() - t0) * 1000.0
        estimate.estimated_cost_usd = _estimate_cost_usd(
            prompt,
            text,
            OPENAI_INPUT_COST_PER_M,
            OPENAI_OUTPUT_COST_PER_M,
        )
        get_apm_runtime().record_metric(
            "llm_response_ms",
            estimate.latency_ms,
            labels={"provider": "openai", "model": model_name},
        )
        return estimate
    except asyncio.TimeoutError:
        return ModelEstimate(
            model_name,
            "openai",
            0.5,
            "low",
            "",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            error="timeout",
        )
    except Exception as exc:
        return ModelEstimate(
            model_name,
            "openai",
            0.5,
            "low",
            "",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            error=str(exc),
        )


class LLMCostTracker:
    """SQLite-backed tracker for per-call cost telemetry and daily caps."""

    def __init__(self, db_path: str | Path = "data/llm_costs.db", daily_cap_usd: float = DEFAULT_DAILY_COST_CAP_USD):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.daily_cap_usd = float(daily_cap_usd)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with capture_external_span(
            "sqlite.llm_cost_events.init",
            system="sqlite",
            action="write",
            labels={"db.path": str(self.db_path)},
        ):
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS llm_cost_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        day TEXT NOT NULL,
                        market_id TEXT,
                        question TEXT,
                        provider TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        prompt_variant TEXT,
                        cost_usd REAL NOT NULL,
                        fallback_mode TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_cost_day ON llm_cost_events(day)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_cost_market ON llm_cost_events(market_id)")

    @staticmethod
    def _local_day(timestamp: Optional[datetime] = None) -> str:
        if timestamp is None:
            timestamp = datetime.now().astimezone()
        return timestamp.date().isoformat()

    def record_usage(
        self,
        estimates: list[ModelEstimate],
        *,
        market_id: str,
        question: str,
        fallback_mode: str,
        event_time: Optional[datetime] = None,
    ) -> None:
        if not estimates:
            return
        timestamp = (event_time or datetime.now().astimezone()).isoformat()
        day = self._local_day(event_time)
        with capture_external_span(
            "sqlite.llm_cost_events.insert",
            system="sqlite",
            action="write",
            labels={"db.path": str(self.db_path)},
        ):
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO llm_cost_events (
                        timestamp,
                        day,
                        market_id,
                        question,
                        provider,
                        model_name,
                        prompt_variant,
                        cost_usd,
                        fallback_mode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            timestamp,
                            day,
                            market_id,
                            question[:500],
                            estimate.provider,
                            estimate.model_name,
                            estimate.prompt_variant,
                            float(estimate.estimated_cost_usd),
                            fallback_mode,
                        )
                        for estimate in estimates
                    ],
                )

    def daily_spend(self, day: Optional[str] = None) -> float:
        target_day = day or self._local_day()
        with capture_external_span(
            "sqlite.llm_cost_events.daily_spend",
            system="sqlite",
            action="read",
            labels={"db.path": str(self.db_path)},
        ):
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0.0) AS total_cost FROM llm_cost_events WHERE day = ?",
                    (target_day,),
                ).fetchone()
        return float(row["total_cost"]) if row is not None else 0.0

    def cost_cap_reached(self, day: Optional[str] = None) -> bool:
        return self.daily_spend(day) >= self.daily_cap_usd


class EnsembleEstimator:
    """Claude Haiku + GPT-4o-mini ensemble with disagreement telemetry."""

    def __init__(
        self,
        *,
        calibrate_fn: Optional[Callable[[float], float]] = None,
        min_edge: float = 0.05,
        daily_cost_cap_usd: float = DEFAULT_DAILY_COST_CAP_USD,
        cost_tracker: Optional[LLMCostTracker] = None,
        enable_second_claude: bool = DEFAULT_ENABLE_SECOND_CLAUDE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.calibrate_fn = calibrate_fn or calibrate_probability
        self.min_edge = float(min_edge)
        self.timeout_seconds = float(timeout_seconds)
        self.enable_second_claude = bool(enable_second_claude)
        self.cost_tracker = cost_tracker or LLMCostTracker(daily_cap_usd=daily_cost_cap_usd)
        self.daily_cost_cap_usd = self.cost_tracker.daily_cap_usd
        self.models = self._configured_model_names()
        self._warned_openai_missing = False
        self._warned_cost_cap = False

        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
            logger.warning("Ensemble estimator has no model credentials configured.")
        elif not os.environ.get("OPENAI_API_KEY"):
            logger.warning("OPENAI_API_KEY missing; ensemble will run in Haiku-only mode.")
            self._warned_openai_missing = True

    def _configured_model_names(self) -> list[str]:
        models: list[str] = []
        has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
        has_openai = bool(os.environ.get("OPENAI_API_KEY"))
        if has_claude:
            models.append("claude-haiku")
            if self.enable_second_claude and has_openai:
                models.append("claude-haiku-counterfactual")
        if has_openai:
            models.append(OPENAI_MODEL_DEFAULT)
        return models

    def _select_call_specs(self, question: str, context: str, news_section: str) -> tuple[list[asyncio.Future], str, bool]:
        fallback_mode = "ensemble"
        cost_cap_triggered = False
        has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
        has_openai = bool(os.environ.get("OPENAI_API_KEY"))
        cap_reached = self.cost_tracker.cost_cap_reached()

        if cap_reached and has_claude:
            fallback_mode = "haiku_only_cost_cap"
            cost_cap_triggered = True
            if not self._warned_cost_cap:
                logger.warning(
                    "Daily ensemble cost cap reached ($%.2f); falling back to Haiku-only.",
                    self.daily_cost_cap_usd,
                )
                self._warned_cost_cap = True
        elif not has_openai and has_claude:
            fallback_mode = "haiku_only_no_openai_key"
            if not self._warned_openai_missing:
                logger.warning("OPENAI_API_KEY missing; ensemble will run in Haiku-only mode.")
                self._warned_openai_missing = True
        elif has_openai and not has_claude:
            fallback_mode = "openai_only_no_claude_key"

        tasks = []
        if has_claude:
            tasks.append(
                call_claude(
                    build_prompt(question, context=context, news_section=news_section),
                    model_name=CLAUDE_MODEL_DEFAULT,
                    prompt_variant="base_rate_first",
                    timeout=self.timeout_seconds,
                )
            )
        if fallback_mode == "ensemble" and has_openai:
            tasks.append(
                call_openai(
                    build_prompt(question, context=context, news_section=news_section),
                    model_name=OPENAI_MODEL_DEFAULT,
                    timeout=self.timeout_seconds,
                )
            )
            if has_claude and self.enable_second_claude:
                tasks.append(
                    call_claude(
                        build_second_claude_prompt(question, context=context, news_section=news_section),
                        model_name=CLAUDE_MODEL_DEFAULT,
                        prompt_variant="counterfactual",
                        timeout=self.timeout_seconds,
                    )
                )
        elif not has_claude and has_openai:
            tasks.append(
                call_openai(
                    build_prompt(question, context=context, news_section=news_section),
                    model_name=OPENAI_MODEL_DEFAULT,
                    timeout=self.timeout_seconds,
                )
            )

        return tasks, fallback_mode, cost_cap_triggered

    async def estimate(
        self,
        question: str,
        *,
        market_price: float,
        category: str = "",
        market_id: str = "",
        context: str = "",
        news_section: str = "",
    ) -> EnsembleEstimate:
        """Estimate a market using the configured ensemble."""
        tasks, fallback_mode, cost_cap_triggered = self._select_call_specs(question, context, news_section)
        if not tasks:
            return EnsembleEstimate(
                question=question,
                market_id=market_id,
                category=category,
                market_price=float(market_price),
                mean_estimate=0.5,
                calibrated_mean=0.5,
                median_estimate=0.5,
                range_estimate=0.0,
                std_estimate=0.0,
                confidence="low",
                reasoning="No ensemble models available",
                confidence_multiplier=1.0,
                disagreement_signal=build_disagreement_signal({}, calibrated_mean=0.5, market_price=market_price, min_edge=self.min_edge).to_dict(),
                call_cost_usd=0.0,
                daily_cost_usd=self.cost_tracker.daily_spend(),
                cost_cap_triggered=cost_cap_triggered,
                fallback_mode="no_models",
                errors=["no_models"],
            )

        estimates = await asyncio.gather(*tasks)
        good_estimates = [estimate for estimate in estimates if not estimate.error]
        errors = [f"{estimate.model_name}: {estimate.error}" for estimate in estimates if estimate.error]

        if not good_estimates:
            return EnsembleEstimate(
                question=question,
                market_id=market_id,
                category=category,
                market_price=float(market_price),
                mean_estimate=0.5,
                calibrated_mean=0.5,
                median_estimate=0.5,
                range_estimate=0.0,
                std_estimate=0.0,
                confidence="low",
                reasoning="All ensemble model calls failed",
                confidence_multiplier=1.0,
                disagreement_signal=build_disagreement_signal({}, calibrated_mean=0.5, market_price=market_price, min_edge=self.min_edge).to_dict(),
                call_cost_usd=0.0,
                daily_cost_usd=self.cost_tracker.daily_spend(),
                cost_cap_triggered=cost_cap_triggered,
                fallback_mode=fallback_mode,
                model_estimates=estimates,
                errors=errors or ["all_models_failed"],
            )

        individual_estimates = {
            estimate.model_name: float(estimate.raw_probability)
            for estimate in good_estimates
        }
        probabilities = list(individual_estimates.values())
        mean_estimate = sum(probabilities) / len(probabilities)
        median_estimate = statistics.median(probabilities)
        range_estimate = max(probabilities) - min(probabilities) if len(probabilities) >= 2 else 0.0
        std_estimate = statistics.pstdev(probabilities) if len(probabilities) >= 2 else 0.0
        calibrated_mean = float(self.calibrate_fn(mean_estimate))

        disagreement = build_disagreement_signal(
            individual_estimates,
            calibrated_mean=calibrated_mean,
            market_price=market_price,
            min_edge=self.min_edge,
        )

        if disagreement.confirmation_signal:
            confidence = "high"
        elif len(good_estimates) >= 2 and std_estimate <= 0.15:
            confidence = "medium"
        elif len(good_estimates) == 1:
            confidence = good_estimates[0].confidence or "medium"
        else:
            confidence = "low"

        reasoning = " | ".join(
            f"[{estimate.model_name}] {estimate.reasoning}"
            for estimate in good_estimates
            if estimate.reasoning
        )
        if not reasoning:
            reasoning = "Ensemble estimate generated from model outputs."

        self.cost_tracker.record_usage(
            good_estimates,
            market_id=market_id,
            question=question,
            fallback_mode=fallback_mode,
        )
        daily_cost_usd = self.cost_tracker.daily_spend()
        call_cost_usd = sum(float(estimate.estimated_cost_usd) for estimate in good_estimates)

        logger.info(
            "Ensemble estimates | market=%s | price=%.3f | mean=%.3f | cal=%.3f | std=%.3f | range=%.3f | cost=$%.4f | daily=$%.4f | mode=%s | models=%s",
            market_id or question[:40],
            float(market_price),
            mean_estimate,
            calibrated_mean,
            std_estimate,
            range_estimate,
            call_cost_usd,
            daily_cost_usd,
            fallback_mode,
            ", ".join(f"{name}={prob:.3f}" for name, prob in individual_estimates.items()),
        )

        return EnsembleEstimate(
            question=question,
            market_id=market_id,
            category=category,
            market_price=float(market_price),
            mean_estimate=mean_estimate,
            calibrated_mean=calibrated_mean,
            median_estimate=median_estimate,
            range_estimate=range_estimate,
            std_estimate=std_estimate,
            confidence=confidence,
            reasoning=reasoning,
            confidence_multiplier=disagreement.confidence_multiplier,
            disagreement_signal=disagreement.to_dict(),
            call_cost_usd=call_cost_usd,
            daily_cost_usd=daily_cost_usd,
            cost_cap_triggered=cost_cap_triggered,
            fallback_mode=fallback_mode,
            model_estimates=good_estimates,
            errors=errors,
        )

    @track_latency("estimate_probability")
    async def estimate_probability(
        self,
        question: str,
        context: str = "",
        category: str = "",
        *,
        market_price: float = 0.5,
        market_id: str = "",
        news_section: str = "",
    ) -> EnsembleEstimate:
        return await self.estimate(
            question,
            market_price=market_price,
            category=category,
            market_id=market_id,
            context=context,
            news_section=news_section,
        )

    async def analyze_market(
        self,
        question: str,
        current_price: float,
        context: str = "",
        news_section: str = "",
        market_id: str = "",
        category: str = "",
    ) -> dict:
        """Compatibility wrapper for the live trading loop."""
        result = await self.estimate_probability(
            question,
            context=context,
            category=category,
            market_price=current_price,
            market_id=market_id,
            news_section=news_section,
        )
        return {
            "probability": result.mean_estimate,
            "calibrated_probability": result.calibrated_mean,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "n_models": len(result.model_estimates),
            "mean_estimate": result.mean_estimate,
            "median_estimate": result.median_estimate,
            "range_estimate": result.range_estimate,
            "std_estimate": result.std_estimate,
            "model_spread": result.range_estimate,
            "model_stddev": result.std_estimate,
            "disagreement": result.std_estimate,
            "disagreement_signal": result.disagreement_signal.get("signal_fired", False),
            "confirmation_signal": result.disagreement_signal.get("confirmation_signal", False),
            "uncertainty_reduction": result.disagreement_signal.get("uncertainty_reduction", False),
            "confidence_multiplier": result.confidence_multiplier,
            "kelly_multiplier": result.confidence_multiplier,
            "individual_model_estimates": {
                estimate.model_name: estimate.raw_probability for estimate in result.model_estimates
            },
            "model_estimates": [estimate.to_dict() for estimate in result.model_estimates],
            "ensemble_call_cost_usd": result.call_cost_usd,
            "ensemble_daily_cost_usd": result.daily_cost_usd,
            "cost_cap_triggered": result.cost_cap_triggered,
            "fallback_mode": result.fallback_mode,
            "errors": result.errors,
        }

    async def batch_analyze(self, markets: list[dict], delay_between: float = 1.0) -> list[dict]:
        """Sequential batch wrapper to keep rate limiting explicit."""
        results = []
        for index, market in enumerate(markets):
            result = await self.analyze_market(
                question=market["question"],
                current_price=float(market["current_price"]),
                context=market.get("context", ""),
                news_section=market.get("news_section", ""),
                market_id=market.get("market_id", ""),
                category=market.get("category", ""),
            )
            result["market_id"] = market.get("market_id", f"market_{index}")
            result["question"] = market["question"]
            results.append(result)
            if index < len(markets) - 1 and delay_between > 0:
                await asyncio.sleep(delay_between)
        return results
