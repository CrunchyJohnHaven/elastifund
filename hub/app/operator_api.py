from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from scripts import runtime_controls
from scripts.runtime_controls import RuntimeControlError


router = APIRouter(tags=["operator"])

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
ACTION_DIR = REPORTS_DIR / "operator_actions"
EFFECTIVE_PROFILE_PATH = REPORTS_DIR / "runtime_profile_effective.json"
OVERRIDES_ENV_PATH = REPORTS_DIR / "runtime_operator_overrides.env"
GUIDANCE_PREFIX = "manage_guidance"
GUIDANCE_LATEST_PATH = ACTION_DIR / f"{GUIDANCE_PREFIX}_latest.json"
RUNTIME_CONTROL_LATEST_PATH = ACTION_DIR / "runtime_control_latest.json"

GUIDANCE_MODE = Literal["repair", "gate", "exploit", "explore", "observe"]
FOCUS_STAGE = Literal["search", "evidence", "gate", "execution", "learning"]


class GuidancePacketRequest(BaseModel):
    route: str = Field(default="/manage/", min_length=1, max_length=128)
    guidance_mode: GUIDANCE_MODE
    focus_stage: FOCUS_STAGE
    runtime_posture: dict[str, Any] = Field(default_factory=dict)
    pnl_state: dict[str, Any] = Field(default_factory=dict)
    learning_state: dict[str, Any] = Field(default_factory=dict)
    directives: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    packet_generated_at: str | None = Field(default=None, max_length=64)
    source: str = Field(default="manage-console", min_length=1, max_length=64)


class RuntimeControlsRequest(BaseModel):
    profile: str = Field(default="shadow_fast_flow", min_length=1, max_length=128)
    yes_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    no_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_resolution_hours: float | None = Field(default=None, gt=0.0, le=168.0)
    hourly_notional_budget_usd: float | None = Field(default=None, ge=0.0, le=500.0)
    per_trade_cap_usd: float | None = Field(default=None, gt=0.0)
    enable_polymarket: bool | None = None
    enable_kalshi: bool | None = None
    guidance_mode: GUIDANCE_MODE | None = None
    focus_stage: FOCUS_STAGE | None = None
    reason: str | None = Field(default=None, max_length=400)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_timestamped_payload(prefix: str, payload: dict[str, Any]) -> Path:
    ACTION_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ACTION_DIR / f"{prefix}_{timestamp}.json"
    _write_json(path, payload)
    return path


def _list_recent_payloads(prefix: str, limit: int) -> list[dict[str, Any]]:
    if not ACTION_DIR.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(ACTION_DIR.glob(f"{prefix}_*.json"), reverse=True):
        if path.name.endswith("_latest.json"):
            continue
        payload = _load_json(path)
        if not payload:
            continue
        items.append(
            {
                "path": _to_repo_relative(path),
                "generated_at": payload.get("generated_at") or payload.get("accepted_at"),
                "status": payload.get("status"),
                "guidance_mode": payload.get("guidance_mode"),
                "focus_stage": payload.get("focus_stage"),
                "directive_count": payload.get("directive_count", len(payload.get("directives") or [])),
                "command": (payload.get("operator_action") or {}).get("command"),
                "profile": (payload.get("operator_action") or {}).get("profile"),
            }
        )
        if len(items) >= limit:
            break
    return items


def _build_runtime_control_args(payload: RuntimeControlsRequest) -> tuple[argparse.Namespace, list[str]]:
    argv = ["--profile", payload.profile, "set-controls"]
    namespace = argparse.Namespace(
        profile=payload.profile,
        reports_dir=str(REPORTS_DIR),
        overrides_path=str(OVERRIDES_ENV_PATH),
        effective_path=str(EFFECTIVE_PROFILE_PATH),
        action_dir=str(ACTION_DIR),
        action_prefix="runtime_control",
        command="set-controls",
        yes_threshold=None,
        no_threshold=None,
        max_resolution_hours=None,
        hourly_notional_budget_usd=None,
        per_trade_cap_usd=None,
        enable_polymarket=None,
        enable_kalshi=None,
    )

    if payload.yes_threshold is not None:
        namespace.yes_threshold = str(payload.yes_threshold)
        argv.extend(["--yes-threshold", f"{payload.yes_threshold:g}"])
    if payload.no_threshold is not None:
        namespace.no_threshold = str(payload.no_threshold)
        argv.extend(["--no-threshold", f"{payload.no_threshold:g}"])
    if payload.max_resolution_hours is not None:
        namespace.max_resolution_hours = str(payload.max_resolution_hours)
        argv.extend(["--max-resolution-hours", f"{payload.max_resolution_hours:g}"])
    if payload.hourly_notional_budget_usd is not None:
        namespace.hourly_notional_budget_usd = str(payload.hourly_notional_budget_usd)
        argv.extend(["--hourly-notional-budget-usd", f"{payload.hourly_notional_budget_usd:g}"])
    if payload.per_trade_cap_usd is not None:
        namespace.per_trade_cap_usd = str(payload.per_trade_cap_usd)
        argv.extend(["--per-trade-cap-usd", f"{payload.per_trade_cap_usd:g}"])
    if payload.enable_polymarket is not None:
        namespace.enable_polymarket = "true" if payload.enable_polymarket else "false"
        argv.extend(["--enable-polymarket", namespace.enable_polymarket])
    if payload.enable_kalshi is not None:
        namespace.enable_kalshi = "true" if payload.enable_kalshi else "false"
        argv.extend(["--enable-kalshi", namespace.enable_kalshi])
    return namespace, argv


def _runtime_controls_requested(payload: RuntimeControlsRequest) -> bool:
    return any(
        value is not None
        for value in (
            payload.yes_threshold,
            payload.no_threshold,
            payload.max_resolution_hours,
            payload.hourly_notional_budget_usd,
            payload.per_trade_cap_usd,
            payload.enable_polymarket,
            payload.enable_kalshi,
        )
    )


@router.get("/api/v1/operator/console")
def get_operator_console_state(limit: int = Query(default=8, ge=1, le=50)) -> dict[str, Any]:
    effective_profile = _load_json(EFFECTIVE_PROFILE_PATH) or {}
    overrides = runtime_controls.parse_runtime_overrides_env(OVERRIDES_ENV_PATH)
    latest_guidance = _load_json(GUIDANCE_LATEST_PATH)
    latest_runtime_control = _load_json(RUNTIME_CONTROL_LATEST_PATH)
    return {
        "status": "ok",
        "generated_at": _iso_utc_now(),
        "paths": {
            "reports_dir": _to_repo_relative(REPORTS_DIR),
            "effective_profile": _to_repo_relative(EFFECTIVE_PROFILE_PATH),
            "overrides_env": _to_repo_relative(OVERRIDES_ENV_PATH),
            "guidance_latest": _to_repo_relative(GUIDANCE_LATEST_PATH),
            "runtime_control_latest": _to_repo_relative(RUNTIME_CONTROL_LATEST_PATH),
        },
        "runtime_controls": {
            "effective_profile": effective_profile,
            "overrides": overrides,
            "latest_action": latest_runtime_control,
            "history": _list_recent_payloads("runtime_control", limit),
        },
        "guidance": {
            "latest_packet": latest_guidance,
            "history": _list_recent_payloads(GUIDANCE_PREFIX, limit),
        },
    }


@router.post("/api/v1/operator/guidance", status_code=status.HTTP_201_CREATED)
def submit_operator_guidance(payload: GuidancePacketRequest) -> dict[str, Any]:
    accepted_at = _iso_utc_now()
    directives = list(payload.directives)[:16]
    packet = {
        "artifact": GUIDANCE_PREFIX,
        "accepted_at": accepted_at,
        "directive_count": len(directives),
        "directives": directives,
        "focus_stage": payload.focus_stage,
        "generated_at": accepted_at,
        "guidance_mode": payload.guidance_mode,
        "learning_state": payload.learning_state,
        "packet_generated_at": payload.packet_generated_at,
        "pnl_state": payload.pnl_state,
        "recommendations": payload.recommendations[:8],
        "route": payload.route,
        "runtime_posture": payload.runtime_posture,
        "source": payload.source,
        "status": "accepted",
    }
    history_path = _write_timestamped_payload(GUIDANCE_PREFIX, packet)
    latest_payload = dict(packet)
    latest_payload["history_path"] = _to_repo_relative(history_path)
    _write_json(GUIDANCE_LATEST_PATH, latest_payload)
    return {
        "acknowledged": True,
        "accepted_at": accepted_at,
        "history_path": _to_repo_relative(history_path),
        "latest_path": _to_repo_relative(GUIDANCE_LATEST_PATH),
        "packet": latest_payload,
    }


@router.post("/api/v1/operator/runtime-controls", status_code=status.HTTP_201_CREATED)
def apply_runtime_controls(payload: RuntimeControlsRequest) -> dict[str, Any]:
    if not _runtime_controls_requested(payload):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one runtime control must be provided.",
        )

    args, argv = _build_runtime_control_args(payload)
    try:
        result = runtime_controls.apply_runtime_control_args(args, argv)
    except RuntimeControlError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    accepted_at = _iso_utc_now()
    latest_payload = {
        "accepted_at": accepted_at,
        "guidance_context": {
            "focus_stage": payload.focus_stage,
            "guidance_mode": payload.guidance_mode,
            "reason": payload.reason,
        },
        "history_path": _to_repo_relative(Path(result["operator_action"])),
        "operator_action": result["action_payload"].get("operator_action", {}),
        "status": "accepted",
        "effective_scope": result["action_payload"].get("effective_scope", {}),
        "effective_profile": _load_json(EFFECTIVE_PROFILE_PATH) or {},
        "overrides": runtime_controls.parse_runtime_overrides_env(OVERRIDES_ENV_PATH),
    }
    _write_json(RUNTIME_CONTROL_LATEST_PATH, latest_payload)
    return {
        "acknowledged": True,
        "accepted_at": accepted_at,
        "effective_profile_path": _to_repo_relative(Path(result["effective_profile"])),
        "history_path": _to_repo_relative(Path(result["operator_action"])),
        "latest_path": _to_repo_relative(RUNTIME_CONTROL_LATEST_PATH),
        "runtime_control": latest_payload,
    }
