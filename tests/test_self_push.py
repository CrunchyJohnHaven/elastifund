from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.self_push import (
    build_runtime_env,
    normalize_github_https_url,
    normalize_json_payload,
    self_push,
)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "JJ Test")
    _git(path, "config", "user.email", "jj@example.com")


def _init_bare_remote(path: Path) -> None:
    _git(path, "init", "--bare")
    # Linux git clones can skip checkout if the bare remote HEAD still points at master.
    _git(path, "symbolic-ref", "HEAD", "refs/heads/main")


def test_self_push_commits_only_selected_paths(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()

    _init_bare_remote(remote)
    _init_repo(repo)
    (repo / "reports").mkdir()
    (repo / "FAST_TRADE_EDGE_ANALYSIS.md").write_text("base\n")
    (repo / "notes.txt").write_text("keep local\n")
    _git(repo, "add", "FAST_TRADE_EDGE_ANALYSIS.md", "notes.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")

    (repo / "FAST_TRADE_EDGE_ANALYSIS.md").write_text("updated\n")
    (repo / "notes.txt").write_text("do not push this\n")

    result = self_push(
        repo,
        message="auto: publish",
        remote="origin",
        branch="main",
        paths=("FAST_TRADE_EDGE_ANALYSIS.md",),
        dry_run=False,
    )

    assert result["pushed"] is True
    assert result["staged_paths"] == ["FAST_TRADE_EDGE_ANALYSIS.md"]
    assert _git(repo, "status", "--short") == "M notes.txt"

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True, text=True)
    assert (clone / "FAST_TRADE_EDGE_ANALYSIS.md").read_text() == "updated\n"
    assert (clone / "notes.txt").read_text() == "keep local\n"


def test_self_push_skips_json_timestamp_only_changes(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()

    _init_bare_remote(remote)
    _init_repo(repo)
    (repo / "reports").mkdir()
    snapshot = {
        "generated_at": "2026-03-08T00:00:00+00:00",
        "summary": {"cycles_completed": 3},
        "artifacts": {"runtime_truth_timestamped_json": "reports/runtime_truth_1.json"},
    }
    path = repo / "reports" / "runtime_truth_latest.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    _git(repo, "add", "reports/runtime_truth_latest.json")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")

    snapshot["generated_at"] = "2026-03-09T00:00:00+00:00"
    snapshot["artifacts"]["runtime_truth_timestamped_json"] = "reports/runtime_truth_2.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))

    result = self_push(
        repo,
        message="auto: publish",
        remote="origin",
        branch="main",
        paths=("reports/runtime_truth_latest.json",),
        dry_run=False,
    )

    assert result["pushed"] is False
    assert result["staged_paths"] == []


def test_self_push_force_adds_ignored_selected_paths(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()

    _init_bare_remote(remote)
    _init_repo(repo)
    (repo / "reports").mkdir()
    (repo / ".gitignore").write_text("reports/\n")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")

    snapshot = {
        "generated_at": "2026-03-09T17:32:19+00:00",
        "runtime": {"btc5_live_filled_rows": 38},
    }
    path = repo / "reports" / "runtime_truth_latest.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))

    result = self_push(
        repo,
        message="auto: publish",
        remote="origin",
        branch="main",
        paths=("reports/runtime_truth_latest.json",),
        dry_run=False,
    )

    assert result["pushed"] is True
    assert result["staged_paths"] == ["reports/runtime_truth_latest.json"]

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True, text=True)
    assert json.loads((clone / "reports" / "runtime_truth_latest.json").read_text()) == snapshot


def test_normalize_github_https_url_handles_ssh_and_https() -> None:
    assert (
        normalize_github_https_url("git@github.com:CrunchyJohnHaven/elastifund.git")
        == "https://github.com/CrunchyJohnHaven/elastifund.git"
    )
    assert (
        normalize_github_https_url("https://x-access-token:secret@github.com/CrunchyJohnHaven/elastifund.git")
        == "https://github.com/CrunchyJohnHaven/elastifund.git"
    )


def test_build_runtime_env_reads_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ELASTIFUND_GITHUB_TOKEN", raising=False)
    (tmp_path / ".env").write_text("ELASTIFUND_GITHUB_TOKEN=test-token\n")

    env = build_runtime_env(tmp_path)

    assert env["ELASTIFUND_GITHUB_TOKEN"] == "test-token"


def test_normalize_json_payload_strips_volatile_fields() -> None:
    payload = {
        "generated_at": "2026-03-09T00:00:00+00:00",
        "summary": {"cycles_completed": 3},
        "artifacts": {
            "scorecard": "reports/flywheel/20260309/scorecard.json",
            "stable": "reports/runtime_truth_latest.json",
        },
    }

    assert normalize_json_payload(payload) == {
        "artifacts": {"stable": "reports/runtime_truth_latest.json"},
        "summary": {"cycles_completed": 3},
    }
