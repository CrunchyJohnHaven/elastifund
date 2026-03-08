#!/usr/bin/env python3
"""Disagreement-derived signal helpers for multi-model probability estimates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping

LOW_STD_CONFIRMATION = 0.05
SIGNAL_STD_THRESHOLD = 0.10
HIGH_STD_UNCERTAINTY = 0.20
REDUCED_SIZE_STD_THRESHOLD = 0.15


def population_stddev(values: list[float]) -> float:
    """Compute the population standard deviation for model estimates."""
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(max(0.0, variance))


def confidence_multiplier_from_std(std_estimate: float, model_count: int) -> float:
    """Map ensemble disagreement to the requested sizing multiplier."""
    if model_count < 2:
        return 1.0
    if std_estimate < LOW_STD_CONFIRMATION:
        return 1.0
    if std_estimate <= REDUCED_SIZE_STD_THRESHOLD:
        return 0.75
    return 0.5


@dataclass(frozen=True)
class DisagreementSignal:
    """Structured output for disagreement-based signal telemetry."""

    signal_fired: bool
    confirmation_signal: bool
    uncertainty_reduction: bool
    std_estimate: float
    mean_estimate: float
    calibrated_mean: float
    market_price: float
    edge: float
    model_count: int
    confidence_multiplier: float
    individual_estimates: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def build_disagreement_signal(
    individual_estimates: Mapping[str, float],
    *,
    calibrated_mean: float,
    market_price: float,
    min_edge: float,
    signal_std_threshold: float = SIGNAL_STD_THRESHOLD,
    confirmation_std_threshold: float = LOW_STD_CONFIRMATION,
    uncertainty_std_threshold: float = HIGH_STD_UNCERTAINTY,
) -> DisagreementSignal:
    """Build the disagreement signal requested in Instance 4."""
    normalized = {
        str(model_name): float(probability)
        for model_name, probability in individual_estimates.items()
    }
    values = list(normalized.values())
    model_count = len(values)
    mean_estimate = sum(values) / model_count if model_count else 0.5
    std_estimate = population_stddev(values)
    edge = abs(float(calibrated_mean) - float(market_price))

    confirmation_signal = model_count >= 2 and std_estimate < confirmation_std_threshold
    signal_fired = model_count >= 2 and std_estimate > signal_std_threshold and edge > min_edge
    uncertainty_reduction = model_count >= 2 and std_estimate > uncertainty_std_threshold

    return DisagreementSignal(
        signal_fired=signal_fired,
        confirmation_signal=confirmation_signal,
        uncertainty_reduction=uncertainty_reduction,
        std_estimate=std_estimate,
        mean_estimate=mean_estimate,
        calibrated_mean=float(calibrated_mean),
        market_price=float(market_price),
        edge=edge,
        model_count=model_count,
        confidence_multiplier=confidence_multiplier_from_std(std_estimate, model_count),
        individual_estimates=normalized,
    )
