"""Recurring-monitor ARR summary contract for JJ-N."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nontrading.offers.website_growth_audit import website_growth_audit_recurring_monitor_offer
from nontrading.revenue_audit.contracts import contract_to_dict, utc_now
from nontrading.revenue_audit.store import RevenueAuditStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_recurring_monitor" / "latest.json"
SCHEMA_VERSION = "revenue_audit_recurring_monitor.v1"


def build_recurring_monitor_summary(
    audit_store: RevenueAuditStore,
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    offer = website_growth_audit_recurring_monitor_offer()
    enrollments = audit_store.list_recurring_monitor_enrollments()
    monitor_runs = audit_store.list_monitor_runs()
    orders = {order.order_id: order for order in audit_store.list_orders()}
    payment_events = audit_store.list_payment_events()

    status_counts = {
        "staged": 0,
        "checkout_pending": 0,
        "active": 0,
        "paused": 0,
        "canceled": 0,
        "churned": 0,
        "refunded": 0,
    }
    for enrollment in enrollments:
        status_counts[enrollment.status] = status_counts.get(enrollment.status, 0) + 1

    active_enrollments = [enrollment for enrollment in enrollments if enrollment.status == "active"]
    recurring_monitor_order_ids = {enrollment.monitor_order_id for enrollment in enrollments if enrollment.monitor_order_id}
    recurring_cash_collected_usd = round(
        sum(
            float(event.amount_total_usd)
            for event in payment_events
            if event.order_id in recurring_monitor_order_ids and event.status in {"paid", "succeeded", "completed"}
        ),
        2,
    )
    recurring_monitor_runs = [
        run for run in monitor_runs if str(run.recurring_monitor_enrollment_id).strip()
    ]
    active_mrr_usd = round(sum(float(enrollment.monthly_amount_usd) for enrollment in active_enrollments), 2)
    monthly_price_usd = round(
        (
            sum(float(enrollment.monthly_amount_usd) for enrollment in enrollments) / len(enrollments)
            if enrollments
            else 299.0
        ),
        2,
    )
    one_time_audit_cash_usd = round(
        sum(
            float(event.amount_total_usd)
            for event in payment_events
            if event.order_id not in recurring_monitor_order_ids and event.status in {"paid", "succeeded", "completed"}
        ),
        2,
    )
    delivered_audits = sum(
        1
        for order in orders.values()
        if order.offer_slug != offer.slug and str(order.fulfillment_status).strip().lower() == "delivered"
    )
    status = "live_contract" if active_enrollments else "assumption_only"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "status": status,
        "active_enrollments": len(active_enrollments),
        "monitor_runs_completed": len(recurring_monitor_runs),
        "delivered_audits": delivered_audits,
        "monthly_price_usd": monthly_price_usd,
        "current_mrr_usd": active_mrr_usd,
        "current_arr_usd": round(active_mrr_usd * 12.0, 2),
        "assumptions": {
            "upsell_rate": round((len(active_enrollments) / delivered_audits), 6) if delivered_audits else 0.0,
            "churn_rate_30d": 0.0,
        },
        "source_artifact": str(output_path),
        "source_db_path": str(audit_store.db_path),
        "offer": {
            "name": offer.name,
            "slug": offer.slug,
            "parent_offer_slug": offer.parent_offer_slug,
            "billing_interval": offer.billing_interval,
            "cadence_days": offer.cadence_days,
            "deliverables": list(offer.deliverables),
        },
        "summary": {
            "staged_enrollments": status_counts.get("staged", 0),
            "checkout_pending_enrollments": status_counts.get("checkout_pending", 0),
            "active_enrollments": status_counts.get("active", 0),
            "paused_enrollments": status_counts.get("paused", 0),
            "canceled_enrollments": status_counts.get("canceled", 0),
            "churned_enrollments": status_counts.get("churned", 0),
            "refunded_enrollments": status_counts.get("refunded", 0),
            "active_mrr_usd": active_mrr_usd,
            "active_arr_usd": round(active_mrr_usd * 12.0, 2),
            "recurring_cash_collected_usd": recurring_cash_collected_usd,
            "one_time_audit_cash_excluded_usd": one_time_audit_cash_usd,
            "delta_reports_completed": len(recurring_monitor_runs),
        },
        "enrollments": [
            {
                **contract_to_dict(enrollment),
                "active_arr_usd": round(float(enrollment.monthly_amount_usd) * 12.0, 2),
                "audit_order_status": getattr(orders.get(enrollment.audit_order_id), "status", None),
                "monitor_order_status": getattr(orders.get(enrollment.monitor_order_id), "status", None)
                if enrollment.monitor_order_id
                else None,
            }
            for enrollment in enrollments
        ],
        "artifacts": {
            "order_count": len(orders),
            "payment_event_count": len(payment_events),
            "monitor_run_count": len(recurring_monitor_runs),
        },
    }


def write_recurring_monitor_summary(
    payload: dict[str, Any],
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
