from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import check_repo_hygiene as hygiene
from scripts.report_envelope import validate_report_envelope


def test_generated_runtime_references_are_allowed() -> None:
    assert hygiene.is_generated_reference("jj_state.json") is True
    assert hygiene.is_generated_reference("reports/runtime_truth_latest.json") is True
    assert hygiene.is_generated_reference("reports/pipeline_20260309T012500Z.json") is True


def test_regular_repo_references_still_require_tracked_paths() -> None:
    assert hygiene.is_generated_reference("README.md") is False
    assert hygiene.is_generated_reference(
        "research/dispatches/DISPATCH_097_competitive_inventory_benchmark_blueprint.md"
    ) is False


def test_duplicate_debris_is_detected() -> None:
    assert hygiene.is_duplicate_debris("scripts/README (1).md") is True
    assert hygiene.is_duplicate_debris("reports/improvement_velocity (1).json") is True
    assert hygiene.is_duplicate_debris("scripts/README.md") is False


def test_main_flags_duplicate_debris_from_tracked_files(monkeypatch, capsys) -> None:
    monkeypatch.setattr(hygiene, "tracked_files", lambda: [Path("scripts/README (1).md")])
    monkeypatch.setattr(hygiene, "untracked_files", lambda: [])

    exit_code = hygiene.main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "duplicate debris file" in output


def test_validate_report_envelope_accepts_canonical_latest_shape() -> None:
    payload = {
        "artifact": "runtime_truth_snapshot",
        "generated_at": "2026-03-22T14:00:00+00:00",
        "status": "hold_repair",
        "source_of_truth": "reports/remote_cycle_status.json",
        "freshness_sla_seconds": 900,
        "stale_after": "2026-03-22T14:15:00Z",
        "blockers": ["launch_posture_not_clear"],
        "summary": {"launch_posture": "blocked"},
    }
    assert validate_report_envelope(payload) == []


def test_list_prunable_worktrees_parses_porcelain(monkeypatch) -> None:
    output = "\n".join(
        [
            "worktree /repo/main",
            "HEAD abc123",
            "branch refs/heads/main",
            "",
            "worktree /tmp/stale",
            "HEAD def456",
            "detached",
            "prunable gitdir file points to non-existent location",
        ]
    )

    monkeypatch.setattr(
        hygiene.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=output.encode("utf-8")),
    )

    assert hygiene.list_prunable_worktrees() == ["/tmp/stale"]
