#!/usr/bin/env bash
# refresh_stale_artifacts.sh
# ============================================================
# Purpose: Clear script-clearable BTC5 stage-1 blockers by
#          regenerating stale artifacts on the Dublin VPS.
#
# Clears these blockers:
#   - strategy_scale_comparison_stale  (blocker #3)
#   - selected_runtime_package_stale   (blocker #4)
#   - confirmation_coverage_insufficient (blocker #6, if fill data exists)
#
# Does NOT clear:
#   - wallet_export_stale (#1) -- requires manual CSV download from Polymarket browser
#   - trailing_12_live_filled_not_positive (#2) -- requires live fills from the service
#   - selected_runtime_package_not_promote (#5) -- requires autoresearch to score "promote"
#
# Usage: Copy-paste this entire script to the VPS and run from
#        /home/ubuntu/polymarket-trading-bot/
#
# Or:    scp this file to VPS and run:
#        bash scripts/refresh_stale_artifacts.sh
# ============================================================

set -euo pipefail

REPO_DIR="/home/ubuntu/polymarket-trading-bot"
cd "$REPO_DIR"

echo "============================================================"
echo "BTC5 Stage-1 Stale Artifact Refresh"
echo "Started: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Working directory: $(pwd)"
echo "============================================================"
echo ""

# ----------------------------------------------------------
# Step 1: Check BTC5 service health (informational)
# ----------------------------------------------------------
echo "[INFO] Checking btc-5min-maker service status..."
if systemctl is-active --quiet btc-5min-maker 2>/dev/null; then
    echo "  btc-5min-maker: RUNNING"
else
    echo "  btc-5min-maker: NOT RUNNING (fills will not accumulate)"
    echo "  Consider: sudo systemctl start btc-5min-maker"
fi
echo ""

# ----------------------------------------------------------
# Step 2: Regenerate strategy_scale_comparison.json
#         Clears blocker: strategy_scale_comparison_stale
# ----------------------------------------------------------
echo "[STEP 2] Regenerating strategy scale comparison..."
echo "  Output: reports/strategy_scale_comparison.json"
python3 backtest/run_scale_comparison_core.py \
    --mode live \
    2>&1 | tail -5
SCALE_EXIT=$?
if [ $SCALE_EXIT -eq 0 ]; then
    echo "  [OK] strategy_scale_comparison regenerated successfully"
else
    echo "  [WARN] strategy_scale_comparison exited with code $SCALE_EXIT"
fi
echo ""

# ----------------------------------------------------------
# Step 3: Run BTC5 autoresearch cycle
#         Clears blocker: selected_runtime_package_stale
# ----------------------------------------------------------
echo "[STEP 3] Running BTC5 autoresearch cycle..."
echo "  Output: reports/btc5_autoresearch/latest.json"
python3 scripts/run_btc5_autoresearch_cycle.py \
    --db-path data/btc_5min_maker.db \
    --strategy-env config/btc5_strategy.env \
    --override-env state/btc5_autoresearch.env \
    --report-dir reports/btc5_autoresearch \
    --paths \
    2>&1 | tail -5
AUTORESEARCH_EXIT=$?
if [ $AUTORESEARCH_EXIT -eq 0 ]; then
    echo "  [OK] autoresearch cycle completed successfully"
else
    echo "  [WARN] autoresearch cycle exited with code $AUTORESEARCH_EXIT"
fi
echo ""

# ----------------------------------------------------------
# Step 4: Run BTC5 policy autoresearch (optional upgrade path)
#         May help clear: selected_runtime_package_not_promote
# ----------------------------------------------------------
echo "[STEP 4] Running BTC5 policy autoresearch..."
echo "  Output: reports/autoresearch/btc5_policy/latest.json"
python3 scripts/run_btc5_policy_autoresearch.py \
    2>&1 | tail -5
POLICY_EXIT=$?
if [ $POLICY_EXIT -eq 0 ]; then
    echo "  [OK] policy autoresearch completed successfully"
else
    echo "  [WARN] policy autoresearch exited with code $POLICY_EXIT"
fi
echo ""

# ----------------------------------------------------------
# Step 5: Run signal source audit
#         Clears blocker: confirmation_coverage_insufficient
#         (only if sufficient fill history exists in the DB)
# ----------------------------------------------------------
echo "[STEP 5] Running signal source audit..."
echo "  Output: reports/signal_source_audit.json"
python3 scripts/run_signal_source_audit.py \
    --db data/btc_5min_maker.db \
    2>&1 | tail -5
AUDIT_EXIT=$?
if [ $AUDIT_EXIT -eq 0 ]; then
    echo "  [OK] signal source audit completed successfully"
else
    echo "  [WARN] signal source audit exited with code $AUDIT_EXIT"
fi
echo ""

# ----------------------------------------------------------
# Step 6: Run the current probe to refresh probe freshness
# ----------------------------------------------------------
echo "[STEP 6] Refreshing BTC5 current probe..."
echo "  Output: reports/btc5_autoresearch_current_probe/latest.json"
if [ -f scripts/run_btc5_autoresearch_cycle.py ]; then
    python3 scripts/run_btc5_autoresearch_cycle.py \
        --db-path data/btc_5min_maker.db \
        --strategy-env config/btc5_strategy.env \
        --override-env state/btc5_autoresearch.env \
        --report-dir reports/btc5_autoresearch_current_probe \
        --paths \
        2>&1 | tail -3
    echo "  [OK] current probe refreshed"
else
    echo "  [SKIP] autoresearch cycle script not found"
fi
echo ""

# ----------------------------------------------------------
# Summary
# ----------------------------------------------------------
echo "============================================================"
echo "Refresh complete: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""
echo "Artifacts regenerated:"
echo "  - reports/strategy_scale_comparison.json     (exit=$SCALE_EXIT)"
echo "  - reports/btc5_autoresearch/latest.json      (exit=$AUTORESEARCH_EXIT)"
echo "  - reports/autoresearch/btc5_policy/latest.json (exit=$POLICY_EXIT)"
echo "  - reports/signal_source_audit.json           (exit=$AUDIT_EXIT)"
echo ""
echo "Remaining manual actions:"
echo "  1. Download fresh Polymarket wallet CSV from browser"
echo "     Then run: python3 scripts/reconcile_polymarket_wallet.py"
echo "  2. Wait for BTC5 service to produce 12+ live fills with positive PnL"
echo "  3. After fills exist, re-run this script to update all artifacts"
echo "============================================================"
