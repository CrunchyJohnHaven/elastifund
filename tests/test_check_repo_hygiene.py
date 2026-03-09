from __future__ import annotations

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
