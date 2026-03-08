#!/bin/bash
# VPS_SETUP.SH — One-shot setup for Dublin VPS
# Paste this entire script into the VPS terminal.
# Configures: env fixes, bot service, auto-sync cron.
set -euo pipefail

BOT_DIR="/home/ubuntu/polymarket-trading-bot"
cd "$BOT_DIR"

echo "========================================="
echo "  JJ VPS Setup — Full Automation"
echo "========================================="

# ── 1. Fix .env: ensure PAPER_TRADING=false ──
echo "[1/6] Fixing .env..."
# Remove any existing PAPER_TRADING line and set to false
sed -i '/^PAPER_TRADING/d' .env
echo "PAPER_TRADING=false" >> .env

# Ensure A-6 shadow is on
grep -q "ENABLE_A6_SHADOW" .env || echo "ENABLE_A6_SHADOW=true" >> .env

# Set correct bankroll
sed -i '/^JJ_INITIAL_BANKROLL/d' .env
echo "JJ_INITIAL_BANKROLL=247.51" >> .env

# Set position size
sed -i '/^JJ_MAX_POSITION_USD/d' .env
echo "JJ_MAX_POSITION_USD=2.00" >> .env

# Set daily loss limit
sed -i '/^JJ_MAX_DAILY_LOSS_USD/d' .env
echo "JJ_MAX_DAILY_LOSS_USD=10" >> .env

echo "  .env updated: PAPER_TRADING=false, bankroll=247.51, max_pos=2.00"

# ── 2. Set PYTHONPATH ──
echo "[2/6] Setting PYTHONPATH..."
export PYTHONPATH="$BOT_DIR:$BOT_DIR/bot:$BOT_DIR/polymarket-bot"
grep -q "PYTHONPATH" ~/.bashrc 2>/dev/null || echo "export PYTHONPATH=\"$BOT_DIR:$BOT_DIR/bot:$BOT_DIR/polymarket-bot\"" >> ~/.bashrc

# ── 3. Verify keys ──
echo "[3/6] Verifying API keys..."
python3 -c "
from dotenv import load_dotenv; load_dotenv()
import os, sys
required = ['POLYMARKET_PK', 'POLY_BUILDER_API_KEY', 'ANTHROPIC_API_KEY']
missing = [k for k in required if not os.getenv(k)]
if missing:
    print(f'FATAL: Missing keys: {missing}')
    sys.exit(1)
for k in required + ['PAPER_TRADING', 'JJ_INITIAL_BANKROLL', 'JJ_MAX_POSITION_USD', 'ENABLE_A6_SHADOW']:
    v = os.getenv(k, '')
    print(f'  {k}: {v[:12]}')
"

# ── 4. Test single scan cycle ──
echo "[4/6] Testing single cycle..."
echo "(Scanning markets, filtering, estimating probabilities...)"
timeout 180 python3 bot/jj_live.py 2>&1 | tail -50 || echo "WARN: bot/jj_live.py failed, trying root jj_live.py..." && timeout 180 python3 jj_live.py 2>&1 | tail -50

# ── 5. Create systemd service ──
echo "[5/6] Creating systemd service..."
sudo tee /etc/systemd/system/jj-live.service > /dev/null << 'UNIT'
[Unit]
Description=JJ Live Trading Bot — Elastifund
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
Environment=PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot
ExecStart=/usr/bin/python3 bot/jj_live.py --continuous
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable jj-live.service
sudo systemctl restart jj-live.service
sleep 5
echo "Service status:"
sudo systemctl status jj-live.service --no-pager | head -15

# ── 6. Set up auto data push (every 2 hours) ──
echo "[6/6] Setting up data sync cron..."
mkdir -p logs

cat > /home/ubuntu/sync_data.sh << 'SYNC'
#!/bin/bash
cd /home/ubuntu/polymarket-trading-bot
mkdir -p logs
journalctl -u jj-live --since "2 hours ago" --no-pager > logs/jj_service.log 2>/dev/null
# Git commit data if repo exists
if [ -d .git ]; then
    git add data/ jj_state.json logs/ FAST_TRADE_EDGE_ANALYSIS.md 2>/dev/null
    git diff --cached --quiet || git commit -m "auto: VPS data sync $(date +%Y-%m-%d-%H%M)" 2>/dev/null
fi
SYNC
chmod +x /home/ubuntu/sync_data.sh

# Init git if needed
if [ ! -d .git ]; then
    git init
    git config user.email "jj@elastifund.ai"
    git config user.name "JJ-Dublin"
    cat > .gitignore << 'GI'
.env
.env.bak*
*.pem
venv/
__pycache__/
*.pyc
.DS_Store
GI
    git add -A
    git commit -m "VPS initial state"
fi

# Install cron
(crontab -l 2>/dev/null | grep -v sync_data; echo "0 */2 * * * /home/ubuntu/sync_data.sh >> /home/ubuntu/sync_data.log 2>&1") | crontab -

echo ""
echo "========================================="
echo "  SETUP COMPLETE"
echo "========================================="
echo "  Bot: $(sudo systemctl is-active jj-live.service)"
echo "  Paper mode: OFF (real trading)"
echo "  Max position: \$2.00"
echo "  Daily loss limit: \$10"
echo "  Bankroll: \$247.51"
echo "  A-6 shadow: ON"
echo "  Data sync: every 2 hours (cron)"
echo ""
echo "  Monitor: journalctl -u jj-live -f"
echo "========================================="
