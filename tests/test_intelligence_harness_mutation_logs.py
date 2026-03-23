from __future__ import annotations

import json
from pathlib import Path

from scripts.intelligence_harness import (
    IntelligenceMetrics,
    log_mutation_acceptance,
    log_mutation_crash,
    log_mutation_rejection,
)


def _metrics(velocity: float, stale: float = 0.0) -> IntelligenceMetrics:
    return IntelligenceMetrics(
        validated_edge_discovery_velocity=velocity,
        stale_fallback_rate=stale,
    )


def test_mutation_acceptance_written_to_jsonl(tmp_path: Path):
    path = log_mutation_acceptance(
        "mut-1",
        _metrics(0.5),
        _metrics(1.0),
        notes=["better discovery"],
        ledger_dir=tmp_path,
    )
    assert path.name == "mutation_acceptances.jsonl"
    payload = json.loads(path.read_text().strip())
    assert payload["mutation_id"] == "mut-1"
    assert payload["outcome"] == "keep"
    assert payload["notes"] == ["better discovery"]


def test_mutation_rejection_written_to_jsonl(tmp_path: Path):
    path = log_mutation_rejection(
        "mut-2",
        _metrics(1.0),
        _metrics(0.8, stale=0.2),
        notes=["regression"],
        ledger_dir=tmp_path,
    )
    assert path.name == "mutation_rejections.jsonl"
    payload = json.loads(path.read_text().strip())
    assert payload["mutation_id"] == "mut-2"
    assert payload["outcome"] == "discard"


def test_mutation_crash_written_to_jsonl(tmp_path: Path):
    path = log_mutation_crash(
        "mut-3",
        _metrics(1.0),
        _metrics(1.0),
        notes=["harness crash"],
        ledger_dir=tmp_path,
    )
    assert path.name == "mutation_crashes.jsonl"
    payload = json.loads(path.read_text().strip())
    assert payload["mutation_id"] == "mut-3"
    assert payload["outcome"] == "crash"
