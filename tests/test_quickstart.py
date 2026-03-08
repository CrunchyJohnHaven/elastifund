from __future__ import annotations

import argparse
from pathlib import Path

from scripts.quickstart import build_setup_command, ensure_env_file


def _args(**overrides):
    values = {
        "prepare_only": False,
        "env_path": ".env",
        "template_path": ".env.example",
        "runtime_manifest": "state/elastifund/runtime-manifest.json",
        "agent_name": "",
        "run_mode": "paper",
        "disable_trading": False,
        "disable_digital_products": False,
        "hub_url": "",
        "hub_external_url": "",
        "hub_bootstrap_token": "",
        "hub_registry_path": "",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_ensure_env_file_copies_template_once(tmp_path: Path):
    template = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    template.write_text("HELLO=world\n")

    created = ensure_env_file(env_path, template)

    assert created is True
    assert env_path.read_text() == "HELLO=world\n"

    env_path.write_text("HELLO=override\n")
    created_again = ensure_env_file(env_path, template)

    assert created_again is False
    assert env_path.read_text() == "HELLO=override\n"


def test_build_setup_command_for_remote_joiner():
    command = build_setup_command(
        _args(
            agent_name="peer-spoke",
            run_mode="live",
            disable_trading=True,
            hub_url="https://hub.example.com",
            hub_external_url="https://hub.example.com",
            hub_bootstrap_token="shared-token",
            hub_registry_path="state/shared/registry.json",
        )
    )

    assert command[1:4] == ["scripts/elastifund_setup.py", "--non-interactive", "--env-path"]
    assert "--agent-name" in command
    assert "--disable-trading" in command
    assert "--hub-url" in command
    assert "--hub-external-url" in command
    assert "--hub-bootstrap-token" in command
    assert "--hub-registry-path" in command
