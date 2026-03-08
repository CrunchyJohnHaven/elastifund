#!/usr/bin/env python3
"""Render an autoresearch-style progress ledger and SVG for Elastifund runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path


@dataclass
class ExperimentRecord:
    experiment: int
    artifact: str
    timestamp: str
    metric: float | None
    status: str
    top_hypothesis: str
    recommendation: str
    description: str


METRIC_LABELS = {
    "score": "Top hypothesis composite score (higher is better)",
    "ev_taker": "Top hypothesis taker EV (higher is better)",
    "win_rate": "Top hypothesis win rate (higher is better)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an autoresearch-style progress view for Elastifund runs.")
    parser.add_argument(
        "--input-glob",
        default="reports/run_*_metrics.json",
        help="Glob for metrics artifacts",
    )
    parser.add_argument(
        "--metric",
        choices=sorted(METRIC_LABELS),
        default="score",
        help="Top-evaluation field to track",
    )
    parser.add_argument(
        "--tsv-out",
        default="research/autoresearch_progress.tsv",
        help="Output TSV path",
    )
    parser.add_argument(
        "--svg-out",
        default="research/autoresearch_progress.svg",
        help="Output SVG path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_records(args.input_glob, args.metric)
    if not records:
        raise SystemExit(f"No run metrics matched {args.input_glob!r}")

    tsv_path = Path(args.tsv_out)
    svg_path = Path(args.svg_out)
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)

    write_tsv(tsv_path, records)
    render_svg(svg_path, records, args.metric)

    print(f"Wrote {tsv_path}")
    print(f"Wrote {svg_path}")


def load_records(input_glob: str, metric_name: str) -> list[ExperimentRecord]:
    records: list[ExperimentRecord] = []
    running_best: float | None = None

    for experiment, path in enumerate(sorted(Path().glob(input_glob)), start=1):
        payload = json.loads(path.read_text())
        evaluations = payload.get("evaluations") or []
        top = evaluations[0] if evaluations else {}
        metric = extract_metric(top, metric_name)
        top_hypothesis = str(top.get("name") or "n/a")
        recommendation = str(payload.get("recommendation") or "n/a")
        is_first_keep = metric is not None and running_best is None

        if metric is None:
            status = "CRASH"
        elif running_best is None or metric > running_best:
            status = "KEEP"
            running_best = metric
        else:
            status = "DISCARD"

        if status == "KEEP" and is_first_keep:
            description = "baseline"
        elif status == "KEEP":
            description = top_hypothesis
        elif top_hypothesis != "n/a":
            description = top_hypothesis
        else:
            description = recommendation

        records.append(
            ExperimentRecord(
                experiment=experiment,
                artifact=path.name,
                timestamp=str(payload.get("timestamp") or "n/a"),
                metric=metric,
                status=status,
                top_hypothesis=top_hypothesis,
                recommendation=recommendation,
                description=description,
            )
        )

    return records


def extract_metric(top_eval: dict[str, object], metric_name: str) -> float | None:
    if not top_eval:
        return None

    if metric_name == "score":
        value = top_eval.get("score")
    else:
        metrics = top_eval.get("metrics") or {}
        if not isinstance(metrics, dict):
            return None
        value = metrics.get(metric_name)

    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def write_tsv(path: Path, records: list[ExperimentRecord]) -> None:
    lines = [
        "\t".join(
            [
                "experiment",
                "artifact",
                "timestamp",
                "metric",
                "status",
                "top_hypothesis",
                "recommendation",
                "description",
            ]
        )
    ]

    for record in records:
        metric = "" if record.metric is None else f"{record.metric:.6f}"
        lines.append(
            "\t".join(
                [
                    str(record.experiment),
                    record.artifact,
                    record.timestamp,
                    metric,
                    record.status.lower(),
                    sanitize_tsv(record.top_hypothesis),
                    sanitize_tsv(record.recommendation),
                    sanitize_tsv(record.description),
                ]
            )
        )

    path.write_text("\n".join(lines) + "\n")


def sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def render_svg(path: Path, records: list[ExperimentRecord], metric_name: str) -> None:
    width = 1600
    height = 860
    margin_left = 110
    margin_right = 24
    margin_top = 50
    margin_bottom = 90
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    valid = [record for record in records if record.metric is not None]
    if not valid:
        raise SystemExit("No valid metrics available to plot")

    kept = [record for record in valid if record.status == "KEEP"]
    discarded = [record for record in valid if record.status == "DISCARD"]

    metric_values = [record.metric for record in valid if record.metric is not None]
    assert metric_values
    metric_min = min(metric_values)
    metric_max = max(metric_values)
    spread = metric_max - metric_min
    margin = spread * 0.15 if spread > 0 else max(abs(metric_max) * 0.05, 0.05)
    y_min = metric_min - margin
    y_max = metric_max + margin

    def x_pos(experiment: int) -> float:
        if len(records) == 1:
            return margin_left + plot_width / 2
        return margin_left + ((experiment - 1) / (len(records) - 1)) * plot_width

    def y_pos(value: float) -> float:
        if y_max == y_min:
            return margin_top + plot_height / 2
        pct = (value - y_min) / (y_max - y_min)
        return margin_top + (1.0 - pct) * plot_height

    y_ticks = 6
    x_ticks = min(9, len(records))
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f2f2f2"/>',
        f'<text x="{width / 2:.1f}" y="28" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#222">'
        f'Elastifund Research Progress: {len(records)} Runs, {len(kept)} Kept High-Water Marks'
        "</text>",
    ]

    for tick in range(y_ticks):
        value = y_min + ((y_max - y_min) * tick / max(1, y_ticks - 1))
        y = y_pos(value)
        svg.append(f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#d7d7d7" stroke-width="1"/>')
        svg.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#555">'
            f"{value:.3f}</text>"
        )

    for tick in range(x_ticks):
        experiment = round(1 + ((len(records) - 1) * tick / max(1, x_ticks - 1)))
        x = x_pos(experiment)
        svg.append(f'<line x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{height - margin_bottom}" stroke="#e1e1e1" stroke-width="1"/>')
        svg.append(
            f'<text x="{x:.2f}" y="{height - margin_bottom + 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#555">'
            f"{experiment}</text>"
        )

    svg.append(
        f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#555" stroke-width="1.5"/>'
    )
    svg.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#555" stroke-width="1.5"/>'
    )

    step_points: list[tuple[float, float]] = []
    if kept:
        previous_y: float | None = None
        for record in kept:
            assert record.metric is not None
            x = x_pos(record.experiment)
            y = y_pos(record.metric)
            if not step_points:
                step_points.append((x, y))
            elif previous_y is not None:
                step_points.append((x, previous_y))
                step_points.append((x, y))
            previous_y = y

        point_str = " ".join(f"{x:.2f},{y:.2f}" for x, y in step_points)
        svg.append(
            f'<polyline points="{point_str}" fill="none" stroke="#27ae60" stroke-width="3" opacity="0.8"/>'
        )

    for record in discarded:
        assert record.metric is not None
        svg.append(
            f'<circle cx="{x_pos(record.experiment):.2f}" cy="{y_pos(record.metric):.2f}" r="4" fill="#c8c8c8" opacity="0.7"/>'
        )

    for record in kept:
        assert record.metric is not None
        cx = x_pos(record.experiment)
        cy = y_pos(record.metric)
        svg.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="6" fill="#2ecc71" stroke="#222" stroke-width="1"/>')
        label = escape(shorten(record.description, 44))
        svg.append(
            f'<text transform="translate({cx + 10:.2f},{cy - 8:.2f}) rotate(-30)" '
            'font-family="Arial, sans-serif" font-size="12" fill="#1a7a3a">'
            f"{label}</text>"
        )

    legend_x = width - 230
    legend_y = 82
    svg.extend(
        [
            f'<rect x="{legend_x}" y="{legend_y - 24}" width="200" height="84" rx="6" fill="#ffffff" stroke="#d0d0d0"/>',
            f'<circle cx="{legend_x + 20}" cy="{legend_y}" r="4" fill="#c8c8c8" opacity="0.7"/>',
            f'<text x="{legend_x + 40}" y="{legend_y + 4}" font-family="Arial, sans-serif" font-size="12" fill="#333">Discarded</text>',
            f'<circle cx="{legend_x + 20}" cy="{legend_y + 24}" r="6" fill="#2ecc71" stroke="#222" stroke-width="1"/>',
            f'<text x="{legend_x + 40}" y="{legend_y + 28}" font-family="Arial, sans-serif" font-size="12" fill="#333">Kept</text>',
            f'<line x1="{legend_x + 12}" y1="{legend_y + 50}" x2="{legend_x + 28}" y2="{legend_y + 50}" stroke="#27ae60" stroke-width="3" opacity="0.8"/>',
            f'<text x="{legend_x + 40}" y="{legend_y + 54}" font-family="Arial, sans-serif" font-size="12" fill="#333">Running best</text>',
        ]
    )

    svg.extend(
        [
            f'<text x="{width / 2:.1f}" y="{height - 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="#222">Experiment #</text>',
            f'<text transform="translate(28,{height / 2:.1f}) rotate(-90)" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="#222">{escape(METRIC_LABELS[metric_name])}</text>',
            "</svg>",
        ]
    )

    path.write_text("\n".join(svg) + "\n")


def shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


if __name__ == "__main__":
    main()
