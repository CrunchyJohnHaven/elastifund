"""Benchmark inventory and methodology surfaces for external bot comparisons."""

from inventory.methodology import BENCHMARK_SPEC_VERSION, methodology_payload
from inventory.service import (
    bot_detail_payload,
    list_bots_payload,
    paper_status_payload,
    rankings_payload,
    run_artifacts_payload,
    runs_payload,
    list_systems_payload,
    system_detail_payload,
)

__all__ = [
    "BENCHMARK_SPEC_VERSION",
    "bot_detail_payload",
    "list_bots_payload",
    "list_systems_payload",
    "methodology_payload",
    "paper_status_payload",
    "rankings_payload",
    "run_artifacts_payload",
    "runs_payload",
    "system_detail_payload",
]
