#!/usr/bin/env python3
"""Deterministic changed-path router for local and CI test selection.

Usage:
  python3 scripts/select_test_targets.py
  python3 scripts/select_test_targets.py path/one.py docs/README.md
  python3 scripts/select_test_targets.py --base-sha <sha> --head-sha <sha>
  python3 scripts/select_test_targets.py --format gha --base-sha <sha> --head-sha <sha>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

DOCS_STATIC_PREFIXES = (
    "build/",
    "docs/",
    "research/",
    "develop/",
    "leaderboards/",
    "manage/",
    "roadmap/",
    "elastic/",
    "diary/",
)
DOCS_STATIC_FILES = {"index.html", "site.css", "site.js"}
LITE_WORKFLOW_FILES = {"requirements-lite.txt"}
FASTPATH_METADATA_FILES = {
    "scripts/README.md",
    "scripts/DEPRECATION_CANDIDATES.md",
    "scripts/scripts_catalog.json",
    "scripts/deprecation_catalog.json",
    "requirements-lite.txt",
}
RUNTIME_ONLY_DIRS = ("data/", "logs/", "reports/")
PACKAGE_MAP_FILES = {"README.md", "PACKAGE_MAP.md"}
PACKAGE_MAP_OWNERS = {
    "agent",
    "archive",
    "codex_instances",
    "config",
    "data",
    "docs",
    "edge-backlog",
    "kalshi",
    "logs",
    "shared",
}

# Paths where a change should default to root regression.
ROOT_SIGNAL_PREFIXES = (
    "bot/",
    "execution/",
    "strategies/",
    "signals/",
    "infra/",
    "src/",
    "inventory/",
    "scripts/",
    "tests/",
    "config/",
)
ROOT_SIGNAL_FILES = {
    "Makefile",
    "pytest.ini",
    ".github/workflows/ci.yml",
}
GLOBAL_DEP_FILES = {
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-elastic.txt",
}
POLY_TEST_HINTS = (
    "polymarket",
    "clob",
    "pm_fast_market",
)
RESEARCH_SIM_PREFIXES = (
    "backtest/",
    "simulator/",
)
PLATFORM_PREFIXES = (
    "hub/",
    "data_layer/",
    "orchestration/",
    "edge-backlog/",
)


def _git_changed_paths() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []

    paths: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        candidate = line[3:]
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        paths.append(candidate)
    return sorted(set(paths))


def _git_diff_paths(base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def _is_docs_static_path(path: str) -> bool:
    if path in DOCS_STATIC_FILES:
        return True
    if path in LITE_WORKFLOW_FILES:
        return True
    if any(path.startswith(prefix) for prefix in DOCS_STATIC_PREFIXES):
        return True
    if path.endswith(".md"):
        return True

    parent = Path(path).parent.as_posix()
    name = Path(path).name
    if name in PACKAGE_MAP_FILES and parent in PACKAGE_MAP_OWNERS:
        return True

    if any(path.startswith(prefix) for prefix in RUNTIME_ONLY_DIRS):
        return True

    return False


def _requires_fastpath_metadata_checks(path: str) -> bool:
    if path in FASTPATH_METADATA_FILES:
        return True
    if Path(path).name == "PACKAGE_MAP.md":
        return True
    return False


def _is_fixture_contract_path(path: str) -> bool:
    return path.startswith("tests/fixtures/") or path.endswith("tests/test_fixture_ownership_contract.py")


def _is_nontrading_path(path: str) -> bool:
    return path.startswith("nontrading/") or path.startswith("tests/nontrading/")


def _is_polymarket_path(path: str) -> bool:
    if path.startswith("polymarket-bot/"):
        return True
    if not path.startswith("tests/"):
        return False
    name = Path(path).name.lower()
    return any(hint in name for hint in POLY_TEST_HINTS)


def _is_root_signal_path(path: str) -> bool:
    if path in GLOBAL_DEP_FILES:
        return True
    if path in ROOT_SIGNAL_FILES:
        return True
    if path.startswith("tests/nontrading/"):
        return False
    if path.startswith("polymarket-bot/"):
        return False
    if any(path.startswith(prefix) for prefix in RESEARCH_SIM_PREFIXES):
        return False
    if any(path.startswith(prefix) for prefix in PLATFORM_PREFIXES):
        return False
    return any(path.startswith(prefix) for prefix in ROOT_SIGNAL_PREFIXES)


def _is_research_sim_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in RESEARCH_SIM_PREFIXES)


def _is_platform_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PLATFORM_PREFIXES)


def _dedupe(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        ordered.append(command)
    return ordered


def route_paths(paths: list[str]) -> dict[str, object]:
    if not paths:
        return {
            "paths": [],
            "docs_or_static_only": True,
            "fastpath_metadata": False,
            "run_docs_static_checks": True,
            "run_fixture_ownership": False,
            "run_research_sim": False,
            "run_platform": False,
            "run_nontrading": False,
            "run_root": False,
            "run_polymarket": False,
            "run_hygiene": False,
            "local_commands": ["make verify-static"],
        }

    docs_only = all(_is_docs_static_path(path) for path in paths)
    fastpath_metadata = any(_requires_fastpath_metadata_checks(path) for path in paths)

    if docs_only:
        local_commands = ["make verify-fastpath"] if fastpath_metadata else ["make verify-static"]
        return {
            "paths": paths,
            "docs_or_static_only": True,
            "fastpath_metadata": fastpath_metadata,
            "run_docs_static_checks": True,
            "run_fixture_ownership": False,
            "run_research_sim": False,
            "run_platform": False,
            "run_nontrading": False,
            "run_root": False,
            "run_polymarket": False,
            "run_hygiene": False,
            "local_commands": local_commands,
        }

    dep_blast_radius = any(path in GLOBAL_DEP_FILES for path in paths)
    run_fixture_ownership = any(_is_fixture_contract_path(path) for path in paths)
    run_research_sim = dep_blast_radius or any(_is_research_sim_path(path) for path in paths)
    run_platform = dep_blast_radius or any(_is_platform_path(path) for path in paths)
    run_nontrading = any(_is_nontrading_path(path) for path in paths)
    run_polymarket = dep_blast_radius or any(_is_polymarket_path(path) for path in paths)
    run_root = dep_blast_radius or any(_is_root_signal_path(path) for path in paths)
    if dep_blast_radius and not run_root:
        run_root = True
    if run_root:
        # Root regression already exercises nontrading via canonical testpaths.
        run_nontrading = False

    # Safety ratchet: if we touched non-doc content but matched no lane, run root regression.
    if (
        not run_nontrading
        and not run_polymarket
        and not run_root
        and not run_research_sim
        and not run_platform
        and not run_fixture_ownership
    ):
        run_root = True

    local_commands: list[str] = ["make hygiene"]
    if run_fixture_ownership:
        local_commands.append("make test-fixture-ownership")
    if run_research_sim:
        local_commands.append("make test-research-sim")
    if run_platform:
        local_commands.append("make test-platform")
    if run_nontrading:
        local_commands.append("make test-nontrading")
    if run_root:
        local_commands.append("make test")
    if run_polymarket:
        local_commands.append("make test-polymarket")

    return {
        "paths": paths,
        "docs_or_static_only": False,
        "fastpath_metadata": fastpath_metadata,
        "run_docs_static_checks": False,
        "run_fixture_ownership": run_fixture_ownership,
        "run_research_sim": run_research_sim,
        "run_platform": run_platform,
        "run_nontrading": run_nontrading,
        "run_root": run_root,
        "run_polymarket": run_polymarket,
        "run_hygiene": True,
        "local_commands": _dedupe(local_commands),
    }


def suggest_targets(paths: list[str]) -> list[str]:
    """Backward-compatible helper used by unit tests and local wrappers."""
    return list(route_paths(paths)["local_commands"])


def _print_text(route: dict[str, object]) -> None:
    print("Changed paths:")
    for path in route["paths"]:
        print(f"- {path}")

    print("\nRouting decisions:")
    print(f"- docs_or_static_only: {str(route['docs_or_static_only']).lower()}")
    print(f"- fastpath_metadata: {str(route['fastpath_metadata']).lower()}")
    print(f"- run_docs_static_checks: {str(route['run_docs_static_checks']).lower()}")
    print(f"- run_fixture_ownership: {str(route['run_fixture_ownership']).lower()}")
    print(f"- run_research_sim: {str(route['run_research_sim']).lower()}")
    print(f"- run_platform: {str(route['run_platform']).lower()}")
    print(f"- run_nontrading: {str(route['run_nontrading']).lower()}")
    print(f"- run_root: {str(route['run_root']).lower()}")
    print(f"- run_polymarket: {str(route['run_polymarket']).lower()}")
    print(f"- run_hygiene: {str(route['run_hygiene']).lower()}")

    print("\nSuggested next commands:")
    for command in route["local_commands"]:
        print(f"- {command}")


def _print_gha(route: dict[str, object]) -> None:
    outputs = {
        "docs_or_static_only": route["docs_or_static_only"],
        "fastpath_metadata": route["fastpath_metadata"],
        "run_docs_static_checks": route["run_docs_static_checks"],
        "run_fixture_ownership": route["run_fixture_ownership"],
        "run_research_sim": route["run_research_sim"],
        "run_platform": route["run_platform"],
        "run_nontrading": route["run_nontrading"],
        "run_root": route["run_root"],
        "run_polymarket": route["run_polymarket"],
        "run_hygiene": route["run_hygiene"],
    }

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={str(bool(value)).lower()}\n")

    for key, value in outputs.items():
        print(f"{key}={str(bool(value)).lower()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Changed paths")
    parser.add_argument(
        "--from-git-status",
        action="store_true",
        help="Read changed paths from git status --porcelain (default if no paths provided)",
    )
    parser.add_argument("--base-sha", help="Diff base SHA for CI routing", default="")
    parser.add_argument("--head-sha", help="Diff head SHA for CI routing", default="")
    parser.add_argument(
        "--format",
        choices=("text", "json", "gha", "commands"),
        default="text",
        help="Output format",
    )
    args = parser.parse_args()

    paths = [path for path in args.paths if path]
    if args.base_sha and args.head_sha:
        paths = _git_diff_paths(args.base_sha, args.head_sha)
    elif args.from_git_status or not paths:
        paths = _git_changed_paths()

    route = route_paths(paths)

    if args.format == "commands":
        for command in route["local_commands"]:
            print(command)
        return 0
    if args.format == "json":
        print(json.dumps(route, sort_keys=True))
        return 0
    if args.format == "gha":
        _print_gha(route)
        return 0

    _print_text(route)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
