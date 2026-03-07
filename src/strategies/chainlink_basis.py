"""Strategy 4: inferred Chainlink-vs-Binance basis lag."""

from __future__ import annotations

from typing import Any

from .base import BacktestResult, Signal


class ChainlinkBasisLagStrategy:
    name = "Chainlink vs Binance Basis Lag"
    description = "Infer lag when market repricing trails Binance move relative to Chainlink resolution behavior."

    def __init__(self, move_threshold: float = 0.0015, lag_threshold: float = 0.06):
        self.move_threshold = move_threshold
        self.lag_threshold = lag_threshold

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
            move = float(row.get("btc_return_60s") or 0.0)
            lag_score = float(row.get("basis_lag_score") or 0.0)
            if abs(move) < self.move_threshold:
                continue
            if abs(lag_score) < self.lag_threshold:
                continue

            side = "YES" if move > 0 else "NO"
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
                    confidence=min(0.98, 0.55 + abs(move) * 10 + abs(lag_score) * 0.3),
                    edge_estimate=lag_score,
                    metadata={
                        "btc_return_60s": move,
                        "basis_lag_score": lag_score,
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
