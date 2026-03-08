"""CLI entrypoint for the non-trading revenue agent."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import replace
from pathlib import Path

from nontrading.campaigns.engine import CampaignEngine
from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import NotConfiguredError, build_sender
from nontrading.importers.csv_import import import_csv
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore

logger = logging.getLogger("nontrading.main")


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def build_runtime(
    settings: RevenueAgentSettings,
    import_csv_path: str | None = None,
) -> tuple[RevenueStore, CampaignEngine]:
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
    store.ensure_default_campaign(settings)
    sender = build_sender(settings, store)
    risk_manager = RevenueRiskManager(store, settings)
    return store, CampaignEngine(store, risk_manager, sender, settings)


def format_status_line(snapshot: dict[str, object], summary: dict[str, int]) -> str:
    return (
        "revenue-agent status "
        f"campaigns={snapshot['campaigns']} "
        f"leads={snapshot['leads']} "
        f"deliverability={snapshot['deliverability_status']} "
        f"kill={snapshot['global_kill_switch']} "
        f"scanned={summary['scanned']} "
        f"queued={summary['queued']} "
        f"sent={summary['sent']} "
        f"filtered={summary['filtered']} "
        f"suppressed={summary['suppressed']} "
        f"deferred={summary['deferred']} "
        f"failed={summary['failed']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the non-trading revenue agent.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-once", action="store_true", help="Process one campaign cycle and exit.")
    mode.add_argument("--daemon", action="store_true", help="Run the campaign loop continuously.")
    parser.add_argument("--db-path", help="Override JJ_REVENUE_DB_PATH for this process.")
    parser.add_argument("--import-csv", help="Optional CSV file to import before running.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    settings = RevenueAgentSettings.from_env()
    if args.db_path:
        settings = replace(settings, db_path=Path(args.db_path))
    configure_logging(args.log_level)

    try:
        store, engine = build_runtime(settings, args.import_csv)
    except NotConfiguredError:
        logger.exception("email_provider_not_configured")
        return 2

    if args.run_once:
        summary = engine.run_once()
        snapshot = store.status_snapshot()
        print(format_status_line(snapshot, summary.__dict__))
        return 0

    while True:
        summary = engine.run_once()
        snapshot = store.status_snapshot()
        logger.info(format_status_line(snapshot, summary.__dict__))
        time.sleep(settings.loop_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

