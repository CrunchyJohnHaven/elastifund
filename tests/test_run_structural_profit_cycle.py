from __future__ import annotations

from pathlib import Path

from scripts import run_structural_profit_cycle


def test_build_cycle_blocks_when_authoritative_artifacts_are_stale(monkeypatch, tmp_path: Path) -> None:
    def fake_run(relpath: str, extra_args=None):  # type: ignore[no-untyped-def]
        return {"script": relpath, "returncode": 0, "stdout_tail": "", "stderr_tail": "", "args": list(extra_args or [])}

    artifact_map = {
        "canonical_operator_truth.json": {"exists": True, "status": "blocked", "generated_at": "x"},
        "ranked_candidates.json": {"exists": True, "status": None, "generated_at": "x"},
        "promotion_bundle.json": {"exists": True, "status": "stale", "generated_at": "x"},
        "latest.json": {"exists": True, "status": "fresh", "generated_at": "x"},
        "structural_lane_snapshot.json": {"exists": True, "status": "fresh", "generated_at": "x"},
        "live_queue.json": {"exists": True, "status": "fresh", "generated_at": "x"},
    }

    def fake_artifact_state(path):  # type: ignore[no-untyped-def]
        state = artifact_map[path.name]
        return {"path": str(path), **state}

    def fake_load_json(path):  # type: ignore[no-untyped-def]
        if path.name == "live_queue.json":
            return {"recommended_live_lane": "neg_risk", "recommended_size_usd": 40.0, "proof_status": "ready"}
        if path.name == "structural_lane_snapshot.json":
            return {"lanes": [{"lane": "neg_risk"}]}
        return {}

    for rel in [
        "reports/canonical_operator_truth.json",
        "reports/simulation/ranked_candidates.json",
        "reports/promotion_bundle.json",
        "reports/strike_factory/latest.json",
        "reports/structural_alpha/structural_lane_snapshot.json",
        "reports/structural_alpha/live_queue.json",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_structural_profit_cycle, "_run", fake_run)
    monkeypatch.setattr(run_structural_profit_cycle, "_artifact_state", fake_artifact_state)
    monkeypatch.setattr(run_structural_profit_cycle, "_load_json", fake_load_json)
    monkeypatch.setattr(run_structural_profit_cycle, "REPO_ROOT", tmp_path)

    report = run_structural_profit_cycle.build_cycle()

    assert report["status"] == "blocked"
    assert "canonical_truth_blocked" in report["blockers"]
    assert "promotion_bundle_stale" in report["blockers"]
