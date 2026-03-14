from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import scripts.btc5_dual_autoresearch_ops as ops
from scripts.btc5_dual_autoresearch_ops import (
    LANE_SPECS,
    build_lane_snapshot,
    build_morning_packet,
    build_surface_snapshot,
    update_lane_state_after_run,
)


def test_build_lane_snapshot_extracts_market_champion_and_health(tmp_path: Path) -> None:
    now = datetime(2026, 3, 11, 16, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "champion": {
                "candidate_model_name": "empirical_backoff_v1",
                "candidate_hash": "abc123",
                "candidate_label": "baseline-market",
                "loss": 5.178,
                "generated_at": (now - timedelta(hours=1)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [
            {
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "status": "keep",
                "experiment_id": "market-exp-6",
                "loss": 1.3,
            },
            {
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "status": "discard",
                "experiment_id": "market-exp-7",
                "loss": 1.28,
            },
        ],
    )
    chart_path = tmp_path / "research" / "btc5_market_model_progress.svg"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_text("<svg/>", encoding="utf-8")

    snapshot = build_lane_snapshot(
        LANE_SPECS["market"],
        repo_root=tmp_path,
        state={"lanes": {}},
        now=now,
    )

    assert snapshot["status"] == "healthy"
    assert snapshot["champion"]["id"] == "baseline-market"
    assert snapshot["champion"]["loss"] == 5.178
    assert snapshot["champion"]["model_name"] == "empirical_backoff_v1"
    assert snapshot["recent_experiment_count_24h"] == 2
    assert snapshot["recent_keep_count_24h"] == 1
    assert snapshot["recent_discard_count_24h"] == 1
    assert snapshot["command_available"] is True
    assert snapshot["command"] == [ops.sys.executable, "scripts/run_btc5_market_model_autoresearch.py"]
    assert snapshot["blockers"] == []


def test_update_lane_state_after_run_uses_exponential_backoff() -> None:
    now = datetime(2026, 3, 11, 17, 0, tzinfo=UTC)
    first = update_lane_state_after_run(
        {},
        success=False,
        now=now,
        spec=LANE_SPECS["policy"],
        status_label="runner_failed",
    )
    second = update_lane_state_after_run(
        first,
        success=False,
        now=now,
        spec=LANE_SPECS["policy"],
        status_label="runner_failed",
    )

    assert first["consecutive_failures"] == 1
    assert first["backoff_until"] == (now + timedelta(seconds=180)).isoformat()
    assert second["consecutive_failures"] == 2
    assert second["backoff_until"] == (now + timedelta(seconds=360)).isoformat()


def test_lane_specs_match_service_timeout_budget_contract() -> None:
    assert LANE_SPECS["market"].timeout_seconds == 1800
    assert LANE_SPECS["command_node"].timeout_seconds == 1800
    assert LANE_SPECS["policy"].timeout_seconds == 600
    assert LANE_SPECS["policy"].command_candidates[0] == (
        ops.sys.executable,
        "scripts/run_btc5_policy_autoresearch.py",
        "--skip-cycle",
    )


def test_build_morning_packet_collects_keeps_promotions_and_crashes(tmp_path: Path) -> None:
    now = datetime(2026, 3, 11, 18, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "champion": {
                "candidate_model_name": "empirical_backoff_v1",
                "candidate_label": "market-exp-8",
                "loss": 1.1,
                "generated_at": now.isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [
            {
                "timestamp": (now - timedelta(hours=3)).isoformat(),
                "status": "discard",
                "experiment_id": "market-exp-7",
                "loss": 1.4,
            },
            {
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "status": "keep",
                "experiment_id": "market-exp-8",
                "loss": 1.1,
            }
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "best_runtime_package": {"profile": {"name": "policy-beta"}},
            "decision": {"action": "promote"},
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [
            {
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "status": "keep",
                "candidate_policy": "policy-beta",
                "promotion_state": "live_promoted",
                "loss": -25.0,
            }
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "champion": {
                "candidate_label": "prompt-22",
                "loss": 6.0,
                "generated_at": now.isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [
            {
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
                "status": "crash",
                "prompt_hash": "prompt-23",
            }
        ],
    )

    for chart_relative in (
        "research/btc5_market_model_progress.svg",
        "research/btc5_command_node_progress.svg",
    ):
        chart_path = tmp_path / chart_relative
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        chart_path.write_text("<svg/>", encoding="utf-8")

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_morning_packet(surface, now=now, window_hours=24)
    written = ops.write_morning_packet(surface, repo_root=tmp_path, now=now, window_hours=24)
    markdown = (tmp_path / "reports" / "autoresearch" / "morning" / "latest.md").read_text(encoding="utf-8")

    assert packet["current_champions"]["policy"]["id"] == "policy-beta"
    assert packet["experiments_run"]["total"] == 4
    assert packet["experiments_run"]["by_lane"] == {
        "market": 2,
        "policy": 1,
        "command_node": 1,
    }
    assert any(item["lane"] == "market" for item in packet["kept_improvements"])
    assert any(item["lane"] == "policy" for item in packet["promotions"])
    assert any(item["lane"] == "command_node" for item in packet["crashes"])
    assert packet["summary_lines"][1] == "Benchmark progress only, not realized P&L."
    assert written["audit_trail_paths"]["service_audit_jsonl"] == "reports/autoresearch/ops/service_audit.jsonl"
    assert "## Benchmark Charts" in markdown
    assert "## Champion Summaries" in markdown
    assert "## Experiments Run" in markdown
    assert "- total: 4" in markdown
    assert "research/btc5_market_model_progress.svg" in markdown
    assert "research/btc5_command_node_progress.svg" in markdown


def test_run_lane_skips_during_backoff_and_appends_audit_rows(tmp_path: Path, monkeypatch) -> None:
    first_now = datetime(2026, 3, 11, 19, 0, tzinfo=UTC)
    second_now = first_now + timedelta(minutes=1)
    timestamps = iter([first_now, first_now + timedelta(seconds=1)])

    def fake_utc_now() -> datetime:
        return next(timestamps)

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(ops, "_utc_now", fake_utc_now)
    monkeypatch.setattr(ops.subprocess, "run", fake_run)

    code, audit_record = ops.run_lane(
        LANE_SPECS["policy"],
        repo_root=tmp_path,
        override_command="python fake_lane.py",
        now=first_now,
    )
    skip_code, skip_record = ops.run_lane(
        LANE_SPECS["policy"],
        repo_root=tmp_path,
        override_command="python fake_lane.py",
        now=second_now,
    )

    assert code == 1
    assert audit_record["status"] == "runner_failed"
    assert skip_code == 0
    assert skip_record["status"] == "backoff_skip"

    audit_rows = _read_jsonl(tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl")
    assert [row["status"] for row in audit_rows] == ["runner_failed", "backoff_skip"]
    state = json.loads((tmp_path / "state" / "btc5_dual_autoresearch_state.json").read_text(encoding="utf-8"))
    assert state["lanes"]["policy"]["consecutive_failures"] == 1


def test_champion_extraction_uses_rich_metadata(tmp_path: Path) -> None:
    """Champion extraction pulls model_name and loss from champion dict."""
    now = datetime(2026, 3, 11, 20, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "champion": {
                "candidate_model_name": "garch_v2",
                "candidate_hash": "hash456",
                "candidate_label": "garch-baseline",
                "loss": 3.5,
                "generated_at": (now - timedelta(hours=1)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "experiment_id": "1", "loss": 3.5}],
    )
    chart_path = tmp_path / "research" / "btc5_market_model_progress.svg"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_text("<svg/>", encoding="utf-8")

    snapshot = build_lane_snapshot(
        LANE_SPECS["market"], repo_root=tmp_path, state={"lanes": {}}, now=now,
    )

    assert snapshot["champion"]["id"] == "garch-baseline"
    assert snapshot["champion"]["loss"] == 3.5
    assert snapshot["champion"]["model_name"] == "garch_v2"


def test_policy_lane_no_arr_chart_blocker(tmp_path: Path) -> None:
    """Policy lane chart_paths is empty — no ARR chart blocker."""
    now = datetime(2026, 3, 11, 20, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "best_runtime_package": {"profile": {"name": "policy-alpha"}},
            "decision": {"action": "promote"},
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "candidate_policy": "policy-alpha", "loss": -10.0}],
    )
    # Deliberately do NOT create btc5_arr_progress.svg — should not matter.

    snapshot = build_lane_snapshot(
        LANE_SPECS["policy"], repo_root=tmp_path, state={"lanes": {}}, now=now,
    )

    # No chart blockers at all.
    stale_chart_blockers = [b for b in snapshot["blockers"] if "arr_progress" in b]
    assert stale_chart_blockers == []


def test_champion_delta_fields_in_morning_packet(tmp_path: Path) -> None:
    """Morning packet includes champion_deltas with previous/current/changed/delta."""
    now = datetime(2026, 3, 11, 21, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {"generated_at": now.isoformat(), "champion": {"candidate_label": "new-market", "loss": 4.0, "generated_at": now.isoformat()}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "experiment_id": "1", "loss": 4.0}],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {"generated_at": now.isoformat(), "best_runtime_package": {"profile": {"name": "pol-a"}}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "candidate_policy": "pol-a", "loss": -20.0}],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {"generated_at": now.isoformat(), "champion": {"candidate_label": "cmd-v2", "loss": 2.0, "generated_at": now.isoformat()}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "prompt_hash": "cmd-v2", "loss": 2.0}],
    )
    for chart_relative in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        p = tmp_path / chart_relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<svg/>", encoding="utf-8")

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    previous_champions = {
        "market": {"id": "old-market", "loss": 5.0, "updated_at": (now - timedelta(hours=8)).isoformat()},
        "policy": {"id": "pol-a", "loss": -20.0, "updated_at": (now - timedelta(hours=8)).isoformat()},
        "command_node": {"id": "cmd-v1", "loss": 3.0, "updated_at": (now - timedelta(hours=8)).isoformat()},
    }
    packet = build_morning_packet(surface, now=now, window_hours=24, previous_champions=previous_champions)

    deltas = packet["champion_deltas"]
    # Market changed: old-market -> new-market, loss improved 5.0 -> 4.0, delta = -1.0
    assert deltas["market"]["changed"] is True
    assert deltas["market"]["previous_champion"]["id"] == "old-market"
    assert deltas["market"]["current_champion"]["id"] == "new-market"
    assert deltas["market"]["delta_if_comparable"] == -1.0
    # Policy unchanged (same id).
    assert deltas["policy"]["changed"] is False
    assert deltas["policy"]["delta_if_comparable"] is None
    # Command node changed.
    assert deltas["command_node"]["changed"] is True
    assert deltas["command_node"]["delta_if_comparable"] == -1.0


def test_morning_packet_separates_benchmark_and_live_blockers(tmp_path: Path) -> None:
    """Benchmark blockers and live posture blockers are separate lists."""
    now = datetime(2026, 3, 11, 22, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {"generated_at": now.isoformat(), "champion": {"candidate_label": "m1", "loss": 1.0, "generated_at": now.isoformat()}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "experiment_id": "1", "loss": 1.0}],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {"generated_at": now.isoformat(), "best_runtime_package": {"profile": {"name": "p1"}}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "candidate_policy": "p1", "loss": -5.0}],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {"generated_at": now.isoformat(), "champion": {"candidate_label": "c1", "loss": 0.0, "generated_at": now.isoformat()}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "prompt_hash": "c1", "loss": 0.0}],
    )
    for chart_relative in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        p = tmp_path / chart_relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<svg/>", encoding="utf-8")

    # Write a runtime_truth that creates live posture blockers.
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "launch_posture": "blocked",
            "allow_order_submission": True,
            "block_reasons": ["finance_gate_blocked:hold_no_spend"],
        },
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = build_morning_packet(surface, now=now, window_hours=24)

    # Live posture blockers should be separate from benchmark blockers.
    assert "finance_gate_blocked:hold_no_spend" in packet["live_posture_blockers"]
    assert "launch_posture_not_clear:blocked" in packet["live_posture_blockers"]
    # Benchmark blockers should not contain live posture items.
    for blocker in packet["benchmark_blockers"]:
        assert "finance_gate" not in blocker
        assert "launch_posture" not in blocker
    # Combined list still has both.
    assert "finance_gate_blocked:hold_no_spend" in packet["blockers"]


def test_morning_markdown_shows_model_name_and_deltas(tmp_path: Path) -> None:
    """Markdown rendering includes model_name in champion summaries and champion deltas section."""
    now = datetime(2026, 3, 11, 23, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {"generated_at": now.isoformat(), "champion": {"candidate_model_name": "garch_v3", "candidate_label": "mk1", "loss": 2.0, "generated_at": now.isoformat()}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "experiment_id": "1", "loss": 2.0}],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {"generated_at": now.isoformat(), "best_runtime_package": {"profile": {"name": "pol-x"}}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "candidate_policy": "pol-x", "loss": -8.0}],
    )
    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {"generated_at": now.isoformat(), "champion": {"candidate_label": "cn1", "loss": 1.0, "generated_at": now.isoformat()}},
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [{"timestamp": now.isoformat(), "status": "keep", "prompt_hash": "cn1", "loss": 1.0}],
    )
    for chart_relative in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        p = tmp_path / chart_relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<svg/>", encoding="utf-8")

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    previous_champions = {
        "market": {"id": "old-mk", "loss": 4.0},
        "command_node": {"id": "old-cn", "loss": 2.0},
    }
    packet = build_morning_packet(surface, now=now, window_hours=24, previous_champions=previous_champions)
    markdown = ops._render_morning_markdown(packet)

    assert "model=garch_v3" in markdown
    assert "## Champion Deltas" in markdown
    assert "changed=True" in markdown
    assert "## Benchmark Blockers" in markdown
    assert "## Live Posture Blockers" in markdown


def test_overnight_closeout_reports_improvement_and_null_result(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=20)).isoformat(),
            "champion": {
                "candidate_hash": "market-v2",
                "candidate_model_name": "market-v2",
                "loss": 0.9,
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
                "candidate_model_name": "market-v1",
                "loss": 1.4,
            },
            {
                "generated_at": (now - timedelta(hours=4)).isoformat(),
                "status": "discard",
                "candidate_hash": "market-try",
                "candidate_model_name": "market-try",
                "loss": 1.2,
            },
            {
                "generated_at": (now - timedelta(hours=2)).isoformat(),
                "status": "keep",
                "candidate_hash": "market-v2",
                "candidate_model_name": "market-v2",
                "loss": 0.9,
                "decision_reason": "improved_frontier",
            },
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=25)).isoformat(),
            "champion": {
                "policy_id": "policy-live",
                "package_hash": "policy-live-package",
                "policy_loss": -12.0,
                "generated_at": (now - timedelta(minutes=25)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=14)).isoformat(),
                "status": "keep",
                "candidate_policy": "policy-live",
                "package_hash": "policy-live-package",
                "policy_loss": -12.0,
            },
            {
                "generated_at": (now - timedelta(hours=1)).isoformat(),
                "status": "discard",
                "candidate_policy": "policy-try",
                "package_hash": "policy-try-package",
                "candidate_policy_loss": -10.0,
                "incumbent_policy": "policy-live",
                "incumbent_policy_loss": -12.0,
            },
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {
            "updated_at": (now - timedelta(minutes=15)).isoformat(),
            "champion": {
                "candidate_label": "baseline-command-node",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
                "updated_at": (now - timedelta(minutes=15)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [
            {
                "evaluated_at": (now - timedelta(hours=13)).isoformat(),
                "status": "keep",
                "candidate_label": "baseline-command-node",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
            },
            {
                "evaluated_at": (now - timedelta(hours=1)).isoformat(),
                "status": "discard",
                "candidate_label": "candidate-try",
                "prompt_hash": "cmd-v2",
                "loss": 2.3,
            },
        ],
    )

    for chart_relative in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        chart_path = tmp_path / chart_relative
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        chart_path.write_text("<svg/>", encoding="utf-8")

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10, minutes=30), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=9), lane="policy"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1, minutes=30), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = ops.write_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)
    markdown = (
        tmp_path / "reports" / "autoresearch" / "overnight_closeout" / "latest.md"
    ).read_text(encoding="utf-8")

    assert packet["overall_status"] == "green"
    assert packet["overall_checks"]["service_audit_span_at_least_8h"] is True
    assert packet["overall_checks"]["market_runs_at_least_4"] is True
    assert packet["overall_checks"]["command_node_runs_at_least_4"] is True
    assert packet["lanes"]["market"]["improved"] is True
    assert packet["lanes"]["market"]["changed"] is True
    assert packet["lanes"]["market"]["champion_before"]["id"] == "market-v1"
    assert packet["lanes"]["market"]["champion_after"]["id"] == "market-v2"
    assert packet["lanes"]["market"]["outcome"] == "improved"
    assert packet["lanes"]["command_node"]["changed"] is False
    assert packet["lanes"]["command_node"]["outcome"] == "no_better_candidate"
    assert packet["lanes"]["command_node"]["outcome_note"] == "no candidate beat the incumbent"
    assert packet["service_audit"]["lane_run_counts"]["market"] == 4
    assert packet["service_audit"]["lane_run_counts"]["command_node"] == 4
    assert packet["summary_lines"][1] == "Benchmark progress only, not realized P&L."
    assert "candidate beat the incumbent" in markdown
    assert "no candidate beat the incumbent" in markdown
    assert "objective_span_hours" in markdown


def test_overnight_closeout_rejects_short_local_window_even_without_crashes(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
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
                "candidate_model_name": "market-v1",
                "loss": 1.4,
            },
            {
                "generated_at": (now - timedelta(hours=1)).isoformat(),
                "status": "discard",
                "candidate_hash": "market-try",
                "candidate_model_name": "market-try",
                "loss": 1.6,
            },
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=15)).isoformat(),
            "champion": {
                "policy_id": "policy-live",
                "package_hash": "policy-live-package",
                "policy_loss": -12.0,
                "generated_at": (now - timedelta(minutes=15)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=14)).isoformat(),
                "status": "keep",
                "candidate_policy": "policy-live",
                "package_hash": "policy-live-package",
                "policy_loss": -12.0,
            },
            {
                "generated_at": (now - timedelta(hours=1)).isoformat(),
                "status": "discard",
                "candidate_policy": "policy-try",
                "package_hash": "policy-try-package",
                "candidate_policy_loss": -10.0,
                "incumbent_policy": "policy-live",
                "incumbent_policy_loss": -12.0,
            },
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {
            "updated_at": (now - timedelta(minutes=10)).isoformat(),
            "champion": {
                "candidate_label": "baseline-command-node",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
                "updated_at": (now - timedelta(minutes=10)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [
            {
                "evaluated_at": (now - timedelta(hours=13)).isoformat(),
                "status": "keep",
                "candidate_label": "baseline-command-node",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
            },
            {
                "evaluated_at": (now - timedelta(hours=1)).isoformat(),
                "status": "discard",
                "candidate_label": "candidate-try",
                "prompt_hash": "cmd-v2",
                "loss": 2.2,
            },
        ],
    )

    for chart_relative in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        chart_path = tmp_path / chart_relative
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        chart_path.write_text("<svg/>", encoding="utf-8")

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=2), lane="market"),
            _audit_run_row(when=now - timedelta(hours=1, minutes=45), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=1), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = ops.build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["overall_status"] == "red"
    assert packet["overall_checks"]["no_lane_crashes"] is True
    assert packet["overall_checks"]["service_audit_span_at_least_8h"] is False
    assert packet["overall_checks"]["market_runs_at_least_4"] is False
    assert packet["overall_checks"]["command_node_runs_at_least_4"] is False
    assert packet["lanes"]["market"]["outcome"] == "no_better_candidate"
    assert packet["lanes"]["command_node"]["outcome"] == "no_better_candidate"
    assert "service_audit_span_below_target" in " ".join(packet["blockers"])
    assert "market_run_count_below_target:2/4" in packet["blockers"]
    assert "command_node_run_count_below_target:2/4" in packet["blockers"]


def test_overnight_closeout_marks_null_result_and_crash_night(tmp_path: Path) -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _touch_script(tmp_path / "scripts" / "run_btc5_market_model_autoresearch.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_autoresearch_cycle.py")
    _touch_script(tmp_path / "scripts" / "run_btc5_command_node_autoresearch.py")

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=10)).isoformat(),
            "champion": {
                "candidate_hash": "market-v1",
                "candidate_model_name": "market-v1",
                "loss": 1.4,
                "generated_at": (now - timedelta(minutes=10)).isoformat(),
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
                "candidate_model_name": "market-v1",
                "loss": 1.4,
            },
            {
                "generated_at": (now - timedelta(hours=2)).isoformat(),
                "status": "discard",
                "candidate_hash": "market-try",
                "candidate_model_name": "market-try",
                "loss": 1.6,
            },
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "latest.json",
        {
            "generated_at": (now - timedelta(minutes=12)).isoformat(),
            "champion": {
                "policy_id": "policy-live",
                "package_hash": "policy-live-package",
                "policy_loss": -12.0,
                "generated_at": (now - timedelta(minutes=12)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl",
        [
            {
                "generated_at": (now - timedelta(hours=14)).isoformat(),
                "status": "keep",
                "candidate_policy": "policy-live",
                "package_hash": "policy-live-package",
                "policy_loss": -12.0,
            }
        ],
    )

    _write_json(
        tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json",
        {
            "updated_at": (now - timedelta(minutes=15)).isoformat(),
            "champion": {
                "candidate_label": "baseline-command-node",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
                "updated_at": (now - timedelta(minutes=15)).isoformat(),
            },
        },
    )
    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl",
        [
            {
                "evaluated_at": (now - timedelta(hours=13)).isoformat(),
                "status": "keep",
                "candidate_label": "baseline-command-node",
                "prompt_hash": "cmd-v1",
                "loss": 2.0,
            },
            {
                "evaluated_at": (now - timedelta(hours=1)).isoformat(),
                "status": "crash",
                "candidate_label": "candidate-try",
                "prompt_hash": "cmd-v2",
            },
        ],
    )

    for chart_relative in ("research/btc5_market_model_progress.svg", "research/btc5_command_node_progress.svg"):
        chart_path = tmp_path / chart_relative
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        chart_path.write_text("<svg/>", encoding="utf-8")

    _write_jsonl(
        tmp_path / "reports" / "autoresearch" / "ops" / "service_audit.jsonl",
        [
            _audit_run_row(when=now - timedelta(hours=11), lane="market"),
            _audit_run_row(when=now - timedelta(hours=10, minutes=30), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=8), lane="market"),
            _audit_run_row(when=now - timedelta(hours=7), lane="command_node"),
            _audit_run_row(when=now - timedelta(hours=5), lane="market"),
            _audit_run_row(when=now - timedelta(hours=3), lane="command_node", status="runner_failed"),
            _audit_run_row(when=now - timedelta(hours=1, minutes=30), lane="market"),
            _audit_run_row(when=now - timedelta(minutes=30), lane="command_node"),
        ],
    )

    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    packet = ops.build_overnight_closeout(surface, repo_root=tmp_path, now=now, window_hours=12)

    assert packet["overall_status"] == "red"
    assert packet["overall_checks"]["service_audit_span_at_least_8h"] is True
    assert packet["overall_checks"]["market_runs_at_least_4"] is True
    assert packet["overall_checks"]["command_node_runs_at_least_4"] is True
    assert packet["overall_checks"]["no_lane_crashes"] is False
    assert packet["lanes"]["market"]["outcome"] == "no_better_candidate"
    assert packet["lanes"]["market"]["changed"] is False
    assert packet["lanes"]["market"]["outcome_note"] == "no candidate beat the incumbent"
    assert packet["lanes"]["command_node"]["outcome"] == "crash"
    assert packet["lanes"]["command_node"]["service_audit_failed_run_count"] == 1
    assert "lane_crashes:command_node" in packet["blockers"]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _touch_script(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _audit_run_row(
    *,
    when: datetime,
    lane: str,
    status: str = "ok",
    returncode: int | None = None,
) -> dict[str, object]:
    code = returncode if returncode is not None else (0 if status == "ok" else 1)
    return {
        "generated_at": when.isoformat(),
        "lane": lane,
        "event_type": "run",
        "status": status,
        "returncode": code,
        "duration_seconds": 60.0,
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
