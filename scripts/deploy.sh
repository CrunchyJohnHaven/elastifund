#!/usr/bin/env bash
# JJ Bot Deploy Script — sync local code to the Dublin VPS.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./scripts/deploy.sh [user@host]
  ./scripts/deploy.sh --clean-env --profile live_aggressive --restart
  ./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart --btc5

Options:
  --clean-env         Strip runtime override vars from the VPS .env and set JJ_RUNTIME_PROFILE
  --profile NAME      Runtime profile to write during --clean-env (default: live_aggressive)
  --restart           Restart jj-live.service after syncing files
  --btc5              Install/restart btc-5min-maker.service on the VPS
  -h, --help          Show this help

Notes:
  - The VPS target defaults to $VPS_USER@$VPS_IP from .env or the shell environment.
  - The remote deploy target is a file copy, not a git checkout.
  - The remote .env is never uploaded from local; it is only edited in place with --clean-env.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # Load only deploy-relevant keys from .env.
    # shellcheck disable=SC1090
    source <(grep -E '^(LIGHTSAIL_KEY|VPS_USER|VPS_IP)=' "$PROJECT_DIR/.env" || true)
    set +a
fi

CLEAN_ENV=false
RESTART_SERVICE=false
ENABLE_BTC5=false
PROFILE_NAME="live_aggressive"
TARGET_VPS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --clean-env)
            CLEAN_ENV=true
            ;;
        --profile)
            shift
            if [ $# -eq 0 ]; then
                echo "--profile requires a value" >&2
                exit 1
            fi
            PROFILE_NAME="$1"
            ;;
        --restart)
            RESTART_SERVICE=true
            ;;
        --btc5)
            ENABLE_BTC5=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            if [ -n "$TARGET_VPS" ]; then
                echo "Unexpected extra target: $1" >&2
                usage >&2
                exit 1
            fi
            TARGET_VPS="$1"
            ;;
    esac
    shift
done

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${TARGET_VPS:-${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP in .env or environment}}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"
SERVICE_NAME="jj-live.service"
BTC5_SERVICE_NAME="btc-5min-maker.service"
REMOTE_PYTHONPATH="$BOT_DIR:$BOT_DIR/bot:$BOT_DIR/polymarket-bot"
SSH_CMD=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no)
SCP_CMD=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=no)

if [ ! -f "$SSH_KEY" ]; then
    echo "SSH key not found: $SSH_KEY" >&2
    exit 1
fi

echo "========================================"
echo "  JJ Bot Deploy → Dublin VPS"
echo "========================================"
echo "  Target:   $VPS:$BOT_DIR"
echo "  Profile:  $PROFILE_NAME"
echo "  Clean env: $CLEAN_ENV"
echo "  Restart:   $RESTART_SERVICE"
echo "  BTC5 service: $ENABLE_BTC5"
echo

POLYBOT_FILES=(
    "polymarket-bot/src/__init__.py"
    "polymarket-bot/src/scanner.py"
    "polymarket-bot/src/claude_analyzer.py"
    "polymarket-bot/src/telegram.py"
    "polymarket-bot/src/core/__init__.py"
    "polymarket-bot/src/core/time_utils.py"
)

SCRIPT_SUPPORT_FILES=(
    "scripts/clean_env_for_profile.sh"
    "scripts/btc5_status.sh"
)

DEPLOY_ASSET_FILES=(
    "deploy/jj-live.service"
    "deploy/btc-5min-maker.service"
)

sync_file() {
    local relative_path="$1"
    local local_path="$PROJECT_DIR/$relative_path"
    if [ ! -f "$local_path" ]; then
        echo "  WARN: $relative_path not found locally, skipping"
        return 0
    fi
    echo "  Syncing $relative_path..."
    "${SCP_CMD[@]}" -q "$local_path" "$VPS:$BOT_DIR/$relative_path"
}

echo "  Creating remote directories..."
"${SSH_CMD[@]}" "$VPS" "mkdir -p \
    $BOT_DIR/bot \
    $BOT_DIR/config/runtime_profiles \
    $BOT_DIR/data \
    $BOT_DIR/deploy \
    $BOT_DIR/polymarket-bot/src/core \
    $BOT_DIR/scripts"

for local_path in "$PROJECT_DIR"/bot/*.py; do
    relative_path="bot/$(basename "$local_path")"
    sync_file "$relative_path"
done

sync_file "config/__init__.py"
sync_file "config/runtime_profile.py"
for local_path in "$PROJECT_DIR"/config/runtime_profiles/*.json; do
    relative_path="config/runtime_profiles/$(basename "$local_path")"
    sync_file "$relative_path"
done

for relative_path in "${POLYBOT_FILES[@]}"; do
    sync_file "$relative_path"
done

for relative_path in "${SCRIPT_SUPPORT_FILES[@]}"; do
    sync_file "$relative_path"
done

for relative_path in "${DEPLOY_ASSET_FILES[@]}"; do
    sync_file "$relative_path"
done

if [ -f "$PROJECT_DIR/data/wallet_scores.db" ]; then
    sync_file "data/wallet_scores.db"
fi

if [ -f "$PROJECT_DIR/data/smart_wallets.json" ]; then
    sync_file "data/smart_wallets.json"
fi

if [ -f "$PROJECT_DIR/jj_state.json" ]; then
    echo "  NOTE: local jj_state.json exists but remote state is authoritative; not syncing"
fi

echo "  Removing stale root jj_live.py if present..."
"${SSH_CMD[@]}" "$VPS" "rm -f $BOT_DIR/jj_live.py && echo 'Ensured stale root jj_live.py is removed'"

echo
echo "  Installing Python dependencies on VPS..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && PY_BIN=\$( [ -x venv/bin/python3 ] && echo venv/bin/python3 || [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo /usr/bin/python3 ) && \$PY_BIN -m pip install -q anthropic openai duckduckgo-search httpx structlog --break-system-packages 2>&1 | tail -3"

if [[ "$CLEAN_ENV" == "true" ]]; then
    echo
    echo "  Cleaning remote .env for runtime profile..."
    "${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && chmod +x scripts/clean_env_for_profile.sh && ./scripts/clean_env_for_profile.sh '$PROFILE_NAME'"
fi

echo
echo "  Installing systemd units..."
"${SSH_CMD[@]}" "$VPS" "sudo install -m 644 $BOT_DIR/deploy/jj-live.service /etc/systemd/system/$SERVICE_NAME && sudo rm -f /etc/systemd/system/$SERVICE_NAME.d/override.conf && { sudo rmdir --ignore-fail-on-non-empty /etc/systemd/system/$SERVICE_NAME.d 2>/dev/null || true; } && sudo systemctl daemon-reload"

echo
echo "  Verifying runtime imports and profile contract..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && ( [ -f venv/bin/activate ] && source venv/bin/activate || [ -f .venv/bin/activate ] && source .venv/bin/activate || true ) && export PYTHONPATH=\"$REMOTE_PYTHONPATH\" && python3 - <<'PY'
import os
from dotenv import load_dotenv
from bot.polymarket_runtime import ClaudeAnalyzer, TelegramNotifier
from bot.runtime_profile import load_runtime_profile

load_dotenv('.env', override=True)
bundle = load_runtime_profile(profile_name=os.getenv('JJ_RUNTIME_PROFILE') or None)
profile = bundle.profile
print('bot.polymarket_runtime OK')
print(f'Profile: {bundle.selected_profile}')
print(f'YES threshold: {profile.signal_thresholds.yes_threshold}')
print(f'NO threshold: {profile.signal_thresholds.no_threshold}')
print(f'Paper: {profile.mode.paper_trading}')
print(f'Order submission: {profile.mode.allow_order_submission}')
print(f'Execution mode: {profile.mode.execution_mode}')
print(f'Crypto priority: {profile.market_filters.category_priorities.get(\"crypto\", \"MISSING\")}')
print(f'Telegram module: {\"available\" if TelegramNotifier is not None else \"missing\"}')
PY"

echo
echo "  Checking bot status surface..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && PY_BIN=\$( [ -x venv/bin/python3 ] && echo venv/bin/python3 || [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo /usr/bin/python3 ) && export PYTHONPATH=\"$REMOTE_PYTHONPATH\" && timeout 120 \$PY_BIN bot/jj_live.py --status >/tmp/jj-live-status.txt 2>&1 || true && tail -20 /tmp/jj-live-status.txt"

if [[ "$RESTART_SERVICE" == "true" ]]; then
    echo
    echo "  Restarting $SERVICE_NAME..."
    "${SSH_CMD[@]}" "$VPS" "sudo systemctl restart $SERVICE_NAME && sleep 2 && sudo systemctl is-active $SERVICE_NAME && sudo journalctl -u $SERVICE_NAME -n 20 --no-pager"
else
    echo
    echo "  Skipping service restart (--restart not set)."
fi

if [[ "$ENABLE_BTC5" == "true" ]]; then
    echo
    echo "  Installing/restarting $BTC5_SERVICE_NAME..."
    "${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && PY_BIN=\$( [ -x venv/bin/python3 ] && echo venv/bin/python3 || [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo /usr/bin/python3 ) && \$PY_BIN -m pip install -q aiohttp websockets python-dotenv --break-system-packages 2>&1 | tail -3"
    "${SSH_CMD[@]}" "$VPS" "sudo install -m 644 $BOT_DIR/deploy/$BTC5_SERVICE_NAME /etc/systemd/system/$BTC5_SERVICE_NAME && sudo systemctl daemon-reload && sudo systemctl enable $BTC5_SERVICE_NAME && sudo systemctl restart $BTC5_SERVICE_NAME && sleep 2 && sudo systemctl is-active $BTC5_SERVICE_NAME && sudo journalctl -u $BTC5_SERVICE_NAME -n 20 --no-pager"
else
    echo
    echo "  Skipping BTC 5-min service setup (--btc5 not set)."
fi

echo
echo "========================================"
echo "  Deploy complete."
echo "========================================"
echo
echo "Examples:"
echo "  ./scripts/deploy.sh --clean-env --profile live_aggressive --restart"
echo "  ./scripts/deploy.sh --clean-env --profile paper_aggressive --restart"
echo "  ./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart --btc5"
echo "  ./scripts/deploy.sh"
