"""Strategy 5: profitable wallet convergence momentum."""

from __future__ import annotations

from typing import Any

from .base import BacktestResult, Signal


class WalletFlowMomentumStrategy:
    name = "Wallet Flow Momentum"
    description = "Follow convergence of historically profitable wallets early in market window."

    def __init__(self, min_wallets: int = 3, min_wallet_trades: int = 50):
        self.min_wallets = min_wallets
        self.min_wallet_trades = min_wallet_trades

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
            wallets = int(row.get("wallet_signal_wallets") or 0)
            wallet_trades = int(row.get("wallet_signal_trades") or 0)
            if wallets < self.min_wallets or wallet_trades < self.min_wallet_trades:
                continue

            bias = float(row.get("wallet_up_bias") or 0.0)
            if abs(bias) < 0.08:
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
                    confidence=min(0.97, 0.55 + abs(bias)),
                    edge_estimate=bias,
                    metadata={
                        "wallets": wallets,
                        "wallet_trades": wallet_trades,
                        "wallet_up_bias": bias,
                        "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                        "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                        "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                        "book_imbalance": float(row.get("book_imbalance") or 0.0),
                    },
                )
            )
        return out

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)
