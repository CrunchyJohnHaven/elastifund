"""Tests for Instance 3: outcome surfaces in packets and hardened overnight gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import scripts.btc5_dual_autoresearch_ops as ops
from scripts.btc5_dual_autoresearch_ops import (
    LANE_SPECS,
    append_outcome_record,
    build_morning_packet,
    build_overnight_closeout,
    build_surface_snapshot,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _touch_script(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")


def _audit_run_row(*, when: datetime, lane: str, status: str = "ok") -> dict:
    return {
        "generated_at": when.isoformat(),
        "lane": lane,
        "event_type": "run",
        "status": status,
        "duration_seconds": 60.0,
    }


def _setup_lane_artifacts(tmp_path: Path, now: datetime) -> None:
    """Set up minimal lane artifacts for all three lanes."""
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=20)).isoformat(),
            "champion": {
                "candidate_hash": "market-v1",
                "candidate_model_name": "market-v1",
                "loss": 1.4,
                "generated_at": (now - timedelta(minutes=20)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=14)).isoformat(),
                "status": "keep",
                "candidate_hash": "market-v1",
                "loss": 1.4,
            },
        ],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=15)).isoformat(),
            "champion": {"policy_id": "policy-live", "policy_loss": -12.0},
        },
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {
            "updated_at": (now - timedelta(minutes=10)).isoformat(),
            "champion": {
                "candidate_label": "baseline-cmd",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [
            {
                "evaluated_at": (now - timedelta(hours=13)).isoformat(),
                "status": "keep",
                "candidate_label": "baseline-cmd",
                "loss": 2.0,
            },
        ],
    )
    for chart_rel in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        chart = tmp_path / chart_rel
        chart.parent.mkdir(parents=True, exist_ok=True)
        chart.write_text("<svg/>", encoding="utf-8")


# --- Outcome surface integration tests ---


def test_morning_packet_includes_outcome_surfaces(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)
    _write_json(
        tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json",
        {
            "portfolio": {"wallet_value_usd": 247.51},
            "current_live": {
                "expected_pnl_per_day_usd": 38.19,
                "historical_pnl_per_day_usd": 26.95,
                "expected_fills_per_day": 104.0,
                "edge_status": {"status": "positive_but_tail_risky"},
            },
            "best_validated_variant": {
                "expected_pnl_per_day_usd": 42.50,
                "edge_status": {"status": "validated_positive"},
            },
        },
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_morning_packet(surface, now=now, repo_root=tmp_path)

    assert "outcome_surfaces" in packet
    outcome = packet["outcome_surfaces"]
    assert outcome["expected_usd_per_day"] == 38.19
    assert outcome["historical_usd_per_day"] == 26.95
    assert outcome["edge_status_current"] == "positive_but_tail_risky"
    assert outcome["disclaimer"] == "Outcome estimates, not realized P&L. Not benchmark loss metrics."


def test_overnight_closeout_includes_outcome_surfaces(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = ops.write_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert "outcome_surfaces" in packet
    assert packet["outcome_surfaces"]["source"] in ("portfolio_expectation", "outcome_ledger")


def test_surface_snapshot_includes_outcome_charts(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    # Create outcome charts
    arr_svg = tmp_path / "research" / "btc5_arr_progress.svg"
    arr_svg.parent.mkdir(parents=True, exist_ok=True)
    arr_svg.write_text("<svg/>", encoding="utf-8")

    usd_svg = tmp_path / "research" / "btc5_usd_per_day_progress.svg"
    usd_svg.write_text("<svg/>", encoding="utf-8")

    surface = ops.write_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    charts = surface["public_charts"]
    assert "arr_outcome" in charts
    assert "usd_per_day_outcome" in charts
    assert charts["arr_outcome"]["exists"] is True
    assert charts["usd_per_day_outcome"]["exists"] is True
    assert charts["arr_outcome"]["benchmark_progress_only"] is False
    assert charts["usd_per_day_outcome"]["benchmark_progress_only"] is False


def test_append_outcome_record_writes_to_ledger(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _write_json(
        tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=5)).isoformat(),
            "current_live": {
                "expected_pnl_per_day_usd": 38.19,
                "historical_pnl_per_day_usd": 26.95,
                "expected_fills_per_day": 104.0,
                "edge_status": {"status": "positive_but_tail_risky"},
            },
        },
    )
    record = append_outcome_record(tmp_path, now=now)
    assert record is not None
    assert record["expected_usd_per_day"] == 38.19

    ledger = tmp_path / "reports" / "autoresearch" / "outcomes" / "history.jsonl"
    assert ledger.exists()
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["expected_usd_per_day"] == 38.19
    assert rows[0]["source_generated_at"] == (now - timedelta(minutes=5)).isoformat()


def test_append_outcome_record_dedupes_same_portfolio_snapshot(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    generated_at = (now - timedelta(minutes=5)).isoformat()
    _write_json(
        tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json",
        {
            "generated_at": generated_at,
            "current_live": {
                "expected_pnl_per_day_usd": 38.19,
                "historical_pnl_per_day_usd": 26.95,
                "expected_fills_per_day": 104.0,
                "edge_status": {"status": "positive_but_tail_risky"},
            },
        },
    )
    first = append_outcome_record(tmp_path, now=now)
    second = append_outcome_record(tmp_path, now=now + timedelta(minutes=1))

    assert first is not None
    assert second is not None
    ledger = tmp_path / "reports" / "autoresearch" / "outcomes" / "history.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["source_generated_at"] == generated_at


def test_morning_packet_prefers_freshest_wallet_scaled_outcome_artifact(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)
    _write_json(
        tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json",
        {
            "generated_at": (now - timedelta(hours=2)).isoformat(),
            "portfolio": {"wallet_value_usd": 247.51},
            "current_live": {
                "expected_pnl_per_day_usd": 12.0,
                "historical_pnl_per_day_usd": 9.0,
                "expected_fills_per_day": 88.0,
                "edge_status": {"status": "stale_live"},
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "outcomes" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=5)).isoformat(),
            "expected_usd_per_day": 38.19,
            "historical_usd_per_day": 26.95,
            "expected_fills_per_day": 104.0,
            "expected_pnl_30d_usd": 1145.7,
        },
    )
    _write_json(
        tmp_path / "research" / "btc5_arr_latest.json",
        {
            "latest_active_arr_pct": 123.4,
            "frontier_active_arr_pct": 456.7,
            "latest_action": "hold",
            "latest_finished_at": (now - timedelta(minutes=10)).isoformat(),
        },
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_morning_packet(surface, now=now, repo_root=tmp_path)

    outcome = packet["outcome_surfaces"]
    assert outcome["source"] == "outcome_ledger"
    assert outcome["expected_usd_per_day"] == 38.19
    assert outcome["arr_latest_active_arr_pct"] == 123.4


def test_append_outcome_record_returns_none_without_pe(tmp_path: Path) -> None:
    record = append_outcome_record(tmp_path)
    assert record is None


def test_write_surface_snapshot_refreshes_outcome_surfaces(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)
    _write_json(
        tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json",
        {
            "portfolio": {"wallet_value_usd": 247.51},
            "current_live": {
                "expected_pnl_per_day_usd": 38.19,
                "historical_pnl_per_day_usd": 26.95,
                "expected_fills_per_day": 104.0,
                "edge_status": {"status": "positive_but_tail_risky"},
            },
            "best_validated_variant": {
                "expected_pnl_per_day_usd": 42.50,
                "expected_fills_per_day": 101.0,
                "edge_status": {"status": "validated_positive"},
            },
        },
    )
    _write_json(
        tmp_path / "research" / "btc5_arr_latest.json",
        {
            "latest_active_arr_pct": 123.4,
            "frontier_active_arr_pct": 156.7,
            "latest_best_arr_pct": 131.0,
            "latest_action": "hold",
            "latest_finished_at": (now - timedelta(minutes=5)).isoformat(),
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "outcomes" / "history.jsonl",
        [
            {
                "finished_at": (now - timedelta(hours=1)).isoformat(),
                "expected_usd_per_day": 38.19,
                "historical_usd_per_day": 26.95,
                "expected_fills_per_day": 104.0,
                "edge_status": "positive_but_tail_risky",
            },
        ],
    )

    ops.write_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)

    latest = json.loads((tmp_path / "reports" / "autoresearch" / "outcomes" / "latest.json").read_text())
    assert latest["expected_arr_pct"] == 123.4
    assert latest["expected_pnl_30d_usd"] == 1145.7
    assert latest["best_validated_variant"]["expected_usd_per_day"] == 42.5
    assert latest["current_vs_best_validated"]["expected_arr_pct_delta"] == 33.3
    assert latest["current_vs_best_validated"]["expected_usd_per_day_delta"] == 4.31
    assert (tmp_path / "research" / "btc5_usd_per_day_progress.svg").exists()


# --- Overnight gate hardening tests ---


def test_overnight_gate_rejects_short_local_run(tmp_path: Path) -> None:
    """A short local run (< 8h span, < 4 runs) must NOT produce green."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    # Only 2 audit rows, spanning 1 hour — far below 8h minimum.
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=1), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["overall_status"] == "red"
    assert packet["overall_checks"]["service_audit_span_at_least_8h"] is False
    assert packet["overall_checks"]["market_runs_at_least_4"] is False
    assert packet["overall_checks"]["command_node_runs_at_least_4"] is False


def test_overnight_gate_rejects_missing_market_runs(tmp_path: Path) -> None:
    """Even with 8h span, if market has < 4 runs the gate is red."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=8), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["overall_status"] == "red"
    assert packet["overall_checks"]["market_runs_at_least_4"] is False
    assert packet["overall_checks"]["command_node_runs_at_least_4"] is True


def test_overnight_gate_passes_valid_null_result_night(tmp_path: Path) -> None:
    """A null-result night (no improved candidates) passes green if gate criteria are met."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    # Add discards (no keeps) within the window.
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=14)).isoformat(),
                "status": "keep",
                "candidate_hash": "market-v1",
                "loss": 1.4,
            },
            {
                "generated_at": (now - timedelta(hours=3)).isoformat(),
                "status": "discard",
                "candidate_hash": "market-try",
                "loss": 1.6,
            },
        ],
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [
            {
                "evaluated_at": (now - timedelta(hours=13)).isoformat(),
                "status": "keep",
                "candidate_label": "baseline-cmd",
                "loss": 2.0,
            },
            {
                "evaluated_at": (now - timedelta(hours=2)).isoformat(),
                "status": "discard",
                "candidate_label": "cmd-try",
                "loss": 2.5,
            },
        ],
    )

    # 8+ hours span, 4+ runs per objective lane.
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["overall_status"] == "green"
    assert all(packet["overall_checks"].values())
    # Verify null-result lanes are tracked honestly.
    assert packet["lanes"]["market"]["outcome"] == "no_better_candidate"
    assert packet["lanes"]["command_node"]["outcome"] == "no_better_candidate"
    assert "market" in packet["null_result_lanes"]
    assert "command_node" in packet["null_result_lanes"]


def test_overnight_gate_rejects_lane_crash(tmp_path: Path) -> None:
    """A lane crash blocks green even if other criteria pass."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node", status="runner_failed"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["overall_status"] == "red"
    assert packet["overall_checks"]["no_lane_crashes"] is False
    assert "command_node" in packet["crashed_lanes"]


def test_overnight_gate_policy_crash_blocks_green(tmp_path: Path) -> None:
    """Policy lane crash blocks green — the spec says policy does not block unless it crashes."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    # Add policy crash to results.
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=2)).isoformat(),
                "status": "crash",
                "candidate_policy": "policy-bad",
            },
        ],
    )

    # Healthy service audit with enough market+command_node runs.
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    # Policy crash shows in lanes AND blocks green (crash_count > 0 for policy).
    assert packet["lanes"]["policy"]["outcome"] == "crash"
    assert packet["overall_checks"]["no_lane_crashes"] is False
    assert packet["overall_status"] == "red"


def test_overnight_gate_uses_burnin_start_marker(tmp_path: Path) -> None:
    """A fresh burn-in marker should ignore pre-deploy failures and judge only the new window."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=11, minutes=30)).isoformat(),
                "status": "crash",
                "candidate_policy": "policy-predeploy-bad",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11, minutes=30), lane="policy", status="runner_failed"),
            _audit_run_row(when=now - timedelta(hours=11, minutes=15), lane="market", status="runner_failed"),
            _audit_run_row(when=now - timedelta(hours=11), lane="command_node", status="runner_failed"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7, minutes=30), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=6), lane="market"),
            _audit_run_row(when=now - timedelta(hours=5, minutes=30), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=4), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3, minutes=30), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=2), lane="market"),
            _audit_run_row(when=now - timedelta(hours=1, minutes=30), lane="command_node"),
            _audit_run_row(when=now - timedelta(minutes=5), lane="market"),
            _audit_run_row(when=now, lane="command_node"),
        ],
    )
    ops.write_burnin_start_marker(
        repo_root=tmp_path,
        now=now - timedelta(hours=8, minutes=5),
        reason="deploy_btc5_autoresearch",
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["burnin_window_active"] is True
    assert packet["burnin_started_at"] == (now - timedelta(hours=8, minutes=5)).isoformat()
    assert packet["overall_checks"]["no_lane_crashes"] is True
    assert packet["overall_status"] == "green"


def test_morning_markdown_separates_benchmark_and_outcome_charts(tmp_path: Path) -> None:
    """Morning markdown must show benchmark charts and outcome charts as separate sections."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = ops.write_morning_packet(surface, repo_root=tmp_path, now=now)
    md = (tmp_path / "reports" / "autoresearch" / "morning" / "latest.md").read_text()

    assert "## Benchmark Charts" in md
    assert "## Outcome Charts (estimates, not benchmark loss)" in md


def test_overnight_markdown_includes_outcome_section(tmp_path: Path) -> None:
    """Overnight closeout markdown should include outcome surfaces section."""
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _setup_lane_artifacts(tmp_path, now)

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [_audit_run_row(when=now - timedelta(hours=1), lane="market")],
    )
    _write_json(
        tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json",
        {
            "portfolio": {"wallet_value_usd": 247.51},
            "current_live": {
                "expected_pnl_per_day_usd": 38.19,
                "historical_pnl_per_day_usd": 26.95,
                "expected_fills_per_day": 104.0,
                "edge_status": {"status": "positive_but_tail_risky"},
            },
            "best_validated_variant": {
                "expected_pnl_per_day_usd": 42.50,
                "edge_status": {"status": "validated_positive"},
            },
        },
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = ops.write_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)
    md = (tmp_path / "reports" / "autoresearch" / "overnight_closeout" / "latest.md").read_text()

    assert "## Outcome Surfaces (estimates, not benchmark loss)" in md
    assert "Expected USD/day" in md
    assert "38.19" in md
