from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.render_public_metrics import (
    build_public_metrics_contract,
    render_arr_estimate_svg,
    render_improvement_velocity_svg,
)


def test_build_public_metrics_contract_uses_probe_and_fallback_run_rate(tmp_path: Path) -> None:
    paths = _write_fixture_artifacts(tmp_path)

    contract = build_public_metrics_contract(
        public_runtime_snapshot_path=paths["public_runtime_snapshot"],
        runtime_truth_path=paths["runtime_truth"],
        remote_cycle_status_path=paths["remote_cycle_status"],
        root_test_status_path=paths["root_test_status"],
        forecast_artifact_paths=[
            paths["forecast_latest"],
            paths["forecast_current_probe"],
            paths["forecast_loop_latest"],
        ],
        loop_history_path=paths["loop_history"],
        btc5_window_rows_path=paths["window_rows"],
    )

    scoreboard = contract["scoreboard"]
    velocity = contract["timebound_velocity"]

    assert scoreboard["fund_realized_arr_claim_status"] == "blocked"
    assert "reconciliation" in scoreboard["fund_realized_arr_claim_reason"].lower()
    assert scoreboard["public_forecast_source_artifact"].endswith("reports/btc5_autoresearch_current_probe/latest.json")
    assert scoreboard["deploy_recommendation"] == "promote"
    assert scoreboard["forecast_confidence_label"] == "high"
    assert scoreboard["realized_btc5_sleeve_window_label"] == "trailing_12_live_fills"
    assert scoreboard["realized_btc5_sleeve_window_live_fills"] == 12
    assert scoreboard["realized_btc5_sleeve_window_pnl_usd"] == pytest.approx(18.0, abs=1e-6)
    assert scoreboard["realized_btc5_sleeve_window_hours"] == pytest.approx(11.0 / 6.0, abs=1e-4)
    expected_run_rate = (18.0 / 25.0) * ((24.0 * 365.0) / (11.0 / 6.0)) * 100.0
    assert scoreboard["realized_btc5_sleeve_run_rate_pct"] == pytest.approx(expected_run_rate, rel=1e-6)
    assert scoreboard["active_forecast_arr_pct"] == pytest.approx(1400.0, abs=1e-6)
    assert scoreboard["best_package_forecast_arr_pct"] == pytest.approx(1650.0, abs=1e-6)
    assert scoreboard["p05_forecast_arr_pct"] == pytest.approx(900.0, abs=1e-6)
    assert scoreboard["forecast_arr_delta_pct"] == pytest.approx(250.0, abs=1e-6)
    assert scoreboard["intraday_live_summary"]["filled_rows_today"] == 9
    assert scoreboard["intraday_live_summary"]["filled_pnl_usd_today"] == pytest.approx(22.5799, abs=1e-6)
    assert scoreboard["intraday_live_summary"]["recent_5_pnl_usd"] == pytest.approx(16.112, abs=1e-6)
    assert scoreboard["intraday_live_summary"]["recent_12_pnl_usd"] == pytest.approx(22.5799, abs=1e-6)
    assert scoreboard["intraday_live_summary"]["recent_20_pnl_usd"] == pytest.approx(56.486, abs=1e-6)
    assert scoreboard["intraday_live_summary"]["skip_price_count"] == 20
    assert scoreboard["intraday_live_summary"]["order_failed_count"] == 19
    assert scoreboard["intraday_live_summary"]["cancelled_unfilled_count"] == 3
    assert scoreboard["intraday_live_summary"]["best_direction_today"]["label"] == "DOWN"
    assert scoreboard["intraday_live_summary"]["best_price_bucket_today"]["label"] == "<0.49"
    assert velocity["cycles_in_window"] == 2
    assert velocity["forecast_arr_gain_pct"] == pytest.approx(250.0, abs=1e-6)
    assert velocity["validation_fill_growth"] == 8
    assert contract["confidence"]["label"] == "high"
    assert contract["arr_estimate"]["combined_current_pct"] == 0.0


def test_render_public_metrics_svgs_include_required_labels(tmp_path: Path) -> None:
    paths = _write_fixture_artifacts(tmp_path)

    contract = build_public_metrics_contract(
        public_runtime_snapshot_path=paths["public_runtime_snapshot"],
        runtime_truth_path=paths["runtime_truth"],
        remote_cycle_status_path=paths["remote_cycle_status"],
        root_test_status_path=paths["root_test_status"],
        forecast_artifact_paths=[
            paths["forecast_latest"],
            paths["forecast_current_probe"],
            paths["forecast_loop_latest"],
        ],
        loop_history_path=paths["loop_history"],
        btc5_window_rows_path=paths["window_rows"],
    )

    velocity_svg = tmp_path / "improvement_velocity.svg"
    arr_svg = tmp_path / "arr_estimate.svg"
    render_improvement_velocity_svg(velocity_svg, contract)
    render_arr_estimate_svg(arr_svg, contract)

    velocity_text = velocity_svg.read_text(encoding="utf-8")
    arr_text = arr_svg.read_text(encoding="utf-8")

    assert "BTC5 Public Improvement Velocity" in velocity_text
    assert "Source:" in velocity_text
    assert "Confidence:" in velocity_text
    assert "BTC5 Public ARR Surface" in arr_text
    assert "FUND-LEVEL REALIZED ARR CLAIM" in arr_text
    assert "reports/btc5_autoresearch_current_probe/latest.json" in arr_text


def _write_fixture_artifacts(tmp_path: Path) -> dict[str, Path]:
    reports = tmp_path / "reports"
    (reports / "btc5_autoresearch").mkdir(parents=True)
    (reports / "btc5_autoresearch_current_probe").mkdir(parents=True)
    (reports / "btc5_autoresearch_loop").mkdir(parents=True)

    base_time = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)

    _write_json(
        reports / "public_runtime_snapshot.json",
        {
            "generated_at": "2026-03-09T02:40:00+00:00",
            "runtime": {
                "btc5_live_filled_rows": 12,
                "btc5_live_filled_pnl_usd": 18.0,
                "btc5_intraday_live_summary": {
                    "filled_rows_today": 9,
                    "filled_pnl_usd_today": 22.5799,
                    "win_rate_today": 0.6667,
                    "recent_5_pnl_usd": 16.112,
                    "recent_12_pnl_usd": 22.5799,
                    "recent_20_pnl_usd": 56.486,
                    "skip_price_count": 20,
                    "order_failed_count": 19,
                    "cancelled_unfilled_count": 3,
                    "best_direction_today": {"label": "DOWN", "pnl_usd": 72.395, "fills": 41},
                    "best_price_bucket_today": {"label": "<0.49", "pnl_usd": 56.3008, "fills": 19},
                },
                "cycles_completed": 565,
                "closed_trades": 0,
                "total_trades": 5,
            },
            "capital": {"deployed_capital_usd": 25.0, "tracked_capital_usd": 347.51},
            "service": {"status": "stopped"},
            "launch": {"posture": "blocked", "fast_flow_restart_ready": True},
        },
    )

    _write_json(
        reports / "runtime_truth_latest.json",
        {
            "generated_at": "2026-03-09T02:40:00+00:00",
            "runtime": {
                "btc5_live_filled_rows": 12,
                "btc5_live_filled_pnl_usd": 18.0,
                "cycles_completed": 565,
                "closed_trades": 0,
                "total_trades": 5,
            },
            "capital": {"deployed_capital_usd": 25.0, "tracked_capital_usd": 347.51},
            "service": {"status": "stopped"},
            "launch": {"posture": "blocked"},
            "accounting_reconciliation": {
                "drift_detected": True,
                "drift_reasons": [
                    "open_positions_mismatch: local=4 remote=25 delta=+21",
                    "closed_positions_mismatch: local=0 remote=31 delta=+31",
                ],
            },
        },
    )

    _write_json(
        reports / "remote_cycle_status.json",
        {
            "generated_at": "2026-03-09T02:40:00+00:00",
            "service": {"status": "stopped"},
        },
    )

    _write_json(
        reports / "root_test_status.json",
        {
            "status": "passing",
            "summary": "1140 passed in 25.88s; 25 passed in 4.47s",
        },
    )

    _write_json(
        reports / "btc5_autoresearch/latest.json",
        {
            "generated_at": "2026-03-09T01:00:00+00:00",
            "arr_tracking": {
                "current_median_arr_pct": 1200.0,
                "best_median_arr_pct": 1300.0,
                "best_p05_arr_pct": 700.0,
                "median_arr_delta_pct": 100.0,
            },
            "decision": {"action": "hold", "median_arr_delta_pct": 100.0},
            "best_candidate": {
                "continuation": {"median_arr_pct": 1300.0, "p05_arr_pct": 700.0},
                "historical": {"replay_live_filled_rows": 9, "baseline_live_filled_rows": 12, "baseline_window_rows": 18},
                "profile": {"name": "grid_hold_candidate"},
            },
            "simulation_summary": {"baseline": {"deduped_live_filled_rows": 12, "deduped_rows": 18}},
        },
    )

    _write_json(
        reports / "btc5_autoresearch_current_probe/latest.json",
        {
            "generated_at": "2026-03-09T02:30:00+00:00",
            "deploy_recommendation": "promote",
            "package_confidence_label": "high",
            "package_confidence_reasons": [
                "validation_live_filled_rows=14",
                "generalization_ratio=0.91",
            ],
            "validation_live_filled_rows": 14,
            "arr_tracking": {
                "current_median_arr_pct": 1400.0,
                "best_median_arr_pct": 1650.0,
                "best_p05_arr_pct": 900.0,
                "median_arr_delta_pct": 250.0,
            },
            "active_runtime_package": {"profile": {"name": "current_live_profile"}},
            "best_runtime_package": {"profile": {"name": "probe_best_profile"}},
        },
    )

    _write_json(
        reports / "btc5_autoresearch_loop/latest.json",
        {
            "summary": {
                "cycles_total": 2,
                "last_cycle_started_at": "2026-03-09T00:30:00+00:00",
                "last_cycle_finished_at": "2026-03-09T01:30:00+00:00",
            }
        },
    )

    history_rows = [
        {
            "started_at": "2026-03-09T00:30:00+00:00",
            "finished_at": "2026-03-09T00:35:00+00:00",
            "arr": {
                "active_median_arr_pct": 1200.0,
                "best_median_arr_pct": 1300.0,
                "median_arr_delta_pct": 100.0,
            },
        },
        {
            "started_at": "2026-03-09T01:30:00+00:00",
            "finished_at": "2026-03-09T01:35:00+00:00",
            "arr": {
                "active_median_arr_pct": 1300.0,
                "best_median_arr_pct": 1450.0,
                "median_arr_delta_pct": 150.0,
            },
        },
    ]
    (reports / "btc5_autoresearch_loop/history.jsonl").write_text(
        "\n".join(json.dumps(row) for row in history_rows) + "\n",
        encoding="utf-8",
    )

    rows = []
    for index in range(12):
        updated_at = base_time + timedelta(minutes=index * 10)
        rows.append(
            {
                "id": index + 1,
                "window_start_ts": 1773057000 + index * 600,
                "order_status": "live_filled",
                "updated_at": updated_at.isoformat(),
                "realized_pnl_usd": 1.5,
            }
        )
    _write_json(reports / "tmp_remote_btc5_window_rows.json", rows)

    return {
        "public_runtime_snapshot": reports / "public_runtime_snapshot.json",
        "runtime_truth": reports / "runtime_truth_latest.json",
        "remote_cycle_status": reports / "remote_cycle_status.json",
        "root_test_status": reports / "root_test_status.json",
        "forecast_latest": reports / "btc5_autoresearch/latest.json",
        "forecast_current_probe": reports / "btc5_autoresearch_current_probe/latest.json",
        "forecast_loop_latest": reports / "btc5_autoresearch_loop/latest.json",
        "loop_history": reports / "btc5_autoresearch_loop/history.jsonl",
        "window_rows": reports / "tmp_remote_btc5_window_rows.json",
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
