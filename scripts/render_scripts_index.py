#!/usr/bin/env python3
"""Render scripts/README.md from scripts/scripts_catalog.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "scripts" / "scripts_catalog.json"
README_PATH = ROOT / "scripts" / "README.md"


def _render_table(columns: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_markdown(catalog: dict) -> str:
    lines: list[str] = []
    lines.append(f"# {catalog['title']}")
    lines.append("")
    lines.append(
        f"_Generated from `{catalog['generated_from']}` via `python3 scripts/render_scripts_index.py --write`._"
    )
    lines.append("")
    lines.append("Canonical command path rule:")
    lines.append("")
    for idx, item in enumerate(catalog["command_path_rule"], start=1):
        lines.append(f"{idx}. {item}")

    for section in catalog["table_sections"]:
        lines.append("")
        lines.append(f"## {section['heading']}")
        lines.append("")
        lines.extend(_render_table(section["columns"], section["rows"]))

    for section in catalog["bullet_sections"]:
        lines.append("")
        lines.append(f"## {section['heading']}")
        lines.append("")
        for item in section["items"]:
            lines.append(f"- {item}")

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write scripts/README.md from manifest")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if scripts/README.md is out of date")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rendered = render_markdown(catalog)

    if args.check:
        current = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""
        if current != rendered:
            print("scripts/README.md is out of date. Run: python3 scripts/render_scripts_index.py --write")
            return 1
        print("scripts/README.md is up to date")
        return 0

    if args.write:
        README_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {README_PATH}")
        return 0

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
