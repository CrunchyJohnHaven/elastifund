"""Template rendering for campaign emails."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from nontrading.config import RevenueAgentSettings
from nontrading.email.headers import build_list_unsubscribe_headers
from nontrading.models import Campaign, Lead, RenderedEmail

PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def render_campaign_email(
    campaign: Campaign,
    lead: Lead,
    settings: RevenueAgentSettings,
) -> RenderedEmail:
    company_name = lead.company_name or lead.email.split("@", 1)[-1]
    unsubscribe_url = settings.build_unsubscribe_url(lead.email, campaign.name)
    context = {
        "campaign_name": campaign.name,
        "company_name": company_name,
        "country_code": lead.country_code,
        "email": lead.email,
        "unsubscribe_url": unsubscribe_url,
    }

    try:
        subject = campaign.subject_template.format(**context).strip()
        base_body = campaign.body_template.format(**context).strip()
    except KeyError as exc:  # pragma: no cover - defensive guard for bad templates
        missing = str(exc).strip("'")
        raise ValueError(f"Campaign template references unknown field '{missing}'") from exc

    footer = (
        f"--\n"
        f"{settings.from_name}\n"
        f"{settings.postal_address}\n"
        f"Unsubscribe: {unsubscribe_url}"
    )
    body = f"{base_body}\n\n{footer}".strip()
    headers = build_list_unsubscribe_headers(unsubscribe_url, settings.unsubscribe_mailto)
    return RenderedEmail(
        subject=subject,
        body=body,
        headers=headers,
        unsubscribe_url=unsubscribe_url,
    )


def render_placeholder_template(template: str, context: Mapping[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise ValueError(f"Email template references unknown field '{key}'")
        return str(context[key]).strip()

    return PLACEHOLDER_RE.sub(replace, template)


def render_file_email_template(
    template_path: str | Path,
    context: Mapping[str, Any],
    settings: RevenueAgentSettings,
    *,
    campaign_name: str,
) -> RenderedEmail:
    path = Path(template_path)
    raw_template = path.read_text().strip()
    if not raw_template:
        raise ValueError(f"Email template is empty: {path}")

    header, separator, body_template = raw_template.partition("\n\n")
    if not separator:
        raise ValueError(f"Email template must contain a blank line after the subject: {path}")

    prefix, marker, subject_template = header.partition(":")
    if marker != ":" or prefix.strip().lower() != "subject":
        raise ValueError(f"Email template must start with 'Subject:': {path}")

    recipient_email = str(context.get("email", "")).strip()
    if not recipient_email:
        raise ValueError("Email template context requires an email field")

    unsubscribe_url = settings.build_unsubscribe_url(recipient_email, campaign_name)
    render_context = dict(context)
    render_context.setdefault("sender_name", settings.from_name)
    render_context.setdefault("postal_address", settings.postal_address)
    render_context.setdefault("unsubscribe_url", unsubscribe_url)

    subject = render_placeholder_template(subject_template.strip(), render_context).strip()
    body = render_placeholder_template(body_template.strip(), render_context).strip()
    headers = build_list_unsubscribe_headers(unsubscribe_url, settings.unsubscribe_mailto)
    return RenderedEmail(
        subject=subject,
        body=body,
        headers=headers,
        unsubscribe_url=unsubscribe_url,
    )
