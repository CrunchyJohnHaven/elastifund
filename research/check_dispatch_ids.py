#!/usr/bin/env python3
"""Fail if non-pointer DISPATCH files reuse the same numeric ID."""

from __future__ import annotations

import re
from pathlib import Path

DISPATCH_RE = re.compile(r"^DISPATCH_(\d+)_.*\.md$")
POINTER_PREFIX = "# Pointer:"


def is_pointer_file(path: Path) -> bool:
    try:
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return bool(first and first[0].strip().startswith(POINTER_PREFIX))


def main() -> int:
    dispatch_dir = Path("research/dispatches")
    seen: dict[str, Path] = {}
    collisions: list[tuple[str, Path, Path]] = []

    for path in sorted(dispatch_dir.glob("DISPATCH_*.md")):
        m = DISPATCH_RE.match(path.name)
        if not m:
            continue
        if is_pointer_file(path):
            # Pointer stubs are compatibility aliases and do not own an ID.
            continue
        dispatch_id = m.group(1)
        if dispatch_id in seen:
            collisions.append((dispatch_id, seen[dispatch_id], path))
        else:
            seen[dispatch_id] = path

    if collisions:
        print("Dispatch ID collision(s) detected:")
        for dispatch_id, first, second in collisions:
            print(f"- ID {dispatch_id}: {first} <-> {second}")
        return 1

    print(f"Dispatch ID check passed ({len(seen)} canonical dispatch files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
