from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.btc5_market.v1.benchmark import freeze_benchmark_from_rows
from scripts.btc5_policy_benchmark import (
    evaluate_runtime_package_against_market,
    runtime_package_hash,
    write_market_policy_handoff,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_btc5_policy_autoresearch.py"


def _runtime_package(
    name: str,
    *,
    max_abs_delta: float = 0.00015,
    up_max_buy_price: float = 0.51,
    down_max_buy_price: float = 0.51,
    session_policy: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "profile": {
            "name": name,
            "max_abs_delta": max_abs_delta,
            "up_max_buy_price": up_max_buy_price,
            "down_max_buy_price": down_max_buy_price,
        },
        "session_policy": session_policy or [],
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
                "slug": f"policy-window-{index:04d}",
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
        "\n".join(
            [
                'CANDIDATE_CONTRACT_VERSION = 1',
                'MODEL_NAME = "policy_test_market_model"',
                'MODEL_VERSION = 1',
                'def fit_market_model(warmup_rows, *, feature_fields, seed=0):',
                '    return {"rows": len(warmup_rows)}',
                'def predict_market_row(model, row, *, feature_fields):',
                '    direction = str(row.get("direction") or "").strip().upper()',
                '    if direction == "UP":',
                '        return {"p_up": 0.88, "fill_rate": 0.96, "pnl_pct": -0.30}',
                '    if direction == "DOWN":',
                '        return {"p_up": 0.12, "fill_rate": 0.96, "pnl_pct": 0.04}',
                '    return {"p_up": 0.50, "fill_rate": 0.10, "pnl_pct": 0.0}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_market_context(tmp_path: Path) -> tuple[Path, Path]:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    benchmark_dir = tmp_path / "market_benchmark"
    manifest = freeze_benchmark_from_rows(_synthetic_market_rows(), benchmark_dir=benchmark_dir)
    candidate_path = tmp_path / "market_model_candidate.py"
    _write_market_model_candidate(candidate_path)
    packet_path = tmp_path / "market_packet.json"
    packet_path.write_text(json.dumps({"metrics": {"simulator_loss": 1.25}}, indent=2) + "\n", encoding="utf-8")
    latest_path = tmp_path / "market_latest.json"
    latest_payload = {
        "benchmark_id": manifest["benchmark_id"],
        "updated_at": now_iso,
        "epoch_id": manifest["epoch"]["epoch_id"],
        "manifest_path": str(benchmark_dir / "manifest.json"),
        "champion": {
            "experiment_id": 7,
            "candidate_model_name": "policy_test_market_model",
            "candidate_hash": "market-test-hash",
            "candidate_path": str(candidate_path),
            "loss": 1.25,
            "packet_json": str(packet_path),
        },
    }
    latest_path.write_text(json.dumps(latest_payload, indent=2) + "\n", encoding="utf-8")
    handoff_path = tmp_path / "market_policy_handoff.json"
    write_market_policy_handoff(market_latest_path=latest_path, output_path=handoff_path)
    return latest_path, handoff_path


def _write_cycle_payload(
    path: Path,
    *,
    active_package: dict[str, object],
    candidate_package: dict[str, object],
    deploy_recommendation: str,
) -> None:
    payload = {
        "generated_at": "2026-03-11T18:00:00+00:00",
        "selected_deploy_recommendation": deploy_recommendation,
        "selected_package_confidence_label": "high",
        "active_runtime_package": active_package,
        "selected_active_runtime_package": active_package,
        "best_runtime_package": candidate_package,
        "selected_best_runtime_package": candidate_package,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_runtime_truth(path: Path, *, launch_posture: str) -> None:
    payload = {
        "launch_posture": launch_posture,
        "launch": {"posture": launch_posture},
        "allow_order_submission": launch_posture == "clear",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run(
    tmp_path: Path,
    *,
    skip_cycle: bool = True,
    rollback_loss_increase: float = 0.0,
) -> subprocess.CompletedProcess[str]:
    cycle_json = tmp_path / "cycle.json"
    portfolio_json = tmp_path / "portfolio.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    market_latest = tmp_path / "market_latest.json"
    market_handoff = tmp_path / "market_policy_handoff.json"
    results = tmp_path / "results.jsonl"
    runs_dir = tmp_path / "runs"
    champion = tmp_path / "champion.json"
    latest_json = tmp_path / "latest.json"
    latest_md = tmp_path / "latest.md"
    active_env = tmp_path / "active.env"
    active_json = tmp_path / "active.json"
    staged_env = tmp_path / "staged.env"
    staged_json = tmp_path / "staged.json"
    promotion_decision_json = tmp_path / "promotion_decision.json"
    frontier_json = tmp_path / "frontier.json"
    command = [
        sys.executable,
        str(RUNNER),
        "--cycle-json",
        str(cycle_json),
        "--portfolio-json",
        str(portfolio_json),
        "--runtime-truth",
        str(runtime_truth),
        "--market-policy-handoff",
        str(market_handoff),
        "--market-latest-json",
        str(market_latest),
        "--frontier-json",
        str(frontier_json),
        "--results-ledger",
        str(results),
        "--runs-dir",
        str(runs_dir),
        "--champion-out",
        str(champion),
        "--promotion-decision-json",
        str(promotion_decision_json),
        "--latest-json",
        str(latest_json),
        "--latest-md",
        str(latest_md),
        "--active-env",
        str(active_env),
        "--active-package-json",
        str(active_json),
        "--staged-env",
        str(staged_env),
        "--staged-package-json",
        str(staged_json),
        "--rollback-loss-increase",
        str(rollback_loss_increase),
    ]
    if skip_cycle:
        command.append("--skip-cycle")
    return subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)


def _write_frontier_payload(
    path: Path,
    *,
    incumbent_package: dict[str, object],
    best_package: dict[str, object],
    selected_package: dict[str, object] | None = None,
    current_market_model_version: str = "7:market-test-hash",
    incumbent_loss: float = -52000.0,
    best_loss: float = -56000.0,
) -> None:
    selected_runtime_package = selected_package or best_package
    payload = {
        "updated_at": "2026-03-11T18:00:00+00:00",
        "incumbent_policy_id": incumbent_package["profile"]["name"],
        "incumbent_package_hash": runtime_package_hash(incumbent_package),
        "incumbent_policy_loss": incumbent_loss,
        "selected_policy_id": selected_runtime_package["profile"]["name"],
        "selected_package_hash": runtime_package_hash(selected_runtime_package),
        "selected_policy_loss": best_loss if selected_runtime_package == best_package else (best_loss + 2500.0),
        "best_market_policy_id": best_package["profile"]["name"],
        "best_market_package_hash": runtime_package_hash(best_package),
        "best_market_policy_loss": best_loss,
        "current_market_model_version": current_market_model_version,
        "loss_improvement_vs_incumbent": round(incumbent_loss - best_loss, 4),
        "selected_loss_gap_vs_best": 0.0 if selected_runtime_package == best_package else 2500.0,
        "beats_incumbent_by_keep_epsilon": True,
        "ranked_policies": [
            {
                "policy_id": best_package["profile"]["name"],
                "package_hash": runtime_package_hash(best_package),
                "runtime_package": best_package,
                "policy_loss": best_loss,
                "policy_components": {
                    "policy_loss": best_loss,
                    "median_30d_return_pct": 1000.0,
                    "p05_30d_return_pct": 900.0,
                    "fill_retention_ratio": 1.0,
                },
                "market_model_version": current_market_model_version,
            },
            {
                "policy_id": incumbent_package["profile"]["name"],
                "package_hash": runtime_package_hash(incumbent_package),
                "runtime_package": incumbent_package,
                "policy_loss": incumbent_loss,
                "policy_components": {
                    "policy_loss": incumbent_loss,
                    "median_30d_return_pct": 900.0,
                    "p05_30d_return_pct": 850.0,
                    "fill_retention_ratio": 1.0,
                },
                "market_model_version": current_market_model_version,
            },
        ],
        "stale_ranked_policies": [],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_decision_packet(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "promotion_decision.json").read_text(encoding="utf-8"))


def _assert_decision_packet_common(
    packet: dict[str, object],
    *,
    expected_status: str,
    expected_action: str,
    expected_reason: str,
) -> None:
    assert packet["status"] == expected_status
    assert packet["action"] == expected_action
    assert packet["decision_reason"] == expected_reason
    assert isinstance(packet["generated_at"], str)
    assert "T" in packet["generated_at"]
    assert isinstance(packet["experiment_id"], int)
    assert isinstance(packet["safety_gates"], dict)
    assert isinstance(packet["artifact_paths"], dict)
    assert str(packet["artifact_paths"]["results_ledger"]).endswith("results.jsonl")
    assert str(packet["artifact_paths"]["champion_registry"]).endswith("champion.json")
    assert str(packet["artifact_paths"]["run_json"]).endswith(".json")


def test_runner_stages_shadow_then_auto_activates_when_posture_clears(tmp_path: Path) -> None:
    _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
        deploy_recommendation="shadow_only",
    )
    _write_runtime_truth(runtime_truth, launch_posture="blocked")
    _write_frontier_payload(
        tmp_path / "frontier.json",
        incumbent_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        best_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
    )

    first = _run(tmp_path)
    assert first.returncode == 0, first.stderr

    first_latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    first_row = first_latest["latest_experiment"]
    assert first_row["status"] == "keep"
    assert first_row["promotion_state"] == "shadow_updated"
    assert first_latest["champion_id"] == "policy-beta"
    assert first_latest["simulator_champion_id"] == 7
    assert first_latest["policy_loss_contract_version"] == 2
    assert first_row["candidate_policy_components"]["fill_retention_ratio"] >= 0.85
    assert first_row["candidate_fold_results"]
    assert first_row["candidate_vs_incumbent_summary"]["fold_count"] >= 1
    assert first_latest["live_package"]["policy_id"] == "current_live_profile"
    assert first_latest["staged_package"]["policy_id"] == "policy-beta"
    assert first_latest["candidate_vs_incumbent_summary"]["fold_count"] >= 1
    assert first_latest["safety_gates"]["all_green"] is True
    assert not (tmp_path / "active.env").exists()
    assert (tmp_path / "staged.env").exists()
    first_packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        first_packet,
        expected_status="keep",
        expected_action="shadow_updated",
        expected_reason="champion_policy_loss_improved_shadow_stage",
    )
    assert first_packet["launch_posture"] == "blocked"
    assert first_packet["candidate"]["policy_id"] == "policy-beta"
    assert first_packet["incumbent"]["policy_id"] == "current_live_profile"
    assert first_packet["champion_after"]["policy_id"] == "policy-beta"
    assert first_packet["live_after"]["policy_id"] == "current_live_profile"
    assert first_packet["staged_after"]["policy_id"] == "policy-beta"
    assert first_packet["simulator_champion_id"] == 7
    assert isinstance(first_packet["market_epoch_id"], str)

    _write_runtime_truth(runtime_truth, launch_posture="clear")
    second = _run(tmp_path)
    assert second.returncode == 0, second.stderr

    second_latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    second_row = second_latest["latest_experiment"]
    assert second_row["status"] == "keep"
    assert second_row["promotion_state"] == "live_activated"
    assert second_latest["champion_id"] == "policy-beta"
    assert second_latest["live_package"]["policy_id"] == "policy-beta"
    assert second_latest["live_package"]["market_model_version"] == "7:market-test-hash"
    assert second_latest["live_package"]["fold_results"]
    assert second_latest["live_package"]["confidence_summary"]["fold_count"] >= 1
    assert second_latest["staged_package"] is None
    active_env_text = (tmp_path / "active.env").read_text(encoding="utf-8")
    assert "# candidate=policy-beta" in active_env_text
    second_packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        second_packet,
        expected_status="keep",
        expected_action="live_activated",
        expected_reason="launch_posture_cleared_activate_staged_champion",
    )
    assert second_packet["launch_posture"] == "clear"
    assert second_packet["candidate"]["policy_id"] == "policy-beta"
    assert second_packet["champion_after"]["policy_id"] == "policy-beta"
    assert second_packet["live_after"]["policy_id"] == "policy-beta"
    assert second_packet["staged_after"] is None
    assert second_packet["simulator_champion_id"] == 7
    assert isinstance(second_packet["market_epoch_id"], str)


def test_runner_overrides_cycle_selected_candidate_with_frontier_best(tmp_path: Path) -> None:
    _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    incumbent = _runtime_package("current_live_profile", up_max_buy_price=0.51)
    frontier_best = _runtime_package("policy-beta", up_max_buy_price=0.48)
    cycle_selected = _runtime_package("policy-gamma", up_max_buy_price=0.50)
    _write_cycle_payload(
        cycle_json,
        active_package=incumbent,
        candidate_package=cycle_selected,
        deploy_recommendation="hold",
    )
    _write_runtime_truth(runtime_truth, launch_posture="blocked")
    _write_frontier_payload(
        tmp_path / "frontier.json",
        incumbent_package=incumbent,
        best_package=frontier_best,
        selected_package=cycle_selected,
        incumbent_loss=-52000.0,
        best_loss=-56000.0,
    )

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    row = latest["latest_experiment"]
    assert row["status"] == "keep"
    assert row["promotion_state"] == "shadow_updated"
    assert latest["champion_id"] == "policy-beta"
    assert latest["staged_package"]["policy_id"] == "policy-beta"
    assert row["candidate_policy"] == "policy-beta"
    assert row["frontier_best_policy_id"] == "policy-beta"
    assert row["staged_because"] == "frontier_best"
    assert row["candidate_vs_incumbent_summary"]["fold_win_rate"] is not None


def test_policy_benchmark_emits_fold_results_and_confidence(tmp_path: Path) -> None:
    market_latest, market_handoff = _write_market_context(tmp_path)
    evaluation = evaluate_runtime_package_against_market(
        _runtime_package("policy-beta", up_max_buy_price=0.48),
        handoff_path=market_handoff,
        market_latest_path=market_latest,
    )

    assert evaluation["market_model_version"] == "7:market-test-hash"
    assert evaluation["policy_benchmark"]["fold_count"] >= 1
    assert len(evaluation["fold_results"]) == evaluation["policy_benchmark"]["fold_count"]
    assert evaluation["confidence_summary"]["fold_count"] == evaluation["policy_benchmark"]["fold_count"]
    assert evaluation["confidence_summary"]["confidence_method"] == "bootstrap_mean_fold_policy_loss_v1"


def test_runner_rejects_worse_policy_and_keeps_incumbent(tmp_path: Path) -> None:
    _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
        deploy_recommendation="shadow_only",
    )
    _write_runtime_truth(runtime_truth, launch_posture="blocked")
    assert _run(tmp_path).returncode == 0

    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-gamma", up_max_buy_price=0.51),
        deploy_recommendation="shadow_only",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["champion_id"] == "policy-beta"
    assert latest["latest_experiment"]["status"] == "discard"
    assert latest["latest_experiment"]["decision_reason"] == "policy_loss_not_improved"
    assert latest["latest_experiment"]["candidate_policy"] == "policy-gamma"
    assert latest["staged_package"]["policy_id"] == "policy-beta"
    packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        packet,
        expected_status="discard",
        expected_action="discard",
        expected_reason="policy_loss_not_improved",
    )
    assert packet["candidate"]["policy_id"] == "policy-gamma"
    assert packet["incumbent"]["policy_id"] == "policy-beta"
    assert packet["champion_after"]["policy_id"] == "policy-beta"
    assert packet["live_after"]["policy_id"] == "current_live_profile"
    assert packet["staged_after"]["policy_id"] == "policy-beta"
    assert packet["simulator_champion_id"] == 7
    assert isinstance(packet["market_epoch_id"], str)


def test_runner_rolls_back_live_package_on_post_promotion_degradation(tmp_path: Path) -> None:
    market_latest, market_handoff = _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"

    alpha_package = _runtime_package("policy-alpha", up_max_buy_price=0.48)
    beta_package = _runtime_package("policy-beta", up_max_buy_price=0.51)
    alpha_eval = evaluate_runtime_package_against_market(
        alpha_package,
        handoff_path=market_handoff,
        market_latest_path=market_latest,
    )
    beta_eval = evaluate_runtime_package_against_market(
        beta_package,
        handoff_path=market_handoff,
        market_latest_path=market_latest,
    )

    champion_payload = {
        "updated_at": "2026-03-11T18:00:00+00:00",
        "champion": {
            "policy_id": "policy-beta",
            "package_hash": runtime_package_hash(beta_package),
            "policy_loss": beta_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": beta_package,
            "policy_components": beta_eval["policy_benchmark"],
            "policy_loss_contract_version": beta_eval["policy_loss_contract_version"],
            "policy_loss_formula": beta_eval["policy_loss_formula"],
            "evaluation_source": beta_eval["evaluation_source"],
            "simulator_champion_id": beta_eval["simulator_champion_id"],
            "market_epoch_id": beta_eval["market_epoch_id"],
            "promotion_state": "live_promoted",
        },
        "live_package": {
            "policy_id": "policy-beta",
            "package_hash": runtime_package_hash(beta_package),
            "policy_loss": max(0.0, beta_eval["policy_benchmark"]["policy_loss"] - 25.0),
            "runtime_package": beta_package,
            "policy_components": beta_eval["policy_benchmark"],
            "fold_results": beta_eval["fold_results"],
            "confidence_summary": beta_eval["confidence_summary"],
            "policy_loss_contract_version": beta_eval["policy_loss_contract_version"],
            "policy_loss_formula": beta_eval["policy_loss_formula"],
            "evaluation_source": beta_eval["evaluation_source"],
            "simulator_champion_id": beta_eval["simulator_champion_id"],
            "market_epoch_id": beta_eval["market_epoch_id"],
            "market_model_version": beta_eval["market_model_version"],
            "promotion_state": "live_promoted",
        },
        "staged_package": None,
        "previous_live_package": {
            "policy_id": "policy-alpha",
            "package_hash": runtime_package_hash(alpha_package),
            "policy_loss": alpha_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": alpha_package,
            "policy_components": alpha_eval["policy_benchmark"],
            "fold_results": alpha_eval["fold_results"],
            "confidence_summary": alpha_eval["confidence_summary"],
            "policy_loss_contract_version": alpha_eval["policy_loss_contract_version"],
            "policy_loss_formula": alpha_eval["policy_loss_formula"],
            "evaluation_source": alpha_eval["evaluation_source"],
            "simulator_champion_id": alpha_eval["simulator_champion_id"],
            "market_epoch_id": alpha_eval["market_epoch_id"],
            "market_model_version": alpha_eval["market_model_version"],
            "promotion_state": "live_previous",
        },
    }
    (tmp_path / "champion.json").write_text(json.dumps(champion_payload, indent=2) + "\n", encoding="utf-8")

    _write_cycle_payload(
        cycle_json,
        active_package=beta_package,
        candidate_package=beta_package,
        deploy_recommendation="hold",
    )
    _write_runtime_truth(runtime_truth, launch_posture="clear")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    row = latest["latest_experiment"]
    assert row["promotion_state"] == "rollback_triggered"
    assert row["decision_reason"] == "post_promotion_policy_loss_degraded"
    assert latest["live_package"]["policy_id"] == "policy-alpha"
    assert latest["live_package"]["market_model_version"] == "7:market-test-hash"
    assert latest["live_package"]["fold_results"]
    assert latest["live_package"]["confidence_summary"]["fold_count"] >= 1
    assert latest["staged_package"]["policy_id"] == "policy-beta"
    assert "# candidate=policy-alpha" in (tmp_path / "active.env").read_text(encoding="utf-8")
    packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        packet,
        expected_status="discard",
        expected_action="rollback_triggered",
        expected_reason="post_promotion_policy_loss_degraded",
    )
    assert packet["candidate"]["policy_id"] == "policy-beta"
    assert packet["incumbent"]["policy_id"] == "policy-beta"
    assert packet["champion_after"]["policy_id"] == "policy-beta"
    assert packet["live_after"]["policy_id"] == "policy-alpha"
    assert packet["staged_after"]["policy_id"] == "policy-beta"
    assert packet["simulator_champion_id"] == 7
    assert isinstance(packet["market_epoch_id"], str)


def test_runner_hydrates_existing_live_package_evidence_from_matching_champion(tmp_path: Path) -> None:
    market_latest, market_handoff = _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"

    beta_package = _runtime_package("policy-beta", up_max_buy_price=0.51)
    beta_eval = evaluate_runtime_package_against_market(
        beta_package,
        handoff_path=market_handoff,
        market_latest_path=market_latest,
    )

    champion_payload = {
        "updated_at": "2026-03-11T18:00:00+00:00",
        "champion": {
            "policy_id": "policy-beta",
            "package_hash": runtime_package_hash(beta_package),
            "policy_loss": beta_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": beta_package,
            "policy_components": beta_eval["policy_benchmark"],
            "fold_results": beta_eval["fold_results"],
            "confidence_summary": beta_eval["confidence_summary"],
            "policy_loss_contract_version": beta_eval["policy_loss_contract_version"],
            "policy_loss_formula": beta_eval["policy_loss_formula"],
            "evaluation_source": beta_eval["evaluation_source"],
            "simulator_champion_id": beta_eval["simulator_champion_id"],
            "market_epoch_id": beta_eval["market_epoch_id"],
            "market_model_version": beta_eval["market_model_version"],
            "promotion_state": "live_activated",
        },
        "live_package": {
            "policy_id": "policy-beta",
            "package_hash": runtime_package_hash(beta_package),
            "policy_loss": beta_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": beta_package,
            "policy_components": beta_eval["policy_benchmark"],
            "policy_loss_contract_version": beta_eval["policy_loss_contract_version"],
            "policy_loss_formula": beta_eval["policy_loss_formula"],
            "evaluation_source": beta_eval["evaluation_source"],
            "simulator_champion_id": beta_eval["simulator_champion_id"],
            "market_epoch_id": beta_eval["market_epoch_id"],
            "promotion_state": "live_activated",
        },
        "staged_package": None,
        "previous_live_package": None,
    }
    (tmp_path / "champion.json").write_text(json.dumps(champion_payload, indent=2) + "\n", encoding="utf-8")

    _write_cycle_payload(
        cycle_json,
        active_package=beta_package,
        candidate_package=beta_package,
        deploy_recommendation="hold",
    )
    _write_runtime_truth(runtime_truth, launch_posture="clear")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["live_package"]["policy_id"] == "policy-beta"
    assert latest["live_package"]["market_model_version"] == "7:market-test-hash"
    assert latest["live_package"]["fold_results"]
    assert latest["live_package"]["confidence_summary"]["fold_count"] >= 1


def test_runner_canonicalizes_live_alias_to_matching_champion_package(tmp_path: Path) -> None:
    market_latest, market_handoff = _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"

    alias_package = _runtime_package("current_live_profile", max_abs_delta=0.00075, up_max_buy_price=0.49, down_max_buy_price=0.51)
    champion_package = _runtime_package(
        "active_profile_probe_d0_00075",
        max_abs_delta=0.00075,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )
    champion_eval = evaluate_runtime_package_against_market(
        champion_package,
        handoff_path=market_handoff,
        market_latest_path=market_latest,
    )

    champion_payload = {
        "updated_at": "2026-03-12T17:12:24+00:00",
        "champion": {
            "policy_id": "active_profile_probe_d0_00075",
            "package_hash": runtime_package_hash(champion_package),
            "policy_loss": champion_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": champion_package,
            "policy_components": champion_eval["policy_benchmark"],
            "fold_results": champion_eval["fold_results"],
            "confidence_summary": champion_eval["confidence_summary"],
            "policy_loss_contract_version": champion_eval["policy_loss_contract_version"],
            "policy_loss_formula": champion_eval["policy_loss_formula"],
            "evaluation_source": champion_eval["evaluation_source"],
            "simulator_champion_id": champion_eval["simulator_champion_id"],
            "market_epoch_id": champion_eval["market_epoch_id"],
            "market_model_version": champion_eval["market_model_version"],
            "promotion_state": "shadow_updated",
            "source_artifact": "reports/parallel/btc5_probe_cycle_d0_00075.json",
        },
        "live_package": {
            "policy_id": "current_live_profile",
            "package_hash": runtime_package_hash(alias_package),
            "policy_loss": champion_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": alias_package,
            "policy_components": champion_eval["policy_benchmark"],
            "fold_results": champion_eval["fold_results"],
            "confidence_summary": champion_eval["confidence_summary"],
            "policy_loss_contract_version": champion_eval["policy_loss_contract_version"],
            "policy_loss_formula": champion_eval["policy_loss_formula"],
            "evaluation_source": champion_eval["evaluation_source"],
            "simulator_champion_id": champion_eval["simulator_champion_id"],
            "market_epoch_id": champion_eval["market_epoch_id"],
            "market_model_version": champion_eval["market_model_version"],
            "promotion_state": "live_current",
            "source_artifact": "state/btc5_autoresearch.env",
        },
        "staged_package": {
            "policy_id": "active_profile_probe_d0_00075",
            "package_hash": runtime_package_hash(champion_package),
            "policy_loss": champion_eval["policy_benchmark"]["policy_loss"],
            "runtime_package": champion_package,
            "policy_components": champion_eval["policy_benchmark"],
            "fold_results": champion_eval["fold_results"],
            "confidence_summary": champion_eval["confidence_summary"],
            "policy_loss_contract_version": champion_eval["policy_loss_contract_version"],
            "policy_loss_formula": champion_eval["policy_loss_formula"],
            "evaluation_source": champion_eval["evaluation_source"],
            "simulator_champion_id": champion_eval["simulator_champion_id"],
            "market_epoch_id": champion_eval["market_epoch_id"],
            "market_model_version": champion_eval["market_model_version"],
            "promotion_state": "shadow_updated",
            "source_artifact": "reports/parallel/btc5_probe_cycle_d0_00075.json",
        },
        "previous_live_package": None,
    }
    (tmp_path / "champion.json").write_text(json.dumps(champion_payload, indent=2) + "\n", encoding="utf-8")

    _write_cycle_payload(
        cycle_json,
        active_package=alias_package,
        candidate_package=alias_package,
        deploy_recommendation="hold",
    )
    _write_runtime_truth(runtime_truth, launch_posture="blocked")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["champion_id"] == "active_profile_probe_d0_00075"
    assert latest["live_package"]["policy_id"] == "active_profile_probe_d0_00075"
    assert latest["live_package"]["promotion_state"] == "live_current"
    assert latest["active_runtime_package"]["profile"]["name"] == "active_profile_probe_d0_00075"
    assert latest["selected_active_runtime_package"]["profile"]["name"] == "active_profile_probe_d0_00075"


def test_runner_live_promotes_when_posture_clear_and_candidate_improves(tmp_path: Path) -> None:
    _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
        deploy_recommendation="promote",
    )
    _write_runtime_truth(runtime_truth, launch_posture="clear")
    _write_frontier_payload(
        tmp_path / "frontier.json",
        incumbent_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        best_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
    )

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    row = latest["latest_experiment"]
    assert row["status"] == "keep"
    assert row["promotion_state"] == "live_promoted"
    assert latest["live_package"]["policy_id"] == "policy-beta"
    assert latest["staged_package"] is None
    packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        packet,
        expected_status="keep",
        expected_action="live_promoted",
        expected_reason="champion_policy_loss_improved_live_promote",
    )
    assert packet["candidate"]["policy_id"] == "policy-beta"
    assert packet["champion_after"]["policy_id"] == "policy-beta"
    assert packet["live_after"]["policy_id"] == "policy-beta"
    assert packet["staged_after"] is None
    assert packet["simulator_champion_id"] == 7
    assert isinstance(packet["market_epoch_id"], str)


def test_runner_stages_shadow_only_candidate_even_when_posture_clear_and_candidate_improves(
    tmp_path: Path,
) -> None:
    _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    _write_cycle_payload(
        cycle_json,
        active_package=_runtime_package("current_live_profile", up_max_buy_price=0.51),
        candidate_package=_runtime_package("policy-beta", up_max_buy_price=0.48),
        deploy_recommendation="shadow_only",
    )
    _write_runtime_truth(runtime_truth, launch_posture="clear")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    row = latest["latest_experiment"]
    assert row["status"] == "keep"
    assert row["promotion_state"] == "shadow_updated"
    assert latest["live_package"]["policy_id"] == "current_live_profile"
    assert latest["staged_package"]["policy_id"] == "policy-beta"
    assert not (tmp_path / "active.env").exists()
    assert "# candidate=policy-beta" in (tmp_path / "staged.env").read_text(encoding="utf-8")
    packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        packet,
        expected_status="keep",
        expected_action="shadow_updated",
        expected_reason="champion_policy_loss_improved_shadow_stage",
    )
    assert packet["candidate"]["policy_id"] == "policy-beta"
    assert packet["champion_after"]["policy_id"] == "policy-beta"
    assert packet["live_after"]["policy_id"] == "current_live_profile"
    assert packet["staged_after"]["policy_id"] == "policy-beta"


def test_runner_downgrades_looser_promote_candidate_to_shadow_stage(tmp_path: Path) -> None:
    _write_market_context(tmp_path)
    cycle_json = tmp_path / "cycle.json"
    runtime_truth = tmp_path / "runtime_truth.json"
    active_package = _runtime_package(
        "current_live_profile",
        max_abs_delta=0.00015,
        up_max_buy_price=0.51,
        down_max_buy_price=0.49,
    )
    candidate_package = _runtime_package(
        "policy-beta",
        max_abs_delta=0.00015,
        up_max_buy_price=0.48,
        down_max_buy_price=0.51,
    )
    _write_cycle_payload(
        cycle_json,
        active_package=active_package,
        candidate_package=candidate_package,
        deploy_recommendation="promote",
    )
    _write_runtime_truth(runtime_truth, launch_posture="clear")
    _write_frontier_payload(
        tmp_path / "frontier.json",
        incumbent_package=active_package,
        best_package=candidate_package,
    )

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    row = latest["latest_experiment"]
    assert row["status"] == "keep"
    assert row["promotion_state"] == "shadow_updated"
    assert latest["live_package"]["policy_id"] == "current_live_profile"
    assert latest["staged_package"]["policy_id"] == "policy-beta"
    packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        packet,
        expected_status="keep",
        expected_action="shadow_updated",
        expected_reason="champion_policy_loss_improved_shadow_stage",
    )
    assert packet["candidate"]["policy_id"] == "policy-beta"
    assert packet["live_after"]["policy_id"] == "current_live_profile"
    assert packet["staged_after"]["policy_id"] == "policy-beta"


def test_runner_writes_crash_decision_packet_when_cycle_payload_missing(tmp_path: Path) -> None:
    _write_runtime_truth(tmp_path / "runtime_truth.json", launch_posture="blocked")
    result = _run(tmp_path)
    assert result.returncode == 1, result.stderr

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    row = latest["latest_experiment"]
    assert row["status"] == "crash"
    assert row["decision_reason"] == "missing_candidate_runtime_package"
    packet = _read_decision_packet(tmp_path)
    _assert_decision_packet_common(
        packet,
        expected_status="crash",
        expected_action="crash",
        expected_reason="missing_candidate_runtime_package",
    )
    assert isinstance(packet["candidate"]["policy_id"], str)
    assert packet["candidate"]["policy_id"]
    assert packet["candidate"]["market_epoch_id"] is None
    assert packet["incumbent"] is None
    assert packet["champion_after"] is None
    assert packet["live_after"] is None
    assert packet["staged_after"] is None
