"""Deterministic issue detectors for the Website Growth Audit."""

from __future__ import annotations

from typing import Callable, Iterable

from .models import FetchedPage, IssueEvidence, ProspectProfile

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
BUSINESS_SCHEMA_TYPES = frozenset(
    {
        "LocalBusiness",
        "Organization",
        "Corporation",
        "ProfessionalService",
        "HomeAndConstructionBusiness",
        "RoofingContractor",
        "Plumber",
        "HVACBusiness",
        "Electrician",
        "Service",
    }
)
GENERIC_HEADLINES = frozenset({"welcome", "home", "homepage", "services", "our services"})
GENERIC_CTA_TEXTS = frozenset({"learn more", "read more", "submit", "more", "click here"})
OFFER_KEYWORDS = frozenset(
    {
        "service",
        "services",
        "repair",
        "installation",
        "estimate",
        "quote",
        "audit",
        "consulting",
        "builder",
        "roofing",
        "plumbing",
        "fence",
        "hvac",
        "solar",
        "design",
        "marketing",
    }
)

Detector = Callable[[ProspectProfile], list[IssueEvidence]]


def run_detectors(profile: ProspectProfile, detectors: Iterable[Detector] | None = None) -> tuple[IssueEvidence, ...]:
    selected = tuple(detectors or DEFAULT_DETECTORS)
    issues: list[IssueEvidence] = []
    for detector in selected:
        issues.extend(detector(profile))
    issues.sort(
        key=lambda issue: (
            SEVERITY_ORDER.get(issue.severity, 99),
            issue.issue_id,
            issue.source_url,
        )
    )
    return tuple(issues)


def detect_missing_metadata(profile: ProspectProfile) -> list[IssueEvidence]:
    homepage = _homepage(profile)
    issues: list[IssueEvidence] = []
    title = homepage.title.strip()
    meta = homepage.meta_description.strip()
    if not title or len(title) < 18:
        issues.append(
            IssueEvidence(
                issue_id="weak_title_signal",
                category="metadata",
                severity="medium" if title else "high",
                confidence=0.94,
                source_url=homepage.final_url,
                summary="Homepage title is missing or too thin for strong intent capture.",
                explanation="Search listings and browser context rely on the title to state the core offer clearly.",
                evidence_snippet=f'title="{title}"',
                missing_data_flags=tuple(flag for flag in ("title",) if not title),
            )
        )
    if not meta or len(meta) < 50:
        issues.append(
            IssueEvidence(
                issue_id="missing_meta_description",
                category="metadata",
                severity="high" if not meta else "medium",
                confidence=0.97,
                source_url=homepage.final_url,
                summary="Homepage meta description is missing or too short.",
                explanation="A thin description weakens search click-through and makes the offer harder to evaluate quickly.",
                evidence_snippet=f'meta_description="{meta}"',
                missing_data_flags=tuple(flag for flag in ("meta_description",) if not meta),
            )
        )
    return issues


def detect_unclear_primary_offer(profile: ProspectProfile) -> list[IssueEvidence]:
    homepage = _homepage(profile)
    headline = (homepage.h1[0] if homepage.h1 else homepage.title).strip()
    body_excerpt = homepage.text[:180]
    keyword_hits = sum(1 for keyword in OFFER_KEYWORDS if keyword in f"{headline} {body_excerpt}".lower())
    headline_generic = headline.lower() in GENERIC_HEADLINES
    if headline and not headline_generic and keyword_hits >= 2:
        return []
    return [
        IssueEvidence(
            issue_id="unclear_primary_offer",
            category="messaging",
            severity="high",
            confidence=0.88,
            source_url=homepage.final_url,
            summary="Homepage does not state the primary service offer clearly.",
            explanation="The visible headline and lead copy stay generic, so buyers have to infer what the business actually sells.",
            evidence_snippet=f'headline="{headline}" body="{body_excerpt}"',
            missing_data_flags=tuple(flag for flag in ("headline",) if not headline),
        )
    ]


def detect_weak_cta_structure(profile: ProspectProfile) -> list[IssueEvidence]:
    pages = profile.pages or tuple()
    all_ctas = [cta.strip().lower() for page in pages for cta in page.cta_texts if cta.strip()]
    if not all_ctas:
        return [
            IssueEvidence(
                issue_id="weak_cta_structure",
                category="conversion",
                severity="high",
                confidence=0.93,
                source_url=_homepage(profile).final_url,
                summary="No clear call-to-action is visible on the sampled public pages.",
                explanation="A strong CTA is the shortest path from visitor intent to a quote, call, or form submission.",
                evidence_snippet="cta_texts=[]",
                missing_data_flags=("cta",),
            )
        ]
    specific_ctas = [cta for cta in all_ctas if cta not in GENERIC_CTA_TEXTS]
    if specific_ctas:
        return []
    return [
        IssueEvidence(
            issue_id="weak_cta_structure",
            category="conversion",
            severity="medium",
            confidence=0.86,
            source_url=_homepage(profile).final_url,
            summary="Visible calls-to-action are generic and low-commitment.",
            explanation="Generic CTA copy tends to underperform compared with service-specific intent capture.",
            evidence_snippet=f"cta_texts={sorted(set(all_ctas))}",
        )
    ]


def detect_missing_contact_affordance(profile: ProspectProfile) -> list[IssueEvidence]:
    channels = profile.contact_channels
    if any(channel.kind in {"email", "phone", "contact_form"} and channel.is_business for channel in channels):
        return []
    if any(channel.kind == "contact_page" for channel in channels):
        return [
            IssueEvidence(
                issue_id="missing_direct_contact_affordance",
                category="conversion",
                severity="medium",
                confidence=0.81,
                source_url=_homepage(profile).final_url,
                summary="The site exposes a contact page but not a direct business contact method in sampled pages.",
                explanation="Prospects convert faster when phone, email, or form access is obvious from the main path.",
                evidence_snippet=f"contact_channels={[channel.kind for channel in channels]}",
            )
        ]
    return [
        IssueEvidence(
            issue_id="missing_contact_affordance",
            category="conversion",
            severity="high",
            confidence=0.95,
            source_url=_homepage(profile).final_url,
            summary="No direct public contact affordance was found in sampled pages.",
            explanation="Without a clear phone, email, form, or contact page, high-intent traffic has no obvious next step.",
            evidence_snippet=f"contact_channels={[channel.kind for channel in channels]}",
            missing_data_flags=("contact_channel",),
        )
    ]


def detect_missing_business_schema(profile: ProspectProfile) -> list[IssueEvidence]:
    schema_types = {schema_type for page in profile.pages for schema_type in page.schema_types}
    if schema_types & BUSINESS_SCHEMA_TYPES:
        return []
    homepage = _homepage(profile)
    return [
        IssueEvidence(
            issue_id="missing_business_schema",
            category="seo",
            severity="medium",
            confidence=0.9,
            source_url=homepage.final_url,
            summary="No business or service schema markup was found in sampled pages.",
            explanation="Structured data helps search engines understand the business, services, and trust signals.",
            evidence_snippet=f"schema_types={sorted(schema_types)}",
            missing_data_flags=("schema_markup",),
        )
    ]


def detect_heavy_homepage_payload(profile: ProspectProfile) -> list[IssueEvidence]:
    homepage = _homepage(profile)
    if homepage.html_bytes < 150_000 and homepage.script_count < 8 and homepage.image_count < 12:
        return []
    severity = "high" if homepage.html_bytes >= 250_000 or homepage.script_count >= 12 else "medium"
    return [
        IssueEvidence(
            issue_id="heavy_homepage_payload",
            category="performance",
            severity=severity,
            confidence=0.82,
            source_url=homepage.final_url,
            summary="Homepage payload hints at avoidable performance drag.",
            explanation="Large HTML, many scripts, or heavy image counts often correlate with slower load and weaker mobile conversion.",
            evidence_snippet=(
                f"html_bytes={homepage.html_bytes} scripts={homepage.script_count} images={homepage.image_count}"
            ),
        )
    ]


DEFAULT_DETECTORS: tuple[Detector, ...] = (
    detect_missing_metadata,
    detect_unclear_primary_offer,
    detect_weak_cta_structure,
    detect_missing_contact_affordance,
    detect_missing_business_schema,
    detect_heavy_homepage_payload,
)


def _homepage(profile: ProspectProfile) -> FetchedPage:
    if profile.homepage is None:
        raise ValueError("revenue audit detectors require at least one fetched page")
    return profile.homepage
