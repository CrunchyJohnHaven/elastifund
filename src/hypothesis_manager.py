"""Hypothesis scoring, lifecycle management, and rejection discipline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import ResearchConfig
from .strategies.base import BacktestResult


@dataclass
class HypothesisEvaluation:
    key: str
    name: str
    status: str
    confidence: float
    score: float
    rejection_reasons: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class HypothesisManager:
    """Apply weighted scoring and strict kill rules to hypothesis results."""

    def __init__(self, research_cfg: ResearchConfig):
        self.research_cfg = research_cfg

    def evaluate(
        self,
        key: str,
        name: str,
        result: BacktestResult,
        stress: dict[str, float],
        simplicity: float,
        perturbation_stability: float,
    ) -> HypothesisEvaluation:
        rejection_reasons: list[str] = []
        failure_modes: list[str] = []

        if result.signals < 50:
            rejection_reasons.append("Too few signals (<50)")
        if result.ev_taker < 0:
            rejection_reasons.append("Negative out-of-sample expectancy")
        if stress.get("cost_up", 0.0) < 0:
            rejection_reasons.append("Collapses under worse cost assumptions")
        if result.calibration_error > 0.20:
            rejection_reasons.append("Poor calibration")
        if perturbation_stability < 0.4:
            rejection_reasons.append("Unstable under parameter perturbation")
        if result.regime_decay:
            rejection_reasons.append("Monotonic or recent performance decay")

        if result.signals < self.research_cfg.min_signals_candidate:
            failure_modes.append("Insufficient sample for candidate status")

        if result.ev_taker <= 0:
            failure_modes.append("No positive expectancy after realistic costs")
        if result.calibration_error > 0.15:
            failure_modes.append("Probability calibration drift")

        if rejection_reasons:
            status = "rejected"
        elif (
            result.signals >= self.research_cfg.min_signals_validated
            and result.p_value < 0.01
            and result.ev_taker > 0
            and stress.get("cost_up", 0.0) > 0
            and perturbation_stability >= 0.6
        ):
            status = "promoted"
        elif result.signals >= self.research_cfg.min_signals_candidate and result.p_value < 0.05 and result.ev_taker > 0:
            status = "active"
        else:
            status = "active"
            failure_modes.append("Under investigation: criteria not yet met")

        score = self._composite_score(result, stress, simplicity, perturbation_stability)
        confidence = self._confidence(result, status)

        return HypothesisEvaluation(
            key=key,
            name=name,
            status=status,
            confidence=confidence,
            score=score,
            rejection_reasons=rejection_reasons,
            failure_modes=failure_modes,
            metrics={
                "signals": result.signals,
                "win_rate": result.win_rate,
                "ev_maker": result.ev_maker,
                "ev_taker": result.ev_taker,
                "p_value": result.p_value,
                "calibration_error": result.calibration_error,
                "sharpe": result.sharpe,
                "max_drawdown": result.max_drawdown,
                "wilson_low": result.wilson_low,
                "wilson_high": result.wilson_high,
                "stress": stress,
                "kelly_fraction": result.kelly_fraction,
            },
        )

    @staticmethod
    def _confidence(result: BacktestResult, status: str) -> float:
        base = 0.3
        base += min(0.3, result.signals / 1000)
        base += min(0.2, max(result.ev_taker, 0) / 20)
        base += 0.1 if result.p_value < 0.05 else 0.0
        if status == "promoted":
            base += 0.1
        if status == "rejected":
            base = min(base, 0.4)
        return max(0.05, min(0.99, base))

    @staticmethod
    def _composite_score(
        result: BacktestResult,
        stress: dict[str, float],
        simplicity: float,
        perturbation_stability: float,
    ) -> float:
        # Weighted score per project brief.
        expectancy = max(-20.0, min(20.0, result.ev_taker)) / 20.0
        robustness_time = 0.0 if result.regime_decay else 1.0
        robustness_vol = max(0.0, 1.0 - min(result.calibration_error, 1.0))

        base = stress.get("base", 0.0)
        cost_up = stress.get("cost_up", 0.0)
        degradation = 1.0
        if base != 0:
            degradation = max(0.0, min(1.0, 1.0 - max(0.0, (base - cost_up) / abs(base))))

        speed = min(1.0, result.signals / 300)

        score = 0.30 * expectancy
        score += 0.20 * robustness_time
        score += 0.15 * robustness_vol
        score += 0.15 * degradation
        score += 0.10 * simplicity
        score += 0.05 * speed
        score += 0.05 * max(0.0, min(1.0, perturbation_stability))
        return score

    @staticmethod
    def rank(evaluations: list[HypothesisEvaluation]) -> list[HypothesisEvaluation]:
        return sorted(evaluations, key=lambda item: item.score, reverse=True)

    @staticmethod
    def recommendation(ranked: list[HypothesisEvaluation]) -> tuple[str, str]:
        if not ranked:
            return "REJECT ALL", "No hypothesis has enough evidence to justify deployment."

        best = ranked[0]
        if best.status == "rejected":
            return "REJECT ALL", "All active hypotheses failed kill rules or expectancy tests."

        if best.status == "promoted":
            return f"TINY LIVE TEST {best.name}", "Promoted hypothesis meets statistical and robustness thresholds."

        if best.metrics.get("signals", 0) >= 100 and best.metrics.get("p_value", 1.0) < 0.05:
            return f"PAPER TRADE {best.name}", "Top hypothesis is positive OOS but not yet validated for tiny-live promotion."

        return "CONTINUE RESEARCH", "Current evidence is not strong enough for deployment decisions."
