"""Strategy: early informed-flow convergence with stale-price confirmation."""

from __future__ import annotations

import math
from typing import Any

from .base import BacktestResult, Signal


class InformedFlowConvergenceStrategy:
    """Follow early smart-wallet convergence when modeled fair value is still ahead of market."""

    name = "Informed Flow Convergence (Maker-Only)"
    description = (
        "Early 15m wallet convergence + flow-implied fair value lag filter. "
        "Signals are intended for post-only maker execution."
    )

    def __init__(
        self,
        early_window_sec: int = 180,
        min_wallets: int = 3,
        min_wallet_trades: int = 20,
        min_consensus_bias: float = 0.12,
        min_wallet_quality: float = 0.56,
        min_fair_gap: float = 0.05,
        flow_logit_scale: float = 2.4,
        wallet_weight: float = 1.4,
        trade_flow_weight: float = 0.7,
        book_weight: float = 0.4,
        basis_weight: float = 0.3,
    ):
        self.early_window_sec = max(30, early_window_sec)
        self.min_wallets = max(1, min_wallets)
        self.min_wallet_trades = max(1, min_wallet_trades)
        self.min_consensus_bias = max(0.01, min_consensus_bias)
        self.min_wallet_quality = max(0.5, min(0.9, min_wallet_quality))
        self.min_fair_gap = max(0.005, min_fair_gap)
        self.flow_logit_scale = max(0.1, flow_logit_scale)
        self.wallet_weight = wallet_weight
        self.trade_flow_weight = trade_flow_weight
        self.book_weight = book_weight
        self.basis_weight = basis_weight

    @staticmethod
    def _clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _logit(p: float) -> float:
        p = max(1e-6, min(1 - 1e-6, p))
        return math.log(p / (1 - p))

    @staticmethod
    def _sigmoid(x: float) -> float:
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    def _flow_fair_yes_probability(self, row: dict[str, Any]) -> float:
        market_yes = self._clip(float(row.get("yes_price") or 0.5), 0.01, 0.99)
        wallet_bias = self._clip(float(row.get("wallet_up_bias") or 0.0), -1.0, 1.0)
        trade_imb = self._clip(float(row.get("trade_flow_imbalance") or 0.0), -1.0, 1.0)
        book_imb = self._clip(float(row.get("book_imbalance") or 0.0), -1.0, 1.0)
        basis_lag = self._clip(float(row.get("basis_lag_score") or 0.0), -0.8, 0.8)

        wallet_quality = self._clip(float(row.get("wallet_avg_win_rate") or 0.5), 0.5, 0.9)
        quality_multiplier = 1.0 + max(0.0, (wallet_quality - 0.5) * 2.0)

        consensus_strength = self._clip(float(row.get("wallet_consensus_strength") or 0.0), 0.0, 1.5)
        flow_push = 0.0
        flow_push += self.wallet_weight * wallet_bias * quality_multiplier
        flow_push += self.trade_flow_weight * trade_imb
        flow_push += self.book_weight * book_imb
        flow_push += self.basis_weight * basis_lag
        flow_push *= max(0.2, 0.7 + consensus_strength)

        return self._sigmoid(self._logit(market_yes) + self.flow_logit_scale * flow_push)

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

            ts = int(row.get("timestamp_ts") or 0)
            start_ts = int(row.get("window_start_ts") or ts)
            age_sec = max(0, ts - start_ts)
            if age_sec > self.early_window_sec:
                continue

            wallets = int(row.get("wallet_signal_wallets") or 0)
            wallet_trades = int(row.get("wallet_signal_trades") or 0)
            if wallets < self.min_wallets or wallet_trades < self.min_wallet_trades:
                continue

            wallet_bias = float(row.get("wallet_up_bias") or 0.0)
            if abs(wallet_bias) < self.min_consensus_bias:
                continue

            wallet_quality = float(row.get("wallet_avg_win_rate") or 0.5)
            if wallet_quality < self.min_wallet_quality:
                continue
            fallback_used = float(row.get("wallet_signal_fallback") or 0.0) > 0.5

            market_yes = self._clip(float(row.get("yes_price") or 0.5), 0.01, 0.99)
            market_no = self._clip(float(row.get("no_price") or (1.0 - market_yes)), 0.01, 0.99)
            fair_yes = self._flow_fair_yes_probability(row)
            fair_gap = fair_yes - market_yes

            # Require signal direction to match wallet convergence direction.
            if fair_gap * wallet_bias <= 0:
                continue
            if abs(fair_gap) < self.min_fair_gap:
                continue

            side = "YES" if fair_gap > 0 else "NO"
            entry = market_yes if side == "YES" else market_no
            model_prob = fair_yes if side == "YES" else (1.0 - fair_yes)
            model_edge = model_prob - entry
            if model_edge <= 0:
                continue

            confidence = self._clip(
                0.50 + abs(fair_gap) + 0.20 * abs(wallet_bias) + max(0.0, wallet_quality - 0.5),
                0.51,
                0.98,
            )
            if fallback_used:
                confidence = max(0.51, confidence - 0.08)
            out.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id")),
                    timestamp_ts=ts,
                    side=side,
                    entry_price=entry,
                    confidence=confidence,
                    edge_estimate=model_edge,
                    metadata={
                        "execution_style": "maker_only",
                        "post_only": True,
                        "wallets": wallets,
                        "wallet_trades": wallet_trades,
                        "wallet_up_bias": wallet_bias,
                        "wallet_avg_win_rate": wallet_quality,
                        "wallet_consensus_strength": float(row.get("wallet_consensus_strength") or 0.0),
                        "wallet_signal_fallback": fallback_used,
                        "market_yes": market_yes,
                        "fair_yes": fair_yes,
                        "fair_gap": fair_gap,
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                        "signal_age_sec": age_sec,
                        "size_cap_fraction": 1 / 16,
                    },
                )
            )
        return out

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
