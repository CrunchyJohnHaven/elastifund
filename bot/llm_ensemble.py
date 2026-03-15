#!/usr/bin/env python3
"""Compatibility shim for the canonical JJ ensemble runtime.

`bot.ensemble_estimator` is the only runtime implementation used by the live
loop. This module keeps the legacy helper surface, Brier tracker, and CLI so
older utilities and tests can continue to import `llm_ensemble` without
carrying a second live ensemble implementation.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Optional

try:
    from bot.disagreement_signal import population_stddev
    from bot.ensemble_estimator import EnsembleEstimator, calibrate_probability
except ImportError:
    from disagreement_signal import population_stddev  # type: ignore
    from ensemble_estimator import EnsembleEstimator, calibrate_probability  # type: ignore

logger = logging.getLogger("JJ.ensemble.compat")

DISAGREEMENT_LOW_STD = float(os.environ.get("JJ_DISAGREEMENT_LOW_STD", "0.05"))
DISAGREEMENT_HIGH_STD = float(os.environ.get("JJ_DISAGREEMENT_HIGH_STD", "0.15"))
DISAGREEMENT_MIN_KELLY = float(os.environ.get("JJ_DISAGREEMENT_MIN_KELLY", f"{1.0 / 32.0:.5f}"))
DISAGREEMENT_MAX_KELLY = float(os.environ.get("JJ_DISAGREEMENT_MAX_KELLY", "0.25"))
SINGLE_MODEL_DISAGREEMENT = 0.20

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
    """Build the legacy prompt format used by compatibility callers."""
    context_section = ""
    if search_context:
        context_section = (
            "RECENT CONTEXT (from web search, may help inform your estimate):\n"
            f"{search_context}\n"
        )
    return BASE_PROMPT.format(question=question, context_section=context_section)


@dataclass
class ModelEstimate:
    """Legacy single-model estimate shape."""

    model_name: str
    probability: float
    confidence: str
    reasoning: str
    latency_ms: float = 0.0
    error: str = ""

    @classmethod
    def from_runtime(cls, estimate: Any) -> "ModelEstimate":
        probability = getattr(estimate, "raw_probability", None)
        if probability is None:
            probability = getattr(estimate, "probability", 0.5)
        return cls(
            model_name=str(getattr(estimate, "model_name", "unknown")),
            probability=float(probability),
            confidence=str(getattr(estimate, "confidence", "medium") or "medium"),
            reasoning=str(getattr(estimate, "reasoning", "") or ""),
            latency_ms=float(getattr(estimate, "latency_ms", 0.0) or 0.0),
            error=str(getattr(estimate, "error", "") or ""),
        )


def parse_llm_response(text: str, model_name: str) -> ModelEstimate:
    """Parse the legacy PROBABILITY/CONFIDENCE/REASONING response format."""
    probability = None
    confidence = "medium"
    reasoning = ""

    for line in text.strip().splitlines():
        normalized = line.strip()
        upper = normalized.upper()

        if upper.startswith("PROBABILITY:"):
            value = normalized.split(":", 1)[1].strip()
            value = re.sub(r"[()%]", "", value).strip().split()[0]
            try:
                probability = float(value)
                if probability > 1.0:
                    probability /= 100.0
                probability = max(0.01, min(0.99, probability))
            except (ValueError, IndexError):
                probability = None
        elif upper.startswith("CONFIDENCE:"):
            value = normalized.split(":", 1)[1].strip().lower()
            if "high" in value:
                confidence = "high"
            elif "low" in value:
                confidence = "low"
            else:
                confidence = "medium"
        elif upper.startswith("REASONING:"):
            reasoning = normalized.split(":", 1)[1].strip()

    if probability is None:
        for match in re.findall(r"0\.\d+", text):
            candidate = float(match)
            if 0.01 <= candidate <= 0.99:
                probability = candidate
                break

    if probability is None:
        return ModelEstimate(
            model_name=model_name,
            probability=0.5,
            confidence="low",
            reasoning="Failed to parse probability",
            error="parse_failure",
        )

    return ModelEstimate(
        model_name=model_name,
        probability=probability,
        confidence=confidence,
        reasoning=reasoning,
    )


@dataclass
class EnsembleResult:
    """Legacy aggregate estimate shape."""

    probability: float
    calibrated_probability: float
    confidence: str
    reasoning: str
    n_models: int = 0
    model_spread: float = 0.0
    model_stddev: float = 0.0
    disagreement: float = 0.0
    consensus: float = 0.0
    agreement: float = 0.0
    kelly_multiplier: float = 1.0
    disagreement_kelly_fraction: float = DISAGREEMENT_MAX_KELLY
    models_agree: bool = False
    search_context_used: bool = False
    counter_probability: Optional[float] = None
    counter_shift: float = 0.0
    counter_fragile: bool = False
    model_estimates: list[ModelEstimate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["model_estimates"] = [asdict(estimate) for estimate in self.model_estimates]
        return payload


def trimmed_mean(values: list[float]) -> float:
    """Drop the highest and lowest estimate when 3+ models are present."""
    if not values:
        return 0.5
    if len(values) <= 2:
        return sum(values) / len(values)
    ordered = sorted(values)
    trimmed = ordered[1:-1]
    return sum(trimmed) / len(trimmed)


def compute_stddev(values: list[float]) -> float:
    """Population stddev for explicit model disagreement."""
    if len(values) < 2:
        return 0.0
    return float(population_stddev([float(value) for value in values]))


def compute_disagreement(values: list[float]) -> float:
    """Legacy single-model pessimistic disagreement fallback."""
    if not values:
        return 0.0
    if len(values) == 1:
        return SINGLE_MODEL_DISAGREEMENT
    return compute_stddev(values)


def aggregate_probability_stats(values: list[float]) -> tuple[float, float]:
    """Return trimmed mean plus explicit stddev."""
    if not values:
        return 0.5, 0.0
    return trimmed_mean(values), compute_stddev(values)


def compute_consensus(estimates: list[ModelEstimate]) -> float:
    """Fraction of models agreeing on YES vs NO."""
    if not estimates:
        return 0.0
    yes_count = sum(1 for estimate in estimates if estimate.probability > 0.5)
    no_count = sum(1 for estimate in estimates if estimate.probability < 0.5)
    return max(yes_count, no_count) / len(estimates)


def confidence_from_spread(spread: float, consensus: float) -> str:
    """Map spread and consensus to the legacy confidence label."""
    if spread < 0.10 and consensus >= 0.9:
        return "high"
    if spread < 0.20 and consensus >= 0.75:
        return "medium"
    return "low"


def compute_agreement_score(spread: float, consensus: float) -> float:
    """Convert spread plus direction consensus into a 0-1 score."""
    spread = max(0.0, min(1.0, float(spread)))
    consensus = max(0.0, min(1.0, float(consensus)))
    spread_component = 1.0 - min(1.0, spread / 0.25)
    return max(0.0, min(1.0, spread_component * consensus))


def kelly_multiplier_from_agreement(agreement: float) -> float:
    """Map agreement score to the historical multiplier curve."""
    agreement = max(0.0, min(1.0, float(agreement)))
    return max(0.25, min(1.5, 0.25 + 1.25 * agreement))


def disagreement_kelly_modifier(std_dev: float) -> float:
    """Legacy disagreement lookup table kept for backtests and tests."""
    std_dev = max(0.0, float(std_dev))
    if std_dev < 0.05:
        return 1.0
    if std_dev < 0.10:
        return 0.75
    if std_dev < 0.15:
        return 0.50
    return 0.25


def kelly_fraction_from_stddev(stddev: float) -> float:
    """Map ensemble stddev to an absolute Kelly cap."""
    stddev = max(0.0, float(stddev))
    if stddev <= DISAGREEMENT_LOW_STD:
        return DISAGREEMENT_MAX_KELLY
    if stddev >= DISAGREEMENT_HIGH_STD:
        return DISAGREEMENT_MIN_KELLY
    fraction = (stddev - DISAGREEMENT_LOW_STD) / (DISAGREEMENT_HIGH_STD - DISAGREEMENT_LOW_STD)
    return DISAGREEMENT_MAX_KELLY - fraction * (DISAGREEMENT_MAX_KELLY - DISAGREEMENT_MIN_KELLY)


def kelly_multiplier_from_stddev(stddev: float) -> float:
    """Normalize the Kelly cap relative to the default quarter-Kelly max."""
    return max(
        0.0,
        min(1.0, kelly_fraction_from_stddev(stddev) / max(DISAGREEMENT_MAX_KELLY, 1e-9)),
    )


class BrierTracker:
    """Track and summarize historical Brier scores for ensemble outputs."""

    def __init__(self, db_path: str = "data/brier_tracking.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(
            """
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
                outcome INTEGER NOT NULL,
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
            """
        )
        conn.close()

    def record_estimate(self, market_id: str, question: str, result: EnsembleResult, category: str = "") -> None:
        """Record an estimate for future Brier scoring."""
        conn = sqlite3.connect(str(self.db_path))
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO estimates (
                market_id,
                question,
                timestamp,
                model_name,
                raw_probability,
                calibrated_probability,
                n_models,
                consensus,
                model_spread,
                search_context_used,
                category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market_id,
                question,
                now,
                "ensemble",
                result.probability,
                result.calibrated_probability,
                result.n_models,
                result.consensus,
                result.model_spread,
                1 if result.search_context_used else 0,
                category,
            ),
        )

        for estimate in result.model_estimates:
            if estimate.error:
                continue
            conn.execute(
                """
                INSERT INTO estimates (
                    market_id,
                    question,
                    timestamp,
                    model_name,
                    raw_probability,
                    calibrated_probability,
                    n_models,
                    consensus,
                    model_spread,
                    search_context_used,
                    category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    question,
                    now,
                    estimate.model_name,
                    estimate.probability,
                    calibrate_probability(estimate.probability),
                    1,
                    None,
                    None,
                    0,
                    category,
                ),
            )

        conn.commit()
        conn.close()

    def record_resolution(self, market_id: str, outcome: int) -> None:
        """Record a market outcome and materialize Brier scores."""
        conn = sqlite3.connect(str(self.db_path))
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT OR REPLACE INTO resolutions (market_id, outcome, resolved_at) VALUES (?, ?, ?)",
            (market_id, outcome, now),
        )

        rows = conn.execute(
            """
            SELECT model_name, raw_probability, calibrated_probability, category
            FROM estimates
            WHERE market_id = ?
            """,
            (market_id,),
        ).fetchall()

        for model_name, raw_probability, calibrated_probability, category in rows:
            brier_raw = (raw_probability - outcome) ** 2
            brier_calibrated = (calibrated_probability - outcome) ** 2 if calibrated_probability else None
            conn.execute(
                """
                INSERT INTO brier_scores (
                    market_id,
                    model_name,
                    raw_probability,
                    calibrated_probability,
                    outcome,
                    brier_raw,
                    brier_calibrated,
                    category,
                    computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    model_name,
                    raw_probability,
                    calibrated_probability,
                    outcome,
                    brier_raw,
                    brier_calibrated,
                    category,
                    now,
                ),
            )

        conn.commit()
        conn.close()

    def get_brier_summary(self) -> dict:
        """Summarize Brier scores by model and category."""
        conn = sqlite3.connect(str(self.db_path))

        by_model_rows = conn.execute(
            """
            SELECT model_name, COUNT(*) as n, AVG(brier_raw) as avg_brier_raw, AVG(brier_calibrated) as avg_brier_cal
            FROM brier_scores
            GROUP BY model_name
            ORDER BY avg_brier_raw
            """
        ).fetchall()
        by_model = [
            {
                "model": row[0],
                "n": row[1],
                "brier_raw": round(row[2], 4),
                "brier_calibrated": round(row[3], 4) if row[3] else None,
            }
            for row in by_model_rows
        ]

        by_category_rows = conn.execute(
            """
            SELECT category, COUNT(*) as n, AVG(brier_calibrated) as avg_brier_cal
            FROM brier_scores
            WHERE model_name = 'ensemble' AND category IS NOT NULL
            GROUP BY category
            ORDER BY avg_brier_cal
            """
        ).fetchall()
        by_category = [
            {
                "category": row[0],
                "n": row[1],
                "brier": round(row[2], 4) if row[2] else None,
            }
            for row in by_category_rows
        ]

        total_markets_estimated = conn.execute("SELECT COUNT(DISTINCT market_id) FROM estimates").fetchone()[0]
        total_resolved = conn.execute("SELECT COUNT(*) FROM resolutions").fetchone()[0]
        conn.close()

        return {
            "total_markets_estimated": total_markets_estimated,
            "total_resolved": total_resolved,
            "by_model": by_model,
            "by_category": by_category,
        }


class LLMEnsemble:
    """Deprecated wrapper that delegates live estimation to EnsembleEstimator."""

    def __init__(
        self,
        enable_rag: bool = True,
        enable_brier: bool = True,
        enable_counter_narrative: Optional[bool] = None,
        counter_shift_threshold: Optional[float] = None,
    ):
        self.enable_rag = enable_rag
        self.enable_counter_narrative = enable_counter_narrative
        self.counter_shift_threshold = (
            float(counter_shift_threshold)
            if counter_shift_threshold is not None
            else float(os.environ.get("JJ_COUNTER_NARRATIVE_MAX_SHIFT", "0.15"))
        )
        self.brier = BrierTracker() if enable_brier else None
        self.estimator = EnsembleEstimator()
        models = getattr(self.estimator, "models", [])
        self.models = list(models) if isinstance(models, (list, tuple)) else []

    @staticmethod
    def _compat_result_from_runtime(result: Any) -> EnsembleResult:
        model_estimates = [ModelEstimate.from_runtime(estimate) for estimate in getattr(result, "model_estimates", [])]
        consensus = compute_consensus(model_estimates)
        spread = float(getattr(result, "range_estimate", 0.0) or 0.0)
        stddev = float(getattr(result, "std_estimate", 0.0) or 0.0)
        confidence_multiplier = float(getattr(result, "confidence_multiplier", 1.0) or 1.0)
        disagreement_signal = getattr(result, "disagreement_signal", {}) or {}
        return EnsembleResult(
            probability=float(getattr(result, "mean_estimate", 0.5) or 0.5),
            calibrated_probability=float(getattr(result, "calibrated_mean", 0.5) or 0.5),
            confidence=str(getattr(result, "confidence", "low") or "low"),
            reasoning=str(getattr(result, "reasoning", "") or ""),
            n_models=len(model_estimates),
            model_spread=spread,
            model_stddev=stddev,
            disagreement=stddev if model_estimates else 0.0,
            consensus=consensus,
            agreement=compute_agreement_score(spread, consensus),
            kelly_multiplier=confidence_multiplier,
            disagreement_kelly_fraction=min(
                DISAGREEMENT_MAX_KELLY,
                max(0.0, DISAGREEMENT_MAX_KELLY * confidence_multiplier),
            ),
            models_agree=bool(disagreement_signal.get("confirmation_signal", False)),
            search_context_used=False,
            counter_probability=None,
            counter_shift=0.0,
            counter_fragile=False,
            model_estimates=model_estimates,
            errors=list(getattr(result, "errors", []) or []),
        )

    async def estimate(
        self,
        question: str,
        category: str = "",
        market_id: str = "",
        timeout: float = 45.0,
    ) -> EnsembleResult:
        """Delegate estimation to the canonical runtime surface."""
        self.estimator.timeout_seconds = float(timeout)
        runtime_result = await self.estimator.estimate(
            question,
            market_price=0.0,
            category=category,
            market_id=market_id,
            context="",
            news_section="",
        )
        compat_result = self._compat_result_from_runtime(runtime_result)
        if self.brier and market_id:
            try:
                self.brier.record_estimate(market_id, question, compat_result, category)
            except Exception as exc:
                logger.debug("Brier recording failed: %s", exc)
        return compat_result

    async def analyze_market(
        self,
        question: str,
        current_price: float = 0.0,
        market_price: float = 0.0,
        price: float = 0.0,
        market_id: str = "",
        category: str = "",
        context: str = "",
        news_section: str = "",
    ) -> dict:
        """Return the legacy dict shape backed by EnsembleEstimator."""
        resolved_price = current_price if current_price != 0.0 else market_price if market_price != 0.0 else price
        runtime_result = await self.estimator.estimate(
            question,
            market_price=float(resolved_price),
            category=category,
            market_id=market_id,
            context=context,
            news_section=news_section,
        )
        compat_result = self._compat_result_from_runtime(runtime_result)
        if self.brier and market_id:
            try:
                self.brier.record_estimate(market_id, question, compat_result, category)
            except Exception as exc:
                logger.debug("Brier recording failed: %s", exc)

        disagreement_signal = getattr(runtime_result, "disagreement_signal", {}) or {}
        return {
            "probability": compat_result.probability,
            "calibrated_probability": compat_result.calibrated_probability,
            "confidence": compat_result.confidence,
            "reasoning": compat_result.reasoning,
            "n_models": compat_result.n_models,
            "model_spread": compat_result.model_spread,
            "model_stddev": compat_result.model_stddev,
            "disagreement": compat_result.disagreement,
            "consensus": compat_result.consensus,
            "agreement": compat_result.agreement,
            "kelly_multiplier": compat_result.kelly_multiplier,
            "disagreement_kelly_fraction": compat_result.disagreement_kelly_fraction,
            "models_agree": compat_result.models_agree,
            "search_context_used": compat_result.search_context_used,
            "counter_probability": compat_result.counter_probability,
            "counter_shift": compat_result.counter_shift,
            "counter_fragile": compat_result.counter_fragile,
            "disagreement_signal": disagreement_signal.get("signal_fired", False),
            "confirmation_signal": disagreement_signal.get("confirmation_signal", False),
            "uncertainty_reduction": disagreement_signal.get("uncertainty_reduction", False),
            "confidence_multiplier": getattr(runtime_result, "confidence_multiplier", 1.0),
            "individual_model_estimates": {
                estimate.model_name: estimate.probability for estimate in compat_result.model_estimates
            },
            "model_estimates": [asdict(estimate) for estimate in compat_result.model_estimates],
            "ensemble_call_cost_usd": getattr(runtime_result, "call_cost_usd", 0.0),
            "ensemble_daily_cost_usd": getattr(runtime_result, "daily_cost_usd", 0.0),
            "cost_cap_triggered": getattr(runtime_result, "cost_cap_triggered", False),
            "fallback_mode": getattr(runtime_result, "fallback_mode", "ensemble"),
            "errors": compat_result.errors,
        }

    def get_brier_summary(self) -> dict:
        """Expose aggregate Brier stats for callers that still use this shim."""
        if self.brier:
            return self.brier.get_brier_summary()
        return {}


async def main() -> None:
    """Small CLI maintained for ad hoc local checks."""
    parser = argparse.ArgumentParser(description="Legacy llm_ensemble compatibility CLI")
    parser.add_argument("mode", choices=["estimate", "brier"], help="Estimate a question or print Brier summary")
    parser.add_argument("--question", "-q", type=str, help="Question to estimate")
    parser.add_argument("--price", type=float, default=0.0, help="Optional market price for analyze_market mode")
    args = parser.parse_args()

    if args.mode == "estimate":
        if not args.question:
            raise SystemExit("--question is required for estimate mode")
        ensemble = LLMEnsemble()
        result = await ensemble.analyze_market(
            question=args.question,
            current_price=args.price,
            market_id="compat-cli",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    print(json.dumps(BrierTracker().get_brier_summary(), indent=2, sort_keys=True))


__all__ = [
    "BrierTracker",
    "EnsembleResult",
    "LLMEnsemble",
    "ModelEstimate",
    "aggregate_probability_stats",
    "build_prompt",
    "calibrate_probability",
    "compute_agreement_score",
    "compute_consensus",
    "compute_disagreement",
    "compute_stddev",
    "confidence_from_spread",
    "disagreement_kelly_modifier",
    "kelly_fraction_from_stddev",
    "kelly_multiplier_from_agreement",
    "kelly_multiplier_from_stddev",
    "trimmed_mean",
]


if __name__ == "__main__":
    asyncio.run(main())
