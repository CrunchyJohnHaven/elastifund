"""Phase 10 hardening tests for the flywheel control plane."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data_layer import crud
from data_layer.schema import Base
from flywheel.resilience import HubControlPlane, simulate_federated_round
from flywheel.runner import run_cycle


def _snapshot_payload(**overrides):
    payload = {
        "snapshot_date": "2026-03-07",
        "starting_bankroll": 100.0,
        "ending_bankroll": 104.0,
        "realized_pnl": 4.0,
        "unrealized_pnl": 1.0,
        "open_positions": 1,
        "closed_trades": 12,
        "win_rate": 0.60,
        "fill_rate": 0.70,
        "avg_slippage_bps": 11.0,
        "rolling_brier": 0.22,
        "rolling_ece": 0.05,
        "max_drawdown_pct": 0.07,
        "kill_events": 0,
        "metrics": {},
    }
    payload.update(overrides)
    return payload


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    return engine, session


def test_hub_commands_round_trip_from_issue_to_ack() -> None:
    engine, session = _session()
    try:
        hub = HubControlPlane(session)
        hub.register_agent(
            agent_id="agent-alpha",
            lane="fast_flow",
            environment="paper",
            metadata={"owner": "test"},
        )
        command = hub.issue_command(
            agent_id="agent-alpha",
            command_type="shutdown",
            reason="emergency stop",
            payload={"source": "test"},
        )
        session.commit()

        delivered = hub.poll_commands(agent_id="agent-alpha")
        assert len(delivered) == 1
        assert delivered[0].id == command.id
        assert delivered[0].status == "delivered"

        acked = hub.acknowledge_command(agent_id="agent-alpha", command_id=command.id)
        session.commit()

        assert acked is not None
        assert acked.status == "acknowledged"
        stored = crud.get_agent_command(session, command.id)
        assert stored is not None
        assert stored.acknowledged_at is not None
    finally:
        session.close()
        engine.dispose()


def test_run_cycle_auto_pauses_on_gt_three_sigma_activity_spike(tmp_path) -> None:
    engine, session = _session()
    try:
        cycle_template = {
            "strategies": [
                {
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-live",
                    "lane": "fast_flow",
                    "deployments": [
                        {
                            "environment": "core_live",
                            "capital_cap_usd": 25.0,
                        }
                    ],
                }
            ],
        }

        for idx in range(5):
            payload = {
                **cycle_template,
                "cycle_key": f"baseline-{idx}",
            }
            payload["strategies"][0]["deployments"][0]["snapshot"] = _snapshot_payload(
                snapshot_date=f"2026-03-{idx + 1:02d}",
                closed_trades=10,
            )
            run_cycle(session, payload, artifact_root=tmp_path)

        spike_payload = {
            **cycle_template,
            "cycle_key": "spike",
        }
        spike_payload["strategies"][0]["deployments"][0]["snapshot"] = _snapshot_payload(
            snapshot_date="2026-03-06",
            closed_trades=120,
        )
        result = run_cycle(session, spike_payload, artifact_root=tmp_path)

        assert len(result["guardrails"]) == 1
        assert result["guardrails"][0]["metric"] == "closed_trades"

        agent_id = "wallet-flow:wf-live:core_live"
        runtime = crud.get_agent_runtime(session, agent_id)
        assert runtime is not None
        assert runtime.status == "paused"
        assert runtime.anomaly_state == "paused"

        commands = crud.list_agent_commands(session, agent_id=agent_id, limit=10)
        assert len(commands) == 1
        assert commands[0].command_type == "pause"
        assert "z=" in commands[0].reason
    finally:
        session.close()
        engine.dispose()


def test_federated_round_simulation_rejects_most_poisoned_updates() -> None:
    result = simulate_federated_round(
        agent_count=50,
        malicious_fraction=0.10,
        dimensions=12,
        seed=7,
    )

    assert result["agent_count"] == 50
    assert len(result["malicious_agent_ids"]) == 5
    assert result["robust_error"] < result["naive_error"]
    assert len(result["rejected_malicious_ids"]) >= 4
    assert result["survivor_count"] < result["agent_count"]


def test_control_plane_handles_one_thousand_agents_in_local_scale_smoke() -> None:
    engine, session = _session()
    try:
        hub = HubControlPlane(session)
        for idx in range(1000):
            hub.record_heartbeat(
                agent_id=f"agent-{idx:04d}",
                lane="fast_flow" if idx % 2 == 0 else "non_trading",
                environment="paper",
                activity_metric="closed_trades",
                activity_value=float(idx % 7),
                metadata={"ordinal": idx},
            )
            if idx % 100 == 0:
                hub.issue_command(
                    agent_id=f"agent-{idx:04d}",
                    command_type="rotate_api_key",
                    reason="weekly_rotation",
                )
        session.commit()

        runtimes = crud.list_agent_runtimes(session, limit=2000)
        commands = crud.list_agent_commands(session, limit=2000)

        assert len(runtimes) == 1000
        assert len(commands) == 10
    finally:
        session.close()
        engine.dispose()
