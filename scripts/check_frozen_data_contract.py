#!/usr/bin/env python3
"""Enforce frozen-data and snapshot offload contracts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "backtest" / "data" / "frozen_data_manifest.json"
BENCHMARK_MANIFEST_PATH = ROOT / "benchmarks" / "calibration_v1" / "manifest.json"

SNAPSHOT_ALLOWLIST = {
    "polymarket-bot/snapshots/README.md",
    "polymarket-bot/snapshots/.gitignore",
}

REQUIRED_PRIORITY_ENTRIES = {
    "backtest/data/historical_markets.json": {
        "classification": "reproducible_generated_cache",
        "tracked": False,
    },
    "backtest/data/claude_cache.json": {
        "classification": "frozen_benchmark_input",
        "tracked": True,
    },
    "polymarket-bot/snapshots/20260305_2243": {
        "classification": "historical_snapshot",
        "tracked": False,
    },
}


def tracked_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    return {
        entry
        for entry in result.stdout.decode("utf-8").split("\0")
        if entry
    }


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected top-level object")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    if manifest.get("version") != 1:
        issues.append("manifest version must equal 1")

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        issues.append("manifest entries must be a non-empty list")
        return issues

    seen_paths: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            issues.append(f"entries[{index}] must be an object")
            continue

        path = entry.get("path")
        classification = entry.get("classification")
        tracked = entry.get("tracked")

        if not isinstance(path, str) or not path:
            issues.append(f"entries[{index}] missing path")
            continue
        if path in seen_paths:
            issues.append(f"duplicate manifest path: {path}")
        seen_paths.add(path)

        if not isinstance(classification, str) or not classification:
            issues.append(f"entries[{index}] missing classification for {path}")

        if not isinstance(tracked, bool):
            issues.append(f"entries[{index}] tracked must be boolean for {path}")

        if classification == "frozen_benchmark_input" and tracked is True:
            sha256 = entry.get("sha256")
            if not isinstance(sha256, str) or len(sha256) != 64:
                issues.append(f"frozen tracked entry missing sha256: {path}")

    return issues


def validate_priority_entries(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    entries = manifest.get("entries")
    by_path = {
        entry.get("path"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }

    for path, expected in REQUIRED_PRIORITY_ENTRIES.items():
        entry = by_path.get(path)
        if entry is None:
            issues.append(f"missing priority manifest entry: {path}")
            continue
        if entry.get("classification") != expected["classification"]:
            issues.append(
                f"priority classification mismatch for {path}: "
                f"{entry.get('classification')} != {expected['classification']}"
            )
        if entry.get("tracked") is not expected["tracked"]:
            issues.append(
                f"priority tracked mismatch for {path}: "
                f"{entry.get('tracked')} != {expected['tracked']}"
            )

    return issues


def validate_tracking_contract(manifest: dict[str, Any], tracked: set[str]) -> list[str]:
    issues: list[str] = []
    entries = manifest.get("entries")

    allowed_backtest_tracked = {
        "backtest/data/README.md",
        "backtest/data/.gitignore",
        "backtest/data/frozen_data_manifest.json",
    }

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        is_tracked = entry.get("tracked")
        if not isinstance(path, str) or not isinstance(is_tracked, bool):
            continue

        if path.endswith("/"):
            path = path.rstrip("/")

        if is_tracked:
            if path not in tracked:
                issues.append(f"manifest marks tracked but git does not track: {path}")
                continue
            allowed_backtest_tracked.add(path)
            continue

        prefix = f"{path.rstrip('/')}/"
        if path in tracked:
            issues.append(f"manifest marks untracked but git tracks file: {path}")
        if any(rel.startswith(prefix) for rel in tracked):
            issues.append(f"manifest marks untracked but git tracks descendants under: {path}")

    for rel_path in tracked:
        if rel_path.startswith("backtest/data/") and rel_path not in allowed_backtest_tracked:
            issues.append(f"unexpected tracked file in backtest/data: {rel_path}")

    for rel_path in tracked:
        if not rel_path.startswith("polymarket-bot/snapshots/"):
            continue
        if rel_path not in SNAPSHOT_ALLOWLIST:
            issues.append(f"tracked snapshot artifact is not allowed: {rel_path}")

    return sorted(set(issues))


def validate_hash_contract(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    entries = manifest.get("entries")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("classification") != "frozen_benchmark_input" or entry.get("tracked") is not True:
            continue
        rel_path = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(rel_path, str) or not isinstance(expected, str):
            continue

        abs_path = ROOT / rel_path
        if not abs_path.exists():
            issues.append(f"frozen input missing on disk: {rel_path}")
            continue

        actual = _sha256(abs_path)
        if actual != expected:
            issues.append(f"sha256 mismatch for {rel_path}: {actual} != {expected}")

    benchmark = _load_json(BENCHMARK_MANIFEST_PATH)
    benchmark_data = benchmark.get("data") if isinstance(benchmark, dict) else None
    if not isinstance(benchmark_data, dict):
        return issues + ["benchmark manifest missing data block"]

    by_path = {
        entry.get("path"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }

    for path_key, hash_key in (
        ("markets_path", "markets_sha256"),
        ("cache_path", "cache_sha256"),
    ):
        rel_path = benchmark_data.get(path_key)
        expected_hash = benchmark_data.get(hash_key)
        if not isinstance(rel_path, str) or not isinstance(expected_hash, str):
            issues.append(f"benchmark manifest missing {path_key}/{hash_key}")
            continue

        entry = by_path.get(rel_path)
        if entry is None:
            issues.append(f"benchmark manifest path missing from frozen data manifest: {rel_path}")
            continue

        manifest_hash = entry.get("sha256")
        if manifest_hash != expected_hash:
            issues.append(
                f"hash mismatch between manifests for {rel_path}: "
                f"{manifest_hash} != {expected_hash}"
            )

    return issues


def run_checks() -> list[str]:
    issues: list[str] = []
    if not MANIFEST_PATH.exists():
        return [f"missing manifest: {MANIFEST_PATH.relative_to(ROOT)}"]

    manifest = _load_json(MANIFEST_PATH)
    tracked = tracked_files()

    issues.extend(validate_manifest_schema(manifest))
    issues.extend(validate_priority_entries(manifest))
    issues.extend(validate_tracking_contract(manifest, tracked))
    issues.extend(validate_hash_contract(manifest))

    return sorted(set(issues))


def main() -> int:
    issues = run_checks()
    if issues:
        print("Frozen data contract check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Frozen data contract check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
