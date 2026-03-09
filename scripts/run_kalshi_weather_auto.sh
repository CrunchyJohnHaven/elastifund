#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

is_placeholder() {
  local v="${1:-}"
  local lc
  lc="$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]')"
  if [ -z "$lc" ]; then
    return 0
  fi
  case "$lc" in
    your*|*placeholder*|*example*)
      return 0
      ;;
  esac
  return 1
}

PYTHON_BIN="python3"
if [ -f "$ROOT_DIR/.venv_kalshi/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv_kalshi/bin/python"
fi

ENV_KEY_ID="${KALSHI_API_KEY_ID:-}"
ENV_KEY_PATH="${KALSHI_RSA_KEY_PATH:-}"
if [ -f "$ROOT_DIR/.env" ]; then
  if [ -z "$ENV_KEY_ID" ]; then
    ENV_KEY_ID="$(awk -F= '/^KALSHI_API_KEY_ID=/{print substr($0,index($0,"=")+1)}' "$ROOT_DIR/.env" | tail -1 | tr -d '"' | tr -d "'")"
  fi
  if [ -z "$ENV_KEY_PATH" ]; then
    ENV_KEY_PATH="$(awk -F= '/^KALSHI_RSA_KEY_PATH=/{print substr($0,index($0,"=")+1)}' "$ROOT_DIR/.env" | tail -1 | tr -d '"' | tr -d "'")"
  fi
fi

MODE="${1:-${KALSHI_WEATHER_MODE:-paper}}"
MODE="$(printf '%s' "$MODE" | tr '[:upper:]' '[:lower:]')"
if [ "$MODE" != "paper" ] && [ "$MODE" != "live" ]; then
  echo "Invalid mode '$MODE'. Use: paper or live." >&2
  exit 2
fi

if [ "$MODE" = "live" ]; then
  if is_placeholder "$ENV_KEY_ID"; then
    echo "KALSHI_API_KEY_ID missing/placeholder; refusing live mode." >&2
    exit 2
  fi
  KEY_PATH="${ENV_KEY_PATH:-bot/kalshi/kalshi_rsa_private.pem}"
  if [ ! -f "$KEY_PATH" ]; then
    echo "Kalshi RSA private key not found at '$KEY_PATH'; refusing live mode." >&2
    exit 2
  fi
  if ! "$PYTHON_BIN" -c "import kalshi_python" >/dev/null 2>&1; then
    echo "kalshi_python not installed; refusing live mode." >&2
    exit 2
  fi
fi

exec "$PYTHON_BIN" kalshi/weather_arb.py \
  --mode "$MODE" \
  ${KALSHI_WEATHER_LOOP:+--loop} \
  --interval-seconds "${KALSHI_WEATHER_LOOP_INTERVAL_SECONDS:-300}" \
  --max-pages "${KALSHI_WEATHER_MAX_PAGES:-2}" \
  --max-signals "${KALSHI_WEATHER_MAX_SIGNALS:-20}" \
  --max-orders "${KALSHI_WEATHER_MAX_ORDERS:-1}" \
  --max-orders-per-hour "${KALSHI_WEATHER_MAX_ORDERS_PER_HOUR:-1}" \
  --hourly-budget-usd "${KALSHI_WEATHER_HOURLY_BUDGET_USD:-${JJ_HOURLY_NOTIONAL_BUDGET_USD:-50}}" \
  --max-order-usd "${KALSHI_WEATHER_MAX_ORDER_USD:-50}" \
  --bankroll-usd "${KALSHI_WEATHER_BANKROLL_USD:-247}" \
  --kelly-fraction "${KALSHI_WEATHER_KELLY_FRACTION:-0.25}" \
  --edge-threshold "${KALSHI_WEATHER_EDGE_THRESHOLD:-0.12}" \
  --max-spread "${KALSHI_WEATHER_MAX_SPREAD:-0.12}"
