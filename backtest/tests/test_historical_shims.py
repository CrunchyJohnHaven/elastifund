from __future__ import annotations

import importlib


def test_historical_compatibility_shims_import() -> None:
    modules = [
        ("backtest.analyze_results", "analyze"),
        ("backtest.fix_portfolio", "fix"),
        ("backtest.patch_resolution", "patch"),
        ("backtest.run_expanded_pipeline", "main"),
        ("backtest.combined_calibrator", "CombinedCalibrator"),
        ("backtest.monte_carlo_advanced", "SimulationConfig"),
    ]

    for module_name, symbol in modules:
        module = importlib.import_module(module_name)
        assert hasattr(module, symbol), f"{module_name} missing expected symbol {symbol}"
