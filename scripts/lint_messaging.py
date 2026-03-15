"""Lint canonical public-facing files for forbidden messaging terminology."""

from __future__ import annotations

import sys
from pathlib import Path


FORBIDDEN = (
    "self-modifying binary",
    "remove the human from the loop",
    "agent swarm that makes money",
    "fully autonomous",
    "no human oversight",
    "uncontrolled",
)

PUBLIC_GLOBS = (
    "README.md",
    "index.html",
    "build/**/*.html",
    "docs/index.html",
    "docs/numbered/*.md",
    "elastic/**/*.html",
    "develop/**/*.html",
    "leaderboards/**/*.html",
    "roadmap/**/*.html",
)


def iter_public_files() -> list[Path]:
    files: set[Path] = set()
    root = Path(".")
    for pattern in PUBLIC_GLOBS:
        files.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(files)


def lint() -> int:
    errors: list[str] = []
    checked = 0
    for path in iter_public_files():
        checked += 1
        content = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN:
            if term in content:
                errors.append(f"FORBIDDEN term '{term}' found in {path}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Messaging lint passed: {checked} files checked, 0 violations")
    return 0


if __name__ == "__main__":
    sys.exit(lint())
