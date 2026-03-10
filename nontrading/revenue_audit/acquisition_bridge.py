"""Hybrid acquisition bridge for the Website Growth Audit launch lane."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from nontrading.approval import ApprovalGate
from nontrading.campaigns.template_selector import TemplateSelector
from nontrading.config import RevenueAgentSettings, is_placeholder_domain, normalize_domain_for_checks
from nontrading.models import Account, Contact, Lead, Message, Opportunity, normalize_country, utc_now
from nontrading.offers.website_growth_audit import WEBSITE_GROWTH_AUDIT, ServiceOffer
from nontrading.store import RevenueStore

SCHEMA_VERSION = "revenue_audit_acquisition_bridge.v2"
DEFAULT_OUTPUT_PATH = Path("reports/nontrading/revenue_audit_launch_bridge.json")
CURATED_BATCH_LIMIT = 10
CURATED_METADATA_KEYS = (
    "curated_launch_batch",
    "launch_ready",
    "node9_curated",
    "human_review_batch",
)
APPROVAL_ACTION_TYPE = "revenue_audit_launch_teaser"
MESSAGE_METADATA_KEY = "revenue_audit_bridge"
CHECKOUT_PATH_HINT = "/v1/nontrading/offers/website-growth-audit"
LANDING_PAGE_SLUG = "website-growth-audit"
MESSAGE_STATUS_BY_APPROVAL = {
    "approved": "approval_granted",
    "pending": "pending_approval",
    "rejected": "blocked",
    "not_required": "draft",
}
EVIDENCE_FIELD_LABELS = (
    ("website_findings", "Website issue"),
    ("specific_finding", "Specific finding"),
    ("competitor_gap", "Competitor gap"),
    ("seo_issue", "SEO issue"),
    ("conversion_issue", "Conversion issue"),
)


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


def _merge_metadata(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            merged.update(item)
    return merged


def _is_curated(metadata: dict[str, Any]) -> bool:
    for key in CURATED_METADATA_KEYS:
        value = metadata.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "launch", "curated"}:
            return True
    return False


def _first_present(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                token = _nonempty_text(item)
                if token:
                    return token
            continue
        token = _nonempty_text(value)
        if token:
            return token
    return ""


@dataclass(frozen=True)
class SenderVerification:
    provider: str
    sender_email: str
    sender_domain: str
    sender_domain_verified: bool
    live_send_eligible: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceSnippet:
    label: str
    detail: str
    source_field: str
    source_url: str = ""
    severity: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class LandingPageCTAOptimization:
    key: str
    title: str
    proposed_cta: str
    rationale: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ProspectContext:
    account: Account
    contact: Contact | None
    lead: Lead
    opportunity: Opportunity
    country_code: str
    website_url: str
    evidence: tuple[EvidenceSnippet, ...]
    contact_channels: tuple[dict[str, Any], ...]
    quick_win: str
    recommended_price_tier: dict[str, Any]
    source_artifact: str | None = None


@dataclass(frozen=True)
class ProspectPacket:
    account_id: int
    opportunity_id: int
    lead_id: int | None
    contact_id: int | None
    company_name: str
    recipient_email: str
    website_url: str
    country_code: str
    fit_score: float
    estimated_value_usd: float
    launch_mode: str
    selection_angle: str
    teaser_subject: str
    teaser_body: str
    issue_highlights: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    contact_channels: tuple[dict[str, Any], ...]
    recommended_price_tier: dict[str, Any]
    quick_win: str
    checkout_path_hint: str
    landing_page_hint: str
    next_step: str
    message_id: int | None = None
    approval_request_id: int | None = None
    approval_status: str = ""
    manual_close_talk_track: tuple[str, ...] = ()
    manual_close_packet: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issue_highlights"] = list(self.issue_highlights)
        payload["evidence"] = list(self.evidence)
        payload["contact_channels"] = list(self.contact_channels)
        payload["manual_close_talk_track"] = list(self.manual_close_talk_track)
        return payload


@dataclass(frozen=True)
class AcquisitionBridgeArtifact:
    schema_version: str
    generated_at: str
    launch_mode: str
    offer_slug: str
    offer_name: str
    sender_verification: dict[str, Any]
    source_artifact: str | None
    curated_candidates: int
    selected_prospects: int
    overflow_count: int
    skipped_uncurated: int
    skipped_non_us: int
    skipped_missing_contact: int
    skipped_missing_evidence: int
    landing_page_cta_optimizations: tuple[dict[str, str], ...]
    prospects: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["landing_page_cta_optimizations"] = list(self.landing_page_cta_optimizations)
        payload["prospects"] = list(self.prospects)
        return payload


@dataclass(frozen=True)
class CandidateSelection:
    candidates: tuple[ProspectContext, ...]
    skipped_uncurated: int = 0
    skipped_non_us: int = 0
    skipped_missing_contact: int = 0
    skipped_missing_evidence: int = 0


def build_sender_verification(settings: RevenueAgentSettings) -> SenderVerification:
    sender_domain = normalize_domain_for_checks(settings.from_email)
    provider = settings.provider.lower()

    if not _nonempty_text(settings.from_name) or "@" not in _nonempty_text(settings.from_email):
        return SenderVerification(
            provider=provider,
            sender_email=settings.from_email,
            sender_domain=sender_domain,
            sender_domain_verified=settings.sender_domain_verified,
            live_send_eligible=False,
            reason="sender_identity_unverified",
        )
    if provider in {"dry_run", "dry-run"}:
        return SenderVerification(
            provider=provider,
            sender_email=settings.from_email,
            sender_domain=sender_domain,
            sender_domain_verified=settings.sender_domain_verified,
            live_send_eligible=False,
            reason="provider_dry_run",
        )
    if is_placeholder_domain(sender_domain):
        return SenderVerification(
            provider=provider,
            sender_email=settings.from_email,
            sender_domain=sender_domain,
            sender_domain_verified=settings.sender_domain_verified,
            live_send_eligible=False,
            reason="placeholder_sender_domain",
        )
    if provider == "sendgrid" and not _nonempty_text(settings.sendgrid_api_key):
        return SenderVerification(
            provider=provider,
            sender_email=settings.from_email,
            sender_domain=sender_domain,
            sender_domain_verified=settings.sender_domain_verified,
            live_send_eligible=False,
            reason="provider_not_configured",
        )
    if provider == "mailgun" and (not _nonempty_text(settings.mailgun_api_key) or not _nonempty_text(settings.mailgun_domain)):
        return SenderVerification(
            provider=provider,
            sender_email=settings.from_email,
            sender_domain=sender_domain,
            sender_domain_verified=settings.sender_domain_verified,
            live_send_eligible=False,
            reason="provider_not_configured",
        )
    if not settings.sender_domain_verified:
        return SenderVerification(
            provider=provider,
            sender_email=settings.from_email,
            sender_domain=sender_domain,
            sender_domain_verified=settings.sender_domain_verified,
            live_send_eligible=False,
            reason="sender_domain_unverified",
        )
    return SenderVerification(
        provider=provider,
        sender_email=settings.from_email,
        sender_domain=sender_domain,
        sender_domain_verified=settings.sender_domain_verified,
        live_send_eligible=True,
        reason="live_sender_ready",
    )


class RevenueAuditAcquisitionBridge:
    """Stage a curated, approval-gated acquisition batch for the Website Growth Audit."""

    def __init__(
        self,
        store: RevenueStore,
        settings: RevenueAgentSettings,
        *,
        offer: ServiceOffer = WEBSITE_GROWTH_AUDIT,
        max_prospects: int = CURATED_BATCH_LIMIT,
    ):
        self.store = store
        self.settings = settings
        self.offer = offer
        self.max_prospects = max(1, int(max_prospects))
        self.selector = TemplateSelector(settings)
        self.approval_gate = ApprovalGate(store, paper_mode=True)

    def build_artifact(self) -> AcquisitionBridgeArtifact:
        verification = build_sender_verification(self.settings)
        launch_mode = "approval_queue_only" if verification.live_send_eligible else "manual_close_only"
        selection = self._collect_candidates(launch_mode=launch_mode)
        selected = list(selection.candidates[: self.max_prospects])
        overflow_count = max(len(selection.candidates) - len(selected), 0)
        packets = [
            self._materialize_packet(context, verification=verification, launch_mode=launch_mode)
            for context in selected
        ]
        ctas = self._landing_page_cta_optimizations(selected) if launch_mode == "manual_close_only" else ()
        source_artifact = next((context.source_artifact for context in selected if context.source_artifact), None)
        return AcquisitionBridgeArtifact(
            schema_version=SCHEMA_VERSION,
            generated_at=utc_now(),
            launch_mode=launch_mode,
            offer_slug=self.offer.slug,
            offer_name=self.offer.name,
            sender_verification=verification.to_dict(),
            source_artifact=source_artifact,
            curated_candidates=len(selection.candidates),
            selected_prospects=len(packets),
            overflow_count=overflow_count,
            skipped_uncurated=selection.skipped_uncurated,
            skipped_non_us=selection.skipped_non_us,
            skipped_missing_contact=selection.skipped_missing_contact,
            skipped_missing_evidence=selection.skipped_missing_evidence,
            landing_page_cta_optimizations=tuple(item.to_dict() for item in ctas),
            prospects=tuple(packet.to_dict() for packet in packets),
        )

    def _collect_candidates(self, *, launch_mode: str) -> CandidateSelection:
        candidates: list[ProspectContext] = []
        skipped_uncurated = 0
        skipped_non_us = 0
        skipped_missing_contact = 0
        skipped_missing_evidence = 0
        seen_accounts: set[int] = set()

        for opportunity in self.store.list_opportunities():
            if opportunity.account_id in seen_accounts:
                continue
            account = self.store.get_account(opportunity.account_id)
            if account is None:
                continue
            contact = self._primary_contact(opportunity.account_id)
            merged_metadata = _merge_metadata(account.metadata, contact.metadata if contact else None, opportunity.metadata)
            if not _is_curated(merged_metadata):
                skipped_uncurated += 1
                continue
            lead = self._lead_for_context(
                account,
                contact,
                opportunity,
                allow_blank_email=(launch_mode == "manual_close_only"),
            )
            if lead is None:
                skipped_missing_contact += 1
                continue
            merged_metadata = _merge_metadata(account.metadata, contact.metadata if contact else None, lead.metadata, opportunity.metadata)
            country_code = normalize_country(
                _first_present(
                    merged_metadata,
                    "country_code",
                    "country",
                )
                or lead.country_code
            )
            if country_code != "US":
                skipped_non_us += 1
                continue
            evidence = self._extract_evidence(merged_metadata)
            if not evidence:
                skipped_missing_evidence += 1
                continue
            contact_channels = self._contact_channels(merged_metadata, contact, lead, website_url_hint=account.website_url)
            if launch_mode == "approval_queue_only" and not _nonempty_text(lead.email):
                skipped_missing_contact += 1
                continue
            if launch_mode == "manual_close_only" and not self._manual_close_contact_ready(contact_channels, lead):
                skipped_missing_contact += 1
                continue
            website_url = _first_present(merged_metadata, "website_url") or account.website_url.strip()
            if not website_url and account.domain_normalized:
                website_url = f"https://{account.domain_normalized}"
            candidates.append(
                ProspectContext(
                    account=account,
                    contact=contact,
                    lead=lead,
                    opportunity=opportunity,
                    country_code=country_code,
                    website_url=website_url,
                    evidence=evidence,
                    contact_channels=contact_channels,
                    quick_win=_first_present(merged_metadata, "quick_win") or self._default_quick_win(evidence),
                    recommended_price_tier=self._recommended_price_tier(
                        merged_metadata,
                        float(opportunity.estimated_value),
                    ),
                    source_artifact=_first_present(merged_metadata, "launch_batch_source_artifact", "source_artifact") or None,
                )
            )
            seen_accounts.add(opportunity.account_id)

        candidates.sort(
            key=lambda item: (
                float(item.opportunity.score),
                float(item.opportunity.estimated_value),
                item.account.updated_at or "",
            ),
            reverse=True,
        )
        return CandidateSelection(
            candidates=tuple(candidates),
            skipped_uncurated=skipped_uncurated,
            skipped_non_us=skipped_non_us,
            skipped_missing_contact=skipped_missing_contact,
            skipped_missing_evidence=skipped_missing_evidence,
        )

    def _materialize_packet(
        self,
        context: ProspectContext,
        *,
        verification: SenderVerification,
        launch_mode: str,
    ) -> ProspectPacket:
        issue_highlights = tuple(
            f"{item.label}: {item.detail}"
            for item in context.evidence[:3]
        )
        landing_page_hint = f"{self.settings.public_base_url.rstrip('/')}/{LANDING_PAGE_SLUG}"
        manual_close_only = launch_mode == "manual_close_only"
        has_email = _nonempty_text(context.lead.email) != ""
        if manual_close_only and not has_email:
            selection_angle = self._manual_selection_angle(context)
            teaser_subject, teaser_body = self._manual_close_teaser(
                context,
                issue_highlights=issue_highlights,
                landing_page_hint=landing_page_hint,
            )
            message = None
        else:
            selection = self.selector.select(
                context.lead,
                self.offer,
                campaign_name=f"revenue-audit-{launch_mode}",
            )
            selection_angle = selection.angle
            teaser_subject = selection.rendered_email.subject
            teaser_body = selection.rendered_email.body
            message = self._ensure_message(
                context,
                launch_mode=launch_mode,
                subject=teaser_subject,
                body=teaser_body,
                selection_angle=selection_angle,
                issue_highlights=issue_highlights,
                verification_reason=verification.reason,
                landing_page_hint=landing_page_hint,
            )

        approval_request_id: int | None = None
        approval_status = "not_required"
        next_step = "manual_close_packet"
        manual_close_talk_track = self._manual_close_talk_track(context, issue_highlights)
        manual_close_packet = self._manual_close_packet(
            context,
            issue_highlights=issue_highlights,
            landing_page_hint=landing_page_hint,
        )

        if launch_mode == "approval_queue_only":
            if message is None:
                raise ValueError("approval_queue_only launch mode requires a deliverable outbound message")
            decision = self.approval_gate.require_approval(
                action_type=APPROVAL_ACTION_TYPE,
                entity_type="message",
                entity_id=str(message.id or 0),
                summary=f"Approve Website Growth Audit teaser for {context.account.name}",
                payload={
                    "account_id": context.account.id or 0,
                    "opportunity_id": context.opportunity.id or 0,
                    "contact_id": context.contact.id if context.contact is not None else 0,
                    "issue_highlights": list(issue_highlights),
                    "selection_angle": selection_angle,
                    "checkout_path_hint": CHECKOUT_PATH_HINT,
                },
                requested_by="node9.revenue_audit_bridge",
            )
            approval_status = decision.request_status
            approval_request_id = decision.request.id if decision.request is not None else None
            status = MESSAGE_STATUS_BY_APPROVAL.get(approval_status, "pending_approval")
            message = self.store.update_message_status(
                message.id or 0,
                status=status,
                approval_status=approval_status,
                sender_name=self.settings.from_name,
                sender_email=self.settings.from_email,
                metadata={
                    "approval_request_id": approval_request_id,
                    "approval_reason": decision.reason,
                    "verification_reason": verification.reason,
                },
            )
            next_step = "human_review_send" if approval_status != "approved" else "dispatch_after_review"
            manual_close_talk_track = ()
        else:
            if message is not None:
                message = self.store.update_message_status(
                    message.id or 0,
                    status="manual_close_ready",
                    approval_status="not_required",
                    sender_name=self.settings.from_name,
                    sender_email=self.settings.from_email,
                    metadata={
                        "verification_reason": verification.reason,
                        "manual_close_only": True,
                    },
                )

        self._sync_opportunity_metadata(
            context.opportunity,
            launch_mode=launch_mode,
            message_id=message.id if message is not None else None,
            approval_request_id=approval_request_id,
            next_step=next_step,
            issue_highlights=issue_highlights,
        )

        return ProspectPacket(
            account_id=context.account.id or 0,
            opportunity_id=context.opportunity.id or 0,
            lead_id=context.lead.id,
            contact_id=context.contact.id if context.contact is not None else None,
            company_name=context.account.name,
            recipient_email=context.lead.email,
            website_url=context.website_url,
            country_code=context.country_code,
            fit_score=float(context.opportunity.score),
            estimated_value_usd=float(context.opportunity.estimated_value),
            launch_mode=launch_mode,
            selection_angle=selection_angle,
            teaser_subject=teaser_subject,
            teaser_body=teaser_body,
            issue_highlights=issue_highlights,
            evidence=tuple(item.to_dict() for item in context.evidence),
            contact_channels=context.contact_channels,
            recommended_price_tier=context.recommended_price_tier,
            quick_win=context.quick_win,
            checkout_path_hint=CHECKOUT_PATH_HINT,
            landing_page_hint=landing_page_hint,
            next_step=next_step,
            message_id=message.id if message is not None else None,
            approval_request_id=approval_request_id,
            approval_status=approval_status,
            manual_close_talk_track=manual_close_talk_track,
            manual_close_packet=manual_close_packet,
        )

    def _ensure_message(
        self,
        context: ProspectContext,
        *,
        launch_mode: str,
        subject: str,
        body: str,
        selection_angle: str,
        issue_highlights: tuple[str, ...],
        verification_reason: str,
        landing_page_hint: str,
    ) -> Message:
        existing = self._existing_bridge_message(context.opportunity.id or 0, launch_mode)
        if existing is not None:
            return existing
        metadata = {
            MESSAGE_METADATA_KEY: True,
            "offer_slug": self.offer.slug,
            "launch_mode": launch_mode,
            "selection_angle": selection_angle,
            "issue_highlights": list(issue_highlights),
            "verification_reason": verification_reason,
            "checkout_path_hint": CHECKOUT_PATH_HINT,
            "landing_page_hint": landing_page_hint,
        }
        return self.store.create_message(
            Message(
                account_id=context.account.id or 0,
                opportunity_id=context.opportunity.id,
                contact_id=context.contact.id if context.contact is not None else None,
                recipient_email=context.lead.email,
                subject=subject,
                body=body,
                status="draft",
                approval_status="pending",
                sender_name=self.settings.from_name,
                sender_email=self.settings.from_email,
                metadata=metadata,
            )
        )

    def _existing_bridge_message(self, opportunity_id: int, launch_mode: str) -> Message | None:
        for message in self.store.list_messages(opportunity_id=opportunity_id):
            if not bool(message.metadata.get(MESSAGE_METADATA_KEY)):
                continue
            if str(message.metadata.get("offer_slug")) != self.offer.slug:
                continue
            if str(message.metadata.get("launch_mode")) != launch_mode:
                continue
            return message
        return None

    def _sync_opportunity_metadata(
        self,
        opportunity: Opportunity,
        *,
        launch_mode: str,
        message_id: int | None,
        approval_request_id: int | None,
        next_step: str,
        issue_highlights: tuple[str, ...],
    ) -> None:
        launch_metadata = dict(opportunity.metadata)
        launch_metadata["launch_bridge"] = {
            "generated_at": utc_now(),
            "launch_mode": launch_mode,
            "message_id": message_id or 0,
            "approval_request_id": approval_request_id or 0,
            "issue_highlights": list(issue_highlights),
        }
        self.store.upsert_opportunity(
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
                next_action=next_step,
                metadata=launch_metadata,
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
            )
        )

    def _primary_contact(self, account_id: int) -> Contact | None:
        contacts = self.store.list_contacts(account_id=account_id)
        return contacts[0] if contacts else None

    def _lead_for_context(
        self,
        account: Account,
        contact: Contact | None,
        opportunity: Opportunity,
        *,
        allow_blank_email: bool = False,
    ) -> Lead | None:
        contact_email = contact.email if contact is not None else _first_present(account.metadata, "lead_email", "contact_email")
        merged_metadata = _merge_metadata(account.metadata, contact.metadata if contact else None, opportunity.metadata)
        if not _nonempty_text(contact_email):
            if not allow_blank_email:
                return None
            full_name = contact.full_name if contact is not None else _first_present(merged_metadata, "contact_name", "full_name")
            role = contact.role if contact is not None else _first_present(merged_metadata, "role", "title")
            return Lead(
                email="",
                company_name=account.name,
                country_code=normalize_country(_first_present(merged_metadata, "country_code", "country")),
                source="curated_launch_batch",
                explicit_opt_in=False,
                metadata={
                    **merged_metadata,
                    "contact_name": full_name,
                    "full_name": full_name,
                    "role": role,
                    "website_url": _first_present(merged_metadata, "website_url") or account.website_url,
                },
            )
        existing_lead = self.store.get_lead_by_email(contact_email)
        if existing_lead is not None:
            return Lead(
                id=existing_lead.id,
                email=existing_lead.email,
                company_name=existing_lead.company_name or account.name,
                country_code=existing_lead.country_code,
                source=existing_lead.source,
                explicit_opt_in=existing_lead.explicit_opt_in,
                opt_in_recorded_at=existing_lead.opt_in_recorded_at,
                metadata=_merge_metadata(existing_lead.metadata, merged_metadata),
                created_at=existing_lead.created_at,
                updated_at=existing_lead.updated_at,
            )
        full_name = contact.full_name if contact is not None else _first_present(merged_metadata, "contact_name", "full_name")
        role = contact.role if contact is not None else _first_present(merged_metadata, "role", "title")
        return Lead(
            email=contact_email,
            company_name=account.name,
            country_code=normalize_country(_first_present(merged_metadata, "country_code", "country")),
            source="curated_launch_batch",
            explicit_opt_in=bool(merged_metadata.get("explicit_opt_in")),
            metadata={
                **merged_metadata,
                "contact_name": full_name,
                "full_name": full_name,
                "role": role,
                "website_url": _first_present(merged_metadata, "website_url") or account.website_url,
            },
        )

    def _extract_evidence(self, metadata: dict[str, Any]) -> tuple[EvidenceSnippet, ...]:
        evidence: list[EvidenceSnippet] = []
        seen_details: set[str] = set()

        raw_issue_evidence = metadata.get("issue_evidence")
        if isinstance(raw_issue_evidence, (list, tuple)):
            for item in raw_issue_evidence:
                if isinstance(item, dict):
                    detail = _first_present(item, "detail", "summary", "finding", "evidence")
                    label = _first_present(item, "title", "label", "issue_type", "source") or "Issue evidence"
                    source_field = _first_present(item, "source_field", "source", "issue_id") or "issue_evidence"
                    source_url = _first_present(item, "source_url", "url")
                    severity = _first_present(item, "severity")
                else:
                    detail = _nonempty_text(item)
                    label = "Issue evidence"
                    source_field = "issue_evidence"
                    source_url = ""
                    severity = ""
                if not detail or detail in seen_details:
                    continue
                seen_details.add(detail)
                evidence.append(
                    EvidenceSnippet(
                        label=label,
                        detail=detail,
                        source_field=source_field,
                        source_url=source_url,
                        severity=severity,
                    )
                )
                if len(evidence) >= 3:
                    return tuple(evidence)

        for field_name, label in EVIDENCE_FIELD_LABELS:
            detail = _first_present(metadata, field_name)
            if not detail or detail in seen_details:
                continue
            seen_details.add(detail)
            evidence.append(EvidenceSnippet(label=label, detail=detail, source_field=field_name))
            if len(evidence) >= 3:
                break
        return tuple(evidence)

    def _manual_close_talk_track(
        self,
        context: ProspectContext,
        issue_highlights: tuple[str, ...],
    ) -> tuple[str, ...]:
        opening = issue_highlights[0] if issue_highlights else "Lead with one public-web issue found on the site."
        recommended_price = int(context.recommended_price_tier.get("price_usd") or self.offer.price_range[0])
        tier_label = _nonempty_text(context.recommended_price_tier.get("label")) or "recommended"
        contact_path = self._manual_close_contact_path(context.contact_channels)
        return (
            f"Open with: {opening}",
            (
                f"Offer the {self.offer.name} as the {tier_label} tier at ${recommended_price:,}, "
                f"with the {self.offer.delivery_days}-day delivery window and recurring monitor upsell."
            ),
            (
                f"Close by pointing the buyer to {CHECKOUT_PATH_HINT} once the offer page is live, "
                f"or use {contact_path} for the first human-reviewed reach-out."
            ),
        )

    def _contact_channels(
        self,
        metadata: dict[str, Any],
        contact: Contact | None,
        lead: Lead,
        *,
        website_url_hint: str = "",
    ) -> tuple[dict[str, Any], ...]:
        channels: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add_channel(kind: str, value: str, source_url: str = "", label: str = "", is_business: bool = True) -> None:
            key = (_nonempty_text(kind).lower(), _nonempty_text(value))
            if not key[0] or not key[1] or key in seen:
                return
            seen.add(key)
            channels.append(
                {
                    "kind": key[0],
                    "value": key[1],
                    "source_url": _nonempty_text(source_url) or _first_present(metadata, "public_contact_url", "website_url") or website_url_hint,
                    "label": _nonempty_text(label),
                    "is_business": bool(is_business),
                }
            )

        raw_channels = metadata.get("public_contact_channels")
        if isinstance(raw_channels, (list, tuple)):
            for item in raw_channels:
                if not isinstance(item, dict):
                    continue
                add_channel(
                    str(item.get("kind") or ""),
                    str(item.get("value") or ""),
                    source_url=str(item.get("source_url") or ""),
                    label=str(item.get("label") or ""),
                    is_business=bool(item.get("is_business", True)),
                )

        add_channel("email", lead.email, label=contact.full_name if contact is not None else "")
        if contact is not None:
            add_channel("phone", contact.phone, label=contact.full_name)
        public_contact_url = _first_present(metadata, "public_contact_url", "contact_url")
        if public_contact_url:
            kind = "contact_form" if "form" in public_contact_url.lower() else "contact_page"
            add_channel(kind, public_contact_url, source_url=public_contact_url, label="public_contact")
        return tuple(channels)

    def _manual_close_contact_ready(
        self,
        contact_channels: tuple[dict[str, Any], ...],
        lead: Lead,
    ) -> bool:
        if _nonempty_text(lead.email):
            return True
        return any(
            _nonempty_text(channel.get("kind")) in {"phone", "contact_form", "contact_page"}
            and _nonempty_text(channel.get("value"))
            for channel in contact_channels
        )

    def _manual_selection_angle(self, context: ProspectContext) -> str:
        if any(item.source_field == "competitor_gap" for item in context.evidence):
            return "angle_2_competitor_benchmark"
        if any(item.source_field in {"quick_win", "weak_cta_structure", "missing_contact_affordance"} for item in context.evidence):
            return "angle_3_quick_win"
        return "angle_1_growth_opportunity"

    def _manual_close_teaser(
        self,
        context: ProspectContext,
        *,
        issue_highlights: tuple[str, ...],
        landing_page_hint: str,
    ) -> tuple[str, str]:
        recommended_price = int(context.recommended_price_tier.get("price_usd") or self.offer.price_range[0])
        subject = f"{context.account.name}: 3 public-web fixes before the audit pitch"
        body = (
            f"{context.account.name} is a strong Website Growth Audit target. "
            f"We found {len(context.evidence)} public-web issues on {context.website_url}, starting with "
            f"{issue_highlights[0] if issue_highlights else 'one obvious conversion blocker'}. "
            f"Quick win: {context.quick_win} Recommend the {context.recommended_price_tier.get('label', 'recommended')} "
            f"tier at ${recommended_price:,}. Once checkout is live, send the buyer to {landing_page_hint}; "
            f"until then keep outreach human-reviewed and use the operator talk track below."
        )
        return subject, body

    def _manual_close_packet(
        self,
        context: ProspectContext,
        *,
        issue_highlights: tuple[str, ...],
        landing_page_hint: str,
    ) -> dict[str, Any]:
        evidence_urls = sorted({item.source_url for item in context.evidence if _nonempty_text(item.source_url)})
        return {
            "headline": f"{context.account.name}: same-day audit teaser",
            "summary": f"{len(context.evidence)} public-web issues found on {context.website_url}.",
            "recommended_price_tier": dict(context.recommended_price_tier),
            "quick_win": context.quick_win,
            "public_evidence_urls": evidence_urls,
            "primary_contact_path": self._manual_close_contact_path(context.contact_channels),
            "landing_page_cta": "Lead with proof, then offer the five-day audit plus recurring monitor.",
            "checkout_followup": landing_page_hint,
            "issue_highlights": list(issue_highlights),
        }

    def _manual_close_contact_path(self, contact_channels: tuple[dict[str, Any], ...]) -> str:
        for preferred_kind in ("email", "phone", "contact_form", "contact_page"):
            for channel in contact_channels:
                if _nonempty_text(channel.get("kind")) == preferred_kind and _nonempty_text(channel.get("value")):
                    return f"{preferred_kind}: {channel['value']}"
        return "a public contact path"

    def _recommended_price_tier(
        self,
        metadata: dict[str, Any],
        estimated_value_usd: float,
    ) -> dict[str, Any]:
        raw = metadata.get("recommended_price_tier")
        if isinstance(raw, dict):
            label = _nonempty_text(raw.get("label")) or "recommended"
            try:
                price_usd = int(float(raw.get("price_usd") or 0))
            except (TypeError, ValueError):
                price_usd = 0
            if price_usd > 0:
                return {"label": label, "price_usd": price_usd}
        if estimated_value_usd >= 1800.0:
            return {"label": "premium", "price_usd": 2500}
        if estimated_value_usd >= 1100.0:
            return {"label": "standard", "price_usd": 1500}
        return {"label": "starter", "price_usd": 500}

    def _default_quick_win(self, evidence: tuple[EvidenceSnippet, ...]) -> str:
        for item in evidence:
            if item.source_field == "heavy_homepage_payload":
                return "Trim homepage scripts and compress hero assets before the next paid traffic push."
            if item.source_field in {"weak_cta_structure", "missing_contact_affordance"}:
                return "Add a single Request Estimate CTA and make the fastest contact path visible above the fold."
            if item.source_field == "unclear_primary_offer":
                return "Rewrite the hero copy to name the exact service and service area in the first screen."
            if item.source_field == "missing_meta_description":
                return "Rewrite the homepage title and meta description around city-plus-service intent."
        return "Turn the clearest public-web issue into a same-week conversion fix."

    def _landing_page_cta_optimizations(
        self,
        contexts: list[ProspectContext],
    ) -> tuple[LandingPageCTAOptimization, ...]:
        competitor_packets = sum(
            1
            for context in contexts
            if any(item.source_field == "competitor_gap" for item in context.evidence)
        )
        quick_win_packets = sum(
            1
            for context in contexts
            if _nonempty_text(context.quick_win)
        )
        total_packets = len(contexts)
        return (
            LandingPageCTAOptimization(
                key="proof_first",
                title="Lead With Public-Web Proof",
                proposed_cta="See the exact issues we found before you buy the audit.",
                rationale=(
                    f"{total_packets} curated prospects were selected from evidence-backed website issues, "
                    "so the landing page should front-load proof instead of generic agency language."
                ),
            ),
            LandingPageCTAOptimization(
                key="competitor_gap",
                title="Offer A Benchmark CTA",
                proposed_cta="Compare your site against the local competitors already outranking you.",
                rationale=(
                    f"{competitor_packets} curated prospects showed competitor-gap evidence, "
                    "so benchmark language should be a visible secondary CTA."
                ),
            ),
            LandingPageCTAOptimization(
                key="quick_win",
                title="Close With A Fast Win",
                proposed_cta="Start with three quick wins in five days, then add the recurring monitor.",
                rationale=(
                    f"{quick_win_packets} curated prospects already have quick-win hooks, "
                    "so the fallback lane should emphasize speed and the monitor upsell."
                ),
            ),
        )


def write_acquisition_bridge_artifact(
    artifact: AcquisitionBridgeArtifact,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
