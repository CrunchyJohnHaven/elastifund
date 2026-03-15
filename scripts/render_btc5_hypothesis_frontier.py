#!/usr/bin/env python3
"""Render the BTC5 hypothesis frontier from local autoresearch loop history."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


@dataclass
class FrontierRecord:
    cycle: int
    finished_at: str
    hypothesis_name: str
    direction: str
    session_name: str
    evidence_band: str
    validation_p05_arr_pct: float
    validation_median_arr_pct: float
    frontier_p05_arr_pct: float
    frontier_median_arr_pct: float
    frontier_delta_arr_pct: float
    validation_live_filled_rows: int
    generalization_ratio: float


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fmt_pct(value: float) -> str:
    return f"{value:,.1f}%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-jsonl",
        default="reports/btc5_autoresearch_loop/history.jsonl",
        help="Loop history emitted by run_btc5_autoresearch_loop.py",
    )
    parser.add_argument(
        "--tsv-out",
        default="research/btc5_hypothesis_frontier.tsv",
        help="Tracked TSV export for the hypothesis frontier",
    )
    parser.add_argument(
        "--svg-out",
        default="research/btc5_hypothesis_frontier.svg",
        help="Tracked SVG export for the hypothesis frontier",
    )
    parser.add_argument(
        "--summary-md-out",
        default="research/btc5_hypothesis_frontier_summary.md",
        help="Tracked markdown summary for the latest frontier state",
    )
    parser.add_argument(
        "--latest-json-out",
        default="research/btc5_hypothesis_frontier_latest.json",
        help="Tracked machine-readable latest frontier summary",
    )
    return parser.parse_args()


def load_records(history_path: Path) -> list[FrontierRecord]:
    if not history_path.exists():
        return []
    records: list[FrontierRecord] = []
    frontier_p05 = float("-inf")
    frontier_median = float("-inf")
    cycle = 0
    for line in history_path.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        lab = payload.get("hypothesis_lab") or {}
        best_hypothesis = lab.get("best_hypothesis") or {}
        best_summary = lab.get("best_summary") or {}
        if not best_hypothesis:
            continue
        cycle += 1
        p05_arr = _safe_float(best_summary.get("validation_p05_arr_pct"))
        median_arr = _safe_float(best_summary.get("validation_median_arr_pct"))
        frontier_p05 = max(frontier_p05, p05_arr)
        frontier_median = max(frontier_median, median_arr)
        records.append(
            FrontierRecord(
                cycle=cycle,
                finished_at=str(payload.get("finished_at") or ""),
                hypothesis_name=str(best_hypothesis.get("name") or "unknown"),
                direction=str(best_hypothesis.get("direction") or "ANY"),
                session_name=str(best_hypothesis.get("session_name") or "any"),
                evidence_band=str(best_summary.get("evidence_band") or "exploratory"),
                validation_p05_arr_pct=p05_arr,
                validation_median_arr_pct=median_arr,
                frontier_p05_arr_pct=frontier_p05,
                frontier_median_arr_pct=frontier_median,
                frontier_delta_arr_pct=(frontier_p05 - records[-1].frontier_p05_arr_pct) if records else 0.0,
                validation_live_filled_rows=_safe_int(best_summary.get("validation_live_filled_rows")),
                generalization_ratio=_safe_float(best_summary.get("generalization_ratio")),
            )
        )
    return records


def write_tsv(path: Path, records: list[FrontierRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "\t".join(
            [
                "cycle",
                "finished_at",
                "hypothesis_name",
                "direction",
                "session_name",
                "evidence_band",
                "validation_p05_arr_pct",
                "validation_median_arr_pct",
                "frontier_p05_arr_pct",
                "frontier_median_arr_pct",
                "frontier_delta_arr_pct",
                "validation_live_filled_rows",
                "generalization_ratio",
            ]
        )
    ]
    for record in records:
        lines.append(
            "\t".join(
                [
                    str(record.cycle),
                    record.finished_at,
                    record.hypothesis_name,
                    record.direction,
                    record.session_name,
                    record.evidence_band,
                    f"{record.validation_p05_arr_pct:.4f}",
                    f"{record.validation_median_arr_pct:.4f}",
                    f"{record.frontier_p05_arr_pct:.4f}",
                    f"{record.frontier_median_arr_pct:.4f}",
                    f"{record.frontier_delta_arr_pct:.4f}",
                    str(record.validation_live_filled_rows),
                    f"{record.generalization_ratio:.4f}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n")


def build_latest_summary(records: list[FrontierRecord]) -> dict[str, Any]:
    latest = records[-1]
    exploratory = sum(1 for record in records if record.evidence_band == "exploratory")
    candidate = sum(1 for record in records if record.evidence_band == "candidate")
    validated = sum(1 for record in records if record.evidence_band == "validated")
    return {
        "metric_name": "validation_p05_arr_pct",
        "cycles_total": len(records),
        "frontier_p05_arr_pct": round(max(record.frontier_p05_arr_pct for record in records), 4),
        "frontier_median_arr_pct": round(max(record.frontier_median_arr_pct for record in records), 4),
        "latest_finished_at": latest.finished_at,
        "latest_hypothesis_name": latest.hypothesis_name,
        "latest_direction": latest.direction,
        "latest_session_name": latest.session_name,
        "latest_evidence_band": latest.evidence_band,
        "latest_validation_p05_arr_pct": round(latest.validation_p05_arr_pct, 4),
        "latest_validation_median_arr_pct": round(latest.validation_median_arr_pct, 4),
        "latest_validation_live_filled_rows": latest.validation_live_filled_rows,
        "latest_generalization_ratio": round(latest.generalization_ratio, 4),
        "evidence_counts": {
            "exploratory": exploratory,
            "candidate": candidate,
            "validated": validated,
        },
    }


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# BTC5 Hypothesis Frontier",
        "",
        "This is the best walk-forward BTC5 hypothesis found on each local autoresearch cycle. The chart is percentage-only and tracks validated return estimates, not dollars at risk.",
        "",
        f"- Cycles tracked: `{summary['cycles_total']}`",
        f"- Frontier P05 ARR: `{summary['frontier_p05_arr_pct']:.2f}%`",
        f"- Frontier median ARR: `{summary['frontier_median_arr_pct']:.2f}%`",
        f"- Latest hypothesis: `{summary['latest_hypothesis_name']}`",
        f"- Latest direction: `{summary['latest_direction']}`",
        f"- Latest session: `{summary['latest_session_name']}`",
        f"- Latest evidence band: `{summary['latest_evidence_band']}`",
        f"- Latest validation P05 ARR: `{summary['latest_validation_p05_arr_pct']:.2f}%`",
        f"- Latest validation median ARR: `{summary['latest_validation_median_arr_pct']:.2f}%`",
        f"- Latest validation fills: `{summary['latest_validation_live_filled_rows']}`",
        f"- Latest generalization ratio: `{summary['latest_generalization_ratio']:.4f}`",
        f"- Evidence counts: exploratory `{summary['evidence_counts']['exploratory']}`, candidate `{summary['evidence_counts']['candidate']}`, validated `{summary['evidence_counts']['validated']}`",
        f"- Latest finished at: `{summary['latest_finished_at']}`",
    ]
    path.write_text("\n".join(lines) + "\n")


def _polyline(points: list[tuple[float, float]], color: str, width: float) -> str:
    if not points:
        return ""
    encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline fill="none" stroke="{color}" stroke-width="{width}" points="{encoded}" />'


def render_svg(path: Path, records: list[FrontierRecord], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 1280
    height = 760
    left = 90
    right = width - 40
    top = 80
    middle = 430
    bottom = 680
    usable_width = max(1, right - left)
    arr_values = [
        value
        for record in records
        for value in (
            record.validation_p05_arr_pct,
            record.validation_median_arr_pct,
            record.frontier_p05_arr_pct,
        )
    ]
    arr_min = min(arr_values)
    arr_max = max(arr_values)
    if abs(arr_max - arr_min) < 1e-9:
        arr_min -= 1.0
        arr_max += 1.0
    fill_values = [record.validation_live_filled_rows for record in records] or [0]
    fill_min = 0
    fill_max = max(fill_values)
    if fill_max == fill_min:
        fill_max += 1

    def x_for(index: int) -> float:
        if len(records) == 1:
            return left + usable_width / 2.0
        return left + (usable_width * index / float(len(records) - 1))

    def y_for_arr(value: float) -> float:
        ratio = (value - arr_min) / (arr_max - arr_min)
        return middle - ratio * (middle - top)

    def y_for_fill(value: int) -> float:
        ratio = (value - fill_min) / float(fill_max - fill_min)
        return bottom - ratio * (bottom - (middle + 70))

    p05_points = [(x_for(index), y_for_arr(record.validation_p05_arr_pct)) for index, record in enumerate(records)]
    median_points = [(x_for(index), y_for_arr(record.validation_median_arr_pct)) for index, record in enumerate(records)]
    frontier_points = [(x_for(index), y_for_arr(record.frontier_p05_arr_pct)) for index, record in enumerate(records)]
    fill_points = [(x_for(index), y_for_fill(record.validation_live_filled_rows)) for index, record in enumerate(records)]
    arr_ticks = [arr_min, (arr_min + arr_max) / 2.0, arr_max]
    fill_ticks = [fill_min, (fill_min + fill_max) / 2.0, fill_max]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="BTC5 hypothesis frontier">
<rect width="{width}" height="{height}" fill="#F8F5EE" />
<text x="{left}" y="42" font-size="28" font-weight="700" fill="#1E1C18">BTC5 Hypothesis Frontier</text>
<text x="{left}" y="66" font-size="16" fill="#5F5A50">Best walk-forward hypothesis per local cycle. Latest {escape(summary['latest_hypothesis_name'])}; evidence {escape(summary['latest_evidence_band'])}; P05 {_fmt_pct(summary['latest_validation_p05_arr_pct'])}.</text>
<text x="{left}" y="{top - 14}" font-size="18" font-weight="600" fill="#1E1C18">Validated Return Estimate</text>
{''.join(f'<line x1="{left}" y1="{y_for_arr(value):.2f}" x2="{right}" y2="{y_for_arr(value):.2f}" stroke="#E6DED1" stroke-width="1" />' for value in arr_ticks)}
{''.join(f'<text x="{left - 12}" y="{y_for_arr(value) + 5:.2f}" text-anchor="end" font-size="16" fill="#5F5A50">{escape(_fmt_pct(value))}</text>' for value in arr_ticks)}
{_polyline(frontier_points, "#6C7E92", 2.2)}
{_polyline(p05_points, "#1B5E72", 3.4)}
{_polyline(median_points, "#C46B1A", 3.0)}
<text x="{right}" y="{top - 14}" text-anchor="end" font-size="15" fill="#1B5E72">Validation P05 ARR</text>
<text x="{right - 170}" y="{top - 14}" text-anchor="end" font-size="15" fill="#C46B1A">Validation median ARR</text>
<text x="{right - 365}" y="{top - 14}" text-anchor="end" font-size="15" fill="#6C7E92">Frontier P05 ARR</text>
<text x="{left}" y="{middle + 42}" font-size="18" font-weight="600" fill="#1E1C18">Validation Fill Count</text>
{''.join(f'<line x1="{left}" y1="{y_for_fill(int(value)):.2f}" x2="{right}" y2="{y_for_fill(int(value)):.2f}" stroke="#E6DED1" stroke-width="1" />' for value in fill_ticks)}
{''.join(f'<text x="{left - 12}" y="{y_for_fill(int(value)) + 5:.2f}" text-anchor="end" font-size="16" fill="#5F5A50">{int(value)}</text>' for value in fill_ticks)}
{_polyline(fill_points, "#2E8B57", 3.0)}
<text x="{right}" y="{middle + 42}" text-anchor="end" font-size="15" fill="#2E8B57">Validation fills</text>
<text x="{right}" y="{bottom + 34}" text-anchor="end" font-size="15" fill="#5F5A50">Last cycle {records[-1].cycle} at {escape(records[-1].finished_at)}</text>
</svg>
"""
    path.write_text(svg)


def main() -> int:
    args = parse_args()
    history_path = Path(args.history_jsonl)
    records = load_records(history_path)
    if not records:
        raise SystemExit(f"No hypothesis frontier history found at {history_path}")
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
