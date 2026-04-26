from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub.app import operator_api


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(operator_api.router)
    return TestClient(app)


def test_submit_operator_guidance_writes_latest_and_history(monkeypatch, tmp_path: Path) -> None:
    action_dir = tmp_path / "operator_actions"
    latest_path = action_dir / "manage_guidance_latest.json"

    monkeypatch.setattr(operator_api, "ACTION_DIR", action_dir)
    monkeypatch.setattr(operator_api, "GUIDANCE_LATEST_PATH", latest_path)
    monkeypatch.setattr(operator_api, "_iso_utc_now", lambda: "2026-03-25T22:00:00Z")

    client = _build_client()
    response = client.post(
        "/api/v1/operator/guidance",
        json={
            "route": "/manage/",
            "guidance_mode": "repair",
            "focus_stage": "gate",
            "runtime_posture": {"loop_health": "Untrusted / cleanup first"},
            "directives": [{"text": "Repair launch truth", "mode": "repair"}],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["acknowledged"] is True
    assert body["packet"]["directive_count"] == 1
    assert latest_path.exists()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["guidance_mode"] == "repair"
    assert latest["history_path"].endswith(".json")
    assert "manage_guidance_" in latest["history_path"]


def test_apply_runtime_controls_returns_ack_and_writes_latest(monkeypatch, tmp_path: Path) -> None:
    action_dir = tmp_path / "operator_actions"
    effective_path = tmp_path / "runtime_profile_effective.json"
    overrides_path = tmp_path / "runtime_operator_overrides.env"
    latest_path = action_dir / "runtime_control_latest.json"
    history_path = action_dir / "runtime_control_20260325T220000Z.json"

    effective_path.write_text(json.dumps({"selected_profile": "shadow_fast_flow"}), encoding="utf-8")

    monkeypatch.setattr(operator_api, "ACTION_DIR", action_dir)
    monkeypatch.setattr(operator_api, "EFFECTIVE_PROFILE_PATH", effective_path)
    monkeypatch.setattr(operator_api, "OVERRIDES_ENV_PATH", overrides_path)
    monkeypatch.setattr(operator_api, "RUNTIME_CONTROL_LATEST_PATH", latest_path)
    monkeypatch.setattr(operator_api, "_iso_utc_now", lambda: "2026-03-25T22:00:00Z")
    monkeypatch.setattr(operator_api.runtime_controls, "parse_runtime_overrides_env", lambda _path: {"JJ_MAX_POSITION_USD": "5"})
    monkeypatch.setattr(
        operator_api.runtime_controls,
        "apply_runtime_control_args",
        lambda args, argv: {
            "effective_profile": str(effective_path),
            "operator_action": str(history_path),
            "action_payload": {
                "operator_action": {"command": "set-controls", "profile": args.profile},
                "effective_scope": {"after": {"risk_limits": {"max_position_usd": 8.0}}},
            },
        },
    )

    client = _build_client()
    response = client.post(
        "/api/v1/operator/runtime-controls",
        json={
            "profile": "shadow_fast_flow",
            "per_trade_cap_usd": 8.0,
            "guidance_mode": "exploit",
            "focus_stage": "execution",
            "reason": "Test the lever path",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["acknowledged"] is True
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["guidance_context"]["guidance_mode"] == "exploit"
    assert latest["operator_action"]["command"] == "set-controls"


def test_get_operator_console_state_reads_effective_profile_and_latest_packets(monkeypatch, tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    action_dir = reports_dir / "operator_actions"
    effective_path = reports_dir / "runtime_profile_effective.json"
    overrides_path = reports_dir / "runtime_operator_overrides.env"
    guidance_latest = action_dir / "manage_guidance_latest.json"
    runtime_latest = action_dir / "runtime_control_latest.json"
    action_dir.mkdir(parents=True)
    effective_path.write_text(json.dumps({"selected_profile": "shadow_fast_flow"}), encoding="utf-8")
    guidance_latest.write_text(json.dumps({"guidance_mode": "repair"}), encoding="utf-8")
    runtime_latest.write_text(json.dumps({"operator_action": {"command": "set-controls"}}), encoding="utf-8")

    monkeypatch.setattr(operator_api, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(operator_api, "ACTION_DIR", action_dir)
    monkeypatch.setattr(operator_api, "EFFECTIVE_PROFILE_PATH", effective_path)
    monkeypatch.setattr(operator_api, "OVERRIDES_ENV_PATH", overrides_path)
    monkeypatch.setattr(operator_api, "GUIDANCE_LATEST_PATH", guidance_latest)
    monkeypatch.setattr(operator_api, "RUNTIME_CONTROL_LATEST_PATH", runtime_latest)
    monkeypatch.setattr(operator_api.runtime_controls, "parse_runtime_overrides_env", lambda _path: {"JJ_MAX_POSITION_USD": "5"})

    client = _build_client()
    response = client.get("/api/v1/operator/console")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_controls"]["effective_profile"]["selected_profile"] == "shadow_fast_flow"
    assert body["guidance"]["latest_packet"]["guidance_mode"] == "repair"
    assert body["runtime_controls"]["latest_action"]["operator_action"]["command"] == "set-controls"
