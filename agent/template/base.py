"""Base class for agents that register with the local hub gateway."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any
from urllib import error, request

from shared.python.runtime import ElastifundRuntimeSettings

logger = logging.getLogger("elastifund.agent")


class ElastifundAgent(ABC):
    def __init__(self, settings: ElastifundRuntimeSettings):
        self.settings = settings
        self.registered = False

    def register_with_hub(self) -> dict[str, Any]:
        payload = {
            "bootstrap_token": self.settings.hub_bootstrap_token,
            "agent_name": self.settings.agent_name,
            "agent_id": self.settings.agent_id,
            "agent_secret": self.settings.agent_secret,
            "run_mode": self.settings.run_mode,
            "capabilities": self.settings.capabilities(),
            "nonprofit": self.settings.nonprofit,
            "initial_capital_usd": self.settings.initial_capital_usd,
            "trading_capital_pct": self.settings.trading_capital_pct,
            "digital_capital_pct": self.settings.digital_capital_pct,
            "stake_weight": 1.0,
        }
        response = self._post_json("/api/v1/agents/register", payload)
        self.registered = True
        return response

    def send_heartbeat(self, status: str, snapshot: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        if not self.registered:
            self.register_with_hub()
        payload = {
            "agent_id": self.settings.agent_id,
            "agent_secret": self.settings.agent_secret,
            "status": status,
            "snapshot": snapshot,
            "metrics": metrics,
        }
        return self._post_json("/api/v1/agents/heartbeat", payload)

    def run_once(self) -> dict[str, Any]:
        metrics = self.execute_strategy()
        snapshot = self.report_performance(metrics)
        self.receive_global_model(None)
        return self.send_heartbeat("ready", snapshot, metrics)

    @abstractmethod
    def execute_strategy(self) -> dict[str, Any]:
        """Run one unit of strategy work and return lightweight metrics."""

    @abstractmethod
    def report_performance(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Summarize the current local agent state for the hub."""

    @abstractmethod
    def receive_global_model(self, model: Any) -> None:
        """Accept the latest shared model or strategy hints from the hub."""

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.hub_url.rstrip('/')}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"hub request failed {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"hub is unreachable at {url}") from exc
