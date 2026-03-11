#!/usr/bin/env python3
"""Validate docs index presence and minimal metadata contracts."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INDEX_DIRS = (
    Path("docs/api"),
    Path("docs/adr"),
    Path("docs/launch"),
    Path("docs/website"),
)

INDEX_REQUIRED_KEYS = (
    "Status",
    "Last reviewed",
    "Scope",
)

WEBSITE_REQUIRED_FRONT_MATTER_KEYS = (
    "title",
    "status",
    "doc_type",
    "last_reviewed",
)

KEY_PATTERN = re.compile(r"^-\s+([^:]+):\s+.+$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_index_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines()[:24]:
        match = KEY_PATTERN.match(line.strip())
        if match:
            keys.add(match.group(1).strip())
    return keys


def extract_front_matter(text: str) -> list[str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines[1:idx]
    return None


def parse_yaml_like_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def main() -> int:
    issues: list[str] = []

    for rel_dir in INDEX_DIRS:
        index_path = ROOT / rel_dir / "README.md"
        if not index_path.exists():
            issues.append(f"{index_path.relative_to(ROOT)}: missing required directory index")
            continue

        keys = parse_index_keys(read_text(index_path))
        for required in INDEX_REQUIRED_KEYS:
            if required not in keys:
                issues.append(
                    f"{index_path.relative_to(ROOT)}: missing metadata key '- {required}:'"
                )

    website_dir = ROOT / "docs/website"
    for doc_path in sorted(website_dir.rglob("*.md")):
        if doc_path.name == "README.md":
            continue
        front_matter = extract_front_matter(read_text(doc_path))
        rel_path = doc_path.relative_to(ROOT)
        if front_matter is None:
            issues.append(f"{rel_path}: missing YAML front matter")
            continue
        keys = parse_yaml_like_keys(front_matter)
        for required in WEBSITE_REQUIRED_FRONT_MATTER_KEYS:
            if required not in keys:
                issues.append(f"{rel_path}: front matter missing '{required}:'")

    if issues:
        print("Docs index check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Docs index check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
