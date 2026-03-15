from __future__ import annotations

import json
from pathlib import Path

from infra.cross_asset_data_plane import CrossAssetDataPlaneConfig
from scripts.run_instance1_data_plane import (
    REPO_ROOT,
    _build_run_output,
    _write_instance1_artifacts,
    build_instance1_artifact,
)


def test_build_instance1_artifact_contract_values_match_dispatch_requirements() -> None:
    config = CrossAssetDataPlaneConfig(
        db_path=Path("state/cross_asset_ticks.db"),
        parquet_root=Path("state/cross_asset_ticks_parquet"),
        health_latest_path=Path("reports/data_plane_health/latest.json"),
    )
    artifact = build_instance1_artifact(
        health_payload={"overall": {"fresh_asset_coverage_ratio": 1.0, "stale_assets": [], "no_data_assets": []}},
        runtime_truth={},
        improvement_velocity={},
        finance_latest={"finance_gate_pass": True},
        finance_model_budget={
            "required_outputs": {
                "one_next_cycle_action": "queue the pilot model-budget package under the finance caps",
            },
            "queue_package": {
                "status": "queued",
                "operating_point": "pilot",
                "monthly_total_usd": 200.0,
                "policy_compliant": True,
            },
        },
        config=config,
        canonical_artifact_path=Path("reports/instance1_data_plane/latest.json"),
        canonical_artifact_exists=True,
    )
    required = artifact["mandatory_output_contract"]
    assert required["candidate_delta_arr_bps"] == 300
    assert required["expected_improvement_velocity_delta"] == 0.25
    assert required["arr_confidence_score"] == 0.80
    assert required["finance_gate_pass"] is True
    assert required["block_reasons"] == []
    assert required["one_next_cycle_action"] == "queue the pilot model-budget package under the finance caps"
    assert artifact["research_tooling_budget"]["queue_package_status"] == "queued"


def test_build_instance1_artifact_normalizes_repo_paths() -> None:
    config = CrossAssetDataPlaneConfig(
        db_path=(REPO_ROOT / "state" / "cross_asset_ticks.db").resolve(),
        parquet_root=(REPO_ROOT / "state" / "cross_asset_ticks_parquet").resolve(),
        health_latest_path=(REPO_ROOT / "reports" / "data_plane_health" / "latest.json").resolve(),
    )
    artifact = build_instance1_artifact(
        health_payload={"overall": {}},
        runtime_truth={},
        improvement_velocity={},
        finance_latest={"finance_gate_pass": True},
        finance_model_budget={},
        config=config,
        canonical_artifact_path=(REPO_ROOT / "reports" / "instance1_data_plane" / "latest.json").resolve(),
        canonical_artifact_exists=True,
    )
    assert artifact["source_of_truth"] == "state/cross_asset_ticks.db"
    assert artifact["parquet_root"] == "state/cross_asset_ticks_parquet"
    assert artifact["health_report_latest"] == "reports/data_plane_health/latest.json"
    assert artifact["artifacts"]["canonical_json"] == "reports/instance1_data_plane/latest.json"
    assert artifact["sources"]["finance_model_budget"] == "reports/finance/model_budget_plan.json"


def test_build_instance1_artifact_missing_path_emits_single_exact_blocker() -> None:
    config = CrossAssetDataPlaneConfig(
        db_path=Path("state/cross_asset_ticks.db"),
        parquet_root=Path("state/cross_asset_ticks_parquet"),
        health_latest_path=Path("reports/data_plane_health/latest.json"),
    )
    artifact = build_instance1_artifact(
        health_payload={"overall": {}},
        runtime_truth={},
        improvement_velocity={},
        finance_latest={"finance_gate_pass": True},
        finance_model_budget={},
        config=config,
        canonical_artifact_path=Path("reports/instance1_data_plane/latest.json"),
        canonical_artifact_exists=False,
    )
    required = artifact["mandatory_output_contract"]
    assert required["block_reasons"] == ["missing_artifact_path:reports/instance1_data_plane/latest.json"]


def test_write_instance1_artifacts_writes_compatibility_mirror(tmp_path: Path) -> None:
    output_json = tmp_path / "reports" / "instance1_data_plane" / "latest.json"
    output_md = tmp_path / "reports" / "instance1_data_plane" / "latest.md"
    compat_json = tmp_path / "reports" / "parallel" / "instance1_multi_asset_data_plane_latest.json"
    compat_md = tmp_path / "reports" / "parallel" / "instance1_multi_asset_data_plane_latest.md"
    artifact = {"artifact": "instance1_multi_asset_data_plane_dispatch.v1", "instance": 1}
    markdown = "# test\n"

    outputs = _write_instance1_artifacts(
        artifact=artifact,
        markdown=markdown,
        output_json=output_json,
        output_md=output_md,
        compat_output_json=compat_json,
        compat_output_md=compat_md,
        write_compat_mirror=True,
    )

    assert output_json.exists()
    assert output_md.exists()
    assert compat_json.exists()
    assert compat_md.exists()
    assert json.loads(output_json.read_text(encoding="utf-8")) == json.loads(compat_json.read_text(encoding="utf-8"))
    assert "instance1_artifact_compat_json" in outputs
    assert "instance1_artifact_compat_md" in outputs


def test_run_output_contract_matches_between_one_shot_and_daemon_modes() -> None:
    result = {
        "health_timestamped_path": str(REPO_ROOT / "reports" / "data_plane_health" / "data_plane_health_20260311T030005Z.json"),
        "counts": {"market_envelopes": 10},
        "compaction": {"status": "up_to_date"},
    }
    one_shot = _build_run_output(run_mode="one_shot", result=result, refreshed_health_latest=True)
    daemon = _build_run_output(run_mode="daemon", result=result, refreshed_health_latest=True)
    assert set(one_shot.keys()) == set(daemon.keys())
    assert one_shot["health_latest_path"] == daemon["health_latest_path"]
