#!/bin/bash
# Install hourly stage-gate cron for multi-asset maker scaling.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  bash scripts/install_auto_stage_gate_cron.sh [--help]

Environment overrides:
  AUTO_STAGE_GATE_CRON_SCHEDULE   Cron schedule (default: 30 * * * *)
  AUTO_STAGE_GATE_STATE_ENV       Env file path (default: state/btc5_capital_stage.env)
  AUTO_STAGE_GATE_LOG_JSON        JSON event log path (default: data/stage_gate_log.json)
  AUTO_STAGE_GATE_LOOKBACK_HOURS  Numeric lookback window (default: 0 = all history)
  AUTO_STAGE_GATE_DB_PATHS        Comma-separated sqlite DB paths (default: six asset DBs)
  PYTHON_BIN                      Python interpreter (default: venv/bin/python3 or python3)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/venv/bin/python3}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "python3 not found" >&2
    exit 1
fi

CRON_SCHEDULE="${AUTO_STAGE_GATE_CRON_SCHEDULE:-30 * * * *}"
STATE_ENV="${AUTO_STAGE_GATE_STATE_ENV:-$PROJECT_DIR/state/btc5_capital_stage.env}"
STAGE_GATE_LOG_JSON="${AUTO_STAGE_GATE_LOG_JSON:-$PROJECT_DIR/data/stage_gate_log.json}"
LOOKBACK_HOURS="${AUTO_STAGE_GATE_LOOKBACK_HOURS:-0}"
DB_PATHS_RAW="${AUTO_STAGE_GATE_DB_PATHS:-$PROJECT_DIR/data/btc_5min_maker.db,$PROJECT_DIR/data/eth_5min_maker.db,$PROJECT_DIR/data/sol_5min_maker.db,$PROJECT_DIR/data/bnb_5min_maker.db,$PROJECT_DIR/data/doge_5min_maker.db,$PROJECT_DIR/data/xrp_5min_maker.db}"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

CMD=(
    "$PYTHON_BIN" -m bot.auto_stage_gate
    --state-env "$STATE_ENV"
    --log-path "$STAGE_GATE_LOG_JSON"
    --lookback-hours "$LOOKBACK_HOURS"
)

IFS=',' read -r -a DB_PATHS_ARRAY <<< "$DB_PATHS_RAW"
for db_path in "${DB_PATHS_ARRAY[@]}"; do
    trimmed="$(echo "$db_path" | xargs)"
    if [ -n "$trimmed" ]; then
        CMD+=(--db-path "$trimmed")
    fi
done

printf -v CMD_STR "%q " "${CMD[@]}"
CRON_LINE="$CRON_SCHEDULE cd $PROJECT_DIR && $CMD_STR>> $LOG_DIR/auto_stage_gate.log 2>&1"

EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"
FILTERED_CRONTAB="$(printf '%s\n' "$EXISTING_CRONTAB" | grep -v 'bot.auto_stage_gate' || true)"
NEW_CRONTAB="$FILTERED_CRONTAB"
if [ -n "$NEW_CRONTAB" ]; then
    NEW_CRONTAB="${NEW_CRONTAB}"$'\n'
fi
NEW_CRONTAB="${NEW_CRONTAB}${CRON_LINE}"

printf '%s\n' "$NEW_CRONTAB" | crontab -

echo "========================================"
echo "  Auto stage-gate cron installed"
echo "========================================"
echo "  Schedule: $CRON_SCHEDULE"
echo "  Log file: $LOG_DIR/auto_stage_gate.log"
echo
echo "Installed command:"
echo "  $CRON_LINE"
