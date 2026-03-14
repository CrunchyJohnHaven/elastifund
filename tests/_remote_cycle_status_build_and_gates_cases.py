import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import _remote_cycle_status_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

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
    assert status["capital"]["polymarket_tracked_vs_observed_delta_usd"] == 206.49
    assert status["runtime"]["polymarket_live_orders"] == 2
    assert status["runtime"]["polymarket_open_positions"] == 3
    assert status["runtime"]["polymarket_closed_positions_realized_pnl_usd"] == -1.49
    assert status["accounting_reconciliation"]["unmatched_open_positions"]["delta_remote_minus_local"] == 0
    assert status["accounting_reconciliation"]["unmatched_closed_positions"]["delta_remote_minus_local"] == 0
    assert status["accounting_reconciliation"]["source_confidence_freshness"]["remote_wallet"]["confidence_score"] >= 0.5


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
    assert status["btc_5min_maker"]["source"] == "local_sqlite_db"
    assert status["btc_5min_maker"]["live_filled_rows"] == 3
    assert status["btc_5min_maker"]["live_filled_pnl_usd"] == 5.6231
    assert status["btc_5min_maker"]["estimated_maker_rebate_usd"] == pytest.approx(0.0468, abs=1e-4)
    assert status["btc_5min_maker"]["net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.6699, abs=1e-4)
    assert status["btc_5min_maker"]["fill_attribution"]["best_direction"]["label"] == "DOWN"
    assert status["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    assert status["btc_5min_maker"]["fill_attribution"]["recent_direction_regime"]["favored_direction"] == "DOWN"
    assert status["btc_5min_maker"]["fill_attribution"]["recent_direction_regime"]["weaker_direction"] == "UP"
    assert status["btc_5min_maker"]["fill_attribution"]["recent_direction_regime"]["triggered"] is False
    assert status["btc_5min_maker"]["intraday_live_summary"]["filled_rows_today"] == 3
    assert status["btc_5min_maker"]["intraday_live_summary"]["filled_pnl_usd_today"] == 5.6231
    assert status["btc_5min_maker"]["intraday_live_summary"]["estimated_maker_rebate_usd_today"] == pytest.approx(0.0468, abs=1e-4)
    assert status["btc_5min_maker"]["intraday_live_summary"]["net_pnl_after_estimated_rebate_usd_today"] == pytest.approx(5.6699, abs=1e-4)
    assert status["btc_5min_maker"]["intraday_live_summary"]["win_rate_today"] == 0.6667
    assert status["btc_5min_maker"]["intraday_live_summary"]["recent_5_pnl_usd"] == 5.6231
    assert status["btc_5min_maker"]["intraday_live_summary"]["recent_5_estimated_maker_rebate_usd"] == pytest.approx(0.0468, abs=1e-4)
    assert status["btc_5min_maker"]["intraday_live_summary"]["recent_5_net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.6699, abs=1e-4)
    assert status["btc_5min_maker"]["intraday_live_summary"]["recent_12_pnl_usd"] == 5.6231
    assert status["btc_5min_maker"]["intraday_live_summary"]["recent_12_estimated_maker_rebate_usd"] == pytest.approx(0.0468, abs=1e-4)
    assert status["btc_5min_maker"]["intraday_live_summary"]["recent_12_net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.6699, abs=1e-4)
    assert status["btc_5min_maker"]["intraday_live_summary"]["skip_price_count"] == 0
    assert status["btc_5min_maker"]["intraday_live_summary"]["order_failed_count"] == 0
    assert status["btc_5min_maker"]["intraday_live_summary"]["cancelled_unfilled_count"] == 0
    assert status["btc_5min_maker"]["intraday_live_summary"]["best_direction_today"]["label"] == "DOWN"
    assert status["btc_5min_maker"]["intraday_live_summary"]["best_price_bucket_today"]["label"] == "<0.49"
    assert status["runtime"]["btc5_live_filled_rows"] == 3
    assert status["runtime"]["btc5_latest_order_status"] == "live_filled"
    assert status["runtime"]["btc5_latest_trade_pnl_usd"] == 5.416
    assert status["runtime"]["btc5_estimated_maker_rebate_usd"] == pytest.approx(0.0468, abs=1e-4)
    assert status["runtime"]["btc5_net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.6699, abs=1e-4)
    assert status["runtime"]["btc5_latest_trade_estimated_maker_rebate_usd"] == pytest.approx(0.0156, abs=1e-4)
    assert status["runtime"]["btc5_latest_trade_net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.4316, abs=1e-4)
    assert status["runtime"]["btc5_source"] == "local_sqlite_db"
    assert status["runtime"]["btc5_best_direction"] == "DOWN"
    assert status["runtime"]["btc5_best_price_bucket"] == "<0.49"
    assert status["runtime"]["btc5_recent_live_filled_estimated_maker_rebate_usd"] == pytest.approx(0.0468, abs=1e-4)
    assert status["runtime"]["btc5_recent_live_filled_net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.6699, abs=1e-4)
    assert status["runtime"]["btc5_recent_regime_favored_direction"] == "DOWN"
    assert status["runtime"]["btc5_recent_regime_weaker_direction"] == "UP"
    assert status["runtime"]["btc5_recent_regime_triggered"] is False
    assert status["runtime"]["btc5_intraday_live_summary"]["filled_pnl_usd_today"] == 5.6231
    assert status["runtime"]["btc5_intraday_live_summary"]["estimated_maker_rebate_usd_today"] == pytest.approx(0.0468, abs=1e-4)


def test_resolve_authoritative_trade_totals_uses_strongest_observation() -> None:
    runtime = {
        "total_trades": 0,
        "trade_db_total_trades": 7,
        "closed_trades": 50,
        "open_positions": 5,
        "btc5_live_filled_rows": 176,
    }
    polymarket_wallet = {
        "status": "ok",
        "open_positions_count": 5,
        "closed_positions_count": 50,
    }
    btc5_maker = {"live_filled_rows": 176}

    _resolve_authoritative_trade_totals(
        runtime=runtime,
        polymarket_wallet=polymarket_wallet,
        btc5_maker=btc5_maker,
    )

    assert runtime["total_trades"] == 176
    assert "runtime.btc5_live_filled_rows" in runtime["total_trades_source"]
    assert runtime["total_trades_observations"]["runtime.trade_db_total_trades"] == 7
    assert runtime["total_trades_observations"]["wallet.open_plus_closed"] == 55


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
    assert status["runtime"]["btc5_source"] == "remote_sqlite_probe"


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


def test_build_remote_cycle_status_blocks_fast_flow_when_remote_storage_is_full(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [{"address": "0x1"}],
            "last_updated": now.isoformat(),
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")
    _write_json(
        tmp_path / "reports" / "deploy_20260310T204307Z.json",
        {
            "generated_at": now.isoformat(),
            "remote_mode": {
                "remote_env_exists": True,
                "runtime_profile": "blocked_safe",
                "agent_run_mode": "shadow",
                "paper_trading": "true",
                "values": {
                    "ELASTIFUND_AGENT_RUN_MODE": "shadow",
                    "JJ_RUNTIME_PROFILE": "blocked_safe",
                    "PAPER_TRADING": "true",
                },
            },
            "pre_service": {
                "checked_at": now.isoformat(),
                "status": "stopped",
                "systemctl_state": "inactive",
            },
            "post_service": {
                "checked_at": now.isoformat(),
                "status": "stopped",
                "systemctl_state": "inactive",
            },
            "validation": {
                "status_command": {
                    "returncode": 1,
                    "stderr_tail": [
                        "OSError: [Errno 28] No space left on device",
                    ],
                }
            },
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 10.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 10.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["deploy_evidence"]["validation"]["storage_blocked"] is True
    assert status["launch"]["fast_flow_restart_ready"] is False
    assert "remote_runtime_storage_blocked" in status["launch"]["blocked_checks"]
    assert status["launch"]["safe_baseline_profile"] == "blocked_safe"
    assert status["launch"]["safe_baseline_reason"] == "remote_runtime_storage_blocked"
    assert status["launch"]["next_operator_action"].startswith("hold_repair:")


def test_build_remote_cycle_status_blocks_when_remote_validation_incomplete(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [{"address": "0x1"}],
            "last_updated": now.isoformat(),
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")
    _write_json(
        tmp_path / "reports" / "deploy_20260310T204307Z.json",
        {
            "generated_at": now.isoformat(),
            "remote_mode": {
                "remote_env_exists": True,
                "runtime_profile": "blocked_safe",
                "agent_run_mode": "shadow",
                "paper_trading": "true",
                "values": {
                    "ELASTIFUND_AGENT_RUN_MODE": "shadow",
                    "JJ_RUNTIME_PROFILE": "blocked_safe",
                    "PAPER_TRADING": "true",
                },
            },
            "pre_service": {
                "checked_at": now.isoformat(),
                "status": "stopped",
                "systemctl_state": "inactive",
            },
            "post_service": {
                "checked_at": now.isoformat(),
                "status": "stopped",
                "systemctl_state": "inactive",
            },
            "validation": {
                "status_command": {
                    "returncode": 1,
                    "stderr_tail": [
                        "Runtime validation command timed out before completion.",
                    ],
                }
            },
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 10.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 10.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["deploy_evidence"]["validation"]["storage_blocked"] is False
    assert "remote_runtime_validation_incomplete" in status["launch"]["blocked_checks"]
    assert any(
        "launch-control truth is not confirmed" in reason
        for reason in status["launch"]["blocked_reasons"]
    )
    assert status["launch"]["next_operator_action"].startswith("hold_repair:")


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
        tmp_path / "reports" / "runtime" / "runtime_truth" / "runtime_truth_20260309T130303Z.json",
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
        == "reports/runtime/runtime_truth/runtime_truth_20260309T130303Z.json"
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


def test_build_remote_cycle_status_uses_fresh_wallet_export_precedence_for_btc5_stage_truth(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale_probe_time = now - timedelta(hours=10)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": stale_probe_time.isoformat(),
                "updated_at": stale_probe_time.isoformat(),
            }
        ],
    )
    _write_text(
        tmp_path / "data" / "Polymarket-History-2026-03-10.csv",
        "\n".join(
            [
                "timestamp,market,status,cashflow_usd,portfolio_equity_usd,cumulative_closed_cashflow_usd,open_notional_usd,open_buy_notional_usd",
                f"{(now - timedelta(hours=1)).isoformat()},BTC Up or Down 5m,closed,42.50,320.00,42.50,0.00,0.00",
            ]
        ),
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "wallet_export_freshness_hours": 1.0,
                "probe_freshness_hours": 10.0,
                "blocking_checks": [
                    "stage_upgrade_probe_stale",
                    "insufficient_trailing_120_live_fills",
                ],
                "reasons": [
                    "Wallet export is fresh enough to allow bounded stage 1.",
                    "Probe freshness still blocks stage 2 and above.",
                ],
            },
            "next_1000_usd": {
                "status": "ready_scale",
                "recommended_amount_usd": 1000,
                "stage_readiness": {
                    "recommended_stage": 1,
                },
                "source_artifacts": ["reports/btc5_autoresearch/latest.json"],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": False,
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 120.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 42.5,
            "total_wallet_value_usd": 120.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)
    wallet_reporting = next(
        item
        for item in status["source_precedence"]["fields"]
        if item["field"] == "wallet_reporting"
    )
    contradiction_codes = {
        item["code"] for item in status["source_precedence"]["contradictions"]
    }

    assert wallet_reporting["selected_value"] == "wallet_export"
    assert wallet_reporting["selected_source"].endswith("Polymarket-History-2026-03-10.csv")
    assert "wallet_export_fresher_than_btc5_probe" in contradiction_codes
    assert status["btc5_stage_readiness"]["can_trade_now"] is True
    assert status["btc5_stage_readiness"]["allowed_stage"] == 1
    assert status["deployment_confidence"]["next_required_artifact"] == (
        "reports/btc5_autoresearch_current_probe/latest.json"
    )


def test_build_remote_cycle_status_flags_stale_service_snapshot_when_btc5_probe_is_fresh(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": (now - timedelta(hours=8)).isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ],
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": [],
                "reasons": ["Bounded stage 1 is allowed."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": True,
                "confirmation_coverage_score": 0.8,
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 250.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)
    contradiction_codes = {
        item["code"] for item in status["source_precedence"]["contradictions"]
    }

    assert "stale_service_file_with_fresh_btc5_probe" in contradiction_codes
    assert status["deployment_confidence"]["can_btc5_trade_now"] is False
    assert "service_status_stale" in status["deployment_confidence"]["stage_1_blockers"]
    assert (
        "stale_service_file_with_fresh_btc5_probe"
        in status["deployment_confidence"]["stage_1_blockers"]
    )
    assert "stale_service_file_with_fresh_btc5_probe" in status["deployment_confidence"]["warning_checks"]
    assert status["deployment_confidence"]["next_required_artifact"] == (
        "reports/remote_service_status.json"
    )
    champion = status["champion_lane_contract"]
    assert champion["status"] == "hold_repair"
    assert "service_status_stale" in champion["blocker_classes"]["truth"]["checks"]
    assert champion["blocker_classes"]["truth"]["status"] == "blocked"


def test_build_remote_cycle_status_prefers_fresh_btc5_service_status_artifact(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale_checked_at = now - timedelta(hours=4)
    fresh_checked_at = now - timedelta(minutes=10)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": stale_checked_at.isoformat(),
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_remote_service_status.json",
        {
            "checked_at": fresh_checked_at.isoformat(),
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
            "service_name": "btc-5min-maker.service",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": fresh_checked_at.isoformat(),
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
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": fresh_checked_at.isoformat(),
                "updated_at": fresh_checked_at.isoformat(),
            }
        ],
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": fresh_checked_at.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": [],
                "reasons": ["Bounded stage 1 is allowed."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": fresh_checked_at.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": True,
                "confirmation_coverage_score": 0.8,
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=fresh_checked_at)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": fresh_checked_at.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 250.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)
    contradiction_codes = {
        item["code"] for item in status["source_precedence"]["contradictions"]
    }

    assert status["service"]["source"] == "reports/btc5_remote_service_status.json"
    assert status["deployment_confidence"]["service_status_freshness"] == "fresh"
    assert "service_status_stale" not in status["deployment_confidence"]["stage_1_blockers"]
    assert "stale_service_file_with_fresh_btc5_probe" not in contradiction_codes


def test_build_remote_cycle_status_blocks_live_when_selected_package_is_not_loaded(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ],
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": [],
                "reasons": ["Bounded stage 1 is allowed."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": True,
                "confirmation_coverage_score": 0.8,
            },
        },
    )
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        promoted_package_selected=False,
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 250.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["btc5_stage_readiness"]["can_trade_now"] is True
    assert status["deployment_confidence"]["can_btc5_trade_now"] is False
    assert status["deployment_confidence"]["validated_package"]["validated_for_live_stage1"] is False
    assert "validated_runtime_package_not_loaded" in status["deployment_confidence"]["blocking_checks"]
    assert status["deployment_confidence"]["next_required_artifact"] == "reports/btc5_autoresearch/latest.json"


def test_build_remote_cycle_status_points_to_stale_confirmation_source_artifact(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": [],
                "reasons": ["Bounded stage 1 is allowed."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": False,
                "confirmation_coverage_score": 0.8,
                "confirmation_freshness_label": "stale",
                "confirmation_stale_sources": ["wallet_flow"],
                "confirmation_next_required_artifact": "data/wallet_scores.db",
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 250.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["deployment_confidence"]["can_btc5_trade_now"] is False
    assert status["deployment_confidence"]["confidence_label"] == "low"
    assert status["deployment_confidence"]["confirmation_evidence_score"] == 0.25
    assert "confirmation_evidence_stale" in status["deployment_confidence"]["blocking_checks"]
    assert status["deployment_confidence"]["next_required_artifact"] == "data/wallet_scores.db"


def test_load_btc5_selected_package_summary_does_not_require_runtime_load_for_hold_package(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        deploy_recommendation="hold",
        confidence_label="medium",
        promoted_package_selected=False,
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert "validated_runtime_package_not_loaded" not in summary["blocking_checks"]
    assert "runtime_package_load_pending" not in summary["blocking_checks"]
    assert "selected_runtime_package_not_promote" in summary["blocking_checks"]
    assert summary["runtime_load_required"] is False


def test_load_btc5_selected_package_summary_requires_runtime_load_for_promote_package(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        deploy_recommendation="promote",
        confidence_label="high",
        promoted_package_selected=False,
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert "runtime_package_load_pending" in summary["blocking_checks"]
    assert "validated_runtime_package_not_loaded" in summary["blocking_checks"]
    assert summary["runtime_load_required"] is True


def test_load_btc5_selected_package_summary_marks_shadow_winner_as_stage1_live_candidate(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        deploy_recommendation="shadow_only",
        confidence_label="high",
        validation_live_filled_rows=205,
        generalization_ratio=1.0099,
        promoted_package_selected=False,
        selected_active_profile_name="current_live_profile",
        selected_best_profile_name="active_profile",
        frontier_gap_vs_incumbent=1246.7435,
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert summary["selected_best_profile_name"] == "active_profile"
    assert summary["selected_active_profile_name"] == "current_live_profile"
    assert summary["stage1_live_candidate"] is True
    assert "selected_runtime_package_not_promote" not in summary["blocking_checks"]


def test_load_btc5_selected_package_summary_marks_runtime_loaded_from_override_env(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        deploy_recommendation="shadow_only",
        confidence_label="high",
        validation_live_filled_rows=205,
        generalization_ratio=1.0099,
        promoted_package_selected=False,
        selected_active_profile_name="current_live_profile",
        selected_best_profile_name="active_profile",
        frontier_gap_vs_incumbent=1246.7435,
    )
    _write_text(
        tmp_path / "state" / "btc5_autoresearch.env",
        "\n".join(
            [
                "# Managed by scripts/run_btc5_autoresearch_cycle.py",
                "# candidate=active_profile",
                "BTC5_MAX_ABS_DELTA=0.00015",
                "",
            ]
        ),
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert summary["runtime_package_loaded"] is True
    assert summary["runtime_load_required"] is False
    assert summary["promoted_package_selected"] is True
    assert summary["runtime_load_evidence_source"] == "state/btc5_autoresearch.env"
    assert "runtime_package_load_pending" not in summary["blocking_checks"]
    assert "validated_runtime_package_not_loaded" not in summary["blocking_checks"]


def test_load_btc5_selected_package_summary_keeps_loaded_override_as_stage1_live_candidate(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        deploy_recommendation="shadow_only",
        confidence_label="high",
        validation_live_filled_rows=214,
        generalization_ratio=1.0142,
        promoted_package_selected=False,
        selected_active_profile_name="current_live_profile",
        selected_best_profile_name="active_profile",
        frontier_gap_vs_incumbent=0.0,
    )
    _write_text(
        tmp_path / "state" / "btc5_autoresearch.env",
        "\n".join(
            [
                "# Managed by scripts/run_btc5_autoresearch_cycle.py",
                "# candidate=active_profile",
                "BTC5_MAX_ABS_DELTA=0.00015",
                "",
            ]
        ),
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert summary["runtime_package_loaded"] is True
    assert summary["stage1_live_candidate"] is True
    assert summary["validated_for_live_stage1"] is True
    assert "selected_runtime_package_not_promote" not in summary["blocking_checks"]


def test_load_btc5_selected_package_summary_prefers_live_promoted_policy_package_when_cycle_is_stale(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale_generated_at = now - timedelta(hours=12)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=stale_generated_at,
        deploy_recommendation="shadow_only",
        confidence_label="high",
        validation_live_filled_rows=212,
        generalization_ratio=1.0047,
        promoted_package_selected=False,
        selected_active_profile_name="current_live_profile",
        selected_best_profile_name="active_profile",
        frontier_gap_vs_incumbent=0.0,
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "updated_at": now.isoformat(),
            "selected_active_runtime_package": {
                "profile": {
                    "name": "active_profile",
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
            "live_package": {
                "generated_at": now.isoformat(),
                "deploy_recommendation": "shadow_only",
                "promotion_state": "live_promoted",
                "runtime_package": {
                    "profile": {
                        "name": "active_profile_probe_d0_00075",
                        "max_abs_delta": 0.00075,
                        "up_max_buy_price": 0.49,
                        "down_max_buy_price": 0.51,
                    },
                    "session_policy": [],
                },
                "confidence_summary": {
                    "fold_count": 4,
                    "confidence_method": "bootstrap_mean_fold_policy_loss_v1",
                },
                "source_artifact": "reports/parallel/btc5_probe_cycle_d0_00075.json",
            },
            "candidate_vs_incumbent_summary": {
                "mean_fold_loss_improvement": 404.072,
            },
        },
    )
    _write_text(
        tmp_path / "state" / "btc5_autoresearch.env",
        "\n".join(
            [
                "# Managed by scripts/run_btc5_autoresearch_cycle.py",
                "# candidate=active_profile_probe_d0_00075",
                "BTC5_MAX_ABS_DELTA=0.00075",
                "",
            ]
        ),
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert summary["path"] == "reports/autoresearch/btc5_policy/latest.json"
    assert summary["selected_best_profile_name"] == "active_profile_probe_d0_00075"
    assert summary["selected_active_profile_name"] == "active_profile"
    assert summary["selected_policy_id"] == "active_profile_probe_d0_00075"
    assert summary["promotion_state"] == "live_promoted"
    assert summary["selected_best_runtime_package"]["profile"]["name"] == "active_profile_probe_d0_00075"
    assert summary["runtime_package_loaded"] is True
    assert summary["validated_for_live_stage1"] is True
    assert summary["selection_source"] == "reports/parallel/btc5_probe_cycle_d0_00075.json"
    assert "selected_runtime_package_stale" not in summary["blocking_checks"]
    assert "validated_runtime_package_not_loaded" not in summary["blocking_checks"]


def test_load_btc5_selected_package_summary_canonicalizes_matching_live_alias_to_policy_champion(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_validated_btc5_package(
        tmp_path,
        generated_at=now,
        deploy_recommendation="shadow_only",
        confidence_label="high",
        validation_live_filled_rows=212,
        generalization_ratio=1.0047,
        promoted_package_selected=False,
        selected_active_profile_name="current_live_profile",
        selected_best_profile_name="current_live_profile",
        frontier_gap_vs_incumbent=0.0,
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "updated_at": now.isoformat(),
            "selected_active_runtime_package": {
                "profile": {
                    "name": "current_live_profile",
                    "max_abs_delta": 0.00075,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
            "champion": {
                "policy_id": "active_profile_probe_d0_00075",
                "promotion_state": "shadow_updated",
                "runtime_package": {
                    "profile": {
                        "name": "active_profile_probe_d0_00075",
                        "max_abs_delta": 0.00075,
                        "up_max_buy_price": 0.49,
                        "down_max_buy_price": 0.51,
                    },
                    "session_policy": [],
                },
                "source_artifact": "reports/parallel/btc5_probe_cycle_d0_00075.json",
            },
            "live_package": {
                "generated_at": now.isoformat(),
                "deploy_recommendation": "shadow_only",
                "promotion_state": "live_current",
                "policy_id": "current_live_profile",
                "runtime_package": {
                    "profile": {
                        "name": "current_live_profile",
                        "max_abs_delta": 0.00075,
                        "up_max_buy_price": 0.49,
                        "down_max_buy_price": 0.51,
                    },
                    "session_policy": [],
                },
                "confidence_summary": {
                    "fold_count": 4,
                    "confidence_method": "bootstrap_mean_fold_policy_loss_v1",
                },
                "source_artifact": "state/btc5_autoresearch.env",
            },
            "candidate_vs_incumbent_summary": {
                "mean_fold_loss_improvement": 404.072,
            },
        },
    )
    _write_text(
        tmp_path / "state" / "btc5_autoresearch.env",
        "\n".join(
            [
                "# Managed by scripts/run_btc5_autoresearch_cycle.py",
                "# candidate=active_profile_probe_d0_00075",
                "BTC5_MAX_ABS_DELTA=0.00075",
                "",
            ]
        ),
    )

    summary = _load_btc5_selected_package_summary(root=tmp_path, generated_at=now)

    assert summary["path"] == "reports/autoresearch/btc5_policy/latest.json"
    assert summary["selected_best_profile_name"] == "active_profile_probe_d0_00075"
    assert summary["selected_active_profile_name"] == "active_profile_probe_d0_00075"
    assert summary["selected_policy_id"] == "active_profile_probe_d0_00075"
    assert summary["promotion_state"] == "live_current"
    assert summary["selected_best_runtime_package"]["profile"]["name"] == "active_profile_probe_d0_00075"
    assert summary["runtime_package_loaded"] is True
    assert summary["selection_source"] == "reports/parallel/btc5_probe_cycle_d0_00075.json"
    assert "validated_runtime_package_not_loaded" not in summary["blocking_checks"]


def test_build_remote_cycle_status_blocks_live_when_confirmation_strength_is_weak(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ],
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": [],
                "reasons": ["Bounded stage 1 is allowed."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": True,
                "wallet_flow_archive_confirmation_ready": True,
                "btc_fast_window_confirmation_ready": True,
                "confirmation_support_status": "ready",
                "confirmation_coverage_score": 0.8,
                "confirmation_coverage_label": "strong",
                "confirmation_strength_score": 0.2,
                "confirmation_strength_label": "weak",
                "confirmation_freshness_label": "fresh",
                "confirmation_sources_ready": ["wallet_flow"],
                "best_confirmation_source": "wallet_flow",
                "confirmation_contradiction_penalty": 0.45,
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 250.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["btc5_stage_readiness"]["can_trade_now"] is True
    assert status["deployment_confidence"]["can_btc5_trade_now"] is False
    assert status["deployment_confidence"]["confidence_label"] == "low"
    assert status["deployment_confidence"]["confirmation_coverage_score"] == 0.8
    assert status["deployment_confidence"]["confirmation_evidence_score"] == 0.2
    assert status["deployment_confidence"]["confirmation_strength_label"] == "weak"
    assert status["deployment_confidence"]["best_confirmation_source"] == "wallet_flow"
    assert "confirmation_coverage_insufficient" in status["deployment_confidence"]["blocking_checks"]
    assert status["deployment_confidence"]["next_required_artifact"] == "reports/signal_source_audit.json"


def test_build_remote_cycle_status_flags_stage1_not_ready_when_local_ledger_drifts(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "jj_state.json",
        {
            "bankroll": 250.0,
            "total_deployed": 25.0,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "daily_pnl_date": "2026-03-10",
            "trades_today": 1,
            "total_trades": 1,
            "open_positions": {"btc-window-1": {"direction": "DOWN"}},
            "cycles_completed": 16,
            "b1_state": {"validation_accuracy": None},
        },
    )
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": now.isoformat(),
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
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
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
        ],
    )
    _write_btc5_db(
        tmp_path / "data" / "btc_5min_maker.db",
        [
            {
                "window_start_ts": 1773061800,
                "window_end_ts": 1773062100,
                "slug": "btc-updown-5m-1773061800",
                "decision_ts": 1773062099,
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ],
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "stage_readiness": {
                "recommended_stage": 1,
                "ready_for_stage_1": True,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": [],
                "reasons": ["Bounded stage 1 is allowed while higher stages remain closed."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": True,
                "confirmation_coverage_score": 0.8,
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 230.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 2,
            "positions_initial_value_usd": 20.0,
            "positions_current_value_usd": 22.0,
            "positions_unrealized_pnl_usd": 2.0,
            "closed_positions_count": 15,
            "closed_positions_realized_pnl_usd": 18.0,
            "total_wallet_value_usd": 252.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)
    contradiction_codes = {
        item["code"] for item in status["source_precedence"]["contradictions"]
    }

    assert status["btc5_stage_readiness"]["can_trade_now"] is True
    assert status["deployment_confidence"]["can_btc5_trade_now"] is False
    assert status["deployment_confidence"]["accounting_coherence_score"] < 1.0
    assert status["deployment_confidence"]["overall_score"] < 1.0
    assert "accounting_reconciliation_drift" in status["deployment_confidence"]["stage_1_blockers"]
    assert "local_ledger_drift_vs_remote_wallet" in contradiction_codes
    assert status["deployment_confidence"]["next_required_artifact"] == "data/jj_trades.db"


def test_build_remote_cycle_status_service_reconciled_but_accounting_mismatched(tmp_path: Path, monkeypatch):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T13:20:00+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-09T13:21:00+00:00",
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
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [{"market_id": "m1", "outcome": None}],
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-09T13:22:00+00:00",
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 10.0,
            "reserved_order_usd": 5.0,
            "live_orders_count": 1,
            "live_orders": [],
            "open_positions_count": 4,
            "positions_initial_value_usd": 25.0,
            "positions_current_value_usd": 24.0,
            "positions_unrealized_pnl_usd": -1.0,
            "closed_positions_count": 3,
            "closed_positions_realized_pnl_usd": 2.0,
            "total_wallet_value_usd": 39.0,
            "warnings": [],
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["service"]["status"] == "stopped"
    assert status["launch"]["live_launch_blocked"] is True
    assert "accounting_reconciliation_drift" not in status["launch"]["blocked_checks"]
    assert "no_closed_trades" not in status["launch"]["blocked_checks"]
    assert "no_deployed_capital" not in status["launch"]["blocked_checks"]
    assert status["runtime_truth"]["service_drift_detected"] is False
    assert status["runtime_truth"]["accounting_drift_detected"] is False
