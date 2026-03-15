#!/usr/bin/env python3
"""BTC5 autoresearch loop v2 — evidence-informed hypothesis generation,
automatic kill list, row-hash cycle skipping, and adaptive Monte Carlo paths.

This module extends the existing autoresearch loop with four optimizations:

1. Evidence-informed hypothesis seeding: prior fill P&L by direction/session/delta
   bucket is used to weight hypothesis generation toward winning combinations.
2. Hypothesis kill list: hypotheses that fail after N fills are tracked and
   auto-skipped in future cycles.
3. Row-hash cycle skipping: expensive Monte Carlo is skipped when the data
   hash hasn't changed since the last cycle.
4. Adaptive Monte Carlo path scaling: fewer paths when data is stale, more
   when fresh fills arrive.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KILL_LIST_PATH = Path("state/btc5_hypothesis_kill_list.json")
DEFAULT_ROW_HASH_PATH = Path("state/btc5_row_hash_cache.json")
DEFAULT_EVIDENCE_CACHE_PATH = Path("state/btc5_evidence_cache.json")

# Kill thresholds
KILL_MIN_FILLS = 12  # Minimum fills before a hypothesis can be killed
KILL_MAX_WIN_RATE = 0.42  # Kill if win rate below this after KILL_MIN_FILLS
KILL_MAX_NEGATIVE_PNL = -3.0  # Kill if cumulative PnL below this
KILL_MIN_PROFIT_FACTOR = 0.7  # Kill if profit factor below this
KILL_COOLDOWN_HOURS = 72.0  # Don't re-evaluate killed hypotheses for N hours

# Adaptive MC path ranges
MC_PATHS_STALE = 800  # When no new evidence (fast cycle)
MC_PATHS_NORMAL = 2000  # Default
MC_PATHS_FRESH = 3000  # When fresh fills just arrived

# Evidence weighting
DIRECTION_WEIGHT_POSITIVE = 1.8  # Boost winning directions
DIRECTION_WEIGHT_NEGATIVE = 0.4  # Suppress losing directions
SESSION_WEIGHT_POSITIVE = 1.6
SESSION_WEIGHT_NEGATIVE = 0.5
DELTA_WEIGHT_POSITIVE = 1.4
DELTA_WEIGHT_NEGATIVE = 0.6


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Row-hash cycle skipping
# ---------------------------------------------------------------------------


def compute_row_hash(rows: list[dict[str, Any]]) -> str:
    """Compute a deterministic hash of trade rows to detect data changes."""
    # Hash the count + last 5 row timestamps + total PnL as a fast fingerprint
    fingerprint_parts: list[str] = [str(len(rows))]
    for row in rows[-5:]:
        fingerprint_parts.append(str(row.get("created_at", "")))
        fingerprint_parts.append(str(row.get("pnl_usd", "")))
    total_pnl = sum(_safe_float(r.get("pnl_usd"), 0.0) for r in rows)
    live_filled = sum(
        1
        for r in rows
        if str(r.get("order_status", "")).strip().lower() == "live_filled"
    )
    fingerprint_parts.append(f"pnl={total_pnl:.4f}")
    fingerprint_parts.append(f"filled={live_filled}")
    return hashlib.sha256("|".join(fingerprint_parts).encode()).hexdigest()[:16]


def load_row_hash_cache(path: Path = DEFAULT_ROW_HASH_PATH) -> dict[str, Any]:
    """Load the row-hash cache from disk."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_row_hash_cache(
    row_hash: str,
    cycle_result: dict[str, Any] | None,
    path: Path = DEFAULT_ROW_HASH_PATH,
) -> None:
    """Save the current row hash and cycle result summary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "row_hash": row_hash,
        "saved_at": _now_utc().isoformat(),
        "cycle_action": (cycle_result or {}).get("decision", {}).get("action", "unknown"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def should_skip_cycle(
    rows: list[dict[str, Any]],
    cache_path: Path = DEFAULT_ROW_HASH_PATH,
) -> tuple[bool, str]:
    """Check if the cycle can be skipped because data hasn't changed.

    Returns (should_skip, current_hash).
    """
    current_hash = compute_row_hash(rows)
    cache = load_row_hash_cache(cache_path)
    if cache.get("row_hash") == current_hash:
        return True, current_hash
    return False, current_hash


# ---------------------------------------------------------------------------
# Adaptive Monte Carlo path scaling
# ---------------------------------------------------------------------------


def adaptive_mc_paths(
    *,
    live_fill_delta: int,
    validation_delta: int,
    probe_freshness_hours: float | None,
    base_paths: int = MC_PATHS_NORMAL,
) -> int:
    """Scale Monte Carlo paths based on evidence freshness.

    When fresh fills arrive, use more paths for higher precision.
    When stale, use fewer paths for faster cycles.
    """
    freshness = probe_freshness_hours if probe_freshness_hours is not None else 9999.0
    has_new_evidence = live_fill_delta > 0 or validation_delta > 0

    if has_new_evidence:
        # Fresh evidence: increase precision
        multiplier = 1.5 if live_fill_delta > 0 and validation_delta > 0 else 1.2
        return min(MC_PATHS_FRESH, max(base_paths, int(base_paths * multiplier)))
    elif freshness > 12.0:
        # Very stale: minimal compute
        return max(400, MC_PATHS_STALE)
    elif freshness > 6.0:
        # Somewhat stale: reduced compute
        return max(600, int(base_paths * 0.6))
    else:
        # Recent but no new fills: normal
        return base_paths


# ---------------------------------------------------------------------------
# Evidence-informed hypothesis seeding
# ---------------------------------------------------------------------------


def build_evidence_weights(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """Analyze prior fill data to build weights for hypothesis generation.

    Returns weights by direction, session, and delta bucket that can be used
    to bias the hypothesis grid toward winning combinations.
    """
    direction_stats: dict[str, dict[str, float]] = {}
    session_stats: dict[str, dict[str, float]] = {}
    delta_stats: dict[str, dict[str, float]] = {}

    for row in rows:
        if str(row.get("order_status", "")).strip().lower() != "live_filled":
            continue
        pnl = _safe_float(row.get("pnl_usd"), 0.0)

        # Direction
        direction = str(row.get("direction", "UNKNOWN")).strip().upper()
        if direction not in direction_stats:
            direction_stats[direction] = {"fills": 0, "pnl": 0.0, "wins": 0}
        direction_stats[direction]["fills"] += 1
        direction_stats[direction]["pnl"] += pnl
        if pnl > 0:
            direction_stats[direction]["wins"] += 1

        # Session
        session = str(row.get("session_name", "any"))
        if session not in session_stats:
            session_stats[session] = {"fills": 0, "pnl": 0.0, "wins": 0}
        session_stats[session]["fills"] += 1
        session_stats[session]["pnl"] += pnl
        if pnl > 0:
            session_stats[session]["wins"] += 1

        # Delta bucket
        abs_delta = _safe_float(row.get("abs_delta") or row.get("delta"), 0.0)
        if abs_delta <= 0.00005:
            bucket = "tight"
        elif abs_delta <= 0.00015:
            bucket = "medium"
        else:
            bucket = "wide"
        if bucket not in delta_stats:
            delta_stats[bucket] = {"fills": 0, "pnl": 0.0, "wins": 0}
        delta_stats[bucket]["fills"] += 1
        delta_stats[bucket]["pnl"] += pnl
        if pnl > 0:
            delta_stats[bucket]["wins"] += 1

    def _weight(stats: dict[str, float]) -> float:
        """Convert stats to a weight multiplier."""
        fills = max(1, int(stats.get("fills", 0)))
        pnl = stats.get("pnl", 0.0)
        win_rate = stats.get("wins", 0) / fills
        if pnl > 0 and win_rate > 0.5:
            return DIRECTION_WEIGHT_POSITIVE
        elif pnl < 0 and win_rate < 0.45:
            return DIRECTION_WEIGHT_NEGATIVE
        return 1.0

    return {
        "direction": {k: _weight(v) for k, v in direction_stats.items()},
        "session": {k: _weight(v) for k, v in session_stats.items()},
        "delta_bucket": {k: _weight(v) for k, v in delta_stats.items()},
        "raw_stats": {
            "direction": {k: dict(v) for k, v in direction_stats.items()},
            "session": {k: dict(v) for k, v in session_stats.items()},
            "delta_bucket": {k: dict(v) for k, v in delta_stats.items()},
        },
    }


def save_evidence_cache(
    weights: dict[str, Any],
    path: Path = DEFAULT_EVIDENCE_CACHE_PATH,
) -> None:
    """Persist evidence weights for use across cycles."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": _now_utc().isoformat(),
        "weights": weights,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load_evidence_cache(
    path: Path = DEFAULT_EVIDENCE_CACHE_PATH,
) -> dict[str, Any]:
    """Load cached evidence weights."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
        return payload.get("weights", {})
    except (json.JSONDecodeError, OSError):
        return {}


def evidence_weight_for_hypothesis(
    weights: dict[str, Any],
    *,
    direction: str | None,
    session_name: str,
    max_abs_delta: float | None,
) -> float:
    """Compute a combined evidence weight for a hypothesis spec."""
    combined = 1.0

    # Direction weight
    dir_weights = weights.get("direction", {})
    if direction and direction.upper() in dir_weights:
        combined *= dir_weights[direction.upper()]
    elif direction is None:
        # ANY direction: use average of all direction weights
        if dir_weights:
            combined *= sum(dir_weights.values()) / len(dir_weights)

    # Session weight
    sess_weights = weights.get("session", {})
    if session_name in sess_weights:
        combined *= sess_weights[session_name]

    # Delta bucket weight
    delta_weights = weights.get("delta_bucket", {})
    if max_abs_delta is not None:
        if max_abs_delta <= 0.00005:
            bucket = "tight"
        elif max_abs_delta <= 0.00015:
            bucket = "medium"
        else:
            bucket = "wide"
        if bucket in delta_weights:
            combined *= delta_weights[bucket]

    return round(combined, 4)


# ---------------------------------------------------------------------------
# Hypothesis kill list
# ---------------------------------------------------------------------------


def load_kill_list(path: Path = DEFAULT_KILL_LIST_PATH) -> dict[str, Any]:
    """Load the hypothesis kill list from disk."""
    if not path.exists():
        return {"killed": {}, "version": 1}
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            return {"killed": {}, "version": 1}
        return payload
    except (json.JSONDecodeError, OSError):
        return {"killed": {}, "version": 1}


def save_kill_list(kill_list: dict[str, Any], path: Path = DEFAULT_KILL_LIST_PATH) -> None:
    """Persist the kill list to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    kill_list["updated_at"] = _now_utc().isoformat()
    path.write_text(json.dumps(kill_list, indent=2, sort_keys=True) + "\n")


def is_hypothesis_killed(
    kill_list: dict[str, Any],
    hypothesis_name: str,
) -> bool:
    """Check if a hypothesis is on the kill list and still within cooldown."""
    killed = kill_list.get("killed", {})
    entry = killed.get(hypothesis_name)
    if entry is None:
        return False
    killed_at_str = entry.get("killed_at", "")
    if not killed_at_str:
        return True  # Killed but no timestamp — treat as permanent
    try:
        killed_at = datetime.fromisoformat(killed_at_str.replace("Z", "+00:00"))
        if killed_at.tzinfo is None:
            killed_at = killed_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    hours_since = (_now_utc() - killed_at).total_seconds() / 3600.0
    return hours_since < KILL_COOLDOWN_HOURS


def evaluate_for_kill(
    rows: list[dict[str, Any]],
    hypothesis_name: str,
    *,
    direction: str | None = None,
    session_name: str = "any",
    max_abs_delta: float | None = None,
    up_max_buy_price: float | None = None,
    down_max_buy_price: float | None = None,
    et_hours: tuple[int, ...] = (),
) -> dict[str, Any] | None:
    """Evaluate whether a hypothesis should be killed based on fill performance.

    Returns a kill record if the hypothesis should be killed, None otherwise.
    """
    # Import here to avoid circular dependency
    from scripts.btc5_hypothesis_lab import (
        HypothesisSpec,
        row_matches_hypothesis,
    )

    spec = HypothesisSpec(
        name=hypothesis_name,
        direction=direction,
        max_abs_delta=max_abs_delta,
        up_max_buy_price=up_max_buy_price,
        down_max_buy_price=down_max_buy_price,
        et_hours=et_hours,
        session_name=session_name,
    )

    matched_filled = [
        row
        for row in rows
        if row_matches_hypothesis(row, spec)
        and str(row.get("order_status", "")).strip().lower() == "live_filled"
    ]

    fills = len(matched_filled)
    if fills < KILL_MIN_FILLS:
        return None  # Not enough evidence to kill

    pnl = sum(_safe_float(r.get("pnl_usd"), 0.0) for r in matched_filled)
    wins = sum(1 for r in matched_filled if _safe_float(r.get("pnl_usd"), 0.0) > 0)
    losses = sum(1 for r in matched_filled if _safe_float(r.get("pnl_usd"), 0.0) < 0)
    win_rate = wins / fills if fills > 0 else 0.0
    gross_wins = sum(
        _safe_float(r.get("pnl_usd"), 0.0)
        for r in matched_filled
        if _safe_float(r.get("pnl_usd"), 0.0) > 0
    )
    gross_losses = abs(
        sum(
            _safe_float(r.get("pnl_usd"), 0.0)
            for r in matched_filled
            if _safe_float(r.get("pnl_usd"), 0.0) < 0
        )
    )
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    kill_reasons: list[str] = []
    if win_rate < KILL_MAX_WIN_RATE:
        kill_reasons.append(f"win_rate={win_rate:.3f}<{KILL_MAX_WIN_RATE}")
    if pnl < KILL_MAX_NEGATIVE_PNL:
        kill_reasons.append(f"pnl={pnl:.2f}<{KILL_MAX_NEGATIVE_PNL}")
    if profit_factor < KILL_MIN_PROFIT_FACTOR:
        kill_reasons.append(f"profit_factor={profit_factor:.3f}<{KILL_MIN_PROFIT_FACTOR}")

    if not kill_reasons:
        return None

    return {
        "hypothesis_name": hypothesis_name,
        "killed_at": _now_utc().isoformat(),
        "fills": fills,
        "wins": wins,
        "losses": losses,
        "pnl_usd": round(pnl, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "kill_reasons": kill_reasons,
    }


def update_kill_list(
    kill_list: dict[str, Any],
    rows: list[dict[str, Any]],
    evaluated_hypotheses: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate all recently tested hypotheses for kill.

    Returns updated kill_list and list of newly killed entries.
    """
    newly_killed: list[dict[str, Any]] = []
    killed = kill_list.setdefault("killed", {})

    for hyp in evaluated_hypotheses:
        hypothesis = hyp.get("hypothesis") or {}
        name = str(hypothesis.get("name", ""))
        if not name or name in killed:
            continue

        kill_record = evaluate_for_kill(
            rows,
            name,
            direction=hypothesis.get("direction"),
            session_name=str(hypothesis.get("session_name", "any")),
            max_abs_delta=(
                _safe_float(hypothesis.get("max_abs_delta"), None)
                if hypothesis.get("max_abs_delta") is not None
                else None
            ),
            up_max_buy_price=(
                _safe_float(hypothesis.get("up_max_buy_price"), None)
                if hypothesis.get("up_max_buy_price") is not None
                else None
            ),
            down_max_buy_price=(
                _safe_float(hypothesis.get("down_max_buy_price"), None)
                if hypothesis.get("down_max_buy_price") is not None
                else None
            ),
            et_hours=tuple(
                int(h)
                for h in (hypothesis.get("et_hours") or [])
                if isinstance(h, (int, float))
            ),
        )
        if kill_record is not None:
            killed[name] = kill_record
            newly_killed.append(kill_record)

    kill_list["killed"] = killed
    return kill_list, newly_killed


# ---------------------------------------------------------------------------
# Enhanced cadence decision
# ---------------------------------------------------------------------------


def enhanced_cadence_decision(
    *,
    entry: dict[str, Any],
    previous_entry: dict[str, Any] | None,
    base_interval_seconds: int,
    consecutive_no_evidence_cycles: int = 0,
) -> dict[str, Any]:
    """More responsive cadence adaptation than the v1 system.

    Key improvements:
    - Exponential backoff when no evidence arrives (caps at 30 min)
    - Faster acceleration on new fills (down to 30s)
    - Time-of-day awareness for US trading hours
    """
    base_interval = max(60, int(base_interval_seconds))
    current_probe = (
        entry.get("current_probe")
        if isinstance(entry.get("current_probe"), dict)
        else {}
    )
    previous_probe = (
        previous_entry.get("current_probe")
        if isinstance((previous_entry or {}).get("current_probe"), dict)
        else {}
    )

    live_fill_delta = _safe_int(
        current_probe.get("live_filled_rows_delta"),
        _safe_int(current_probe.get("live_filled_row_count"), 0)
        - _safe_int(previous_probe.get("live_filled_row_count"), 0),
    )
    validation_delta = _safe_int(
        current_probe.get("validation_live_filled_rows_delta"),
        _safe_int(entry.get("validation_live_filled_rows"), 0)
        - _safe_int((previous_entry or {}).get("validation_live_filled_rows"), 0),
    )
    probe_freshness_hours = _safe_float(
        current_probe.get("probe_freshness_hours"), 9999.0
    )
    has_new_evidence = live_fill_delta > 0 or validation_delta > 0

    # Check if we're in US trading hours (roughly 14:00-21:00 UTC = 9-4 ET)
    now = _now_utc()
    is_trading_hours = 14 <= now.hour <= 21

    if has_new_evidence:
        # Aggressive acceleration
        if live_fill_delta > 0 and validation_delta > 0:
            multiplier = 0.2  # Both arrived: very fast
        elif live_fill_delta > 0:
            multiplier = 0.3  # New fills: fast
        else:
            multiplier = 0.4  # Just validation: moderately fast
        recommended = max(30, int(round(base_interval * multiplier)))
        mode = "accelerated"
        reason = "new_fills_or_validation_rows_arrived"
    elif is_trading_hours and probe_freshness_hours <= 1.0:
        # During trading hours with fresh probe: stay responsive
        recommended = max(60, int(round(base_interval * 0.6)))
        mode = "trading_hours_watch"
        reason = "us_trading_hours_probe_fresh"
    elif probe_freshness_hours > 12.0:
        # Very stale: exponential backoff capped at 30 min
        backoff_factor = min(6.0, 2.0 + (consecutive_no_evidence_cycles * 0.5))
        recommended = min(1800, int(round(base_interval * backoff_factor)))
        mode = "deep_sleep"
        reason = "probe_stale_and_no_new_evidence"
    elif consecutive_no_evidence_cycles > 3:
        # Multiple stale cycles: progressive backoff
        backoff_factor = min(4.0, 1.5 + (consecutive_no_evidence_cycles * 0.3))
        recommended = min(1200, int(round(base_interval * backoff_factor)))
        mode = "slowed"
        reason = "consecutive_no_evidence_cycles"
    else:
        recommended = min(900, int(round(base_interval * 1.2)))
        mode = "normal"
        reason = "no_new_evidence_short_backoff"

    return {
        "mode": mode,
        "reason": reason,
        "base_interval_seconds": int(base_interval),
        "recommended_interval_seconds": int(recommended),
        "live_filled_rows_delta": int(live_fill_delta),
        "validation_live_filled_rows_delta": int(validation_delta),
        "probe_freshness_hours": (
            round(probe_freshness_hours, 4) if probe_freshness_hours < 9999.0 else None
        ),
        "consecutive_no_evidence_cycles": consecutive_no_evidence_cycles,
        "is_trading_hours": is_trading_hours,
    }


# ---------------------------------------------------------------------------
# Cycle orchestration summary
# ---------------------------------------------------------------------------


def v2_cycle_metadata(
    *,
    rows: list[dict[str, Any]],
    kill_list: dict[str, Any],
    evidence_weights: dict[str, Any],
    row_hash: str,
    skipped: bool,
    mc_paths: int,
    newly_killed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build metadata for v2 cycle tracking."""
    return {
        "v2_version": "2.0.0",
        "row_hash": row_hash,
        "cycle_skipped": skipped,
        "mc_paths_used": mc_paths,
        "killed_hypotheses_total": len(kill_list.get("killed", {})),
        "newly_killed_count": len(newly_killed),
        "newly_killed": newly_killed,
        "evidence_weights_summary": {
            "direction": evidence_weights.get("direction", {}),
            "session": evidence_weights.get("session", {}),
            "delta_bucket": evidence_weights.get("delta_bucket", {}),
        },
        "generated_at": _now_utc().isoformat(),
    }
