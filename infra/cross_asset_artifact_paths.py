"""Canonical + compatibility artifact path helpers for cross-asset lanes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class CrossAssetArtifactPaths:
    repo_root: Path
    data_plane_health_latest: Path
    instance1_artifact_latest_json: Path
    instance1_artifact_latest_md: Path
    instance1_artifact_compat_json: Path
    instance1_artifact_compat_md: Path

    @classmethod
    def for_repo(cls, repo_root: Path) -> "CrossAssetArtifactPaths":
        reports = repo_root / "reports"
        return cls(
            repo_root=repo_root,
            data_plane_health_latest=reports / "data_plane_health" / "latest.json",
            instance1_artifact_latest_json=reports / "instance1_data_plane" / "latest.json",
            instance1_artifact_latest_md=reports / "instance1_data_plane" / "latest.md",
            instance1_artifact_compat_json=reports / "parallel" / "instance1_multi_asset_data_plane_latest.json",
            instance1_artifact_compat_md=reports / "parallel" / "instance1_multi_asset_data_plane_latest.md",
        )

    def instance1_json_candidates(self) -> tuple[Path, ...]:
        return (self.instance1_artifact_latest_json, self.instance1_artifact_compat_json)

    def instance1_md_candidates(self) -> tuple[Path, ...]:
        return (self.instance1_artifact_latest_md, self.instance1_artifact_compat_md)


def normalize_repo_path(path: Path, *, repo_root: Path) -> str:
    """Prefer repo-relative strings so contracts stay stable across machines."""
    candidate = path if path.is_absolute() else (repo_root / path)
    candidate = candidate.resolve()
    root = repo_root.resolve()
    try:
        rel = candidate.relative_to(root)
    except ValueError:
        return str(candidate)
    return rel.as_posix()


def resolve_first_existing(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
