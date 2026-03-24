from __future__ import annotations

import json
from pathlib import Path

from scripts import promotion_bundle


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_assemble_promotion_emits_structural_live_queue(tmp_path: Path, monkeypatch) -> None:
    thesis_path = tmp_path / "thesis_bundle.json"
    output_path = tmp_path / "promotion_bundle.json"
    canonical_truth_path = tmp_path / "canonical_operator_truth.json"
    ranked_path = tmp_path / "ranked_candidates.json"
    structural_dir = tmp_path / "structural_alpha"

    _write(thesis_path, {"generated_at": "2026-03-22T18:00:00+00:00", "status": "fresh", "theses": []})
    _write(canonical_truth_path, {"truth_status": "green"})
    _write(
        ranked_path,
        {
            "ranked_candidates": [
                {
                    "lane": "pair_completion",
                    "moonshot_score": 4.2,
                    "net_after_fee_expectancy": 0.6,
                    "partial_fill_breach_rate": 0.05,
                    "truth_dependency_status": "green",
                    "promotion_fast_track_ready": True,
                    "fills_simulated": 60,
                    "opportunity_half_life_ms": 200000,
                }
            ]
        },
    )

    monkeypatch.setattr(promotion_bundle, "THESIS_PATH", thesis_path)
    monkeypatch.setattr(promotion_bundle, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(promotion_bundle, "CANONICAL_TRUTH_PATH", canonical_truth_path)
    monkeypatch.setattr(promotion_bundle, "SIMULATION_RANKED_PATH", ranked_path)
    monkeypatch.setattr(promotion_bundle, "STRUCTURAL_ALPHA_DIR", structural_dir)
    monkeypatch.setattr(promotion_bundle, "STRUCTURAL_LIVE_QUEUE_PATH", structural_dir / "live_queue.json")
    monkeypatch.setattr(promotion_bundle, "STRUCTURAL_LANE_SNAPSHOT_PATH", structural_dir / "structural_lane_snapshot.json")
    monkeypatch.setattr(promotion_bundle, "CAPITAL_LAB_PATH", tmp_path / "missing_capital_lab.json")
    monkeypatch.setattr(promotion_bundle, "COUNTERFACTUAL_LAB_PATH", tmp_path / "missing_counterfactual_lab.json")

    bundle = promotion_bundle.assemble_promotion()

    assert bundle["recommended_live_lane"] == "dual_sided_pair"
    assert bundle["recommended_size_usd"] > 0
    assert (structural_dir / "live_queue.json").exists()
    assert (structural_dir / "structural_lane_snapshot.json").exists()


def test_assemble_promotion_blocks_structural_queue_when_truth_blocked(tmp_path: Path, monkeypatch) -> None:
    thesis_path = tmp_path / "thesis_bundle.json"
    output_path = tmp_path / "promotion_bundle.json"
    canonical_truth_path = tmp_path / "canonical_operator_truth.json"
    ranked_path = tmp_path / "ranked_candidates.json"
    structural_dir = tmp_path / "structural_alpha"

    _write(thesis_path, {"generated_at": "2026-03-22T18:00:00+00:00", "status": "fresh", "theses": []})
    _write(canonical_truth_path, {"truth_status": "blocked", "blockers": ["wallet_mismatch"]})
    _write(
        ranked_path,
        {
            "ranked_candidates": [
                {
                    "lane": "neg_risk",
                    "moonshot_score": 5.0,
                    "net_after_fee_expectancy": 1.0,
                    "partial_fill_breach_rate": 0.0,
                    "truth_dependency_status": "green",
                    "promotion_fast_track_ready": True,
                    "fills_simulated": 30,
                    "opportunity_half_life_ms": 400000,
                    "parameters_tested": {"taxonomy_ambiguity": 0},
                }
            ]
        },
    )

    monkeypatch.setattr(promotion_bundle, "THESIS_PATH", thesis_path)
    monkeypatch.setattr(promotion_bundle, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(promotion_bundle, "CANONICAL_TRUTH_PATH", canonical_truth_path)
    monkeypatch.setattr(promotion_bundle, "SIMULATION_RANKED_PATH", ranked_path)
    monkeypatch.setattr(promotion_bundle, "STRUCTURAL_ALPHA_DIR", structural_dir)
    monkeypatch.setattr(promotion_bundle, "STRUCTURAL_LIVE_QUEUE_PATH", structural_dir / "live_queue.json")
    monkeypatch.setattr(promotion_bundle, "STRUCTURAL_LANE_SNAPSHOT_PATH", structural_dir / "structural_lane_snapshot.json")
    monkeypatch.setattr(promotion_bundle, "CAPITAL_LAB_PATH", tmp_path / "missing_capital_lab.json")
    monkeypatch.setattr(promotion_bundle, "COUNTERFACTUAL_LAB_PATH", tmp_path / "missing_counterfactual_lab.json")

    bundle = promotion_bundle.assemble_promotion()

    assert bundle["recommended_live_lane"] is None
    assert "truth_status_blocked" in bundle["capital_blockers"]
