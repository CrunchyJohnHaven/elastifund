#!/usr/bin/env python3
"""Send or print the JJ daily summary."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.health_monitor import (  # noqa: E402
    DEFAULT_DB_PATH,
    DEFAULT_HEARTBEAT_FILE,
    DEFAULT_JJ_STATE_FILE,
    build_daily_summary_snapshot,
    build_telegram_sender,
    format_daily_summary,
)


def _default_target_date() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send or print the JJ daily summary")
    parser.add_argument(
        "--date",
        dest="target_date",
        default=None,
        help="UTC date to summarize in YYYY-MM-DD format (default: yesterday)",
    )
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--jj-state-file", default=str(DEFAULT_JJ_STATE_FILE))
    parser.add_argument("--heartbeat-file", default=str(DEFAULT_HEARTBEAT_FILE))
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="Print the summary without attempting Telegram delivery",
    )
    args = parser.parse_args()

    target_date = date.fromisoformat(args.target_date) if args.target_date else _default_target_date()
    snapshot = build_daily_summary_snapshot(
        target_date=target_date,
        db_path=Path(args.db_path),
        jj_state_path=Path(args.jj_state_file),
        heartbeat_path=Path(args.heartbeat_file),
    )
    summary = format_daily_summary(snapshot)
    print(summary)

    if args.stdout_only:
        return 0

    sender = build_telegram_sender()
    if sender is None:
        return 0
    return 0 if sender(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
