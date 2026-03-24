#!/usr/bin/env python3
"""
BTC5 Autoresearch -> Main Hypothesis Feed

Reads BTC5 autoresearch results and generates structured context for the
main research pipeline:
  - What parameters are winning/losing
  - What time-of-day effects are observed
  - What direction biases exist
  - What kill/skip reasons dominate (and what that implies for new strategies)

Inputs:
  - reports/btc5_autoresearch_current_probe/latest.json  (current probe state)
  - state/btc5_autoresearch.env                          (active overrides)
  - reports/autoresearch_cycles.jsonl                     (cycle history, optional)
  - data/btc_5min_maker.db                               (trade DB, optional)

Output:
  - reports/btc5_research_feedback.json
"""
import argparse
import json
import logging
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_env_file(path: str) -> dict:
    """Parse a KEY=VALUE env file, ignoring comments and blank lines."""
    result = {}
    p = Path(path)
    if not p.exists():
        return result
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("'\"")
    return result


def load_latest_probe(path: str) -> dict:
    """Load the latest autoresearch probe JSON."""
    p = Path(path)
    if not p.exists():
        logger.warning("Probe file not found: %s", path)
        return {}
    with open(p) as f:
        return json.load(f)


def load_cycle_history(path: str, max_cycles: int = 50) -> list:
    """Load recent autoresearch cycle results from JSONL."""
    p = Path(path)
    if not p.exists():
        return []
    cycles = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                cycles.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return cycles[-max_cycles:]


def extract_skip_distribution(db_path: str) -> dict:
    """Query the BTC5 maker DB for skip reason distribution."""
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT skip_reason, COUNT(*) as cnt "
            "FROM trades WHERE skip_reason IS NOT NULL AND skip_reason != '' "
            "GROUP BY skip_reason ORDER BY cnt DESC"
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.warning("Could not query skip distribution: %s", e)
        return {}


def extract_hour_performance(db_path: str) -> dict:
    """Query the BTC5 maker DB for hour-of-day P&L distribution."""
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path)
        # Attempt to get hour-level aggregation from filled trades
        rows = conn.execute(
            "SELECT CAST(strftime('%%H', fill_time) AS INTEGER) as hour_utc, "
            "COUNT(*) as cnt, "
            "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(pnl) as total_pnl "
            "FROM trades "
            "WHERE fill_time IS NOT NULL AND pnl IS NOT NULL "
            "GROUP BY hour_utc ORDER BY hour_utc"
        ).fetchall()
        conn.close()
        result = {}
        for row in rows:
            hour = row[0]
            result[str(hour)] = {
                "count": row[1],
                "wins": row[2],
                "total_pnl": round(row[3], 4) if row[3] else 0,
                "win_rate": round(row[2] / row[1], 4) if row[1] > 0 else 0,
            }
        return result
    except Exception as e:
        logger.warning("Could not query hour performance: %s", e)
        return {}


def extract_direction_bias(db_path: str) -> dict:
    """Query the BTC5 maker DB for direction-level P&L."""
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT direction, COUNT(*) as cnt, "
            "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(pnl) as total_pnl "
            "FROM trades "
            "WHERE direction IS NOT NULL AND pnl IS NOT NULL "
            "GROUP BY direction"
        ).fetchall()
        conn.close()
        result = {}
        for row in rows:
            result[row[0]] = {
                "count": row[1],
                "wins": row[2],
                "total_pnl": round(row[3], 4) if row[3] else 0,
                "win_rate": round(row[2] / row[1], 4) if row[1] > 0 else 0,
            }
        return result
    except Exception as e:
        logger.warning("Could not query direction bias: %s", e)
        return {}


def analyze_parameter_performance(cycles: list) -> dict:
    """Analyze which parameters correlate with winning/losing cycles."""
    if not cycles:
        return {"winning_params": {}, "losing_params": {}, "sample_size": 0}

    winning_params: Counter = Counter()
    losing_params: Counter = Counter()
    total = 0

    for cycle in cycles:
        params = cycle.get("parameters", cycle.get("overrides", {}))
        result = cycle.get("result", cycle.get("outcome", ""))
        pnl = cycle.get("pnl", cycle.get("realized_pnl", 0))

        if not params:
            continue
        total += 1

        bucket = winning_params if (pnl and pnl > 0) else losing_params
        for k, v in params.items():
            bucket[f"{k}={v}"] += 1

    return {
        "winning_params": dict(winning_params.most_common(10)),
        "losing_params": dict(losing_params.most_common(10)),
        "sample_size": total,
    }


def generate_implications(
    skip_dist: dict,
    hour_perf: dict,
    direction_bias: dict,
    param_analysis: dict,
) -> list:
    """Generate actionable implications from the analysis."""
    implications = []

    # Skip reason implications
    if skip_dist:
        total_skips = sum(skip_dist.values())
        for reason, count in sorted(
            skip_dist.items(), key=lambda x: -x[1]
        )[:3]:
            pct = count / total_skips * 100
            if "delta" in reason.lower() and pct > 40:
                implications.append(
                    f"Delta filter causes {pct:.0f}% of skips. "
                    "Consider widening BTC5_MAX_ABS_DELTA."
                )
            elif "shadow" in reason.lower() and pct > 15:
                implications.append(
                    f"Shadow-only skips at {pct:.0f}%. "
                    "Book depth may be insufficient for current sizing."
                )
            elif "toxic" in reason.lower() and pct > 10:
                implications.append(
                    f"Toxic order flow skip at {pct:.0f}%. "
                    "Consider time-of-day filtering to avoid high-toxicity windows."
                )

    # Hour-of-day implications
    if hour_perf:
        losing_hours = [
            h for h, d in hour_perf.items()
            if d.get("total_pnl", 0) < 0 and d.get("count", 0) >= 5
        ]
        winning_hours = [
            h for h, d in hour_perf.items()
            if d.get("total_pnl", 0) > 0 and d.get("count", 0) >= 5
        ]
        if losing_hours:
            implications.append(
                f"Losing hours (UTC): {', '.join(sorted(losing_hours))}. "
                "Implement time-of-day filter to suppress trading in these windows."
            )
        if winning_hours:
            implications.append(
                f"Winning hours (UTC): {', '.join(sorted(winning_hours))}. "
                "Concentrate trading in these windows."
            )

    # Direction bias implications
    if direction_bias:
        for direction, stats in direction_bias.items():
            if stats.get("count", 0) >= 10:
                wr = stats.get("win_rate", 0)
                pnl = stats.get("total_pnl", 0)
                if pnl > 0 and wr > 0.52:
                    implications.append(
                        f"{direction} shows edge: WR={wr:.1%}, PnL=${pnl:.2f}. "
                        f"Consider {direction}-only mode."
                    )
                elif pnl < 0:
                    implications.append(
                        f"{direction} is net negative: PnL=${pnl:.2f}. "
                        f"Consider disabling {direction} trades."
                    )

    return implications


def build_feedback(
    probe_path: str,
    env_path: str,
    cycles_path: str,
    db_path: str,
) -> dict:
    """Build the complete research feedback artifact."""
    probe = load_latest_probe(probe_path)
    env_overrides = parse_env_file(env_path)
    cycles = load_cycle_history(cycles_path)
    skip_dist = extract_skip_distribution(db_path)
    hour_perf = extract_hour_performance(db_path)
    direction_bias = extract_direction_bias(db_path)
    param_analysis = analyze_parameter_performance(cycles)
    implications = generate_implications(
        skip_dist, hour_perf, direction_bias, param_analysis
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "btc5_autoresearch",
        "current_probe": {
            "hypothesis_id": probe.get("hypothesis_id", "unknown"),
            "status": probe.get("status", "unknown"),
            "direction_bias": probe.get("direction_bias", "none"),
            "parameters": probe.get("parameters", {}),
            "evidence_fills": probe.get("evidence_fills", 0),
            "evidence_grade": probe.get("evidence_grade", "none"),
        },
        "active_overrides": env_overrides,
        "skip_distribution": skip_dist,
        "hour_of_day_performance": hour_perf,
        "direction_bias": direction_bias,
        "parameter_analysis": param_analysis,
        "cycle_count": len(cycles),
        "implications": implications,
        "research_recommendations": {
            "for_hypothesis_generator": [
                "Use actual fill rate from execution feedback, not backtest assumptions",
                "Account for skip rate when estimating expected PnL",
                "Time-of-day is a real signal; incorporate as a feature",
                "Direction bias exists; test directional strategies separately",
            ],
            "for_cost_model": {
                "note": "Calibrate from actual execution, not theory",
                "skip_rate_pct": (
                    sum(skip_dist.values())
                    / max(sum(skip_dist.values()) + len(direction_bias), 1)
                    * 100
                    if skip_dist
                    else 0
                ),
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Feed BTC5 autoresearch results into the main hypothesis generator"
    )
    parser.add_argument(
        "--probe-path",
        default="reports/btc5_autoresearch_current_probe/latest.json",
        help="Path to latest probe JSON",
    )
    parser.add_argument(
        "--env-path",
        default="state/btc5_autoresearch.env",
        help="Path to autoresearch env overrides",
    )
    parser.add_argument(
        "--cycles-path",
        default="reports/autoresearch_cycles.jsonl",
        help="Path to cycle history JSONL",
    )
    parser.add_argument(
        "--db-path",
        default="data/btc_5min_maker.db",
        help="Path to BTC5 maker trade database",
    )
    parser.add_argument(
        "--output",
        default="reports/btc5_research_feedback.json",
        help="Output path for feedback JSON",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    feedback = build_feedback(
        probe_path=args.probe_path,
        env_path=args.env_path,
        cycles_path=args.cycles_path,
        db_path=args.db_path,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(feedback, f, indent=2)

    logger.info("BTC5 research feedback written to %s", output_path)
    logger.info(
        "Implications: %d, Cycle history: %d, Skip reasons: %d",
        len(feedback["implications"]),
        feedback["cycle_count"],
        len(feedback["skip_distribution"]),
    )


if __name__ == "__main__":
    main()
