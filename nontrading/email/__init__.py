"""Email delivery substrate for the non-trading revenue agent."""

from nontrading.email.render import (
    render_campaign_email,
    render_file_email_template,
    render_placeholder_template,
)

__all__ = [
    "render_campaign_email",
    "render_file_email_template",
    "render_placeholder_template",
]
