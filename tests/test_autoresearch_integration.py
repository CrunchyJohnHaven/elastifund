"""Tests for the calibration autoresearch integration flow."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from data_layer import crud, database
from benchmarks.calibration_v1.benchmark import run_benchmark


ROOT = Path(__file__).resolve().parents[1]


def test_run_benchmark_uses_frozen_manifest() -> None:
    packet = run_benchmark(ROOT / "benchmarks/calibration_v1/manifest.json")

    assert packet["benchmark_id"] == "calibration_v1"
    assert packet["dataset"]["total_rows"] == 532
    assert packet["dataset"]["warmup_rows"] == 372
    assert packet["dataset"]["holdout_rows"] == 160
    assert packet["selected_variant"]["name"] in {"static", "expanding", "rolling_100", "rolling_200"}
    assert packet["selected_variant"]["benchmark_score"] <= 0
    assert len(packet["variants"]) == 4
    assert packet["diagnostics"]["confidence_bands"]


def test_lane_runner_logs_keep_then_discard_and_creates_flywheel_tasks(tmp_path: Path) -> None:
    ledger = tmp_path / "results.tsv"
    progress_tsv = tmp_path / "progress.tsv"
    progress_svg = tmp_path / "progress.svg"
    summary_md = tmp_path / "summary.md"
    output_dir = tmp_path / "packets"
    control_db = tmp_path / "flywheel.db"
    db_url = f"sqlite:///{control_db}"

    run_args = [
        sys.executable,
        "scripts/run_lane_autoresearch.py",
        "--ledger",
        str(ledger),
        "--progress-tsv",
        str(progress_tsv),
        "--progress-svg",
        str(progress_svg),
        "--summary-md",
        str(summary_md),
        "--output-dir",
        str(output_dir),
        "--control-db-url",
        db_url,
    ]

    first = subprocess.run(
        [*run_args, "--candidate-label", "baseline", "--description", "baseline freeze"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "keep"
    assert first_payload["decision_reason"] == "baseline_frontier"

    second = subprocess.run(
        [*run_args, "--candidate-label", "same-code", "--description", "repeat run"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    second_payload = json.loads(second.stdout)
    assert second_payload["status"] == "discard"
    assert second_payload["decision_reason"] == "below_frontier"

    with ledger.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 2
    assert rows[0]["status"] == "keep"
    assert rows[1]["status"] == "discard"
    assert progress_tsv.exists()
    assert progress_svg.exists()
    assert summary_md.exists()

    database.reset_engine()
    engine = database.get_engine(db_url)
    session = database.get_session_factory(engine)()
    try:
        tasks = crud.list_flywheel_tasks(session, status="open", limit=10)
        findings = crud.list_flywheel_findings(session, source_kind="benchmark_lane", limit=10)
        assert len(tasks) == 2
        assert len(findings) == 2
        assert tasks[0].title in {
            "Freeze calibration benchmark baseline",
            "Record calibration benchmark null result",
        }
        assert tasks[1].title in {
            "Freeze calibration benchmark baseline",
            "Record calibration benchmark null result",
        }
        assert all(task.source_kind == "benchmark_lane" for task in tasks)
    finally:
        session.close()
        database.reset_engine()
