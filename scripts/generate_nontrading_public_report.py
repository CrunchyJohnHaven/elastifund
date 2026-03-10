#!/usr/bin/env python3
"""Generate a public-safe JJ-N report artifact for the website."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.arr_lab import (
    DEFAULT_OUTPUT_PATH as DEFAULT_ARR_LAB_OUTPUT_PATH,
    DEFAULT_RECURRING_MONITOR_OUTPUT_PATH,
    build_arr_lab,
    build_recurring_monitor_summary as build_fallback_recurring_monitor_summary,
    load_cycle_reports,
)
from nontrading.first_dollar import (
    PUBLIC_REPORT_SCHEMA_VERSION,
    build_allocator_input,
    build_comparison_artifact,
    build_first_dollar_readiness,
    build_first_dollar_scoreboard,
    build_operations_summary,
)
from nontrading.offers.website_growth_audit import website_growth_audit_offer
from nontrading.revenue_audit.launch_summary import DEFAULT_OUTPUT_PATH as DEFAULT_LAUNCH_SUMMARY_PATH
from nontrading.revenue_audit.launch_summary import build_launch_summary, coerce_launch_summary
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.store import RevenueStore
from orchestration.models import REVENUE_AUDIT_ENGINE

try:
    from nontrading.revenue_audit.launch_summary import (
        DEFAULT_OPERATOR_CHECKLIST_PATH as DEFAULT_LAUNCH_CHECKLIST_ARTIFACT_PATH,
    )
except ImportError:
    DEFAULT_LAUNCH_CHECKLIST_ARTIFACT_PATH = PROJECT_ROOT / "reports" / "nontrading_launch_operator_checklist.json"

try:
    from nontrading.revenue_audit.recurring_monitor import (
        build_recurring_monitor_summary as build_live_recurring_monitor_summary,
    )
except ImportError:
    build_live_recurring_monitor_summary = None


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "revenue_agent.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_public_report.json"
DEFAULT_LAUNCH_OUTPUT_PATH = DEFAULT_LAUNCH_SUMMARY_PATH
DEFAULT_LAUNCH_CHECKLIST_OUTPUT_PATH = DEFAULT_LAUNCH_CHECKLIST_ARTIFACT_PATH
DEFAULT_STATUS_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_first_dollar_status.json"
DEFAULT_ALLOCATOR_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_allocator_input.json"
DEFAULT_COMPARISON_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_benchmark_comparison.json"
DEFAULT_BENCHMARK_INPUT_PATH = PROJECT_ROOT / "reports" / "openclaw" / "normalized" / "latest.json"
DEFAULT_LAUNCH_BRIDGE_INPUT_PATH = PROJECT_ROOT / "reports" / "nontrading" / "revenue_audit_launch_bridge.json"
DEFAULT_CYCLE_REPORT_INPUT_PATH = PROJECT_ROOT / "reports" / "nontrading" / "website_growth_audit_cycle_reports.jsonl"
UTC = timezone.utc


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


def _supports_operator_checklist(func: Any) -> bool:
    try:
        return "operator_checklist_path" in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def _fallback_launch_checklist(summary: dict[str, Any], output_path: Path) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    if not bool(summary.get("checkout_ready")):
        missing.append(
            {
                "key": "checkout_surface",
                "surface": "checkout",
                "detail": "Checkout surface still needs route or config work.",
            }
        )
    if not bool(summary.get("webhook_ready")):
        missing.append(
            {
                "key": "billing_webhook",
                "surface": "webhook",
                "detail": "Stripe webhook route or secret configuration is still incomplete.",
            }
        )
    if not bool(summary.get("manual_close_ready")):
        missing.append(
            {
                "key": "manual_close_lane",
                "surface": "manual_close",
                "detail": "The manual-close staging lane is not currently available.",
            }
        )
    if not bool(summary.get("fulfillment_ready")):
        missing.append(
            {
                "key": "fulfillment_surface",
                "surface": "fulfillment",
                "detail": "Fulfillment is not yet callable from the current runtime state.",
            }
        )
    return {
        "schema_version": "revenue_audit_launch_operator_checklist.v1",
        "generated_at": str(summary.get("generated_at") or datetime.now(tz=UTC).replace(microsecond=0).isoformat()),
        "source_artifact": str(output_path),
        "status": "ready" if not missing else "blocked",
        "launchable": bool(summary.get("launchable")),
        "blocking_reasons": list(summary.get("blocking_reasons") or ()),
        "live_offer_url": summary.get("live_offer_url"),
        "missing_requirements": missing,
    }


def _normalize_launch_checklist(summary: dict[str, Any], output_path: Path) -> dict[str, Any]:
    raw = summary.get("operator_checklist")
    if isinstance(raw, dict):
        normalized = dict(raw)
        normalized["source_artifact"] = str(output_path)
        normalized["launchable"] = bool(normalized.get("launchable", summary.get("launchable")))
        normalized["blocking_reasons"] = list(
            normalized.get("blocking_reasons") or summary.get("blocking_reasons") or ()
        )
        normalized["live_offer_url"] = normalized.get("live_offer_url", summary.get("live_offer_url"))
        normalized["missing_requirements"] = list(normalized.get("missing_requirements") or ())
        return normalized
    return _fallback_launch_checklist(summary, output_path)


def build_public_report(
    store: RevenueStore,
    *,
    launch_summary: dict[str, Any] | None = None,
    benchmark_payload: dict[str, Any] | None = None,
    launch_bridge_payload: dict[str, Any] | None = None,
    cycle_reports: list[dict[str, Any]] | None = None,
    recurring_monitor_payload: dict[str, Any] | None = None,
    report_path: Path = DEFAULT_OUTPUT_PATH,
    launch_summary_path: Path = DEFAULT_LAUNCH_OUTPUT_PATH,
    launch_checklist_path: Path = DEFAULT_LAUNCH_CHECKLIST_OUTPUT_PATH,
    status_path: Path = DEFAULT_STATUS_OUTPUT_PATH,
    allocator_path: Path = DEFAULT_ALLOCATOR_OUTPUT_PATH,
    comparison_path: Path = DEFAULT_COMPARISON_OUTPUT_PATH,
    arr_lab_path: Path | None = None,
    recurring_monitor_path: Path | None = None,
) -> dict[str, Any]:
    resolved_arr_lab_path = arr_lab_path or report_path.parent / "nontrading_arr_lab" / "latest.json"
    resolved_recurring_monitor_path = (
        recurring_monitor_path
        or report_path.parent / "nontrading_recurring_monitor" / "latest.json"
    )
    if launch_summary is not None:
        coerce_kwargs: dict[str, Any] = {"output_path": launch_summary_path}
        if _supports_operator_checklist(coerce_launch_summary):
            coerce_kwargs["operator_checklist_path"] = launch_checklist_path
        resolved_launch_summary = coerce_launch_summary(launch_summary, **coerce_kwargs)
    else:
        build_kwargs: dict[str, Any] = {"db_path": store.db_path, "output_path": launch_summary_path}
        if _supports_operator_checklist(build_launch_summary):
            build_kwargs["operator_checklist_path"] = launch_checklist_path
        resolved_launch_summary = build_launch_summary(**build_kwargs)
    resolved_launch_summary = {
        **resolved_launch_summary,
        "operator_checklist": _normalize_launch_checklist(resolved_launch_summary, launch_checklist_path),
    }
    snapshot = store.public_report_snapshot()
    status_snapshot = store.status_snapshot()
    operations = build_operations_summary(
        status_snapshot=status_snapshot,
        engine_states=store.list_engine_states(),
    )
    offer = website_growth_audit_offer()
    recurring_monitor = (
        dict(recurring_monitor_payload)
        if recurring_monitor_payload is not None
        else (
            build_live_recurring_monitor_summary(
                RevenueAuditStore(store.db_path),
                output_path=resolved_recurring_monitor_path,
            )
            if build_live_recurring_monitor_summary is not None
            else build_fallback_recurring_monitor_summary(
                snapshot=snapshot,
                launch_summary=resolved_launch_summary,
                offer=offer,
                bridge_payload=launch_bridge_payload,
                output_path=resolved_recurring_monitor_path,
            )
        )
    )
    if not recurring_monitor.get("source_artifact"):
        recurring_monitor["source_artifact"] = str(resolved_recurring_monitor_path)
    arr_lab = build_arr_lab(
        snapshot=snapshot,
        operations=operations,
        launch_summary=resolved_launch_summary,
        offer=offer,
        launch_bridge_payload=launch_bridge_payload,
        cycle_reports=cycle_reports,
        recurring_monitor_payload=recurring_monitor,
        output_path=resolved_arr_lab_path,
    )
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
        "launch_checklist_artifact": str(launch_checklist_path),
        "status_artifact": str(status_path),
        "allocator_input_artifact": str(allocator_path),
        "benchmark_comparison_artifact": str(comparison_path),
        "arr_lab_artifact": str(resolved_arr_lab_path),
        "recurring_monitor_artifact": str(resolved_recurring_monitor_path),
    }
    if resolved_launch_summary.get("source_artifact"):
        source_artifacts["launch_summary"] = str(resolved_launch_summary["source_artifact"])
    if benchmark_payload and benchmark_payload.get("source_artifact"):
        source_artifacts["benchmark_input"] = str(benchmark_payload["source_artifact"])
    if launch_bridge_payload and launch_bridge_payload.get("source_artifact"):
        source_artifacts["launch_bridge_input"] = str(launch_bridge_payload["source_artifact"])
    else:
        source_artifacts["launch_bridge_input"] = str(DEFAULT_LAUNCH_BRIDGE_INPUT_PATH)
    source_artifacts["cycle_report_input"] = str(DEFAULT_CYCLE_REPORT_INPUT_PATH)

    readiness = build_first_dollar_readiness(
        snapshot=snapshot,
        offer=offer,
        operations=operations,
        launch_summary=resolved_launch_summary,
        arr_lab=arr_lab,
        source_artifacts={
            "public_report": str(report_path),
            "launch_summary": str(launch_summary_path),
            "launch_checklist_artifact": str(launch_checklist_path),
            "status_artifact": str(status_path),
            "allocator_input_artifact": str(allocator_path),
            "benchmark_comparison_artifact": str(comparison_path),
            "arr_lab": str(resolved_arr_lab_path),
            "recurring_monitor": str(resolved_recurring_monitor_path),
        },
    )
    allocator_input = build_allocator_input(
        snapshot=snapshot,
        readiness=readiness,
        operations=operations,
        launch_summary=resolved_launch_summary,
        arr_lab=arr_lab,
    )
    scoreboard = build_first_dollar_scoreboard(
        snapshot=snapshot,
        readiness=readiness,
        allocator_input=allocator_input,
        launch_summary=resolved_launch_summary,
        arr_lab=arr_lab,
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
        "arr_lab": arr_lab,
        "recurring_monitor": recurring_monitor,
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
    launch_checklist_path: Path = DEFAULT_LAUNCH_CHECKLIST_OUTPUT_PATH,
    arr_lab_path: Path | None = None,
    recurring_monitor_path: Path | None = None,
) -> None:
    write_json_artifact(report["launch_summary"], launch_summary_path)
    write_json_artifact(report["launch_summary"]["operator_checklist"], launch_checklist_path)
    write_json_artifact(report["first_dollar_readiness"], status_path)
    write_json_artifact({REVENUE_AUDIT_ENGINE: report["allocator_input"]}, allocator_path)
    write_json_artifact(report["comparison_artifact"], comparison_path)
    if arr_lab_path is not None:
        write_json_artifact(report["arr_lab"], arr_lab_path)
    if recurring_monitor_path is not None:
        write_json_artifact(report["recurring_monitor"], recurring_monitor_path)


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
        "--launch-checklist-output",
        type=Path,
        default=DEFAULT_LAUNCH_CHECKLIST_OUTPUT_PATH,
        help=(
            "Where to write the launch operator checklist artifact "
            f"(default: {DEFAULT_LAUNCH_CHECKLIST_OUTPUT_PATH})."
        ),
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
    parser.add_argument(
        "--launch-bridge-input",
        type=Path,
        default=None,
        help=(
            "Optional launch-bridge JSON input. "
            f"If omitted, the generator auto-loads {DEFAULT_LAUNCH_BRIDGE_INPUT_PATH} when present."
        ),
    )
    parser.add_argument(
        "--cycle-report-input",
        type=Path,
        default=None,
        help=(
            "Optional cycle-report JSONL input. "
            f"If omitted, the generator auto-loads {DEFAULT_CYCLE_REPORT_INPUT_PATH} when present."
        ),
    )
    parser.add_argument(
        "--recurring-monitor-input",
        type=Path,
        default=None,
        help=(
            "Optional recurring-monitor JSON contract. "
            f"If omitted, the generator auto-loads {DEFAULT_RECURRING_MONITOR_OUTPUT_PATH} when present."
        ),
    )
    parser.add_argument(
        "--arr-lab-output",
        type=Path,
        default=DEFAULT_ARR_LAB_OUTPUT_PATH,
        help=f"Where to write the ARR-lab forecast artifact (default: {DEFAULT_ARR_LAB_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--recurring-monitor-output",
        type=Path,
        default=DEFAULT_RECURRING_MONITOR_OUTPUT_PATH,
        help=(
            "Where to write the recurring-monitor summary artifact "
            f"(default: {DEFAULT_RECURRING_MONITOR_OUTPUT_PATH})."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = RevenueStore(args.db_path)
    raw_launch_summary = _load_optional_json(resolve_optional_input_path(args.launch_input))
    if raw_launch_summary is not None:
        coerce_kwargs: dict[str, Any] = {
            "output_path": args.launch_output,
            "input_artifact": args.launch_input,
        }
        if _supports_operator_checklist(coerce_launch_summary):
            coerce_kwargs["operator_checklist_path"] = args.launch_checklist_output
        launch_summary = coerce_launch_summary(raw_launch_summary, **coerce_kwargs)
    else:
        launch_summary = None
    benchmark_payload = _load_optional_json(
        resolve_optional_input_path(
            args.benchmark_input,
            fallback=DEFAULT_BENCHMARK_INPUT_PATH,
        )
    )
    launch_bridge_payload = _load_optional_json(
        resolve_optional_input_path(
            args.launch_bridge_input,
            fallback=DEFAULT_LAUNCH_BRIDGE_INPUT_PATH,
        )
    )
    cycle_report_path = resolve_optional_input_path(
        args.cycle_report_input,
        fallback=DEFAULT_CYCLE_REPORT_INPUT_PATH,
    )
    cycle_reports = load_cycle_reports(cycle_report_path) if cycle_report_path is not None else None
    recurring_monitor_payload = _load_optional_json(
        resolve_optional_input_path(
            args.recurring_monitor_input,
            fallback=DEFAULT_RECURRING_MONITOR_OUTPUT_PATH,
        )
    )
    report = build_public_report(
        store,
        launch_summary=launch_summary,
        benchmark_payload=benchmark_payload,
        launch_bridge_payload=launch_bridge_payload,
        cycle_reports=cycle_reports,
        recurring_monitor_payload=recurring_monitor_payload,
        report_path=args.output,
        launch_summary_path=args.launch_output,
        launch_checklist_path=args.launch_checklist_output,
        status_path=args.status_output,
        allocator_path=args.allocator_output,
        comparison_path=args.comparison_output,
        arr_lab_path=args.arr_lab_output,
        recurring_monitor_path=args.recurring_monitor_output,
    )
    write_report(report, args.output)
    write_sidecar_artifacts(
        report,
        launch_summary_path=args.launch_output,
        launch_checklist_path=args.launch_checklist_output,
        status_path=args.status_output,
        allocator_path=args.allocator_output,
        comparison_path=args.comparison_output,
        arr_lab_path=args.arr_lab_output,
        recurring_monitor_path=args.recurring_monitor_output,
    )
    print(
        "Wrote JJ-N public report, launch summary, launch checklist, first-dollar readiness, "
        "allocator input, benchmark comparison, ARR-lab, and recurring-monitor artifacts "
        f"to {args.output.parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
