"""Tests for the optional Elastic telemetry bridge."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from src.core.config import Settings
from src.telemetry.elastic import ElasticTelemetry


def _settings(**overrides) -> Settings:
    defaults = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "elastic_telemetry_enabled": True,
        "elasticsearch_url": "http://localhost:9200",
        "elasticsearch_username": "elastic",
        "elasticsearch_password": "changeme",
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_upsert_agent_status_writes_expected_document():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"result": "updated"})

    telemetry = ElasticTelemetry(
        _settings(
            elasticsearch_api_key="id:api-key",
            elasticsearch_username="",
            elasticsearch_password="",
        ),
        transport=httpx.MockTransport(handler),
    )

    ok = await telemetry.upsert_agent_status(
        status="running",
        metadata={"mode": "paper"},
    )

    assert ok is True
    assert captured["method"] == "PUT"
    assert captured["path"] == "/elastifund-agents/_doc/polymarket-bot"
    assert captured["payload"]["status"] == "running"
    assert captured["payload"]["metadata"]["mode"] == "paper"
    assert captured["auth"] == (
        "ApiKey " + base64.b64encode(b"id:api-key").decode("ascii")
    )


@pytest.mark.asyncio
async def test_emit_metrics_posts_to_metrics_stream():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json={"result": "created"})

    telemetry = ElasticTelemetry(
        _settings(),
        transport=httpx.MockTransport(handler),
    )

    ok = await telemetry.emit_metrics(
        strategy_id="smacross-5-20",
        pnl_usd=1.25,
        drawdown_pct=0.0,
        revenue_usd=1.25,
        sharpe_ratio=0.0,
        cost_usd=0.05,
    )

    assert ok is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/elastifund-metrics/_doc"
    assert captured["payload"]["agent_id"] == "polymarket-bot"
    assert captured["payload"]["strategy_id"] == "smacross-5-20"
    assert captured["payload"]["venue"] == "polymarket"
    assert captured["payload"]["pnl_usd"] == 1.25


@pytest.mark.asyncio
async def test_emit_trade_writes_trade_snapshot():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"result": "updated"})

    telemetry = ElasticTelemetry(
        _settings(),
        transport=httpx.MockTransport(handler),
    )

    ok = await telemetry.emit_trade(
        trade_id="trade-123",
        strategy_id="smacross-5-20",
        market_id="market-1",
        side="BUY",
        order_type="LIMIT",
        status="FILLED",
        price=0.42,
        size=10,
        metadata={"mode": "paper"},
    )

    assert ok is True
    assert captured["method"] == "PUT"
    assert captured["path"] == "/elastifund-trades/_doc/trade-123"
    assert captured["payload"]["trade_id"] == "trade-123"
    assert captured["payload"]["notional_usd"] == 4.2
    assert captured["payload"]["metadata"]["mode"] == "paper"


@pytest.mark.asyncio
async def test_ping_failure_is_fail_open_and_visible_in_snapshot():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cluster down", request=request)

    telemetry = ElasticTelemetry(
        _settings(),
        transport=httpx.MockTransport(handler),
    )

    ok = await telemetry.ping()

    assert ok is False
    snapshot = telemetry.snapshot()
    assert snapshot["reachable"] is False
    assert "cluster down" in snapshot["last_error"]


def test_strategy_id_is_normalized_for_tsds_dimensions():
    telemetry = ElasticTelemetry(_settings())

    assert telemetry.resolve_strategy_id("SMACross(5,20)") == "smacross-5-20"
