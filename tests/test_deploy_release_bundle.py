from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from scripts.deploy_release_bundle import (
    DeployError,
    build_release_contract,
    build_env_key_diff,
    build_release_manifest,
    build_remote_paper_commands,
    compare_env_keys,
    create_release_bundle,
    load_release_plan,
    normalize_service_state,
    parse_env_keys_from_text,
    select_deployable_changed_files,
    validate_env_key_alignment,
    validate_release_plan,
)


def test_parse_env_keys_from_text_ignores_comments_and_invalid_keys() -> None:
    text = """
    # comment
    VALID_ONE=value
    export INVALID_EXPORT=value
    VALID_TWO = spaced
    MISSING_VALUE=
    not-an-assignment
    1BROKEN=value
    """

    assert parse_env_keys_from_text(text) == ["VALID_ONE", "VALID_TWO", "MISSING_VALUE"]


def test_compare_env_keys_returns_sorted_missing_values() -> None:
    template = ["BETA", "ALPHA", "GAMMA"]
    remote = ["ALPHA"]

    assert compare_env_keys(template, remote) == ["BETA", "GAMMA"]


def test_select_deployable_changed_files_filters_to_runtime_surfaces() -> None:
    changed_files = [
        "README.md",
        "docs/REPO_MAP.md",
        "tests/test_remote_cycle_status.py",
        ".env.example",
        "bot/jj_live.py",
        "infra/filebeat.yml",
        "scripts/deploy_release_bundle.py",
        "index.html",
        "reports/remote_cycle_status.json",
        "nontrading/main.py",
    ]

    assert select_deployable_changed_files(changed_files) == (
        ".env.example",
        "bot/jj_live.py",
        "infra/filebeat.yml",
        "scripts/deploy_release_bundle.py",
    )


def test_build_env_key_diff_detects_added_and_removed_keys() -> None:
    diff = build_env_key_diff(
        "BETA=1\nGAMMA=1\n",
        "ALPHA=1\nBETA=1\n",
    )

    assert diff["template_key_count"] == 2
    assert diff["added_in_cycle"] == ["GAMMA"]
    assert diff["removed_in_cycle"] == ["ALPHA"]


def test_normalize_service_state_maps_systemctl_states() -> None:
    assert normalize_service_state("active")["status"] == "running"
    assert normalize_service_state("inactive")["status"] == "stopped"
    assert normalize_service_state("")["status"] == "unknown"


def test_load_release_plan_expands_directories_and_hashes_files(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "deploy").mkdir()
    (tmp_path / "scripts" / "bridge.sh").write_text("echo bridge\n")
    (tmp_path / "deploy" / "README.md").write_text("deploy readme\n")
    (tmp_path / "reports" / "parallel").mkdir(parents=True)
    manifest = tmp_path / "reports" / "parallel" / "release_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repo_sha": "abc123",
                "ci_status": "green",
                "restart_recommended": True,
                "deploy_files": ["scripts", "deploy/README.md"],
            }
        )
    )

    plan = load_release_plan(tmp_path, manifest)

    expected_files = ("deploy/README.md", "scripts/bridge.sh")
    assert plan.repo_sha == "abc123"
    assert plan.ci_status == "green"
    assert plan.restart_recommended is True
    assert plan.deploy_files == expected_files
    assert plan.checksums["scripts/bridge.sh"] == hashlib.sha256(b"echo bridge\n").hexdigest()
    assert plan.checksums["deploy/README.md"] == hashlib.sha256(b"deploy readme\n").hexdigest()


def test_load_release_plan_rejects_stale_manifest_checksums(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bridge.sh").write_text("echo bridge\n")
    (tmp_path / "reports" / "parallel").mkdir(parents=True)
    manifest = tmp_path / "reports" / "parallel" / "release_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "deploy_files": ["scripts/bridge.sh"],
                "checksums": {"scripts/bridge.sh": "deadbeef"},
            }
        )
    )

    with pytest.raises(DeployError, match="checksum validation failed"):
        load_release_plan(tmp_path, manifest)


def test_load_release_plan_rejects_repo_escape(tmp_path: Path) -> None:
    (tmp_path / "reports" / "parallel").mkdir(parents=True)
    manifest = tmp_path / "reports" / "parallel" / "release_manifest.json"
    manifest.write_text(json.dumps({"deploy_files": ["../outside.txt"]}))

    with pytest.raises(DeployError):
        load_release_plan(tmp_path, manifest)


def test_load_release_plan_rejects_non_allowlisted_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "reports" / "parallel").mkdir(parents=True)
    manifest = tmp_path / "reports" / "parallel" / "release_manifest.json"
    manifest.write_text(json.dumps({"deploy_files": ["README.md"]}))

    with pytest.raises(DeployError, match="non-deployable"):
        load_release_plan(tmp_path, manifest)


def test_create_release_bundle_includes_only_allowlisted_files(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.sh").write_text("echo deploy\n")
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "reports" / "parallel").mkdir(parents=True)
    manifest = tmp_path / "reports" / "parallel" / "release_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "deploy_files": ["scripts/deploy.sh"],
            }
        )
    )
    plan = load_release_plan(tmp_path, manifest)
    bundle_path = tmp_path / "bundle.tar.gz"

    create_release_bundle(tmp_path, plan, bundle_path)

    with tarfile.open(bundle_path, "r:gz") as archive:
        assert archive.getnames() == ["scripts/deploy.sh"]


def test_validate_env_key_alignment_reports_missing_template_keys(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("KNOWN_KEY=1\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "env_check.py").write_text(
        "import os\n"
        "KNOWN = os.getenv('KNOWN_KEY')\n"
        "MISSING = os.environ['MISSING_KEY']\n"
    )

    report = validate_env_key_alignment(tmp_path, ["scripts/env_check.py"])

    assert report["referenced_keys"] == ["KNOWN_KEY", "MISSING_KEY"]
    assert report["missing_from_template"] == ["MISSING_KEY"]
    assert report["valid"] is False


def test_build_release_contract_requires_snapshot_and_profile_selection(tmp_path: Path) -> None:
    _write_release_contract_files(tmp_path)
    (tmp_path / ".env.example").write_text("JJ_RUNTIME_PROFILE=shadow_fast_flow\n")

    contract = build_release_contract(tmp_path)

    assert contract["valid"] is True
    assert contract["selected_profile"] == "shadow_fast_flow"
    assert contract["missing_bundle_files"] == []
    assert contract["missing_profile_names"] == []
    assert contract["required_bundle_files"] == [
        ".env.example",
        "config/runtime_profiles/blocked_safe.json",
        "config/runtime_profiles/research_scan.json",
        "config/runtime_profiles/shadow_fast_flow.json",
        "reports/public_runtime_snapshot.json",
        "reports/runtime_profile_effective.json",
        "reports/runtime_truth_latest.json",
    ]


def test_validate_release_plan_flags_stale_sha_and_missing_required_bundle_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bridge.sh").write_text("echo bridge\n")
    _write_release_contract_files(tmp_path)
    (tmp_path / ".env.example").write_text("JJ_RUNTIME_PROFILE=shadow_fast_flow\n")
    (tmp_path / "reports" / "parallel").mkdir(parents=True)
    manifest = tmp_path / "reports" / "parallel" / "release_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repo_sha": "oldsha",
                "ci_status": "green",
                "deploy_files": ["scripts/bridge.sh"],
                "checksums": {
                    "scripts/bridge.sh": hashlib.sha256(b"echo bridge\n").hexdigest(),
                },
            }
        )
    )
    monkeypatch.setattr(
        "scripts.deploy_release_bundle._get_git_head_sha",
        lambda _repo_root: "newsha",
    )

    plan = load_release_plan(tmp_path, manifest)
    validation = validate_release_plan(tmp_path, manifest, plan)

    assert validation["valid"] is False
    assert validation["repo_sha_matches_head"] is False
    assert validation["missing_required_bundle_files"] == [
        ".env.example",
        "config/runtime_profiles/blocked_safe.json",
        "config/runtime_profiles/research_scan.json",
        "config/runtime_profiles/shadow_fast_flow.json",
        "reports/public_runtime_snapshot.json",
        "reports/runtime_profile_effective.json",
        "reports/runtime_truth_latest.json",
    ]
    assert any("does not match HEAD" in issue for issue in validation["issues"])


def test_build_release_manifest_collects_checksums_and_runtime_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "bot").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "config" / "runtime_profiles").mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    (tmp_path / "bot" / "jj_live.py").write_text("print('ok')\n")
    (tmp_path / "docs" / "ignored.md").write_text("skip\n")
    _write_release_contract_files(tmp_path)
    (tmp_path / ".env.example").write_text("KEEP_ME=1\nNEW_KEY=1\nJJ_RUNTIME_PROFILE=shadow_fast_flow\n")
    (tmp_path / "reports" / "root_test_status.json").write_text(
        json.dumps({"status": "passing", "summary": "22 passed", "checked_at": "2026-03-09T00:06:56Z"})
    )
    (tmp_path / "reports" / "remote_cycle_status.json").write_text(
        json.dumps(
            {
                "launch": {
                    "fast_flow_restart_ready": True,
                    "live_launch_blocked": True,
                },
                "runtime_truth": {
                    "drift_detected": True,
                    "service_drift_detected": True,
                },
            }
        )
    )
    (tmp_path / "reports" / "edge_scan_20260309T000551Z.json").write_text(
        json.dumps({"restart_recommended": True})
    )
    (tmp_path / "config" / "runtime_profiles" / "blocked_safe.json").write_text("{}\n")
    (tmp_path / "config" / "runtime_profiles" / "shadow_fast_flow.json").write_text("{}\n")
    (tmp_path / "config" / "runtime_profiles" / "research_scan.json").write_text("{}\n")

    monkeypatch.setattr(
        "scripts.deploy_release_bundle.list_cycle_changed_files",
        lambda _repo_root: ("bot/jj_live.py", "docs/ignored.md", ".env.example"),
    )
    monkeypatch.setattr(
        "scripts.deploy_release_bundle._get_git_head_sha",
        lambda _repo_root: "abc123def456",
    )
    monkeypatch.setattr(
        "scripts.deploy_release_bundle._git_show_text",
        lambda _repo_root, _revision, _path: "KEEP_ME=1\nOLD_KEY=1\n",
    )

    manifest = build_release_manifest(tmp_path)

    assert manifest["repo_sha"] == "abc123def456"
    assert manifest["repo_sha_short"] == "abc123d"
    assert manifest["ci_status"] == "green"
    assert manifest["restart_recommended"] is False
    assert manifest["restart_source"] == "reports/remote_cycle_status.json#launch.live_launch_blocked"
    assert manifest["deploy_files"] == [
        ".env.example",
        "bot/jj_live.py",
        "config/runtime_profiles/blocked_safe.json",
        "config/runtime_profiles/research_scan.json",
        "config/runtime_profiles/shadow_fast_flow.json",
        "reports/public_runtime_snapshot.json",
        "reports/runtime_profile_effective.json",
        "reports/runtime_truth_latest.json",
    ]
    assert manifest["excluded_changed_files"] == ["docs/ignored.md"]
    assert manifest["checksums"]["bot/jj_live.py"] == hashlib.sha256(b"print('ok')\n").hexdigest()
    assert manifest["env_key_diff"]["added_in_cycle"] == ["JJ_RUNTIME_PROFILE", "NEW_KEY"]
    assert manifest["env_key_diff"]["removed_in_cycle"] == ["OLD_KEY"]
    assert manifest["env_key_alignment"]["valid"] is True
    assert manifest["release_contract"]["selected_profile"] == "shadow_fast_flow"


def test_build_remote_paper_commands_uses_remote_dir() -> None:
    status_command, cycle_command = build_remote_paper_commands("/srv/bot")

    assert "PYTHONPATH=/srv/bot:/srv/bot/bot:/srv/bot/polymarket-bot" in status_command
    assert status_command.endswith("timeout 120 python3 bot/jj_live.py --status")
    assert "timeout 300 python3 bot/jj_live.py" in cycle_command


def _write_release_contract_files(tmp_path: Path) -> None:
    (tmp_path / "config" / "runtime_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "runtime_profiles" / "blocked_safe.json").write_text("{}\n")
    (tmp_path / "config" / "runtime_profiles" / "shadow_fast_flow.json").write_text("{}\n")
    (tmp_path / "config" / "runtime_profiles" / "research_scan.json").write_text("{}\n")
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "reports" / "runtime_truth_latest.json").write_text("{}\n")
    (tmp_path / "reports" / "public_runtime_snapshot.json").write_text("{}\n")
    (tmp_path / "reports" / "runtime_profile_effective.json").write_text(
        json.dumps({"selected_profile": "shadow_fast_flow"})
    )
