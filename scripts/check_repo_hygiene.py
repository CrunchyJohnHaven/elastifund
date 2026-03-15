#!/usr/bin/env python3
"""Fail on tracked high-risk artifacts and high-confidence secret patterns."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]


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
    Path("PROJECT_INSTRUCTIONS.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("docs/ops/llm_context_manifest.md"),
    Path("docs/strategy/flywheel_strategy.md"),
    Path("docs/ops/dispatch_instructions.md"),
    Path("docs/FORK_AND_RUN.md"),
    Path("docs/PARALLEL_AGENT_WORKFLOW.md"),
    Path("docs/REPO_MAP.md"),
)

ROOT_NUMBERED_DOC_STUBS = (
    Path("00_MISSION_AND_PRINCIPLES.md"),
    Path("01_EXECUTIVE_SUMMARY.md"),
    Path("02_ARCHITECTURE.md"),
    Path("03_METRICS_AND_LEADERBOARDS.md"),
    Path("04_TRADING_WORKERS.md"),
    Path("05_NON_TRADING_WORKERS.md"),
    Path("06_EXPERIMENT_DIARY.md"),
    Path("07_FORECASTS_AND_CHECKPOINTS.md"),
    Path("08_PROMPT_LIBRARY.md"),
    Path("09_GOVERNANCE_AND_SAFETY.md"),
    Path("10_OPERATIONS_RUNBOOK.md"),
    Path("11_PUBLIC_MESSAGING.md"),
    Path("12_MANAGED_SERVICE_BOUNDARY.md"),
)

ROOT_STUB_PREFIX = "docs/numbered/"
ROOT_STUB_MAX_NONEMPTY_LINES = 12
ROOT_STUB_MAX_CHAR_COUNT = 900
DOCS_STRATEGY_PATH = Path("docs/strategy")
DOCS_STRATEGY_CANONICAL_NAME_RE = re.compile(r"^[a-z0-9_]+\.md$")
# Legacy compatibility filenames kept intentionally as thin pointers.
DOCS_STRATEGY_FILENAME_ALLOWLIST = {
    "README.md",
    "STRATEGY_REPORT.md",
    "LLM_ENSEMBLE_SPEC.md",
    "SMART_WALLET_SPEC.md",
    "Market_Selection_Map.md",
    "POLYMARKET_BOT_BUILD_PLAN.md",
    "SystemDesignResearch_v1.0.0.md",
    "llm-probability-calibration-system.md",
    "monte_carlo_simulation_design.md",
    "polymarket-llm-bot-research.md",
    "polymarket_backtesting_framework.md",
    "prediction-market-fund-research.md",
    "resolution-rule-edge-playbook.md",
}

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")
BACKTICK_REFERENCE_SUFFIXES = (".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".sh")
GENERATED_REFERENCE_PATHS = ("jj_state.json",)
GENERATED_REFERENCE_PREFIXES = ("reports/",)
ARCHIVE_CANONICAL_PREFIXES = (
    "archive/",
    "docs/ops/_archive/",
    "research/archive/",
    "research/history/",
)
ROOT_COMPATIBILITY_SYMLINKS = {
    Path("arr_estimate.svg"): Path("reports/arr_estimate.svg"),
    Path("improvement_velocity.json"): Path("reports/improvement_velocity.json"),
    Path("improvement_velocity.svg"): Path("reports/improvement_velocity.svg"),
    Path("jjn_public_report.json"): Path("reports/nontrading_public_report.json"),
}
TOP_LEVEL_PACKAGE_MAP_REQUIREMENTS = {
    "agent": "agent/README.md",
    "archive": "archive/README.md",
    "codex_instances": "codex_instances/README.md",
    "config": "config/README.md",
    "data": "data/README.md",
    "docs": "docs/README.md",
    "edge-backlog": "edge-backlog/README.md",
    "kalshi": "kalshi/README.md",
    "logs": "logs/README.md",
    "nontrading": "nontrading/PACKAGE_MAP.md",
    "shared": "shared/README.md",
}
GENERATED_INDEX_CHECKS = (
    ("scripts/README.md", ["python3", "scripts/render_scripts_index.py", "--check"]),
    (
        "scripts/DEPRECATION_CANDIDATES.md",
        ["python3", "scripts/render_deprecation_candidates.py", "--check"],
    ),
)
CANONICAL_PATH_MARKERS = (
    re.compile(r"^\|\s*Canonical file\s*\|\s*`([^`]+)`", re.IGNORECASE),
    re.compile(r"^\*\*Canonical Filename:\*\*\s*`([^`]+)`", re.IGNORECASE),
    re.compile(r"^\s*Canonical source:\s*\[([^\]]+)\]\([^)]+\)\s*$", re.IGNORECASE),
)
POINTER_PREFIX = "# Pointer:"
PROMPT_CONTEXT_LABEL_RULES: dict[Path, tuple[str, ...]] = {
    Path("CLAUDE.md"): ("Status: canonical", "Purpose: behavior"),
    Path("CODEX_DISPATCH.md"): ("Status: historical (non-canonical)",),
    Path("CODEX_MASTER_PLAN.md"): ("Status: historical (non-canonical)",),
    Path("docs/ops/dispatch_instructions.md"): ("Status: historical (non-canonical)",),
    Path("docs/ops/llm_context_manifest.md"): ("Status: canonical index",),
}

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
REPORTS_DIR = ROOT / "reports"
REPORTS_RETENTION_POLICY = REPORTS_DIR / "retention_policy.json"
REPORTS_LEGACY_ALIASES_INDEX = REPORTS_DIR / "legacy_aliases_latest.json"
REPORTS_TOP_LEVEL_TIMESTAMPED_RE = re.compile(r".*_\d{8}T\d{6}Z\.(?:json|md|csv|txt|png)$")


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(entry) for entry in result.stdout.decode("utf-8").split("\0") if entry]


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


def is_archive_canonical_path(path: str) -> bool:
    normalized = path.strip().lstrip("./")
    return any(normalized.startswith(prefix) for prefix in ARCHIVE_CANONICAL_PREFIXES)


def reports_top_level_symlink_contract_issues() -> list[str]:
    issues: list[str] = []
    if not REPORTS_DIR.exists():
        return issues
    if not REPORTS_RETENTION_POLICY.exists():
        return ["reports/retention_policy.json: missing reports retention policy"]
    try:
        policy = json.loads(REPORTS_RETENTION_POLICY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["reports/retention_policy.json: invalid JSON"]

    raw = policy.get("top_level_symlink_allowlist", [])
    allowlist = {str(item).strip() for item in raw if str(item).strip()}
    top_level_symlinks = {
        path.name
        for path in REPORTS_DIR.iterdir()
        if path.is_symlink()
    }
    non_allowlisted = sorted(top_level_symlinks - allowlist)
    if non_allowlisted:
        issues.append(
            "reports/: non-allowlisted top-level symlinks present: "
            + ", ".join(non_allowlisted[:20])
            + (" ..." if len(non_allowlisted) > 20 else "")
        )
    if not REPORTS_LEGACY_ALIASES_INDEX.exists():
        issues.append("reports/legacy_aliases_latest.json: missing alias index for retired top-level symlinks")
    return issues


def reports_top_level_timestamp_contract_issues() -> list[str]:
    issues: list[str] = []
    if not REPORTS_DIR.exists():
        return issues
    if not REPORTS_RETENTION_POLICY.exists():
        return ["reports/retention_policy.json: missing reports retention policy"]
    try:
        policy = json.loads(REPORTS_RETENTION_POLICY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["reports/retention_policy.json: invalid JSON"]

    raw_allowlist = policy.get("top_level_timestamped_file_allowlist")
    if not isinstance(raw_allowlist, list):
        raw_allowlist = policy.get("top_level_timestamped_allowlist", [])
    allowlist = {str(item).strip() for item in raw_allowlist if str(item).strip()}
    top_level_timestamped = sorted(
        path.name
        for path in REPORTS_DIR.iterdir()
        if path.is_file() and not path.is_symlink() and REPORTS_TOP_LEVEL_TIMESTAMPED_RE.fullmatch(path.name)
    )
    non_allowlisted = [name for name in top_level_timestamped if name not in allowlist]
    if non_allowlisted:
        issues.append(
            "reports/: non-allowlisted top-level timestamped files present: "
            + ", ".join(non_allowlisted[:20])
            + (" ..." if len(non_allowlisted) > 20 else "")
        )
    return issues


def _extract_canonical_targets_from_line(line: str) -> list[str]:
    targets: list[str] = []
    stripped = line.strip()
    for pattern in CANONICAL_PATH_MARKERS:
        match = pattern.match(stripped)
        if not match:
            continue
        candidate = match.group(1).strip()
        if candidate:
            targets.append(candidate)
    return targets


def find_canonical_targets(text: str) -> list[str]:
    targets: list[str] = []
    capture = False
    for line in text.splitlines():
        stripped = line.strip()
        targets.extend(_extract_canonical_targets_from_line(stripped))
        lowered = stripped.lower()
        if lowered.startswith("canonical file:"):
            capture = True
            continue
        if not capture:
            continue
        if stripped.startswith("-"):
            code_match = re.search(r"`([^`]+)`", stripped)
            if code_match:
                targets.append(code_match.group(1).strip())
            continue
        if stripped:
            capture = False
    return targets


def is_pointer_stub(path: Path) -> bool:
    if path in ROOT_NUMBERED_DOC_STUBS:
        return True
    if path.suffix != ".md" or not path.exists():
        return False
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return bool(lines and lines[0].strip().startswith(POINTER_PREFIX))


def iter_markdown_files(files: Iterable[Path]) -> list[Path]:
    return sorted(path for path in files if path.suffix.lower() == ".md")


def canonical_reference_target(rel_path: str) -> Path:
    stem = rel_path.replace(".md", "")
    return Path(f"{ROOT_STUB_PREFIX}{stem}.md")


def root_stub_pointer_only_issues(rel_path: Path, text: str) -> list[str]:
    issues: list[str] = []
    stripped_lines = [line.strip() for line in text.splitlines() if line.strip()]

    if len(stripped_lines) > ROOT_STUB_MAX_NONEMPTY_LINES:
        issues.append(
            f"{rel_path}: compatibility shim has too many non-empty lines "
            f"({len(stripped_lines)} > {ROOT_STUB_MAX_NONEMPTY_LINES})"
        )

    if len(text) > ROOT_STUB_MAX_CHAR_COUNT:
        issues.append(
            f"{rel_path}: compatibility shim is too large "
            f"({len(text)} chars > {ROOT_STUB_MAX_CHAR_COUNT})"
        )

    for marker in ("## ", "### ", "#### "):
        if marker in text:
            issues.append(f"{rel_path}: compatibility shim must not include section headers ({marker.strip()})")
            break

    return issues


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

    for top_level, expected_map in TOP_LEVEL_PACKAGE_MAP_REQUIREMENTS.items():
        top_level_path = ROOT / top_level
        if not top_level_path.exists() or not top_level_path.is_dir():
            issues.append(f"{top_level}: missing required top-level directory for package-map coverage")
            continue
        expected_path = ROOT / expected_map
        if not expected_path.exists():
            issues.append(f"{expected_map}: missing required package-map coverage doc for {top_level}/")

    for rel_output, command in GENERATED_INDEX_CHECKS:
        output_path = ROOT / rel_output
        if not output_path.exists():
            issues.append(f"{rel_output}: missing generated index/manifest output")
            continue
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = (result.stdout + "\n" + result.stderr).strip()
            trimmed = " ".join(detail.splitlines())[:220]
            issues.append(f"{rel_output}: stale generated index/manifest ({' '.join(command)}): {trimmed}")

    for rel_symlink, rel_target in ROOT_COMPATIBILITY_SYMLINKS.items():
        symlink_path = ROOT / rel_symlink
        target_path = ROOT / rel_target
        if not symlink_path.exists():
            issues.append(f"{rel_symlink}: missing required root compatibility symlink")
            continue
        if not symlink_path.is_symlink():
            issues.append(f"{rel_symlink}: expected symlink for root compatibility shim")
            continue
        resolved = symlink_path.resolve()
        if not target_path.exists():
            issues.append(f"{rel_target}: missing canonical symlink target for {rel_symlink}")
            continue
        if resolved != target_path.resolve():
            issues.append(
                f"{rel_symlink}: symlink target mismatch (expected {rel_target}, got {symlink_path.readlink()})"
            )
    issues.extend(reports_top_level_symlink_contract_issues())
    issues.extend(reports_top_level_timestamp_contract_issues())

    for rel_path in files:
        if rel_path.parts[:2] == DOCS_STRATEGY_PATH.parts and rel_path.suffix == ".md":
            name = rel_path.name
            if (
                name not in DOCS_STRATEGY_FILENAME_ALLOWLIST
                and not DOCS_STRATEGY_CANONICAL_NAME_RE.fullmatch(name)
            ):
                issues.append(
                    f"{rel_path}: non-canonical docs/strategy filename (use lowercase snake_case or allowlist)"
                )

    for rel_path in files:
        for label, rule in BLOCKED_PATH_RULES:
            if rule(rel_path):
                issues.append(f"{rel_path}: blocked {label}")

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

    for rel_path in ROOT_NUMBERED_DOC_STUBS:
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            issues.append(f"{rel_path}: canonical stub is missing")
            continue

        expected_target = canonical_reference_target(rel_path.as_posix())
        expected_line = f"Canonical source: [{expected_target.as_posix()}]({expected_target.as_posix()})"
        text = abs_path.read_text(encoding="utf-8", errors="ignore")

        if "Compatibility shim." not in text:
            issues.append(f"{rel_path}: shim marker is missing")
        if expected_line not in text:
            issues.append(f"{rel_path}: expected canonical redirect missing: {expected_line}")
        issues.extend(root_stub_pointer_only_issues(rel_path, text))
        if not expected_target.exists():
            issues.append(f"{rel_path}: canonical redirect target is missing ({expected_target})")

    for rel_path, required_markers in PROMPT_CONTEXT_LABEL_RULES.items():
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            issues.append(f"{rel_path}: required prompt/context surface is missing")
            continue
        text = abs_path.read_text(encoding="utf-8", errors="ignore")
        for marker in required_markers:
            if marker not in text:
                issues.append(f"{rel_path}: required marker is missing: {marker}")

    for rel_path in iter_markdown_files(files):
        abs_path = ROOT / rel_path
        if not abs_path.exists() or not abs_path.is_file():
            continue
        text = abs_path.read_text(encoding="utf-8", errors="ignore")
        for target in find_canonical_targets(text):
            normalized = target.strip().lstrip("./")
            if is_archive_canonical_path(normalized):
                issues.append(f"{rel_path}: canonical target must not point to archived history path: {target}")
                continue
            if target.startswith(("/", "http://", "https://")):
                continue
            target_path = ROOT / normalized
            if not target_path.exists():
                issues.append(f"{rel_path}: canonical target does not exist: {target}")
                continue
            try:
                rel_target = target_path.relative_to(ROOT)
            except ValueError:
                issues.append(f"{rel_path}: canonical target is outside repo: {target}")
                continue
            if is_pointer_stub(rel_target):
                issues.append(f"{rel_path}: canonical target resolves to pointer/shim file: {target}")

    if issues:
        print("Repo hygiene check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Repo hygiene check passed: no tracked sensitive artifacts detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
