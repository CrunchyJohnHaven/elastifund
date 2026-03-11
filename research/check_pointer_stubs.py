#!/usr/bin/env python3
"""Validate research pointer stubs and their canonical targets."""

from __future__ import annotations

import re
from pathlib import Path

POINTER_PREFIX = "# Pointer:"
CODE_PATH_RE = re.compile(r"`([^`]+)`")


def iter_pointer_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        parts = set(path.parts)
        if ".git" in parts or "__pycache__" in parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if lines and lines[0].strip().startswith(POINTER_PREFIX):
            files.append(path)
    return files


def parse_targets(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    targets: list[str] = []
    capture = False
    for line in lines:
        if line.strip().lower().startswith("canonical file:"):
            capture = True
            continue
        if not capture:
            continue
        if line.strip().startswith("-"):
            m = CODE_PATH_RE.search(line)
            if m:
                targets.append(m.group(1).strip())
            continue
        if line.strip():
            break
    return targets


def main() -> int:
    root = Path("research")
    pointer_files = iter_pointer_files(root)
    errors: list[str] = []

    for path in pointer_files:
        targets = parse_targets(path)
        if not targets:
            errors.append(f"{path}: missing `Canonical file:` section or target list")
            continue
        for target in targets:
            target_path = Path(target)
            if not target_path.exists():
                errors.append(f"{path}: canonical target does not exist: {target}")
                continue
            if target_path.resolve() == path.resolve():
                errors.append(f"{path}: canonical target points to itself: {target}")

    if errors:
        print("Pointer stub check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print(f"Pointer stub check passed ({len(pointer_files)} pointer file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
