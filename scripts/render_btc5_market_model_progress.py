#!/usr/bin/env python3
"""Render the BTC5 market-model progress chart from the lane ledger."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProgressRecord:
    experiment_id: int
    status: str
    loss: float | None
    keep: bool
    champion_id: int | None
    candidate_label: str
    decision_reason: str


DISCARD_COLOR = "#b8b8b8"
KEEP_COLOR = "#1f7a3a"
CRASH_COLOR = "#5f5f5f"
CRASH_TEXT = "#8a2e1f"
BACKGROUND = "#f7f5ef"
GRID = "#d8d2c6"
AXIS = "#363636"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        default="reports/autoresearch/btc5_market/results.jsonl",
        help="Append-only JSONL results ledger",
    )
    parser.add_argument(
        "--svg-out",
        default="research/btc5_market_model_progress.svg",
        help="Output SVG path",
    )
    parser.add_argument(
        "--title",
        default="BTC5 Market-Model Benchmark Progress",
        help="Chart title",
    )
    parser.add_argument(
        "--y-label",
        default="BTC5 market-model loss (lower is better)",
        help="Y-axis label",
    )
    return parser.parse_args()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_records(path: str | Path) -> list[ProgressRecord]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    records: list[ProgressRecord] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        loss = _safe_float(payload.get("loss"))
        status = str(payload.get("status") or "discard").strip().lower()
        keep = bool(payload.get("keep")) or status == "keep"
        records.append(
            ProgressRecord(
                experiment_id=int(payload.get("experiment_id") or 0),
                status=status,
                loss=loss,
                keep=keep,
                champion_id=(
                    int(payload["champion_id"])
                    if payload.get("champion_id") not in (None, "")
                    else None
                ),
                candidate_label=str(
                    payload.get("candidate_model_name")
                    or payload.get("candidate_label")
                    or payload.get("candidate_hash", "")
                ).strip(),
                decision_reason=str(payload.get("decision_reason") or "").strip(),
            )
        )
    return records


def _write_empty_svg(path: Path, *, title: str) -> None:
    path.write_text(
        "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="160" viewBox="0 0 960 160">',
                f'<rect width="100%" height="100%" fill="{BACKGROUND}"/>',
                f'<text x="480" y="56" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" fill="{AXIS}">{escape(title)}</text>',
                '<text x="480" y="98" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#666666">No BTC5 market-model experiments logged yet</text>',
                "</svg>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def render_progress(
    records: list[ProgressRecord],
    *,
    svg_out: str | Path,
    title: str,
    y_label: str,
) -> None:
    output = Path(svg_out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        _write_empty_svg(output, title=title)
        return

    width = 1600
    height = 900
    left = 125
    right = width - 40
    top = 80
    bottom = height - 130
    plot_width = right - left
    plot_height = bottom - top
    crash_lane_y = top + 28

    indexed_records = list(enumerate(records))
    scored_records = [
        (index, record)
        for index, record in indexed_records
        if record.loss is not None and record.status != "crash"
    ]
    kept = [(index, record) for index, record in scored_records if record.status == "keep"]
    discarded = [(index, record) for index, record in scored_records if record.status == "discard"]
    crashed = [(index, record) for index, record in indexed_records if record.status == "crash"]

    def x_pos(index: int) -> float:
        if len(records) == 1:
            return left + (plot_width / 2.0)
        return left + (index / float(max(1, len(records) - 1))) * plot_width

    if scored_records:
        losses = [record.loss for _, record in scored_records if record.loss is not None]
        assert losses
        min_loss = min(losses)
        max_loss = max(losses)
        spread = max_loss - min_loss
        margin = spread * 0.15 if spread > 0 else max(abs(min_loss) * 0.10, 0.10)
        y_min = min_loss - margin
        y_max = max_loss + margin

        def y_pos(loss: float) -> float:
            if y_max == y_min:
                return top + (plot_height / 2.0)
            ratio = (loss - y_min) / (y_max - y_min)
            return top + ((1.0 - ratio) * plot_height)

    else:
        y_min = None
        y_max = None

        def y_pos(loss: float) -> float:
            return top + (plot_height / 2.0)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{BACKGROUND}"/>',
        f'<text x="{width / 2:.1f}" y="38" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" fill="{AXIS}">{escape(title)}</text>',
    ]

    if scored_records:
        assert y_min is not None and y_max is not None
        for tick in range(6):
            value = y_min + ((y_max - y_min) * tick / 5.0)
            y = y_pos(value)
            svg.append(
                f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" stroke="{GRID}" stroke-width="1"/>'
            )
            svg.append(
                f'<text x="{left - 14}" y="{y + 5:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#555555">{value:.3f}</text>'
            )
    else:
        svg.append(
            f'<text x="{width / 2:.1f}" y="{top + 86:.2f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#666666">No completed loss values yet. Crash markers are still shown in the crash lane.</text>'
        )

    x_ticks = min(10, len(records))
    tick_indices: list[int] = []
    for tick in range(x_ticks):
        index = round(((len(records) - 1) * tick) / float(max(1, x_ticks - 1)))
        if index in tick_indices:
            continue
        tick_indices.append(index)
        record = records[index]
        x = x_pos(index)
        svg.append(
            f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{bottom}" stroke="#ece7dc" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{x:.2f}" y="{bottom + 28}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#555555">{record.experiment_id}</text>'
        )

    svg.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{AXIS}" stroke-width="1.5"/>')
    svg.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{AXIS}" stroke-width="1.5"/>')
    if crashed:
        svg.append(
            f'<line x1="{left}" y1="{crash_lane_y:.2f}" x2="{right}" y2="{crash_lane_y:.2f}" stroke="{CRASH_COLOR}" stroke-width="1.2" stroke-dasharray="6 5" opacity="0.65"/>'
        )
        svg.append(
            f'<text x="{right:.2f}" y="{crash_lane_y - 10:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="{CRASH_TEXT}">crash lane</text>'
        )

    step_points: list[tuple[float, float]] = []
    frontier_loss: float | None = None
    previous_y: float | None = None
    for index, record in scored_records:
        assert record.loss is not None
        if frontier_loss is None or record.loss < frontier_loss:
            x = x_pos(index)
            y = y_pos(record.loss)
            if not step_points:
                step_points.append((x, y))
            else:
                assert previous_y is not None
                step_points.append((x, previous_y))
                step_points.append((x, y))
            frontier_loss = record.loss
            previous_y = y
    if step_points:
        encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in step_points)
        svg.append(
            f'<polyline points="{encoded}" fill="none" stroke="{KEEP_COLOR}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    for index, record in discarded:
        assert record.loss is not None
        x = x_pos(index)
        y = y_pos(record.loss)
        svg.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6.5" fill="{DISCARD_COLOR}" stroke="#ffffff" stroke-width="1.5"/>'
        )

    for index, record in crashed:
        x = x_pos(index)
        y = crash_lane_y
        svg.append(
            f'<line x1="{x - 6:.2f}" y1="{y - 6:.2f}" x2="{x + 6:.2f}" y2="{y + 6:.2f}" stroke="{CRASH_COLOR}" stroke-width="2"/>'
        )
        svg.append(
            f'<line x1="{x + 6:.2f}" y1="{y - 6:.2f}" x2="{x - 6:.2f}" y2="{y + 6:.2f}" stroke="{CRASH_COLOR}" stroke-width="2"/>'
        )
        svg.append(
            f'<text x="{x:.2f}" y="{y - 12:.2f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="{CRASH_TEXT}">crash {record.experiment_id}</text>'
        )

    for index, record in kept:
        assert record.loss is not None
        x = x_pos(index)
        y = y_pos(record.loss)
        label = record.candidate_label or f"exp {record.experiment_id}"
        svg.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7.5" fill="{KEEP_COLOR}" stroke="#ffffff" stroke-width="2"/>'
        )
        svg.append(
            f'<text x="{x + 14:.2f}" y="{y - 12:.2f}" transform="rotate(-32 {x + 14:.2f} {y - 12:.2f})" '
            f'font-family="Arial, sans-serif" font-size="12" fill="{KEEP_COLOR}">{escape(label)}</text>'
        )

    legend_x = left
    legend_y = height - 78
    svg.extend(
        [
            f'<circle cx="{legend_x:.2f}" cy="{legend_y:.2f}" r="6.5" fill="{DISCARD_COLOR}" stroke="#ffffff" stroke-width="1.5"/>',
            f'<text x="{legend_x + 16:.2f}" y="{legend_y + 4:.2f}" font-family="Arial, sans-serif" font-size="12" fill="{AXIS}">discarded</text>',
            f'<circle cx="{legend_x + 132:.2f}" cy="{legend_y:.2f}" r="7.0" fill="{KEEP_COLOR}" stroke="#ffffff" stroke-width="2"/>',
            f'<text x="{legend_x + 148:.2f}" y="{legend_y + 4:.2f}" font-family="Arial, sans-serif" font-size="12" fill="{AXIS}">kept</text>',
            f'<line x1="{legend_x + 220:.2f}" y1="{legend_y:.2f}" x2="{legend_x + 268:.2f}" y2="{legend_y:.2f}" stroke="{KEEP_COLOR}" stroke-width="3.5"/>',
            f'<text x="{legend_x + 278:.2f}" y="{legend_y + 4:.2f}" font-family="Arial, sans-serif" font-size="12" fill="{AXIS}">running best</text>',
            f'<line x1="{legend_x + 392:.2f}" y1="{legend_y - 6:.2f}" x2="{legend_x + 404:.2f}" y2="{legend_y + 6:.2f}" stroke="{CRASH_COLOR}" stroke-width="2"/>',
            f'<line x1="{legend_x + 404:.2f}" y1="{legend_y - 6:.2f}" x2="{legend_x + 392:.2f}" y2="{legend_y + 6:.2f}" stroke="{CRASH_COLOR}" stroke-width="2"/>',
            f'<text x="{legend_x + 414:.2f}" y="{legend_y + 4:.2f}" font-family="Arial, sans-serif" font-size="12" fill="{AXIS}">crash</text>',
        ]
    )
    svg.append(
        f'<text x="{right:.2f}" y="{bottom + 68:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#555555">Experiments {len(records)} | keeps {len(kept)} | discards {len(discarded)} | crashes {len(crashed)}</text>'
    )

    svg.append(
        f'<text x="{width / 2:.1f}" y="{height - 28}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="{AXIS}">experiment number</text>'
    )
    svg.append(
        f'<text x="36" y="{height / 2:.1f}" transform="rotate(-90 36 {height / 2:.1f})" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="{AXIS}">{escape(y_label)}</text>'
    )
    svg.append("</svg>")
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    records = load_records(args.ledger)
    render_progress(records, svg_out=args.svg_out, title=args.title, y_label=args.y_label)
    print(f"Wrote {args.svg_out}")
    print(f"Records: {len(records)}")


if __name__ == "__main__":
    main()
