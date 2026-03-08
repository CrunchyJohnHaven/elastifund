from __future__ import annotations

import argparse

from scripts.elastifund_setup import DEFAULT_NONPROFIT, build_answers


def _args(**overrides):
    values = {
        "agent_name": "",
        "run_mode": "paper",
        "disable_trading": False,
        "disable_digital_products": False,
        "hub_url": "",
        "hub_external_url": "",
        "hub_bootstrap_token": "",
        "hub_registry_path": "",
        "llm_provider": "anthropic",
        "initial_capital_usd": 250,
        "trading_capital_pct": 70,
        "digital_capital_pct": 30,
        "anthropic_api_key": "",
        "openai_api_key": "",
        "polymarket_api_key": "",
        "polymarket_api_secret": "",
        "polymarket_api_passphrase": "",
        "polymarket_funder": "",
        "polymarket_pk": "",
        "kalshi_api_key_id": "",
        "kalshi_rsa_key_path": "kalshi/kalshi_rsa_private.pem",
        "etsy_api_key": "",
        "etsy_shop_id": "",
        "nonprofit": DEFAULT_NONPROFIT,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_build_answers_uses_remote_hub_url_as_external_url_when_flag_set():
    answers = build_answers(
        _args(hub_url="https://hub.example.com"),
        {"ELASTIFUND_HUB_EXTERNAL_URL": "http://localhost:8080"},
    )

    assert answers.hub_url == "https://hub.example.com"
    assert answers.hub_external_url == "https://hub.example.com"


def test_build_answers_preserves_existing_hub_values_without_flags():
    answers = build_answers(
        _args(),
        {
            "ELASTIFUND_AGENT_NAME": "saved-agent",
            "ELASTIFUND_HUB_URL": "https://saved-hub.example.com",
            "ELASTIFUND_HUB_EXTERNAL_URL": "https://saved-hub.example.com",
            "ELASTIFUND_HUB_BOOTSTRAP_TOKEN": "saved-token",
            "ELASTIFUND_HUB_REGISTRY_PATH": "state/shared/registry.json",
        },
    )

    assert answers.agent_name == "saved-agent"
    assert answers.hub_url == "https://saved-hub.example.com"
    assert answers.hub_external_url == "https://saved-hub.example.com"
    assert answers.hub_bootstrap_token == "saved-token"
    assert answers.hub_registry_path == "state/shared/registry.json"
