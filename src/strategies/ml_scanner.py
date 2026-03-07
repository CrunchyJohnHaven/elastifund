"""Strategy 9: ML-driven feature candidate discovery."""

from __future__ import annotations

from dataclasses import dataclass
import statistics
from typing import Any

from ..models.classifiers import GradientBoostClassifier
from .base import BacktestResult, Signal


@dataclass
class FeatureCandidate:
    name: str
    importance: float
    note: str


class MLFeatureDiscoveryStrategy:
    name = "ML Feature Discovery"
    description = "Train boosted classifier and surface high-importance unexplored features."

    def __init__(self, min_rows: int = 150):
        self.min_rows = min_rows

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],
        trade_data: list[dict[str, Any]],
        features: list[dict[str, Any]],
    ) -> list[Signal]:
        # Scanner is primarily for hypothesis discovery, not direct signal production.
        return []

    def discover(self, features: list[dict[str, Any]], known_feature_names: set[str]) -> list[FeatureCandidate]:
        resolved = [row for row in features if row.get("label_up") is not None]
        if len(resolved) < self.min_rows:
            return []

        feature_names = [
            "yes_price",
            "btc_return_since_open",
            "btc_return_60s",
            "realized_vol_30m",
            "realized_vol_1h",
            "realized_vol_2h",
            "trade_count_60s",
            "trade_flow_imbalance",
            "book_imbalance",
            "basis_lag_score",
            "time_remaining_sec",
            "hour_utc",
            "weekday",
            "prev_window_return",
            "inner_up_bias",
            "inner_resolved_count",
        ]
        labels = [int(row["label_up"]) for row in resolved]

        model = GradientBoostClassifier(feature_names)
        model.fit(resolved, labels)
        probs = model.predict_proba(resolved)

        # Lightweight proxy importance: absolute correlation with model output.
        candidates: list[FeatureCandidate] = []
        prob_mean = statistics.mean(probs)
        for name in feature_names:
            values = [float(row.get(name, 0.0)) for row in resolved]
            value_mean = statistics.mean(values)
            numerator = sum((v - value_mean) * (p - prob_mean) for v, p in zip(values, probs, strict=False))
            denom_left = sum((v - value_mean) ** 2 for v in values)
            denom_right = sum((p - prob_mean) ** 2 for p in probs)
            denom = (denom_left * denom_right) ** 0.5
            corr = abs(numerator / denom) if denom > 0 else 0.0
            if corr < 0.05:
                continue
            if name in known_feature_names:
                continue
            candidates.append(
                FeatureCandidate(
                    name=name,
                    importance=min(1.0, corr),
                    note="Model output correlation suggests incremental predictive signal.",
                )
            )

        return sorted(candidates, key=lambda c: c.importance, reverse=True)

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
