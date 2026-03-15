"""Paper-trade simulator package.

Canonical import surface: ``simulator.api``.
"""

from .api import (
    PaperTradeSimulator,
    SimulationReport,
    SimulatorEngine,
    load_simulator_config,
    load_simulator_inputs,
    run_baseline_simulation,
    run_report_simulation,
)

__all__ = [
    "PaperTradeSimulator",
    "SimulationReport",
    "SimulatorEngine",
    "load_simulator_config",
    "load_simulator_inputs",
    "run_baseline_simulation",
    "run_report_simulation",
]
