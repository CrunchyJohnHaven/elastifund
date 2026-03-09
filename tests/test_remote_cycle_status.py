from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.write_remote_cycle_status import (  # noqa: E402
    build_remote_cycle_status,
    render_remote_cycle_status_markdown,
    write_remote_cycle_status,
)


def test_build_remote_cycle_status_includes_polymarket_wallet_observation(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "12 passed",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-09T12:31:00+00:00",
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 12.34,
            "reserved_order_usd": 5.67,
            "live_orders_count": 2,
            "live_orders": [],
            "open_positions_count": 3,
            "positions_initial_value_usd": 22.22,
            "positions_current_value_usd": 25.5,
            "positions_unrealized_pnl_usd": 3.28,
            "closed_positions_count": 4,
            "closed_positions_realized_pnl_usd": -1.49,
            "total_wallet_value_usd": 43.51,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["polymarket_wallet"]["status"] == "ok"
    assert status["capital"]["polymarket_actual_deployable_usd"] == 12.34
    assert status["capital"]["polymarket_observed_deployed_usd"] == 27.89
    assert status["capital"]["polymarket_observed_total_usd"] == 43.51
    assert status["capital"]["polymarket_tracked_vs_observed_delta_usd"] == 204.0
    assert status["runtime"]["polymarket_live_orders"] == 2
    assert status["runtime"]["polymarket_open_positions"] == 3
    assert status["runtime"]["polymarket_closed_positions_realized_pnl_usd"] == -1.49


def test_build_remote_cycle_status_includes_btc5_maker_observation(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "12 passed",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_btc5_db(
        tmp_path / "data" / "btc_5min_maker.db",
        [
            {
                "window_start_ts": 1773061200,
                "window_end_ts": 1773061500,
                "slug": "btc-updown-5m-1773061200",
                "decision_ts": 1773061499,
                "direction": "UP",
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.2071,
                "created_at": "2026-03-09T13:04:59+00:00",
                "updated_at": "2026-03-09T13:05:00+00:00",
            },
            {
                "window_start_ts": 1773062400,
                "window_end_ts": 1773062700,
                "slug": "btc-updown-5m-1773062400",
                "decision_ts": 1773062699,
                "direction": "UP",
                "order_price": 0.50,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": -5.0,
                "created_at": "2026-03-09T13:24:59+00:00",
                "updated_at": "2026-03-09T13:25:00+00:00",
            },
            {
                "window_start_ts": 1773063000,
                "window_end_ts": 1773063300,
                "slug": "btc-updown-5m-1773063000",
                "decision_ts": 1773063299,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.416,
                "created_at": "2026-03-09T13:34:59+00:00",
                "updated_at": "2026-03-09T13:35:00+00:00",
            },
        ],
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["btc_5min_maker"]["status"] == "ok"
    assert status["btc_5min_maker"]["live_filled_rows"] == 3
    assert status["btc_5min_maker"]["live_filled_pnl_usd"] == 5.6231
    assert status["btc_5min_maker"]["fill_attribution"]["best_direction"]["label"] == "DOWN"
    assert status["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    assert status["runtime"]["btc5_live_filled_rows"] == 3
    assert status["runtime"]["btc5_latest_order_status"] == "live_filled"
    assert status["runtime"]["btc5_latest_trade_pnl_usd"] == 5.416
    assert status["runtime"]["btc5_best_direction"] == "DOWN"
    assert status["runtime"]["btc5_best_price_bucket"] == "<0.49"


def test_build_remote_cycle_status_refreshes_data_cadence_from_live_observations(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    fresh_now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": (fresh_now - timedelta(minutes=1)).isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": fresh_now.isoformat(),
            "command": "make test",
            "status": "passing",
            "summary": "12 passed",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_btc5_db(
        tmp_path / "data" / "btc_5min_maker.db",
        [
            {
                "window_start_ts": 1773061200,
                "window_end_ts": 1773061500,
                "slug": "btc-updown-5m-1773061200",
                "decision_ts": 1773061499,
                "direction": "UP",
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.2071,
                "created_at": fresh_now.isoformat(),
                "updated_at": fresh_now.isoformat(),
            },
        ],
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": fresh_now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 12.34,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 1,
            "positions_initial_value_usd": 5.0,
            "positions_current_value_usd": 5.5,
            "positions_unrealized_pnl_usd": 0.5,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 1.25,
            "total_wallet_value_usd": 17.84,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    refreshed_at = datetime.fromisoformat(status["runtime"]["last_remote_pull_at"])
    assert refreshed_at >= fresh_now
    assert status["data_cadence"]["last_remote_pull_at"] == status["runtime"]["last_remote_pull_at"]
    assert status["data_cadence"]["stale"] is False
    assert status["data_cadence"]["freshness_basis"] == "remote_observation"
    assert any(
        source in status["data_cadence"]["freshness_sources"]
        for source in ("polymarket_wallet_probe", "btc5_maker_probe")
    )


def test_build_remote_cycle_status_prefers_remote_btc5_probe(tmp_path: Path, monkeypatch):
    _write_base_remote_state(tmp_path)
    _write_text(
        tmp_path / ".env",
        "\n".join(
            [
                "LIGHTSAIL_KEY=/tmp/test-key",
                "VPS_IP=1.2.3.4",
                "",
            ]
        ),
    )
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "12 passed",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {"status": "unavailable", "checked_at": "2026-03-09T13:31:00+00:00"},
    )

    def fake_run(*args, **kwargs):
        command = args[0]
        if command[0] == "ssh":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": "ok",
                        "checked_at": "2026-03-09T13:31:16+00:00",
                        "db_path": "/remote/data/btc_5min_maker.db",
                        "total_rows": 17,
                        "live_filled_rows": 6,
                        "live_filled_pnl_usd": 0.0539,
                        "avg_live_filled_pnl_usd": 0.009,
                        "latest_live_filled_at": "2026-03-09T13:30:00+00:00",
                        "latest_trade": {
                            "window_start_ts": 1773062700,
                            "direction": "DOWN",
                            "order_status": "live_filled",
                            "pnl_usd": -5.0029,
                        },
                        "recent_live_filled": [],
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected subprocess call: {command}")

    monkeypatch.setattr("scripts.write_remote_cycle_status.subprocess.run", fake_run)

    status = build_remote_cycle_status(tmp_path)

    assert status["btc_5min_maker"]["source"] == "remote_sqlite_probe"
    assert status["runtime"]["btc5_live_filled_rows"] == 6
    assert status["runtime"]["btc5_live_filled_pnl_usd"] == 0.0539
    assert status["runtime"]["btc5_latest_trade_pnl_usd"] == -5.0029


def test_build_remote_cycle_status_reports_launch_blockers(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "failing",
            "summary": "scripts/run_edge_collector.py uses stdlib-incompatible logging kwargs.",
            "returncode": 2,
            "output_tail": ["FAILED tests/test_edge_collector_standalone.py"],
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "fill_proxy": {
                "full_fill_proxy_rate": None,
            },
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {
                "measurement_status": "insufficient_live_samples",
            },
        },
    )
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
            {"market_id": "m2", "outcome": None},
        ],
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["service"]["status"] == "stopped"
    assert status["root_tests"]["status"] == "failing"
    assert status["runtime"]["closed_trades"] == 1
    assert status["wallet_flow"]["ready"] is False
    assert "missing_data/smart_wallets.json" in status["wallet_flow"]["reasons"]
    assert "missing_data/wallet_scores.db" in status["wallet_flow"]["reasons"]
    assert status["structural_gates"]["a6"]["status"] == "blocked"
    assert status["structural_gates"]["b1"]["status"] == "blocked"
    assert status["launch"]["fast_flow_restart_ready"] is False
    assert status["launch"]["live_launch_blocked"] is True
    assert status["launch"]["next_operator_action"].startswith(
        "Merge the root regression repair"
    )


def test_build_remote_cycle_status_falls_back_to_local_systemctl_and_runtime_truth(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_json(
        tmp_path / "reports" / "runtime_truth_20260309T130303Z.json",
        {
            "generated_at": "2026-03-09T13:03:03+00:00",
            "service": {
                "status": "running",
                "systemctl_state": "active",
                "checked_at": "2026-03-09T13:02:00+00:00",
            },
            "verification": {
                "status": "passing",
                "summary": "1096 passed in 22.67s; 25 passed in 3.59s",
                "checked_at": "2026-03-09T13:01:00+00:00",
                "command": "make test",
            },
        },
    )

    def fake_run(*args, **kwargs):
        command = args[0]
        if command[:2] == ["systemctl", "show"]:
            return SimpleNamespace(
                returncode=0,
                stdout="ActiveState=active\nSubState=running\n",
                stderr="",
            )
        raise AssertionError(f"unexpected subprocess call: {command}")

    monkeypatch.setattr("scripts.write_remote_cycle_status.subprocess.run", fake_run)

    status = build_remote_cycle_status(tmp_path)

    assert status["service"]["status"] == "running"
    assert status["service"]["source"] == "local_systemctl"
    assert status["root_tests"]["status"] == "passing"
    assert (
        status["root_tests"]["source"]
        == "reports/runtime_truth_20260309T130303Z.json"
    )


def test_build_remote_cycle_status_falls_back_to_pipeline_verification(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T13:02:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_json(
        tmp_path / "reports" / "pipeline_20260309T131500Z.json",
        {
            "report_generated_at": "2026-03-09T13:15:00+00:00",
            "verification": {
                "integrated_entrypoint_status": "passed",
                "make_test_status": "passed",
                "root_suite": "1096 passed in 22.67s",
                "jj_live_import_boundary_suite": "25 passed in 3.59s",
            },
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["root_tests"]["status"] == "passing"
    assert status["root_tests"]["summary"] == "1096 passed in 22.67s; 25 passed in 3.59s"
    assert status["root_tests"]["source"] == "reports/pipeline_20260309T131500Z.json"


def test_write_remote_cycle_status_refreshes_root_test_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "fill_proxy": {"full_fill_proxy_rate": 0.72},
            "gating_metrics": {
                "all_gates_pass": True,
                "fill_probability_gate": "pass",
                "half_life_gate": "pass",
                "half_life_seconds": 480.0,
                "settlement_path_gate": "pass",
            },
            "settlement": {
                "successful_operation_count": 3,
            },
            "lanes": {
                "b1": {
                    "status": "ready_for_shadow",
                    "summary": "B-1 is ready for shadow validation.",
                    "classification_accuracy": 0.9,
                    "false_positive_rate": 0.03,
                }
            },
        },
    )
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [
                {"address": "0x1"},
                {"address": "0x2"},
                {"address": "0x3"},
            ],
            "last_updated": "2026-03-08T08:55:00+00:00",
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
            {"market_id": "m2", "outcome": "lost"},
        ],
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="collected 12 items\n12 passed\n",
            stderr="",
        )

    monkeypatch.setattr("scripts.write_remote_cycle_status.subprocess.run", fake_run)

    written = write_remote_cycle_status(tmp_path, refresh_root_tests=True)

    root_test_snapshot = json.loads(
        (tmp_path / "reports" / "root_test_status.json").read_text()
    )
    payload = json.loads(Path(written["json"]).read_text())

    assert root_test_snapshot["status"] == "passing"
    assert root_test_snapshot["summary"] == "12 passed"
    assert payload["root_tests"]["status"] == "passing"
    assert payload["wallet_flow"]["ready"] is True
    assert payload["structural_gates"]["a6"]["status"] == "ready_for_shadow"
    assert payload["structural_gates"]["b1"]["status"] == "ready_for_shadow"


def test_write_remote_cycle_status_emits_runtime_truth_and_public_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T00:24:22+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
            "host": "ubuntu@example",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-09T00:26:41+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "22 passed in 3.49s",
            "output_tail": [
                "849 passed in 18.53s",
                "22 passed in 3.49s",
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [{"address": "0x1"}, {"address": "0x2"}],
            "last_updated": "2026-03-09T00:24:53+00:00",
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")
    _write_btc5_db(
        tmp_path / "data" / "btc_5min_maker.db",
        [
            {
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "UP",
                "order_price": 0.48,
                "trade_size_usd": 5.0016,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.4184,
                "created_at": "2026-03-09T13:14:59+00:00",
                "updated_at": "2026-03-09T13:15:00+00:00",
            }
        ],
    )
    _write_json(
        tmp_path / "reports" / "edge_scan_20260309T002925Z.json",
        {
            "generated_at": "2026-03-09T00:29:25+00:00",
            "recommended_action": "human_review_required",
            "action_reason": "Service is active while launch posture is still blocked.",
            "purpose": "edge_scan_and_fast_flow_restart_readiness",
        },
    )
    _write_json(
        tmp_path / "reports" / "pipeline_20260309T002002Z.json",
        {
            "report_generated_at": "2026-03-09T00:20:45+00:00",
            "run_timestamp": "2026-03-09T00:20:02+00:00",
            "pipeline_verdict": {
                "recommendation": "REJECT ALL",
                "reasoning": "All active hypotheses failed kill rules or expectancy tests.",
            },
            "verification": {
                "integrated_entrypoint_status": "passed",
                "make_test_status": "passed",
                "root_suite": "849 passed in 18.53s",
                "jj_live_import_boundary_suite": "22 passed in 3.49s",
            },
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-09T00:30:00+00:00",
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 0.0,
            "reserved_order_usd": 11.83,
            "live_orders_count": 2,
            "live_orders": [{"id": "o1"}, {"id": "o2"}],
            "open_positions_count": 5,
            "positions_initial_value_usd": 46.16,
            "positions_current_value_usd": 48.84,
            "positions_unrealized_pnl_usd": -0.33,
            "closed_positions_count": 2,
            "closed_positions_realized_pnl_usd": -1.49,
            "total_wallet_value_usd": 60.67,
            "warnings": ["closed_positions_fetch_failed:test"],
        },
    )

    written = write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    public_snapshot = json.loads(
        (tmp_path / "reports" / "public_runtime_snapshot.json").read_text()
    )
    timestamped = [
        path
        for path in (tmp_path / "reports").glob("runtime_truth_*.json")
        if path.name != "runtime_truth_latest.json"
    ]

    assert written["runtime_truth_latest"].endswith("reports/runtime_truth_latest.json")
    assert written["public_runtime_snapshot"].endswith("reports/public_runtime_snapshot.json")
    assert written["state_improvement_latest"].endswith("reports/state_improvement_latest.json")
    assert written["state_improvement_digest"].endswith("reports/state_improvement_digest.md")
    assert len(timestamped) == 1
    assert runtime_truth["summary"]["wallet_flow_status"] == "ready"
    assert runtime_truth["service"]["drift_detected"] is True
    assert runtime_truth["verification"]["summary"] == "849 passed in 18.53s; 22 passed in 3.49s"
    assert runtime_truth["latest_edge_scan"]["recommended_action"] == "human_review_required"
    assert runtime_truth["latest_pipeline"]["recommendation"] == "REJECT ALL"
    assert runtime_truth["polymarket_wallet"]["maker_address"] == "0xabc"
    assert runtime_truth["btc_5min_maker"]["live_filled_rows"] == 1
    assert runtime_truth["btc_5min_maker"]["fill_attribution"]["best_direction"]["label"] == "UP"
    assert runtime_truth["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    assert runtime_truth["reconciliation"]["btc_5min_maker"]["live_filled_pnl_usd"] == 5.4184
    assert runtime_truth["reconciliation"]["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    assert runtime_truth["reconciliation"]["polymarket_wallet"]["free_collateral_usd"] == 0.0
    assert runtime_truth["state_improvement"]["hourly_budget_progress"]["window_minutes"] == 60
    assert runtime_truth["state_improvement"]["per_venue_candidate_counts"]["polymarket"] >= 0
    assert isinstance(runtime_truth["state_improvement"]["reject_reasons"], list)
    assert runtime_truth["state_improvement"]["operator_digest"]
    assert runtime_truth["state_improvement"]["strategy_recommendations"]["btc5_edge_profile"]["best_direction"]["label"] == "UP"
    assert public_snapshot["snapshot_source"] == "reports/runtime_truth_latest.json"
    assert public_snapshot["service"]["status"] == "running"
    assert "host" not in public_snapshot["service"]
    assert public_snapshot["capital"]["polymarket_actual_deployable_usd"] == 0.0
    assert public_snapshot["polymarket_wallet"]["total_wallet_value_usd"] == 60.67
    assert public_snapshot["btc_5min_maker"]["live_filled_pnl_usd"] == 5.4184
    assert public_snapshot["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    assert public_snapshot["runtime"]["btc5_live_filled_rows"] == 1
    assert "maker_address" not in public_snapshot["polymarket_wallet"]
    assert public_snapshot["state_improvement"]["operator_digest"]
    assert any(
        "jj-live.service is running while launch posture remains blocked" in headline
        for headline in public_snapshot["operator_headlines"]
    )
    assert (tmp_path / "reports" / "state_improvement_latest.json").exists()
    assert (tmp_path / "reports" / "state_improvement_digest.md").exists()


def test_write_remote_cycle_status_emits_runtime_mode_reconciliation_artifact(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "jj_state.json",
        {
            "bankroll": 247.51,
            "total_deployed": 25.0,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "daily_pnl_date": "2026-03-09",
            "trades_today": 5,
            "total_trades": 5,
            "open_positions": {
                "m1": {},
                "m2": {},
                "m3": {},
                "m4": {},
            },
            "cycles_completed": 565,
            "b1_state": {"validation_accuracy": None},
        },
    )
    _write_json(
        tmp_path / "data" / "intel_snapshot.json",
        {
            "last_updated": "2026-03-09T11:25:12+00:00",
            "total_cycles": 565,
        },
    )
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T11:25:24+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
            "host": "ubuntu@example",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-09T11:31:50+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "1096 passed in 22.67s; 25 passed in 3.59s",
            "output_tail": [
                "1096 passed in 22.67s",
                "25 passed in 3.59s",
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [{"address": "0x1"}, {"address": "0x2"}],
            "last_updated": "2026-03-09T11:24:53+00:00",
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": None},
            {"market_id": "m2", "outcome": None},
            {"market_id": "m3", "outcome": None},
            {"market_id": "m4", "outcome": None},
            {"market_id": "m5", "outcome": None},
        ],
    )
    _write_text(tmp_path / ".env", "JJ_RUNTIME_PROFILE=maker_velocity_all_in\n")
    _write_text(
        tmp_path / ".env.example",
        "\n".join(
            [
                "JJ_RUNTIME_PROFILE=blocked_safe",
                "PAPER_TRADING=true",
                "",
            ]
        ),
    )
    _write_text(
        tmp_path / "reports" / "runtime_operator_overrides.env",
        "\n".join(
            [
                "JJ_MAX_POSITION_USD=247.51",
                "JJ_MAX_OPEN_POSITIONS=1",
                "JJ_YES_THRESHOLD=0.05",
                "JJ_NO_THRESHOLD=0.02",
                "",
            ]
        ),
    )
    _write_text(tmp_path / "README.md", "| Runtime state | `0` trades after `314` cycles |\n")
    _write_text(
        tmp_path / "PROJECT_INSTRUCTIONS.md",
        "Runtime remains `0` closed trades with `0` deployed capital after `314` cycles.\n",
    )
    _write_json(
        tmp_path / "reports" / "deploy_20260309T112719Z.json",
        {
            "generated_at": "2026-03-09T11:28:02+00:00",
            "remote_mode": {
                "remote_env_exists": True,
                "runtime_profile": "maker_velocity_all_in",
                "agent_run_mode": "shadow",
                "paper_trading": "false",
                "values": {
                    "ELASTIFUND_AGENT_RUN_MODE": "shadow",
                    "JJ_RUNTIME_PROFILE": "maker_velocity_all_in",
                    "PAPER_TRADING": "false",
                },
            },
            "pre_service": {
                "checked_at": "2026-03-09T11:27:23+00:00",
                "status": "running",
                "systemctl_state": "active",
            },
            "post_service": {
                "checked_at": "2026-03-09T11:28:02+00:00",
                "status": "running",
                "systemctl_state": "active",
            },
            "validation": {
                "status_command": {
                    "returncode": 0,
                    "stdout_tail": [
                        "  llm: active",
                        "  wallet_flow: active",
                        "  lmsr: active",
                        "  cross_platform_arb: disabled",
                        "",
                        "Open Positions:",
                        "  buy_yes $5.00 one",
                        "  buy_yes $5.00 two",
                        "  buy_yes $5.00 three",
                        "  buy_yes $10.00 four",
                        "",
                        "Last 5 trades:",
                        "  [2026-03-09T02:40:50] buy_yes",
                        "  [2026-03-09T02:40:51] buy_yes",
                        "  [2026-03-09T02:40:52] buy_yes",
                        "  [2026-03-09T02:40:53] buy_yes",
                        "  [2026-03-09T03:42:40] buy_yes",
                        "==================================================",
                    ],
                }
            },
        },
    )

    written = write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    public_snapshot = json.loads(
        (tmp_path / "reports" / "public_runtime_snapshot.json").read_text()
    )
    note_path = Path(written["runtime_mode_reconciliation_markdown"])

    assert note_path.exists()
    assert runtime_truth["remote_runtime_profile"] == "maker_velocity_all_in"
    assert runtime_truth["agent_run_mode"] == "shadow"
    assert runtime_truth["execution_mode"] == "shadow"
    assert runtime_truth["paper_trading"] is False
    assert runtime_truth["allow_order_submission"] is True
    assert runtime_truth["order_submit_enabled"] is False
    assert runtime_truth["launch_posture"] == "blocked"
    assert runtime_truth["restart_recommended"] is False
    assert runtime_truth["effective_caps"]["max_position_usd"] == 247.51
    assert runtime_truth["effective_thresholds"]["yes_threshold"] == 0.05
    assert runtime_truth["drift_flags"]["profile_override_drift"] is True
    assert runtime_truth["drift_flags"]["docs_stale"] is True
    assert runtime_truth["drift_flags"]["service_running_while_launch_blocked"] is True
    assert runtime_truth["mode_reconciliation"]["remote_probe"]["open_positions"] == 4
    assert runtime_truth["mode_reconciliation"]["remote_probe"]["last_trades"] == 5
    assert public_snapshot["runtime_mode"]["order_submit_enabled"] is False
    assert "- Order submit enabled: no" in note_path.read_text()


def test_write_remote_cycle_status_computes_state_improvement_deltas_from_previous_snapshot(
    tmp_path: Path,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": "2026-03-09T00:00:00+00:00",
            "state_improvement": {
                "metrics": {
                    "edge_reachability": 2.0,
                    "candidate_to_trade_conversion": 0.10,
                    "realized_expected_pnl_drift_usd": -1.0,
                }
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T00:24:22+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-09T00:26:41+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "22 passed in 3.49s",
            "output_tail": [
                "849 passed in 18.53s",
                "22 passed in 3.49s",
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_json(
        tmp_path / "reports" / "edge_scan_20260309T002925Z.json",
        {
            "generated_at": "2026-03-09T00:29:25+00:00",
            "recommended_action": "stay_paused",
            "action_reason": "No validated edge.",
            "candidate_markets": [],
            "cross_platform_arb": {"arb_opportunities": 0, "matches": 0},
            "threshold_sensitivity": {"current": {"yes": 0.15, "no": 0.05}},
        },
    )
    _write_json(
        tmp_path / "reports" / "pipeline_20260309T002002Z.json",
        {
            "report_generated_at": "2026-03-09T00:20:45+00:00",
            "pipeline_verdict": {
                "recommendation": "REJECT ALL",
                "reasoning": "No validated edge.",
            },
            "new_viable_strategies": [],
            "threshold_sensitivity": {
                "current": {"tradeable": 4, "yes_reachable_markets": 4, "no_reachable_markets": 2}
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "runtime_profile_effective.json",
        {
            "profile_name": "blocked_safe",
            "signal_thresholds": {"yes_threshold": 0.15, "no_threshold": 0.05},
            "market_filters": {"max_resolution_hours": 24.0},
            "risk_limits": {"hourly_notional_budget_usd": 50.0},
        },
    )

    write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    state_improvement = runtime_truth["state_improvement"]
    deltas = state_improvement["improvement_velocity"]["deltas"]

    assert deltas["edge_reachability_delta"] == 2.0
    assert deltas["candidate_to_trade_conversion_delta"] is None
    assert deltas["realized_expected_pnl_drift_delta_usd"] == 1.0
    assert state_improvement["hourly_budget_progress"]["cap_usd"] == 50.0
    assert state_improvement["improvement_velocity"]["previous_snapshot_generated_at"] == "2026-03-09T00:00:00+00:00"


def test_write_remote_cycle_status_overwrites_stale_remote_summary_artifact(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_cycle_status.json",
        {
            "generated_at": "2026-03-08T08:00:00+00:00",
            "runtime": {"cycles_completed": 3},
            "wallet_flow": {
                "status": "not_ready",
                "ready": False,
                "wallet_count": 0,
                "reasons": ["stale_remote_snapshot"],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T00:24:22+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-09T00:26:41+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "22 passed in 3.49s",
            "output_tail": [
                "849 passed in 18.53s",
                "22 passed in 3.49s",
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [{"address": "0x1"}],
            "last_updated": "2026-03-09T00:24:53+00:00",
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")

    written = write_remote_cycle_status(tmp_path)

    refreshed = json.loads(Path(written["json"]).read_text())
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())

    assert refreshed["runtime"]["cycles_completed"] == 16
    assert refreshed["wallet_flow"]["status"] == "ready"
    assert runtime_truth["reconciliation"]["cycles_completed"]["selected_value"] == 16
    assert runtime_truth["reconciliation"]["cycles_completed"]["selected_source"] == "jj_state.json"
    assert runtime_truth["wallet_flow"]["ready"] is True


def test_render_remote_cycle_status_markdown_includes_operator_truth(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "failing",
            "summary": "make test is still red.",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
        ],
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-09T12:31:00+00:00",
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 0.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 1,
            "positions_initial_value_usd": 5.0,
            "positions_current_value_usd": 4.5,
            "positions_unrealized_pnl_usd": -0.5,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": -1.49,
            "total_wallet_value_usd": 4.5,
            "warnings": ["positions_fetch_failed:test"],
        },
    )

    markdown = render_remote_cycle_status_markdown(build_remote_cycle_status(tmp_path))

    assert "- Service: stopped (inactive)" in markdown
    assert "- Root regression suite: failing" in markdown
    assert "- Wallet-flow bootstrap: not_ready" in markdown
    assert "- Closed trades: 1" in markdown
    assert "- Polymarket actual deployable USD: $0.00" in markdown
    assert "- Wallet status: ok" in markdown
    assert "- Realized PnL: $-1.49" in markdown
    assert "- A-6 gate: blocked" in markdown
    assert "- B-1 gate: blocked" in markdown
    assert "- Live launch blocked: yes" in markdown
    assert "Merge the root regression repair" in markdown


def test_bridge_pull_only_captures_service_snapshot_before_status(tmp_path: Path):
    project_dir = tmp_path / "project"
    bin_dir = tmp_path / "bin"
    project_dir.mkdir()
    (project_dir / "scripts").mkdir()
    (project_dir / "reports").mkdir()
    (project_dir / "data").mkdir()
    bin_dir.mkdir()

    key_path = tmp_path / "lightsail.pem"
    key_path.write_text("test-key")

    bridge_script = REPO_ROOT / "scripts" / "bridge.sh"
    trace_path = project_dir / "status_invocation.json"
    command_log = tmp_path / "bridge_commands.log"

    _write_text(
        project_dir / "scripts" / "write_remote_cycle_status.py",
        "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "root = Path(__file__).resolve().parents[1]",
                "payload = {",
                "    'service_snapshot_exists': (root / 'reports' / 'remote_service_status.json').exists(),",
                "    'jj_state_exists': (root / 'jj_state.json').exists(),",
                "}",
                f"Path({str(trace_path)!r}).write_text(json.dumps(payload, sort_keys=True))",
                "print(json.dumps({'ok': True}, sort_keys=True))",
            ]
        ),
    )
    _write_executable(
        bin_dir / "rsync",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "log = Path(os.environ['BRIDGE_TEST_COMMAND_LOG'])",
                "with log.open('a') as fh:",
                "    fh.write('rsync ' + ' '.join(sys.argv[1:]) + '\\n')",
                "dest = Path(sys.argv[-1])",
                "if ':' not in sys.argv[-1]:",
                "    (dest / 'data').mkdir(parents=True, exist_ok=True)",
                "    (dest / 'reports' / 'flywheel').mkdir(parents=True, exist_ok=True)",
                "    (dest / 'jj_state.json').write_text(json.dumps({",
                "        'bankroll': 247.51,",
                "        'total_deployed': 0.0,",
                "        'daily_pnl': 0.0,",
                "        'total_pnl': 0.0,",
                "        'daily_pnl_date': '2026-03-08',",
                "        'trades_today': 0,",
                "        'total_trades': 0,",
                "        'open_positions': {},",
                "        'cycles_completed': 16,",
                "    }, sort_keys=True))",
                "    (dest / 'data' / 'intel_snapshot.json').write_text(json.dumps({",
                "        'last_updated': '2026-03-08T08:53:32+00:00',",
                "        'total_cycles': 16,",
                "    }, sort_keys=True))",
                "    (dest / 'reports' / 'flywheel' / 'latest_sync.json').write_text(json.dumps({",
                "        'cycle_key': 'live-flywheel-20260308T085000Z',",
                "        'evaluated': 1,",
                "        'decisions': [{'decision': 'hold', 'reason_code': 'insufficient_evidence'}],",
                "        'artifacts': {},",
                "    }, sort_keys=True))",
            ]
        ),
    )
    _write_executable(
        bin_dir / "ssh",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "import sys",
                "from pathlib import Path",
                "log = Path(os.environ['BRIDGE_TEST_COMMAND_LOG'])",
                "with log.open('a') as fh:",
                "    fh.write('ssh ' + ' '.join(sys.argv[1:]) + '\\n')",
                "command = sys.argv[-1]",
                "if 'systemctl is-active jj-live.service' in command:",
                "    print('inactive')",
                "elif 'jj_state.json' in command:",
                "    print('  Bankroll: $247.51')",
                "    print('  Daily P&L: $0.00')",
                "    print('  Total P&L: $0.00')",
                "    print('  Open positions: 0')",
                "    print('  Total trades: 0')",
                "    print('  Cycles: 16')",
            ]
        ),
    )

    env = os.environ.copy()
    env["ELASTIFUND_PROJECT_DIR"] = str(project_dir)
    env["PYTHON_BIN"] = sys.executable
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["BRIDGE_TEST_COMMAND_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "bash",
            str(bridge_script),
            "--pull-only",
            "--skip-flywheel",
            "--key",
            str(key_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    service_status = json.loads(
        (project_dir / "reports" / "remote_service_status.json").read_text()
    )
    status_invocation = json.loads(trace_path.read_text())

    assert service_status["status"] == "stopped"
    assert service_status["systemctl_state"] == "inactive"
    assert status_invocation == {
        "jj_state_exists": True,
        "service_snapshot_exists": True,
    }


def _write_base_remote_state(root: Path) -> None:
    _write_json(
        root / "config" / "remote_cycle_status.json",
        {
            "capital_sources": [
                {"account": "Polymarket", "amount_usd": 247.51, "source": "jj_state.json"},
                {"account": "Kalshi", "amount_usd": 100.0, "source": "manual_tracked_balance"},
            ],
            "pull_policy": {
                "pull_cadence_minutes": 30,
                "full_cycle_cadence_minutes": 60,
                "freshness_sla_minutes": 45,
                "expected_next_data_note": "Expect the next synced dataset on the next 30-minute pull.",
                "manual_pull_triggers": ["Immediately before any deploy."],
            },
            "velocity_forecast": {
                "current_annualized_return_pct": 0.0,
                "next_target_annualized_return_pct": 10.0,
                "next_target_after_hours_of_work": 3.0,
            },
            "deployment_finish": {
                "status": "blocked",
                "eta": "TBD",
                "blockers": ["Need more evidence."],
                "exit_criteria": ["Collect closed trades."],
            },
        },
    )
    _write_json(
        root / "jj_state.json",
        {
            "bankroll": 247.51,
            "total_deployed": 0.0,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "daily_pnl_date": "2026-03-08",
            "trades_today": 0,
            "total_trades": 0,
            "open_positions": {},
            "cycles_completed": 16,
            "b1_state": {"validation_accuracy": None},
        },
    )
    _write_json(
        root / "data" / "intel_snapshot.json",
        {
            "last_updated": "2026-03-08T08:53:32+00:00",
            "total_cycles": 16,
        },
    )
    _write_json(
        root / "reports" / "flywheel" / "latest_sync.json",
        {
            "cycle_key": "live-flywheel-20260308T085000Z",
            "evaluated": 1,
            "decisions": [
                {
                    "decision": "hold",
                    "reason_code": "insufficient_evidence",
                    "notes": "Collect more closed trades before promoting.",
                }
            ],
            "artifacts": {
                "summary_md": "reports/flywheel/latest.md",
                "scorecard": "reports/flywheel/latest.json",
            },
        },
    )


def _write_trade_db(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trades (market_id TEXT, outcome TEXT)")
    conn.executemany(
        "INSERT INTO trades (market_id, outcome) VALUES (?, ?)",
        [(row["market_id"], row["outcome"]) for row in rows],
    )
    conn.commit()
    conn.close()


def _write_btc5_db(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER NOT NULL UNIQUE,
            window_end_ts INTEGER NOT NULL,
            slug TEXT NOT NULL,
            decision_ts INTEGER NOT NULL,
            direction TEXT,
            open_price REAL,
            current_price REAL,
            delta REAL,
            token_id TEXT,
            best_bid REAL,
            best_ask REAL,
            order_price REAL,
            trade_size_usd REAL,
            shares REAL,
            order_id TEXT,
            order_status TEXT NOT NULL,
            filled INTEGER,
            reason TEXT,
            resolved_side TEXT,
            won INTEGER,
            pnl_usd REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO window_trades (
            window_start_ts,
            window_end_ts,
            slug,
            decision_ts,
            direction,
            order_price,
            trade_size_usd,
            order_status,
            filled,
            pnl_usd,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["window_start_ts"],
                row["window_end_ts"],
                row["slug"],
                row["decision_ts"],
                row.get("direction"),
                row.get("order_price"),
                row.get("trade_size_usd"),
                row["order_status"],
                row.get("filled"),
                row.get("pnl_usd"),
                row["created_at"],
                row["updated_at"],
            )
            for row in rows
        ],
    )
    conn.commit()
    conn.close()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_executable(path: Path, text: str) -> None:
    _write_text(path, text)
    path.chmod(0o755)
