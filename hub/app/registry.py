"""Filesystem-backed agent registry used by the local hub gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from shared.python.runtime import secret_digest, utc_now


@dataclass
class HubRegistry:
    path: Path

    def __post_init__(self) -> None:
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def register(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        agent_id = str(payload["agent_id"])
        secret = str(payload["agent_secret"])
        now = utc_now()

        with self._lock:
            data = self._load()
            agents = data.setdefault("agents", {})
            existing = agents.get(agent_id)
            secret_hash = secret_digest(secret)

            if existing and existing.get("agent_secret_hash") != secret_hash:
                raise ValueError(f"agent_id '{agent_id}' is already registered with a different secret")

            record = {
                "agent_id": agent_id,
                "agent_name": payload.get("agent_name", ""),
                "agent_secret_hash": secret_hash,
                "capabilities": dict(payload.get("capabilities", {})),
                "run_mode": payload.get("run_mode", "paper"),
                "nonprofit": payload.get("nonprofit", "veteran-suicide-prevention"),
                "initial_capital_usd": payload.get("initial_capital_usd", 0),
                "trading_capital_pct": payload.get("trading_capital_pct", 0),
                "digital_capital_pct": payload.get("digital_capital_pct", 0),
                "stake_weight": payload.get("stake_weight", 1.0),
                "registered_at": existing.get("registered_at", now) if existing else now,
                "last_heartbeat_at": existing.get("last_heartbeat_at") if existing else None,
                "last_status": existing.get("last_status", "registered") if existing else "registered",
                "last_snapshot": existing.get("last_snapshot", {}) if existing else {},
            }
            agents[agent_id] = record
            self._save(data)
        return self._sanitize(record)

    def heartbeat(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        agent_id = str(payload["agent_id"])
        secret = str(payload["agent_secret"])

        with self._lock:
            data = self._load()
            agents = data.setdefault("agents", {})
            if agent_id not in agents:
                raise KeyError(f"agent_id '{agent_id}' is not registered")
            record = agents[agent_id]
            if record.get("agent_secret_hash") != secret_digest(secret):
                raise PermissionError(f"agent_id '{agent_id}' failed authentication")

            record["last_heartbeat_at"] = utc_now()
            record["last_status"] = payload.get("status", "online")
            record["last_snapshot"] = dict(payload.get("snapshot", {}))
            record["last_metrics"] = dict(payload.get("metrics", {}))
            self._save(data)
        return self._sanitize(record)

    def summary(self) -> dict[str, Any]:
        data = self._load()
        agents = list(data.get("agents", {}).values())
        online = sum(1 for agent in agents if agent.get("last_status") in {"online", "ready"})
        return {
            "total_agents": len(agents),
            "online_agents": online,
            "agents": [self._sanitize(agent) for agent in agents],
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"agents": {}}
        return json.loads(self.path.read_text())

    def _save(self, data: Mapping[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def _sanitize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "agent_secret_hash"}
