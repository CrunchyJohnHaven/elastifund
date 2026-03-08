import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from data_layer import crud, database
from hub.app.main import app


client = TestClient(app)


def test_benchmark_methodology_endpoint_returns_published_spec():
    response = client.get("/api/v1/benchmark/methodology")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "methodology_published"
    assert body["spec_version"] == "2026.03-candidate1"


def test_bots_endpoint_returns_catalog_items():
    response = client.get("/api/v1/bots", params={"category": "open_source_execution"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] >= 4
    assert any(item["id"] == "freqtrade" for item in body["items"])


def test_bot_detail_endpoint_404s_for_unknown_system():
    response = client.get("/api/v1/bots/not-a-real-bot")

    assert response.status_code == 404
    assert "unknown bot" in response.json()["detail"]


def test_runs_endpoint_exposes_planned_tier1_runs():
    response = client.get("/api/v1/runs", params={"status": "planned"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {item["system_id"] for item in body["items"]} == {
        "freqtrade",
        "hummingbot",
        "nautilustrader",
    }


def test_paper_status_endpoint_reflects_methodology_first_state():
    response = client.get("/api/v1/paper-status", params={"bot_id": "freqtrade"})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "not_started"
    assert body["items"][0]["bot_id"] == "freqtrade"


def test_agent_endpoints_share_the_main_gateway_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("ELASTIFUND_HUB_REGISTRY_PATH", str(tmp_path / "registry.json"))
    monkeypatch.setenv("ELASTIFUND_HUB_BOOTSTRAP_TOKEN", "test-bootstrap-token")

    register_response = client.post(
        "/api/v1/agents/register",
        json={
            "bootstrap_token": "test-bootstrap-token",
            "agent_name": "Test Agent",
            "agent_id": "agent-main-contract",
            "agent_secret": "secret-123",
            "run_mode": "paper",
            "capabilities": {"trading": True, "digital_products": False},
            "initial_capital_usd": 250,
            "trading_capital_pct": 70,
            "digital_capital_pct": 30,
        },
    )
    assert register_response.status_code == 200
    assert register_response.json()["status"] == "registered"

    heartbeat_response = client.post(
        "/api/v1/agents/heartbeat",
        json={
            "agent_id": "agent-main-contract",
            "agent_secret": "secret-123",
            "status": "ready",
            "snapshot": {"lane_status": {"trading": "ready"}},
            "metrics": {"enabled_lanes": 1},
        },
    )
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["status"] == "accepted"

    list_response = client.get("/api/v1/agents")
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total_agents"] == 1
    assert body["agents"][0]["agent_id"] == "agent-main-contract"


def test_flywheel_endpoints_expose_structured_tasks_and_findings(tmp_path, monkeypatch):
    control_db = tmp_path / "flywheel.db"
    monkeypatch.setenv("ELASTIFUND_CONTROL_DB_URL", f"sqlite:///{control_db}")

    database.reset_engine()
    engine = database.get_engine(f"sqlite:///{control_db}")
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        cycle = crud.create_flywheel_cycle(session, cycle_key="hub-flywheel-test", status="completed")
        finding = crud.create_flywheel_finding(
            session,
            finding_key="finding-hub-1",
            cycle_id=cycle.id,
            strategy_version_id=None,
            lane="fast_flow",
            environment="paper",
            source_kind="policy_cycle",
            finding_type="promotion",
            title="Wallet flow passed paper gate",
            summary="Promotion rules passed.",
            lesson="Use explicit promotion gates.",
            evidence={"closed_trades": 24},
            priority=20,
        )
        crud.create_flywheel_task(
            session,
            cycle_id=cycle.id,
            strategy_version_id=None,
            finding_id=finding.id,
            action="promote",
            title="Promote wallet-flow to shadow",
            details="Paper stage evidence is sufficient.",
            priority=20,
            status="open",
            lane="fast_flow",
            environment="paper",
            source_kind="policy_cycle",
            source_ref="cycle:hub-flywheel-test",
            metadata={"closed_trades": 24},
        )
        session.commit()
    finally:
        session.close()
        database.reset_engine()

    tasks_response = client.get("/api/v1/flywheel/tasks", params={"lane": "fast_flow", "status": "open"})
    assert tasks_response.status_code == 200
    tasks_body = tasks_response.json()
    assert tasks_body["total"] == 1
    assert tasks_body["items"][0]["title"] == "Promote wallet-flow to shadow"
    assert tasks_body["items"][0]["metadata"]["closed_trades"] == 24

    findings_response = client.get(
        "/api/v1/flywheel/findings",
        params={"lane": "fast_flow", "status": "open"},
    )
    assert findings_response.status_code == 200
    findings_body = findings_response.json()
    assert findings_body["total"] == 1
    assert findings_body["items"][0]["finding_key"] == "finding-hub-1"
    assert findings_body["items"][0]["lesson"] == "Use explicit promotion gates."
