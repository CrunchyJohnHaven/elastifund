"""Helpers for the fork-and-run setup wizard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from bot.kalshi_auth import load_kalshi_credentials
from .envfile import is_placeholder_value
from .identity import generate_agent_id, generate_secret
from .runtime import utc_now


@dataclass(frozen=True)
class OnboardingAnswers:
    agent_name: str
    run_mode: str = "paper"
    enable_trading: bool = True
    enable_digital_products: bool = True
    hub_url: str = ""
    hub_external_url: str = ""
    hub_bootstrap_token: str = ""
    hub_registry_path: str = ""
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    polymarket_funder: str = ""
    polymarket_pk: str = ""
    kalshi_api_key_id: str = ""
    kalshi_rsa_key_path: str = "kalshi/kalshi_rsa_private.pem"
    kalshi_rsa_private_key: str = ""
    kalshi_rsa_private_key_b64: str = ""
    etsy_api_key: str = ""
    etsy_shop_id: str = ""
    nonprofit: str = "veteran-suicide-prevention"
    initial_capital_usd: int = 250
    trading_capital_pct: int = 70
    digital_capital_pct: int = 30


def build_env_updates(existing_env: Mapping[str, str], answers: OnboardingAnswers) -> dict[str, str]:
    trading_pct, digital_pct = _normalize_split(
        answers.trading_capital_pct,
        answers.digital_capital_pct,
    )
    agent_id = _existing_or_generated(existing_env, "ELASTIFUND_AGENT_ID", answers.agent_name, generate_agent_id)
    agent_secret = _existing_or_generated(existing_env, "ELASTIFUND_AGENT_SECRET", "", lambda _: generate_secret(24))
    hub_url = answers.hub_url or existing_env.get("ELASTIFUND_HUB_URL", "http://hub-gateway:8080")
    hub_external_url = answers.hub_external_url or (
        answers.hub_url
        if answers.hub_url
        else existing_env.get("ELASTIFUND_HUB_EXTERNAL_URL", "http://localhost:8080")
    )
    hub_token = answers.hub_bootstrap_token
    if not hub_token or is_placeholder_value(hub_token):
        hub_token = _existing_or_generated(
            existing_env,
            "ELASTIFUND_HUB_BOOTSTRAP_TOKEN",
            "",
            lambda _: generate_secret(18),
        )
    hub_registry_path = answers.hub_registry_path or existing_env.get(
        "ELASTIFUND_HUB_REGISTRY_PATH",
        "state/elastifund/registry.json",
    )
    elastic_password = _existing_or_generated(
        existing_env,
        "ELASTIC_PASSWORD",
        "",
        lambda _: generate_secret(18),
    )
    kibana_encryption_key = _existing_or_generated(
        existing_env,
        "KIBANA_ENCRYPTION_KEY",
        "",
        lambda _: generate_secret(24),
    )

    updates = {
        "ELASTIFUND_PROFILE": existing_env.get("ELASTIFUND_PROFILE", "local"),
        "ELASTIFUND_AGENT_NAME": answers.agent_name,
        "ELASTIFUND_AGENT_ID": agent_id,
        "ELASTIFUND_AGENT_SECRET": agent_secret,
        "ELASTIFUND_HUB_URL": hub_url,
        "ELASTIFUND_HUB_EXTERNAL_URL": hub_external_url,
        "ELASTIFUND_HUB_BOOTSTRAP_TOKEN": hub_token,
        "ELASTIFUND_HUB_REGISTRY_PATH": hub_registry_path,
        "ELASTIFUND_ENABLE_TRADING": _bool_text(answers.enable_trading),
        "ELASTIFUND_ENABLE_DIGITAL_PRODUCTS": _bool_text(answers.enable_digital_products),
        "ELASTIFUND_AGENT_RUN_MODE": answers.run_mode,
        "ELASTIFUND_LLM_PROVIDER": answers.llm_provider,
        "ELASTIFUND_NONPROFIT": answers.nonprofit,
        "ELASTIFUND_DONATION_PERCENT": existing_env.get("ELASTIFUND_DONATION_PERCENT", "20"),
        "ELASTIFUND_INITIAL_CAPITAL_USD": str(answers.initial_capital_usd),
        "ELASTIFUND_TRADING_CAPITAL_PCT": str(trading_pct),
        "ELASTIFUND_DIGITAL_CAPITAL_PCT": str(digital_pct),
        "ELASTIFUND_AGENT_HEARTBEAT_SECONDS": existing_env.get("ELASTIFUND_AGENT_HEARTBEAT_SECONDS", "60"),
        "ELASTIC_VERSION": existing_env.get("ELASTIC_VERSION", "8.15.5"),
        "ELASTIC_PASSWORD": elastic_password,
        "KIBANA_ENCRYPTION_KEY": kibana_encryption_key,
        "ELASTIFUND_ELASTICSEARCH_HOST": existing_env.get("ELASTIFUND_ELASTICSEARCH_HOST", "elasticsearch"),
        "ELASTIFUND_ELASTICSEARCH_PORT": existing_env.get("ELASTIFUND_ELASTICSEARCH_PORT", "9200"),
        "ELASTIFUND_KIBANA_HOST": existing_env.get("ELASTIFUND_KIBANA_HOST", "kibana"),
        "ELASTIFUND_KIBANA_PORT": existing_env.get("ELASTIFUND_KIBANA_PORT", "5601"),
        "ELASTIFUND_KAFKA_HOST": existing_env.get("ELASTIFUND_KAFKA_HOST", "kafka"),
        "ELASTIFUND_KAFKA_PORT": existing_env.get("ELASTIFUND_KAFKA_PORT", "9092"),
        "ELASTIFUND_REDIS_HOST": existing_env.get("ELASTIFUND_REDIS_HOST", "redis"),
        "ELASTIFUND_REDIS_PORT": existing_env.get("ELASTIFUND_REDIS_PORT", "6379"),
        "ANTHROPIC_API_KEY": answers.anthropic_api_key or existing_env.get("ANTHROPIC_API_KEY", ""),
        "OPENAI_API_KEY": answers.openai_api_key or existing_env.get("OPENAI_API_KEY", ""),
        "POLYMARKET_API_KEY": answers.polymarket_api_key or existing_env.get("POLYMARKET_API_KEY", ""),
        "POLYMARKET_API_SECRET": answers.polymarket_api_secret or existing_env.get("POLYMARKET_API_SECRET", ""),
        "POLYMARKET_API_PASSPHRASE": answers.polymarket_api_passphrase
        or existing_env.get("POLYMARKET_API_PASSPHRASE", ""),
        "POLYMARKET_FUNDER": answers.polymarket_funder or existing_env.get("POLYMARKET_FUNDER", ""),
        "POLYMARKET_PK": answers.polymarket_pk or existing_env.get("POLYMARKET_PK", ""),
        "KALSHI_API_KEY_ID": answers.kalshi_api_key_id or existing_env.get("KALSHI_API_KEY_ID", ""),
        "KALSHI_RSA_KEY_PATH": answers.kalshi_rsa_key_path or existing_env.get("KALSHI_RSA_KEY_PATH", ""),
        "KALSHI_RSA_PRIVATE_KEY": answers.kalshi_rsa_private_key or existing_env.get("KALSHI_RSA_PRIVATE_KEY", ""),
        "KALSHI_RSA_PRIVATE_KEY_B64": answers.kalshi_rsa_private_key_b64 or existing_env.get("KALSHI_RSA_PRIVATE_KEY_B64", ""),
        "ETSY_API_KEY": answers.etsy_api_key or existing_env.get("ETSY_API_KEY", ""),
        "ETSY_SHOP_ID": answers.etsy_shop_id or existing_env.get("ETSY_SHOP_ID", ""),
    }
    return updates


def build_runtime_manifest(env: Mapping[str, str]) -> dict[str, object]:
    kalshi_credentials = load_kalshi_credentials(env)
    return {
        "generated_at": utc_now(),
        "agent": {
            "name": env.get("ELASTIFUND_AGENT_NAME", ""),
            "id": env.get("ELASTIFUND_AGENT_ID", ""),
            "profile": env.get("ELASTIFUND_PROFILE", "local"),
            "run_mode": env.get("ELASTIFUND_AGENT_RUN_MODE", "paper"),
        },
        "hub": {
            "url": env.get("ELASTIFUND_HUB_URL", "http://hub-gateway:8080"),
            "external_url": env.get("ELASTIFUND_HUB_EXTERNAL_URL", "http://localhost:8080"),
            "registry_path": env.get("ELASTIFUND_HUB_REGISTRY_PATH", "state/elastifund/registry.json"),
            "bootstrap_token_present": not is_placeholder_value(env.get("ELASTIFUND_HUB_BOOTSTRAP_TOKEN", "")),
        },
        "capabilities": {
            "trading": env.get("ELASTIFUND_ENABLE_TRADING", "true").lower() == "true",
            "digital_products": env.get("ELASTIFUND_ENABLE_DIGITAL_PRODUCTS", "true").lower() == "true",
        },
        "integrations": {
            "polymarket_configured": _configured(
                env,
                "POLYMARKET_API_KEY",
                "POLYMARKET_API_SECRET",
                "POLYMARKET_API_PASSPHRASE",
                "POLYMARKET_FUNDER",
                "POLYMARKET_PK",
            ),
            "kalshi_configured": kalshi_credentials.configured,
            "etsy_configured": _configured(env, "ETSY_API_KEY", "ETSY_SHOP_ID"),
            "anthropic_configured": _configured(env, "ANTHROPIC_API_KEY"),
            "openai_configured": _configured(env, "OPENAI_API_KEY"),
            "llm_provider": env.get("ELASTIFUND_LLM_PROVIDER", "anthropic"),
        },
        "allocation": {
            "initial_capital_usd": int(env.get("ELASTIFUND_INITIAL_CAPITAL_USD", "250") or 250),
            "trading_pct": int(env.get("ELASTIFUND_TRADING_CAPITAL_PCT", "70") or 70),
            "digital_products_pct": int(env.get("ELASTIFUND_DIGITAL_CAPITAL_PCT", "30") or 30),
            "donation_pct": int(env.get("ELASTIFUND_DONATION_PERCENT", "20") or 20),
            "nonprofit": env.get("ELASTIFUND_NONPROFIT", "veteran-suicide-prevention"),
        },
    }


def _normalize_split(trading_pct: int, digital_pct: int) -> tuple[int, int]:
    if trading_pct < 0 or digital_pct < 0:
        raise ValueError("capital split cannot be negative")
    total = trading_pct + digital_pct
    if total == 100:
        return trading_pct, digital_pct
    if total == 0:
        return 70, 30
    normalized_trading = round((trading_pct / total) * 100)
    return normalized_trading, 100 - normalized_trading


def _existing_or_generated(
    existing_env: Mapping[str, str],
    key: str,
    seed: str,
    generator,
) -> str:
    existing = existing_env.get(key, "")
    if existing and not is_placeholder_value(existing):
        return existing
    return generator(seed)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _configured(env: Mapping[str, str], *keys: str) -> bool:
    return all(not is_placeholder_value(env.get(key, "")) for key in keys)
