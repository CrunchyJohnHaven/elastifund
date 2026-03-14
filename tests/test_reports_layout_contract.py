from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_collapse_top_level_symlinks_respects_allowlist(tmp_path: Path) -> None:
    mod = _load_module(
        Path(__file__).resolve().parents[1] / "reports" / "tools" / "collapse_top_level_symlinks.py",
        "collapse_top_level_symlinks",
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "target.json").write_text("{}", encoding="utf-8")
    (reports_dir / "keep.json").symlink_to("target.json")
    (reports_dir / "drop.json").symlink_to("target.json")

    dry = mod.collapse_symlinks(reports_dir=reports_dir, allowlist={"keep.json"}, apply=False)
    assert dry["top_level_symlink_total"] == 2
    assert dry["top_level_symlink_kept"] == 1
    assert dry["top_level_symlink_removed_or_planned"] == 1
    assert (reports_dir / "drop.json").is_symlink()

    applied = mod.collapse_symlinks(reports_dir=reports_dir, allowlist={"keep.json"}, apply=True)
    assert applied["top_level_symlink_removed_or_planned"] == 1
    assert not (reports_dir / "drop.json").exists()
    assert (reports_dir / "keep.json").is_symlink()


def test_render_reports_manifest_counts_non_allowlisted_symlinks(tmp_path: Path) -> None:
    mod = _load_module(
        Path(__file__).resolve().parents[1] / "reports" / "tools" / "render_reports_manifest.py",
        "render_reports_manifest",
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    retention_policy = reports_dir / "retention_policy.json"
    retention_policy.write_text('{"top_level_symlink_allowlist": ["keep.json"]}\n', encoding="utf-8")
    (reports_dir / "README.md").write_text("# reports\n", encoding="utf-8")
    (reports_dir / "manifest_latest.json").write_text("{}\n", encoding="utf-8")
    (reports_dir / "runtime_truth_latest.json").write_text("{}\n", encoding="utf-8")
    (reports_dir / "target.json").write_text("{}\n", encoding="utf-8")
    (reports_dir / "keep.json").symlink_to("target.json")
    (reports_dir / "drop.json").symlink_to("target.json")

    mod.REPORTS = reports_dir
    mod.RETENTION_POLICY_PATH = retention_policy

    (
        _regular_count,
        symlink_count,
        _loose,
        _regular_files,
        non_allowlisted_count,
        allowlist,
        non_allowlisted,
    ) = mod._top_level_file_stats()

    assert symlink_count == 2
    assert non_allowlisted_count == 1
    assert allowlist == ["keep.json"]
    assert non_allowlisted == ["drop.json"]
