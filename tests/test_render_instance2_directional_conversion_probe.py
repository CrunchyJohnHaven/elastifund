from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.render_instance2_directional_conversion_probe import build_directional_conversion_probe


UTC = timezone.utc


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_build_directional_conversion_probe_holds_live_swap_until_same_stream_shadow_exists() -> None:
    start = datetime(2026, 3, 12, 12, 49, 50, tzinfo=UTC)
    archive_snapshots = []
    statuses = ["skip_delta_too_large"] * 10 + ["skip_bad_book", "skip_shadow_only_direction"]
    for idx, status in enumerate(statuses):
        created_at = start + timedelta(minutes=5 * idx)
        generated_at = created_at + timedelta(minutes=1)
        archive_snapshots.append(
            {
                "path": Path(f"runtime_truth_{idx:02d}.json"),
                "generated_at": generated_at,
                "payload": {
                    "generated_at": _iso(generated_at),
                    "btc_5min_maker": {
                        "checked_at": _iso(generated_at),
                        "source": "remote_sqlite_probe",
                        "latest_trade": {
                            "created_at": _iso(created_at),
                            "updated_at": _iso(created_at),
                            "window_start_ts": 1773319500 + (idx * 300),
                            "slug": f"btc-updown-5m-{1773319500 + (idx * 300)}",
                            "direction": "UP" if idx % 2 == 0 else "DOWN",
                            "order_status": status,
                        },
                    },
                },
            }
        )
    archive_snapshots.append(
        {
            "path": Path("runtime_truth_gap.json"),
            "generated_at": start + timedelta(hours=2, minutes=40),
            "payload": {
                "generated_at": _iso(start + timedelta(hours=2, minutes=40)),
                "btc_5min_maker": {
                    "checked_at": _iso(start + timedelta(hours=2, minutes=40)),
                    "source": "local_sqlite_db",
                    "latest_trade": {},
                },
            },
        }
    )
    runtime_truth = {
        "generated_at": _iso(start + timedelta(hours=2, minutes=44)),
        "allow_order_submission": True,
        "finance_gate_pass": True,
        "service_state": "running",
        "service_consistency": "consistent",
        "observed_service_name": "btc-5min-maker.service",
        "primary_service": "btc-5min-maker.service",
        "runtime": {
            "btc5_latest_order_status": None,
            "btc5_latest_window_start_ts": None,
            "btc5_live_filled_rows": 0,
            "btc5_live_filled_pnl_usd": 0.0,
        },
        "btc5_selected_package": {
            "selected_policy_id": "active_profile_probe_d0_00075",
            "selected_best_profile_name": "active_profile_probe_d0_00075",
        },
        "btc5_stage_readiness": {
            "trade_now_status": "unblocked",
            "baseline_live_status": "unblocked",
        },
    }
    historical_rows = []
    for idx in range(12):
        historical_rows.append(
            {
                "window_start_ts": 1773239100 + (idx * 300),
                "slug": f"btc-updown-5m-{1773239100 + (idx * 300)}",
                "updated_at": _iso(datetime(2026, 3, 11, 15, 0, tzinfo=UTC) + timedelta(minutes=5 * idx)),
                "order_status": "live_filled" if idx < 7 else "skip_loss_cluster_suppressed",
            }
        )

    payload = build_directional_conversion_probe(
        runtime_truth=runtime_truth,
        archive_snapshots=archive_snapshots,
        env_values={
            "BTC5_MAX_ABS_DELTA": "0.00075",
            "BTC5_UP_MAX_BUY_PRICE": "0.49",
            "BTC5_DOWN_MAX_BUY_PRICE": "0.51",
            "BTC5_SESSION_POLICY_JSON": "[]",
        },
        env_metadata={"candidate": "active_profile_probe_d0_00075"},
        historical_rows=historical_rows,
        policy_latest={
            "frontier_best_candidate": {
                "policy_id": "active_profile",
                "runtime_package": {
                    "profile": {
                        "name": "active_profile",
                        "max_abs_delta": 0.00015,
                        "up_max_buy_price": 0.49,
                        "down_max_buy_price": 0.51,
                    },
                    "session_policy": [],
                },
            }
        },
        generated_at=datetime(2026, 3, 12, 15, 35, tzinfo=UTC),
    )

    assert payload["baseline_policy"]["policy_id"] == "active_profile_probe_d0_00075"
    assert payload["baseline_policy"]["shadow_comparator_policy_id"] == "active_profile"
    assert payload["fresh_live_window_observation"]["window_count"] == 12
    assert payload["fresh_live_window_observation"]["status_counts"]["skip_delta_too_large"] == 10
    assert payload["latest_runtime_gap_observation"]["gap_detected"] is True
    assert payload["historical_order_path_proof"]["contains_live_fill"] is True
    assert payload["shadow_only_comparator"]["status"] == "not_captured_on_same_stream"
    assert payload["shadow_only_comparator"]["requested_profile"] == "active_profile"
    assert payload["decision"]["selected_next_live_decision"] == "hold_and_wait_for_better_book_conditions"
    assert payload["candidate_delta_arr_bps"] == 0
    assert payload["arr_confidence_score"] == 0.11
    assert payload["finance_gate_pass"] is True
    assert "runtime_truth_latest_missing_btc5_latest_order_status_while_service_reports_running" in payload["block_reasons"]


def test_build_directional_conversion_probe_uses_fresh_matched_window_comparator_and_canonical_package() -> None:
    start = datetime(2026, 3, 12, 18, 54, 50, tzinfo=UTC)
    archive_snapshots = []
    for idx in range(12):
        created_at = start + timedelta(minutes=5 * idx)
        generated_at = created_at + timedelta(minutes=1)
        archive_snapshots.append(
            {
                "path": Path(f"runtime_truth_{idx:02d}.json"),
                "generated_at": generated_at,
                "payload": {
                    "generated_at": _iso(generated_at),
                    "btc_5min_maker": {
                        "checked_at": _iso(generated_at),
                        "source": "remote_sqlite_probe",
                        "latest_trade": {
                            "created_at": _iso(created_at),
                            "updated_at": _iso(created_at),
                            "window_start_ts": 1773341100 + (idx * 300),
                            "slug": f"btc-updown-5m-{1773341100 + (idx * 300)}",
                            "direction": "UP" if idx % 2 == 0 else "DOWN",
                            "order_status": "skip_delta_too_large",
                        },
                    },
                },
            }
        )

    runtime_truth = {
        "generated_at": _iso(start + timedelta(hours=4)),
        "allow_order_submission": True,
        "finance_gate_pass": True,
        "service_state": "running",
        "service_consistency": "consistent",
        "btc5_selected_package": {
            "selected_policy_id": "current_live_profile",
            "selected_best_profile_name": "current_live_profile",
        },
        "btc5_stage_readiness": {
            "trade_now_status": "unblocked",
            "baseline_live_status": "unblocked",
        },
    }
    historical_rows = []
    for idx in range(60):
        updated_at = start + timedelta(minutes=5 * idx)
        abs_delta = 0.0001 if idx < 7 else 0.0006 if idx < 35 else 0.0012 if idx < 54 else 0.0019
        historical_rows.append(
            {
                "window_start_ts": 1773341100 + (idx * 300),
                "slug": f"btc-updown-5m-{1773341100 + (idx * 300)}",
                "direction": "UP" if idx % 2 == 0 else "DOWN",
                "abs_delta": abs_delta,
                "updated_at": _iso(updated_at),
                "order_status": "skip_delta_too_large" if idx >= 35 else "skip_toxic_order_flow",
            }
        )

    baseline_artifact = {
        "selected_package": {
            "selected_best_profile_name": "active_profile_probe_d0_00075",
            "selection_source": "reports/parallel/btc5_probe_cycle_d0_00075.json",
        }
    }

    payload = build_directional_conversion_probe(
        runtime_truth=runtime_truth,
        archive_snapshots=archive_snapshots,
        env_values={
            "BTC5_MAX_ABS_DELTA": "0.00075",
            "BTC5_UP_MAX_BUY_PRICE": "0.49",
            "BTC5_DOWN_MAX_BUY_PRICE": "0.51",
            "BTC5_SESSION_POLICY_JSON": "[]",
        },
        env_metadata={},
        historical_rows=historical_rows,
        historical_rows_path=Path("reports/tmp_remote_btc5_window_rows.json"),
        baseline_artifact=baseline_artifact,
        policy_latest={
            "frontier_best_candidate": {
                "policy_id": "active_profile",
                "runtime_package": {
                    "profile": {
                        "name": "active_profile",
                        "max_abs_delta": 0.00015,
                        "up_max_buy_price": 0.49,
                        "down_max_buy_price": 0.51,
                    },
                    "session_policy": [],
                },
            }
        },
        generated_at=datetime(2026, 3, 12, 23, 50, tzinfo=UTC),
    )

    comparator = payload["matched_window_live_vs_shadow_comparator"]
    assert payload["baseline_policy"]["policy_id"] == "active_profile_probe_d0_00075"
    assert payload["baseline_policy"]["canonical_live_package"]["alignment_status"] == "mismatch"
    assert payload["baseline_policy"]["shadow_comparator_policy_id"] == "active_profile"
    assert comparator["same_window_comparison_ready"] is True
    assert comparator["baseline_eligible_window_count"] == 35
    assert comparator["shadow_profile"] == "active_profile"
    assert comparator["shadow_eligible_window_count"] == 7
    assert comparator["shadow_restricted_window_count"] == 28
    assert payload["decision"]["selected_next_live_decision"] == "keep_0.00075"
    assert payload["candidate_delta_arr_bps"] == 0
    assert payload["expected_improvement_velocity_delta"] == 0.08
    assert payload["arr_confidence_score"] == 0.38
    assert "runtime_truth_selected_package_disagrees_with_canonical_live_baseline" in payload["block_reasons"]
    assert "matched_window_shadow_execution_delta_active_profile_not_measured" in payload["block_reasons"]
