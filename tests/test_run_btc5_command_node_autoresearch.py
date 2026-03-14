from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.run_btc5_command_node_autoresearch as runner

from benchmarks.command_node_btc5.v4.benchmark import load_manifest, load_tasks


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_V1_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v1" / "manifest.json"
MANIFEST_V2_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v2" / "manifest.json"
MANIFEST_V3_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v3" / "manifest.json"
MANIFEST_V4_PATH = ROOT / "benchmarks" / "command_node_btc5" / "v4" / "manifest.json"
RUNNER_PATH = ROOT / "scripts" / "run_btc5_command_node_autoresearch.py"


def _candidate_packet(manifest_path: Path, *, weak: bool = False) -> dict[str, object]:
    manifest = load_manifest(manifest_path)
    tasks = load_tasks(manifest)
    responses: list[dict[str, object]] = []
    for index, task in enumerate(tasks):
        response = {
            "task_id": task.task_id,
            "objective": f"Execute {task.title} with {'; '.join(task.required_clarity_terms)} and preserve the frozen BTC5 task contract.",
            "owner_model": task.expected_owner_model,
            "read_first": list(task.required_read_first),
            "files_to_edit": list(task.required_files_to_edit),
            "output_files": list(task.required_output_files),
            "dependencies": list(task.required_dependency_order),
            "verification_commands": [f"verify {term}" for term in task.required_verification_terms],
            "checklist": list(task.required_checklist),
            "notes": f"Follow the machine-truth bundle, keep one owner per path, and preserve {' '.join(task.required_clarity_terms)}.",
        }
        if weak and index == 0:
            response["owner_model"] = "Wrong Model"
            response["files_to_edit"] = []
            response["output_files"] = []
            response["dependencies"] = ["emit_handoff"]
        responses.append(response)
    task_suite_id = str((manifest.get("scoring") or {}).get("task_suite_id") or "")
    return {
        "task_suite_id": task_suite_id,
        "candidate_label": "weak" if weak else "strong",
        "responses": responses,
    }


def _candidate_markdown(manifest_path: Path, *, weak: bool = False) -> str:
    return "# BTC5 Command Node Candidate\n\n```json\n" + json.dumps(_candidate_packet(manifest_path, weak=weak), indent=2) + "\n```\n"


def _repo_baseline_markdown() -> str:
    return (ROOT / "btc5_command_node.md").read_text(encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_runner(
    candidate: Path,
    *,
    results_path: Path,
    runs_dir: Path,
    champion_path: Path,
    latest_path: Path,
    chart_path: Path,
    manifest_path: Path | None = None,
    allow_noncanonical_candidate: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(RUNNER_PATH),
        "--candidate-md",
        str(candidate),
        "--results-ledger",
        str(results_path),
        "--runs-dir",
        str(runs_dir),
        "--champion-out",
        str(champion_path),
        "--latest-out",
        str(latest_path),
        "--svg-out",
        str(chart_path),
    ]
    if manifest_path is not None:
        command.extend(["--manifest", str(manifest_path)])
    if allow_noncanonical_candidate:
        command.append("--allow-noncanonical-candidate")
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_select_proposer_policy_can_force_escalated() -> None:
    args = runner.parse_args(["--force-proposer-tier", "escalated"])

    selection = runner._select_proposer_policy(
        rows=[],
        champion=None,
        now=runner._now_utc(),
        args=args,
    )

    assert selection["tier"] == "escalated"
    assert selection["proposer_model"] == runner.DEFAULT_ESCALATED_PROPOSER
    assert "forced_escalated" in selection["reason_tags"]


def test_runner_rejects_noncanonical_candidate_without_escape_hatch(tmp_path: Path) -> None:
    candidate = tmp_path / "strong.md"
    candidate.write_text(_candidate_markdown(MANIFEST_V4_PATH), encoding="utf-8")

    results_path = tmp_path / "results.jsonl"
    runs_dir = tmp_path / "runs"
    champion_path = tmp_path / "champion.json"
    latest_path = tmp_path / "latest.json"
    chart_path = tmp_path / "progress.svg"

    result = _run_runner(
        candidate,
        results_path=results_path,
        runs_dir=runs_dir,
        champion_path=champion_path,
        latest_path=latest_path,
        chart_path=chart_path,
    )

    assert result.returncode != 0
    assert "one mutable surface only" in result.stderr
    assert not results_path.exists()
    assert not champion_path.exists()
    assert not latest_path.exists()


def test_runner_defaults_to_v4_manifest_and_writes_proposer_metadata(tmp_path: Path) -> None:
    candidate = tmp_path / "baseline.md"
    original_text = _repo_baseline_markdown()
    candidate.write_text(original_text, encoding="utf-8")

    results_path = tmp_path / "results.jsonl"
    runs_dir = tmp_path / "runs"
    champion_path = tmp_path / "champion.json"
    latest_path = tmp_path / "latest.json"
    chart_path = tmp_path / "progress.svg"

    result = _run_runner(
        candidate,
        results_path=results_path,
        runs_dir=runs_dir,
        champion_path=champion_path,
        latest_path=latest_path,
        chart_path=chart_path,
        allow_noncanonical_candidate=True,
    )

    assert result.returncode == 0, result.stderr
    ledger_rows = _load_jsonl(results_path)
    assert len(ledger_rows) == 1
    first = ledger_rows[0]
    assert first["status"] == "keep"
    assert first["decision_reason"] == "baseline_frontier"
    assert first["task_suite_id"] == "command_node_btc5_v4"
    assert first["proposal_id"] == "proposal_0001"
    assert first["proposer_model"] == "command-node-routine-proposer"
    assert first["estimated_llm_cost_usd"] == pytest.approx(0.35)
    assert first["mutation_type"] == "targeted_task_repair"
    assert isinstance(first["mutation_summary"], dict)
    assert first["mutable_surface"] == str(candidate)
    assert first["candidate_program_path"].endswith("_candidate.md")
    assert candidate.read_text(encoding="utf-8") != original_text
    champion = json.loads(champion_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert champion["benchmark_id"] == "command_node_btc5_v4"
    assert champion["task_suite_id"] == "command_node_btc5_v4"
    assert champion["candidate_program_path"] == str(candidate)
    assert latest["latest_total_score"] < 100.0
    assert latest["latest_loss"] > 0.0
    assert latest["latest_proposal"]["proposal_id"] == "proposal_0001"
    assert latest["latest_proposal"]["proposer_tier"] == "routine"
    assert chart_path.exists()
    assert len(list(runs_dir.glob("experiment_*.json"))) == 1
    assert len(list(runs_dir.glob("experiment_*_candidate.md"))) == 1


def test_runner_hill_climbs_then_discards_no_better_candidate_without_overwriting_surface(tmp_path: Path) -> None:
    candidate = tmp_path / "perfect.md"
    candidate.write_text(_candidate_markdown(MANIFEST_V4_PATH), encoding="utf-8")

    results_path = tmp_path / "results.jsonl"
    runs_dir = tmp_path / "runs"
    champion_path = tmp_path / "champion.json"
    latest_path = tmp_path / "latest.json"
    chart_path = tmp_path / "progress.svg"

    surface_versions = [candidate.read_text(encoding="utf-8")]
    statuses: list[str] = []
    for _ in range(5):
        result = _run_runner(
            candidate,
            results_path=results_path,
            runs_dir=runs_dir,
            champion_path=champion_path,
            latest_path=latest_path,
            chart_path=chart_path,
            allow_noncanonical_candidate=True,
        )
        assert result.returncode == 0, result.stderr
        ledger_rows = _load_jsonl(results_path)
        latest_row = ledger_rows[-1]
        statuses.append(str(latest_row["status"]))
        current_surface = candidate.read_text(encoding="utf-8")
        if latest_row["status"] == "keep":
            assert current_surface != surface_versions[-1]
        else:
            assert latest_row["decision_reason"] == "no_better_candidate"
            assert current_surface == surface_versions[-1]
            break
        surface_versions.append(current_surface)
    else:
        raise AssertionError("runner never reached a no_better_candidate discard within five attempts")

    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert statuses.count("keep") >= 1
    assert statuses[-1] == "discard"
    assert latest["latest_status"] == "discard"
    assert latest["latest_decision_reason"] == "no_better_candidate"
    assert latest["champion"]["experiment_id"] == statuses.count("keep")


def test_runner_ignores_legacy_champion_from_old_suite(tmp_path: Path) -> None:
    candidate = tmp_path / "baseline.md"
    original_text = _repo_baseline_markdown()
    candidate.write_text(original_text, encoding="utf-8")

    results_path = tmp_path / "results.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "experiment_id": 1,
                "evaluated_at": "2026-03-11T00:15:00+00:00",
                "benchmark_id": "command_node_btc5_v3",
                "task_suite_id": "command_node_btc5_v3",
                "status": "keep",
                "loss": 0.0,
                "estimated_llm_cost_usd": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    champion_path = tmp_path / "champion.json"
    champion_path.write_text(
        json.dumps(
            {
                "benchmark_id": "command_node_btc5_v3",
                "task_suite_id": "command_node_btc5_v3",
                "experiment_id": 1,
                "loss": 0.0,
            }
        ),
        encoding="utf-8",
    )
    runs_dir = tmp_path / "runs"
    latest_path = tmp_path / "latest.json"
    chart_path = tmp_path / "progress.svg"

    result = _run_runner(
        candidate,
        results_path=results_path,
        runs_dir=runs_dir,
        champion_path=champion_path,
        latest_path=latest_path,
        chart_path=chart_path,
        allow_noncanonical_candidate=True,
    )

    assert result.returncode == 0, result.stderr
    ledger_rows = _load_jsonl(results_path)
    assert [row["task_suite_id"] for row in ledger_rows] == ["command_node_btc5_v3", "command_node_btc5_v4"]
    assert ledger_rows[1]["status"] == "keep"
    assert ledger_rows[1]["decision_reason"] == "baseline_frontier"

    champion = json.loads(champion_path.read_text(encoding="utf-8"))
    assert champion["benchmark_id"] == "command_node_btc5_v4"
    assert champion["experiment_id"] == 2


def test_runner_escalates_after_ten_discards(tmp_path: Path) -> None:
    candidate = tmp_path / "baseline.md"
    candidate.write_text(_repo_baseline_markdown(), encoding="utf-8")

    results_path = tmp_path / "results.jsonl"
    discard_rows = [
        {
            "experiment_id": index,
            "evaluated_at": f"2026-03-11T0{index % 10}:00:00+00:00",
            "benchmark_id": "command_node_btc5_v4",
            "task_suite_id": "command_node_btc5_v4",
            "status": "discard",
            "loss": 10.0 + index,
            "estimated_llm_cost_usd": 0.35,
        }
        for index in range(1, 11)
    ]
    results_path.write_text(
        "\n".join(json.dumps(row) for row in discard_rows) + "\n",
        encoding="utf-8",
    )
    runs_dir = tmp_path / "runs"
    champion_path = tmp_path / "champion.json"
    latest_path = tmp_path / "latest.json"
    chart_path = tmp_path / "progress.svg"

    result = _run_runner(
        candidate,
        results_path=results_path,
        runs_dir=runs_dir,
        champion_path=champion_path,
        latest_path=latest_path,
        chart_path=chart_path,
        allow_noncanonical_candidate=True,
    )

    assert result.returncode == 0, result.stderr
    ledger_rows = _load_jsonl(results_path)
    latest_row = ledger_rows[-1]
    assert latest_row["proposer_model"] == "command-node-escalated-proposer"
    assert latest_row["estimated_llm_cost_usd"] == pytest.approx(1.25)
    assert latest_row["mutation_type"] == "full_packet_refresh"

    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["latest_proposal"]["proposer_tier"] == "escalated"
    assert "consecutive_discards_threshold_reached" in latest["latest_proposal"]["reason_tags"]


@pytest.mark.parametrize(
    ("manifest_path", "expected_task_suite_id"),
    (
        (MANIFEST_V1_PATH, "command_node_btc5_v1"),
        (MANIFEST_V2_PATH, "command_node_btc5_v2"),
        (MANIFEST_V3_PATH, "command_node_btc5_v3"),
    ),
)
def test_runner_supports_legacy_manifest_override(
    manifest_path: Path,
    expected_task_suite_id: str,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / f"{expected_task_suite_id}.md"
    candidate.write_text(_candidate_markdown(manifest_path), encoding="utf-8")

    results_path = tmp_path / "results.jsonl"
    runs_dir = tmp_path / "runs"
    champion_path = tmp_path / "champion.json"
    latest_path = tmp_path / "latest.json"
    chart_path = tmp_path / "progress.svg"

    result = _run_runner(
        candidate,
        results_path=results_path,
        runs_dir=runs_dir,
        champion_path=champion_path,
        latest_path=latest_path,
        chart_path=chart_path,
        manifest_path=manifest_path,
        allow_noncanonical_candidate=True,
    )

    assert result.returncode == 0, result.stderr
    ledger_rows = _load_jsonl(results_path)
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["status"] == "keep"
    assert ledger_rows[0]["task_suite_id"] == expected_task_suite_id
