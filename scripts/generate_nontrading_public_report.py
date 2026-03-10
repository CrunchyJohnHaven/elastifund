#!/usr/bin/env python3
"""Generate a public-safe JJ-N report artifact for the website."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.first_dollar import (
    PUBLIC_REPORT_SCHEMA_VERSION,
    build_allocator_input,
    build_comparison_artifact,
    build_first_dollar_readiness,
    build_first_dollar_scoreboard,
    build_operations_summary,
)
from nontrading.offers.website_growth_audit import website_growth_audit_offer
from nontrading.revenue_audit.launch_summary import (
    DEFAULT_OUTPUT_PATH as DEFAULT_LAUNCH_SUMMARY_PATH,
    build_launch_summary,
    coerce_launch_summary,
)
from nontrading.store import RevenueStore
from orchestration.models import REVENUE_AUDIT_ENGINE


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "revenue_agent.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_public_report.json"
DEFAULT_LAUNCH_OUTPUT_PATH = DEFAULT_LAUNCH_SUMMARY_PATH
DEFAULT_STATUS_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_first_dollar_status.json"
DEFAULT_ALLOCATOR_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_allocator_input.json"
DEFAULT_COMPARISON_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_benchmark_comparison.json"
DEFAULT_BENCHMARK_INPUT_PATH = PROJECT_ROOT / "reports" / "openclaw" / "normalized" / "latest.json"


def _headline(snapshot: dict[str, Any]) -> str:
    phase = snapshot["phase"]["current_phase"]
    if phase == "phase_0_revenue_evidence":
        return "JJ-N has repo-tracked revenue evidence and a live fulfillment queue to manage."
    if phase == "phase_0_offer_ready":
        return "JJ-N has a priced offer, proposal flow, and fulfillment telemetry, but closed-won revenue is still pending."
    if phase == "phase_0_outreach_active":
        return "JJ-N has a working outreach funnel and dashboard visibility, with revenue claims still blocked."
    if phase == "phase_0_pipeline_seeded":
        return "JJ-N is qualifying targets and instrumenting the first revenue wedge before live launch."
    if phase == "phase_0_research_active":
        return "JJ-N has researched accounts and a visible first wedge, but qualification, outreach, and revenue claims remain pre-launch."
    return "JJ-N is in setup mode with the Website Growth Audit as the first launch wedge."


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    if not payload.get("source_artifact"):
        payload["source_artifact"] = str(path)
    return payload


def resolve_optional_input_path(path: Path | None, *, fallback: Path | None = None) -> Path | None:
    for candidate in (path, fallback):
        if candidate is not None and candidate.exists():
            return candidate
    return None


def build_public_report(
    store: RevenueStore,
    *,
    launch_summary: dict[str, Any] | None = None,
    benchmark_payload: dict[str, Any] | None = None,
    report_path: Path = DEFAULT_OUTPUT_PATH,
    launch_summary_path: Path = DEFAULT_LAUNCH_OUTPUT_PATH,
    status_path: Path = DEFAULT_STATUS_OUTPUT_PATH,
    allocator_path: Path = DEFAULT_ALLOCATOR_OUTPUT_PATH,
    comparison_path: Path = DEFAULT_COMPARISON_OUTPUT_PATH,
) -> dict[str, Any]:
    resolved_launch_summary = (
        coerce_launch_summary(launch_summary, output_path=launch_summary_path)
        if launch_summary is not None
        else build_launch_summary(
            db_path=store.db_path,
            output_path=launch_summary_path,
        )
    )
    snapshot = store.public_report_snapshot()
    status_snapshot = store.status_snapshot()
    operations = build_operations_summary(
        status_snapshot=status_snapshot,
        engine_states=store.list_engine_states(),
    )
    offer = website_growth_audit_offer()
    funnel = snapshot["funnel"]
    commercial = snapshot["commercial"]
    phase = snapshot["phase"]

    wedge_status = "launch_prep"
    if commercial["revenue_won_usd"] > 0:
        wedge_status = "revenue_evidence"
    elif funnel["proposals_sent"] > 0:
        wedge_status = "proposal_ready"
    elif funnel["delivered_messages"] > 0:
        wedge_status = "outreach_active"
    elif funnel["qualified_accounts"] > 0:
        wedge_status = "qualified_pipeline_seeded"

    source_artifacts = {
        "primary_store": snapshot["source_snapshot"]["db_path"],
        "telemetry_dataset": snapshot["source_snapshot"]["telemetry_dataset"],
        "report_artifact": str(report_path),
        "status_artifact": str(status_path),
        "allocator_input_artifact": str(allocator_path),
        "benchmark_comparison_artifact": str(comparison_path),
    }
    if resolved_launch_summary.get("source_artifact"):
        source_artifacts["launch_summary"] = str(resolved_launch_summary["source_artifact"])
    if benchmark_payload and benchmark_payload.get("source_artifact"):
        source_artifacts["benchmark_input"] = str(benchmark_payload["source_artifact"])

    readiness = build_first_dollar_readiness(
        snapshot=snapshot,
        offer=offer,
        operations=operations,
        launch_summary=resolved_launch_summary,
        source_artifacts={
            "public_report": str(report_path),
            "launch_summary": str(launch_summary_path),
            "status_artifact": str(status_path),
            "allocator_input_artifact": str(allocator_path),
            "benchmark_comparison_artifact": str(comparison_path),
        },
    )
    allocator_input = build_allocator_input(
        snapshot=snapshot,
        readiness=readiness,
        operations=operations,
        launch_summary=resolved_launch_summary,
    )
    scoreboard = build_first_dollar_scoreboard(
        snapshot=snapshot,
        readiness=readiness,
        allocator_input=allocator_input,
        launch_summary=resolved_launch_summary,
    )
    comparison_artifact = build_comparison_artifact(
        snapshot=snapshot,
        operations=operations,
        readiness=readiness,
        allocator_input=allocator_input,
        launch_summary=resolved_launch_summary,
        benchmark_payload=benchmark_payload,
    )

    return {
        **snapshot,
        "schema_version": PUBLIC_REPORT_SCHEMA_VERSION,
        "launch_summary": resolved_launch_summary,
        "headline": {
            "title": "JJ-N Website Growth Audit",
            "summary": _headline(snapshot),
            "current_phase": phase["current_phase"],
            "claim_status": phase["claim_status"],
        },
        "wedge": {
            "offer_name": offer.name,
            "offer_slug": offer.slug,
            "description": offer.description,
            "price_range_usd": {"low": offer.price_range[0], "high": offer.price_range[1]},
            "delivery_days": offer.delivery_days,
            "fulfillment_type": offer.fulfillment_type,
            "funnel_stages": list(offer.funnel_stages),
            "provisioning": dict(offer.fulfillment_provisioning),
            "status": wedge_status,
            "live_send_status": snapshot["fulfillment"]["delivery_claim_status"],
            "claim_status": phase["claim_status"],
        },
        "operations": operations,
        "first_dollar_readiness": readiness.to_dict(),
        "first_dollar_scoreboard": scoreboard,
        "allocator_input": allocator_input,
        "comparison_artifact": comparison_artifact,
        "source_artifacts": source_artifacts,
    }


def write_json_artifact(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_report(report: dict[str, Any], output_path: Path) -> None:
    write_json_artifact(report, output_path)


def write_sidecar_artifacts(
    report: dict[str, Any],
    *,
    launch_summary_path: Path,
    status_path: Path,
    allocator_path: Path,
    comparison_path: Path,
) -> None:
    write_json_artifact(report["launch_summary"], launch_summary_path)
    write_json_artifact(report["first_dollar_readiness"], status_path)
    write_json_artifact({REVENUE_AUDIT_ENGINE: report["allocator_input"]}, allocator_path)
    write_json_artifact(report["comparison_artifact"], comparison_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to the JJ-N revenue SQLite database.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Where to write the public-safe report artifact (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--launch-input",
        type=Path,
        default=None,
        help="Optional JSON contract from checkout/manual-close/fulfillment surfaces.",
    )
    parser.add_argument(
        "--launch-output",
        type=Path,
        default=DEFAULT_LAUNCH_OUTPUT_PATH,
        help=f"Where to write the canonical JJ-N launch-summary artifact (default: {DEFAULT_LAUNCH_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--benchmark-input",
        type=Path,
        default=None,
        help=(
            "Optional JSON contract from the isolated comparison benchmark adapter. "
            f"If omitted, the generator auto-loads {DEFAULT_BENCHMARK_INPUT_PATH} when present."
        ),
    )
    parser.add_argument(
        "--status-output",
        type=Path,
        default=DEFAULT_STATUS_OUTPUT_PATH,
        help=f"Where to write the first-dollar readiness artifact (default: {DEFAULT_STATUS_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--allocator-output",
        type=Path,
        default=DEFAULT_ALLOCATOR_OUTPUT_PATH,
        help=f"Where to write the allocator-ready engine-family input (default: {DEFAULT_ALLOCATOR_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--comparison-output",
        type=Path,
        default=DEFAULT_COMPARISON_OUTPUT_PATH,
        help=f"Where to write the benchmark comparison artifact (default: {DEFAULT_COMPARISON_OUTPUT_PATH}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = RevenueStore(args.db_path)
    raw_launch_summary = _load_optional_json(resolve_optional_input_path(args.launch_input))
    launch_summary = (
        coerce_launch_summary(
            raw_launch_summary,
            output_path=args.launch_output,
            input_artifact=args.launch_input,
        )
        if raw_launch_summary is not None
        else None
    )
    benchmark_payload = _load_optional_json(
        resolve_optional_input_path(
            args.benchmark_input,
            fallback=DEFAULT_BENCHMARK_INPUT_PATH,
        )
    )
    report = build_public_report(
        store,
        launch_summary=launch_summary,
        benchmark_payload=benchmark_payload,
        report_path=args.output,
        launch_summary_path=args.launch_output,
        status_path=args.status_output,
        allocator_path=args.allocator_output,
        comparison_path=args.comparison_output,
    )
    write_report(report, args.output)
    write_sidecar_artifacts(
        report,
        launch_summary_path=args.launch_output,
        status_path=args.status_output,
        allocator_path=args.allocator_output,
        comparison_path=args.comparison_output,
    )
    print(
        "Wrote JJ-N public report, launch summary, first-dollar readiness, allocator input, "
        f"and benchmark comparison artifacts to {args.output.parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
