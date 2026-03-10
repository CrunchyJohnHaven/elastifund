#!/usr/bin/env python3
"""Fulfill one paid revenue-audit order and regenerate JJ-N first-dollar artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.models import utc_now
from nontrading.revenue_audit.fulfillment import DEFAULT_ARTIFACT_ROOT, RevenueAuditFulfillmentService
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry
from scripts.generate_nontrading_public_report import (
    build_public_report,
    write_report,
    write_sidecar_artifacts,
)

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "revenue_agent.db"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "reports" / "nontrading" / "operations"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return cleaned.strip("-._") or "order"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", required=True, help="Paid revenue-audit order id to fulfill.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to the JJ-N revenue SQLite database.")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_ARTIFACT_ROOT,
        help="Where delivery and monitor artifacts should be written.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for regenerated report and sidecar artifacts.",
    )
    parser.add_argument(
        "--skip-monitor",
        action="store_true",
        help="Skip the baseline monitor rerun artifact.",
    )
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _status_timeline(metadata: dict[str, object] | None) -> list[dict[str, object]]:
    if not metadata:
        return []
    timeline = metadata.get("status_timeline")
    if not isinstance(timeline, list):
        return []
    return [dict(item) for item in timeline if isinstance(item, dict)]


def _artifact_catalog(metadata: dict[str, object] | None) -> dict[str, object]:
    if not metadata:
        return {}
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {str(key): value for key, value in artifacts.items()}


def main() -> int:
    args = parse_args()
    db_path = args.db_path
    output_dir = args.output_root / _slugify(args.order_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_store = RevenueAuditStore(db_path)
    revenue_store = RevenueStore(db_path)
    telemetry = NonTradingTelemetry(revenue_store)
    service = RevenueAuditFulfillmentService(
        audit_store=audit_store,
        revenue_store=revenue_store,
        telemetry=telemetry,
        artifact_root=args.artifact_root,
    )

    order = audit_store.get_order(args.order_id)
    if order is None:
        raise SystemExit(f"Unknown revenue-audit order: {args.order_id}")

    fulfillment = service.fulfill_order(args.order_id)
    monitor = None
    monitor_status = "skipped"
    monitor_reason = ""
    if args.skip_monitor:
        monitor_reason = "disabled_by_flag"
    elif order.audit_bundle is None:
        monitor_reason = "missing_baseline_bundle"
    else:
        monitor = service.run_monitor(args.order_id, current_bundle=order.audit_bundle)
        monitor_status = "completed"

    report_path = output_dir / "nontrading_public_report.json"
    launch_summary_path = output_dir / "nontrading_launch_summary.json"
    launch_checklist_path = output_dir / "nontrading_launch_operator_checklist.json"
    status_path = output_dir / "nontrading_first_dollar_status.json"
    allocator_path = output_dir / "nontrading_allocator_input.json"
    comparison_path = output_dir / "nontrading_benchmark_comparison.json"
    report = build_public_report(
        revenue_store,
        report_path=report_path,
        launch_summary_path=launch_summary_path,
        launch_checklist_path=launch_checklist_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
    )
    write_report(report, report_path)
    write_sidecar_artifacts(
        report,
        launch_summary_path=launch_summary_path,
        launch_checklist_path=launch_checklist_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
    )
    final_order = audit_store.get_order(args.order_id)
    final_metadata = dict(final_order.metadata) if final_order is not None else {}
    timeline = _status_timeline(final_metadata)
    artifacts = _artifact_catalog(final_metadata)
    ship_artifact = str(artifacts.get("delivery_markdown") or fulfillment.artifact_path)
    operator_steps = [
        {
            "step": "regenerate_report",
            "status": "completed",
            "artifact_path": str(report_path),
        },
        {
            "step": "verify_status",
            "status": "completed" if report["first_dollar_readiness"]["status"] == "first_dollar_observed" else "needs_review",
            "detail": report["first_dollar_readiness"]["status"],
            "artifact_path": str(status_path),
        },
        {
            "step": "ship_delivery_pack",
            "status": "completed" if ship_artifact else "needs_review",
            "artifact_path": ship_artifact,
        },
    ]

    summary = {
        "schema_version": "revenue_audit_fulfillment_run.v1",
        "generated_at": utc_now(),
        "order_id": args.order_id,
        "db_path": str(db_path),
        "artifact_root": str(args.artifact_root),
        "report_status": report["first_dollar_readiness"]["status"],
        "claim_status": report["headline"]["claim_status"],
        "delivery_artifact_paths": list(fulfillment.artifact_paths),
        "delivery_checklist_path": fulfillment.delivery_checklist_path,
        "delivery_pack_path": fulfillment.delivery_pack_path,
        "monitor_status": monitor_status,
        "monitor_reason": monitor_reason,
        "monitor_artifact_paths": list(monitor.artifact_paths) if monitor is not None else [],
        "order_timeline": timeline,
        "order_artifacts": artifacts,
        "operator_steps": operator_steps,
        "outputs": {
            "report": str(report_path),
            "launch_summary": str(launch_summary_path),
            "launch_checklist": str(launch_checklist_path),
            "status": str(status_path),
            "allocator_input": str(allocator_path),
            "comparison": str(comparison_path),
        },
    }
    summary_path = output_dir / "summary.json"
    write_json(summary_path, summary)
    print(
        f"Fulfilled {args.order_id}: report_status={summary['report_status']} "
        f"claim_status={summary['claim_status']} summary={summary_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
