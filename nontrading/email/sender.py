"""Email sender abstraction with dry-run default behavior."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.email.validate import ValidationError, validate_outbox_message
from nontrading.models import OutboxMessage
from nontrading.store import RevenueStore

logger = logging.getLogger("nontrading.email")


class NotConfiguredError(RuntimeError):
    """Raised when a real email provider is requested without credentials."""


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    status: str
    detail: str = ""
    transport_message_id: str | None = None
    filesystem_path: str | None = None


class BaseSender:
    provider_name = "base"

    def __init__(self, settings: RevenueAgentSettings, store: RevenueStore):
        self.settings = settings
        self.store = store
        self.settings.ensure_paths()

    def _preflight(self, message: OutboxMessage) -> DeliveryResult | None:
        if self.store.is_suppressed(message.recipient_email):
            self.store.update_outbox_message_status(
                message.id or 0,
                status="suppressed",
                detail="recipient is present in suppression list",
            )
            return DeliveryResult(
                provider=self.provider_name,
                status="suppressed",
                detail="recipient is present in suppression list",
            )

        try:
            validate_outbox_message(message, self.settings.postal_address)
        except ValidationError as exc:
            self.store.update_outbox_message_status(
                message.id or 0,
                status="rejected",
                detail=str(exc),
            )
            return DeliveryResult(
                provider=self.provider_name,
                status="rejected",
                detail=str(exc),
            )

        return None

    def send(self, message: OutboxMessage) -> DeliveryResult:  # pragma: no cover - interface contract
        raise NotImplementedError


class DryRunSender(BaseSender):
    provider_name = "dry_run"

    def send(self, message: OutboxMessage) -> DeliveryResult:
        blocked = self._preflight(message)
        if blocked is not None:
            return blocked

        filesystem_path = self._write_message(message)
        self.store.update_outbox_message_status(
            message.id or 0,
            status="dry_run",
            detail="rendered to local outbox",
            filesystem_path=str(filesystem_path),
        )
        return DeliveryResult(
            provider=self.provider_name,
            status="dry_run",
            detail="rendered to local outbox",
            filesystem_path=str(filesystem_path),
        )

    def _write_message(self, message: OutboxMessage) -> Path:
        dated_dir = self.settings.outbox_dir / Path(message.created_at or "undated").name[:10]
        dated_dir.mkdir(parents=True, exist_ok=True)
        path = dated_dir / f"message_{message.id}.json"
        payload = {
            "campaign_id": message.campaign_id,
            "lead_id": message.lead_id,
            "recipient_email": message.recipient_email,
            "subject": message.subject,
            "body": message.body,
            "from_email": message.from_email,
            "headers": message.headers,
            "provider": self.provider_name,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return path


def build_sender(settings: RevenueAgentSettings, store: RevenueStore) -> BaseSender:
    provider = settings.provider.lower()
    if provider in {"dry_run", "dry-run"}:
        return DryRunSender(settings, store)
    if provider == "sendgrid":
        from nontrading.email.providers.sendgrid_adapter import SendGridSender

        return SendGridSender(settings, store)
    if provider == "mailgun":
        from nontrading.email.providers.mailgun_adapter import MailgunSender

        return MailgunSender(settings, store)
    raise ValueError(f"Unsupported revenue email provider: {settings.provider}")

