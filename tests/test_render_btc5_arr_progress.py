from __future__ import annotations

import json
from pathlib import Path

from scripts.render_btc5_arr_progress import (
    build_latest_summary,
    load_records,
    render_svg,
    write_summary_md,
    write_tsv,
)


def _write_history(path: Path) -> None:
    entries = [
        {
            "finished_at": "2026-03-09T18:30:05+00:00",
            "decision": {"action": "hold", "reason": "current_profile_is_best"},
            "arr": {
                "active_median_arr_pct": 1200.0,
                "best_median_arr_pct": 1200.0,
                "median_arr_delta_pct": 0.0,
                "active_p05_arr_pct": 200.0,
                "best_p05_arr_pct": 200.0,
            },
        },
        {
            "finished_at": "2026-03-09T18:35:05+00:00",
            "decision": {"action": "promote", "reason": "promotion_thresholds_met"},
            "arr": {
                "active_median_arr_pct": 1200.0,
                "best_median_arr_pct": 1450.0,
                "median_arr_delta_pct": 250.0,
                "active_p05_arr_pct": 200.0,
                "best_p05_arr_pct": 260.0,
            },
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


def test_load_records_and_build_summary(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_latest_summary(records)
    assert len(records) == 2
    assert summary["cycles_total"] == 2
    assert summary["latest_best_arr_pct"] == 1450.0
    assert summary["latest_delta_arr_pct"] == 250.0


def test_render_outputs_write_tracked_artifacts(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_latest_summary(records)
    tsv = tmp_path / "arr.tsv"
    svg = tmp_path / "arr.svg"
    md = tmp_path / "arr.md"
    write_tsv(tsv, records)
    render_svg(svg, records, summary)
    write_summary_md(md, summary)
    assert "active_arr_pct" in tsv.read_text()
    assert "<svg" in svg.read_text()
    assert "Latest best-candidate ARR" in md.read_text()
