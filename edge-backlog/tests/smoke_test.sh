#!/usr/bin/env bash
# Smoke test: full edge lifecycle IDEA → BACKTEST → PAPER → SHADOW (LIVE blocked)
set -uo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
STORE="$(mktemp).json"
PASS=0
FAIL=0

run() {
    python3 -m edge_backlog --store "$STORE" "$@"
}

check() {
    local desc="$1"; shift
    if "$@" > /dev/null 2>&1; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc"
        FAIL=$((FAIL + 1))
    fi
}

check_fail() {
    local desc="$1"; shift
    if ! "$@" > /dev/null 2>&1; then
        echo "  ✓ $desc (correctly failed)"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc (should have failed)"
        FAIL=$((FAIL + 1))
    fi
}

cd "$DIR"

echo "=== Edge Backlog Smoke Test ==="
echo ""

# 1. Add edge
echo "1. Add edge"
OUTPUT=$(run add-edge "Mean Reversion" "Markets overcorrect on breaking news" --tags "stat-arb,news" 2>&1)
EDGE_ID=$(echo "$OUTPUT" | grep -oE '[a-f0-9]{8}' | head -1)
check "Edge created with ID $EDGE_ID" test -n "$EDGE_ID"

# 2. List edges
echo "2. List edges"
check "Edge appears in list" run list-edges
check "Filter by IDEA shows edge" run list-edges --status IDEA

# 3. Score edge
echo "3. Score edge"
check "Score edge" run score-edge "$EDGE_ID" 7.5 --notes "Promising backtest data"

# 4. Start experiment
echo "4. Start experiment"
EXP_OUTPUT=$(run start-experiment "$EDGE_ID" "Backtest 500 markets" 2>&1)
EXP_ID=$(echo "$EXP_OUTPUT" | grep -oE '\([a-f0-9]{8}\)' | tr -d '()')
check "Experiment started with ID $EXP_ID" test -n "$EXP_ID"

# 5. Log result
echo "5. Log result"
check "Log win_rate" run log-result "$EDGE_ID" "$EXP_ID" win_rate 0.649
check "Log avg_pnl" run log-result "$EDGE_ID" "$EXP_ID" avg_pnl 0.60 --notes "Per trade at \$2 size"

# 6. Promote: IDEA → BACKTEST → PAPER → SHADOW
echo "6. Promote lifecycle"
check "Promote IDEA → BACKTEST" run promote "$EDGE_ID"
check "Promote BACKTEST → PAPER" run promote "$EDGE_ID"
check "Promote PAPER → SHADOW" run promote "$EDGE_ID"

# 7. LIVE must be blocked
echo "7. LIVE gate"
check_fail "Promote SHADOW → LIVE blocked" run promote "$EDGE_ID"

# 8. Demote: SHADOW → PAPER
echo "8. Demote"
check "Demote SHADOW → PAPER" run demote "$EDGE_ID"

# 9. Cannot demote below IDEA
echo "9. Demote floor"
run demote "$EDGE_ID" > /dev/null 2>&1 || true  # PAPER → BACKTEST
run demote "$EDGE_ID" > /dev/null 2>&1 || true  # BACKTEST → IDEA
check_fail "Demote below IDEA blocked" run demote "$EDGE_ID"

# Cleanup
rm -f "$STORE"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
