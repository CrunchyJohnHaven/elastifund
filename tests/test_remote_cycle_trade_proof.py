from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from scripts.write_remote_cycle_status import write_remote_cycle_status  # noqa: E402
from test_remote_cycle_status import (  # noqa: E402
    _write_base_remote_state,
    _write_btc5_db,
    _write_json,
)
from _remote_cycle_status_shared import _write_validated_btc5_package  # noqa: E402


def test_write_remote_cycle_status_emits_trade_proof_artifact(tmp_path: Path, monkeypatch) -> None:
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-14T18:00:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
            "service_name": "btc-5min-maker.service",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-14T18:01:00+00:00",
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
    _write_validated_btc5_package(
        tmp_path,
        generated_at=datetime(2026, 3, 14, 17, 58, tzinfo=timezone.utc),
        selected_active_profile_name="active_profile_probe_d0_00075",
        selected_best_profile_name="active_profile_probe_d0_00075",
        validation_live_filled_rows=12,
        generalization_ratio=0.92,
        confidence_label="medium",
        deploy_recommendation="shadow_only",
    )
    _write_btc5_db(
        tmp_path / "data" / "btc_5min_maker.db",
        [
            {
                "window_start_ts": 1773501600,
                "window_end_ts": 1773501900,
                "slug": "btc-updown-5m-1773501600",
                "decision_ts": 1773501899,
                "direction": "DOWN",
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "order_status": "live_filled",
                "filled": 1,
                "pnl_usd": 5.11,
                "created_at": "2026-03-14T17:59:59+00:00",
                "updated_at": "2026-03-14T18:00:00+00:00",
            }
        ],
    )

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-14T18:00:00+00:00",
            "free_collateral_usd": 125.0,
            "reserved_order_usd": 0.0,
            "open_positions_count": 1,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": 5.11,
            "warnings": [],
        },
    )

    written = write_remote_cycle_status(tmp_path)

    trade_proof = json.loads((tmp_path / "reports" / "trade_proof" / "latest.json").read_text())
    runtime_truth = json.loads((tmp_path / "reports" / "runtime_truth_latest.json").read_text())
    status = json.loads((tmp_path / "reports" / "remote_cycle_status.json").read_text())

    assert Path(written["trade_proof_latest"]).exists()
    for payload in (trade_proof, runtime_truth, status):
        assert payload["artifact"]
        assert payload["generated_at"]
        assert payload["status"] in {"fresh", "stale", "blocked", "error"}
        assert isinstance(payload["blockers"], list)
    assert trade_proof["artifact"] == "btc5_trade_proof"
    assert trade_proof["proof_status"] == "fill_confirmed"
    assert trade_proof["fill_confirmed"] is True
    assert "reports/runtime_truth_latest.json" in trade_proof["source_of_truth"]
    assert trade_proof["freshness_sla_seconds"] == 3600
    assert trade_proof["stale_after"].endswith("Z")
    assert trade_proof["summary"].startswith("BTC5 trade proof")
    assert trade_proof["lane_id"] == "maker_bootstrap_live"
    assert trade_proof["strategy_family"] == "btc5_maker_bootstrap"
    assert trade_proof["profile_id"] == "active_profile_probe_d0_00075"
    assert trade_proof["trade_size_usd"] == 5.0
    assert trade_proof["order_price"] == 0.49
    assert trade_proof["attribution_mode"] == "trade_log_fallback_only"
    assert trade_proof["missing_fields"] == []
    assert runtime_truth["source_of_truth"] is not None
    assert runtime_truth["freshness_sla_seconds"] >= 900
    assert runtime_truth["attribution"]["attribution_mode"] == "trade_log_fallback_only"
    assert runtime_truth["attribution"]["profile_id"] == "active_profile_probe_d0_00075"
    assert runtime_truth["trade_proof"]["proof_status"] == "fill_confirmed"
    assert runtime_truth["trade_confirmation"]["profile_id"] == "active_profile_probe_d0_00075"
    assert status["attribution"]["attribution_mode"] == "trade_log_fallback_only"
    assert status["attribution"]["profile_id"] == "active_profile_probe_d0_00075"
    assert status["trade_proof"]["proof_status"] == "fill_confirmed"
