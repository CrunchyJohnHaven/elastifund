#!/usr/bin/env bash
# JJ Bot Deploy Script — sync local code to the Dublin VPS.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./scripts/deploy.sh [user@host]
  ./scripts/deploy.sh --clean-env --profile live_aggressive --restart
  ./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart --btc5 --btc5-autoresearch --kalshi --loop

Options:
  --clean-env         Strip runtime override vars from the VPS .env and set JJ_RUNTIME_PROFILE
  --profile NAME      Runtime profile to write during --clean-env (default: live_aggressive)
  --restart           Restart jj-live.service after syncing files
  --btc5              Install/restart btc-5min-maker.service on the VPS
  --btc5-autoresearch Install/enable the BTC5 dual-autoresearch timers
  --kalshi            Install/enable kalshi-weather-trader.timer (runs every 5m)
  --loop              Install/enable jj-improvement-loop.timer (runs every 30m)
  -h, --help          Show this help

Notes:
  - The VPS target defaults to $VPS_USER@$VPS_IP from .env or the shell environment.
  - The remote deploy target is a file copy, not a git checkout.
  - The remote .env is never uploaded from local; it is only edited in place with --clean-env.
  - BTC5 deploys also sync state/btc5_capital_stage.env when present and refresh reports/btc5_deploy_activation.json locally.
  - Runtime-affecting deploys refresh the checked-in status artifacts and repo-root public metrics locally after the remote step.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # Load only deploy-relevant keys from .env.
    # shellcheck disable=SC1090
    source <(grep -E '^(LIGHTSAIL_KEY|VPS_USER|VPS_IP)=' "$PROJECT_DIR/.env" || true)
    set +a
    # Some shells/sandboxes do not persist assignments from process substitution.
    if [ -z "${VPS_IP:-}" ] || [ -z "${VPS_USER:-}" ] || [ -z "${LIGHTSAIL_KEY:-}" ]; then
        while IFS='=' read -r key value; do
            case "$key" in
                LIGHTSAIL_KEY|VPS_USER|VPS_IP)
                    # Normalize optional surrounding quotes from .env values.
                    value="${value%\"}"
                    value="${value#\"}"
                    export "$key=$value"
                    ;;
            esac
        done < <(grep -E '^(LIGHTSAIL_KEY|VPS_USER|VPS_IP)=' "$PROJECT_DIR/.env" || true)
    fi
fi

CLEAN_ENV=false
RESTART_SERVICE=false
ENABLE_BTC5=false
ENABLE_BTC5_AUTORESEARCH=false
ENABLE_KALSHI=false
ENABLE_LOOP=false
BTC5_ACTIVATION_VERIFIED=false
PROFILE_NAME="live_aggressive"
TARGET_VPS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --clean-env)
            CLEAN_ENV=true
            ;;
        --profile)
            shift
            if [ $# -eq 0 ]; then
                echo "--profile requires a value" >&2
                exit 1
            fi
            PROFILE_NAME="$1"
            ;;
        --restart)
            RESTART_SERVICE=true
            ;;
        --btc5)
            ENABLE_BTC5=true
            ;;
        --btc5-autoresearch)
            ENABLE_BTC5_AUTORESEARCH=true
            ;;
        --kalshi)
            ENABLE_KALSHI=true
            ;;
        --loop)
            ENABLE_LOOP=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            if [ -n "$TARGET_VPS" ]; then
                echo "Unexpected extra target: $1" >&2
                usage >&2
                exit 1
            fi
            TARGET_VPS="$1"
            ;;
    esac
    shift
done

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${TARGET_VPS:-${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP in .env or environment}}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"
SERVICE_NAME="jj-live.service"
BTC5_SERVICE_NAME="btc-5min-maker.service"
PRIMARY_SERVICE_NAME="${PRIMARY_SERVICE_NAME:-$BTC5_SERVICE_NAME}"
BTC5_AUTORESEARCH_SERVICE_NAME="btc5-autoresearch.service"
BTC5_AUTORESEARCH_TIMER_NAME="btc5-autoresearch.timer"
BTC5_MARKET_AUTORESEARCH_SERVICE_NAME="btc5-market-model-autoresearch.service"
BTC5_MARKET_AUTORESEARCH_TIMER_NAME="btc5-market-model-autoresearch.timer"
BTC5_COMMAND_NODE_AUTORESEARCH_SERVICE_NAME="btc5-command-node-autoresearch.service"
BTC5_COMMAND_NODE_AUTORESEARCH_TIMER_NAME="btc5-command-node-autoresearch.timer"
BTC5_POLICY_AUTORESEARCH_SERVICE_NAME="btc5-policy-autoresearch.service"
BTC5_POLICY_AUTORESEARCH_TIMER_NAME="btc5-policy-autoresearch.timer"
BTC5_DUAL_MORNING_SERVICE_NAME="btc5-dual-autoresearch-morning.service"
BTC5_DUAL_MORNING_TIMER_NAME="btc5-dual-autoresearch-morning.timer"
KALSHI_SERVICE_NAME="kalshi-weather-trader.service"
KALSHI_TIMER_NAME="kalshi-weather-trader.timer"
LOOP_SERVICE_NAME="jj-improvement-loop.service"
LOOP_TIMER_NAME="jj-improvement-loop.timer"
REMOTE_PYTHONPATH="$BOT_DIR:$BOT_DIR/bot:$BOT_DIR/polymarket-bot"
SSH_CMD=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no)
SCP_CMD=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=no)

if [ ! -f "$SSH_KEY" ]; then
    echo "SSH key not found: $SSH_KEY" >&2
    exit 1
fi

echo "========================================"
echo "  JJ Bot Deploy → Dublin VPS"
echo "========================================"
echo "  Target:   $VPS:$BOT_DIR"
echo "  Profile:  $PROFILE_NAME"
echo "  Clean env: $CLEAN_ENV"
echo "  Restart:   $RESTART_SERVICE"
echo "  BTC5 service: $ENABLE_BTC5"
echo "  BTC5 autoresearch: $ENABLE_BTC5_AUTORESEARCH"
echo "  Kalshi timer: $ENABLE_KALSHI"
echo "  Loop timer:   $ENABLE_LOOP"
echo

POLYBOT_FILES=(
    "polymarket-bot/src/__init__.py"
    "polymarket-bot/src/scanner.py"
    "polymarket-bot/src/claude_analyzer.py"
    "polymarket-bot/src/telegram.py"
    "polymarket-bot/src/core/__init__.py"
    "polymarket-bot/src/core/time_utils.py"
)

SCRIPT_SUPPORT_FILES=(
    "scripts/clean_env_for_profile.sh"
    "scripts/btc5_status.sh"
    "scripts/run_btc5_service.sh"
    "scripts/btc5_monte_carlo.py"
    "scripts/btc5_regime_policy_lab.py"
    "scripts/run_btc5_autoresearch_cycle.py"
    "scripts/run_kalshi_weather_auto.sh"
    "scripts/run_flywheel_cycle.py"
    "scripts/write_remote_cycle_status.py"
)

BTC5_AUTORESEARCH_SUPPORT_FILES=(
    "btc5_market_model_candidate.py"
    "btc5_command_node.md"
    "benchmarks/__init__.py"
    "infra/__init__.py"
    "infra/fast_json.py"
    "scripts/btc5_dual_autoresearch_ops.py"
    "scripts/btc5_monte_carlo_core.py"
    "scripts/btc5_monte_carlo_markdown.py"
    "scripts/btc5_policy_benchmark.py"
    "scripts/btc5_portfolio_expectation.py"
    "scripts/btc5_runtime_helpers.py"
    "scripts/render_btc5_arr_progress.py"
    "scripts/render_btc5_command_node_progress.py"
    "scripts/render_btc5_market_model_progress.py"
    "scripts/render_btc5_usd_per_day_progress.py"
    "scripts/research_artifacts.py"
    "scripts/research_cli.py"
    "scripts/research_runtime.py"
    "scripts/run_btc5_command_node_autoresearch.py"
    "scripts/run_btc5_command_node_mutation_cycle.py"
    "scripts/run_btc5_market_model_autoresearch.py"
    "scripts/run_btc5_market_model_mutation_cycle.py"
    "scripts/run_btc5_policy_autoresearch.py"
)

BTC5_AUTORESEARCH_BENCHMARK_DIRS=(
    "benchmarks/btc5_market"
    "benchmarks/command_node_btc5"
)

DEPLOY_ASSET_FILES=(
    "deploy/jj-live.service"
    "deploy/btc-5min-maker.service"
    "deploy/btc5-autoresearch.service"
    "deploy/btc5-autoresearch.timer"
    "deploy/btc5-market-model-autoresearch.service"
    "deploy/btc5-market-model-autoresearch.timer"
    "deploy/btc5-command-node-autoresearch.service"
    "deploy/btc5-command-node-autoresearch.timer"
    "deploy/btc5-policy-autoresearch.service"
    "deploy/btc5-policy-autoresearch.timer"
    "deploy/btc5-dual-autoresearch-morning.service"
    "deploy/btc5-dual-autoresearch-morning.timer"
    "deploy/kalshi-weather-trader.service"
    "deploy/kalshi-weather-trader.timer"
    "deploy/jj-improvement-loop.service"
    "deploy/jj-improvement-loop.timer"
)

sync_file() {
    local relative_path="$1"
    local local_path="$PROJECT_DIR/$relative_path"
    local remote_parent=""
    if [ ! -f "$local_path" ]; then
        echo "  WARN: $relative_path not found locally, skipping"
        return 0
    fi
    remote_parent="$(dirname "$relative_path")"
    echo "  Syncing $relative_path..."
    "${SSH_CMD[@]}" "$VPS" "mkdir -p \"$BOT_DIR/$remote_parent\""
    "${SCP_CMD[@]}" -q "$local_path" "$VPS:$BOT_DIR/$relative_path"
}

capture_remote_service_status() {
    local target="$PROJECT_DIR/reports/remote_service_status.json"
    local service_name="${1:-$PRIMARY_SERVICE_NAME}"
    local systemctl_state="unknown"
    local detail="unknown"

    mkdir -p "$(dirname "$target")"
    if detail=$("${SSH_CMD[@]}" "$VPS" "systemctl is-active $service_name 2>/dev/null || true" 2>&1); then
        systemctl_state="$(printf '%s\n' "$detail" | tail -1 | tr -d '\r')"
        detail="$systemctl_state"
    else
        detail="$(printf '%s\n' "$detail" | tail -1 | tr -d '\r')"
        systemctl_state="unknown"
    fi

    python3 - "$target" "$VPS" "$service_name" "$systemctl_state" "$detail" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
host = sys.argv[2]
service_name = sys.argv[3]
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

capture_remote_btc5_activation_artifact() {
    local target="$PROJECT_DIR/reports/btc5_deploy_activation.json"
    local remote_payload=""

    mkdir -p "$(dirname "$target")"
    echo "  Capturing BTC5 deploy activation artifact..."

    if ! remote_payload=$("${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && export PYTHONPATH=\"$REMOTE_PYTHONPATH\" BTC5_SERVICE_NAME=\"$BTC5_SERVICE_NAME\" && python3 - <<'PY'
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path


TRACKED_OVERRIDE_KEYS = {
    'BTC5_CAPITAL_STAGE',
    'BTC5_BANKROLL_USD',
    'BTC5_RISK_FRACTION',
    'BTC5_MAX_TRADE_USD',
    'BTC5_MIN_TRADE_USD',
    'BTC5_DAILY_LOSS_LIMIT_USD',
    'BTC5_STAGE1_MAX_TRADE_USD',
    'BTC5_STAGE2_MAX_TRADE_USD',
    'BTC5_STAGE3_MAX_TRADE_USD',
}
REQUIRED_STAGE_OVERRIDE_KEYS = (
    'BTC5_CAPITAL_STAGE',
    'BTC5_BANKROLL_USD',
    'BTC5_RISK_FRACTION',
    'BTC5_MAX_TRADE_USD',
    'BTC5_MIN_TRADE_USD',
    'BTC5_DAILY_LOSS_LIMIT_USD',
)


def load_env_file(path: Path) -> dict[str, object]:
    detail = {
        \"exists\": path.exists(),
        \"loaded\": False,
        \"keys\": [],
        \"tracked_values\": {},
    }
    if not path.exists():
        return detail
    pattern = re.compile(r\"^[A-Za-z_][A-Za-z0-9_]*$\")
    keys: list[str] = []
    tracked_values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith(\"#\") or \"=\" not in line:
            continue
        key, value = line.split(\"=\", 1)
        key = key.strip()
        if not pattern.match(key):
            continue
        keys.append(key)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {\"'\", '\"'}:
            value = value[1:-1]
        os.environ[key] = value
        if key in TRACKED_OVERRIDE_KEYS:
            tracked_values[key] = value
    detail[\"loaded\"] = True
    detail[\"keys\"] = sorted(set(keys))
    detail[\"tracked_values\"] = tracked_values
    return detail


def iso_from_epoch(epoch_value: int | None) -> str | None:
    if epoch_value is None:
        return None
    return datetime.fromtimestamp(int(epoch_value), tz=timezone.utc).isoformat()


def _matches_float(actual: float, expected: object, *, tolerance: float = 1e-9) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


root = Path.cwd()
loaded_env_files: list[str] = []
env_file_details: dict[str, dict[str, object]] = {}
for relative_path in (
    \"config/btc5_strategy.env\",
    \"state/btc5_autoresearch.env\",
    \".env\",
    \"state/btc5_capital_stage.env\",
):
    detail = load_env_file(root / relative_path)
    env_file_details[relative_path] = detail
    if detail[\"loaded\"]:
        loaded_env_files.append(relative_path)

profile_selector_occurrences: list[dict[str, object]] = []
total_profile_selector_occurrences = 0
for relative_path, detail in env_file_details.items():
    key_count = sum(1 for key in (detail.get(\"keys\") or []) if key == \"JJ_RUNTIME_PROFILE\")
    if key_count <= 0:
        continue
    profile_selector_occurrences.append({\"path\": relative_path, \"count\": key_count})
    total_profile_selector_occurrences += key_count

from bot.btc_5min_maker import MakerConfig, TradeDB

cfg = MakerConfig()
db = TradeDB(cfg.db_path)
status = db.status_summary()
today_notional = float(status.get(\"today_notional_usd\") or 0.0)
bankroll = max(float(cfg.bankroll_usd), 1e-9)
capital_utilization = max(0.0, today_notional / bankroll)
service_name = os.environ.get(\"BTC5_SERVICE_NAME\", \"btc-5min-maker.service\")
active_capital_stage = int(cfg.capital_stage or 0)
deploy_mode = str(os.environ.get(\"BTC5_DEPLOY_MODE\") or \"\").strip() or (
    \"shadow_probe\" if cfg.paper_trading else \"live_stage1\"
)
paper_trading = bool(cfg.paper_trading)

service_raw = subprocess.run(
    [\"systemctl\", \"is-active\", service_name],
    check=False,
    capture_output=True,
    text=True,
)
state_lines = (service_raw.stdout or service_raw.stderr or \"unknown\").strip().splitlines()
systemctl_state = state_lines[-1].strip() if state_lines else \"unknown\"
if systemctl_state == \"active\":
    service_status = \"running\"
elif systemctl_state in {\"inactive\", \"failed\", \"deactivating\"}:
    service_status = \"stopped\"
else:
    service_status = \"unknown\"

def _systemctl_show_value(property_name: str) -> str | None:
    value = subprocess.run(
        [\"systemctl\", \"show\", \"-p\", property_name, \"--value\", service_name],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return value or None

service_definition = {
    \"fragment_path\": _systemctl_show_value(\"FragmentPath\"),
    \"load_state\": _systemctl_show_value(\"LoadState\") or \"unknown\",
    \"unit_file_state\": _systemctl_show_value(\"UnitFileState\") or \"unknown\",
    \"sub_state\": _systemctl_show_value(\"SubState\") or \"unknown\",
}

active_enter_text = subprocess.run(
    [\"systemctl\", \"show\", \"-p\", \"ActiveEnterTimestamp\", \"--value\", service_name],
    check=False,
    capture_output=True,
    text=True,
).stdout.strip()
active_enter_usec_raw = subprocess.run(
    [\"systemctl\", \"show\", \"-p\", \"ActiveEnterTimestampUSec\", \"--value\", service_name],
    check=False,
    capture_output=True,
    text=True,
).stdout.strip()
restart_epoch = int(active_enter_usec_raw) // 1_000_000 if active_enter_usec_raw.isdigit() else None

with sqlite3.connect(str(cfg.db_path), timeout=30) as conn:
    conn.row_factory = sqlite3.Row
    fills = conn.execute(
        \"\"\"
        SELECT
            COUNT(*) AS fills_since_restart_count,
            MIN(decision_ts) AS first_fill_decision_ts,
            MAX(decision_ts) AS latest_fill_decision_ts,
            MIN(updated_at) AS first_fill_updated_at,
            MAX(updated_at) AS latest_fill_updated_at
        FROM window_trades
        WHERE filled = 1
          AND LOWER(COALESCE(order_status, '')) LIKE 'live_%'
          AND (? IS NULL OR decision_ts >= ?)
        \"\"\",
        (restart_epoch, restart_epoch),
    ).fetchone()
    rows = conn.execute(
        \"\"\"
        SELECT COUNT(*) AS rows_seen_since_restart
        FROM window_trades
        WHERE (? IS NULL OR decision_ts >= ?)
        \"\"\",
        (restart_epoch, restart_epoch),
    ).fetchone()

first_fill_decision_ts = int(fills[\"first_fill_decision_ts\"]) if fills[\"first_fill_decision_ts\"] is not None else None
latest_fill_decision_ts = int(fills[\"latest_fill_decision_ts\"]) if fills[\"latest_fill_decision_ts\"] is not None else None
stage_override_detail = env_file_details.get(\"state/btc5_capital_stage.env\") or {
    \"exists\": False,
    \"loaded\": False,
    \"keys\": [],
    \"tracked_values\": {},
}
stage_override_keys = list(stage_override_detail.get(\"keys\") or [])
stage_override_values = dict(stage_override_detail.get(\"tracked_values\") or {})
missing_override_keys = [
    key for key in REQUIRED_STAGE_OVERRIDE_KEYS if key not in set(stage_override_keys)
]
override_env_loaded = bool(stage_override_detail.get(\"loaded\")) and bool(stage_override_values)

override_value_checks: dict[str, bool] = {}
if \"BTC5_CAPITAL_STAGE\" in stage_override_values:
    override_value_checks[\"BTC5_CAPITAL_STAGE\"] = active_capital_stage == int(stage_override_values[\"BTC5_CAPITAL_STAGE\"])
if \"BTC5_BANKROLL_USD\" in stage_override_values:
    override_value_checks[\"BTC5_BANKROLL_USD\"] = _matches_float(cfg.bankroll_usd, stage_override_values[\"BTC5_BANKROLL_USD\"])
if \"BTC5_RISK_FRACTION\" in stage_override_values:
    override_value_checks[\"BTC5_RISK_FRACTION\"] = _matches_float(cfg.risk_fraction, stage_override_values[\"BTC5_RISK_FRACTION\"])
if \"BTC5_MAX_TRADE_USD\" in stage_override_values:
    override_value_checks[\"BTC5_MAX_TRADE_USD\"] = _matches_float(cfg.max_trade_usd, stage_override_values[\"BTC5_MAX_TRADE_USD\"])
if \"BTC5_MIN_TRADE_USD\" in stage_override_values:
    override_value_checks[\"BTC5_MIN_TRADE_USD\"] = _matches_float(cfg.min_trade_usd, stage_override_values[\"BTC5_MIN_TRADE_USD\"])
if \"BTC5_DAILY_LOSS_LIMIT_USD\" in stage_override_values:
    override_value_checks[\"BTC5_DAILY_LOSS_LIMIT_USD\"] = _matches_float(cfg.daily_loss_limit_usd, stage_override_values[\"BTC5_DAILY_LOSS_LIMIT_USD\"])
if \"BTC5_STAGE1_MAX_TRADE_USD\" in stage_override_values:
    override_value_checks[\"BTC5_STAGE1_MAX_TRADE_USD\"] = _matches_float(cfg.stage1_max_trade_usd, stage_override_values[\"BTC5_STAGE1_MAX_TRADE_USD\"])
if \"BTC5_STAGE2_MAX_TRADE_USD\" in stage_override_values:
    override_value_checks[\"BTC5_STAGE2_MAX_TRADE_USD\"] = _matches_float(cfg.stage2_max_trade_usd, stage_override_values[\"BTC5_STAGE2_MAX_TRADE_USD\"])
if \"BTC5_STAGE3_MAX_TRADE_USD\" in stage_override_values:
    override_value_checks[\"BTC5_STAGE3_MAX_TRADE_USD\"] = _matches_float(cfg.stage3_max_trade_usd, stage_override_values[\"BTC5_STAGE3_MAX_TRADE_USD\"])

expected_effective_max_trade_usd = float(cfg.max_trade_usd)
if active_capital_stage == 1:
    expected_effective_max_trade_usd = float(cfg.stage1_max_trade_usd)
elif active_capital_stage == 2:
    expected_effective_max_trade_usd = float(cfg.stage2_max_trade_usd)
elif active_capital_stage == 3:
    expected_effective_max_trade_usd = float(cfg.stage3_max_trade_usd)

effective_stage_env_values_active = (
    override_env_loaded
    and not missing_override_keys
    and bool(override_value_checks)
    and all(override_value_checks.values())
    and _matches_float(cfg.effective_max_trade_usd, expected_effective_max_trade_usd)
    and _matches_float(cfg.effective_daily_loss_limit_usd, cfg.daily_loss_limit_usd)
)

session_policy_records = {
    \"count\": len(cfg.session_guardrail_overrides),
    \"names\": [override.session_name for override in cfg.session_guardrail_overrides],
    \"hours_covered_et\": sorted(
        {
            int(hour)
            for override in cfg.session_guardrail_overrides
            for hour in override.et_hours
        }
    ),
    \"path\": cfg.session_policy_path or None,
    \"inline_present\": bool(str(cfg.session_policy_json or \"\").strip()),
}
verification_checks = {
    \"service_active\": service_status == \"running\",
    \"service_unit_loaded\": service_definition[\"load_state\"] == \"loaded\",
    \"service_fragment_matches\": bool(service_definition[\"fragment_path\"]) and service_definition[\"fragment_path\"].endswith(service_name),
    \"override_env_loaded\": override_env_loaded,
    \"session_policy_records_present\": session_policy_records[\"count\"] > 0,
    \"effective_stage_env_values_active\": effective_stage_env_values_active,
    \"duplicate_profile_selector_absent\": total_profile_selector_occurrences <= 1,
    \"deploy_mode_matches_paper_setting\": (
        (deploy_mode in {\"shadow_probe\", \"shadow\", \"paper\", \"probe\"} and paper_trading)
        or (deploy_mode in {\"live_stage1\", \"live\", \"stage1_live\"} and not paper_trading)
    ),
    \"post_restart_fill_fields_present\": True,
}

payload = {
    \"checked_at\": datetime.now(timezone.utc).isoformat(),
    \"cwd\": str(root),
    \"db_path\": str(cfg.db_path),
    \"loaded_env_files\": loaded_env_files,
    \"env_file_details\": env_file_details,
    \"service_name\": service_name,
    \"service_status\": service_status,
    \"systemctl_state\": systemctl_state or \"unknown\",
    \"deploy_mode\": deploy_mode,
    \"paper_trading\": paper_trading,
    \"service_definition\": service_definition,
    \"service_active_enter_timestamp\": active_enter_text or None,
    \"service_active_enter_epoch\": restart_epoch,
    \"runtime_profile\": os.environ.get(\"JJ_RUNTIME_PROFILE\") or None,
    \"profile_selector_occurrences\": profile_selector_occurrences,
    \"duplicate_profile_selector_detected\": total_profile_selector_occurrences > 1,
    \"override_env\": {
        \"path\": \"state/btc5_capital_stage.env\",
        \"exists\": bool(stage_override_detail.get(\"exists\")),
        \"loaded\": bool(stage_override_detail.get(\"loaded\")),
        \"loaded_keys\": stage_override_keys,
        \"required_keys\": list(REQUIRED_STAGE_OVERRIDE_KEYS),
        \"missing_required_keys\": missing_override_keys,
        \"tracked_values\": stage_override_values,
        \"value_checks\": override_value_checks,
    },
    \"session_policy_records\": session_policy_records,
    \"stage_in_effect\": {
        \"capital_stage\": active_capital_stage,
        \"bankroll_usd\": round(float(cfg.bankroll_usd), 4),
        \"risk_fraction\": round(float(cfg.risk_fraction), 6),
        \"base_max_trade_usd\": round(float(cfg.max_trade_usd), 4),
        \"stage1_max_trade_usd\": round(float(cfg.stage1_max_trade_usd), 4),
        \"effective_max_trade_usd\": round(float(cfg.effective_max_trade_usd), 4),
        \"stage2_max_trade_usd\": round(float(cfg.stage2_max_trade_usd), 4),
        \"stage3_max_trade_usd\": round(float(cfg.stage3_max_trade_usd), 4),
        \"min_trade_usd\": round(float(cfg.min_trade_usd), 4),
        \"effective_daily_loss_limit_usd\": round(float(cfg.effective_daily_loss_limit_usd), 4),
        \"capital_utilization_ratio\": round(capital_utilization, 6),
    },
    \"status_summary\": {
        **status,
        \"capital_stage\": active_capital_stage,
        \"effective_max_trade_usd\": round(float(cfg.effective_max_trade_usd), 4),
        \"effective_daily_loss_limit_usd\": round(float(cfg.effective_daily_loss_limit_usd), 4),
        \"capital_utilization_ratio\": round(capital_utilization, 6),
    },
    \"post_restart_fill_activity\": {
        \"rows_seen_since_restart\": int(rows[\"rows_seen_since_restart\"] or 0),
        \"fills_since_restart_count\": int(fills[\"fills_since_restart_count\"] or 0),
        \"first_fill_decision_ts\": first_fill_decision_ts,
        \"first_fill_decision_at\": iso_from_epoch(first_fill_decision_ts),
        \"latest_fill_decision_ts\": latest_fill_decision_ts,
        \"latest_fill_decision_at\": iso_from_epoch(latest_fill_decision_ts),
        \"first_fill_updated_at\": fills[\"first_fill_updated_at\"],
        \"latest_fill_updated_at\": fills[\"latest_fill_updated_at\"],
    },
    \"verification_checks\": verification_checks,
}
print(json.dumps(payload, sort_keys=True))
PY" 2>&1); then
        echo "  ERROR: failed to capture BTC5 deploy activation artifact" >&2
        printf '%s\n' "$remote_payload" >&2
        return 1
    fi

    REMOTE_BTC5_DEPLOY_PAYLOAD="$remote_payload" python3 - "$target" <<'PY'
import json
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
payload = json.loads(os.environ["REMOTE_BTC5_DEPLOY_PAYLOAD"])
checks = payload.get("verification_checks") or {}
required_checks = (
    "service_active",
    "service_unit_loaded",
    "service_fragment_matches",
    "override_env_loaded",
    "session_policy_records_present",
    "effective_stage_env_values_active",
    "duplicate_profile_selector_absent",
    "deploy_mode_matches_paper_setting",
)
failed_required_checks = [name for name in required_checks if not checks.get(name)]
payload.setdefault("verification_checks", {})["failed_required_checks"] = failed_required_checks
payload["verification_checks"]["required_passed"] = not failed_required_checks
target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, indent=2, sort_keys=True))
if failed_required_checks:
    raise SystemExit(
        "BTC5 deploy activation checks failed: " + ", ".join(failed_required_checks)
    )
PY
}

refresh_runtime_artifacts() {
    echo
    echo "  Refreshing local runtime artifacts..."
    capture_remote_service_status
    if [[ "$ENABLE_BTC5" == "true" && "$BTC5_ACTIVATION_VERIFIED" != "true" ]]; then
        capture_remote_btc5_activation_artifact
    fi
    (
        cd "$PROJECT_DIR"
        python3 scripts/write_remote_cycle_status.py \
            --service-status-json reports/remote_service_status.json
        python3 scripts/render_public_metrics.py
    )
}

echo "  Creating remote directories..."
"${SSH_CMD[@]}" "$VPS" "mkdir -p \
    $BOT_DIR/bot \
    $BOT_DIR/config \
    $BOT_DIR/config/runtime_profiles \
    $BOT_DIR/data \
    $BOT_DIR/deploy \
    $BOT_DIR/kalshi \
    $BOT_DIR/polymarket-bot/src/core \
    $BOT_DIR/scripts \
    $BOT_DIR/state"

for local_path in "$PROJECT_DIR"/bot/*.py; do
    relative_path="bot/$(basename "$local_path")"
    sync_file "$relative_path"
done

for local_path in "$PROJECT_DIR"/kalshi/*.py; do
    [ -f "$local_path" ] || continue
    relative_path="kalshi/$(basename "$local_path")"
    sync_file "$relative_path"
done

sync_file "config/__init__.py"
sync_file "config/runtime_profile.py"
if [ -f "$PROJECT_DIR/config/btc5_strategy.env" ]; then
    sync_file "config/btc5_strategy.env"
fi
if [ -f "$PROJECT_DIR/config/flywheel_runtime.local.json" ]; then
    sync_file "config/flywheel_runtime.local.json"
fi
if [ -f "$PROJECT_DIR/state/btc5_autoresearch.env" ]; then
    sync_file "state/btc5_autoresearch.env"
fi
if [ -f "$PROJECT_DIR/state/btc5_capital_stage.env" ]; then
    sync_file "state/btc5_capital_stage.env"
fi
for local_path in "$PROJECT_DIR"/config/runtime_profiles/*.json; do
    relative_path="config/runtime_profiles/$(basename "$local_path")"
    sync_file "$relative_path"
done

for relative_path in "${POLYBOT_FILES[@]}"; do
    sync_file "$relative_path"
done

for relative_path in "${SCRIPT_SUPPORT_FILES[@]}"; do
    sync_file "$relative_path"
done

for relative_path in "${DEPLOY_ASSET_FILES[@]}"; do
    sync_file "$relative_path"
done

if [[ "$ENABLE_BTC5_AUTORESEARCH" == "true" ]]; then
    for relative_path in "${BTC5_AUTORESEARCH_SUPPORT_FILES[@]}"; do
        sync_file "$relative_path"
    done
    for benchmark_dir in "${BTC5_AUTORESEARCH_BENCHMARK_DIRS[@]}"; do
        if [ ! -d "$PROJECT_DIR/$benchmark_dir" ]; then
            continue
        fi
        while IFS= read -r local_path; do
            [ -n "$local_path" ] || continue
            relative_path="${local_path#$PROJECT_DIR/}"
            sync_file "$relative_path"
        done < <(find "$PROJECT_DIR/$benchmark_dir" -type f | sort)
    done
fi

if [ -f "$PROJECT_DIR/data/wallet_scores.db" ]; then
    sync_file "data/wallet_scores.db"
fi

if [ -f "$PROJECT_DIR/data/smart_wallets.json" ]; then
    sync_file "data/smart_wallets.json"
fi

if [ -f "$PROJECT_DIR/jj_state.json" ]; then
    echo "  NOTE: local jj_state.json exists but remote state is authoritative; not syncing"
fi

echo "  Removing stale root jj_live.py if present..."
"${SSH_CMD[@]}" "$VPS" "rm -f $BOT_DIR/jj_live.py && echo 'Ensured stale root jj_live.py is removed'"

echo
echo "  Installing Python dependencies on VPS..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && PY_BIN=\$( [ -x venv/bin/python3 ] && echo venv/bin/python3 || [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo /usr/bin/python3 ) && \$PY_BIN -m pip install -q anthropic openai duckduckgo-search httpx structlog --break-system-packages 2>&1 | tail -3"

if [[ "$CLEAN_ENV" == "true" ]]; then
    echo
    echo "  Cleaning remote .env for runtime profile..."
    "${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && chmod +x scripts/clean_env_for_profile.sh && ./scripts/clean_env_for_profile.sh '$PROFILE_NAME'"
fi

echo
echo "  Ensuring BTC5 service runner is executable..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && chmod +x scripts/run_btc5_service.sh scripts/clean_env_for_profile.sh"

echo
echo "  Installing systemd units..."
"${SSH_CMD[@]}" "$VPS" "sudo install -m 644 $BOT_DIR/deploy/jj-live.service /etc/systemd/system/$SERVICE_NAME && sudo rm -f /etc/systemd/system/$SERVICE_NAME.d/override.conf && { sudo rmdir --ignore-fail-on-non-empty /etc/systemd/system/$SERVICE_NAME.d 2>/dev/null || true; } && sudo systemctl daemon-reload"

echo
echo "  Verifying runtime imports and profile contract..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && ( [ -f venv/bin/activate ] && source venv/bin/activate || [ -f .venv/bin/activate ] && source .venv/bin/activate || true ) && export PYTHONPATH=\"$REMOTE_PYTHONPATH\" && python3 - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv
from bot.polymarket_runtime import ClaudeAnalyzer, TelegramNotifier
from bot.runtime_profile import load_runtime_profile

env_paths = [
    Path('.env'),
    Path('config/btc5_strategy.env'),
    Path('state/btc5_autoresearch.env'),
    Path('state/btc5_capital_stage.env'),
]
profile_occurrences = []
for path in env_paths:
    if not path.exists():
        continue
    count = 0
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key = line.split('=', 1)[0].strip()
        if key == 'JJ_RUNTIME_PROFILE':
            count += 1
    if count:
        profile_occurrences.append((path.as_posix(), count))
if sum(count for _, count in profile_occurrences) > 1:
    raise SystemExit(
        'Duplicate JJ_RUNTIME_PROFILE definitions detected across remote env files: '
        + ', '.join(f'{path} (count={count})' for path, count in profile_occurrences)
    )

load_dotenv('.env', override=True)
bundle = load_runtime_profile(profile_name=os.getenv('JJ_RUNTIME_PROFILE') or None)
profile = bundle.profile
print('bot.polymarket_runtime OK')
print(
    'JJ_RUNTIME_PROFILE occurrences: '
    + (', '.join(f'{path}={count}' for path, count in profile_occurrences) if profile_occurrences else 'none')
)
print(f'Profile: {bundle.selected_profile}')
print(f'YES threshold: {profile.signal_thresholds.yes_threshold}')
print(f'NO threshold: {profile.signal_thresholds.no_threshold}')
print(f'Paper: {profile.mode.paper_trading}')
print(f'Order submission: {profile.mode.allow_order_submission}')
print(f'Execution mode: {profile.mode.execution_mode}')
print(f'Crypto priority: {profile.market_filters.category_priorities.get(\"crypto\", \"MISSING\")}')
print(f'Telegram module: {\"available\" if TelegramNotifier is not None else \"missing\"}')
PY"

echo
echo "  Checking bot status surface..."
"${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && PY_BIN=\$( [ -x venv/bin/python3 ] && echo venv/bin/python3 || [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo /usr/bin/python3 ) && export PYTHONPATH=\"$REMOTE_PYTHONPATH\" && timeout 120 \$PY_BIN bot/jj_live.py --status >/tmp/jj-live-status.txt 2>&1 || true && tail -20 /tmp/jj-live-status.txt"

if [[ "$RESTART_SERVICE" == "true" ]]; then
    echo
    echo "  Restarting $SERVICE_NAME..."
    "${SSH_CMD[@]}" "$VPS" "sudo systemctl restart $SERVICE_NAME && sleep 2 && sudo systemctl is-active $SERVICE_NAME && sudo journalctl -u $SERVICE_NAME -n 20 --no-pager"
else
    echo
    echo "  Skipping service restart (--restart not set)."
fi

if [[ "$ENABLE_BTC5" == "true" ]]; then
    echo
    echo "  Installing/restarting $BTC5_SERVICE_NAME..."
    "${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && PY_BIN=\$( [ -x venv/bin/python3 ] && echo venv/bin/python3 || [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo /usr/bin/python3 ) && \$PY_BIN -m pip install -q aiohttp websockets python-dotenv --break-system-packages 2>&1 | tail -3"
    "${SSH_CMD[@]}" "$VPS" "sudo install -m 644 $BOT_DIR/deploy/$BTC5_SERVICE_NAME /etc/systemd/system/$BTC5_SERVICE_NAME && sudo systemctl daemon-reload && sudo systemctl enable $BTC5_SERVICE_NAME && sudo systemctl restart $BTC5_SERVICE_NAME && sleep 2 && echo 'BTC5 service state:' && sudo systemctl is-active $BTC5_SERVICE_NAME && echo 'BTC5 service definition:' && sudo systemctl show -p FragmentPath,LoadState,UnitFileState,SubState --value $BTC5_SERVICE_NAME && echo 'BTC5 active since:' && sudo systemctl show -p ActiveEnterTimestamp --value $BTC5_SERVICE_NAME && echo 'BTC5 recent logs:' && sudo journalctl -u $BTC5_SERVICE_NAME -n 20 --no-pager"
    capture_remote_btc5_activation_artifact
    BTC5_ACTIVATION_VERIFIED=true
else
    echo
    echo "  Skipping BTC 5-min service setup (--btc5 not set)."
fi

if [[ "$ENABLE_BTC5_AUTORESEARCH" == "true" ]]; then
    echo
    echo "  Installing/enabling BTC5 dual-autoresearch timers..."
    "${SSH_CMD[@]}" "$VPS" "sudo install -m 644 $BOT_DIR/deploy/$BTC5_MARKET_AUTORESEARCH_SERVICE_NAME /etc/systemd/system/$BTC5_MARKET_AUTORESEARCH_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_MARKET_AUTORESEARCH_TIMER_NAME /etc/systemd/system/$BTC5_MARKET_AUTORESEARCH_TIMER_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_COMMAND_NODE_AUTORESEARCH_SERVICE_NAME /etc/systemd/system/$BTC5_COMMAND_NODE_AUTORESEARCH_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_COMMAND_NODE_AUTORESEARCH_TIMER_NAME /etc/systemd/system/$BTC5_COMMAND_NODE_AUTORESEARCH_TIMER_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_POLICY_AUTORESEARCH_SERVICE_NAME /etc/systemd/system/$BTC5_POLICY_AUTORESEARCH_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_POLICY_AUTORESEARCH_TIMER_NAME /etc/systemd/system/$BTC5_POLICY_AUTORESEARCH_TIMER_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_AUTORESEARCH_SERVICE_NAME /etc/systemd/system/$BTC5_AUTORESEARCH_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_AUTORESEARCH_TIMER_NAME /etc/systemd/system/$BTC5_AUTORESEARCH_TIMER_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_DUAL_MORNING_SERVICE_NAME /etc/systemd/system/$BTC5_DUAL_MORNING_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$BTC5_DUAL_MORNING_TIMER_NAME /etc/systemd/system/$BTC5_DUAL_MORNING_TIMER_NAME && sudo systemctl daemon-reload && cd $BOT_DIR && /usr/bin/python3 scripts/btc5_dual_autoresearch_ops.py mark-burnin-start --reason deploy_btc5_autoresearch >/tmp/btc5-burnin-start.json && sudo systemctl enable $BTC5_MARKET_AUTORESEARCH_TIMER_NAME $BTC5_COMMAND_NODE_AUTORESEARCH_TIMER_NAME $BTC5_POLICY_AUTORESEARCH_TIMER_NAME $BTC5_AUTORESEARCH_TIMER_NAME $BTC5_DUAL_MORNING_TIMER_NAME && sudo systemctl restart $BTC5_MARKET_AUTORESEARCH_TIMER_NAME $BTC5_COMMAND_NODE_AUTORESEARCH_TIMER_NAME $BTC5_POLICY_AUTORESEARCH_TIMER_NAME $BTC5_AUTORESEARCH_TIMER_NAME $BTC5_DUAL_MORNING_TIMER_NAME && echo 'BTC5 dual-autoresearch timers active:' && sudo systemctl list-timers --all | egrep 'btc5-(market-model|command-node|policy|autoresearch|dual-autoresearch-morning)' && echo 'BTC5 burn-in marker:' && cat /tmp/btc5-burnin-start.json"
else
    echo
    echo "  Skipping BTC5 autoresearch timer (--btc5-autoresearch not set)."
fi

if [[ "$ENABLE_KALSHI" == "true" ]]; then
    echo
    echo "  Installing/enabling Kalshi weather trader timer..."
    "${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && mkdir -p kalshi && sudo install -m 644 $BOT_DIR/deploy/$KALSHI_SERVICE_NAME /etc/systemd/system/$KALSHI_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$KALSHI_TIMER_NAME /etc/systemd/system/$KALSHI_TIMER_NAME && sudo systemctl daemon-reload && sudo systemctl enable $KALSHI_TIMER_NAME && sudo systemctl start $KALSHI_TIMER_NAME && echo 'Kalshi timer active:' && sudo systemctl list-timers $KALSHI_TIMER_NAME --no-pager"
else
    echo
    echo "  Skipping Kalshi weather trader (--kalshi not set)."
fi

if [[ "$ENABLE_LOOP" == "true" ]]; then
    echo
    echo "  Installing/enabling improvement loop timer..."
    "${SSH_CMD[@]}" "$VPS" "sudo install -m 644 $BOT_DIR/deploy/$LOOP_SERVICE_NAME /etc/systemd/system/$LOOP_SERVICE_NAME && sudo install -m 644 $BOT_DIR/deploy/$LOOP_TIMER_NAME /etc/systemd/system/$LOOP_TIMER_NAME && sudo systemctl daemon-reload && sudo systemctl enable $LOOP_TIMER_NAME && sudo systemctl start $LOOP_TIMER_NAME && echo 'Improvement loop timer active:' && sudo systemctl list-timers $LOOP_TIMER_NAME --no-pager"
else
    echo
    echo "  Skipping improvement loop timer (--loop not set)."
fi

if [[ "$CLEAN_ENV" == "true" || "$RESTART_SERVICE" == "true" || "$ENABLE_BTC5" == "true" || "$ENABLE_BTC5_AUTORESEARCH" == "true" || "$ENABLE_KALSHI" == "true" || "$ENABLE_LOOP" == "true" ]]; then
    refresh_runtime_artifacts
else
    echo
    echo "  Skipping local runtime artifact refresh (no runtime-affecting flags set)."
fi

echo
echo "========================================"
echo "  Deploy complete."
echo "========================================"
echo
echo "Examples:"
echo "  ./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart --btc5 --btc5-autoresearch --kalshi --loop"
echo "  ./scripts/deploy.sh --clean-env --profile live_aggressive --restart"
echo "  ./scripts/deploy.sh --clean-env --profile paper_aggressive --restart"
echo "  ./scripts/deploy.sh"
