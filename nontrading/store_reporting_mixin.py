"""Reporting and daily-count methods for RevenueStore."""

from __future__ import annotations

import statistics
from typing import Any

from nontrading.models import utc_now
from nontrading.revenue_audit.models import FirstDollarReadiness
from nontrading.store_contracts import (
    ACTUAL_REVENUE_OUTCOME_STATUSES,
    DEFAULT_TABLES,
    PUBLIC_REPORT_SCHEMA,
    SUCCESSFUL_MESSAGE_STATUSES,
    SUCCESSFUL_OUTBOX_STATUSES,
    hours_between,
    parse_timestamp,
)


class RevenueStoreReportingMixin:
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
        time_to_first_dollar_hours = hours_between(first_research_at, observed_at)

        payments_collected_usd = round(sum(float(event.amount_total_usd) for event in payment_events), 2)
        first_paid_datetime = parse_timestamp(first_paid_at)
        last_paid_datetime = parse_timestamp(
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
        time_to_first_dollar_hours = hours_between(first_research_at, first_revenue_at)

        approval_latencies = [
            latency
            for request in approval_requests
            if request.status in {"approved", "rejected"}
            and (latency := hours_between(request.created_at, request.reviewed_at)) is not None
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
