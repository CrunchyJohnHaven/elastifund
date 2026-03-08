"""Minimal SendGrid adapter behind an opt-in env flag."""

from __future__ import annotations

import json
from urllib import error, request

from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import BaseSender, DeliveryResult, NotConfiguredError
from nontrading.models import OutboxMessage
from nontrading.store import RevenueStore


class SendGridSender(BaseSender):
    provider_name = "sendgrid"
    endpoint = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, settings: RevenueAgentSettings, store: RevenueStore):
        super().__init__(settings, store)
        if not settings.sendgrid_api_key:
            raise NotConfiguredError("SENDGRID_API_KEY is required when JJ_REVENUE_PROVIDER=sendgrid")
        self.api_key = settings.sendgrid_api_key

    def send(self, message: OutboxMessage) -> DeliveryResult:
        blocked = self._preflight(message)
        if blocked is not None:
            return blocked

        payload = {
            "personalizations": [{"to": [{"email": message.recipient_email}]}],
            "from": {"email": message.from_email, "name": self.settings.from_name},
            "subject": message.subject,
            "content": [{"type": "text/plain", "value": message.body}],
            "headers": message.headers,
        }
        req = request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                status = "provider_accepted" if 200 <= response.status < 300 else "failed"
                detail = f"http {response.status}"
                transport_message_id = response.headers.get("X-Message-Id")
        except error.HTTPError as exc:
            status = "failed"
            detail = f"http {exc.code}"
            transport_message_id = None
        except error.URLError as exc:
            status = "failed"
            detail = f"network error: {exc.reason}"
            transport_message_id = None

        self.store.update_outbox_message_status(
            message.id or 0,
            status=status,
            detail=detail,
            transport_message_id=transport_message_id,
        )
        return DeliveryResult(
            provider=self.provider_name,
            status=status,
            detail=detail,
            transport_message_id=transport_message_id,
        )

