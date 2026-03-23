from __future__ import annotations

from pathlib import Path

from scripts.report_envelope import build_report_envelope, write_report


def test_empty_payload_becomes_blocked_report(tmp_path: Path) -> None:
    report = build_report_envelope(
        artifact="example_report",
        payload={},
        status="fresh",
        source_of_truth="reports/example.json",
        freshness_sla_seconds=60,
        summary="",
    )

    assert report["artifact"] == "example_report"
    assert report["status"] == "blocked"
    assert report["blockers"] == ["empty_payload"]
    assert report["stale_after"] is not None
    assert report["summary"] == "example_report emitted an empty payload"


def test_write_report_preserves_payload_and_envelope(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    report = write_report(
        path,
        artifact="example_report",
        payload={"value": 42},
        status="fresh",
        source_of_truth="reports/example.json",
        freshness_sla_seconds=60,
        summary="value=42",
    )

    assert path.exists()
    assert report["artifact"] == "example_report"
    assert report["value"] == 42
    assert report["status"] == "fresh"
    assert report["source_of_truth"] == "reports/example.json"
