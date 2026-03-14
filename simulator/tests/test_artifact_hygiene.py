from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


def test_simulator_output_has_no_tracked_temp_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / ".git").exists():
        pytest.skip("git metadata unavailable")
    if shutil.which("git") is None:
        pytest.skip("git command unavailable")

    result = subprocess.run(
        ["git", "ls-files", "simulator/output"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    tracked_paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    banned = [
        path
        for path in tracked_paths
        if (repo_root / path).exists()
        and (
            Path(path).name.startswith("_tmp_config")
            or Path(path).name.startswith("sim_config_override_")
            or Path(path).name.endswith(".tmp")
        )
    ]
    assert not banned, f"Tracked simulator temp artifacts found: {banned}"
