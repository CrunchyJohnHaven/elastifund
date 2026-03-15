from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.render_instance2_directional_conversion_probe import build_directional_conversion_probe


UTC = timezone.utc


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_build_directional_conversion_probe_holds_live_widening_until_same_stream_shadow_exists() -> None:
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
        generated_at=datetime(2026, 3, 12, 15, 35, tzinfo=UTC),
    )

    assert payload["baseline_policy"]["policy_id"] == "active_profile_probe_d0_00075"
    assert payload["fresh_live_window_observation"]["window_count"] == 12
    assert payload["fresh_live_window_observation"]["status_counts"]["skip_delta_too_large"] == 10
    assert payload["latest_runtime_gap_observation"]["gap_detected"] is True
    assert payload["historical_order_path_proof"]["contains_live_fill"] is True
    assert payload["shadow_only_comparator"]["status"] == "not_captured_on_same_stream"
    assert payload["decision"]["selected_next_live_decision"] == "hold_and_wait_for_better_book_conditions"
    assert payload["candidate_delta_arr_bps"] == 0
    assert payload["arr_confidence_score"] == 0.11
    assert payload["finance_gate_pass"] is True
    assert "runtime_truth_latest_missing_btc5_latest_order_status_while_service_reports_running" in payload["block_reasons"]
