"""Shared constants and helpers for nontrading SQLite store surfaces."""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc
PUBLIC_REPORT_SCHEMA = "nontrading_public_report.v1"
ACTUAL_REVENUE_OUTCOME_STATUSES = {"won"}
SUCCESSFUL_MESSAGE_STATUSES = {"sent"}
SUCCESSFUL_OUTBOX_STATUSES = {"dry_run", "provider_accepted", "sent"}


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def hours_between(start: str | None, end: str | None) -> float | None:
    start_dt = parse_timestamp(start)
    end_dt = parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return round(max((end_dt - start_dt).total_seconds() / 3600.0, 0.0), 6)


DEFAULT_TABLES = {
    "agent_state": "agent_state",
    "engine_states": "engine_states",
    "campaigns": "campaigns",
    "leads": "leads",
    "suppression_list": "suppression_list",
    "outbox_messages": "outbox_messages",
    "send_events": "send_events",
    "risk_events": "risk_events",
    "accounts": "accounts",
    "contacts": "contacts",
    "opportunities": "crm_opportunities",
    "messages": "crm_messages",
    "meetings": "crm_meetings",
    "proposals": "crm_proposals",
    "outcomes": "crm_outcomes",
    "approval_requests": "approval_requests",
    "telemetry_events": "telemetry_events",
    "prospect_profiles": "prospect_profiles",
    "issue_evidence": "issue_evidence",
    "audit_bundles": "audit_bundles",
    "checkout_sessions": "checkout_sessions",
    "payment_events": "payment_events",
    "fulfillment_jobs": "fulfillment_jobs",
    "monitor_runs": "monitor_runs",
}

COMPAT_TABLES = {
    "agent_state": "nt_agent_state",
    "engine_states": "nt_engine_states",
    "campaigns": "nt_campaigns",
    "leads": "nt_leads",
    "suppression_list": "nt_suppression_list",
    "outbox_messages": "nt_outbox_messages",
    "send_events": "nt_send_events",
    "risk_events": "nt_risk_events",
    "accounts": "nt_accounts",
    "contacts": "nt_contacts",
    "opportunities": "nt_crm_opportunities",
    "messages": "nt_crm_messages",
    "meetings": "nt_crm_meetings",
    "proposals": "nt_crm_proposals",
    "outcomes": "nt_crm_outcomes",
    "approval_requests": "nt_approval_requests",
    "telemetry_events": "nt_telemetry_events",
    "prospect_profiles": "nt_prospect_profiles",
    "issue_evidence": "nt_issue_evidence",
    "audit_bundles": "nt_audit_bundles",
    "checkout_sessions": "nt_checkout_sessions",
    "payment_events": "nt_payment_events",
    "fulfillment_jobs": "nt_fulfillment_jobs",
    "monitor_runs": "nt_monitor_runs",
}

REQUIRED_DEFAULT_COLUMNS = {
    "agent_state": {"id", "global_kill_switch", "deliverability_status"},
    "engine_states": {"engine_name", "kill_switch_active", "run_mode"},
    "campaigns": {"id", "subject_template", "body_template", "daily_send_quota"},
    "leads": {"id", "email_normalized", "explicit_opt_in"},
    "suppression_list": {"id", "email_normalized", "created_at"},
    "outbox_messages": {"id", "recipient_email_normalized", "body", "updated_at"},
    "send_events": {"id", "email_normalized", "metadata_json", "created_at"},
    "risk_events": {"id", "metadata_json", "created_at"},
    "accounts": {"id", "domain_normalized", "status", "updated_at"},
    "contacts": {"id", "account_id", "email_normalized", "updated_at"},
    "opportunities": {"id", "account_id", "score", "updated_at"},
    "messages": {"id", "account_id", "recipient_email_normalized", "approval_status", "updated_at"},
    "meetings": {"id", "account_id", "scheduled_for", "updated_at"},
    "proposals": {"id", "account_id", "opportunity_id", "updated_at"},
    "outcomes": {"id", "account_id", "opportunity_id", "updated_at"},
    "approval_requests": {"id", "action_type", "entity_id", "updated_at"},
    "telemetry_events": {"id", "event_type", "entity_type", "created_at"},
    "prospect_profiles": {"id", "company_name", "domain_normalized", "updated_at"},
    "issue_evidence": {"id", "prospect_id", "issue_key", "updated_at"},
    "audit_bundles": {"id", "prospect_id", "bundle_kind", "issue_ids_json", "updated_at"},
    "checkout_sessions": {"id", "provider", "status", "order_id", "updated_at"},
    "payment_events": {"id", "provider", "event_type", "status", "updated_at"},
    "fulfillment_jobs": {"id", "opportunity_id", "payment_event_id", "status", "updated_at"},
    "monitor_runs": {"id", "opportunity_id", "baseline_bundle_id", "current_bundle_id", "updated_at"},
}
