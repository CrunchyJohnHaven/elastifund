"""Canonical simulator API surface.

Use this module for imports from other packages. Legacy modules remain for
compatibility, but new code should import from ``simulator.api``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .engine import PaperTradeSimulator
from .metrics import SimulationReport
from .simulator import SimulatorEngine, _cache_key, load_config, load_inputs, run_simulation


def load_simulator_config(path: Optional[str] = None) -> dict:
    """Load simulator YAML config."""
    return load_config(path)


def load_simulator_inputs(
    markets_path: Optional[str] = None,
    cache_path: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """Load historical markets and cached estimate inputs."""
    return load_inputs(markets_path=markets_path, cache_path=cache_path)


def run_baseline_simulation(
    config_path: Optional[str] = None,
    markets_path: Optional[str] = None,
    cache_path: Optional[str] = None,
    max_markets: int = 0,
) -> dict:
    """Run the deterministic baseline simulation engine."""
    return run_simulation(
        config_path=config_path,
        markets_path=markets_path,
        cache_path=cache_path,
        max_markets=max_markets,
    )


def run_report_simulation(
    config_path: str | Path,
    markets_path: str | Path,
    cache_path: str | Path,
) -> SimulationReport:
    """Run the report-shaped simulator used by audit/compare CLI surfaces."""
    return PaperTradeSimulator(config_path).run(markets_path=markets_path, cache_path=cache_path)


def question_cache_key(question: str) -> str:
    """Build the canonical cache key used by simulator/backtest surfaces."""
    return _cache_key(question)


__all__ = [
    "PaperTradeSimulator",
    "SimulationReport",
    "SimulatorEngine",
    "load_simulator_config",
    "load_simulator_inputs",
    "run_baseline_simulation",
    "question_cache_key",
    "run_report_simulation",
]
