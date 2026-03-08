"""Hard validation for outbound marketing email payloads."""

from __future__ import annotations

import re

from nontrading.models import OutboxMessage


UNSUBSCRIBE_URL_RE = re.compile(r"<(https?://[^>]+)>")


class ValidationError(ValueError):
    """Raised when an outbound email fails a compliance requirement."""


def extract_unsubscribe_url(message: OutboxMessage) -> str | None:
    header_value = message.headers.get("List-Unsubscribe", "")
    match = UNSUBSCRIBE_URL_RE.search(header_value)
    if match is None:
        return None
    return match.group(1)


def validate_outbox_message(message: OutboxMessage, postal_address: str) -> None:
    if not message.subject.strip():
        raise ValidationError("subject is required")
    if not message.body.strip():
        raise ValidationError("body is required")
    if postal_address not in message.body:
        raise ValidationError("physical mailing address footer missing from body")

    if "List-Unsubscribe" not in message.headers:
        raise ValidationError("List-Unsubscribe header is required")
    if message.headers.get("List-Unsubscribe-Post") != "List-Unsubscribe=One-Click":
        raise ValidationError("List-Unsubscribe-Post must signal one-click unsubscribe")

    unsubscribe_url = extract_unsubscribe_url(message)
    if unsubscribe_url is None:
        raise ValidationError("List-Unsubscribe must include an HTTPS URL")
    if unsubscribe_url not in message.body:
        raise ValidationError("unsubscribe URL must be present in the message body")

