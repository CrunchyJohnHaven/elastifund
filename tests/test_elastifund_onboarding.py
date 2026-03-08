from pathlib import Path

from shared.python.envfile import load_env_file, write_env_file
from shared.python.onboarding import OnboardingAnswers, build_env_updates, build_runtime_manifest


def test_build_env_updates_generates_identity_and_normalizes_split():
    answers = OnboardingAnswers(
        agent_name="Revenue Pod",
        trading_capital_pct=8,
        digital_capital_pct=2,
    )

    updates = build_env_updates({}, answers)

    assert updates["ELASTIFUND_AGENT_ID"].startswith("elastifund-revenue-pod-")
    assert updates["ELASTIFUND_AGENT_SECRET"]
    assert updates["ELASTIFUND_HUB_BOOTSTRAP_TOKEN"]
    assert updates["ELASTIFUND_TRADING_CAPITAL_PCT"] == "80"
    assert updates["ELASTIFUND_DIGITAL_CAPITAL_PCT"] == "20"


def test_build_env_updates_replaces_template_security_defaults():
    answers = OnboardingAnswers(agent_name="Host Hub")

    updates = build_env_updates(
        {
            "ELASTIFUND_HUB_BOOTSTRAP_TOKEN": "local-bootstrap-token",
            "ELASTIC_PASSWORD": "change-this-elastic-password",
            "KIBANA_ENCRYPTION_KEY": "replace-with-a-32-char-minimum-key",
        },
        answers,
    )

    assert updates["ELASTIFUND_HUB_BOOTSTRAP_TOKEN"] != "local-bootstrap-token"
    assert updates["ELASTIC_PASSWORD"] != "change-this-elastic-password"
    assert updates["KIBANA_ENCRYPTION_KEY"] != "replace-with-a-32-char-minimum-key"
    assert len(updates["KIBANA_ENCRYPTION_KEY"]) >= 32


def test_build_env_updates_accepts_remote_hub_overrides():
    answers = OnboardingAnswers(
        agent_name="Peer Spoke",
        hub_url="https://hub.example.com",
        hub_external_url="https://hub.example.com",
        hub_bootstrap_token="shared-secret-token",
        hub_registry_path="state/shared/registry.json",
    )

    updates = build_env_updates({}, answers)

    assert updates["ELASTIFUND_HUB_URL"] == "https://hub.example.com"
    assert updates["ELASTIFUND_HUB_EXTERNAL_URL"] == "https://hub.example.com"
    assert updates["ELASTIFUND_HUB_BOOTSTRAP_TOKEN"] == "shared-secret-token"
    assert updates["ELASTIFUND_HUB_REGISTRY_PATH"] == "state/shared/registry.json"


def test_build_env_updates_uses_remote_hub_url_as_share_url_when_not_provided():
    answers = OnboardingAnswers(
        agent_name="Peer Spoke",
        hub_url="https://hub.example.com",
    )

    updates = build_env_updates({}, answers)

    assert updates["ELASTIFUND_HUB_EXTERNAL_URL"] == "https://hub.example.com"


def test_write_env_file_appends_missing_onboarding_values(tmp_path: Path):
    template = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    template.write_text("PAPER_TRADING=true\n")

    write_env_file(
        env_path,
        template,
        {
            "ELASTIFUND_AGENT_NAME": "local-bootstrap",
            "ELASTIFUND_AGENT_ID": "elastifund-local-bootstrap-abc123",
        },
    )

    env = load_env_file(env_path)
    manifest = build_runtime_manifest(env)

    assert env["ELASTIFUND_AGENT_NAME"] == "local-bootstrap"
    assert manifest["agent"]["id"] == "elastifund-local-bootstrap-abc123"
