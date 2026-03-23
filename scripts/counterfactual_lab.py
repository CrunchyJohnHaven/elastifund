#!/usr/bin/env python3
"""Counterfactual Lab: lane-aware counterfactual analysis.

Reads:
- BTC5 skip decisions from asset DBs (reuses counterfactual_analyzer logic)
- data/kalshi_weather_decisions.jsonl  (rejected decisions = weather counterfactuals)

Produces:
- reports/counterfactual_lab/latest.json

For the weather shadow lane, every rejected candidate is a counterfactual
because the market will resolve whether or not we entered. Positive average
edge on rejections means we are leaving money on the table (verdict: RELAX).
Negative average edge means the rejections saved us losses (verdict: TIGHTEN).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.report_envelope import write_report

from scripts.counterfactual_analyzer import (  # noqa: E402
    DEFAULT_DB_PATHS,
    build_counterfactual_report,
)

DEFAULT_WEATHER_DECISIONS_PATH = REPO_ROOT / "data" / "kalshi_weather_decisions.jsonl"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "counterfactual_lab" / "latest.json"

NEUTRAL_EPSILON = 1e-9


def _verdict(value: float) -> str:
    if value > NEUTRAL_EPSILON:
        return "RELAX"
    if value < -NEUTRAL_EPSILON:
        return "TIGHTEN"
    return "KEEP"


def _analyze_weather_counterfactuals(path: Path) -> dict[str, Any]:
    """Compute counterfactual metrics for rejected weather decisions by reason_code."""
    base: dict[str, Any] = {
        "path": str(path),
        "total_rejected": 0,
        "table": [],
        "overall": {"count": 0, "avg_edge": None},
    }
    if not path.exists():
        return {"status": "missing", **base}

    rejected: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("execution_result") == "rejected":
                        rejected.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        return {"status": f"read_error:{exc}", **base}

    by_reason: dict[str, list[float]] = {}
    for d in rejected:
        code = str(d.get("reason_code") or "unknown")
        edge = float(d.get("edge") or 0.0)
        by_reason.setdefault(code, []).append(edge)

    table: list[dict[str, Any]] = []
    for code in sorted(by_reason):
        edges = by_reason[code]
        avg_edge = sum(edges) / len(edges)
        table.append(
            {
                "reason_code": code,
                "count": len(edges),
                "avg_edge": round(avg_edge, 6),
                "verdict": _verdict(avg_edge),
            }
        )
    table.sort(key=lambda r: float(r["avg_edge"]), reverse=True)

    all_edges = [e for edges in by_reason.values() for e in edges]
    overall_avg = sum(all_edges) / len(all_edges) if all_edges else None

    return {
        "status": "ok",
        "path": str(path),
        "total_rejected": len(rejected),
        "table": table,
        "overall": {
            "count": len(rejected),
            "avg_edge": round(overall_avg, 6) if overall_avg is not None else None,
        },
    }


def run_counterfactual_lab(
    *,
    db_paths: list[Path] | None = None,
    weather_decisions_path: Path = DEFAULT_WEATHER_DECISIONS_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    db_paths = db_paths if db_paths is not None else list(DEFAULT_DB_PATHS)

    btc5_report = build_counterfactual_report(db_paths=db_paths)
    weather_cf = _analyze_weather_counterfactuals(weather_decisions_path)

    btc5_overall = btc5_report.get("overall") or {}
    weather_overall = weather_cf.get("overall") or {}

    lane_verdicts: dict[str, Any] = {
        "btc5": {
            "overall_pnl_per_trade": btc5_overall.get("counterfactual_PnL_per_trade"),
            "overall_wr": btc5_overall.get("counterfactual_WR"),
            "top_relax_reasons": [
                r["skip_reason"]
                for r in btc5_report.get("table", [])[:3]
                if r.get("verdict") == "RELAX"
            ],
            "top_tighten_reasons": [
                r["skip_reason"]
                for r in btc5_report.get("table", [])
                if r.get("verdict") == "TIGHTEN"
            ][:3],
        },
        "weather": {
            "overall_avg_edge": weather_overall.get("avg_edge"),
            "total_rejected": weather_overall.get("count"),
            "top_relax_reasons": [
                r["reason_code"]
                for r in weather_cf.get("table", [])[:3]
                if r.get("verdict") == "RELAX"
            ],
            "top_tighten_reasons": [
                r["reason_code"]
                for r in weather_cf.get("table", [])
                if r.get("verdict") == "TIGHTEN"
            ][:3],
        },
    }

    result: dict[str, Any] = {
        "artifact": "counterfactual_lab.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lane_verdicts": lane_verdicts,
        "btc5": btc5_report,
        "weather": weather_cf,
    }

    blockers: list[str] = []
    if (btc5_report.get("status") or "ok") != "ok":
        blockers.append(f"btc5:{btc5_report.get('status')}")
    if (weather_cf.get("status") or "ok") != "ok":
        blockers.append(f"weather:{weather_cf.get('status')}")
    write_report(
        output_path,
        artifact="counterfactual_lab.v1",
        payload=result,
        status="fresh" if not blockers else "stale",
        source_of_truth="data/jj_trades.db; data/kalshi_weather_decisions.jsonl",
        freshness_sla_seconds=1800,
        blockers=blockers,
        summary=(
            f"btc5={btc5_overall.get('counterfactual_WR')} "
            f"weather_avg_edge={weather_overall.get('avg_edge')}"
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-decisions", type=Path, default=DEFAULT_WEATHER_DECISIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--db",
        action="append",
        default=[],
        help="Override BTC5 DB paths (repeatable). Default: six maker DBs.",
    )
    args = parser.parse_args(argv)

    db_paths = [Path(p) for p in args.db] if args.db else None

    result = run_counterfactual_lab(
        db_paths=db_paths,
        weather_decisions_path=args.weather_decisions,
        output_path=args.output,
    )

    print(f"Wrote {args.output}")
    for lane, verdict in result["lane_verdicts"].items():
        print(f"  {lane}: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
