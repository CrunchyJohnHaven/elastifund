#!/usr/bin/env python3
"""Render docs/ops/repo_manifest.json from canonical repo maps and routing docs."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "docs" / "ops" / "repo_manifest.json"
REPO_MAP_PATH = ROOT / "docs" / "REPO_MAP.md"
AGENTS_PATH = ROOT / "AGENTS.md"
TESTS_README_PATH = ROOT / "tests" / "README.md"
NONTRADING_PACKAGE_MAP_PATH = ROOT / "nontrading" / "PACKAGE_MAP.md"

SOURCE_DOCS = (
    "AGENTS.md",
    "docs/REPO_MAP.md",
    "tests/README.md",
    "nontrading/PACKAGE_MAP.md",
)

ENTRYPOINTS = {
    "start_here": "docs/FORK_AND_RUN.md",
    "operator_packet": "COMMAND_NODE.md",
    "operator_policy": "PROJECT_INSTRUCTIONS.md",
    "machine_entrypoint": "AGENTS.md",
    "repo_map": "docs/REPO_MAP.md",
    "contributor_rules": "CONTRIBUTING.md",
}

SUBSYSTEM_PATHS = (
    "agent/",
    "archive/",
    "backtest/",
    "benchmarks/",
    "build/",
    "bot/",
    "config/",
    "data/",
    "data_layer/",
    "deploy/",
    "develop/",
    "diary/",
    "docs/",
    "edge-backlog/",
    "elastic/",
    "execution/",
    "flywheel/",
    "hub/",
    "infra/",
    "inventory/",
    "kalshi/",
    "leaderboards/",
    "live/",
    "logs/",
    "manage/",
    "nontrading/",
    "orchestration/",
    "polymarket-bot/",
    "reports/",
    "research/",
    "roadmap/",
    "scripts/",
    "shared/",
    "signals/",
    "simulator/",
    "src/",
    "state/",
    "strategies/",
    "tests/",
    "tweets/",
)

NARROW_TEST_COMMANDS = {
    "agent/": "make test",
    "archive/": "make verify-static",
    "backtest/": "pytest -q backtest/tests",
    "benchmarks/": "make test",
    "build/": "make verify-static",
    "bot/": "pytest -q bot/tests",
    "config/": "make test",
    "data/": "make verify-static",
    "data_layer/": "pytest -q data_layer/tests",
    "deploy/": "make verify-static",
    "develop/": "make verify-static",
    "diary/": "make verify-static",
    "docs/": "make verify-static",
    "edge-backlog/": "pytest -q edge-backlog/tests",
    "elastic/": "make verify-static",
    "execution/": "make test",
    "flywheel/": "make test",
    "hub/": "pytest -q hub/tests",
    "infra/": "make test",
    "inventory/": "pytest -q tests/test_inventory_service.py",
    "kalshi/": "make test",
    "leaderboards/": "make verify-static",
    "live/": "make verify-static",
    "logs/": "make verify-static",
    "manage/": "make verify-static",
    "nontrading/": "make test-nontrading",
    "orchestration/": "pytest -q orchestration/tests",
    "polymarket-bot/": "make test-polymarket",
    "reports/": "make verify-static",
    "research/": "make verify-static",
    "roadmap/": "make verify-static",
    "scripts/": "make hygiene",
    "shared/": "make test",
    "signals/": "make test",
    "simulator/": "pytest -q simulator/tests",
    "src/": "make test",
    "state/": "make verify-static",
    "strategies/": "make test",
    "tests/": "make test",
    "tweets/": "make verify-static",
}

CANONICAL_DOCS_BY_PATH = {
    "agent/": ["AGENTS.md", "docs/REPO_MAP.md"],
    "archive/": ["docs/REPO_MAP.md"],
    "backtest/": ["docs/REPO_MAP.md"],
    "benchmarks/": ["docs/REPO_MAP.md"],
    "build/": ["docs/REPO_MAP.md", "REPLIT_NEXT_BUILD.md"],
    "bot/": ["docs/REPO_MAP.md", "COMMAND_NODE.md"],
    "config/": ["PROJECT_INSTRUCTIONS.md", "docs/REPO_MAP.md"],
    "data/": ["docs/REPO_MAP.md"],
    "data_layer/": ["docs/REPO_MAP.md"],
    "deploy/": ["docs/REPO_MAP.md", "PROJECT_INSTRUCTIONS.md"],
    "develop/": ["docs/REPO_MAP.md"],
    "diary/": ["docs/REPO_MAP.md"],
    "docs/": ["docs/REPO_MAP.md", "docs/FORK_AND_RUN.md"],
    "edge-backlog/": ["docs/REPO_MAP.md"],
    "elastic/": ["docs/REPO_MAP.md"],
    "execution/": ["docs/REPO_MAP.md", "COMMAND_NODE.md"],
    "flywheel/": ["docs/REPO_MAP.md", "COMMAND_NODE.md"],
    "hub/": ["docs/REPO_MAP.md"],
    "infra/": ["docs/REPO_MAP.md"],
    "inventory/": ["docs/REPO_MAP.md"],
    "kalshi/": ["docs/REPO_MAP.md"],
    "leaderboards/": ["docs/REPO_MAP.md"],
    "live/": ["docs/REPO_MAP.md"],
    "logs/": ["docs/REPO_MAP.md"],
    "manage/": ["docs/REPO_MAP.md"],
    "nontrading/": ["docs/REPO_MAP.md", "docs/ops/finance_control_plane.md"],
    "orchestration/": ["docs/REPO_MAP.md"],
    "polymarket-bot/": ["docs/REPO_MAP.md"],
    "reports/": ["reports/manifest_latest.json", "docs/ops/llm_context_manifest.md"],
    "research/": ["docs/REPO_MAP.md"],
    "roadmap/": ["docs/REPO_MAP.md"],
    "scripts/": ["scripts/README.md", "docs/REPO_MAP.md"],
    "shared/": ["docs/REPO_MAP.md"],
    "signals/": ["docs/REPO_MAP.md"],
    "simulator/": ["docs/REPO_MAP.md"],
    "src/": ["docs/REPO_MAP.md"],
    "state/": ["docs/ops/finance_control_plane.md", "AGENTS.md"],
    "strategies/": ["docs/REPO_MAP.md", "COMMAND_NODE.md"],
    "tests/": ["tests/README.md", "CONTRIBUTING.md"],
    "tweets/": ["docs/REPO_MAP.md"],
}

HEAVY_MODULE_WARNINGS = {
    "backtest/": "Historical data, snapshots, and broad test surfaces can inflate context and runtime costs.",
    "bot/": "Live-trading-sensitive runtime path; changes require focused tests and evidence.",
    "nontrading/": "Finance and treasury-sensitive path; respect autonomy caps and destination policy.",
    "polymarket-bot/": "Standalone subproject with separate suite; skip by default unless paths changed.",
    "reports/": "Runtime artifacts and snapshots should stay generated and compact.",
    "research/": "Large narrative files can bloat LLM context; prefer narrow source loading.",
    "simulator/": "Simulation parameter sweeps can be compute-heavy; keep targeted commands narrow.",
}

MACHINE_CONTRACT_ARTIFACTS = (
    "reports/runtime_truth_latest.json",
    "reports/remote_cycle_status.json",
    "reports/remote_service_status.json",
    "reports/finance/latest.json",
    "reports/finance/subscription_audit.json",
    "reports/finance/allocation_plan.json",
    "reports/finance/action_queue.json",
    "reports/agent_workflow_mining/summary.json",
    "reports/manifest_latest.json",
)

RUNTIME_ONLY_PREFIXES = ("data/", "logs/", "state/")
GENERATED_PREFIXES = ("reports/", "data/", "logs/")
ARCHIVE_PREFIXES = ("archive/", "docs/ops/_archive/", "research/archive/")
def _parse_markdown_table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell) <= {"-"} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _extract_section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    start_index: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start_index = idx + 1
            break
    if start_index is None:
        return ""

    body: list[str] = []
    for line in lines[start_index:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _extract_directory_map_roles(repo_map_text: str) -> dict[str, dict[str, str]]:
    section = _extract_section(repo_map_text, "Directory Map")
    if not section.strip():
        return {}
    rows = _parse_markdown_table_rows(section)
    out: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        path_cell, purpose, notes = row[0], row[1], row[2]
        for path in re.findall(r"`([^`]+)`", path_cell):
            if path.endswith("/"):
                out[path] = {"package_role": purpose, "notes": notes}
    return out


def _extract_task_routing(agents_text: str) -> list[dict[str, object]]:
    section = _extract_section(agents_text, "Task Routing")
    if not section.strip():
        return []
    entries: list[dict[str, object]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        lane, path_blob = stripped[2:].split(":", 1)
        paths = re.findall(r"`([^`]+)`", path_blob)
        entries.append({"lane": lane.strip(), "paths": paths})
    return entries


def _extract_tests_narrow_entrypoints(text: str) -> list[dict[str, str]]:
    section = _extract_section(text, "Narrow Test Entrypoints")
    if not section.strip():
        return []
    rows = _parse_markdown_table_rows(section)
    entries: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        entries.append({"subsystem": row[0], "command": row[1]})
    return entries


def _extract_nontrading_package_rows(text: str) -> list[dict[str, str]]:
    rows = _parse_markdown_table_rows(text)
    if not rows:
        return []
    entries: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) < 4:
            continue
        entries.append(
            {
                "path": row[0].strip("`"),
                "role": row[1],
                "operator_entrypoint": row[2],
                "status": row[3],
            }
        )
    return entries


def _build_path_to_lane(task_routing: list[dict[str, object]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in task_routing:
        lane = str(row["lane"])
        for path in row["paths"]:
            if isinstance(path, str):
                mapping[path] = lane
    return mapping


def _derive_flags(path: str) -> dict[str, bool]:
    return {
        "archive": path.startswith(ARCHIVE_PREFIXES),
        "generated": path.startswith(GENERATED_PREFIXES),
        "runtime_only": path.startswith(RUNTIME_ONLY_PREFIXES),
    }


def build_payload() -> dict:
    repo_map_text = REPO_MAP_PATH.read_text(encoding="utf-8")
    agents_text = AGENTS_PATH.read_text(encoding="utf-8")
    tests_text = TESTS_README_PATH.read_text(encoding="utf-8")
    nontrading_text = NONTRADING_PACKAGE_MAP_PATH.read_text(encoding="utf-8")

    directory_roles = _extract_directory_map_roles(repo_map_text)
    task_routing = _extract_task_routing(agents_text)
    path_to_lane = _build_path_to_lane(task_routing)
    narrow_entrypoints = _extract_tests_narrow_entrypoints(tests_text)
    nontrading_rows = _extract_nontrading_package_rows(nontrading_text)
    subsystems: list[dict[str, object]] = []
    for path in SUBSYSTEM_PATHS:
        role_row = directory_roles.get(path, {})
        lane = path_to_lane.get(path) or path_to_lane.get(path.rstrip("/")) or "General"
        flags = _derive_flags(path)
        heavy_warning = HEAVY_MODULE_WARNINGS.get(path)

        subsystems.append(
            {
                "path": path,
                "owner_lane": lane,
                "package_role": role_row.get("package_role", "Unmapped package role"),
                "notes": role_row.get("notes", ""),
                "narrow_test_command": NARROW_TEST_COMMANDS.get(path, "make test"),
                "canonical_docs": CANONICAL_DOCS_BY_PATH.get(path, ["docs/REPO_MAP.md"]),
                "flags": flags,
                "heavy_module_warning": heavy_warning or "",
            }
        )

    payload = {
        "schema_version": "2026-03-11.repo-manifest.v1",
        "generated_at": date.today().isoformat(),
        "generator": "scripts/render_repo_manifest.py",
        "purpose": "Deterministic machine-readable routing for path ownership, canonical docs, and narrow verification.",
        "entrypoints": ENTRYPOINTS,
        "source_docs": list(SOURCE_DOCS),
        "machine_contract_artifacts": list(MACHINE_CONTRACT_ARTIFACTS),
        "refresh_commands": {
            "render": "make repo-manifest-refresh",
            "check": "make repo-manifest-check",
        },
        "task_routing": task_routing,
        "subsystems": subsystems,
        "tests_narrow_entrypoints": narrow_entrypoints,
        "nontrading_package_map_rows": nontrading_rows,
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write docs/ops/repo_manifest.json")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if docs/ops/repo_manifest.json is stale")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload()
    rendered = json.dumps(payload, indent=2, sort_keys=False) + "\n"

    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print("docs/ops/repo_manifest.json is out of date. Run: python3 scripts/render_repo_manifest.py --write")
            return 1
        print("docs/ops/repo_manifest.json is up to date")
        return 0

    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {OUTPUT_PATH}")
        return 0

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
