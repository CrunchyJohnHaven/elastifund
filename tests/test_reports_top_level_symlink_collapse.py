from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_collapse_top_level_symlinks_removes_non_allowlisted(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    target = reports / "canonical.json"
    target.write_text("{}\n", encoding="utf-8")
    (reports / "keep.json").symlink_to("canonical.json")
    (reports / "drop.json").symlink_to("canonical.json")

    policy = reports / "retention_policy.json"
    policy.write_text(json.dumps({"top_level_symlink_allowlist": ["keep.json"]}) + "\n", encoding="utf-8")

    mod = _load_module(
        Path(__file__).resolve().parents[1] / "reports" / "tools" / "collapse_top_level_symlinks.py",
        "collapse_top_level_symlinks",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "REPORTS", reports)
    monkeypatch.setattr(mod, "POLICY_PATH", policy)
    monkeypatch.setattr(sys, "argv", ["collapse_top_level_symlinks.py", "--apply"])

    rc = mod.main()
    assert rc == 0
    assert (reports / "keep.json").is_symlink()
    assert not (reports / "drop.json").exists()


def test_collapse_top_level_symlinks_creates_allowlisted_missing_symlink(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    canonical_dir = reports / "runtime"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    (canonical_dir / "canonical.json").write_text("{}\n", encoding="utf-8")

    policy = reports / "retention_policy.json"
    policy.write_text(json.dumps({"top_level_symlink_allowlist": ["canonical.json"]}) + "\n", encoding="utf-8")

    mod = _load_module(
        Path(__file__).resolve().parents[1] / "reports" / "tools" / "collapse_top_level_symlinks.py",
        "collapse_top_level_symlinks_create",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "REPORTS", reports)
    monkeypatch.setattr(mod, "POLICY_PATH", policy)
    monkeypatch.setattr(mod, "ALIASES_INDEX_PATH", reports / "legacy_aliases_latest.json")
    monkeypatch.setattr(sys, "argv", ["collapse_top_level_symlinks.py", "--apply"])

    rc = mod.main()
    assert rc == 0
    assert (reports / "canonical.json").is_symlink()
    assert (reports / "canonical.json").resolve() == (canonical_dir / "canonical.json")


def test_render_reports_manifest_tracks_allowlist_and_non_allowlisted(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    for name in (
        "README.md",
        "repo_manifest.json",
        "manifest_latest.json",
        "retention_policy.json",
        "normalization_plan_latest.json",
        "improvement_velocity.json",
        "improvement_velocity.svg",
        "arr_estimate.svg",
        "jjn_public_report.json",
        "nontrading_public_report.json",
        "runtime_truth_latest.json",
        "remote_cycle_status.json",
        "remote_service_status.json",
        "public_runtime_snapshot.json",
        "launch_packet_latest.json",
        "state_improvement_latest.json",
    ):
        (reports / name).write_text("{}\n", encoding="utf-8")

    (reports / "keep.json").write_text("{}\n", encoding="utf-8")
    (reports / "legacy_keep.json").symlink_to("keep.json")
    (reports / "legacy_drop.json").symlink_to("keep.json")

    retention_policy = {
        "top_level_symlink_allowlist": ["legacy_keep.json"],
    }
    (reports / "retention_policy.json").write_text(json.dumps(retention_policy) + "\n", encoding="utf-8")
    (reports / "normalization_plan_latest.json").write_text(
        json.dumps({"generated_at": "2026-03-11T00:00:00Z", "summary": {"proposed_move_count": 0}}) + "\n",
        encoding="utf-8",
    )

    out = reports / "manifest_latest.json"
    mod = _load_module(
        Path(__file__).resolve().parents[1] / "reports" / "tools" / "render_reports_manifest.py",
        "render_reports_manifest",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "REPORTS", reports)
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(mod, "RETENTION_POLICY_PATH", reports / "retention_policy.json")

    rc = mod.main()
    assert rc == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    layout = manifest["layout_status"]
    assert layout["top_level_symlink_count"] == 2
    assert layout["compatibility_symlink_allowlist"] == ["legacy_keep.json"]
    assert layout["non_allowlisted_symlink_count"] == 1
    assert layout["non_allowlisted_symlinks"] == ["legacy_drop.json"]
