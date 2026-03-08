"""Preflight and runtime health checks for the onboarding flow."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Mapping

from .envfile import is_placeholder_value
from .runtime import ElastifundRuntimeSettings


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str


def run_preflight_checks(
    settings: ElastifundRuntimeSettings,
    env: Mapping[str, str],
) -> list[HealthCheck]:
    checks = [
        _status(
            "agent_identity",
            bool(settings.agent_id and settings.agent_secret),
            f"agent_id={settings.agent_id or 'missing'}",
        ),
        _status(
            "hub_bootstrap_token",
            not is_placeholder_value(settings.hub_bootstrap_token),
            "bootstrap token configured",
        ),
        _status(
            "capital_split",
            settings.trading_capital_pct + settings.digital_capital_pct == 100,
            (
                f"trading={settings.trading_capital_pct}% "
                f"digital={settings.digital_capital_pct}%"
            ),
        ),
    ]

    if settings.enable_trading:
        trading_live_ready = _configured(
            env,
            "POLYMARKET_API_KEY",
            "POLYMARKET_API_SECRET",
            "POLYMARKET_API_PASSPHRASE",
            "POLYMARKET_FUNDER",
            "POLYMARKET_PK",
        )
        checks.append(
            _warnable(
                "trading_credentials",
                trading_live_ready,
                settings.run_mode == "paper",
                "Polymarket credentials configured" if trading_live_ready else "Polymarket credentials still placeholder",
            )
        )
    else:
        checks.append(HealthCheck("trading_lane", "skip", "trading lane disabled"))

    if settings.enable_digital_products:
        etsy_ready = _configured(env, "ETSY_API_KEY", "ETSY_SHOP_ID")
        llm_ready = _configured(env, "ANTHROPIC_API_KEY") or _configured(env, "OPENAI_API_KEY")
        checks.append(
            _warnable(
                "digital_products",
                etsy_ready and llm_ready,
                settings.run_mode == "paper",
                "Etsy plus LLM credentials configured"
                if etsy_ready and llm_ready
                else "Etsy and/or LLM credentials still placeholder",
            )
        )
    else:
        checks.append(HealthCheck("digital_products", "skip", "digital products lane disabled"))

    return checks


def run_runtime_dependency_checks(settings: ElastifundRuntimeSettings) -> list[HealthCheck]:
    return [
        _tcp_check("elasticsearch", settings.elasticsearch_host, settings.elasticsearch_port),
        _tcp_check("kibana", settings.kibana_host, settings.kibana_port),
        _tcp_check("kafka", settings.kafka_host, settings.kafka_port),
        _tcp_check("redis", settings.redis_host, settings.redis_port),
    ]


def format_checks(checks: list[HealthCheck]) -> str:
    width = max((len(check.name) for check in checks), default=10)
    lines = []
    for check in checks:
        lines.append(f"{check.name.ljust(width)}  {check.status.upper():<5}  {check.detail}")
    return "\n".join(lines)


def _tcp_check(name: str, host: str, port: int) -> HealthCheck:
    try:
        with socket.create_connection((host, port), timeout=1):
            return HealthCheck(name, "pass", f"reachable at {host}:{port}")
    except OSError as exc:
        return HealthCheck(name, "fail", f"{host}:{port} unreachable ({exc.__class__.__name__})")


def _configured(env: Mapping[str, str], *keys: str) -> bool:
    return all(not is_placeholder_value(env.get(key, "")) for key in keys)


def _status(name: str, ok: bool, detail: str) -> HealthCheck:
    return HealthCheck(name, "pass" if ok else "fail", detail)


def _warnable(name: str, ok: bool, allow_warn: bool, detail: str) -> HealthCheck:
    if ok:
        return HealthCheck(name, "pass", detail)
    if allow_warn:
        return HealthCheck(name, "warn", detail)
    return HealthCheck(name, "fail", detail)
