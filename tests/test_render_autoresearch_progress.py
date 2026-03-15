"""Tests for the autoresearch progress and velocity renderer."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_renderer_writes_velocity_artifacts(tmp_path: Path) -> None:
    write_metrics(
        tmp_path / "run_20260307_000000_metrics.json",
        timestamp="2026-03-07T00:00:00+00:00",
        score=0.40,
        name="baseline",
    )
    write_metrics(
        tmp_path / "run_20260307_010000_metrics.json",
        timestamp="2026-03-07T01:00:00+00:00",
        score=0.40,
        name="repeat",
    )
    write_metrics(
        tmp_path / "run_20260307_013000_metrics.json",
        timestamp="2026-03-07T01:30:00+00:00",
        score=0.55,
        name="lift-one",
    )
    write_metrics(
        tmp_path / "run_20260307_020000_metrics.json",
        timestamp="2026-03-07T02:00:00+00:00",
        score=0.70,
        name="lift-two",
    )

    progress_tsv = tmp_path / "progress.tsv"
    progress_svg = tmp_path / "progress.svg"
    velocity_tsv = tmp_path / "velocity.tsv"
    velocity_svg = tmp_path / "velocity.svg"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_autoresearch_progress.py"),
            "--input-glob",
            "run_*_metrics.json",
            "--tsv-out",
            str(progress_tsv),
            "--svg-out",
            str(progress_svg),
            "--velocity-tsv-out",
            str(velocity_tsv),
            "--velocity-svg-out",
            str(velocity_svg),
            "--rolling-window",
            "3",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert progress_tsv.exists()
    assert progress_svg.exists()
    assert velocity_tsv.exists()
    assert velocity_svg.exists()

    with velocity_tsv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert [row["status"] for row in rows] == ["keep", "discard", "keep", "keep"]
    assert float(rows[2]["frontier_delta"]) == pytest.approx(0.15, abs=1e-6)
    assert float(rows[2]["hours_since_prev"]) == pytest.approx(0.5, abs=1e-6)
    assert float(rows[2]["velocity_per_hour"]) == pytest.approx(0.3, abs=1e-6)
    assert float(rows[2]["keep_velocity_per_hour"]) == pytest.approx(0.1, abs=1e-6)
    assert float(rows[3]["rolling_velocity_per_hour"]) > 0.0

    svg_text = velocity_svg.read_text(encoding="utf-8")
    assert "Elastifund Improvement Velocity" in svg_text
    assert "Frontier Velocity (3-run rolling slope)" in svg_text


def write_metrics(path: Path, *, timestamp: str, score: float, name: str) -> None:
    payload = {
        "timestamp": timestamp,
        "recommendation": "KEEP TESTING",
        "evaluations": [
            {
                "name": name,
                "score": score,
                "metrics": {
                    "ev_taker": score * 10,
                    "win_rate": 0.5,
                },
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
