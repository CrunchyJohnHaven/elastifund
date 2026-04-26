#!/bin/bash
# BRIDGE.SH — Controlled sync between Mac and Dublin VPS
# Run this on your Mac. It handles:
#   1. Pull state/data FROM VPS TO Mac before any analysis or deploy
#   2. Run the local flywheel cycle from the pulled VPS DB
#   3. Push validated code FROM Mac TO VPS only after the pull step
#   4. Refresh remote/status artifacts with service and regression truth
#
# Usage:
#   ./scripts/bridge.sh                      # push + pull + local flywheel
#   ./scripts/bridge.sh --pull-only         # pull VPS data + local flywheel
#   ./scripts/bridge.sh --push-only         # mandatory pre-pull + push code
#   ./scripts/bridge.sh --skip-flywheel     # sync without local flywheel
#   ./scripts/bridge.sh --key ~/path.pem    # specify key
#   ./scripts/bridge.sh --loop              # continuous sync every 30 min
#
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: ./scripts/bridge.sh [--pull-only|--push-only|--skip-flywheel|--loop] [--key PATH]

Controlled sync between the Mac and the Dublin VPS.
  --pull-only       Pull VPS data and run the local flywheel.
  --push-only       Perform the mandatory pre-pull, then push code.
  --skip-flywheel   Skip the local flywheel step.
  --loop            Repeat the sync every 30 minutes.
  --key PATH        Use a specific SSH key.
EOF
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${ELASTIFUND_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
VPS_HOST="ubuntu@52.208.155.0"
VPS_DIR="/home/ubuntu/polymarket-trading-bot"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FYWHEEL_CONFIG="${FLYWHEEL_CONFIG:-$PROJECT_DIR/config/flywheel_runtime.local.json}"
FYWHEEL_LATEST="${FLYWHEEL_LATEST:-$PROJECT_DIR/reports/flywheel/latest_sync.json}"
REMOTE_SERVICE_STATUS="${REMOTE_SERVICE_STATUS:-$PROJECT_DIR/reports/remote_service_status.json}"
ROOT_TEST_STATUS="${ROOT_TEST_STATUS:-$PROJECT_DIR/reports/root_test_status.json}"
AUTO_PUSH_GITHUB="${ELASTIFUND_AUTO_PUSH_GITHUB:-false}"
AUTO_PUSH_MESSAGE_PREFIX="${ELASTIFUND_AUTO_PUSH_MESSAGE_PREFIX:-auto: remote cycle publish}"

# ── Find SSH key ──
KEY="${ELASTIFUND_BRIDGE_KEY:-}"
LOOP=false
PUSH_CODE=true
PULL_DATA=true
RUN_FLYWHEEL=true
PUSH_ONLY_REQUESTED=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --key) KEY="$2"; shift 2 ;;
        --loop) LOOP=true; shift ;;
        --pull-only) PUSH_CODE=false; shift ;;
        --push-only) PUSH_ONLY_REQUESTED=true; shift ;;
        --skip-flywheel) RUN_FLYWHEEL=false; shift ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

if $PUSH_ONLY_REQUESTED; then
    echo "[MODE] push-only requested; performing the mandatory pre-deploy pull first."
    PUSH_CODE=true
    PULL_DATA=true
    RUN_FLYWHEEL=false
fi

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

pull_remote_data() {
    local label="$1"
    echo "[PULL] $label"

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
}

capture_remote_service_status() {
    mkdir -p "$(dirname "$REMOTE_SERVICE_STATUS")"
    local service_name="jj-live.service"
    echo "[SERVICE] Capturing ${service_name} status..."

    local systemctl_state="unknown"
    local detail="unknown"

    if detail=$($SSH_CMD "$VPS_HOST" "systemctl is-active ${service_name} 2>/dev/null || true" 2>&1); then
        systemctl_state="$(printf '%s\n' "$detail" | tail -1 | tr -d '\r')"
        detail="$systemctl_state"
    else
        detail="$(printf '%s\n' "$detail" | tail -1 | tr -d '\r')"
        systemctl_state="unknown"
    fi

    "$PYTHON_BIN" - "$REMOTE_SERVICE_STATUS" "$VPS_HOST" "$service_name" "$systemctl_state" "$detail" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
host = sys.argv[2]
service_name = (sys.argv[3] or "jj-live.service").strip()
systemctl_state = (sys.argv[4] or "unknown").strip()
detail = (sys.argv[5] or "unknown").strip()

if systemctl_state == "active":
    status = "running"
elif systemctl_state in {"inactive", "failed", "deactivating"}:
    status = "stopped"
else:
    status = "unknown"

payload = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "host": host,
    "service_name": service_name,
    "status": status,
    "systemctl_state": systemctl_state,
    "detail": detail,
}
target.write_text(json.dumps(payload, indent=2, sort_keys=True))
print(json.dumps(payload, indent=2, sort_keys=True))
PY
}

write_status_report() {
    echo "[REPORT] Refreshing remote cycle status..."

    local report_output
    if ! report_output=$("$PYTHON_BIN" "$PROJECT_DIR/scripts/write_remote_cycle_status.py" \
        --refresh-root-tests \
        --root-test-status-json "$ROOT_TEST_STATUS" \
        --service-status-json "$REMOTE_SERVICE_STATUS" 2>&1); then
        printf '%s\n' "$report_output"
        return 1
    fi

    printf '%s\n' "$report_output"
}

auto_push_github() {
    case "${AUTO_PUSH_GITHUB}" in
        1|true|TRUE|yes|YES)
            ;;
        *)
            echo "[GIT] Skipped (ELASTIFUND_AUTO_PUSH_GITHUB disabled)."
            return 0
            ;;
    esac

    echo "[GIT] Publishing material cycle updates to GitHub..."
    local push_output
    if ! push_output=$("$PYTHON_BIN" "$PROJECT_DIR/scripts/self_push.py" \
        --repo-root "$PROJECT_DIR" \
        --message "${AUTO_PUSH_MESSAGE_PREFIX} $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>&1); then
        printf '%s\n' "$push_output"
        return 1
    fi

    printf '%s\n' "$push_output"
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

    # ── PULL: VPS → Mac (data, state, logs) ──
    if $PULL_DATA; then
        pull_remote_data "Pulling data from VPS before analysis or deploy..."
    else
        echo "[PULL] Skipped (push-only mode)."
    fi

    run_local_flywheel

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

    # ── Restart bot if code changed ──
    if $PUSH_CODE && $push_changed; then
        local service_name="jj-live.service"
        echo "[RESTART] Restarting ${service_name} (code changed)..."
        $SSH_CMD "$VPS_HOST" "sudo systemctl restart ${service_name} && sleep 3 && sudo systemctl is-active ${service_name}" 2>&1
    elif $PUSH_CODE; then
        echo "[RESTART] Skipped (no code changes pushed)."
    else
        echo "[RESTART] Skipped (pull-only mode)."
    fi

    if $PUSH_CODE && $PULL_DATA && $push_changed; then
        pull_remote_data "Refreshing validation data after deploy..."
    fi

    capture_remote_service_status
    write_status_report
    auto_push_github

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
