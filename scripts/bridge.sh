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

usage() {
    cat <<'EOF'
Usage:
  ./scripts/bridge.sh                      # push + pull + local flywheel
  ./scripts/bridge.sh --pull-only         # pull VPS data + local flywheel
  ./scripts/bridge.sh --push-only         # mandatory pre-pull + push code
  ./scripts/bridge.sh --skip-flywheel     # sync without local flywheel
  ./scripts/bridge.sh --key ~/path.pem    # specify key
  ./scripts/bridge.sh --loop              # continuous sync every 30 min
  ./scripts/bridge.sh --help
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${ELASTIFUND_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
VPS_HOST="ubuntu@34.244.34.108"
VPS_DIR="/home/ubuntu/polymarket-trading-bot"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FLYWHEEL_CONFIG="${FLYWHEEL_CONFIG:-$PROJECT_DIR/config/flywheel_runtime.local.json}"
FLYWHEEL_LATEST="${FLYWHEEL_LATEST:-$PROJECT_DIR/reports/flywheel/latest_sync.json}"
REMOTE_SERVICE_STATUS="${REMOTE_SERVICE_STATUS:-$PROJECT_DIR/reports/remote_service_status.json}"
PRIMARY_SERVICE_NAME="${PRIMARY_SERVICE_NAME:-btc-5min-maker.service}"
ROOT_TEST_STATUS="${ROOT_TEST_STATUS:-$PROJECT_DIR/reports/root_test_status.json}"
FRESHNESS_ARTIFACT="${FRESHNESS_ARTIFACT:-$PROJECT_DIR/reports/openclaw/freshness.json}"
FLYWHEEL_OPENCLAW_PATH="${FLYWHEEL_OPENCLAW_PATH:-$PROJECT_DIR/reports/openclaw/normalized/latest.json}"
FLYWHEEL_OPENCLAW_NORMALIZED_PATH="${FLYWHEEL_OPENCLAW_NORMALIZED_PATH:-$FLYWHEEL_OPENCLAW_PATH}"
FLYWHEEL_STALE_STATE="${FLYWHEEL_STALE_STATE:-$PROJECT_DIR/state/flywheel_stale_state.json}"
JJ_DATA_MAX_AGE_MINUTES="${JJ_DATA_MAX_AGE_MINUTES:-15}"
JJ_OPENCLAW_MAX_AGE_MINUTES="${JJ_OPENCLAW_MAX_AGE_MINUTES:-120}"
JJ_MAX_STALE_FAIL_OPEN="${JJ_MAX_STALE_FAIL_OPEN:-3}"
JJ_MIN_ARR_IMPROVEMENT_BPS="${JJ_MIN_ARR_IMPROVEMENT_BPS:-0}"
JJ_STRATEGY_IMPROVEMENT_INTERVAL_MINUTES="${JJ_STRATEGY_IMPROVEMENT_INTERVAL_MINUTES:-30}"
AUTO_PUSH_GITHUB="${ELASTIFUND_AUTO_PUSH_GITHUB:-false}"
AUTO_PUSH_MESSAGE_PREFIX="${ELASTIFUND_AUTO_PUSH_MESSAGE_PREFIX:-auto: remote cycle publish}"
FLYWHEEL_READ_ONLY=false
FLYWHEEL_BLOCK_REASONS=""
FLYWHEEL_OPENCLAW_AGE_MINUTES="${JJ_OPENCLAW_MAX_AGE_MINUTES}"
FLYWHEEL_MARKET_AGE_MINUTES="${JJ_DATA_MAX_AGE_MINUTES}"
FRESHNESS_REASONS_JSON="[]"
FRESHNESS_MARKET_AGE="null"
FRESHNESS_OPENCLAW_AGE="null"

# ── Find SSH key ──
KEY="${ELASTIFUND_BRIDGE_KEY:-}"
LOOP=false
PUSH_CODE=true
PULL_DATA=true
RUN_FLYWHEEL=true
PUSH_ONLY_REQUESTED=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help) usage; exit 0 ;;
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

artifact_age_minutes() {
    local path="$1"

    if [ ! -f "$path" ]; then
        echo ""
        return 1
    fi

    "$PYTHON_BIN" - "$path" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

path = sys.argv[1]
now = datetime.now(timezone.utc)
timestamp_candidates = []

try:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    payload = None

if isinstance(payload, dict):
    for key in ("checked_at", "generated_at", "timestamp", "finished_at", "created_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            timestamp_candidates.append(value.strip())

for candidate in timestamp_candidates:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            ts = datetime.strptime(candidate, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = max((now - ts).total_seconds() / 60.0, 0.0)
            print(f"{age:.4f}")
            raise SystemExit
        except ValueError:
            pass

try:
    mtime = os.path.getmtime(path)
    age = max((now.timestamp() - mtime) / 60.0, 0.0)
    print(f"{age:.4f}")
except Exception:
    raise SystemExit(1)
PY
}

_comma_join() {
    local joined=""
    local item

    for item in "$@"; do
        if [ -z "$item" ]; then
            continue
        fi
        if [ -z "$joined" ]; then
            joined="$item"
        else
            joined="${joined},${item}"
        fi
    done
    printf '%s\n' "$joined"
}

refresh_freshness_state() {
    local market_file="$1"
    local openclaw_file="$2"
    local checked_at="$3"

    local reasons_csv=""
    local market_age="null"
    local openclaw_age="null"

    if [ -n "$market_file" ] && [ -f "$market_file" ]; then
        local age
        if age="$(artifact_age_minutes "$market_file" 2>/dev/null)"; then
            market_age="$age"
            if awk "BEGIN { exit !($age > $FLYWHEEL_MARKET_AGE_MINUTES) }"; then
                reasons_csv="$(_comma_join "$reasons_csv" "market_data_stale")"
            fi
        else
            reasons_csv="$(_comma_join "$reasons_csv" "market_age_parse_failed")"
        fi
    else
        reasons_csv="$(_comma_join "$reasons_csv" "market_artifact_missing")"
    fi

    if [ -n "$openclaw_file" ] && [ -f "$openclaw_file" ]; then
        local openclaw_age_raw
        if openclaw_age_raw="$(artifact_age_minutes "$openclaw_file" 2>/dev/null)"; then
            openclaw_age="$openclaw_age_raw"
            if awk "BEGIN { exit !($openclaw_age_raw > $FLYWHEEL_OPENCLAW_AGE_MINUTES) }"; then
                reasons_csv="$(_comma_join "$reasons_csv" "openclaw_data_stale")"
            fi
        else
            reasons_csv="$(_comma_join "$reasons_csv" "openclaw_age_parse_failed")"
        fi
    else
        reasons_csv="$(_comma_join "$reasons_csv" "openclaw_artifact_missing")"
    fi

    FRESHNESS_REASONS_JSON=$("$PYTHON_BIN" - "$reasons_csv" <<'PY'
import json
import sys

raw = sys.argv[1]
items = [part.strip() for part in raw.split(",") if part.strip()]
print(json.dumps(items))
PY
)
    FRESHNESS_MARKET_AGE="$market_age"
    FRESHNESS_OPENCLAW_AGE="$openclaw_age"

    local stale_run_count
    stale_run_count="$(read_stale_state "$FLYWHEEL_STALE_STATE")"
    if [ -n "$reasons_csv" ]; then
        stale_run_count=$((stale_run_count + 1))
        FLYWHEEL_READ_ONLY=true
        if [ "$stale_run_count" -ge "$JJ_MAX_STALE_FAIL_OPEN" ]; then
            reasons_csv="$(_comma_join "$reasons_csv" "stale_fail_open_threshold_exceeded")"
            FRESHNESS_REASONS_JSON=$("$PYTHON_BIN" - "$reasons_csv" <<'PY'
import json
import sys

raw = sys.argv[1]
items = [part.strip() for part in raw.split(",") if part.strip()]
print(json.dumps(items))
PY
)
        fi
    else
        stale_run_count=0
        FLYWHEEL_READ_ONLY=false
    fi

    write_stale_state "$FLYWHEEL_STALE_STATE" "$stale_run_count" "$JJ_MAX_STALE_FAIL_OPEN"
    write_openclaw_freshness_manifest "$checked_at" "$market_file" "$openclaw_file" "$market_age" "$openclaw_age" "$checked_at" "$FRESHNESS_REASONS_JSON"
    FLYWHEEL_BLOCK_REASONS="$reasons_csv"

    if [ "$FLYWHEEL_READ_ONLY" = true ]; then
        echo "[FRESHNESS] stale inputs detected: ${FLYWHEEL_BLOCK_REASONS}"
    else
        echo "[FRESHNESS] all required inputs are within threshold."
    fi
}

freshest_market_file() {
    for path in "$PROJECT_DIR/data/jj_trades.db" "$PROJECT_DIR/jj_state.json" "$PROJECT_DIR/data/state.json" "$PROJECT_DIR/data/runtime.json"; do
        if [ -f "$path" ]; then
            echo "$path"
            return
        fi
    done

    local latest=""
    local latest_mtime=0
    local current
    for current in "$PROJECT_DIR/data"/*.json "$PROJECT_DIR/data"/*.db; do
        [ -f "$current" ] || continue
        local mtime
        mtime="$($PYTHON_BIN - <<'PY'
import os
import sys
print(int(os.path.getmtime(sys.argv[1])) )
PY
 "$current")"
        if [ -n "$mtime" ] && [ "$mtime" -gt "$latest_mtime" ]; then
            latest_mtime="$mtime"
            latest="$current"
        fi
    done
    if [ -n "$latest" ]; then
        echo "$latest"
    fi
}

read_stale_state() {
    local state_file="$1"
    if [ ! -f "$state_file" ]; then
        echo 0
        return
    fi
    "$PYTHON_BIN" - "$state_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    payload = json.loads(open(path, "r", encoding="utf-8").read())
    print(int(payload.get("stale_run_count", 0) or 0))
except Exception:
    print(0)
PY
}

write_stale_state() {
    local state_file="$1"
    local count="$2"
    local max_count="$3"
    mkdir -p "$(dirname "$state_file")"
    cat > "$state_file" <<EOF
{
  "stale_run_count": ${count},
  "max_stale_fail_open": ${max_count},
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}

write_openclaw_freshness_manifest() {
    local checked_at="$1"
    local market_file="$2"
    local openclaw_file="$3"
    local market_age="$4"
    local openclaw_age="$5"
    local run_id="$6"
    local stale_reasons_json="$7"

    mkdir -p "$(dirname "$FRESHNESS_ARTIFACT")"
    cat > "$FRESHNESS_ARTIFACT" <<EOF
{
  "timestamp": "${checked_at}",
  "age_minutes": {
    "market": ${market_age:-null},
    "openclaw": ${openclaw_age:-null}
  },
  "run_id": "${run_id}",
  "source": "bridge.sh",
  "market_artifact": "${market_file}",
  "openclaw_artifact": "${openclaw_file}",
  "reasons": ${stale_reasons_json}
}
EOF
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
        --include 'reports/openclaw/' \
        --include 'reports/openclaw/normalized/' \
        --include 'reports/openclaw/normalized/*' \
        --include 'reports/openclaw/freshness.json' \
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
    echo "[SERVICE] Capturing $PRIMARY_SERVICE_NAME status..."

    local systemctl_state="unknown"
    local detail="unknown"

    if detail=$($SSH_CMD "$VPS_HOST" "systemctl is-active $PRIMARY_SERVICE_NAME 2>/dev/null || true" 2>&1); then
        systemctl_state="$(printf '%s\n' "$detail" | tail -1 | tr -d '\r')"
        detail="$systemctl_state"
    else
        detail="$(printf '%s\n' "$detail" | tail -1 | tr -d '\r')"
        systemctl_state="unknown"
    fi

    "$PYTHON_BIN" - "$REMOTE_SERVICE_STATUS" "$VPS_HOST" "$PRIMARY_SERVICE_NAME" "$systemctl_state" "$detail" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
host = sys.argv[2]
service_name = (sys.argv[3] or "unknown").strip()
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
    if [ ! -f "$FLYWHEEL_CONFIG" ]; then
        echo "[FLYWHEEL] Skipped (missing config: $FLYWHEEL_CONFIG)"
        return 0
    fi

    mkdir -p "$(dirname "$FLYWHEEL_LATEST")"
    echo "[FLYWHEEL] Running local flywheel from pulled VPS data..."

    local flywheel_output
    if ! flywheel_output=$(
        JJ_FLYWHEEL_READ_ONLY="$FLYWHEEL_READ_ONLY" \
        JJ_BLOCK_REASONS="$FLYWHEEL_BLOCK_REASONS" \
        FLYWHEEL_OPENCLAW_NORMALIZED_PATH="$FLYWHEEL_OPENCLAW_NORMALIZED_PATH" \
        JJ_DATA_MAX_AGE_MINUTES="$JJ_DATA_MAX_AGE_MINUTES" \
        JJ_OPENCLAW_MAX_AGE_MINUTES="$JJ_OPENCLAW_MAX_AGE_MINUTES" \
        JJ_MIN_ARR_IMPROVEMENT_BPS="$JJ_MIN_ARR_IMPROVEMENT_BPS" \
        JJ_MAX_STALE_FAIL_OPEN="$JJ_MAX_STALE_FAIL_OPEN" \
        "$PYTHON_BIN" "$PROJECT_DIR/scripts/run_flywheel_cycle.py" --config "$FLYWHEEL_CONFIG" 2>&1
    ); then
        printf '%s\n' "$flywheel_output"
        return 1
    fi

    printf '%s\n' "$flywheel_output" > "$FLYWHEEL_LATEST"
    "$PYTHON_BIN" - "$FLYWHEEL_LATEST" <<'PY'
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
    local market_file=""
    local checked_at
    local openclaw_file="$FLYWHEEL_OPENCLAW_NORMALIZED_PATH"

    checked_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "$(date '+%Y-%m-%d %H:%M:%S') ── BRIDGE SYNC START ──"

    # ── PULL: VPS → Mac (data, state, logs) ──
    if $PULL_DATA; then
        pull_remote_data "Pulling data from VPS before analysis or deploy..."
        market_file="$(freshest_market_file || true)"
        refresh_freshness_state "$market_file" "$openclaw_file" "$checked_at"
        echo "[FRESHNESS] market_age=${FRESHNESS_MARKET_AGE} openclaw_age=${FRESHNESS_OPENCLAW_AGE}"
        echo "[FRESHNESS] reasons=${FLYWHEEL_BLOCK_REASONS:-none}"
    else
        echo "[PULL] Skipped (push-only mode)."
        FLYWHEEL_BLOCK_REASONS=""
        FRESHNESS_REASONS_JSON="[]"
        FLYWHEEL_READ_ONLY=false
        write_openclaw_freshness_manifest "$checked_at" "" "$openclaw_file" "null" "null" "$checked_at" "$FRESHNESS_REASONS_JSON"
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
        echo "[RESTART] Restarting jj-live service (code changed)..."
        $SSH_CMD "$VPS_HOST" "sudo systemctl restart jj-live.service && sleep 3 && sudo systemctl is-active jj-live.service" 2>&1
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
    LOOP_INTERVAL_SECONDS="$("$PYTHON_BIN" - <<'PY'
import os

try:
    minutes = float(os.getenv("JJ_STRATEGY_IMPROVEMENT_INTERVAL_MINUTES", "30"))
except ValueError:
    minutes = 30.0

print(int(minutes * 60))
PY
)"
    echo "Running continuous bridge sync (every ${JJ_STRATEGY_IMPROVEMENT_INTERVAL_MINUTES} min). Ctrl+C to stop."
    while true; do
        do_sync
        echo "Next sync in ${JJ_STRATEGY_IMPROVEMENT_INTERVAL_MINUTES} minutes..."
        sleep "$LOOP_INTERVAL_SECONDS"
    done
else
    do_sync
fi
