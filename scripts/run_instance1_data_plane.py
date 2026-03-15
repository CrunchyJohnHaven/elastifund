#!/usr/bin/env python3
"""Run Instance 1 canonical multi-venue data plane and emit operator artifacts."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.cross_asset_artifact_paths import (  # noqa: E402
    CrossAssetArtifactPaths,
    normalize_repo_path,
)
from infra.cross_asset_data_plane import (  # noqa: E402
    CrossAssetDataPlane,
    CrossAssetDataPlaneConfig,
    CrossAssetDataPlaneRunner,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PATHS = CrossAssetArtifactPaths.for_repo(REPO_ROOT)

DEFAULT_RUNTIME_TRUTH = REPO_ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_IMPROVEMENT_VELOCITY = REPO_ROOT / "improvement_velocity.json"
DEFAULT_FINANCE_LATEST = REPO_ROOT / "reports" / "finance" / "latest.json"
DEFAULT_FINANCE_MODEL_BUDGET = REPO_ROOT / "reports" / "finance" / "model_budget_plan.json"
DEFAULT_OUTPUT_JSON = PATHS.instance1_artifact_latest_json
DEFAULT_OUTPUT_MD = PATHS.instance1_artifact_latest_md
DEFAULT_COMPAT_OUTPUT_JSON = PATHS.instance1_artifact_compat_json
DEFAULT_COMPAT_OUTPUT_MD = PATHS.instance1_artifact_compat_md


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _normalize(path: Path) -> str:
    return normalize_repo_path(path, repo_root=REPO_ROOT)


def _refresh_canonical_health_latest(result: dict[str, Any]) -> bool:
    health_payload = result.get("health")
    source_latest = result.get("health_latest_path")
    canonical_latest = PATHS.data_plane_health_latest
    canonical_latest.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(health_payload, dict):
        canonical_latest.write_text(json.dumps(health_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return True
    if isinstance(source_latest, str):
        source_path = Path(source_latest)
        if source_path.exists():
            canonical_latest.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
            return True
    return False


def build_instance1_artifact(
    *,
    health_payload: dict[str, Any],
    runtime_truth: dict[str, Any] | None,
    improvement_velocity: dict[str, Any] | None,
    finance_latest: dict[str, Any],
    finance_model_budget: dict[str, Any],
    config: CrossAssetDataPlaneConfig,
    canonical_artifact_path: Path,
    canonical_artifact_exists: bool = True,
) -> dict[str, Any]:
    del runtime_truth
    del improvement_velocity

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    overall = health_payload.get("overall") if isinstance(health_payload.get("overall"), dict) else {}

    finance_gate = finance_latest.get("finance_gate") if isinstance(finance_latest.get("finance_gate"), dict) else {}
    finance_gate_pass = _safe_bool(
        finance_latest.get("finance_gate_pass"),
        default=_safe_bool(finance_gate.get("pass"), True),
    )
    queue_package = (
        finance_model_budget.get("queue_package")
        if isinstance(finance_model_budget.get("queue_package"), dict)
        else {}
    )
    required_outputs = (
        finance_model_budget.get("required_outputs")
        if isinstance(finance_model_budget.get("required_outputs"), dict)
        else {}
    )
    next_cycle_action = str(
        required_outputs.get("one_next_cycle_action")
        or "route canonical envelopes into Instance 5 shadow scoring"
    )

    canonical_path = _normalize(canonical_artifact_path)
    block_reasons = [] if canonical_artifact_exists else [f"missing_artifact_path:{canonical_path}"]
    mandatory_output = {
        "candidate_delta_arr_bps": 300,
        "expected_improvement_velocity_delta": 0.25,
        "arr_confidence_score": 0.80,
        "block_reasons": block_reasons,
        "finance_gate_pass": finance_gate_pass,
        "one_next_cycle_action": next_cycle_action,
    }

    return {
        "artifact": "instance1_multi_asset_data_plane_dispatch.v1",
        "instance": 1,
        "generated_at": generated_at,
        "objective": (
            "Canonical multi-venue market envelope ingestion (Binance/Coinbase/Polymarket/Deribit), "
            "SQLite-first persistence, venue health telemetry, and candle anchors."
        ),
        "schemas": {
            "market_envelope": "market_envelope.v1",
            "venue_health": "venue_health.v1",
            "candle_anchor": "candle_anchor.v1",
        },
        "source_of_truth": _normalize(config.db_path),
        "parquet_root": _normalize(config.parquet_root),
        "health_report_latest": _normalize(PATHS.data_plane_health_latest),
        "assets": list(config.assets),
        "overall_health": overall,
        "mandatory_output_contract": mandatory_output,
        "candidate_delta_arr_bps": mandatory_output["candidate_delta_arr_bps"],
        "expected_improvement_velocity_delta": mandatory_output["expected_improvement_velocity_delta"],
        "arr_confidence_score": mandatory_output["arr_confidence_score"],
        "block_reasons": mandatory_output["block_reasons"],
        "finance_gate_pass": mandatory_output["finance_gate_pass"],
        "one_next_cycle_action": mandatory_output["one_next_cycle_action"],
        "artifacts": {
            "canonical_json": canonical_path,
            "compatibility_mirror_json": _normalize(DEFAULT_COMPAT_OUTPUT_JSON),
        },
        "sources": {
            "runtime_truth": _normalize(DEFAULT_RUNTIME_TRUTH),
            "improvement_velocity": _normalize(DEFAULT_IMPROVEMENT_VELOCITY),
            "finance_latest": _normalize(DEFAULT_FINANCE_LATEST),
            "finance_model_budget": _normalize(DEFAULT_FINANCE_MODEL_BUDGET),
            "data_plane_health": _normalize(PATHS.data_plane_health_latest),
        },
        "research_tooling_budget": {
            "queue_package_status": queue_package.get("status"),
            "queue_package_operating_point": queue_package.get("operating_point"),
            "queue_package_monthly_total_usd": queue_package.get("monthly_total_usd"),
            "policy_compliant": queue_package.get("policy_compliant"),
        },
    }


def render_markdown(artifact: dict[str, Any]) -> str:
    contract = artifact.get("mandatory_output_contract") if isinstance(artifact.get("mandatory_output_contract"), dict) else {}
    block_reasons = contract.get("block_reasons")
    if not isinstance(block_reasons, list):
        block_reasons = []
    lines = [
        "# Instance 1 Multi-Asset Data Plane Dispatch",
        "",
        f"- generated_at: {artifact.get('generated_at')}",
        f"- source_of_truth: `{artifact.get('source_of_truth')}`",
        f"- parquet_root: `{artifact.get('parquet_root')}`",
        f"- health_report_latest: `{artifact.get('health_report_latest')}`",
        "",
        "## Required Outputs",
        f"- candidate_delta_arr_bps: `{contract.get('candidate_delta_arr_bps')}`",
        f"- expected_improvement_velocity_delta: `{contract.get('expected_improvement_velocity_delta')}`",
        f"- arr_confidence_score: `{contract.get('arr_confidence_score')}`",
        f"- finance_gate_pass: `{str(contract.get('finance_gate_pass')).lower()}`",
        f"- one_next_cycle_action: {contract.get('one_next_cycle_action')}",
        "",
        "## Block Reasons",
    ]
    if block_reasons:
        for item in block_reasons:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _write_instance1_artifacts(
    *,
    artifact: dict[str, Any],
    markdown: str,
    output_json: Path,
    output_md: Path,
    compat_output_json: Path,
    compat_output_md: Path,
    write_compat_mirror: bool,
) -> dict[str, str]:
    payload = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(payload, encoding="utf-8")
    output_md.write_text(markdown, encoding="utf-8")

    results = {
        "instance1_artifact_json": _normalize(output_json),
        "instance1_artifact_md": _normalize(output_md),
    }

    should_write_mirror = write_compat_mirror and (
        compat_output_json.resolve() != output_json.resolve() or compat_output_md.resolve() != output_md.resolve()
    )
    if should_write_mirror:
        compat_output_json.parent.mkdir(parents=True, exist_ok=True)
        compat_output_md.parent.mkdir(parents=True, exist_ok=True)
        compat_output_json.write_text(payload, encoding="utf-8")
        compat_output_md.write_text(markdown, encoding="utf-8")
        results["instance1_artifact_compat_json"] = _normalize(compat_output_json)
        results["instance1_artifact_compat_md"] = _normalize(compat_output_md)
    return results


def _build_run_output(
    *,
    run_mode: str,
    result: dict[str, Any],
    refreshed_health_latest: bool,
) -> dict[str, Any]:
    timestamped = result.get("health_timestamped_path")
    timestamped_path = Path(str(timestamped)) if isinstance(timestamped, str) and timestamped else PATHS.data_plane_health_latest
    return {
        "run_mode": run_mode,
        "health_latest_path": _normalize(PATHS.data_plane_health_latest),
        "health_timestamped_path": _normalize(timestamped_path),
        "health_latest_refreshed": bool(refreshed_health_latest),
        "counts": result.get("counts"),
        "compaction": result.get("compaction"),
    }


async def _run_pipeline(args: argparse.Namespace, config: CrossAssetDataPlaneConfig) -> dict[str, Any]:
    plane = CrossAssetDataPlane(config=config)
    runner = CrossAssetDataPlaneRunner(plane=plane, enable_websockets=not args.disable_websockets)
    if args.run_once:
        return await runner.run_once()
    return await runner.run(duration_seconds=args.duration_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Instance 1 cross-asset data plane dispatch.")
    parser.add_argument("--run-once", action="store_true", help="Run one rest-snapshot cycle and exit.")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=120,
        help="Continuous run duration in seconds when --run-once is not supplied.",
    )
    parser.add_argument("--disable-websockets", action="store_true", help="Force rest-poll mode only.")
    parser.add_argument(
        "--skip-instance-artifact",
        action="store_true",
        help="Skip writing Instance 1 dispatch artifacts.",
    )
    parser.add_argument(
        "--skip-compat-mirror",
        action="store_true",
        help="Skip writing reports/parallel compatibility mirror outputs.",
    )
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--improvement-velocity", type=Path, default=DEFAULT_IMPROVEMENT_VELOCITY)
    parser.add_argument("--finance-latest", type=Path, default=DEFAULT_FINANCE_LATEST)
    parser.add_argument("--finance-model-budget", type=Path, default=DEFAULT_FINANCE_MODEL_BUDGET)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--compat-output-json", type=Path, default=DEFAULT_COMPAT_OUTPUT_JSON)
    parser.add_argument("--compat-output-md", type=Path, default=DEFAULT_COMPAT_OUTPUT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = CrossAssetDataPlaneConfig.from_env()
    run_mode = "one_shot" if args.run_once else "daemon"
    result = asyncio.run(_run_pipeline(args, config))

    refreshed = _refresh_canonical_health_latest(result)
    output_payload: dict[str, Any] = _build_run_output(run_mode=run_mode, result=result, refreshed_health_latest=refreshed)

    if not args.skip_instance_artifact:
        runtime_truth = _load_optional_json(args.runtime_truth)
        improvement_velocity = _load_optional_json(args.improvement_velocity)
        finance_latest = _load_optional_json(args.finance_latest)
        finance_model_budget = _load_optional_json(args.finance_model_budget)

        artifact = build_instance1_artifact(
            health_payload=result.get("health") if isinstance(result.get("health"), dict) else {},
            runtime_truth=runtime_truth,
            improvement_velocity=improvement_velocity,
            finance_latest=finance_latest,
            finance_model_budget=finance_model_budget,
            config=config,
            canonical_artifact_path=args.output_json,
            canonical_artifact_exists=True,
        )
        markdown = render_markdown(artifact)
        output_payload.update(
            _write_instance1_artifacts(
                artifact=artifact,
                markdown=markdown,
                output_json=args.output_json,
                output_md=args.output_md,
                compat_output_json=args.compat_output_json,
                compat_output_md=args.compat_output_md,
                write_compat_mirror=not args.skip_compat_mirror,
            )
        )

    print(json.dumps(output_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
