"""Compliance-first lead policies for campaign eligibility."""

from __future__ import annotations

from dataclasses import dataclass

from nontrading.config import RevenueAgentSettings
from nontrading.models import Campaign, Lead


@dataclass(frozen=True)
class LeadPolicyDecision:
    allowed: bool
    score: float
    reasons: tuple[str, ...]
    role_based_email: bool


def _effective_allowed_countries(campaign: Campaign, settings: RevenueAgentSettings) -> set[str] | None:
    if settings.allow_all_countries:
        if "*" in campaign.allowed_countries or "ALL" in campaign.allowed_countries:
            return None
        return {country.upper() for country in campaign.allowed_countries}

    global_allowed = {country.upper() for country in settings.allowed_countries}
    if "*" in campaign.allowed_countries or "ALL" in campaign.allowed_countries:
        return global_allowed
    campaign_allowed = {country.upper() for country in campaign.allowed_countries}
    return global_allowed & campaign_allowed


def is_personal_email_domain(email: str, personal_domains: tuple[str, ...]) -> bool:
    domain = email.split("@", 1)[-1].lower()
    return domain in set(personal_domains)


def is_role_based_business_email(
    email: str,
    role_localparts: tuple[str, ...],
    personal_domains: tuple[str, ...],
) -> bool:
    localpart, _, domain = email.partition("@")
    if not domain:
        return False
    if domain.lower() in set(personal_domains):
        return False
    return localpart.lower() in set(role_localparts)


def evaluate_lead_policy(
    lead: Lead,
    campaign: Campaign,
    settings: RevenueAgentSettings,
) -> LeadPolicyDecision:
    reasons: list[str] = []
    effective_allowed = _effective_allowed_countries(campaign, settings)
    country_code = (lead.country_code or "").upper()
    if effective_allowed is not None and country_code not in effective_allowed:
        reasons.append(f"country_blocked:{country_code or 'UNKNOWN'}")

    role_based_email = is_role_based_business_email(
        lead.email,
        settings.role_based_localparts,
        settings.personal_email_domains,
    )
    if not (lead.explicit_opt_in or role_based_email):
        reasons.append("requires_opt_in_or_role_address")

    score = 0.0
    if not reasons:
        score += 100.0 if lead.explicit_opt_in else 50.0
        if role_based_email:
            score += 10.0
        if lead.source.startswith("manual"):
            score += 5.0

    return LeadPolicyDecision(
        allowed=not reasons,
        score=score,
        reasons=tuple(reasons),
        role_based_email=role_based_email,
    )

