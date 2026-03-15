"""CRM and revenue-audit persistence methods for RevenueStore."""

from __future__ import annotations

import json
from typing import Any

from nontrading.models import (
    Account,
    ApprovalRequest,
    Contact,
    Meeting,
    Message,
    Opportunity,
    Outcome,
    Proposal,
    TelemetryEvent,
    normalize_country,
    normalize_domain,
    normalize_email,
    utc_now,
)
from nontrading.revenue_audit.models import (
    AuditBundle,
    CheckoutSession,
    FulfillmentJob,
    IssueEvidence,
    MonitorRun,
    PaymentEvent,
    ProspectProfile,
)
from nontrading.store_contracts import hours_between


class RevenueStoreCrmMixin:
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
            review_latency_hours = hours_between(updated.created_at, updated.reviewed_at)
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
