"""Frozen evaluator wrapper for the BTC5 command-node benchmark v3 lane."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchmarks.command_node_btc5.v1 import benchmark as v1


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MUTABLE_SURFACE = v1.DEFAULT_MUTABLE_SURFACE
TaskDefinition = v1.TaskDefinition
TaskResponse = v1.TaskResponse
TaskScore = v1.TaskScore
extract_candidate_packet = v1.extract_candidate_packet
load_manifest = v1.load_manifest
load_tasks = v1.load_tasks
manifest_path = v1.manifest_path
score_task = v1.score_task
sha256_file = v1.sha256_file
utc_now_iso = v1.utc_now_iso
verify_manifest = v1.verify_manifest


def _benchmark_id(manifest_path_value: str | Path) -> str:
    manifest_file = Path(manifest_path_value)
    if not manifest_file.is_absolute():
        manifest_file = ROOT / manifest_file
    try:
        manifest = load_manifest(manifest_file)
    except Exception:
        return "command_node_btc5_v3"
    return str(manifest.get("benchmark_id") or "command_node_btc5_v3")


def evaluate_candidate(
    manifest_path_value: str | Path,
    candidate_packet_path: str | Path,
    *,
    allow_noncanonical_candidate: bool = False,
    description: str = "",
) -> dict[str, Any]:
    try:
        return v1.evaluate_candidate(
            manifest_path_value,
            candidate_packet_path,
            allow_noncanonical_candidate=allow_noncanonical_candidate,
            description=description,
        )
    except ValueError as error:
        message = str(error)
        legacy_prefix = "command_node_btc5_v1 enforces one mutable surface:"
        if message.startswith(legacy_prefix):
            benchmark_id = _benchmark_id(manifest_path_value)
            raise ValueError(message.replace("command_node_btc5_v1", benchmark_id, 1)) from error
        raise
