import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import _remote_cycle_status_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

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
        for path in (tmp_path / "reports" / "runtime" / "runtime_truth").glob("runtime_truth_*.json")
    ]

    assert written["runtime_truth_latest"].endswith("reports/runtime_truth_latest.json")
    assert written["runtime_truth_timestamped"].startswith(
        str(tmp_path / "reports" / "runtime" / "runtime_truth" / "runtime_truth_")
    )
    assert written["public_runtime_snapshot"].endswith("reports/public_runtime_snapshot.json")
    assert written["launch_packet_latest"].endswith("reports/launch_packet_latest.json")
    assert written["launch_packet_timestamped"].startswith(
        str(tmp_path / "reports" / "runtime" / "launch_packets" / "launch_packet_")
    )
    assert written["state_improvement_latest"].endswith("reports/state_improvement_latest.json")
    assert written["state_improvement_timestamped"].startswith(
        str(tmp_path / "reports" / "runtime" / "state_improvement" / "state_improvement_")
    )
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
    assert runtime_truth["reconciliation"]["btc_5min_maker"]["selected_source"] == "local_sqlite_db"
    assert runtime_truth["reconciliation"]["btc_5min_maker"]["db_path"].endswith("data/btc_5min_maker.db")
    assert runtime_truth["reconciliation"]["btc_5min_maker"]["live_filled_pnl_usd"] == 5.4184
    assert runtime_truth["reconciliation"]["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    accounting = runtime_truth["reconciliation"]["accounting"]
    assert isinstance(accounting["drift_detected"], bool)
    if accounting["drift_detected"]:
        assert accounting["unmatched_open_positions"]["delta_remote_minus_local"] == 5
        assert accounting["unmatched_closed_positions"]["delta_remote_minus_local"] == 2
    else:
        assert accounting["unmatched_open_positions"]["delta_remote_minus_local"] == 0
        assert accounting["unmatched_closed_positions"]["delta_remote_minus_local"] == 0
    assert runtime_truth["accounting_reconciliation"]["source_confidence_freshness"]["remote_wallet"]["freshness"] in {"fresh", "aging", "stale", "unknown"}
    if accounting["drift_detected"]:
        assert any(reason.startswith("Accounting drift: ") for reason in runtime_truth["drift"]["reasons"])
    assert runtime_truth["reconciliation"]["polymarket_wallet"]["free_collateral_usd"] == 0.0
    assert runtime_truth["state_improvement"]["hourly_budget_progress"]["window_minutes"] == 60
    assert runtime_truth["state_improvement"]["per_venue_candidate_counts"]["polymarket"] >= 0
    assert isinstance(runtime_truth["state_improvement"]["reject_reasons"], list)
    assert runtime_truth["state_improvement"]["operator_digest"]
    assert runtime_truth["state_improvement"]["strategy_recommendations"]["btc5_edge_profile"]["best_direction"]["label"] == "UP"
    scoreboard = runtime_truth["state_improvement"]["strategy_recommendations"]["public_performance_scoreboard"]
    capital_gate = runtime_truth["state_improvement"]["strategy_recommendations"]["capital_addition_readiness"]
    control_plane = runtime_truth["state_improvement"]["strategy_recommendations"]["control_plane_consistency"]
    assert scoreboard["fund_realized_arr_claim_status"] in {"blocked", "unblocked"}
    assert scoreboard["fund_realized_arr_claim_reason"].startswith("fund_realized_arr_claim_")
    assert scoreboard["realized_btc5_sleeve_window_live_fills"] == 1
    assert scoreboard["realized_btc5_sleeve_window_pnl_usd"] == 5.4184
    assert scoreboard["realized_btc5_sleeve_window_hours"] is not None
    assert scoreboard["realized_btc5_sleeve_run_rate_pct"] is not None
    assert scoreboard["intraday_live_summary"]["filled_rows_today"] == 1
    assert scoreboard["intraday_live_summary"]["filled_pnl_usd_today"] == 5.4184
    assert scoreboard["intraday_live_summary"]["estimated_maker_rebate_usd_today"] == pytest.approx(0.0156, abs=1e-4)
    assert scoreboard["intraday_live_summary"]["net_pnl_after_estimated_rebate_usd_today"] == pytest.approx(5.4340, abs=1e-4)
    assert scoreboard["intraday_live_summary"]["recent_5_pnl_usd"] == 5.4184
    assert scoreboard["intraday_live_summary"]["recent_5_estimated_maker_rebate_usd"] == pytest.approx(0.0156, abs=1e-4)
    assert scoreboard["intraday_live_summary"]["recent_5_net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.4340, abs=1e-4)
    assert scoreboard["intraday_live_summary"]["skip_price_count"] == 0
    assert scoreboard["intraday_live_summary"]["order_failed_count"] == 0
    assert scoreboard["intraday_live_summary"]["best_direction_today"]["label"] == "UP"
    assert scoreboard["intraday_live_summary"]["best_price_bucket_today"]["label"] == "<0.49"
    assert scoreboard["timebound_velocity_forecast_gain_pct"] is None
    assert scoreboard["timebound_velocity_forecast_gain_pct_per_day"] is None
    assert capital_gate["fund"]["status"] in {"hold", "ready_scale"}
    assert capital_gate["fund"]["recommended_amount_usd"] in {0, 1000}
    assert capital_gate["polymarket_btc5"]["status"] == "hold"
    assert capital_gate["kalshi_weather"]["status"] == "hold"
    assert capital_gate["next_1000_usd"]["status"] in {"hold", "ready_scale"}
    assert capital_gate["next_1000_usd"]["recommended_amount_usd"] in {0, 1000}
    assert control_plane["profile_consistency"]["status"] in {"consistent", "mismatch"}
    assert control_plane["profile_consistency"]["selected_profile"] is not None
    assert control_plane["service_consistency"]["status"] == "mismatch"
    launch_packet = runtime_truth["launch_packet"]
    assert launch_packet["artifact"] == "launch_packet"
    assert launch_packet["launch_verdict"]["posture"] in {"blocked", "clear"}
    assert launch_packet["launch_state"]["service"]["state"] in {"running", "stopped", "unknown"}
    assert launch_packet["launch_state"]["storage"]["state"] in {"blocked", "clear", "unknown"}
    assert launch_packet["launch_state"]["package_load"]["state"] in {
        "loaded",
        "load_pending",
        "not_required",
        "unknown",
    }
    assert launch_packet["launch_state"]["stage"]["allowed_stage_label"]
    mandatory = launch_packet["mandatory_outputs"]
    assert set(mandatory.keys()) == {
        "candidate_delta_arr_bps",
        "expected_improvement_velocity_delta",
        "arr_confidence_score",
        "block_reasons",
        "finance_gate_pass",
        "treasury_gate_pass",
        "one_next_cycle_action",
    }
    assert runtime_truth["summary"]["launch_posture"] == launch_packet["launch_verdict"]["posture"]
    assert runtime_truth["summary"]["one_next_cycle_action"] == mandatory["one_next_cycle_action"]
    assert runtime_truth["one_next_cycle_action"] == launch_packet["one_next_cycle_action"]
    assert runtime_truth["one_next_cycle_action"] == launch_packet["mandatory_outputs"]["one_next_cycle_action"]
    next_cycle_metrics = runtime_truth["state_improvement"]["next_cycle_metrics"]
    assert isinstance(next_cycle_metrics["contract_mismatch_count"], int)
    assert isinstance(next_cycle_metrics["contract_mismatch_codes"], list)
    assert next_cycle_metrics["cap_breach_count"] >= 0
    assert next_cycle_metrics["cap_breach_rows_checked"] >= 0
    truth_precedence = runtime_truth["state_improvement"]["truth_precedence"]
    assert "launch" in truth_precedence["domains"]
    assert "stage" in truth_precedence["domains"]
    assert "pnl" in truth_precedence["domains"]
    assert "candidate_flow" in truth_precedence["domains"]
    assert "capital" in truth_precedence["domains"]
    evidence_freshness = runtime_truth["state_improvement"]["evidence_freshness"]
    assert "fresh_wrapper_stale_input" in evidence_freshness
    if launch_packet["launch_verdict"]["posture"] == "blocked":
        assert "launch is blocked;" in runtime_truth["state_improvement"]["operator_digest"]
    assert control_plane["service_consistency"]["observed_service_name"] == "btc-5min-maker.service"
    assert any(
        reason.startswith("service_target_mismatch:")
        or reason == "launch_blocked_but_service_running"
        for reason in control_plane["service_consistency"]["reasons"]
    )
    assert control_plane["truth_source_consistency"]["status"] in {"consistent", "mismatch"}
    assert control_plane["capital_consistency"]["status"] in {"consistent", "conflict"}
    assert public_snapshot["snapshot_source"] == "reports/runtime_truth_latest.json"
    assert public_snapshot["service"]["status"] == "running"
    assert "host" not in public_snapshot["service"]
    assert public_snapshot["capital"]["polymarket_actual_deployable_usd"] == 0.0
    assert public_snapshot["polymarket_wallet"]["total_wallet_value_usd"] == 60.67
    assert public_snapshot["runtime"]["btc5_source"] == "local_sqlite_db"
    assert public_snapshot["runtime"]["btc5_intraday_live_summary"]["filled_rows_today"] == 1
    assert public_snapshot["runtime"]["btc5_intraday_live_summary"]["estimated_maker_rebate_usd_today"] == pytest.approx(0.0156, abs=1e-4)
    assert public_snapshot["btc_5min_maker"]["live_filled_pnl_usd"] == 5.4184
    assert public_snapshot["btc_5min_maker"]["estimated_maker_rebate_usd"] == pytest.approx(0.0156, abs=1e-4)
    assert public_snapshot["btc_5min_maker"]["net_pnl_after_estimated_rebate_usd"] == pytest.approx(5.4340, abs=1e-4)
    assert public_snapshot["btc_5min_maker"]["source"] == "local_sqlite_db"
    assert public_snapshot["btc_5min_maker"]["fill_attribution"]["best_price_bucket"]["label"] == "<0.49"
    assert public_snapshot["btc_5min_maker"]["intraday_live_summary"]["filled_pnl_usd_today"] == 5.4184
    assert public_snapshot["btc_5min_maker"]["intraday_live_summary"]["estimated_maker_rebate_usd_today"] == pytest.approx(0.0156, abs=1e-4)
    assert public_snapshot["runtime"]["btc5_live_filled_rows"] == 1
    assert "maker_address" not in public_snapshot["polymarket_wallet"]
    assert public_snapshot["launch_packet"]["launch_state"] == launch_packet["launch_state"]
    assert public_snapshot["state_improvement"]["operator_digest"]
    assert (
        public_snapshot["state_improvement"]["strategy_recommendations"]["control_plane_consistency"]["service_consistency"]["expected_primary_service"]
        == "btc-5min-maker.service"
    )
    assert (
        public_snapshot["state_improvement"]["strategy_recommendations"]["public_performance_scoreboard"]["fund_realized_arr_claim_status"]
        in {"blocked", "unblocked"}
    )
    assert (
        public_snapshot["state_improvement"]["strategy_recommendations"]["capital_addition_readiness"]["next_1000_usd"]["status"]
        in {"hold", "ready_scale"}
    )
    assert any(
        "jj-live.service is running while launch posture remains blocked" in headline
        for headline in public_snapshot["operator_headlines"]
    )
    assert (tmp_path / "reports" / "state_improvement_latest.json").exists()
    assert (tmp_path / "reports" / "state_improvement_digest.md").exists()


def test_write_remote_cycle_status_populates_btc5_forecast_confidence_from_research(
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
                "window_start_ts": 1773061200,
                "window_end_ts": 1773061500,
                "slug": "btc-updown-5m-1773061200",
                "decision_ts": 1773061499,
                "direction": "UP",
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        ],
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "active_profile": {
                "name": "active",
                "max_abs_delta": 0.00015,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            },
            "best_candidate": {
                "profile": {
                    "name": "best",
                    "max_abs_delta": 0.00010,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                }
            },
            "arr_tracking": {
                "current_median_arr_pct": 100.0,
                "best_median_arr_pct": 125.0,
                "median_arr_delta_pct": 25.0,
                "current_p05_arr_pct": 40.0,
                "best_p05_arr_pct": 45.0,
            },
            "decision": {"action": "hold", "reason": "validation still building"},
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_loop" / "latest.json",
        {
            "summary": {"last_cycle_finished_at": now.isoformat()},
            "latest_entry": {
                "arr": {
                    "active_median_arr_pct": 100.0,
                    "best_median_arr_pct": 125.0,
                    "active_p05_arr_pct": 40.0,
                    "best_p05_arr_pct": 45.0,
                    "median_arr_delta_pct": 25.0,
                }
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_hypothesis_lab" / "summary.json",
        {
            "generated_at": now.isoformat(),
            "best_hypothesis": {
                "hypothesis": {
                    "name": "midday-policy",
                    "session_name": "midday_et",
                    "et_hours": [12, 13],
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.49,
                },
                "summary": {
                    "validation_live_filled_rows": 8,
                    "generalization_ratio": 0.85,
                    "evidence_band": "candidate",
                },
            },
            "baseline": {"deduped_live_filled_rows": 12},
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {"status": "unavailable", "checked_at": now.isoformat()},
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    public_snapshot = json.loads((tmp_path / "reports" / "public_runtime_snapshot.json").read_text())

    strategy = runtime_truth["state_improvement"]["strategy_recommendations"]
    forecast = strategy["btc5_forecast_confidence"]
    edge_profile = strategy["btc5_edge_profile"]

    assert forecast["confidence_label"] == "medium"
    assert forecast["validation_live_filled_rows"] == 8
    assert forecast["generalization_ratio"] == 0.85
    assert forecast["active_median_arr_pct"] == 100.0
    assert forecast["best_median_arr_pct"] == 125.0
    assert forecast["median_arr_delta_pct"] == 25.0
    assert "reports/btc5_autoresearch/latest.json" in forecast["source_artifacts"]
    assert edge_profile["active_profile"]["name"] == "active"
    assert edge_profile["best_profile"]["name"] == "best"
    assert edge_profile["recommended_session_policy"][0]["name"] == "midday-policy"
    assert edge_profile["validation_live_filled_rows"] == 8
    assert public_snapshot["state_improvement"]["strategy_recommendations"]["btc5_forecast_confidence"]["confidence_label"] == "medium"


def test_write_remote_cycle_status_marks_missing_or_stale_primary_research_artifacts(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale_time = (now - timedelta(hours=7)).isoformat()
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
        tmp_path / "reports" / "btc5_autoresearch" / "latest.json",
        {
            "generated_at": stale_time,
            "arr_tracking": {
                "current_median_arr_pct": 100.0,
                "best_median_arr_pct": 120.0,
                "median_arr_delta_pct": 20.0,
                "current_p05_arr_pct": 30.0,
                "best_p05_arr_pct": 35.0,
            },
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {"status": "unavailable", "checked_at": now.isoformat()},
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    reasons = runtime_truth["state_improvement"]["strategy_recommendations"]["btc5_forecast_confidence"]["confidence_reasons"]

    assert any(reason.startswith("stale_primary_research_artifact:reports/btc5_autoresearch/latest.json") for reason in reasons)
    assert any(reason.startswith("missing_primary_research_artifact:reports/btc5_autoresearch_loop/latest.json") for reason in reasons)


def test_write_remote_cycle_status_public_forecast_selection_prefers_confidence_then_deploy_rank(
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
                "window_start_ts": 1773061200,
                "window_end_ts": 1773061500,
                "slug": "btc-updown-5m-1773061200",
                "decision_ts": 1773061499,
                "direction": "UP",
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        ],
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "arr_tracking": {
                "current_median_arr_pct": 100.0,
                "best_median_arr_pct": 120.0,
                "median_arr_delta_pct": 20.0,
            },
            "deploy_recommendation": "hold",
            "package_confidence_label": "medium",
            "package_confidence_reasons": ["baseline_medium_confidence"],
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_current_probe" / "latest.json",
        {
            "generated_at": (now - timedelta(hours=1)).isoformat(),
            "arr_tracking": {
                "current_median_arr_pct": 120.0,
                "best_median_arr_pct": 180.0,
                "median_arr_delta_pct": 60.0,
            },
            "deploy_recommendation": "promote",
            "package_confidence_label": "high",
            "package_confidence_reasons": ["probe_live_validation_strong"],
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_loop" / "latest.json",
        {
            "summary": {"last_cycle_finished_at": now.isoformat()},
            "latest_entry": {
                "arr": {
                    "active_median_arr_pct": 121.0,
                    "best_median_arr_pct": 170.0,
                    "median_arr_delta_pct": 49.0,
                },
                "deploy_recommendation": "shadow_only",
                "package_confidence_label": "high",
            },
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {"status": "unavailable", "checked_at": now.isoformat()},
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    scoreboard = runtime_truth["state_improvement"]["strategy_recommendations"]["public_performance_scoreboard"]
    truth_lattice = runtime_truth["state_improvement"]["strategy_recommendations"]["truth_lattice"]
    launch_packet = runtime_truth["launch_packet"]

    assert scoreboard["public_forecast_source_artifact"] == "reports/btc5_autoresearch_current_probe/latest.json"
    assert scoreboard["selected_deploy_recommendation"] == "promote"
    assert scoreboard["deploy_recommendation"] == "hold"
    assert scoreboard["deploy_recommendation_conflict"] is True
    assert scoreboard["deploy_recommendation_conflict_values"] == ["hold", "promote", "shadow_only"]
    assert scoreboard["forecast_confidence_label"] == "high"
    assert "forecast_artifact_deploy_conflict" in scoreboard["forecast_confidence_reasons"]
    assert scoreboard["forecast_best_arr_pct"] == 180.0
    assert scoreboard["forecast_arr_delta_pct"] == 60.0
    assert scoreboard["timebound_velocity_window_hours"] is not None
    assert scoreboard["timebound_velocity_forecast_gain_pct"] == 60.0
    assert scoreboard["timebound_velocity_forecast_gain_pct_per_day"] is not None
    assert truth_lattice["status"] == "broken"
    assert truth_lattice["repair_branch_required"] is True
    assert "forecast_deploy_recommendation_conflict_requires_repair_branch" in truth_lattice["broken_reasons"]
    assert (
        "forecast_deploy_recommendation_conflict_requires_repair_branch"
        in launch_packet["mandatory_outputs"]["block_reasons"]
    )


def test_write_remote_cycle_status_prefers_frontier_authoritative_standard_forecast_over_probe_conflict(
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
                "window_start_ts": 1773061200,
                "window_end_ts": 1773061500,
                "slug": "btc-updown-5m-1773061200",
                "decision_ts": 1773061499,
                "direction": "UP",
                "order_price": 0.49,
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
        tmp_path / "reports" / "btc5_autoresearch" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "arr_tracking": {
                "current_median_arr_pct": 100.0,
                "best_median_arr_pct": 140.0,
                "median_arr_delta_pct": 40.0,
            },
            "deploy_recommendation": "shadow_only",
            "selected_deploy_recommendation": "shadow_only",
            "package_confidence_label": "high",
            "selected_package_confidence_label": "high",
            "package_confidence_reasons": ["frontier_authoritative"],
            "runtime_package_selection": {
                "selection_source": "frontier_policy_loss",
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_current_probe" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "arr_tracking": {
                "current_median_arr_pct": 120.0,
                "best_median_arr_pct": 180.0,
                "median_arr_delta_pct": 60.0,
            },
            "deploy_recommendation": "hold",
            "package_confidence_label": "low",
            "package_confidence_reasons": ["probe_advisory_only"],
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_loop" / "latest.json",
        {
            "summary": {"last_cycle_finished_at": now.isoformat()},
            "latest_entry": {
                "arr": {
                    "active_median_arr_pct": 99.0,
                    "best_median_arr_pct": 130.0,
                    "median_arr_delta_pct": 31.0,
                },
                "deploy_recommendation": "shadow_only",
                "package_confidence_label": "medium",
            },
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {"status": "unavailable", "checked_at": now.isoformat()},
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    scoreboard = runtime_truth["state_improvement"]["strategy_recommendations"]["public_performance_scoreboard"]
    truth_lattice = runtime_truth["state_improvement"]["strategy_recommendations"]["truth_lattice"]

    assert scoreboard["public_forecast_source_artifact"] == "reports/btc5_autoresearch/latest.json"
    assert scoreboard["selected_deploy_recommendation"] == "shadow_only"
    assert scoreboard["deploy_recommendation"] == "shadow_only"
    assert scoreboard["deploy_recommendation_conflict"] is False
    assert "forecast_artifact_deploy_conflict" not in scoreboard["forecast_confidence_reasons"]
    assert "forecast_deploy_recommendation_conflict_requires_repair_branch" not in truth_lattice["broken_reasons"]


def test_write_remote_cycle_status_public_scoreboard_includes_wallet_closed_batch_metrics(
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
        tmp_path / "reports" / "btc5_autoresearch_loop" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "arr_tracking": {
                "current_median_arr_pct": 100.0,
                "best_median_arr_pct": 160.0,
                "median_arr_delta_pct": 60.0,
            },
            "deploy_recommendation": "promote",
            "package_confidence_label": "high",
            "package_confidence_reasons": ["fresh_probe"],
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 120.0,
            "reserved_order_usd": 10.0,
            "live_orders_count": 2,
            "live_orders": [],
            "open_positions_count": 5,
            "positions_initial_value_usd": 43.1,
            "positions_current_value_usd": 247.91,
            "positions_unrealized_pnl_usd": 4.0,
            "closed_positions_count": 128,
            "closed_positions_realized_pnl_usd": 84.6,
            "total_wallet_value_usd": 377.91,
            "closed_batch_metrics": {
                "btc_closed_cashflow_usd": 131.52,
                "btc_contracts_resolved": 128,
                "btc_wins": 75,
                "btc_losses": 53,
                "btc_profit_factor": 1.49,
                "btc_average_win_usd": 5.35,
                "btc_average_loss_usd": -5.10,
                "btc_closed_window_hours": 24.0,
                "all_book_closed_cashflow_usd": 84.60,
                "open_non_btc_notional_usd": 43.10,
                "conservative_closed_net_usd": 84.60,
                "all_book_closed_window_hours": 72.0,
            },
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": (now - timedelta(hours=10)).isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 1,
            "live_filled_pnl_usd": 1.0,
            "avg_live_filled_pnl_usd": 1.0,
            "latest_live_filled_at": (now - timedelta(hours=10)).isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    scoreboard = runtime_truth["state_improvement"]["strategy_recommendations"]["public_performance_scoreboard"]
    wallet_closed = scoreboard["wallet_closed_batch"]

    assert wallet_closed["btc_closed_cashflow_usd"] == 131.52
    assert wallet_closed["btc_contracts_resolved"] == 128
    assert wallet_closed["btc_profit_factor"] == 1.49
    assert wallet_closed["btc_closed_run_rate_pct_initial_capital"] is not None
    assert wallet_closed["btc_closed_run_rate_pct_current_portfolio"] is not None
    assert wallet_closed["conservative_all_book_run_rate_pct_initial_capital"] is not None
    assert scoreboard["fund_realized_arr_claim_status"] == "unblocked"


def test_write_remote_cycle_status_prefers_fresh_wallet_export_for_reporting(
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
                "direction": "UP",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.0,
                "created_at": (now - timedelta(hours=26)).isoformat(),
                "updated_at": (now - timedelta(hours=26)).isoformat(),
            }
        ],
    )
    _write_text(
        tmp_path / "data" / "Polymarket-History-2026-03-10 (1).csv",
        "\n".join(
            [
                "timestamp,market,status,cashflow_usd,portfolio_equity_usd,cumulative_closed_cashflow_usd,open_notional_usd,open_buy_notional_usd",
                f"{(now - timedelta(hours=25)).isoformat()},BTC Up or Down 5m,closed,50.00,300.00,50.00,40.00,0.00",
                f"{(now - timedelta(hours=1)).isoformat()},BTC Up or Down 5m,closed,84.60,380.00,84.60,43.10,0.00",
                f"{(now - timedelta(hours=1)).isoformat()},ETH Up or Down 5m,open,0.00,380.00,84.60,43.10,43.10",
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
            "free_collateral_usd": 120.0,
            "reserved_order_usd": 10.0,
            "live_orders_count": 2,
            "live_orders": [],
            "open_positions_count": 5,
            "positions_initial_value_usd": 43.1,
            "positions_current_value_usd": 247.91,
            "positions_unrealized_pnl_usd": 4.0,
            "closed_positions_count": 128,
            "closed_positions_realized_pnl_usd": 84.6,
            "total_wallet_value_usd": 377.91,
            "closed_batch_metrics": {
                "btc_closed_cashflow_usd": 131.52,
                "btc_contracts_resolved": 128,
                "btc_wins": 75,
                "btc_losses": 53,
                "btc_profit_factor": 1.49,
                "btc_average_win_usd": 5.35,
                "btc_average_loss_usd": -5.10,
                "btc_closed_window_hours": 24.0,
                "all_book_closed_cashflow_usd": 84.60,
                "open_non_btc_notional_usd": 43.10,
                "conservative_closed_net_usd": 84.60,
                "all_book_closed_window_hours": 72.0,
            },
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": (now - timedelta(hours=10)).isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 1,
            "live_filled_pnl_usd": 1.0,
            "avg_live_filled_pnl_usd": 1.0,
            "latest_live_filled_at": (now - timedelta(hours=10)).isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    strategy = runtime_truth["state_improvement"]["strategy_recommendations"]
    scoreboard = strategy["public_performance_scoreboard"]
    wallet_summary = strategy["wallet_reconciliation_summary"]
    control_plane = strategy["control_plane_consistency"]

    assert wallet_summary["source_class"] == "wallet_export_csv"
    assert wallet_summary["reporting_precedence"] == "wallet_export"
    assert wallet_summary["reporting_precedence_reason"] == "wallet_export_fresh_and_at_least_as_recent_as_btc5_probe"
    assert wallet_summary["wallet_export_freshness_label"] == "fresh"
    assert wallet_summary["btc5_probe_freshness_label"] == "stale"
    assert wallet_summary["btc_closed_markets"] == 2
    assert wallet_summary["btc_closed_net_cashflow_usd"] == 134.6
    assert wallet_summary["btc_open_markets"] == 0
    assert wallet_summary["non_btc_open_buy_notional_usd"] == 43.1
    assert strategy["portfolio_equity_delta_1d"] == 80.0
    assert strategy["closed_cashflow_delta_1d"] == 34.6
    assert strategy["open_notional_delta_1d"] == 3.1
    assert scoreboard["realized_btc5_sleeve_window_mode"] == "wallet_closed_batch"
    assert scoreboard["realized_btc5_sleeve_window_live_fills"] == 2
    assert scoreboard["realized_btc5_sleeve_window_pnl_usd"] == 134.6
    assert control_plane["truth_source_consistency"]["status"] == "mismatch"
    assert control_plane["truth_source_consistency"]["reporting_precedence"] == "wallet_export"
    assert control_plane["truth_source_consistency"]["wallet_export_freshness"] == "fresh"
    assert control_plane["truth_source_consistency"]["btc5_probe_freshness"] == "stale"
    assert "fresh_wallet_export_with_stale_btc5_probe" in control_plane["truth_source_consistency"]["reasons"]


def test_write_remote_cycle_status_prefers_downloads_activity_export_with_epoch_timestamps(
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
    monkeypatch.setenv("HOME", str(tmp_path))
    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ELASTIFUND_WALLET_EXPORT_DIRS", str(downloads_dir))
    _write_text(
        downloads_dir / "Polymarket-History-2026-03-11 (2).csv",
        "\n".join(
            [
                '"marketName",action,usdcAmount,tokenAmount,tokenName,timestamp,hash',
                f'"Deposited funds",Deposit,250,250,USDC,{int((now - timedelta(hours=2)).timestamp())},0xdeposit',
                f'"Bitcoin Up or Down - March 11, 6:00AM-6:05AM ET",Buy,5.00,10,Down,{int((now - timedelta(hours=1)).timestamp())},0xbuy1',
                f'"Bitcoin Up or Down - March 11, 6:00AM-6:05AM ET",Redeem,12.00,12,,{int((now - timedelta(minutes=30)).timestamp())},0xredeem1',
                f'"Bitcoin Up or Down - March 11, 6:05AM-6:10AM ET",Buy,4.50,9,Down,{int((now - timedelta(minutes=20)).timestamp())},0xbuy2',
                f'"Ethereum Up or Down - March 11, 6:10AM-6:15AM ET",Buy,7.00,14,Down,{int((now - timedelta(minutes=15)).timestamp())},0xbuy3',
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
            "free_collateral_usd": 120.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 2,
            "positions_initial_value_usd": 11.5,
            "positions_current_value_usd": 11.5,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 7.0,
            "total_wallet_value_usd": 131.5,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": (now - timedelta(hours=10)).isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 1,
            "live_filled_pnl_usd": 1.0,
            "avg_live_filled_pnl_usd": 1.0,
            "latest_live_filled_at": (now - timedelta(hours=10)).isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    wallet_summary = runtime_truth["state_improvement"]["strategy_recommendations"]["wallet_reconciliation_summary"]

    assert str(wallet_summary["source_artifact"]).endswith("Downloads/Polymarket-History-2026-03-11 (2).csv")
    assert wallet_summary["wallet_export_freshness_label"] == "fresh"
    assert wallet_summary["reporting_precedence"] == "wallet_export"
    assert wallet_summary["btc_closed_markets"] == 1
    assert wallet_summary["btc_closed_net_cashflow_usd"] == 7.0
    assert wallet_summary["btc_open_markets"] == 1
    assert wallet_summary["non_btc_open_buy_notional_usd"] == 7.0
    assert wallet_summary["row_count"] == 5
    assert wallet_summary["market_count"] == 3
    assert wallet_summary["net_trading_cash_flow_excluding_deposits_usd"] == -4.5
    assert wallet_summary["after_midnight_et_net_trading_cash_flow_usd"] == -4.5
    assert wallet_summary["maker_rebate_usdc"] == 0.0
    assert wallet_summary["zero_value_redeems"] == 0
    assert wallet_summary["top_realized_winners"][0]["market_name"] == "Bitcoin Up or Down - March 11, 6:00AM-6:05AM ET"
    assert wallet_summary["top_realized_winners"][0]["net_cash_flow_including_rebates_usd"] == 7.0
    assert wallet_summary["top_unresolved_exposures"][0]["market_name"] == "Ethereum Up or Down - March 11, 6:10AM-6:15AM ET"
    assert wallet_summary["top_unresolved_exposures"][0]["net_cash_flow_including_rebates_usd"] == -7.0


def test_write_remote_cycle_status_prefers_fresher_wallet_export_content_over_file_mtime(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime(2026, 3, 11, 15, 0, tzinfo=timezone.utc)
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
    monkeypatch.setenv("HOME", str(tmp_path))
    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ELASTIFUND_WALLET_EXPORT_DIRS", str(downloads_dir))
    stale_export = downloads_dir / "Polymarket-History-2026-03-11.csv"
    fresher_export = downloads_dir / "Polymarket-History-2026-03-11 (1).csv"
    _write_text(
        stale_export,
        "\n".join(
            [
                '"marketName",action,usdcAmount,tokenAmount,tokenName,timestamp,hash',
                f'"Bitcoin Up or Down - March 11, 6:00AM-6:05AM ET",Buy,5.00,10,Down,{int(datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc).timestamp())},0xbuy-stale',
            ]
        ),
    )
    _write_text(
        fresher_export,
        "\n".join(
            [
                '"marketName",action,usdcAmount,tokenAmount,tokenName,timestamp,hash',
                f'"Bitcoin Up or Down - March 11, 6:00AM-6:05AM ET",Buy,5.00,10,Down,{int(datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc).timestamp())},0xbuy-fresh',
                f'"Bitcoin Up or Down - March 11, 6:00AM-6:05AM ET",Redeem,12.00,12,,{int(datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc).timestamp())},0xredeem-fresh',
                f'"Will Harvey Weinstein be sentenced to no prison time?",Buy,28.0399,28.0399,Yes,{int(datetime(2026, 3, 11, 13, 30, tzinfo=timezone.utc).timestamp())},0xopen-fresh',
            ]
        ),
    )
    stale_stat = stale_export.stat()
    fresher_stat = fresher_export.stat()
    stale_export.touch()
    fresher_export.touch()
    os.utime(stale_export, (fresher_stat.st_atime + 60, fresher_stat.st_mtime + 60))
    os.utime(fresher_export, (stale_stat.st_atime, stale_stat.st_mtime))

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
            "open_positions_count": 1,
            "positions_initial_value_usd": 28.0399,
            "positions_current_value_usd": 28.0399,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 7.0,
            "total_wallet_value_usd": 148.0399,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": (now - timedelta(hours=10)).isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 1,
            "live_filled_pnl_usd": 1.0,
            "avg_live_filled_pnl_usd": 1.0,
            "latest_live_filled_at": (now - timedelta(hours=10)).isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    wallet_summary = runtime_truth["state_improvement"]["strategy_recommendations"]["wallet_reconciliation_summary"]

    assert str(wallet_summary["source_artifact"]).endswith("Downloads/Polymarket-History-2026-03-11 (1).csv")
    assert wallet_summary["row_count"] == 3
    assert wallet_summary["latest_timestamp"] == "2026-03-11T14:00:00+00:00"
    assert wallet_summary["net_trading_cash_flow_excluding_deposits_usd"] == -21.0399
    assert wallet_summary["top_unresolved_exposures"][0]["market_name"] == "Will Harvey Weinstein be sentenced to no prison time?"
    assert wallet_summary["top_unresolved_exposures"][0]["net_cash_flow_including_rebates_usd"] == -28.0399


def test_write_remote_cycle_status_capital_addition_readiness_defaults_to_btc5_test_tranche(
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
        {"generated_at": now.isoformat(), "artifact": "strategy_scale_comparison"},
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {"generated_at": now.isoformat(), "artifact": "signal_source_audit"},
    )
    rows = []
    base = 1773061200
    for idx in range(12):
        rows.append(
            {
                "window_start_ts": base + (idx * 300),
                "window_end_ts": base + (idx * 300) + 300,
                "slug": f"btc-updown-5m-{base + (idx * 300)}",
                "decision_ts": base + (idx * 300) + 299,
                "direction": "UP" if idx % 2 == 0 else "DOWN",
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 2.0 if idx < 8 else -1.0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        )
    _write_btc5_db(tmp_path / "data" / "btc_5min_maker.db", rows)
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_current_probe" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "deploy_recommendation": "promote",
            "package_confidence_label": "high",
            "arr_tracking": {
                "current_median_arr_pct": 100.0,
                "best_median_arr_pct": 150.0,
                "median_arr_delta_pct": 50.0,
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch" / "latest.json",
        {"generated_at": now.isoformat()},
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_loop" / "latest.json",
        {"summary": {"last_cycle_finished_at": now.isoformat()}},
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 1.0,
            "reserved_order_usd": 2.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 1,
            "positions_initial_value_usd": 5.0,
            "positions_current_value_usd": 5.1,
            "positions_unrealized_pnl_usd": 0.1,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 0.1,
            "total_wallet_value_usd": 8.2,
            "warnings": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    readiness = runtime_truth["state_improvement"]["strategy_recommendations"]["capital_addition_readiness"]
    assert readiness["fund"]["status"] == "hold"
    assert readiness["polymarket_btc5"]["status"] == "ready_test_tranche"
    assert readiness["polymarket_btc5"]["recommended_amount_usd"] == 100
    assert readiness["kalshi_weather"]["status"] == "hold"
    assert readiness["next_1000_usd"]["status"] == "hold"


def test_write_remote_cycle_status_reports_capital_conflicts_across_artifacts(
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
            "service_name": "btc-5min-maker.service",
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
    rows = []
    base_time = now - timedelta(hours=2)
    for idx in range(12):
        rows.append(
            {
                "window_start_ts": int((base_time + timedelta(minutes=5 * idx)).timestamp()),
                "window_end_ts": int((base_time + timedelta(minutes=5 * (idx + 1))).timestamp()),
                "slug": f"btc-updown-5m-{idx}",
                "decision_ts": int((base_time + timedelta(minutes=5 * idx, seconds=299)).timestamp()),
                "direction": "DOWN",
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 1.5,
                "created_at": (base_time + timedelta(minutes=5 * idx)).isoformat(),
                "updated_at": (base_time + timedelta(minutes=5 * idx)).isoformat(),
            }
        )
    _write_btc5_db(tmp_path / "data" / "btc_5min_maker.db", rows)
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_current_probe" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "deploy_recommendation": "promote",
            "package_confidence_label": "high",
            "arr_tracking": {
                "current_median_arr_pct": 1400.0,
                "best_median_arr_pct": 1650.0,
                "median_arr_delta_pct": 250.0,
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch" / "latest.json",
        {"generated_at": now.isoformat()},
    )
    _write_json(
        tmp_path / "reports" / "btc5_autoresearch_loop" / "latest.json",
        {"summary": {"last_cycle_finished_at": now.isoformat()}},
    )
    _write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "venue_scoreboard": [
                {
                    "venue": "polymarket",
                    "lane": "btc5",
                    "capital_status": "ready_scale",
                    "deployment_readiness": "ready_scale",
                    "stage_readiness": {"recommended_stage": 1},
                }
            ],
            "capital_allocation_recommendation": {
                "next_1000_usd": {
                    "status": "ready_scale",
                    "recommended_amount_usd": 1000,
                    "stage_readiness": {"recommended_stage": 1},
                }
            },
            "next_1000_usd": {
                "status": "ready_scale",
                "recommended_amount_usd": 1000,
                "stage_gate_reason": "Stage 1 is eligible now.",
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "audit_generated_at": now.isoformat(),
                "trade_attribution_ready": False,
                "wallet_flow_confirmation_ready": False,
                "supports_capital_allocation": False,
                "stage_upgrade_support_status": "limited",
                "best_component_source": "wallet_flow",
                "best_source_combo": "llm+wallet_flow",
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
            "free_collateral_usd": 1.0,
            "reserved_order_usd": 2.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 1,
            "positions_initial_value_usd": 5.0,
            "positions_current_value_usd": 5.1,
            "positions_unrealized_pnl_usd": 0.1,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 0.1,
            "total_wallet_value_usd": 8.2,
            "warnings": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    strategy = runtime_truth["state_improvement"]["strategy_recommendations"]
    scoreboard = strategy["public_performance_scoreboard"]
    control_plane = strategy["control_plane_consistency"]

    assert scoreboard["capital_stage_readiness"] == "ready_test_tranche"
    assert scoreboard["next_1000_usd_status"] == "hold"
    assert scoreboard["performance_split"]["capital_stage_readiness"] == "ready_test_tranche"
    assert control_plane["capital_consistency"]["status"] == "conflict"
    assert (
        "next_1000_status_conflict: runtime=hold strategy_scale=ready_scale"
        in control_plane["capital_consistency"]["reasons"]
    )
    assert "signal_source_audit_limits_stage_upgrade_but_strategy_scale_promotes" in control_plane["capital_consistency"]["reasons"]
    assert (
        control_plane["capital_consistency"]["artifacts"]["strategy_scale_comparison"]["next_1000_status"]
        == "ready_scale"
    )
    assert (
        control_plane["capital_consistency"]["artifacts"]["signal_source_audit"]["stage_upgrade_support_status"]
        == "limited"
    )


def test_write_remote_cycle_status_uses_cached_remote_btc5_rows_for_realized_run_rate(
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
    cached_rows = []
    base_ts = datetime(2026, 3, 9, 18, 0, tzinfo=timezone.utc)
    for idx in range(12):
        cached_rows.append(
            {
                "id": idx + 1,
                "window_start_ts": int((base_ts + timedelta(minutes=5 * idx)).timestamp()),
                "order_status": "live_filled",
                "pnl_usd": 1.5,
                "updated_at": (base_ts + timedelta(minutes=5 * idx)).isoformat(),
            }
        )
    _write_json(tmp_path / "reports" / "tmp_remote_btc5_window_rows.json", cached_rows)

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 225.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 1,
            "positions_initial_value_usd": 25.0,
            "positions_current_value_usd": 25.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 250.0,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 12,
            "live_filled_pnl_usd": 18.0,
            "avg_live_filled_pnl_usd": 1.5,
            "latest_live_filled_at": cached_rows[-1]["updated_at"],
            "recent_live_filled": cached_rows[-5:],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    scoreboard = runtime_truth["state_improvement"]["strategy_recommendations"]["public_performance_scoreboard"]

    assert scoreboard["realized_btc5_sleeve_window_mode"] == "trailing_12_live_fills"
    assert scoreboard["realized_btc5_sleeve_window_live_fills"] == 12
    assert scoreboard["realized_btc5_sleeve_window_hours"] is not None
    assert scoreboard["realized_btc5_sleeve_run_rate_pct"] is not None


def test_write_remote_cycle_status_uses_recent_remote_btc5_fills_for_execution_metrics(
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
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 225.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 225.0,
            "warnings": [],
        },
    )
    recent_rows = [
        {
            "id": 101,
            "window_start_ts": int((now - timedelta(minutes=15)).timestamp()),
            "order_status": "live_filled",
            "trade_size_usd": 12.08,
            "pnl_usd": 1.0,
            "updated_at": (now - timedelta(minutes=15)).isoformat(),
        },
        {
            "id": 102,
            "window_start_ts": int((now - timedelta(minutes=45)).timestamp()),
            "order_status": "live_filled",
            "trade_size_usd": 24.14,
            "pnl_usd": -1.0,
            "updated_at": (now - timedelta(minutes=45)).isoformat(),
        },
        {
            "id": 103,
            "window_start_ts": int((now - timedelta(minutes=95)).timestamp()),
            "order_status": "live_filled",
            "trade_size_usd": 10.0,
            "pnl_usd": 0.5,
            "updated_at": (now - timedelta(minutes=95)).isoformat(),
        },
    ]
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 185,
            "live_filled_pnl_usd": 6.5,
            "avg_live_filled_pnl_usd": 0.0351,
            "latest_live_filled_at": recent_rows[0]["updated_at"],
            "recent_live_filled": recent_rows,
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    state_improvement = runtime_truth["state_improvement"]

    assert state_improvement["per_venue_executed_notional_usd"]["polymarket_hourly"] == 36.22
    assert state_improvement["per_venue_executed_notional_usd"]["combined_hourly"] == 36.22
    assert state_improvement["per_venue_trade_counts"]["polymarket_hourly"] == 2
    assert state_improvement["per_venue_trade_counts"]["combined_hourly"] == 2
    assert state_improvement["five_metric_scorecard"]["metrics"]["executed_notional_usd"] == 36.22


def test_write_remote_cycle_status_prefers_nested_runtime_artifacts_for_candidate_funnel(
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
    _write_json(
        tmp_path / "reports" / "research" / "edge_scan" / "edge_scan_20260310T173641Z.json",
        {
            "generated_at": "2026-03-10T17:36:41+00:00",
            "recommended_action": "observe",
            "action_reason": "Nested edge scan is the newest artifact.",
            "candidate_markets": [
                {"slug": "btc-a"},
                {"slug": "btc-b"},
                {"slug": "btc-c"},
                {"slug": "btc-d"},
                {"slug": "btc-e"},
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "runtime" / "pipeline" / "pipeline_refresh_20260311T095942Z.json",
        {
            "generated_at": "2026-03-11T09:59:42+00:00",
            "pipeline_verdict": {
                "reasoning": "Nested pipeline refresh is the freshest funnel artifact.",
            },
            "threshold_sensitivity": {
                "current": {
                    "tradeable": 7,
                    "yes_reachable_markets": 4,
                    "no_reachable_markets": 7,
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
            "free_collateral_usd": 225.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 225.0,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 12,
            "live_filled_pnl_usd": 18.0,
            "avg_live_filled_pnl_usd": 1.5,
            "latest_live_filled_at": now.isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    state_improvement = runtime_truth["state_improvement"]

    assert runtime_truth["latest_edge_scan"]["path"] == "reports/research/edge_scan/edge_scan_20260310T173641Z.json"
    assert runtime_truth["latest_pipeline"]["path"] == "reports/runtime/pipeline/pipeline_refresh_20260311T095942Z.json"
    assert state_improvement["per_venue_candidate_counts"]["polymarket"] == 5
    assert state_improvement["per_venue_candidate_counts"]["total"] == 5
    assert state_improvement["metrics"]["edge_reachability"] == 7.0


def test_write_remote_cycle_status_uses_fresh_wallet_reconciliation_when_remote_probe_unavailable(
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
    _write_json(
        tmp_path / "reports" / "wallet_reconciliation" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "status": "ok",
            "user_address": "0xabc",
            "wallet_reconciliation_summary": {
                "checked_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                "status": "ready_for_launch_gate",
                "stage_gate_ready": True,
                "open_positions_count": 7,
                "closed_positions_count": 50,
                "wallet_export_freshness_label": "fresh",
            },
            "capital_attribution": {
                "wallet_value_usd": 550.8009,
                "free_collateral_usd": 428.0927,
                "reserved_order_usd": 17.58,
                "open_position_costs_usd": 87.2602,
                "open_position_current_value_usd": 105.1282,
                "capital_accounting_delta_usd": 0.0,
            },
            "open_positions": {"count": 7, "rows": []},
            "closed_positions": {"count": 50, "rows": []},
        },
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "unavailable",
            "checked_at": now.isoformat(),
            "reason": "remote_wallet_probe_failed",
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 57,
            "live_filled_pnl_usd": 76.2989,
            "avg_live_filled_pnl_usd": 1.3386,
            "latest_live_filled_at": now.isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    accounting = runtime_truth["accounting_reconciliation"]

    assert accounting["remote_wallet_counts"]["status"] == "ok"
    assert accounting["remote_wallet_counts"]["source"] == "reports/wallet_reconciliation/latest.json"
    assert accounting["remote_wallet_counts"]["open_positions"] == 7
    assert accounting["remote_wallet_counts"]["closed_positions"] == 50
    assert not any(
        str(reason).startswith("remote_wallet_unavailable")
        for reason in accounting["drift_reasons"]
    )
    assert runtime_truth["runtime"]["closed_trades"] == 50
    assert "no_closed_trades" not in runtime_truth["launch"]["blocked_checks"]
    assert "no_deployed_capital" not in runtime_truth["launch"]["blocked_checks"]


def test_write_remote_cycle_status_materializes_allowlisted_aliases_from_legacy_index(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_json(
        tmp_path / "reports" / "legacy_aliases_latest.json",
        {
            "generated_at": now.isoformat(),
            "allowlist": [
                "strategy_scale_comparison.json",
                "signal_source_audit.json",
                "root_test_status.json",
                "arb_empirical_snapshot.json",
            ],
            "aliases": {
                "reports/strategy_scale_comparison.json": "reports/research/scale_comparison/strategy_scale_comparison.json",
                "reports/signal_source_audit.json": "reports/runtime/signals/signal_source_audit.json",
                "reports/root_test_status.json": "reports/runtime/verification/root_test_status.json",
                "reports/arb_empirical_snapshot.json": "reports/research/structural_alpha/arb_empirical_snapshot.json",
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "runtime" / "verification" / "root_test_status.json",
        {
            "checked_at": now.isoformat(),
            "command": "make test",
            "status": "passing",
            "summary": "12 passed",
        },
    )
    _write_json(
        tmp_path / "reports" / "research" / "structural_alpha" / "arb_empirical_snapshot.json",
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
        tmp_path / "reports" / "research" / "scale_comparison" / "strategy_scale_comparison.json",
        {
            "generated_at": now.isoformat(),
            "capital_allocation_recommendation": {
                "next_1000_usd": {
                    "status": "hold",
                    "recommended_amount_usd": 0,
                }
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "runtime" / "signals" / "signal_source_audit.json",
        {
            "generated_at": now.isoformat(),
            "capital_ranking_support": {
                "audit_generated_at": now.isoformat(),
                "stage_upgrade_support_status": "limited",
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
            "free_collateral_usd": 225.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 0,
            "positions_initial_value_usd": 0.0,
            "positions_current_value_usd": 0.0,
            "positions_unrealized_pnl_usd": 0.0,
            "closed_positions_count": 0,
            "closed_positions_realized_pnl_usd": 0.0,
            "total_wallet_value_usd": 225.0,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_btc5_maker_state",
        lambda root: {
            "status": "ok",
            "checked_at": now.isoformat(),
            "source": "remote_sqlite_probe",
            "db_path": "/remote/data/btc_5min_maker.db",
            "live_filled_rows": 0,
            "live_filled_pnl_usd": 0.0,
            "avg_live_filled_pnl_usd": 0.0,
            "latest_live_filled_at": now.isoformat(),
            "recent_live_filled": [],
        },
    )

    write_remote_cycle_status(tmp_path)
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())

    assert (tmp_path / "reports" / "strategy_scale_comparison.json").is_symlink()
    assert (tmp_path / "reports" / "signal_source_audit.json").is_symlink()
    assert (tmp_path / "reports" / "root_test_status.json").is_symlink()
    assert (tmp_path / "reports" / "arb_empirical_snapshot.json").is_symlink()
    assert runtime_truth["verification"]["status"] == "passing"
    artifacts = runtime_truth["state_improvement"]["strategy_recommendations"]["control_plane_consistency"]["capital_consistency"]["artifacts"]
    assert artifacts["strategy_scale_comparison"]["exists"] is True
    assert artifacts["signal_source_audit"]["exists"] is True
