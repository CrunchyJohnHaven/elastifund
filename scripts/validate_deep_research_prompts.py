#!/usr/bin/env python3
"""Validate and index deep research prompts in UNEXECUTED_DEEP_RESEARCH_PROMPTS/.

Checks:
  - YAML frontmatter exists with required fields (id, title, tool, priority, status)
  - Each prompt contains all four required sections:
      Formulas Required, Measurable Hypotheses, Failure Modes, Direct Repo Integration Targets
  - No duplicate IDs
  - Prints machine-readable summary to stdout

Exit code 0 if all prompts pass, 1 if any fail.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "research" / "UNEXECUTED_DEEP_RESEARCH_PROMPTS"

REQUIRED_FRONTMATTER = {"id", "title", "tool", "priority", "status"}
REQUIRED_SECTIONS = [
    "Formulas Required",
    "Measurable Hypotheses",
    "Failure Modes",
    "Direct Repo Integration Targets",
]
VALID_STATUSES = {"READY", "DISPATCHED", "COMPLETED", "INTEGRATED"}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_TOOLS = {
    "CLAUDE_CODE",
    "CLAUDE_DEEP_RESEARCH",
    "CHATGPT_DEEP_RESEARCH",
    "COWORK",
    "GROK",
}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def validate_prompt(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    fm = parse_frontmatter(text)
    if not fm:
        errors.append("missing YAML frontmatter")
        return errors

    missing_fields = REQUIRED_FRONTMATTER - set(fm.keys())
    if missing_fields:
        errors.append(f"missing frontmatter fields: {sorted(missing_fields)}")

    if fm.get("status") and fm["status"] not in VALID_STATUSES:
        errors.append(f"invalid status: {fm['status']} (expected {VALID_STATUSES})")

    if fm.get("priority") and fm["priority"] not in VALID_PRIORITIES:
        errors.append(f"invalid priority: {fm['priority']} (expected {VALID_PRIORITIES})")

    if fm.get("tool") and fm["tool"] not in VALID_TOOLS:
        errors.append(f"invalid tool: {fm['tool']} (expected {VALID_TOOLS})")

    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in text and f"# {section}" not in text:
            errors.append(f"missing required section: '{section}'")

    return errors


def main() -> int:
    if not PROMPTS_DIR.is_dir():
        print(f"SKIP: {PROMPTS_DIR} does not exist")
        return 0

    prompt_files = sorted(PROMPTS_DIR.glob("BTC5_DRP_*.md"))
    if not prompt_files:
        print("SKIP: no BTC5_DRP_*.md files found")
        return 0

    seen_ids: dict[str, Path] = {}
    total_errors = 0
    summary: list[dict[str, str]] = []

    for path in prompt_files:
        errors = validate_prompt(path)
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        prompt_id = fm.get("id", "UNKNOWN")

        if prompt_id in seen_ids:
            errors.append(f"duplicate ID '{prompt_id}' (also in {seen_ids[prompt_id].name})")
        seen_ids[prompt_id] = path

        status = "PASS" if not errors else "FAIL"
        total_errors += len(errors)

        summary.append({
            "file": path.name,
            "id": prompt_id,
            "status": fm.get("status", "?"),
            "priority": fm.get("priority", "?"),
            "tool": fm.get("tool", "?"),
            "validation": status,
        })

        if errors:
            for err in errors:
                print(f"FAIL: {path.name}: {err}")

    print()
    print(f"{'FILE':<50} {'ID':<20} {'STATUS':<12} {'PRI':<5} {'TOOL':<25} {'VALID'}")
    print("-" * 120)
    for row in summary:
        print(
            f"{row['file']:<50} {row['id']:<20} {row['status']:<12} "
            f"{row['priority']:<5} {row['tool']:<25} {row['validation']}"
        )

    print()
    print(f"Total prompts: {len(prompt_files)}")
    print(f"Validation errors: {total_errors}")

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
