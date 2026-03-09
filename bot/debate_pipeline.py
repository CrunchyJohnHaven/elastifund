#!/usr/bin/env python3
"""
Multi-Agent Debate Pipeline — Adversarial Probability Estimation
================================================================
Dispatch #75 — Strategy D-1: Multi-Agent Cross-Examination

Architecture:
  1. GPT-5.1 generates BASE THESIS (strong generalist reasoning)
  2. Claude 4.5 generates COUNTER-THESIS (strong logic, adversarial refutation)
  3. Gemini 3 Pro JUDGES both arguments and outputs final probability
  4. (Optional) Conformal prediction wrapper adds uncertainty interval

This replaces simple ensemble median with structured adversarial debate.
Academic basis: Multi-agent debate reduces acquiescence bias and tightens
calibration (P(Works): 80% per dispatch assessment).

Kill Criterion: Brier score improvement over baseline < 0.015.

Env vars:
    OPENAI_API_KEY       — GPT-5.1 (thesis generator)
    ANTHROPIC_API_KEY    — Claude 4.5 (adversarial refuter)
    GOOGLE_API_KEY       — Gemini 3 Pro (judge/synthesizer)

Author: JJ (autonomous)
Date: 2026-03-07
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _current_date_str() -> str:
    """Return current date for temporal grounding in LLM prompts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


try:
    from bot.apm_setup import capture_external_span, get_apm_runtime
    from bot.latency_tracker import track_latency
except ImportError:  # pragma: no cover - direct script execution fallback
    from apm_setup import capture_external_span, get_apm_runtime  # type: ignore
    from latency_tracker import track_latency  # type: ignore

logger = logging.getLogger("JJ.debate")

# Model identifiers — update these as new models release
GPT_THESIS_MODEL = os.environ.get("DEBATE_GPT_MODEL", "gpt-5.1")
CLAUDE_REFUTER_MODEL = os.environ.get("DEBATE_CLAUDE_MODEL", "claude-sonnet-4-5-20250514")
GEMINI_JUDGE_MODEL = os.environ.get("DEBATE_GEMINI_MODEL", "gemini-3-pro")


@dataclass
class DebateResult:
    """Output of the multi-agent debate pipeline."""
    probability: float                # Final point estimate (0-1)
    confidence: float                 # Judge's confidence in synthesis (0-1)
    thesis_probability: float         # GPT-5.1's raw estimate
    counter_probability: float        # Claude 4.5's raw estimate
    judge_probability: float          # Gemini's synthesized estimate
    thesis_reasoning: str = ""        # GPT's argument
    counter_reasoning: str = ""       # Claude's refutation
    judge_reasoning: str = ""         # Gemini's synthesis
    model_spread: float = 0.0        # Spread between thesis/counter
    debate_quality: str = "unknown"   # "high", "medium", "low"
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    error: str = ""


THESIS_PROMPT = """You are a senior quantitative analyst. Your task is to estimate the probability of the following event occurring.

Today's date: {current_date}

QUESTION: {question}

CATEGORY: {category}

ADDITIONAL CONTEXT:
{context}

INSTRUCTIONS:
1. Reason step-by-step about the key factors that influence this outcome
2. Consider base rates, historical precedents, and current conditions
3. Weigh evidence for AND against the event occurring
4. Provide your final probability estimate as a decimal between 0.01 and 0.99

Format your response as:
REASONING: [Your detailed analysis]
PROBABILITY: [Your estimate, e.g., 0.65]
KEY_FACTORS: [Top 3 factors driving your estimate]"""

COUNTER_PROMPT = """You are a contrarian risk analyst whose job is to STRESS-TEST probability estimates. Another analyst has provided their assessment of this question. Your job is to find every flaw in their reasoning and argue for a DIFFERENT probability.

Today's date: {current_date}

QUESTION: {question}

CATEGORY: {category}

THESIS ANALYST'S ASSESSMENT:
{thesis_reasoning}
Their probability estimate: {thesis_probability}

ADDITIONAL CONTEXT:
{context}

INSTRUCTIONS:
1. Identify the WEAKEST assumptions in the thesis
2. Find evidence or arguments the thesis MISSED
3. Consider failure modes, tail risks, and overlooked factors
4. Argue for an alternative probability (you MUST disagree meaningfully)
5. Be specific about WHY the thesis probability is wrong

Format your response as:
FLAWS_IN_THESIS: [Specific weaknesses you found]
COUNTER_REASONING: [Your alternative analysis]
COUNTER_PROBABILITY: [Your alternative estimate, e.g., 0.42]
CONFIDENCE_IN_COUNTER: [How confident you are in YOUR alternative, 0-1]"""

JUDGE_PROMPT = """You are a senior portfolio manager who must make a FINAL probability estimate after reviewing a debate between two analysts.

Today's date: {current_date}

QUESTION: {question}

CATEGORY: {category}

THESIS (Analyst A — probability: {thesis_probability}):
{thesis_reasoning}

COUNTER-THESIS (Analyst B — probability: {counter_probability}):
{counter_reasoning}

ADDITIONAL CONTEXT:
{context}

INSTRUCTIONS:
1. Evaluate the strength of EACH argument on its merits
2. Identify which analyst made stronger empirical claims
3. Consider whether the counter-thesis found genuine flaws or was contrarian for its own sake
4. Synthesize both perspectives into a FINAL probability
5. Rate the quality of this debate (did it surface useful disagreement?)

Format your response as:
SYNTHESIS: [Your integrated analysis weighing both sides]
FINAL_PROBABILITY: [Your synthesized estimate, e.g., 0.55]
CONFIDENCE: [Your confidence in this estimate, 0-1]
DEBATE_QUALITY: [high/medium/low — did the debate surface useful information?]
DOMINANT_ARGUMENT: [thesis/counter/balanced]"""


def _extract_probability(text: str, field: str = "PROBABILITY") -> float:
    """Extract probability value from structured model output."""
    pattern = rf"{field}:\s*(\d*\.?\d+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        val = float(match.group(1))
        # Clamp to valid range
        return max(0.01, min(0.99, val))
    # Fallback: look for any decimal between 0 and 1
    decimals = re.findall(r"\b0\.\d{1,4}\b", text)
    if decimals:
        return max(0.01, min(0.99, float(decimals[-1])))
    return 0.5  # Default if parsing fails


def _extract_field(text: str, field: str) -> str:
    """Extract a text field from structured model output."""
    pattern = rf"{field}:\s*(.+?)(?=\n[A-Z_]+:|$)"
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


class DebatePipeline:
    """
    Orchestrates the 3-agent adversarial debate for probability estimation.

    Usage:
        pipeline = DebatePipeline()
        result = await pipeline.debate("Will X happen?", category="politics")
        if result.model_spread > 0.15:
            # High disagreement — size down or skip
            pass
    """

    def __init__(self):
        self._openai_client = None
        self._anthropic_client = None
        self._google_client = None
        self._initialized = False

    async def _init_clients(self):
        """Lazy-initialize API clients."""
        if self._initialized:
            return

        # OpenAI (GPT-5.1)
        try:
            from openai import AsyncOpenAI
            if os.environ.get("OPENAI_API_KEY"):
                self._openai_client = AsyncOpenAI()
                logger.info(f"Debate: OpenAI client ready ({GPT_THESIS_MODEL})")
        except ImportError:
            logger.warning("Debate: openai package not installed")

        # Anthropic (Claude 4.5)
        try:
            import anthropic
            if os.environ.get("ANTHROPIC_API_KEY"):
                self._anthropic_client = anthropic.AsyncAnthropic()
                logger.info(f"Debate: Anthropic client ready ({CLAUDE_REFUTER_MODEL})")
        except ImportError:
            logger.warning("Debate: anthropic package not installed")

        # Google (Gemini 3 Pro)
        try:
            import google.generativeai as genai
            if os.environ.get("GOOGLE_API_KEY"):
                genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
                self._google_client = genai
                logger.info(f"Debate: Google client ready ({GEMINI_JUDGE_MODEL})")
        except ImportError:
            logger.warning("Debate: google-generativeai package not installed")

        self._initialized = True

    async def _call_openai(self, prompt: str) -> str:
        """Call GPT-5.1 for thesis generation."""
        if not self._openai_client:
            raise RuntimeError("OpenAI client not available")
        started = time.perf_counter()
        with capture_external_span(
            "openai.chat.completions.create",
            system="llm",
            action="openai",
            labels={"provider": "openai", "model": GPT_THESIS_MODEL},
            context={"prompt_chars": len(prompt)},
        ):
            response = await self._openai_client.chat.completions.create(
                model=GPT_THESIS_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
        get_apm_runtime().record_metric(
            "llm_response_ms",
            (time.perf_counter() - started) * 1000.0,
            labels={"provider": "openai", "model": GPT_THESIS_MODEL, "debate_role": "thesis"},
        )
        return response.choices[0].message.content or ""

    async def _call_anthropic(self, prompt: str) -> str:
        """Call Claude 4.5 for counter-thesis generation."""
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client not available")
        started = time.perf_counter()
        with capture_external_span(
            "anthropic.messages.create",
            system="llm",
            action="anthropic",
            labels={"provider": "anthropic", "model": CLAUDE_REFUTER_MODEL},
            context={"prompt_chars": len(prompt)},
        ):
            response = await self._anthropic_client.messages.create(
                model=CLAUDE_REFUTER_MODEL,
                max_tokens=1500,
                temperature=0.4,  # Slightly higher for contrarian thinking
                messages=[{"role": "user", "content": prompt}],
            )
        get_apm_runtime().record_metric(
            "llm_response_ms",
            (time.perf_counter() - started) * 1000.0,
            labels={"provider": "anthropic", "model": CLAUDE_REFUTER_MODEL, "debate_role": "counter"},
        )
        return response.content[0].text if response.content else ""

    async def _call_gemini(self, prompt: str) -> str:
        """Call Gemini 3 Pro for judging."""
        if not self._google_client:
            raise RuntimeError("Google AI client not available")
        model = self._google_client.GenerativeModel(GEMINI_JUDGE_MODEL)
        started = time.perf_counter()
        with capture_external_span(
            "google.generativeai.generate_content",
            system="llm",
            action="gemini",
            labels={"provider": "google", "model": GEMINI_JUDGE_MODEL},
            context={"prompt_chars": len(prompt)},
        ):
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={"temperature": 0.2, "max_output_tokens": 1500},
            )
        get_apm_runtime().record_metric(
            "llm_response_ms",
            (time.perf_counter() - started) * 1000.0,
            labels={"provider": "google", "model": GEMINI_JUDGE_MODEL, "debate_role": "judge"},
        )
        return response.text or ""

    @track_latency("debate_round")
    async def debate(
        self,
        question: str,
        category: str = "general",
        context: str = "",
    ) -> DebateResult:
        """
        Run the full 3-agent adversarial debate.

        Steps:
          1. GPT-5.1 → thesis
          2. Claude 4.5 → counter-thesis (sees thesis)
          3. Gemini 3 Pro → judge (sees both)

        Args:
            question: The prediction market question
            category: Market category for context
            context: Additional context (news, data, etc.)

        Returns:
            DebateResult with synthesized probability and metadata
        """
        start = time.monotonic()
        await self._init_clients()

        result = DebateResult(
            probability=0.5,
            confidence=0.0,
            thesis_probability=0.5,
            counter_probability=0.5,
            judge_probability=0.5,
        )

        try:
            # Phase 1: Thesis (GPT-5.1)
            thesis_prompt = THESIS_PROMPT.format(
                question=question, category=category, context=context or "None provided",
                current_date=_current_date_str(),
            )
            thesis_text = await self._call_openai(thesis_prompt)
            thesis_prob = _extract_probability(thesis_text, "PROBABILITY")
            result.thesis_probability = thesis_prob
            result.thesis_reasoning = thesis_text
            logger.info(f"Debate thesis: {thesis_prob:.3f}")

            # Phase 2: Counter-thesis (Claude 4.5) — sees the thesis
            counter_prompt = COUNTER_PROMPT.format(
                question=question,
                category=category,
                thesis_reasoning=thesis_text,
                thesis_probability=thesis_prob,
                context=context or "None provided",
                current_date=_current_date_str(),
            )
            counter_text = await self._call_anthropic(counter_prompt)
            counter_prob = _extract_probability(counter_text, "COUNTER_PROBABILITY")
            result.counter_probability = counter_prob
            result.counter_reasoning = counter_text
            logger.info(f"Debate counter: {counter_prob:.3f}")

            # Phase 3: Judge (Gemini 3 Pro) — sees both
            judge_prompt = JUDGE_PROMPT.format(
                question=question,
                category=category,
                thesis_probability=thesis_prob,
                thesis_reasoning=thesis_text,
                counter_probability=counter_prob,
                counter_reasoning=counter_text,
                context=context or "None provided",
                current_date=_current_date_str(),
            )
            judge_text = await self._call_gemini(judge_prompt)
            judge_prob = _extract_probability(judge_text, "FINAL_PROBABILITY")
            result.judge_probability = judge_prob
            result.judge_reasoning = judge_text
            result.probability = judge_prob
            result.model_spread = abs(thesis_prob - counter_prob)

            # Extract metadata
            confidence_str = _extract_field(judge_text, "CONFIDENCE")
            try:
                result.confidence = float(re.search(r"(\d*\.?\d+)", confidence_str).group(1))
            except (AttributeError, ValueError):
                result.confidence = 0.5

            quality = _extract_field(judge_text, "DEBATE_QUALITY").lower()
            result.debate_quality = quality if quality in ("high", "medium", "low") else "unknown"

            logger.info(
                f"Debate result: thesis={thesis_prob:.3f} counter={counter_prob:.3f} "
                f"judge={judge_prob:.3f} spread={result.model_spread:.3f} "
                f"quality={result.debate_quality}"
            )

        except Exception as e:
            logger.error(f"Debate pipeline error: {e}")
            result.error = str(e)
            # Fallback: if we got at least a thesis, use it
            if result.thesis_probability != 0.5:
                result.probability = result.thesis_probability

        result.latency_ms = (time.monotonic() - start) * 1000
        return result


class ConformalWrapper:
    """
    Conformal prediction wrapper for DebatePipeline.

    Dispatch #75 — Strategy D-2: Conformal Prediction for Uncertainty Quantification.

    Maps model outputs to strict statistical coverage guarantees.
    Only trade when market price falls OUTSIDE the conformal interval.

    Requires calibration dataset of past (prediction, actual_outcome) pairs.
    """

    def __init__(self, coverage: float = 0.90):
        """
        Args:
            coverage: Target coverage probability (e.g., 0.90 = 90%)
        """
        if not (0.0 < coverage < 1.0):
            raise ValueError(f"coverage must be in (0, 1), got {coverage}")
        self.coverage = coverage
        self._nonconformity_scores: list[float] = []
        self._calibrated = False
        self._quantile: float = 1.0  # Width of interval (starts wide)

    def calibrate(self, predictions: list[float], actuals: list[int]):
        """
        Calibrate conformal prediction using historical data.

        Args:
            predictions: Past probability estimates (0-1)
            actuals: Past actual outcomes (0 or 1)
        """
        if len(predictions) != len(actuals):
            raise ValueError(
                "predictions and actuals must be the same length: "
                f"{len(predictions)} != {len(actuals)}"
            )
        if not predictions:
            raise ValueError("calibration data is empty")

        cleaned_actuals: list[int] = []
        for i, (pred, actual) in enumerate(zip(predictions, actuals, strict=False)):
            if not (0.0 <= pred <= 1.0):
                raise ValueError(f"prediction at index {i} out of range [0, 1]: {pred}")
            if actual not in (0, 1, False, True):
                raise ValueError(f"actual at index {i} must be 0/1, got {actual!r}")
            cleaned_actuals.append(int(actual))

        if len(predictions) < 20:
            logger.warning(
                f"Conformal: only {len(predictions)} calibration points. "
                f"Need 50+ for reliable intervals."
            )

        # Split-conformal nonconformity: absolute residual on calibration set.
        self._nonconformity_scores = [
            abs(pred - actual) for pred, actual in zip(predictions, cleaned_actuals, strict=False)
        ]

        # Quantile index: ceil((n + 1) * (1 - alpha)) with coverage = 1 - alpha.
        # 1-based rank is converted to 0-based index below and clipped to [1, n].
        sorted_scores = sorted(self._nonconformity_scores)
        n = len(sorted_scores)
        rank = math.ceil((n + 1) * self.coverage)
        rank = min(max(rank, 1), n)
        idx = rank - 1
        self._quantile = sorted_scores[idx]
        self._calibrated = True

        logger.info(
            f"Conformal calibrated: n={n}, coverage={self.coverage:.0%}, "
            f"interval_width={self._quantile:.3f}"
        )

    def get_interval(self, probability: float) -> tuple[float, float]:
        """
        Get prediction interval for a probability estimate.

        Returns:
            (lower, upper) bounds of the conformal interval
        """
        if not self._calibrated:
            # Uncalibrated: return full range (no trades)
            return (0.0, 1.0)

        lower = max(0.0, probability - self._quantile)
        upper = min(1.0, probability + self._quantile)
        return (lower, upper)

    def should_trade(self, probability: float, market_price: float) -> bool:
        """
        Should we trade? Only if market price is outside conformal interval.

        Args:
            probability: Our estimated probability
            market_price: Current market price

        Returns:
            True if market_price is outside the interval (mispriced with
            statistical confidence).
        """
        lower, upper = self.get_interval(probability)
        return market_price < lower or market_price > upper

    def get_sizing_factor(self, probability: float) -> float:
        """
        Size inversely proportional to interval width.
        Narrow interval = high confidence = larger position.

        Returns:
            Sizing multiplier (0-1). 1.0 = maximum confidence.
        """
        if not self._calibrated:
            return 0.0
        width = self._quantile * 2
        if width >= 0.8:
            return 0.0  # Too uncertain
        # Linear scaling: width 0 → factor 1.0, width 0.8 → factor 0.0
        return max(0.0, 1.0 - (width / 0.8))
