"""Elastic-ready telemetry documents for JJ-N events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nontrading.models import Account, Meeting, Message, Outcome, Proposal, TelemetryEvent
from nontrading.store import RevenueStore

PHASE0_EVENT_TYPES = {
    "account_researched",
    "message_sent",
    "reply_received",
    "meeting_booked",
    "proposal_sent",
    "outcome_recorded",
}

DEFAULT_EVENTS_PATH = Path(__file__).with_name("events.jsonl")
UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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
        return {
            "@timestamp": event.created_at,
            "event": {
                "action": event.event_type,
                "category": "nontrading",
                "status": event.status,
            },
            "elastifund": {
                "worker_family": "nontrading",
                "worker_name": self.system_name,
                "environment": event.payload.get("environment", self.environment),
            },
            "entity": {
                "type": event.entity_type,
                "id": event.entity_id,
            },
            "payload": event.payload,
        }

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
        return self.emit(
            event_type="outcome_recorded",
            entity_type="outcome",
            entity_id=str(outcome.id or ""),
            payload={
                "account_id": outcome.account_id,
                "opportunity_id": outcome.opportunity_id,
                "proposal_id": outcome.proposal_id or 0,
                "status": outcome.status,
                "revenue": outcome.revenue,
                "gross_margin": outcome.gross_margin,
            },
        )


class TelemetryBridge:
    """Write Elastic-compatible Phase 0 events to a local JSONL sink."""

    def __init__(
        self,
        output_path: str | Path | None = None,
        *,
        worker_name: str = "jj-n",
        environment: str = "paper",
        ecs_version: str = "8.11.0",
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
        event_type = str(event.get("event_type", "unknown"))
        timestamp = str(event.get("timestamp") or event.get("@timestamp") or utc_now())
        status = str(event.get("status") or event.get("result") or "recorded")
        entity_id = str(event.get("id") or event.get("interaction_id") or event.get("lead_id") or "")

        document: dict[str, Any] = {
            "@timestamp": timestamp,
            "ecs": {"version": self.ecs_version},
            "event": {
                "kind": "event",
                "category": ["agent"],
                "type": ["info"],
                "action": event_type,
                "outcome": status,
            },
            "service": {
                "name": self.worker_name,
                "type": "nontrading",
            },
            "labels": {
                "environment": self.environment,
            },
            "elastifund": {
                "worker_family": "nontrading",
                "worker_name": self.worker_name,
                "payload": dict(event),
            },
        }
        if entity_id:
            document["related"] = {"id": [entity_id]}
        return document

    @staticmethod
    def is_ecs_compatible(document: Mapping[str, Any]) -> bool:
        event = document.get("event")
        ecs = document.get("ecs")
        return bool(
            isinstance(document.get("@timestamp"), str)
            and isinstance(event, Mapping)
            and isinstance(ecs, Mapping)
            and "action" in event
            and "version" in ecs
        )

    def read_all(self) -> list[dict[str, Any]]:
        if not self.output_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
