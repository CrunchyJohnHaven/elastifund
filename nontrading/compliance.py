"""CAN-SPAM oriented compliance checks for Phase 0 outreach."""

from __future__ import annotations

from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Iterable

from nontrading.store import RevenueStore
from nontrading.models import SendEvent, normalize_domain, normalize_email


@dataclass(frozen=True)
class ComplianceDecision:
    allowed: bool
    reason: str = ""
    metadata: dict[str, str | int] = field(default_factory=dict)


class ComplianceGuard:
    """Applies sender, suppression, unsubscribe, and rate-limit policy."""

    def __init__(
        self,
        store: RevenueStore,
        *,
        verified_domains: Iterable[str],
        daily_message_limit: int = 25,
    ):
        self.store = store
        self.verified_domains = {normalize_domain(domain) for domain in verified_domains if normalize_domain(domain)}
        self.daily_message_limit = daily_message_limit

    def is_verified_domain(self, sender_email: str) -> bool:
        _, parsed = parseaddr(sender_email)
        if not parsed or "@" not in parsed:
            return False
        return normalize_domain(parsed.split("@", 1)[1]) in self.verified_domains

    def sender_identity_verified(self, sender_name: str, sender_email: str) -> bool:
        _, parsed = parseaddr(sender_email)
        return bool(sender_name.strip()) and bool(parsed) and parsed == sender_email.strip()

    def register_unsubscribe(self, email: str, *, detail: str = "phase0_unsubscribe") -> SendEvent:
        return self.store.record_unsubscribe(email=email, detail=detail, provider="phase0")

    def evaluate_outreach(
        self,
        *,
        sender_name: str,
        sender_email: str,
        recipient_email: str,
    ) -> ComplianceDecision:
        normalized_recipient = normalize_email(recipient_email)
        if not self.sender_identity_verified(sender_name, sender_email):
            return ComplianceDecision(allowed=False, reason="sender_identity_unverified")

        if not self.is_verified_domain(sender_email):
            return ComplianceDecision(allowed=False, reason="sender_domain_unverified")

        if self.store.is_suppressed(normalized_recipient):
            return ComplianceDecision(allowed=False, reason="recipient_suppressed")

        sends_today = self.store.count_total_sends_today() + self.store.count_telemetry_events_today("message_sent")
        if sends_today >= self.daily_message_limit:
            return ComplianceDecision(
                allowed=False,
                reason="daily_rate_limit_exceeded",
                metadata={"daily_message_limit": self.daily_message_limit, "sends_today": sends_today},
            )

        return ComplianceDecision(
            allowed=True,
            metadata={"daily_message_limit": self.daily_message_limit, "sends_today": sends_today},
        )
