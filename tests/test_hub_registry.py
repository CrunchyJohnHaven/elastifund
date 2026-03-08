from pathlib import Path

from hub.app.registry import HubRegistry


def test_registry_registers_and_accepts_heartbeat(tmp_path: Path):
    registry = HubRegistry(tmp_path / "registry.json")
    agent = registry.register(
        {
            "agent_id": "elastifund-test-agent",
            "agent_name": "Test Agent",
            "agent_secret": "secret-123",
            "capabilities": {"trading": True, "digital_products": False},
            "run_mode": "paper",
        }
    )

    heartbeat = registry.heartbeat(
        {
            "agent_id": "elastifund-test-agent",
            "agent_secret": "secret-123",
            "status": "ready",
            "snapshot": {"lane_status": {"trading": "ready"}},
            "metrics": {"enabled_lanes": 1},
        }
    )

    assert agent["agent_id"] == "elastifund-test-agent"
    assert heartbeat["last_status"] == "ready"
    assert registry.summary()["online_agents"] == 1
