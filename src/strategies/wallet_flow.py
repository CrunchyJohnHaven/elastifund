"""Strategy 5: profitable wallet convergence momentum."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .base import BacktestResult, Signal


def _maybe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


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

            metadata = {
                "wallets": wallets,
                "wallet_trades": wallet_trades,
                "wallet_up_bias": bias,
                "time_remaining_sec": float(row.get("time_remaining_sec") or 0.0),
                "trade_count_60s": float(row.get("trade_count_60s") or 0.0),
                "trade_flow_imbalance": float(row.get("trade_flow_imbalance") or 0.0),
                "book_imbalance": float(row.get("book_imbalance") or 0.0),
                "wallet_consensus_wallets": _maybe_int(
                    row.get("wallet_consensus_wallets", wallets)
                ),
                "wallet_consensus_notional_usd": _maybe_float(
                    row.get("wallet_consensus_notional_usd")
                ),
                "wallet_consensus_share": _maybe_float(
                    row.get("wallet_consensus_share")
                ),
                "wallet_opposition_wallets": _maybe_int(
                    row.get("wallet_opposition_wallets")
                ),
                "wallet_opposition_notional_usd": _maybe_float(
                    row.get("wallet_opposition_notional_usd")
                ),
                "wallet_signal_age_seconds": _maybe_float(
                    row.get("wallet_signal_age_seconds")
                ),
                "wallet_window_start_ts": row.get("wallet_window_start_ts"),
                "wallet_window_minutes": _maybe_int(
                    row.get("wallet_window_minutes")
                ),
            }

            out.append(
                Signal(
                    strategy=self.name,
                    condition_id=str(row.get("condition_id")),
                    timestamp_ts=int(row.get("timestamp_ts") or 0),
                    side=side,
                    entry_price=max(0.01, min(0.99, entry)),
                    confidence=min(0.97, 0.55 + abs(bias)),
                    edge_estimate=bias,
                    metadata={k: v for k, v in metadata.items() if v is not None},
                )
            )
        return out

    def backtest(self, signals: list[Signal], resolutions: dict[str, str], backtester: Any) -> BacktestResult:
        return backtester.evaluate(self.name, signals, resolutions)


def build_wallet_flow_replay_entry(
    signal: Signal,
    resolution: str,
    market_title: str,
    volume_proxy: float,
    liquidity_proxy: float,
) -> dict[str, Any]:
    """Convert a resolved wallet-flow signal into a stable replay entry."""
    side = str(signal.side).upper()
    direction = "buy_yes" if side == "YES" else "buy_no"
    resolved = str(resolution).upper()
    actual_outcome = "YES_WON" if resolved == "UP" else "NO_WON"
    timestamp = datetime.fromtimestamp(int(signal.timestamp_ts), tz=timezone.utc).isoformat()
    metadata = signal.metadata or {}

    replay_entry = {
        "condition_id": str(signal.condition_id),
        "market_title": str(market_title or signal.condition_id),
        "timestamp": timestamp,
        "timestamp_ts": int(signal.timestamp_ts),
        "side": side,
        "direction": direction,
        "entry_price": float(signal.entry_price),
        "confidence": float(signal.confidence),
        "edge": abs(float(signal.edge_estimate)),
        "win_probability": float(signal.confidence),
        "resolution": resolved,
        "actual_outcome": actual_outcome,
        "timeframe": str(metadata.get("timeframe") or "15m"),
        "wallets": int(metadata.get("wallets") or 0),
        "wallet_trades": int(metadata.get("wallet_trades") or 0),
        "wallet_up_bias": float(metadata.get("wallet_up_bias") or 0.0),
        "trade_flow_imbalance": float(metadata.get("trade_flow_imbalance") or 0.0),
        "book_imbalance": float(metadata.get("book_imbalance") or 0.0),
        "time_remaining_sec": float(metadata.get("time_remaining_sec") or 0.0),
        "volume_proxy": float(volume_proxy),
        "liquidity_proxy": float(liquidity_proxy),
    }
    for key in (
        "wallet_consensus_wallets",
        "wallet_consensus_notional_usd",
        "wallet_consensus_share",
        "wallet_opposition_wallets",
        "wallet_opposition_notional_usd",
        "wallet_signal_age_seconds",
        "wallet_window_start_ts",
        "wallet_window_minutes",
    ):
        value = metadata.get(key)
        if value is not None:
            replay_entry[key] = value
    return replay_entry
