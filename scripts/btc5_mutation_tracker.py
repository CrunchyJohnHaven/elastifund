#!/usr/bin/env python3
"""
btc5_mutation_tracker.py — Mutation lifecycle manager for BTC5 strategy configs.

Tracks a single "active mutation" at a time: the currently promoted config variant
that is being verified against a minimum performance bar before becoming the new
incumbent. Supports automatic revert if safety criteria are breached.

State file: state/btc5_active_mutation.json
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = _REPO_ROOT / "state" / "btc5_active_mutation.json"

# ---------------------------------------------------------------------------
# Auto-revert thresholds
# ---------------------------------------------------------------------------
CAP_BREACH_LIMIT = 0         # any breach triggers revert
UP_ORDER_ATTEMPT_LIMIT = 0   # any UP attempt triggers revert
CONFIG_HASH_MISMATCH_LIMIT = 3
MIN_FILLS_FOR_WINRATE_CHECK = 20
MIN_WIN_RATE = 0.30


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_active_mutation() -> dict | None:
    """Load the active mutation record from disk. Returns None if missing."""
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load active mutation state: %s", exc)
        return None


def save_active_mutation(mutation: dict) -> None:
    """Persist the mutation record to disk atomically."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mutation, indent=2))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def promote_mutation(
    mutation_id: str,
    config_hash: str,
    config_snapshot: dict[str, Any],
    notes: str = "",
) -> dict:
    """Create a new mutation record for the promoted config.

    Any prior mutation is superseded. The caller is responsible for preserving
    the incumbent hash before calling this.
    """
    existing = load_active_mutation()
    incumbent_hash = (existing or {}).get("config_hash")

    mutation: dict[str, Any] = {
        "mutation_id": mutation_id,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": config_hash,
        "config_snapshot": config_snapshot,
        "incumbent_config_hash": incumbent_hash,
        "verification_status": "pending",
        "verification_started_at": datetime.now(timezone.utc).isoformat(),
        "windows_since_promotion": 0,
        "fills_since_promotion": 0,
        "wins_since_promotion": 0,
        "losses_since_promotion": 0,
        "cap_breach_count": 0,
        "up_order_attempt_count": 0,
        "config_hash_mismatch_count": 0,
        "auto_revert_triggered": False,
        "auto_revert_reason": None,
        "auto_revert_at": None,
        "notes": notes,
    }
    save_active_mutation(mutation)
    logger.info("Promoted mutation %s (hash=%s)", mutation_id, config_hash)
    return mutation


def record_fill(won: bool) -> None:
    """Increment fill counters for the active mutation."""
    mutation = load_active_mutation()
    if mutation is None:
        logger.warning("record_fill called but no active mutation found")
        return
    mutation["fills_since_promotion"] = mutation.get("fills_since_promotion", 0) + 1
    if won:
        mutation["wins_since_promotion"] = mutation.get("wins_since_promotion", 0) + 1
    else:
        mutation["losses_since_promotion"] = mutation.get("losses_since_promotion", 0) + 1
    save_active_mutation(mutation)


def record_cap_breach() -> dict:
    """Record a position-cap breach and trigger auto-revert."""
    mutation = load_active_mutation()
    if mutation is None:
        logger.error("record_cap_breach called but no active mutation found")
        return {}
    mutation["cap_breach_count"] = mutation.get("cap_breach_count", 0) + 1
    mutation["auto_revert_triggered"] = True
    mutation["auto_revert_reason"] = (
        f"cap_breach: cap_breach_count={mutation['cap_breach_count']}"
    )
    mutation["auto_revert_at"] = datetime.now(timezone.utc).isoformat()
    mutation["verification_status"] = "reverted"
    save_active_mutation(mutation)
    logger.error(
        "AUTO-REVERT TRIGGERED — cap breach #%d on mutation %s",
        mutation["cap_breach_count"],
        mutation.get("mutation_id"),
    )
    return mutation


def record_up_order_attempt() -> dict:
    """Record an UP-direction order attempt and trigger auto-revert."""
    mutation = load_active_mutation()
    if mutation is None:
        logger.error("record_up_order_attempt called but no active mutation found")
        return {}
    mutation["up_order_attempt_count"] = mutation.get("up_order_attempt_count", 0) + 1
    mutation["auto_revert_triggered"] = True
    mutation["auto_revert_reason"] = (
        f"up_order_attempt: count={mutation['up_order_attempt_count']}"
    )
    mutation["auto_revert_at"] = datetime.now(timezone.utc).isoformat()
    mutation["verification_status"] = "reverted"
    save_active_mutation(mutation)
    logger.error(
        "AUTO-REVERT TRIGGERED — UP order attempt #%d on mutation %s",
        mutation["up_order_attempt_count"],
        mutation.get("mutation_id"),
    )
    return mutation


def check_auto_revert_needed(mutation: dict) -> tuple[bool, str]:
    """Evaluate whether the active mutation should be reverted.

    Returns (should_revert: bool, reason: str).
    An empty reason string means no revert needed.
    """
    if mutation.get("cap_breach_count", 0) > CAP_BREACH_LIMIT:
        return True, f"cap_breach_count={mutation['cap_breach_count']}"

    if mutation.get("up_order_attempt_count", 0) > UP_ORDER_ATTEMPT_LIMIT:
        return True, f"up_order_attempt_count={mutation['up_order_attempt_count']}"

    if mutation.get("config_hash_mismatch_count", 0) > CONFIG_HASH_MISMATCH_LIMIT:
        return True, f"config_hash_mismatch_count={mutation['config_hash_mismatch_count']}"

    fills = mutation.get("fills_since_promotion", 0)
    wins = mutation.get("wins_since_promotion", 0)
    if fills >= MIN_FILLS_FOR_WINRATE_CHECK:
        win_rate = wins / fills
        if win_rate < MIN_WIN_RATE:
            return True, f"win_rate={win_rate:.3f} < {MIN_WIN_RATE} after {fills} fills"

    return False, ""


def get_mutation_summary() -> str:
    """Return a human-readable summary of the active mutation for health checks."""
    mutation = load_active_mutation()
    if mutation is None:
        return "NO ACTIVE MUTATION — state/btc5_active_mutation.json missing"

    fills = mutation.get("fills_since_promotion", 0)
    wins = mutation.get("wins_since_promotion", 0)
    win_rate = (wins / fills) if fills > 0 else float("nan")

    should_revert, revert_reason = check_auto_revert_needed(mutation)
    revert_flag = f"REVERT_NEEDED({revert_reason})" if should_revert else "ok"

    lines = [
        f"mutation_id        : {mutation.get('mutation_id')}",
        f"verification_status: {mutation.get('verification_status')}",
        f"promoted_at        : {mutation.get('promoted_at')}",
        f"fills              : {fills}  wins={wins}  win_rate={win_rate:.3f}" if fills > 0 else f"fills              : 0",
        f"cap_breach_count   : {mutation.get('cap_breach_count', 0)}",
        f"up_order_attempts  : {mutation.get('up_order_attempt_count', 0)}",
        f"hash_mismatches    : {mutation.get('config_hash_mismatch_count', 0)}",
        f"auto_revert        : {mutation.get('auto_revert_triggered')} — {mutation.get('auto_revert_reason') or 'none'}",
        f"revert_check       : {revert_flag}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: hash a config dict
# ---------------------------------------------------------------------------

def hash_config(config: dict[str, Any]) -> str:
    """Return a stable SHA-256 hex digest of a config dict."""
    serialized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        print(get_mutation_summary())
    elif cmd == "revert-check":
        m = load_active_mutation()
        if m is None:
            print("MUTATION_UNKNOWN — no state file")
            sys.exit(2)
        needed, reason = check_auto_revert_needed(m)
        if needed:
            print(f"REVERT_NEEDED — {reason}")
            sys.exit(1)
        else:
            print("REVERT_NOT_NEEDED")
            sys.exit(0)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
