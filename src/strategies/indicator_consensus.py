"""Strategy: trade only when multiple technical indicators agree."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .base import BacktestResult, Signal


class IndicatorConsensusStrategy:
    """Build a market-agnostic directional bias from independent indicator votes."""

    name = "Technical Indicator Consensus"
    description = (
        "Trend, momentum, and mean-reversion indicators must agree strongly enough "
        "to justify a trade, then only the top few edges per timestamp are kept."
    )

    def __init__(
        self,
        *,
        min_consensus: float = 0.72,
        min_edge: float = 0.05,
        min_bias: float = 0.15,
        max_dispersion: float = 0.58,
        max_vol_ratio: float = 1.85,
        probability_scale: float = 0.26,
        top_k_per_timestamp: int = 3,
    ):
        self.min_consensus = max(0.51, min(0.95, min_consensus))
        self.min_edge = max(0.01, min_edge)
        self.min_bias = max(0.02, min_bias)
        self.max_dispersion = max(0.05, max_dispersion)
        self.max_vol_ratio = max(0.5, max_vol_ratio)
        self.probability_scale = max(0.05, min(0.45, probability_scale))
        self.top_k_per_timestamp = max(1, top_k_per_timestamp)

    @staticmethod
    def _clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _indicator_components(self, row: dict[str, Any]) -> list[tuple[str, float, float]]:
        rsi = float(row.get("rsi_14") or 50.0)
        bollinger_z = float(row.get("bollinger_zscore_20") or 0.0)
        flow_confirm = self._clip(
            (float(row.get("trade_flow_imbalance") or 0.0) * 1.8)
            + (float(row.get("book_imbalance") or 0.0) * 1.2),
            -1.0,
            1.0,
        )
        return [
            ("ma_gap_15m", self._clip(float(row.get("ma_gap_15m") or 0.0) * 150.0, -1.0, 1.0), 1.00),
            ("ma_gap_30m", self._clip(float(row.get("ma_gap_30m") or 0.0) * 120.0, -1.0, 1.0), 0.90),
            ("ema_gap_15m", self._clip(float(row.get("ema_gap_15m") or 0.0) * 150.0, -1.0, 1.0), 0.80),
            ("momentum_15m", self._clip(float(row.get("momentum_15m") or 0.0) * 120.0, -1.0, 1.0), 1.00),
            ("momentum_30m", self._clip(float(row.get("momentum_30m") or 0.0) * 90.0, -1.0, 1.0), 0.80),
            ("macd_hist", self._clip(float(row.get("macd_hist") or 0.0) * 350.0, -1.0, 1.0), 1.10),
            ("rsi_14", self._clip((50.0 - rsi) / 20.0, -1.0, 1.0), 0.80),
            ("bollinger", self._clip(-bollinger_z / 2.5, -1.0, 1.0), 0.70),
            ("flow_confirm", flow_confirm, 0.40),
        ]

    def _ranked_signals(self, signals: list[Signal]) -> list[Signal]:
        buckets: dict[int, list[Signal]] = defaultdict(list)
        for signal in signals:
            buckets[int(signal.timestamp_ts)].append(signal)

        out: list[Signal] = []
        for timestamp in sorted(buckets):
            ranked = sorted(
                buckets[timestamp],
                key=lambda signal: (abs(float(signal.edge_estimate)), float(signal.confidence)),
                reverse=True,
            )
            out.extend(ranked[: self.top_k_per_timestamp])
        return out

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],
        trade_data: list[dict[str, Any]],
        features: list[dict[str, Any]],
    ) -> list[Signal]:
        del market_data, price_data, trade_data

        out: list[Signal] = []
        for row in features:
            if row.get("timeframe") != "15m":
                continue

            vol_ratio = float(row.get("vol_ratio_30m_2h") or 0.0)
            rsi = float(row.get("rsi_14") or 50.0)
            if vol_ratio > self.max_vol_ratio:
                continue

            components = self._indicator_components(row)
            total_weight = sum(weight for _, _, weight in components)
            if total_weight <= 0.0:
                continue

            weighted_bias = sum(score * weight for _, score, weight in components) / total_weight
            if abs(weighted_bias) < self.min_bias:
                continue

            positive_weight = sum(weight for _, score, weight in components if score > 0.05)
            negative_weight = sum(weight for _, score, weight in components if score < -0.05)
            consensus = max(positive_weight, negative_weight) / total_weight
            if consensus < self.min_consensus:
                continue

            dispersion = sum(abs(score - weighted_bias) * weight for _, score, weight in components) / total_weight
            if dispersion > self.max_dispersion:
                continue

            market_yes = self._clip(float(row.get("yes_price") or 0.5), 0.01, 0.99)
            market_no = self._clip(float(row.get("no_price") or (1.0 - market_yes)), 0.01, 0.99)
            fair_yes = self._clip(0.5 + (weighted_bias * self.probability_scale), 0.02, 0.98)
            edge = fair_yes - market_yes
            if abs(edge) < self.min_edge or edge * weighted_bias <= 0:
                continue

            side = "YES" if edge > 0 else "NO"
            entry = market_yes if side == "YES" else market_no
            confidence = self._clip(
                0.50 + abs(edge) + (0.18 * consensus) - (0.12 * dispersion),
                0.51,
                0.97,
            )
            component_map = {name: score for name, score, _ in components}

            out.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id") or ""),
                    timestamp_ts=int(row.get("timestamp_ts") or 0),
                    side=side,
                    entry_price=entry,
                    confidence=confidence,
                    edge_estimate=edge,
                    metadata={
                        "fair_yes": fair_yes,
                        "indicator_bias": weighted_bias,
                        "indicator_consensus": consensus,
                        "indicator_dispersion": dispersion,
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                        "rsi_14": rsi,
                        "macd_hist": float(row.get("macd_hist") or 0.0),
                        "bollinger_zscore_20": float(row.get("bollinger_zscore_20") or 0.0),
                        "vol_ratio_30m_2h": vol_ratio,
                        "component_scores": component_map,
                    },
                )
            )

        return self._ranked_signals(out)

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
