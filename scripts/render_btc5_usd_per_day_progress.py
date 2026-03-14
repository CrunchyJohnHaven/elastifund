#!/usr/bin/env python3
"""Render wallet-scaled BTC5 USD/day outcome progress chart and summary."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

DAYS_PER_MONTH = 30.0


@dataclass
class UsdPerDayRecord:
    cycle: int
    finished_at: str
    expected_usd_per_day: float
    historical_usd_per_day: float
    expected_fills_per_day: float
    edge_status: str
    frontier_expected_usd_per_day: float


BACKGROUND = "#FBF7EE"
AXIS_COLOR = "#1E1C18"
MUTED = "#5F5A50"
GRID_COLOR = "#E7E0D4"
EXPECTED_COLOR = "#16324F"
HISTORICAL_COLOR = "#C56A1A"
FRONTIER_COLOR = "#5B7188"
ZERO_LINE_COLOR = "#8E8A80"


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


def _coerce_per_day(
    payload: dict[str, Any],
    *,
    per_day_key: str,
    pnl_30d_key: str,
) -> float:
    per_day = _safe_float(payload.get(per_day_key))
    if per_day != 0.0:
        return per_day
    pnl_30d = _safe_float(payload.get(pnl_30d_key))
    if pnl_30d != 0.0:
        return pnl_30d / DAYS_PER_MONTH
    return 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-jsonl",
        default="reports/autoresearch/outcomes/history.jsonl",
        help="Append-only JSONL outcome ledger",
    )
    parser.add_argument(
        "--portfolio-expectation-json",
        default="reports/btc5_portfolio_expectation/latest.json",
        help="Optional wallet-scaled portfolio expectation summary",
    )
    parser.add_argument(
        "--arr-summary-json",
        default="research/btc5_arr_latest.json",
        help="Optional ARR summary artifact for outcome-surface enrichment",
    )
    parser.add_argument(
        "--svg-out",
        default="research/btc5_usd_per_day_progress.svg",
        help="Output SVG path",
    )
    parser.add_argument(
        "--summary-json-out",
        default="reports/autoresearch/outcomes/latest.json",
        help="Machine-readable outcome summary JSON",
    )
    return parser.parse_args()


def load_records(history_path: Path) -> list[UsdPerDayRecord]:
    if not history_path.exists():
        return []
    records: list[UsdPerDayRecord] = []
    frontier = float("-inf")
    for cycle, line in enumerate(history_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        expected = _safe_float(payload.get("expected_usd_per_day"))
        frontier = max(frontier, expected)
        records.append(
            UsdPerDayRecord(
                cycle=cycle,
                finished_at=str(payload.get("finished_at") or ""),
                expected_usd_per_day=expected,
                historical_usd_per_day=_safe_float(payload.get("historical_usd_per_day")),
                expected_fills_per_day=_safe_float(payload.get("expected_fills_per_day")),
                edge_status=str(payload.get("edge_status") or "unknown"),
                frontier_expected_usd_per_day=frontier,
            )
        )
    return records


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_outcome_summary(
    records: list[UsdPerDayRecord],
    *,
    portfolio_expectation: dict[str, Any] | None = None,
    arr_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build machine-readable outcome summary from history and optional live expectation."""
    pe = portfolio_expectation or {}
    arr = arr_summary or {}
    current_live = pe.get("current_live") or {}
    best_variant = pe.get("best_validated_variant") or {}

    # Wallet-scaled outcome fields from portfolio expectation if available.
    expected_usd_per_day = _coerce_per_day(
        current_live,
        per_day_key="expected_pnl_per_day_usd",
        pnl_30d_key="expected_pnl_30d_usd",
    )
    expected_fills_per_day = _safe_float(current_live.get("expected_fills_per_day"))
    historical_usd_per_day = _coerce_per_day(
        current_live,
        per_day_key="historical_pnl_per_day_usd",
        pnl_30d_key="historical_pnl_30d_usd",
    )
    best_expected_usd_per_day = _coerce_per_day(
        best_variant,
        per_day_key="expected_pnl_per_day_usd",
        pnl_30d_key="expected_pnl_30d_usd",
    )
    best_expected_fills_per_day = _safe_float(best_variant.get("expected_fills_per_day"))
    best_expected_pnl_30d_usd = best_expected_usd_per_day * DAYS_PER_MONTH
    expected_arr_pct = _safe_float(arr.get("latest_active_arr_pct"))
    best_validated_arr_pct = _safe_float(arr.get("frontier_active_arr_pct"))
    latest_candidate_arr_pct = _safe_float(arr.get("latest_best_arr_pct"))

    # If we have records, also pull from ledger.
    if records:
        latest = records[-1]
        ledger_expected = latest.expected_usd_per_day
        ledger_historical = latest.historical_usd_per_day
        frontier = max(r.frontier_expected_usd_per_day for r in records)
    else:
        ledger_expected = 0.0
        ledger_historical = 0.0
        frontier = 0.0

    # Prefer live portfolio expectation if available, fall back to ledger.
    if expected_usd_per_day == 0.0 and ledger_expected != 0.0:
        expected_usd_per_day = ledger_expected
    if historical_usd_per_day == 0.0 and ledger_historical != 0.0:
        historical_usd_per_day = ledger_historical
    if best_expected_usd_per_day == 0.0 and frontier != 0.0:
        best_expected_usd_per_day = frontier
        best_expected_pnl_30d_usd = best_expected_usd_per_day * DAYS_PER_MONTH
    if best_validated_arr_pct == 0.0 and expected_arr_pct != 0.0:
        best_validated_arr_pct = expected_arr_pct

    # Compute 30d projection.
    expected_pnl_30d_usd = expected_usd_per_day * DAYS_PER_MONTH

    summary: dict[str, Any] = {
        "metric_name": "btc5_outcome_surfaces",
        "outcome_type": "wallet_scaled_estimate",
        "disclaimer": "Outcome estimates, not realized P&L. Not benchmark loss metrics.",
        "expected_arr_pct": round(expected_arr_pct, 4),
        "expected_usd_per_day": round(expected_usd_per_day, 4),
        "historical_usd_per_day": round(historical_usd_per_day, 4),
        "expected_fills_per_day": round(expected_fills_per_day, 4),
        "expected_pnl_30d_usd": round(expected_pnl_30d_usd, 2),
        "best_validated_arr_pct": round(best_validated_arr_pct, 4),
        "latest_candidate_arr_pct": round(latest_candidate_arr_pct, 4),
        "best_variant_expected_usd_per_day": round(best_expected_usd_per_day, 4),
        "frontier_expected_usd_per_day": round(frontier, 4),
        "current_live": {
            "expected_arr_pct": round(expected_arr_pct, 4),
            "expected_usd_per_day": round(expected_usd_per_day, 4),
            "historical_usd_per_day": round(historical_usd_per_day, 4),
            "expected_fills_per_day": round(expected_fills_per_day, 4),
            "expected_pnl_30d_usd": round(expected_pnl_30d_usd, 2),
        },
        "best_validated_variant": {
            "expected_arr_pct": round(best_validated_arr_pct, 4),
            "expected_usd_per_day": round(best_expected_usd_per_day, 4),
            "expected_fills_per_day": round(best_expected_fills_per_day, 4),
            "expected_pnl_30d_usd": round(best_expected_pnl_30d_usd, 2),
        },
        "current_vs_best_validated": {
            "expected_arr_pct_delta": round(best_validated_arr_pct - expected_arr_pct, 4),
            "expected_usd_per_day_delta": round(best_expected_usd_per_day - expected_usd_per_day, 4),
            "expected_pnl_30d_usd_delta": round(best_expected_pnl_30d_usd - expected_pnl_30d_usd, 2),
            "expected_fills_per_day_delta": round(best_expected_fills_per_day - expected_fills_per_day, 4),
        },
        "ledger_cycles": len(records),
    }
    if records:
        summary["latest_edge_status"] = records[-1].edge_status
        summary["latest_finished_at"] = records[-1].finished_at
    if pe:
        summary["portfolio_wallet_usd"] = _safe_float((pe.get("portfolio") or {}).get("wallet_value_usd"))
        summary["edge_status_current"] = (current_live.get("edge_status") or {}).get("status", "unknown")
        summary["edge_status_best"] = (best_variant.get("edge_status") or {}).get("status", "unknown")
    if arr:
        summary["arr_latest_action"] = arr.get("latest_action")
        summary["arr_latest_finished_at"] = arr.get("latest_finished_at")
    return summary


def _polyline(points: list[tuple[float, float]], color: str, width: float) -> str:
    if not points:
        return ""
    encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline fill="none" stroke="{color}" stroke-width="{width}" points="{encoded}" />'


def render_svg(path: Path, records: list[UsdPerDayRecord], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="200" viewBox="0 0 1280 200">\n'
            f'<rect width="100%" height="100%" fill="{BACKGROUND}"/>\n'
            f'<text x="640" y="80" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" fill="{AXIS_COLOR}">BTC5 USD/Day Outcome</text>\n'
            '<text x="640" y="120" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#666666">No outcome records yet</text>\n'
            "</svg>\n",
            encoding="utf-8",
        )
        return

    width = 1280
    height = 620
    left = 100
    right = width - 40
    top = 80
    bottom = 520
    usable_width = max(1, right - left)
    plot_height = bottom - top

    all_values = [
        v
        for r in records
        for v in (r.expected_usd_per_day, r.historical_usd_per_day, r.frontier_expected_usd_per_day)
    ]
    val_min = min(min(all_values), 0.0)
    val_max = max(all_values)
    if abs(val_max - val_min) < 1e-9:
        val_min -= 1.0
        val_max += 1.0
    margin = (val_max - val_min) * 0.10
    val_min -= margin
    val_max += margin

    def x_for(index: int) -> float:
        if len(records) == 1:
            return left + usable_width / 2.0
        return left + (usable_width * index / float(len(records) - 1))

    def y_for(value: float) -> float:
        ratio = (value - val_min) / (val_max - val_min)
        return bottom - ratio * plot_height

    expected_pts = [(x_for(i), y_for(r.expected_usd_per_day)) for i, r in enumerate(records)]
    historical_pts = [(x_for(i), y_for(r.historical_usd_per_day)) for i, r in enumerate(records)]
    frontier_pts = [(x_for(i), y_for(r.frontier_expected_usd_per_day)) for i, r in enumerate(records)]

    latest = records[-1]
    ticks = [val_min, (val_min + val_max) / 2.0, val_max]
    tick_lines = "\n".join(
        f'<line x1="{left}" y1="{y_for(v):.2f}" x2="{right}" y2="{y_for(v):.2f}" stroke="{GRID_COLOR}" stroke-width="1" />'
        for v in ticks
    )
    tick_labels = "\n".join(
        f'<text x="{left - 12}" y="{y_for(v) + 5:.2f}" text-anchor="end" font-size="14" fill="{MUTED}">{_fmt_usd(v)}</text>'
        for v in ticks
    )
    circles = "\n".join(
        [
            f'<circle cx="{expected_pts[-1][0]:.2f}" cy="{expected_pts[-1][1]:.2f}" r="6" fill="{EXPECTED_COLOR}" />',
            f'<circle cx="{historical_pts[-1][0]:.2f}" cy="{historical_pts[-1][1]:.2f}" r="6" fill="{HISTORICAL_COLOR}" />',
        ]
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="BTC5 USD per day outcome progress">
<rect width="{width}" height="{height}" fill="{BACKGROUND}" />
<text x="{left}" y="42" font-size="28" font-weight="700" fill="{AXIS_COLOR}">BTC5 USD/Day Outcome</text>
<text x="{left}" y="66" font-size="16" fill="{MUTED}">Wallet-scaled outcome estimate. Expected {_fmt_usd(latest.expected_usd_per_day)}/day; historical {_fmt_usd(latest.historical_usd_per_day)}/day. Not benchmark loss.</text>
{tick_lines}
{tick_labels}
<line x1="{left}" y1="{y_for(0.0):.2f}" x2="{right}" y2="{y_for(0.0):.2f}" stroke="{ZERO_LINE_COLOR}" stroke-width="1.5" stroke-dasharray="4 4" />
{_polyline(frontier_pts, FRONTIER_COLOR, 2.0)}
{_polyline(expected_pts, EXPECTED_COLOR, 3.5)}
{_polyline(historical_pts, HISTORICAL_COLOR, 3.5)}
{circles}
<text x="{right}" y="{top - 14}" text-anchor="end" font-size="15" fill="{EXPECTED_COLOR}">Expected (MC median)</text>
<text x="{right - 180}" y="{top - 14}" text-anchor="end" font-size="15" fill="{HISTORICAL_COLOR}">Historical replay</text>
<text x="{right - 340}" y="{top - 14}" text-anchor="end" font-size="15" fill="{FRONTIER_COLOR}">Frontier expected</text>
<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{AXIS_COLOR}" stroke-width="1.5" />
<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{AXIS_COLOR}" stroke-width="1.5" />
<text x="{width / 2:.0f}" y="{height - 28}" text-anchor="middle" font-size="14" fill="{AXIS_COLOR}">outcome cycle</text>
<text x="36" y="{height / 2:.0f}" transform="rotate(-90 36 {height / 2:.0f})" text-anchor="middle" font-size="14" fill="{AXIS_COLOR}">USD / day</text>
<text x="{right}" y="{bottom + 48}" text-anchor="end" font-size="15" fill="{MUTED}">Cycle {latest.cycle} at {escape(latest.finished_at)} | edge: {escape(latest.edge_status)}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    args = parse_args()
    history_path = Path(args.history_jsonl)
    portfolio_expectation_path = Path(args.portfolio_expectation_json)
    arr_summary_path = Path(args.arr_summary_json)
    records = load_records(history_path)
    portfolio_expectation = _load_optional_json(portfolio_expectation_path)
    summary = build_outcome_summary(
        records,
        portfolio_expectation=portfolio_expectation,
        arr_summary=_load_optional_json(arr_summary_path),
    )
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    if portfolio_expectation:
        summary["source_path"] = str(portfolio_expectation_path)
        summary["source_generated_at"] = portfolio_expectation.get("generated_at")
    else:
        summary["source_path"] = str(history_path)
        summary["source_generated_at"] = summary.get("latest_finished_at")
    svg_out = Path(args.svg_out)
    summary_json_out = Path(args.summary_json_out)
    render_svg(svg_out, records, summary)
    summary_json_out.parent.mkdir(parents=True, exist_ok=True)
    summary_json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"svg": str(svg_out), "summary_json": str(summary_json_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
