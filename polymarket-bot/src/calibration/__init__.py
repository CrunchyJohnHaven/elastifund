"""Category-specific calibration module for Polymarket probability estimates.

Provides per-category Platt scaling calibration to correct systematic bias
in Claude probability estimates across different market types.

Main exports:
- CategoryCalibrator: Apply category-specific calibration to probabilities
- CalibrationTrainer: Train calibration parameters from backtest data
- CalibrationReport: Validation metrics and performance tracking
- rank_markets_by_category_edge: Sort markets by calibrated edge strength

Usage example:
    from calibration import CategoryCalibrator, CalibrationTrainer

    # Train from backtest data
    calibrator, report = CalibrationTrainer.train_from_backtest(
        "historical_markets.json",
        "claude_cache.json"
    )

    # Apply to new estimates
    calibrated_prob = calibrator.calibrate(raw_prob=0.75, category="politics")

    # Compute trading edge with category routing
    edge = calibrator.compute_edge(raw_prob=0.75, market_price=0.60, category="politics")

    # Rank markets by edge
    from calibration import rank_markets_by_category_edge
    ranked = rank_markets_by_category_edge(markets, calibrator)
"""

from .category_calibration import (
    CategoryCalibrator,
    CalibrationReport,
    CalibrationTrainer,
    CategoryPerformance,
    DEFAULT_CATEGORY_PARAMS,
    CATEGORY_EDGE_THRESHOLDS,
    rank_markets_by_category_edge,
)

__all__ = [
    "CategoryCalibrator",
    "CalibrationReport",
    "CalibrationTrainer",
    "CategoryPerformance",
    "DEFAULT_CATEGORY_PARAMS",
    "CATEGORY_EDGE_THRESHOLDS",
    "rank_markets_by_category_edge",
]
