from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shared.python.runtime import ElastifundRuntimeSettings

from .registry import HubRegistry


class RegisterRequest(BaseModel):
    bootstrap_token: str
    agent_name: str
    agent_id: str
    agent_secret: str
    run_mode: str = "paper"
    capabilities: dict[str, bool] = Field(default_factory=dict)
    nonprofit: str = "veteran-suicide-prevention"
    initial_capital_usd: int = 0
    trading_capital_pct: int = 0
    digital_capital_pct: int = 0
    stake_weight: float = 1.0


class HeartbeatRequest(BaseModel):
    agent_id: str
    agent_secret: str
    status: str = "online"
    snapshot: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)


router = APIRouter(tags=["agents"])


def _registry() -> HubRegistry:
    return HubRegistry(ElastifundRuntimeSettings.from_env().hub_registry_path)


@router.post("/api/v1/agents/register")
def register_agent(request: RegisterRequest) -> dict[str, Any]:
    settings = ElastifundRuntimeSettings.from_env()
    if request.bootstrap_token != settings.hub_bootstrap_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bootstrap token")
    try:
        record = _registry().register(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "status": "registered",
        "agent": record,
        "heartbeat_interval_seconds": settings.heartbeat_seconds,
    }


@router.post("/api/v1/agents/heartbeat")
def heartbeat(request: HeartbeatRequest) -> dict[str, Any]:
    try:
        record = _registry().heartbeat(request.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return {"status": "accepted", "agent": record}


@router.get("/api/v1/agents")
def list_agents() -> dict[str, Any]:
    return _registry().summary()
