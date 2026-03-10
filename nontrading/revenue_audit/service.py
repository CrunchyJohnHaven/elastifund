"""Checkout and webhook service for the JJ-N website growth audit."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from nontrading.config import is_placeholder_domain
from nontrading.models import Account, Opportunity, Proposal
from nontrading.offers.website_growth_audit import website_growth_audit_offer
from nontrading.revenue_audit.config import RevenueAuditSettings
from nontrading.revenue_audit.contracts import (
    AuditOrder,
    CheckoutSession,
    CreateCheckoutRequest,
    FulfillmentJob,
    PaymentEvent,
    ProspectProfile,
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

    def offer_payload(self) -> dict[str, Any]:
        checklist = self.launch_checklist_payload()
        return {
            "offer": {
                "name": self.offer.name,
                "slug": self.offer.slug,
                "description": self.offer.description,
                "delivery_days": self.offer.delivery_days,
                "fulfillment_type": self.offer.fulfillment_type,
                "price_range_usd": {
                    "low": self.offer.price_range[0],
                    "high": self.offer.price_range[1],
                },
            },
            "pricing": {
                "currency": self.settings.currency,
                "options": [contract_to_dict(option) for option in self.settings.pricing],
            },
            "checkout": {
                "provider": "stripe",
                "enabled": checklist["summary"]["checkout_ready"],
                "launch_ready": checklist["launch_ready"],
                "live_offer_url": self.settings.live_offer_url,
                "success_url_template": self.settings.stripe_success_url,
                "cancel_url": self.settings.stripe_cancel_url,
                "launch_blockers": checklist["blocking_requirements"],
            },
            "order_lookup": {
                "by_order_id": "/v1/nontrading/orders/{order_id}",
                "by_session_id": "/v1/nontrading/orders/lookup?session_id={CHECKOUT_SESSION_ID}",
                "by_payment_intent": "/v1/nontrading/orders/lookup?payment_intent={PAYMENT_INTENT_ID}",
            },
            "launch_checklist": checklist,
        }

    def launch_checklist_payload(self) -> dict[str, Any]:
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
                "env": "JJ_N_WEBSITE_GROWTH_AUDIT_SUCCESS_URL",
                "ready": _url_is_configured(self.settings.stripe_success_url),
                "current_value": self.settings.stripe_success_url,
                "detail": "Must be an absolute HTTPS URL on an allowed host and include {CHECKOUT_SESSION_ID}.",
            },
            {
                "key": "cancel_url",
                "label": "Checkout cancel URL",
                "env": "JJ_N_WEBSITE_GROWTH_AUDIT_CANCEL_URL",
                "ready": _url_is_configured(self.settings.stripe_cancel_url),
                "current_value": self.settings.stripe_cancel_url,
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
            "success_url_ready": _url_is_configured(self.settings.stripe_success_url),
            "cancel_url_ready": _url_is_configured(self.settings.stripe_cancel_url),
            "order_lookup_ready": True,
        }
        blocking = [item["key"] for item in requirements if not item["ready"]]
        return {
            "offer_slug": self.settings.offer_slug,
            "live_offer_url": self.settings.live_offer_url,
            "launch_ready": summary["checkout_ready"] and summary["webhook_ready"],
            "blocking_requirements": blocking,
            "summary": summary,
            "requirements": requirements,
        }

    def create_checkout_session(self, request: CreateCheckoutRequest) -> dict[str, Any]:
        if not request.customer_email:
            raise ValueError("customer_email is required")
        if not EMAIL_RE.match(request.customer_email):
            raise ValueError("customer_email must be a valid email address")
        if not request.business_name and not request.website_url:
            raise ValueError("business_name or website_url is required")
        if request.website_url and not _website_url_is_valid(request.website_url):
            raise ValueError("website_url must be an absolute http(s) URL")

        try:
            price = self.settings.price_option(request.price_key)
        except KeyError as exc:
            raise ValueError(f"Unknown price key: {request.price_key}") from exc
        success_url = self._resolve_redirect_url(request.success_url, kind="success")
        cancel_url = self._resolve_redirect_url(request.cancel_url, kind="cancel")
        prospect_profile = request.prospect_profile or ProspectProfile(
            business_name=request.business_name or request.customer_name or "Website Growth Audit Customer",
            website_url=request.website_url,
            contact_email=request.customer_email,
            contact_name=request.customer_name,
            metadata={"source": "checkout"},
        )
        order = self.audit_store.create_order(
            AuditOrder(
                order_id=self.audit_store.next_order_id(),
                offer_slug=self.settings.offer_slug,
                price_key=price.key,
                amount_subtotal_usd=price.amount_usd,
                amount_total_usd=price.amount_usd,
                currency=self.settings.currency,
                status="checkout_pending",
                fulfillment_status="not_started",
                customer_email=request.customer_email,
                customer_name=request.customer_name,
                business_name=request.business_name or prospect_profile.business_name,
                website_url=request.website_url or prospect_profile.website_url,
                prospect_profile=prospect_profile,
                audit_bundle=request.audit_bundle,
                metadata={
                    **request.metadata,
                    "price_label": price.label,
                    "price_description": price.description,
                },
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
                customer_email=order.customer_email,
                client_reference_id=order.order_id,
                metadata={
                    "order_id": order.order_id,
                    "offer_slug": order.offer_slug,
                    "price_key": order.price_key,
                    "business_name": order.business_name,
                    "website_url": order.website_url,
                },
                line_item_name=f"{self.offer.name} - {price.label}",
                line_item_description=price.description or self.offer.description,
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
        return {
            "order": contract_to_dict(order),
            "checkout_session": contract_to_dict(checkout_session),
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
        }

    def _resolve_redirect_url(self, explicit_url: str, *, kind: str) -> str:
        configured = explicit_url.strip() if explicit_url.strip() else (
            self.settings.stripe_success_url if kind == "success" else self.settings.stripe_cancel_url
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

        if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"} and (
            str(data_object.get("payment_status", "")).strip().lower() == "paid"
        ):
            order = self._mark_order_paid(order, payment_event, event)
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type == "checkout.session.expired":
            order = self.audit_store.update_order(order.order_id, status="expired", updated_at=utc_now())
            self._sync_checkout_session(order.order_id, data_object, payment_event, status="expired")
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type in {"payment_intent.payment_failed", "checkout.session.async_payment_failed"}:
            order = self.audit_store.update_order(order.order_id, status="payment_failed", updated_at=utc_now())
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        if event_type == "charge.refunded":
            order = self.audit_store.update_order(order.order_id, status="refunded", updated_at=utc_now())
            return {"status": "processed", "order_id": order.order_id, "order_status": order.status}
        return {"status": "processed", "order_id": order.order_id, "order_status": order.status}

    def _resolve_order_for_event(self, data_object: dict[str, Any]) -> AuditOrder | None:
        metadata = dict(data_object.get("metadata", {}) or {})
        order_id = str(metadata.get("order_id", "")).strip()
        if order_id:
            return self.audit_store.get_order(order_id)
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
        if not order.crm_account_id or not order.crm_opportunity_id or not order.crm_proposal_id:
            crm_ids = self._ensure_crm_records(order)
            order = self.audit_store.update_order(
                order.order_id,
                status="paid",
                fulfillment_status="queued",
                crm_account_id=crm_ids["account_id"],
                crm_opportunity_id=crm_ids["opportunity_id"],
                crm_proposal_id=crm_ids["proposal_id"],
                paid_at=_iso_from_unix(event_payload.get("created")) or utc_now(),
                updated_at=utc_now(),
            )
        else:
            order = self.audit_store.update_order(
                order.order_id,
                status="paid",
                fulfillment_status="queued",
                paid_at=order.paid_at or (_iso_from_unix(event_payload.get("created")) or utc_now()),
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
