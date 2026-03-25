#!/usr/bin/env bash
# Launch the BTC5 maker service in bounded live stage 1 or shadow/probe mode.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./scripts/run_btc5_service.sh

Description:
  Resolve BTC5 mode from env/stage overrides and launch bot/btc_5min_maker.py.

Environment:
  BTC5_DEPLOY_MODE      Explicit mode override (live|paper|shadow variants)
  BTC5_PAPER_TRADING    Bool fallback when BTC5_DEPLOY_MODE is unset
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STAGE_ENV_PATH="$PROJECT_DIR/state/btc5_capital_stage.env"

normalize_bool() {
    local raw_value="${1:-}"
    local normalized="${raw_value,,}"
    case "$normalized" in
        1|true|yes|on)
            echo "true"
            ;;
        0|false|no|off|"")
            echo "false"
            ;;
        *)
            echo "Unsupported BTC5_PAPER_TRADING value: $raw_value" >&2
            exit 2
            ;;
    esac
}

load_stage_override() {
    local path="$1"
    local line key value
    [ -f "$path" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [ -n "$line" ] || continue
        [[ "$line" == \#* ]] && continue
        [[ "$line" == *=* ]] || continue
        key="${line%%=*}"
        value="${line#*=}"
        key="${key%"${key##*[![:space:]]}"}"
        key="${key#"${key%%[![:space:]]*}"}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        case "$key" in
            BTC5_DEPLOY_MODE)
                deploy_mode="$value"
                ;;
            BTC5_PAPER_TRADING)
                raw_paper_trading="$value"
                ;;
        esac
    done < "$path"
}

deploy_mode="${BTC5_DEPLOY_MODE:-}"
# Default paper_trading to false when the live profile is active; the stage file
# or an explicit BTC5_PAPER_TRADING value can still override this below.
if [[ -z "${BTC5_PAPER_TRADING:-}" && "${JJ_RUNTIME_PROFILE:-}" == "maker_velocity_live" ]]; then
    raw_paper_trading="false"
else
    raw_paper_trading="${BTC5_PAPER_TRADING:-true}"
fi
load_stage_override "$STAGE_ENV_PATH"
paper_trading="$(normalize_bool "$raw_paper_trading")"
mode_flag="--live"

case "${deploy_mode:-}" in
    "" )
        if [[ "$paper_trading" == "true" ]]; then
            mode_flag="--paper"
        fi
        ;;
    live|live_stage1|stage1_live)
        mode_flag="--live"
        ;;
    paper|probe|shadow|shadow_probe)
        mode_flag="--paper"
        ;;
    *)
        echo "Unsupported BTC5_DEPLOY_MODE: $deploy_mode" >&2
        exit 2
        ;;
esac

echo "BTC5 runner resolved deploy_mode=${deploy_mode:-<empty>} paper_trading=$paper_trading mode_flag=$mode_flag stage_env=$STAGE_ENV_PATH" >&2
exec /usr/bin/python3 "$PROJECT_DIR/bot/btc_5min_maker.py" --continuous "$mode_flag"
