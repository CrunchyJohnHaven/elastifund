"""Shared runtime settings for hub and agent services."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from os import environ
from pathlib import Path
from typing import Mapping


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ElastifundRuntimeSettings:
    profile: str = "local"
    agent_name: str = "local-bootstrap"
    agent_id: str = ""
    agent_secret: str = ""
    hub_url: str = "http://hub-gateway:8080"
    hub_external_url: str = "http://localhost:8080"
    hub_bootstrap_token: str = "local-bootstrap-token"
    hub_registry_path: Path = Path("state/elastifund/registry.json")
    enable_trading: bool = True
    enable_digital_products: bool = True
    run_mode: str = "paper"
    llm_provider: str = "anthropic"
    donation_percent: int = 20
    nonprofit: str = "veteran-suicide-prevention"
    initial_capital_usd: int = 250
    trading_capital_pct: int = 70
    digital_capital_pct: int = 30
    heartbeat_seconds: int = 60
    elasticsearch_host: str = "elasticsearch"
    elasticsearch_port: int = 9200
    kibana_host: str = "kibana"
    kibana_port: int = 5601
    kafka_host: str = "kafka"
    kafka_port: int = 9092
    redis_host: str = "redis"
    redis_port: int = 6379

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ElastifundRuntimeSettings":
        values = environ if env is None else env
        return cls(
            profile=values.get("ELASTIFUND_PROFILE", "local"),
            agent_name=values.get("ELASTIFUND_AGENT_NAME", "local-bootstrap"),
            agent_id=values.get("ELASTIFUND_AGENT_ID", ""),
            agent_secret=values.get("ELASTIFUND_AGENT_SECRET", ""),
            hub_url=values.get("ELASTIFUND_HUB_URL", "http://hub-gateway:8080"),
            hub_external_url=values.get("ELASTIFUND_HUB_EXTERNAL_URL", "http://localhost:8080"),
            hub_bootstrap_token=values.get("ELASTIFUND_HUB_BOOTSTRAP_TOKEN", "local-bootstrap-token"),
            hub_registry_path=Path(values.get("ELASTIFUND_HUB_REGISTRY_PATH", "state/elastifund/registry.json")),
            enable_trading=parse_bool(values.get("ELASTIFUND_ENABLE_TRADING"), True),
            enable_digital_products=parse_bool(values.get("ELASTIFUND_ENABLE_DIGITAL_PRODUCTS"), True),
            run_mode=values.get("ELASTIFUND_AGENT_RUN_MODE", "paper"),
            llm_provider=values.get("ELASTIFUND_LLM_PROVIDER", "anthropic"),
            donation_percent=parse_int(values.get("ELASTIFUND_DONATION_PERCENT"), 20),
            nonprofit=values.get("ELASTIFUND_NONPROFIT", "veteran-suicide-prevention"),
            initial_capital_usd=parse_int(values.get("ELASTIFUND_INITIAL_CAPITAL_USD"), 250),
            trading_capital_pct=parse_int(values.get("ELASTIFUND_TRADING_CAPITAL_PCT"), 70),
            digital_capital_pct=parse_int(values.get("ELASTIFUND_DIGITAL_CAPITAL_PCT"), 30),
            heartbeat_seconds=parse_int(values.get("ELASTIFUND_AGENT_HEARTBEAT_SECONDS"), 60),
            elasticsearch_host=values.get("ELASTIFUND_ELASTICSEARCH_HOST", "elasticsearch"),
            elasticsearch_port=parse_int(values.get("ELASTIFUND_ELASTICSEARCH_PORT"), 9200),
            kibana_host=values.get("ELASTIFUND_KIBANA_HOST", "kibana"),
            kibana_port=parse_int(values.get("ELASTIFUND_KIBANA_PORT"), 5601),
            kafka_host=values.get("ELASTIFUND_KAFKA_HOST", "kafka"),
            kafka_port=parse_int(values.get("ELASTIFUND_KAFKA_PORT"), 9092),
            redis_host=values.get("ELASTIFUND_REDIS_HOST", "redis"),
            redis_port=parse_int(values.get("ELASTIFUND_REDIS_PORT"), 6379),
        )

    def capabilities(self) -> dict[str, bool]:
        return {
            "trading": self.enable_trading,
            "digital_products": self.enable_digital_products,
        }

    def allocation(self) -> dict[str, int]:
        return {
            "total_usd": self.initial_capital_usd,
            "trading_pct": self.trading_capital_pct,
            "digital_products_pct": self.digital_capital_pct,
            "donation_pct": self.donation_percent,
        }
