#!/usr/bin/env python3
"""Render the BTC5 command-node Karpathy-style loss chart."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResultRecord:
    experiment_id: int
    status: str
    keep: bool
    loss: float | None
    candidate_label: str
    prompt_hash: str
    evaluated_at: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-jsonl",
        default="reports/autoresearch/command_node/results.jsonl",
        help="Append-only results ledger for the BTC5 command-node lane",
    )
    parser.add_argument(
        "--svg-out",
        default="research/btc5_command_node_progress.svg",
        help="Output SVG path",
    )
    return parser.parse_args()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_records(path: Path) -> list[ResultRecord]:
    if not path.exists():
        return []
    rows: list[ResultRecord] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        rows.append(
            ResultRecord(
                experiment_id=int(payload.get("experiment_id") or len(rows) + 1),
                status=str(payload.get("status") or "discard"),
                keep=bool(payload.get("keep")),
                loss=_safe_float(payload.get("loss")),
                candidate_label=str(payload.get("candidate_label") or f"exp-{len(rows) + 1}"),
                prompt_hash=str(payload.get("prompt_hash") or ""),
                evaluated_at=str(payload.get("evaluated_at") or ""),
            )
        )
    return rows


def _step_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points:
        return []
    if len(points) == 1:
        return points
    stepped = [points[0]]
    previous_y = points[0][1]
    for x_value, y_value in points[1:]:
        stepped.append((x_value, previous_y))
        stepped.append((x_value, y_value))
        previous_y = y_value
    return stepped


def _polyline(points: list[tuple[float, float]], *, color: str, width: float) -> str:
    if not points:
        return ""
    encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline fill="none" stroke="{color}" stroke-width="{width}" points="{encoded}" />'


def render_svg(path: Path, records: list[ResultRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 1280
    height = 760
    left = 100
    right = width - 60
    top = 110
    bottom = height - 120
    usable_width = right - left
    usable_height = bottom - top
    numeric_records = [record for record in records if record.loss is not None]
    if not numeric_records:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="240"><text x="40" y="80" font-size="24">BTC5 command-node loss (lower is better)</text><text x="40" y="130" font-size="16">No results yet.</text></svg>',
            encoding="utf-8",
        )
        return

    losses = [record.loss for record in numeric_records if record.loss is not None]
    assert losses
    min_loss = min(losses)
    max_loss = max(losses)
    margin = max(2.0, (max_loss - min_loss) * 0.15 or 2.0)
    min_loss -= margin
    max_loss += margin

    def x_for(experiment_index: int) -> float:
        if len(records) == 1:
            return left + usable_width / 2.0
        return left + usable_width * experiment_index / max(1, len(records) - 1)

    def y_for(loss_value: float) -> float:
        ratio = (loss_value - min_loss) / max(1e-9, (max_loss - min_loss))
        return bottom - ratio * usable_height

    frontier_value: float | None = None
    frontier_points: list[tuple[float, float]] = []
    keep_annotations: list[str] = []
    discard_points: list[str] = []
    keep_points: list[str] = []
    crash_labels: list[str] = []
    for index, record in enumerate(records):
        x_value = x_for(index)
        if record.loss is None:
            crash_labels.append(
                f'<text x="{x_value:.2f}" y="{top - 16}" text-anchor="middle" font-size="13" fill="#B04632">crash {record.experiment_id}</text>'
            )
            continue
        y_value = y_for(record.loss)
        if frontier_value is None or record.loss < frontier_value:
            frontier_value = record.loss
        frontier_points.append((x_value, y_for(frontier_value)))
        if record.keep:
            keep_points.append(f'<circle cx="{x_value:.2f}" cy="{y_value:.2f}" r="7" fill="#2D8A4E" />')
            keep_annotations.append(
                f'<g transform="translate({x_value + 8:.2f},{y_value - 10:.2f}) rotate(-24)"><text font-size="14" fill="#2D8A4E">exp {record.experiment_id}: {record.loss:.2f}</text></g>'
            )
        else:
            discard_points.append(f'<circle cx="{x_value:.2f}" cy="{y_value:.2f}" r="6" fill="#B8B8B8" />')

    y_ticks = [min_loss, (min_loss + max_loss) / 2.0, max_loss]
    y_guides = "\n".join(
        f'<line x1="{left}" y1="{y_for(value):.2f}" x2="{right}" y2="{y_for(value):.2f}" stroke="#E6E2D9" stroke-width="1" />'
        for value in y_ticks
    )
    y_labels = "\n".join(
        f'<text x="{left - 12}" y="{y_for(value) + 5:.2f}" text-anchor="end" font-size="15" fill="#5B584F">{value:.2f}</text>'
        for value in y_ticks
    )
    x_labels = "\n".join(
        f'<text x="{x_for(index):.2f}" y="{bottom + 30}" text-anchor="middle" font-size="14" fill="#5B584F">{record.experiment_id}</text>'
        for index, record in enumerate(records)
    )
    running_best = _polyline(_step_points(frontier_points), color="#2D8A4E", width=3.0)
    champion_loss = min(losses)
    keep_total = sum(1 for record in records if record.keep and record.loss is not None)
    discard_total = sum(1 for record in records if not record.keep and record.loss is not None and record.status != "crash")
    crash_total = sum(1 for record in records if record.status == "crash")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="BTC5 command-node progress chart">
<rect width="{width}" height="{height}" fill="#FBF7EE" />
<text x="{left}" y="48" font-size="30" font-weight="700" fill="#1E1C18">BTC5 command-node benchmark progress</text>
<text x="{left}" y="76" font-size="16" fill="#5B584F">Gray discarded points, green kept points, green running-best step line. Current champion loss {champion_loss:.2f}. Lower is better.</text>
{y_guides}
{y_labels}
<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#8D887C" stroke-width="1.5" />
<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#8D887C" stroke-width="1.5" />
{running_best}
{''.join(discard_points)}
{''.join(keep_points)}
{''.join(keep_annotations)}
{''.join(crash_labels)}
<text x="{(left + right) / 2:.2f}" y="{height - 48}" text-anchor="middle" font-size="18" fill="#1E1C18">Experiment number</text>
<g transform="translate(32,{(top + bottom) / 2:.2f}) rotate(-90)"><text text-anchor="middle" font-size="18" fill="#1E1C18">BTC5 command-node loss (lower is better)</text></g>
{x_labels}
<circle cx="{right - 320}" cy="34" r="6" fill="#B8B8B8" /><text x="{right - 306}" y="39" font-size="14" fill="#5B584F">Discarded</text>
<circle cx="{right - 220}" cy="34" r="6" fill="#2D8A4E" /><text x="{right - 206}" y="39" font-size="14" fill="#5B584F">Kept</text>
<line x1="{right - 120}" y1="34" x2="{right - 82}" y2="34" stroke="#2D8A4E" stroke-width="3" /><text x="{right - 74}" y="39" font-size="14" fill="#5B584F">Running best</text>
<text x="{right}" y="{bottom + 64}" text-anchor="end" font-size="14" fill="#5B584F">Experiments {len(records)} | keeps {keep_total} | discards {discard_total} | crashes {crash_total}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    args = parse_args()
    records = load_records(Path(args.results_jsonl))
    render_svg(Path(args.svg_out), records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
