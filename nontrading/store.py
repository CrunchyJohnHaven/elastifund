"""SQLite store for the non-trading revenue agent."""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nontrading.config import RevenueAgentSettings
from nontrading.models import (
    Account,
    AgentState,
    ApprovalRequest,
    Campaign,
    Contact,
    EngineState,
    Lead,
    Meeting,
    Message,
    Opportunity,
    OutboxMessage,
    Outcome,
    Proposal,
    RiskEvent,
    SendEvent,
    TelemetryEvent,
    normalize_country,
    normalize_domain,
    normalize_email,
    utc_now,
)
from nontrading.revenue_audit.models import (
    AuditBundle,
    CheckoutSession,
    FirstDollarReadiness,
    FulfillmentJob,
    IssueEvidence,
    MonitorRun,
    PaymentEvent,
    ProspectProfile,
)

logger = logging.getLogger("nontrading.store")
UTC = timezone.utc
PUBLIC_REPORT_SCHEMA = "nontrading_public_report.v1"
ACTUAL_REVENUE_OUTCOME_STATUSES = {"won"}
SUCCESSFUL_MESSAGE_STATUSES = {"sent"}
SUCCESSFUL_OUTBOX_STATUSES = {"dry_run", "provider_accepted", "sent"}


def _parse_timestamp(value: str | None) -> datetime | None:
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


def _hours_between(start: str | None, end: str | None) -> float | None:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
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


class RevenueStore:
    """Simple synchronous SQLite store for revenue-agent state."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.tables = self._resolve_table_names()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _resolve_table_names(self) -> dict[str, str]:
        if not self.db_path.exists():
            return dict(DEFAULT_TABLES)

        with sqlite3.connect(str(self.db_path)) as conn:
            compat_present = any(self._table_columns(conn, name) for name in COMPAT_TABLES.values())
            if compat_present:
                return dict(COMPAT_TABLES)

            for logical_name, required_columns in REQUIRED_DEFAULT_COLUMNS.items():
                existing_columns = self._table_columns(conn, DEFAULT_TABLES[logical_name])
                if existing_columns and not required_columns.issubset(existing_columns):
                    logger.info(
                        "legacy_revenue_schema_detected db=%s logical_table=%s using_namespaced_tables",
                        self.db_path,
                        logical_name,
                    )
                    return dict(COMPAT_TABLES)

        return dict(DEFAULT_TABLES)

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row[1]) for row in rows}

    def initialize(self) -> None:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {t['agent_state']} (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    global_kill_switch INTEGER NOT NULL DEFAULT 0,
                    kill_reason TEXT NOT NULL DEFAULT '',
                    deliverability_status TEXT NOT NULL DEFAULT 'green',
                    last_heartbeat_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS {t['engine_states']} (
                    engine_name TEXT PRIMARY KEY,
                    engine_family TEXT NOT NULL DEFAULT 'non_trading',
                    status TEXT NOT NULL DEFAULT 'idle',
                    run_mode TEXT NOT NULL DEFAULT 'sim',
                    kill_switch_active INTEGER NOT NULL DEFAULT 0,
                    kill_reason TEXT NOT NULL DEFAULT '',
                    last_heartbeat_at TEXT,
                    last_event_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_{t['engine_states']}_status
                    ON {t['engine_states']}(status, updated_at);

                CREATE TABLE IF NOT EXISTS {t['campaigns']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    subject_template TEXT NOT NULL,
                    body_template TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    daily_send_quota INTEGER NOT NULL DEFAULT 25,
                    allowed_countries TEXT NOT NULL DEFAULT 'US',
                    kill_switch_active INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS {t['leads']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    email_normalized TEXT NOT NULL UNIQUE,
                    company_name TEXT NOT NULL DEFAULT '',
                    country_code TEXT NOT NULL DEFAULT 'US',
                    source TEXT NOT NULL DEFAULT 'manual',
                    explicit_opt_in INTEGER NOT NULL DEFAULT 0,
                    opt_in_recorded_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS {t['suppression_list']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    email_normalized TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_{t['suppression_list']}_email
                    ON {t['suppression_list']}(email_normalized);

                CREATE TABLE IF NOT EXISTS {t['outbox_messages']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    lead_id INTEGER NOT NULL,
                    recipient_email TEXT NOT NULL,
                    recipient_email_normalized TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    from_email TEXT NOT NULL,
                    headers_json TEXT NOT NULL DEFAULT '{{}}',
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    transport_message_id TEXT,
                    filesystem_path TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(campaign_id) REFERENCES {t['campaigns']}(id),
                    FOREIGN KEY(lead_id) REFERENCES {t['leads']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['outbox_messages']}_campaign_status
                    ON {t['outbox_messages']}(campaign_id, status, created_at);

                CREATE TABLE IF NOT EXISTS {t['send_events']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    lead_id INTEGER,
                    email TEXT NOT NULL,
                    email_normalized TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(campaign_id) REFERENCES {t['campaigns']}(id),
                    FOREIGN KEY(lead_id) REFERENCES {t['leads']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['send_events']}_event_type
                    ON {t['send_events']}(event_type, created_at);

                CREATE TABLE IF NOT EXISTS {t['risk_events']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_{t['risk_events']}_scope
                    ON {t['risk_events']}(scope, created_at);

                CREATE TABLE IF NOT EXISTS {t['accounts']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    domain_normalized TEXT NOT NULL DEFAULT '',
                    industry TEXT NOT NULL DEFAULT '',
                    website_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'researching',
                    notes TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{t['accounts']}_domain
                    ON {t['accounts']}(domain_normalized)
                    WHERE domain_normalized != '';

                CREATE TABLE IF NOT EXISTS {t['contacts']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    email_normalized TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{t['contacts']}_account_email
                    ON {t['contacts']}(account_id, email_normalized)
                    WHERE email_normalized != '';

                CREATE TABLE IF NOT EXISTS {t['opportunities']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    offer_name TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT 'research',
                    status TEXT NOT NULL DEFAULT 'open',
                    score REAL NOT NULL DEFAULT 0.0,
                    score_breakdown_json TEXT NOT NULL DEFAULT '{{}}',
                    estimated_value REAL NOT NULL DEFAULT 0.0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    next_action TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['opportunities']}_account_status
                    ON {t['opportunities']}(account_id, status, updated_at);

                CREATE TABLE IF NOT EXISTS {t['messages']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    opportunity_id INTEGER,
                    contact_id INTEGER,
                    recipient_email TEXT NOT NULL,
                    recipient_email_normalized TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'email',
                    direction TEXT NOT NULL DEFAULT 'outbound',
                    status TEXT NOT NULL DEFAULT 'draft',
                    requires_approval INTEGER NOT NULL DEFAULT 1,
                    approval_status TEXT NOT NULL DEFAULT 'pending',
                    sender_name TEXT NOT NULL DEFAULT '',
                    sender_email TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(contact_id) REFERENCES {t['contacts']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['messages']}_status
                    ON {t['messages']}(status, approval_status, created_at);

                CREATE TABLE IF NOT EXISTS {t['meetings']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    opportunity_id INTEGER,
                    contact_id INTEGER,
                    scheduled_for TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'booked',
                    owner TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(contact_id) REFERENCES {t['contacts']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['meetings']}_status
                    ON {t['meetings']}(status, scheduled_for);

                CREATE TABLE IF NOT EXISTS {t['proposals']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    opportunity_id INTEGER NOT NULL,
                    contact_id INTEGER,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    amount REAL NOT NULL DEFAULT 0.0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(contact_id) REFERENCES {t['contacts']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['proposals']}_status
                    ON {t['proposals']}(status, created_at);

                CREATE TABLE IF NOT EXISTS {t['outcomes']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    opportunity_id INTEGER NOT NULL,
                    proposal_id INTEGER,
                    status TEXT NOT NULL,
                    revenue REAL NOT NULL DEFAULT 0.0,
                    gross_margin REAL NOT NULL DEFAULT 0.0,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(proposal_id) REFERENCES {t['proposals']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['outcomes']}_status
                    ON {t['outcomes']}(status, created_at);

                CREATE TABLE IF NOT EXISTS {t['approval_requests']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_by TEXT NOT NULL DEFAULT 'system',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    review_notes TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_{t['approval_requests']}_entity
                    ON {t['approval_requests']}(action_type, entity_type, entity_id, status);

                CREATE TABLE IF NOT EXISTS {t['telemetry_events']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'recorded',
                    payload_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_{t['telemetry_events']}_event
                    ON {t['telemetry_events']}(event_type, created_at);

                CREATE TABLE IF NOT EXISTS {t['prospect_profiles']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    opportunity_id INTEGER,
                    company_name TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    domain_normalized TEXT NOT NULL DEFAULT '',
                    website_url TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'public_web',
                    segment TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'discovered',
                    country_code TEXT NOT NULL DEFAULT 'US',
                    score REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES {t['accounts']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['prospect_profiles']}_opportunity
                    ON {t['prospect_profiles']}(opportunity_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_{t['prospect_profiles']}_domain
                    ON {t['prospect_profiles']}(domain_normalized, updated_at);

                CREATE TABLE IF NOT EXISTS {t['issue_evidence']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prospect_id INTEGER NOT NULL,
                    issue_key TEXT NOT NULL,
                    detector_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    impact_score REAL NOT NULL DEFAULT 0.0,
                    source_url TEXT NOT NULL DEFAULT '',
                    evidence_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(prospect_id) REFERENCES {t['prospect_profiles']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['issue_evidence']}_prospect
                    ON {t['issue_evidence']}(prospect_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_{t['issue_evidence']}_issue_key
                    ON {t['issue_evidence']}(issue_key, detector_key);

                CREATE TABLE IF NOT EXISTS {t['audit_bundles']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prospect_id INTEGER NOT NULL,
                    opportunity_id INTEGER,
                    proposal_id INTEGER,
                    order_id TEXT NOT NULL DEFAULT '',
                    bundle_kind TEXT NOT NULL DEFAULT 'baseline',
                    status TEXT NOT NULL DEFAULT 'draft',
                    offer_slug TEXT NOT NULL DEFAULT 'website-growth-audit',
                    summary TEXT NOT NULL DEFAULT '',
                    score REAL NOT NULL DEFAULT 0.0,
                    issue_ids_json TEXT NOT NULL DEFAULT '[]',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(prospect_id) REFERENCES {t['prospect_profiles']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(proposal_id) REFERENCES {t['proposals']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['audit_bundles']}_opportunity
                    ON {t['audit_bundles']}(opportunity_id, bundle_kind, updated_at);

                CREATE TABLE IF NOT EXISTS {t['checkout_sessions']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prospect_id INTEGER,
                    opportunity_id INTEGER,
                    proposal_id INTEGER,
                    offer_slug TEXT NOT NULL DEFAULT 'website-growth-audit',
                    provider TEXT NOT NULL DEFAULT 'stripe',
                    status TEXT NOT NULL DEFAULT 'created',
                    amount REAL NOT NULL DEFAULT 0.0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    order_id TEXT NOT NULL DEFAULT '',
                    provider_session_id TEXT NOT NULL DEFAULT '',
                    success_url TEXT NOT NULL DEFAULT '',
                    cancel_url TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(prospect_id) REFERENCES {t['prospect_profiles']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(proposal_id) REFERENCES {t['proposals']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['checkout_sessions']}_status
                    ON {t['checkout_sessions']}(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_{t['checkout_sessions']}_order
                    ON {t['checkout_sessions']}(order_id, provider_session_id);

                CREATE TABLE IF NOT EXISTS {t['payment_events']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkout_session_id INTEGER,
                    prospect_id INTEGER,
                    opportunity_id INTEGER,
                    proposal_id INTEGER,
                    provider TEXT NOT NULL DEFAULT 'stripe',
                    event_type TEXT NOT NULL DEFAULT 'checkout.session.completed',
                    status TEXT NOT NULL DEFAULT 'pending',
                    amount REAL NOT NULL DEFAULT 0.0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    order_id TEXT NOT NULL DEFAULT '',
                    provider_event_id TEXT NOT NULL DEFAULT '',
                    customer_email TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(checkout_session_id) REFERENCES {t['checkout_sessions']}(id),
                    FOREIGN KEY(prospect_id) REFERENCES {t['prospect_profiles']}(id),
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(proposal_id) REFERENCES {t['proposals']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['payment_events']}_status
                    ON {t['payment_events']}(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_{t['payment_events']}_order
                    ON {t['payment_events']}(order_id, provider_event_id);

                CREATE TABLE IF NOT EXISTS {t['fulfillment_jobs']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id INTEGER NOT NULL,
                    proposal_id INTEGER,
                    prospect_id INTEGER,
                    payment_event_id INTEGER NOT NULL,
                    audit_bundle_id INTEGER,
                    offer_slug TEXT NOT NULL DEFAULT 'website-growth-audit',
                    status TEXT NOT NULL DEFAULT 'queued',
                    current_step TEXT NOT NULL DEFAULT 'provisioning',
                    order_id TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    checklist_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(proposal_id) REFERENCES {t['proposals']}(id),
                    FOREIGN KEY(prospect_id) REFERENCES {t['prospect_profiles']}(id),
                    FOREIGN KEY(payment_event_id) REFERENCES {t['payment_events']}(id),
                    FOREIGN KEY(audit_bundle_id) REFERENCES {t['audit_bundles']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['fulfillment_jobs']}_status
                    ON {t['fulfillment_jobs']}(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_{t['fulfillment_jobs']}_payment
                    ON {t['fulfillment_jobs']}(payment_event_id, updated_at);

                CREATE TABLE IF NOT EXISTS {t['monitor_runs']} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id INTEGER NOT NULL,
                    fulfillment_job_id INTEGER,
                    baseline_bundle_id INTEGER NOT NULL,
                    current_bundle_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    delta_artifact_path TEXT NOT NULL DEFAULT '',
                    new_issue_count INTEGER NOT NULL DEFAULT 0,
                    resolved_issue_count INTEGER NOT NULL DEFAULT 0,
                    persistent_issue_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(opportunity_id) REFERENCES {t['opportunities']}(id),
                    FOREIGN KEY(fulfillment_job_id) REFERENCES {t['fulfillment_jobs']}(id),
                    FOREIGN KEY(baseline_bundle_id) REFERENCES {t['audit_bundles']}(id),
                    FOREIGN KEY(current_bundle_id) REFERENCES {t['audit_bundles']}(id)
                );
                CREATE INDEX IF NOT EXISTS idx_{t['monitor_runs']}_status
                    ON {t['monitor_runs']}(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_{t['monitor_runs']}_opportunity
                    ON {t['monitor_runs']}(opportunity_id, updated_at);
                """
            )
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {t['agent_state']} (
                    id,
                    global_kill_switch,
                    kill_reason,
                    deliverability_status,
                    updated_at
                ) VALUES (1, 0, '', 'green', ?)
                """,
                (now,),
            )

    def _campaign_from_row(self, row: sqlite3.Row) -> Campaign:
        allowed = tuple(part.strip().upper() for part in row["allowed_countries"].split(",") if part.strip())
        return Campaign(
            id=row["id"],
            name=row["name"],
            subject_template=row["subject_template"],
            body_template=row["body_template"],
            status=row["status"],
            daily_send_quota=row["daily_send_quota"],
            allowed_countries=allowed or ("US",),
            kill_switch_active=bool(row["kill_switch_active"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _lead_from_row(self, row: sqlite3.Row) -> Lead:
        return Lead(
            id=row["id"],
            email=row["email"],
            company_name=row["company_name"],
            country_code=row["country_code"],
            source=row["source"],
            explicit_opt_in=bool(row["explicit_opt_in"]),
            opt_in_recorded_at=row["opt_in_recorded_at"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _outbox_from_row(self, row: sqlite3.Row) -> OutboxMessage:
        return OutboxMessage(
            id=row["id"],
            campaign_id=row["campaign_id"],
            lead_id=row["lead_id"],
            recipient_email=row["recipient_email"],
            subject=row["subject"],
            body=row["body"],
            from_email=row["from_email"],
            headers=json.loads(row["headers_json"]),
            provider=row["provider"],
            status=row["status"],
            detail=row["detail"],
            transport_message_id=row["transport_message_id"],
            filesystem_path=row["filesystem_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _account_from_row(self, row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            name=row["name"],
            domain=row["domain"],
            industry=row["industry"],
            website_url=row["website_url"],
            status=row["status"],
            notes=row["notes"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _contact_from_row(self, row: sqlite3.Row) -> Contact:
        return Contact(
            id=row["id"],
            account_id=row["account_id"],
            full_name=row["full_name"],
            email=row["email"],
            title=row["title"],
            phone=row["phone"],
            role=row["role"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _opportunity_from_row(self, row: sqlite3.Row) -> Opportunity:
        return Opportunity(
            id=row["id"],
            account_id=row["account_id"],
            name=row["name"],
            offer_name=row["offer_name"],
            stage=row["stage"],
            status=row["status"],
            score=float(row["score"]),
            score_breakdown=json.loads(row["score_breakdown_json"]),
            estimated_value=float(row["estimated_value"]),
            currency=row["currency"],
            next_action=row["next_action"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _message_from_row(self, row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            account_id=row["account_id"],
            opportunity_id=row["opportunity_id"],
            contact_id=row["contact_id"],
            recipient_email=row["recipient_email"],
            subject=row["subject"],
            body=row["body"],
            channel=row["channel"],
            direction=row["direction"],
            status=row["status"],
            requires_approval=bool(row["requires_approval"]),
            approval_status=row["approval_status"],
            sender_name=row["sender_name"],
            sender_email=row["sender_email"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _meeting_from_row(self, row: sqlite3.Row) -> Meeting:
        return Meeting(
            id=row["id"],
            account_id=row["account_id"],
            opportunity_id=row["opportunity_id"],
            contact_id=row["contact_id"],
            scheduled_for=row["scheduled_for"],
            status=row["status"],
            owner=row["owner"],
            notes=row["notes"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _proposal_from_row(self, row: sqlite3.Row) -> Proposal:
        return Proposal(
            id=row["id"],
            account_id=row["account_id"],
            opportunity_id=row["opportunity_id"],
            contact_id=row["contact_id"],
            title=row["title"],
            status=row["status"],
            amount=float(row["amount"]),
            currency=row["currency"],
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _outcome_from_row(self, row: sqlite3.Row) -> Outcome:
        return Outcome(
            id=row["id"],
            account_id=row["account_id"],
            opportunity_id=row["opportunity_id"],
            proposal_id=row["proposal_id"],
            status=row["status"],
            revenue=float(row["revenue"]),
            gross_margin=float(row["gross_margin"]),
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _approval_request_from_row(self, row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            id=row["id"],
            action_type=row["action_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            summary=row["summary"],
            status=row["status"],
            requested_by=row["requested_by"],
            reviewed_by=row["reviewed_by"],
            review_notes=row["review_notes"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            reviewed_at=row["reviewed_at"],
        )

    def _telemetry_event_from_row(self, row: sqlite3.Row) -> TelemetryEvent:
        return TelemetryEvent(
            id=row["id"],
            event_type=row["event_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            status=row["status"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )

    def _prospect_profile_from_row(self, row: sqlite3.Row) -> ProspectProfile:
        return ProspectProfile(
            id=row["id"],
            account_id=row["account_id"],
            opportunity_id=row["opportunity_id"],
            company_name=row["company_name"],
            domain=row["domain"],
            website_url=row["website_url"],
            source=row["source"],
            segment=row["segment"],
            status=row["status"],
            country_code=row["country_code"],
            score=float(row["score"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _issue_evidence_from_row(self, row: sqlite3.Row) -> IssueEvidence:
        return IssueEvidence(
            id=row["id"],
            prospect_id=row["prospect_id"],
            issue_key=row["issue_key"],
            detector_key=row["detector_key"],
            title=row["title"],
            summary=row["summary"],
            severity=row["severity"],
            confidence=float(row["confidence"]),
            impact_score=float(row["impact_score"]),
            source_url=row["source_url"],
            evidence_text=row["evidence_text"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _audit_bundle_from_row(self, row: sqlite3.Row) -> AuditBundle:
        return AuditBundle(
            id=row["id"],
            prospect_id=row["prospect_id"],
            opportunity_id=row["opportunity_id"],
            proposal_id=row["proposal_id"],
            order_id=row["order_id"],
            bundle_kind=row["bundle_kind"],
            status=row["status"],
            offer_slug=row["offer_slug"],
            summary=row["summary"],
            score=float(row["score"]),
            issue_ids=tuple(int(item) for item in json.loads(row["issue_ids_json"])),
            artifact_path=row["artifact_path"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _checkout_session_from_row(self, row: sqlite3.Row) -> CheckoutSession:
        return CheckoutSession(
            id=row["id"],
            prospect_id=row["prospect_id"],
            opportunity_id=row["opportunity_id"],
            proposal_id=row["proposal_id"],
            offer_slug=row["offer_slug"],
            provider=row["provider"],
            status=row["status"],
            amount=float(row["amount"]),
            currency=row["currency"],
            order_id=row["order_id"],
            provider_session_id=row["provider_session_id"],
            success_url=row["success_url"],
            cancel_url=row["cancel_url"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _payment_event_from_row(self, row: sqlite3.Row) -> PaymentEvent:
        return PaymentEvent(
            id=row["id"],
            checkout_session_id=row["checkout_session_id"],
            prospect_id=row["prospect_id"],
            opportunity_id=row["opportunity_id"],
            proposal_id=row["proposal_id"],
            provider=row["provider"],
            event_type=row["event_type"],
            status=row["status"],
            amount=float(row["amount"]),
            currency=row["currency"],
            order_id=row["order_id"],
            provider_event_id=row["provider_event_id"],
            customer_email=row["customer_email"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _fulfillment_job_from_row(self, row: sqlite3.Row) -> FulfillmentJob:
        return FulfillmentJob(
            id=row["id"],
            opportunity_id=row["opportunity_id"],
            proposal_id=row["proposal_id"],
            prospect_id=row["prospect_id"],
            payment_event_id=row["payment_event_id"],
            audit_bundle_id=row["audit_bundle_id"],
            offer_slug=row["offer_slug"],
            status=row["status"],
            current_step=row["current_step"],
            order_id=row["order_id"],
            artifact_path=row["artifact_path"],
            checklist=tuple(json.loads(row["checklist_json"])),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def _monitor_run_from_row(self, row: sqlite3.Row) -> MonitorRun:
        return MonitorRun(
            id=row["id"],
            opportunity_id=row["opportunity_id"],
            fulfillment_job_id=row["fulfillment_job_id"],
            baseline_bundle_id=row["baseline_bundle_id"],
            current_bundle_id=row["current_bundle_id"],
            status=row["status"],
            delta_artifact_path=row["delta_artifact_path"],
            new_issue_count=int(row["new_issue_count"]),
            resolved_issue_count=int(row["resolved_issue_count"]),
            persistent_issue_count=int(row["persistent_issue_count"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def get_agent_state(self) -> AgentState:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['agent_state']} WHERE id = 1").fetchone()
        if row is None:
            return AgentState()
        return AgentState(
            global_kill_switch=bool(row["global_kill_switch"]),
            kill_reason=row["kill_reason"],
            deliverability_status=row["deliverability_status"],
            last_heartbeat_at=row["last_heartbeat_at"],
            updated_at=row["updated_at"],
        )

    def _engine_state_from_row(self, row: sqlite3.Row) -> EngineState:
        return EngineState(
            engine_name=row["engine_name"],
            engine_family=row["engine_family"],
            status=row["status"],
            run_mode=row["run_mode"],
            kill_switch_active=bool(row["kill_switch_active"]),
            kill_reason=row["kill_reason"],
            last_heartbeat_at=row["last_heartbeat_at"],
            last_event_at=row["last_event_at"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_engine_state(self, engine_name: str) -> EngineState | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['engine_states']} WHERE engine_name = ?",
                (engine_name.strip(),),
            ).fetchone()
        if row is None:
            return None
        return self._engine_state_from_row(row)

    def list_engine_states(self) -> list[EngineState]:
        t = self.tables
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {t['engine_states']} ORDER BY engine_family ASC, engine_name ASC"
            ).fetchall()
        return [self._engine_state_from_row(row) for row in rows]

    def upsert_engine_state(
        self,
        engine_name: str,
        *,
        engine_family: str = "non_trading",
        status: str = "idle",
        run_mode: str = "sim",
        metadata: dict[str, Any] | None = None,
        last_heartbeat_at: str | None = None,
        last_event_at: str | None = None,
    ) -> EngineState:
        now = utc_now()
        normalized_name = engine_name.strip()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {t['engine_states']} (
                    engine_name,
                    engine_family,
                    status,
                    run_mode,
                    kill_switch_active,
                    kill_reason,
                    last_heartbeat_at,
                    last_event_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 0, '', ?, ?, ?, ?, ?)
                ON CONFLICT(engine_name) DO UPDATE SET
                    engine_family = excluded.engine_family,
                    status = excluded.status,
                    run_mode = excluded.run_mode,
                    last_heartbeat_at = COALESCE(excluded.last_heartbeat_at, last_heartbeat_at),
                    last_event_at = COALESCE(excluded.last_event_at, last_event_at),
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_name,
                    engine_family,
                    status,
                    run_mode,
                    last_heartbeat_at,
                    last_event_at,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
        engine_state = self.get_engine_state(normalized_name)
        if engine_state is None:
            raise RuntimeError(f"Engine state {normalized_name} disappeared")
        return engine_state

    def touch_engine_heartbeat(
        self,
        engine_name: str,
        *,
        engine_family: str = "non_trading",
        status: str = "running",
        run_mode: str = "sim",
        metadata: dict[str, Any] | None = None,
        last_event_at: str | None = None,
    ) -> EngineState:
        now = utc_now()
        return self.upsert_engine_state(
            engine_name,
            engine_family=engine_family,
            status=status,
            run_mode=run_mode,
            metadata=metadata,
            last_heartbeat_at=now,
            last_event_at=last_event_at,
        )

    def update_deliverability_status(self, status: str) -> None:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['agent_state']}
                SET deliverability_status = ?, updated_at = ?
                WHERE id = 1
                """,
                (status, now),
            )

    def touch_heartbeat(self) -> None:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['agent_state']}
                SET last_heartbeat_at = ?, updated_at = ?
                WHERE id = 1
                """,
                (now, now),
            )

    def set_global_kill_switch(self, enabled: bool, reason: str = "") -> None:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['agent_state']}
                SET global_kill_switch = ?, kill_reason = ?, updated_at = ?
                WHERE id = 1
                """,
                (1 if enabled else 0, reason, now),
            )

    def set_engine_kill_switch(self, engine_name: str, enabled: bool, reason: str = "") -> None:
        now = utc_now()
        normalized_name = engine_name.strip()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {t['engine_states']} (
                    engine_name,
                    engine_family,
                    status,
                    run_mode,
                    kill_switch_active,
                    kill_reason,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, 'non_trading', 'idle', 'sim', ?, ?, '{{}}', ?, ?)
                ON CONFLICT(engine_name) DO UPDATE SET
                    kill_switch_active = excluded.kill_switch_active,
                    kill_reason = excluded.kill_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_name,
                    1 if enabled else 0,
                    reason,
                    now,
                    now,
                ),
            )

    def ensure_default_campaign(self, settings: RevenueAgentSettings) -> Campaign:
        existing = self.get_campaign_by_name(settings.default_campaign_name)
        if existing is not None:
            return existing
        return self.create_campaign(
            Campaign(
                name=settings.default_campaign_name,
                subject_template=settings.default_subject_template,
                body_template=settings.default_body_template,
                daily_send_quota=settings.daily_send_quota,
                allowed_countries=settings.allowed_countries,
            )
        )

    def create_campaign(self, campaign: Campaign) -> Campaign:
        now = utc_now()
        allowed = ",".join(campaign.allowed_countries)
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['campaigns']} (
                    name,
                    subject_template,
                    body_template,
                    status,
                    daily_send_quota,
                    allowed_countries,
                    kill_switch_active,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.name,
                    campaign.subject_template,
                    campaign.body_template,
                    campaign.status,
                    campaign.daily_send_quota,
                    allowed,
                    1 if campaign.kill_switch_active else 0,
                    json.dumps(campaign.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            campaign_id = int(cursor.lastrowid)
        return Campaign(
            id=campaign_id,
            name=campaign.name,
            subject_template=campaign.subject_template,
            body_template=campaign.body_template,
            status=campaign.status,
            daily_send_quota=campaign.daily_send_quota,
            allowed_countries=campaign.allowed_countries,
            kill_switch_active=campaign.kill_switch_active,
            metadata=campaign.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_campaign(self, campaign_id: int) -> Campaign | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['campaigns']} WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            return None
        return self._campaign_from_row(row)

    def get_campaign_by_name(self, name: str) -> Campaign | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['campaigns']} WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return self._campaign_from_row(row)

    def list_active_campaigns(self) -> list[Campaign]:
        t = self.tables
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {t['campaigns']} WHERE status = 'active' ORDER BY created_at ASC"
            ).fetchall()
        return [self._campaign_from_row(row) for row in rows]

    def set_campaign_kill_switch(self, campaign_id: int, enabled: bool, reason: str = "") -> None:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['campaigns']}
                SET kill_switch_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, now, campaign_id),
            )
        if reason:
            self.record_risk_event(
                RiskEvent(
                    scope="campaign",
                    scope_id=str(campaign_id),
                    severity="critical" if enabled else "info",
                    event_type="campaign_kill_switch",
                    detail=reason,
                )
            )

    def upsert_lead(self, lead: Lead) -> tuple[Lead, bool]:
        email_normalized = normalize_email(lead.email)
        now = utc_now()
        existing = self.get_lead_by_email(lead.email)
        t = self.tables
        if existing is None:
            with self._connect() as conn:
                cursor = conn.execute(
                    f"""
                    INSERT INTO {t['leads']} (
                        email,
                        email_normalized,
                        company_name,
                        country_code,
                        source,
                        explicit_opt_in,
                        opt_in_recorded_at,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lead.email.strip(),
                        email_normalized,
                        lead.company_name.strip(),
                        normalize_country(lead.country_code),
                        lead.source.strip() or "manual",
                        1 if lead.explicit_opt_in else 0,
                        lead.opt_in_recorded_at,
                        json.dumps(lead.metadata, sort_keys=True),
                        now,
                        now,
                    ),
                )
                lead_id = int(cursor.lastrowid)
            return (
                Lead(
                    id=lead_id,
                    email=lead.email.strip(),
                    company_name=lead.company_name.strip(),
                    country_code=normalize_country(lead.country_code),
                    source=lead.source.strip() or "manual",
                    explicit_opt_in=lead.explicit_opt_in,
                    opt_in_recorded_at=lead.opt_in_recorded_at,
                    metadata=lead.metadata,
                    created_at=now,
                    updated_at=now,
                ),
                True,
            )

        merged_metadata: dict[str, Any] = dict(existing.metadata)
        merged_metadata.update(lead.metadata)
        updated = Lead(
            id=existing.id,
            email=existing.email,
            company_name=lead.company_name.strip() or existing.company_name,
            country_code=normalize_country(lead.country_code or existing.country_code),
            source=lead.source.strip() or existing.source,
            explicit_opt_in=existing.explicit_opt_in or lead.explicit_opt_in,
            opt_in_recorded_at=lead.opt_in_recorded_at or existing.opt_in_recorded_at,
            metadata=merged_metadata,
            created_at=existing.created_at,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['leads']}
                SET company_name = ?,
                    country_code = ?,
                    source = ?,
                    explicit_opt_in = ?,
                    opt_in_recorded_at = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE email_normalized = ?
                """,
                (
                    updated.company_name,
                    updated.country_code,
                    updated.source,
                    1 if updated.explicit_opt_in else 0,
                    updated.opt_in_recorded_at,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    email_normalized,
                ),
            )
        return updated, False

    def get_lead_by_email(self, email: str) -> Lead | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['leads']} WHERE email_normalized = ?",
                (normalize_email(email),),
            ).fetchone()
        if row is None:
            return None
        return self._lead_from_row(row)

    def list_unsent_leads_for_campaign(self, campaign_id: int, limit: int | None = None) -> list[Lead]:
        t = self.tables
        sql = f"""
            SELECT l.*
            FROM {t['leads']} AS l
            WHERE NOT EXISTS (
                SELECT 1
                FROM {t['suppression_list']} AS s
                WHERE s.email_normalized = l.email_normalized
            )
              AND NOT EXISTS (
                SELECT 1
                FROM {t['outbox_messages']} AS o
                WHERE o.campaign_id = ?
                  AND o.lead_id = l.id
                  AND o.status IN ('queued', 'dry_run', 'provider_accepted', 'sent')
            )
            ORDER BY l.explicit_opt_in DESC, l.created_at ASC
        """
        params: list[Any] = [campaign_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._lead_from_row(row) for row in rows]

    def queue_outbox_message(
        self,
        campaign: Campaign,
        lead: Lead,
        subject: str,
        body: str,
        headers: dict[str, str],
        from_email: str,
        provider: str,
    ) -> OutboxMessage:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['outbox_messages']} (
                    campaign_id,
                    lead_id,
                    recipient_email,
                    recipient_email_normalized,
                    subject,
                    body,
                    from_email,
                    headers_json,
                    provider,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    campaign.id,
                    lead.id,
                    lead.email,
                    lead.email_normalized,
                    subject,
                    body,
                    from_email,
                    json.dumps(headers, sort_keys=True),
                    provider,
                    now,
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)
        return OutboxMessage(
            id=message_id,
            campaign_id=campaign.id or 0,
            lead_id=lead.id or 0,
            recipient_email=lead.email,
            subject=subject,
            body=body,
            from_email=from_email,
            headers=headers,
            provider=provider,
            status="queued",
            created_at=now,
            updated_at=now,
        )

    def update_outbox_message_status(
        self,
        message_id: int,
        status: str,
        detail: str = "",
        transport_message_id: str | None = None,
        filesystem_path: str | None = None,
    ) -> OutboxMessage:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['outbox_messages']}
                SET status = ?,
                    detail = ?,
                    transport_message_id = ?,
                    filesystem_path = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, detail, transport_message_id, filesystem_path, now, message_id),
            )
        message = self.get_outbox_message(message_id)
        if message is None:
            raise RuntimeError(f"Outbox message {message_id} disappeared")
        return message

    def get_outbox_message(self, message_id: int) -> OutboxMessage | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['outbox_messages']} WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            return None
        return self._outbox_from_row(row)

    def list_outbox_messages(self, campaign_id: int | None = None) -> list[OutboxMessage]:
        t = self.tables
        sql = f"SELECT * FROM {t['outbox_messages']}"
        params: list[Any] = []
        if campaign_id is not None:
            sql += " WHERE campaign_id = ?"
            params.append(campaign_id)
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._outbox_from_row(row) for row in rows]

    def is_suppressed(self, email: str) -> bool:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {t['suppression_list']} WHERE email_normalized = ? LIMIT 1",
                (normalize_email(email),),
            ).fetchone()
        return row is not None

    def append_suppression(self, email: str, reason: str, source: str) -> bool:
        normalized = normalize_email(email)
        if self.is_suppressed(email):
            return False
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {t['suppression_list']} (
                    email,
                    email_normalized,
                    reason,
                    source,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (email.strip(), normalized, reason, source, utc_now()),
            )
        return True

    def record_send_event(self, event: SendEvent) -> SendEvent:
        created_at = event.created_at or utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['send_events']} (
                    campaign_id,
                    lead_id,
                    email,
                    email_normalized,
                    event_type,
                    status,
                    provider,
                    detail,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.campaign_id,
                    event.lead_id,
                    event.email,
                    normalize_email(event.email),
                    event.event_type,
                    event.status,
                    event.provider,
                    event.detail,
                    json.dumps(event.metadata, sort_keys=True),
                    created_at,
                ),
            )
            event_id = int(cursor.lastrowid)
        if event.event_type == "unsubscribe" or event.status == "unsubscribed":
            self.append_suppression(event.email, event.detail or "unsubscribe", event.provider)
        return SendEvent(
            id=event_id,
            campaign_id=event.campaign_id,
            lead_id=event.lead_id,
            email=event.email,
            event_type=event.event_type,
            status=event.status,
            provider=event.provider,
            detail=event.detail,
            metadata=event.metadata,
            created_at=created_at,
        )

    def record_unsubscribe(
        self,
        email: str,
        campaign_id: int | None = None,
        lead_id: int | None = None,
        detail: str = "unsubscribe_link",
        provider: str = "system",
    ) -> SendEvent:
        return self.record_send_event(
            SendEvent(
                campaign_id=campaign_id,
                lead_id=lead_id,
                email=email,
                event_type="unsubscribe",
                status="unsubscribed",
                provider=provider,
                detail=detail,
            )
        )

    def record_risk_event(self, event: RiskEvent) -> RiskEvent:
        created_at = event.created_at or utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['risk_events']} (
                    scope,
                    scope_id,
                    severity,
                    event_type,
                    detail,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.scope,
                    event.scope_id,
                    event.severity,
                    event.event_type,
                    event.detail,
                    json.dumps(event.metadata, sort_keys=True),
                    created_at,
                ),
            )
            event_id = int(cursor.lastrowid)
        return RiskEvent(
            id=event_id,
            scope=event.scope,
            scope_id=event.scope_id,
            severity=event.severity,
            event_type=event.event_type,
            detail=event.detail,
            metadata=event.metadata,
            created_at=created_at,
        )

    def upsert_account(self, account: Account) -> tuple[Account, bool]:
        now = utc_now()
        t = self.tables
        domain_normalized = normalize_domain(account.domain)
        existing = self.get_account_by_domain(account.domain) if domain_normalized else self.get_account_by_name(account.name)

        if existing is None:
            with self._connect() as conn:
                cursor = conn.execute(
                    f"""
                    INSERT INTO {t['accounts']} (
                        name,
                        domain,
                        domain_normalized,
                        industry,
                        website_url,
                        status,
                        notes,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.name.strip(),
                        account.domain.strip(),
                        domain_normalized,
                        account.industry.strip(),
                        account.website_url.strip(),
                        account.status,
                        account.notes,
                        json.dumps(account.metadata, sort_keys=True),
                        now,
                        now,
                    ),
                )
                account_id = int(cursor.lastrowid)
            return (
                Account(
                    id=account_id,
                    name=account.name.strip(),
                    domain=account.domain.strip(),
                    industry=account.industry.strip(),
                    website_url=account.website_url.strip(),
                    status=account.status,
                    notes=account.notes,
                    metadata=account.metadata,
                    created_at=now,
                    updated_at=now,
                ),
                True,
            )

        merged_metadata = dict(existing.metadata)
        merged_metadata.update(account.metadata)
        updated = Account(
            id=existing.id,
            name=account.name.strip() or existing.name,
            domain=account.domain.strip() or existing.domain,
            industry=account.industry.strip() or existing.industry,
            website_url=account.website_url.strip() or existing.website_url,
            status=account.status or existing.status,
            notes=account.notes or existing.notes,
            metadata=merged_metadata,
            created_at=existing.created_at,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['accounts']}
                SET name = ?,
                    domain = ?,
                    domain_normalized = ?,
                    industry = ?,
                    website_url = ?,
                    status = ?,
                    notes = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    updated.domain,
                    normalize_domain(updated.domain),
                    updated.industry,
                    updated.website_url,
                    updated.status,
                    updated.notes,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated, False

    def create_account(self, account: Account) -> Account:
        stored, _ = self.upsert_account(account)
        return stored

    def get_account(self, account_id: int) -> Account | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['accounts']} WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            return None
        return self._account_from_row(row)

    def get_account_by_name(self, name: str) -> Account | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['accounts']} WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (name.strip(),),
            ).fetchone()
        if row is None:
            return None
        return self._account_from_row(row)

    def get_account_by_domain(self, domain: str | None) -> Account | None:
        normalized = normalize_domain(domain)
        if not normalized:
            return None
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['accounts']} WHERE domain_normalized = ? LIMIT 1",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return self._account_from_row(row)

    def list_accounts(self, status: str | None = None) -> list[Account]:
        t = self.tables
        sql = f"SELECT * FROM {t['accounts']}"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC, id DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._account_from_row(row) for row in rows]

    def upsert_contact(self, contact: Contact) -> tuple[Contact, bool]:
        normalized_email = normalize_email(contact.email)
        now = utc_now()
        t = self.tables
        existing = self.get_contact(contact.id) if contact.id is not None else None
        if normalized_email:
            existing = existing or self.get_contact_by_email(contact.account_id, contact.email)

        if existing is None:
            with self._connect() as conn:
                cursor = conn.execute(
                    f"""
                    INSERT INTO {t['contacts']} (
                        account_id,
                        full_name,
                        email,
                        email_normalized,
                        title,
                        phone,
                        role,
                        status,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        contact.account_id,
                        contact.full_name.strip(),
                        contact.email.strip(),
                        normalized_email,
                        contact.title.strip(),
                        contact.phone.strip(),
                        contact.role.strip(),
                        contact.status,
                        json.dumps(contact.metadata, sort_keys=True),
                        now,
                        now,
                    ),
                )
                contact_id = int(cursor.lastrowid)
            return (
                Contact(
                    id=contact_id,
                    account_id=contact.account_id,
                    full_name=contact.full_name.strip(),
                    email=contact.email.strip(),
                    title=contact.title.strip(),
                    phone=contact.phone.strip(),
                    role=contact.role.strip(),
                    status=contact.status,
                    metadata=contact.metadata,
                    created_at=now,
                    updated_at=now,
                ),
                True,
            )

        merged_metadata = dict(existing.metadata)
        merged_metadata.update(contact.metadata)
        updated = Contact(
            id=existing.id,
            account_id=existing.account_id,
            full_name=contact.full_name.strip() or existing.full_name,
            email=contact.email.strip() or existing.email,
            title=contact.title.strip() or existing.title,
            phone=contact.phone.strip() or existing.phone,
            role=contact.role.strip() or existing.role,
            status=contact.status or existing.status,
            metadata=merged_metadata,
            created_at=existing.created_at,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['contacts']}
                SET full_name = ?,
                    email = ?,
                    email_normalized = ?,
                    title = ?,
                    phone = ?,
                    role = ?,
                    status = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.full_name,
                    updated.email,
                    normalize_email(updated.email),
                    updated.title,
                    updated.phone,
                    updated.role,
                    updated.status,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated, False

    def create_contact(self, contact: Contact) -> Contact:
        stored, _ = self.upsert_contact(contact)
        return stored

    def get_contact(self, contact_id: int) -> Contact | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['contacts']} WHERE id = ?", (contact_id,)).fetchone()
        if row is None:
            return None
        return self._contact_from_row(row)

    def get_contact_by_email(self, account_id: int, email: str | None) -> Contact | None:
        normalized = normalize_email(email)
        if not normalized:
            return None
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM {t['contacts']}
                WHERE account_id = ?
                  AND email_normalized = ?
                LIMIT 1
                """,
                (account_id, normalized),
            ).fetchone()
        if row is None:
            return None
        return self._contact_from_row(row)

    def list_contacts(self, account_id: int | None = None) -> list[Contact]:
        t = self.tables
        sql = f"SELECT * FROM {t['contacts']}"
        params: list[Any] = []
        if account_id is not None:
            sql += " WHERE account_id = ?"
            params.append(account_id)
        sql += " ORDER BY updated_at DESC, id DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._contact_from_row(row) for row in rows]

    def prospect_profile_from_account(self, account: Account, opportunity_id: int | None = None) -> ProspectProfile:
        return ProspectProfile(
            account_id=account.id,
            opportunity_id=opportunity_id,
            company_name=account.name,
            domain=account.domain,
            website_url=account.website_url,
            source="account_record",
            segment=account.industry,
            status="discovered",
            score=float(account.metadata.get("fit_score", 0.0) or 0.0),
            metadata={
                "account_id": account.id,
                "account_status": account.status,
            },
        )

    def create_prospect_profile(self, profile: ProspectProfile) -> ProspectProfile:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['prospect_profiles']} (
                    account_id,
                    opportunity_id,
                    company_name,
                    domain,
                    domain_normalized,
                    website_url,
                    source,
                    segment,
                    status,
                    country_code,
                    score,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.account_id,
                    profile.opportunity_id,
                    profile.company_name.strip(),
                    profile.domain.strip(),
                    normalize_domain(profile.domain),
                    profile.website_url.strip(),
                    profile.source.strip() or "public_web",
                    profile.segment.strip(),
                    profile.status,
                    normalize_country(profile.country_code),
                    float(profile.score),
                    json.dumps(profile.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            profile_id = int(cursor.lastrowid)
        return ProspectProfile(
            id=profile_id,
            account_id=profile.account_id,
            opportunity_id=profile.opportunity_id,
            company_name=profile.company_name.strip(),
            domain=profile.domain.strip(),
            website_url=profile.website_url.strip(),
            source=profile.source.strip() or "public_web",
            segment=profile.segment.strip(),
            status=profile.status,
            country_code=normalize_country(profile.country_code),
            score=float(profile.score),
            metadata=profile.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_prospect_profile(self, profile_id: int) -> ProspectProfile | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['prospect_profiles']} WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return self._prospect_profile_from_row(row)

    def list_prospect_profiles(
        self,
        *,
        account_id: int | None = None,
        opportunity_id: int | None = None,
        status: str | None = None,
    ) -> list[ProspectProfile]:
        t = self.tables
        sql = f"SELECT * FROM {t['prospect_profiles']}"
        params: list[Any] = []
        clauses: list[str] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._prospect_profile_from_row(row) for row in rows]

    def create_issue_evidence(self, evidence: IssueEvidence) -> IssueEvidence:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['issue_evidence']} (
                    prospect_id,
                    issue_key,
                    detector_key,
                    title,
                    summary,
                    severity,
                    confidence,
                    impact_score,
                    source_url,
                    evidence_text,
                    status,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.prospect_id,
                    evidence.issue_key,
                    evidence.detector_key,
                    evidence.title,
                    evidence.summary,
                    evidence.severity,
                    float(evidence.confidence),
                    float(evidence.impact_score),
                    evidence.source_url,
                    evidence.evidence_text,
                    evidence.status,
                    json.dumps(evidence.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            evidence_id = int(cursor.lastrowid)
        return IssueEvidence(
            id=evidence_id,
            prospect_id=evidence.prospect_id,
            issue_key=evidence.issue_key,
            detector_key=evidence.detector_key,
            title=evidence.title,
            summary=evidence.summary,
            severity=evidence.severity,
            confidence=float(evidence.confidence),
            impact_score=float(evidence.impact_score),
            source_url=evidence.source_url,
            evidence_text=evidence.evidence_text,
            status=evidence.status,
            metadata=evidence.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_issue_evidence(self, evidence_id: int) -> IssueEvidence | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['issue_evidence']} WHERE id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            return None
        return self._issue_evidence_from_row(row)

    def list_issue_evidence(
        self,
        *,
        prospect_id: int | None = None,
        bundle_id: int | None = None,
        status: str | None = None,
    ) -> list[IssueEvidence]:
        t = self.tables
        if bundle_id is not None:
            bundle = self.get_audit_bundle(bundle_id)
            if bundle is None or not bundle.issue_ids:
                return []
            placeholders = ",".join("?" for _ in bundle.issue_ids)
            sql = f"SELECT * FROM {t['issue_evidence']} WHERE id IN ({placeholders})"
            params: list[Any] = list(bundle.issue_ids)
            if status:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY impact_score DESC, id ASC"
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [self._issue_evidence_from_row(row) for row in rows]

        sql = f"SELECT * FROM {t['issue_evidence']}"
        params = []
        clauses: list[str] = []
        if prospect_id is not None:
            clauses.append("prospect_id = ?")
            params.append(prospect_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY impact_score DESC, created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._issue_evidence_from_row(row) for row in rows]

    def create_audit_bundle(self, bundle: AuditBundle) -> AuditBundle:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['audit_bundles']} (
                    prospect_id,
                    opportunity_id,
                    proposal_id,
                    order_id,
                    bundle_kind,
                    status,
                    offer_slug,
                    summary,
                    score,
                    issue_ids_json,
                    artifact_path,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle.prospect_id,
                    bundle.opportunity_id,
                    bundle.proposal_id,
                    bundle.order_id,
                    bundle.bundle_kind,
                    bundle.status,
                    bundle.offer_slug,
                    bundle.summary,
                    float(bundle.score),
                    json.dumps(list(bundle.issue_ids), sort_keys=True),
                    bundle.artifact_path,
                    json.dumps(bundle.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            bundle_id = int(cursor.lastrowid)
        return AuditBundle(
            id=bundle_id,
            prospect_id=bundle.prospect_id,
            opportunity_id=bundle.opportunity_id,
            proposal_id=bundle.proposal_id,
            order_id=bundle.order_id,
            bundle_kind=bundle.bundle_kind,
            status=bundle.status,
            offer_slug=bundle.offer_slug,
            summary=bundle.summary,
            score=float(bundle.score),
            issue_ids=tuple(int(item) for item in bundle.issue_ids),
            artifact_path=bundle.artifact_path,
            metadata=bundle.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_audit_bundle(self, bundle_id: int) -> AuditBundle | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['audit_bundles']} WHERE id = ?",
                (bundle_id,),
            ).fetchone()
        if row is None:
            return None
        return self._audit_bundle_from_row(row)

    def list_audit_bundles(
        self,
        *,
        prospect_id: int | None = None,
        opportunity_id: int | None = None,
        bundle_kind: str | None = None,
        status: str | None = None,
    ) -> list[AuditBundle]:
        t = self.tables
        sql = f"SELECT * FROM {t['audit_bundles']}"
        params: list[Any] = []
        clauses: list[str] = []
        if prospect_id is not None:
            clauses.append("prospect_id = ?")
            params.append(prospect_id)
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if bundle_kind:
            clauses.append("bundle_kind = ?")
            params.append(bundle_kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._audit_bundle_from_row(row) for row in rows]

    def create_checkout_session(self, session: CheckoutSession) -> CheckoutSession:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['checkout_sessions']} (
                    prospect_id,
                    opportunity_id,
                    proposal_id,
                    offer_slug,
                    provider,
                    status,
                    amount,
                    currency,
                    order_id,
                    provider_session_id,
                    success_url,
                    cancel_url,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.prospect_id,
                    session.opportunity_id,
                    session.proposal_id,
                    session.offer_slug,
                    session.provider,
                    session.status,
                    float(session.amount),
                    session.currency,
                    session.order_id,
                    session.provider_session_id,
                    session.success_url,
                    session.cancel_url,
                    json.dumps(session.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            session_id = int(cursor.lastrowid)
        return CheckoutSession(
            id=session_id,
            prospect_id=session.prospect_id,
            opportunity_id=session.opportunity_id,
            proposal_id=session.proposal_id,
            offer_slug=session.offer_slug,
            provider=session.provider,
            status=session.status,
            amount=float(session.amount),
            currency=session.currency,
            order_id=session.order_id,
            provider_session_id=session.provider_session_id,
            success_url=session.success_url,
            cancel_url=session.cancel_url,
            metadata=session.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_checkout_session(self, session_id: int) -> CheckoutSession | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['checkout_sessions']} WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._checkout_session_from_row(row)

    def list_checkout_sessions(
        self,
        *,
        opportunity_id: int | None = None,
        status: str | None = None,
    ) -> list[CheckoutSession]:
        t = self.tables
        sql = f"SELECT * FROM {t['checkout_sessions']}"
        params: list[Any] = []
        clauses: list[str] = []
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._checkout_session_from_row(row) for row in rows]

    def create_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['payment_events']} (
                    checkout_session_id,
                    prospect_id,
                    opportunity_id,
                    proposal_id,
                    provider,
                    event_type,
                    status,
                    amount,
                    currency,
                    order_id,
                    provider_event_id,
                    customer_email,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.checkout_session_id,
                    event.prospect_id,
                    event.opportunity_id,
                    event.proposal_id,
                    event.provider,
                    event.event_type,
                    event.status,
                    float(event.amount),
                    event.currency,
                    event.order_id,
                    event.provider_event_id,
                    event.customer_email,
                    json.dumps(event.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            event_id = int(cursor.lastrowid)
        return PaymentEvent(
            id=event_id,
            checkout_session_id=event.checkout_session_id,
            prospect_id=event.prospect_id,
            opportunity_id=event.opportunity_id,
            proposal_id=event.proposal_id,
            provider=event.provider,
            event_type=event.event_type,
            status=event.status,
            amount=float(event.amount),
            currency=event.currency,
            order_id=event.order_id,
            provider_event_id=event.provider_event_id,
            customer_email=event.customer_email,
            metadata=event.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_payment_event(self, event_id: int) -> PaymentEvent | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['payment_events']} WHERE id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return self._payment_event_from_row(row)

    def list_payment_events(
        self,
        *,
        opportunity_id: int | None = None,
        status: str | None = None,
    ) -> list[PaymentEvent]:
        t = self.tables
        sql = f"SELECT * FROM {t['payment_events']}"
        params: list[Any] = []
        clauses: list[str] = []
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._payment_event_from_row(row) for row in rows]

    def create_fulfillment_job(self, job: FulfillmentJob) -> FulfillmentJob:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['fulfillment_jobs']} (
                    opportunity_id,
                    proposal_id,
                    prospect_id,
                    payment_event_id,
                    audit_bundle_id,
                    offer_slug,
                    status,
                    current_step,
                    order_id,
                    artifact_path,
                    checklist_json,
                    metadata_json,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.opportunity_id,
                    job.proposal_id,
                    job.prospect_id,
                    job.payment_event_id,
                    job.audit_bundle_id,
                    job.offer_slug,
                    job.status,
                    job.current_step,
                    job.order_id,
                    job.artifact_path,
                    json.dumps(list(job.checklist), sort_keys=True),
                    json.dumps(job.metadata, sort_keys=True),
                    now,
                    now,
                    job.started_at,
                    job.completed_at,
                ),
            )
            job_id = int(cursor.lastrowid)
        return FulfillmentJob(
            id=job_id,
            opportunity_id=job.opportunity_id,
            proposal_id=job.proposal_id,
            prospect_id=job.prospect_id,
            payment_event_id=job.payment_event_id,
            audit_bundle_id=job.audit_bundle_id,
            offer_slug=job.offer_slug,
            status=job.status,
            current_step=job.current_step,
            order_id=job.order_id,
            artifact_path=job.artifact_path,
            checklist=tuple(job.checklist),
            metadata=job.metadata,
            created_at=now,
            updated_at=now,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )

    def get_fulfillment_job(self, job_id: int) -> FulfillmentJob | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['fulfillment_jobs']} WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._fulfillment_job_from_row(row)

    def list_fulfillment_jobs(
        self,
        *,
        opportunity_id: int | None = None,
        payment_event_id: int | None = None,
        status: str | None = None,
    ) -> list[FulfillmentJob]:
        t = self.tables
        sql = f"SELECT * FROM {t['fulfillment_jobs']}"
        params: list[Any] = []
        clauses: list[str] = []
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if payment_event_id is not None:
            clauses.append("payment_event_id = ?")
            params.append(payment_event_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._fulfillment_job_from_row(row) for row in rows]

    def update_fulfillment_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        current_step: str | None = None,
        audit_bundle_id: int | None = None,
        order_id: str | None = None,
        artifact_path: str | None = None,
        checklist: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> FulfillmentJob:
        existing = self.get_fulfillment_job(job_id)
        if existing is None:
            raise RuntimeError(f"Fulfillment job {job_id} disappeared")
        now = utc_now()
        merged_metadata = dict(existing.metadata)
        if metadata:
            merged_metadata.update(metadata)
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['fulfillment_jobs']}
                SET status = ?,
                    current_step = ?,
                    audit_bundle_id = ?,
                    order_id = ?,
                    artifact_path = ?,
                    checklist_json = ?,
                    metadata_json = ?,
                    updated_at = ?,
                    started_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    status or existing.status,
                    current_step or existing.current_step,
                    audit_bundle_id if audit_bundle_id is not None else existing.audit_bundle_id,
                    order_id if order_id is not None else existing.order_id,
                    artifact_path if artifact_path is not None else existing.artifact_path,
                    json.dumps(list(checklist if checklist is not None else existing.checklist), sort_keys=True),
                    json.dumps(merged_metadata, sort_keys=True),
                    now,
                    started_at if started_at is not None else existing.started_at,
                    completed_at if completed_at is not None else existing.completed_at,
                    job_id,
                ),
            )
        updated = self.get_fulfillment_job(job_id)
        if updated is None:
            raise RuntimeError(f"Fulfillment job {job_id} disappeared")
        return updated

    def create_monitor_run(self, run: MonitorRun) -> MonitorRun:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['monitor_runs']} (
                    opportunity_id,
                    fulfillment_job_id,
                    baseline_bundle_id,
                    current_bundle_id,
                    status,
                    delta_artifact_path,
                    new_issue_count,
                    resolved_issue_count,
                    persistent_issue_count,
                    metadata_json,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.opportunity_id,
                    run.fulfillment_job_id,
                    run.baseline_bundle_id,
                    run.current_bundle_id,
                    run.status,
                    run.delta_artifact_path,
                    int(run.new_issue_count),
                    int(run.resolved_issue_count),
                    int(run.persistent_issue_count),
                    json.dumps(run.metadata, sort_keys=True),
                    now,
                    now,
                    run.started_at,
                    run.completed_at,
                ),
            )
            run_id = int(cursor.lastrowid)
        return MonitorRun(
            id=run_id,
            opportunity_id=run.opportunity_id,
            fulfillment_job_id=run.fulfillment_job_id,
            baseline_bundle_id=run.baseline_bundle_id,
            current_bundle_id=run.current_bundle_id,
            status=run.status,
            delta_artifact_path=run.delta_artifact_path,
            new_issue_count=int(run.new_issue_count),
            resolved_issue_count=int(run.resolved_issue_count),
            persistent_issue_count=int(run.persistent_issue_count),
            metadata=run.metadata,
            created_at=now,
            updated_at=now,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def get_monitor_run(self, run_id: int) -> MonitorRun | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['monitor_runs']} WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return self._monitor_run_from_row(row)

    def list_monitor_runs(
        self,
        *,
        opportunity_id: int | None = None,
        status: str | None = None,
    ) -> list[MonitorRun]:
        t = self.tables
        sql = f"SELECT * FROM {t['monitor_runs']}"
        params: list[Any] = []
        clauses: list[str] = []
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._monitor_run_from_row(row) for row in rows]

    def create_opportunity(self, opportunity: Opportunity) -> Opportunity:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['opportunities']} (
                    account_id,
                    name,
                    offer_name,
                    stage,
                    status,
                    score,
                    score_breakdown_json,
                    estimated_value,
                    currency,
                    next_action,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.account_id,
                    opportunity.name,
                    opportunity.offer_name,
                    opportunity.stage,
                    opportunity.status,
                    float(opportunity.score),
                    json.dumps(opportunity.score_breakdown, sort_keys=True),
                    float(opportunity.estimated_value),
                    opportunity.currency,
                    opportunity.next_action,
                    json.dumps(opportunity.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            opportunity_id = int(cursor.lastrowid)
        return Opportunity(
            id=opportunity_id,
            account_id=opportunity.account_id,
            name=opportunity.name,
            offer_name=opportunity.offer_name,
            stage=opportunity.stage,
            status=opportunity.status,
            score=float(opportunity.score),
            score_breakdown=opportunity.score_breakdown,
            estimated_value=float(opportunity.estimated_value),
            currency=opportunity.currency,
            next_action=opportunity.next_action,
            metadata=opportunity.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_opportunity_by_name(
        self,
        account_id: int,
        name: str,
        offer_name: str | None = None,
    ) -> Opportunity | None:
        t = self.tables
        sql = f"""
            SELECT * FROM {t['opportunities']}
            WHERE account_id = ?
              AND LOWER(name) = LOWER(?)
        """
        params: list[Any] = [account_id, name.strip()]
        if offer_name is not None:
            sql += " AND LOWER(offer_name) = LOWER(?)"
            params.append(offer_name.strip())
        sql += " ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return self._opportunity_from_row(row)

    def upsert_opportunity(self, opportunity: Opportunity) -> tuple[Opportunity, bool]:
        existing = None
        if opportunity.id is not None:
            existing = self.get_opportunity(opportunity.id)
        if existing is None:
            existing = self.get_opportunity_by_name(
                opportunity.account_id,
                opportunity.name,
                opportunity.offer_name,
            )
        if existing is None:
            return self.create_opportunity(opportunity), True

        now = utc_now()
        updated = Opportunity(
            id=existing.id,
            account_id=opportunity.account_id,
            name=opportunity.name,
            offer_name=opportunity.offer_name,
            stage=opportunity.stage,
            status=opportunity.status,
            score=float(opportunity.score),
            score_breakdown=dict(opportunity.score_breakdown),
            estimated_value=float(opportunity.estimated_value),
            currency=opportunity.currency,
            next_action=opportunity.next_action,
            metadata=dict(opportunity.metadata),
            created_at=existing.created_at,
            updated_at=now,
        )
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['opportunities']}
                SET account_id = ?,
                    name = ?,
                    offer_name = ?,
                    stage = ?,
                    status = ?,
                    score = ?,
                    score_breakdown_json = ?,
                    estimated_value = ?,
                    currency = ?,
                    next_action = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.account_id,
                    updated.name,
                    updated.offer_name,
                    updated.stage,
                    updated.status,
                    float(updated.score),
                    json.dumps(updated.score_breakdown, sort_keys=True),
                    float(updated.estimated_value),
                    updated.currency,
                    updated.next_action,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated, False

    def get_opportunity(self, opportunity_id: int) -> Opportunity | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['opportunities']} WHERE id = ?", (opportunity_id,)).fetchone()
        if row is None:
            return None
        return self._opportunity_from_row(row)

    def list_opportunities(
        self,
        account_id: int | None = None,
        status: str | None = None,
    ) -> list[Opportunity]:
        t = self.tables
        sql = f"SELECT * FROM {t['opportunities']}"
        params: list[Any] = []
        clauses: list[str] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY score DESC, updated_at DESC, id DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._opportunity_from_row(row) for row in rows]

    def create_message(self, message: Message) -> Message:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['messages']} (
                    account_id,
                    opportunity_id,
                    contact_id,
                    recipient_email,
                    recipient_email_normalized,
                    subject,
                    body,
                    channel,
                    direction,
                    status,
                    requires_approval,
                    approval_status,
                    sender_name,
                    sender_email,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.account_id,
                    message.opportunity_id,
                    message.contact_id,
                    message.recipient_email,
                    normalize_email(message.recipient_email),
                    message.subject,
                    message.body,
                    message.channel,
                    message.direction,
                    message.status,
                    1 if message.requires_approval else 0,
                    message.approval_status,
                    message.sender_name,
                    message.sender_email,
                    json.dumps(message.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)
        return Message(
            id=message_id,
            account_id=message.account_id,
            opportunity_id=message.opportunity_id,
            contact_id=message.contact_id,
            recipient_email=message.recipient_email,
            subject=message.subject,
            body=message.body,
            channel=message.channel,
            direction=message.direction,
            status=message.status,
            requires_approval=message.requires_approval,
            approval_status=message.approval_status,
            sender_name=message.sender_name,
            sender_email=message.sender_email,
            metadata=message.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_message(self, message_id: int) -> Message | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['messages']} WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            return None
        return self._message_from_row(row)

    def update_message_status(
        self,
        message_id: int,
        *,
        status: str | None = None,
        approval_status: str | None = None,
        sender_name: str | None = None,
        sender_email: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        existing = self.get_message(message_id)
        if existing is None:
            raise RuntimeError(f"CRM message {message_id} disappeared")
        merged_metadata = dict(existing.metadata)
        if metadata:
            merged_metadata.update(metadata)
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['messages']}
                SET status = ?,
                    approval_status = ?,
                    sender_name = ?,
                    sender_email = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status or existing.status,
                    approval_status or existing.approval_status,
                    sender_name if sender_name is not None else existing.sender_name,
                    sender_email if sender_email is not None else existing.sender_email,
                    json.dumps(merged_metadata, sort_keys=True),
                    now,
                    message_id,
                ),
            )
        updated = self.get_message(message_id)
        if updated is None:
            raise RuntimeError(f"CRM message {message_id} disappeared")
        return updated

    def list_messages(
        self,
        account_id: int | None = None,
        opportunity_id: int | None = None,
        status: str | None = None,
    ) -> list[Message]:
        t = self.tables
        sql = f"SELECT * FROM {t['messages']}"
        params: list[Any] = []
        clauses: list[str] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._message_from_row(row) for row in rows]

    def create_meeting(self, meeting: Meeting) -> Meeting:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['meetings']} (
                    account_id,
                    opportunity_id,
                    contact_id,
                    scheduled_for,
                    status,
                    owner,
                    notes,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meeting.account_id,
                    meeting.opportunity_id,
                    meeting.contact_id,
                    meeting.scheduled_for,
                    meeting.status,
                    meeting.owner,
                    meeting.notes,
                    json.dumps(meeting.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            meeting_id = int(cursor.lastrowid)
        return Meeting(
            id=meeting_id,
            account_id=meeting.account_id,
            opportunity_id=meeting.opportunity_id,
            contact_id=meeting.contact_id,
            scheduled_for=meeting.scheduled_for,
            status=meeting.status,
            owner=meeting.owner,
            notes=meeting.notes,
            metadata=meeting.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_meeting(self, meeting_id: int) -> Meeting | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['meetings']} WHERE id = ?", (meeting_id,)).fetchone()
        if row is None:
            return None
        return self._meeting_from_row(row)

    def list_meetings(
        self,
        account_id: int | None = None,
        status: str | None = None,
    ) -> list[Meeting]:
        t = self.tables
        sql = f"SELECT * FROM {t['meetings']}"
        params: list[Any] = []
        clauses: list[str] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY scheduled_for ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._meeting_from_row(row) for row in rows]

    def create_proposal(self, proposal: Proposal) -> Proposal:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['proposals']} (
                    account_id,
                    opportunity_id,
                    contact_id,
                    title,
                    status,
                    amount,
                    currency,
                    summary,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.account_id,
                    proposal.opportunity_id,
                    proposal.contact_id,
                    proposal.title,
                    proposal.status,
                    float(proposal.amount),
                    proposal.currency,
                    proposal.summary,
                    json.dumps(proposal.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            proposal_id = int(cursor.lastrowid)
        return Proposal(
            id=proposal_id,
            account_id=proposal.account_id,
            opportunity_id=proposal.opportunity_id,
            contact_id=proposal.contact_id,
            title=proposal.title,
            status=proposal.status,
            amount=float(proposal.amount),
            currency=proposal.currency,
            summary=proposal.summary,
            metadata=proposal.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_proposal(self, proposal_id: int) -> Proposal | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['proposals']} WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            return None
        return self._proposal_from_row(row)

    def list_proposals(
        self,
        account_id: int | None = None,
        opportunity_id: int | None = None,
        status: str | None = None,
    ) -> list[Proposal]:
        t = self.tables
        sql = f"SELECT * FROM {t['proposals']}"
        params: list[Any] = []
        clauses: list[str] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._proposal_from_row(row) for row in rows]

    def create_outcome(self, outcome: Outcome) -> Outcome:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['outcomes']} (
                    account_id,
                    opportunity_id,
                    proposal_id,
                    status,
                    revenue,
                    gross_margin,
                    summary,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.account_id,
                    outcome.opportunity_id,
                    outcome.proposal_id,
                    outcome.status,
                    float(outcome.revenue),
                    float(outcome.gross_margin),
                    outcome.summary,
                    json.dumps(outcome.metadata, sort_keys=True),
                    now,
                    now,
                ),
            )
            outcome_id = int(cursor.lastrowid)
        return Outcome(
            id=outcome_id,
            account_id=outcome.account_id,
            opportunity_id=outcome.opportunity_id,
            proposal_id=outcome.proposal_id,
            status=outcome.status,
            revenue=float(outcome.revenue),
            gross_margin=float(outcome.gross_margin),
            summary=outcome.summary,
            metadata=outcome.metadata,
            created_at=now,
            updated_at=now,
        )

    def get_outcome(self, outcome_id: int) -> Outcome | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {t['outcomes']} WHERE id = ?", (outcome_id,)).fetchone()
        if row is None:
            return None
        return self._outcome_from_row(row)

    def list_outcomes(
        self,
        account_id: int | None = None,
        opportunity_id: int | None = None,
    ) -> list[Outcome]:
        t = self.tables
        sql = f"SELECT * FROM {t['outcomes']}"
        params: list[Any] = []
        clauses: list[str] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._outcome_from_row(row) for row in rows]

    def create_approval_request(self, request: ApprovalRequest) -> ApprovalRequest:
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['approval_requests']} (
                    action_type,
                    entity_type,
                    entity_id,
                    summary,
                    status,
                    requested_by,
                    reviewed_by,
                    review_notes,
                    payload_json,
                    created_at,
                    updated_at,
                    reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.action_type,
                    request.entity_type,
                    request.entity_id,
                    request.summary,
                    request.status,
                    request.requested_by,
                    request.reviewed_by,
                    request.review_notes,
                    json.dumps(request.payload, sort_keys=True),
                    now,
                    now,
                    request.reviewed_at,
                ),
            )
            request_id = int(cursor.lastrowid)
        return ApprovalRequest(
            id=request_id,
            action_type=request.action_type,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            summary=request.summary,
            status=request.status,
            requested_by=request.requested_by,
            reviewed_by=request.reviewed_by,
            review_notes=request.review_notes,
            payload=request.payload,
            created_at=now,
            updated_at=now,
            reviewed_at=request.reviewed_at,
        )

    def get_approval_request(self, request_id: int) -> ApprovalRequest | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {t['approval_requests']} WHERE id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return self._approval_request_from_row(row)

    def find_latest_approval_request(
        self,
        action_type: str,
        entity_type: str,
        entity_id: str,
    ) -> ApprovalRequest | None:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM {t['approval_requests']}
                WHERE action_type = ?
                  AND entity_type = ?
                  AND entity_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (action_type, entity_type, entity_id),
            ).fetchone()
        if row is None:
            return None
        return self._approval_request_from_row(row)

    def update_approval_request_status(
        self,
        request_id: int,
        *,
        status: str,
        reviewed_by: str,
        review_notes: str = "",
    ) -> ApprovalRequest:
        reviewed_at = utc_now() if status in {"approved", "rejected"} else None
        now = utc_now()
        t = self.tables
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {t['approval_requests']}
                SET status = ?,
                    reviewed_by = ?,
                    review_notes = ?,
                    updated_at = ?,
                    reviewed_at = ?
                WHERE id = ?
                """,
                (status, reviewed_by, review_notes, now, reviewed_at, request_id),
            )
        updated = self.get_approval_request(request_id)
        if updated is None:
            raise RuntimeError(f"Approval request {request_id} disappeared")
        if status in {"approved", "rejected"}:
            review_latency_hours = _hours_between(updated.created_at, updated.reviewed_at)
            self.record_telemetry_event(
                TelemetryEvent(
                    event_type="approval_decision",
                    entity_type=updated.entity_type,
                    entity_id=updated.entity_id,
                    status=updated.status,
                    payload={
                        "request_id": updated.id or 0,
                        "action_type": updated.action_type,
                        "summary": updated.summary,
                        "requested_by": updated.requested_by,
                        "reviewed_by": updated.reviewed_by,
                        "review_notes": updated.review_notes,
                        "created_at": updated.created_at or "",
                        "reviewed_at": updated.reviewed_at or "",
                        "review_latency_hours": review_latency_hours,
                    },
                )
            )
        return updated

    def list_approval_requests(self, status: str | None = None) -> list[ApprovalRequest]:
        t = self.tables
        sql = f"SELECT * FROM {t['approval_requests']}"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._approval_request_from_row(row) for row in rows]

    def record_telemetry_event(self, event: TelemetryEvent) -> TelemetryEvent:
        created_at = event.created_at or utc_now()
        t = self.tables
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {t['telemetry_events']} (
                    event_type,
                    entity_type,
                    entity_id,
                    status,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.status,
                    json.dumps(event.payload, sort_keys=True),
                    created_at,
                ),
            )
            event_id = int(cursor.lastrowid)
        return TelemetryEvent(
            id=event_id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            status=event.status,
            payload=event.payload,
            created_at=created_at,
        )

    def list_telemetry_events(self, event_type: str | None = None) -> list[TelemetryEvent]:
        t = self.tables
        sql = f"SELECT * FROM {t['telemetry_events']}"
        params: list[Any] = []
        if event_type:
            sql += " WHERE event_type = ?"
            params.append(event_type)
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._telemetry_event_from_row(row) for row in rows]

    def count_campaign_sends_today(self, campaign_id: int) -> int:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {t['outbox_messages']}
                WHERE campaign_id = ?
                  AND status IN ('dry_run', 'provider_accepted', 'sent')
                  AND DATE(created_at) = DATE('now')
                """,
                (campaign_id,),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def count_total_sends_today(self) -> int:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {t['outbox_messages']}
                WHERE status IN ('dry_run', 'provider_accepted', 'sent')
                  AND DATE(created_at) = DATE('now')
                """
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def count_send_events_today(self, event_type: str) -> int:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {t['send_events']}
                WHERE event_type = ?
                  AND DATE(created_at) = DATE('now')
                """,
                (event_type,),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def count_telemetry_events_today(self, event_type: str) -> int:
        t = self.tables
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {t['telemetry_events']}
                WHERE event_type = ?
                  AND DATE(created_at) = DATE('now')
                """,
                (event_type,),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def status_snapshot(self) -> dict[str, Any]:
        t = self.tables
        state = self.get_agent_state()
        engine_states = self.list_engine_states()
        with self._connect() as conn:
            lead_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['leads']}").fetchone()["total"]
            campaign_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['campaigns']}").fetchone()["total"]
            outbox_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['outbox_messages']}").fetchone()["total"]
            suppression_count = conn.execute(
                f"SELECT COUNT(*) AS total FROM {t['suppression_list']}"
            ).fetchone()["total"]
            account_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['accounts']}").fetchone()["total"]
            contact_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['contacts']}").fetchone()["total"]
            opportunity_count = conn.execute(
                f"SELECT COUNT(*) AS total FROM {t['opportunities']}"
            ).fetchone()["total"]
            approval_count = conn.execute(
                f"SELECT COUNT(*) AS total FROM {t['approval_requests']}"
            ).fetchone()["total"]
            telemetry_count = conn.execute(
                f"SELECT COUNT(*) AS total FROM {t['telemetry_events']}"
            ).fetchone()["total"]
        return {
            "db_path": str(self.db_path),
            "campaigns": int(campaign_count),
            "leads": int(lead_count),
            "outbox_messages": int(outbox_count),
            "suppression_entries": int(suppression_count),
            "accounts": int(account_count),
            "contacts": int(contact_count),
            "crm_opportunities": int(opportunity_count),
            "approval_requests": int(approval_count),
            "telemetry_events": int(telemetry_count),
            "global_kill_switch": state.global_kill_switch,
            "deliverability_status": state.deliverability_status,
            "engine_states": len(engine_states),
            "engine_kill_switches": sum(1 for row in engine_states if row.kill_switch_active),
            "table_namespace": "compat" if t != DEFAULT_TABLES else "default",
        }

    def first_dollar_readiness(self) -> FirstDollarReadiness:
        from nontrading.revenue_audit.store import RevenueAuditStore

        telemetry_events = self.list_telemetry_events()
        audit_store = RevenueAuditStore(self.db_path)
        orders = audit_store.list_orders()
        checkout_sessions = audit_store.list_checkout_sessions()
        payment_events = [
            event
            for event in audit_store.list_payment_events()
            if str(event.status).strip().lower() in {"paid", "succeeded", "completed"}
        ]
        outcomes = self.list_outcomes()
        real_revenue_outcomes = [
            outcome
            for outcome in outcomes
            if not bool(outcome.metadata.get("simulated"))
            and outcome.status in ACTUAL_REVENUE_OUTCOME_STATUSES
            and float(outcome.revenue) > 0.0
        ]
        fulfillment_jobs = audit_store.list_fulfillment_jobs()
        delivered_jobs = [
            job
            for job in fulfillment_jobs
            if str(job.status).strip().lower() in {"completed", "delivered"}
        ]
        monitor_runs = [
            run for run in audit_store.list_monitor_runs() if str(run.status).strip().lower() == "completed"
        ]

        first_research_at = min(
            (
                event.created_at
                for event in telemetry_events
                if event.event_type == "account_researched" and event.created_at
            ),
            default=None,
        )
        first_paid_at = min((event.created_at for event in payment_events if event.created_at), default=None)
        first_revenue_at = min(
            (outcome.created_at for outcome in real_revenue_outcomes if outcome.created_at),
            default=None,
        )
        observed_at = first_revenue_at or first_paid_at
        time_to_first_dollar_hours = _hours_between(first_research_at, observed_at)

        payments_collected_usd = round(sum(float(event.amount_total_usd) for event in payment_events), 2)
        first_paid_datetime = _parse_timestamp(first_paid_at)
        last_paid_datetime = _parse_timestamp(
            max((event.created_at for event in payment_events if event.created_at), default=None)
        )
        expected_30d_cashflow_usd = 0.0
        if payment_events:
            observed_days = 1.0
            if first_paid_datetime is not None and last_paid_datetime is not None:
                observed_days = max((last_paid_datetime - first_paid_datetime).total_seconds() / 86400.0, 1.0)
            expected_30d_cashflow_usd = round((payments_collected_usd / observed_days) * 30.0, 2)

        paid_orders = [order for order in orders if str(order.status).strip().lower() == "paid"]
        if real_revenue_outcomes:
            status = "first_dollar_observed"
        elif payment_events:
            status = "paid_order_seen"
        elif checkout_sessions or orders:
            status = "launchable"
        else:
            status = "setup_only"

        readiness_score = {
            "setup_only": 25.0,
            "launchable": 55.0,
            "paid_order_seen": 80.0,
            "first_dollar_observed": 100.0,
        }[status]
        blockers: list[str] = []
        if status == "setup_only":
            blockers.append("checkout_not_ready")
        if status in {"setup_only", "launchable"}:
            blockers.append("paid_order_not_observed")
        if payment_events and not delivered_jobs:
            blockers.append("fulfillment_delivery_pending")
        if payment_events and not monitor_runs:
            blockers.append("monitor_run_not_completed")

        return FirstDollarReadiness(
            status=status,
            launchable=bool(checkout_sessions or orders or real_revenue_outcomes),
            readiness_score=readiness_score,
            paid_orders_seen=len(paid_orders),
            cash_collected_usd=payments_collected_usd,
            time_to_first_dollar_hours=time_to_first_dollar_hours,
            blockers=tuple(blockers),
            metrics={
                "checkout_sessions_created": len(checkout_sessions),
                "paid_order_seen": bool(payment_events),
                "first_dollar_observed": bool(real_revenue_outcomes),
                "fulfillment_jobs_total": len(fulfillment_jobs),
                "delivered_jobs_total": len(delivered_jobs),
                "completed_monitor_runs": len(monitor_runs),
                "expected_30d_cashflow_usd": expected_30d_cashflow_usd,
                "first_paid_at": first_paid_at,
                "first_revenue_at": first_revenue_at,
            },
        )

    def public_report_snapshot(self) -> dict[str, Any]:
        from nontrading.revenue_audit.store import RevenueAuditStore

        snapshot = self.status_snapshot()
        telemetry_events = self.list_telemetry_events()
        opportunities = self.list_opportunities()
        messages = self.list_messages()
        meetings = self.list_meetings()
        proposals = self.list_proposals()
        outcomes = self.list_outcomes()
        approval_requests = self.list_approval_requests()
        outbox_messages = self.list_outbox_messages()
        audit_store = RevenueAuditStore(self.db_path)
        checkout_sessions = audit_store.list_checkout_sessions()
        payment_events = audit_store.list_payment_events()
        fulfillment_jobs = audit_store.list_fulfillment_jobs()
        monitor_runs = audit_store.list_monitor_runs()
        readiness = self.first_dollar_readiness()

        account_researched_events = [event for event in telemetry_events if event.event_type == "account_researched"]
        cycle_events = [event for event in telemetry_events if event.event_type == "cycle_complete"]
        fulfillment_events = [event for event in telemetry_events if event.event_type == "fulfillment_status_changed"]
        approval_decisions = [event for event in telemetry_events if event.event_type == "approval_decision"]

        qualified_account_ids = {
            opportunity.account_id
            for opportunity in opportunities
            if opportunity.stage == "qualified"
            or opportunity.status not in {"research_only", "closed_lost"}
            or float(opportunity.score) >= 70.0
        }
        delivered_messages = [
            message
            for message in messages
            if message.direction == "outbound" and message.status in SUCCESSFUL_MESSAGE_STATUSES
        ]
        replies_recorded = [
            message
            for message in messages
            if message.direction == "inbound" and message.status == "received"
        ]
        meetings_booked = [meeting for meeting in meetings if meeting.status in {"booked", "completed"}]
        proposals_sent = [proposal for proposal in proposals if proposal.status == "sent"]
        actual_outcomes = [outcome for outcome in outcomes if not bool(outcome.metadata.get("simulated"))]
        simulated_outcomes = [outcome for outcome in outcomes if bool(outcome.metadata.get("simulated"))]
        revenue_outcomes = [
            outcome
            for outcome in actual_outcomes
            if outcome.status in ACTUAL_REVENUE_OUTCOME_STATUSES and float(outcome.revenue) > 0.0
        ]
        paid_payment_events = [
            event
            for event in payment_events
            if str(event.status).strip().lower() in {"paid", "succeeded", "completed"}
        ]

        revenue_won_usd = round(sum(float(outcome.revenue) for outcome in revenue_outcomes), 2)
        gross_margin_usd = round(sum(float(outcome.gross_margin) for outcome in revenue_outcomes), 2)
        gross_margin_pct = round(gross_margin_usd / revenue_won_usd, 6) if revenue_won_usd > 0 else None
        first_research_at = min(
            (event.created_at for event in account_researched_events if event.created_at),
            default=None,
        )
        first_revenue_at = min(
            (outcome.created_at for outcome in revenue_outcomes if outcome.created_at),
            default=None,
        )
        time_to_first_dollar_hours = _hours_between(first_research_at, first_revenue_at)

        approval_latencies = [
            latency
            for request in approval_requests
            if request.status in {"approved", "rejected"}
            and (latency := _hours_between(request.created_at, request.reviewed_at)) is not None
        ]
        median_approval_latency_hours = (
            round(statistics.median(approval_latencies), 6) if approval_latencies else None
        )

        latest_fulfillment_event = fulfillment_events[-1] if fulfillment_events else None
        fulfillment_status_counts: dict[str, int] = {}
        for event in fulfillment_events:
            status = str(event.status or event.payload.get("fulfillment_status") or "unknown")
            fulfillment_status_counts[status] = fulfillment_status_counts.get(status, 0) + 1

        if revenue_won_usd > 0.0:
            current_phase = "phase_0_revenue_evidence"
            claim_status = "actual_revenue_recorded"
            claim_reason = "Closed-won JJ-N revenue is recorded in repo-tracked outcomes."
        elif paid_payment_events:
            current_phase = "phase_0_revenue_evidence"
            claim_status = "payment_recorded"
            claim_reason = "A paid JJ-N order is recorded and fulfillment can proceed without manual DB edits."
        elif proposals_sent or actual_outcomes:
            current_phase = "phase_0_offer_ready"
            claim_status = "pipeline_only_no_revenue"
            claim_reason = "JJ-N has proposal and outcome plumbing, but no closed-won revenue is recorded yet."
        elif delivered_messages:
            current_phase = "phase_0_outreach_active"
            claim_status = "paper_funnel_only"
            claim_reason = "JJ-N has outreach activity, but revenue proof is not recorded yet."
        elif qualified_account_ids:
            current_phase = "phase_0_pipeline_seeded"
            claim_status = "qualification_only"
            claim_reason = "JJ-N is qualifying targets, but outreach and revenue proof remain pre-launch."
        elif account_researched_events:
            current_phase = "phase_0_research_active"
            claim_status = "research_only"
            claim_reason = "JJ-N has researched accounts in repo-tracked telemetry, but qualification and revenue proof remain pre-launch."
        else:
            current_phase = "phase_0_setup"
            claim_status = "setup_only"
            claim_reason = "JJ-N remains in setup and dry-run instrumentation mode."

        live_delivery_observed = any(
            message.provider != "dry_run" and message.status in SUCCESSFUL_OUTBOX_STATUSES
            for message in outbox_messages
        )
        latest_event_at = max(
            (event.created_at for event in telemetry_events if event.created_at),
            default=None,
        )
        latest_cycle_completed_at = max(
            (
                str(event.payload.get("completed_at") or event.created_at)
                for event in cycle_events
                if event.created_at
            ),
            default=None,
        )

        return {
            "schema_version": PUBLIC_REPORT_SCHEMA,
            "generated_at": utc_now(),
            "funnel": {
                "researched_accounts": len(account_researched_events),
                "qualified_accounts": len(qualified_account_ids),
                "delivered_messages": len(delivered_messages),
                "reply_rate": round(len(replies_recorded) / len(delivered_messages), 6) if delivered_messages else None,
                "meetings_booked": len(meetings_booked),
                "proposals_sent": len(proposals_sent),
                "outcomes_recorded": len(actual_outcomes),
                "simulated_outcomes_recorded": len(simulated_outcomes),
            },
            "commercial": {
                "revenue_won_usd": revenue_won_usd,
                "payments_collected_usd": round(
                    sum(float(event.amount_total_usd) for event in paid_payment_events),
                    2,
                ),
                "paid_orders_count": len(paid_payment_events),
                "gross_margin_usd": gross_margin_usd,
                "gross_margin_pct": gross_margin_pct,
                "time_to_first_dollar_hours": time_to_first_dollar_hours,
                "time_to_first_dollar_status": (
                    "observed" if time_to_first_dollar_hours is not None else "not_yet_observed"
                ),
            },
            "approval": {
                "pending_requests": sum(1 for request in approval_requests if request.status == "pending"),
                "approved_requests": sum(1 for request in approval_requests if request.status == "approved"),
                "rejected_requests": sum(1 for request in approval_requests if request.status == "rejected"),
                "decisions_recorded": len(approval_decisions),
                "median_review_latency_hours": median_approval_latency_hours,
            },
            "fulfillment": {
                "events_recorded": len(fulfillment_events),
                "status_counts": fulfillment_status_counts,
                "jobs_total": len(fulfillment_jobs),
                "delivered_jobs": sum(
                    1
                    for job in fulfillment_jobs
                    if str(job.status).strip().lower() in {"completed", "delivered"}
                ),
                "monitor_runs_completed": sum(
                    1 for run in monitor_runs if str(run.status).strip().lower() == "completed"
                ),
                "latest_status": (
                    str(
                        (latest_fulfillment_event.payload.get("fulfillment_status") if latest_fulfillment_event else "")
                        or (latest_fulfillment_event.status if latest_fulfillment_event else "")
                        or ""
                    )
                    or None
                ),
                "delivery_claim_status": "live_delivery_observed" if live_delivery_observed else "no_live_delivery_observed",
            },
            "phase": {
                "current_phase": current_phase,
                "claim_status": claim_status,
                "claim_reason": claim_reason,
            },
            "freshness": {
                "latest_event_at": latest_event_at,
                "latest_cycle_completed_at": latest_cycle_completed_at,
                "first_account_researched_at": first_research_at,
                "first_revenue_at": first_revenue_at,
            },
            "source_snapshot": {
                "db_path": str(self.db_path),
                "table_namespace": snapshot["table_namespace"],
                "telemetry_dataset": "elastifund.nontrading",
                "accounts": snapshot["accounts"],
                "crm_opportunities": snapshot["crm_opportunities"],
                "approval_requests": snapshot["approval_requests"],
                "telemetry_events": snapshot["telemetry_events"],
                "checkout_sessions": len(checkout_sessions),
                "payment_events": len(payment_events),
            },
            "first_dollar_readiness": readiness.to_dict(),
            "operations": {
                "checkout_sessions_created": len(checkout_sessions),
                "payment_events_recorded": len(payment_events),
                "fulfillment_jobs_total": len(fulfillment_jobs),
                "monitor_runs_total": len(monitor_runs),
            },
        }
