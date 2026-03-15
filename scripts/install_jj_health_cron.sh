#!/bin/bash
# Install a VPS cron job that monitors JJ heartbeat, restarts stale services,
# and sends the daily summary after 00:00 UTC.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/venv/bin/python3}"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "python3 not found"
    exit 1
fi

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

CRON_SCHEDULE="${JJ_HEALTH_CRON_SCHEDULE:-*/5 * * * *}"
HEARTBEAT_FILE="${JJ_HEARTBEAT_FILE:-$PROJECT_DIR/data/heartbeat.json}"
STATE_FILE="${JJ_HEALTH_MONITOR_STATE_FILE:-$PROJECT_DIR/data/health_monitor_state.json}"
DB_PATH="${JJ_DB_FILE:-$PROJECT_DIR/data/jj_trades.db}"
JJ_STATE_FILE="${JJ_STATE_FILE:-$PROJECT_DIR/jj_state.json}"
TIMEOUT_SECONDS="${JJ_HEARTBEAT_TIMEOUT_SECONDS:-600}"
RESTART_COOLDOWN_SECONDS="${JJ_HEALTH_RESTART_COOLDOWN_SECONDS:-900}"
SERVICE_NAME="${JJ_HEALTH_SERVICE_NAME:-jj-live.service}"
DAILY_HOUR_UTC="${JJ_DAILY_SUMMARY_HOUR_UTC:-0}"
DAILY_MINUTE_UTC="${JJ_DAILY_SUMMARY_MINUTE_UTC:-0}"
USE_SUDO_SYSTEMCTL="${JJ_HEALTH_USE_SUDO_SYSTEMCTL:-true}"

MONITOR_CMD=(
    "$PYTHON_BIN" -m bot.health_monitor
    --heartbeat-file "$HEARTBEAT_FILE"
    --state-file "$STATE_FILE"
    --db-path "$DB_PATH"
    --jj-state-file "$JJ_STATE_FILE"
    --timeout-seconds "$TIMEOUT_SECONDS"
    --service-name "$SERVICE_NAME"
    --restart-cooldown-seconds "$RESTART_COOLDOWN_SECONDS"
    --auto-restart
    --send-daily-summary
    --daily-summary-hour-utc "$DAILY_HOUR_UTC"
    --daily-summary-minute-utc "$DAILY_MINUTE_UTC"
)

if [ "$USE_SUDO_SYSTEMCTL" = "true" ]; then
    MONITOR_CMD+=(--sudo-systemctl)
fi

printf -v MONITOR_CMD_STR "%q " "${MONITOR_CMD[@]}"
CRON_LINE="$CRON_SCHEDULE cd $PROJECT_DIR && $MONITOR_CMD_STR>> $LOG_DIR/health_monitor.log 2>&1"

EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"
FILTERED_CRONTAB="$(printf '%s\n' "$EXISTING_CRONTAB" | grep -v 'bot.health_monitor' || true)"
NEW_CRONTAB="$FILTERED_CRONTAB"
if [ -n "$NEW_CRONTAB" ]; then
    NEW_CRONTAB="${NEW_CRONTAB}"$'\n'
fi
NEW_CRONTAB="${NEW_CRONTAB}${CRON_LINE}"

printf '%s\n' "$NEW_CRONTAB" | crontab -

echo "========================================"
echo "  JJ health monitor cron installed"
echo "========================================"
echo "  Schedule: $CRON_SCHEDULE"
echo "  Service:  $SERVICE_NAME"
echo "  Timeout:  ${TIMEOUT_SECONDS}s"
echo "  Cooldown: ${RESTART_COOLDOWN_SECONDS}s"
echo "  Log file: $LOG_DIR/health_monitor.log"
echo
echo "Installed command:"
echo "  $CRON_LINE"
echo
echo "View logs:"
echo "  tail -f $LOG_DIR/health_monitor.log"
