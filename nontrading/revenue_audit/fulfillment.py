"""Paid-audit fulfillment and recurring-monitor helpers for JJ-N."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nontrading.models import Opportunity, Outcome
from nontrading.offers.website_growth_audit import website_growth_audit_recurring_monitor_offer
from nontrading.revenue_audit.contracts import (
    AuditBundle,
    AuditOrder,
    FulfillmentJob,
    MonitorRun,
    RecurringMonitorEnrollment,
    contract_to_dict,
    utc_now,
)
from nontrading.revenue_audit.models import (
    AuditBundle as StoreAuditBundle,
    FulfillmentJob as StoreFulfillmentJob,
    MonitorRun as StoreMonitorRun,
)
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry

DEFAULT_ARTIFACT_ROOT = Path("reports/nontrading")
DEFAULT_FULFILLMENT_JOB_TYPE = "website_growth_audit"
PAID_ORDER_STATUSES = {"paid"}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
UTC = timezone.utc


@dataclass(frozen=True)
class FulfillmentExecution:
    order: AuditOrder | None = None
    job: Any | None = None
    delivered_bundle: Any | None = None
    outcome: Outcome | None = None
    artifact_path: str = ""
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)
    delivery_checklist_path: str = ""
    delivery_pack_path: str = ""

    def __post_init__(self) -> None:
        artifact_path = str(self.artifact_path).strip()
        artifact_paths = tuple(str(path).strip() for path in self.artifact_paths if str(path).strip())
        if not artifact_path and artifact_paths:
            artifact_path = artifact_paths[0]
        if artifact_path and not artifact_paths:
            artifact_paths = (artifact_path,)
        object.__setattr__(self, "artifact_path", artifact_path)
        object.__setattr__(self, "artifact_paths", artifact_paths)
        object.__setattr__(self, "delivery_checklist_path", str(self.delivery_checklist_path).strip())
        object.__setattr__(self, "delivery_pack_path", str(self.delivery_pack_path).strip())


@dataclass(frozen=True)
class MonitorExecution:
    order: AuditOrder | None = None
    monitor_run: Any | None = None
    artifact_path: str = ""
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        artifact_path = str(self.artifact_path).strip()
        artifact_paths = tuple(str(path).strip() for path in self.artifact_paths if str(path).strip())
        if not artifact_path and artifact_paths:
            artifact_path = artifact_paths[0]
        if artifact_path and not artifact_paths:
            artifact_paths = (artifact_path,)
        object.__setattr__(self, "artifact_path", artifact_path)
        object.__setattr__(self, "artifact_paths", artifact_paths)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return cleaned.strip("-._") or "artifact"


def _severity_value(value: str) -> int:
    return SEVERITY_RANK.get(str(value).strip().lower(), 0)


def _issue_key(issue: Any) -> str:
    if hasattr(issue, "issue_id"):
        return str(issue.issue_id).strip().lower()
    if hasattr(issue, "detector_key"):
        return str(issue.detector_key).strip().lower()
    return json.dumps(contract_to_dict(issue), sort_keys=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _delivery_checklist() -> tuple[dict[str, str], ...]:
    return (
        {"step": "payment_confirmed", "status": "completed"},
        {"step": "baseline_bundle_loaded", "status": "completed"},
        {"step": "artifact_generated", "status": "completed"},
        {"step": "delivery_packet_ready", "status": "completed"},
        {"step": "monitor_enrolled", "status": "completed"},
    )


def _bundle_from_metadata(payload: dict[str, Any] | None) -> AuditBundle | None:
    if not payload:
        return None
    current = payload.get("current_bundle") or payload.get("latest_monitor_bundle")
    if not isinstance(current, dict) or not current:
        return None
    return AuditBundle(**current)


def _add_days_iso(timestamp: str | None, days: int) -> str | None:
    if not timestamp:
        return None
    parsed = str(timestamp).strip()
    if parsed.endswith("Z"):
        parsed = f"{parsed[:-1]}+00:00"
    try:
        current = datetime.fromisoformat(parsed)
    except ValueError:
        return None
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return (current + timedelta(days=int(days))).replace(microsecond=0).isoformat()


def _status_timeline(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not metadata:
        return []
    timeline = metadata.get("status_timeline")
    if not isinstance(timeline, list):
        return []
    return [dict(item) for item in timeline if isinstance(item, dict)]


def _artifact_catalog(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {str(key): value for key, value in artifacts.items()}


def _timeline_entry(
    *,
    status: str,
    occurred_at: str,
    detail: str,
    artifact_paths: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "status": str(status).strip(),
        "occurred_at": str(occurred_at).strip(),
        "detail": str(detail).strip(),
    }
    cleaned_paths = [str(path).strip() for path in artifact_paths if str(path).strip()]
    if cleaned_paths:
        entry["artifact_paths"] = cleaned_paths
    if metadata:
        entry["metadata"] = contract_to_dict(metadata)
    return entry


def _append_timeline_entries(metadata: dict[str, Any] | None, *entries: dict[str, Any]) -> dict[str, Any]:
    updated = dict(metadata or {})
    timeline = _status_timeline(updated)
    for entry in entries:
        if not entry:
            continue
        if timeline and timeline[-1] == entry:
            continue
        timeline.append(entry)
    updated["status_timeline"] = timeline
    return updated


def _merge_artifacts(metadata: dict[str, Any] | None, **artifacts: Any) -> dict[str, Any]:
    updated = dict(metadata or {})
    catalog = _artifact_catalog(updated)
    for key, value in artifacts.items():
        if isinstance(value, (list, tuple)):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if cleaned:
                catalog[str(key)] = cleaned
            continue
        if isinstance(value, dict):
            catalog[str(key)] = contract_to_dict(value)
            continue
        text = str(value or "").strip()
        if text:
            catalog[str(key)] = text
    updated["artifacts"] = catalog
    return updated


class RevenueAuditFulfillmentService:
    """Generate paid audit artifacts and recurring monitor deltas from queued orders."""

    def __init__(
        self,
        revenue_store: RevenueStore | None = None,
        telemetry: NonTradingTelemetry | None = None,
        *,
        audit_store: RevenueAuditStore | None = None,
        artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
        default_gross_margin_pct: float = 0.72,
    ) -> None:
        self.audit_store = audit_store
        self.revenue_store = revenue_store
        if self.revenue_store is None and self.audit_store is None:
            raise ValueError("RevenueAuditFulfillmentService requires revenue_store or audit_store")
        self.telemetry = telemetry or (
            NonTradingTelemetry(self.revenue_store) if self.revenue_store is not None else None
        )
        if self.telemetry is None:
            raise ValueError("RevenueAuditFulfillmentService requires telemetry when no revenue_store is provided")
        self.artifact_root = Path(artifact_root)
        self.default_gross_margin_pct = float(default_gross_margin_pct)
        self.recurring_monitor_offer = website_growth_audit_recurring_monitor_offer()

    def _ensure_staged_recurring_monitor(self, order: AuditOrder) -> RecurringMonitorEnrollment | None:
        if self.audit_store is None:
            return None
        existing = self.audit_store.find_recurring_monitor_enrollment_by_audit_order(order.order_id)
        amount = float(existing.monthly_amount_usd) if existing is not None else 299.0
        if existing is None:
            return self.audit_store.create_recurring_monitor_enrollment(
                RecurringMonitorEnrollment(
                    enrollment_id=self.audit_store.next_recurring_monitor_enrollment_id(),
                    audit_order_id=order.order_id,
                    offer_slug=self.recurring_monitor_offer.slug,
                    parent_offer_slug=order.offer_slug,
                    status="staged",
                    cadence_days=int(self.recurring_monitor_offer.cadence_days),
                    monthly_amount_usd=amount,
                    currency=order.currency,
                    metadata={
                        "audit_business_name": order.business_name,
                        "audit_website_url": order.website_url,
                    },
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        return self.audit_store.update_recurring_monitor_enrollment(
            existing.enrollment_id,
            metadata={
                **existing.metadata,
                "audit_business_name": order.business_name,
                "audit_website_url": order.website_url,
            },
            updated_at=utc_now(),
        )

    def _recurring_monitor_payload(
        self,
        *,
        order: AuditOrder,
        enrollment: RecurringMonitorEnrollment | None,
    ) -> dict[str, Any]:
        amount = float(enrollment.monthly_amount_usd) if enrollment is not None else 299.0
        return {
            "offer": {
                "name": self.recurring_monitor_offer.name,
                "slug": self.recurring_monitor_offer.slug,
                "description": self.recurring_monitor_offer.description,
                "billing_interval": self.recurring_monitor_offer.billing_interval,
                "cadence_days": self.recurring_monitor_offer.cadence_days,
                "deliverables": list(self.recurring_monitor_offer.deliverables),
                "monthly_amount_usd": amount,
                "annualized_arr_usd": round(amount * 12.0, 2),
            },
            "status": enrollment.status if enrollment is not None else "staged",
            "enrollment": contract_to_dict(enrollment) if enrollment is not None else None,
            "checkout_request_template": {
                "offer_slug": self.recurring_monitor_offer.slug,
                "source_order_id": order.order_id,
                "price_key": "monitor-monthly",
            },
        }

    def fulfill_paid_order(
        self,
        payment_event_id: int,
        *,
        baseline_bundle_id: int | None = None,
    ) -> FulfillmentExecution:
        if self.revenue_store is None:
            raise ValueError("fulfill_paid_order requires a RevenueStore-backed fulfillment service")

        store = self.revenue_store
        payment = store.get_payment_event(payment_event_id)
        if payment is None:
            raise ValueError(f"Unknown payment event: {payment_event_id}")
        if str(payment.status).strip().lower() not in {"paid", "succeeded", "completed"}:
            raise ValueError(f"Payment event {payment_event_id} is not paid: {payment.status}")

        checkout = store.get_checkout_session(payment.checkout_session_id or 0) if payment.checkout_session_id else None
        opportunity_id = payment.opportunity_id or (checkout.opportunity_id if checkout is not None else None)
        if opportunity_id is None:
            raise ValueError(f"Payment event {payment_event_id} is missing opportunity context")
        opportunity = store.get_opportunity(int(opportunity_id))
        if opportunity is None:
            raise ValueError(f"Unknown opportunity for payment event {payment_event_id}")

        prospect = None
        if payment.prospect_id is not None:
            prospect = store.get_prospect_profile(payment.prospect_id)
        if prospect is None:
            profiles = store.list_prospect_profiles(opportunity_id=opportunity.id)
            prospect = profiles[-1] if profiles else None
        if prospect is None:
            prospect = store.prospect_profile_from_account(store.get_account(opportunity.account_id), opportunity.id)

        baseline_bundle = (
            store.get_audit_bundle(baseline_bundle_id)
            if baseline_bundle_id is not None
            else self._resolve_store_bundle(opportunity.id or 0, exclude_bundle_id=None)
        )
        if baseline_bundle is None:
            raise ValueError(f"Opportunity {opportunity.id} is missing a baseline audit bundle")
        baseline_issues = store.list_issue_evidence(bundle_id=baseline_bundle.id or 0)

        order_id = (
            payment.order_id
            or (checkout.order_id if checkout is not None else "")
            or f"order-{payment.id or payment_event_id}"
        )
        generated_at = utc_now()
        artifact_dir = self.artifact_root / "fulfillment" / _slugify(order_id)
        artifact_path = artifact_dir / "paid_audit.json"
        payload = self._build_store_paid_audit_payload(
            order_id=order_id,
            prospect=prospect,
            payment=payment,
            baseline_bundle=baseline_bundle,
            baseline_issues=baseline_issues,
            generated_at=generated_at,
        )
        _write_json(artifact_path, payload)

        delivered_bundle = store.create_audit_bundle(
            StoreAuditBundle(
                prospect_id=prospect.id,
                opportunity_id=opportunity.id,
                proposal_id=payment.proposal_id,
                order_id=order_id,
                bundle_kind="delivery",
                status="delivered",
                summary=payload["summary"],
                score=float(baseline_bundle.score),
                issue_ids=tuple(issue.id or 0 for issue in baseline_issues),
                artifact_path=str(artifact_path),
                metadata={
                    "payment_event_id": payment.id,
                    "source_bundle_id": baseline_bundle.id,
                    "generated_at": generated_at,
                },
            )
        )

        existing_jobs = store.list_fulfillment_jobs(payment_event_id=payment.id)
        if existing_jobs:
            job = store.update_fulfillment_job(
                existing_jobs[-1].id or 0,
                status="delivered",
                current_step="delivered",
                audit_bundle_id=delivered_bundle.id,
                order_id=order_id,
                artifact_path=str(artifact_path),
                checklist=_delivery_checklist(),
                started_at=existing_jobs[-1].started_at or generated_at,
                completed_at=generated_at,
                metadata={
                    **existing_jobs[-1].metadata,
                    "source_bundle_id": baseline_bundle.id,
                },
            )
        else:
            job = store.create_fulfillment_job(
                StoreFulfillmentJob(
                    opportunity_id=opportunity.id,
                    proposal_id=payment.proposal_id,
                    prospect_id=prospect.id,
                    payment_event_id=payment.id,
                    audit_bundle_id=delivered_bundle.id,
                    order_id=order_id,
                    status="delivered",
                    current_step="delivered",
                    artifact_path=str(artifact_path),
                    checklist=_delivery_checklist(),
                    metadata={"source_bundle_id": baseline_bundle.id},
                    started_at=generated_at,
                    completed_at=generated_at,
                )
            )

        gross_margin = round(float(payment.amount) * self.default_gross_margin_pct, 2)
        outcome = store.create_outcome(
            Outcome(
                account_id=opportunity.account_id,
                opportunity_id=opportunity.id or 0,
                proposal_id=payment.proposal_id,
                status="won",
                revenue=float(payment.amount),
                gross_margin=gross_margin,
                summary=payload["summary"],
                metadata={
                    "simulated": False,
                    "fulfillment_status": "delivered",
                    "payment_event_id": payment.id,
                    "fulfillment_job_id": job.id,
                    "artifact_path": str(artifact_path),
                    "order_id": order_id,
                },
            )
        )

        self.telemetry.fulfillment_status_changed(
            account_id=opportunity.account_id,
            opportunity_id=opportunity.id or 0,
            outcome_id=0,
            status="payment_received",
            metadata={"payment_event_id": payment.id or 0, "order_id": order_id},
        )
        self.telemetry.fulfillment_status_changed(
            account_id=opportunity.account_id,
            opportunity_id=opportunity.id or 0,
            outcome_id=0,
            status="artifact_generated",
            metadata={
                "payment_event_id": payment.id or 0,
                "fulfillment_job_id": job.id or 0,
                "artifact_path": str(artifact_path),
                "order_id": order_id,
            },
        )
        self.telemetry.outcome_recorded(outcome)

        store.upsert_opportunity(
            Opportunity(
                id=opportunity.id,
                account_id=opportunity.account_id,
                name=opportunity.name,
                offer_name=opportunity.offer_name,
                stage="outcome",
                status="won",
                score=opportunity.score,
                score_breakdown=opportunity.score_breakdown,
                estimated_value=opportunity.estimated_value,
                currency=opportunity.currency,
                next_action="monitor_rerun",
                metadata={
                    **opportunity.metadata,
                    "payment_event_id": payment.id,
                    "fulfillment_job_id": job.id,
                    "latest_audit_bundle_id": delivered_bundle.id,
                    "latest_audit_artifact_path": str(artifact_path),
                    "order_id": order_id,
                    "proposal_id": payment.proposal_id,
                },
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
            )
        )
        return FulfillmentExecution(
            job=job,
            delivered_bundle=delivered_bundle,
            outcome=outcome,
            artifact_path=str(artifact_path),
        )

    def fulfill_order(self, order_id: str) -> FulfillmentExecution:
        if self.audit_store is None:
            raise ValueError("fulfill_order requires an audit-store-backed fulfillment service")
        order = self._get_paid_order(order_id)
        bundle = order.audit_bundle
        if bundle is None:
            raise ValueError(f"Order {order_id} is missing an audit bundle")
        prospect = bundle.prospect or order.prospect_profile
        if prospect is None:
            raise ValueError(f"Order {order_id} is missing a prospect profile")

        payment_events = self.audit_store.list_payment_events(order.order_id)
        paid_events = [event for event in payment_events if event.status == "paid"]
        if not paid_events:
            raise ValueError(f"Order {order_id} has no paid payment events recorded")

        job = self.audit_store.find_fulfillment_job(order.order_id, DEFAULT_FULFILLMENT_JOB_TYPE)
        now = utc_now()
        if job is None:
            job = self.audit_store.create_fulfillment_job(
                FulfillmentJob(
                    job_id=self.audit_store.next_fulfillment_job_id(),
                    order_id=order.order_id,
                    job_type=DEFAULT_FULFILLMENT_JOB_TYPE,
                    status="queued",
                    metadata={"source": "fulfillment_runner"},
                    created_at=now,
                    updated_at=now,
                )
            )

        artifact_dir = self.artifact_root / "audits" / _slugify(order.order_id)
        checklist_path = artifact_dir / "delivery_checklist.json"
        json_path = artifact_dir / "paid_audit.json"
        markdown_path = artifact_dir / "paid_audit.md"
        pack_path = artifact_dir / "delivery_pack.json"
        staged_monitor = self._ensure_staged_recurring_monitor(order)
        payload = self._build_paid_audit_payload(
            order=order,
            bundle=bundle,
            paid_events=paid_events,
            generated_at=now,
            recurring_monitor=staged_monitor,
        )
        checklist_payload = self._build_delivery_checklist_payload(order=order, generated_at=now)
        _write_json(checklist_path, checklist_payload)
        _write_json(json_path, payload)
        _write_markdown(markdown_path, self._render_paid_audit_markdown(payload))
        order_metadata = {
            **_merge_artifacts(
                _append_timeline_entries(
                    order.metadata,
                    _timeline_entry(
                        status="artifact_generated",
                        occurred_at=now,
                        detail="Customer delivery artifacts were rendered and attached to the paid order.",
                        artifact_paths=(str(json_path), str(markdown_path), str(checklist_path), str(pack_path)),
                    ),
                    _timeline_entry(
                        status="delivered",
                        occurred_at=now,
                        detail="The paid Website Growth Audit delivery pack is ready to ship.",
                        artifact_paths=(str(json_path), str(markdown_path), str(checklist_path), str(pack_path)),
                    ),
                ),
                delivery_checklist=str(checklist_path),
                delivery_json=str(json_path),
                delivery_markdown=str(markdown_path),
                delivery_pack=str(pack_path),
                delivery_artifact_paths=[str(json_path), str(markdown_path)],
            ),
            "delivery_checklist": list(_delivery_checklist()),
            "delivery_artifact_paths": [str(json_path), str(markdown_path)],
        }
        pack_payload = self._build_delivery_pack_payload(
            order=order,
            generated_at=now,
            delivery_payload=payload,
            checklist_path=str(checklist_path),
            audit_json_path=str(json_path),
            audit_markdown_path=str(markdown_path),
            timeline=_status_timeline(order_metadata),
            recurring_monitor=payload["recurring_monitor"],
        )
        _write_json(pack_path, pack_payload)

        updated_job = self.audit_store.update_fulfillment_job(
            job.job_id,
            status="completed",
            artifact_uri=str(json_path),
            metadata={
                **job.metadata,
                "artifact_paths": [
                    str(json_path),
                    str(markdown_path),
                    str(checklist_path),
                    str(pack_path),
                ],
                "delivery_checklist": list(_delivery_checklist()),
                "completed_at": now,
            },
            updated_at=now,
        )
        outcome = self._find_existing_revenue_outcome(order)
        outcome_created = False
        if outcome is None:
            if self.revenue_store is None or not order.crm_account_id or not order.crm_opportunity_id:
                raise ValueError(f"Order {order_id} is missing CRM context required for fulfillment revenue evidence")
            gross_margin = round(float(order.amount_total_usd) * self.default_gross_margin_pct, 2)
            outcome = self.revenue_store.create_outcome(
                Outcome(
                    account_id=order.crm_account_id,
                    opportunity_id=order.crm_opportunity_id,
                    proposal_id=order.crm_proposal_id,
                    status="won",
                    revenue=order.amount_total_usd,
                    gross_margin=gross_margin,
                    summary=payload["summary"],
                    metadata={
                        "revenue_audit_order_id": order.order_id,
                        "checkout_provider": "stripe",
                        "price_key": order.price_key,
                        "fulfillment_status": "delivered",
                        "delivery_artifact_paths": [str(json_path), str(markdown_path)],
                        "delivery_pack_path": str(pack_path),
                    },
                )
            )
            outcome_created = True
        updated_order = self.audit_store.update_order(
            order.order_id,
            fulfillment_status="delivered",
            crm_outcome_id=outcome.id,
            delivered_at=now,
            metadata=order_metadata,
            updated_at=now,
        )

        self._sync_crm_delivery(updated_order, artifact_paths=(str(json_path), str(markdown_path)))
        self._emit_fulfillment_status(
            updated_order,
            status="artifact_generated",
            metadata={
                "job_id": updated_job.job_id,
                "artifact_paths": [str(json_path), str(markdown_path)],
            },
        )
        if outcome_created:
            self.telemetry.outcome_recorded(outcome)
        else:
            self._emit_fulfillment_status(
                updated_order,
                status="delivered",
                metadata={
                    "job_id": updated_job.job_id,
                    "artifact_paths": [str(json_path), str(markdown_path)],
                },
            )
        return FulfillmentExecution(
            order=updated_order,
            job=updated_job,
            outcome=outcome,
            artifact_paths=(str(json_path), str(markdown_path)),
            delivery_checklist_path=str(checklist_path),
            delivery_pack_path=str(pack_path),
        )

    def run_monitor(
        self,
        order_id: str | int,
        *,
        current_bundle: AuditBundle | None = None,
        current_bundle_id: int | None = None,
    ) -> MonitorExecution:
        if current_bundle_id is not None or isinstance(order_id, int):
            if self.revenue_store is None:
                raise ValueError("RevenueStore-backed monitor flow is unavailable")
            opportunity_id = int(order_id)
            bundle_id = current_bundle_id
            if bundle_id is None:
                raise ValueError("current_bundle_id is required for RevenueStore monitor runs")
            return self._run_store_monitor(opportunity_id, bundle_id)

        if self.audit_store is None:
            raise ValueError("run_monitor requires an audit-store-backed fulfillment service")
        if current_bundle is None:
            raise ValueError("current_bundle is required for order-based monitor runs")
        order = self._get_paid_order(order_id)
        baseline_bundle = _bundle_from_metadata(order.metadata) or order.audit_bundle
        if baseline_bundle is None:
            raise ValueError(f"Order {order_id} is missing a baseline audit bundle")

        delta = self._build_delta_payload(order=order, baseline_bundle=baseline_bundle, current_bundle=current_bundle)
        artifact_dir = self.artifact_root / "monitor" / _slugify(order.order_id)
        json_path = artifact_dir / "monitor_delta.json"
        markdown_path = artifact_dir / "monitor_delta.md"
        _write_json(json_path, delta)
        _write_markdown(markdown_path, self._render_monitor_markdown(delta))

        now = utc_now()
        enrollment = self.audit_store.find_recurring_monitor_enrollment_by_audit_order(order.order_id)
        monitor_run = self.audit_store.create_monitor_run(
            MonitorRun(
                run_id=self.audit_store.next_monitor_run_id(),
                order_id=order.order_id,
                status="completed",
                baseline_bundle_id=baseline_bundle.bundle_id,
                current_bundle_id=current_bundle.bundle_id,
                recurring_monitor_enrollment_id=enrollment.enrollment_id if enrollment is not None else "",
                delta_summary=delta["summary"]["headline"],
                metadata={
                    "delta": delta,
                    "artifact_paths": [str(json_path), str(markdown_path)],
                    "current_bundle": contract_to_dict(current_bundle),
                },
                created_at=now,
                updated_at=now,
            )
        )
        if enrollment is not None and enrollment.status in {"active", "paused"}:
            self.audit_store.update_recurring_monitor_enrollment(
                enrollment.enrollment_id,
                latest_monitor_run_id=monitor_run.run_id,
                monitor_runs_completed=enrollment.monitor_runs_completed + 1,
                next_run_at=_add_days_iso(now, enrollment.cadence_days),
                metadata={
                    **enrollment.metadata,
                    "latest_monitor_artifact_paths": [str(json_path), str(markdown_path)],
                },
                updated_at=now,
            )
        updated_order = self.audit_store.update_order(
            order.order_id,
            metadata={
                **_merge_artifacts(
                    _append_timeline_entries(
                        order.metadata,
                        _timeline_entry(
                            status="monitor_rerun_completed",
                            occurred_at=now,
                            detail="The recurring-monitor delta was generated for the delivered audit.",
                            artifact_paths=(str(json_path), str(markdown_path)),
                            metadata={
                                "monitor_run_id": monitor_run.run_id,
                                "headline": delta["summary"]["headline"],
                            },
                        ),
                    ),
                    monitor_json=str(json_path),
                    monitor_markdown=str(markdown_path),
                    latest_monitor_artifact_paths=[str(json_path), str(markdown_path)],
                ),
                "latest_monitor_run_id": monitor_run.run_id,
                "latest_monitor_bundle": contract_to_dict(current_bundle),
                "latest_monitor_artifact_paths": [str(json_path), str(markdown_path)],
            },
            updated_at=now,
        )
        self._sync_crm_monitor(updated_order, artifact_paths=(str(json_path), str(markdown_path)))
        self._emit_fulfillment_status(
            updated_order,
            status="monitor_rerun_completed",
            metadata={
                "monitor_run_id": monitor_run.run_id,
                "artifact_paths": [str(json_path), str(markdown_path)],
                "delta": delta["summary"],
            },
        )
        return MonitorExecution(
            order=updated_order,
            monitor_run=monitor_run,
            artifact_paths=(str(json_path), str(markdown_path)),
        )

    def _run_store_monitor(self, opportunity_id: int, current_bundle_id: int) -> MonitorExecution:
        assert self.revenue_store is not None
        store = self.revenue_store
        opportunity = store.get_opportunity(opportunity_id)
        if opportunity is None:
            raise ValueError(f"Unknown opportunity: {opportunity_id}")
        current_bundle = store.get_audit_bundle(current_bundle_id)
        if current_bundle is None:
            raise ValueError(f"Unknown audit bundle: {current_bundle_id}")
        baseline_bundle = self._resolve_store_bundle(opportunity_id, exclude_bundle_id=current_bundle_id)
        if baseline_bundle is None:
            raise ValueError(f"Opportunity {opportunity_id} is missing a prior audit bundle")

        baseline_issues = store.list_issue_evidence(bundle_id=baseline_bundle.id or 0)
        current_issues = store.list_issue_evidence(bundle_id=current_bundle.id or 0)
        payload = self._build_store_monitor_delta_payload(
            opportunity=opportunity,
            baseline_bundle=baseline_bundle,
            current_bundle=current_bundle,
            baseline_issues=baseline_issues,
            current_issues=current_issues,
        )
        started_at = utc_now()
        artifact_dir = self.artifact_root / "monitor" / f"opportunity-{opportunity_id}"
        artifact_path = artifact_dir / f"monitor_delta_{started_at.replace(':', '').replace('+00:00', 'Z')}.json"
        _write_json(artifact_path, payload)
        monitor_run = store.create_monitor_run(
            StoreMonitorRun(
                opportunity_id=opportunity_id,
                fulfillment_job_id=int(opportunity.metadata.get("fulfillment_job_id", 0) or 0) or None,
                baseline_bundle_id=baseline_bundle.id,
                current_bundle_id=current_bundle.id,
                status="completed",
                delta_artifact_path=str(artifact_path),
                new_issue_count=payload["summary"]["new_issue_count"],
                resolved_issue_count=payload["summary"]["resolved_issue_count"],
                persistent_issue_count=payload["summary"]["persistent_issue_count"],
                metadata={"severity_changes": payload["severity_changes"]},
                started_at=started_at,
                completed_at=started_at,
            )
        )
        self.telemetry.fulfillment_status_changed(
            account_id=opportunity.account_id,
            opportunity_id=opportunity_id,
            outcome_id=0,
            status="monitor_rerun_completed",
            metadata={
                "monitor_run_id": monitor_run.id or 0,
                "artifact_path": str(artifact_path),
                "delta": payload["summary"],
            },
        )
        return MonitorExecution(monitor_run=monitor_run, artifact_path=str(artifact_path))

    def _resolve_store_bundle(
        self,
        opportunity_id: int,
        *,
        exclude_bundle_id: int | None,
    ) -> StoreAuditBundle | None:
        assert self.revenue_store is not None
        bundles = self.revenue_store.list_audit_bundles(opportunity_id=opportunity_id)
        candidates = [
            bundle for bundle in bundles if bundle.id is not None and bundle.id != exclude_bundle_id
        ]
        return candidates[-1] if candidates else None

    def _build_store_paid_audit_payload(
        self,
        *,
        order_id: str,
        prospect: Any,
        payment: Any,
        baseline_bundle: Any,
        baseline_issues: list[Any],
        generated_at: str,
    ) -> dict[str, Any]:
        ordered_issues = sorted(
            baseline_issues,
            key=lambda issue: (_severity_value(issue.severity), float(issue.impact_score), issue.issue_key),
            reverse=True,
        )
        return {
            "artifact": "revenue_audit_delivery",
            "generated_at": generated_at,
            "order_id": order_id,
            "summary": baseline_bundle.summary or f"{len(ordered_issues)} findings delivered.",
            "payment": {
                "id": payment.id,
                "status": payment.status,
                "amount": float(payment.amount),
                "currency": payment.currency,
                "order_id": order_id,
            },
            "prospect": contract_to_dict(prospect),
            "bundle": {
                "bundle_id": baseline_bundle.id,
                "bundle_kind": baseline_bundle.bundle_kind,
                "summary": baseline_bundle.summary,
                "score": float(baseline_bundle.score),
                "issue_count": len(ordered_issues),
            },
            "issues": [
                {
                    "id": issue.id,
                    "issue_key": issue.issue_key,
                    "title": issue.title,
                    "summary": issue.summary,
                    "severity": issue.severity,
                    "confidence": float(issue.confidence),
                    "impact_score": float(issue.impact_score),
                    "source_url": issue.source_url,
                    "evidence_text": issue.evidence_text,
                }
                for issue in ordered_issues
            ],
        }

    def _build_store_monitor_delta_payload(
        self,
        *,
        opportunity: Opportunity,
        baseline_bundle: Any,
        current_bundle: Any,
        baseline_issues: list[Any],
        current_issues: list[Any],
    ) -> dict[str, Any]:
        baseline_map = {_issue_key(issue): issue for issue in baseline_issues}
        current_map = {_issue_key(issue): issue for issue in current_issues}
        new_keys = sorted(set(current_map) - set(baseline_map))
        resolved_keys = sorted(set(baseline_map) - set(current_map))
        persistent_keys = sorted(set(baseline_map) & set(current_map))
        severity_changes: list[dict[str, Any]] = []
        for key in persistent_keys:
            old_issue = baseline_map[key]
            new_issue = current_map[key]
            old_score = _severity_value(old_issue.severity)
            new_score = _severity_value(new_issue.severity)
            if new_score == old_score:
                continue
            severity_changes.append(
                {
                    "issue_key": key,
                    "from": old_issue.severity,
                    "to": new_issue.severity,
                    "direction": "worsened" if new_score > old_score else "improved",
                }
            )
        payload = {
            "artifact": "revenue_audit_monitor_delta",
            "generated_at": utc_now(),
            "opportunity_id": opportunity.id,
            "baseline_bundle_id": baseline_bundle.id,
            "current_bundle_id": current_bundle.id,
            "summary": {
                "new_issue_count": len(new_keys),
                "resolved_issue_count": len(resolved_keys),
                "persistent_issue_count": len(persistent_keys),
            },
            "new_issues": [contract_to_dict(current_map[key]) for key in new_keys],
            "resolved_issues": [contract_to_dict(baseline_map[key]) for key in resolved_keys],
            "severity_changes": severity_changes,
        }
        return payload

    def _get_paid_order(self, order_id: str) -> AuditOrder:
        order = self.audit_store.get_order(order_id)
        if order is None:
            raise ValueError(f"Unknown revenue audit order: {order_id}")
        if order.status not in PAID_ORDER_STATUSES:
            raise ValueError(f"Order {order_id} is not paid: {order.status}")
        return order

    def _build_paid_audit_payload(
        self,
        *,
        order: AuditOrder,
        bundle: AuditBundle,
        paid_events: list[Any],
        generated_at: str,
        recurring_monitor: RecurringMonitorEnrollment | None,
    ) -> dict[str, Any]:
        prospect = bundle.prospect or order.prospect_profile
        severity_counts: dict[str, int] = {}
        for issue in bundle.issues:
            severity = str(issue.severity or "medium").strip().lower()
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        total_paid = round(sum(float(event.amount_total_usd) for event in paid_events), 2)
        return {
            "artifact": "revenue_audit_delivery",
            "generated_at": generated_at,
            "order_id": order.order_id,
            "offer_slug": order.offer_slug,
            "summary": bundle.summary or f"{len(bundle.issues)} deterministic findings delivered.",
            "customer": {
                "business_name": order.business_name,
                "website_url": order.website_url,
                "customer_email": order.customer_email,
            },
            "prospect": contract_to_dict(prospect) if prospect is not None else {},
            "audit_bundle": contract_to_dict(bundle),
            "payment": {
                "paid_events": [contract_to_dict(event) for event in paid_events],
                "payments_collected_usd": total_paid,
            },
            "delivery": {
                "checklist": list(_delivery_checklist()),
                "severity_counts": severity_counts,
            },
            "recurring_monitor": self._recurring_monitor_payload(order=order, enrollment=recurring_monitor),
        }

    def _build_delivery_checklist_payload(
        self,
        *,
        order: AuditOrder,
        generated_at: str,
    ) -> dict[str, Any]:
        return {
            "artifact": "revenue_audit_delivery_checklist",
            "generated_at": generated_at,
            "order_id": order.order_id,
            "customer": {
                "business_name": order.business_name,
                "website_url": order.website_url,
                "customer_email": order.customer_email,
            },
            "checklist": list(_delivery_checklist()),
        }

    def _build_delivery_pack_payload(
        self,
        *,
        order: AuditOrder,
        generated_at: str,
        delivery_payload: dict[str, Any],
        checklist_path: str,
        audit_json_path: str,
        audit_markdown_path: str,
        timeline: list[dict[str, Any]],
        recurring_monitor: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "artifact": "revenue_audit_delivery_pack",
            "generated_at": generated_at,
            "order_id": order.order_id,
            "summary": delivery_payload["summary"],
            "customer_delivery": {
                "primary_artifact_path": audit_markdown_path,
                "machine_readable_artifact_path": audit_json_path,
                "ship_status": "ready",
            },
            "checklist_artifact_path": checklist_path,
            "delivery_artifact_paths": [audit_json_path, audit_markdown_path],
            "timeline": timeline,
            "monitor_contract": {
                "status": recurring_monitor.get("status", "ready_for_rerun"),
                "artifact_kind": "revenue_audit_monitor_delta",
                "reuse_surface": "recurring_monitor",
            },
            "recurring_monitor": recurring_monitor,
        }

    def _render_paid_audit_markdown(self, payload: dict[str, Any]) -> list[str]:
        issues = payload["audit_bundle"].get("issues", [])
        recurring_monitor = payload.get("recurring_monitor", {})
        lines = [
            "# Website Growth Audit",
            "",
            f"Order: `{payload['order_id']}`",
            f"Generated: `{payload['generated_at']}`",
            "",
            payload["summary"],
            "",
            "## Delivery Checklist",
        ]
        for item in payload["delivery"]["checklist"]:
            lines.append(f"- {item['step']}: {item['status']}")
        lines.extend(["", "## Findings"])
        for issue in issues:
            lines.append(
                f"- [{issue.get('severity', 'medium')}] {issue.get('summary', '')} ({issue.get('detector_key', '')})"
            )
        lines.extend(
            [
                "",
                "## Recurring Monitor",
                f"- Status: {recurring_monitor.get('status', 'staged')}",
                f"- Monthly price: ${recurring_monitor.get('offer', {}).get('monthly_amount_usd', 0):.2f}",
                f"- Cadence: every {recurring_monitor.get('offer', {}).get('cadence_days', 30)} days",
            ]
        )
        return lines

    def _build_delta_payload(
        self,
        *,
        order: AuditOrder,
        baseline_bundle: AuditBundle,
        current_bundle: AuditBundle,
    ) -> dict[str, Any]:
        baseline_map = {_issue_key(issue): issue for issue in baseline_bundle.issues}
        current_map = {_issue_key(issue): issue for issue in current_bundle.issues}
        new_keys = sorted(set(current_map) - set(baseline_map))
        resolved_keys = sorted(set(baseline_map) - set(current_map))
        persistent_keys = sorted(set(baseline_map) & set(current_map))

        severity_changes: list[dict[str, Any]] = []
        for key in persistent_keys:
            previous = baseline_map[key]
            current = current_map[key]
            before = _severity_value(previous.severity)
            after = _severity_value(current.severity)
            if before != after:
                severity_changes.append(
                    {
                        "issue_id": key,
                        "summary": current.summary,
                        "from": previous.severity,
                        "to": current.severity,
                        "direction": "worsened" if after > before else "improved",
                    }
                )

        summary = {
            "headline": (
                f"new={len(new_keys)} resolved={len(resolved_keys)} "
                f"persistent={len(persistent_keys)} severity_changes={len(severity_changes)}"
            ),
            "new_issue_count": len(new_keys),
            "resolved_issue_count": len(resolved_keys),
            "persistent_issue_count": len(persistent_keys),
            "severity_change_count": len(severity_changes),
        }
        return {
            "artifact": "revenue_audit_monitor_delta",
            "generated_at": utc_now(),
            "order_id": order.order_id,
            "baseline_bundle_id": baseline_bundle.bundle_id,
            "current_bundle_id": current_bundle.bundle_id,
            "summary": summary,
            "new_issues": [contract_to_dict(current_map[key]) for key in new_keys],
            "resolved_issues": [contract_to_dict(baseline_map[key]) for key in resolved_keys],
            "persistent_issues": [contract_to_dict(current_map[key]) for key in persistent_keys],
            "severity_changes": severity_changes,
        }

    def _render_monitor_markdown(self, payload: dict[str, Any]) -> list[str]:
        lines = [
            "# Website Growth Audit Monitor Delta",
            "",
            f"Order: `{payload['order_id']}`",
            f"Generated: `{payload['generated_at']}`",
            "",
            payload["summary"]["headline"],
            "",
            "## New Issues",
        ]
        for issue in payload["new_issues"]:
            lines.append(f"- {issue.get('summary', '')}")
        lines.extend(["", "## Resolved Issues"])
        for issue in payload["resolved_issues"]:
            lines.append(f"- {issue.get('summary', '')}")
        lines.extend(["", "## Severity Changes"])
        for issue in payload["severity_changes"]:
            lines.append(f"- {issue['issue_id']}: {issue['from']} -> {issue['to']} ({issue['direction']})")
        return lines

    def _find_existing_revenue_outcome(self, order: AuditOrder) -> Outcome | None:
        if self.revenue_store is None or not order.crm_opportunity_id:
            return None
        outcomes = self.revenue_store.list_outcomes(opportunity_id=order.crm_opportunity_id)
        for candidate in reversed(outcomes):
            if str(candidate.status).strip().lower() != "won":
                continue
            if float(candidate.revenue) <= 0.0:
                continue
            if str(candidate.metadata.get("revenue_audit_order_id", "")).strip() != order.order_id:
                continue
            return candidate
        return None

    def _emit_fulfillment_status(self, order: AuditOrder, *, status: str, metadata: dict[str, Any]) -> None:
        if not order.crm_account_id or not order.crm_opportunity_id:
            return
        self.telemetry.fulfillment_status_changed(
            account_id=order.crm_account_id,
            opportunity_id=order.crm_opportunity_id,
            outcome_id=order.crm_outcome_id or 0,
            status=status,
            revenue=order.amount_total_usd,
            gross_margin=0.0,
            is_simulated=False,
            metadata={"revenue_audit_order_id": order.order_id, **metadata},
        )

    def _sync_crm_delivery(self, order: AuditOrder, *, artifact_paths: tuple[str, ...]) -> None:
        if not order.crm_opportunity_id:
            return
        opportunity = self.revenue_store.get_opportunity(order.crm_opportunity_id)
        if opportunity is None:
            return
        metadata = dict(opportunity.metadata)
        metadata.update(
            {
                "revenue_audit_order_id": order.order_id,
                "delivery_artifact_paths": list(artifact_paths),
            }
        )
        self.revenue_store.upsert_opportunity(
            Opportunity(
                id=opportunity.id,
                account_id=opportunity.account_id,
                name=opportunity.name,
                offer_name=opportunity.offer_name,
                stage="outcome",
                status="won",
                score=opportunity.score,
                score_breakdown=opportunity.score_breakdown,
                estimated_value=opportunity.estimated_value,
                currency=opportunity.currency,
                next_action="schedule_monitor",
                metadata=metadata,
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
            )
        )

    def _sync_crm_monitor(self, order: AuditOrder, *, artifact_paths: tuple[str, ...]) -> None:
        if not order.crm_opportunity_id:
            return
        opportunity = self.revenue_store.get_opportunity(order.crm_opportunity_id)
        if opportunity is None:
            return
        metadata = dict(opportunity.metadata)
        metadata.update(
            {
                "revenue_audit_order_id": order.order_id,
                "latest_monitor_artifact_paths": list(artifact_paths),
            }
        )
        self.revenue_store.upsert_opportunity(
            Opportunity(
                id=opportunity.id,
                account_id=opportunity.account_id,
                name=opportunity.name,
                offer_name=opportunity.offer_name,
                stage=opportunity.stage,
                status=opportunity.status,
                score=opportunity.score,
                score_breakdown=opportunity.score_breakdown,
                estimated_value=opportunity.estimated_value,
                currency=opportunity.currency,
                next_action="review_monitor_delta",
                metadata=metadata,
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
            )
        )
