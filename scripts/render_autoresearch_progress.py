#!/usr/bin/env python3
"""Render autoresearch-style progress and velocity artifacts for Elastifund runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
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
    frontier_metric: float | None = None
    frontier_delta: float | None = None
    hours_since_start: float | None = None
    hours_since_prev: float | None = None
    hours_since_prev_keep: float | None = None
    velocity_per_hour: float | None = None
    keep_velocity_per_hour: float | None = None
    rolling_velocity_per_hour: float | None = None
    acceleration_per_hour2: float | None = None


METRIC_LABELS = {
    "score": "Top hypothesis composite score (higher is better)",
    "ev_taker": "Top hypothesis taker EV (higher is better)",
    "win_rate": "Top hypothesis win rate (higher is better)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render autoresearch-style progress and velocity views.")
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
        help="Output TSV path for the progress ledger",
    )
    parser.add_argument(
        "--svg-out",
        default="research/autoresearch_progress.svg",
        help="Output SVG path for the progress chart",
    )
    parser.add_argument(
        "--velocity-tsv-out",
        default="research/autoresearch_velocity.tsv",
        help="Output TSV path for the velocity ledger",
    )
    parser.add_argument(
        "--velocity-svg-out",
        default="research/autoresearch_velocity.svg",
        help="Output SVG path for the velocity chart",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=5,
        help="Trailing experiment window used for rolling velocity slope",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_records(args.input_glob, args.metric, rolling_window=args.rolling_window)
    if not records:
        raise SystemExit(f"No run metrics matched {args.input_glob!r}")

    progress_tsv = Path(args.tsv_out)
    progress_svg = Path(args.svg_out)
    velocity_tsv = Path(args.velocity_tsv_out)
    velocity_svg = Path(args.velocity_svg_out)
    for output in (progress_tsv, progress_svg, velocity_tsv, velocity_svg):
        output.parent.mkdir(parents=True, exist_ok=True)

    write_progress_tsv(progress_tsv, records)
    render_progress_svg(progress_svg, records, args.metric)
    write_velocity_tsv(velocity_tsv, records)
    render_velocity_svg(velocity_svg, records, args.metric, rolling_window=args.rolling_window)

    print(f"Wrote {progress_tsv}")
    print(f"Wrote {progress_svg}")
    print(f"Wrote {velocity_tsv}")
    print(f"Wrote {velocity_svg}")


def load_records(input_glob: str, metric_name: str, *, rolling_window: int = 5) -> list[ExperimentRecord]:
    if rolling_window < 2:
        raise ValueError("rolling_window must be at least 2")

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

    enrich_records(records, rolling_window=rolling_window)
    return records


def enrich_records(records: list[ExperimentRecord], *, rolling_window: int) -> None:
    first_timestamp: datetime | None = None
    for record in records:
        parsed = parse_timestamp(record.timestamp)
        if parsed is not None:
            first_timestamp = parsed
            break
    previous_timestamp: datetime | None = None
    previous_keep_timestamp: datetime | None = None
    previous_frontier: float | None = None

    for record in records:
        timestamp = parse_timestamp(record.timestamp)
        record.hours_since_start = diff_hours(first_timestamp, timestamp)
        record.hours_since_prev = diff_hours(previous_timestamp, timestamp)
        record.frontier_metric = frontier_value(previous_frontier, record.metric)
        record.frontier_delta = compute_frontier_delta(previous_frontier, record.frontier_metric)
        record.hours_since_prev_keep = diff_hours(previous_keep_timestamp, timestamp)

        if record.frontier_delta is not None and record.frontier_delta > 0:
            record.velocity_per_hour = safe_rate(record.frontier_delta, record.hours_since_prev)
            record.keep_velocity_per_hour = safe_rate(record.frontier_delta, record.hours_since_prev_keep)
        elif record.frontier_delta == 0:
            record.velocity_per_hour = 0.0 if record.hours_since_prev is not None else None
            record.keep_velocity_per_hour = None

        if record.status == "KEEP" and timestamp is not None:
            previous_keep_timestamp = timestamp
        if timestamp is not None:
            previous_timestamp = timestamp
        if record.frontier_metric is not None:
            previous_frontier = record.frontier_metric

    previous_rolling_velocity: float | None = None
    for index, record in enumerate(records):
        window = records[max(0, index - rolling_window + 1) : index + 1]
        record.rolling_velocity_per_hour = rolling_velocity(window)
        if record.rolling_velocity_per_hour is not None:
            record.acceleration_per_hour2 = safe_rate(
                None
                if previous_rolling_velocity is None
                else record.rolling_velocity_per_hour - previous_rolling_velocity,
                record.hours_since_prev,
            )
            previous_rolling_velocity = record.rolling_velocity_per_hour


def frontier_value(previous_frontier: float | None, metric: float | None) -> float | None:
    if metric is None:
        return previous_frontier
    if previous_frontier is None:
        return metric
    return max(previous_frontier, metric)


def compute_frontier_delta(previous_frontier: float | None, frontier_metric: float | None) -> float | None:
    if previous_frontier is None or frontier_metric is None:
        return None
    return max(0.0, frontier_metric - previous_frontier)


def safe_rate(delta: float | None, hours: float | None) -> float | None:
    if delta is None or hours is None or hours <= 0:
        return None
    return delta / hours


def rolling_velocity(window: list[ExperimentRecord]) -> float | None:
    points = [
        (record.hours_since_start, record.frontier_metric)
        for record in window
        if record.hours_since_start is not None and record.frontier_metric is not None
    ]
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator <= 0:
        return None
    numerator = sum((x_value - mean_x) * (y_value - mean_y) for x_value, y_value in zip(xs, ys))
    return numerator / denominator


def parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text or text == "n/a":
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def diff_hours(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600.0


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


def write_progress_tsv(path: Path, records: list[ExperimentRecord]) -> None:
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

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_velocity_tsv(path: Path, records: list[ExperimentRecord]) -> None:
    lines = [
        "\t".join(
            [
                "experiment",
                "artifact",
                "timestamp",
                "metric",
                "status",
                "frontier_metric",
                "frontier_delta",
                "hours_since_start",
                "hours_since_prev",
                "hours_since_prev_keep",
                "velocity_per_hour",
                "keep_velocity_per_hour",
                "rolling_velocity_per_hour",
                "acceleration_per_hour2",
                "top_hypothesis",
                "description",
            ]
        )
    ]

    for record in records:
        lines.append(
            "\t".join(
                [
                    str(record.experiment),
                    record.artifact,
                    record.timestamp,
                    format_float(record.metric),
                    record.status.lower(),
                    format_float(record.frontier_metric),
                    format_float(record.frontier_delta),
                    format_float(record.hours_since_start),
                    format_float(record.hours_since_prev),
                    format_float(record.hours_since_prev_keep),
                    format_float(record.velocity_per_hour),
                    format_float(record.keep_velocity_per_hour),
                    format_float(record.rolling_velocity_per_hour),
                    format_float(record.acceleration_per_hour2),
                    sanitize_tsv(record.top_hypothesis),
                    sanitize_tsv(record.description),
                ]
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def format_float(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def render_progress_svg(path: Path, records: list[ExperimentRecord], metric_name: str) -> None:
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
    y_min, y_max = chart_bounds(metric_values)

    def x_pos(experiment: int) -> float:
        if len(records) == 1:
            return margin_left + plot_width / 2
        return margin_left + ((experiment - 1) / (len(records) - 1)) * plot_width

    def y_pos(value: float) -> float:
        return scale_y(value, y_min=y_min, y_max=y_max, top=margin_top, height=plot_height)

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

    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def render_velocity_svg(path: Path, records: list[ExperimentRecord], metric_name: str, *, rolling_window: int) -> None:
    valid = [record for record in records if record.metric is not None]
    if not valid:
        raise SystemExit("No valid metrics available to plot")

    width = 1600
    height = 980
    margin_left = 105
    margin_right = 28
    margin_top = 62
    margin_bottom = 82
    panel_gap = 78
    panel_height = 300
    plot_width = width - margin_left - margin_right
    top_panel_top = 120
    bottom_panel_top = top_panel_top + panel_height + panel_gap

    use_time_axis = can_use_time_axis(valid)
    x_values = [record.hours_since_start if use_time_axis else float(record.experiment) for record in valid]
    assert x_values
    x_min = min(x_values)
    x_max = max(x_values)
    if x_min == x_max:
        x_min -= 0.5
        x_max += 0.5

    frontier_values = [
        value
        for record in valid
        for value in (record.metric, record.frontier_metric)
        if value is not None
    ]
    velocity_values = [
        value
        for record in valid
        for value in (record.velocity_per_hour, record.rolling_velocity_per_hour)
        if value is not None
    ]
    frontier_min, frontier_max = chart_bounds(frontier_values)
    velocity_min, velocity_max = chart_bounds(velocity_values or [0.0], include_zero=True)
    latest_rolling_velocity = latest_value(valid, "rolling_velocity_per_hour")
    latest_acceleration = latest_value(valid, "acceleration_per_hour2")
    total_hours = max(0.0, x_max - x_min)
    total_frontier_change = 0.0
    if frontier_values:
        total_frontier_change = frontier_values[-1] - frontier_values[0]
    keep_count = sum(1 for record in valid if record.status == "KEEP")
    average_runs_per_hour = (len(records) - 1) / total_hours if total_hours > 0 else 0.0
    trend_label = classify_trend(latest_acceleration)

    def x_pos(record: ExperimentRecord) -> float:
        x_value = record.hours_since_start if use_time_axis else float(record.experiment)
        assert x_value is not None
        return margin_left + ((x_value - x_min) / (x_max - x_min)) * plot_width

    def frontier_y(value: float) -> float:
        return scale_y(value, y_min=frontier_min, y_max=frontier_max, top=top_panel_top, height=panel_height)

    def velocity_y(value: float) -> float:
        return scale_y(value, y_min=velocity_min, y_max=velocity_max, top=bottom_panel_top, height=panel_height)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f5f4ef"/>',
        f'<text x="{width / 2:.1f}" y="28" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#1f1f1f">'
        "Elastifund Improvement Velocity"
        "</text>",
        f'<text x="{width / 2:.1f}" y="52" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#4c4c4c">'
        f'{len(records)} runs, {keep_count} kept marks, frontier change {total_frontier_change:.4f}, latest {rolling_window}-run slope {safe_display(latest_rolling_velocity)} / hour, trend {trend_label}'
        "</text>",
        f'<text x="{width / 2:.1f}" y="72" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#666">'
        f'Average cadence {average_runs_per_hour:.2f} runs/hour. Metric: {escape(METRIC_LABELS[metric_name])}'
        "</text>",
    ]

    draw_panel(
        svg,
        x_min=x_min,
        x_max=x_max,
        y_min=frontier_min,
        y_max=frontier_max,
        left=margin_left,
        right=width - margin_right,
        top=top_panel_top,
        height=panel_height,
        title="Running Frontier",
        y_label=METRIC_LABELS[metric_name],
        x_axis_label=time_axis_label(use_time_axis),
    )
    draw_panel(
        svg,
        x_min=x_min,
        x_max=x_max,
        y_min=velocity_min,
        y_max=velocity_max,
        left=margin_left,
        right=width - margin_right,
        top=bottom_panel_top,
        height=panel_height,
        title=f"Frontier Velocity ({rolling_window}-run rolling slope)",
        y_label="Improvement rate per hour",
        x_axis_label=time_axis_label(use_time_axis),
    )

    zero_line = velocity_y(0.0)
    svg.append(
        f'<line x1="{margin_left}" y1="{zero_line:.2f}" x2="{width - margin_right}" y2="{zero_line:.2f}" stroke="#8a8a8a" stroke-dasharray="6 6" stroke-width="1.2"/>'
    )

    raw_metric_points = [
        (x_pos(record), frontier_y(record.metric))
        for record in valid
        if record.metric is not None
    ]
    svg.append(
        '<polyline points="{}" fill="none" stroke="#c6c6c6" stroke-width="2" opacity="0.75"/>'.format(
            " ".join(f"{x:.2f},{y:.2f}" for x, y in raw_metric_points)
        )
    )

    frontier_points = [
        (x_pos(record), frontier_y(record.frontier_metric))
        for record in valid
        if record.frontier_metric is not None
    ]
    svg.append(
        '<polyline points="{}" fill="none" stroke="#167c5b" stroke-width="3.4" stroke-linejoin="round" stroke-linecap="round"/>'.format(
            " ".join(f"{x:.2f},{y:.2f}" for x, y in frontier_points)
        )
    )

    for record in valid:
        if record.metric is None or record.frontier_metric is None:
            continue
        cx = x_pos(record)
        metric_y = frontier_y(record.metric)
        frontier_marker_y = frontier_y(record.frontier_metric)
        if record.status == "KEEP":
            svg.append(f'<circle cx="{cx:.2f}" cy="{metric_y:.2f}" r="5.5" fill="#167c5b" stroke="#ffffff" stroke-width="1.5"/>')
            label = escape(shorten(record.description, 28))
            svg.append(
                f'<text x="{cx + 8:.2f}" y="{frontier_marker_y - 8:.2f}" font-family="Arial, sans-serif" font-size="11" fill="#155440">{label}</text>'
            )
        elif record.status == "DISCARD":
            svg.append(f'<circle cx="{cx:.2f}" cy="{metric_y:.2f}" r="4.2" fill="#b8b8b8"/>')
        else:
            svg.append(f'<circle cx="{cx:.2f}" cy="{metric_y:.2f}" r="4.2" fill="#c0392b"/>')

    for record in valid:
        if record.velocity_per_hour is None:
            continue
        cx = x_pos(record)
        bar_top = velocity_y(max(0.0, record.velocity_per_hour))
        bar_bottom = velocity_y(min(0.0, record.velocity_per_hour))
        color = "#2f855a" if record.velocity_per_hour > 0 else "#b7bcc4"
        svg.append(
            f'<rect x="{cx - 4:.2f}" y="{min(bar_top, bar_bottom):.2f}" width="8" height="{abs(bar_bottom - bar_top):.2f}" fill="{color}" opacity="0.85"/>'
        )

    rolling_points = [
        (x_pos(record), velocity_y(record.rolling_velocity_per_hour))
        for record in valid
        if record.rolling_velocity_per_hour is not None
    ]
    if rolling_points:
        svg.append(
            '<polyline points="{}" fill="none" stroke="#0f4c81" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'.format(
                " ".join(f"{x:.2f},{y:.2f}" for x, y in rolling_points)
            )
        )
        for x_value, y_value in rolling_points:
            svg.append(f'<circle cx="{x_value:.2f}" cy="{y_value:.2f}" r="3.3" fill="#0f4c81"/>')

    legend_x = width - 272
    legend_y = 88
    svg.extend(
        [
            f'<rect x="{legend_x}" y="{legend_y}" width="236" height="106" rx="8" fill="#ffffff" stroke="#d4d0c8"/>',
            f'<line x1="{legend_x + 16}" y1="{legend_y + 24}" x2="{legend_x + 44}" y2="{legend_y + 24}" stroke="#167c5b" stroke-width="3.4"/>',
            f'<text x="{legend_x + 56}" y="{legend_y + 28}" font-family="Arial, sans-serif" font-size="12" fill="#333">Running frontier</text>',
            f'<rect x="{legend_x + 12}" y="{legend_y + 40}" width="10" height="16" fill="#2f855a" opacity="0.85"/>',
            f'<text x="{legend_x + 56}" y="{legend_y + 53}" font-family="Arial, sans-serif" font-size="12" fill="#333">Improvement spike</text>',
            f'<line x1="{legend_x + 16}" y1="{legend_y + 72}" x2="{legend_x + 44}" y2="{legend_y + 72}" stroke="#0f4c81" stroke-width="3"/>',
            f'<text x="{legend_x + 56}" y="{legend_y + 76}" font-family="Arial, sans-serif" font-size="12" fill="#333">Rolling velocity</text>',
            f'<circle cx="{legend_x + 20}" cy="{legend_y + 92}" r="4.6" fill="#167c5b" stroke="#ffffff" stroke-width="1.2"/>',
            f'<text x="{legend_x + 56}" y="{legend_y + 96}" font-family="Arial, sans-serif" font-size="12" fill="#333">Kept high-water mark</text>',
        ]
    )

    if latest_acceleration is not None:
        svg.append(
            f'<text x="{margin_left}" y="{height - 28}" font-family="Arial, sans-serif" font-size="12" fill="#666">'
            f'Latest acceleration: {latest_acceleration:+.4f} per hour²'
            "</text>"
        )

    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def draw_panel(
    svg: list[str],
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    left: float,
    right: float,
    top: float,
    height: float,
    title: str,
    y_label: str,
    x_axis_label: str,
) -> None:
    bottom = top + height
    svg.append(f'<rect x="{left}" y="{top}" width="{right - left}" height="{height}" fill="#ffffff" stroke="#d8d2c9"/>')
    svg.append(
        f'<text x="{left}" y="{top - 14}" font-family="Arial, sans-serif" font-size="14" fill="#1f1f1f">{escape(title)}</text>'
    )

    for tick in range(6):
        value = y_min + ((y_max - y_min) * tick / 5)
        y = scale_y(value, y_min=y_min, y_max=y_max, top=top, height=height)
        svg.append(f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" stroke="#ece8e2" stroke-width="1"/>')
        svg.append(
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="11" fill="#666">'
            f"{value:.3f}</text>"
        )

    for tick in range(6):
        value = x_min + ((x_max - x_min) * tick / 5)
        x = left + ((value - x_min) / (x_max - x_min)) * (right - left)
        svg.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{bottom}" stroke="#f0ede8" stroke-width="1"/>')
        label = f"{value:.1f}" if x_axis_label.startswith("Elapsed") else f"{round(value)}"
        svg.append(
            f'<text x="{x:.2f}" y="{bottom + 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#666">{label}</text>'
        )

    svg.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#5e5a55" stroke-width="1.5"/>')
    svg.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#5e5a55" stroke-width="1.5"/>')
    svg.append(
        f'<text x="{(left + right) / 2:.1f}" y="{bottom + 44}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#444">{escape(x_axis_label)}</text>'
    )
    svg.append(
        f'<text transform="translate({left - 72:.1f},{top + height / 2:.1f}) rotate(-90)" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#444">{escape(y_label)}</text>'
    )


def chart_bounds(values: list[float], *, include_zero: bool = False) -> tuple[float, float]:
    if include_zero:
        values = [*values, 0.0]
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum
    margin = spread * 0.15 if spread > 0 else max(abs(maximum) * 0.08, 0.05)
    return minimum - margin, maximum + margin


def scale_y(value: float, *, y_min: float, y_max: float, top: float, height: float) -> float:
    if y_max == y_min:
        return top + height / 2
    pct = (value - y_min) / (y_max - y_min)
    return top + (1.0 - pct) * height


def can_use_time_axis(records: list[ExperimentRecord]) -> bool:
    values = sorted({record.hours_since_start for record in records if record.hours_since_start is not None})
    return len(values) >= 2


def latest_value(records: list[ExperimentRecord], field: str) -> float | None:
    for record in reversed(records):
        value = getattr(record, field)
        if value is not None:
            return float(value)
    return None


def classify_trend(acceleration: float | None) -> str:
    if acceleration is None:
        return "insufficient data"
    if acceleration > 1e-6:
        return "rising"
    if acceleration < -1e-6:
        return "slowing"
    return "flat"


def safe_display(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def time_axis_label(use_time_axis: bool) -> str:
    return "Elapsed hours since first run" if use_time_axis else "Experiment #"


def shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


if __name__ == "__main__":
    main()
