"""Elastic-ready telemetry documents for JJ-N events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nontrading.models import Account, ApprovalRequest, Meeting, Message, Outcome, Proposal, TelemetryEvent
from nontrading.store import RevenueStore

PHASE0_EVENT_TYPES = {
    "account_researched",
    "approval_decision",
    "approval_gate",
    "fulfillment_status_changed",
    "message_sent",
    "reply_received",
    "meeting_booked",
    "proposal_sent",
    "outcome_recorded",
    "cycle_complete",
}

DEFAULT_EVENTS_PATH = Path(__file__).with_name("events.jsonl")
UTC = timezone.utc
DEFAULT_ECS_VERSION = "8.11.0"
NONTRADING_EVENT_DATASET = "elastifund.nontrading"
EVENT_METADATA = {
    "account_researched": {
        "engine": "account_intelligence",
        "pipeline_stage": "research",
        "event_alias": "jjn.account.researched",
    },
    "approval_decision": {
        "engine": "approval",
        "pipeline_stage": "approval",
        "event_alias": "jjn.approval.decision",
    },
    "approval_gate": {
        "engine": "approval",
        "pipeline_stage": "approval",
        "event_alias": "jjn.approval.gate",
    },
    "fulfillment_status_changed": {
        "engine": "fulfillment",
        "pipeline_stage": "fulfillment",
        "event_alias": "jjn.fulfillment.status.changed",
    },
    "message_sent": {
        "engine": "outreach",
        "pipeline_stage": "outreach",
        "event_alias": "jjn.outreach.sent",
    },
    "reply_received": {
        "engine": "interaction",
        "pipeline_stage": "interaction",
        "event_alias": "jjn.interaction.reply_received",
    },
    "meeting_booked": {
        "engine": "interaction",
        "pipeline_stage": "interaction",
        "event_alias": "jjn.interaction.meeting_booked",
    },
    "proposal_sent": {
        "engine": "proposal",
        "pipeline_stage": "proposal",
        "event_alias": "jjn.proposal.sent",
    },
    "outcome_recorded": {
        "engine": "learning",
        "pipeline_stage": "learning",
        "event_alias": "jjn.outcome.recorded",
    },
    "cycle_complete": {
        "engine": "revenue_pipeline",
        "pipeline_stage": "pipeline",
        "event_alias": "jjn.cycle.complete",
    },
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _event_metadata(event_type: str, payload: Mapping[str, Any]) -> dict[str, str]:
    configured = EVENT_METADATA.get(event_type, {})
    engine = str(payload.get("engine") or configured.get("engine") or "unknown")
    pipeline_stage = str(payload.get("pipeline_stage") or payload.get("stage") or configured.get("pipeline_stage") or engine)
    event_alias = str(payload.get("event_alias") or configured.get("event_alias") or event_type)
    return {
        "engine": engine,
        "pipeline_stage": pipeline_stage,
        "event_alias": event_alias,
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _gross_margin_pct(revenue: float, gross_margin: float) -> float | None:
    if revenue <= 0:
        return None
    return round(gross_margin / revenue, 6)


def _fulfillment_status_for_outcome(outcome: Outcome) -> str:
    explicit = str(outcome.metadata.get("fulfillment_status", "")).strip().lower()
    if explicit:
        return explicit
    if str(outcome.status).strip().lower() in {"won", "simulated_won"}:
        return "delivery_pending"
    if str(outcome.status).strip().lower() in {"lost", "simulated_lost"}:
        return "not_applicable"
    return "awaiting_outcome"


def _cycle_summary_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    outreach_sent = int(report.get("outreach_sent", 0) or 0)
    replies_recorded = int(report.get("replies_recorded", 0) or 0)
    meetings_booked = int(report.get("meetings_booked", 0) or 0)
    proposals_sent = int(report.get("proposals_sent", 0) or 0)
    outcomes_recorded = int(report.get("outcomes_recorded", 0) or 0)
    return {
        "cycle_id": str(report.get("cycle_id", "revenue_pipeline")),
        "started_at": str(report.get("started_at", "")),
        "completed_at": str(report.get("completed_at", "")),
        "status": str(report.get("status", "completed")),
        "reason": str(report.get("reason", "")),
        "blocked_stage": str(report.get("blocked_stage", "")),
        "scanned_leads": int(report.get("scanned_leads", 0) or 0),
        "suppressed_leads": int(report.get("suppressed_leads", 0) or 0),
        "skipped_existing": int(report.get("skipped_existing", 0) or 0),
        "accounts_researched": int(report.get("accounts_researched", 0) or 0),
        "qualified_accounts": int(report.get("qualified_accounts", 0) or 0),
        "outreach_attempted": int(report.get("outreach_attempted", 0) or 0),
        "outreach_sent": outreach_sent,
        "approval_pending": int(report.get("approval_pending", 0) or 0),
        "replies_recorded": replies_recorded,
        "meetings_booked": meetings_booked,
        "proposals_sent": proposals_sent,
        "outcomes_recorded": outcomes_recorded,
        "reply_rate": round((replies_recorded / outreach_sent), 6) if outreach_sent else None,
        "meeting_rate": round((meetings_booked / replies_recorded), 6) if replies_recorded else None,
        "proposal_rate": round((proposals_sent / meetings_booked), 6) if meetings_booked else None,
        "outcome_rate": round((outcomes_recorded / proposals_sent), 6) if proposals_sent else None,
    }


def build_ecs_document(
    *,
    event_type: str,
    timestamp: str,
    status: str,
    worker_name: str,
    environment: str,
    payload: Mapping[str, Any],
    ecs_version: str = DEFAULT_ECS_VERSION,
    entity_type: str | None = None,
    entity_id: str = "",
) -> dict[str, Any]:
    entity_id_value = str(entity_id)
    payload_dict = dict(payload)
    metadata = _event_metadata(event_type, payload_dict)
    document: dict[str, Any] = {
        "@timestamp": timestamp,
        "ecs": {"version": ecs_version},
        "event": {
            "kind": "event",
            "category": ["agent"],
            "type": ["info"],
            "action": event_type,
            "outcome": status,
            "dataset": NONTRADING_EVENT_DATASET,
        },
        "service": {
            "name": worker_name,
            "type": "nontrading",
        },
        "labels": {
            "environment": environment,
            "engine": metadata["engine"],
            "pipeline_stage": metadata["pipeline_stage"],
        },
        "elastifund": {
            "worker_family": "nontrading",
            "worker_name": worker_name,
            "event_type": event_type,
            "event_alias": metadata["event_alias"],
            "engine": metadata["engine"],
            "pipeline_stage": metadata["pipeline_stage"],
            "payload": payload_dict,
        },
        "payload": payload_dict,
    }
    if entity_type:
        document["entity"] = {"type": entity_type}
        if entity_id_value:
            document["entity"]["id"] = entity_id_value
    elif entity_id_value:
        document["entity"] = {"id": entity_id_value}
    if entity_id_value:
        document["related"] = {"id": [entity_id_value]}
    return document


class NonTradingTelemetry:
    """Records Phase 0 events in an Elastic-friendly shape."""

    def __init__(self, store: RevenueStore, *, system_name: str = "jj-n", environment: str = "paper"):
        self.store = store
        self.system_name = system_name
        self.environment = environment

    def emit(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        status: str = "recorded",
    ) -> TelemetryEvent:
        if event_type not in PHASE0_EVENT_TYPES:
            raise ValueError(f"Unsupported Phase 0 event type: {event_type}")
        enriched_payload = {
            "system_name": self.system_name,
            "environment": self.environment,
            **(payload or {}),
        }
        return self.store.record_telemetry_event(
            TelemetryEvent(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                status=status,
                payload=enriched_payload,
            )
        )

    def build_document(self, event: TelemetryEvent) -> dict[str, Any]:
        return build_ecs_document(
            event_type=event.event_type,
            timestamp=event.created_at or utc_now(),
            status=event.status,
            worker_name=str(event.payload.get("system_name", self.system_name)),
            environment=str(event.payload.get("environment", self.environment)),
            payload=event.payload,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
        )

    def account_researched(self, account: Account, *, source: str, notes: str = "") -> TelemetryEvent:
        return self.emit(
            event_type="account_researched",
            entity_type="account",
            entity_id=str(account.id or ""),
            payload={
                "account_name": account.name,
                "account_domain": account.domain_normalized,
                "source": source,
                "notes": notes,
            },
        )

    def approval_decision(self, request: ApprovalRequest) -> TelemetryEvent:
        reviewed_latency_hours = None
        if request.created_at and request.reviewed_at:
            created = datetime.fromisoformat(request.created_at.replace("Z", "+00:00"))
            reviewed = datetime.fromisoformat(request.reviewed_at.replace("Z", "+00:00"))
            reviewed_latency_hours = round(max((reviewed - created).total_seconds() / 3600.0, 0.0), 6)
        return self.emit(
            event_type="approval_decision",
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            status=request.status,
            payload={
                "request_id": request.id or 0,
                "action_type": request.action_type,
                "summary": request.summary,
                "requested_by": request.requested_by,
                "reviewed_by": request.reviewed_by,
                "review_notes": request.review_notes,
                "created_at": request.created_at or "",
                "reviewed_at": request.reviewed_at or "",
                "review_latency_hours": reviewed_latency_hours,
            },
        )

    def message_sent(self, message: Message) -> TelemetryEvent:
        return self.emit(
            event_type="message_sent",
            entity_type="message",
            entity_id=str(message.id or ""),
            payload={
                "account_id": message.account_id,
                "opportunity_id": message.opportunity_id or 0,
                "contact_id": message.contact_id or 0,
                "recipient_email": message.recipient_email_normalized,
                "channel": message.channel,
            },
        )

    def reply_received(self, message: Message) -> TelemetryEvent:
        return self.emit(
            event_type="reply_received",
            entity_type="message",
            entity_id=str(message.id or ""),
            payload={
                "account_id": message.account_id,
                "opportunity_id": message.opportunity_id or 0,
                "contact_id": message.contact_id or 0,
                "channel": message.channel,
            },
        )

    def meeting_booked(self, meeting: Meeting) -> TelemetryEvent:
        return self.emit(
            event_type="meeting_booked",
            entity_type="meeting",
            entity_id=str(meeting.id or ""),
            payload={
                "account_id": meeting.account_id,
                "opportunity_id": meeting.opportunity_id or 0,
                "contact_id": meeting.contact_id or 0,
                "scheduled_for": meeting.scheduled_for,
                "owner": meeting.owner,
            },
        )

    def proposal_sent(self, proposal: Proposal) -> TelemetryEvent:
        return self.emit(
            event_type="proposal_sent",
            entity_type="proposal",
            entity_id=str(proposal.id or ""),
            payload={
                "account_id": proposal.account_id,
                "opportunity_id": proposal.opportunity_id,
                "contact_id": proposal.contact_id or 0,
                "amount": proposal.amount,
                "currency": proposal.currency,
            },
        )

    def outcome_recorded(self, outcome: Outcome) -> TelemetryEvent:
        revenue = _safe_float(outcome.revenue)
        gross_margin = _safe_float(outcome.gross_margin)
        event = self.emit(
            event_type="outcome_recorded",
            entity_type="outcome",
            entity_id=str(outcome.id or ""),
            payload={
                "account_id": outcome.account_id,
                "opportunity_id": outcome.opportunity_id,
                "proposal_id": outcome.proposal_id or 0,
                "status": outcome.status,
                "revenue": revenue,
                "gross_margin": gross_margin,
                "gross_margin_pct": _gross_margin_pct(revenue, gross_margin),
                "is_closed_won": str(outcome.status).strip().lower() in {"won", "simulated_won"},
                "is_revenue_realized": str(outcome.status).strip().lower() == "won" and revenue > 0.0,
                "is_simulated": bool(outcome.metadata.get("simulated")),
            },
        )
        fulfillment_status = _fulfillment_status_for_outcome(outcome)
        self.fulfillment_status_changed(
            account_id=outcome.account_id,
            opportunity_id=outcome.opportunity_id,
            outcome_id=outcome.id or 0,
            status=fulfillment_status,
            revenue=revenue,
            gross_margin=gross_margin,
            is_simulated=bool(outcome.metadata.get("simulated")),
        )
        return event

    def fulfillment_status_changed(
        self,
        *,
        account_id: int,
        opportunity_id: int,
        outcome_id: int,
        status: str,
        revenue: float = 0.0,
        gross_margin: float = 0.0,
        is_simulated: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> TelemetryEvent:
        payload = {
            "account_id": account_id,
            "opportunity_id": opportunity_id,
            "outcome_id": outcome_id,
            "fulfillment_status": status,
            "revenue": revenue,
            "gross_margin": gross_margin,
            "gross_margin_pct": _gross_margin_pct(revenue, gross_margin),
            "is_simulated": is_simulated,
        }
        if metadata:
            payload.update(dict(metadata))
        return self.emit(
            event_type="fulfillment_status_changed",
            entity_type="opportunity",
            entity_id=str(opportunity_id),
            status=status,
            payload=payload,
        )

    def cycle_completed(
        self,
        report: Mapping[str, Any],
        *,
        status: str = "recorded",
    ) -> TelemetryEvent:
        summary = _cycle_summary_payload(report)
        return self.emit(
            event_type="cycle_complete",
            entity_type="pipeline",
            entity_id=str(report.get("cycle_id", "revenue_pipeline")),
            payload={
                **summary,
                "report": dict(report),
            },
            status=status,
        )


class TelemetryBridge:
    """Write Elastic-compatible Phase 0 events to a local JSONL sink."""

    def __init__(
        self,
        output_path: str | Path | None = None,
        *,
        worker_name: str = "jj-n",
        environment: str = "paper",
        ecs_version: str = DEFAULT_ECS_VERSION,
    ):
        self.output_path = Path(output_path) if output_path is not None else DEFAULT_EVENTS_PATH
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.worker_name = worker_name
        self.environment = environment
        self.ecs_version = ecs_version

    def emit(self, event: Mapping[str, Any]) -> dict[str, Any]:
        document = self.format_event(event)
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(document, sort_keys=True) + "\n")
        return document

    def format_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        if self.is_ecs_compatible(event):
            return dict(event)
        event_type = str(event.get("event_type", "unknown"))
        timestamp = str(event.get("timestamp") or event.get("@timestamp") or utc_now())
        status = str(event.get("status") or event.get("result") or "recorded")
        entity_id = str(event.get("id") or event.get("interaction_id") or event.get("lead_id") or "")
        entity_type = event.get("entity_type")
        return build_ecs_document(
            event_type=event_type,
            timestamp=timestamp,
            status=status,
            worker_name=self.worker_name,
            environment=self.environment,
            payload=event,
            ecs_version=self.ecs_version,
            entity_type=str(entity_type) if entity_type else None,
            entity_id=entity_id,
        )

    @staticmethod
    def is_ecs_compatible(document: Mapping[str, Any]) -> bool:
        event = document.get("event")
        ecs = document.get("ecs")
        service = document.get("service")
        labels = document.get("labels")
        return bool(
            isinstance(document.get("@timestamp"), str)
            and isinstance(event, Mapping)
            and isinstance(ecs, Mapping)
            and isinstance(service, Mapping)
            and isinstance(labels, Mapping)
            and "action" in event
            and "dataset" in event
            and "version" in ecs
            and "name" in service
            and "environment" in labels
        )

    def read_all(self) -> list[dict[str, Any]]:
        if not self.output_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
