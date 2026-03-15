"""Registry of edge hypotheses and strategy constructors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import AppConfig
from .strategies import (
    BookImbalanceStrategy,
    ChainlinkBasisLagStrategy,
    CrossTimeframeConstraintStrategy,
    IndicatorConsensusStrategy,
    InformedFlowConvergenceStrategy,
    MeanReversionStrategy,
    ResidualHorizonStrategy,
    TimeOfDayPatternStrategy,
    VolatilityRegimeStrategy,
    WalletFlowMomentumStrategy,
)


@dataclass
class EdgeHypothesis:
    key: str
    name: str
    intuition: str
    features_used: list[str]
    simulation_method: str
    constructor: Callable[[], Any]
    simplicity: float


def build_registry(config: AppConfig) -> list[EdgeHypothesis]:
    return [
        EdgeHypothesis(
            key="residual_horizon",
            name="Residual Horizon Fair Value",
            intuition="Closed-form fair probability should dominate when market lags true state.",
            features_used=["btc_return_since_open", "realized_vol_2h", "time_remaining_sec", "yes_price"],
            simulation_method="Closed-form normal CDF",
            constructor=lambda: ResidualHorizonStrategy(threshold=config.backtest.edge_thresholds[1]),
            simplicity=1.0,
        ),
        EdgeHypothesis(
            key="vol_regime",
            name="Volatility Regime Mismatch",
            intuition="If realized vol diverges from implied vol, binary prices may be miscalibrated.",
            features_used=["realized_vol_1h", "yes_price", "btc_return_since_open"],
            simulation_method="Implied-vol inversion",
            constructor=lambda: VolatilityRegimeStrategy(),
            simplicity=0.8,
        ),
        EdgeHypothesis(
            key="cross_timeframe",
            name="Cross-Timeframe Constraint Violation",
            intuition="Resolved inner windows constrain outer window probability before repricing completes.",
            features_used=["inner_resolved_count", "inner_up_bias", "yes_price"],
            simulation_method="Constraint propagation",
            constructor=lambda: CrossTimeframeConstraintStrategy(),
            simplicity=0.75,
        ),
        EdgeHypothesis(
            key="chainlink_basis",
            name="Chainlink vs Binance Basis Lag",
            intuition="Discrete Chainlink updates can lag continuous Binance moves and distort pricing.",
            features_used=["btc_return_60s", "basis_lag_score", "yes_price"],
            simulation_method="Lag proxy",
            constructor=lambda: ChainlinkBasisLagStrategy(),
            simplicity=0.7,
        ),
        EdgeHypothesis(
            key="indicator_consensus",
            name="Technical Indicator Consensus",
            intuition="Only trade when several independent BTC state indicators point the same way.",
            features_used=[
                "ma_gap_15m",
                "ma_gap_30m",
                "momentum_15m",
                "macd_hist",
                "rsi_14",
                "bollinger_zscore_20",
            ],
            simulation_method="Indicator vote ensemble + consensus gating",
            constructor=lambda: IndicatorConsensusStrategy(),
            simplicity=0.55,
        ),
        EdgeHypothesis(
            key="wallet_flow",
            name="Wallet Flow Momentum",
            intuition="Historically profitable wallets may reveal informed directional flow.",
            features_used=["wallet_up_bias", "wallet_signal_wallets", "wallet_signal_trades"],
            simulation_method="Wallet cohort scoring",
            constructor=lambda: WalletFlowMomentumStrategy(),
            simplicity=0.65,
        ),
        EdgeHypothesis(
            key="informed_flow_convergence",
            name="Informed Flow Convergence (Maker-Only)",
            intuition=(
                "Early agreement from vetted wallets can lead price discovery before "
                "market probabilities fully catch up to flow-implied fair value."
            ),
            features_used=[
                "wallet_up_bias",
                "wallet_avg_win_rate",
                "wallet_consensus_strength",
                "trade_flow_imbalance",
                "book_imbalance",
                "basis_lag_score",
            ],
            simulation_method="Flow-logit fair value blend + maker-only intent",
            constructor=lambda: InformedFlowConvergenceStrategy(),
            simplicity=0.6,
        ),
        EdgeHypothesis(
            key="mean_reversion",
            name="Post-Extreme Mean Reversion",
            intuition="Short-horizon directional overshoot may revert in next 15-minute window.",
            features_used=["prev_window_return", "yes_price"],
            simulation_method="Threshold reversion",
            constructor=lambda: MeanReversionStrategy(),
            simplicity=0.9,
        ),
        EdgeHypothesis(
            key="time_of_day",
            name="Time-of-Day Session Effect",
            intuition="Mispricing can cluster by session liquidity and recurring microstructure regimes.",
            features_used=["hour_utc", "weekday", "yes_price"],
            simulation_method="Empirical session prior",
            constructor=lambda: TimeOfDayPatternStrategy(),
            simplicity=0.85,
        ),
        EdgeHypothesis(
            key="book_imbalance",
            name="Order Book / Flow Imbalance",
            intuition="Depth or flow imbalance can reveal short-term pressure before resolution.",
            features_used=["book_imbalance", "trade_flow_imbalance", "yes_price"],
            simulation_method="Microstructure proxy",
            constructor=lambda: BookImbalanceStrategy(),
            simplicity=0.8,
        ),
    ]
