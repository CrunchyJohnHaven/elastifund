"""Transparent scoring for deterministic revenue-audit bundles."""

from __future__ import annotations

from dataclasses import dataclass

from nontrading.offers.website_growth_audit import ServiceOffer, website_growth_audit_offer

from .detectors import run_detectors
from .models import AuditBundle, AuditScore, IssueEvidence, ProspectProfile

SEVERITY_POINTS = {
    "critical": 1.0,
    "high": 0.8,
    "medium": 0.55,
    "low": 0.3,
}


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


@dataclass(frozen=True)
class ScoreComponents:
    issue_signal: float
    contactability: float
    missing_data_penalty: float
    average_issue_confidence: float
    coverage_score: float


def score_audit_bundle(
    prospect: ProspectProfile,
    issues: tuple[IssueEvidence, ...],
    *,
    offer: ServiceOffer | None = None,
) -> AuditScore:
    offer = offer or website_growth_audit_offer()
    components = _score_components(prospect, issues)

    confidence_score = _clamp(
        0.28
        + 0.28 * components.coverage_score
        + 0.22 * components.average_issue_confidence
        + 0.16 * components.contactability
        - 0.22 * components.missing_data_penalty
    )
    compliance_risk_score = _clamp(
        0.08
        + 0.34 * (1.0 - components.contactability)
        + 0.16 * _personal_contact_ratio(prospect)
        + 0.12 * (1.0 if prospect.country_code != "US" else 0.0)
        + 0.10 * components.missing_data_penalty
    )
    purchase_probability = _clamp(
        0.05
        + 0.46 * components.issue_signal
        + 0.12 * components.contactability
        + 0.12 * confidence_score
        - 0.18 * compliance_risk_score,
        minimum=0.02,
        maximum=0.95,
    )

    low_price, high_price = offer.price_range
    projected_price_usd = low_price + components.issue_signal * (high_price - low_price)
    estimated_fulfillment_cost_usd = (
        340.0
        + 180.0 * (1.0 - confidence_score)
        + 130.0 * components.missing_data_penalty
        + 90.0 * (1.0 - components.contactability)
    )
    expected_margin_usd = projected_price_usd - estimated_fulfillment_cost_usd
    expected_margin_pct = expected_margin_usd / projected_price_usd if projected_price_usd > 0 else 0.0
    expected_value_usd = purchase_probability * expected_margin_usd
    expected_payback_days = (
        5.0
        + 16.0 * (1.0 - purchase_probability)
        + 8.0 * compliance_risk_score
        + 5.0 * (1.0 - confidence_score)
    )

    explanation = {
        "formula_version": "revenue_audit.score.v1",
        "offer_slug": offer.slug,
        "inputs": {
            "issue_signal": round(components.issue_signal, 4),
            "contactability": round(components.contactability, 4),
            "missing_data_penalty": round(components.missing_data_penalty, 4),
            "average_issue_confidence": round(components.average_issue_confidence, 4),
            "coverage_score": round(components.coverage_score, 4),
            "issue_count": len(issues),
            "country_code": prospect.country_code,
        },
        "outputs": {
            "purchase_probability": round(purchase_probability, 4),
            "projected_price_usd": round(projected_price_usd, 2),
            "estimated_fulfillment_cost_usd": round(estimated_fulfillment_cost_usd, 2),
            "expected_margin_usd": round(expected_margin_usd, 2),
            "expected_margin_pct": round(expected_margin_pct, 4),
            "expected_value_usd": round(expected_value_usd, 2),
            "expected_payback_days": round(expected_payback_days, 2),
            "confidence_score": round(confidence_score, 4),
            "compliance_risk_score": round(compliance_risk_score, 4),
        },
    }
    return AuditScore(
        purchase_probability=purchase_probability,
        projected_price_usd=projected_price_usd,
        expected_margin_usd=expected_margin_usd,
        expected_margin_pct=expected_margin_pct,
        expected_value_usd=expected_value_usd,
        expected_payback_days=expected_payback_days,
        confidence_score=confidence_score,
        compliance_risk_score=compliance_risk_score,
        explanation=explanation,
    )


def build_audit_bundle(
    prospect: ProspectProfile,
    *,
    offer: ServiceOffer | None = None,
) -> AuditBundle:
    issues = run_detectors(prospect)
    score = score_audit_bundle(prospect, issues, offer=offer)
    return AuditBundle(prospect=prospect, issues=issues, score=score, offer_slug=(offer or website_growth_audit_offer()).slug)


def _score_components(prospect: ProspectProfile, issues: tuple[IssueEvidence, ...]) -> ScoreComponents:
    if issues:
        weighted_points = sum(SEVERITY_POINTS.get(issue.severity, 0.0) * issue.confidence for issue in issues)
        average_issue_confidence = sum(issue.confidence for issue in issues) / len(issues)
        missing_flags = sum(len(issue.missing_data_flags) for issue in issues)
    else:
        weighted_points = 0.0
        average_issue_confidence = 0.5
        missing_flags = 0
    issue_signal = _clamp(weighted_points / 3.5)
    coverage_score = _clamp(len(prospect.pages) / 3.0)
    missing_data_penalty = _clamp(missing_flags / 6.0)
    return ScoreComponents(
        issue_signal=issue_signal,
        contactability=_contactability_score(prospect),
        missing_data_penalty=missing_data_penalty,
        average_issue_confidence=average_issue_confidence,
        coverage_score=coverage_score,
    )


def _contactability_score(prospect: ProspectProfile) -> float:
    score = 0.0
    for channel in prospect.contact_channels:
        if channel.kind == "email" and channel.is_business:
            score += 0.45
        elif channel.kind == "phone":
            score += 0.35
        elif channel.kind == "contact_form":
            score += 0.25
        elif channel.kind == "contact_page":
            score += 0.15
        elif channel.kind == "email":
            score += 0.10
    return _clamp(score)


def _personal_contact_ratio(prospect: ProspectProfile) -> float:
    emails = [channel for channel in prospect.contact_channels if channel.kind == "email"]
    if not emails:
        return 0.0
    personal_count = sum(1 for channel in emails if not channel.is_business)
    return personal_count / len(emails)
