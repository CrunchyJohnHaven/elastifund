#!/usr/bin/env python3
"""Render percentage-only BTC5 continuation ARR progress artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


@dataclass
class ArrRecord:
    cycle: int
    finished_at: str
    active_arr_pct: float
    best_arr_pct: float
    delta_arr_pct: float
    p05_active_arr_pct: float
    p05_best_arr_pct: float
    frontier_active_arr_pct: float
    frontier_best_arr_pct: float
    action: str
    reason: str


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_pct(value: float) -> str:
    return f"{value:,.1f}%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-jsonl",
        default="reports/btc5_autoresearch_loop/history.jsonl",
        help="Loop history ledger emitted by run_btc5_autoresearch_loop.py",
    )
    parser.add_argument(
        "--tsv-out",
        default="research/btc5_arr_progress.tsv",
        help="Tracked TSV export for ARR progress",
    )
    parser.add_argument(
        "--svg-out",
        default="research/btc5_arr_progress.svg",
        help="Tracked SVG export for ARR progress",
    )
    parser.add_argument(
        "--summary-md-out",
        default="research/btc5_arr_summary.md",
        help="Tracked markdown summary for the latest ARR read",
    )
    parser.add_argument(
        "--latest-json-out",
        default="research/btc5_arr_latest.json",
        help="Tracked machine-readable latest ARR summary",
    )
    return parser.parse_args()


def load_records(history_path: Path) -> list[ArrRecord]:
    if not history_path.exists():
        return []
    records: list[ArrRecord] = []
    frontier_active = float("-inf")
    frontier_best = float("-inf")
    for cycle, line in enumerate(history_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        arr = payload.get("arr") or {}
        active = _safe_float(arr.get("active_median_arr_pct"))
        best = _safe_float(arr.get("best_median_arr_pct"))
        frontier_active = max(frontier_active, active)
        frontier_best = max(frontier_best, best)
        decision = payload.get("decision") or {}
        records.append(
            ArrRecord(
                cycle=cycle,
                finished_at=str(payload.get("finished_at") or ""),
                active_arr_pct=active,
                best_arr_pct=best,
                delta_arr_pct=_safe_float(arr.get("median_arr_delta_pct")),
                p05_active_arr_pct=_safe_float(arr.get("active_p05_arr_pct")),
                p05_best_arr_pct=_safe_float(arr.get("best_p05_arr_pct")),
                frontier_active_arr_pct=frontier_active,
                frontier_best_arr_pct=frontier_best,
                action=str(decision.get("action") or "unknown"),
                reason=str(decision.get("reason") or ""),
            )
        )
    return records


def write_tsv(path: Path, records: list[ArrRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "\t".join(
            [
                "cycle",
                "finished_at",
                "active_arr_pct",
                "best_arr_pct",
                "delta_arr_pct",
                "p05_active_arr_pct",
                "p05_best_arr_pct",
                "frontier_active_arr_pct",
                "frontier_best_arr_pct",
                "action",
                "reason",
            ]
        )
    ]
    for record in records:
        lines.append(
            "\t".join(
                [
                    str(record.cycle),
                    record.finished_at,
                    f"{record.active_arr_pct:.4f}",
                    f"{record.best_arr_pct:.4f}",
                    f"{record.delta_arr_pct:.4f}",
                    f"{record.p05_active_arr_pct:.4f}",
                    f"{record.p05_best_arr_pct:.4f}",
                    f"{record.frontier_active_arr_pct:.4f}",
                    f"{record.frontier_best_arr_pct:.4f}",
                    record.action,
                    record.reason,
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n")


def build_latest_summary(records: list[ArrRecord]) -> dict[str, Any]:
    latest = records[-1]
    promotions = sum(1 for record in records if record.action == "promote")
    holds = sum(1 for record in records if record.action == "hold")
    return {
        "metric_name": "continuation_arr_pct",
        "cycles_total": len(records),
        "promotions_total": promotions,
        "holds_total": holds,
        "latest_finished_at": latest.finished_at,
        "latest_active_arr_pct": round(latest.active_arr_pct, 4),
        "latest_best_arr_pct": round(latest.best_arr_pct, 4),
        "latest_delta_arr_pct": round(latest.delta_arr_pct, 4),
        "latest_p05_active_arr_pct": round(latest.p05_active_arr_pct, 4),
        "latest_p05_best_arr_pct": round(latest.p05_best_arr_pct, 4),
        "frontier_active_arr_pct": round(max(record.frontier_active_arr_pct for record in records), 4),
        "frontier_best_arr_pct": round(max(record.frontier_best_arr_pct for record in records), 4),
        "latest_action": latest.action,
        "latest_reason": latest.reason,
    }


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# BTC5 Continuation ARR",
        "",
        "This is a continuation estimate derived from the 5-minute simulation loop. It is percentage-only and annualizes the strategy's simulated return rate per average deployed 5-minute capital, not fund-level bankroll return.",
        "",
        f"- Cycles tracked: `{summary['cycles_total']}`",
        f"- Promotions: `{summary['promotions_total']}`",
        f"- Holds: `{summary['holds_total']}`",
        f"- Latest active ARR: `{summary['latest_active_arr_pct']:.2f}%`",
        f"- Latest best-candidate ARR: `{summary['latest_best_arr_pct']:.2f}%`",
        f"- Latest ARR delta: `{summary['latest_delta_arr_pct']:.2f}` percentage points",
        f"- Latest active P05 ARR: `{summary['latest_p05_active_arr_pct']:.2f}%`",
        f"- Latest best-candidate P05 ARR: `{summary['latest_p05_best_arr_pct']:.2f}%`",
        f"- Frontier active ARR: `{summary['frontier_active_arr_pct']:.2f}%`",
        f"- Frontier best-candidate ARR: `{summary['frontier_best_arr_pct']:.2f}%`",
        f"- Latest action: `{summary['latest_action']}`",
        f"- Latest reason: `{summary['latest_reason']}`",
        f"- Latest finished at: `{summary['latest_finished_at']}`",
    ]
    path.write_text("\n".join(lines) + "\n")


def _polyline(points: list[tuple[float, float]], color: str, width: float) -> str:
    if not points:
        return ""
    encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline fill="none" stroke="{color}" stroke-width="{width}" points="{encoded}" />'


def render_svg(path: Path, records: list[ArrRecord], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 1280
    height = 760
    left = 90
    right = width - 40
    top_chart_top = 80
    top_chart_bottom = 420
    delta_chart_top = 500
    delta_chart_bottom = 680
    usable_width = max(1, right - left)
    arr_values = [
        value
        for record in records
        for value in (
            record.active_arr_pct,
            record.best_arr_pct,
            record.frontier_active_arr_pct,
            record.frontier_best_arr_pct,
        )
    ]
    arr_min = min(arr_values)
    arr_max = max(arr_values)
    if abs(arr_max - arr_min) < 1e-9:
        arr_min -= 1.0
        arr_max += 1.0
    delta_values = [record.delta_arr_pct for record in records] or [0.0]
    delta_min = min(min(delta_values), 0.0)
    delta_max = max(max(delta_values), 0.0)
    if abs(delta_max - delta_min) < 1e-9:
        delta_min -= 1.0
        delta_max += 1.0

    def x_for(index: int) -> float:
        if len(records) == 1:
            return left + usable_width / 2.0
        return left + (usable_width * index / float(len(records) - 1))

    def y_for_arr(value: float) -> float:
        ratio = (value - arr_min) / (arr_max - arr_min)
        return top_chart_bottom - ratio * (top_chart_bottom - top_chart_top)

    def y_for_delta(value: float) -> float:
        ratio = (value - delta_min) / (delta_max - delta_min)
        return delta_chart_bottom - ratio * (delta_chart_bottom - delta_chart_top)

    active_points = [(x_for(index), y_for_arr(record.active_arr_pct)) for index, record in enumerate(records)]
    best_points = [(x_for(index), y_for_arr(record.best_arr_pct)) for index, record in enumerate(records)]
    frontier_points = [(x_for(index), y_for_arr(record.frontier_active_arr_pct)) for index, record in enumerate(records)]
    delta_points = [(x_for(index), y_for_delta(record.delta_arr_pct)) for index, record in enumerate(records)]
    latest = records[-1]

    arr_ticks = [arr_min, (arr_min + arr_max) / 2.0, arr_max]
    delta_ticks = [delta_min, 0.0, delta_max]
    vertical_guides = "\n".join(
        f'<line x1="{x_for(index):.2f}" y1="{top_chart_top}" x2="{x_for(index):.2f}" y2="{top_chart_bottom}" stroke="#E7E0D4" stroke-width="1" />'
        for index in range(len(records))
    )
    arr_tick_lines = "\n".join(
        f'<line x1="{left}" y1="{y_for_arr(value):.2f}" x2="{right}" y2="{y_for_arr(value):.2f}" stroke="#E7E0D4" stroke-width="1" />'
        for value in arr_ticks
    )
    delta_tick_lines = "\n".join(
        f'<line x1="{left}" y1="{y_for_delta(value):.2f}" x2="{right}" y2="{y_for_delta(value):.2f}" stroke="#E7E0D4" stroke-width="1" />'
        for value in delta_ticks
    )
    arr_tick_labels = "\n".join(
        f'<text x="{left - 12}" y="{y_for_arr(value) + 5:.2f}" text-anchor="end" font-size="16" fill="#5F5A50">{escape(_fmt_pct(value))}</text>'
        for value in arr_ticks
    )
    delta_tick_labels = "\n".join(
        f'<text x="{left - 12}" y="{y_for_delta(value) + 5:.2f}" text-anchor="end" font-size="16" fill="#5F5A50">{escape(_fmt_pct(value))}</text>'
        for value in delta_ticks
    )
    circles = "\n".join(
        [
            f'<circle cx="{active_points[-1][0]:.2f}" cy="{active_points[-1][1]:.2f}" r="6" fill="#16324F" />',
            f'<circle cx="{best_points[-1][0]:.2f}" cy="{best_points[-1][1]:.2f}" r="6" fill="#C56A1A" />',
            f'<circle cx="{delta_points[-1][0]:.2f}" cy="{delta_points[-1][1]:.2f}" r="6" fill="#1E8A5C" />',
        ]
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="BTC5 continuation ARR progress">
<rect width="{width}" height="{height}" fill="#FBF7EE" />
<text x="{left}" y="42" font-size="28" font-weight="700" fill="#1E1C18">BTC5 Continuation ARR</text>
<text x="{left}" y="66" font-size="16" fill="#5F5A50">Percentage-only strategy estimate. Latest active {_fmt_pct(summary['latest_active_arr_pct'])}; latest best {_fmt_pct(summary['latest_best_arr_pct'])}; delta {_fmt_pct(summary['latest_delta_arr_pct'])}.</text>
<text x="{left}" y="{top_chart_top - 14}" font-size="18" font-weight="600" fill="#1E1C18">ARR Estimate</text>
{vertical_guides}
{arr_tick_lines}
{arr_tick_labels}
{_polyline(frontier_points, "#5B7188", 2.0)}
{_polyline(active_points, "#16324F", 3.5)}
{_polyline(best_points, "#C56A1A", 3.5)}
<text x="{right}" y="{top_chart_top - 14}" text-anchor="end" font-size="15" fill="#16324F">Active</text>
<text x="{right - 70}" y="{top_chart_top - 14}" text-anchor="end" font-size="15" fill="#C56A1A">Best candidate</text>
<text x="{right - 230}" y="{top_chart_top - 14}" text-anchor="end" font-size="15" fill="#5B7188">Frontier active</text>
<text x="{left}" y="{delta_chart_top - 14}" font-size="18" font-weight="600" fill="#1E1C18">Best minus Active</text>
{delta_tick_lines}
{delta_tick_labels}
{_polyline(delta_points, "#1E8A5C", 3.0)}
<line x1="{left}" y1="{y_for_delta(0.0):.2f}" x2="{right}" y2="{y_for_delta(0.0):.2f}" stroke="#8E8A80" stroke-width="1.5" stroke-dasharray="4 4" />
{circles}
<text x="{right}" y="{delta_chart_bottom + 34}" text-anchor="end" font-size="15" fill="#5F5A50">Last cycle {latest.cycle} at {escape(latest.finished_at)}</text>
</svg>
"""
    path.write_text(svg)


def main() -> int:
    args = parse_args()
    history_path = Path(args.history_jsonl)
    records = load_records(history_path)
    if not records:
        raise SystemExit(f"No ARR history found at {history_path}")
    tsv_out = Path(args.tsv_out)
    svg_out = Path(args.svg_out)
    summary_md_out = Path(args.summary_md_out)
    latest_json_out = Path(args.latest_json_out)
    summary = build_latest_summary(records)
    write_tsv(tsv_out, records)
    render_svg(svg_out, records, summary)
    write_summary_md(summary_md_out, summary)
    latest_json_out.parent.mkdir(parents=True, exist_ok=True)
    latest_json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"tsv": str(tsv_out), "svg": str(svg_out), "summary_md": str(summary_md_out), "latest_json": str(latest_json_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
