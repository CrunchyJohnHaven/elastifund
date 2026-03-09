"""Environment-backed settings for the non-trading revenue agent."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


DEFAULT_ROLE_LOCALPARTS = (
    "info",
    "sales",
    "contact",
    "hello",
    "support",
    "team",
    "partnerships",
    "partnership",
    "bizdev",
    "business",
    "admin",
)

DEFAULT_PERSONAL_EMAIL_DOMAINS = (
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "me.com",
    "live.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
)

PLACEHOLDER_DOMAINS = {
    "example.invalid",
    "invalid",
    "localhost",
    "example.com",
    "example.org",
    "example.net",
}


def _get_bool(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _get_text(name: str, default: str) -> str:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _split_csv(raw: str | None, default: Iterable[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        values = tuple(default)
    else:
        values = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    return values or tuple(default)


def _split_localparts(raw: str | None, default: Iterable[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        values = tuple(default)
    else:
        values = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return values or tuple(default)


def normalize_domain_for_checks(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "@" in text:
        text = text.split("@", 1)[1]
    return text.strip(".")


def is_placeholder_domain(value: str | None) -> bool:
    domain = normalize_domain_for_checks(value)
    if not domain:
        return True
    if domain in PLACEHOLDER_DOMAINS:
        return True
    return domain.endswith(".invalid") or domain.endswith(".local")


@dataclass(frozen=True)
class RevenueAgentSettings:
    db_path: Path = Path("data/revenue_agent.db")
    outbox_dir: Path = Path("data/revenue_outbox")
    provider: str = "dry_run"
    public_base_url: str = "https://example.invalid"
    from_name: str = "Elastifund"
    from_email: str = "partnerships@example.invalid"
    postal_address: str = "123 Example Street, Dublin, Ireland"
    unsubscribe_mailto: str = "unsubscribe@example.invalid"
    default_campaign_name: str = "default-revenue-campaign"
    default_subject_template: str = "Elastifund for {company_name}"
    default_body_template: str = (
        "Hi,\n\n"
        "This is Elastifund's rules-based revenue agent. "
        "If this mailbox handles partnerships or your team opted in, "
        "reply to explore fit.\n"
    )
    allowed_countries: tuple[str, ...] = ("US",)
    role_based_localparts: tuple[str, ...] = DEFAULT_ROLE_LOCALPARTS
    personal_email_domains: tuple[str, ...] = DEFAULT_PERSONAL_EMAIL_DOMAINS
    daily_send_quota: int = 25
    loop_seconds: int = 300
    complaint_rate_yellow: float = 0.001
    complaint_rate_red: float = 0.003
    bounce_rate_yellow: float = 0.02
    bounce_rate_red: float = 0.05
    sendgrid_api_key: str | None = None
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = None

    @classmethod
    def from_env(cls) -> "RevenueAgentSettings":
        return cls(
            db_path=Path(_get_text("JJ_REVENUE_DB_PATH", "data/revenue_agent.db")),
            outbox_dir=Path(_get_text("JJ_REVENUE_OUTBOX_DIR", "data/revenue_outbox")),
            provider=_get_text("JJ_REVENUE_PROVIDER", "dry_run").lower(),
            public_base_url=_get_text("JJ_REVENUE_PUBLIC_BASE_URL", "https://example.invalid"),
            from_name=_get_text("JJ_REVENUE_FROM_NAME", "Elastifund"),
            from_email=_get_text("JJ_REVENUE_FROM_EMAIL", "partnerships@example.invalid"),
            postal_address=_get_text("JJ_REVENUE_POSTAL_ADDRESS", "123 Example Street, Dublin, Ireland"),
            unsubscribe_mailto=_get_text("JJ_REVENUE_UNSUBSCRIBE_MAILTO", "unsubscribe@example.invalid"),
            default_campaign_name=_get_text("JJ_REVENUE_DEFAULT_CAMPAIGN_NAME", "default-revenue-campaign"),
            default_subject_template=_get_text("JJ_REVENUE_DEFAULT_SUBJECT", "Elastifund for {company_name}"),
            default_body_template=_get_text(
                "JJ_REVENUE_DEFAULT_BODY",
                (
                    "Hi,\n\n"
                    "This is Elastifund's rules-based revenue agent. "
                    "If this mailbox handles partnerships or your team opted in, "
                    "reply to explore fit.\n"
                ),
            ),
            allowed_countries=_split_csv(getenv("JJ_REVENUE_ALLOWED_COUNTRIES"), ("US",)),
            role_based_localparts=_split_localparts(getenv("JJ_REVENUE_ROLE_LOCALPARTS"), DEFAULT_ROLE_LOCALPARTS),
            personal_email_domains=_split_localparts(
                getenv("JJ_REVENUE_PERSONAL_EMAIL_DOMAINS"),
                DEFAULT_PERSONAL_EMAIL_DOMAINS,
            ),
            daily_send_quota=_get_int("JJ_REVENUE_DAILY_SEND_QUOTA", 25),
            loop_seconds=_get_int("JJ_REVENUE_LOOP_SECONDS", 300),
            complaint_rate_yellow=_get_float("JJ_REVENUE_COMPLAINT_RATE_YELLOW", 0.001),
            complaint_rate_red=_get_float("JJ_REVENUE_COMPLAINT_RATE_RED", 0.003),
            bounce_rate_yellow=_get_float("JJ_REVENUE_BOUNCE_RATE_YELLOW", 0.02),
            bounce_rate_red=_get_float("JJ_REVENUE_BOUNCE_RATE_RED", 0.05),
            sendgrid_api_key=getenv("SENDGRID_API_KEY"),
            mailgun_api_key=getenv("MAILGUN_API_KEY"),
            mailgun_domain=getenv("MAILGUN_DOMAIN"),
        )

    def ensure_paths(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    @property
    def allow_all_countries(self) -> bool:
        return "*" in self.allowed_countries or "ALL" in self.allowed_countries

    def country_allowed(self, country_code: str) -> bool:
        if self.allow_all_countries:
            return True
        return (country_code or "").strip().upper() in set(self.allowed_countries)

    def build_unsubscribe_url(self, email: str, campaign_name: str) -> str:
        base = self.public_base_url.rstrip("/")
        encoded_email = quote(email, safe="")
        encoded_campaign = quote(campaign_name, safe="")
        return f"{base}/unsubscribe?email={encoded_email}&campaign={encoded_campaign}"
