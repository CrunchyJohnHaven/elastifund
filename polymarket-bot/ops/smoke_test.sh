#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
TOKEN="${DASHBOARD_TOKEN:-test_token}"

echo "=== Smoke Test: $BASE_URL ==="
PASS=0
FAIL=0

check() {
    local name="$1"
    local url="$2"
    local expected="${3:-200}"
    
    status=$(curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$url" 2>/dev/null || echo "000")
    if [ "$status" = "$expected" ]; then
        echo "  PASS: $name ($status)"
        ((PASS++))
    else
        echo "  FAIL: $name (got $status, expected $expected)"
        ((FAIL++))
    fi
}

# Health (no auth required)
check "GET /health" "$BASE_URL/health"

# Authenticated endpoints
check "GET /status" "$BASE_URL/status"
check "GET /metrics" "$BASE_URL/metrics"
check "GET /risk" "$BASE_URL/risk"
check "GET /orders" "$BASE_URL/orders"

# Check heartbeat freshness
HEARTBEAT=$(curl -sf -H "Authorization: Bearer $TOKEN" "$BASE_URL/status" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('last_heartbeat','none'))" 2>/dev/null || echo "error")
echo "  Heartbeat: $HEARTBEAT"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
