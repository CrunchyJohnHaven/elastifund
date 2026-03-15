from __future__ import annotations

import json
from pathlib import Path

from scripts.render_btc5_hypothesis_frontier import (
    build_latest_summary,
    load_records,
    render_svg,
    write_summary_md,
    write_tsv,
)


def _write_history(path: Path) -> None:
    entries = [
        {
            "finished_at": "2026-03-09T18:57:19+00:00",
            "hypothesis_lab": {
                "best_hypothesis": {
                    "name": "hyp_down_hour_11",
                    "direction": "DOWN",
                    "session_name": "hour_et_11",
                },
                "best_summary": {
                    "evidence_band": "exploratory",
                    "validation_p05_arr_pct": 4200.0,
                    "validation_median_arr_pct": 9000.0,
                    "validation_live_filled_rows": 5,
                    "generalization_ratio": 4.2,
                },
            },
        },
        {
            "finished_at": "2026-03-09T19:02:19+00:00",
            "hypothesis_lab": {
                "best_hypothesis": {
                    "name": "hyp_down_open",
                    "direction": "DOWN",
                    "session_name": "open_et",
                },
                "best_summary": {
                    "evidence_band": "candidate",
                    "validation_p05_arr_pct": 5200.0,
                    "validation_median_arr_pct": 9800.0,
                    "validation_live_filled_rows": 9,
                    "generalization_ratio": 2.6,
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


def test_load_records_and_summary(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_latest_summary(records)
    assert len(records) == 2
    assert summary["frontier_p05_arr_pct"] == 5200.0
    assert summary["latest_hypothesis_name"] == "hyp_down_open"
    assert summary["evidence_counts"]["candidate"] == 1


def test_render_outputs_write_frontier_artifacts(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history)
    records = load_records(history)
    summary = build_latest_summary(records)
    tsv = tmp_path / "frontier.tsv"
    svg = tmp_path / "frontier.svg"
    md = tmp_path / "frontier.md"
    write_tsv(tsv, records)
    render_svg(svg, records, summary)
    write_summary_md(md, summary)
    assert "validation_p05_arr_pct" in tsv.read_text()
    assert "<svg" in svg.read_text()
    assert "Latest hypothesis" in md.read_text()
