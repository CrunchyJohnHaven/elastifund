from __future__ import annotations

from typing import Any


BENCHMARK_SPEC_VERSION = "2026.03-candidate1"

BENCHMARK_ENVIRONMENT = {
    "os": "Ubuntu 22.04 LTS",
    "python": "Python 3.12 host tools plus project-pinned runtime images",
    "container_runtime": "Docker, rootless when possible",
    "network_policy": "Outbound HTTPS only plus explicit testnet allowlists",
    "secrets_policy": "Ephemeral paper or sandbox credentials only, rotated per run",
}

EXECUTION_LABELS = [
    {
        "id": "internal_simulation",
        "name": "Internal simulation",
        "meaning": "System simulates fills on live or historical data using its own paper mode.",
        "realism_rank": 1,
    },
    {
        "id": "exchange_sandbox",
        "name": "Exchange sandbox",
        "meaning": "System trades against official demo or testnet infrastructure.",
        "realism_rank": 2,
    },
    {
        "id": "deterministic_simulation",
        "name": "Deterministic simulation",
        "meaning": "Historical replay with a controlled exchange or broker model.",
        "realism_rank": 3,
    },
]

DATA_TRACKS = [
    {
        "id": "candle",
        "name": "Candle track",
        "systems": "Directional, DCA, grid, and general execution bots.",
    },
    {
        "id": "order_book",
        "name": "Order-book track",
        "systems": "Market making, queue-position, latency-sensitive, and HFT-style systems.",
    },
]

STRATEGY_LABELS = [
    {
        "id": "native",
        "name": "Native strategy",
        "meaning": "Use the system's first-class strategy interface or shipped primitives.",
    },
    {
        "id": "translated",
        "name": "Translated strategy",
        "meaning": "Port a canonical Elastifund benchmark strategy into the system API.",
    },
]

TEST_MATRIX = [
    {
        "id": "T0",
        "name": "Reproducible build",
        "measures": "Install from a clean machine without manual edits.",
        "pass_criteria": "Build succeeds from pinned instructions with no hand patching.",
    },
    {
        "id": "T1",
        "name": "Smoke paper run",
        "measures": "Time to first valid decision in a safe environment.",
        "pass_criteria": "Makes a valid paper decision within 15 minutes.",
    },
    {
        "id": "T2",
        "name": "Forced restart",
        "measures": "Crash recovery and state integrity.",
        "pass_criteria": "Recovers within 5 minutes with no corrupted state.",
    },
    {
        "id": "T3",
        "name": "Data-feed disconnect",
        "measures": "Reconnect logic and missing-data transparency.",
        "pass_criteria": "Reconnects within 2 minutes and logs the gap.",
    },
    {
        "id": "T4",
        "name": "24-hour soak",
        "measures": "Memory leaks and silent operational drift.",
        "pass_criteria": "No crash and less than 10 percent RSS drift.",
    },
    {
        "id": "T5",
        "name": "7-day run",
        "measures": "Operational stability over a benchmark window.",
        "pass_criteria": "Crash-free at 99 percent or better uptime.",
    },
    {
        "id": "T6",
        "name": "Backtest parity",
        "measures": "Research-to-paper divergence.",
        "pass_criteria": "Signal divergence stays within the versioned tolerance band.",
    },
    {
        "id": "T7",
        "name": "Execution fidelity",
        "measures": "Order semantics, slippage realism, and fill honesty.",
        "pass_criteria": "Observed fills stay inside the declared slippage band.",
    },
]

SCORING_RUBRIC = [
    {
        "id": "reliability_operations",
        "name": "Reliability and operations",
        "weight": 25,
        "measures": "Uptime, restart behavior, reconnect logic, and soak-test stability.",
    },
    {
        "id": "execution_fidelity",
        "name": "Execution fidelity",
        "weight": 20,
        "measures": "Order semantics, slippage realism, and fill handling.",
    },
    {
        "id": "research_iteration_speed",
        "name": "Research and iteration speed",
        "weight": 15,
        "measures": "Backtest reproducibility, build speed, and data ergonomics.",
    },
    {
        "id": "integration_breadth",
        "name": "Integration breadth",
        "weight": 15,
        "measures": "Venue coverage, adapter quality, and paper or sandbox support.",
    },
    {
        "id": "usability_onboarding",
        "name": "Usability and onboarding",
        "weight": 10,
        "measures": "Docker-first setup, docs clarity, and time to first paper run.",
    },
    {
        "id": "community_maintenance",
        "name": "Community and maintenance",
        "weight": 10,
        "measures": "Recent releases, contributor health, and maintenance recency.",
    },
    {
        "id": "license_legal",
        "name": "License and legal",
        "weight": 5,
        "measures": "Copyleft burden, redistribution risk, and licensing clarity.",
    },
]

PIPELINE_MERMAID = """flowchart TD
  A["Discovery and intake"] --> B["Metadata normalize"]
  B --> C["License and policy gate"]
  C -->|pass| D["Build container image"]
  C -->|fail| C1["Quarantine or doc-only entry"]
  D --> E["Static security scans"]
  E -->|pass| F["Unit and smoke tests"]
  E -->|fail| E1["Quarantine or score penalty"]
  F --> G["Backtest track jobs"]
  F --> H["Paper-trade track jobs"]
  G --> I["Metrics extract and normalize"]
  H --> I
  I --> J["Score and rank compute"]
  J --> K["Publish API and web UI"]
"""


def methodology_payload() -> dict[str, Any]:
    return {
        "spec_version": BENCHMARK_SPEC_VERSION,
        "state": "methodology_published",
        "environment": BENCHMARK_ENVIRONMENT,
        "execution_labels": EXECUTION_LABELS,
        "data_tracks": DATA_TRACKS,
        "strategy_labels": STRATEGY_LABELS,
        "test_matrix": TEST_MATRIX,
        "scoring_rubric": SCORING_RUBRIC,
        "pipeline_mermaid": PIPELINE_MERMAID,
        "fairness_rules": [
            "Do not mix candle-track and order-book-track systems into one leaderboard.",
            "Disclose whether a run used internal simulation, exchange sandbox, or deterministic simulation.",
            "Label every run as native strategy or translated strategy.",
            "Do not publish profitability rankings before operational evidence exists.",
        ],
        "initial_cohort": [
            "freqtrade",
            "hummingbot",
            "jesse",
            "octobot",
            "nautilustrader",
            "lean",
        ],
    }
