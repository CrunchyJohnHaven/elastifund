#!/usr/bin/env python3
"""Fail on tracked high-risk artifacts and high-confidence secret patterns."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.report_envelope import validate_report_envelope


@dataclass(frozen=True)
class SecretPattern:
    label: str
    regex: re.Pattern[str]


BLOCKED_PATH_RULES = (
    ("tracked .pem file", lambda rel: rel.name.endswith(".pem")),
    ("tracked .db file", lambda rel: rel.name.endswith(".db")),
    ("tracked .env file", lambda rel: rel.name == ".env"),
    ("tracked jj_state.json", lambda rel: rel.name == "jj_state.json"),
)

SECRET_PATTERNS = (
    SecretPattern(
        "private key header",
        re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP|PRIVATE) PRIVATE KEY-----"),
    ),
    SecretPattern("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    SecretPattern(
        "GitHub personal access token",
        re.compile(r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    SecretPattern(
        "Anthropic API key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ),
    SecretPattern(
        "generic API key",
        re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_-]{32,}\b"),
    ),
    SecretPattern("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{24,}\b")),
    SecretPattern(
        "Telegram bot token",
        re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    ),
)

CANONICAL_REFERENCE_FILES = (
    Path("AGENTS.md"),
    Path("README.md"),
    Path("CLAUDE.md"),
    Path("scripts/README.md"),
    Path("PROJECT_INSTRUCTIONS.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("docs/ops/LOCAL_TWIN_ENTRYPOINTS.md"),
    Path("docs/ops/llm_context_manifest.md"),
    Path("docs/strategy/flywheel_strategy.md"),
    Path("docs/ops/dispatch_instructions.md"),
    Path("docs/FORK_AND_RUN.md"),
    Path("docs/PARALLEL_AGENT_WORKFLOW.md"),
    Path("docs/REPO_MAP.md"),
    Path("docs/architecture/README.md"),
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")
BACKTICK_REFERENCE_SUFFIXES = (".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".sh")
GENERATED_REFERENCE_PATHS = ("jj_state.json",)
GENERATED_REFERENCE_PREFIXES = ("reports/",)
DEBRIS_SUFFIX_RE = re.compile(r".* \(\d+\)(?:\.[^/]+)?$")

CANONICAL_LATEST_REPORTS = (
    Path("reports/runtime_truth_latest.json"),
    Path("reports/public_runtime_snapshot.json"),
    Path("reports/trade_proof/latest.json"),
    Path("reports/canonical_operator_truth.json"),
    Path("reports/wallet_live_snapshot_latest.json"),
    Path("reports/evidence_bundle.json"),
    Path("reports/thesis_bundle.json"),
    Path("reports/promotion_bundle.json"),
    Path("reports/capital_lab/latest.json"),
    Path("reports/counterfactual_lab/latest.json"),
    Path("reports/learning_bundle.json"),
)

PLACEHOLDER_MARKERS = (
    "...",
    "example",
    "examples",
    "paste",
    "placeholder",
    "sample",
    "dummy",
    "your_",
    "your-",
    "xxx",
    "xxxx",
    "<",
    ">",
)

ABSOLUTE_FILESYSTEM_PREFIXES = ("/Users/", "/home/", "file://")
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(entry) for entry in result.stdout.decode("utf-8").split("\0") if entry]


def untracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-o", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(entry) for entry in result.stdout.decode("utf-8").split("\0") if entry]


def list_prunable_worktrees() -> list[str]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    prunable: list[str] = []
    current: str | None = None
    for raw_line in result.stdout.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("worktree "):
            current = line.split(" ", 1)[1].strip()
            continue
        if line.startswith("prunable") and current:
            prunable.append(current)
    return prunable


def canonical_report_issues() -> list[str]:
    issues: list[str] = []
    for rel_path in CANONICAL_LATEST_REPORTS:
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            issues.append(f"{rel_path}: canonical latest artifact is missing")
            continue
        try:
            payload = json.loads(abs_path.read_text())
        except Exception as exc:
            issues.append(f"{rel_path}: canonical latest artifact is unreadable: {exc}")
            continue
        issues.extend(f"{rel_path}: {issue}" for issue in validate_report_envelope(payload))
    return issues


def is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def is_text_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return b"\x00" not in data


def iter_text_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def iter_reference_targets(text: str) -> list[str]:
    targets: list[str] = []

    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).split("#", 1)[0].strip()
        if target:
            targets.append(target)

    for match in BACKTICK_PATH_RE.finditer(text):
        candidate = match.group(1).strip()
        if "/" in candidate or candidate.endswith(BACKTICK_REFERENCE_SUFFIXES):
            targets.append(candidate)

    return targets


def is_local_reference(target: str) -> bool:
    if not target or target.startswith("#"):
        return False
    if target.startswith(("http://", "https://", "mailto:", "tel:")):
        return False
    if target.startswith("/"):
        return False
    return True


def is_absolute_filesystem_reference(target: str) -> bool:
    if target.startswith(ABSOLUTE_FILESYSTEM_PREFIXES):
        return True
    return bool(WINDOWS_ABSOLUTE_PATH_RE.match(target))


def is_generated_reference(target: str) -> bool:
    if target in GENERATED_REFERENCE_PATHS:
        return True
    return target.startswith(GENERATED_REFERENCE_PREFIXES)


def is_duplicate_debris(path: Path | str) -> bool:
    return bool(DEBRIS_SUFFIX_RE.match(Path(path).name))


def reference_exists(source: Path, target: str) -> bool:
    candidate = (source.parent / target).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return False
    if candidate.exists():
        return True
    if target.startswith(("./", "../")):
        return False
    return (ROOT / target).exists()


def main() -> int:
    issues: list[str] = []
    files = tracked_files()
    all_files = {*(files), *(untracked_files())}

    for rel_path in files:
        for label, rule in BLOCKED_PATH_RULES:
            if rule(rel_path):
                issues.append(f"{rel_path}: blocked {label}")

    for rel_path in sorted(all_files, key=str):
        if is_duplicate_debris(rel_path):
            issues.append(f"{rel_path}: duplicate debris file")

    for rel_path in files:
        abs_path = ROOT / rel_path
        if not abs_path.is_file() or not is_text_file(abs_path):
            continue

        for line_number, line in enumerate(iter_text_lines(abs_path), start=1):
            for pattern in SECRET_PATTERNS:
                for match in pattern.regex.finditer(line):
                    value = match.group(0)
                    if is_placeholder(value):
                        continue
                    issues.append(
                        f"{rel_path}:{line_number}: possible {pattern.label}: {value[:12]}..."
                    )

    issues.extend(canonical_report_issues())

    for worktree in list_prunable_worktrees():
        issues.append(f"stale worktree reference: {worktree}")

    seen_reference_issues: set[tuple[Path, str]] = set()
    for rel_path in CANONICAL_REFERENCE_FILES:
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            issues.append(f"{rel_path}: canonical reference file is missing")
            continue

        text = abs_path.read_text(encoding="utf-8", errors="ignore")
        for target in iter_reference_targets(text):
            if is_absolute_filesystem_reference(target):
                issues.append(f"{rel_path}: absolute filesystem reference is not portable: {target}")
                continue
            if not is_local_reference(target):
                continue
            if is_generated_reference(target):
                continue
            key = (rel_path, target)
            if key in seen_reference_issues:
                continue
            seen_reference_issues.add(key)
            if not reference_exists(abs_path, target):
                issues.append(f"{rel_path}: missing referenced path: {target}")

    if issues:
        print("Repo hygiene check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Repo hygiene check passed: no tracked sensitive artifacts detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
