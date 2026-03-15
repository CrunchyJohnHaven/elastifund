"""Standalone frontier builder — runs every 30 minutes via cron. No LLM needed.

Extracts build_expansion_frontier() + persist from autoresearch_loop.
Writes artifacts to data/ directory for downstream consumption.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ACTIONABLE_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/exact_actionable_frontier.json")
SIGNAL_ONLY_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/signal_only_frontier.json")


def main() -> None:
    import time as _time
    _t0 = _time.time()

    from bot.autoresearch_loop import (
        build_expansion_frontier, persist_expansion_frontier,
        build_ev_consistency_audit, build_h_dir_down_diagnosis,
    )

    logging.info("Building expansion frontier...")
    frontier = build_expansion_frontier(hours=48)

    actionable = [c for c in frontier if c.get("actionable")]
    signal_only = [c for c in frontier if not c.get("actionable")]

    logging.info("Frontier: %d actionable, %d signal-only", len(actionable), len(signal_only))

    # Persist to DB with cycle scoping.
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    if frontier:
        persist_expansion_frontier(frontier, cycle_id=cycle_id)

    # Write JSON artifacts.
    now = datetime.now(timezone.utc).isoformat()
    ACTIONABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTIONABLE_PATH.write_text(json.dumps({
        "generated_at": now,
        "cycle_id": cycle_id,
        "total": len(actionable),
        "cells": actionable,
    }, indent=2))

    SIGNAL_ONLY_PATH.write_text(json.dumps({
        "generated_at": now,
        "cycle_id": cycle_id,
        "total": len(signal_only),
        "note": "Signal-only: not eligible for allowlists. Use for instrumentation priorities.",
        "cells": signal_only,
    }, indent=2))

    # Build audit artifacts.
    ev_audit = build_ev_consistency_audit(frontier) if frontier else None
    h_diag = build_h_dir_down_diagnosis()

    logging.info("Artifacts written: actionable=%s, signal_only=%s", ACTIONABLE_PATH, SIGNAL_ONLY_PATH)
    logging.info("EV audit status: %s", ev_audit.get("status") if ev_audit else "no_frontier")
    logging.info("h_dir_down: %s", h_diag.get("recommendation"))

    # Log to cost ledger.
    try:
        from scripts.cost_ledger import log_invocation
        log_invocation(task_class="frontier", execution_path="deterministic",
                       duration_seconds=round(_time.time() - _t0, 2))
    except Exception as _e:
        logging.warning("cost_ledger write failed: %s", _e)


if __name__ == "__main__":
    main()
