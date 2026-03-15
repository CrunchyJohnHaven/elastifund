#!/usr/bin/env python3
"""Prune non-allowlisted top-level symlinks in reports/."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
POLICY_PATH = REPORTS / "retention_policy.json"
ALIASES_INDEX_PATH = REPORTS / "legacy_aliases_latest.json"


def load_allowlist() -> set[str]:
    if not POLICY_PATH.exists():
        return set()
    try:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    values = payload.get("top_level_symlink_allowlist", [])
    if not isinstance(values, list):
        return set()
    normalized = {str(value).strip() for value in values if str(value).strip()}
    return normalized


def _load_alias_targets() -> dict[str, str]:
    if not ALIASES_INDEX_PATH.exists():
        return {}
    try:
        payload = json.loads(ALIASES_INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    aliases = payload.get("aliases", payload)
    if not isinstance(aliases, dict):
        return {}
    resolved: dict[str, str] = {}
    for key, value in aliases.items():
        name = str(key).strip()
        target = str(value).strip()
        if name and target:
            resolved[name] = target
    return resolved


def _discover_target(reports_dir: Path, alias_name: str, alias_targets: dict[str, str]) -> Path | None:
    configured = alias_targets.get(alias_name)
    if configured:
        target = reports_dir / configured
        if target.exists():
            return target

    direct = reports_dir / alias_name
    if direct.exists():
        return direct

    for candidate in sorted(reports_dir.rglob(alias_name)):
        if candidate.is_file() and candidate.parent != reports_dir:
            return candidate
    return None


def collapse_symlinks(*, reports_dir: Path, allowlist: set[str], apply: bool) -> dict[str, Any]:
    reports_dir = Path(reports_dir)
    symlink_names = sorted(path.name for path in reports_dir.iterdir() if path.is_symlink())
    kept = sorted(name for name in symlink_names if name in allowlist)
    removed = sorted(name for name in symlink_names if name not in allowlist)

    if apply:
        for name in removed:
            (reports_dir / name).unlink(missing_ok=True)

        alias_targets = _load_alias_targets()
        for alias_name in sorted(allowlist):
            alias_path = reports_dir / alias_name
            if alias_path.exists():
                continue
            target = _discover_target(reports_dir, alias_name, alias_targets)
            if target is None:
                continue
            relative_target = target.relative_to(reports_dir)
            alias_path.symlink_to(relative_target)

    return {
        "top_level_symlink_total": len(symlink_names),
        "top_level_symlink_kept": len(kept),
        "top_level_symlink_removed_or_planned": len(removed),
        "kept": kept,
        "removed": removed,
        "apply": bool(apply),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete non-allowlisted top-level symlinks in-place")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    allowlist = load_allowlist()
    summary = collapse_symlinks(reports_dir=REPORTS, allowlist=allowlist, apply=args.apply)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
