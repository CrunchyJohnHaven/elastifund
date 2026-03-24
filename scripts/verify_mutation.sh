#!/usr/bin/env bash
# Run after autoresearch promotes a new parameter set.
# Waits N cycles, then checks whether fill rate improved.
set -euo pipefail

DB="/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db"
WAIT_MINUTES="${1:-30}"
MIN_FILL_PCT="${2:-20}"

echo "Waiting ${WAIT_MINUTES}m for post-mutation data..."
sleep $((WAIT_MINUTES * 60))

TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM window_trades WHERE created_at > datetime('now', '-${WAIT_MINUTES} minutes');")
SKIPS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM window_trades WHERE created_at > datetime('now', '-${WAIT_MINUTES} minutes') AND order_status LIKE 'skip_%';")

if [ "$TOTAL" -eq 0 ]; then
  echo "FAIL: Zero rows in last ${WAIT_MINUTES}m. Bot may not be running."
  exit 2
fi

FILL_PCT=$(echo "scale=1; 100 * ($TOTAL - $SKIPS) / $TOTAL" | bc)
echo "Post-mutation: ${TOTAL} cycles, ${SKIPS} skips, fill attempt rate: ${FILL_PCT}%"

SKIP_BREAKDOWN=$(sqlite3 "$DB" "SELECT order_status, COUNT(*) FROM window_trades WHERE created_at > datetime('now', '-${WAIT_MINUTES} minutes') GROUP BY order_status ORDER BY COUNT(*) DESC;")
echo "Skip breakdown:"
echo "$SKIP_BREAKDOWN"

PASS=$(echo "$FILL_PCT $MIN_FILL_PCT" | awk '{print ($1 >= $2) ? 1 : 0}')
if [ "$PASS" -eq 1 ]; then
  echo "PASS: Fill rate ${FILL_PCT}% >= ${MIN_FILL_PCT}% target"
  exit 0
else
  echo "FAIL: Fill rate ${FILL_PCT}% < ${MIN_FILL_PCT}% target"
  echo "Mutation may not have reached runtime. Check:"
  echo "  1. grep BTC5 /home/ubuntu/polymarket-trading-bot/.env"
  echo "  2. systemctl show btc-5min-maker.service -p Environment"
  echo "  3. journalctl -u btc-5min-maker.service -n 50 | grep -i config"
  exit 1
fi
