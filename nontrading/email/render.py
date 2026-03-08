"""Template rendering for campaign emails."""

from __future__ import annotations

from nontrading.config import RevenueAgentSettings
from nontrading.email.headers import build_list_unsubscribe_headers
from nontrading.models import Campaign, Lead, RenderedEmail


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

