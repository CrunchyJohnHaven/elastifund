#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SCHEDULE="${AUTO_STAGE_GATE_SCHEDULE:-30 * * * *}"
LOG_PATH="${AUTO_STAGE_GATE_LOG_PATH:-$REPO_DIR/logs/auto_stage_gate.log}"

mkdir -p "$(dirname "$LOG_PATH")"

CRON_LINE="$SCHEDULE cd $REPO_DIR && python3 bot/auto_stage_gate.py >> $LOG_PATH 2>&1"

(
    crontab -l 2>/dev/null | rg -v "bot/auto_stage_gate.py" || true
    echo "$CRON_LINE"
) | crontab -

echo "Installed auto stage gate cron:"
echo "  $CRON_LINE"
