"""Strategy 3: same-source cross-timeframe constraint violations."""

from __future__ import annotations

from typing import Any

from .base import BacktestResult, Signal


class CrossTimeframeConstraintStrategy:
    name = "Cross-Timeframe Constraint Violation"
    description = "Exploit lagged repricing between resolved inner windows and outer market prices."

    def __init__(self, min_inner_windows: int = 1, threshold: float = 0.08):
        self.min_inner_windows = min_inner_windows
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
            if row.get("timeframe") not in ("15m", "4h"):
                continue

            inner_count = int(row.get("inner_resolved_count") or 0)
            if inner_count < self.min_inner_windows:
                continue

            implied_from_inner = float(row.get("inner_up_bias") or 0.5)
            market_prob = float(row.get("yes_price") or 0.5)
            edge = implied_from_inner - market_prob
            if abs(edge) < self.threshold:
                continue

            side = "YES" if edge > 0 else "NO"
            entry = market_prob if side == "YES" else float(row.get("no_price") or (1 - market_prob))
            signals.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id")),
                    timestamp_ts=int(row.get("timestamp_ts") or 0),
                    side=side,
                    entry_price=max(0.01, min(0.99, entry)),
                    confidence=min(0.95, 0.55 + abs(edge)),
                    edge_estimate=edge,
                    metadata={
                        "inner_count": inner_count,
                        "inner_up_bias": implied_from_inner,
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                    },
                )
            )
        return signals

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
