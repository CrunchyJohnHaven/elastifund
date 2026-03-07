#!/bin/bash
# JJ Bot Deploy Script — sync local code to Dublin VPS and restart service
#
# Usage:
#   ./scripts/deploy.sh                              # deploy to Dublin VPS (reads VPS_IP from .env)
#   ./scripts/deploy.sh ubuntu@your-vps-ip            # deploy to specific host
#
# Deploys: bot/jj_live.py, bot/llm_ensemble.py, src/claude_analyzer.py
# Does NOT deploy: .env, jj_state.json, credentials, API keys
#
# Pre-requisites on VPS:
#   pip install anthropic openai duckduckgo-search httpx
#   .env must have: ANTHROPIC_API_KEY, XAI_API_KEY (and optionally OPENAI_API_KEY, GROQ_API_KEY)

set -euo pipefail

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${1:-${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP in .env}}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no"

echo "========================================"
echo "  JJ Bot Deploy → Dublin VPS"
echo "========================================"
echo "  Target: $VPS:$BOT_DIR"
echo ""

# Main bot files to sync
BOT_FILES=(
    "bot/jj_live.py"
    "bot/llm_ensemble.py"
)

# Legacy src/ files (still needed for fallback)
SRC_FILES=(
    "src/claude_analyzer.py"
)

# Sync bot/ files — create directory on VPS if needed
echo "  Creating bot/ directory on VPS..."
ssh $SSH_OPTS "$VPS" "mkdir -p $BOT_DIR/bot $BOT_DIR/src $BOT_DIR/data"

for f in "${BOT_FILES[@]}"; do
    local_path="$PROJECT_DIR/$f"
    if [ -f "$local_path" ]; then
        echo "  Syncing $f..."
        scp $SSH_OPTS -q "$local_path" "$VPS:$BOT_DIR/$f"
    else
        echo "  WARN: $f not found locally, skipping"
    fi
done

# Sync src/ files
for f in "${SRC_FILES[@]}"; do
    local_path="$PROJECT_DIR/$f"
    if [ -f "$local_path" ]; then
        echo "  Syncing $f..."
        scp $SSH_OPTS -q "$local_path" "$VPS:$BOT_DIR/$f"
    else
        echo "  WARN: $f not found locally, skipping"
    fi
done

# Also sync jj_live.py to root dir (VPS expects it there for systemd)
echo "  Syncing jj_live.py to root bot dir..."
scp $SSH_OPTS -q "$PROJECT_DIR/bot/jj_live.py" "$VPS:$BOT_DIR/jj_live.py"

# Install Python dependencies on VPS
echo ""
echo "  Installing Python dependencies on VPS..."
ssh $SSH_OPTS "$VPS" "cd $BOT_DIR && source venv/bin/activate && pip install -q anthropic openai duckduckgo-search httpx 2>&1 | tail -3"

# Verify syntax on VPS
echo ""
echo "  Verifying import..."
ssh $SSH_OPTS "$VPS" "cd $BOT_DIR && source venv/bin/activate && python3 -c 'import jj_live; print(\"Import OK\")'"

# Restart jj-live service if running
echo ""
echo "  Checking service status..."
if ssh $SSH_OPTS "$VPS" "systemctl is-active jj-live 2>/dev/null" | grep -q "active"; then
    echo "  Restarting jj-live service..."
    ssh $SSH_OPTS "$VPS" "sudo systemctl restart jj-live"
    sleep 2
    ssh $SSH_OPTS "$VPS" "sudo systemctl status jj-live --no-pager -l | head -15"
    echo "  Service restarted."
else
    echo "  jj-live service not running."
    echo "  Start with: ssh $SSH_OPTS $VPS 'sudo systemctl start jj-live'"
fi

echo ""
echo "========================================"
echo "  Deploy complete."
echo "========================================"
echo ""
echo "  Next steps:"
echo "    1. Verify .env has API keys: ssh $SSH_OPTS $VPS 'grep -c API_KEY $BOT_DIR/.env'"
echo "    2. Start service: ssh $SSH_OPTS $VPS 'sudo systemctl start jj-live'"
echo "    3. Watch logs: ssh $SSH_OPTS $VPS 'journalctl -u jj-live -f'"
