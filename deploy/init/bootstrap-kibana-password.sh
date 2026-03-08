#!/bin/sh
set -eu

ES_URL="${ELASTICSEARCH_URL:-http://elasticsearch:9200}"
ELASTIC_PASSWORD="${ELASTIC_PASSWORD:-changeme}"
KIBANA_SYSTEM_PASSWORD="${KIBANA_SYSTEM_PASSWORD:-changeme-kibana}"

echo "Waiting for Elasticsearch security API..."
until curl -s -u "elastic:${ELASTIC_PASSWORD}" "${ES_URL}" >/dev/null 2>&1; do
  sleep 3
done

echo "Setting kibana_system password..."
curl -s -u "elastic:${ELASTIC_PASSWORD}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${ES_URL}/_security/user/kibana_system/_password" \
  -d "{\"password\":\"${KIBANA_SYSTEM_PASSWORD}\"}" >/dev/null

echo "Kibana password bootstrap complete."
