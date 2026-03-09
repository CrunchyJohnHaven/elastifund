#!/usr/bin/env python3
"""Commit and push material flywheel/runtime updates without interactive auth."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_PUSH_PATHS = (
    "FAST_TRADE_EDGE_ANALYSIS.md",
    "reports/flywheel/latest_sync.json",
    "reports/public_runtime_snapshot.json",
    "reports/runtime_truth_latest.json",
)
VOLATILE_JSON_KEYS = {
    "checked_at",
    "cycle_key",
    "expected_next_pull_at",
    "generated_at",
    "last_updated",
    "report_generated_at",
    "timestamp",
}
VOLATILE_ARTIFACT_KEYS = {
    "findings_json",
    "runtime_truth_timestamped_json",
    "scorecard",
    "summary_md",
}
SSH_KEY_ENV_KEYS = ("ELASTIFUND_GITHUB_SSH_KEY",)
TOKEN_ENV_KEYS = ("ELASTIFUND_GITHUB_TOKEN", "GITHUB_TOKEN")
SSH_KEY_CANDIDATES = (
    Path("~/.elastifund/github_id_ed25519").expanduser(),
    Path("~/.ssh/id_ed25519").expanduser(),
    Path("~/.ssh/id_rsa").expanduser(),
)


class SelfPushError(RuntimeError):
    """Raised when staging, committing, or pushing fails."""


@dataclass(frozen=True)
class PushAuth:
    push_target: str
    env: dict[str, str]
    auth_mode: str
    cleanup_path: Path | None = None


def load_dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not ENV_KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values.setdefault(key, value)
    return values


def build_runtime_env(repo_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in load_dotenv_values(repo_root / ".env").items():
        env.setdefault(key, value)
    return env


def run_git(
    repo_root: Path,
    args: Iterable[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise SelfPushError(stderr)
    return result


def git_remote_url(repo_root: Path, remote: str) -> str:
    return run_git(repo_root, ["config", "--get", f"remote.{remote}.url"]).stdout.strip()


def current_branch(repo_root: Path) -> str:
    branch = run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if not branch or branch == "HEAD":
        raise SelfPushError("cannot self-push from a detached HEAD")
    return branch


def normalize_github_https_url(remote_url: str) -> str | None:
    if remote_url.startswith("git@github.com:"):
        return f"https://github.com/{remote_url.split(':', 1)[1]}"
    if remote_url.startswith("ssh://git@github.com/"):
        return f"https://github.com/{remote_url.split('ssh://git@github.com/', 1)[1]}"
    parsed = urlparse(remote_url)
    if parsed.scheme in {"http", "https"} and parsed.hostname == "github.com":
        return f"https://github.com/{parsed.path.lstrip('/')}"
    return None


def create_askpass_script() -> Path:
    handle = tempfile.NamedTemporaryFile("w", delete=False, prefix="elastifund-askpass-", suffix=".sh")
    handle.write(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  *Username*) printf "%s" "x-access-token" ;;\n'
        '  *) printf "%s" "${ELASTIFUND_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}" ;;\n'
        "esac\n"
    )
    handle.close()
    path = Path(handle.name)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def detect_ssh_key(env: dict[str, str]) -> Path | None:
    for key in SSH_KEY_ENV_KEYS:
        value = env.get(key)
        if value:
            path = Path(value).expanduser()
            if not path.exists():
                raise SelfPushError(f"{key} points to a missing file: {path}")
            return path
    for candidate in SSH_KEY_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def build_push_auth(repo_root: Path, remote: str, env: dict[str, str]) -> PushAuth:
    remote_url = git_remote_url(repo_root, remote)
    token = next((env.get(key) for key in TOKEN_ENV_KEYS if env.get(key)), None)
    if token:
        https_remote = normalize_github_https_url(remote_url)
        if not https_remote:
            raise SelfPushError("token auth is only supported for GitHub remotes")
        askpass_path = create_askpass_script()
        push_env = dict(env)
        push_env["GIT_ASKPASS"] = str(askpass_path)
        push_env["GIT_TERMINAL_PROMPT"] = "0"
        push_env["ELASTIFUND_GITHUB_TOKEN"] = token
        return PushAuth(push_target=https_remote, env=push_env, auth_mode="token", cleanup_path=askpass_path)

    ssh_key = detect_ssh_key(env)
    if ssh_key and "github.com" in remote_url:
        push_env = dict(env)
        push_env["GIT_SSH_COMMAND"] = (
            f"ssh -i {shlex.quote(str(ssh_key))} "
            "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )
        return PushAuth(push_target=remote, env=push_env, auth_mode="ssh_key")

    return PushAuth(push_target=remote, env=dict(env), auth_mode="default")


def status_lines_for_path(repo_root: Path, path: str) -> list[str]:
    output = run_git(repo_root, ["status", "--porcelain=v1", "--", path]).stdout
    return [line for line in output.splitlines() if line.strip()]


def head_file_text(repo_root: Path, path: str) -> str | None:
    result = run_git(repo_root, ["show", f"HEAD:{path}"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def normalize_json_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key, value in sorted(payload.items()):
            if key in VOLATILE_JSON_KEYS:
                continue
            if key == "artifacts" and isinstance(value, dict):
                artifacts = {
                    artifact_key: normalize_json_payload(artifact_value)
                    for artifact_key, artifact_value in sorted(value.items())
                    if artifact_key not in VOLATILE_ARTIFACT_KEYS
                }
                if artifacts:
                    normalized[key] = artifacts
                continue
            normalized[key] = normalize_json_payload(value)
        return normalized
    if isinstance(payload, list):
        return [normalize_json_payload(item) for item in payload]
    return payload


def is_json_metadata_only_change(repo_root: Path, path: str) -> bool:
    current_path = repo_root / path
    head_text = head_file_text(repo_root, path)
    if head_text is None or not current_path.exists():
        return False
    try:
        current_payload = json.loads(current_path.read_text())
        head_payload = json.loads(head_text)
    except json.JSONDecodeError:
        return False
    return normalize_json_payload(current_payload) == normalize_json_payload(head_payload)


def select_paths_to_stage(repo_root: Path, paths: Iterable[str]) -> list[str]:
    selected: list[str] = []
    for path in paths:
        lines = status_lines_for_path(repo_root, path)
        if not lines:
            continue
        if path.endswith(".json") and is_json_metadata_only_change(repo_root, path):
            continue
        selected.append(path)
    return selected


def stage_paths(repo_root: Path, paths: Iterable[str]) -> list[str]:
    selected = select_paths_to_stage(repo_root, paths)
    if not selected:
        return []
    run_git(repo_root, ["add", "--all", "--", *selected])
    return selected


def has_staged_changes(repo_root: Path) -> bool:
    result = run_git(repo_root, ["diff", "--cached", "--quiet"], check=False)
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise SelfPushError(result.stderr.strip() or "failed to inspect staged diff")


def create_commit(repo_root: Path, message: str) -> str:
    run_git(repo_root, ["commit", "-s", "--no-gpg-sign", "-m", message])
    return run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()


def push_head(repo_root: Path, push_auth: PushAuth, branch: str, *, dry_run: bool) -> None:
    args = ["push", "--porcelain"]
    if dry_run:
        args.append("--dry-run")
    args.extend([push_auth.push_target, f"HEAD:{branch}"])
    run_git(repo_root, args, env=push_auth.env)


def self_push(
    repo_root: Path,
    *,
    message: str,
    remote: str,
    branch: str | None,
    paths: Iterable[str],
    dry_run: bool,
) -> dict[str, Any]:
    runtime_env = build_runtime_env(repo_root)
    push_auth = build_push_auth(repo_root, remote, runtime_env)
    resolved_branch = branch or current_branch(repo_root)
    try:
        staged_paths = stage_paths(repo_root, paths)
        if not staged_paths or not has_staged_changes(repo_root):
            return {
                "auth_mode": push_auth.auth_mode,
                "branch": resolved_branch,
                "commit": None,
                "pushed": False,
                "staged_paths": staged_paths,
            }
        commit_sha = create_commit(repo_root, message)
        push_head(repo_root, push_auth, resolved_branch, dry_run=dry_run)
    finally:
        if push_auth.cleanup_path is not None and push_auth.cleanup_path.exists():
            push_auth.cleanup_path.unlink()
    return {
        "auth_mode": push_auth.auth_mode,
        "branch": resolved_branch,
        "commit": commit_sha,
        "pushed": True,
        "staged_paths": staged_paths,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Commit and push material cycle artifacts to GitHub.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repo root to push from")
    parser.add_argument("--message", help="Commit message")
    parser.add_argument("--remote", default="origin", help="Git remote name")
    parser.add_argument("--branch", help="Branch to push to (defaults to current branch)")
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Path to stage; repeat to add more paths. Defaults to the cycle artifact allowlist.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Create the commit, but dry-run the push")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    message = args.message or f"auto: cycle publish {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    result = self_push(
        repo_root,
        message=message,
        remote=args.remote,
        branch=args.branch,
        paths=tuple(args.paths or DEFAULT_PUSH_PATHS),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
