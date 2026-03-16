#!/usr/bin/env python3
"""Compatibility wrapper for bot.health_monitor."""

from bot.health_monitor import (  # noqa: F401
    HeartbeatWriter,
    build_daily_summary_snapshot,
    build_morning_report,
    build_multi_asset_health_snapshot,
    check_cascade_active,
    check_fill_rate_trend,
    check_skip_spike,
    check_streak_active,
    evaluate_heartbeat,
    format_daily_summary,
    main,
    run_health_check,
)


if __name__ == "__main__":
    raise SystemExit(main())
