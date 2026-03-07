#!/usr/bin/env python3
"""
LLM Ensemble + Agentic RAG — Multi-Model Probability Estimation
================================================================
Drop-in replacement for single-Claude estimation in jj_live.py.

Architecture:
  1. AGENTIC RAG: Search web for recent context about the market question
  2. MULTI-MODEL: Run Claude Haiku + GPT-4.1-mini + (optional) Groq in parallel
  3. AGGREGATE: Trimmed mean + consensus gating
  4. CALIBRATE: Platt scaling on ensemble output
  5. BRIER TRACK: Record estimates for live accuracy measurement

Research basis:
  - Agentic RAG: Brier delta -0.06 to -0.15 (Halawi 2024, NeurIPS)
  - Multi-model ensemble: Brier delta -0.01 to -0.03 (Halawi 2024)
  - GPT-4.1 Brier: 0.1542 vs Claude Haiku 0.22 (ForecastBench 2025)
  - Trimmed mean: robust to outlier models (Bridgewater AIA 2025)
  - Consensus gating: only trade when 75%+ models agree on direction

Usage:
    ensemble = LLMEnsemble()
    result = await ensemble.estimate("Will X happen by Y?", category="politics")
    # Returns: {probability, calibrated_probability, confidence, reasoning,
    #           n_models, model_spread, consensus, search_context_used}

Env vars:
    ANTHROPIC_API_KEY  — Claude (required)
    OPENAI_API_KEY     — GPT-4.1-mini (recommended, $0.40/1M input)
    GROQ_API_KEY       — Free Llama 3.3 70B (optional, $0)

Cost at 50 markets/day:
    Claude Haiku:   ~$0.80/mo
    GPT-4.1-mini:   ~$1.50/mo
    Groq:           $0.00/mo (free tier)
    Total:          ~$2.30/mo for 3-model ensemble
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("JJ.ensemble")

# ---------------------------------------------------------------------------
# Calibration (same Platt params as jj_live.py / claude_analyzer.py)
# ---------------------------------------------------------------------------
PLATT_A = float(os.environ.get("PLATT_A", "0.55"))
PLATT_B = float(os.environ.get("PLATT_B", "-0.40"))


def calibrate_probability(raw_prob: float) -> float:
    """Apply Platt scaling. Maps: 90% → 71%, 80% → 60%, 70% → 53%."""
    raw_prob = max(0.001, min(0.999, raw_prob))
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability(1.0 - raw_prob)
    logit_input = math.log(raw_prob / (1 - raw_prob))
    logit_output = PLATT_A * logit_input + PLATT_B
    logit_output = max(-30, min(30, logit_output))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


# ---------------------------------------------------------------------------
# Estimation Prompt
# ---------------------------------------------------------------------------
BASE_PROMPT = """Estimate the probability that this event resolves YES.

Question: {question}

{context_section}

Step 1: What is the historical base rate for events like this?
Step 2: What specific evidence — including any recent context provided above — adjusts the probability up or down from the base rate?
Step 3: Give your final estimate.

IMPORTANT CALIBRATION NOTE: LLMs have a documented tendency to overestimate YES probabilities by 20-30%. When you feel 70-80% confident in YES, the true rate is closer to 50-55%. When you feel 90%+ confident in YES, the true rate is closer to 63%. Adjust your estimate downward accordingly.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""


def build_prompt(question: str, search_context: str = "") -> str:
    """Build estimation prompt with optional RAG context."""
    if search_context:
        context_section = (
            f"RECENT CONTEXT (from web search, may help inform your estimate):\n"
            f"{search_context}\n"
        )
    else:
        context_section = ""
    return BASE_PROMPT.format(question=question, context_section=context_section)


# ---------------------------------------------------------------------------
# Response Parsing
# ---------------------------------------------------------------------------
@dataclass
class ModelEstimate:
    """Single model's probability estimate."""
    model_name: str
    probability: float
    confidence: str  # "low", "medium", "high"
    reasoning: str
    latency_ms: float = 0.0
    error: str = ""


def parse_llm_response(text: str, model_name: str) -> ModelEstimate:
    """Parse PROBABILITY/CONFIDENCE/REASONING from LLM response text."""
    prob = None
    confidence = "medium"
    reasoning = ""

    for line in text.strip().split("\n"):
        line_clean = line.strip()
        upper = line_clean.upper()

        if upper.startswith("PROBABILITY:"):
            val = line_clean.split(":", 1)[1].strip()
            # Handle "0.65" or "65%" or "0.65 (65%)"
            val = re.sub(r'[()%]', '', val).strip().split()[0]
            try:
                p = float(val)
                if p > 1.0:
                    p /= 100.0  # "65" → 0.65
                prob = max(0.01, min(0.99, p))
            except (ValueError, IndexError):
                pass

        elif upper.startswith("CONFIDENCE:"):
            val = line_clean.split(":", 1)[1].strip().lower()
            if "high" in val:
                confidence = "high"
            elif "low" in val:
                confidence = "low"
            else:
                confidence = "medium"

        elif upper.startswith("REASONING:"):
            reasoning = line_clean.split(":", 1)[1].strip()

    if prob is None:
        # Fallback: find any decimal in [0.01, 0.99]
        numbers = re.findall(r'0\.\d+', text)
        for n in numbers:
            p = float(n)
            if 0.01 <= p <= 0.99:
                prob = p
                break

    if prob is None:
        return ModelEstimate(
            model_name=model_name,
            probability=0.5,
            confidence="low",
            reasoning="Failed to parse probability",
            error="parse_failure",
        )

    return ModelEstimate(
        model_name=model_name,
        probability=prob,
        confidence=confidence,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Agentic RAG — Web Search for Context
# ---------------------------------------------------------------------------
async def search_for_context(question: str, max_results: int = 5) -> str:
    """Search the web for recent context about the market question.

    Uses DuckDuckGo (free, no API key). Falls back gracefully.
    Returns a condensed string of search snippets.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.debug("ddgs/duckduckgo-search not installed, skipping RAG")
            return ""

    # Build search query from question — strip question marks, common filler
    query = question.replace("?", "").strip()
    # Truncate to avoid overly long queries
    if len(query) > 120:
        query = query[:120]

    try:
        # Run in executor since DDGS is synchronous
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: list(DDGS().text(query, max_results=max_results, region="wt-wt")),
        )

        if not results:
            return ""

        # Condense to key snippets (keep it short for the LLM context)
        snippets = []
        for r in results[:max_results]:
            title = r.get("title", "")
            body = r.get("body", "")
            # Truncate each snippet
            snippet = f"- {title}: {body[:200]}"
            snippets.append(snippet)

        context = "\n".join(snippets)
        # Cap total context to ~800 chars to keep prompt costs low
        if len(context) > 800:
            context = context[:800] + "..."

        logger.debug(f"RAG search returned {len(results)} results for: {query[:60]}")
        return context

    except Exception as e:
        logger.debug(f"RAG search failed (non-fatal): {e}")
        return ""


# ---------------------------------------------------------------------------
# Individual Model Callers
# ---------------------------------------------------------------------------
async def call_claude(prompt: str, timeout: float = 30.0) -> ModelEstimate:
    """Call Claude Haiku via Anthropic SDK."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ModelEstimate("claude-haiku", 0.5, "low", "", error="no_api_key")

    try:
        import anthropic
    except ImportError:
        return ModelEstimate("claude-haiku", 0.5, "low", "", error="sdk_not_installed")

    # Try models in order of preference (newest first)
    CLAUDE_MODELS = [
        os.environ.get("CLAUDE_MODEL", ""),
        "claude-haiku-4-5-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-haiku-20240307",
    ]
    # Remove empty strings and deduplicate while preserving order
    models_to_try = list(dict.fromkeys(m for m in CLAUDE_MODELS if m))

    t0 = time.monotonic()
    client = anthropic.AsyncAnthropic(api_key=api_key)
    last_error = ""

    for model_name in models_to_try:
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model_name,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout,
            )
            text = response.content[0].text
            result = parse_llm_response(text, f"claude-haiku")
            result.latency_ms = (time.monotonic() - t0) * 1000
            return result
        except asyncio.TimeoutError:
            return ModelEstimate("claude-haiku", 0.5, "low", "", error="timeout",
                                 latency_ms=(time.monotonic() - t0) * 1000)
        except Exception as e:
            last_error = str(e)
            if "not_found" in last_error or "404" in last_error:
                continue  # Try next model
            break  # Other errors (auth, rate limit) → don't retry

    return ModelEstimate("claude-haiku", 0.5, "low", "", error=last_error,
                         latency_ms=(time.monotonic() - t0) * 1000)


async def call_gpt(prompt: str, model: str = "gpt-4.1-mini",
                   timeout: float = 30.0) -> ModelEstimate:
    """Call OpenAI GPT via openai SDK."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ModelEstimate(model, 0.5, "low", "", error="no_api_key")

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return ModelEstimate(model, 0.5, "low", "", error="sdk_not_installed")

    t0 = time.monotonic()
    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a probability estimation expert. Be precise and "
                        "calibrated. Respond in the exact format requested."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=300,
                temperature=0.2,
            ),
            timeout=timeout,
        )
        text = response.choices[0].message.content or ""
        result = parse_llm_response(text, model)
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result
    except asyncio.TimeoutError:
        return ModelEstimate(model, 0.5, "low", "", error="timeout",
                             latency_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        return ModelEstimate(model, 0.5, "low", "", error=str(e),
                             latency_ms=(time.monotonic() - t0) * 1000)


async def call_groq(prompt: str, model: str = "llama-3.3-70b-versatile",
                    timeout: float = 30.0) -> ModelEstimate:
    """Call Groq free tier via OpenAI-compatible API."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return ModelEstimate(f"groq-{model}", 0.5, "low", "", error="no_api_key")

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return ModelEstimate(f"groq-{model}", 0.5, "low", "", error="sdk_not_installed")

    t0 = time.monotonic()
    try:
        client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a probability estimation expert. Be precise and "
                        "calibrated. Respond in the exact format requested."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.2,
            ),
            timeout=timeout,
        )
        text = response.choices[0].message.content or ""
        result = parse_llm_response(text, f"groq-{model}")
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result
    except asyncio.TimeoutError:
        return ModelEstimate(f"groq-{model}", 0.5, "low", "", error="timeout",
                             latency_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        return ModelEstimate(f"groq-{model}", 0.5, "low", "", error=str(e),
                             latency_ms=(time.monotonic() - t0) * 1000)


async def call_grok(prompt: str, model: str = "grok-3-mini-fast",
                    timeout: float = 60.0) -> ModelEstimate:
    """Call xAI Grok via OpenAI-compatible API."""
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return ModelEstimate(f"grok", 0.5, "low", "", error="no_api_key")

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return ModelEstimate(f"grok", 0.5, "low", "", error="sdk_not_installed")

    t0 = time.monotonic()
    try:
        client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a probability estimation expert. Be precise and "
                        "calibrated. Respond in the exact format requested."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.2,
            ),
            timeout=timeout,
        )
        text = response.choices[0].message.content or ""
        result = parse_llm_response(text, "grok")
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result
    except asyncio.TimeoutError:
        return ModelEstimate("grok", 0.5, "low", "", error="timeout",
                             latency_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        return ModelEstimate("grok", 0.5, "low", "", error=str(e),
                             latency_ms=(time.monotonic() - t0) * 1000)


# ---------------------------------------------------------------------------
# Ensemble Aggregation
# ---------------------------------------------------------------------------
@dataclass
class EnsembleResult:
    """Result from multi-model ensemble estimation."""
    # Raw ensemble output
    probability: float           # Trimmed mean of model estimates
    calibrated_probability: float  # After Platt scaling
    confidence: str              # "high", "medium", "low"
    reasoning: str               # Combined reasoning from models

    # Ensemble metadata
    n_models: int = 0            # How many models succeeded
    model_spread: float = 0.0    # Max - min estimate (disagreement)
    consensus: float = 0.0       # Fraction agreeing on YES/NO direction
    models_agree: bool = False   # consensus >= 0.75 AND spread < 0.20
    search_context_used: bool = False  # Was RAG context injected?

    # Individual model outputs
    model_estimates: list = field(default_factory=list)

    # Errors
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["model_estimates"] = [asdict(m) for m in self.model_estimates]
        return d


def trimmed_mean(values: list[float]) -> float:
    """Trimmed mean — drop highest and lowest, average rest.

    For 2 models: simple average.
    For 3+ models: drop 1 extreme from each end.
    """
    if not values:
        return 0.5
    if len(values) <= 2:
        return sum(values) / len(values)

    sorted_vals = sorted(values)
    # Drop 1 from each end
    trimmed = sorted_vals[1:-1]
    return sum(trimmed) / len(trimmed)


def compute_consensus(estimates: list[ModelEstimate]) -> float:
    """Fraction of models agreeing on direction (> 0.5 = YES, < 0.5 = NO)."""
    if not estimates:
        return 0.0
    yes_count = sum(1 for e in estimates if e.probability > 0.5)
    no_count = sum(1 for e in estimates if e.probability < 0.5)
    return max(yes_count, no_count) / len(estimates)


def confidence_from_spread(spread: float, consensus: float) -> str:
    """Map model disagreement to confidence level."""
    if spread < 0.10 and consensus >= 0.9:
        return "high"
    elif spread < 0.20 and consensus >= 0.75:
        return "medium"
    else:
        return "low"


# ---------------------------------------------------------------------------
# Brier Score Tracking
# ---------------------------------------------------------------------------
class BrierTracker:
    """Track live Brier scores in SQLite for accuracy measurement.

    Records every probability estimate; when a market resolves, call
    record_resolution() to compute and store the Brier score.
    """

    def __init__(self, db_path: str = "data/brier_tracking.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS estimates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                question TEXT,
                timestamp TEXT NOT NULL,
                model_name TEXT NOT NULL,
                raw_probability REAL NOT NULL,
                calibrated_probability REAL,
                n_models INTEGER DEFAULT 1,
                consensus REAL,
                model_spread REAL,
                search_context_used INTEGER DEFAULT 0,
                category TEXT
            );

            CREATE TABLE IF NOT EXISTS resolutions (
                market_id TEXT PRIMARY KEY,
                outcome INTEGER NOT NULL,  -- 1 = YES, 0 = NO
                resolved_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS brier_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                raw_probability REAL NOT NULL,
                calibrated_probability REAL,
                outcome INTEGER NOT NULL,
                brier_raw REAL NOT NULL,
                brier_calibrated REAL,
                category TEXT,
                computed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_estimates_market ON estimates(market_id);
            CREATE INDEX IF NOT EXISTS idx_brier_model ON brier_scores(model_name);
            CREATE INDEX IF NOT EXISTS idx_brier_category ON brier_scores(category);
        """)
        conn.close()

    def record_estimate(self, market_id: str, question: str,
                        result: EnsembleResult, category: str = ""):
        """Record an ensemble estimate for later Brier scoring."""
        conn = sqlite3.connect(str(self.db_path))
        now = datetime.now(timezone.utc).isoformat()

        # Record ensemble estimate
        conn.execute(
            """INSERT INTO estimates
               (market_id, question, timestamp, model_name,
                raw_probability, calibrated_probability,
                n_models, consensus, model_spread, search_context_used, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (market_id, question, now, "ensemble",
             result.probability, result.calibrated_probability,
             result.n_models, result.consensus, result.model_spread,
             1 if result.search_context_used else 0, category),
        )

        # Record individual model estimates
        for est in result.model_estimates:
            if not est.error:
                conn.execute(
                    """INSERT INTO estimates
                       (market_id, question, timestamp, model_name,
                        raw_probability, calibrated_probability,
                        n_models, consensus, model_spread, search_context_used, category)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (market_id, question, now, est.model_name,
                     est.probability, calibrate_probability(est.probability),
                     1, None, None, 0, category),
                )

        conn.commit()
        conn.close()

    def record_resolution(self, market_id: str, outcome: int):
        """Record market resolution and compute Brier scores.

        outcome: 1 = YES resolved, 0 = NO resolved.
        """
        conn = sqlite3.connect(str(self.db_path))
        now = datetime.now(timezone.utc).isoformat()

        # Store resolution
        conn.execute(
            "INSERT OR REPLACE INTO resolutions (market_id, outcome, resolved_at) VALUES (?, ?, ?)",
            (market_id, outcome, now),
        )

        # Compute Brier for all estimates on this market
        cursor = conn.execute(
            "SELECT model_name, raw_probability, calibrated_probability, category "
            "FROM estimates WHERE market_id = ?",
            (market_id,),
        )

        for row in cursor.fetchall():
            model_name, raw_prob, cal_prob, category = row
            brier_raw = (raw_prob - outcome) ** 2
            brier_cal = (cal_prob - outcome) ** 2 if cal_prob else None

            conn.execute(
                """INSERT INTO brier_scores
                   (market_id, model_name, raw_probability, calibrated_probability,
                    outcome, brier_raw, brier_calibrated, category, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (market_id, model_name, raw_prob, cal_prob,
                 outcome, brier_raw, brier_cal, category, now),
            )

        conn.commit()
        conn.close()

    def get_brier_summary(self) -> dict:
        """Get aggregate Brier scores by model and category."""
        conn = sqlite3.connect(str(self.db_path))

        # Overall by model
        cursor = conn.execute("""
            SELECT model_name,
                   COUNT(*) as n,
                   AVG(brier_raw) as avg_brier_raw,
                   AVG(brier_calibrated) as avg_brier_cal
            FROM brier_scores
            GROUP BY model_name
            ORDER BY avg_brier_raw
        """)
        by_model = [
            {"model": r[0], "n": r[1], "brier_raw": round(r[2], 4),
             "brier_calibrated": round(r[3], 4) if r[3] else None}
            for r in cursor.fetchall()
        ]

        # By category (ensemble only)
        cursor = conn.execute("""
            SELECT category,
                   COUNT(*) as n,
                   AVG(brier_calibrated) as avg_brier_cal
            FROM brier_scores
            WHERE model_name = 'ensemble' AND category IS NOT NULL
            GROUP BY category
            ORDER BY avg_brier_cal
        """)
        by_category = [
            {"category": r[0], "n": r[1], "brier": round(r[2], 4) if r[2] else None}
            for r in cursor.fetchall()
        ]

        # Total estimates recorded
        cursor = conn.execute("SELECT COUNT(DISTINCT market_id) FROM estimates")
        total_markets = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM resolutions")
        total_resolved = cursor.fetchone()[0]

        conn.close()

        return {
            "total_markets_estimated": total_markets,
            "total_resolved": total_resolved,
            "by_model": by_model,
            "by_category": by_category,
        }


# ---------------------------------------------------------------------------
# Main Ensemble Class
# ---------------------------------------------------------------------------
class LLMEnsemble:
    """Multi-model ensemble with agentic RAG for probability estimation.

    Drop-in replacement for single-Claude estimation.
    """

    def __init__(self, enable_rag: bool = True, enable_brier: bool = True):
        self.enable_rag = enable_rag
        self.brier = BrierTracker() if enable_brier else None

        # Detect available models
        self.models = []
        if os.environ.get("ANTHROPIC_API_KEY"):
            self.models.append("claude-haiku")
        if os.environ.get("OPENAI_API_KEY"):
            self.models.append("gpt-4.1-mini")
        if os.environ.get("XAI_API_KEY"):
            self.models.append("grok")
        if os.environ.get("GROQ_API_KEY"):
            self.models.append("groq-llama-3.3-70b")

        logger.info(
            f"LLM Ensemble initialized: {len(self.models)} models available "
            f"({', '.join(self.models) or 'NONE'}), "
            f"RAG={'ON' if enable_rag else 'OFF'}, "
            f"Brier={'ON' if enable_brier else 'OFF'}"
        )

        if not self.models:
            logger.warning("No LLM API keys found! Set ANTHROPIC_API_KEY at minimum.")

    async def estimate(self, question: str, category: str = "",
                       market_id: str = "", timeout: float = 45.0) -> EnsembleResult:
        """Estimate probability of a market question.

        Pipeline:
          1. RAG search (parallel with model calls? No — sequential,
             because context feeds into prompts)
          2. Build prompt with context
          3. Call all models in parallel
          4. Aggregate via trimmed mean
          5. Apply Platt calibration
          6. Record for Brier tracking

        Returns EnsembleResult with calibrated probability.
        """
        # Step 1: Agentic RAG — search for recent context
        search_context = ""
        if self.enable_rag:
            try:
                search_context = await asyncio.wait_for(
                    search_for_context(question),
                    timeout=10.0,
                )
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"RAG search timed out or failed: {e}")

        # Step 2: Build prompt with context
        prompt = build_prompt(question, search_context)

        # Step 3: Call all available models in parallel
        tasks = []
        if "claude-haiku" in self.models:
            tasks.append(call_claude(prompt, timeout=timeout))
        if "gpt-4.1-mini" in self.models:
            tasks.append(call_gpt(prompt, model="gpt-4.1-mini", timeout=timeout))
        if "grok" in self.models:
            tasks.append(call_grok(prompt, timeout=timeout))
        if "groq-llama-3.3-70b" in self.models:
            tasks.append(call_groq(prompt, timeout=timeout))

        if not tasks:
            return EnsembleResult(
                probability=0.5,
                calibrated_probability=0.5,
                confidence="low",
                reasoning="No LLM models available",
                errors=["no_models"],
            )

        estimates: list[ModelEstimate] = await asyncio.gather(*tasks)

        # Step 4: Filter out failures, aggregate
        good_estimates = [e for e in estimates if not e.error]
        errors = [f"{e.model_name}: {e.error}" for e in estimates if e.error]

        if not good_estimates:
            return EnsembleResult(
                probability=0.5,
                calibrated_probability=0.5,
                confidence="low",
                reasoning="All models failed",
                errors=errors,
                model_estimates=estimates,
            )

        # Trimmed mean
        probs = [e.probability for e in good_estimates]
        mean_prob = trimmed_mean(probs)

        # Spread and consensus
        spread = max(probs) - min(probs) if len(probs) > 1 else 0.0
        consensus = compute_consensus(good_estimates)
        models_agree = consensus >= 0.75 and spread < 0.20

        # Confidence
        confidence = confidence_from_spread(spread, consensus)

        # Combined reasoning
        reasonings = [
            f"[{e.model_name}] {e.reasoning}" for e in good_estimates if e.reasoning
        ]
        combined_reasoning = " | ".join(reasonings) if reasonings else ""
        if search_context:
            combined_reasoning = f"[RAG context used] {combined_reasoning}"

        # Step 5: Platt calibration on ensemble mean
        calibrated = calibrate_probability(mean_prob)

        result = EnsembleResult(
            probability=mean_prob,
            calibrated_probability=calibrated,
            confidence=confidence,
            reasoning=combined_reasoning,
            n_models=len(good_estimates),
            model_spread=round(spread, 4),
            consensus=round(consensus, 4),
            models_agree=models_agree,
            search_context_used=bool(search_context),
            model_estimates=good_estimates,
            errors=errors,
        )

        # Step 6: Record for Brier tracking
        if self.brier and market_id:
            try:
                self.brier.record_estimate(market_id, question, result, category)
            except Exception as e:
                logger.debug(f"Brier recording failed: {e}")

        return result

    async def analyze_market(self, question: str, current_price: float = 0.0,
                             market_price: float = 0.0, price: float = 0.0,
                             market_id: str = "", category: str = "") -> dict:
        """Drop-in replacement for ClaudeAnalyzer.analyze_market().

        Returns dict compatible with jj_live.py signal processing.
        """
        result = await self.estimate(
            question=question,
            category=category,
            market_id=market_id,
        )

        return {
            "probability": result.probability,
            "calibrated_probability": result.calibrated_probability,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "n_models": result.n_models,
            "model_spread": result.model_spread,
            "consensus": result.consensus,
            "models_agree": result.models_agree,
            "search_context_used": result.search_context_used,
        }

    def get_brier_summary(self) -> dict:
        """Get aggregate Brier scores."""
        if self.brier:
            return self.brier.get_brier_summary()
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="LLM Ensemble + RAG")
    parser.add_argument("mode", choices=["estimate", "brier", "test"],
                        help="Mode: estimate a question, show Brier stats, or run test")
    parser.add_argument("--question", "-q", type=str,
                        help="Question to estimate (for estimate mode)")
    parser.add_argument("--no-rag", action="store_true",
                        help="Disable web search context")
    args = parser.parse_args()

    if args.mode == "estimate":
        if not args.question:
            print("ERROR: --question required for estimate mode")
            return

        ensemble = LLMEnsemble(enable_rag=not args.no_rag)
        result = await ensemble.estimate(args.question, market_id="cli-test")

        print(f"\n{'='*60}")
        print(f"Question: {args.question}")
        print(f"{'='*60}")
        print(f"Ensemble probability:   {result.probability:.3f}")
        print(f"Calibrated probability: {result.calibrated_probability:.3f}")
        print(f"Confidence:             {result.confidence}")
        print(f"Models used:            {result.n_models}")
        print(f"Model spread:           {result.model_spread:.3f}")
        print(f"Consensus:              {result.consensus:.2f}")
        print(f"Models agree:           {result.models_agree}")
        print(f"RAG context used:       {result.search_context_used}")
        print(f"\nIndividual estimates:")
        for est in result.model_estimates:
            status = f"p={est.probability:.3f}" if not est.error else f"ERROR: {est.error}"
            print(f"  {est.model_name:25s} {status:20s} {est.latency_ms:.0f}ms")
            if est.reasoning:
                print(f"    → {est.reasoning[:100]}")
        if result.errors:
            print(f"\nErrors: {result.errors}")
        print(f"\nReasoning: {result.reasoning[:200]}")

    elif args.mode == "brier":
        tracker = BrierTracker()
        summary = tracker.get_brier_summary()
        print(json.dumps(summary, indent=2))

    elif args.mode == "test":
        # Quick test with a well-known question
        ensemble = LLMEnsemble(enable_rag=True)
        questions = [
            "Will the US GDP grow more than 2% in Q1 2026?",
            "Will it rain in New York City tomorrow?",
        ]
        for q in questions:
            result = await ensemble.estimate(q, market_id=f"test-{hash(q)}")
            print(f"\n{q}")
            print(f"  → {result.calibrated_probability:.3f} "
                  f"(raw={result.probability:.3f}, "
                  f"n={result.n_models}, "
                  f"spread={result.model_spread:.3f}, "
                  f"rag={result.search_context_used})")
            for est in result.model_estimates:
                tag = f"p={est.probability:.3f}" if not est.error else est.error
                print(f"    {est.model_name}: {tag}")


if __name__ == "__main__":
    asyncio.run(main())
