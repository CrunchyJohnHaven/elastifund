#!/usr/bin/env python3
"""Render a lane-local progress view from an append-only ledger."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path


@dataclass(frozen=True)
class LaneRecord:
    run_id: int
    timestamp: str
    status: str
    benchmark_score: float | None
    frontier_score: float | None
    selected_variant: str
    description: str
    packet_json: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render progress artifacts from a lane ledger.")
    parser.add_argument(
        "--ledger",
        default="research/results/calibration/results.tsv",
        help="Append-only lane ledger",
    )
    parser.add_argument(
        "--tsv-out",
        default="research/results/calibration/progress.tsv",
        help="Derived progress TSV path",
    )
    parser.add_argument(
        "--svg-out",
        default="research/results/calibration/progress.svg",
        help="Progress SVG path",
    )
    return parser.parse_args()


def load_ledger(path: str | Path) -> list[LaneRecord]:
    ledger = Path(path)
    if not ledger.exists():
        return []
    running_best: float | None = None
    records: list[LaneRecord] = []
    with ledger.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            score_text = (row.get("benchmark_score") or "").strip()
            score = float(score_text) if score_text else None
            if score is not None:
                running_best = score if running_best is None else max(running_best, score)
            records.append(
                LaneRecord(
                    run_id=int(row["run_id"]),
                    timestamp=row["timestamp"],
                    status=row["status"],
                    benchmark_score=score,
                    frontier_score=running_best,
                    selected_variant=row.get("selected_variant", ""),
                    description=row.get("description", ""),
                    packet_json=row.get("packet_json", ""),
                )
            )
    return records


def write_progress_tsv(path: str | Path, records: list[LaneRecord]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "\t".join(
            [
                "run_id",
                "timestamp",
                "benchmark_score",
                "frontier_score",
                "status",
                "selected_variant",
                "description",
                "packet_json",
            ]
        )
    ]
    for record in records:
        score = "" if record.benchmark_score is None else f"{record.benchmark_score:.6f}"
        frontier = "" if record.frontier_score is None else f"{record.frontier_score:.6f}"
        lines.append(
            "\t".join(
                [
                    str(record.run_id),
                    record.timestamp,
                    score,
                    frontier,
                    record.status,
                    sanitize_tsv(record.selected_variant),
                    sanitize_tsv(record.description),
                    sanitize_tsv(record.packet_json),
                ]
            )
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_svg(path: str | Path, records: list[LaneRecord]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    width = 1600
    height = 860
    margin_left = 110
    margin_right = 24
    margin_top = 50
    margin_bottom = 90
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    valid = [record for record in records if record.benchmark_score is not None]
    if not valid:
        output.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120">'
            '<rect width="100%" height="100%" fill="#f8f8f8"/>'
            '<text x="400" y="64" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#444">'
            "No calibration benchmark scores logged yet"
            "</text></svg>",
            encoding="utf-8",
        )
        return

    kept = [record for record in valid if record.status == "keep"]
    discarded = [record for record in valid if record.status == "discard"]
    scores = [record.benchmark_score for record in valid if record.benchmark_score is not None]
    metric_min = min(scores)
    metric_max = max(scores)
    spread = metric_max - metric_min
    margin = spread * 0.15 if spread > 0 else max(abs(metric_max) * 0.05, 0.05)
    y_min = metric_min - margin
    y_max = metric_max + margin

    def x_pos(run_id: int) -> float:
        if len(records) == 1:
            return margin_left + plot_width / 2
        return margin_left + ((run_id - 1) / (len(records) - 1)) * plot_width

    def y_pos(value: float) -> float:
        if y_max == y_min:
            return margin_top + plot_height / 2
        pct = (value - y_min) / (y_max - y_min)
        return margin_top + (1.0 - pct) * plot_height

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f2f2f2"/>',
        f'<text x="{width / 2:.1f}" y="28" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#222">'
        f'Calibration Lane Progress: {len(records)} Runs, {len(kept)} Kept High-Water Marks'
        "</text>",
    ]

    for tick in range(6):
        value = y_min + ((y_max - y_min) * tick / 5)
        y = y_pos(value)
        svg.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#d7d7d7" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#555">'
            f"{value:.3f}</text>"
        )

    x_ticks = min(9, len(records))
    for tick in range(x_ticks):
        run_id = round(1 + ((len(records) - 1) * tick / max(1, x_ticks - 1)))
        x = x_pos(run_id)
        svg.append(
            f'<line x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{height - margin_bottom}" stroke="#e1e1e1" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{x:.2f}" y="{height - margin_bottom + 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#555">'
            f"{run_id}</text>"
        )

    svg.append(
        f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#555" stroke-width="1.5"/>'
    )
    svg.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#555" stroke-width="1.5"/>'
    )

    step_points: list[tuple[float, float]] = []
    previous_y: float | None = None
    for record in kept:
        assert record.benchmark_score is not None
        x = x_pos(record.run_id)
        y = y_pos(record.benchmark_score)
        if not step_points:
            step_points.append((x, y))
        else:
            assert previous_y is not None
            step_points.append((x, previous_y))
            step_points.append((x, y))
        previous_y = y
    if step_points:
        points_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in step_points)
        svg.append(
            f'<polyline points="{points_text}" fill="none" stroke="#0d7a35" stroke-width="3" stroke-linejoin="round"/>'
        )

    for record in discarded:
        assert record.benchmark_score is not None
        x = x_pos(record.run_id)
        y = y_pos(record.benchmark_score)
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6.5" fill="#b51f1f" opacity="0.9"/>')

    for record in kept:
        assert record.benchmark_score is not None
        x = x_pos(record.run_id)
        y = y_pos(record.benchmark_score)
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7.5" fill="#0d7a35" stroke="#ffffff" stroke-width="2"/>')
        svg.append(
            f'<text x="{x + 10:.2f}" y="{y - 10:.2f}" font-family="Arial, sans-serif" font-size="11" fill="#222">'
            f"{escape(record.selected_variant or record.description or f'run {record.run_id}')}"
            "</text>"
        )

    svg.append(
        f'<text x="{width / 2:.1f}" y="{height - 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#444">'
        "Run Number"
        "</text>"
    )
    svg.append(
        f'<text x="30" y="{height / 2:.1f}" transform="rotate(-90 30 {height / 2:.1f})" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#444">'
        "Benchmark Score (higher is better)"
        "</text>"
    )
    svg.append("</svg>")

    output.write_text("\n".join(svg), encoding="utf-8")


def render_progress(ledger_path: str | Path, tsv_out: str | Path, svg_out: str | Path) -> list[LaneRecord]:
    records = load_ledger(ledger_path)
    write_progress_tsv(tsv_out, records)
    render_svg(svg_out, records)
    return records


def sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def main() -> None:
    args = parse_args()
    records = render_progress(args.ledger, args.tsv_out, args.svg_out)
    print(f"Wrote {args.tsv_out}")
    print(f"Wrote {args.svg_out}")
    print(f"Records: {len(records)}")


if __name__ == "__main__":
    main()
