"""SQLite store for the non-trading revenue agent."""

from __future__ import annotations

import json
import logging
import sqlite3
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
from nontrading.store_contracts import (
    COMPAT_TABLES,
    DEFAULT_TABLES,
    REQUIRED_DEFAULT_COLUMNS,
)
from nontrading.store_crm_mixin import RevenueStoreCrmMixin
from nontrading.store_reporting_mixin import RevenueStoreReportingMixin

logger = logging.getLogger("nontrading.store")


class RevenueStore(RevenueStoreCrmMixin, RevenueStoreReportingMixin):
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
