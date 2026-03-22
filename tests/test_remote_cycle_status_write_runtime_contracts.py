import json
import sys
from pathlib import Path
from types import SimpleNamespace

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import _remote_cycle_status_shared as _shared
import scripts.remote_cycle_status_core as remote_cycle_status_core  # noqa: E402
import scripts.write_remote_cycle_status as remote_cycle_status  # noqa: E402
from scripts.write_remote_cycle_status import (  # noqa: E402
    _apply_shared_truth_contract_to_status,
    _load_latest_deploy_evidence,
    _prepare_local_runtime_profile_evidence,
    build_runtime_mode_reconciliation,
)

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})


def test_load_latest_deploy_evidence_prefers_btc5_activation_report(tmp_path: Path) -> None:
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "deploy_20260309T112719Z.json",
        {
            "generated_at": "2026-03-09T11:28:02+00:00",
            "remote_mode": {
                "remote_env_exists": True,
                "runtime_profile": "shadow_fast_flow",
                "agent_run_mode": "shadow",
                "paper_trading": "true",
                "values": {
                    "ELASTIFUND_AGENT_RUN_MODE": "shadow",
                    "JJ_RUNTIME_PROFILE": "shadow_fast_flow",
                    "PAPER_TRADING": "true",
                },
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_deploy_activation.json",
        {
            "checked_at": "2026-03-12T00:56:04+00:00",
            "deploy_mode": "live_stage1",
            "paper_trading": False,
            "runtime_profile": "maker_velocity_live",
            "service_status": "running",
            "verification_checks": {
                "required_passed": True,
                "failed_required_checks": [],
            },
            "status_summary": {
                "fills": 2,
            },
            "override_env": {
                "exists": True,
                "tracked_values": {
                    "BTC5_PAPER_TRADING": "false",
                    "BTC5_CAPITAL_STAGE": "1",
                },
            },
        },
    )

    evidence = _load_latest_deploy_evidence(tmp_path)

    assert evidence["path"] == "reports/btc5_deploy_activation.json"
    assert evidence["remote_runtime_profile"] == "maker_velocity_live"
    assert evidence["agent_run_mode"] == "live"
    assert evidence["paper_trading"] is False
    assert evidence["remote_values"]["JJ_RUNTIME_PROFILE"] == "maker_velocity_live"
    assert evidence["remote_values"]["PAPER_TRADING"] == "false"
    assert evidence["remote_values"]["ELASTIFUND_AGENT_RUN_MODE"] == "live"
    assert evidence["deploy_mode"] == "live_stage1"
    assert evidence["required_passed"] is True
    assert evidence["verification_checks"]["required_passed"] is True
    assert evidence["process_state"] == "activation_verified"
    assert evidence["validation"]["returncode"] == 0


def test_prepare_local_runtime_profile_evidence_merges_stage_env_override(tmp_path: Path) -> None:
    _write_base_remote_state(tmp_path)
    _write_text(
        tmp_path / ".env",
        "\n".join(
            [
                "JJ_RUNTIME_PROFILE=maker_velocity_live",
                "PAPER_TRADING=true",
                "",
            ]
        ),
    )
    _write_text(tmp_path / ".env.example", "JJ_RUNTIME_PROFILE=blocked_safe\n")
    _write_text(
        tmp_path / "state" / "btc5_capital_stage.env",
        "\n".join(
            [
                "BTC5_DEPLOY_MODE=live_stage1",
                "BTC5_PAPER_TRADING=false",
                "",
            ]
        ),
    )

    evidence = _prepare_local_runtime_profile_evidence(tmp_path)

    assert evidence["merged_env"]["PAPER_TRADING"] == "false"
    assert evidence["capital_stage_env"]["BTC5_DEPLOY_MODE"] == "live_stage1"
    assert evidence["bundle"].config["mode"]["paper_trading"] is False


def test_build_runtime_mode_reconciliation_keeps_live_profile_for_bounded_stage1(
    tmp_path: Path,
) -> None:
    _write_base_remote_state(tmp_path)
    _write_text(
        tmp_path / ".env",
        "\n".join(
            [
                "JJ_RUNTIME_PROFILE=maker_velocity_live",
                "PAPER_TRADING=false",
                "",
            ]
        ),
    )
    _write_text(tmp_path / ".env.example", "JJ_RUNTIME_PROFILE=blocked_safe\n")
    _write_text(
        tmp_path / "state" / "btc5_capital_stage.env",
        "\n".join(
            [
                "BTC5_DEPLOY_MODE=live_stage1",
                "BTC5_PAPER_TRADING=false",
                "",
            ]
        ),
    )
    _write_json(
        tmp_path / "reports" / "btc5_deploy_activation.json",
        {
            "checked_at": "2026-03-12T00:56:04+00:00",
            "deploy_mode": "live_stage1",
            "paper_trading": False,
            "runtime_profile": "maker_velocity_live",
            "service_status": "running",
            "verification_checks": {
                "required_passed": True,
                "failed_required_checks": [],
            },
            "override_env": {
                "exists": True,
                "tracked_values": {
                    "BTC5_PAPER_TRADING": "false",
                },
            },
        },
    )
    runtime_profile_refresh = _prepare_local_runtime_profile_evidence(tmp_path)

    reconciliation = build_runtime_mode_reconciliation(
        tmp_path,
        status={
            "launch": {
                "live_launch_blocked": True,
                "blocked_checks": ["no_closed_trades"],
                "safe_baseline_profile": "shadow_fast_flow",
                "safe_baseline_reason": "fast_flow_restart_ready",
            },
            "service": {"status": "running"},
        },
        runtime_truth_snapshot={
            "generated_at": "2026-03-12T00:56:04+00:00",
            "finance_gate": {"finance_gate_pass": True},
            "btc5_selected_package": {"stage1_live_candidate": True},
        },
        runtime_profile_refresh=runtime_profile_refresh,
        runtime_mode_reconciliation_path=tmp_path / "reports" / "runtime_mode_reconciliation.md",
    )

    assert reconciliation["effective_runtime_profile"] == "maker_velocity_live"
    assert reconciliation["execution_mode"] == "live"
    assert reconciliation["paper_trading"] is False
    assert reconciliation["launch_guard"]["bounded_stage1_live_override"] is True
    assert reconciliation["remote_runtime_profile"] == "maker_velocity_live"
    assert reconciliation["agent_run_mode"] == "live"


def test_build_launch_status_treats_broad_root_test_failures_as_advisory_when_runtime_validation_passes() -> None:
    launch = remote_cycle_status._build_launch_status(
        status={
            "runtime": {"closed_trades": 0},
            "flywheel": {},
            "capital": {
                "deployed_capital_usd": 25.0,
                "polymarket_actual_deployable_usd": 100.0,
            },
            "polymarket_wallet": {"status": "ok"},
        },
        service={"status": "running", "systemctl_state": "active"},
        root_tests={
            "status": "failing",
            "summary": "50 failed, 1957 passed in a broad repo sweep",
        },
        wallet_flow={"ready": True, "reasons": []},
        a6_gate={},
        b1_gate={},
        accounting_reconciliation={"drift_detected": False},
        deploy_evidence={"validation": {"required_passed": True}},
    )

    assert "root_tests_not_passing" not in launch["blocked_checks"]
    assert launch["fast_flow_restart_ready"] is True
    assert not launch["next_operator_action"].startswith(
        "Merge the root regression repair"
    )


def test_apply_shared_truth_contract_to_status_backfills_btc5_compatibility_flags() -> None:
    status = _apply_shared_truth_contract_to_status(
        {
            "service_name": "btc-5min-maker.service",
        },
        runtime_truth_snapshot={
            "state_permissions": {
                "baseline_live_allowed": True,
                "stage_upgrade_allowed": False,
                "capital_expansion_allowed": False,
            },
            "operator_verdict": {
                "baseline_live_allowed": True,
                "stage_upgrade_allowed": False,
                "capital_expansion_allowed": False,
            },
        },
    )

    assert status["baseline_live_allowed"] is True
    assert status["stage_upgrade_allowed"] is False
    assert status["capital_expansion_allowed"] is False
    assert status["can_btc5_trade_now"] is True
    assert status["btc5_baseline_live_allowed"] is True
    assert status["btc5_stage_upgrade_can_trade_now"] is False


def test_load_btc5_maker_state_materializes_remote_window_row_cache(
    tmp_path: Path, monkeypatch
) -> None:
    _write_text(
        tmp_path / ".env",
        "\n".join(
            [
                "LIGHTSAIL_KEY=/tmp/fake-lightsail.pem",
                "VPS_IP=127.0.0.1",
                "VPS_USER=ubuntu",
                "",
            ]
        ),
    )
    payload = {
        "status": "ok",
        "checked_at": "2026-03-13T18:00:00+00:00",
        "latest_trade": {
            "id": 11,
            "window_start_ts": 1773421200,
            "direction": "UP",
            "order_status": "live_filled",
            "trade_size_usd": 8.5,
            "updated_at": "2026-03-13T18:00:00+00:00",
        },
        "recent_window_rows": [
            {
                "id": 10,
                "window_start_ts": 1773420900,
                "direction": "DOWN",
                "order_status": "skip_delta_too_large",
                "updated_at": "2026-03-13T17:55:00+00:00",
            },
            {
                "id": 11,
                "window_start_ts": 1773421200,
                "direction": "UP",
                "order_status": "live_filled",
                "trade_size_usd": 8.5,
                "updated_at": "2026-03-13T18:00:00+00:00",
            },
        ],
        "recent_live_filled": [
            {
                "id": 11,
                "window_start_ts": 1773421200,
                "direction": "UP",
                "order_status": "live_filled",
                "trade_size_usd": 8.5,
                "updated_at": "2026-03-13T18:00:00+00:00",
            }
        ],
        "live_filled_rows": 1,
        "live_filled_pnl_usd": 1.2,
    }

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(remote_cycle_status.subprocess, "run", fake_run)
    monkeypatch.setattr(remote_cycle_status_core.subprocess, "run", fake_run)

    observed = remote_cycle_status_core._load_btc5_maker_state(tmp_path)
    cached_rows = json.loads((tmp_path / "reports" / "tmp_remote_btc5_window_rows.json").read_text())
    conn = sqlite3.connect(tmp_path / "data" / "btc_5min_maker.db")
    try:
        mirrored_rows = conn.execute(
            """
            SELECT window_start_ts, window_end_ts, decision_ts, order_status, trade_size_usd
            FROM window_trades
            ORDER BY window_start_ts ASC
            """
        ).fetchall()
    finally:
        conn.close()
    ledger_conn = sqlite3.connect(tmp_path / "data" / "jj_trades.db")
    try:
        trade_rows = ledger_conn.execute(
            """
            SELECT market_id, order_id, position_size_usd, source, source_combo, source_count
            FROM trades
            ORDER BY timestamp ASC
            """
        ).fetchall()
        order_rows = ledger_conn.execute(
            """
            SELECT order_id, trade_id, market_id, price, size_usd, status, fill_count
            FROM orders
            ORDER BY timestamp ASC
            """
        ).fetchall()
        fill_rows = ledger_conn.execute(
            """
            SELECT order_id, trade_id, market_id, fill_price, fill_size_usd
            FROM fills
            ORDER BY timestamp ASC
            """
        ).fetchall()
    finally:
        ledger_conn.close()
    ledger_conn = sqlite3.connect(tmp_path / "data" / "jj_trades.db")
    try:
        trade_columns = {
            row[1]
            for row in ledger_conn.execute("PRAGMA table_info(trades)").fetchall()
        }
    finally:
        ledger_conn.close()

    assert observed["source"] == "remote_sqlite_probe"
    assert observed["latest_trade"]["order_status"] == "live_filled"
    assert len(cached_rows) == 2
    assert cached_rows[-1]["order_status"] == "live_filled"
    assert cached_rows[-1]["source"] == "remote_probe:ssh"
    assert len(mirrored_rows) == 2
    assert mirrored_rows[-1][0] == 1773421200
    assert mirrored_rows[-1][1] == 1773421500
    assert mirrored_rows[-1][2] > 0
    assert mirrored_rows[-1][3] == "live_filled"
    assert trade_rows == [
        (
            "btc-updown-5m-1773421200",
            "btc5-mirror-order-1773421200",
            8.5,
            "polymarket_btc5_remote_mirror",
            "polymarket_btc5_remote_mirror",
            1,
        )
    ]
    assert len(order_rows) == 1
    assert order_rows[0][0] == "btc5-mirror-order-1773421200"
    assert order_rows[0][2] == "btc-updown-5m-1773421200"
    assert order_rows[0][4] == 8.5
    assert order_rows[0][5] == "filled"
    assert order_rows[0][6] == 1
    assert len(fill_rows) == 1
    assert fill_rows[0][0] == "btc5-mirror-order-1773421200"
    assert fill_rows[0][2] == "btc-updown-5m-1773421200"
    assert fill_rows[0][4] == 8.5
    assert {"source", "source_combo", "source_components_json", "source_count"}.issubset(trade_columns)


def test_write_remote_cycle_status_emits_runtime_mode_reconciliation_artifact(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "jj_state.json",
        {
            "bankroll": 250.0,
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
                "JJ_MAX_POSITION_USD=250.0",
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
    remote_status = json.loads((tmp_path / "reports" / "remote_cycle_status.json").read_text())
    public_snapshot = json.loads(
        (tmp_path / "reports" / "public_runtime_snapshot.json").read_text()
    )
    note_path = Path(written["runtime_mode_reconciliation_markdown"])

    assert note_path.exists()
    assert runtime_truth["remote_runtime_profile"] == "maker_velocity_all_in"
    assert runtime_truth["effective_runtime_profile"] == "shadow_fast_flow"
    assert runtime_truth["safe_baseline_required"] is True
    assert runtime_truth["agent_run_mode"] == "shadow"
    assert runtime_truth["execution_mode"] == "shadow"
    assert runtime_truth["paper_trading"] is True
    assert runtime_truth["allow_order_submission"] is False
    assert runtime_truth["order_submit_enabled"] is False
    assert runtime_truth["launch_posture"] == "blocked"
    assert runtime_truth["restart_recommended"] is False
    assert runtime_truth["effective_caps"]["max_position_usd"] == 5.0
    assert runtime_truth["effective_thresholds"]["yes_threshold"] == 0.15
    assert runtime_truth["drift_flags"]["profile_override_drift"] is True
    assert runtime_truth["drift_flags"]["docs_stale"] is True
    assert runtime_truth["drift_flags"]["service_running_while_launch_blocked"] is True
    assert runtime_truth["mode_reconciliation"]["remote_probe"]["open_positions"] == 4
    assert runtime_truth["mode_reconciliation"]["remote_probe"]["last_trades"] == 5
    assert remote_status["launch_posture"] == "blocked"
    assert remote_status["launch"]["posture"] == "blocked"
    assert remote_status["allow_order_submission"] is False
    assert remote_status["launch"]["allow_order_submission"] is False
    assert remote_status["runtime_mode_reconciliation"]["effective_profile"] == "shadow_fast_flow"
    assert remote_status["runtime_truth"]["effective_runtime_profile"] == "shadow_fast_flow"
    profile_consistency = runtime_truth["state_improvement"]["strategy_recommendations"]["control_plane_consistency"]["profile_consistency"]
    assert profile_consistency["status"] == "mismatch"
    assert profile_consistency["selected_profile"] == "maker_velocity_all_in"
    assert profile_consistency["local_selector"] == "maker_velocity_all_in"
    assert profile_consistency["remote_selector"] == "maker_velocity_all_in"
    assert "profile_override_drift" in profile_consistency["reasons"]
    assert public_snapshot["runtime_mode"]["order_submit_enabled"] is False
    assert "- Order submit enabled: no" in note_path.read_text()


def test_write_remote_cycle_status_reports_runtime_profile_selector_mismatch(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-09T11:25:24+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
            "service_name": "btc-5min-maker.service",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-09T11:31:50+00:00",
            "command": "make test",
            "status": "passing",
            "summary": "1096 passed in 22.67s; 25 passed in 3.59s",
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
    _write_text(tmp_path / ".env", "JJ_RUNTIME_PROFILE=blocked_safe\n")
    _write_text(tmp_path / ".env.example", "JJ_RUNTIME_PROFILE=blocked_safe\n")
    _write_text(tmp_path / "reports" / "runtime_operator_overrides.env", "")
    _write_json(
        tmp_path / "reports" / "deploy_20260309T112719Z.json",
        {
            "generated_at": "2026-03-09T11:28:02+00:00",
            "remote_mode": {
                "remote_env_exists": True,
                "runtime_profile": "paper_aggressive",
                "agent_run_mode": "paper",
                "paper_trading": "true",
                "values": {
                    "ELASTIFUND_AGENT_RUN_MODE": "paper",
                    "JJ_RUNTIME_PROFILE": "paper_aggressive",
                    "PAPER_TRADING": "true",
                },
            },
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    profile_consistency = runtime_truth["state_improvement"]["strategy_recommendations"]["control_plane_consistency"]["profile_consistency"]

    assert profile_consistency["status"] == "mismatch"
    assert profile_consistency["selected_profile"] == "blocked_safe"
    assert profile_consistency["local_selector"] == "blocked_safe"
    assert profile_consistency["remote_selector"] == "paper_aggressive"
    assert profile_consistency["observed_remote_runtime_profile"] == "paper_aggressive"
    assert "remote_selector_differs_from_selected_profile" in profile_consistency["reasons"]
    assert "observed_remote_runtime_profile_differs_from_selected_profile" in profile_consistency["reasons"]


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


def test_write_remote_cycle_status_uses_fast_market_search_for_btc5_candidate_recovery(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-10T20:24:22+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-10T20:26:41+00:00",
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
        tmp_path / "reports" / "edge_scan_20260310T202000Z.json",
        {
            "generated_at": "2026-03-10T20:20:00+00:00",
            "recommended_action": "stay_paused",
            "action_reason": "Zero viable markets even at wide-open thresholds (YES=0.05, NO=0.02); Platt parameters may be stale.",
            "candidate_markets": [],
            "cross_platform_arb": {"arb_opportunities": 0, "matches": 0},
            "threshold_sensitivity": {"current": {"yes": 0.05, "no": 0.02}},
        },
    )
    _write_json(
        tmp_path / "reports" / "pipeline_20260310T202005Z.json",
        {
            "report_generated_at": "2026-03-10T20:20:05+00:00",
            "pipeline_verdict": {
                "recommendation": "REJECT ALL",
                "reasoning": "No validated edge.",
            },
            "new_viable_strategies": [],
            "threshold_sensitivity": {
                "current": {"tradeable": 0, "yes_reachable_markets": 0, "no_reachable_markets": 0}
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "runtime_profile_effective.json",
        {
            "profile_name": "maker_velocity_all_in",
            "signal_thresholds": {"yes_threshold": 0.05, "no_threshold": 0.02},
            "market_filters": {"max_resolution_hours": 24.0},
            "risk_limits": {"hourly_notional_budget_usd": 250.0},
        },
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": "2026-03-10T20:21:25+00:00",
            "stage_readiness": {
                "recommended_stage": 0,
                "ready_for_stage_1": False,
                "ready_for_stage_2": False,
                "ready_for_stage_3": False,
                "blocking_checks": ["trailing_12_live_filled_not_positive"],
                "reasons": ["Recent BTC5 validation is still negative in the short window."],
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": "2026-03-10T20:21:25+00:00",
            "capital_ranking_support": {
                "supports_capital_allocation": True,
                "wallet_flow_confirmation_ready": False,
                "confirmation_coverage_score": 0.8,
                "confirmation_strength_score": 0.8,
                "confirmation_freshness_label": "stale",
                "confirmation_next_required_artifact": "reports/signal_source_audit.json",
            },
        },
    )
    _write_validated_btc5_package(
        tmp_path,
        generated_at=datetime.fromisoformat("2026-03-10T20:21:25+00:00"),
        deploy_recommendation="hold",
        confidence_label="medium",
        promoted_package_selected=False,
    )
    _write_json(
        tmp_path / "reports" / "fast_market_search" / "latest.json",
        {
            "generated_at": "2026-03-10T20:21:25+00:00",
            "summary": {
                "best_btc5_candidate_id": "btc5:guardrail_replay_d0.00005_up0.48_down0.51",
                "primary_blockers": [
                    "confirmation_evidence_stale",
                    "trailing_12_live_filled_not_positive",
                ],
            },
            "ranked_candidates": [
                {
                    "candidate_id": "btc5:guardrail_replay_d0.00005_up0.48_down0.51",
                    "candidate_name": "guardrail_replay_d0.00005_up0.48_down0.51",
                    "candidate_family": "guardrail_followup",
                    "market_scope": "btc_5m",
                    "deployment_class": "btc5_probe_only",
                    "deployment_mode": "shadow_only",
                    "blocking_checks": [
                        "confirmation_evidence_stale",
                        "trailing_12_live_filled_not_positive",
                    ],
                }
            ],
        },
    )
    _write_finance_latest(
        tmp_path,
        generated_at=datetime.fromisoformat("2026-03-10T20:21:25+00:00"),
        finance_gate_pass=False,
        reason="destination_not_whitelisted",
        status="hold_repair",
        retry_in_minutes=30,
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-10T20:21:25+00:00",
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
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 120.0,
            "warnings": [],
        },
    )

    write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    state_improvement = runtime_truth["state_improvement"]
    candidate_recovery = state_improvement["strategy_recommendations"]["btc5_candidate_recovery"]
    champion = state_improvement["strategy_recommendations"]["champion_lane_contract"]

    assert state_improvement["per_venue_candidate_counts"]["polymarket"] == 1
    assert state_improvement["per_venue_candidate_counts"]["total"] == 1
    assert candidate_recovery["btc5_candidate_count"] == 1
    assert candidate_recovery["top_candidate_id"] == "btc5:guardrail_replay_d0.00005_up0.48_down0.51"
    assert candidate_recovery["shadow_candidate_available"] is True
    assert "confirmation_evidence_stale" in state_improvement["reject_reasons"]
    assert (
        "Zero viable markets even at wide-open thresholds (YES=0.05, NO=0.02); Platt parameters may be stale."
        not in state_improvement["reject_reasons"]
    )
    assert champion["status"] == "shadow_only"
    assert champion["champion_lane"]["lane"] == "btc_5m"
    assert champion["challenger_rule_set"]["policy"] == "comparison_only_until_replayable_evidence"
    assert "confirmation_evidence_stale" in champion["blocker_classes"]["confirmation"]["checks"]
    assert champion["blocker_classes"]["capital"]["checks"] == ["destination_not_whitelisted"]
    assert champion["required_outputs"]["finance_gate_pass"] is False
    assert "destination_not_whitelisted" in champion["required_outputs"]["block_reasons"]


def test_write_remote_cycle_status_persists_candidate_ready_champion_lane_contract(
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
                "confirmation_strength_score": 0.8,
                "confirmation_strength_label": "strong",
                "confirmation_freshness_label": "fresh",
                "confirmation_sources_ready": ["wallet_flow"],
                "best_confirmation_source": "wallet_flow",
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now, median_arr_delta_pct=25.0)
    _write_finance_latest(
        tmp_path,
        generated_at=now,
        finance_gate_pass=True,
    )
    _write_json(
        tmp_path / "reports" / "fast_market_search" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "summary": {
                "primary_blockers": [],
            },
            "lane_map": [
                {
                    "lane": "btc_5m",
                    "candidate_count": 1,
                    "top_candidate_id": "btc5:promote_ready",
                    "top_deployment_class": "validated_btc5_ready",
                    "top_evidence_band": "validated",
                    "top_ranking_score": 91.2,
                    "validation_live_filled_rows": 12,
                    "blocking_checks": [],
                },
                {
                    "lane": "btc_15m",
                    "candidate_count": 1,
                    "top_candidate_id": "adjacent:btc_15m",
                    "top_deployment_class": "adjacent_shadow_only",
                    "top_evidence_band": "exploratory",
                    "top_ranking_score": 22.0,
                    "validation_live_filled_rows": 0,
                    "blocking_checks": ["no_replayable_evidence"],
                },
            ],
            "ranked_candidates": [
                {
                    "candidate_id": "btc5:promote_ready",
                    "candidate_name": "promote_ready",
                    "candidate_family": "regime_policy",
                    "market_scope": "btc_5m",
                    "deployment_class": "validated_btc5_ready",
                    "deployment_mode": "bounded_live_only",
                    "blocking_checks": [],
                    "arr_estimates": {"median_arr_delta_pct": 25.0},
                },
            ],
        },
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

    write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    remote_status = json.loads((tmp_path / "reports" / "remote_cycle_status.json").read_text())
    public_snapshot = json.loads((tmp_path / "reports" / "public_runtime_snapshot.json").read_text())
    champion = runtime_truth["state_improvement"]["strategy_recommendations"]["champion_lane_contract"]

    assert champion["status"] == "candidate_ready"
    assert champion["champion_lane"]["selected_deploy_recommendation"] == "promote"
    assert champion["challenger_rule_set"]["active_challenger_lane"] == "btc_15m"
    assert champion["blocker_classes"]["truth"]["checks"] == []
    assert champion["blocker_classes"]["candidate"]["checks"] == []
    assert champion["blocker_classes"]["confirmation"]["checks"] == []
    assert champion["blocker_classes"]["capital"]["checks"] == []
    assert champion["required_outputs"]["candidate_delta_arr_bps"] == 2500
    assert champion["required_outputs"]["finance_gate_pass"] is True
    assert runtime_truth["summary"]["trading_cycle_status"] == "candidate_ready"
    assert runtime_truth["truth_gate_status"] == "consistent"
    assert remote_status["truth_gate_status"] == "consistent"
    assert remote_status["runtime_truth"]["truth_gate_status"] == "consistent"
    assert public_snapshot["truth_gate_status"] == "consistent"
    assert runtime_truth["selected_best_profile"] is not None
    assert runtime_truth["selected_policy_id"] == runtime_truth["selected_best_profile"]
    assert isinstance(runtime_truth["selected_best_runtime_package"], dict)
    assert runtime_truth["promotion_state"] == "live_promoted"
    assert remote_status["selected_best_profile"] == runtime_truth["selected_best_profile"]
    assert remote_status["selected_policy_id"] == runtime_truth["selected_policy_id"]
    assert isinstance(remote_status["selected_best_runtime_package"], dict)
    assert public_snapshot["selected_best_profile"] == runtime_truth["selected_best_profile"]
    assert public_snapshot["selected_policy_id"] == runtime_truth["selected_policy_id"]
    assert isinstance(public_snapshot["selected_best_runtime_package"], dict)
    assert public_snapshot["promotion_state"] == runtime_truth["promotion_state"]
    assert isinstance(runtime_truth["truth_precedence"], dict)
    assert remote_status["truth_precedence"] == runtime_truth["truth_precedence"]
    assert public_snapshot["truth_precedence"] == runtime_truth["truth_precedence"]
    assert public_snapshot["state_improvement"]["strategy_recommendations"]["champion_lane_contract"]["status"] == "candidate_ready"


def test_write_remote_cycle_status_forces_hold_repair_on_truth_lattice_trade_count_divergence(
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
                "confirmation_strength_score": 0.8,
                "confirmation_strength_label": "strong",
                "confirmation_freshness_label": "fresh",
                "confirmation_sources_ready": ["wallet_flow"],
                "best_confirmation_source": "wallet_flow",
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now, median_arr_delta_pct=25.0)
    _write_finance_latest(
        tmp_path,
        generated_at=now,
        finance_gate_pass=True,
    )
    _write_json(
        tmp_path / "reports" / "fast_market_search" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "summary": {
                "primary_blockers": [],
            },
            "lane_map": [
                {
                    "lane": "btc_5m",
                    "candidate_count": 1,
                    "top_candidate_id": "btc5:promote_ready",
                    "top_deployment_class": "validated_btc5_ready",
                    "top_evidence_band": "validated",
                    "top_ranking_score": 91.2,
                    "validation_live_filled_rows": 12,
                    "blocking_checks": [],
                }
            ],
            "ranked_candidates": [
                {
                    "candidate_id": "btc5:promote_ready",
                    "candidate_name": "promote_ready",
                    "candidate_family": "regime_policy",
                    "market_scope": "btc_5m",
                    "deployment_class": "validated_btc5_ready",
                    "deployment_mode": "bounded_live_only",
                    "blocking_checks": [],
                    "arr_estimates": {"median_arr_delta_pct": 25.0},
                },
            ],
        },
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
            "open_positions_count": 5,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 50,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )

    write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    remote_status = json.loads((tmp_path / "reports" / "remote_cycle_status.json").read_text())
    public_snapshot = json.loads((tmp_path / "reports" / "public_runtime_snapshot.json").read_text())
    truth_lattice = runtime_truth["state_improvement"]["strategy_recommendations"]["truth_lattice"]
    champion = runtime_truth["state_improvement"]["strategy_recommendations"]["champion_lane_contract"]
    launch_packet = runtime_truth["launch_packet"]

    assert truth_lattice["status"] == "consistent"
    assert truth_lattice["repair_branch_required"] is False
    assert "trade_count_divergence_requires_repair_branch" not in truth_lattice["broken_reasons"]
    assert str(runtime_truth["runtime"]["total_trades_source"]).startswith("max_observed:")
    assert champion["status"] == "candidate_ready"
    assert (
        "trade_count_divergence_requires_repair_branch"
        not in champion["blocker_classes"]["truth"]["checks"]
    )
    assert (
        "trade_count_divergence_requires_repair_branch"
        not in champion["required_outputs"]["block_reasons"]
    )
    assert launch_packet["launch_verdict"]["reason"] != "blocked_by_truth_lattice"
    assert (
        "trade_count_divergence_requires_repair_branch"
        not in launch_packet["mandatory_outputs"]["block_reasons"]
    )
    assert runtime_truth["truth_gate_status"] == "consistent"
    assert remote_status["truth_gate_status"] == "consistent"
    assert public_snapshot["truth_gate_status"] == "consistent"
    assert remote_status["truth_lattice"] == runtime_truth["truth_lattice"]
    assert public_snapshot["truth_lattice"] == runtime_truth["truth_lattice"]
    assert runtime_truth["summary"]["trading_cycle_status"] == "candidate_ready"


def test_write_remote_cycle_status_forces_hold_repair_on_wallet_export_candidate_conflict(
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
                "wallet_flow_archive_confirmation_ready": True,
                "btc_fast_window_confirmation_ready": True,
                "confirmation_support_status": "ready",
                "confirmation_coverage_score": 0.8,
                "confirmation_coverage_label": "strong",
                "confirmation_strength_score": 0.8,
                "confirmation_strength_label": "strong",
                "confirmation_freshness_label": "fresh",
                "confirmation_sources_ready": ["wallet_flow"],
                "best_confirmation_source": "wallet_flow",
            },
        },
    )
    _write_validated_btc5_package(tmp_path, generated_at=now, median_arr_delta_pct=25.0)
    _write_finance_latest(
        tmp_path,
        generated_at=now,
        finance_gate_pass=True,
    )
    _write_json(
        tmp_path / "reports" / "fast_market_search" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "summary": {
                "primary_blockers": [],
            },
            "lane_map": [
                {
                    "lane": "btc_5m",
                    "candidate_count": 1,
                    "top_candidate_id": "btc5:promote_ready",
                    "top_deployment_class": "validated_btc5_ready",
                    "top_evidence_band": "validated",
                    "top_ranking_score": 91.2,
                    "validation_live_filled_rows": 12,
                    "blocking_checks": [],
                }
            ],
            "ranked_candidates": [
                {
                    "candidate_id": "btc5:promote_ready",
                    "candidate_name": "promote_ready",
                    "candidate_family": "regime_policy",
                    "market_scope": "btc_5m",
                    "deployment_class": "validated_btc5_ready",
                    "deployment_mode": "bounded_live_only",
                    "blocking_checks": [],
                    "arr_estimates": {"median_arr_delta_pct": 25.0},
                },
            ],
        },
    )
    _write_text(
        tmp_path / "Polymarket-History-2026-03-10.csv",
        "\n".join(
            [
                "timestamp,marketName,action,usdcAmount,status",
                "2026-03-10T10:00:00+00:00,BTC above 100k,Buy,5.00,open",
                "2026-03-10T12:00:00+00:00,BTC above 100k,Redeem,8.00,resolved",
                "",
            ]
        ),
    )
    _write_text(
        tmp_path / "Polymarket-History-2026-03-11.csv",
        "\n".join(
            [
                "timestamp,marketName,action,usdcAmount,status",
                "2026-03-11T10:00:00+00:00,BTC above 100k,Buy,10.00,open",
                "2026-03-11T11:00:00+00:00,BTC above 100k,Redeem,4.00,resolved",
                "2026-03-11T12:00:00+00:00,ETH above 3k,Buy,2.00,open",
                "",
            ]
        ),
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

    write_remote_cycle_status(tmp_path)

    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    remote_status = json.loads((tmp_path / "reports" / "remote_cycle_status.json").read_text())
    public_snapshot = json.loads((tmp_path / "reports" / "public_runtime_snapshot.json").read_text())
    wallet_summary = runtime_truth["state_improvement"]["strategy_recommendations"]["wallet_reconciliation_summary"]
    truth_lattice = runtime_truth["truth_lattice"]
    champion = runtime_truth["state_improvement"]["strategy_recommendations"]["champion_lane_contract"]
    launch_packet = runtime_truth["launch_packet"]

    assert wallet_summary["candidate_count"] == 2
    assert wallet_summary["candidate_conflict_status"] == "conflict"
    assert len(wallet_summary["candidate_conflicts"]) == 1
    assert {
        "row_count_mismatch",
        "market_count_mismatch",
        "net_trading_cash_flow_mismatch",
    } == set(wallet_summary["candidate_conflicts"][0]["conflict_reasons"])
    assert runtime_truth["truth_gate_status"] == "hold_repair"
    assert remote_status["truth_gate_status"] == "hold_repair"
    assert remote_status["runtime_truth"]["truth_gate_status"] == "hold_repair"
    assert public_snapshot["truth_gate_status"] == "hold_repair"
    assert "wallet_export_candidate_conflict_requires_repair_branch" not in truth_lattice["broken_reasons"]
    assert wallet_summary["reporting_precedence"] == "btc5_runtime_db"
    assert remote_status["truth_lattice"] == truth_lattice
    assert public_snapshot["truth_lattice"] == truth_lattice
    assert champion["status"] == "hold_repair"
    assert launch_packet["launch_verdict"]["reason"] == "blocked_by_truth_lattice"


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
