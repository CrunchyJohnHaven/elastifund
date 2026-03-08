from __future__ import annotations

import socket
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from hub.app.agent_api import router as agent_router
from hub.app.benchmark_api import router as benchmark_router
from hub.app.config import get_settings
from hub.app.elasticsearch_security import ElasticsearchSecurityClient
from hub.app.flywheel_api import router as flywheel_router
from hub.app.registry import HubRegistry
from shared.python.elastifund_shared.topology import (
    ELASTIFUND_KNOWLEDGE_SHARING_TIERS,
    ELASTIFUND_PRIVATE_BOUNDARY,
)
from shared.python.runtime import ElastifundRuntimeSettings

settings = get_settings()
es_security = ElasticsearchSecurityClient(
    base_url=settings.elasticsearch_url,
    username=settings.elasticsearch_username,
    password=settings.elasticsearch_password,
    verify_certs=settings.elasticsearch_verify_certs,
)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    summary="Gateway for the Elastifund hub-and-spoke platform scaffold.",
)
app.include_router(benchmark_router)
app.include_router(agent_router)
app.include_router(flywheel_router)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    role_descriptors: dict[str, Any] = Field(default_factory=dict)


def _tcp_check(host: str, port: int, timeout_seconds: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout_seconds):
            return True
    except OSError:
        return False


def _redis_status(redis_url: str) -> dict[str, Any]:
    parsed = urlparse(redis_url)
    host = parsed.hostname or "redis"
    port = parsed.port or 6379
    return {"ok": _tcp_check(host, port), "host": host, "port": port}


def _kafka_status(bootstrap_servers: tuple[str, ...]) -> dict[str, Any]:
    host = "kafka"
    port = 9092
    if bootstrap_servers:
        first = bootstrap_servers[0]
        if ":" in first:
            host, raw_port = first.rsplit(":", 1)
            port = int(raw_port)
        else:
            host = first
    return {"ok": _tcp_check(host, port), "host": host, "port": port}


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": settings.app_name,
        "environment": settings.environment,
        "autonomy_caveat": "Fully autonomous revenue generation remains aspirational in 2026; this scaffold is built for supervised automation.",
        "topology_endpoint": "/v1/topology",
        "health_endpoint": "/healthz",
    }


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    es_ok, es_meta = es_security.ping()
    kafka_meta = _kafka_status(settings.kafka_bootstrap_servers)
    redis_meta = _redis_status(settings.redis_url)
    registry = HubRegistry(ElastifundRuntimeSettings.from_env().hub_registry_path)
    dependencies = {
        "elasticsearch": {"ok": es_ok, **es_meta},
        "kafka": kafka_meta,
        "redis": redis_meta,
    }
    overall = "ok" if all(item["ok"] for item in dependencies.values()) else "degraded"
    return {
        "status": overall,
        "service": settings.app_name,
        "dependencies": dependencies,
        "registry": registry.summary(),
    }


@app.get("/v1/topology")
def topology() -> dict[str, Any]:
    return {
        "settings": settings.public_dict(),
        "indices": settings.default_indices,
        "topics": settings.default_topics,
        "privacy_tiers": ELASTIFUND_KNOWLEDGE_SHARING_TIERS,
        "private_boundary": ELASTIFUND_PRIVATE_BOUNDARY,
        "capability_note": "The hub stack is the coordination backbone. Trading and non-trading agents remain separate execution concerns.",
    }


@app.post("/v1/auth/api-keys")
def create_api_key(payload: ApiKeyCreateRequest) -> dict[str, Any]:
    try:
        response = es_security.create_api_key(
            name=payload.name,
            role_descriptors=payload.role_descriptors,
            metadata=payload.metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return response
