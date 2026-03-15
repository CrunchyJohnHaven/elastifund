#!/bin/bash
# Deploy WebSocket infrastructure to Dublin VPS
#
# Usage:
#   ./scripts/deploy_ws.sh                     # deploy to Dublin VPS (reads VPS_IP from .env)
#   ./scripts/deploy_ws.sh ubuntu@your-vps-ip  # deploy to specific host
#
# Deploys: bot/ws_trade_stream.py, bot/vpin_toxicity.py, bot/clob_ws_client.py, infra/clob_ws.py
# Creates: jj-ws.service systemd unit (separate from jj-live.service)
# Does NOT deploy: .env, credentials, API keys
#
# Rollback: if the service fails within 30s of restart, restores the previous version

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./scripts/deploy_ws.sh [user@host]

Description:
  Deploy WebSocket-specific bot/infra files and manage the jj-ws service.
  Defaults target to $VPS_USER@$VPS_IP from .env or environment.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${1:-${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP in .env}}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no"
BACKUP_DIR="$BOT_DIR/.ws_backup"
SERVICE_NAME="jj-ws"

echo "========================================"
echo "  WebSocket Deploy → Dublin VPS"
echo "========================================"
echo "  Target: $VPS:$BOT_DIR"
echo ""

# Files to deploy
WS_FILES=(
    "bot/ws_trade_stream.py"
    "bot/vpin_toxicity.py"
    "bot/clob_ws_client.py"
    "infra/clob_ws.py"
)

# Create directories on VPS
echo "  Creating directories on VPS..."
ssh $SSH_OPTS "$VPS" "mkdir -p $BOT_DIR/bot $BOT_DIR/infra $BOT_DIR/data $BACKUP_DIR"

# Backup current versions for rollback
echo "  Backing up current files..."
for f in "${WS_FILES[@]}"; do
    ssh $SSH_OPTS "$VPS" "[ -f $BOT_DIR/$f ] && cp $BOT_DIR/$f $BACKUP_DIR/$(basename $f).bak || true"
done

# Sync files
for f in "${WS_FILES[@]}"; do
    local_path="$PROJECT_DIR/$f"
    if [ -f "$local_path" ]; then
        echo "  Syncing $f..."
        scp $SSH_OPTS -q "$local_path" "$VPS:$BOT_DIR/$f"
    else
        echo "  WARN: $f not found locally, skipping"
    fi
done

# Install/update dependencies
echo ""
echo "  Installing Python dependencies..."
ssh $SSH_OPTS "$VPS" "cd $BOT_DIR && source venv/bin/activate && pip install -q websockets httpx 2>&1 | tail -3"

# Verify imports on VPS
echo ""
echo "  Verifying imports..."
ssh $SSH_OPTS "$VPS" "cd $BOT_DIR && source venv/bin/activate && python3 -c '
from bot.ws_trade_stream import TradeStreamManager
from bot.vpin_toxicity import VPINManager
print(\"WebSocket imports OK\")
'"

# Create systemd service if it doesn't exist
echo ""
echo "  Configuring $SERVICE_NAME.service..."
ssh $SSH_OPTS "$VPS" "cat > /tmp/$SERVICE_NAME.service << 'UNIT'
[Unit]
Description=JJ WebSocket Trade Stream (VPIN + OFI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$BOT_DIR
EnvironmentFile=$BOT_DIR/.env
ExecStart=$BOT_DIR/venv/bin/python3 -m bot.ws_trade_stream
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5

[Install]
WantedBy=multi-user.target
UNIT
sudo mv /tmp/$SERVICE_NAME.service /etc/systemd/system/$SERVICE_NAME.service
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME"

# Restart service and verify health
echo ""
echo "  Restarting $SERVICE_NAME..."
ssh $SSH_OPTS "$VPS" "sudo systemctl restart $SERVICE_NAME"

echo "  Waiting 30s for health check..."
sleep 30

ACTIVE=$(ssh $SSH_OPTS "$VPS" "systemctl is-active $SERVICE_NAME 2>/dev/null || echo 'failed'")
if [ "$ACTIVE" = "active" ]; then
    echo "  Service healthy."
    ssh $SSH_OPTS "$VPS" "sudo systemctl status $SERVICE_NAME --no-pager -l | head -15"
else
    echo "  SERVICE FAILED — initiating rollback..."
    echo ""
    ssh $SSH_OPTS "$VPS" "journalctl -u $SERVICE_NAME --no-pager -n 30"
    echo ""

    # Restore backups
    for f in "${WS_FILES[@]}"; do
        bak="$BACKUP_DIR/$(basename $f).bak"
        ssh $SSH_OPTS "$VPS" "[ -f $bak ] && cp $bak $BOT_DIR/$f || true"
    done

    # Restart with old version
    ssh $SSH_OPTS "$VPS" "sudo systemctl restart $SERVICE_NAME || true"
    echo ""
    echo "  Rollback complete. Previous version restored."
    echo "  Check logs: ssh $SSH_OPTS $VPS 'journalctl -u $SERVICE_NAME -f'"
    exit 1
fi

echo ""
echo "========================================"
echo "  WebSocket deploy complete."
echo "========================================"
echo ""
echo "  Next steps:"
echo "    1. Watch logs: ssh $SSH_OPTS $VPS 'journalctl -u $SERVICE_NAME -f'"
echo "    2. Check latency DB: ssh $SSH_OPTS $VPS 'sqlite3 $BOT_DIR/data/ws_latency.db \"SELECT * FROM latency_snapshots ORDER BY timestamp DESC LIMIT 5\"'"
echo "    3. Status: ssh $SSH_OPTS $VPS 'sudo systemctl status $SERVICE_NAME'"
