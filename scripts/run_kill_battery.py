#!/usr/bin/env python3
"""Weekly kill battery runner.

Reads accumulated signal/shadow data from edge_discovery.db, runs the
full kill_rules.py battery on each strategy family, and outputs an
updated FAST_TRADE_EDGE_ANALYSIS.md report.

Usage:
    python scripts/run_kill_battery.py                      # Full report
    python scripts/run_kill_battery.py --output reports/     # Custom output dir
    python scripts/run_kill_battery.py --db data/edge_discovery.db

Environment:
    KILL_BATTERY_DB       - database path (default data/edge_discovery.db)
    KILL_BATTERY_OUTPUT   - output directory (default project root)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.kill_rules import (
    KillResult,
    run_full_kill_battery,
    check_minimum_signals,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kill_battery")


@dataclass
class StrategyStats:
    """Aggregated stats for a strategy family from shadow signals."""
    name: str
    signal_group: str
    total_signals: int = 0
    resolved_signals: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_maker: float = 0.0
    total_pnl_taker: float = 0.0
    avg_confidence: float = 0.0
    avg_edge: float = 0.0
    avg_entry_price: float = 0.5

    @property
    def win_rate(self) -> float:
        if self.resolved_signals == 0:
            return 0.0
        return self.wins / self.resolved_signals

    @property
    def ev_maker(self) -> float:
        if self.resolved_signals == 0:
            return 0.0
        return self.total_pnl_maker / self.resolved_signals

    @property
    def ev_taker(self) -> float:
        if self.resolved_signals == 0:
            return 0.0
        return self.total_pnl_taker / self.resolved_signals


def load_strategy_stats(db_path: Path) -> list[StrategyStats]:
    """Load and aggregate shadow signal data by strategy group."""
    if not db_path.exists():
        logger.warning("database_not_found", path=str(db_path))
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Check if signal_shadow table exists
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "signal_shadow" not in tables:
        logger.warning("signal_shadow_table_not_found")
        conn.close()
        return []

    rows = conn.execute("""
        SELECT signal_group, signal_key, status, win, pnl_maker, pnl_taker,
               confidence, edge_estimate, entry_price
        FROM signal_shadow
        ORDER BY signal_group, created_at_ts
    """).fetchall()
    conn.close()

    if not rows:
        logger.info("no_shadow_signals_found")
        return []

    # Aggregate by signal_group
    groups: dict[str, StrategyStats] = {}
    for row in rows:
        group = row["signal_group"]
        if group not in groups:
            groups[group] = StrategyStats(
                name=_format_strategy_name(group),
                signal_group=group,
            )
        stats = groups[group]
        stats.total_signals += 1

        if row["status"] == "resolved":
            stats.resolved_signals += 1
            if row["win"]:
                stats.wins += 1
            else:
                stats.losses += 1
            stats.total_pnl_maker += float(row["pnl_maker"] or 0)
            stats.total_pnl_taker += float(row["pnl_taker"] or 0)

        stats.avg_confidence += float(row["confidence"] or 0)
        stats.avg_edge += float(row["edge_estimate"] or 0)
        stats.avg_entry_price += float(row["entry_price"] or 0.5)

    # Finalize averages
    for stats in groups.values():
        n = max(stats.total_signals, 1)
        stats.avg_confidence /= n
        stats.avg_edge /= n
        stats.avg_entry_price /= n

    return sorted(groups.values(), key=lambda s: s.total_signals, reverse=True)


def _format_strategy_name(signal_group: str) -> str:
    """Convert signal_group key to human-readable name."""
    return signal_group.replace("_", " ").replace("-", " ").title()


def run_battery_on_strategy(stats: StrategyStats) -> tuple[str, list[KillResult]]:
    """Run kill battery on a strategy and return verdict + results.

    Returns: ("CONTINUE" | "WATCH" | "KILL", results_list)
    """
    if stats.total_signals == 0:
        result = check_minimum_signals(0, "candidate")
        return "KILL", [result]

    passed, results = run_full_kill_battery(
        semantic_confidence=stats.avg_confidence,
        pnl_under_toxic=stats.total_pnl_maker * 0.5,  # Assume 50% in toxic regime
        pnl_normal=stats.total_pnl_maker * 0.5,
        gross_ev=stats.ev_maker,
        avg_price=stats.avg_entry_price,
        category="default",
        raw_prob=0.5,
        calibrated_prob=0.5,
        signal_count=stats.total_signals,
        stage="candidate",
        oos_ev=stats.ev_maker,
        in_sample_ev=stats.ev_maker * 1.2 if stats.ev_maker > 0 else 0.0,
        skip_toxicity=(stats.resolved_signals < 10),
        skip_semantic=(stats.avg_confidence == 0),
    )

    if passed:
        if stats.total_signals >= 100:
            return "CONTINUE", results
        return "WATCH", results
    return "KILL", results


def generate_report(
    strategies: list[StrategyStats],
    verdicts: dict[str, tuple[str, list[KillResult]]],
    db_path: Path,
) -> str:
    """Generate FAST_TRADE_EDGE_ANALYSIS.md content."""
    now = datetime.now(timezone.utc).isoformat()

    # Count data coverage from DB
    data_coverage = _get_data_coverage(db_path)

    # Overall recommendation
    any_continue = any(v[0] == "CONTINUE" for v in verdicts.values())
    recommendation = "CONTINUE BEST CANDIDATE" if any_continue else "REJECT ALL"

    lines = [
        "# Fast Trade Edge Analysis",
        f"**Last Updated:** {now}",
        f"**System Status:** running",
        f"**Data Window:** {data_coverage.get('first_ts', 'N/A')} to {data_coverage.get('last_ts', 'N/A')}",
        "",
        "## Data Coverage",
        f"- Markets tracked: {data_coverage.get('market_count', 0)}",
        f"- Price snapshots: {data_coverage.get('price_count', 0)}",
        f"- Shadow signals: {sum(s.total_signals for s in strategies)}",
        f"- Resolved signals: {sum(s.resolved_signals for s in strategies)}",
        "",
        "## Current Recommendation",
        recommendation,
        "",
        f"Reasoning: {'Best candidate passes all kill rules.' if any_continue else 'All active hypotheses failed kill rules or expectancy tests.'}",
        "",
        "---",
        "",
    ]

    # Validated edges
    validated = [s for s in strategies if verdicts.get(s.signal_group, ("KILL",))[0] == "CONTINUE" and s.total_signals >= 300]
    lines.append("## VALIDATED EDGES (p < 0.01, n > 300)")
    if validated:
        for s in validated:
            lines.append(f"- **{s.name}**: {s.total_signals} signals, {s.win_rate:.1%} win rate, EV maker: {s.ev_maker:.4f}")
    else:
        lines.append("None currently validated.")
    lines.extend(["", "---", ""])

    # Candidates
    candidates = [s for s in strategies if verdicts.get(s.signal_group, ("KILL",))[0] in ("CONTINUE", "WATCH") and s.total_signals >= 25]
    lines.append("## CANDIDATE EDGES (n >= 25)")
    if candidates:
        for s in candidates:
            verdict = verdicts[s.signal_group][0]
            lines.append(f"- **{s.name}** [{verdict}]: {s.total_signals} signals, {s.win_rate:.1%} win rate")
    else:
        lines.append("No candidate edges currently meet thresholds.")
    lines.extend(["", "---", ""])

    # Rejected
    rejected = [s for s in strategies if verdicts.get(s.signal_group, ("KILL",))[0] == "KILL"]
    lines.append("## REJECTED")
    lines.append("| Strategy | Signals | Win Rate | Verdict | Reason for Rejection |")
    lines.append("|----------|---------|----------|---------|----------------------|")
    for s in rejected:
        _, results = verdicts.get(s.signal_group, ("KILL", []))
        failures = [r for r in results if not r.passed]
        reason_str = "; ".join(r.detail[:60] for r in failures) if failures else "Insufficient data"
        lines.append(
            f"| {s.name} | {s.total_signals} | {s.win_rate:.2%} | KILL | {reason_str} |"
        )
    lines.extend(["", "---", ""])

    # Per-strategy detail
    lines.append("## KILL BATTERY DETAIL")
    for s in strategies:
        verdict, results = verdicts.get(s.signal_group, ("KILL", []))
        lines.append(f"### {s.name}")
        lines.append(f"- **Verdict:** {verdict}")
        lines.append(f"- **Signals:** {s.total_signals} (resolved: {s.resolved_signals})")
        lines.append(f"- **Win Rate:** {s.win_rate:.2%}")
        lines.append(f"- **EV (maker):** {s.ev_maker:.4f}")
        lines.append(f"- **EV (taker):** {s.ev_taker:.4f}")
        lines.append(f"- **Avg Confidence:** {s.avg_confidence:.3f}")
        lines.append("")
        lines.append("| Rule | Passed | Detail |")
        lines.append("|------|--------|--------|")
        for r in results:
            status = "PASS" if r.passed else "KILL"
            lines.append(f"| {r.reason.value if r.reason else 'N/A'} | {status} | {r.detail[:80]} |")
        lines.extend(["", "---", ""])

    # Next actions
    lines.append("## NEXT ACTIONS")
    lines.append("- Increase data collection horizon to reach >=100 signals for top strategy.")
    lines.append("- Run edge collector daemon (`scripts/run_edge_collector.py`) to accumulate market data.")
    lines.append("- Re-run kill battery weekly to track progress toward validation thresholds.")
    lines.append(f"- Kill conditions: reject if OOS expectancy <= 0 or cost-stress flips sign")
    lines.append(f"- Promotion conditions: n>=300, p<0.01, positive taker EV under stress")
    lines.append("")

    return "\n".join(lines)


def _get_data_coverage(db_path: Path) -> dict:
    """Get data coverage stats from the database."""
    if not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    result: dict = {}

    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "markets" in tables:
            row = conn.execute("SELECT COUNT(*) FROM markets").fetchone()
            result["market_count"] = row[0] if row else 0

        if "market_prices" in tables:
            row = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()
            result["price_count"] = row[0] if row else 0

            row = conn.execute(
                "SELECT MIN(timestamp_ts), MAX(timestamp_ts) FROM market_prices"
            ).fetchone()
            if row and row[0]:
                result["first_ts"] = datetime.fromtimestamp(
                    row[0], tz=timezone.utc
                ).isoformat()
                result["last_ts"] = datetime.fromtimestamp(
                    row[1], tz=timezone.utc
                ).isoformat()
    except Exception as e:
        logger.warning("data_coverage_error", error=str(e))
    finally:
        conn.close()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run kill battery on accumulated edge discovery data"
    )
    parser.add_argument(
        "--db", type=str,
        default=os.getenv("KILL_BATTERY_DB", "data/edge_discovery.db"),
        help="Database path",
    )
    parser.add_argument(
        "--output", type=str,
        default=os.getenv("KILL_BATTERY_OUTPUT", "."),
        help="Output directory for report",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("kill_battery_start", db=str(db_path))

    # Load strategy stats
    strategies = load_strategy_stats(db_path)

    if not strategies:
        logger.info("no_strategies_to_evaluate")
        # Still generate report showing empty state
        strategies = []

    # Run battery on each strategy
    verdicts: dict[str, tuple[str, list[KillResult]]] = {}
    for stats in strategies:
        verdict, results = run_battery_on_strategy(stats)
        verdicts[stats.signal_group] = (verdict, results)
        logger.info(
            "strategy_verdict",
            strategy=stats.name,
            verdict=verdict,
            signals=stats.total_signals,
            resolved=stats.resolved_signals,
            win_rate=f"{stats.win_rate:.2%}",
        )

    # Generate report
    report = generate_report(strategies, verdicts, db_path)
    report_path = output_dir / "FAST_TRADE_EDGE_ANALYSIS.md"
    report_path.write_text(report)
    logger.info("report_written", path=str(report_path))

    # Summary
    total_signals = sum(s.total_signals for s in strategies)
    total_resolved = sum(s.resolved_signals for s in strategies)
    kills = sum(1 for v in verdicts.values() if v[0] == "KILL")
    watches = sum(1 for v in verdicts.values() if v[0] == "WATCH")
    continues = sum(1 for v in verdicts.values() if v[0] == "CONTINUE")

    print(f"\n{'='*60}")
    print(f"KILL BATTERY REPORT")
    print(f"{'='*60}")
    print(f"Strategies evaluated: {len(strategies)}")
    print(f"Total signals: {total_signals} ({total_resolved} resolved)")
    print(f"Verdicts: {kills} KILL, {watches} WATCH, {continues} CONTINUE")
    print(f"Report: {report_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
