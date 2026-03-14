#!/usr/bin/env bash
# Refresh the full edge scan pipeline: pipeline refresh + edge scan + kill battery.
# Run from Mac terminal or VPS with network access to Polymarket APIs.
#
# Usage:
#   ./scripts/refresh_edge_pipeline.sh              # Full refresh
#   ./scripts/refresh_edge_pipeline.sh --kill-only   # Just re-run kill battery (no API needed)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

KILL_ONLY=false
if [[ "${1:-}" == "--kill-only" ]]; then
    KILL_ONLY=true
fi

echo "=== Edge Pipeline Refresh ==="
echo "Repo: $REPO_ROOT"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

if [[ "$KILL_ONLY" == "false" ]]; then
    echo "--- Step 1/3: Pipeline Refresh (Gamma API) ---"
    python3 -m src.pipeline_refresh 2>&1 || {
        echo "WARNING: Pipeline refresh failed (network access required). Skipping."
    }
    echo ""

    echo "--- Step 2/3: Edge Scan Report ---"
    python3 bot/edge_scan_report.py 2>&1 || {
        echo "WARNING: Edge scan failed (network access required). Skipping."
    }
    echo ""
fi

echo "--- Step 3/3: Kill Battery ---"
python3 scripts/run_kill_battery.py --db data/edge_discovery.db --output "$REPO_ROOT" 2>&1

echo ""
echo "=== Pipeline refresh complete ==="
echo "Report: $REPO_ROOT/FAST_TRADE_EDGE_ANALYSIS.md"
echo "Last 3 lines:"
tail -3 "$REPO_ROOT/FAST_TRADE_EDGE_ANALYSIS.md"
