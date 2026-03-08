#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_PATH="${1:-$REPO_DIR/config/flywheel_runtime.local.json}"
SCHEDULE="${FLYWHEEL_SCHEDULE:-0 * * * *}"
LOG_PATH="${FLYWHEEL_LOG_PATH:-$REPO_DIR/reports/flywheel/cron.log}"

mkdir -p "$(dirname "$LOG_PATH")"

CRON_CMD="$SCHEDULE cd $REPO_DIR && PYTHON_BIN=$PYTHON_BIN FLYWHEEL_CONFIG=$CONFIG_PATH $REPO_DIR/scripts/bridge.sh --pull-only >> $LOG_PATH 2>&1"

(
    crontab -l 2>/dev/null | grep -v "scripts/run_flywheel_cycle.py" | grep -v "scripts/bridge.sh --pull-only" || true
    echo "$CRON_CMD"
) | crontab -

echo "Installed flywheel cron:"
echo "  $CRON_CMD"
