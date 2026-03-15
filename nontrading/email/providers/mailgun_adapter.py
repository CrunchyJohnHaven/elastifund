"""Minimal Mailgun adapter behind an opt-in env flag."""

from __future__ import annotations

import base64
from urllib import error, parse, request

from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import BaseSender, DeliveryResult, NotConfiguredError
from nontrading.models import OutboxMessage
from nontrading.store import RevenueStore


class MailgunSender(BaseSender):
    provider_name = "mailgun"

    def __init__(self, settings: RevenueAgentSettings, store: RevenueStore):
        super().__init__(settings, store)
        if not settings.mailgun_api_key or not settings.mailgun_domain:
            raise NotConfiguredError(
                "MAILGUN_API_KEY and MAILGUN_DOMAIN are required when JJ_REVENUE_PROVIDER=mailgun"
            )
        self.api_key = settings.mailgun_api_key
        self.domain = settings.mailgun_domain

    def send(self, message: OutboxMessage) -> DeliveryResult:
        blocked = self._preflight(message)
        if blocked is not None:
            return blocked

        headers = {
            f"h:{header_name}": header_value
            for header_name, header_value in message.headers.items()
        }
        payload = {
            "from": f"{self.settings.from_name} <{message.from_email}>",
            "to": message.recipient_email,
            "subject": message.subject,
            "text": message.body,
            **headers,
        }
        endpoint = f"https://api.mailgun.net/v3/{self.domain}/messages"
        data = parse.urlencode(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            data=data,
            method="POST",
            headers={
                "Authorization": "Basic "
                + base64.b64encode(f"api:{self.api_key}".encode("utf-8")).decode("ascii"),
                "Content-Type": "application/x-www-form-urlencoded",
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
