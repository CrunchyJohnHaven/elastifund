from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "reports" / "tools" / "collapse_top_level_symlinks.py"
    spec = importlib.util.spec_from_file_location("collapse_top_level_symlinks", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_prune_keeps_allowlisted_symlink_and_removes_other(tmp_path: Path) -> None:
    mod = _load_module()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)

    target = reports_dir / "runtime"
    target.mkdir()
    (target / "keep_me.json").write_text("{}", encoding="utf-8")
    (target / "drop_me.json").write_text("{}", encoding="utf-8")
    (reports_dir / "keep_me.json").symlink_to("runtime/keep_me.json")
    (reports_dir / "drop_me.json").symlink_to("runtime/drop_me.json")

    dry_run = mod.collapse_symlinks(reports_dir=reports_dir, allowlist={"keep_me.json"}, apply=False)
    assert dry_run["top_level_symlink_total"] == 2
    assert dry_run["kept"] == ["keep_me.json"]
    assert dry_run["removed"] == ["drop_me.json"]
    assert (reports_dir / "drop_me.json").is_symlink()

    apply = mod.collapse_symlinks(reports_dir=reports_dir, allowlist={"keep_me.json"}, apply=True)
    assert apply["top_level_symlink_removed_or_planned"] == 1
    assert (reports_dir / "keep_me.json").is_symlink()
    assert not (reports_dir / "drop_me.json").exists()
