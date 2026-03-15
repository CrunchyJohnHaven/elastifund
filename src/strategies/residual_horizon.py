"""Strategy 1: residual horizon fair value mispricing."""

from __future__ import annotations

from typing import Any

from ..models.baseline import ClosedFormInput, closed_form_up_probability
from .base import BacktestResult, Signal


class ResidualHorizonStrategy:
    name = "Residual Horizon Fair Value"
    description = "Closed-form fair probability vs market YES price mispricing."

    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],
        trade_data: list[dict[str, Any]],
        features: list[dict[str, Any]],
    ) -> list[Signal]:
        signals: list[Signal] = []
        for row in features:
            if row.get("timeframe") != "15m":
                continue
            current = float(row.get("btc_price") or 0.0)
            open_price = float(row.get("open_price") or 0.0)
            yes_price = float(row.get("yes_price") or 0.5)
            delta = float(row.get("time_remaining_sec") or 0.0)
            if current <= 0.0 or open_price <= 0.0 or delta <= 1.0:
                continue

            fair = closed_form_up_probability(
                ClosedFormInput(
                    current_price=current,
                    open_price=open_price,
                    mu_per_sec=float(row.get("mu_per_sec") or 0.0),
                    sigma_per_sqrt_sec=float(row.get("sigma_per_sqrt_sec") or 1e-4),
                    time_remaining_sec=delta,
                )
            )

            edge = fair - yes_price
            if abs(edge) < self.threshold:
                continue

            side = "YES" if edge > 0 else "NO"
            entry = yes_price if side == "YES" else float(row.get("no_price") or (1 - yes_price))
            signals.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id")),
                    timestamp_ts=int(row.get("timestamp_ts") or 0),
                    side=side,
                    entry_price=max(0.01, min(0.99, entry)),
                    confidence=min(0.99, 0.5 + abs(edge)),
                    edge_estimate=edge,
                    metadata={
                        "fair_prob": fair,
                        "market_prob": yes_price,
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                    },
                )
            )
        return signals

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
