"""Strategy 6: mean reversion after extreme prior-window moves."""

from __future__ import annotations

from typing import Any

from .base import BacktestResult, Signal


class MeanReversionStrategy:
    name = "Post-Extreme Mean Reversion"
    description = "Fade next-window directional continuation after large previous move."

    def __init__(self, thresholds: list[float] | None = None):
        self.thresholds = thresholds or [0.002, 0.003, 0.005, 0.01]

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],
        trade_data: list[dict[str, Any]],
        features: list[dict[str, Any]],
    ) -> list[Signal]:
        out: list[Signal] = []
        for row in features:
            if row.get("timeframe") != "15m":
                continue
            prev_move = float(row.get("prev_window_return") or 0.0)
            threshold = next((t for t in sorted(self.thresholds) if abs(prev_move) >= t), None)
            if threshold is None:
                continue

            side = "NO" if prev_move > 0 else "YES"
            entry = float(row.get("yes_price") or 0.5)
            if side == "NO":
                entry = float(row.get("no_price") or (1 - entry))

            edge = min(0.2, abs(prev_move) * 12)
            out.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id")),
                    timestamp_ts=int(row.get("timestamp_ts") or 0),
                    side=side,
                    entry_price=max(0.01, min(0.99, entry)),
                    confidence=min(0.95, 0.52 + edge),
                    edge_estimate=edge,
                    metadata={
                        "prev_window_return": prev_move,
                        "threshold": threshold,
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
