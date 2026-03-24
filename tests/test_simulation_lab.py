from __future__ import annotations

import json
import os
from pathlib import Path

from scripts import simulation_lab


def test_structural_family_sims_cover_required_lanes() -> None:
    results = simulation_lab.structural_family_sims()
    lanes = {str(result.parameters_tested.get("lane") or "") for result in results}

    assert "pair_completion" in lanes
    assert "neg_risk" in lanes
    assert "resolution_sniper" in lanes
    assert "weather_settlement_timing" in lanes
    assert "weather_dst_window" in lanes
    assert "queue_dominance" in lanes


def test_write_results_emits_ranked_candidates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(simulation_lab, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(simulation_lab, "RANKED_CANDIDATES_PATH", tmp_path / "ranked_candidates.json")

    results = simulation_lab.structural_family_sims()
    simulation_lab._write_results(results, label="test")

    ranked = json.loads((tmp_path / "ranked_candidates.json").read_text(encoding="utf-8"))
    assert ranked["artifact"] == "ranked_candidates.v1"
    assert ranked["candidate_count"] == len(results)
    assert ranked["ranked_candidates"][0]["lane"] in {"pair_completion", "neg_risk", "resolution_sniper"}


def test_resolve_csv_path_prefers_env_then_latest_candidate(tmp_path: Path, monkeypatch) -> None:
    env_csv = tmp_path / "env.csv"
    env_csv.write_text("timestamp\n1\n", encoding="utf-8")

    export_root = tmp_path / "exports"
    export_root.mkdir()
    older = export_root / "Polymarket-History-2026-03-20.csv"
    newer = export_root / "Polymarket-History-2026-03-21.csv"
    older.write_text("timestamp\n1\n", encoding="utf-8")
    newer.write_text("timestamp\n2\n", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    monkeypatch.setattr(simulation_lab, "CSV_SEARCH_ROOTS", (export_root,))
    monkeypatch.setattr(simulation_lab, "LEGACY_CSV_PATH", tmp_path / "fallback.csv")

    monkeypatch.setenv("POLYMARKET_HISTORY_CSV", str(env_csv))
    assert simulation_lab._resolve_csv_path() == env_csv

    monkeypatch.delenv("POLYMARKET_HISTORY_CSV")
    assert simulation_lab._resolve_csv_path() == newer
