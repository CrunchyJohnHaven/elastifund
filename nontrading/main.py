"""CLI entrypoint for the non-trading revenue agent."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import replace
from pathlib import Path

from nontrading.approval import ApprovalGate
from nontrading.compliance import ComplianceGuard
from nontrading.config import RevenueAgentSettings, is_placeholder_domain, normalize_domain_for_checks
from nontrading.email.sender import DryRunSender, NotConfiguredError, build_sender
from nontrading.importers.csv_import import import_csv
from nontrading.pipeline import CycleReport, RevenuePipeline
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry

logger = logging.getLogger("nontrading.main")


class RuntimeSafetyError(RuntimeError):
    """Raised when runtime safety gates fail before the pipeline starts."""


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def build_runtime(
    settings: RevenueAgentSettings,
    import_csv_path: str | None = None,
    *,
    dry_run: bool = False,
) -> tuple[RevenueStore, RevenuePipeline]:
    settings.ensure_paths()
    store = RevenueStore(settings.db_path)
    if import_csv_path:
        import_summary = import_csv(import_csv_path, store)
        logger.info(
            "csv_import_complete inserted=%d updated=%d skipped=%d",
            import_summary.inserted,
            import_summary.updated,
            import_summary.skipped,
        )
    campaign = store.ensure_default_campaign(settings)
    sender = DryRunSender(settings, store) if dry_run else build_sender(settings, store)
    risk_manager = RevenueRiskManager(store, settings)
    approval_gate = ApprovalGate(store, paper_mode=sender.provider_name != "dry_run")
    verified_domain = normalize_domain_for_checks(settings.from_email)
    if sender.provider_name != "dry_run":
        if is_placeholder_domain(verified_domain):
            raise RuntimeSafetyError(
                "live_sender_blocked: from_email domain is placeholder or unverified; "
                "set JJ_REVENUE_FROM_EMAIL to a verified sender domain"
            )
        if not settings.sender_domain_verified:
            raise RuntimeSafetyError(
                "live_sender_blocked: sender domain is not verified; "
                "set JJ_REVENUE_SENDER_DOMAIN_VERIFIED=true after DNS/auth checks pass"
            )
        if settings.provider == "mailgun" and not settings.mailgun_domain:
            raise RuntimeSafetyError(
                "live_sender_blocked: MAILGUN_DOMAIN is required when JJ_REVENUE_PROVIDER=mailgun"
            )
    logger.info(
        "runtime_start mode=%s provider=%s approval_paper_mode=%s sender_domain=%s sender_domain_verified=%s",
        "dry_run" if sender.provider_name == "dry_run" else "live",
        sender.provider_name,
        approval_gate.paper_mode,
        verified_domain or "unset",
        settings.sender_domain_verified,
    )
    compliance_guard = ComplianceGuard(
        store,
        verified_domains={verified_domain},
        daily_message_limit=settings.daily_send_quota,
    )
    telemetry = NonTradingTelemetry(store, environment="paper" if sender.provider_name == "dry_run" else "live")
    return (
        store,
        RevenuePipeline(
            store,
            settings,
            risk_manager,
            approval_gate,
            compliance_guard,
            telemetry,
            sender,
            campaign=campaign,
            simulate_responses=sender.provider_name == "dry_run",
        ),
    )


def format_status_line(snapshot: dict[str, object], report: CycleReport) -> str:
    return (
        "revenue-pipeline status "
        f"leads={snapshot['leads']} "
        f"accounts={snapshot['accounts']} "
        f"opportunities={snapshot['crm_opportunities']} "
        f"telemetry={snapshot['telemetry_events']} "
        f"kill={snapshot['global_kill_switch']} "
        f"status={report.status} "
        f"scanned={report.scanned_leads} "
        f"suppressed={report.suppressed_leads} "
        f"existing={report.skipped_existing} "
        f"researched={report.accounts_researched} "
        f"qualified={report.qualified_accounts} "
        f"approved={report.outreach_approved} "
        f"outreach={report.outreach_sent} "
        f"blocked_outreach={report.outreach_blocked} "
        f"pending={report.approval_pending} "
        f"replies={report.replies_recorded} "
        f"meetings={report.meetings_booked} "
        f"proposals={report.proposals_sent} "
        f"fulfillment={report.fulfillment_planned} "
        f"outcomes={report.outcomes_recorded} "
        f"won={report.outcomes_won}"
    )


def run_daemon(
    store: RevenueStore,
    pipeline: RevenuePipeline,
    settings: RevenueAgentSettings,
    *,
    sleep_fn=time.sleep,
    max_cycles: int | None = None,
) -> None:
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        report = pipeline.run_cycle()
        snapshot = store.status_snapshot()
        logger.info(format_status_line(snapshot, report))
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return
        sleep_fn(settings.loop_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the non-trading revenue agent.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-once", action="store_true", help="Process one JJ-N pipeline cycle and exit.")
    mode.add_argument("--daemon", action="store_true", help="Run the JJ-N pipeline continuously.")
    parser.add_argument("--db-path", help="Override JJ_REVENUE_DB_PATH for this process.")
    parser.add_argument("--import-csv", help="Optional CSV file to import before running.")
    parser.add_argument("--dry-run", action="store_true", help="Force the dry-run sender and simulated downstream stages.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    settings = RevenueAgentSettings.from_env()
    if args.db_path:
        settings = replace(settings, db_path=Path(args.db_path))
    configure_logging(args.log_level)

    try:
        store, pipeline = build_runtime(settings, args.import_csv, dry_run=args.dry_run)
    except (NotConfiguredError, RuntimeSafetyError):
        logger.exception("runtime_start_blocked")
        return 2

    if args.run_once:
        summary = pipeline.run_cycle()
        snapshot = store.status_snapshot()
        print(format_status_line(snapshot, summary))
        return 0

    run_daemon(store, pipeline, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
