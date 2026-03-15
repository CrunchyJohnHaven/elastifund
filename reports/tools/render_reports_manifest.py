#!/usr/bin/env python3
"""Render a compact reports/ layout manifest."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
RETENTION_POLICY_PATH = REPORTS / "retention_policy.json"
OUT = REPORTS / "manifest_latest.json"


def _load_allowlist() -> list[str]:
    if not RETENTION_POLICY_PATH.exists():
        return []
    try:
        payload = json.loads(RETENTION_POLICY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    raw = payload.get("top_level_symlink_allowlist", [])
    if not isinstance(raw, list):
        return []
    normalized = sorted({str(item).strip() for item in raw if str(item).strip()})
    return normalized


def _top_level_file_stats() -> tuple[int, int, list[str], list[str], int, list[str], list[str]]:
    allowlist = _load_allowlist()
    allowset = set(allowlist)

    regular_files: list[str] = []
    symlinks: list[str] = []
    loose: list[str] = []

    for entry in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and not entry.is_symlink():
            continue
        if entry.is_symlink():
            symlinks.append(entry.name)
            continue
        if entry.is_file():
            regular_files.append(entry.name)
            continue
        loose.append(entry.name)

    non_allowlisted = sorted(name for name in symlinks if name not in allowset)
    return (
        len(regular_files),
        len(symlinks),
        loose,
        regular_files,
        len(non_allowlisted),
        allowlist,
        non_allowlisted,
    )


def main() -> int:
    (
        regular_count,
        symlink_count,
        loose,
        regular_files,
        non_allowlisted_count,
        allowlist,
        non_allowlisted,
    ) = _top_level_file_stats()
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_dir": str(REPORTS),
        "layout_status": {
            "top_level_regular_file_count": regular_count,
            "top_level_symlink_count": symlink_count,
            "top_level_loose_entry_count": len(loose),
            "compatibility_symlink_allowlist": allowlist,
            "non_allowlisted_symlink_count": non_allowlisted_count,
            "non_allowlisted_symlinks": non_allowlisted,
            "top_level_regular_files": regular_files,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
