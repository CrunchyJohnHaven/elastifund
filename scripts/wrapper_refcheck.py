#!/usr/bin/env python3
"""Catalog-driven wrapper reference check for deprecation planning."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "scripts" / "deprecation_catalog.json"


@dataclass(frozen=True)
class CandidateCounts:
    path: str
    total: int
    external: int


def _escape(pattern: str) -> str:
    return re.escape(pattern)


def _count_refs(pattern: str, scope_paths: list[str]) -> int:
    cmd = ["rg", "-n", pattern, *scope_paths]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    return len([line for line in result.stdout.splitlines() if line.strip()])


def compute_counts(catalog: dict) -> list[CandidateCounts]:
    counts: list[CandidateCounts] = []
    scope_paths = catalog["reference_scope_paths"]
    external_scope_paths = catalog["external_scope_paths"]
    for item in catalog["candidates"]:
        path = item["path"]
        pat = _escape(path)
        counts.append(
            CandidateCounts(
                path=path,
                total=_count_refs(pat, scope_paths),
                external=_count_refs(pat, external_scope_paths),
            )
        )
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-only", action="store_true", help="Print only candidates with external refs == 0")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    counts = compute_counts(catalog)

    if args.ready_only:
        ready = [item for item in counts if item.external == 0]
        if not ready:
            print("No deprecation candidates are ready (external refs == 0).")
            return 0
        print("Ready deprecation candidates (external refs == 0):")
        for item in ready:
            print(f"- {item.path} (total refs: {item.total})")
        return 0

    print("Wrapper reference counts:")
    print("path,total_refs,external_refs")
    for item in counts:
        print(f"{item.path},{item.total},{item.external}")

    ready = [item for item in counts if item.external == 0]
    if ready:
        print("")
        print("Ready candidates:")
        for item in ready:
            print(f"- {item.path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
