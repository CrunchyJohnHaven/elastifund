#!/usr/bin/env python3
"""Deploy an allowlisted release bundle to the Dublin VPS."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "reports" / "parallel" / "release_manifest.json"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_REMOTE_DIR = "/home/ubuntu/polymarket-trading-bot"
DEFAULT_REMOTE_HOST = (
    f"{os.environ.get('VPS_USER', 'ubuntu')}@{os.environ['VPS_IP']}"
    if os.environ.get("VPS_IP")
    else "ubuntu@52.208.155.0"
)
SERVICE_NAME = "jj-live.service"
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DOCUMENTED_ENV_KEY_RE = re.compile(r"^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)
ROOT_DEPLOYABLE_FILES = {
    ".env.example",
    "Makefile",
    "docker-compose.yml",
    "requirements.txt",
    "requirements-elastic.txt",
}
DEPLOYABLE_PREFIXES = (
    "bot/",
    "config/",
    "data_layer/",
    "deploy/",
    "execution/",
    "hub/",
    "infra/",
    "orchestration/",
    "polymarket-bot/",
    "scripts/",
    "signals/",
    "strategies/",
)
NON_DEPLOYABLE_PREFIXES = (
    "archive/",
    "docs/",
    "nontrading/",
    "reports/",
    "research/",
    "state/",
    "tests/",
)
NON_DEPLOYABLE_EXACT_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX_PLANNING_PROMPT.md",
    "COMMAND_NODE.md",
    "FAST_TRADE_EDGE_ANALYSIS.md",
    "PROJECT_INSTRUCTIONS.md",
    "README.md",
    "index.html",
}
PYTHON_ENV_ACCESS_RE = re.compile(
    r"""(?:os\.getenv|os\.environ\.get|environ\.get)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
)
PYTHON_ENV_INDEX_RE = re.compile(
    r"""(?:os\.environ|environ)\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]"""
)
COMMON_RUNTIME_ENV_KEYS = {
    "ELASTIFUND_BRIDGE_KEY",
    "HOME",
    "LIGHTSAIL_KEY",
    "PATH",
    "PWD",
    "PYTHONPATH",
    "SHELL",
    "SHLVL",
    "TERM",
    "TMPDIR",
    "USER",
    "VPS_IP",
    "VPS_USER",
}


class DeployError(RuntimeError):
    """Raised when the deploy cannot proceed safely."""


@dataclass(frozen=True)
class ReleasePlan:
    repo_sha: str | None
    ci_status: str | None
    restart_recommended: bool
    deploy_files: tuple[str, ...]
    checksums: dict[str, str]


def _run_git_command(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return _run_command(["git", *args], check=False,)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def is_deployable_changed_file(path: str) -> bool:
    if not path or path in NON_DEPLOYABLE_EXACT_FILES:
        return False
    if any(path.startswith(prefix) for prefix in NON_DEPLOYABLE_PREFIXES):
        return False
    if path in ROOT_DEPLOYABLE_FILES:
        return True
    return any(path.startswith(prefix) for prefix in DEPLOYABLE_PREFIXES)


def select_deployable_changed_files(changed_files: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                path
                for path in changed_files
                if is_deployable_changed_file(path)
            }
        )
    )


def list_cycle_changed_files(repo_root: Path) -> tuple[str, ...]:
    tracked = _run_git_command(
        repo_root,
        ["-C", str(repo_root), "diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
    )
    if tracked.returncode != 0:
        raise DeployError(tracked.stderr.strip() or "failed to list tracked changes")
    untracked = _run_git_command(
        repo_root,
        ["-C", str(repo_root), "ls-files", "--others", "--exclude-standard"],
    )
    if untracked.returncode != 0:
        raise DeployError(untracked.stderr.strip() or "failed to list untracked files")
    changed = {
        line.strip()
        for line in (tracked.stdout.splitlines() + untracked.stdout.splitlines())
        if line.strip()
    }
    return tuple(sorted(changed))


def _get_git_head_sha(repo_root: Path) -> str | None:
    result = _run_git_command(repo_root, ["-C", str(repo_root), "rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def compute_checksums(repo_root: Path, paths: Sequence[str]) -> dict[str, str]:
    return {relative: _sha256_for_file(repo_root / relative) for relative in paths}


def _compute_manifest_fingerprint(checksums: dict[str, str]) -> str:
    payload = json.dumps(checksums, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_show_text(repo_root: Path, revision: str, relative_path: str) -> str | None:
    result = _run_git_command(
        repo_root,
        ["-C", str(repo_root), "show", f"{revision}:{relative_path}"],
    )
    if result.returncode != 0:
        return None
    return result.stdout


def build_env_key_diff(current_text: str, previous_text: str | None = None) -> dict[str, Any]:
    current_keys = sorted(set(parse_documented_env_keys_from_text(current_text)))
    previous_keys = sorted(set(parse_documented_env_keys_from_text(previous_text or "")))
    previous_key_set = set(previous_keys)
    current_key_set = set(current_keys)
    return {
        "template_key_count": len(current_keys),
        "added_in_cycle": sorted(current_key_set - previous_key_set),
        "removed_in_cycle": sorted(previous_key_set - current_key_set),
    }


def _extract_python_env_references_from_text(text: str) -> set[str]:
    references = set(PYTHON_ENV_INDEX_RE.findall(text))
    references.update(PYTHON_ENV_ACCESS_RE.findall(text))
    return {
        key
        for key in references
        if key and key not in COMMON_RUNTIME_ENV_KEYS
    }


def validate_env_key_alignment(repo_root: Path, deploy_files: Sequence[str]) -> dict[str, Any]:
    template_keys = set(read_documented_env_keys(repo_root / ".env.example"))
    referenced_keys: set[str] = set()
    for relative in deploy_files:
        path = repo_root / relative
        if path.suffix != ".py":
            continue
        try:
            current_text = path.read_text()
        except UnicodeDecodeError:
            continue
        previous_lines = set((_git_show_text(repo_root, "HEAD", relative) or "").splitlines())
        added_lines = [line for line in current_text.splitlines() if line not in previous_lines]
        referenced_keys.update(_extract_python_env_references_from_text("\n".join(added_lines)))
    missing_from_template = sorted(referenced_keys - template_keys)
    return {
        "template_path": ".env.example",
        "template_key_count": len(template_keys),
        "referenced_keys": sorted(referenced_keys),
        "missing_from_template": missing_from_template,
        "valid": not missing_from_template,
    }


def _derive_ci_status(repo_root: Path) -> tuple[str | None, dict[str, Any]]:
    root_status = read_json(repo_root / "reports" / "root_test_status.json")
    status = str(root_status.get("status") or "").strip().lower()
    summary = str(root_status.get("summary") or "").strip() or None
    if status == "passing":
        return "green", {
            "source": "reports/root_test_status.json",
            "status": status,
            "summary": summary,
            "checked_at": root_status.get("checked_at"),
        }
    if status:
        return status, {
            "source": "reports/root_test_status.json",
            "status": status,
            "summary": summary,
            "checked_at": root_status.get("checked_at"),
        }
    return None, {
        "source": "reports/root_test_status.json",
        "status": "unknown",
        "summary": summary,
        "checked_at": root_status.get("checked_at"),
    }


def _derive_restart_recommendation(repo_root: Path) -> tuple[bool, str]:
    edge_scans = sorted((repo_root / "reports").glob("edge_scan_*.json"))
    for latest_edge_scan in reversed(edge_scans):
        payload = read_json(latest_edge_scan)
        if "restart_recommended" in payload:
            return bool(payload.get("restart_recommended")), str(latest_edge_scan.relative_to(repo_root))

    remote_cycle_status = read_json(repo_root / "reports" / "remote_cycle_status.json")
    launch = remote_cycle_status.get("launch") if isinstance(remote_cycle_status, dict) else {}
    return bool((launch or {}).get("fast_flow_restart_ready")), "reports/remote_cycle_status.json"


def build_release_manifest(repo_root: Path) -> dict[str, Any]:
    changed_files = list_cycle_changed_files(repo_root)
    deploy_files = select_deployable_changed_files(changed_files)
    if not deploy_files:
        raise DeployError("no deployable changed files found in the current cycle")

    checksums = compute_checksums(repo_root, deploy_files)
    repo_sha = _get_git_head_sha(repo_root)
    ci_status, ci_evidence = _derive_ci_status(repo_root)
    restart_recommended, restart_source = _derive_restart_recommendation(repo_root)
    current_env_text = (repo_root / ".env.example").read_text() if (repo_root / ".env.example").exists() else ""
    previous_env_text = _git_show_text(repo_root, "HEAD", ".env.example")
    env_key_diff = build_env_key_diff(current_env_text, previous_env_text)
    env_alignment = validate_env_key_alignment(repo_root, deploy_files)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_sha": repo_sha,
        "repo_sha_short": repo_sha[:7] if repo_sha else None,
        "repo_dirty": True,
        "ci_status": ci_status,
        "ci_evidence": ci_evidence,
        "restart_recommended": restart_recommended,
        "restart_source": restart_source,
        "changed_files_scanned": list(changed_files),
        "excluded_changed_files": [path for path in changed_files if path not in set(deploy_files)],
        "deploy_files": list(deploy_files),
        "checksums": checksums,
        "content_fingerprint": _compute_manifest_fingerprint(checksums),
        "env_key_diff": env_key_diff,
        "env_key_alignment": env_alignment,
    }


def write_release_manifest(repo_root: Path, manifest_path: Path | None = None) -> Path:
    target = _resolve_manifest_path(manifest_path)
    _write_json(target, build_release_manifest(repo_root))
    return target


def parse_env_keys_from_text(text: str) -> list[str]:
    """Return assigned env keys from an env-style file."""

    keys: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if ENV_KEY_RE.match(key):
            keys.append(key)
    return keys


def parse_documented_env_keys_from_text(text: str) -> list[str]:
    """Return env keys documented as assignments or commented examples."""

    return [match.group(1) for match in DOCUMENTED_ENV_KEY_RE.finditer(text)]


def read_env_keys(path: Path) -> list[str]:
    """Return env keys from a local file path."""

    if not path.exists():
        return []
    return parse_env_keys_from_text(path.read_text())


def read_documented_env_keys(path: Path) -> list[str]:
    if not path.exists():
        return []
    return parse_documented_env_keys_from_text(path.read_text())


def normalize_service_state(raw_state: str) -> dict[str, str]:
    """Normalize systemctl output into a stable service snapshot."""

    state = (raw_state or "").strip().splitlines()
    systemctl_state = state[-1].strip() if state else "unknown"
    if systemctl_state == "active":
        status = "running"
    elif systemctl_state in {"inactive", "failed", "deactivating"}:
        status = "stopped"
    else:
        status = "unknown"
    return {
        "status": status,
        "systemctl_state": systemctl_state or "unknown",
        "detail": systemctl_state or "unknown",
    }


def compare_env_keys(template_keys: Sequence[str], remote_keys: Sequence[str]) -> list[str]:
    """Return template keys missing from the remote env file."""

    remote_key_set = set(remote_keys)
    return sorted(key for key in template_keys if key not in remote_key_set)


def _resolve_manifest_path(path: Path | None) -> Path:
    return path if path is not None else DEFAULT_MANIFEST_PATH


def _validate_manifest_entry(entry: str) -> PurePosixPath:
    candidate = PurePosixPath(entry)
    if not entry or candidate.is_absolute() or ".." in candidate.parts:
        raise DeployError(f"invalid deploy path in manifest: {entry!r}")
    return candidate


def _collect_manifest_files(repo_root: Path, entries: Sequence[str]) -> tuple[str, ...]:
    resolved_root = repo_root.resolve()
    files: list[str] = []
    seen: set[str] = set()

    for entry in entries:
        pure_path = _validate_manifest_entry(entry)
        local_path = (repo_root / pure_path.as_posix()).resolve()
        try:
            local_path.relative_to(resolved_root)
        except ValueError as exc:
            raise DeployError(f"deploy path escapes repo root: {entry}") from exc
        if not local_path.exists():
            raise DeployError(f"deploy path missing from repo: {entry}")

        if local_path.is_dir():
            children = sorted(path for path in local_path.rglob("*") if path.is_file())
        elif local_path.is_file():
            children = [local_path]
        else:
            raise DeployError(f"deploy path is not a regular file or directory: {entry}")

        for child in children:
            resolved_child = child.resolve()
            try:
                resolved_child.relative_to(resolved_root)
            except ValueError as exc:
                raise DeployError(f"deploy file escapes repo root: {child}") from exc
            relative = resolved_child.relative_to(resolved_root).as_posix()
            if relative not in seen:
                seen.add(relative)
                files.append(relative)

    return tuple(sorted(files))


def _sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_release_plan(repo_root: Path, manifest_path: Path | None = None) -> ReleasePlan:
    """Load the release manifest and expand the deploy allowlist."""

    manifest_file = _resolve_manifest_path(manifest_path)
    payload = json.loads(manifest_file.read_text())
    raw_deploy_files = payload.get("deploy_files") or payload.get("changed_files") or []
    if not isinstance(raw_deploy_files, list) or not raw_deploy_files:
        raise DeployError("release manifest is missing a non-empty deploy_files list")

    deploy_files = _collect_manifest_files(repo_root, [str(item) for item in raw_deploy_files])
    checksums = compute_checksums(repo_root, deploy_files)
    expected_checksums = payload.get("checksums")
    if expected_checksums is not None:
        if not isinstance(expected_checksums, dict):
            raise DeployError("release manifest checksums must be an object when present")
        missing_checksum_entries = sorted(set(deploy_files) - set(expected_checksums))
        mismatched_checksums = sorted(
            relative
            for relative in deploy_files
            if str(expected_checksums.get(relative) or "") != checksums[relative]
        )
        if missing_checksum_entries or mismatched_checksums:
            details = []
            if missing_checksum_entries:
                details.append(f"missing checksum entries: {', '.join(missing_checksum_entries)}")
            if mismatched_checksums:
                details.append(f"stale checksum entries: {', '.join(mismatched_checksums)}")
            raise DeployError("release manifest checksum validation failed; " + "; ".join(details))
    return ReleasePlan(
        repo_sha=str(payload.get("repo_sha") or "") or None,
        ci_status=str(payload.get("ci_status") or "") or None,
        restart_recommended=bool(payload.get("restart_recommended")),
        deploy_files=deploy_files,
        checksums=checksums,
    )


def create_release_bundle(repo_root: Path, plan: ReleasePlan, bundle_path: Path) -> Path:
    """Archive the allowlisted release files into a tar.gz bundle."""

    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, "w:gz") as archive:
        for relative in plan.deploy_files:
            archive.add(repo_root / relative, arcname=relative, recursive=False)
    return bundle_path


def build_remote_paper_commands(remote_dir: str) -> tuple[str, str]:
    """Return the paper-mode status and single-cycle commands."""

    pythonpath = f"{remote_dir}:{remote_dir}/bot:{remote_dir}/polymarket-bot"
    status_command = (
        f"env PAPER_TRADING=true PYTHONPATH={shlex.quote(pythonpath)} "
        "python3 bot/jj_live.py --status"
    )
    single_cycle_command = (
        f"env PAPER_TRADING=true PYTHONPATH={shlex.quote(pythonpath)} "
        "timeout 300 python3 bot/jj_live.py"
    )
    return status_command, single_cycle_command


def _ssh_base_args(host: str, key_path: Path) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key_path),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=15",
        host,
    ]


def _scp_base_args(key_path: Path) -> list[str]:
    return [
        "scp",
        "-i",
        str(key_path),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=15",
    ]


def _run_command(
    args: Sequence[str],
    *,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def run_remote_command(
    host: str,
    key_path: Path,
    command: str,
    *,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    args = _ssh_base_args(host, key_path) + [command]
    return _run_command(args, input_text=input_text, check=check)


def upload_bundle(host: str, key_path: Path, local_bundle: Path, remote_bundle: str) -> None:
    _run_command(
        _scp_base_args(key_path) + [str(local_bundle), f"{host}:{remote_bundle}"],
        check=True,
    )


def discover_ssh_key(repo_root: Path) -> Path | None:
    """Find the VPS SSH key using the same search order as bridge.sh."""

    candidates = [
        os.environ.get("ELASTIFUND_BRIDGE_KEY"),
        os.environ.get("LIGHTSAIL_KEY"),
        str(repo_root / "LightsailDefaultKey-eu-west-1.pem"),
        str(Path.home() / "Downloads" / "LightsailDefaultKey-eu-west-1.pem"),
        str(Path.home() / ".ssh" / "lightsail.pem"),
        str(Path.home() / ".ssh" / "LightsailDefaultKey-eu-west-1.pem"),
        str(Path.home() / "Desktop" / "LightsailDefaultKey-eu-west-1.pem"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        expanded = Path(candidate).expanduser()
        if expanded.exists():
            return expanded
    return None


def get_remote_service_snapshot(host: str, key_path: Path) -> dict[str, Any]:
    """Capture the current service state from the remote host."""

    result = run_remote_command(
        host,
        key_path,
        f"systemctl is-active {SERVICE_NAME} 2>/dev/null || true",
    )
    snapshot = normalize_service_state(result.stdout or result.stderr)
    snapshot.update(
        {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "host": host,
            "service_name": SERVICE_NAME,
        }
    )
    return snapshot


def get_remote_env_keys(host: str, key_path: Path, remote_dir: str) -> dict[str, Any]:
    """Read remote .env keys without exposing secret values."""

    script = f"""
import json
import re
from pathlib import Path

root = Path({remote_dir!r})
path = root / ".env"
keys = []
if path.exists():
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            keys.append(key)
print(json.dumps({{"exists": path.exists(), "keys": sorted(keys)}}, sort_keys=True))
"""
    command = (
        f"cd {shlex.quote(remote_dir)} && "
        "python3 - <<'PY'\n"
        f"{script}"
        "PY"
    )
    result = run_remote_command(host, key_path, command, check=True)
    return json.loads(result.stdout)


def extract_remote_bundle(
    host: str,
    key_path: Path,
    remote_dir: str,
    remote_bundle: str,
) -> subprocess.CompletedProcess[str]:
    command = (
        f"mkdir -p {shlex.quote(remote_dir)} && "
        f"tar -xzf {shlex.quote(remote_bundle)} -C {shlex.quote(remote_dir)} && "
        f"rm -f {shlex.quote(remote_bundle)}"
    )
    return run_remote_command(host, key_path, command, check=True)


def verify_remote_checksums(
    host: str,
    key_path: Path,
    remote_dir: str,
    checksums: dict[str, str],
) -> dict[str, Any]:
    """Verify that remote files match the deployed local checksums."""

    encoded = base64.b64encode(json.dumps(checksums, sort_keys=True).encode("utf-8")).decode("ascii")
    script = f"""
import base64
import hashlib
import json
from pathlib import Path

base = Path({remote_dir!r})
checksums = json.loads(base64.b64decode({encoded!r}).decode("utf-8"))
result = {{"ok": True, "matched": [], "missing": [], "mismatched": []}}
for relative, expected in sorted(checksums.items()):
    path = base / relative
    if not path.exists():
        result["ok"] = False
        result["missing"].append(relative)
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        result["ok"] = False
        result["mismatched"].append({{"path": relative, "expected": expected, "actual": digest}})
    else:
        result["matched"].append(relative)
print(json.dumps(result, sort_keys=True))
"""
    command = (
        f"cd {shlex.quote(remote_dir)} && "
        "python3 - <<'PY'\n"
        f"{script}"
        "PY"
    )
    result = run_remote_command(host, key_path, command, check=True)
    return json.loads(result.stdout)


def restart_remote_service(host: str, key_path: Path) -> subprocess.CompletedProcess[str]:
    """Restart jj-live on the remote host."""

    command = (
        f"sudo systemctl restart {SERVICE_NAME} && "
        "sleep 3 && "
        f"systemctl is-active {SERVICE_NAME}"
    )
    return run_remote_command(host, key_path, command, check=False)


def run_remote_paper_validation(
    host: str,
    key_path: Path,
    remote_dir: str,
) -> dict[str, Any]:
    """Run paper-mode validation on the remote host while the service stays stopped."""

    status_cmd, cycle_cmd = build_remote_paper_commands(remote_dir)
    status_command = f"cd {shlex.quote(remote_dir)} && {status_cmd}"
    status_result = run_remote_command(host, key_path, status_command, check=False)
    validation: dict[str, Any] = {
        "status_command": {
            "command": status_cmd,
            "returncode": status_result.returncode,
            "stdout_tail": (status_result.stdout or "").splitlines()[-20:],
            "stderr_tail": (status_result.stderr or "").splitlines()[-20:],
        },
        "single_cycle": {
            "command": cycle_cmd,
            "skipped": True,
            "reason": "status command failed",
            "returncode": None,
            "stdout_tail": [],
            "stderr_tail": [],
        },
    }
    if status_result.returncode != 0:
        return validation

    cycle_command = f"cd {shlex.quote(remote_dir)} && {cycle_cmd}"
    cycle_result = run_remote_command(host, key_path, cycle_command, check=False)
    validation["single_cycle"] = {
        "command": cycle_cmd,
        "skipped": False,
        "reason": "",
        "returncode": cycle_result.returncode,
        "stdout_tail": (cycle_result.stdout or "").splitlines()[-20:],
        "stderr_tail": (cycle_result.stderr or "").splitlines()[-20:],
    }
    return validation


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def build_deploy_artifact(
    *,
    report_path: Path,
    manifest_path: Path,
    release_plan: ReleasePlan | None,
    deploy_status: str,
    host: str,
    remote_dir: str,
    bridge_refresh_attempted: bool,
    pre_service: dict[str, Any] | None,
    post_service: dict[str, Any] | None,
    env_key_report: dict[str, Any] | None,
    checksum_report: dict[str, Any] | None,
    validation_report: dict[str, Any] | None,
    stale_state: bool,
    notes: Sequence[str],
) -> dict[str, Any]:
    """Build and persist the deploy artifact."""

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_status": deploy_status,
        "stale_state": stale_state,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "bridge_refresh_attempted": bridge_refresh_attempted,
        "target": {
            "host": host,
            "remote_dir": remote_dir,
        },
        "release": {
            "repo_sha": release_plan.repo_sha if release_plan else None,
            "ci_status": release_plan.ci_status if release_plan else None,
            "restart_recommended": release_plan.restart_recommended if release_plan else None,
            "deploy_files": list(release_plan.deploy_files) if release_plan else [],
        },
        "pre_service": pre_service,
        "post_service": post_service,
        "env_keys": env_key_report,
        "checksums": checksum_report,
        "validation": validation_report,
        "notes": list(notes),
    }
    _write_json(report_path, payload)
    return payload


def _timestamped_deploy_report_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORTS_DIR / f"deploy_{timestamp}.json"


def _run_bridge_pull_only(key_path: Path) -> subprocess.CompletedProcess[str]:
    return _run_command(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "bridge.sh"),
            "--pull-only",
            "--skip-flywheel",
            "--key",
            str(key_path),
        ],
        check=False,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy a release bundle to the VPS")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the release manifest JSON",
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Generate a deterministic release manifest from this cycle's changed files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to the deploy artifact JSON",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_REMOTE_HOST,
        help="Remote SSH target",
    )
    parser.add_argument(
        "--remote-dir",
        default=DEFAULT_REMOTE_DIR,
        help="Remote deployment directory",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=None,
        help="Path to the VPS SSH key",
    )
    parser.add_argument(
        "--skip-bridge-refresh",
        action="store_true",
        help="Skip the required bridge pull-only refresh",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = args.manifest.resolve()
    if args.write_manifest:
        written = write_release_manifest(REPO_ROOT, manifest_path)
        print(written)
        return 0

    report_path = args.output.resolve() if args.output else _timestamped_deploy_report_path()
    key_path = args.key.resolve() if args.key else discover_ssh_key(REPO_ROOT)
    if key_path is None:
        raise DeployError("SSH key not found; pass --key or configure LIGHTSAIL_KEY")

    bridge_refresh_attempted = False
    notes: list[str] = []
    if not args.skip_bridge_refresh:
        bridge_refresh_attempted = True
        bridge_result = _run_bridge_pull_only(key_path)
        notes.append(
            f"bridge_pull_only_returncode={bridge_result.returncode}"
        )
        if bridge_result.returncode != 0:
            notes.append("bridge pull-only refresh failed before deploy")

    pre_service = get_remote_service_snapshot(args.host, key_path)
    post_service: dict[str, Any] | None = None
    env_key_report: dict[str, Any] | None = None
    checksum_report: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    release_plan: ReleasePlan | None = None

    template_keys = read_env_keys(REPO_ROOT / ".env.example")
    remote_env = get_remote_env_keys(args.host, key_path, args.remote_dir)
    env_key_report = {
        "template_key_count": len(template_keys),
        "remote_env_exists": bool(remote_env.get("exists")),
        "remote_key_count": len(remote_env.get("keys", [])),
        "missing_keys": compare_env_keys(template_keys, remote_env.get("keys", [])),
    }

    if not manifest_path.exists():
        notes.append("release manifest missing; deploy skipped with stale-state note")
        validation_report = (
            run_remote_paper_validation(args.host, key_path, args.remote_dir)
            if pre_service["status"] == "stopped"
            else None
        )
        build_deploy_artifact(
            report_path=report_path,
            manifest_path=manifest_path,
            release_plan=None,
            deploy_status="skipped_missing_manifest",
            host=args.host,
            remote_dir=args.remote_dir,
            bridge_refresh_attempted=bridge_refresh_attempted,
            pre_service=pre_service,
            post_service=None,
            env_key_report=env_key_report,
            checksum_report=None,
            validation_report=validation_report,
            stale_state=True,
            notes=notes,
        )
        print(report_path)
        return 0

    release_plan = load_release_plan(REPO_ROOT, manifest_path)
    notes.append(
        f"release manifest loaded for repo_sha={release_plan.repo_sha or 'unknown'}"
    )

    with tempfile.TemporaryDirectory(prefix="elastifund-release-") as tmpdir:
        bundle_path = Path(tmpdir) / "release_bundle.tar.gz"
        create_release_bundle(REPO_ROOT, release_plan, bundle_path)
        remote_bundle = f"/tmp/elastifund-release-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
        upload_bundle(args.host, key_path, bundle_path, remote_bundle)
        extract_remote_bundle(args.host, key_path, args.remote_dir, remote_bundle)

    checksum_report = verify_remote_checksums(
        args.host,
        key_path,
        args.remote_dir,
        release_plan.checksums,
    )
    if not checksum_report.get("ok"):
        notes.append("remote checksum verification failed")
        post_service = get_remote_service_snapshot(args.host, key_path)
        build_deploy_artifact(
            report_path=report_path,
            manifest_path=manifest_path,
            release_plan=release_plan,
            deploy_status="failed_checksum_mismatch",
            host=args.host,
            remote_dir=args.remote_dir,
            bridge_refresh_attempted=bridge_refresh_attempted,
            pre_service=pre_service,
            post_service=post_service,
            env_key_report=env_key_report,
            checksum_report=checksum_report,
            validation_report=None,
            stale_state=False,
            notes=notes,
        )
        print(report_path)
        return 1

    if pre_service["status"] == "running":
        restart_result = restart_remote_service(args.host, key_path)
        notes.append(f"service_restart_returncode={restart_result.returncode}")
        post_service = get_remote_service_snapshot(args.host, key_path)
        deploy_status = (
            "deployed"
            if restart_result.returncode == 0 and post_service["status"] == "running"
            else "failed_service_restart"
        )
    else:
        if release_plan.restart_recommended:
            notes.append("restart recommended upstream, but service was already stopped and remained stopped")
        validation_report = run_remote_paper_validation(args.host, key_path, args.remote_dir)
        post_service = get_remote_service_snapshot(args.host, key_path)
        status_ok = validation_report["status_command"]["returncode"] == 0
        cycle = validation_report["single_cycle"]
        cycle_ok = cycle["skipped"] or cycle["returncode"] == 0
        deploy_status = "deployed" if status_ok and cycle_ok else "deployed_validation_failed"

    build_deploy_artifact(
        report_path=report_path,
        manifest_path=manifest_path,
        release_plan=release_plan,
        deploy_status=deploy_status,
        host=args.host,
        remote_dir=args.remote_dir,
        bridge_refresh_attempted=bridge_refresh_attempted,
        pre_service=pre_service,
        post_service=post_service,
        env_key_report=env_key_report,
        checksum_report=checksum_report,
        validation_report=validation_report,
        stale_state=False,
        notes=notes,
    )
    print(report_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
