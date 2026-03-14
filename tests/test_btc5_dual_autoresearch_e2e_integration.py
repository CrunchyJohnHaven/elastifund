from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.btc5_market.v1.benchmark import freeze_benchmark_from_rows
from scripts.btc5_dual_autoresearch_ops import build_morning_packet, build_surface_snapshot
import scripts.run_btc5_market_model_autoresearch as market_runner


ROOT = Path(__file__).resolve().parents[1]
MARKET_RUNNER = ROOT / "scripts" / "run_btc5_market_model_autoresearch.py"
POLICY_RUNNER = ROOT / "scripts" / "run_btc5_policy_autoresearch.py"
BASE_MARKET_CANDIDATE_SOURCE = (ROOT / "btc5_market_model_candidate.py").read_text(encoding="utf-8")


def _runtime_package(name: str, *, up_max_buy_price: float) -> dict[str, object]:
    return {
        "profile": {
            "name": name,
            "max_abs_delta": 0.00015,
            "up_max_buy_price": up_max_buy_price,
            "down_max_buy_price": 0.51,
        },
        "session_policy": [],
    }


def _synthetic_market_rows(count: int = 320) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start_ts = 1_773_057_000
    for index in range(count):
        direction = "UP" if index % 7 == 0 else "DOWN"
        pnl_pct = -0.30 if direction == "UP" else 0.04
        pnl_usd = pnl_pct * 10.0
        rows.append(
            {
                "id": index + 1,
                "window_start_ts": start_ts + (index * 300),
                "slug": f"e2e-window-{index:04d}",
                "direction": direction,
                "delta": 0.00009 if direction == "UP" else -0.00009,
                "abs_delta": 0.00009,
                "order_price": 0.50,
                "price_bucket": "0.49_to_0.51",
                "delta_bucket": "le_0.00010",
                "trade_size_usd": 10.0,
                "won": direction == "DOWN",
                "pnl_usd": pnl_usd,
                "realized_pnl_usd": pnl_usd,
                "order_status": "live_filled",
                "et_hour": 10,
                "session_name": "open_et",
                "best_bid": 0.49,
                "best_ask": 0.51,
                "open_price": 84_000.0,
                "current_price": 84_012.0,
                "edge_tier": "high" if direction == "DOWN" else "medium",
                "session_policy_name": "open_et",
                "effective_stage": 1,
                "loss_cluster_suppressed": 0,
                "source": "synthetic",
            }
        )
    return rows


def _write_market_model_candidate(path: Path) -> None:
    path.write_text(
        market_runner._replace_mutation_surface(
            BASE_MARKET_CANDIDATE_SOURCE,
            {
                "model_name": "e2e_market_baseline",
                "model_version": 1,
                "feature_levels": [[]],
                "target_priors": {"p_up": 0.5, "fill_rate": 0.5, "pnl_pct": 0.0},
                "target_smoothing": {"p_up": 20.0, "fill_rate": 20.0, "pnl_pct": 20.0},
                "global_backstop_weight_min": 0.25,
                "global_backstop_weight_max": 0.92,
                "pnl_fill_blend_base": 0.80,
                "pnl_fill_blend_scale": 0.20,
                "pnl_clamp_abs": 0.75,
            },
        ),
        encoding="utf-8",
    )


def _run_market_lane(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    benchmark_dir = tmp_path / "benchmarks" / "btc5_market"
    freeze_benchmark_from_rows(_synthetic_market_rows(), benchmark_dir=benchmark_dir)

    candidate = tmp_path / "btc5_market_model_candidate.py"
    _write_market_model_candidate(candidate)

    lane_dir = tmp_path / "reports" / "autoresearch" / "btc5_market"
    ledger = lane_dir / "results.jsonl"
    champion = lane_dir / "champion.json"
    latest_json = lane_dir / "latest.json"
    latest_md = lane_dir / "latest.md"
    policy_handoff = lane_dir / "policy_handoff.json"
    chart_svg = tmp_path / "research" / "btc5_market_model_progress.svg"
    packets = lane_dir / "packets"

    result = subprocess.run(
        [
            sys.executable,
            str(MARKET_RUNNER),
            "--allow-noncanonical-candidate",
            "--manifest",
            str(benchmark_dir / "manifest.json"),
            "--candidate-path",
            str(candidate),
            "--ledger",
            str(ledger),
            "--champion-path",
            str(champion),
            "--latest-json",
            str(latest_json),
            "--latest-md",
            str(latest_md),
            "--policy-handoff-json",
            str(policy_handoff),
            "--chart-out",
            str(chart_svg),
            "--packet-dir",
            str(packets),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return latest_json, policy_handoff, chart_svg, ledger, champion


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_cycle_payload(path: Path, *, active_package: dict[str, object], candidate_package: dict[str, object]) -> None:
    _write_json(
        path,
        {
            "generated_at": "2026-03-11T18:00:00+00:00",
            "selected_deploy_recommendation": "shadow_only",
            "selected_package_confidence_label": "high",
            "active_runtime_package": active_package,
            "selected_active_runtime_package": active_package,
            "best_runtime_package": candidate_package,
            "selected_best_runtime_package": candidate_package,
        },
    )


def _write_runtime_truth(path: Path, *, launch_posture: str) -> None:
    _write_json(
        path,
        {
            "launch_posture": launch_posture,
            "launch": {"posture": launch_posture},
            "allow_order_submission": launch_posture == "clear",
        },
    )


def _run_policy_lane(
    tmp_path: Path,
    *,
    cycle_json: Path,
    runtime_truth: Path,
    market_handoff: Path,
    market_latest: Path,
    lane_dir: Path,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            sys.executable,
            str(POLICY_RUNNER),
            "--skip-cycle",
            "--cycle-json",
            str(cycle_json),
            "--portfolio-json",
            str(tmp_path / "reports" / "btc5_portfolio_expectation" / "latest.json"),
            "--runtime-truth",
            str(runtime_truth),
            "--market-policy-handoff",
            str(market_handoff),
            "--market-latest-json",
            str(market_latest),
            "--results-ledger",
            str(lane_dir / "results.jsonl"),
            "--runs-dir",
            str(lane_dir / "runs"),
            "--champion-out",
            str(lane_dir / "champion.json"),
            "--promotion-decision-json",
            str(lane_dir / "promotion_decision.json"),
            "--latest-json",
            str(lane_dir / "latest.json"),
            "--latest-md",
            str(lane_dir / "latest.md"),
            "--active-env",
            str(tmp_path / "state" / "btc5_autoresearch.env"),
            "--active-package-json",
            str(lane_dir / "active_candidate.json"),
            "--staged-env",
            str(lane_dir / "staged_candidate.env"),
            "--staged-package-json",
            str(lane_dir / "staged_candidate.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result


def _seed_command_node_fixture(tmp_path: Path) -> None:
    latest = tmp_path / "reports" / "autoresearch" / "command_node" / "latest.json"
    ledger = tmp_path / "reports" / "autoresearch" / "command_node" / "results.jsonl"
    _write_json(
        latest,
        {
            "generated_at": "2026-03-11T18:02:00+00:00",
            "champion_id": "command-node-v2-fixture",
            "loss": 5.4,
        },
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "timestamp": "2026-03-11T18:02:00+00:00",
                "status": "keep",
                "prompt_hash": "command-node-v2-fixture",
                "loss": 5.4,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_ops_lane_prereqs(tmp_path: Path) -> None:
    for script_rel in (
        "scripts/run_btc5_market_model_autoresearch.py",
        "scripts/run_btc5_policy_autoresearch.py",
        "scripts/run_btc5_command_node_autoresearch.py",
    ):
        script = tmp_path / script_rel
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    for chart_rel in (
        "research/btc5_market_model_progress.svg",
        "research/btc5_arr_progress.svg",
        "research/btc5_command_node_progress.svg",
    ):
        chart = tmp_path / chart_rel
        chart.parent.mkdir(parents=True, exist_ok=True)
        if not chart.exists():
            chart.write_text("<svg/>", encoding="utf-8")


def test_e2e_market_to_policy_to_ops_shadow_then_live_activation(tmp_path: Path) -> None:
    market_latest, market_handoff, market_chart, market_ledger, market_champion = _run_market_lane(tmp_path)
    market_handoff_payload = json.loads(market_handoff.read_text(encoding="utf-8"))
    market_champion_hash = market_handoff_payload["market_champion"]["candidate_hash"]
    market_champion_experiment_id = market_handoff_payload["market_champion"]["id"]

    policy_lane_dir = tmp_path / "reports" / "autoresearch" / "btc5_policy"
    cycle_json = tmp_path / "reports" / "btc5_autoresearch" / "latest.json"
    runtime_truth = tmp_path / "reports" / "runtime_truth_latest.json"

    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
    )
    _write_runtime_truth(runtime_truth, launch_posture="blocked")

    blocked_run = _run_policy_lane(
        tmp_path,
        cycle_json=cycle_json,
        runtime_truth=runtime_truth,
        market_handoff=market_handoff,
        market_latest=market_latest,
        lane_dir=policy_lane_dir,
    )
    assert blocked_run.returncode == 0, blocked_run.stderr

    blocked_latest = json.loads((policy_lane_dir / "latest.json").read_text(encoding="utf-8"))
    blocked_decision = json.loads((policy_lane_dir / "promotion_decision.json").read_text(encoding="utf-8"))
    assert blocked_latest["latest_experiment"]["promotion_state"] == "shadow_updated"
    assert blocked_latest["staged_package"]["policy_id"] == "policy-beta"
    assert blocked_latest["live_package"]["policy_id"] == "current_live_profile"
    assert blocked_decision["action"] == "shadow_updated"
    assert blocked_decision["candidate"]["policy_id"] == "policy-beta"

    _write_runtime_truth(runtime_truth, launch_posture="clear")
    clear_run = _run_policy_lane(
        tmp_path,
        cycle_json=cycle_json,
        runtime_truth=runtime_truth,
        market_handoff=market_handoff,
        market_latest=market_latest,
        lane_dir=policy_lane_dir,
    )
    assert clear_run.returncode == 0, clear_run.stderr

    clear_latest = json.loads((policy_lane_dir / "latest.json").read_text(encoding="utf-8"))
    clear_decision = json.loads((policy_lane_dir / "promotion_decision.json").read_text(encoding="utf-8"))
    assert clear_latest["latest_experiment"]["promotion_state"] == "live_activated"
    assert clear_latest["champion_id"] == "policy-beta"
    assert clear_latest["live_package"]["policy_id"] == "policy-beta"
    assert clear_latest["staged_package"] is None
    assert clear_decision["action"] == "live_activated"
    assert clear_decision["champion_after"]["policy_id"] == "policy-beta"
    assert clear_decision["live_after"]["policy_id"] == "policy-beta"
    assert clear_decision["simulator_champion_id"] == market_champion_experiment_id

    _seed_command_node_fixture(tmp_path)
    _seed_ops_lane_prereqs(tmp_path)
    # Keep chart timestamp from market runner as real benchmark output.
    assert market_chart.exists()
    assert market_ledger.exists()
    assert market_champion.exists()

    now = datetime(2026, 3, 11, 18, 10, tzinfo=UTC)
    surface = build_surface_snapshot(repo_root=tmp_path, state={"lanes": {}}, now=now)
    morning = build_morning_packet(surface, now=now, window_hours=24)

    assert surface["current_champions"]["market"]["id"] == market_champion_hash
    assert surface["current_champions"]["policy"]["id"] == "policy-beta"
    assert surface["current_champions"]["command_node"]["id"] == "command-node-v2-fixture"
    assert surface["lane_summaries"]["market"]["benchmark_label"] == "BTC5 market-model benchmark progress"
    assert surface["lane_summaries"]["command_node"]["benchmark_label"] == "BTC5 command-node benchmark progress"
    assert surface["public_charts"]["market_model"]["benchmark_progress_only"] is True
    assert surface["public_charts"]["command_node"]["benchmark_progress_only"] is True

    assert morning["current_champions"]["market"]["id"] == market_champion_hash
    assert morning["current_champions"]["policy"]["id"] == "policy-beta"
    assert any(item["lane"] == "policy" and item["promotion_state"] == "live_activated" for item in morning["promotions"])


def test_e2e_policy_vetoes_when_market_handoff_is_stale(tmp_path: Path) -> None:
    market_latest, market_handoff, _, _, _ = _run_market_lane(tmp_path)
    handoff_payload = json.loads(market_handoff.read_text(encoding="utf-8"))
    handoff_payload["market_latest"]["is_fresh"] = False
    handoff_payload["market_latest"]["age_seconds"] = float(handoff_payload["market_latest"].get("freshness_seconds", 3600) + 1)
    market_handoff.write_text(json.dumps(handoff_payload, indent=2) + "\n", encoding="utf-8")

    policy_lane_dir = tmp_path / "reports" / "autoresearch" / "btc5_policy"
    cycle_json = tmp_path / "reports" / "btc5_autoresearch" / "latest.json"
    runtime_truth = tmp_path / "reports" / "runtime_truth_latest.json"
    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
    )
    _write_runtime_truth(runtime_truth, launch_posture="clear")

    run = _run_policy_lane(
        tmp_path,
        cycle_json=cycle_json,
        runtime_truth=runtime_truth,
        market_handoff=market_handoff,
        market_latest=market_latest,
        lane_dir=policy_lane_dir,
    )
    assert run.returncode == 0, run.stderr

    latest = json.loads((policy_lane_dir / "latest.json").read_text(encoding="utf-8"))
    decision = json.loads((policy_lane_dir / "promotion_decision.json").read_text(encoding="utf-8"))

    assert latest["latest_experiment"]["status"] == "discard"
    assert latest["latest_experiment"]["promotion_state"] is None
    assert latest["latest_experiment"]["decision_reason"] == "non_posture_safety_interlocks_not_green"
    assert latest["latest_experiment"]["safety_gates"]["market_policy_handoff_fresh"] is False
    assert latest["latest_experiment"]["safety_gates"]["all_green"] is False

    assert decision["status"] == "discard"
    assert decision["action"] == "discard"
    assert decision["decision_reason"] == "non_posture_safety_interlocks_not_green"
    assert decision["safety_gates"]["market_policy_handoff_fresh"] is False
    assert decision["safety_gates"]["all_green"] is False
    assert decision["live_after"]["policy_id"] == "current_live_profile"
