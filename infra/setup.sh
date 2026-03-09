#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.elastic.yml"
STATE_DIR="${REPO_ROOT}/state/elastifund/elastic"
ENV_FILE="${STATE_DIR}/elastic-stack.env"
FILEBEAT_DATA_DIR="${STATE_DIR}/filebeat-data"
LOG_DIR="${REPO_ROOT}/logs/elastifund"

log() {
  printf '[elastic-setup] %s\n' "$*"
}

fail() {
  printf '[elastic-setup] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return
  fi
  fail "docker compose or docker-compose is required"
}

random_password() {
  local length="${1:-24}"
  python3 - "${length}" <<'PY'
import secrets
import string
import sys

length = int(sys.argv[1])
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(length)))
PY
}

ensure_env_var() {
  local name="$1"
  local value="$2"
  if ! grep -Eq "^${name}=" "${ENV_FILE}"; then
    printf '%s=%s\n' "${name}" "${value}" >>"${ENV_FILE}"
  fi
}

ensure_env_file() {
  mkdir -p "${STATE_DIR}" "${FILEBEAT_DATA_DIR}" "${LOG_DIR}"
  touch "${LOG_DIR}/bot.json.log"

  if [[ ! -f "${ENV_FILE}" ]]; then
    local password
    local kibana_password
    local encryption_key
    password="${ELASTIC_PASSWORD:-$(random_password 24)}"
    kibana_password="${KIBANA_SYSTEM_PASSWORD:-$(random_password 24)}"
    encryption_key="${KIBANA_ENCRYPTION_KEY:-$(random_password 48)}"

    umask 077
    cat >"${ENV_FILE}" <<EOF
ELASTIC_VERSION=${ELASTIC_VERSION:-8.19.4}
ELASTIC_PASSWORD=${password}
KIBANA_SYSTEM_PASSWORD=${kibana_password}
KIBANA_ENCRYPTION_KEY=${encryption_key}
ELASTICSEARCH_HOST=http://elasticsearch:9200
ELASTICSEARCH_USERNAME=elastic
ELASTICSEARCH_PORT=${ELASTICSEARCH_PORT:-9200}
KIBANA_PORT=${KIBANA_PORT:-5601}
APM_PORT=${APM_PORT:-8200}
ELASTIFUND_LOG_DIR=${LOG_DIR}
KIBANA_PUBLIC_BASE_URL=http://127.0.0.1:5601
EOF
  fi

  ensure_env_var "ELASTIC_PASSWORD" "$(random_password 24)"
  ensure_env_var "KIBANA_SYSTEM_PASSWORD" "$(random_password 24)"
  ensure_env_var "KIBANA_ENCRYPTION_KEY" "$(random_password 48)"
  ensure_env_var "ELASTICSEARCH_HOST" "http://elasticsearch:9200"
  ensure_env_var "ELASTICSEARCH_USERNAME" "elastic"
  ensure_env_var "ELASTICSEARCH_PORT" "9200"
  ensure_env_var "KIBANA_PORT" "5601"
  ensure_env_var "APM_PORT" "8200"
  ensure_env_var "ELASTIFUND_LOG_DIR" "${LOG_DIR}"
  ensure_env_var "KIBANA_PUBLIC_BASE_URL" "http://127.0.0.1:5601"
  chmod 600 "${ENV_FILE}"
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
}

wait_for_elasticsearch() {
  local attempt=0
  local health=""
  until health="$(curl -sS -u "elastic:${ELASTIC_PASSWORD}" "http://127.0.0.1:${ELASTICSEARCH_PORT}/_cluster/health" 2>/dev/null)"; do
    attempt=$((attempt + 1))
    if [[ "${attempt}" -ge 60 ]]; then
      fail "Timed out waiting for Elasticsearch HTTP endpoint"
    fi
    sleep 2
  done

  attempt=0
  while [[ "${health}" != *"\"status\":\"yellow\""* && "${health}" != *"\"status\":\"green\""* ]]; do
    attempt=$((attempt + 1))
    if [[ "${attempt}" -ge 60 ]]; then
      fail "Timed out waiting for Elasticsearch cluster health"
    fi
    sleep 2
    health="$(curl -sS -u "elastic:${ELASTIC_PASSWORD}" "http://127.0.0.1:${ELASTICSEARCH_PORT}/_cluster/health")"
  done

  log "Elasticsearch health: ${health}"
}

set_kibana_system_password() {
  log "Configuring kibana_system password"
  curl -sS \
    -u "elastic:${ELASTIC_PASSWORD}" \
    -H 'Content-Type: application/json' \
    -X POST \
    "http://127.0.0.1:${ELASTICSEARCH_PORT}/_security/user/kibana_system/_password" \
    -d "{\"password\":\"${KIBANA_SYSTEM_PASSWORD}\"}" >/dev/null
}

apply_template() {
  local template_path="$1"
  local template_name
  template_name="$(basename "${template_path}" .json)"

  log "Applying index template ${template_name}"
  curl -sS \
    -u "elastic:${ELASTIC_PASSWORD}" \
    -H 'Content-Type: application/json' \
    -X PUT \
    "http://127.0.0.1:${ELASTICSEARCH_PORT}/_index_template/${template_name}" \
    --data-binary "@${template_path}" >/dev/null
}

main() {
  require_cmd docker
  require_cmd curl
  require_cmd python3
  detect_compose
  ensure_env_file
  load_env

  if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon is not reachable"
  fi

  log "Pulling Elastic images"
  "${COMPOSE_CMD[@]}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull

  log "Starting Elasticsearch"
  "${COMPOSE_CMD[@]}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d elasticsearch

  wait_for_elasticsearch
  set_kibana_system_password

  log "Starting Kibana, Filebeat, and APM Server"
  "${COMPOSE_CMD[@]}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d kibana filebeat apm-server

  for template in "${SCRIPT_DIR}"/index_templates/*.json; do
    apply_template "${template}"
  done

  log "Kibana: http://127.0.0.1:${KIBANA_PORT}"
  log "Elasticsearch: http://127.0.0.1:${ELASTICSEARCH_PORT}"
  log "APM Server: http://127.0.0.1:${APM_PORT}"
  log "Filebeat harvest path: ${LOG_DIR}/bot.json.log"
  log "Elastic password saved to ${ENV_FILE}"
  log "If you want the bootstrap logs too, run:"
  log "  ${COMPOSE_CMD[*]} --env-file ${ENV_FILE} -f ${COMPOSE_FILE} logs elasticsearch"
}

main "$@"
