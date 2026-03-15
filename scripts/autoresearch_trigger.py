"""Autoresearch trigger — runs every 5 minutes via cron.

Fires autoresearch cycle when N new resolved windows have accumulated
since the last cycle. This replaces fixed-schedule autoresearch with
data-driven triggering.

Usage:
    python3 scripts/autoresearch_trigger.py [--dry-run] [--force]
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path.
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db")
TRIGGER_STATE_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/autoresearch_trigger_state.json")
RESULTS_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/autoresearch_results.json")

TRIGGER_THRESHOLD = 12   # Fire when N new resolved windows since last run.
MIN_INTERVAL_SECONDS = 3600  # Never run more than once per hour.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("AutoresearchTrigger")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _telegram_send(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or "your-bot-token" in token:
        logger.info("[TELEGRAM-STUB] %s", text[:200])
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_trigger_state() -> dict:
    if TRIGGER_STATE_PATH.exists():
        try:
            return json.loads(TRIGGER_STATE_PATH.read_text())
        except Exception:
            pass
    return {
        "last_run_ts": 0,
        "last_run_resolved_count": 0,
        "cycle_count": 0,
        "last_frontier_cells": [],
    }


def save_trigger_state(state: dict) -> None:
    TRIGGER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRIGGER_STATE_PATH.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def count_resolved_windows() -> int:
    """Count total windows with resolved_outcome set."""
    conn = sqlite3.connect(str(DB_PATH))
    n = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE resolved_outcome IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    return n


def count_recent_resolved(since_ts: int) -> int:
    """Count newly resolved windows since a given timestamp."""
    conn = sqlite3.connect(str(DB_PATH))
    n = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE resolved_outcome IS NOT NULL AND window_start_ts > ?",
        (since_ts,),
    ).fetchone()[0]
    conn.close()
    return n


# ---------------------------------------------------------------------------
# Frontier comparison
# ---------------------------------------------------------------------------

FRONTIER_ALERT_MIN_N = 5  # Minimum sample size before alerting on a frontier cell.


def _frontier_key(cell: dict) -> str:
    return f"{cell.get('skip_reason')}/{cell.get('direction')}/{cell.get('price_bucket')}/{cell.get('delta_bucket')}"


def _should_alert_frontier_change(cell: dict) -> bool:
    """Gate for frontier alerts. Only alert on high-quality, exact-actionable cells.

    All conditions must hold:
    - exact_price_exact_resolution counterfactual quality
    - actionable=True (not signal_only)
    - n >= FRONTIER_ALERT_MIN_N
    - no consistency_flag
    - fillability_adjusted_pnl_usd_std5 present (not None)
    """
    return (
        cell.get("counterfactual_quality") == "exact_price_exact_resolution"
        and cell.get("actionable") is True
        and (cell.get("n") or 0) >= FRONTIER_ALERT_MIN_N
        and not cell.get("consistency_flag")
        and cell.get("fillability_adjusted_pnl_usd_std5") is not None
    )


def compare_frontiers(prev_cells: list[dict], curr_cells: list[dict]) -> dict:
    """Compare two frontier snapshots. Detect sign flips and new candidates.

    Only reports cells that pass _should_alert_frontier_change() on both prev and curr.
    Signal-only cells are ignored entirely.
    """
    # Filter to exact-actionable cells only.
    prev_map = {_frontier_key(c): c for c in prev_cells if _should_alert_frontier_change(c)}
    curr_alertable = [c for c in curr_cells if _should_alert_frontier_change(c)]
    curr_map = {_frontier_key(c): c for c in curr_alertable}

    sign_flips = []
    new_candidates = []
    disappeared = []

    for key, curr in curr_map.items():
        curr_pnl = curr.get("fillability_adjusted_pnl_usd_std5") or curr.get("upper_bound_pnl_usd_std5") or 0
        if key in prev_map:
            prev = prev_map[key]
            prev_pnl = prev.get("fillability_adjusted_pnl_usd_std5") or prev.get("upper_bound_pnl_usd_std5") or 0
            if (prev_pnl > 0) != (curr_pnl > 0):
                sign_flips.append({
                    "key": key,
                    "prev_pnl": round(prev_pnl, 2),
                    "curr_pnl": round(curr_pnl, 2),
                    "direction": "pos_to_neg" if curr_pnl < 0 else "neg_to_pos",
                    "n": curr.get("n"),
                })
        else:
            if curr_pnl > 0:
                new_candidates.append({
                    "key": key,
                    "pnl": round(curr_pnl, 2),
                    "n": curr.get("n"),
                    "wr_edge": curr.get("wr_edge"),
                    "cq": curr.get("counterfactual_quality"),
                })

    for key in prev_map:
        if key not in curr_map:
            disappeared.append(key)

    return {
        "sign_flips": sign_flips,
        "new_candidates": new_candidates,
        "disappeared": disappeared,
        "alertable_cells_curr": len(curr_alertable),
    }


# ---------------------------------------------------------------------------
# Run autoresearch cycle
# ---------------------------------------------------------------------------

def run_autoresearch_cycle() -> dict:
    """Import and run the autoresearch cycle."""
    try:
        from bot.autoresearch_loop import run_cycle
        result = run_cycle()
        return result
    except Exception as exc:
        logger.error("Autoresearch cycle failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, force: bool = False) -> dict:
    state = load_trigger_state()
    now_ts = int(time.time())

    # Count resolved windows.
    total_resolved = count_resolved_windows()
    new_since_last = total_resolved - state.get("last_run_resolved_count", 0)
    seconds_since_last = now_ts - state.get("last_run_ts", 0)

    logger.info(
        "Trigger check: total_resolved=%d, new_since_last=%d, seconds_since_last=%d",
        total_resolved, new_since_last, seconds_since_last,
    )

    # Check trigger conditions.
    should_run = force or (
        new_since_last >= TRIGGER_THRESHOLD
        and seconds_since_last >= MIN_INTERVAL_SECONDS
    )

    if not should_run:
        reason = (
            f"waiting for data ({new_since_last}/{TRIGGER_THRESHOLD} new resolved windows)"
            if new_since_last < TRIGGER_THRESHOLD
            else f"min interval not met ({seconds_since_last}s < {MIN_INTERVAL_SECONDS}s)"
        )
        logger.info("Not triggering: %s", reason)
        return {"triggered": False, "reason": reason, "new_since_last": new_since_last}

    logger.info(
        "TRIGGERING autoresearch: %d new resolved windows (threshold=%d)",
        new_since_last, TRIGGER_THRESHOLD,
    )

    # Load previous frontier for comparison.
    prev_frontier: list[dict] = state.get("last_frontier_cells", [])

    if dry_run:
        logger.info("[DRY-RUN] Would run autoresearch cycle now")
        return {"triggered": True, "dry_run": True}

    # Run cycle.
    cycle_start = time.time()
    result = run_autoresearch_cycle()
    cycle_secs = round(time.time() - cycle_start, 1)

    error = result.get("error")
    if error:
        msg = f"🚨 Autoresearch cycle FAILED: {error}"
        logger.error(msg)
        _telegram_send(msg)
        return {"triggered": True, "error": error}

    # Extract frontier from result.
    curr_frontier = (
        result.get("expansion_frontier_actionable", []) +
        result.get("expansion_frontier_signal_only", [])
    )

    # Compare frontiers.
    diff = compare_frontiers(prev_frontier, curr_frontier)

    # Build notification message.
    obs = result.get("observation", {})
    velocity = result.get("velocity", {})
    promoted = result.get("promoted")
    allowlist_count = len(result.get("allowlist_rules", []))

    lines = [
        f"<b>🔬 Autoresearch Cycle #{state.get('cycle_count', 0) + 1}</b>",
        f"⏱ {cycle_secs}s | {new_since_last} new windows resolved",
        "",
        f"<b>Performance (24h):</b>",
        f"  Fills: {obs.get('total_fills', 0)} | WR: {obs.get('win_rate', 0):.0%} | "
        f"PnL: ${obs.get('total_pnl', 0):.2f}",
        f"  Fill rate: {velocity.get('fill_rate', 0):.1%}",
    ]

    if promoted:
        lines.append(f"\n✅ <b>PROMOTED:</b> {promoted}")

    if allowlist_count:
        lines.append(f"📋 Allowlist rules (shadow-only): {allowlist_count}")

    if diff["sign_flips"]:
        lines.append(f"\n⚠️ <b>Sign flips ({len(diff['sign_flips'])}):</b>")
        for sf in diff["sign_flips"][:3]:
            lines.append(f"  {sf['key']}: ${sf['prev_pnl']} → ${sf['curr_pnl']}")

    if diff["new_candidates"]:
        lines.append(f"\n🆕 <b>New candidates ({len(diff['new_candidates'])}):</b>")
        for nc in diff["new_candidates"][:3]:
            lines.append(f"  {nc['key']} n={nc['n']} cf=${nc['pnl']}")

    # h_dir_down warning.
    diag = result.get("h_dir_down_diagnosis", {})
    if diag.get("recommendation") == "REAL_WARNING":
        lines.append("\n⚠️ h_dir_down: REAL_WARNING (thin edge at high prices)")

    msg = "\n".join(lines)
    logger.info("Autoresearch cycle complete:\n%s", msg)
    _telegram_send(msg)

    # Update state.
    state["last_run_ts"] = now_ts
    state["last_run_resolved_count"] = total_resolved
    state["cycle_count"] = state.get("cycle_count", 0) + 1
    state["last_frontier_cells"] = curr_frontier[:50]  # Store top 50 cells.
    save_trigger_state(state)

    return {
        "triggered": True,
        "new_since_last": new_since_last,
        "cycle_secs": cycle_secs,
        "sign_flips": len(diff["sign_flips"]),
        "new_candidates": len(diff["new_candidates"]),
        "promoted": promoted,
    }


if __name__ == "__main__":
    import time as _time
    _t0 = _time.time()

    parser = argparse.ArgumentParser(description="Autoresearch trigger")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually run cycle")
    parser.add_argument("--force", action="store_true", help="Force run regardless of threshold")
    args = parser.parse_args()

    # Load .env.
    env_file = Path("/home/ubuntu/polymarket-trading-bot/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

    result = run(dry_run=args.dry_run, force=args.force)
    print(json.dumps(result, indent=2))

    path = "api_sonnet" if result.get("triggered") and not result.get("dry_run") else "deterministic"
    try:
        from scripts.cost_ledger import log_invocation
        log_invocation(task_class="autoresearch", execution_path=path,
                       duration_seconds=round(_time.time() - _t0, 2),
                       notes=f"triggered={result.get('triggered')}")
    except Exception as _e:
        logger.warning("cost_ledger write failed: %s", _e)
