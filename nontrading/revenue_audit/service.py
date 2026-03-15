"""Checkout and webhook service for the JJ-N website growth audit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import urlparse

from nontrading.config import is_placeholder_domain
from nontrading.models import Account, Opportunity, Proposal
from nontrading.offers.website_growth_audit import (
    website_growth_audit_offer,
    website_growth_audit_recurring_monitor_offer,
)
from nontrading.revenue_audit.config import RevenueAuditSettings
from nontrading.revenue_audit.contracts import (
    AuditOrder,
    CheckoutSession,
    CreateCheckoutRequest,
    FulfillmentJob,
    PaymentEvent,
    ProspectProfile,
    RecurringMonitorEnrollment,
    contract_to_dict,
    utc_now,
)
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.revenue_audit.stripe import (
    StripeCheckoutClient,
    StripeClientError,
    WebhookVerificationError,
    verify_webhook_signature,
)
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry

UTC = timezone.utc
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOCAL_REDIRECT_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _iso_from_unix(timestamp: int | str | None) -> str | None:
    if timestamp in {None, ""}:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=UTC).replace(microsecond=0).isoformat()


def _amount_usd(amount_minor_units: int | float | str | None, currency: str) -> float:
    if str(currency or "USD").strip().upper() != "USD":
        raise ValueError(f"Unsupported currency for revenue_audit checkout: {currency}")
    if amount_minor_units in {None, ""}:
        return 0.0
    return round(float(amount_minor_units) / 100.0, 2)


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.hostname or ""
    return host.lower()


def _mask_secret(secret: str) -> str:
    text = str(secret or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _url_is_configured(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if not parsed.scheme or not host:
        return False
    if parsed.scheme == "https":
        return not is_placeholder_domain(host)
    return parsed.scheme == "http" and host in LOCAL_REDIRECT_HOSTS


def _website_url_is_valid(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)


def _metadata_from_event_object(data_object: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(data_object.get("metadata", {}) or {})
    subscription_details = data_object.get("subscription_details")
    if isinstance(subscription_details, dict):
        subscription_metadata = dict(subscription_details.get("metadata", {}) or {})
        for key, value in subscription_metadata.items():
            metadata.setdefault(str(key), value)
    return metadata


def _add_days_iso(timestamp: str | None, days: int) -> str | None:
    if not timestamp:
        return None
    parsed = timestamp.strip()
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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "status": str(status).strip(),
        "occurred_at": str(occurred_at).strip(),
        "detail": str(detail).strip(),
    }
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


class RevenueAuditCheckoutService:
    def __init__(
        self,
        settings: RevenueAuditSettings,
        *,
        audit_store: RevenueAuditStore | None = None,
        revenue_store: RevenueStore | None = None,
        telemetry: NonTradingTelemetry | None = None,
        stripe_client: StripeCheckoutClient | None = None,
    ) -> None:
        self.settings = settings
        self.settings.ensure_paths()
        self.audit_store = audit_store or RevenueAuditStore(self.settings.db_path)
        self.revenue_store = revenue_store or RevenueStore(self.settings.db_path)
        self.telemetry = telemetry or NonTradingTelemetry(self.revenue_store)
        self.stripe_client = stripe_client or StripeCheckoutClient(
            self.settings.stripe_secret_key,
            api_base=self.settings.stripe_api_base,
        )
        self.offer = website_growth_audit_offer()
        self.recurring_monitor_offer = website_growth_audit_recurring_monitor_offer()

    def _offer_context(self, offer_slug: str) -> dict[str, Any]:
        normalized = str(offer_slug or self.settings.offer_slug).strip().lower()
        if normalized == self.recurring_monitor_offer.slug:
            return {
                "offer": self.recurring_monitor_offer,
                "pricing": self.settings.recurring_monitor_pricing,
                "success_url": self.settings.recurring_monitor_success_url,
                "cancel_url": self.settings.recurring_monitor_cancel_url,
                "live_offer_url": self.settings.recurring_monitor_live_offer_url,
                "checkout_mode": "subscription",
                "billing_interval": self.recurring_monitor_offer.billing_interval,
            }
        return {
            "offer": self.offer,
            "pricing": self.settings.pricing,
            "success_url": self.settings.stripe_success_url,
            "cancel_url": self.settings.stripe_cancel_url,
            "live_offer_url": self.settings.live_offer_url,
            "checkout_mode": "payment",
            "billing_interval": None,
        }

    def _offer_checkout_payload(self, *, offer_slug: str, checklist: dict[str, Any]) -> dict[str, Any]:
        context = self._offer_context(offer_slug)
        offer = context["offer"]
        price_options = list(context["pricing"])
        price_low = min(option.amount_usd for option in price_options)
        price_high = max(option.amount_usd for option in price_options)
        payload = {
            "offer": {
                "name": offer.name,
                "slug": offer.slug,
                "description": offer.description,
                "fulfillment_type": offer.fulfillment_type,
                "price_range_usd": {
                    "low": price_low,
                    "high": price_high,
                },
            },
            "pricing": {
                "currency": self.settings.currency,
                "options": [contract_to_dict(option) for option in price_options],
            },
            "checkout": {
                "provider": "stripe",
                "mode": context["checkout_mode"],
                "enabled": checklist["summary"]["checkout_ready"],
                "launch_ready": checklist["launch_ready"],
                "live_offer_url": context["live_offer_url"],
                "success_url_template": context["success_url"],
                "cancel_url": context["cancel_url"],
                "launch_blockers": checklist["blocking_requirements"],
            },
        }
        if hasattr(offer, "delivery_days"):
            payload["offer"]["delivery_days"] = offer.delivery_days
        if hasattr(offer, "billing_interval"):
            payload["offer"]["billing_interval"] = offer.billing_interval
            payload["offer"]["cadence_days"] = offer.cadence_days
            payload["offer"]["parent_offer_slug"] = offer.parent_offer_slug
            payload["offer"]["deliverables"] = list(getattr(offer, "deliverables", ()))
        return payload

    def _launch_checklist_payload_for_offer(
        self,
        *,
        offer_slug: str,
        live_offer_url: str,
        success_url: str,
        cancel_url: str,
        success_env: str,
        cancel_env: str,
    ) -> dict[str, Any]:
        requirements = [
            {
                "key": "public_base_url",
                "label": "Public offer base URL",
                "env": "JJ_N_WEBSITE_GROWTH_AUDIT_PUBLIC_BASE_URL or JJ_REVENUE_PUBLIC_BASE_URL",
                "ready": self.settings.public_base_url_ready,
                "current_value": self.settings.public_base_url,
                "detail": "Must point at the public hub host that serves the offer and success/cancel pages.",
            },
            {
                "key": "stripe_secret_key",
                "label": "Stripe secret key",
                "env": "STRIPE_SECRET_KEY",
                "ready": bool(self.settings.stripe_secret_key),
                "current_value": _mask_secret(self.settings.stripe_secret_key),
                "detail": "Required to create hosted Stripe Checkout sessions.",
            },
            {
                "key": "stripe_webhook_secret",
                "label": "Stripe webhook secret",
                "env": "STRIPE_WEBHOOK_SECRET",
                "ready": bool(self.settings.stripe_webhook_secret),
                "current_value": _mask_secret(self.settings.stripe_webhook_secret),
                "detail": "Required to verify Stripe webhook signatures before marking orders paid.",
            },
            {
                "key": "success_url",
                "label": "Checkout success URL",
                "env": success_env,
                "ready": _url_is_configured(success_url),
                "current_value": success_url,
                "detail": "Must be an absolute HTTPS URL on an allowed host and include {CHECKOUT_SESSION_ID}.",
            },
            {
                "key": "cancel_url",
                "label": "Checkout cancel URL",
                "env": cancel_env,
                "ready": _url_is_configured(cancel_url),
                "current_value": cancel_url,
                "detail": "Must be an absolute HTTPS URL on an allowed host.",
            },
        ]
        checkout_ready = all(
            item["ready"]
            for item in requirements
            if item["key"] in {"public_base_url", "stripe_secret_key", "success_url", "cancel_url"}
        )
        summary = {
            "offer_surface_ready": self.settings.public_base_url_ready,
            "checkout_ready": checkout_ready,
            "webhook_ready": bool(self.settings.stripe_webhook_secret),
            "success_url_ready": _url_is_configured(success_url),
            "cancel_url_ready": _url_is_configured(cancel_url),
            "order_lookup_ready": True,
        }
        blocking = [item["key"] for item in requirements if not item["ready"]]
        return {
            "offer_slug": offer_slug,
            "live_offer_url": live_offer_url,
            "launch_ready": summary["checkout_ready"] and summary["webhook_ready"],
            "blocking_requirements": blocking,
            "summary": summary,
            "requirements": requirements,
        }

    def offer_payload(self) -> dict[str, Any]:
        checklist = self.launch_checklist_payload()
        payload = {
            **self._offer_checkout_payload(offer_slug=self.offer.slug, checklist=checklist),
            "order_lookup": {
                "by_order_id": "/v1/nontrading/orders/{order_id}",
                "by_session_id": "/v1/nontrading/orders/lookup?session_id={CHECKOUT_SESSION_ID}",
                "by_payment_intent": "/v1/nontrading/orders/lookup?payment_intent={PAYMENT_INTENT_ID}",
            },
            "launch_checklist": checklist,
        }
        payload["expansion_offer"] = self.recurring_monitor_offer_payload()
        return payload

    def recurring_monitor_offer_payload(self) -> dict[str, Any]:
        checklist = self.recurring_monitor_launch_checklist_payload()
        payload = self._offer_checkout_payload(
            offer_slug=self.recurring_monitor_offer.slug,
            checklist=checklist,
        )
        payload["checkout"]["required_fields"] = {
            "offer_slug": self.recurring_monitor_offer.slug,
            "source_order_id": "order_id_from_paid_audit",
        }
        payload["lifecycle"] = {
            "attached_to_offer_slug": self.offer.slug,
            "status_flow": [
                "staged",
                "checkout_pending",
                "active",
                "paused",
                "canceled",
                "churned",
                "refunded",
            ],
            "delta_report_artifact": "revenue_audit_monitor_delta",
        }
        payload["launch_checklist"] = checklist
        return payload

    def launch_checklist_payload(self) -> dict[str, Any]:
        return self._launch_checklist_payload_for_offer(
            offer_slug=self.settings.offer_slug,
            live_offer_url=self.settings.live_offer_url,
            success_url=self.settings.stripe_success_url,
            cancel_url=self.settings.stripe_cancel_url,
            success_env="JJ_N_WEBSITE_GROWTH_AUDIT_SUCCESS_URL",
            cancel_env="JJ_N_WEBSITE_GROWTH_AUDIT_CANCEL_URL",
        )

    def recurring_monitor_launch_checklist_payload(self) -> dict[str, Any]:
        return self._launch_checklist_payload_for_offer(
            offer_slug=self.settings.recurring_monitor_offer_slug,
            live_offer_url=self.settings.recurring_monitor_live_offer_url,
            success_url=self.settings.recurring_monitor_success_url,
            cancel_url=self.settings.recurring_monitor_cancel_url,
            success_env="JJ_N_WEBSITE_GROWTH_MONITOR_SUCCESS_URL",
            cancel_env="JJ_N_WEBSITE_GROWTH_MONITOR_CANCEL_URL",
        )

    def create_checkout_session(self, request: CreateCheckoutRequest) -> dict[str, Any]:
        if not request.customer_email:
            raise ValueError("customer_email is required")
        if not EMAIL_RE.match(request.customer_email):
            raise ValueError("customer_email must be a valid email address")
        offer_context = self._offer_context(request.offer_slug)
        offer = offer_context["offer"]
        source_order = None
        if request.offer_slug == self.recurring_monitor_offer.slug:
            if not request.source_order_id:
                raise ValueError("source_order_id is required for recurring monitor checkout")
            source_order = self.audit_store.get_order(request.source_order_id)
            if source_order is None:
                raise ValueError(f"Unknown source_order_id: {request.source_order_id}")
            if str(source_order.status).strip().lower() != "paid":
                raise ValueError("source_order_id must reference a paid audit order")
        if not request.business_name and not request.website_url and source_order is None:
            raise ValueError("business_name or website_url is required")
        if request.website_url and not _website_url_is_valid(request.website_url):
            raise ValueError("website_url must be an absolute http(s) URL")

        try:
            price = self.settings.price_option(request.price_key, offer_slug=request.offer_slug)
        except KeyError as exc:
            raise ValueError(f"Unknown price key: {request.price_key}") from exc
        success_url = self._resolve_redirect_url(request.success_url, kind="success", offer_slug=request.offer_slug)
        cancel_url = self._resolve_redirect_url(request.cancel_url, kind="cancel", offer_slug=request.offer_slug)
        business_name = request.business_name or (source_order.business_name if source_order is not None else "")
        website_url = request.website_url or (source_order.website_url if source_order is not None else "")
        prospect_profile = request.prospect_profile or ProspectProfile(
            business_name=business_name or request.customer_name or "Website Growth Audit Customer",
            website_url=website_url,
            contact_email=request.customer_email,
            contact_name=request.customer_name,
            metadata={
                "source": "checkout",
                **({"source_order_id": request.source_order_id} if request.source_order_id else {}),
            },
        )
        order_metadata = {
            **request.metadata,
            "price_label": price.label,
            "price_description": price.description,
        }
        if source_order is not None:
            order_metadata.update(
                {
                    "source_order_id": source_order.order_id,
                    "parent_offer_slug": source_order.offer_slug,
                    "parent_customer_email": source_order.customer_email,
                }
            )
        order = self.audit_store.create_order(
            AuditOrder(
                order_id=self.audit_store.next_order_id(),
                offer_slug=offer.slug,
                price_key=price.key,
                amount_subtotal_usd=price.amount_usd,
                amount_total_usd=price.amount_usd,
                currency=self.settings.currency,
                status="checkout_pending",
                fulfillment_status="enrollment_pending" if offer.slug == self.recurring_monitor_offer.slug else "not_started",
                customer_email=request.customer_email,
                customer_name=request.customer_name,
                business_name=business_name or prospect_profile.business_name,
                website_url=website_url or prospect_profile.website_url,
                prospect_profile=prospect_profile,
                audit_bundle=request.audit_bundle,
                metadata=order_metadata,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        try:
            stripe_session = self.stripe_client.create_checkout_session(
                amount_cents=price.amount_cents,
                currency=self.settings.currency,
                success_url=success_url,
                cancel_url=cancel_url,
                mode=str(offer_context["checkout_mode"]),
                billing_interval=offer_context["billing_interval"],
                customer_email=order.customer_email,
                client_reference_id=order.order_id,
                metadata={
                    "order_id": order.order_id,
                    "offer_slug": order.offer_slug,
                    "price_key": order.price_key,
                    "business_name": order.business_name,
                    "website_url": order.website_url,
                    "source_order_id": request.source_order_id,
                },
                subscription_metadata={
                    "order_id": order.order_id,
                    "offer_slug": order.offer_slug,
                    "source_order_id": request.source_order_id,
                },
                line_item_name=f"{offer.name} - {price.label}",
                line_item_description=price.description or offer.description,
            )
        except StripeClientError:
            self.audit_store.update_order(order.order_id, status="checkout_error", updated_at=utc_now())
            raise

        checkout_session = self.audit_store.create_checkout_session(
            CheckoutSession(
                session_id=self.audit_store.next_checkout_session_id(),
                order_id=order.order_id,
                provider="stripe",
                provider_session_id=stripe_session["id"],
                provider_payment_intent_id=stripe_session["payment_intent"],
                status=stripe_session.get("status") or "created",
                hosted_url=stripe_session["url"],
                amount_subtotal_usd=order.amount_subtotal_usd,
                amount_total_usd=order.amount_total_usd,
                currency=order.currency,
                customer_email=order.customer_email,
                expires_at=stripe_session.get("expires_at"),
                metadata=stripe_session.get("raw", {}),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        if source_order is not None:
            self._stage_or_update_recurring_monitor_enrollment(
                audit_order=source_order,
                monitor_order=order,
                checkout_session=checkout_session,
                price_key=price.key,
                monthly_amount_usd=price.amount_usd,
                status="checkout_pending",
            )
        return {
            "order": contract_to_dict(self.audit_store.get_order(order.order_id) or order),
            "checkout_session": contract_to_dict(checkout_session),
            "recurring_monitor": (
                self._recurring_monitor_payload_for_order(source_order)
                if source_order is not None
                else self._recurring_monitor_payload_for_order(order)
            ),
        }

    def get_order_payload(
        self,
        order_id: str | None = None,
        *,
        provider_session_id: str | None = None,
        provider_payment_intent_id: str | None = None,
    ) -> dict[str, Any]:
        order = self._lookup_order(
            order_id=order_id,
            provider_session_id=provider_session_id,
            provider_payment_intent_id=provider_payment_intent_id,
        )
        if order is None:
            raise LookupError("Unknown revenue audit order lookup")
        checkout_session = self.audit_store.get_checkout_session_by_order(order.order_id)
        payment_events = self.audit_store.list_payment_events(order.order_id)
        fulfillment_jobs = self.audit_store.list_fulfillment_jobs(order.order_id)
        monitor_runs = self.audit_store.list_monitor_runs(order.order_id)
        return {
            "order": contract_to_dict(order),
            "checkout_session": contract_to_dict(checkout_session) if checkout_session else None,
            "payment_events": [contract_to_dict(event) for event in payment_events],
            "fulfillment_jobs": [contract_to_dict(job) for job in fulfillment_jobs],
            "monitor_runs": [contract_to_dict(run) for run in monitor_runs],
            "timeline": _status_timeline(order.metadata),
            "artifacts": _artifact_catalog(order.metadata),
            "recurring_monitor": self._recurring_monitor_payload_for_order(order),
        }

    def _recurring_monitor_payload_for_order(self, order: AuditOrder) -> dict[str, Any]:
        if order.offer_slug == self.recurring_monitor_offer.slug:
            audit_order_id = str(order.metadata.get("source_order_id", "")).strip()
        else:
            audit_order_id = order.order_id
        enrollment = self.audit_store.find_recurring_monitor_enrollment_by_audit_order(audit_order_id)
        monitor_order_id = ""
        if enrollment is not None:
            candidate_monitor_order_id = str(enrollment.monitor_order_id).strip()
            if candidate_monitor_order_id and candidate_monitor_order_id != audit_order_id:
                monitor_order_id = candidate_monitor_order_id
        related_order = (
            self.audit_store.get_order(monitor_order_id)
            if monitor_order_id
            else None
        )
        payload = {
            "offer": self.recurring_monitor_offer_payload(),
            "enrollment": contract_to_dict(enrollment) if enrollment is not None else None,
            "related_order": contract_to_dict(related_order) if related_order is not None else None,
            "eligible": str(order.status).strip().lower() == "paid" and order.offer_slug != self.recurring_monitor_offer.slug,
            "checkout_request_template": {
                "offer_slug": self.recurring_monitor_offer.slug,
                "source_order_id": audit_order_id,
            },
        }
        if order.offer_slug == self.recurring_monitor_offer.slug:
            payload["source_order_id"] = audit_order_id
        return payload

    def _stage_or_update_recurring_monitor_enrollment(
        self,
        *,
        audit_order: AuditOrder,
        monitor_order: AuditOrder | None = None,
        checkout_session: CheckoutSession | None = None,
        price_key: str = "",
        monthly_amount_usd: float | None = None,
        status: str = "staged",
    ) -> RecurringMonitorEnrollment:
        existing = self.audit_store.find_recurring_monitor_enrollment_by_audit_order(audit_order.order_id)
        amount = (
            round(float(monthly_amount_usd), 2)
            if monthly_amount_usd is not None
            else self.settings.recurring_monitor_pricing[0].amount_usd
        )
        staged_monitor_order_id = monitor_order.order_id if monitor_order is not None else None
        metadata = {
            "audit_business_name": audit_order.business_name,
            "audit_website_url": audit_order.website_url,
            "upsell_offer_slug": self.recurring_monitor_offer.slug,
            "staged_without_monitor_order": monitor_order is None,
        }
        if existing is None:
            return self.audit_store.create_recurring_monitor_enrollment(
                RecurringMonitorEnrollment(
                    enrollment_id=self.audit_store.next_recurring_monitor_enrollment_id(),
                    audit_order_id=audit_order.order_id,
                    offer_slug=self.recurring_monitor_offer.slug,
                    parent_offer_slug=audit_order.offer_slug,
                    monitor_order_id=staged_monitor_order_id,
                    price_key=price_key or self.settings.recurring_monitor_pricing[0].key,
                    status=status,
                    cadence_days=self.settings.recurring_monitor_cadence_days,
                    monthly_amount_usd=amount,
                    currency=audit_order.currency,
                    checkout_session_id=checkout_session.session_id if checkout_session is not None else "",
                    metadata=metadata,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        updated_metadata = {**existing.metadata, **metadata}
        return self.audit_store.update_recurring_monitor_enrollment(
            existing.enrollment_id,
            monitor_order_id=monitor_order.order_id if monitor_order is not None else existing.monitor_order_id,
            price_key=price_key or existing.price_key,
            status=status,
            monthly_amount_usd=amount,
            checkout_session_id=checkout_session.session_id if checkout_session is not None else existing.checkout_session_id,
            metadata=updated_metadata,
            updated_at=utc_now(),
        )

    def _mark_recurring_monitor_active(
        self,
        *,
        order: AuditOrder,
        payment_event: PaymentEvent,
        data_object: dict[str, Any],
    ) -> AuditOrder:
        source_order_id = str(order.metadata.get("source_order_id", "")).strip()
        audit_order = self.audit_store.get_order(source_order_id) if source_order_id else None
        if audit_order is None:
            raise ValueError("Recurring monitor payment is missing source audit order context")
        enrollment = self._stage_or_update_recurring_monitor_enrollment(
            audit_order=audit_order,
            monitor_order=order,
            price_key=order.price_key,
            monthly_amount_usd=order.amount_total_usd,
            status="checkout_pending",
        )
        paid_at = order.paid_at or payment_event.created_at or utc_now()
        provider_subscription_id = str(data_object.get("subscription", "") or enrollment.provider_subscription_id).strip()
        enrollment = self.audit_store.update_recurring_monitor_enrollment(
            enrollment.enrollment_id,
            status="active",
            monitor_order_id=order.order_id,
            price_key=order.price_key,
            monthly_amount_usd=order.amount_total_usd,
            checkout_session_id=enrollment.checkout_session_id,
            provider_subscription_id=provider_subscription_id,
            source_payment_event_id=payment_event.payment_event_id,
            enrolled_at=enrollment.enrolled_at or paid_at,
            next_run_at=_add_days_iso(enrollment.enrolled_at or paid_at, enrollment.cadence_days),
            metadata={
                **enrollment.metadata,
                "last_paid_at": paid_at,
            },
            updated_at=utc_now(),
        )
        order = self.audit_store.update_order(
            order.order_id,
            status="paid",
            fulfillment_status="active",
            paid_at=paid_at,
            metadata=_append_timeline_entries(
                order.metadata,
                _timeline_entry(
                    status="recurring_monitor_activated",
                    occurred_at=paid_at,
                    detail="Stripe activated the recurring monitor subscription.",
                    metadata={
                        "enrollment_id": enrollment.enrollment_id,
                        "provider_subscription_id": provider_subscription_id,
                    },
                ),
            ),
            updated_at=utc_now(),
        )
        return order

    def _update_recurring_monitor_status(
        self,
        *,
        order: AuditOrder,
        status: str,
        occurred_at: str,
        provider_subscription_id: str = "",
        payment_event_id: str = "",
        refunded: bool = False,
    ) -> AuditOrder:
        enrollment = self.audit_store.find_recurring_monitor_enrollment_by_monitor_order(order.order_id)
        if enrollment is None:
            source_order_id = str(order.metadata.get("source_order_id", "")).strip()
            audit_order = self.audit_store.get_order(source_order_id) if source_order_id else None
            if audit_order is None:
                return order
            enrollment = self._stage_or_update_recurring_monitor_enrollment(
                audit_order=audit_order,
                monitor_order=order,
                price_key=order.price_key,
                monthly_amount_usd=order.amount_total_usd,
                status="checkout_pending",
            )
        update_fields: dict[str, Any] = {
            "status": status,
            "provider_subscription_id": provider_subscription_id or enrollment.provider_subscription_id,
            "source_payment_event_id": payment_event_id or enrollment.source_payment_event_id,
            "updated_at": utc_now(),
            "metadata": {
                **enrollment.metadata,
                "last_status_change_at": occurred_at,
            },
        }
        if status == "canceled":
            update_fields["canceled_at"] = occurred_at
            update_fields["next_run_at"] = None
        elif status == "churned":
            update_fields["churned_at"] = occurred_at
            update_fields["next_run_at"] = None
        elif status == "refunded" or refunded:
            update_fields["refunded_at"] = occurred_at
            update_fields["next_run_at"] = None
        elif status == "active":
            update_fields["enrolled_at"] = enrollment.enrolled_at or occurred_at
            update_fields["next_run_at"] = _add_days_iso(enrollment.enrolled_at or occurred_at, enrollment.cadence_days)
        self.audit_store.update_recurring_monitor_enrollment(enrollment.enrollment_id, **update_fields)
        return self.audit_store.update_order(
            order.order_id,
            fulfillment_status=status,
            metadata=_append_timeline_entries(
                order.metadata,
                _timeline_entry(
                    status=f"recurring_monitor_{status}",
                    occurred_at=occurred_at,
                    detail=f"Recurring monitor status changed to {status}.",
                    metadata={"enrollment_id": enrollment.enrollment_id},
                ),
            ),
            updated_at=utc_now(),
        )

    def _resolve_redirect_url(self, explicit_url: str, *, kind: str, offer_slug: str | None = None) -> str:
        context = self._offer_context(offer_slug or self.settings.offer_slug)
        configured = explicit_url.strip() if explicit_url.strip() else (
            context["success_url"] if kind == "success" else context["cancel_url"]
        )
        parsed = urlparse(configured)
        host = (parsed.hostname or "").lower()
        scheme = parsed.scheme.lower()
        if not scheme or not host:
            raise ValueError(f"{kind}_url must be an absolute URL")
        if scheme == "https":
            pass
        elif scheme == "http" and host in LOCAL_REDIRECT_HOSTS:
            pass
        else:
            raise ValueError(f"{kind}_url must use https outside local development")
        if is_placeholder_domain(host):
            raise ValueError(f"{kind}_url uses a placeholder host: {host}")
        if self.settings.allowed_redirect_hosts and host not in self.settings.allowed_redirect_hosts:
            raise ValueError(f"{kind}_url host '{host}' is not allowed")
        if kind == "success" and "{CHECKOUT_SESSION_ID}" not in configured and "session_id=" not in configured:
            raise ValueError("success_url must include a session_id placeholder or query parameter")
        return configured

    def _lookup_order(
        self,
        *,
        order_id: str | None = None,
        provider_session_id: str | None = None,
        provider_payment_intent_id: str | None = None,
    ) -> AuditOrder | None:
        if order_id:
            return self.audit_store.get_order(order_id)
        if provider_session_id:
            checkout_session = self.audit_store.get_checkout_session_by_provider_session_id(provider_session_id)
            if checkout_session is not None:
                return self.audit_store.get_order(checkout_session.order_id)
        if provider_payment_intent_id:
            checkout_session = self.audit_store.get_checkout_session_by_payment_intent(provider_payment_intent_id)
            if checkout_session is not None:
                return self.audit_store.get_order(checkout_session.order_id)
        return None

    def handle_stripe_webhook(self, payload: bytes, signature_header: str) -> dict[str, Any]:
        event = verify_webhook_signature(
            payload=payload,
            signature_header=signature_header,
            secret=self.settings.stripe_webhook_secret,
            tolerance_seconds=self.settings.stripe_webhook_tolerance_seconds,
        )
        provider_event_id = str(event.get("id", "")).strip()
        if not provider_event_id:
            raise WebhookVerificationError("Stripe webhook payload is missing event id")
        existing = self.audit_store.get_payment_event_by_provider_event_id(provider_event_id)
        if existing is not None:
            order = self.audit_store.get_order(existing.order_id)
            return {
                "status": "duplicate",
                "order_id": existing.order_id,
                "order_status": order.status if order is not None else "unknown",
            }

        event_type = str(event.get("type", "")).strip()
        data_object = dict(event.get("data", {}).get("object", {}) or {})
        metadata = _metadata_from_event_object(data_object)
        order = self._resolve_order_for_event(data_object)
        if order is None:
            return {"status": "ignored", "reason": "unknown_order", "event_type": event_type}

        provider_session_id = str(data_object.get("id", "")).strip() if event_type.startswith("checkout.session") else ""
        provider_payment_intent_id = str(data_object.get("payment_intent", "") or "").strip()
        currency = str(data_object.get("currency", order.currency)).upper()
        amount_total_usd = _amount_usd(
            data_object.get("amount_total") or data_object.get("amount") or 0,
            currency,
        )
        payment_event = self.audit_store.record_payment_event(
            PaymentEvent(
                payment_event_id=self.audit_store.next_payment_event_id(),
                order_id=order.order_id,
                provider="stripe",
                provider_event_id=provider_event_id,
                event_type=event_type,
                status=str(data_object.get("payment_status") or data_object.get("status") or "recorded"),
                amount_total_usd=amount_total_usd,
                currency=currency,
                provider_session_id=provider_session_id,
                provider_payment_intent_id=provider_payment_intent_id,
                payload=event,
                created_at=_iso_from_unix(event.get("created")) or utc_now(),
            )
        )

        if provider_session_id:
            self._sync_checkout_session(order.order_id, data_object, payment_event)

        if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded", "invoice.paid"} and (
            str(data_object.get("payment_status", "")).strip().lower() == "paid"
            or event_type == "invoice.paid"
        ):
            order = self._mark_order_paid(order, payment_event, event)
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type == "checkout.session.expired":
            order = self.audit_store.update_order(order.order_id, status="expired", updated_at=utc_now())
            self._sync_checkout_session(order.order_id, data_object, payment_event, status="expired")
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type in {"payment_intent.payment_failed", "checkout.session.async_payment_failed", "invoice.payment_failed"}:
            order = self.audit_store.update_order(order.order_id, status="payment_failed", updated_at=utc_now())
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type in {"customer.subscription.updated", "customer.subscription.resumed"}:
            subscription_status = str(data_object.get("status", "")).strip().lower()
            if subscription_status in {"active", "trialing"}:
                order = self._update_recurring_monitor_status(
                    order=order,
                    status="active",
                    occurred_at=_iso_from_unix(event.get("created")) or utc_now(),
                    provider_subscription_id=str(data_object.get("id", "")).strip(),
                )
            elif subscription_status == "paused":
                order = self._update_recurring_monitor_status(
                    order=order,
                    status="paused",
                    occurred_at=_iso_from_unix(event.get("created")) or utc_now(),
                    provider_subscription_id=str(data_object.get("id", "")).strip(),
                )
            elif subscription_status in {"canceled", "cancelled"}:
                order = self._update_recurring_monitor_status(
                    order=order,
                    status="canceled",
                    occurred_at=_iso_from_unix(event.get("created")) or utc_now(),
                    provider_subscription_id=str(data_object.get("id", "")).strip(),
                )
            elif subscription_status in {"unpaid", "incomplete_expired"}:
                order = self._update_recurring_monitor_status(
                    order=order,
                    status="churned",
                    occurred_at=_iso_from_unix(event.get("created")) or utc_now(),
                    provider_subscription_id=str(data_object.get("id", "")).strip(),
                )
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type in {"customer.subscription.deleted", "customer.subscription.paused"}:
            order = self._update_recurring_monitor_status(
                order=order,
                status="canceled" if event_type.endswith("deleted") else "paused",
                occurred_at=_iso_from_unix(event.get("created")) or utc_now(),
                provider_subscription_id=str(data_object.get("id", "")).strip(),
            )
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type == "charge.refunded":
            order = self.audit_store.update_order(order.order_id, status="refunded", updated_at=utc_now())
            if order.offer_slug == self.recurring_monitor_offer.slug:
                order = self._update_recurring_monitor_status(
                    order=order,
                    status="refunded",
                    occurred_at=_iso_from_unix(event.get("created")) or utc_now(),
                    provider_subscription_id=str(metadata.get("subscription", "")).strip(),
                    payment_event_id=payment_event.payment_event_id,
                    refunded=True,
                )
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        return {"status": "processed", "order_id": order.order_id, "order_status": order.status}

    def _resolve_order_for_event(self, data_object: dict[str, Any]) -> AuditOrder | None:
        metadata = _metadata_from_event_object(data_object)
        order_id = str(metadata.get("order_id", "")).strip()
        if order_id:
            return self.audit_store.get_order(order_id)
        subscription_id = str(data_object.get("subscription", "") or data_object.get("id", "")).strip()
        if subscription_id:
            enrollment = self.audit_store.find_recurring_monitor_enrollment_by_subscription(subscription_id)
            if enrollment is not None and enrollment.monitor_order_id:
                return self.audit_store.get_order(enrollment.monitor_order_id)
        provider_session_id = str(data_object.get("id", "")).strip()
        if provider_session_id:
            checkout_session = self.audit_store.get_checkout_session_by_provider_session_id(provider_session_id)
            if checkout_session is not None:
                return self.audit_store.get_order(checkout_session.order_id)
        payment_intent_id = str(data_object.get("payment_intent", "") or "").strip()
        if payment_intent_id:
            checkout_session = self.audit_store.get_checkout_session_by_payment_intent(payment_intent_id)
            if checkout_session is not None:
                return self.audit_store.get_order(checkout_session.order_id)
        return None

    def _sync_checkout_session(
        self,
        order_id: str,
        data_object: dict[str, Any],
        payment_event: PaymentEvent,
        *,
        status: str | None = None,
    ) -> None:
        provider_session_id = str(data_object.get("id", "")).strip()
        if not provider_session_id:
            return
        checkout_session = self.audit_store.get_checkout_session_by_provider_session_id(provider_session_id)
        if checkout_session is None:
            return
        metadata = dict(checkout_session.metadata)
        metadata["last_webhook_payload"] = data_object
        self.audit_store.update_checkout_session(
            checkout_session.session_id,
            order_id=order_id,
            provider_payment_intent_id=payment_event.provider_payment_intent_id or checkout_session.provider_payment_intent_id,
            status=status or str(data_object.get("payment_status") or data_object.get("status") or checkout_session.status),
            metadata=metadata,
            updated_at=utc_now(),
        )

    def _mark_order_paid(
        self,
        order: AuditOrder,
        payment_event: PaymentEvent,
        event_payload: dict[str, Any],
    ) -> AuditOrder:
        data_object = dict(event_payload.get("data", {}).get("object", {}) or {})
        if order.offer_slug == self.recurring_monitor_offer.slug:
            return self._mark_recurring_monitor_active(
                order=order,
                payment_event=payment_event,
                data_object=data_object,
            )
        paid_at = order.paid_at or (_iso_from_unix(event_payload.get("created")) or utc_now())
        if not order.crm_account_id or not order.crm_opportunity_id or not order.crm_proposal_id:
            crm_ids = self._ensure_crm_records(order)
            order = self.audit_store.update_order(
                order.order_id,
                status="paid",
                fulfillment_status="queued",
                crm_account_id=crm_ids["account_id"],
                crm_opportunity_id=crm_ids["opportunity_id"],
                crm_proposal_id=crm_ids["proposal_id"],
                paid_at=paid_at,
                updated_at=utc_now(),
            )
        else:
            order = self.audit_store.update_order(
                order.order_id,
                status="paid",
                fulfillment_status="queued",
                paid_at=paid_at,
                updated_at=utc_now(),
            )
        job = self.audit_store.create_fulfillment_job(
            FulfillmentJob(
                job_id=self.audit_store.next_fulfillment_job_id(),
                order_id=order.order_id,
                job_type="website_growth_audit",
                status="queued",
                metadata={
                    "source": "stripe_webhook",
                    "payment_event_id": payment_event.payment_event_id,
                    "provider_event_id": payment_event.provider_event_id,
                },
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        order = self.audit_store.update_order(
            order.order_id,
            metadata=_append_timeline_entries(
                order.metadata,
                _timeline_entry(
                    status="payment_received",
                    occurred_at=paid_at,
                    detail="Stripe marked the checkout session paid and attached the order to fulfillment.",
                    metadata={
                        "payment_event_id": payment_event.payment_event_id,
                        "provider_event_id": payment_event.provider_event_id,
                    },
                ),
                _timeline_entry(
                    status="fulfillment_queued",
                    occurred_at=utc_now(),
                    detail="The paid order is queued for same-day audit delivery.",
                    metadata={"fulfillment_job_id": job.job_id},
                ),
            ),
            updated_at=utc_now(),
        )
        enrollment = self._stage_or_update_recurring_monitor_enrollment(audit_order=order, status="staged")
        order = self.audit_store.update_order(
            order.order_id,
            metadata=_append_timeline_entries(
                order.metadata,
                _timeline_entry(
                    status="recurring_monitor_staged",
                    occurred_at=utc_now(),
                    detail="The recurring monitor upsell is staged and ready for hosted checkout.",
                    metadata={"enrollment_id": enrollment.enrollment_id},
                ),
            ),
            updated_at=utc_now(),
        )
        if order.crm_account_id and order.crm_opportunity_id:
            self.telemetry.fulfillment_status_changed(
                account_id=order.crm_account_id,
                opportunity_id=order.crm_opportunity_id,
                outcome_id=order.crm_outcome_id or 0,
                status="payment_received",
                revenue=payment_event.amount_total_usd,
                gross_margin=0.0,
                is_simulated=False,
                metadata={
                    "revenue_audit_order_id": order.order_id,
                    "payment_event_id": payment_event.payment_event_id,
                    "provider_event_id": payment_event.provider_event_id,
                    "fulfillment_job_id": job.job_id,
                },
            )
        return order

    def _ensure_crm_records(self, order: AuditOrder) -> dict[str, int]:
        domain = _domain_from_url(order.website_url)
        account = self.revenue_store.create_account(
            Account(
                name=order.business_name or domain or order.customer_name or "Website Growth Audit Customer",
                domain=domain,
                website_url=order.website_url,
                status="customer",
                metadata={
                    "revenue_audit_order_id": order.order_id,
                    "customer_email": order.customer_email,
                },
            )
        )
        opportunity = self.revenue_store.create_opportunity(
            Opportunity(
                account_id=account.id or 0,
                name=f"{self.offer.name} Order {order.order_id}",
                offer_name=self.offer.name,
                stage="fulfillment",
                status="won",
                score=100.0,
                estimated_value=order.amount_total_usd,
                currency=order.currency,
                next_action="Generate paid audit artifact",
                metadata={"revenue_audit_order_id": order.order_id},
            )
        )
        proposal = self.revenue_store.create_proposal(
            Proposal(
                account_id=account.id or 0,
                opportunity_id=opportunity.id or 0,
                title=self.offer.name,
                amount=order.amount_total_usd,
                currency=order.currency,
                status="accepted",
                summary="Stripe Checkout payment captured for website growth audit.",
                metadata={
                    "revenue_audit_order_id": order.order_id,
                    "price_key": order.price_key,
                },
            )
        )
        return {
            "account_id": account.id or 0,
            "opportunity_id": opportunity.id or 0,
            "proposal_id": proposal.id or 0,
        }
