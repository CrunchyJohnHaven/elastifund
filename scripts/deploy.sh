#!/bin/bash
# JJ Bot Deploy Script — sync local code to Dublin VPS and restart service
#
# Usage:
#   ./scripts/deploy.sh                              # deploy to Dublin VPS (reads VPS_IP from .env)
#   ./scripts/deploy.sh ubuntu@your-vps-ip            # deploy to specific host
#
# Deploys the live JJ bot plus the runtime shims it imports on the VPS.
# Does NOT deploy: .env, jj_state.json, credentials, API keys
#
# Pre-requisites on VPS:
#   pip install anthropic openai duckduckgo-search httpx
#   .env must have: ANTHROPIC_API_KEY, XAI_API_KEY (and optionally OPENAI_API_KEY, GROQ_API_KEY)

set -euo pipefail

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${1:-${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP in .env}}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"
SERVICE_NAME="jj-live.service"
REMOTE_PYTHONPATH="$BOT_DIR:$BOT_DIR/bot:$BOT_DIR/polymarket-bot"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no"

echo "========================================"
echo "  JJ Bot Deploy → Dublin VPS"
echo "========================================"
echo "  Target: $VPS:$BOT_DIR"
echo ""

# Checked-in runtime profile contract (required for profile-based launches)
CONFIG_FILES=(
    "config/__init__.py"
    "config/runtime_profile.py"
    "config/runtime_profiles/blocked_safe.json"
    "config/runtime_profiles/paper_aggressive.json"
    "config/runtime_profiles/live_aggressive.json"
    "config/runtime_profiles/research_scan.json"
    "config/runtime_profiles/shadow_fast_flow.json"
)

# polymarket-bot shared modules (imported by bot/jj_live.py)
POLYBOT_FILES=(
    "polymarket-bot/src/__init__.py"
    "polymarket-bot/src/scanner.py"
    "polymarket-bot/src/claude_analyzer.py"
    "polymarket-bot/src/telegram.py"
)

# Sync bot/ files — create directory on VPS if needed
echo "  Creating bot/ directory on VPS..."
ssh $SSH_OPTS "$VPS" "mkdir -p $BOT_DIR/bot $BOT_DIR/config/runtime_profiles $BOT_DIR/src $BOT_DIR/data"

# Sync the full top-level bot package surface. The VPS deploy target is a
# file copy, not a git checkout, so jj_live imports must stay in lock-step.
for local_path in "$PROJECT_DIR"/bot/*.py; do
    relative_path="bot/$(basename "$local_path")"
    echo "  Syncing $relative_path..."
    scp $SSH_OPTS -q "$local_path" "$VPS:$BOT_DIR/$relative_path"
done

# Sync config/ runtime profile contract
for f in "${CONFIG_FILES[@]}"; do
    local_path="$PROJECT_DIR/$f"
    if [ -f "$local_path" ]; then
        echo "  Syncing $f..."
        scp $SSH_OPTS -q "$local_path" "$VPS:$BOT_DIR/$f"
    else
        echo "  WARN: $f not found locally, skipping"
    fi
done

# Sync polymarket-bot/ shared modules
ssh $SSH_OPTS "$VPS" "mkdir -p $BOT_DIR/polymarket-bot/src"
for f in "${POLYBOT_FILES[@]}"; do
    local_path="$PROJECT_DIR/$f"
    if [ -f "$local_path" ]; then
        echo "  Syncing $f..."
        scp $SSH_OPTS -q "$local_path" "$VPS:$BOT_DIR/$f"
    else
        echo "  WARN: $f not found locally, skipping"
    fi
done

# Clean up any stale root-level jj_live.py (systemd runs bot/jj_live.py, not root copy)
echo "  Removing stale root jj_live.py if present..."
ssh $SSH_OPTS "$VPS" "if [ -f $BOT_DIR/jj_live.py ]; then rm -f $BOT_DIR/jj_live.py && echo 'Removed stale root jj_live.py'; else echo 'No stale root jj_live.py'; fi"

# Install Python dependencies on VPS
echo ""
echo "  Installing Python dependencies on VPS..."
ssh $SSH_OPTS "$VPS" "cd $BOT_DIR && source venv/bin/activate && pip install -q anthropic openai duckduckgo-search httpx 2>&1 | tail -3"

# Verify imports on VPS using the same PYTHONPATH shape as systemd
echo ""
echo "  Verifying runtime imports and profile contract..."
ssh $SSH_OPTS "$VPS" "cd $BOT_DIR && source venv/bin/activate && export PYTHONPATH=\"$REMOTE_PYTHONPATH\" && test -f bot/polymarket_runtime.py && test -f bot/runtime_profile.py && test -f config/runtime_profile.py && test -f config/runtime_profiles/paper_aggressive.json && python3 -c \"from bot.polymarket_runtime import ClaudeAnalyzer; print('bot.polymarket_runtime OK')\" && set -a && source .env && set +a && python3 - <<'PY'
from bot.runtime_profile import load_runtime_profile

bundle = load_runtime_profile()
profile = bundle.profile
print(f\"Profile: {bundle.selected_profile}\")
print(f\"YES threshold: {profile.signal_thresholds.yes_threshold}\")
print(f\"NO threshold: {profile.signal_thresholds.no_threshold}\")
print(f\"Crypto priority: {profile.market_filters.category_priorities.get('crypto', 'MISSING')}\")
print(f\"Paper mode: {profile.mode.paper_trading}\")
print(f\"Order submission: {profile.mode.allow_order_submission}\")
print(f\"Execution mode: {profile.mode.execution_mode}\")
PY
timeout 120 python3 bot/jj_live.py --status >/tmp/jj-live-status.txt && tail -20 /tmp/jj-live-status.txt"

# Restart jj-live service if running
echo ""
echo "  Checking service status..."
if ssh $SSH_OPTS "$VPS" "systemctl is-active $SERVICE_NAME 2>/dev/null" | grep -q "active"; then
    echo "  Restarting $SERVICE_NAME..."
    ssh $SSH_OPTS "$VPS" "sudo systemctl restart $SERVICE_NAME"
    sleep 2
    ssh $SSH_OPTS "$VPS" "sudo systemctl status $SERVICE_NAME --no-pager -l | head -15"
    echo "  Service restarted."
else
    echo "  $SERVICE_NAME not running."
    echo "  Start with: ssh $SSH_OPTS $VPS 'sudo systemctl start $SERVICE_NAME'"
fi

echo ""
echo "========================================"
echo "  Deploy complete."
echo "========================================"
echo ""
echo "  Next steps:"
echo "    1. Verify .env has API keys: ssh $SSH_OPTS $VPS 'grep -c API_KEY $BOT_DIR/.env'"
echo "    2. Start service: ssh $SSH_OPTS $VPS 'sudo systemctl start $SERVICE_NAME'"
echo "    3. Watch logs: ssh $SSH_OPTS $VPS 'journalctl -u $SERVICE_NAME -f'"
