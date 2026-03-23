#!/usr/bin/env bash
# Pure bash + jq heartbeat checker for cron use.

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: ./scripts/health_check.sh

Pure bash + jq heartbeat checker for cron use.
EOF
    exit 0
fi

HEARTBEAT_FILE="${JJ_HEARTBEAT_FILE:-data/heartbeat.json}"
TIMEOUT_SECONDS="${JJ_HEARTBEAT_TIMEOUT_SECONDS:-600}"
NOW_EPOCH="${JJ_HEALTH_NOW_EPOCH:-$(date -u +%s)}"

if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required for scripts/health_check.sh" >&2
    exit 2
fi

timestamp_to_epoch() {
    local raw_value="$1"
    local normalized="${raw_value/Z/+00:00}"
    local bsd_value

    if date -u -d "$normalized" +%s >/dev/null 2>&1; then
        date -u -d "$normalized" +%s
        return 0
    fi

    if command -v gdate >/dev/null 2>&1; then
        gdate -u -d "$normalized" +%s
        return 0
    fi

    bsd_value="$(printf '%s' "$normalized" \
        | sed -E 's/\.[0-9]+([+-][0-9]{2}:[0-9]{2})$/\1/' \
        | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/')"
    if date -j -u -f "%Y-%m-%dT%H:%M:%S%z" "$bsd_value" +%s >/dev/null 2>&1; then
        date -j -u -f "%Y-%m-%dT%H:%M:%S%z" "$bsd_value" +%s
        return 0
    fi

    return 1
}

send_alert() {
    local message="$1"
    local token="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_TOKEN:-}}"
    local chat_id="${TELEGRAM_CHAT_ID:-}"

    if [ -n "$token" ] && [ -n "$chat_id" ] && command -v curl >/dev/null 2>&1; then
        curl -fsS -X POST "https://api.telegram.org/bot${token}/sendMessage" \
            --data-urlencode "chat_id=${chat_id}" \
            --data-urlencode "text=${message}" \
            >/dev/null || true
    fi

    printf '%s\n' "$message" >&2
}

if [ ! -f "$HEARTBEAT_FILE" ]; then
    send_alert "JJ HEALTH ALERT
Heartbeat file missing: $HEARTBEAT_FILE"
    exit 1
fi

REFERENCE_FIELD="$(jq -r 'if .last_cycle_completed_at then "last_cycle_completed_at" elif .last_updated_at then "last_updated_at" elif .started_at then "started_at" else "" end' "$HEARTBEAT_FILE")"
REFERENCE_VALUE="$(jq -r '.last_cycle_completed_at // .last_updated_at // .started_at // ""' "$HEARTBEAT_FILE")"

if [ -z "$REFERENCE_FIELD" ] || [ -z "$REFERENCE_VALUE" ]; then
    send_alert "JJ HEALTH ALERT
Heartbeat unreadable: $HEARTBEAT_FILE"
    exit 1
fi

if ! REFERENCE_EPOCH="$(timestamp_to_epoch "$REFERENCE_VALUE")"; then
    send_alert "JJ HEALTH ALERT
Could not parse heartbeat timestamp: $REFERENCE_VALUE"
    exit 1
fi

AGE_SECONDS=$(( NOW_EPOCH - REFERENCE_EPOCH ))
if [ "$AGE_SECONDS" -gt "$TIMEOUT_SECONDS" ]; then
    STATUS="$(jq -r '.status // "unknown"' "$HEARTBEAT_FILE")"
    CYCLE_NUMBER="$(jq -r '.cycle_number // 0' "$HEARTBEAT_FILE")"
    PROFILE_NAME="$(jq -r '.profile_name // "unknown"' "$HEARTBEAT_FILE")"
    RUNTIME_MODE="$(jq -r '.runtime_mode // "unknown"' "$HEARTBEAT_FILE")"
    LAST_ERROR="$(jq -r '.last_error // ""' "$HEARTBEAT_FILE")"

    MESSAGE="JJ HEALTH ALERT
Status: stale
Reason: heartbeat older than ${TIMEOUT_SECONDS}s
Age: ${AGE_SECONDS}s
Cycle: ${CYCLE_NUMBER}
Profile: ${PROFILE_NAME}
Mode: ${RUNTIME_MODE}
Reference: ${REFERENCE_FIELD}=${REFERENCE_VALUE}"
    if [ -n "$LAST_ERROR" ]; then
        MESSAGE="${MESSAGE}
Last error: ${LAST_ERROR}"
    fi
    send_alert "$MESSAGE"
    exit 1
fi

exit 0
