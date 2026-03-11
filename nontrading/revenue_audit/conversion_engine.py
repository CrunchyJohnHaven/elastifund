"""Stage teaser, proposal, and follow-up conversion packets for revenue-audit prospects."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nontrading.campaigns.sequences import SequenceRunner, SequenceState
from nontrading.compliance import ComplianceDecision, ComplianceGuard
from nontrading.config import RevenueAgentSettings, is_placeholder_domain, normalize_domain_for_checks
from nontrading.email.sender import DryRunSender
from nontrading.engines.proposal import ProposalEngine
from nontrading.models import Account, Campaign, Contact, Lead, Message, Opportunity, Proposal, utc_now
from nontrading.offers.website_growth_audit import WEBSITE_GROWTH_AUDIT, ServiceOffer
from nontrading.revenue_audit.acquisition_bridge import (
    CHECKOUT_PATH_HINT,
    LANDING_PAGE_SLUG,
    AcquisitionBridgeArtifact,
    RevenueAuditAcquisitionBridge,
    SenderVerification,
    build_sender_verification,
)
from nontrading.store import RevenueStore

PACKET_SCHEMA_VERSION = "revenue_audit_conversion_packet.v1"
SUMMARY_SCHEMA_VERSION = "revenue_audit_conversion_summary.v1"
DEFAULT_SUMMARY_PATH = Path("reports/nontrading/revenue_audit_conversion_summary.json")
DEFAULT_PACKET_DIR = Path("reports/nontrading/conversion_packets")
CONVERSION_MESSAGE_METADATA_KEY = "revenue_audit_conversion_message"
CONVERSION_PROPOSAL_METADATA_KEY = "revenue_audit_conversion_proposal"
FOLLOW_UP_MESSAGE_STATUS = "follow_up_staged"
MANUAL_FOLLOW_UP_STATUS = "manual_follow_up_preview"


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


def _slugify_company(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower())
    return normalized.strip("-") or "prospect"


def _merge_metadata(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            merged.update(item)
    return merged


def _first_evidence_detail(evidence: list[dict[str, Any]], *source_fields: str) -> str:
    if not source_fields:
        source_fields = ("website_findings", "specific_finding", "conversion_issue", "seo_issue", "competitor_gap")
    for source_field in source_fields:
        for item in evidence:
            if _nonempty_text(item.get("source_field")) != source_field:
                continue
            detail = _nonempty_text(item.get("detail")) or _nonempty_text(item.get("label"))
            if detail:
                return detail
    for item in evidence:
        detail = _nonempty_text(item.get("detail")) or _nonempty_text(item.get("label"))
        if detail:
            return detail
    return ""


def _url_is_placeholder(url: str) -> bool:
    parsed = urlparse(_nonempty_text(url))
    host = parsed.netloc or parsed.path
    return is_placeholder_domain(host)


def load_acquisition_bridge_payload(input_path: Path) -> dict[str, Any]:
    return json.loads(input_path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ConversionPacket:
    company_name: str
    account_id: int
    opportunity_id: int
    contact_id: int | None
    lead_id: int | None
    launch_mode: str
    website_url: str
    fit_score: float
    estimated_value_usd: float
    teaser_evidence_summary: str
    issue_highlights: tuple[str, ...]
    quick_win: str
    recommended_price_tier: dict[str, Any]
    teaser: dict[str, Any]
    proposal: dict[str, Any]
    checkout_cta: dict[str, Any]
    follow_up: dict[str, Any]
    sender_verification: dict[str, Any]
    compliance: dict[str, Any]
    live_send_allowed: bool
    operator_next_action: str
    manual_close_packet: dict[str, Any] = field(default_factory=dict)
    packet_path: str = ""
    schema_version: str = PACKET_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issue_highlights"] = list(self.issue_highlights)
        return payload


@dataclass(frozen=True)
class ConversionSummary:
    launch_mode: str
    offer_slug: str
    offer_name: str
    sender_verification: dict[str, Any]
    source_artifact: str | None
    source_bridge_path: str | None
    selected_prospects: int
    staged_packets: int
    staged_proposals: int
    staged_follow_ups: int
    manual_follow_up_only: int
    live_send_ready: int
    compliance_blocked: int
    placeholder_checkout_urls: int
    packets: tuple[dict[str, Any], ...]
    schema_version: str = SUMMARY_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["packets"] = list(self.packets)
        return payload


class RevenueAuditConversionEngine:
    """Stage proposal and follow-up assets from the launch bridge without sending them."""

    def __init__(
        self,
        store: RevenueStore,
        settings: RevenueAgentSettings,
        *,
        offer: ServiceOffer = WEBSITE_GROWTH_AUDIT,
        compliance_guard: ComplianceGuard | None = None,
        proposal_engine: ProposalEngine | None = None,
        sequence_runner: SequenceRunner | None = None,
    ):
        self.store = store
        self.settings = settings
        self.offer = offer
        verified_domain = normalize_domain_for_checks(settings.from_email)
        self.compliance_guard = compliance_guard or ComplianceGuard(
            store,
            verified_domains={verified_domain},
            daily_message_limit=settings.daily_send_quota,
        )
        self.proposal_engine = proposal_engine or ProposalEngine(store=store)
        self.sequence_runner = sequence_runner or SequenceRunner(
            store,
            DryRunSender(settings, store),
            settings,
        )

    def build_from_store(self) -> tuple[ConversionSummary, tuple[ConversionPacket, ...]]:
        bridge = RevenueAuditAcquisitionBridge(self.store, self.settings).build_artifact()
        return self.build_artifact(bridge)

    def build_artifact(
        self,
        bridge_artifact: AcquisitionBridgeArtifact | dict[str, Any],
        *,
        source_bridge_path: Path | None = None,
    ) -> tuple[ConversionSummary, tuple[ConversionPacket, ...]]:
        bridge_payload = (
            bridge_artifact.to_dict() if isinstance(bridge_artifact, AcquisitionBridgeArtifact) else dict(bridge_artifact)
        )
        sender_verification = build_sender_verification(self.settings)
        launch_mode = _nonempty_text(bridge_payload.get("launch_mode")) or "manual_close_only"
        staged_packets = tuple(
            self._stage_packet(
                packet_payload,
                launch_mode=launch_mode,
                sender_verification=sender_verification,
            )
            for packet_payload in bridge_payload.get("prospects", ())
            if isinstance(packet_payload, dict)
        )
        summary = ConversionSummary(
            launch_mode=launch_mode,
            offer_slug=_nonempty_text(bridge_payload.get("offer_slug")) or self.offer.slug,
            offer_name=_nonempty_text(bridge_payload.get("offer_name")) or self.offer.name,
            sender_verification=sender_verification.to_dict(),
            source_artifact=_nonempty_text(bridge_payload.get("source_artifact")) or None,
            source_bridge_path=str(source_bridge_path) if source_bridge_path is not None else None,
            selected_prospects=int(bridge_payload.get("selected_prospects") or len(staged_packets)),
            staged_packets=len(staged_packets),
            staged_proposals=sum(1 for packet in staged_packets if int(packet.proposal.get("proposal_id") or 0) > 0),
            staged_follow_ups=sum(1 for packet in staged_packets if int(packet.follow_up.get("message_id") or 0) > 0),
            manual_follow_up_only=sum(1 for packet in staged_packets if packet.follow_up.get("status") == MANUAL_FOLLOW_UP_STATUS),
            live_send_ready=sum(1 for packet in staged_packets if packet.live_send_allowed),
            compliance_blocked=sum(1 for packet in staged_packets if not bool(packet.compliance.get("allowed"))),
            placeholder_checkout_urls=sum(
                1 for packet in staged_packets if bool(packet.checkout_cta.get("url_is_placeholder"))
            ),
            packets=tuple(
                {
                    "company_name": packet.company_name,
                    "opportunity_id": packet.opportunity_id,
                    "launch_mode": packet.launch_mode,
                    "proposal_id": packet.proposal.get("proposal_id"),
                    "follow_up_message_id": packet.follow_up.get("message_id"),
                    "live_send_allowed": packet.live_send_allowed,
                    "operator_next_action": packet.operator_next_action,
                    "packet_path": packet.packet_path,
                }
                for packet in staged_packets
            ),
        )
        return summary, staged_packets

    def _stage_packet(
        self,
        packet_payload: dict[str, Any],
        *,
        launch_mode: str,
        sender_verification: SenderVerification,
    ) -> ConversionPacket:
        account_id = int(packet_payload.get("account_id") or 0)
        opportunity_id = int(packet_payload.get("opportunity_id") or 0)
        contact_id = int(packet_payload.get("contact_id") or 0) or None
        lead_email = _nonempty_text(packet_payload.get("recipient_email"))

        account = self.store.get_account(account_id) if account_id else None
        opportunity = self.store.get_opportunity(opportunity_id) if opportunity_id else None
        contact = self.store.get_contact(contact_id) if contact_id else None
        lead = self._build_lead(packet_payload, account=account, contact=contact, opportunity=opportunity)
        evidence = [
            item
            for item in packet_payload.get("evidence", ())
            if isinstance(item, dict)
        ]
        issue_highlights = tuple(str(item) for item in packet_payload.get("issue_highlights", ()) if _nonempty_text(item))
        compliance = self._evaluate_compliance(lead_email)
        checkout_cta = self._build_checkout_cta(packet_payload, launch_mode=launch_mode)
        live_send_allowed = bool(
            sender_verification.live_send_eligible
            and compliance.allowed
            and launch_mode == "approval_queue_only"
            and not bool(checkout_cta["url_is_placeholder"])
        )
        teaser_message = self._get_teaser_message(packet_payload)
        proposal = self.proposal_engine.ensure_staged_proposal(
            Proposal(
                account_id=account_id,
                opportunity_id=opportunity_id,
                contact_id=contact_id,
                title=f"{self.offer.name} Proposal for {_nonempty_text(packet_payload.get('company_name'))}",
                status="draft",
                amount=float(packet_payload.get("recommended_price_tier", {}).get("price_usd") or self.offer.price_range[0]),
                summary=self._proposal_summary(packet_payload, evidence),
                metadata={
                    CONVERSION_PROPOSAL_METADATA_KEY: True,
                    "offer_slug": self.offer.slug,
                    "launch_mode": launch_mode,
                    "selection_angle": packet_payload.get("selection_angle"),
                    "issue_highlights": list(issue_highlights),
                    "quick_win": packet_payload.get("quick_win"),
                    "checkout_cta_url": checkout_cta["url"],
                    "checkout_api_path": checkout_cta["api_path"],
                    "recommended_price_tier": dict(packet_payload.get("recommended_price_tier") or {}),
                    "source_message_id": packet_payload.get("message_id") or 0,
                },
            ),
            metadata_match={
                CONVERSION_PROPOSAL_METADATA_KEY: True,
                "offer_slug": self.offer.slug,
            },
        )
        follow_up = self._stage_follow_up(
            lead,
            packet_payload,
            launch_mode=launch_mode,
            teaser_message=teaser_message,
            checkout_cta=checkout_cta,
        )
        operator_next_action = self._operator_next_action(
            packet_payload,
            launch_mode=launch_mode,
            sender_verification=sender_verification,
            compliance=compliance,
            checkout_cta=checkout_cta,
        )
        packet = ConversionPacket(
            company_name=_nonempty_text(packet_payload.get("company_name")),
            account_id=account_id,
            opportunity_id=opportunity_id,
            contact_id=contact_id,
            lead_id=int(packet_payload.get("lead_id") or 0) or None,
            launch_mode=launch_mode,
            website_url=_nonempty_text(packet_payload.get("website_url")),
            fit_score=round(float(packet_payload.get("fit_score") or 0.0), 2),
            estimated_value_usd=round(float(packet_payload.get("estimated_value_usd") or 0.0), 2),
            teaser_evidence_summary=self._teaser_summary(packet_payload, evidence),
            issue_highlights=issue_highlights,
            quick_win=_nonempty_text(packet_payload.get("quick_win")),
            recommended_price_tier=dict(packet_payload.get("recommended_price_tier") or {}),
            teaser={
                "message_id": packet_payload.get("message_id"),
                "approval_request_id": packet_payload.get("approval_request_id"),
                "approval_status": _nonempty_text(packet_payload.get("approval_status")) or "not_required",
                "selection_angle": _nonempty_text(packet_payload.get("selection_angle")),
                "subject": _nonempty_text(packet_payload.get("teaser_subject")),
                "body": _nonempty_text(packet_payload.get("teaser_body")),
                "status": teaser_message.status if teaser_message is not None else "manual_preview_only",
            },
            proposal={
                "proposal_id": proposal.id,
                "status": proposal.status,
                "title": proposal.title,
                "amount_usd": round(float(proposal.amount), 2),
                "summary": proposal.summary,
            },
            checkout_cta=checkout_cta,
            follow_up=follow_up,
            sender_verification=sender_verification.to_dict(),
            compliance={
                "allowed": compliance.allowed,
                "reason": compliance.reason,
                "metadata": compliance.metadata,
            },
            live_send_allowed=live_send_allowed,
            operator_next_action=operator_next_action,
            manual_close_packet=dict(packet_payload.get("manual_close_packet") or {}),
        )
        self._sync_opportunity_metadata(
            opportunity,
            proposal_id=proposal.id,
            follow_up_message_id=follow_up.get("message_id"),
            operator_next_action=operator_next_action,
        )
        return packet

    def _build_lead(
        self,
        packet_payload: dict[str, Any],
        *,
        account: Account | None,
        contact: Contact | None,
        opportunity: Opportunity | None,
    ) -> Lead:
        email = _nonempty_text(packet_payload.get("recipient_email"))
        existing = self.store.get_lead_by_email(email) if email else None
        evidence = [
            item
            for item in packet_payload.get("evidence", ())
            if isinstance(item, dict)
        ]
        merged_metadata = _merge_metadata(
            account.metadata if account is not None else None,
            contact.metadata if contact is not None else None,
            existing.metadata if existing is not None else None,
            opportunity.metadata if opportunity is not None else None,
        )
        first_detail = _first_evidence_detail(evidence)
        website_url = _nonempty_text(packet_payload.get("website_url"))
        if not website_url and account is not None:
            website_url = account.website_url
        merged_metadata.update(
            {
                "website_url": website_url,
                "website_findings": _first_evidence_detail(
                    evidence,
                    "website_findings",
                    "specific_finding",
                    "conversion_issue",
                    "seo_issue",
                )
                or first_detail,
                "competitor_gap": _first_evidence_detail(evidence, "competitor_gap"),
                "quick_win": _nonempty_text(packet_payload.get("quick_win")),
                "specific_finding": first_detail,
                "contact_name": contact.full_name if contact is not None else merged_metadata.get("contact_name", ""),
                "full_name": contact.full_name if contact is not None else merged_metadata.get("full_name", ""),
                "role": contact.role if contact is not None else merged_metadata.get("role", ""),
                "recommended_price_tier_label": _nonempty_text(
                    packet_payload.get("recommended_price_tier", {}).get("label")
                ),
            }
        )
        return Lead(
            id=existing.id if existing is not None else int(packet_payload.get("lead_id") or 0) or None,
            email=email,
            company_name=_nonempty_text(packet_payload.get("company_name")) or (existing.company_name if existing else ""),
            country_code=_nonempty_text(packet_payload.get("country_code")) or (existing.country_code if existing else "US"),
            source="revenue_audit_bridge",
            explicit_opt_in=bool(existing.explicit_opt_in) if existing is not None else False,
            metadata=merged_metadata,
            created_at=existing.created_at if existing is not None else None,
            updated_at=existing.updated_at if existing is not None else None,
        )

    def _evaluate_compliance(self, recipient_email: str) -> ComplianceDecision:
        if not recipient_email:
            return ComplianceDecision(allowed=False, reason="recipient_missing_email")
        return self.compliance_guard.evaluate_outreach(
            sender_name=self.settings.from_name,
            sender_email=self.settings.from_email,
            recipient_email=recipient_email,
        )

    def _build_checkout_cta(self, packet_payload: dict[str, Any], *, launch_mode: str) -> dict[str, Any]:
        landing_page_hint = _nonempty_text(packet_payload.get("landing_page_hint"))
        if not landing_page_hint:
            landing_page_hint = f"{self.settings.public_base_url.rstrip('/')}/{LANDING_PAGE_SLUG}"
        return {
            "label": f"Buy the {self.offer.name}",
            "url": landing_page_hint,
            "api_path": _nonempty_text(packet_payload.get("checkout_path_hint")) or CHECKOUT_PATH_HINT,
            "launch_mode": launch_mode,
            "url_is_placeholder": _url_is_placeholder(landing_page_hint),
            "operator_note": "Use the hosted offer URL when it is live; otherwise keep checkout as a staged CTA only.",
        }

    def _proposal_summary(self, packet_payload: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        first_detail = _first_evidence_detail(evidence) or "one clear conversion blocker"
        quick_win = _nonempty_text(packet_payload.get("quick_win")) or "three same-week fixes"
        return (
            f"{self.offer.delivery_days}-day {self.offer.name} for {_nonempty_text(packet_payload.get('company_name'))} "
            f"covering {first_detail}, prioritized quick wins, and a checkout-ready remediation plan. "
            f"Immediate quick win: {quick_win}"
        )

    def _teaser_summary(self, packet_payload: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        first_detail = _first_evidence_detail(evidence) or "a public-web issue"
        return (
            f"Lead with {first_detail}, then anchor the pitch to the "
            f"{_nonempty_text(packet_payload.get('recommended_price_tier', {}).get('label')) or 'recommended'} "
            f"price tier and the recurring-monitor upsell."
        )

    def _get_teaser_message(self, packet_payload: dict[str, Any]) -> Message | None:
        message_id = int(packet_payload.get("message_id") or 0)
        if message_id <= 0:
            return None
        return self.store.get_message(message_id)

    def _ensure_follow_up_campaign(self, launch_mode: str) -> Campaign:
        name = f"{self.offer.slug}-{launch_mode}-follow-up"
        existing = self.store.get_campaign_by_name(name)
        if existing is not None:
            return existing
        return self.store.create_campaign(
            Campaign(
                name=name,
                subject_template=f"{self.offer.name} follow-up",
                body_template="staged follow-up preview",
                daily_send_quota=self.settings.daily_send_quota,
                allowed_countries=self.settings.allowed_countries,
                metadata={
                    "offer_slug": self.offer.slug,
                    "launch_mode": launch_mode,
                    "staged_only": True,
                },
            )
        )

    def _stage_follow_up(
        self,
        lead: Lead,
        packet_payload: dict[str, Any],
        *,
        launch_mode: str,
        teaser_message: Message | None,
        checkout_cta: dict[str, Any],
    ) -> dict[str, Any]:
        initial_angle = _nonempty_text(packet_payload.get("selection_angle"))
        state = SequenceState(sent_angles=(initial_angle,) if initial_angle else ())
        campaign = self._ensure_follow_up_campaign(launch_mode)
        if lead.email:
            plan = self.sequence_runner.plan_due_step(
                lead,
                self.offer,
                campaign,
                days_since_start=3,
                state=state,
            )
            if plan is None:
                return {}
            message = self._ensure_follow_up_message(
                packet_payload,
                plan=plan,
                launch_mode=launch_mode,
                teaser_message=teaser_message,
                checkout_cta=checkout_cta,
            )
            return {
                "message_id": message.id,
                "status": message.status,
                "approval_status": message.approval_status,
                "step_number": plan.planned_step.step_number,
                "day_offset": plan.planned_step.day_offset,
                "label": plan.planned_step.label,
                "angle": plan.planned_step.angle,
                "subject": message.subject,
                "body": message.body,
            }
        planned_step = self.sequence_runner.sequence.next_step(
            lead,
            self.offer,
            self.sequence_runner.selector,
            days_since_start=3,
            state=state,
        )
        if planned_step is None:
            return {}
        return self._manual_follow_up_preview(packet_payload, planned_step, checkout_cta)

    def _ensure_follow_up_message(
        self,
        packet_payload: dict[str, Any],
        *,
        plan,
        launch_mode: str,
        teaser_message: Message | None,
        checkout_cta: dict[str, Any],
    ) -> Message:
        opportunity_id = int(packet_payload.get("opportunity_id") or 0)
        for existing in self.store.list_messages(opportunity_id=opportunity_id):
            if not bool(existing.metadata.get(CONVERSION_MESSAGE_METADATA_KEY)):
                continue
            if int(existing.metadata.get("sequence_step_number") or 0) != plan.planned_step.step_number:
                continue
            return existing
        return self.store.create_message(
            Message(
                account_id=int(packet_payload.get("account_id") or 0),
                opportunity_id=opportunity_id,
                contact_id=int(packet_payload.get("contact_id") or 0) or None,
                recipient_email=_nonempty_text(packet_payload.get("recipient_email")),
                subject=plan.selection.rendered_email.subject,
                body=plan.selection.rendered_email.body,
                status=FOLLOW_UP_MESSAGE_STATUS,
                requires_approval=(launch_mode == "approval_queue_only"),
                approval_status="pending" if launch_mode == "approval_queue_only" else "not_required",
                sender_name=self.settings.from_name,
                sender_email=self.settings.from_email,
                metadata={
                    CONVERSION_MESSAGE_METADATA_KEY: True,
                    "offer_slug": self.offer.slug,
                    "launch_mode": launch_mode,
                    "sequence_step_number": plan.planned_step.step_number,
                    "sequence_day_offset": plan.planned_step.day_offset,
                    "sequence_label": plan.planned_step.label,
                    "sequence_angle": plan.planned_step.angle,
                    "source_teaser_message_id": teaser_message.id if teaser_message is not None else 0,
                    "checkout_cta_url": checkout_cta["url"],
                    "checkout_api_path": checkout_cta["api_path"],
                },
            )
        )

    def _manual_follow_up_preview(
        self,
        packet_payload: dict[str, Any],
        planned_step,
        checkout_cta: dict[str, Any],
    ) -> dict[str, Any]:
        manual_close_packet = dict(packet_payload.get("manual_close_packet") or {})
        price_usd = int(packet_payload.get("recommended_price_tier", {}).get("price_usd") or self.offer.price_range[0])
        primary_contact_path = _nonempty_text(manual_close_packet.get("primary_contact_path")) or "the primary public contact path"
        quick_win = _nonempty_text(packet_payload.get("quick_win")) or "the clearest same-week quick win"
        return {
            "message_id": None,
            "status": MANUAL_FOLLOW_UP_STATUS,
            "approval_status": "not_required",
            "step_number": planned_step.step_number,
            "day_offset": planned_step.day_offset,
            "label": planned_step.label,
            "angle": planned_step.angle,
            "subject": f"{_nonempty_text(packet_payload.get('company_name'))}: manual follow-up after the audit teaser",
            "body": (
                f"Follow up on {quick_win}. Re-anchor the offer at ${price_usd:,}, point the buyer to "
                f"{checkout_cta['url']}, and keep the first touch human-reviewed through {primary_contact_path}."
            ),
        }

    def _operator_next_action(
        self,
        packet_payload: dict[str, Any],
        *,
        launch_mode: str,
        sender_verification: SenderVerification,
        compliance: ComplianceDecision,
        checkout_cta: dict[str, Any],
    ) -> str:
        if bool(checkout_cta["url_is_placeholder"]):
            return "wait_for_live_offer_url"
        if launch_mode == "manual_close_only" and not _nonempty_text(packet_payload.get("recipient_email")):
            return "review_manual_close_packet"
        if not sender_verification.live_send_eligible:
            return "review_manual_close_packet"
        if not compliance.allowed:
            return "resolve_compliance_blocker"
        if launch_mode == "approval_queue_only":
            approval_status = _nonempty_text(packet_payload.get("approval_status")) or "pending"
            return "dispatch_teaser" if approval_status == "approved" else "approve_teaser_then_send"
        return "human_review_teaser_then_send"

    def _sync_opportunity_metadata(
        self,
        opportunity: Opportunity | None,
        *,
        proposal_id: int | None,
        follow_up_message_id: int | None,
        operator_next_action: str,
    ) -> None:
        if opportunity is None:
            return
        metadata = dict(opportunity.metadata)
        metadata["conversion_packet"] = {
            "generated_at": utc_now(),
            "proposal_id": proposal_id or 0,
            "follow_up_message_id": follow_up_message_id or 0,
            "operator_next_action": operator_next_action,
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
                next_action=operator_next_action,
                metadata=metadata,
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
            )
        )


def write_conversion_artifacts(
    summary: ConversionSummary,
    packets: tuple[ConversionPacket, ...],
    *,
    summary_output: Path = DEFAULT_SUMMARY_PATH,
    packet_dir: Path = DEFAULT_PACKET_DIR,
) -> tuple[Path, tuple[Path, ...], ConversionSummary, tuple[ConversionPacket, ...]]:
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_paths: list[Path] = []
    persisted_packets: list[ConversionPacket] = []
    for packet in packets:
        packet_path = packet_dir / f"{packet.opportunity_id}_{_slugify_company(packet.company_name)}.json"
        persisted_packet = replace(packet, packet_path=str(packet_path))
        packet_path.write_text(
            json.dumps(persisted_packet.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        packet_paths.append(packet_path)
        persisted_packets.append(persisted_packet)
    persisted_summary = replace(
        summary,
        packets=tuple(
            {
                **dict(item),
                "packet_path": str(packet_paths[index]),
            }
            for index, item in enumerate(summary.packets)
        ),
    )
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(persisted_summary.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary_output, tuple(packet_paths), persisted_summary, tuple(persisted_packets)
