from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.command_node_btc5.v1 import benchmark as benchmark_v1
from benchmarks.command_node_btc5.v2 import benchmark as benchmark_v2
from benchmarks.command_node_btc5.v3 import benchmark as benchmark_v3
from benchmarks.command_node_btc5.v4 import benchmark as benchmark_v4


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_V1_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v1" / "manifest.json"
MANIFEST_V2_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v2" / "manifest.json"
MANIFEST_V3_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v3" / "manifest.json"
MANIFEST_V4_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v4" / "manifest.json"
BENCHMARK_CASES = (
    (benchmark_v1, MANIFEST_V1_PATH, "command_node_btc5_v1", 5),
    (benchmark_v2, MANIFEST_V2_PATH, "command_node_btc5_v2", 4),
    (benchmark_v3, MANIFEST_V3_PATH, "command_node_btc5_v3", 4),
    (benchmark_v4, MANIFEST_V4_PATH, "command_node_btc5_v4", 3),
)


def _perfect_candidate_packet(
    tasks: list[object],
    *,
    task_suite_id: str,
    candidate_label: str = "perfect-baseline",
) -> dict[str, object]:
    responses: list[dict[str, object]] = []
    for task in tasks:
        clarity_terms = list(task.required_clarity_terms)
        responses.append(
            {
                "task_id": task.task_id,
                "objective": f"Execute {task.title} with {'; '.join(clarity_terms)} and preserve the frozen BTC5 task contract.",
                "owner_model": task.expected_owner_model,
                "read_first": list(task.required_read_first),
                "files_to_edit": list(task.required_files_to_edit),
                "output_files": list(task.required_output_files),
                "dependencies": list(task.required_dependency_order),
                "verification_commands": [f"verify {term}" for term in task.required_verification_terms],
                "checklist": list(task.required_checklist),
                "notes": (
                    f"This packet keeps one owner per path, prioritizes machine-truth artifacts, and follows "
                    f"the frozen dependency order for {task.task_id}. {' '.join(clarity_terms)}."
                ),
            }
        )
    return {
        "task_suite_id": task_suite_id,
        "candidate_label": candidate_label,
        "responses": responses,
    }


def _candidate_markdown(payload: dict[str, object]) -> str:
    return "# BTC5 Command Node Candidate\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n"


def _ported_v3_baseline_packet_for_v4() -> dict[str, object]:
    manifest_v3 = benchmark_v3.load_manifest(MANIFEST_V3_PATH)
    tasks_v3 = benchmark_v3.load_tasks(manifest_v3)
    v3_payload = _perfect_candidate_packet(
        tasks_v3,
        task_suite_id="command_node_btc5_v3",
        candidate_label="ported-v3-baseline",
    )
    responses_by_task = {
        str(response["task_id"]): dict(response)
        for response in v3_payload["responses"]
        if isinstance(response, dict)
    }

    manifest_v4 = benchmark_v4.load_manifest(MANIFEST_V4_PATH)
    tasks_v4 = benchmark_v4.load_tasks(manifest_v4)
    responses: list[dict[str, object]] = []
    for task in tasks_v4:
        response = dict(responses_by_task.get(task.task_id, {}))
        response["task_id"] = task.task_id
        responses.append(response)
    return {
        "task_suite_id": "command_node_btc5_v4",
        "candidate_label": "ported-v3-baseline",
        "responses": responses,
    }


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_extract_candidate_packet_reads_markdown_block(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
) -> None:
    del manifest_path, expected_count
    payload = benchmark_module.extract_candidate_packet(
        _candidate_markdown({"task_suite_id": task_suite_id, "responses": []})
    )
    assert payload["task_suite_id"] == task_suite_id


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_manifest_checksum_matches_tasks(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
) -> None:
    del task_suite_id
    manifest = benchmark_module.load_manifest(manifest_path)
    verified = benchmark_module.verify_manifest(manifest)
    assert verified["tasks_sha256"] == manifest["data"]["tasks_sha256"]
    assert verified["task_count"] == expected_count


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_benchmark_scores_all_frozen_tasks(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
    tmp_path: Path,
) -> None:
    manifest = benchmark_module.load_manifest(manifest_path)
    tasks = benchmark_module.load_tasks(manifest)
    assert len(tasks) == expected_count

    candidate_path = tmp_path / "btc5_command_node.md"
    candidate_path.write_text(
        _candidate_markdown(_perfect_candidate_packet(tasks, task_suite_id=task_suite_id)),
        encoding="utf-8",
    )

    packet = benchmark_module.evaluate_candidate(
        manifest_path,
        candidate_path,
        allow_noncanonical_candidate=True,
    )
    assert packet["task_suite"]["task_count"] == expected_count
    assert packet["task_suite"]["task_suite_id"] == task_suite_id
    assert packet["candidate_label"] == "perfect-baseline"
    assert packet["total_score"] == 100.0
    assert packet["loss"] == 0.0
    assert packet["subscores"] == {
        "source_path_correctness": 30.0,
        "dependency_correctness": 25.0,
        "dispatch_completeness": 25.0,
        "judge_clarity": 20.0,
    }


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_benchmark_penalizes_wrong_owner_and_missing_paths(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
    tmp_path: Path,
) -> None:
    del expected_count
    manifest = benchmark_module.load_manifest(manifest_path)
    tasks = benchmark_module.load_tasks(manifest)
    payload = _perfect_candidate_packet(tasks, task_suite_id=task_suite_id)
    first = payload["responses"][0]
    assert isinstance(first, dict)
    first["owner_model"] = "Wrong Model"
    first["output_files"] = []
    first["dependencies"] = ["emit_handoff"]

    candidate_path = tmp_path / "btc5_command_node.md"
    candidate_path.write_text(_candidate_markdown(payload), encoding="utf-8")

    packet = benchmark_module.evaluate_candidate(
        manifest_path,
        candidate_path,
        allow_noncanonical_candidate=True,
    )
    assert packet["total_score"] < 100.0
    assert packet["loss"] > 0.0
    task_scores = {row["task_id"]: row for row in packet["tasks"]}
    broken = task_scores[tasks[0].task_id]
    assert broken["dispatch_completeness"] < 25.0
    assert broken["source_path_correctness"] < 30.0
    assert broken["dependency_correctness"] < 25.0


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_benchmark_rejects_noncanonical_candidate_by_default(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
    tmp_path: Path,
) -> None:
    del expected_count
    manifest = benchmark_module.load_manifest(manifest_path)
    tasks = benchmark_module.load_tasks(manifest)
    candidate_path = tmp_path / "btc5_command_node.md"
    candidate_path.write_text(
        _candidate_markdown(_perfect_candidate_packet(tasks, task_suite_id=task_suite_id)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="enforces one mutable surface"):
        benchmark_module.evaluate_candidate(manifest_path, candidate_path)


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_benchmark_uses_scored_file_hashes_for_escape_hatch_candidate(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
    tmp_path: Path,
) -> None:
    del expected_count
    manifest = benchmark_module.load_manifest(manifest_path)
    tasks = benchmark_module.load_tasks(manifest)
    candidate_path = tmp_path / "alt_candidate.md"
    candidate_path.write_text(
        _candidate_markdown(_perfect_candidate_packet(tasks, task_suite_id=task_suite_id)),
        encoding="utf-8",
    )

    packet = benchmark_module.evaluate_candidate(
        manifest_path,
        candidate_path,
        allow_noncanonical_candidate=True,
    )
    expected_hash = benchmark_module.sha256_file(candidate_path)

    assert packet["candidate_program_path"] == str(candidate_path)
    assert packet["mutable_surface_sha256"] == expected_hash
    assert packet["prompt_hash"] == expected_hash
    assert packet["candidate_hash"] == expected_hash


@pytest.mark.parametrize(
    ("benchmark_module", "manifest_path", "task_suite_id", "expected_count"),
    BENCHMARK_CASES,
)
def test_benchmark_is_deterministic_for_same_candidate(
    benchmark_module: object,
    manifest_path: Path,
    task_suite_id: str,
    expected_count: int,
    tmp_path: Path,
) -> None:
    del expected_count
    manifest = benchmark_module.load_manifest(manifest_path)
    tasks = benchmark_module.load_tasks(manifest)
    candidate_path = tmp_path / "btc5_command_node.md"
    candidate_path.write_text(
        _candidate_markdown(_perfect_candidate_packet(tasks, task_suite_id=task_suite_id)),
        encoding="utf-8",
    )

    first = benchmark_module.evaluate_candidate(
        manifest_path,
        candidate_path,
        allow_noncanonical_candidate=True,
    )
    second = benchmark_module.evaluate_candidate(
        manifest_path,
        candidate_path,
        allow_noncanonical_candidate=True,
    )

    assert first["loss"] == second["loss"]
    assert first["total_score"] == second["total_score"]
    assert first["subscores"] == second["subscores"]
    assert first["tasks"] == second["tasks"]


def test_v3_benchmark_reopens_headroom_against_ported_v2_baseline(tmp_path: Path) -> None:
    manifest_v2 = benchmark_v2.load_manifest(MANIFEST_V2_PATH)
    tasks_v2 = benchmark_v2.load_tasks(manifest_v2)
    manifest_v3 = benchmark_v3.load_manifest(MANIFEST_V3_PATH)
    tasks_v3 = benchmark_v3.load_tasks(manifest_v3)
    responses: list[dict[str, object]] = []
    for v3_task, v2_task in zip(tasks_v3, tasks_v2, strict=True):
        responses.append(
            {
                "task_id": v3_task.task_id,
                "objective": f"Execute {v2_task.title} with {'; '.join(v2_task.required_clarity_terms)} and preserve the frozen BTC5 task contract.",
                "owner_model": v2_task.expected_owner_model,
                "read_first": list(v2_task.required_read_first),
                "files_to_edit": list(v2_task.required_files_to_edit),
                "output_files": list(v2_task.required_output_files),
                "dependencies": list(v2_task.required_dependency_order),
                "verification_commands": [f"verify {term}" for term in v2_task.required_verification_terms],
                "checklist": list(v2_task.required_checklist),
                "notes": (
                    "This packet preserves the older bridge-oriented coverage and leaves the new "
                    "headroom refresh requirements unaddressed."
                ),
            }
        )
    candidate_path = tmp_path / "ported_v2_baseline.md"
    candidate_path.write_text(
        _candidate_markdown(
            {
                "task_suite_id": "command_node_btc5_v3",
                "candidate_label": "ported-v2-baseline",
                "responses": responses,
            }
        ),
        encoding="utf-8",
    )

    packet = benchmark_v3.evaluate_candidate(
        MANIFEST_V3_PATH,
        candidate_path,
        allow_noncanonical_candidate=True,
    )

    assert packet["candidate_label"] == "ported-v2-baseline"
    assert packet["total_score"] < 95.0
    assert packet["loss"] > 5.0


def test_v4_benchmark_reopens_headroom_against_ported_v3_baseline(tmp_path: Path) -> None:
    candidate_path = tmp_path / "ported_v3_baseline.md"
    candidate_path.write_text(
        _candidate_markdown(_ported_v3_baseline_packet_for_v4()),
        encoding="utf-8",
    )

    packet = benchmark_v4.evaluate_candidate(
        MANIFEST_V4_PATH,
        candidate_path,
        allow_noncanonical_candidate=True,
    )

    assert packet["candidate_label"] == "ported-v3-baseline"
    assert packet["total_score"] < 95.0
    assert packet["loss"] > 5.0

    task_scores = {row["task_id"]: row for row in packet["tasks"]}
    assert task_scores["agent_lane_headroom_rebenchmark"]["source_path_correctness"] < 30.0
    assert task_scores["overnight_closeout_lane_artifact"]["judge_clarity"] < 20.0


def test_v4_current_mutable_surface_still_has_headroom_after_v4_cutover() -> None:
    packet = benchmark_v4.evaluate_candidate(MANIFEST_V4_PATH, ROOT / "btc5_command_node.md")

    assert str(packet["candidate_label"]).startswith("headroom-command-node-v4")
    assert packet["task_suite"]["task_suite_id"] == "command_node_btc5_v4"
    assert packet["total_score"] < 95.0
    assert packet["loss"] > 5.0


def test_v3_benchmark_penalizes_wrong_runner_selection_and_dependency_conflict(tmp_path: Path) -> None:
    manifest = benchmark_v3.load_manifest(MANIFEST_V3_PATH)
    tasks = benchmark_v3.load_tasks(manifest)
    payload = _perfect_candidate_packet(tasks, task_suite_id="command_node_btc5_v3")
    first = payload["responses"][0]
    assert isinstance(first, dict)
    first["read_first"] = [
        path for path in first["read_first"] if path != "scripts/run_btc5_command_node_autoresearch.py"
    ]
    first["files_to_edit"] = [
        path for path in first["files_to_edit"] if path != "scripts/run_btc5_command_node_autoresearch.py"
    ]
    first["dependencies"] = list(reversed(first["dependencies"]))

    candidate_path = tmp_path / "wrong_runner.md"
    candidate_path.write_text(_candidate_markdown(payload), encoding="utf-8")

    packet = benchmark_v3.evaluate_candidate(
        MANIFEST_V3_PATH,
        candidate_path,
        allow_noncanonical_candidate=True,
    )
    task_scores = {row["task_id"]: row for row in packet["tasks"]}
    broken = task_scores["agent_lane_headroom_rebenchmark"]

    assert packet["total_score"] < 100.0
    assert broken["source_path_correctness"] < 30.0
    assert broken["dependency_correctness"] < 25.0


def test_v4_benchmark_penalizes_ambiguous_model_choice_and_blurred_closeout_gate(tmp_path: Path) -> None:
    manifest = benchmark_v4.load_manifest(MANIFEST_V4_PATH)
    tasks = benchmark_v4.load_tasks(manifest)
    payload = _perfect_candidate_packet(tasks, task_suite_id="command_node_btc5_v4")

    headroom = payload["responses"][0]
    assert isinstance(headroom, dict)
    headroom["owner_model"] = "Claude Code | Sonnet 4.5"
    headroom["dependencies"] = list(reversed(headroom["dependencies"]))

    overnight = payload["responses"][1]
    assert isinstance(overnight, dict)
    overnight["objective"] = "Tighten the overnight closeout gate without blurring the acceptance rule."
    overnight["notes"] = "Keep the overnight gate honest and do not call a short local run green."
    overnight["checklist"] = [
        "A short local run can no longer produce green",
        "A real overnight run can still produce green with null results",
    ]

    candidate_path = tmp_path / "blurred_v4.md"
    candidate_path.write_text(_candidate_markdown(payload), encoding="utf-8")

    packet = benchmark_v4.evaluate_candidate(
        MANIFEST_V4_PATH,
        candidate_path,
        allow_noncanonical_candidate=True,
    )
    task_scores = {row["task_id"]: row for row in packet["tasks"]}
    broken_headroom = task_scores["agent_lane_headroom_rebenchmark"]
    broken_overnight = task_scores["overnight_closeout_lane_artifact"]

    assert packet["total_score"] < 100.0
    assert broken_headroom["dispatch_completeness"] < 25.0
    assert broken_headroom["dependency_correctness"] < 25.0
    assert broken_overnight["dispatch_completeness"] < 25.0
    assert broken_overnight["judge_clarity"] < 20.0
