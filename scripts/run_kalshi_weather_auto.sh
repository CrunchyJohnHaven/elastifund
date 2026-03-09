#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

get_env_or_dotenv() {
  local key="$1"
  local fallback="${2:-}"
  local cur="${!key:-}"
  if [ -n "$cur" ]; then
    printf '%s' "$cur"
    return 0
  fi
  if [ -f "$ROOT_DIR/.env" ]; then
    local val
    val="$(awk -F= -v k="$key" '$1==k{print substr($0,index($0,"=")+1)}' "$ROOT_DIR/.env" | tail -1 | tr -d '"' | tr -d "'")"
    if [ -n "$val" ]; then
      printf '%s' "$val"
      return 0
    fi
  fi
  printf '%s' "$fallback"
}

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

ENV_KEY_ID="$(get_env_or_dotenv KALSHI_API_KEY_ID '')"
ENV_KEY_PATH="$(get_env_or_dotenv KALSHI_RSA_KEY_PATH 'bot/kalshi/kalshi_rsa_private.pem')"
ENV_MAX_PAGES="$(get_env_or_dotenv KALSHI_WEATHER_MAX_PAGES '2')"
ENV_MAX_SIGNALS="$(get_env_or_dotenv KALSHI_WEATHER_MAX_SIGNALS '20')"
ENV_MAX_ORDERS="$(get_env_or_dotenv KALSHI_WEATHER_MAX_ORDERS '1')"
ENV_MAX_ORDER_USD="$(get_env_or_dotenv KALSHI_WEATHER_MAX_ORDER_USD '3')"
ENV_BANKROLL_USD="$(get_env_or_dotenv KALSHI_WEATHER_BANKROLL_USD '81')"
ENV_KELLY_FRACTION="$(get_env_or_dotenv KALSHI_WEATHER_KELLY_FRACTION '0.25')"
ENV_EDGE_THRESHOLD="$(get_env_or_dotenv KALSHI_WEATHER_EDGE_THRESHOLD '0.12')"
ENV_MAX_SPREAD="$(get_env_or_dotenv KALSHI_WEATHER_MAX_SPREAD '0.12')"

EXECUTE_FLAG=""
if ! is_placeholder "$ENV_KEY_ID"; then
  if [ -f "$ENV_KEY_PATH" ] && "$PYTHON_BIN" -c "import kalshi_python" >/dev/null 2>&1; then
    EXECUTE_FLAG="--execute"
  fi
fi

exec "$PYTHON_BIN" kalshi/weather_arb.py \
  ${EXECUTE_FLAG} \
  --max-pages "${ENV_MAX_PAGES}" \
  --max-signals "${ENV_MAX_SIGNALS}" \
  --max-orders "${ENV_MAX_ORDERS}" \
  --max-order-usd "${ENV_MAX_ORDER_USD}" \
  --bankroll-usd "${ENV_BANKROLL_USD}" \
  --kelly-fraction "${ENV_KELLY_FRACTION}" \
  --edge-threshold "${ENV_EDGE_THRESHOLD}" \
  --max-spread "${ENV_MAX_SPREAD}"
