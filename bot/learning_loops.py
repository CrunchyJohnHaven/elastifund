"""
Learning Loops -- Three-speed self-improvement framework.

Fast loop (daily/intraday): Safe recalibrations that are fully reversible.
  - Volatility scaling updates
  - Spread/impact estimate refresh
  - Execution aggression bands
  - Risk limits tied to liquidity state
  - Skip threshold auto-adjustment based on recent fill rate

Medium loop (weekly): Controlled model refresh with rollback capability.
  - Coefficient updates (Platt A/B recalibration)
  - Feature re-estimation
  - Ensemble weight refresh
  - Regime classifier refresh
  - BTC5 parameter autoresearch integration
  - Kill-propagation sweep

Slow loop (monthly/manual): Architecture changes requiring full validation.
  - New feature families
  - New model classes
  - New execution logic
  - New market/universe
  - New portfolio constraints
  - These go through Bronze -> Silver -> Gold -> Platinum gates

Key principle: slow-loop changes go back through the full validation stack.
Never allow 'self-improvement' to mean 'the model can silently redesign production.'
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Callable
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths used by execute functions.  All are relative to the project root.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _REPO_ROOT / "state" / "learning_loops"
_BTC5_DB = _REPO_ROOT / "data" / "btc_5min_maker.db"
_JJ_TRADES_DB = _REPO_ROOT / "data" / "jj_trades.db"
_PROBE_JSON = _REPO_ROOT / "reports" / "btc5_autoresearch_current_probe" / "latest.json"

# Configured initial bankroll used as the exposure baseline (from CLAUDE.md).
_INITIAL_BANKROLL_USD = 247.51

# Skip-reason severity bands.  Anything above these fractions triggers a
# recommendation.  Values are conservative to avoid alert fatigue.
_DELTA_SKIP_WARN_FRACTION = 0.60   # >60 % of skips -> widen delta
_SHADOW_SKIP_WARN_FRACTION = 0.20  # >20 % of skips -> book depth concern
_TOXIC_SKIP_WARN_FRACTION = 0.15   # >15 % of skips -> time-of-day concern

# Risk exposure thresholds.
_EXPOSURE_WARN_PCT = 0.50   # >50 % of bankroll deployed -> WARNING
_EXPOSURE_CRIT_PCT = 0.80   # >80 % of bankroll deployed -> CRITICAL


# ---------------------------------------------------------------------------
# Helper utilities shared across execute functions.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: dict) -> None:
    """Atomically write *data* as JSON to *path*, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    """Read JSON from *path*; return empty dict if missing or corrupt."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _query_btc5_skip_distribution() -> dict:
    """Return {skip_reason: count} from the BTC5 window_trades table.

    The VPS DB stores skip reasons in the ``order_status`` column prefixed
    with ``skip_``.  The local DB uses the same schema.
    """
    if not _BTC5_DB.exists():
        return {}
    try:
        conn = sqlite3.connect(str(_BTC5_DB))
        rows = conn.execute(
            """
            SELECT order_status, COUNT(*) AS cnt
            FROM window_trades
            WHERE order_status LIKE 'skip_%'
            GROUP BY order_status
            ORDER BY cnt DESC
            """
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as exc:
        logger.warning("BTC5 skip distribution query failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Fast-loop execute functions.
# ---------------------------------------------------------------------------

def _execute_volatility_scaling() -> None:
    """Read BTC5 skip stats; if delta skips dominate, emit a recommendation.

    Writes: state/learning_loops/volatility_scaling_recommendation.json
    Never modifies .env or any live configuration.
    """
    out_path = _STATE_DIR / "volatility_scaling_recommendation.json"
    skip_dist = _query_btc5_skip_distribution()
    total_skips = sum(skip_dist.values())

    delta_skip_count = skip_dist.get("skip_delta_too_large", 0)
    delta_skip_fraction = delta_skip_count / total_skips if total_skips else 0.0

    # Derive the current configured delta from the autoresearch env (fallback 0.01).
    autoresearch_env_path = _REPO_ROOT / "state" / "btc5_autoresearch.env"
    current_delta: Optional[float] = None
    if autoresearch_env_path.exists():
        for line in autoresearch_env_path.read_text().splitlines():
            if line.startswith("BTC5_MAX_ABS_DELTA="):
                try:
                    current_delta = float(line.split("=", 1)[1].strip())
                except ValueError:
                    pass

    action_needed = delta_skip_fraction > _DELTA_SKIP_WARN_FRACTION

    recommendation: dict = {
        "generated_at": _now_iso(),
        "action": "none",
        "reason": "delta_skip_fraction_within_acceptable_range",
        "skip_distribution": skip_dist,
        "total_skips": total_skips,
        "delta_skip_count": delta_skip_count,
        "delta_skip_fraction": round(delta_skip_fraction, 4),
        "threshold_fraction": _DELTA_SKIP_WARN_FRACTION,
        "current_btc5_max_abs_delta": current_delta,
        "proposed_btc5_max_abs_delta": None,
        "manual_apply_command": None,
    }

    if action_needed and current_delta is not None:
        # Propose a 50 % widening, capped at 0.02.
        proposed = min(round(current_delta * 1.5, 5), 0.02)
        recommendation.update({
            "action": "widen_delta",
            "reason": (
                f"skip_delta_too_large accounts for {delta_skip_fraction:.0%} of "
                f"skips (threshold {_DELTA_SKIP_WARN_FRACTION:.0%}).  "
                "Current delta may be too tight for current BTC volatility."
            ),
            "proposed_btc5_max_abs_delta": proposed,
            "manual_apply_command": (
                f"Edit state/btc5_autoresearch.env: "
                f"BTC5_MAX_ABS_DELTA={proposed}"
            ),
        })
        logger.info(
            "volatility_scaling: recommend widening BTC5_MAX_ABS_DELTA "
            "%s -> %s (delta skips: %d/%d = %.0f%%)",
            current_delta, proposed, delta_skip_count, total_skips,
            delta_skip_fraction * 100,
        )
    elif action_needed:
        recommendation.update({
            "action": "widen_delta_manual",
            "reason": (
                f"skip_delta_too_large accounts for {delta_skip_fraction:.0%} of "
                "skips but current delta could not be read from env.  "
                "Manual review required."
            ),
        })
        logger.warning(
            "volatility_scaling: delta skips are high (%.0f%%) but current "
            "BTC5_MAX_ABS_DELTA could not be determined; manual review needed.",
            delta_skip_fraction * 100,
        )
    else:
        logger.info(
            "volatility_scaling: delta skip fraction %.0f%% is below threshold "
            "%.0f%% — no action required.",
            delta_skip_fraction * 100,
            _DELTA_SKIP_WARN_FRACTION * 100,
        )

    _write_json(out_path, recommendation)
    logger.info("volatility_scaling: wrote recommendation to %s", out_path)


def _execute_spread_impact_refresh() -> None:
    """Read BTC5 autoresearch probe state and log the current spread estimate.

    Writes: state/learning_loops/spread_impact.json
    """
    out_path = _STATE_DIR / "spread_impact.json"
    probe = _read_json(_PROBE_JSON)

    # Extract spread-relevant fields from the probe.
    active_profile = probe.get("active_profile", {})
    execution_drag = probe.get("execution_drag_summary", {})
    capital_stage = probe.get("capital_stage_recommendation", {})

    # Best-effort spread estimate: half the ask-bid spread implied by
    # the skip_price fraction (a proxy for market tightness).
    skip_rate = execution_drag.get("skip_rate", None)
    fill_retention_ratio = execution_drag.get(
        "best_live_fill_retention_ratio", None
    )

    # Gather recent fill prices from the BTC5 DB.
    avg_order_price: Optional[float] = None
    avg_spread_estimate: Optional[float] = None
    fill_count = 0
    if _BTC5_DB.exists():
        try:
            conn = sqlite3.connect(str(_BTC5_DB))
            row = conn.execute(
                "SELECT COUNT(*), AVG(order_price), AVG(best_ask - best_bid) "
                "FROM window_trades WHERE filled = 1"
            ).fetchone()
            conn.close()
            if row and row[0]:
                fill_count = row[0]
                avg_order_price = round(row[1], 4) if row[1] is not None else None
                avg_spread_estimate = (
                    round(row[2], 4) if row[2] is not None else None
                )
        except Exception as exc:
            logger.warning("spread_impact_refresh: DB query failed: %s", exc)

    result = {
        "generated_at": _now_iso(),
        "source": "btc5_autoresearch_probe + window_trades",
        "probe_generated_at": probe.get("generated_at"),
        "active_profile": active_profile,
        "skip_rate": skip_rate,
        "fill_retention_ratio": fill_retention_ratio,
        "live_fill_count": fill_count,
        "avg_order_price_filled": avg_order_price,
        "avg_bid_ask_spread_filled": avg_spread_estimate,
        "capital_stage": capital_stage.get("recommended_stage"),
        "deploy_recommendation": probe.get("deploy_recommendation"),
        "notes": (
            "avg_bid_ask_spread_filled is the mean (best_ask - best_bid) at "
            "order placement time across all filled windows.  "
            "A spread > 0.04 indicates thin books; consider reducing trade size."
        ),
    }

    _write_json(out_path, result)
    logger.info(
        "spread_impact_refresh: wrote to %s (fill_count=%d, "
        "avg_spread=%s, skip_rate=%s)",
        out_path, fill_count, avg_spread_estimate, skip_rate,
    )


def _execute_skip_threshold_adjust() -> None:
    """Read BTC5 skip distribution; recommend threshold changes.

    Writes: state/learning_loops/skip_threshold_recommendation.json
    """
    out_path = _STATE_DIR / "skip_threshold_recommendation.json"
    skip_dist = _query_btc5_skip_distribution()
    total_skips = sum(skip_dist.values())

    recommendations: list = []

    if total_skips == 0:
        result = {
            "generated_at": _now_iso(),
            "total_skips": 0,
            "skip_distribution": {},
            "recommendations": [],
            "summary": "No skip data available — DB may be empty or inaccessible.",
        }
        _write_json(out_path, result)
        logger.info("skip_threshold_adjust: no skip data found; wrote empty report.")
        return

    skip_fractions = {k: v / total_skips for k, v in skip_dist.items()}

    # --- delta too large -------------------------------------------------
    delta_frac = skip_fractions.get("skip_delta_too_large", 0.0)
    if delta_frac > _DELTA_SKIP_WARN_FRACTION:
        recommendations.append({
            "parameter": "BTC5_MAX_ABS_DELTA",
            "current_env_file": "state/btc5_autoresearch.env",
            "direction": "increase",
            "rationale": (
                f"{delta_frac:.0%} of skips are skip_delta_too_large "
                f"(threshold {_DELTA_SKIP_WARN_FRACTION:.0%}).  "
                "The delta filter is blocking too many opportunities."
            ),
            "suggested_change": "+50% of current value, max 0.02",
            "skip_count": skip_dist["skip_delta_too_large"],
            "skip_fraction": round(delta_frac, 4),
        })

    # --- delta too small -------------------------------------------------
    delta_small_frac = skip_fractions.get("skip_delta_too_small", 0.0)
    if delta_small_frac > 0.30:
        recommendations.append({
            "parameter": "BTC5_MAX_ABS_DELTA (lower bound)",
            "current_env_file": "state/btc5_autoresearch.env",
            "direction": "decrease",
            "rationale": (
                f"{delta_small_frac:.0%} of skips are skip_delta_too_small.  "
                "The minimum delta threshold may be too high; "
                "many calm periods are being suppressed."
            ),
            "suggested_change": "-20% of current minimum delta value",
            "skip_count": skip_dist["skip_delta_too_small"],
            "skip_fraction": round(delta_small_frac, 4),
        })

    # --- shadow-only / bad book -----------------------------------------
    shadow_frac = skip_fractions.get("skip_bad_book", 0.0)
    if shadow_frac > _SHADOW_SKIP_WARN_FRACTION:
        recommendations.append({
            "parameter": "BTC5_MIN_BOOK_DEPTH or trade size",
            "current_env_file": "config/btc5_strategy.env",
            "direction": "relax_or_reduce_size",
            "rationale": (
                f"{shadow_frac:.0%} of skips are skip_bad_book "
                f"(threshold {_SHADOW_SKIP_WARN_FRACTION:.0%}).  "
                "Book depth is insufficient for current sizing."
            ),
            "suggested_change": "Reduce BTC5_TRADE_SIZE_USD by 20% or relax book-depth gate",
            "skip_count": skip_dist["skip_bad_book"],
            "skip_fraction": round(shadow_frac, 4),
        })

    # --- probe confirmation mismatch ------------------------------------
    probe_frac = skip_fractions.get("skip_probe_confirmation_mismatch", 0.0)
    if probe_frac > 0.40:
        recommendations.append({
            "parameter": "probe_confirmation_gate",
            "current_env_file": "config/btc5_strategy.env",
            "direction": "review_probe_state",
            "rationale": (
                f"{probe_frac:.0%} of skips are probe confirmation mismatches.  "
                "The autoresearch probe may be in a stale or contradictory state.  "
                "Run a new autoresearch cycle or reset the probe."
            ),
            "suggested_change": "Run scripts/run_btc5_autoresearch_cycle.py",
            "skip_count": skip_dist["skip_probe_confirmation_mismatch"],
            "skip_fraction": round(probe_frac, 4),
        })

    # --- adaptive direction suppression ---------------------------------
    adapt_frac = skip_fractions.get("skip_adaptive_direction_suppressed", 0.0)
    if adapt_frac > 0.25:
        recommendations.append({
            "parameter": "BTC5_ADAPT_SUPPRESS_WR_THRESHOLD",
            "current_env_file": "config/btc5_strategy.env",
            "direction": "tighten_or_widen",
            "rationale": (
                f"{adapt_frac:.0%} of skips are adaptive direction suppression.  "
                "If this is intentional (poor recent WR), no action needed.  "
                "If win rate has recovered, lower the suppression threshold."
            ),
            "suggested_change": (
                "Review BTC5_ADAPT_SUPPRESS_WR_THRESHOLD and "
                "BTC5_ADAPT_SUPPRESS_WINDOW_FILLS"
            ),
            "skip_count": skip_dist["skip_adaptive_direction_suppressed"],
            "skip_fraction": round(adapt_frac, 4),
        })

    result = {
        "generated_at": _now_iso(),
        "total_skips": total_skips,
        "skip_distribution": skip_dist,
        "skip_fractions": {k: round(v, 4) for k, v in skip_fractions.items()},
        "recommendations": recommendations,
        "summary": (
            f"{len(recommendations)} threshold adjustment(s) recommended "
            f"from {total_skips} total skips across {len(skip_dist)} reason(s)."
        ),
    }

    _write_json(out_path, result)
    logger.info(
        "skip_threshold_adjust: wrote %d recommendation(s) to %s "
        "(total_skips=%d)",
        len(recommendations), out_path, total_skips,
    )


def _execute_risk_limit_update() -> None:
    """Compare current wallet exposure to the initial bankroll.

    Reads wallet data from jj_trades.db (open + closed positions).
    Writes: state/learning_loops/risk_limit_status.json
    """
    out_path = _STATE_DIR / "risk_limit_status.json"

    open_count = 0
    open_cost_basis_usd = 0.0
    open_current_value_usd = 0.0
    closed_count = 0
    closed_realized_pnl_usd = 0.0
    checked_at: Optional[str] = None

    if _JJ_TRADES_DB.exists():
        try:
            conn = sqlite3.connect(str(_JJ_TRADES_DB))

            # Open positions: cost basis = avg_price * size.
            row = conn.execute(
                "SELECT COUNT(*), SUM(avg_price * size), SUM(current_value) "
                "FROM wallet_open_positions"
            ).fetchone()
            if row and row[0]:
                open_count = row[0]
                open_cost_basis_usd = round(row[1] or 0.0, 2)
                open_current_value_usd = round(row[2] or 0.0, 2)

            # Closed positions: realized P&L from reconciliation runs.
            row2 = conn.execute(
                "SELECT COUNT(*), SUM(realized_pnl) FROM wallet_closed_positions"
            ).fetchone()
            if row2 and row2[0]:
                closed_count = row2[0]
                closed_realized_pnl_usd = round(row2[1] or 0.0, 2)

            # Most recent reconciliation run timestamp.
            row3 = conn.execute(
                "SELECT checked_at FROM wallet_reconciliation_runs "
                "ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
            if row3:
                checked_at = row3[0]

            conn.close()
        except Exception as exc:
            logger.warning("risk_limit_update: DB query failed: %s", exc)

    # Exposure is how much capital is currently locked in open positions
    # relative to the initial bankroll.
    exposure_usd = open_cost_basis_usd
    exposure_pct = (
        exposure_usd / _INITIAL_BANKROLL_USD if _INITIAL_BANKROLL_USD > 0 else 0.0
    )

    if exposure_pct >= _EXPOSURE_CRIT_PCT:
        status = "CRITICAL"
        action = "reduce_open_positions_immediately"
    elif exposure_pct >= _EXPOSURE_WARN_PCT:
        status = "WARNING"
        action = "review_open_positions_before_new_trades"
    else:
        status = "OK"
        action = "none"

    unrealized_pnl_usd = round(open_current_value_usd - open_cost_basis_usd, 2)
    net_pnl_usd = round(closed_realized_pnl_usd + unrealized_pnl_usd, 2)

    result = {
        "generated_at": _now_iso(),
        "wallet_data_as_of": checked_at,
        "initial_bankroll_usd": _INITIAL_BANKROLL_USD,
        "open_positions": {
            "count": open_count,
            "cost_basis_usd": open_cost_basis_usd,
            "current_value_usd": open_current_value_usd,
            "unrealized_pnl_usd": unrealized_pnl_usd,
        },
        "closed_positions": {
            "count": closed_count,
            "realized_pnl_usd": closed_realized_pnl_usd,
        },
        "exposure_usd": exposure_usd,
        "exposure_pct": round(exposure_pct, 4),
        "net_pnl_usd": net_pnl_usd,
        "status": status,
        "action": action,
        "thresholds": {
            "warn_pct": _EXPOSURE_WARN_PCT,
            "critical_pct": _EXPOSURE_CRIT_PCT,
        },
        "notes": (
            "exposure_usd is the cost basis of open positions.  "
            "status=CRITICAL means >80% of the initial bankroll is locked in "
            "open positions; halt new trades until some resolve."
        ),
    }

    _write_json(out_path, result)
    logger.info(
        "risk_limit_update: wrote to %s (status=%s, exposure=%.0f%%, "
        "open=%d, net_pnl=%.2f)",
        out_path, status, exposure_pct * 100, open_count, net_pnl_usd,
    )


# ---------------------------------------------------------------------------
# Medium-loop execute function.
# ---------------------------------------------------------------------------

def _execute_btc5_param_integration() -> None:
    """Consolidate all recommendation files into a single integration report.

    Reads:
      - state/learning_loops/volatility_scaling_recommendation.json
      - state/learning_loops/spread_impact.json
      - state/learning_loops/skip_threshold_recommendation.json
      - state/learning_loops/risk_limit_status.json
    Writes:
      - state/learning_loops/btc5_param_integration_report.json
    """
    out_path = _STATE_DIR / "btc5_param_integration_report.json"

    volatility = _read_json(_STATE_DIR / "volatility_scaling_recommendation.json")
    spread = _read_json(_STATE_DIR / "spread_impact.json")
    skip_thresh = _read_json(_STATE_DIR / "skip_threshold_recommendation.json")
    risk = _read_json(_STATE_DIR / "risk_limit_status.json")

    # Derive a composite readiness assessment.
    risk_status = risk.get("status", "UNKNOWN")
    skip_recs = skip_thresh.get("recommendations", [])
    vol_action = volatility.get("action", "none")
    deploy_rec = spread.get("deploy_recommendation", "unknown")

    # Collect all parameter changes suggested across the recommendation files.
    param_changes: list = []

    if vol_action not in ("none", ""):
        param_changes.append({
            "source": "volatility_scaling",
            "action": vol_action,
            "parameter": "BTC5_MAX_ABS_DELTA",
            "proposed_value": volatility.get("proposed_btc5_max_abs_delta"),
            "manual_apply_command": volatility.get("manual_apply_command"),
            "priority": "HIGH" if vol_action == "widen_delta" else "MEDIUM",
        })

    for rec in skip_recs:
        param_changes.append({
            "source": "skip_threshold_adjust",
            "action": rec.get("direction"),
            "parameter": rec.get("parameter"),
            "env_file": rec.get("current_env_file"),
            "suggested_change": rec.get("suggested_change"),
            "rationale": rec.get("rationale"),
            "priority": "HIGH" if rec.get("skip_fraction", 0) > 0.50 else "MEDIUM",
        })

    # Gate: do not recommend param changes if risk status is CRITICAL.
    if risk_status == "CRITICAL":
        gate_status = "BLOCKED"
        gate_reason = (
            "risk_limit_status is CRITICAL — open position exposure exceeds "
            f"{int(_EXPOSURE_CRIT_PCT * 100)}% of initial bankroll.  "
            "Resolve open positions before applying any parameter changes."
        )
    elif deploy_rec not in ("none", "hold", "unknown", ""):
        gate_status = "READY"
        gate_reason = (
            f"deploy_recommendation={deploy_rec!r}.  "
            "Parameter changes may be applied after manual review."
        )
    else:
        gate_status = "HOLD"
        gate_reason = (
            f"deploy_recommendation={deploy_rec!r} and risk_status={risk_status!r}.  "
            "No parameter changes recommended at this time."
        )

    # Summary of what each sub-report found.
    sub_report_summaries = {
        "volatility_scaling": {
            "action": vol_action,
            "delta_skip_fraction": volatility.get("delta_skip_fraction"),
            "proposed_delta": volatility.get("proposed_btc5_max_abs_delta"),
            "as_of": volatility.get("generated_at"),
        },
        "spread_impact": {
            "fill_count": spread.get("live_fill_count"),
            "avg_order_price": spread.get("avg_order_price_filled"),
            "avg_spread": spread.get("avg_bid_ask_spread_filled"),
            "skip_rate": spread.get("skip_rate"),
            "as_of": spread.get("generated_at"),
        },
        "skip_threshold": {
            "total_skips": skip_thresh.get("total_skips"),
            "recommendation_count": len(skip_recs),
            "summary": skip_thresh.get("summary"),
            "as_of": skip_thresh.get("generated_at"),
        },
        "risk_limit": {
            "status": risk_status,
            "exposure_pct": risk.get("exposure_pct"),
            "net_pnl_usd": risk.get("net_pnl_usd"),
            "open_count": risk.get("open_positions", {}).get("count"),
            "as_of": risk.get("generated_at"),
        },
    }

    report = {
        "generated_at": _now_iso(),
        "gate_status": gate_status,
        "gate_reason": gate_reason,
        "param_changes_recommended": param_changes,
        "sub_reports": sub_report_summaries,
        "next_steps": _derive_next_steps(
            gate_status, param_changes, risk_status, deploy_rec
        ),
    }

    _write_json(out_path, report)
    logger.info(
        "btc5_param_integration: wrote report to %s "
        "(gate=%s, %d param change(s))",
        out_path, gate_status, len(param_changes),
    )


def _derive_next_steps(
    gate_status: str,
    param_changes: list,
    risk_status: str,
    deploy_rec: str,
) -> list:
    """Return a prioritised list of human-readable next-step strings."""
    steps = []
    if risk_status == "CRITICAL":
        steps.append(
            "URGENT: Reduce open positions — exposure exceeds 80% of bankroll."
        )
    if gate_status == "READY" and param_changes:
        steps.append(
            f"Review {len(param_changes)} parameter change recommendation(s) "
            "in param_changes_recommended and apply manually after validation."
        )
    elif gate_status == "HOLD":
        steps.append(
            "Hold all parameter changes until deploy_recommendation != 'hold' "
            "or risk_status == 'OK'."
        )
    if not param_changes:
        steps.append(
            "No parameter changes needed — run fast-loop actions first to "
            "generate sub-report data."
        )
    steps.append(
        "Re-run btc5_param_integration after the next fast-loop cycle to "
        "refresh the consolidated view."
    )
    return steps


class LoopSpeed(Enum):
    FAST = "fast"      # daily/intraday
    MEDIUM = "medium"  # weekly
    SLOW = "slow"      # monthly, requires full validation


@dataclass
class LoopAction:
    """A single action that can be executed within a learning loop."""
    name: str
    speed: LoopSpeed
    description: str
    execute: Optional[Callable] = None
    last_run: str = ""
    last_result: str = ""
    enabled: bool = True
    requires_approval: bool = False  # Slow loop requires human approval


@dataclass
class LoopResult:
    """Result of executing a loop action, with rollback support."""
    action_name: str
    speed: str
    success: bool
    timestamp: str
    changes_made: List[str] = field(default_factory=list)
    metrics_before: Dict = field(default_factory=dict)
    metrics_after: Dict = field(default_factory=dict)
    rollback_data: str = ""  # JSON snapshot for rollback
    notes: str = ""


class LearningLoopManager:
    """
    Manages three learning speeds for continuous self-improvement.

    Fast loop: Safe, reversible recalibrations (daily)
    Medium loop: Controlled model refresh (weekly)
    Slow loop: Architecture changes requiring full validation (manual)

    Key principle: Slow-loop changes go back through the full validation stack.
    Never allow 'self-improvement' to mean 'the model can silently redesign production.'
    """

    # Intervals between runs for each speed tier
    INTERVALS = {
        LoopSpeed.FAST: timedelta(hours=24),
        LoopSpeed.MEDIUM: timedelta(days=7),
        LoopSpeed.SLOW: timedelta(days=30),
    }

    def __init__(self, state_dir: str = "state/learning_loops"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.state_dir / "loop_history.db")
        self._init_db()
        self.actions: Dict[str, LoopAction] = {}
        self._register_default_actions()

    def _init_db(self):
        """Initialize SQLite database for loop run history."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS loop_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_name TEXT NOT NULL,
                speed TEXT NOT NULL,
                success INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                changes_json TEXT DEFAULT '[]',
                metrics_before_json TEXT DEFAULT '{}',
                metrics_after_json TEXT DEFAULT '{}',
                rollback_data TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_loop_action ON loop_runs(action_name);
            CREATE INDEX IF NOT EXISTS idx_loop_time ON loop_runs(timestamp);
        """)
        conn.commit()
        conn.close()

    def _register_default_actions(self):
        """Register the standard set of loop actions across all three speeds."""
        # --- Fast loop actions ---
        self.register_action(LoopAction(
            name="volatility_scaling",
            speed=LoopSpeed.FAST,
            description="Update volatility estimates from recent market data",
            execute=_execute_volatility_scaling,
        ))
        self.register_action(LoopAction(
            name="spread_impact_refresh",
            speed=LoopSpeed.FAST,
            description="Recalculate spread and market impact from recent fills",
            execute=_execute_spread_impact_refresh,
        ))
        self.register_action(LoopAction(
            name="skip_threshold_adjust",
            speed=LoopSpeed.FAST,
            description="Auto-adjust skip thresholds based on recent fill rate",
            execute=_execute_skip_threshold_adjust,
        ))
        self.register_action(LoopAction(
            name="risk_limit_update",
            speed=LoopSpeed.FAST,
            description="Adjust risk limits based on current liquidity state",
            execute=_execute_risk_limit_update,
        ))

        # --- Medium loop actions ---
        self.register_action(LoopAction(
            name="platt_recalibration",
            speed=LoopSpeed.MEDIUM,
            description="Recalibrate Platt scaling coefficients A/B",
        ))
        self.register_action(LoopAction(
            name="regime_classifier_refresh",
            speed=LoopSpeed.MEDIUM,
            description="Refresh regime detection parameters",
        ))
        self.register_action(LoopAction(
            name="btc5_param_integration",
            speed=LoopSpeed.MEDIUM,
            description="Integrate BTC5 autoresearch findings into main config",
            execute=_execute_btc5_param_integration,
        ))
        self.register_action(LoopAction(
            name="kill_propagation_sweep",
            speed=LoopSpeed.MEDIUM,
            description="Check if any strategy should be killed based on new data",
        ))
        self.register_action(LoopAction(
            name="negative_results_update",
            speed=LoopSpeed.MEDIUM,
            description="Update negative results library with recent failures",
        ))

        # --- Slow loop actions (require approval) ---
        self.register_action(LoopAction(
            name="new_feature_family",
            speed=LoopSpeed.SLOW,
            description="Add new feature family to signal generation",
            requires_approval=True,
        ))
        self.register_action(LoopAction(
            name="new_model_class",
            speed=LoopSpeed.SLOW,
            description="Introduce new model architecture",
            requires_approval=True,
        ))
        self.register_action(LoopAction(
            name="new_market_universe",
            speed=LoopSpeed.SLOW,
            description="Expand to new market or venue",
            requires_approval=True,
        ))

    def register_action(self, action: LoopAction):
        """Register a loop action. Overwrites if name already exists."""
        self.actions[action.name] = action

    def get_due_actions(self, speed: LoopSpeed) -> List[LoopAction]:
        """Get actions that are due to run based on their speed and last run time."""
        interval = self.INTERVALS[speed]
        now = datetime.now(timezone.utc)
        due = []

        for action in self.actions.values():
            if action.speed != speed or not action.enabled:
                continue
            if not action.last_run:
                due.append(action)
                continue
            last = datetime.fromisoformat(action.last_run)
            if now - last >= interval:
                due.append(action)

        return due

    def record_run(self, result: LoopResult):
        """Record a loop execution result to the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO loop_runs (action_name, speed, success, timestamp,
                    changes_json, metrics_before_json, metrics_after_json,
                    rollback_data, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.action_name, result.speed, int(result.success),
                result.timestamp, json.dumps(result.changes_made),
                json.dumps(result.metrics_before), json.dumps(result.metrics_after),
                result.rollback_data, result.notes,
            ))
            conn.commit()

            # Update last_run on the action
            if result.action_name in self.actions:
                self.actions[result.action_name].last_run = result.timestamp
                self.actions[result.action_name].last_result = (
                    "success" if result.success else "failed"
                )

            logger.info(
                "Loop run recorded: %s (%s) -> %s",
                result.action_name, result.speed,
                "OK" if result.success else "FAIL",
            )
        finally:
            conn.close()

    def get_run_history(
        self, action_name: Optional[str] = None, limit: int = 50
    ) -> list:
        """Get recent loop run history, optionally filtered by action name."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if action_name:
                rows = conn.execute(
                    "SELECT * FROM loop_runs WHERE action_name = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (action_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM loop_runs ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _run_loop(self, speed: LoopSpeed) -> List[LoopResult]:
        """Execute all due actions for a given speed tier."""
        due = self.get_due_actions(speed)
        results = []
        for action in due:
            logger.info("Running %s-loop action: %s", speed.value, action.name)
            result = LoopResult(
                action_name=action.name,
                speed=speed.value,
                success=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
                notes=f"Executed: {action.description}",
            )
            if action.execute:
                try:
                    action.execute()
                except Exception as e:
                    result.success = False
                    result.notes = f"Failed: {e}"
                    logger.error(
                        "%s-loop action %s failed: %s", speed.value, action.name, e
                    )
            self.record_run(result)
            results.append(result)
        return results

    def run_fast_loop(self) -> List[LoopResult]:
        """Execute all due fast-loop actions. Safe to run daily."""
        return self._run_loop(LoopSpeed.FAST)

    def run_medium_loop(self) -> List[LoopResult]:
        """Execute all due medium-loop actions. Safe to run weekly."""
        return self._run_loop(LoopSpeed.MEDIUM)

    def check_slow_loop_candidates(self) -> List[LoopAction]:
        """Return slow-loop actions that are due. These require human approval."""
        return [a for a in self.get_due_actions(LoopSpeed.SLOW) if a.requires_approval]
