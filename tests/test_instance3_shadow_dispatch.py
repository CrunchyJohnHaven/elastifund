from __future__ import annotations

import json
from pathlib import Path

from scripts.run_instance3_shadow_dispatch import build_shadow_readiness


def test_instance3_shadow_dispatch_writes_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    (reports / "runtime_truth_latest.json").write_text(
        json.dumps(
            {
                "summary": {"launch_posture": "blocked"},
                "launch": {"posture": "blocked"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (reports / "runtime_profile_effective.json").write_text(
        json.dumps({"mode": {"paper_trading": False, "allow_order_submission": True}}) + "\n",
        encoding="utf-8",
    )
    (reports / "poly_fastlane_candidates_20260309T010000Z.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "market_id": "mkt-1",
                        "direction": "buy_yes",
                        "market_probability": 0.51,
                        "expected_maker_fill_probability": 0.62,
                        "route_score": 0.4,
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    readiness_path, plan_path = build_shadow_readiness()
    assert readiness_path.exists()
    assert plan_path.exists()

    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    assert readiness["artifact"] == "polymarket_shadow_readiness"
    assert readiness["runtime_guard"]["greenlight"] is False
    assert readiness["submission_policy"] == "shadow_only"
    assert readiness["candidate_intake"]["loaded_count"] == 1
    assert readiness["candidate_intake"]["staged_shadow_orders"] == 1
