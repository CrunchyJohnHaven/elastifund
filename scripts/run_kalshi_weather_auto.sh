#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

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

PYTHON_BIN="python3"
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [ -f "$ROOT_DIR/venv/bin/python3" ]; then
  PYTHON_BIN="$ROOT_DIR/venv/bin/python3"
elif [ -f "$ROOT_DIR/.venv_kalshi/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv_kalshi/bin/python"
fi

ENV_MODE="$(get_env_or_dotenv KALSHI_WEATHER_MODE 'paper')"
ENV_MAX_PAGES="$(get_env_or_dotenv KALSHI_WEATHER_MAX_PAGES '2')"
ENV_MAX_SIGNALS="$(get_env_or_dotenv KALSHI_WEATHER_MAX_SIGNALS '20')"
ENV_MAX_ORDERS="$(get_env_or_dotenv KALSHI_WEATHER_MAX_ORDERS '1')"
ENV_MAX_ORDER_USD="$(get_env_or_dotenv KALSHI_WEATHER_MAX_ORDER_USD '3')"
ENV_MAX_CONTRACT_NOTIONAL_USD="$(get_env_or_dotenv KALSHI_WEATHER_MAX_CONTRACT_NOTIONAL_USD "$ENV_MAX_ORDER_USD")"
ENV_BANKROLL_USD="$(get_env_or_dotenv KALSHI_WEATHER_BANKROLL_USD '81')"
ENV_KELLY_FRACTION="$(get_env_or_dotenv KALSHI_WEATHER_KELLY_FRACTION '0.25')"
ENV_EDGE_THRESHOLD="$(get_env_or_dotenv KALSHI_WEATHER_EDGE_THRESHOLD '0.12')"
ENV_MAX_SPREAD="$(get_env_or_dotenv KALSHI_WEATHER_MAX_SPREAD '0.12')"

exec "$PYTHON_BIN" -m kalshi.weather_arb \
  --mode "${ENV_MODE}" \
  --max-pages "${ENV_MAX_PAGES}" \
  --max-signals "${ENV_MAX_SIGNALS}" \
  --max-orders "${ENV_MAX_ORDERS}" \
  --max-order-usd "${ENV_MAX_ORDER_USD}" \
  --max-contract-notional-usd "${ENV_MAX_CONTRACT_NOTIONAL_USD}" \
  --bankroll-usd "${ENV_BANKROLL_USD}" \
  --kelly-fraction "${ENV_KELLY_FRACTION}" \
  --edge-threshold "${ENV_EDGE_THRESHOLD}" \
  --max-spread "${ENV_MAX_SPREAD}" \
  "$@"
