"""Strategy 7: time/session pattern exploitation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .base import BacktestResult, Signal


class TimeOfDayPatternStrategy:
    name = "Time-of-Day Session Effect"
    description = "Use recurring session/hour directional biases when statistically meaningful."

    def __init__(self, min_history: int = 20, min_bias: float = 0.08):
        self.min_history = min_history
        self.min_bias = min_bias

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],
        trade_data: list[dict[str, Any]],
        features: list[dict[str, Any]],
    ) -> list[Signal]:
        grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
        for row in features:
            label = row.get("label_up")
            if label is None:
                continue
            grouped[(int(row.get("hour_utc") or 0), int(row.get("weekday") or 0))].append(int(label))

        out: list[Signal] = []
        for row in features:
            if row.get("timeframe") != "15m":
                continue
            key = (int(row.get("hour_utc") or 0), int(row.get("weekday") or 0))
            hist = grouped.get(key, [])
            if len(hist) < self.min_history:
                continue

            up_rate = sum(hist) / len(hist)
            bias = up_rate - 0.5
            if abs(bias) < self.min_bias:
                continue

            side = "YES" if bias > 0 else "NO"
            entry = float(row.get("yes_price") or 0.5)
            if side == "NO":
                entry = float(row.get("no_price") or (1 - entry))

            out.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id")),
                    timestamp_ts=int(row.get("timestamp_ts") or 0),
                    side=side,
                    entry_price=max(0.01, min(0.99, entry)),
                    confidence=min(0.92, 0.5 + abs(bias)),
                    edge_estimate=bias,
                    metadata={
                        "historical_up_rate": up_rate,
                        "sample": len(hist),
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                    },
                )
            )
        return out

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
