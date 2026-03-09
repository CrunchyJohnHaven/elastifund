#!/usr/bin/env bash
# Strip runtime overrides from .env while preserving secrets and operator settings.

set -euo pipefail

PROFILE_NAME="${1:-live_aggressive}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
PROFILE_PATH="$PROJECT_DIR/config/runtime_profiles/$PROFILE_NAME.json"

if [ ! -f "$ENV_FILE" ]; then
    echo ".env not found at $ENV_FILE" >&2
    exit 1
fi

if [ ! -f "$PROFILE_PATH" ]; then
    echo "Runtime profile not found: $PROFILE_PATH" >&2
    exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="$PROJECT_DIR/.env.backup.$timestamp"
tmp_env="$(mktemp "$PROJECT_DIR/.env.clean.XXXXXX")"
trap 'rm -f "$tmp_env"' EXIT

cp "$ENV_FILE" "$backup_path"

trim_leading_space() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    printf '%s' "$value"
}

trim_trailing_space() {
    local value="$1"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

extract_env_key() {
    local line
    line="$(trim_leading_space "$1")"
    if [[ "$line" == export[[:space:]]* ]]; then
        line="$(trim_leading_space "${line#export}")"
    fi
    line="${line%%=*}"
    line="$(trim_trailing_space "$line")"
    printf '%s' "$line"
}

should_remove_key() {
    case "$1" in
        JJ_*|PAPER_TRADING|LIVE_TRADING|ENABLE_*|CLAUDE_MODEL|ELASTIFUND_AGENT_RUN_MODE)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

while IFS= read -r line || [ -n "$line" ]; do
    if [ -z "$line" ] || [[ "$line" =~ ^[[:space:]]*# ]]; then
        printf '%s\n' "$line" >>"$tmp_env"
        continue
    fi

    if [[ "$line" != *"="* ]]; then
        printf '%s\n' "$line" >>"$tmp_env"
        continue
    fi

    key="$(extract_env_key "$line")"
    if should_remove_key "$key"; then
        continue
    fi

    printf '%s\n' "$line" >>"$tmp_env"
done <"$ENV_FILE"

printf '\nJJ_RUNTIME_PROFILE=%s\n' "$PROFILE_NAME" >>"$tmp_env"
mv "$tmp_env" "$ENV_FILE"
trap - EXIT

echo "========================================"
echo "  Cleaned .env for runtime profile"
echo "========================================"
echo "  Backup:  $backup_path"
echo "  Profile: $PROFILE_NAME"
echo
cat "$ENV_FILE"
echo

(
    cd "$PROJECT_DIR"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    python3 - <<'PY'
from bot.runtime_profile import load_runtime_profile

bundle = load_runtime_profile()
profile = bundle.profile
print("Verification:")
print(f"  Profile: {bundle.selected_profile}")
print(f"  YES threshold: {profile.signal_thresholds.yes_threshold}")
print(f"  NO threshold: {profile.signal_thresholds.no_threshold}")
print(f"  Max position USD: {profile.risk_limits.max_position_usd}")
print(f"  Paper trading: {profile.mode.paper_trading}")
print(f"  Order submission: {profile.mode.allow_order_submission}")
print(f"  Execution mode: {profile.mode.execution_mode}")
print(f"  Crypto priority: {profile.market_filters.category_priorities.get('crypto', 'MISSING')}")
PY
)
