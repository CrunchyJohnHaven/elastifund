"""Optional Elasticsearch telemetry bridge for the Polymarket bot."""

from __future__ import annotations

import base64
from datetime import datetime, UTC
from typing import Any

import httpx
import structlog

from src.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_telemetry: "ElasticTelemetry | None" = None


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class ElasticTelemetry:
    """Best-effort Elastic writer for bot heartbeats, metrics, and trades."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.enabled = bool(self.settings.elastic_telemetry_enabled)
        self.reachable: bool | None = None
        self.last_error: str | None = None

    @property
    def agent_id(self) -> str:
        return self.settings.elastic_agent_id or "polymarket-bot"

    @property
    def agent_name(self) -> str:
        return self.settings.elastic_agent_name or "Polymarket Bot"

    def resolve_strategy_id(self, strategy_name: str | None = None) -> str:
        if self.settings.elastic_strategy_id:
            return self.settings.elastic_strategy_id
        if not strategy_name:
            return "default"
        normalized = []
        for char in strategy_name.lower():
            if char.isalnum():
                normalized.append(char)
            elif char in {" ", "-", "_", ",", "(", ")"}:
                normalized.append("-")
        value = "".join(normalized).strip("-")
        while "--" in value:
            value = value.replace("--", "-")
        return value or "default"

    async def ping(self) -> bool:
        """Check whether Elasticsearch is reachable."""
        if not self.enabled:
            return False
        response = await self._request("GET", "/")
        return response is not None

    async def upsert_agent_status(
        self,
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Write the current bot status to the shared agent alias."""
        if not self.enabled:
            return False
        payload = {
            "agent_id": self.agent_id,
            "agent_type": self.settings.elastic_agent_type,
            "status": status,
            "runtime": "polymarket-bot",
            "stake_weight": 1.0,
            "verified_return": 0.0,
            "capabilities": [
                "trading",
                "risk_controls",
                "dashboard_api",
                "elastic_telemetry",
            ],
            "heartbeat_at": _utcnow(),
            "registered_at": _utcnow(),
            "last_model_sync_at": _utcnow(),
            "metadata": {
                "agent_name": self.agent_name,
                **(metadata or {}),
            },
        }
        response = await self._request(
            "PUT",
            f"/{self.settings.elastic_agents_alias}/_doc/{self.agent_id}",
            payload,
        )
        return response is not None

    async def emit_metrics(
        self,
        *,
        strategy_id: str,
        pnl_usd: float,
        drawdown_pct: float,
        revenue_usd: float,
        sharpe_ratio: float,
        cost_usd: float,
        venue: str = "polymarket",
    ) -> bool:
        """Write one cycle-level metrics document into the hub TSDS stream."""
        if not self.enabled:
            return False
        payload = {
            "@timestamp": _utcnow(),
            "agent_id": self.agent_id,
            "strategy_id": strategy_id,
            "agent_type": self.settings.elastic_agent_type,
            "venue": venue,
            "pnl_usd": round(pnl_usd, 6),
            "drawdown_pct": round(drawdown_pct, 6),
            "revenue_usd": round(revenue_usd, 6),
            "sharpe_ratio": round(sharpe_ratio, 6),
            "cost_usd": round(cost_usd, 6),
        }
        response = await self._request(
            "POST",
            f"/{self.settings.elastic_metrics_data_stream}/_doc",
            payload,
        )
        return response is not None

    async def emit_trade(
        self,
        *,
        trade_id: str,
        strategy_id: str,
        market_id: str,
        side: str,
        order_type: str,
        status: str,
        price: float,
        size: float,
        fee_usd: float = 0.0,
        realized_pnl_usd: float = 0.0,
        unrealized_pnl_usd: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Write one trade or order snapshot into the shared trades alias."""
        if not self.enabled:
            return False
        now = _utcnow()
        payload = {
            "trade_id": trade_id,
            "agent_id": self.agent_id,
            "strategy_id": strategy_id,
            "venue": "polymarket",
            "market_id": market_id,
            "event_id": market_id,
            "side": side,
            "order_type": order_type,
            "status": status,
            "price": round(price, 6),
            "size": round(size, 6),
            "notional_usd": round(price * size, 6),
            "fee_usd": round(fee_usd, 6),
            "realized_pnl_usd": round(realized_pnl_usd, 6),
            "unrealized_pnl_usd": round(unrealized_pnl_usd, 6),
            "executed_at": now,
            "recorded_at": now,
            "metadata": metadata or {},
        }
        response = await self._request(
            "PUT",
            f"/{self.settings.elastic_trades_alias}/_doc/{trade_id}",
            payload,
        )
        return response is not None

    def snapshot(self) -> dict[str, Any]:
        """Return the current telemetry state for the dashboard API."""
        auth_mode = "none"
        if self.settings.elasticsearch_api_key:
            auth_mode = "api_key"
        elif self.settings.elasticsearch_username and self.settings.elasticsearch_password:
            auth_mode = "basic"
        return {
            "enabled": self.enabled,
            "agent_id": self.agent_id,
            "reachable": self.reachable,
            "auth_mode": auth_mode,
            "base_url": self.settings.elasticsearch_url,
            "agents_alias": self.settings.elastic_agents_alias,
            "trades_alias": self.settings.elastic_trades_alias,
            "metrics_data_stream": self.settings.elastic_metrics_data_stream,
            "last_error": self.last_error,
        }

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        url = self.settings.elasticsearch_url.rstrip("/") + "/" + path.lstrip("/")
        previous_error = self.last_error
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.elastic_timeout_seconds,
                verify=self.settings.elasticsearch_verify_certs,
                headers=self._headers(),
                transport=self.transport,
            ) as client:
                response = await client.request(method, url, json=payload)
                response.raise_for_status()
                self.reachable = True
                self.last_error = None
                if not response.content:
                    return {}
                return response.json()
        except Exception as exc:
            self.reachable = False
            self.last_error = str(exc)
            if self.last_error != previous_error:
                logger.warning(
                    "elastic_telemetry_request_failed",
                    method=method,
                    path=path,
                    error=self.last_error,
                )
            return None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        api_key = self.settings.elasticsearch_api_key
        if api_key:
            token = api_key
            if ":" in api_key:
                token = base64.b64encode(api_key.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"ApiKey {token}"
            return headers
        username = self.settings.elasticsearch_username
        password = self.settings.elasticsearch_password
        if username and password:
            raw = f"{username}:{password}".encode("utf-8")
            headers["Authorization"] = (
                f"Basic {base64.b64encode(raw).decode('ascii')}"
            )
        return headers


def get_elastic_telemetry(settings: Settings | None = None) -> ElasticTelemetry:
    """Return a singleton telemetry bridge for the current process."""
    global _telemetry
    if _telemetry is None:
        _telemetry = ElasticTelemetry(settings=settings)
    return _telemetry
