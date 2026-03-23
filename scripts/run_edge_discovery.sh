#!/bin/bash
# run_edge_discovery.sh — Continuous Edge Discovery Daemon
# =========================================================
# Runs the EdgeDiscoveryEngine in a loop: generate hypotheses, test via
# walk-forward, apply kill rules, surface survivors, sleep, repeat.
#
# Usage:
#   ./scripts/run_edge_discovery.sh                        # defaults
#   ./scripts/run_edge_discovery.sh --max-hypotheses 100   # larger batches
#   ./scripts/run_edge_discovery.sh --once                 # single cycle
#
# Environment variables:
#   EDGE_DISCOVERY_MAX_HYPOTHESES   (default: 50)
#   EDGE_DISCOVERY_CYCLE_TIMEOUT    (default: 3600 seconds)
#   EDGE_DISCOVERY_OUTPUT_DIR       (default: /tmp/edge_discovery)
#   EDGE_DISCOVERY_SLEEP_SEC        (default: 60 seconds between cycles)
#   EDGE_DISCOVERY_DATA_PATH        (default: empty, uses synthetic data)
#   EDGE_DISCOVERY_WORKERS          (default: cpu_count - 1)
#   EDGE_DISCOVERY_VERBOSE          (set to "1" for debug logging)

set -euo pipefail

# -------------------------------------------------------------------
# Resolve repo root (script lives in scripts/, repo root is one up)
# -------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export ELASTIFUND_ROOT="$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"

# -------------------------------------------------------------------
# Configuration from environment with defaults
# -------------------------------------------------------------------

MAX_HYPOTHESES="${EDGE_DISCOVERY_MAX_HYPOTHESES:-50}"
CYCLE_TIMEOUT="${EDGE_DISCOVERY_CYCLE_TIMEOUT:-3600}"
OUTPUT_DIR="${EDGE_DISCOVERY_OUTPUT_DIR:-/tmp/edge_discovery}"
SLEEP_SEC="${EDGE_DISCOVERY_SLEEP_SEC:-60}"
DATA_PATH="${EDGE_DISCOVERY_DATA_PATH:-}"
WORKERS="${EDGE_DISCOVERY_WORKERS:-0}"
VERBOSE="${EDGE_DISCOVERY_VERBOSE:-0}"
CONFIG_FILE="$REPO_ROOT/config/edge_discovery_config.yaml"

# -------------------------------------------------------------------
# Parse CLI args (override env vars)
# -------------------------------------------------------------------

RUN_ONCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-hypotheses)
            MAX_HYPOTHESES="$2"; shift 2 ;;
        --cycle-timeout)
            CYCLE_TIMEOUT="$2"; shift 2 ;;
        --output-dir)
            OUTPUT_DIR="$2"; shift 2 ;;
        --sleep)
            SLEEP_SEC="$2"; shift 2 ;;
        --data-path)
            DATA_PATH="$2"; shift 2 ;;
        --workers)
            WORKERS="$2"; shift 2 ;;
        --verbose)
            VERBOSE=1; shift ;;
        --once)
            RUN_ONCE=true; shift ;;
        --config)
            CONFIG_FILE="$2"; shift 2 ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Build Python command
# -------------------------------------------------------------------

PYTHON_CMD="python3 $REPO_ROOT/src/edge_discovery_engine.py"
PYTHON_CMD="$PYTHON_CMD --max-hypotheses $MAX_HYPOTHESES"
PYTHON_CMD="$PYTHON_CMD --cycle-timeout $CYCLE_TIMEOUT"
PYTHON_CMD="$PYTHON_CMD --output-dir $OUTPUT_DIR"

if [[ -n "$DATA_PATH" ]]; then
    PYTHON_CMD="$PYTHON_CMD --data-path $DATA_PATH"
fi

if [[ "$WORKERS" -gt 0 ]]; then
    PYTHON_CMD="$PYTHON_CMD --workers $WORKERS"
fi

if [[ -f "$CONFIG_FILE" ]]; then
    PYTHON_CMD="$PYTHON_CMD --config $CONFIG_FILE"
fi

if [[ "$VERBOSE" == "1" ]]; then
    PYTHON_CMD="$PYTHON_CMD --verbose"
fi

BACKLOG="$REPO_ROOT/research/edge_backlog_ranked.md"
if [[ -f "$BACKLOG" ]]; then
    PYTHON_CMD="$PYTHON_CMD --backlog $BACKLOG"
fi

# -------------------------------------------------------------------
# Ensure output directory exists
# -------------------------------------------------------------------

mkdir -p "$OUTPUT_DIR"

# -------------------------------------------------------------------
# Log banner
# -------------------------------------------------------------------

echo ""
echo "================================================================"
echo " EDGE DISCOVERY ENGINE — Elastifund / JJ"
echo "================================================================"
echo " Repo root:        $REPO_ROOT"
echo " Output dir:       $OUTPUT_DIR"
echo " Max hypotheses:   $MAX_HYPOTHESES per cycle"
echo " Cycle timeout:    ${CYCLE_TIMEOUT}s"
echo " Sleep between:    ${SLEEP_SEC}s"
echo " Workers:          ${WORKERS:-auto}"
echo " Config file:      ${CONFIG_FILE:-none}"
echo " Run once:         $RUN_ONCE"
echo "================================================================"
echo ""

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------

CYCLE=0

while true; do
    CYCLE=$((CYCLE + 1))
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting edge discovery cycle $CYCLE..."
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] CMD: $PYTHON_CMD"
    echo ""

    # Run the engine; capture exit code without aborting the loop
    if eval "$PYTHON_CMD"; then
        echo ""
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Cycle $CYCLE complete (success)."
    else
        EXIT_CODE=$?
        echo ""
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] WARNING: Cycle $CYCLE exited with code $EXIT_CODE." >&2
    fi

    # Check for survivors and log count
    SURVIVORS_FILE="$OUTPUT_DIR/survivors.json"
    if [[ -f "$SURVIVORS_FILE" ]]; then
        SURVIVOR_COUNT=$(python3 -c "import json,sys; d=json.load(open('$SURVIVORS_FILE')); print(len(d))" 2>/dev/null || echo "?")
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Total survivors in $SURVIVORS_FILE: $SURVIVOR_COUNT"
    fi

    if [[ "$RUN_ONCE" == true ]]; then
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] --once flag set. Exiting."
        break
    fi

    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Sleeping ${SLEEP_SEC}s before next cycle..."
    sleep "$SLEEP_SEC"
    echo ""
done

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Edge discovery daemon exited after $CYCLE cycles."
