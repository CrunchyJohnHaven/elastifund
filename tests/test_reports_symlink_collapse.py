from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "reports" / "tools" / "collapse_top_level_symlinks.py"
    spec = importlib.util.spec_from_file_location("collapse_top_level_symlinks", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_load_allowlist_from_policy(tmp_path: Path):
    mod = _load_module()
    reports = tmp_path / "reports"
    reports.mkdir()
    policy = reports / "retention_policy.json"
    policy.write_text(
        json.dumps(
            {
                "top_level_symlink_allowlist": [
                    "jjn_public_report.json",
                    " jjn_public_report.json ",
                    "runtime_truth_latest.json",
                ]
            }
        ),
        encoding="utf-8",
    )

    mod.POLICY_PATH = policy
    assert mod.load_allowlist() == {"jjn_public_report.json", "runtime_truth_latest.json"}


def test_collapse_tool_keeps_allowlisted_symlink_and_removes_others(tmp_path: Path):
    reports = tmp_path / "reports"
    tools = reports / "tools"
    tools.mkdir(parents=True)
    (reports / "target.json").write_text("{}", encoding="utf-8")
    (reports / "legacy.json").write_text("{}", encoding="utf-8")
    (reports / "jjn_public_report.json").symlink_to("target.json")
    (reports / "old_alias.json").symlink_to("legacy.json")
    (reports / "retention_policy.json").write_text(
        json.dumps({"top_level_symlink_allowlist": ["jjn_public_report.json"]}),
        encoding="utf-8",
    )

    script_src = (
        Path(__file__).resolve().parents[1] / "reports" / "tools" / "collapse_top_level_symlinks.py"
    )
    script_dst = tools / "collapse_top_level_symlinks.py"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    cmd = [sys.executable, str(script_dst), "--apply"]
    subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True, text=True)

    assert (reports / "jjn_public_report.json").is_symlink()
    assert not (reports / "old_alias.json").exists()
