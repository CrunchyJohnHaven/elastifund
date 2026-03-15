"""Strategy 2: realized vs implied volatility mismatch."""

from __future__ import annotations

from typing import Any

from ..models.baseline import implied_volatility
from .base import BacktestResult, Signal


class VolatilityRegimeStrategy:
    name = "Volatility Regime Mismatch"
    description = "Signal when realized volatility diverges from implied market volatility."

    def __init__(self, divergence_threshold: float = 1.2):
        self.divergence_threshold = divergence_threshold

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
            market_prob = float(row.get("yes_price") or 0.5)
            realized = float(row.get("realized_vol_1h") or 0.0)
            if realized <= 0.0:
                continue

            implied = implied_volatility(
                market_prob=market_prob,
                current_price=float(row.get("btc_price") or 0.0),
                open_price=float(row.get("open_price") or 0.0),
                mu_per_sec=float(row.get("mu_per_sec") or 0.0),
                time_remaining_sec=float(row.get("time_remaining_sec") or 60.0),
            )
            if implied <= 0.0:
                continue

            ratio = realized / implied
            edge = ratio - 1.0
            if ratio > self.divergence_threshold:
                side = "YES" if float(row.get("btc_return_since_open") or 0.0) >= 0.0 else "NO"
            elif ratio < (1.0 / self.divergence_threshold):
                side = "NO" if float(row.get("btc_return_since_open") or 0.0) >= 0.0 else "YES"
            else:
                continue

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
                    confidence=min(0.95, 0.5 + abs(edge) * 0.25),
                    edge_estimate=edge,
                    metadata={
                        "implied_vol": implied,
                        "realized_vol": realized,
                        "ratio": ratio,
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
