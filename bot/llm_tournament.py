#!/usr/bin/env python3
"""
LLM Tournament — Wisdom of the Silicon Crowd
============================================
Runs multiple LLMs (Claude, GPT, Gemini) on the same prediction market question
independently, WITHOUT showing them the market price (anti-anchoring).

When models agree tightly with each other but disagree significantly with the
market price, that consensus divergence is a high-conviction trading signal.

Academic basis: "Wisdom of the Silicon Crowd" (Science Advances, 2024).

Key design decisions:
  - Anti-anchoring: market price is NEVER in the prompt
  - Low temperature (0.3) for deterministic estimates
  - Agreement score normalized to [0,1] with std=0.25 as the "maximum
    disagreement" anchor
  - Signal requires BOTH agreement (models agree) AND divergence (they disagree
    with market)
  - Kelly sizing with 5% bankroll cap

Env vars:
    ANTHROPIC_API_KEY    — Claude
    OPENAI_API_KEY       — GPT
    GOOGLE_API_KEY       — Gemini

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from bot.apm_setup import capture_external_span, get_apm_runtime
except ImportError:  # pragma: no cover - direct script execution fallback
    from apm_setup import capture_external_span, get_apm_runtime  # type: ignore

logger = logging.getLogger("JJ.llm_tournament")

# Default model roster — override via constructor
# Cost-optimized default: 1 premium + 2 cheap = diversity without burning cash
DEFAULT_MODELS = ["claude-haiku-3-5", "gemini-2.0-flash", "gpt-4o-mini"]

# Full model roster with cost-per-1k-tokens (input + output blended)
_MODEL_COST_PER_1K: dict[str, float] = {
    # Premium (use sparingly for high-conviction checks)
    "claude-sonnet-4-6": 0.003,
    "gpt-4o": 0.005,
    "gemini-1.5-pro": 0.00125,
    # Cheap workhorses (primary tournament participants)
    "claude-haiku-3-5": 0.0008,
    "gpt-4o-mini": 0.00015,
    "gemini-2.0-flash": 0.00035,
    # Near-free (Groq free tier, Kimi/Moonshot, DeepSeek)
    "llama-3.3-70b-versatile": 0.0,      # Groq free tier
    "llama-3.1-8b-instant": 0.0,          # Groq free tier
    "qwen-qwq-32b": 0.0,                  # Groq free tier
    "moonshot-v1-8k": 0.0001,             # Kimi 2.5 / Moonshot AI
    "moonshot-v1-32k": 0.0002,            # Kimi 2.5 long context
    "deepseek-chat": 0.00014,             # DeepSeek V3
    "deepseek-reasoner": 0.00042,         # DeepSeek R1
}
_DEFAULT_COST_PER_1K = 0.002  # fallback for unknown models

# Provider routing: model prefix -> base URL for OpenAI-compatible APIs
_PROVIDER_BASE_URLS: dict[str, str] = {
    "llama-": "https://api.groq.com/openai/v1",
    "qwen-": "https://api.groq.com/openai/v1",
    "moonshot-": "https://api.moonshot.cn/v1",
    "deepseek-": "https://api.deepseek.com/v1",
}

# API key env-var for each OpenAI-compat provider prefix
_PROVIDER_API_KEY_ENVS: dict[str, str] = {
    "llama-": "GROQ_API_KEY",
    "qwen-": "GROQ_API_KEY",
    "moonshot-": "MOONSHOT_API_KEY",
    "deepseek-": "DEEPSEEK_API_KEY",
}

PROMPT_TEMPLATE = """You are a superforecaster estimating probabilities for prediction markets.

Question: {question}
{context_block}
{resolution_block}
Instructions:
1. Think step by step about the base rate for this type of event
2. Consider the most important factors that would shift the probability
3. State your probability estimate as a single number between 0.00 and 1.00
4. Rate your confidence: HIGH, MEDIUM, or LOW
5. Summarize your reasoning in 1-2 sentences

Format your response EXACTLY as:
PROBABILITY: X.XX
CONFIDENCE: [HIGH/MEDIUM/LOW]
REASONING: [your reasoning]"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ModelEstimate:
    """Single LLM's probability estimate for a question."""

    model_name: str
    probability: float           # Model's estimated probability (0-1)
    confidence: str              # "high", "medium", "low"
    reasoning_summary: str       # 1-2 sentence summary of reasoning
    response_time_ms: float
    cost_usd: float              # API cost for this call
    raw_response: str            # Full response for audit


@dataclass
class TournamentResult:
    """Aggregated outcome of a multi-model probability tournament."""

    market_id: str
    market_question: str
    estimates: list[ModelEstimate]

    # Consensus metrics
    mean_probability: float
    median_probability: float
    std_probability: float
    agreement_score: float       # 1 - min(std/0.25, 1.0); higher = more agreement

    # Market comparison
    market_price: float          # Current market YES price
    divergence: float            # mean_probability - market_price  (signed)
    abs_divergence: float        # |divergence|

    # Signal
    signal: str                  # "BUY_YES", "BUY_NO", "NO_SIGNAL"
    signal_strength: float       # agreement_score * abs_divergence * (n / 3)

    # Metadata
    total_cost_usd: float
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class LLMTournament:
    """
    Runs a panel of LLMs on a prediction market question and extracts a
    consensus-divergence trading signal.

    Usage (injected responses for tests / offline use):

        tournament = LLMTournament()
        result = await tournament.run_tournament(
            market_id="abc123",
            question="Will X happen by Y?",
            market_price=0.55,
            model_responses={
                "claude-sonnet-4-6": "PROBABILITY: 0.75\\nCONFIDENCE: HIGH\\nREASONING: ...",
                "gpt-4o": "PROBABILITY: 0.76\\nCONFIDENCE: HIGH\\nREASONING: ...",
                "gemini-2.0-flash": "PROBABILITY: 0.74\\nCONFIDENCE: MEDIUM\\nREASONING: ...",
            },
        )
    """

    def __init__(
        self,
        models: Optional[list[str]] = None,
        min_agreement: float = 0.80,
        min_divergence: float = 0.10,
        temperature: float = 0.3,
        max_concurrent: int = 3,
        budget_per_question_usd: float = 0.50,
    ) -> None:
        self.models = models if models is not None else list(DEFAULT_MODELS)
        self.min_agreement = min_agreement
        self.min_divergence = min_divergence
        self.temperature = temperature
        self.max_concurrent = max_concurrent
        self.budget_per_question_usd = budget_per_question_usd

        # Lazy-initialized API clients
        self._anthropic_client = None
        self._openai_client = None
        self._google_client = None
        self._compat_clients: dict[str, object] = {}   # prefix -> AsyncOpenAI
        self._clients_initialized = False

        # Historical accuracy tracking
        self._history: list[dict] = []

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def build_prompt(
        self,
        question: str,
        context: str = "",
        resolution_criteria: str = "",
    ) -> str:
        """Build the probability estimation prompt.

        CRITICAL: The market price is NEVER included in this prompt.
        Anti-anchoring is the #1 design rule.
        """
        context_block = f"\nContext: {context}\n" if context else ""
        resolution_block = (
            f"\nResolution criteria: {resolution_criteria}\n"
            if resolution_criteria
            else ""
        )
        return PROMPT_TEMPLATE.format(
            question=question,
            context_block=context_block,
            resolution_block=resolution_block,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def parse_response(self, response: str, model_name: str) -> ModelEstimate:
        """Parse an LLM response into a ModelEstimate.

        Handles:
        - Exact format compliance
        - Missing fields (confidence defaults to MEDIUM)
        - Probability outside [0, 1] (clamped)
        - Non-numeric probability (raises ValueError)
        """
        # Extract PROBABILITY (allow optional leading minus so clamping works)
        prob_match = re.search(
            r"PROBABILITY\s*:\s*(-?[0-9]*\.?[0-9]+)", response, re.IGNORECASE
        )
        if not prob_match:
            raise ValueError(
                f"[{model_name}] Could not parse PROBABILITY from response: "
                f"{response[:120]!r}"
            )
        raw_prob = float(prob_match.group(1))
        probability = max(0.0, min(1.0, raw_prob))
        if raw_prob != probability:
            logger.warning(
                "[%s] Probability %.4f out of range, clamped to %.4f",
                model_name,
                raw_prob,
                probability,
            )

        # Extract CONFIDENCE (default MEDIUM)
        conf_match = re.search(
            r"CONFIDENCE\s*:\s*(HIGH|MEDIUM|LOW)", response, re.IGNORECASE
        )
        confidence = conf_match.group(1).lower() if conf_match else "medium"

        # Extract REASONING
        reasoning_match = re.search(
            r"REASONING\s*:\s*(.+?)(?:\n[A-Z_]+\s*:|$)",
            response,
            re.IGNORECASE | re.DOTALL,
        )
        reasoning_summary = (
            reasoning_match.group(1).strip() if reasoning_match else ""
        )

        return ModelEstimate(
            model_name=model_name,
            probability=probability,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            response_time_ms=0.0,   # filled in by query_model
            cost_usd=0.0,           # filled in by query_model
            raw_response=response,
        )

    # ------------------------------------------------------------------
    # Agreement metric
    # ------------------------------------------------------------------

    def compute_agreement(self, estimates: list[ModelEstimate]) -> float:
        """Compute agreement score from model estimates.

        agreement = 1.0 - min(std / 0.25, 1.0)

        Rationale: std of 0.25 means models span half the probability space.
        std of 0 means perfect agreement. Normalizes to [0, 1].
        """
        if len(estimates) < 2:
            return 1.0  # single model — trivially "agrees with itself"
        probs = [e.probability for e in estimates]
        std = float(np.std(probs, ddof=0))
        return 1.0 - min(std / 0.25, 1.0)

    # ------------------------------------------------------------------
    # API client initialization (lazy)
    # ------------------------------------------------------------------

    async def _init_clients(self) -> None:
        """Lazy-initialize API clients on first live query."""
        if self._clients_initialized:
            return
        import os

        try:
            import anthropic
            if os.environ.get("ANTHROPIC_API_KEY"):
                self._anthropic_client = anthropic.AsyncAnthropic()
                logger.info("Tournament: Anthropic client ready")
        except ImportError:
            logger.warning("Tournament: anthropic package not installed")

        try:
            from openai import AsyncOpenAI
            if os.environ.get("OPENAI_API_KEY"):
                self._openai_client = AsyncOpenAI()
                logger.info("Tournament: OpenAI client ready")
        except ImportError:
            logger.warning("Tournament: openai package not installed")

        try:
            import google.generativeai as genai
            import os as _os
            if _os.environ.get("GOOGLE_API_KEY"):
                genai.configure(api_key=_os.environ["GOOGLE_API_KEY"])
                self._google_client = genai
                logger.info("Tournament: Google Generative AI client ready")
        except ImportError:
            logger.warning("Tournament: google-generativeai package not installed")

        self._clients_initialized = True

    # ------------------------------------------------------------------
    # Single-model query
    # ------------------------------------------------------------------

    def _estimate_cost(self, model_name: str, prompt: str, response: str) -> float:
        """Rough cost estimate based on token count heuristic (4 chars ≈ 1 token)."""
        cost_per_1k = _MODEL_COST_PER_1K.get(model_name, _DEFAULT_COST_PER_1K)
        tokens = (len(prompt) + len(response)) / 4.0
        return (tokens / 1000.0) * cost_per_1k

    async def query_model(self, model_name: str, prompt: str) -> ModelEstimate:
        """Query a single LLM and return its estimate.

        In production, dispatches to the appropriate SDK based on model_name
        prefix.  In tests, responses are injected via run_tournament's
        model_responses parameter, so this method is only called for live runs.
        """
        await self._init_clients()
        started = time.perf_counter()

        try:
            if model_name.startswith("claude"):
                raw = await self._call_anthropic(model_name, prompt)
            elif model_name.startswith("gpt") or model_name.startswith("o"):
                raw = await self._call_openai(model_name, prompt)
            elif model_name.startswith("gemini"):
                raw = await self._call_google(model_name, prompt)
            elif any(model_name.startswith(p) for p in _PROVIDER_BASE_URLS):
                raw = await self._call_compat(model_name, prompt)
            else:
                raise RuntimeError(
                    f"Unknown model provider for model name: {model_name!r}"
                )
        except Exception as exc:
            logger.error("[%s] API call failed: %s", model_name, exc)
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cost = self._estimate_cost(model_name, prompt, raw)

        estimate = self.parse_response(raw, model_name)
        estimate.response_time_ms = elapsed_ms
        estimate.cost_usd = cost
        return estimate

    async def _call_anthropic(self, model_name: str, prompt: str) -> str:
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client not available (no API key?)")
        response = await self._anthropic_client.messages.create(
            model=model_name,
            max_tokens=512,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    async def _call_openai(self, model_name: str, prompt: str) -> str:
        if not self._openai_client:
            raise RuntimeError("OpenAI client not available (no API key?)")
        response = await self._openai_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=512,
        )
        return response.choices[0].message.content or ""

    async def _call_google(self, model_name: str, prompt: str) -> str:
        if not self._google_client:
            raise RuntimeError("Google client not available (no API key?)")
        model = self._google_client.GenerativeModel(model_name)
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text if response.text else ""

    async def _call_compat(self, model_name: str, prompt: str) -> str:
        """Call an OpenAI-compatible provider (Groq, Moonshot, DeepSeek, etc.)."""
        import os
        from openai import AsyncOpenAI

        # Find the matching prefix
        prefix = next(
            (p for p in _PROVIDER_BASE_URLS if model_name.startswith(p)), None
        )
        if prefix is None:
            raise RuntimeError(f"No compat base URL for model: {model_name!r}")

        # Build client once per prefix and cache it
        if prefix not in self._compat_clients:
            base_url = _PROVIDER_BASE_URLS[prefix]
            api_key_env = _PROVIDER_API_KEY_ENVS.get(prefix, "")
            api_key = os.environ.get(api_key_env, "") if api_key_env else ""
            if not api_key or api_key.startswith("your-"):
                raise RuntimeError(
                    f"API key not set for provider {prefix!r} "
                    f"(env var: {api_key_env!r})"
                )
            self._compat_clients[prefix] = AsyncOpenAI(
                api_key=api_key, base_url=base_url
            )
            logger.info("Tournament: compat client ready for prefix=%r", prefix)

        client = self._compat_clients[prefix]
        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=512,
        )
        text = response.choices[0].message.content or ""
        # Log usage so provider status flips from configured → active
        self._log_provider_usage(prefix=prefix, model_name=model_name, prompt=prompt, response=text)
        return text

    def _log_provider_usage(
        self,
        *,
        prefix: str,
        model_name: str,
        prompt: str,
        response: str,
    ) -> None:
        """Append one usage record to reports/autoresearch/providers/{name}/history.jsonl."""
        import json as _json
        import time as _time
        from pathlib import Path as _Path
        from datetime import datetime as _dt, timezone as _tz

        # Derive a human-friendly provider name from the prefix (strip trailing dash)
        provider_name = prefix.rstrip("-")
        cost = self._estimate_cost(model_name, prompt, response)
        tokens_estimate = int((len(prompt) + len(response)) / 4)
        record = {
            "ts": _dt.now(tz=_tz.utc).isoformat(),
            "epoch_s": _time.time(),
            "provider": provider_name,
            "model": model_name,
            "prompt_chars": len(prompt),
            "response_chars": len(response),
            "tokens_estimate": tokens_estimate,
            "cost_usd": round(cost, 8),
            "lane": "tournament",
        }
        try:
            root = _Path(__file__).resolve().parents[1]
            provider_dir = root / "reports" / "autoresearch" / "providers" / provider_name
            provider_dir.mkdir(parents=True, exist_ok=True)
            history_path = provider_dir / "history.jsonl"
            with history_path.open("a", encoding="utf-8") as fh:
                fh.write(_json.dumps(record) + "\n")
            # Overwrite status with latest activity
            status = {
                "provider": provider_name,
                "status": "active",
                "last_used_at": record["ts"],
                "last_model": model_name,
                "last_cost_usd": record["cost_usd"],
            }
            (provider_dir / "status.json").write_text(
                _json.dumps(status, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider usage log failed for %s: %s", provider_name, exc)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_tournament(
        self,
        market_id: str,
        question: str,
        market_price: float,
        context: str = "",
        resolution_criteria: str = "",
        model_responses: Optional[dict[str, str]] = None,
    ) -> TournamentResult:
        """Run the full tournament.

        Steps:
        1. Build prompt (NO market price included)
        2. Query all models in parallel (or use injected responses)
        3. Parse all responses
        4. Compute consensus metrics
        5. Compare to market price
        6. Generate signal

        Args:
            model_responses: If provided, bypass live API calls and use these
                             raw response strings keyed by model name.  Models
                             not present in the dict are skipped.  This is the
                             primary mechanism for testing.
        """
        prompt = self.build_prompt(question, context, resolution_criteria)

        # Gather estimates (parallel for live, direct parse for injected)
        if model_responses is not None:
            estimates = self._parse_injected_responses(model_responses)
        else:
            estimates = await self._query_all_models(prompt)

        if not estimates:
            raise RuntimeError(f"No estimates produced for market {market_id!r}")

        probs = np.array([e.probability for e in estimates])
        mean_prob = float(np.mean(probs))
        median_prob = float(np.median(probs))
        std_prob = float(np.std(probs, ddof=0))
        agreement = self.compute_agreement(estimates)

        divergence = mean_prob - market_price
        abs_divergence = abs(divergence)

        signal = self._determine_signal(agreement, divergence, abs_divergence)
        signal_strength = agreement * abs_divergence * (len(estimates) / 3.0)

        total_cost = sum(e.cost_usd for e in estimates)

        result = TournamentResult(
            market_id=market_id,
            market_question=question,
            estimates=estimates,
            mean_probability=mean_prob,
            median_probability=median_prob,
            std_probability=std_prob,
            agreement_score=agreement,
            market_price=market_price,
            divergence=divergence,
            abs_divergence=abs_divergence,
            signal=signal,
            signal_strength=signal_strength,
            total_cost_usd=total_cost,
            timestamp=time.time(),
        )

        self._emit_telemetry(result)
        logger.info(
            "Tournament[%s]: signal=%s strength=%.3f agreement=%.2f "
            "mean=%.2f market=%.2f divergence=%+.2f cost=$%.4f",
            market_id,
            signal,
            signal_strength,
            agreement,
            mean_prob,
            market_price,
            divergence,
            total_cost,
        )
        return result

    def _parse_injected_responses(
        self, model_responses: dict[str, str]
    ) -> list[ModelEstimate]:
        estimates: list[ModelEstimate] = []
        for model_name, raw_response in model_responses.items():
            try:
                est = self.parse_response(raw_response, model_name)
                # Injected responses have zero latency / cost by convention
                est.response_time_ms = 0.0
                est.cost_usd = 0.0
                estimates.append(est)
            except ValueError as exc:
                logger.error("Injected response parse failed: %s", exc)
        return estimates

    async def _query_all_models(self, prompt: str) -> list[ModelEstimate]:
        """Query all models in parallel, respecting max_concurrent."""
        sem = asyncio.Semaphore(self.max_concurrent)
        budget_remaining = [self.budget_per_question_usd]

        async def _guarded_query(model_name: str) -> Optional[ModelEstimate]:
            async with sem:
                if budget_remaining[0] <= 0:
                    logger.warning(
                        "[%s] Budget exhausted, skipping", model_name
                    )
                    return None
                try:
                    est = await self.query_model(model_name, prompt)
                    budget_remaining[0] -= est.cost_usd
                    return est
                except Exception as exc:
                    logger.error("[%s] query failed: %s", model_name, exc)
                    return None

        tasks = [_guarded_query(m) for m in self.models]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _determine_signal(
        self, agreement: float, divergence: float, abs_divergence: float
    ) -> str:
        if agreement < self.min_agreement:
            return "NO_SIGNAL"
        if abs_divergence < self.min_divergence:
            return "NO_SIGNAL"
        return "BUY_YES" if divergence > 0 else "BUY_NO"

    # ------------------------------------------------------------------
    # Trading helpers
    # ------------------------------------------------------------------

    def should_trade(self, result: TournamentResult) -> bool:
        """True if signal is actionable (not NO_SIGNAL) and strength is nonzero."""
        return result.signal != "NO_SIGNAL" and result.signal_strength > 0.0

    def get_position_size(
        self,
        result: TournamentResult,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
    ) -> float:
        """Kelly-size the position based on signal strength.

        edge = abs_divergence * agreement_score
        kelly_size = kelly_fraction * bankroll * edge
        Capped at bankroll * 0.05 (max 5% per trade)
        """
        edge = result.abs_divergence * result.agreement_score
        kelly_size = kelly_fraction * bankroll * edge
        cap = bankroll * 0.05
        return min(kelly_size, cap)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_alert(self, result: TournamentResult) -> str:
        """Format tournament result as a Telegram-style alert string."""
        model_lines = "\n".join(
            f"  {e.model_name}: {e.probability:.2f} ({e.confidence})"
            for e in result.estimates
        )
        lines = [
            f"LLM TOURNAMENT — {result.signal}",
            f"Market: {result.market_question}",
            f"ID: {result.market_id}",
            f"",
            f"Model estimates:",
            model_lines,
            f"",
            f"Consensus: mean={result.mean_probability:.3f}  "
            f"std={result.std_probability:.3f}  "
            f"agreement={result.agreement_score:.2f}",
            f"Market price: {result.market_price:.3f}",
            f"Divergence: {result.divergence:+.3f}",
            f"Signal strength: {result.signal_strength:.3f}",
            f"Total cost: ${result.total_cost_usd:.4f}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Historical accuracy
    # ------------------------------------------------------------------

    def record_outcome(self, result: TournamentResult, resolved_yes: bool) -> None:
        """Record the actual resolution of a market for accuracy tracking.

        Call this after a market resolves to feed the self-evaluation loop.
        """
        if result.signal == "NO_SIGNAL":
            return
        predicted_yes = result.signal == "BUY_YES"
        correct = predicted_yes == resolved_yes
        self._history.append(
            {
                "market_id": result.market_id,
                "signal": result.signal,
                "mean_probability": result.mean_probability,
                "market_price": result.market_price,
                "abs_divergence": result.abs_divergence,
                "signal_strength": result.signal_strength,
                "resolved_yes": resolved_yes,
                "correct": correct,
            }
        )
        logger.info(
            "Historical record: market=%s signal=%s correct=%s",
            result.market_id,
            result.signal,
            correct,
        )

    def historical_accuracy(self) -> dict:
        """Return accuracy statistics over all recorded signals."""
        total = len(self._history)
        if total == 0:
            return {
                "total_signals": 0,
                "correct": 0,
                "accuracy": None,
                "avg_divergence_on_correct": None,
            }
        correct_records = [r for r in self._history if r["correct"]]
        correct = len(correct_records)
        accuracy = correct / total
        avg_div_correct = (
            float(np.mean([r["abs_divergence"] for r in correct_records]))
            if correct_records
            else None
        )
        return {
            "total_signals": total,
            "correct": correct,
            "accuracy": accuracy,
            "avg_divergence_on_correct": avg_div_correct,
        }

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _emit_telemetry(self, result: TournamentResult) -> None:
        """Emit APM metrics for the tournament result."""
        try:
            apm = get_apm_runtime()
            labels = {
                "signal": result.signal,
                "market_id": result.market_id,
            }
            apm.record_metric("tournament.agreement_score", result.agreement_score, labels=labels)
            apm.record_metric("tournament.abs_divergence", result.abs_divergence, labels=labels)
            apm.record_metric("tournament.signal_strength", result.signal_strength, labels=labels)
            apm.record_metric("tournament.total_cost_usd", result.total_cost_usd, labels=labels)
        except Exception:
            pass  # Telemetry is best-effort
