#!/usr/bin/env python3
"""Render scripts/DEPRECATION_CANDIDATES.md from scripts/deprecation_catalog.json."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "scripts" / "deprecation_catalog.json"
OUTPUT_PATH = ROOT / "scripts" / "DEPRECATION_CANDIDATES.md"


def _run_rg(pattern: str, scope_paths: list[str]) -> tuple[int, str]:
    cmd = ["rg", "-n", pattern, *scope_paths]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return len(lines), "\n".join(lines)


def _escape(pattern: str) -> str:
    return pattern.replace(".", "\\.")


def render_markdown(catalog: dict) -> str:
    lines: list[str] = []
    lines.append(f"# {catalog['title']}")
    lines.append("")
    lines.append(
        f"_Generated from `{catalog['generated_from']}` via `python3 scripts/render_deprecation_candidates.py --write`._"
    )
    lines.append("")
    lines.append("This file tracks wrappers that could be deprecated in a future wave after reference migration.")
    lines.append("")

    pattern = "|".join(_escape(item["path"]) for item in catalog["candidates"])
    scope_joined = " ".join(catalog["reference_scope_paths"])
    lines.append("## Reference-Proof Command")
    lines.append("")
    lines.append("```bash")
    lines.append(f'rg -n "{pattern}" {scope_joined}')
    lines.append("```")
    lines.append("")

    lines.append("## Current Blockers")
    lines.append("")
    lines.append("| Script | Reference count | External refs | Why not removed now |")
    lines.append("|---|---:|---:|---|")

    scope_paths = catalog["reference_scope_paths"]
    external_scope_paths = catalog["external_scope_paths"]

    for item in catalog["candidates"]:
        script = item["path"]
        script_pat = _escape(script)
        total_count, _ = _run_rg(script_pat, scope_paths)
        ext_count, _ = _run_rg(script_pat, external_scope_paths)
        lines.append(f"| `{script}` | {total_count} | {ext_count} | {item['why_not_removed']} |")

    lines.append("")
    lines.append("## Completed In This Wave")
    lines.append("")
    lines.append("| Script | Action | Proof |")
    lines.append("|---|---|---|")
    for item in catalog.get("completed", []):
        lines.append(f"| `{item['path']}` | {item['action']} | {item['proof']} |")

    lines.append("")
    lines.append("## Exit Criteria For Future Deletion")
    lines.append("")
    for idx, criterion in enumerate(catalog.get("exit_criteria", []), start=1):
        lines.append(f"{idx}. {criterion}")

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write scripts/DEPRECATION_CANDIDATES.md")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if output is stale")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rendered = render_markdown(catalog)

    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print("scripts/DEPRECATION_CANDIDATES.md is out of date. Run: python3 scripts/render_deprecation_candidates.py --write")
            return 1
        print("scripts/DEPRECATION_CANDIDATES.md is up to date")
        return 0

    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {OUTPUT_PATH}")
        return 0

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
