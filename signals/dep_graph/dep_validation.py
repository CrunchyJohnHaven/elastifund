"""Validation workflow helpers for B-1 edge labels."""

from __future__ import annotations

import json
from pathlib import Path

from signals.dep_graph.dep_graph_store import DepGraphStore


class DepValidationHarness:
    """Export review batches, import labels, and summarize accuracy."""

    def __init__(self, store: DepGraphStore) -> None:
        self.store = store

    def export_review_batch(
        self,
        path: str | Path,
        *,
        limit: int = 50,
        min_confidence: float = 0.7,
    ) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        batch = self.store.sample_edges_for_review(limit=limit, min_confidence=min_confidence)
        target.write_text(json.dumps(batch, indent=2, sort_keys=True), encoding="utf-8")
        return target

    def import_review_labels(self, path: str | Path) -> int:
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("review payload must be a list")
        self.store.record_validation_samples(payload)
        return len(payload)

    def accuracy_summary(self, *, min_confidence: float | None = None) -> dict[str, float | int]:
        return self.store.accuracy_summary(min_confidence=min_confidence)
