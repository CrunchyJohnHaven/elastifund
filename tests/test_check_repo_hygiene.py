from __future__ import annotations

import json
from pathlib import Path

from scripts import check_repo_hygiene as hygiene


def test_generated_runtime_references_are_allowed() -> None:
    assert hygiene.is_generated_reference("jj_state.json") is True
    assert hygiene.is_generated_reference("reports/runtime_truth_latest.json") is True
    assert hygiene.is_generated_reference("reports/pipeline_20260309T012500Z.json") is True


def test_regular_repo_references_still_require_tracked_paths() -> None:
    assert hygiene.is_generated_reference("README.md") is False
    assert hygiene.is_generated_reference(
        "research/dispatches/DISPATCH_097_competitive_inventory_benchmark_blueprint.md"
    ) is False


def test_archive_paths_cannot_be_canonical_targets() -> None:
    assert hygiene.is_archive_canonical_path("archive/some_plan.md") is True
    assert hygiene.is_archive_canonical_path("research/archive/old.md") is True
    assert hygiene.is_archive_canonical_path("research/history/2026_q1/README.md") is True
    assert hygiene.is_archive_canonical_path("docs/ops/_archive/old.md") is True
    assert hygiene.is_archive_canonical_path("docs/ops/runbook.md") is False


def test_find_canonical_targets_reads_structured_markers() -> None:
    sample = "\n".join(
        [
            "| Canonical file | `docs/FORK_AND_RUN.md` |",
            "Canonical source: [docs/numbered/03_METRICS_AND_LEADERBOARDS.md](docs/numbered/03_METRICS_AND_LEADERBOARDS.md)",
            "**Canonical Filename:** `research/deep_research_prompt.md`",
            "Canonical file:",
            "- `research/dispatches/DISPATCH_102_BTC5_truth_plumbing_and_execution_confidence.md`",
        ]
    )
    targets = hygiene.find_canonical_targets(sample)
    assert "docs/FORK_AND_RUN.md" in targets
    assert "docs/numbered/03_METRICS_AND_LEADERBOARDS.md" in targets
    assert "research/deep_research_prompt.md" in targets
    assert "research/dispatches/DISPATCH_102_BTC5_truth_plumbing_and_execution_confidence.md" in targets


def test_reports_top_level_timestamp_contract_issues_flags_non_allowlisted(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "runtime_truth_20260311T150000Z.json").write_text("{}\n", encoding="utf-8")
    (reports / "retention_policy.json").write_text(
        json.dumps({"top_level_timestamped_file_allowlist": []}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(hygiene, "REPORTS_DIR", reports)
    monkeypatch.setattr(hygiene, "REPORTS_RETENTION_POLICY", reports / "retention_policy.json")

    issues = hygiene.reports_top_level_timestamp_contract_issues()
    assert len(issues) == 1
    assert "non-allowlisted top-level timestamped files present" in issues[0]


def test_reports_top_level_timestamp_contract_issues_respects_allowlist(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "runtime_truth_20260311T150000Z.json").write_text("{}\n", encoding="utf-8")
    (reports / "retention_policy.json").write_text(
        json.dumps({"top_level_timestamped_file_allowlist": ["runtime_truth_20260311T150000Z.json"]}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(hygiene, "REPORTS_DIR", reports)
    monkeypatch.setattr(hygiene, "REPORTS_RETENTION_POLICY", reports / "retention_policy.json")

    assert hygiene.reports_top_level_timestamp_contract_issues() == []
