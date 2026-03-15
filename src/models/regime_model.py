"""Simple hidden-regime approximation for volatility state detection."""

from __future__ import annotations

from dataclasses import dataclass
import statistics


@dataclass
class RegimeState:
    name: str
    sigma: float


class TwoStateRegimeModel:
    """Threshold-based high/low volatility regime model."""

    def __init__(self) -> None:
        self.low_sigma: float = 0.0
        self.high_sigma: float = 0.0
        self.threshold: float = 0.0

    def fit(self, realized_vols: list[float]) -> None:
        if not realized_vols:
            self.low_sigma = 1e-4
            self.high_sigma = 2e-4
            self.threshold = 1.5e-4
            return

        clean = sorted(v for v in realized_vols if v > 0.0)
        if not clean:
            clean = [1e-4, 2e-4]

        self.threshold = statistics.median(clean)
        low = [v for v in clean if v <= self.threshold]
        high = [v for v in clean if v > self.threshold]

        self.low_sigma = statistics.mean(low) if low else self.threshold
        self.high_sigma = statistics.mean(high) if high else max(self.threshold * 1.5, self.low_sigma)

    def predict_state(self, realized_vol: float) -> RegimeState:
        if realized_vol >= self.threshold:
            return RegimeState(name="high_vol", sigma=max(self.high_sigma, 1e-8))
        return RegimeState(name="low_vol", sigma=max(self.low_sigma, 1e-8))

    def transition_probs(self) -> dict[str, float]:
        """Static transition approximation for downstream MC parameterization."""
        return {
            "p_low_to_high": 0.05,
            "p_high_to_low": 0.10,
        }
