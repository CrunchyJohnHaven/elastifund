from __future__ import annotations

import json
from pathlib import Path

from scripts.render_btc5_command_node_progress import load_records, render_svg


def test_renderer_emits_karpathy_style_labels(tmp_path: Path) -> None:
    results_path = tmp_path / "results.jsonl"
    rows = [
        {"experiment_id": 1, "evaluated_at": "2026-03-11T10:00:00+00:00", "status": "keep", "keep": True, "loss": 42.0, "candidate_label": "baseline", "prompt_hash": "a"},
        {"experiment_id": 2, "evaluated_at": "2026-03-11T10:05:00+00:00", "status": "discard", "keep": False, "loss": 44.0, "candidate_label": "worse", "prompt_hash": "b"},
        {"experiment_id": 3, "evaluated_at": "2026-03-11T10:10:00+00:00", "status": "keep", "keep": True, "loss": 39.5, "candidate_label": "better", "prompt_hash": "c"},
        {"experiment_id": 4, "evaluated_at": "2026-03-11T10:15:00+00:00", "status": "crash", "keep": False, "loss": None, "candidate_label": "crash", "prompt_hash": "d"},
    ]
    results_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    records = load_records(results_path)
    svg_path = tmp_path / "progress.svg"
    render_svg(svg_path, records)

    svg_text = svg_path.read_text(encoding="utf-8")
    assert "BTC5 command-node benchmark progress" in svg_text
    assert "Discarded" in svg_text
    assert "Kept" in svg_text
    assert "Running best" in svg_text
    assert "BTC5 command-node loss (lower is better)" in svg_text
    assert "Experiment number" in svg_text
    assert "crash 4" in svg_text
