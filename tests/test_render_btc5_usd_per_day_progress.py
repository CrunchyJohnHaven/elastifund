from __future__ import annotations

import json
from pathlib import Path

from scripts.render_btc5_usd_per_day_progress import (
    build_outcome_summary,
    load_records,
    render_svg,
)


def _write_history(path: Path) -> None:
    entries = [
        {
            "finished_at": "2026-03-10T12:00:00+00:00",
            "expected_usd_per_day": 38.19,
            "historical_usd_per_day": 26.95,
            "expected_fills_per_day": 104.0,
            "edge_status": "positive_but_tail_risky",
        },
        {
            "finished_at": "2026-03-10T14:00:00+00:00",
            "expected_usd_per_day": 42.50,
            "historical_usd_per_day": 31.42,
            "expected_fills_per_day": 101.0,
            "edge_status": "validated_positive",
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def test_load_records_parses_history(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    assert len(records) == 2
    assert records[0].expected_usd_per_day == 38.19
    assert records[1].frontier_expected_usd_per_day == 42.50
    assert records[0].frontier_expected_usd_per_day == 38.19


def test_load_records_empty_file(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    assert load_records(history) == []


def test_build_outcome_summary_from_records(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_outcome_summary(records)
    assert summary["metric_name"] == "btc5_outcome_surfaces"
    assert summary["ledger_cycles"] == 2
    assert summary["latest_edge_status"] == "validated_positive"
    assert summary["frontier_expected_usd_per_day"] == 42.50


def test_build_outcome_summary_with_portfolio_expectation() -> None:
    pe = {
        "portfolio": {"wallet_value_usd": 247.51},
        "current_live": {
            "expected_pnl_per_day_usd": 38.19,
            "historical_pnl_per_day_usd": 26.95,
            "expected_fills_per_day": 104.0,
            "edge_status": {"status": "positive_but_tail_risky"},
        },
        "best_validated_variant": {
            "expected_pnl_per_day_usd": 42.50,
            "expected_fills_per_day": 101.0,
            "edge_status": {"status": "validated_positive"},
        },
    }
    arr_summary = {
        "latest_active_arr_pct": 123.4,
        "frontier_active_arr_pct": 156.7,
        "latest_best_arr_pct": 131.0,
        "latest_action": "hold",
    }
    summary = build_outcome_summary([], portfolio_expectation=pe, arr_summary=arr_summary)
    assert summary["expected_arr_pct"] == 123.4
    assert summary["best_validated_arr_pct"] == 156.7
    assert summary["latest_candidate_arr_pct"] == 131.0
    assert summary["expected_usd_per_day"] == 38.19
    assert summary["best_variant_expected_usd_per_day"] == 42.50
    assert summary["portfolio_wallet_usd"] == 247.51
    assert summary["expected_pnl_30d_usd"] == round(38.19 * 30, 2)
    assert summary["current_vs_best_validated"]["expected_arr_pct_delta"] == 33.3
    assert summary["current_vs_best_validated"]["expected_usd_per_day_delta"] == 4.31
    assert summary["current_vs_best_validated"]["expected_pnl_30d_usd_delta"] == 129.3
    assert summary["current_vs_best_validated"]["expected_fills_per_day_delta"] == -3.0


def test_build_outcome_summary_uses_30d_default_when_per_day_missing() -> None:
    pe = {
        "current_live": {
            "expected_pnl_30d_usd": 1145.5,
            "historical_pnl_30d_usd": 808.5,
            "expected_fills_per_day": 104.0,
        },
        "best_validated_variant": {
            "expected_pnl_30d_usd": 1275.0,
        },
    }
    summary = build_outcome_summary([], portfolio_expectation=pe)
    assert summary["expected_usd_per_day"] == round(1145.5 / 30.0, 4)
    assert summary["historical_usd_per_day"] == round(808.5 / 30.0, 4)
    assert summary["best_variant_expected_usd_per_day"] == round(1275.0 / 30.0, 4)


def test_build_outcome_summary_uses_frontier_when_best_variant_missing(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_outcome_summary(records, arr_summary={"latest_active_arr_pct": 123.4})
    assert summary["best_variant_expected_usd_per_day"] == 42.5
    assert summary["best_validated_arr_pct"] == 123.4


def test_render_svg_creates_valid_svg(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_outcome_summary(records)
    svg_out = tmp_path / "usd_per_day.svg"
    render_svg(svg_out, records, summary)
    content = svg_out.read_text()
    assert "<svg" in content
    assert "USD/Day" in content


def test_render_svg_empty_records(tmp_path: Path) -> None:
    svg_out = tmp_path / "usd_per_day.svg"
    render_svg(svg_out, [], {})
    content = svg_out.read_text()
    assert "<svg" in content
    assert "No outcome records" in content
