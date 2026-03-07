"""Strategy 8: order book or trade-flow imbalance."""

from __future__ import annotations

from typing import Any

from .base import BacktestResult, Signal


class BookImbalanceStrategy:
    name = "Order Book / Flow Imbalance"
    description = "Use CLOB depth imbalance, or trade flow imbalance when CLOB is unavailable."

    def __init__(self, imbalance_threshold: float = 0.15):
        self.imbalance_threshold = imbalance_threshold

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
            imbalance = float(row.get("book_imbalance") or row.get("trade_flow_imbalance") or 0.0)
            if abs(imbalance) < self.imbalance_threshold:
                continue

            side = "YES" if imbalance > 0 else "NO"
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
                    confidence=min(0.95, 0.5 + abs(imbalance)),
                    edge_estimate=imbalance,
                    metadata={
                        "imbalance": imbalance,
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                    },
                )
            )
        return out

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
