#!/bin/bash
# BRIDGE.SH — Bidirectional sync between Mac and Dublin VPS
# Run this on your Mac. It handles:
#   1. Push code FROM Mac TO VPS
#   2. Pull state/data FROM VPS TO Mac
#   3. Run the local flywheel cycle from the pulled VPS DB
#
# Usage:
#   ./scripts/bridge.sh                      # push + pull + local flywheel
#   ./scripts/bridge.sh --pull-only         # pull VPS data + local flywheel
#   ./scripts/bridge.sh --push-only         # push code only
#   ./scripts/bridge.sh --skip-flywheel     # sync without local flywheel
#   ./scripts/bridge.sh --key ~/path.pem    # specify key
#   ./scripts/bridge.sh --loop              # continuous sync every 30 min
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${ELASTIFUND_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
VPS_HOST="ubuntu@52.208.155.0"
VPS_DIR="/home/ubuntu/polymarket-trading-bot"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FYWHEEL_CONFIG="${FLYWHEEL_CONFIG:-$PROJECT_DIR/config/flywheel_runtime.local.json}"
FYWHEEL_LATEST="${FLYWHEEL_LATEST:-$PROJECT_DIR/reports/flywheel/latest_sync.json}"

# ── Find SSH key ──
KEY="${ELASTIFUND_BRIDGE_KEY:-}"
LOOP=false
PUSH_CODE=true
PULL_DATA=true
RUN_FLYWHEEL=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --key) KEY="$2"; shift 2 ;;
        --loop) LOOP=true; shift ;;
        --pull-only) PUSH_CODE=false; shift ;;
        --push-only) PULL_DATA=false; shift ;;
        --skip-flywheel) RUN_FLYWHEEL=false; shift ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

if [ -z "$KEY" ]; then
    # Search common locations
    for candidate in \
        "$PROJECT_DIR/LightsailDefaultKey-eu-west-1.pem" \
        "$HOME/Downloads/LightsailDefaultKey-eu-west-1.pem" \
        "$HOME/.ssh/lightsail.pem" \
        "$HOME/.ssh/LightsailDefaultKey-eu-west-1.pem" \
        "$HOME/Desktop/LightsailDefaultKey-eu-west-1.pem"; do
        if [ -f "$candidate" ]; then
            KEY="$candidate"
            break
        fi
    done
fi

if [ -z "$KEY" ] || [ ! -f "$KEY" ]; then
    echo "ERROR: SSH key not found. Use: $0 --key /path/to/key.pem"
    exit 1
fi

chmod 600 "$KEY"
SSH_CMD="ssh -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15"
RSYNC_SSH="ssh -i $KEY -o StrictHostKeyChecking=no"

print_tail() {
    local output="$1"
    if [ -n "$output" ]; then
        printf '%s\n' "$output" | tail -5
    fi
}

write_status_report() {
    echo "[REPORT] Refreshing remote cycle status..."

    local report_output
    if ! report_output=$("$PYTHON_BIN" "$PROJECT_DIR/scripts/write_remote_cycle_status.py" 2>&1); then
        printf '%s\n' "$report_output"
        return 1
    fi

    printf '%s\n' "$report_output"
}

run_local_flywheel() {
    if ! $RUN_FLYWHEEL; then
        echo "[FLYWHEEL] Skipped (--skip-flywheel)."
        return 0
    fi
    if ! $PULL_DATA; then
        echo "[FLYWHEEL] Skipped (push-only mode)."
        return 0
    fi
    if [ ! -f "$FYWHEEL_CONFIG" ]; then
        echo "[FLYWHEEL] Skipped (missing config: $FYWHEEL_CONFIG)"
        return 0
    fi

    mkdir -p "$(dirname "$FYWHEEL_LATEST")"
    echo "[FLYWHEEL] Running local flywheel from pulled VPS data..."

    local flywheel_output
    if ! flywheel_output=$("$PYTHON_BIN" "$PROJECT_DIR/scripts/run_flywheel_cycle.py" --config "$FYWHEEL_CONFIG" 2>&1); then
        printf '%s\n' "$flywheel_output"
        return 1
    fi

    printf '%s\n' "$flywheel_output" > "$FYWHEEL_LATEST"
    "$PYTHON_BIN" - "$FYWHEEL_LATEST" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
artifacts = data.get("artifacts", {})
print(f"  Cycle: {data.get('cycle_key', 'n/a')}")
print(f"  Evaluated: {data.get('evaluated', 0)}")
print(f"  Summary: {artifacts.get('summary_md', 'n/a')}")
print(f"  Scorecard: {artifacts.get('scorecard', 'n/a')}")
PY
}

do_sync() {
    local push_changed=false
    echo "$(date '+%Y-%m-%d %H:%M:%S') ── BRIDGE SYNC START ──"

    # ── PUSH: Mac → VPS (code, configs, improvements) ──
    if $PUSH_CODE; then
        echo "[PUSH] Syncing code to VPS..."
        local push_output
        if ! push_output=$(rsync -avz --delete --itemize-changes \
            --exclude '.env' \
            --exclude '.env.*' \
            --exclude '*.pem' \
            --exclude 'data/*.db' \
            --exclude 'data/*.db-*' \
            --exclude 'data/cache/' \
            --exclude 'data/snapshots/' \
            --exclude 'data/*.jsonl' \
            --exclude 'data/*.json' \
            --exclude '.git/' \
            --exclude '__pycache__/' \
            --exclude 'venv/' \
            --exclude '.DS_Store' \
            --exclude 'jj_state.json' \
            --exclude 'logs/' \
            -e "$RSYNC_SSH" \
            "$PROJECT_DIR/" "$VPS_HOST:$VPS_DIR/" 2>&1); then
            printf '%s\n' "$push_output"
            return 1
        fi
        print_tail "$push_output"
        if printf '%s\n' "$push_output" | grep -Eq '^[<>ch\*][^ ]* .+[^/]$'; then
            push_changed=true
        fi
    else
        echo "[PUSH] Skipped (pull-only mode)."
    fi

    # ── PULL: VPS → Mac (data, state, logs) ──
    if $PULL_DATA; then
        echo "[PULL] Pulling data from VPS..."
        local pull_output
        if ! pull_output=$(rsync -avz \
            --include 'data/' \
            --include 'data/*.db' \
            --include 'data/*.json' \
            --include 'data/*.jsonl' \
            --include 'jj_state.json' \
            --include 'logs/' \
            --include 'logs/*' \
            --include 'FAST_TRADE_EDGE_ANALYSIS.md' \
            --exclude '*' \
            -e "$RSYNC_SSH" \
            "$VPS_HOST:$VPS_DIR/" "$PROJECT_DIR/" 2>&1); then
            printf '%s\n' "$pull_output"
            return 1
        fi
        print_tail "$pull_output"
    else
        echo "[PULL] Skipped (push-only mode)."
    fi

    # ── Restart bot if code changed ──
    if $PUSH_CODE && $push_changed; then
        echo "[RESTART] Restarting jj-live service (code changed)..."
        $SSH_CMD "$VPS_HOST" "sudo systemctl restart jj-live.service && sleep 3 && sudo systemctl is-active jj-live.service" 2>&1
    elif $PUSH_CODE; then
        echo "[RESTART] Skipped (no code changes pushed)."
    else
        echo "[RESTART] Skipped (pull-only mode)."
    fi

    run_local_flywheel
    write_status_report

    # ── Quick status ──
    echo "[STATUS] Current bot state:"
    $SSH_CMD "$VPS_HOST" "cd $VPS_DIR && python3 - <<'PY'
import json
from pathlib import Path

path = Path('jj_state.json')
if not path.exists():
    print('  jj_state.json missing on VPS')
    raise SystemExit(0)

with path.open() as f:
    s = json.load(f)

print(f'  Bankroll: \${s[\"bankroll\"]:.2f}')
print(f'  Daily P&L: \${s[\"daily_pnl\"]:.2f}')
print(f'  Total P&L: \${s[\"total_pnl\"]:.2f}')
print(f'  Open positions: {len(s[\"open_positions\"])}')
print(f'  Total trades: {s[\"total_trades\"]}')
print(f'  Cycles: {s[\"cycles_completed\"]}')
PY" 2>&1

    echo "$(date '+%Y-%m-%d %H:%M:%S') ── BRIDGE SYNC DONE ──"
    echo ""
}

if $LOOP; then
    echo "Running continuous bridge sync (every 30 min). Ctrl+C to stop."
    while true; do
        do_sync
        echo "Next sync in 30 minutes..."
        sleep 1800
    done
else
    do_sync
fi
