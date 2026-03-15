#!/usr/bin/env bash
# Check BTC 5-min maker service status on VPS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source <(grep -E '^(LIGHTSAIL_KEY|VPS_USER|VPS_IP)=' "$PROJECT_DIR/.env" || true)
    set +a
fi

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${1:-${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP in .env or environment}}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"
REMOTE_PYTHONPATH="$BOT_DIR:$BOT_DIR/bot:$BOT_DIR/polymarket-bot"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VPS" "
  echo '=== Service Status ==='
  sudo systemctl is-active btc-5min-maker.service 2>/dev/null || echo 'not installed'
  echo
  echo '=== Last 20 Log Lines ==='
  sudo journalctl -u btc-5min-maker.service -n 20 --no-pager 2>/dev/null || echo 'no logs'
  echo
  echo '=== SQLite Summary ==='
  cd $BOT_DIR
  export PYTHONPATH='$REMOTE_PYTHONPATH'
  if [ -x venv/bin/python3 ]; then
    PY_BIN='venv/bin/python3'
  elif [ -x .venv/bin/python3 ]; then
    PY_BIN='.venv/bin/python3'
  else
    PY_BIN='/usr/bin/python3'
  fi
  \"\$PY_BIN\" bot/btc_5min_maker.py --status 2>/dev/null || echo 'status unavailable'
"
