"""Frozen evaluator for the BTC5 command-node benchmark lane."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MUTABLE_SURFACE = ROOT / "btc5_command_node.md"


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    task_suite_id: str
    title: str
    expected_owner_model: str
    required_read_first: tuple[str, ...]
    required_files_to_edit: tuple[str, ...]
    required_output_files: tuple[str, ...]
    required_dependency_order: tuple[str, ...]
    required_verification_terms: tuple[str, ...]
    required_checklist: tuple[str, ...]
    required_clarity_terms: tuple[str, ...]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class TaskResponse:
    task_id: str
    objective: str
    owner_model: str
    read_first: tuple[str, ...]
    files_to_edit: tuple[str, ...]
    output_files: tuple[str, ...]
    dependencies: tuple[str, ...]
    verification_commands: tuple[str, ...]
    checklist: tuple[str, ...]
    notes: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None, task_id: str) -> "TaskResponse":
        payload = payload or {}
        return cls(
            task_id=task_id,
            objective=_clean_text(payload.get("objective")),
            owner_model=_clean_text(payload.get("owner_model")),
            read_first=_clean_list(payload.get("read_first")),
            files_to_edit=_clean_list(payload.get("files_to_edit")),
            output_files=_clean_list(payload.get("output_files")),
            dependencies=_clean_list(payload.get("dependencies")),
            verification_commands=_clean_list(payload.get("verification_commands")),
            checklist=_clean_list(payload.get("checklist")),
            notes=_clean_text(payload.get("notes")),
        )


@dataclass(frozen=True)
class TaskScore:
    task_id: str
    title: str
    source_path_correctness: float
    dependency_correctness: float
    dispatch_completeness: float
    judge_clarity: float
    total_score: float
    response_missing: bool
    details: dict[str, Any]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in map(str, value) if item and str(item).strip())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract_candidate_packet(text: str) -> dict[str, Any]:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("candidate packet must decode to an object")
        return payload

    marker = "```json"
    start = text.find(marker)
    if start < 0:
        raise ValueError("candidate markdown is missing a fenced JSON packet")
    start += len(marker)
    end = text.find("```", start)
    if end < 0:
        raise ValueError("candidate markdown JSON block is not terminated")
    payload = json.loads(text[start:end].strip())
    if not isinstance(payload, dict):
        raise ValueError("candidate JSON block must decode to an object")
    return payload


def manifest_path(path_value: str) -> Path:
    return ROOT / path_value


def verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    tasks_path = manifest_path(manifest["data"]["tasks_path"])
    observed_sha = sha256_file(tasks_path)
    expected_sha = manifest["data"]["tasks_sha256"]
    if observed_sha != expected_sha:
        raise ValueError(
            f"checksum mismatch for {tasks_path}: expected {expected_sha}, observed {observed_sha}"
        )
    task_rows = [line for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_count = int(manifest["data"]["task_count"])
    if len(task_rows) != expected_count:
        raise ValueError(f"expected {expected_count} tasks, found {len(task_rows)}")
    return {
        "tasks_path": str(tasks_path.relative_to(ROOT)),
        "tasks_sha256": observed_sha,
        "task_count": len(task_rows),
    }


def load_tasks(manifest: dict[str, Any]) -> list[TaskDefinition]:
    verify_manifest(manifest)
    tasks_path = manifest_path(manifest["data"]["tasks_path"])
    rows: list[TaskDefinition] = []
    for raw_line in tasks_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        rows.append(
            TaskDefinition(
                task_id=str(payload["task_id"]),
                task_suite_id=str(payload["task_suite_id"]),
                title=str(payload["title"]),
                expected_owner_model=str(payload["expected_owner_model"]),
                required_read_first=tuple(payload.get("required_read_first") or []),
                required_files_to_edit=tuple(payload.get("required_files_to_edit") or []),
                required_output_files=tuple(payload.get("required_output_files") or []),
                required_dependency_order=tuple(payload.get("required_dependency_order") or []),
                required_verification_terms=tuple(payload.get("required_verification_terms") or []),
                required_checklist=tuple(payload.get("required_checklist") or []),
                required_clarity_terms=tuple(payload.get("required_clarity_terms") or []),
                provenance=dict(payload.get("provenance") or {}),
            )
        )
    return rows


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").lstrip("./")


def _normalize_term(value: str) -> str:
    return " ".join(value.lower().split())


def _coverage_points(
    expected: tuple[str, ...],
    observed: tuple[str, ...],
    points: float,
    *,
    contains: bool = False,
    path_mode: bool = False,
) -> tuple[float, int, int]:
    if not expected:
        return float(points), 0, 0
    if path_mode:
        expected_norm = [_normalize_path(item) for item in expected]
        observed_norm = {_normalize_path(item) for item in observed}
    else:
        expected_norm = [_normalize_term(item) for item in expected]
        observed_norm = {_normalize_term(item) for item in observed}
    matched = 0
    for item in expected_norm:
        if contains:
            if any(item in observed_item for observed_item in observed_norm):
                matched += 1
        elif item in observed_norm:
            matched += 1
    return round(points * matched / len(expected_norm), 4), matched, len(expected_norm)


def _lcs_length(expected: tuple[str, ...], observed: tuple[str, ...]) -> int:
    expected_norm = [_normalize_term(item) for item in expected]
    observed_norm = [_normalize_term(item) for item in observed]
    if not expected_norm or not observed_norm:
        return 0
    widths = len(observed_norm) + 1
    previous = [0] * widths
    current = [0] * widths
    for expected_item in expected_norm:
        for index, observed_item in enumerate(observed_norm, start=1):
            if expected_item == observed_item:
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous, current = current, [0] * widths
    return previous[-1]


def _structure_points(response: TaskResponse) -> tuple[float, dict[str, bool]]:
    objective_ok = 20 <= len(response.objective) <= 280
    notes_ok = 40 <= len(response.notes) <= 500
    lists_ok = all(
        values and len(set(values)) == len(values)
        for values in (
            response.read_first,
            response.files_to_edit,
            response.output_files,
            response.dependencies,
            response.checklist,
        )
    )
    verification_ok = bool(response.verification_commands)
    score = 0.0
    score += 4.0 if objective_ok else 0.0
    score += 4.0 if notes_ok else 0.0
    score += 3.0 if lists_ok else 0.0
    score += 3.0 if verification_ok else 0.0
    return score, {
        "objective_ok": objective_ok,
        "notes_ok": notes_ok,
        "lists_unique_and_present": lists_ok,
        "verification_present": verification_ok,
    }


def score_task(task: TaskDefinition, response: TaskResponse, manifest: dict[str, Any]) -> TaskScore:
    scoring = manifest["scoring"]
    read_points, read_matched, read_total = _coverage_points(
        task.required_read_first,
        response.read_first,
        float(scoring["read_first_points"]),
        path_mode=True,
    )
    file_points, files_matched, files_total = _coverage_points(
        task.required_files_to_edit,
        response.files_to_edit,
        float(scoring["files_to_edit_points"]),
        path_mode=True,
    )
    output_points, output_matched, output_total = _coverage_points(
        task.required_output_files,
        response.output_files,
        float(scoring["output_files_points"]),
        path_mode=True,
    )
    source_path_correctness = round(read_points + file_points + output_points, 4)

    lcs_length = _lcs_length(task.required_dependency_order, response.dependencies)
    dependency_correctness = round(
        float(scoring["dependency_order_points"]) * lcs_length / max(1, len(task.required_dependency_order)),
        4,
    )

    owner_points = (
        float(scoring["owner_model_points"])
        if _normalize_term(response.owner_model) == _normalize_term(task.expected_owner_model)
        else 0.0
    )
    verification_points, verification_matched, verification_total = _coverage_points(
        task.required_verification_terms,
        response.verification_commands,
        float(scoring["verification_points"]),
        contains=True,
    )
    checklist_points, checklist_matched, checklist_total = _coverage_points(
        task.required_checklist,
        response.checklist,
        float(scoring["checklist_points"]),
    )
    dispatch_completeness = round(owner_points + verification_points + checklist_points, 4)

    clarity_structure_points, structure_flags = _structure_points(response)
    clarity_terms_points, clarity_matched, clarity_total = _coverage_points(
        task.required_clarity_terms,
        tuple([response.objective, response.notes, *response.checklist, *response.dependencies]),
        float(scoring["clarity_term_points"]),
        contains=True,
    )
    judge_clarity = round(clarity_structure_points + clarity_terms_points, 4)
    total_score = round(
        source_path_correctness + dependency_correctness + dispatch_completeness + judge_clarity,
        4,
    )
    return TaskScore(
        task_id=task.task_id,
        title=task.title,
        source_path_correctness=source_path_correctness,
        dependency_correctness=dependency_correctness,
        dispatch_completeness=dispatch_completeness,
        judge_clarity=judge_clarity,
        total_score=total_score,
        response_missing=not any(
            (
                response.objective,
                response.owner_model,
                response.read_first,
                response.files_to_edit,
                response.output_files,
                response.dependencies,
                response.verification_commands,
                response.checklist,
                response.notes,
            )
        ),
        details={
            "matched_read_first": {"matched": read_matched, "expected": read_total},
            "matched_files_to_edit": {"matched": files_matched, "expected": files_total},
            "matched_output_files": {"matched": output_matched, "expected": output_total},
            "dependency_lcs": {"matched": lcs_length, "expected": len(task.required_dependency_order)},
            "owner_model_match": bool(owner_points),
            "verification_matches": {"matched": verification_matched, "expected": verification_total},
            "checklist_matches": {"matched": checklist_matched, "expected": checklist_total},
            "clarity_term_matches": {"matched": clarity_matched, "expected": clarity_total},
            "structure_flags": structure_flags,
        },
    )


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _resolve_candidate_path(path_value: str | Path) -> Path:
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def _git_metadata() -> dict[str, Any]:
    def _run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()

    return {
        "sha": _run("rev-parse", "HEAD") or "unknown",
        "branch": _run("branch", "--show-current") or "unknown",
        "dirty": bool(_run("status", "--short")),
    }


def evaluate_candidate(
    manifest_path_value: str | Path,
    candidate_packet_path: str | Path,
    *,
    allow_noncanonical_candidate: bool = False,
    description: str = "",
) -> dict[str, Any]:
    manifest_file = Path(manifest_path_value)
    if not manifest_file.is_absolute():
        manifest_file = ROOT / manifest_file
    candidate_file = _resolve_candidate_path(candidate_packet_path)

    manifest = load_manifest(manifest_file)
    canonical_candidate = manifest_path(manifest["mutable_surface"]).resolve()
    if (not allow_noncanonical_candidate) and candidate_file != canonical_candidate:
        raise ValueError(
            "command_node_btc5_v1 enforces one mutable surface: "
            f"{_relative_path(canonical_candidate)}"
        )
    task_rows = load_tasks(manifest)
    candidate_text = candidate_file.read_text(encoding="utf-8")
    packet = extract_candidate_packet(candidate_text)
    expected_suite_id = str(manifest["scoring"]["task_suite_id"])
    observed_suite_id = str(packet.get("task_suite_id") or "")
    if observed_suite_id != expected_suite_id:
        raise ValueError(f"candidate packet task_suite_id mismatch: expected {expected_suite_id}, observed {observed_suite_id}")

    responses_by_task: dict[str, dict[str, Any]] = {}
    for payload in packet.get("responses") or []:
        task_id = str((payload or {}).get("task_id") or "")
        if not task_id:
            continue
        if task_id in responses_by_task:
            raise ValueError(f"duplicate response for task_id={task_id}")
        responses_by_task[task_id] = dict(payload)

    task_scores: list[TaskScore] = []
    for task in task_rows:
        response = TaskResponse.from_payload(responses_by_task.get(task.task_id), task.task_id)
        task_scores.append(score_task(task, response, manifest))

    total_score = round(sum(item.total_score for item in task_scores) / max(1, len(task_scores)), 4)
    loss = round(100.0 - total_score, 4)
    subscores = {
        "source_path_correctness": round(
            sum(item.source_path_correctness for item in task_scores) / max(1, len(task_scores)),
            4,
        ),
        "dependency_correctness": round(
            sum(item.dependency_correctness for item in task_scores) / max(1, len(task_scores)),
            4,
        ),
        "dispatch_completeness": round(
            sum(item.dispatch_completeness for item in task_scores) / max(1, len(task_scores)),
            4,
        ),
        "judge_clarity": round(
            sum(item.judge_clarity for item in task_scores) / max(1, len(task_scores)),
            4,
        ),
    }

    return {
        "benchmark_id": manifest["benchmark_id"],
        "generated_at": utc_now_iso(),
        "description": description.strip(),
        "manifest_path": _relative_path(manifest_file),
        "candidate_program_path": _relative_path(candidate_file),
        "mutable_surface": manifest["mutable_surface"],
        "mutable_surface_sha256": sha256_file(candidate_file),
        "prompt_hash": sha256_file(candidate_file),
        "candidate_hash": sha256_file(candidate_file),
        "git": _git_metadata(),
        "objective": manifest["objective"],
        "task_suite": {
            "task_suite_id": expected_suite_id,
            "task_count": len(task_rows),
            "tasks_path": manifest["data"]["tasks_path"],
            "tasks_sha256": manifest["data"]["tasks_sha256"],
        },
        "candidate_label": str(packet.get("candidate_label") or candidate_file.stem),
        "subscores": subscores,
        "total_score": total_score,
        "loss": loss,
        "tasks": [asdict(item) for item in task_scores],
    }
