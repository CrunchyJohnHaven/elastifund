"""
Sensitivity analysis: vary one assumption at a time, measure PnL impact.

Identifies which assumption dominates the P&L outcome by computing
the partial derivative of total PnL with respect to each parameter.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Optional

from .api import SimulatorEngine

logger = logging.getLogger(__name__)

# Each scenario: (name, config_path, low_value, high_value, description)
SCENARIOS = [
    {
        "name": "winner_fee",
        "path": ["fees", "winner_fee"],
        "values": [0.0, 0.01, 0.02, 0.03, 0.04],
        "baseline": 0.02,
        "unit": "%",
        "description": "Winner fee rate (Polymarket charges on winning payouts)",
    },
    {
        "name": "taker_fee",
        "path": ["fees", "taker_rate"],
        "values": [0.0, 0.01, 0.02, 0.03, 0.05],
        "baseline": 0.02,
        "unit": "%",
        "description": "Taker fee on entry (applied to order notional)",
    },
    {
        "name": "slippage_bps",
        "path": ["fill_model", "taker", "base_slippage_bps"],
        "values": [0, 25, 50, 100, 200],
        "baseline": 50,
        "unit": "bps",
        "description": "Base slippage in basis points for taker orders",
    },
    {
        "name": "half_spread",
        "path": ["fill_model", "spreads", "us_weather", "half_spread_cents"],
        "values": [1.0, 3.0, 7.0, 15.0, 30.0],
        "baseline": 7.0,
        "unit": "cents",
        "description": "Half-spread for mid-tier markets (us_weather tier, cents)",
    },
    {
        "name": "fill_probability",
        "path": ["fill_model", "maker", "base_fill_probability"],
        "values": [0.30, 0.45, 0.55, 0.70, 0.85],
        "baseline": 0.55,
        "unit": "prob",
        "description": "Maker base fill probability (only active in maker mode)",
    },
    {
        "name": "edge_threshold",
        "path": ["execution", "min_edge_threshold"],
        "values": [0.03, 0.05, 0.07, 0.10, 0.15],
        "baseline": 0.05,
        "unit": "frac",
        "description": "Minimum edge threshold to enter a trade",
    },
    {
        "name": "position_cap",
        "path": ["execution", "max_concurrent_positions"],
        "values": [10, 25, 50, 100, 200],
        "baseline": 50,
        "unit": "count",
        "description": "Maximum concurrent positions",
    },
    {
        "name": "sizing_fraction",
        "path": ["sizing", "fixed_fraction", "fraction"],
        "values": [0.013, 0.020, 0.027, 0.040, 0.067],
        "baseline": 0.027,
        "unit": "frac",
        "description": "Fixed fraction of capital per trade",
    },
    {
        "name": "execution_mode",
        "path": ["execution", "mode"],
        "values": ["taker", "maker"],
        "baseline": "taker",
        "unit": "mode",
        "description": "Execution mode: taker (cross spread) vs maker (passive limit)",
    },
]


def _set_nested(config: dict, path: list[str], value) -> dict:
    """Set a value at a nested dict path."""
    cfg = deepcopy(config)
    d = cfg
    for key in path[:-1]:
        d = d[key]
    d[path[-1]] = value
    return cfg


def run_sensitivity(
    base_config: dict,
    markets: list[dict],
    claude_cache: dict,
    scenarios: Optional[list[dict]] = None,
    max_markets: int = 0,
) -> dict:
    """
    Run sensitivity analysis across all scenarios.

    For each assumption, varies it across its range while holding all others
    at baseline. Reports total PnL, hit rate, and trade count for each level.

    Returns a dict with per-scenario results and a ranked summary of which
    assumption has the largest PnL swing (max - min across tested values).
    """
    scenarios = scenarios or SCENARIOS

    # Run baseline first
    logger.info("Running baseline scenario...")
    baseline_engine = SimulatorEngine(base_config)
    baseline_report = baseline_engine.run(markets, claude_cache, max_markets=max_markets)
    baseline_pnl = baseline_report["total_pnl"]

    results = {
        "baseline": {
            "total_pnl": baseline_pnl,
            "hit_rate": baseline_report["hit_rate"],
            "filled_trades": baseline_report["filled_trades"],
            "max_drawdown": baseline_report["max_drawdown"],
            "return_pct": baseline_report["return_pct"],
        },
        "scenarios": {},
        "ranking": [],
    }

    for scenario in scenarios:
        name = scenario["name"]
        logger.info(f"Sensitivity: {name}")

        scenario_results = []
        for value in scenario["values"]:
            cfg = _set_nested(base_config, scenario["path"], value)

            # If switching to maker mode, use maker fee rate
            if name == "execution_mode" and value == "maker":
                cfg["fees"]["taker_rate"] = cfg["fees"]["maker_rate"]

            engine = SimulatorEngine(cfg)
            report = engine.run(markets, claude_cache, max_markets=max_markets)

            scenario_results.append({
                "value": value,
                "total_pnl": report["total_pnl"],
                "hit_rate": report["hit_rate"],
                "filled_trades": report["filled_trades"],
                "max_drawdown": report["max_drawdown"],
                "return_pct": report["return_pct"],
                "avg_pnl_per_trade": report["avg_pnl_per_trade"],
            })

        pnl_values = [r["total_pnl"] for r in scenario_results]
        pnl_swing = max(pnl_values) - min(pnl_values)

        results["scenarios"][name] = {
            "description": scenario["description"],
            "unit": scenario["unit"],
            "baseline_value": scenario["baseline"],
            "results": scenario_results,
            "pnl_swing": round(pnl_swing, 2),
            "pnl_range": [round(min(pnl_values), 2), round(max(pnl_values), 2)],
        }

    # Rank by PnL swing
    ranking = sorted(
        [
            {"name": name, "pnl_swing": data["pnl_swing"], "description": data["description"]}
            for name, data in results["scenarios"].items()
        ],
        key=lambda x: x["pnl_swing"],
        reverse=True,
    )
    results["ranking"] = ranking

    return results


def format_sensitivity_report(results: dict) -> str:
    """Format sensitivity results as a readable report."""
    lines = []
    lines.append("=" * 70)
    lines.append("  SENSITIVITY ANALYSIS — Which Assumption Dominates PnL?")
    lines.append("=" * 70)
    lines.append("")

    # Baseline
    b = results["baseline"]
    lines.append(f"  Baseline PnL:      ${b['total_pnl']:+.2f}")
    lines.append(f"  Baseline Hit Rate: {b['hit_rate']:.1%}")
    lines.append(f"  Baseline Trades:   {b['filled_trades']}")
    lines.append(f"  Baseline Return:   {b['return_pct']:.1%}")
    lines.append("")

    # Ranking
    lines.append("  ASSUMPTION RANKING (by PnL swing, highest impact first):")
    lines.append("  " + "-" * 66)
    for i, r in enumerate(results["ranking"], 1):
        lines.append(f"  {i}. {r['name']:25s} PnL swing: ${r['pnl_swing']:>10.2f}")
        lines.append(f"     {r['description']}")
    lines.append("")

    # Detail per scenario
    for name, data in results["scenarios"].items():
        lines.append(f"  --- {name} ({data['description']}) ---")
        lines.append(f"  {'Value':>12s} {'PnL':>12s} {'Hit Rate':>10s} {'Trades':>8s} {'MaxDD':>10s}")
        for r in data["results"]:
            marker = " *" if r["value"] == data["baseline_value"] else ""
            lines.append(
                f"  {str(r['value']):>12s} ${r['total_pnl']:>10.2f} "
                f"{r['hit_rate']:>9.1%} {r['filled_trades']:>8d} "
                f"${r['max_drawdown']:>8.2f}{marker}"
            )
        lines.append(f"  PnL range: ${data['pnl_range'][0]:+.2f} to ${data['pnl_range'][1]:+.2f}")
        lines.append("")

    # Dominant assumption
    if results["ranking"]:
        dominant = results["ranking"][0]
        lines.append("=" * 70)
        lines.append(f"  DOMINANT ASSUMPTION: {dominant['name']}")
        lines.append(f"  PnL swing: ${dominant['pnl_swing']:+.2f}")
        lines.append(f"  {dominant['description']}")
        lines.append("=" * 70)

    return "\n".join(lines)
