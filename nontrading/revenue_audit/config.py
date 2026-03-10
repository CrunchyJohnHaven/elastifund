"""Environment-backed settings for revenue_audit checkout and billing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from urllib.parse import urljoin, urlparse

from nontrading.config import is_placeholder_domain
from nontrading.revenue_audit.contracts import CheckoutPrice

DEFAULT_PRICING = (
    CheckoutPrice(
        key="starter",
        label="Starter Audit",
        amount_usd=500.0,
        description="One-time website growth audit with prioritized findings.",
    ),
    CheckoutPrice(
        key="growth",
        label="Growth Audit",
        amount_usd=1500.0,
        description="Website growth audit with competitor benchmark appendix.",
    ),
    CheckoutPrice(
        key="scale",
        label="Scale Audit",
        amount_usd=2500.0,
        description="Website growth audit plus implementation roadmap and monitor setup.",
    ),
)


def _get_text(name: str, default: str) -> str:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _get_int(name: str, default: int) -> int:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _normalize_path(value: str, default: str) -> str:
    text = (value or "").strip() or default
    if not text.startswith("/"):
        text = "/" + text
    return text


def _host_from_url(value: str) -> str:
    return (urlparse((value or "").strip()).hostname or "").strip().lower()


def _build_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _parse_redirect_hosts(public_base_url: str) -> tuple[str, ...]:
    raw = getenv("JJ_N_WEBSITE_GROWTH_AUDIT_REDIRECT_HOSTS")
    hosts = {
        part.strip().lower()
        for part in (raw or "").split(",")
        if part.strip()
    }
    public_host = _host_from_url(public_base_url)
    if public_host:
        hosts.add(public_host)
    return tuple(sorted(hosts))


def _parse_pricing() -> tuple[CheckoutPrice, ...]:
    raw = getenv("JJ_N_WEBSITE_GROWTH_AUDIT_PRICING_JSON")
    if raw is None or not raw.strip():
        return DEFAULT_PRICING
    payload = json.loads(raw)
    options = tuple(
        CheckoutPrice(
            key=str(item["key"]),
            label=str(item["label"]),
            amount_usd=float(item["amount_usd"]),
            description=str(item.get("description", "")),
            metadata=dict(item.get("metadata", {})),
        )
        for item in payload
    )
    return options or DEFAULT_PRICING


@dataclass(frozen=True)
class RevenueAuditSettings:
    db_path: Path
    offer_slug: str
    currency: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_api_base: str
    stripe_success_url: str
    stripe_cancel_url: str
    stripe_webhook_tolerance_seconds: int
    pricing: tuple[CheckoutPrice, ...]
    public_base_url: str = "https://example.invalid"
    offer_path: str = "/nontrading/website-growth-audit"
    allowed_redirect_hosts: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "RevenueAuditSettings":
        public_base_url = _get_text(
            "JJ_N_WEBSITE_GROWTH_AUDIT_PUBLIC_BASE_URL",
            _get_text("JJ_REVENUE_PUBLIC_BASE_URL", "https://example.invalid"),
        )
        offer_path = _normalize_path(
            _get_text("JJ_N_WEBSITE_GROWTH_AUDIT_OFFER_PATH", "/nontrading/website-growth-audit"),
            "/nontrading/website-growth-audit",
        )
        success_url = _get_text(
            "JJ_N_WEBSITE_GROWTH_AUDIT_SUCCESS_URL",
            _build_url(public_base_url, f"{offer_path}/success") + "?session_id={CHECKOUT_SESSION_ID}",
        )
        cancel_url = _get_text(
            "JJ_N_WEBSITE_GROWTH_AUDIT_CANCEL_URL",
            _build_url(public_base_url, f"{offer_path}/cancel"),
        )
        return cls(
            db_path=Path(_get_text("JJ_REVENUE_DB_PATH", "data/revenue_agent.db")),
            offer_slug=_get_text("JJ_N_WEBSITE_GROWTH_AUDIT_SLUG", "website-growth-audit"),
            currency=_get_text("JJ_N_WEBSITE_GROWTH_AUDIT_CURRENCY", "USD").upper(),
            public_base_url=public_base_url,
            offer_path=offer_path,
            stripe_secret_key=_get_text("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=_get_text("STRIPE_WEBHOOK_SECRET", ""),
            stripe_api_base=_get_text("STRIPE_API_BASE", "https://api.stripe.com"),
            stripe_success_url=success_url,
            stripe_cancel_url=cancel_url,
            stripe_webhook_tolerance_seconds=_get_int("STRIPE_WEBHOOK_TOLERANCE_SECONDS", 300),
            allowed_redirect_hosts=_parse_redirect_hosts(public_base_url),
            pricing=_parse_pricing(),
        )

    def ensure_paths(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def price_option(self, price_key: str) -> CheckoutPrice:
        normalized = str(price_key).strip().lower()
        for option in self.pricing:
            if option.key == normalized:
                return option
        raise KeyError(f"Unknown price key: {price_key}")

    @property
    def live_offer_url(self) -> str:
        return _build_url(self.public_base_url, self.offer_path)

    @property
    def public_base_url_ready(self) -> bool:
        host = _host_from_url(self.public_base_url)
        return bool(host) and not is_placeholder_domain(host)
