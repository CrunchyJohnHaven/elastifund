from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _build_temp_project(tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "bot").mkdir()
    (project / "config").mkdir()

    shutil.copy2(
        repo_root / "scripts" / "clean_env_for_profile.sh",
        project / "scripts" / "clean_env_for_profile.sh",
    )
    shutil.copy2(
        repo_root / "bot" / "runtime_profile.py",
        project / "bot" / "runtime_profile.py",
    )
    shutil.copy2(
        repo_root / "config" / "__init__.py",
        project / "config" / "__init__.py",
    )
    shutil.copy2(
        repo_root / "config" / "runtime_profile.py",
        project / "config" / "runtime_profile.py",
    )
    shutil.copytree(
        repo_root / "config" / "runtime_profiles",
        project / "config" / "runtime_profiles",
    )

    return project


def _run_helper(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(project / "scripts" / "clean_env_for_profile.sh"), *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )


def test_clean_env_helper_strips_runtime_overrides_and_preserves_secrets(tmp_path: Path) -> None:
    project = _build_temp_project(tmp_path)
    original_env = "\n".join(
        [
            "# operator settings",
            "POLYMARKET_API_KEY=keep-me",
            "export TELEGRAM_BOT_TOKEN=telegram-secret",
            "PROXY_ADDRESS=0xproxy",
            "SAFE_ADDRESS=0xsafe",
            "FUNDER_WALLET=0xfunder",
            "PASSPHRASE=topsecret",
            "OTHER_SETTING=keep-this-too",
            "PAPER_TRADING = false",
            "LIVE_TRADING=true",
            "export ENABLE_WALLET_FLOW=true",
            "JJ_MAX_POSITION_USD=99",
            "JJ_RUNTIME_PROFILE=blocked_safe",
            "CLAUDE_MODEL=claude-3-7-sonnet",
            "ELASTIFUND_AGENT_RUN_MODE=live",
            "",
        ]
    )
    (project / ".env").write_text(original_env)

    result = _run_helper(project, "paper_aggressive")

    cleaned_env = (project / ".env").read_text()
    backup_files = list(project.glob(".env.backup.*"))

    assert len(backup_files) == 1
    assert backup_files[0].read_text() == original_env

    assert "POLYMARKET_API_KEY=keep-me" in cleaned_env
    assert "export TELEGRAM_BOT_TOKEN=telegram-secret" in cleaned_env
    assert "PROXY_ADDRESS=0xproxy" in cleaned_env
    assert "SAFE_ADDRESS=0xsafe" in cleaned_env
    assert "FUNDER_WALLET=0xfunder" in cleaned_env
    assert "PASSPHRASE=topsecret" in cleaned_env
    assert "OTHER_SETTING=keep-this-too" in cleaned_env

    assert "PAPER_TRADING" not in cleaned_env
    assert "LIVE_TRADING" not in cleaned_env
    assert "ENABLE_WALLET_FLOW" not in cleaned_env
    assert "JJ_MAX_POSITION_USD" not in cleaned_env
    assert "CLAUDE_MODEL" not in cleaned_env
    assert "ELASTIFUND_AGENT_RUN_MODE" not in cleaned_env
    assert cleaned_env.count("JJ_RUNTIME_PROFILE=") == 1
    assert cleaned_env.rstrip().endswith("JJ_RUNTIME_PROFILE=paper_aggressive")

    assert "JJ_RUNTIME_PROFILE=paper_aggressive" in result.stdout
    assert "Verification:" in result.stdout
    assert "Profile: paper_aggressive" in result.stdout
    assert "YES threshold: 0.08" in result.stdout
    assert "NO threshold: 0.03" in result.stdout
    assert "Paper trading: True" in result.stdout


def test_clean_env_helper_defaults_to_live_aggressive(tmp_path: Path) -> None:
    project = _build_temp_project(tmp_path)
    (project / ".env").write_text(
        "\n".join(
            [
                "API_KEY=keep-me",
                "JJ_RUNTIME_PROFILE=blocked_safe",
                "PAPER_TRADING=false",
                "",
            ]
        )
    )

    result = _run_helper(project)
    cleaned_env = (project / ".env").read_text()

    assert "API_KEY=keep-me" in cleaned_env
    assert "PAPER_TRADING" not in cleaned_env
    assert cleaned_env.count("JJ_RUNTIME_PROFILE=") == 1
    assert cleaned_env.rstrip().endswith("JJ_RUNTIME_PROFILE=live_aggressive")
    assert "Profile: live_aggressive" in result.stdout
