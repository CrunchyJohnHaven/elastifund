"""SQLite persistence for revenue_audit checkout, payment, and fulfillment state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from nontrading.revenue_audit.contracts import (
    AuditBundle,
    AuditOrder,
    CheckoutSession,
    FulfillmentJob,
    MonitorRun,
    PaymentEvent,
    ProspectProfile,
    RecurringMonitorEnrollment,
)


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class RevenueAuditStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    @classmethod
    def _ensure_column(
        cls,
        conn: sqlite3.Connection,
        *,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        if column_name in cls._table_columns(conn, table_name):
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS revenue_audit_orders (
                    order_id TEXT PRIMARY KEY,
                    offer_slug TEXT NOT NULL,
                    price_key TEXT NOT NULL,
                    amount_subtotal_usd REAL NOT NULL,
                    amount_total_usd REAL NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fulfillment_status TEXT NOT NULL,
                    customer_email TEXT NOT NULL DEFAULT '',
                    customer_name TEXT NOT NULL DEFAULT '',
                    business_name TEXT NOT NULL DEFAULT '',
                    website_url TEXT NOT NULL DEFAULT '',
                    crm_account_id INTEGER,
                    crm_opportunity_id INTEGER,
                    crm_proposal_id INTEGER,
                    crm_outcome_id INTEGER,
                    prospect_profile_json TEXT NOT NULL DEFAULT '{}',
                    audit_bundle_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    paid_at TEXT,
                    delivered_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_revenue_audit_orders_status
                    ON revenue_audit_orders(status, updated_at);

                CREATE TABLE IF NOT EXISTS revenue_audit_checkout_sessions (
                    session_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_session_id TEXT NOT NULL UNIQUE,
                    provider_payment_intent_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    hosted_url TEXT NOT NULL DEFAULT '',
                    amount_subtotal_usd REAL NOT NULL,
                    amount_total_usd REAL NOT NULL,
                    currency TEXT NOT NULL,
                    customer_email TEXT NOT NULL DEFAULT '',
                    expires_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES revenue_audit_orders(order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_revenue_audit_checkout_sessions_order
                    ON revenue_audit_checkout_sessions(order_id, updated_at);

                CREATE TABLE IF NOT EXISTS revenue_audit_payment_events (
                    payment_event_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    amount_total_usd REAL NOT NULL,
                    currency TEXT NOT NULL,
                    provider_session_id TEXT NOT NULL DEFAULT '',
                    provider_payment_intent_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES revenue_audit_orders(order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_revenue_audit_payment_events_order
                    ON revenue_audit_payment_events(order_id, created_at);

                CREATE TABLE IF NOT EXISTS revenue_audit_fulfillment_jobs (
                    job_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_uri TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES revenue_audit_orders(order_id),
                    UNIQUE(order_id, job_type)
                );
                CREATE INDEX IF NOT EXISTS idx_revenue_audit_fulfillment_jobs_order
                    ON revenue_audit_fulfillment_jobs(order_id, updated_at);

                CREATE TABLE IF NOT EXISTS revenue_audit_monitor_runs (
                    run_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    baseline_bundle_id TEXT NOT NULL DEFAULT '',
                    current_bundle_id TEXT NOT NULL DEFAULT '',
                    recurring_monitor_enrollment_id TEXT NOT NULL DEFAULT '',
                    delta_summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES revenue_audit_orders(order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_revenue_audit_monitor_runs_order
                    ON revenue_audit_monitor_runs(order_id, updated_at);

                CREATE TABLE IF NOT EXISTS revenue_audit_recurring_monitor_enrollments (
                    enrollment_id TEXT PRIMARY KEY,
                    audit_order_id TEXT NOT NULL,
                    offer_slug TEXT NOT NULL,
                    parent_offer_slug TEXT NOT NULL,
                    monitor_order_id TEXT DEFAULT NULL,
                    price_key TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    cadence_days INTEGER NOT NULL,
                    monthly_amount_usd REAL NOT NULL,
                    currency TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_subscription_id TEXT NOT NULL DEFAULT '',
                    checkout_session_id TEXT NOT NULL DEFAULT '',
                    source_payment_event_id TEXT NOT NULL DEFAULT '',
                    latest_monitor_run_id TEXT NOT NULL DEFAULT '',
                    monitor_runs_completed INTEGER NOT NULL DEFAULT 0,
                    next_run_at TEXT,
                    enrolled_at TEXT,
                    canceled_at TEXT,
                    churned_at TEXT,
                    refunded_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(audit_order_id) REFERENCES revenue_audit_orders(order_id),
                    FOREIGN KEY(monitor_order_id) REFERENCES revenue_audit_orders(order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_revenue_audit_recurring_monitor_enrollments_audit_order
                    ON revenue_audit_recurring_monitor_enrollments(audit_order_id, updated_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_revenue_audit_recurring_monitor_enrollments_monitor_order
                    ON revenue_audit_recurring_monitor_enrollments(monitor_order_id)
                    WHERE monitor_order_id IS NOT NULL AND monitor_order_id != '';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_revenue_audit_recurring_monitor_enrollments_subscription
                    ON revenue_audit_recurring_monitor_enrollments(provider_subscription_id)
                    WHERE provider_subscription_id != '';
                """
            )
            self._ensure_column(
                conn,
                table_name="revenue_audit_monitor_runs",
                column_name="recurring_monitor_enrollment_id",
                column_sql="TEXT NOT NULL DEFAULT ''",
            )

    def _prospect_profile_from_json(self, value: str | None) -> ProspectProfile | None:
        payload = _json_load(value)
        return ProspectProfile(**payload) if payload else None

    def _audit_bundle_from_json(self, value: str | None) -> AuditBundle | None:
        payload = _json_load(value)
        if not payload:
            return None
        prospect_payload = payload.get("prospect")
        issue_payloads = payload.get("issues", [])
        if prospect_payload:
            payload["prospect"] = ProspectProfile(**prospect_payload)
        if issue_payloads:
            from nontrading.revenue_audit.contracts import IssueEvidence

            payload["issues"] = tuple(IssueEvidence(**item) for item in issue_payloads)
        return AuditBundle(**payload)

    def _order_from_row(self, row: sqlite3.Row) -> AuditOrder:
        return AuditOrder(
            order_id=row["order_id"],
            offer_slug=row["offer_slug"],
            price_key=row["price_key"],
            amount_subtotal_usd=float(row["amount_subtotal_usd"]),
            amount_total_usd=float(row["amount_total_usd"]),
            currency=row["currency"],
            status=row["status"],
            fulfillment_status=row["fulfillment_status"],
            customer_email=row["customer_email"],
            customer_name=row["customer_name"],
            business_name=row["business_name"],
            website_url=row["website_url"],
            crm_account_id=row["crm_account_id"],
            crm_opportunity_id=row["crm_opportunity_id"],
            crm_proposal_id=row["crm_proposal_id"],
            crm_outcome_id=row["crm_outcome_id"],
            prospect_profile=self._prospect_profile_from_json(row["prospect_profile_json"]),
            audit_bundle=self._audit_bundle_from_json(row["audit_bundle_json"]),
            metadata=_json_load(row["metadata_json"]),
            paid_at=row["paid_at"],
            delivered_at=row["delivered_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _checkout_session_from_row(self, row: sqlite3.Row) -> CheckoutSession:
        return CheckoutSession(
            session_id=row["session_id"],
            order_id=row["order_id"],
            provider=row["provider"],
            provider_session_id=row["provider_session_id"],
            provider_payment_intent_id=row["provider_payment_intent_id"],
            status=row["status"],
            hosted_url=row["hosted_url"],
            amount_subtotal_usd=float(row["amount_subtotal_usd"]),
            amount_total_usd=float(row["amount_total_usd"]),
            currency=row["currency"],
            customer_email=row["customer_email"],
            expires_at=row["expires_at"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _payment_event_from_row(self, row: sqlite3.Row) -> PaymentEvent:
        return PaymentEvent(
            payment_event_id=row["payment_event_id"],
            order_id=row["order_id"],
            provider=row["provider"],
            provider_event_id=row["provider_event_id"],
            event_type=row["event_type"],
            status=row["status"],
            amount_total_usd=float(row["amount_total_usd"]),
            currency=row["currency"],
            provider_session_id=row["provider_session_id"],
            provider_payment_intent_id=row["provider_payment_intent_id"],
            payload=_json_load(row["payload_json"]),
            created_at=row["created_at"],
        )

    def _fulfillment_job_from_row(self, row: sqlite3.Row) -> FulfillmentJob:
        return FulfillmentJob(
            job_id=row["job_id"],
            order_id=row["order_id"],
            job_type=row["job_type"],
            status=row["status"],
            artifact_uri=row["artifact_uri"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _monitor_run_from_row(self, row: sqlite3.Row) -> MonitorRun:
        return MonitorRun(
            run_id=row["run_id"],
            order_id=row["order_id"],
            status=row["status"],
            baseline_bundle_id=row["baseline_bundle_id"],
            current_bundle_id=row["current_bundle_id"],
            recurring_monitor_enrollment_id=row["recurring_monitor_enrollment_id"],
            delta_summary=row["delta_summary"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _recurring_monitor_enrollment_from_row(self, row: sqlite3.Row) -> RecurringMonitorEnrollment:
        return RecurringMonitorEnrollment(
            enrollment_id=row["enrollment_id"],
            audit_order_id=row["audit_order_id"],
            offer_slug=row["offer_slug"],
            parent_offer_slug=row["parent_offer_slug"],
            monitor_order_id=row["monitor_order_id"],
            price_key=row["price_key"],
            status=row["status"],
            cadence_days=int(row["cadence_days"]),
            monthly_amount_usd=float(row["monthly_amount_usd"]),
            currency=row["currency"],
            provider=row["provider"],
            provider_subscription_id=row["provider_subscription_id"],
            checkout_session_id=row["checkout_session_id"],
            source_payment_event_id=row["source_payment_event_id"],
            latest_monitor_run_id=row["latest_monitor_run_id"],
            monitor_runs_completed=int(row["monitor_runs_completed"]),
            next_run_at=row["next_run_at"],
            enrolled_at=row["enrolled_at"],
            canceled_at=row["canceled_at"],
            churned_at=row["churned_at"],
            refunded_at=row["refunded_at"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_order(self, order: AuditOrder) -> AuditOrder:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_audit_orders (
                    order_id, offer_slug, price_key, amount_subtotal_usd, amount_total_usd,
                    currency, status, fulfillment_status, customer_email, customer_name,
                    business_name, website_url, crm_account_id, crm_opportunity_id,
                    crm_proposal_id, crm_outcome_id, prospect_profile_json, audit_bundle_json,
                    metadata_json, paid_at, delivered_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.offer_slug,
                    order.price_key,
                    order.amount_subtotal_usd,
                    order.amount_total_usd,
                    order.currency,
                    order.status,
                    order.fulfillment_status,
                    order.customer_email,
                    order.customer_name,
                    order.business_name,
                    order.website_url,
                    order.crm_account_id,
                    order.crm_opportunity_id,
                    order.crm_proposal_id,
                    order.crm_outcome_id,
                    json.dumps(order.prospect_profile.__dict__ if order.prospect_profile else {}, sort_keys=True),
                    json.dumps(order.audit_bundle, default=lambda item: item.__dict__, sort_keys=True),
                    json.dumps(order.metadata, sort_keys=True),
                    order.paid_at,
                    order.delivered_at,
                    order.created_at,
                    order.updated_at,
                ),
            )
        return self.get_order(order.order_id) or order

    def get_order(self, order_id: str) -> AuditOrder | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM revenue_audit_orders WHERE order_id = ?",
                (str(order_id).strip(),),
            ).fetchone()
        return self._order_from_row(row) if row is not None else None

    def list_orders(self) -> list[AuditOrder]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM revenue_audit_orders
                ORDER BY created_at ASC, order_id ASC
                """
            ).fetchall()
        return [self._order_from_row(row) for row in rows]

    def update_order(self, order_id: str, **fields: Any) -> AuditOrder:
        existing = self.get_order(order_id)
        if existing is None:
            raise RuntimeError(f"Revenue audit order {order_id} disappeared")
        updated = AuditOrder(
            order_id=existing.order_id,
            offer_slug=str(fields.get("offer_slug", existing.offer_slug)),
            price_key=str(fields.get("price_key", existing.price_key)),
            amount_subtotal_usd=float(fields.get("amount_subtotal_usd", existing.amount_subtotal_usd)),
            amount_total_usd=float(fields.get("amount_total_usd", existing.amount_total_usd)),
            currency=str(fields.get("currency", existing.currency)),
            status=str(fields.get("status", existing.status)),
            fulfillment_status=str(fields.get("fulfillment_status", existing.fulfillment_status)),
            customer_email=str(fields.get("customer_email", existing.customer_email)),
            customer_name=str(fields.get("customer_name", existing.customer_name)),
            business_name=str(fields.get("business_name", existing.business_name)),
            website_url=str(fields.get("website_url", existing.website_url)),
            crm_account_id=fields.get("crm_account_id", existing.crm_account_id),
            crm_opportunity_id=fields.get("crm_opportunity_id", existing.crm_opportunity_id),
            crm_proposal_id=fields.get("crm_proposal_id", existing.crm_proposal_id),
            crm_outcome_id=fields.get("crm_outcome_id", existing.crm_outcome_id),
            prospect_profile=fields.get("prospect_profile", existing.prospect_profile),
            audit_bundle=fields.get("audit_bundle", existing.audit_bundle),
            metadata=dict(fields.get("metadata", existing.metadata)),
            paid_at=fields.get("paid_at", existing.paid_at),
            delivered_at=fields.get("delivered_at", existing.delivered_at),
            created_at=existing.created_at,
            updated_at=str(fields.get("updated_at", existing.updated_at)),
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE revenue_audit_orders
                SET offer_slug = ?, price_key = ?, amount_subtotal_usd = ?, amount_total_usd = ?,
                    currency = ?, status = ?, fulfillment_status = ?, customer_email = ?,
                    customer_name = ?, business_name = ?, website_url = ?, crm_account_id = ?,
                    crm_opportunity_id = ?, crm_proposal_id = ?, crm_outcome_id = ?,
                    prospect_profile_json = ?, audit_bundle_json = ?, metadata_json = ?,
                    paid_at = ?, delivered_at = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (
                    updated.offer_slug,
                    updated.price_key,
                    updated.amount_subtotal_usd,
                    updated.amount_total_usd,
                    updated.currency,
                    updated.status,
                    updated.fulfillment_status,
                    updated.customer_email,
                    updated.customer_name,
                    updated.business_name,
                    updated.website_url,
                    updated.crm_account_id,
                    updated.crm_opportunity_id,
                    updated.crm_proposal_id,
                    updated.crm_outcome_id,
                    json.dumps(updated.prospect_profile.__dict__ if updated.prospect_profile else {}, sort_keys=True),
                    json.dumps(updated.audit_bundle, default=lambda item: item.__dict__, sort_keys=True),
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.paid_at,
                    updated.delivered_at,
                    updated.updated_at,
                    updated.order_id,
                ),
            )
        return self.get_order(order_id) or updated

    def create_checkout_session(self, checkout_session: CheckoutSession) -> CheckoutSession:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_audit_checkout_sessions (
                    session_id, order_id, provider, provider_session_id, provider_payment_intent_id,
                    status, hosted_url, amount_subtotal_usd, amount_total_usd, currency,
                    customer_email, expires_at, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkout_session.session_id,
                    checkout_session.order_id,
                    checkout_session.provider,
                    checkout_session.provider_session_id,
                    checkout_session.provider_payment_intent_id,
                    checkout_session.status,
                    checkout_session.hosted_url,
                    checkout_session.amount_subtotal_usd,
                    checkout_session.amount_total_usd,
                    checkout_session.currency,
                    checkout_session.customer_email,
                    checkout_session.expires_at,
                    json.dumps(checkout_session.metadata, sort_keys=True),
                    checkout_session.created_at,
                    checkout_session.updated_at,
                ),
            )
        return self.get_checkout_session(checkout_session.session_id) or checkout_session

    def get_checkout_session(self, session_id: str) -> CheckoutSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM revenue_audit_checkout_sessions WHERE session_id = ?",
                (str(session_id).strip(),),
            ).fetchone()
        return self._checkout_session_from_row(row) if row is not None else None

    def list_checkout_sessions(self, order_id: str | None = None) -> list[CheckoutSession]:
        params: tuple[Any, ...] = ()
        query = """
            SELECT * FROM revenue_audit_checkout_sessions
        """
        if order_id is not None:
            query += " WHERE order_id = ?"
            params = (str(order_id).strip(),)
        query += " ORDER BY created_at ASC, session_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._checkout_session_from_row(row) for row in rows]

    def get_checkout_session_by_order(self, order_id: str) -> CheckoutSession | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_checkout_sessions
                WHERE order_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (str(order_id).strip(),),
            ).fetchone()
        return self._checkout_session_from_row(row) if row is not None else None

    def get_checkout_session_by_provider_session_id(self, provider_session_id: str) -> CheckoutSession | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_checkout_sessions
                WHERE provider_session_id = ?
                LIMIT 1
                """,
                (str(provider_session_id).strip(),),
            ).fetchone()
        return self._checkout_session_from_row(row) if row is not None else None

    def get_checkout_session_by_payment_intent(self, provider_payment_intent_id: str) -> CheckoutSession | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_checkout_sessions
                WHERE provider_payment_intent_id = ?
                LIMIT 1
                """,
                (str(provider_payment_intent_id).strip(),),
            ).fetchone()
        return self._checkout_session_from_row(row) if row is not None else None

    def update_checkout_session(self, session_id: str, **fields: Any) -> CheckoutSession:
        existing = self.get_checkout_session(session_id)
        if existing is None:
            raise RuntimeError(f"Revenue audit checkout session {session_id} disappeared")
        updated = CheckoutSession(
            session_id=existing.session_id,
            order_id=str(fields.get("order_id", existing.order_id)),
            provider=str(fields.get("provider", existing.provider)),
            provider_session_id=str(fields.get("provider_session_id", existing.provider_session_id)),
            provider_payment_intent_id=str(
                fields.get("provider_payment_intent_id", existing.provider_payment_intent_id)
            ),
            status=str(fields.get("status", existing.status)),
            hosted_url=str(fields.get("hosted_url", existing.hosted_url)),
            amount_subtotal_usd=float(fields.get("amount_subtotal_usd", existing.amount_subtotal_usd)),
            amount_total_usd=float(fields.get("amount_total_usd", existing.amount_total_usd)),
            currency=str(fields.get("currency", existing.currency)),
            customer_email=str(fields.get("customer_email", existing.customer_email)),
            expires_at=fields.get("expires_at", existing.expires_at),
            metadata=dict(fields.get("metadata", existing.metadata)),
            created_at=existing.created_at,
            updated_at=str(fields.get("updated_at", existing.updated_at)),
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE revenue_audit_checkout_sessions
                SET order_id = ?, provider = ?, provider_session_id = ?, provider_payment_intent_id = ?,
                    status = ?, hosted_url = ?, amount_subtotal_usd = ?, amount_total_usd = ?,
                    currency = ?, customer_email = ?, expires_at = ?, metadata_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    updated.order_id,
                    updated.provider,
                    updated.provider_session_id,
                    updated.provider_payment_intent_id,
                    updated.status,
                    updated.hosted_url,
                    updated.amount_subtotal_usd,
                    updated.amount_total_usd,
                    updated.currency,
                    updated.customer_email,
                    updated.expires_at,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    updated.session_id,
                ),
            )
        return self.get_checkout_session(session_id) or updated

    def get_payment_event_by_provider_event_id(self, provider_event_id: str) -> PaymentEvent | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_payment_events
                WHERE provider_event_id = ?
                LIMIT 1
                """,
                (str(provider_event_id).strip(),),
            ).fetchone()
        return self._payment_event_from_row(row) if row is not None else None

    def record_payment_event(self, payment_event: PaymentEvent) -> PaymentEvent:
        existing = self.get_payment_event_by_provider_event_id(payment_event.provider_event_id)
        if existing is not None:
            return existing
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_audit_payment_events (
                    payment_event_id, order_id, provider, provider_event_id, event_type,
                    status, amount_total_usd, currency, provider_session_id,
                    provider_payment_intent_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment_event.payment_event_id,
                    payment_event.order_id,
                    payment_event.provider,
                    payment_event.provider_event_id,
                    payment_event.event_type,
                    payment_event.status,
                    payment_event.amount_total_usd,
                    payment_event.currency,
                    payment_event.provider_session_id,
                    payment_event.provider_payment_intent_id,
                    json.dumps(payment_event.payload, sort_keys=True),
                    payment_event.created_at,
                ),
            )
        return self.get_payment_event_by_provider_event_id(payment_event.provider_event_id) or payment_event

    def list_payment_events(self, order_id: str | None = None) -> list[PaymentEvent]:
        params: tuple[Any, ...] = ()
        query = """
            SELECT * FROM revenue_audit_payment_events
        """
        if order_id is not None:
            query += " WHERE order_id = ?"
            params = (str(order_id).strip(),)
        query += " ORDER BY created_at ASC, payment_event_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._payment_event_from_row(row) for row in rows]

    def get_fulfillment_job(self, job_id: str) -> FulfillmentJob | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM revenue_audit_fulfillment_jobs WHERE job_id = ?",
                (str(job_id).strip(),),
            ).fetchone()
        return self._fulfillment_job_from_row(row) if row is not None else None

    def find_fulfillment_job(self, order_id: str, job_type: str) -> FulfillmentJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_fulfillment_jobs
                WHERE order_id = ? AND job_type = ?
                LIMIT 1
                """,
                (str(order_id).strip(), str(job_type).strip().lower()),
            ).fetchone()
        return self._fulfillment_job_from_row(row) if row is not None else None

    def create_fulfillment_job(self, fulfillment_job: FulfillmentJob) -> FulfillmentJob:
        existing = self.find_fulfillment_job(fulfillment_job.order_id, fulfillment_job.job_type)
        if existing is not None:
            return existing
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_audit_fulfillment_jobs (
                    job_id, order_id, job_type, status, artifact_uri, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fulfillment_job.job_id,
                    fulfillment_job.order_id,
                    fulfillment_job.job_type,
                    fulfillment_job.status,
                    fulfillment_job.artifact_uri,
                    json.dumps(fulfillment_job.metadata, sort_keys=True),
                    fulfillment_job.created_at,
                    fulfillment_job.updated_at,
                ),
            )
        return self.find_fulfillment_job(fulfillment_job.order_id, fulfillment_job.job_type) or fulfillment_job

    def update_fulfillment_job(self, job_id: str, **fields: Any) -> FulfillmentJob:
        existing = self.get_fulfillment_job(job_id)
        if existing is None:
            raise RuntimeError(f"Revenue audit fulfillment job {job_id} disappeared")
        updated = FulfillmentJob(
            job_id=existing.job_id,
            order_id=str(fields.get("order_id", existing.order_id)),
            job_type=str(fields.get("job_type", existing.job_type)),
            status=str(fields.get("status", existing.status)),
            artifact_uri=str(fields.get("artifact_uri", existing.artifact_uri)),
            metadata=dict(fields.get("metadata", existing.metadata)),
            created_at=existing.created_at,
            updated_at=str(fields.get("updated_at", existing.updated_at)),
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE revenue_audit_fulfillment_jobs
                SET order_id = ?, job_type = ?, status = ?, artifact_uri = ?, metadata_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    updated.order_id,
                    updated.job_type,
                    updated.status,
                    updated.artifact_uri,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    updated.job_id,
                ),
            )
        return self.get_fulfillment_job(job_id) or updated

    def list_fulfillment_jobs(self, order_id: str | None = None) -> list[FulfillmentJob]:
        params: tuple[Any, ...] = ()
        query = """
            SELECT * FROM revenue_audit_fulfillment_jobs
        """
        if order_id is not None:
            query += " WHERE order_id = ?"
            params = (str(order_id).strip(),)
        query += " ORDER BY created_at ASC, job_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._fulfillment_job_from_row(row) for row in rows]

    def list_monitor_runs(
        self,
        order_id: str | None = None,
        *,
        recurring_monitor_enrollment_id: str | None = None,
    ) -> list[MonitorRun]:
        params: list[Any] = []
        query = """
            SELECT * FROM revenue_audit_monitor_runs
        """
        conditions: list[str] = []
        if order_id is not None:
            conditions.append("order_id = ?")
            params.append(str(order_id).strip())
        if recurring_monitor_enrollment_id is not None:
            conditions.append("recurring_monitor_enrollment_id = ?")
            params.append(str(recurring_monitor_enrollment_id).strip())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at ASC, run_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._monitor_run_from_row(row) for row in rows]

    def create_monitor_run(self, monitor_run: MonitorRun) -> MonitorRun:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_audit_monitor_runs (
                    run_id, order_id, status, baseline_bundle_id, current_bundle_id,
                    recurring_monitor_enrollment_id, delta_summary, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    monitor_run.run_id,
                    monitor_run.order_id,
                    monitor_run.status,
                    monitor_run.baseline_bundle_id,
                    monitor_run.current_bundle_id,
                    monitor_run.recurring_monitor_enrollment_id,
                    monitor_run.delta_summary,
                    json.dumps(monitor_run.metadata, sort_keys=True),
                    monitor_run.created_at,
                    monitor_run.updated_at,
                ),
            )
        return self.list_monitor_runs(monitor_run.order_id)[-1]

    def get_recurring_monitor_enrollment(self, enrollment_id: str) -> RecurringMonitorEnrollment | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_recurring_monitor_enrollments
                WHERE enrollment_id = ?
                LIMIT 1
                """,
                (str(enrollment_id).strip(),),
            ).fetchone()
        return self._recurring_monitor_enrollment_from_row(row) if row is not None else None

    def find_recurring_monitor_enrollment_by_audit_order(
        self,
        audit_order_id: str,
    ) -> RecurringMonitorEnrollment | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_recurring_monitor_enrollments
                WHERE audit_order_id = ?
                ORDER BY created_at DESC, enrollment_id DESC
                LIMIT 1
                """,
                (str(audit_order_id).strip(),),
            ).fetchone()
        return self._recurring_monitor_enrollment_from_row(row) if row is not None else None

    def find_recurring_monitor_enrollment_by_monitor_order(
        self,
        monitor_order_id: str,
    ) -> RecurringMonitorEnrollment | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_recurring_monitor_enrollments
                WHERE monitor_order_id = ?
                LIMIT 1
                """,
                (str(monitor_order_id).strip(),),
            ).fetchone()
        return self._recurring_monitor_enrollment_from_row(row) if row is not None else None

    def find_recurring_monitor_enrollment_by_subscription(
        self,
        provider_subscription_id: str,
    ) -> RecurringMonitorEnrollment | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM revenue_audit_recurring_monitor_enrollments
                WHERE provider_subscription_id = ?
                LIMIT 1
                """,
                (str(provider_subscription_id).strip(),),
            ).fetchone()
        return self._recurring_monitor_enrollment_from_row(row) if row is not None else None

    def list_recurring_monitor_enrollments(
        self,
        *,
        audit_order_id: str | None = None,
        status: str | None = None,
    ) -> list[RecurringMonitorEnrollment]:
        params: list[Any] = []
        query = """
            SELECT * FROM revenue_audit_recurring_monitor_enrollments
        """
        conditions: list[str] = []
        if audit_order_id is not None:
            conditions.append("audit_order_id = ?")
            params.append(str(audit_order_id).strip())
        if status is not None:
            conditions.append("status = ?")
            params.append(str(status).strip().lower())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at ASC, enrollment_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._recurring_monitor_enrollment_from_row(row) for row in rows]

    def create_recurring_monitor_enrollment(
        self,
        enrollment: RecurringMonitorEnrollment,
    ) -> RecurringMonitorEnrollment:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_audit_recurring_monitor_enrollments (
                    enrollment_id, audit_order_id, offer_slug, parent_offer_slug, monitor_order_id,
                    price_key, status, cadence_days, monthly_amount_usd, currency, provider,
                    provider_subscription_id, checkout_session_id, source_payment_event_id,
                    latest_monitor_run_id, monitor_runs_completed, next_run_at, enrolled_at,
                    canceled_at, churned_at, refunded_at, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    enrollment.enrollment_id,
                    enrollment.audit_order_id,
                    enrollment.offer_slug,
                    enrollment.parent_offer_slug,
                    enrollment.monitor_order_id,
                    enrollment.price_key,
                    enrollment.status,
                    enrollment.cadence_days,
                    enrollment.monthly_amount_usd,
                    enrollment.currency,
                    enrollment.provider,
                    enrollment.provider_subscription_id,
                    enrollment.checkout_session_id,
                    enrollment.source_payment_event_id,
                    enrollment.latest_monitor_run_id,
                    enrollment.monitor_runs_completed,
                    enrollment.next_run_at,
                    enrollment.enrolled_at,
                    enrollment.canceled_at,
                    enrollment.churned_at,
                    enrollment.refunded_at,
                    json.dumps(enrollment.metadata, sort_keys=True),
                    enrollment.created_at,
                    enrollment.updated_at,
                ),
            )
        return self.get_recurring_monitor_enrollment(enrollment.enrollment_id) or enrollment

    def update_recurring_monitor_enrollment(
        self,
        enrollment_id: str,
        **fields: Any,
    ) -> RecurringMonitorEnrollment:
        existing = self.get_recurring_monitor_enrollment(enrollment_id)
        if existing is None:
            raise RuntimeError(f"Recurring monitor enrollment {enrollment_id} disappeared")
        updated = RecurringMonitorEnrollment(
            enrollment_id=existing.enrollment_id,
            audit_order_id=str(fields.get("audit_order_id", existing.audit_order_id)),
            offer_slug=str(fields.get("offer_slug", existing.offer_slug)),
            parent_offer_slug=str(fields.get("parent_offer_slug", existing.parent_offer_slug)),
            monitor_order_id=fields.get("monitor_order_id", existing.monitor_order_id),
            price_key=str(fields.get("price_key", existing.price_key)),
            status=str(fields.get("status", existing.status)),
            cadence_days=int(fields.get("cadence_days", existing.cadence_days)),
            monthly_amount_usd=float(fields.get("monthly_amount_usd", existing.monthly_amount_usd)),
            currency=str(fields.get("currency", existing.currency)),
            provider=str(fields.get("provider", existing.provider)),
            provider_subscription_id=str(
                fields.get("provider_subscription_id", existing.provider_subscription_id)
            ),
            checkout_session_id=str(fields.get("checkout_session_id", existing.checkout_session_id)),
            source_payment_event_id=str(
                fields.get("source_payment_event_id", existing.source_payment_event_id)
            ),
            latest_monitor_run_id=str(fields.get("latest_monitor_run_id", existing.latest_monitor_run_id)),
            monitor_runs_completed=int(fields.get("monitor_runs_completed", existing.monitor_runs_completed)),
            next_run_at=fields.get("next_run_at", existing.next_run_at),
            enrolled_at=fields.get("enrolled_at", existing.enrolled_at),
            canceled_at=fields.get("canceled_at", existing.canceled_at),
            churned_at=fields.get("churned_at", existing.churned_at),
            refunded_at=fields.get("refunded_at", existing.refunded_at),
            metadata=dict(fields.get("metadata", existing.metadata)),
            created_at=existing.created_at,
            updated_at=str(fields.get("updated_at", existing.updated_at)),
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE revenue_audit_recurring_monitor_enrollments
                SET audit_order_id = ?, offer_slug = ?, parent_offer_slug = ?, monitor_order_id = ?,
                    price_key = ?, status = ?, cadence_days = ?, monthly_amount_usd = ?, currency = ?,
                    provider = ?, provider_subscription_id = ?, checkout_session_id = ?,
                    source_payment_event_id = ?, latest_monitor_run_id = ?, monitor_runs_completed = ?,
                    next_run_at = ?, enrolled_at = ?, canceled_at = ?, churned_at = ?, refunded_at = ?,
                    metadata_json = ?, updated_at = ?
                WHERE enrollment_id = ?
                """,
                (
                    updated.audit_order_id,
                    updated.offer_slug,
                    updated.parent_offer_slug,
                    updated.monitor_order_id,
                    updated.price_key,
                    updated.status,
                    updated.cadence_days,
                    updated.monthly_amount_usd,
                    updated.currency,
                    updated.provider,
                    updated.provider_subscription_id,
                    updated.checkout_session_id,
                    updated.source_payment_event_id,
                    updated.latest_monitor_run_id,
                    updated.monitor_runs_completed,
                    updated.next_run_at,
                    updated.enrolled_at,
                    updated.canceled_at,
                    updated.churned_at,
                    updated.refunded_at,
                    json.dumps(updated.metadata, sort_keys=True),
                    updated.updated_at,
                    updated.enrollment_id,
                ),
            )
        return self.get_recurring_monitor_enrollment(enrollment_id) or updated

    def next_order_id(self) -> str:
        return _identifier("order")

    def next_checkout_session_id(self) -> str:
        return _identifier("checkout")

    def next_payment_event_id(self) -> str:
        return _identifier("payment")

    def next_fulfillment_job_id(self) -> str:
        return _identifier("fulfillment")

    def next_monitor_run_id(self) -> str:
        return _identifier("monitor")

    def next_recurring_monitor_enrollment_id(self) -> str:
        return _identifier("monitor_enrollment")
