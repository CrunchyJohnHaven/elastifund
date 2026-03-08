"""SQLite store for the non-trading revenue agent."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from nontrading.config import RevenueAgentSettings
from nontrading.models import (
    AgentState,
    Campaign,
    Lead,
    OutboxMessage,
    RiskEvent,
    SendEvent,
    normalize_country,
    normalize_email,
    utc_now,
)

logger = logging.getLogger("nontrading.store")

DEFAULT_TABLES = {
    "agent_state": "agent_state",
    "campaigns": "campaigns",
    "leads": "leads",
    "suppression_list": "suppression_list",
    "outbox_messages": "outbox_messages",
    "send_events": "send_events",
    "risk_events": "risk_events",
}

COMPAT_TABLES = {
    "agent_state": "nt_agent_state",
    "campaigns": "nt_campaigns",
    "leads": "nt_leads",
    "suppression_list": "nt_suppression_list",
    "outbox_messages": "nt_outbox_messages",
    "send_events": "nt_send_events",
    "risk_events": "nt_risk_events",
}

REQUIRED_DEFAULT_COLUMNS = {
    "agent_state": {"id", "global_kill_switch", "deliverability_status"},
    "campaigns": {"id", "subject_template", "body_template", "daily_send_quota"},
    "leads": {"id", "email_normalized", "explicit_opt_in"},
    "suppression_list": {"id", "email_normalized", "created_at"},
    "outbox_messages": {"id", "recipient_email_normalized", "body", "updated_at"},
    "send_events": {"id", "email_normalized", "metadata_json", "created_at"},
    "risk_events": {"id", "metadata_json", "created_at"},
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

    def status_snapshot(self) -> dict[str, Any]:
        t = self.tables
        state = self.get_agent_state()
        with self._connect() as conn:
            lead_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['leads']}").fetchone()["total"]
            campaign_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['campaigns']}").fetchone()["total"]
            outbox_count = conn.execute(f"SELECT COUNT(*) AS total FROM {t['outbox_messages']}").fetchone()["total"]
            suppression_count = conn.execute(
                f"SELECT COUNT(*) AS total FROM {t['suppression_list']}"
            ).fetchone()["total"]
        return {
            "db_path": str(self.db_path),
            "campaigns": int(campaign_count),
            "leads": int(lead_count),
            "outbox_messages": int(outbox_count),
            "suppression_entries": int(suppression_count),
            "global_kill_switch": state.global_kill_switch,
            "deliverability_status": state.deliverability_status,
            "table_namespace": "compat" if t != DEFAULT_TABLES else "default",
        }

