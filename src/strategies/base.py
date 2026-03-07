"""Strategy base interfaces and signal/result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Signal:
    strategy: str
    condition_id: str
    timestamp_ts: int
    side: str  # YES or NO
    entry_price: float
    confidence: float
    edge_estimate: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    strategy: str
    signals: int
    wins: int
    win_rate: float
    ev_maker: float
    ev_taker: float
    sharpe: float
    max_drawdown: float
    p_value: float
    calibration_error: float
    regime_decay: bool
    kelly_fraction: float
    wilson_low: float
    wilson_high: float
    notes: list[str] = field(default_factory=list)


class Strategy(Protocol):
    """Required strategy interface."""

    name: str
    description: str

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],
        trade_data: list[dict[str, Any]],
        features: list[dict[str, Any]],
    ) -> list[Signal]:
        """Produce timestamped signals using the shared data inputs."""

    def backtest(
        self,
        signals: list[Signal],
        resolutions: dict[str, str],
        backtester: Any,
    ) -> BacktestResult:
        """Delegate scoring to the backtesting engine."""
