from __future__ import annotations

import json
from pathlib import Path

from scripts import promotion_bundle
from scripts.simulation_lab import build_structural_live_queue, structural_family_sims


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_structural_live_queue_prioritizes_pair_completion() -> None:
    payload = build_structural_live_queue(structural_family_sims())

    assert payload["best_live_ready_lane"] is not None
    assert payload["best_live_ready_lane"]["lane"] == "pair_completion"

    snapshots = {item["lane"]: item for item in payload["structural_lane_snapshot"]}
    assert snapshots["pair_completion"]["promotion_ready"] is True
    assert snapshots["pair_completion"]["recommended_capital_usd"] == 60.0
    assert snapshots["weather_settlement_timing"]["promotion_ready"] is False
    assert "shadow_only_lane" in snapshots["weather_settlement_timing"]["current_blockers"]


def test_assemble_promotion_approves_structural_lane_from_live_queue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    live_queue = build_structural_live_queue(structural_family_sims())
    live_queue["generated_at"] = "2026-03-22T23:30:00+00:00"

    monkeypatch.setattr(promotion_bundle, "THESIS_PATH", tmp_path / "reports" / "thesis_bundle.json")
    monkeypatch.setattr(promotion_bundle, "PROMO_HISTORY_PATH", tmp_path / "reports" / "promotion_history.jsonl")
    monkeypatch.setattr(promotion_bundle, "OUTPUT_PATH", tmp_path / "reports" / "promotion_bundle.json")
    monkeypatch.setattr(promotion_bundle, "CAPITAL_LAB_PATH", tmp_path / "reports" / "capital_lab" / "latest.json")
    monkeypatch.setattr(
        promotion_bundle,
        "COUNTERFACTUAL_LAB_PATH",
        tmp_path / "reports" / "counterfactual_lab" / "latest.json",
    )
    monkeypatch.setattr(
        promotion_bundle,
        "CANONICAL_TRUTH_PATH",
        tmp_path / "reports" / "canonical_operator_truth.json",
    )
    monkeypatch.setattr(
        promotion_bundle,
        "SIMULATION_RANKED_PATH",
        tmp_path / "reports" / "simulation" / "ranked_candidates.json",
    )
    monkeypatch.setattr(
        promotion_bundle,
        "STRUCTURAL_ALPHA_DIR",
        tmp_path / "reports" / "structural_alpha",
    )
    monkeypatch.setattr(
        promotion_bundle,
        "STRUCTURAL_LIVE_QUEUE_PATH",
        tmp_path / "reports" / "structural_alpha" / "live_queue.json",
    )
    monkeypatch.setattr(
        promotion_bundle,
        "STRUCTURAL_LANE_SNAPSHOT_PATH",
        tmp_path / "reports" / "structural_alpha" / "structural_lane_snapshot.json",
    )
    monkeypatch.setattr(
        promotion_bundle,
        "RUNTIME_TRUTH_LATEST_PATH",
        tmp_path / "reports" / "runtime_truth_latest.json",
    )

    _write_json(promotion_bundle.CAPITAL_LAB_PATH, {"generated_at": "2026-03-22T23:30:00+00:00", "lanes": {}})
    _write_json(
        promotion_bundle.COUNTERFACTUAL_LAB_PATH,
        {"generated_at": "2026-03-22T23:30:00+00:00", "verdict": "KEEP"},
    )
    _write_json(
        promotion_bundle.CANONICAL_TRUTH_PATH,
        {"generated_at": "2026-03-22T23:30:00+00:00", "truth_status": "green"},
    )
    _write_json(promotion_bundle.STRUCTURAL_LIVE_QUEUE_PATH, live_queue)

    bundle = promotion_bundle.assemble_promotion()

    assert bundle["approved_count"] >= 1
    assert bundle["recommended_live_lane"] == "dual_sided_pair"
    assert bundle["proof_status"] == "ready"
    assert bundle["next_capital_recommendation"]["lane"] == "dual_sided_pair"
    assert bundle["next_capital_recommendation"]["capital_usd"] > 0
    assert any(
        item["promotion_decision"] == promotion_bundle.PromoDecision.APPROVE
        and item["lane"] == "pair_completion"
        for item in bundle["evaluations"]
    )

    written = json.loads(promotion_bundle.OUTPUT_PATH.read_text(encoding="utf-8"))
    assert written["artifact"] == "promotion_bundle"
    assert written["recommended_live_lane"] == "dual_sided_pair"
    assert written["approved_count"] >= 1
