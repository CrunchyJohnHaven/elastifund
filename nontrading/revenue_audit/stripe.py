"""Small Stripe helpers without adding a hard SDK dependency."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests


class StripeClientError(RuntimeError):
    """Raised when Stripe rejects a checkout request."""


class WebhookVerificationError(ValueError):
    """Raised when the Stripe webhook signature is invalid."""


def _iso_from_unix(timestamp: int | str | None) -> str | None:
    if timestamp in {None, ""}:
        return None
    value = int(timestamp)
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat()


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    if not signature_header.strip():
        raise WebhookVerificationError("Missing Stripe-Signature header")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        if key == "t" and value:
            timestamp = int(value)
        if key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        raise WebhookVerificationError("Malformed Stripe-Signature header")
    return timestamp, signatures


def verify_webhook_signature(
    *,
    payload: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> dict[str, Any]:
    if not secret.strip():
        raise WebhookVerificationError("Stripe webhook secret is not configured")
    timestamp, signatures = _parse_signature_header(signature_header)
    now = int(time.time())
    if tolerance_seconds >= 0 and abs(now - timestamp) > tolerance_seconds:
        raise WebhookVerificationError("Stripe webhook signature is outside the allowed tolerance")
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise WebhookVerificationError("Stripe webhook signature mismatch")
    return json.loads(payload.decode("utf-8"))


def generate_signature_header(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    effective_timestamp = int(time.time()) if timestamp is None else int(timestamp)
    signed_payload = f"{effective_timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={effective_timestamp},v1={digest}"


class StripeCheckoutClient:
    """Minimal Stripe Checkout session creator."""

    def __init__(self, secret_key: str, *, api_base: str = "https://api.stripe.com", timeout_seconds: int = 30):
        self.secret_key = secret_key.strip()
        self.api_base = api_base.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def create_checkout_session(
        self,
        *,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        mode: str = "payment",
        billing_interval: str | None = None,
        customer_email: str = "",
        client_reference_id: str = "",
        metadata: dict[str, Any] | None = None,
        subscription_metadata: dict[str, Any] | None = None,
        line_item_name: str,
        line_item_description: str = "",
    ) -> dict[str, Any]:
        if not self.secret_key:
            raise StripeClientError("Stripe secret key is not configured")
        checkout_mode = str(mode or "payment").strip().lower()
        if checkout_mode not in {"payment", "subscription"}:
            raise StripeClientError(f"Unsupported Stripe checkout mode: {mode}")
        payload: dict[str, Any] = {
            "mode": checkout_mode,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][product_data][name]": line_item_name,
            "line_items[0][price_data][unit_amount]": int(amount_cents),
            "line_items[0][quantity]": 1,
            "payment_method_types[0]": "card",
        }
        if checkout_mode == "subscription":
            interval = str(billing_interval or "month").strip().lower()
            if interval not in {"month", "quarter", "year"}:
                raise StripeClientError(f"Unsupported Stripe recurring interval: {billing_interval}")
            payload["line_items[0][price_data][recurring][interval]"] = "month" if interval == "quarter" else interval
            if interval == "quarter":
                payload["line_items[0][price_data][recurring][interval_count]"] = 3
        if line_item_description:
            payload["line_items[0][price_data][product_data][description]"] = line_item_description
        if customer_email:
            payload["customer_email"] = customer_email
        if client_reference_id:
            payload["client_reference_id"] = client_reference_id
        for key, value in (metadata or {}).items():
            payload[f"metadata[{key}]"] = str(value)
        for key, value in (subscription_metadata or {}).items():
            payload[f"subscription_data[metadata][{key}]"] = str(value)

        response = requests.post(
            urljoin(self.api_base, "v1/checkout/sessions"),
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise StripeClientError(f"Stripe checkout session creation failed: {response.text}")
        body = response.json()
        return {
            "id": str(body.get("id", "")),
            "url": str(body.get("url", "")),
            "mode": str(body.get("mode", "") or checkout_mode),
            "payment_intent": str(body.get("payment_intent", "") or ""),
            "subscription": str(body.get("subscription", "") or ""),
            "status": str(body.get("status", "") or ""),
            "expires_at": _iso_from_unix(body.get("expires_at")),
            "raw": body,
        }
