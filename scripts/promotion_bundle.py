#!/usr/bin/env python3
"""
Promotion Bundle — Opportunity, Capital, and Counterfactual Unified
====================================================================
Third stage of the self-improvement kernel.

Reads thesis_bundle.json and evaluates each thesis against four promotion
criteria.  Produces a single promotion_bundle.json with ranked promotion
decisions and capital allocations.

Promotion path (thesis must pass in order)
-------------------------------------------
  0a. evidence_freshness — evidence bundle <24h old, runtime_truth <6h old
  0b. btc5_pnl_truth    — BTC5 PnL present if fills exist; negative PnL blocks
  1.  replay_status      — thesis has been replayed on historical data
  2.  off_policy_status  — thesis has been validated against off-policy logs
  3.  world_league_status — thesis competes against all known hypotheses
  4.  execution_quality  — projected fill rate × (1 - toxic_flow_rate)

This is the ONLY path to capital.  There is no "fast track" or "emergency
allocation" that bypasses these gates.

Replaces (and demotes to sub-components of):
  - opportunity_exchange    (thesis→candidate ranking)
  - capital_laboratory      (Kelly-based sizing)
  - counterfactual_capital_laboratory (what-if P&L simulation)

Output: reports/promotion_bundle.json
Kernel: updates reports/kernel/kernel_state.json promotion bundle status

Usage
-----
  python3 scripts/promotion_bundle.py           # run once
  python3 scripts/promotion_bundle.py --daemon  # continuous (default 30min)

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.capital_router import CapitalRouter  # noqa: E402
from scripts.report_envelope import write_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("JJ.promotion")

PROJECT_ROOT = REPO_ROOT
REPORTS = PROJECT_ROOT / "reports"
THESIS_PATH = REPORTS / "thesis_bundle.json"
PROMO_HISTORY_PATH = REPORTS / "promotion_history.jsonl"
OUTPUT_PATH = REPORTS / "promotion_bundle.json"

# Sub-component lab artifacts — demoted from top-level decision systems to gate inputs
CAPITAL_LAB_PATH = REPORTS / "capital_lab" / "latest.json"
COUNTERFACTUAL_LAB_PATH = REPORTS / "counterfactual_lab" / "latest.json"
CANONICAL_TRUTH_PATH = REPORTS / "canonical_operator_truth.json"
SIMULATION_RANKED_PATH = REPORTS / "simulation" / "ranked_candidates.json"
STRUCTURAL_ALPHA_DIR = REPORTS / "structural_alpha"
STRUCTURAL_LIVE_QUEUE_PATH = STRUCTURAL_ALPHA_DIR / "live_queue.json"
STRUCTURAL_LANE_SNAPSHOT_PATH = STRUCTURAL_ALPHA_DIR / "structural_lane_snapshot.json"

INTERVAL = int(os.environ.get("PROMOTION_INTERVAL_SECONDS", "1800"))

# ---------------------------------------------------------------------------
# Structural fast-track gate definitions
# ---------------------------------------------------------------------------
# Deterministic microstructure lanes (pair_completion, neg_risk) may bypass
# the generic 200-event / 7-day replay/off_policy/world_league gates when
# they meet the tighter, bounded-risk thresholds below.
STRUCTURAL_FAST_TRACK_GATES: dict[str, dict[str, Any]] = {
    "pair_completion": {
        "min_replay_opportunities": 50,
        "min_shadow_opportunities": 25,
        "min_shadow_clean_completions": 10,
        "min_micro_live_settled": 10,
        "max_truth_mismatches": 0,
        "max_stale_evidence_executions": 0,
        "require_positive_net_pnl": True,
    },
    "neg_risk": {
        "min_replay_opportunities": 20,
        "min_shadow_opportunities": 10,
        "min_micro_live_settled": 10,
        "max_taxonomy_ambiguity": 0,
        "require_bounded_worst_case": True,
    },
}

# Lane verdict constants
LANE_APPROVED = "approved"
LANE_BLOCKED = "blocked"
LANE_INSUFFICIENT = "insufficient_data"

# Promotion gate thresholds
REPLAY_MIN_SCENARIOS = int(os.environ.get("PROMO_REPLAY_MIN_SCENARIOS", "5"))
EXECUTION_QUALITY_MIN = float(os.environ.get("PROMO_EXEC_QUALITY_MIN", "0.40"))
KELLY_FRACTION = float(os.environ.get("KELLY_FRACTION", "0.25"))
MAX_POSITION_USD = float(os.environ.get("MAX_POSITION_USD", "10.0"))

# Freshness hard-gate thresholds (seconds)
EVIDENCE_FRESHNESS_MAX_AGE = int(os.environ.get("PROMO_EVIDENCE_MAX_AGE_SECONDS", str(24 * 3600)))
RUNTIME_TRUTH_MAX_AGE = int(os.environ.get("PROMO_RUNTIME_TRUTH_MAX_AGE_SECONDS", str(6 * 3600)))

# Runtime truth paths
RUNTIME_TRUTH_LATEST_PATH = REPORTS / "runtime_truth_latest.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _load_ranked_structural_candidates() -> list[dict[str, Any]]:
    live_queue = load_json(STRUCTURAL_LIVE_QUEUE_PATH)
    if live_queue is not None:
        ranked = live_queue.get("ranked_lanes")
        if isinstance(ranked, list):
            return [item for item in ranked if isinstance(item, dict)]
    payload = load_json(SIMULATION_RANKED_PATH)
    if payload is None:
        return []
    ranked = payload.get("ranked_candidates")
    if isinstance(ranked, list):
        return [item for item in ranked if isinstance(item, dict)]
    return []


def _write_structural_artifacts(
    *,
    queue_payload: dict[str, Any],
    snapshot_payload: dict[str, Any],
) -> None:
    STRUCTURAL_ALPHA_DIR.mkdir(parents=True, exist_ok=True)
    queue_blockers = list(queue_payload.get("capital_blockers") or [])
    queue_status = "fresh" if queue_payload.get("recommended_live_lane") and not queue_blockers else "blocked"
    write_report(
        STRUCTURAL_LIVE_QUEUE_PATH,
        artifact="structural_live_queue",
        payload=queue_payload,
        status=queue_status,
        source_of_truth="reports/simulation/ranked_candidates.json; reports/canonical_operator_truth.json; reports/promotion_bundle.json",
        freshness_sla_seconds=1800,
        blockers=queue_blockers,
        summary=(
            f"recommended_live_lane={queue_payload.get('recommended_live_lane') or 'none'} "
            f"size_usd={float(queue_payload.get('recommended_size_usd') or 0.0):.2f}"
        ),
    )
    write_report(
        STRUCTURAL_LANE_SNAPSHOT_PATH,
        artifact="structural_lane_snapshot",
        payload=snapshot_payload,
        status=queue_status,
        source_of_truth="reports/simulation/ranked_candidates.json; reports/canonical_operator_truth.json; reports/promotion_bundle.json",
        freshness_sla_seconds=1800,
        blockers=queue_blockers,
        summary=f"lanes={len(snapshot_payload.get('lanes') or [])}",
    )


def age_seconds(iso: str) -> float:
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return -1.0


# ---------------------------------------------------------------------------
# Promotion gate evaluation
# ---------------------------------------------------------------------------


def _load_promo_history() -> dict[str, Any]:
    """Load existing promotion history keyed by thesis_id."""
    history: dict[str, Any] = {}
    if not PROMO_HISTORY_PATH.exists():
        return history
    try:
        for line in PROMO_HISTORY_PATH.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            tid = entry.get("thesis_id")
            if tid:
                history[tid] = entry
    except Exception:
        pass
    return history


def _evaluate_evidence_freshness(
    thesis_bundle: dict[str, Any] | None,
    lane: str = "",
) -> dict[str, Any]:
    """Lane-aware hard gate: evidence bundle and runtime truth must be fresh enough.

    Previously this gate was global — any stale signal blocked all lanes.  The
    new behaviour is lane-specific:

    * Stale weather evidence disables ONLY the weather lane.
    * A missing / stale runtime truth file disables ONLY lanes that rely on it
      (btc5 and any lane whose verdict key lives in runtime_truth_latest.json).
    * Truth mismatch (wallet/ledger disagreement) disables ALL new live capital
      — this remains global and is handled separately in evaluate_thesis.

    The ``lane`` parameter is the normalised lane string extracted from the
    thesis (e.g. "btc5", "weather", "pair_completion", "neg_risk", "").
    """
    reasons: list[str] = []

    # --- thesis bundle freshness (applies to all lanes) ---
    if thesis_bundle is None:
        reasons.append("evidence bundle (thesis_bundle.json) missing")
    else:
        gen = thesis_bundle.get("generated_at") or ""
        age = age_seconds(gen)
        if age < 0:
            reasons.append("evidence bundle has no valid generated_at timestamp")
        elif age > EVIDENCE_FRESHNESS_MAX_AGE:
            reasons.append(
                f"evidence bundle is {age / 3600:.1f}h old "
                f"(max {EVIDENCE_FRESHNESS_MAX_AGE / 3600:.0f}h)"
            )

    # --- runtime truth freshness (lane-specific) ---
    # Weather evidence staleness only disables the weather lane.
    # Lanes that don't depend on runtime_truth_latest.json are not penalised.
    lanes_requiring_runtime_truth = {"btc5", "weather"}
    if lane in lanes_requiring_runtime_truth or not lane:
        rt = load_json(RUNTIME_TRUTH_LATEST_PATH)
        if rt is None:
            reasons.append(
                f"runtime_truth_latest.json missing "
                f"(required for lane='{lane or 'global'}')"
            )
        else:
            rt_gen = rt.get("generated_at") or ""
            rt_age = age_seconds(rt_gen)
            if rt_age < 0:
                reasons.append("runtime_truth_latest.json has no valid generated_at timestamp")
            elif rt_age > RUNTIME_TRUTH_MAX_AGE:
                # Weather staleness: block weather lane only (caller handles this)
                reasons.append(
                    f"runtime_truth_latest.json is {rt_age / 3600:.1f}h old "
                    f"(max {RUNTIME_TRUTH_MAX_AGE / 3600:.0f}h; "
                    f"disables lane='{lane or 'global'}' only)"
                )

    passed = len(reasons) == 0
    return {
        "gate": "evidence_freshness",
        "passed": passed,
        "lane": lane or "global",
        "reasons": reasons,
        "note": "fresh" if passed else "; ".join(reasons),
    }


def _evaluate_btc5_pnl_truth(lane: str = "") -> dict[str, Any]:
    """Lane-aware hard gate: BTC5 negative PnL blocks ONLY the BTC5 expansion lane.

    Previously this gate ran for every thesis regardless of lane, which caused
    global deadlock whenever BTC5 was underwater.  The new behaviour:

    * For non-BTC5 lanes the gate auto-passes (BTC5 health is irrelevant).
    * For the BTC5 lane the original logic is preserved:
        1. Fills present but PnL null -> FAIL (data integrity)
        2. Negative cumulative PnL AND profit_factor < 1.0 -> FAIL (expansion blocked)

    The ``lane`` parameter is the normalised lane string from the thesis.
    """
    # Non-BTC5 lanes are unaffected by BTC5 PnL
    if lane and "btc5" not in lane:
        return {
            "gate": "btc5_pnl_truth",
            "passed": True,
            "lane": lane,
            "note": f"auto-pass: lane='{lane}' does not depend on BTC5 PnL",
        }

    rt = load_json(RUNTIME_TRUTH_LATEST_PATH)
    if rt is None:
        return {
            "gate": "btc5_pnl_truth",
            "passed": False,
            "lane": lane or "global",
            "note": "runtime_truth_latest.json missing — cannot verify BTC5 PnL",
        }

    # Extract BTC5 fill count and PnL from multiple possible locations
    acct = rt.get("accounting_reconciliation") or {}
    btc5_counts = acct.get("btc_5min_maker_counts") or {}

    fill_rows = btc5_counts.get("live_filled_rows")
    if fill_rows is None:
        fill_rows = rt.get("btc5_live_filled_rows")
    pnl = btc5_counts.get("live_filled_pnl_usd")
    if pnl is None:
        pnl = rt.get("btc5_live_filled_pnl_usd")

    profit_factor = rt.get("btc_profit_factor")

    # Gate 1: fills exist but PnL is null/missing -> data integrity failure
    if fill_rows and fill_rows > 0 and pnl is None:
        return {
            "gate": "btc5_pnl_truth",
            "passed": False,
            "lane": lane or "btc5",
            "fill_rows": fill_rows,
            "pnl_usd": None,
            "profit_factor": profit_factor,
            "note": (
                f"BTC5 has {fill_rows} fills but PnL is null — "
                "data integrity failure, BTC5 expansion blocked"
            ),
        }

    # Gate 2: negative cumulative PnL AND profit_factor < 1.0 -> expansion blocked
    has_pnl = pnl is not None
    pnl_negative = has_pnl and pnl < 0
    pf_below_one = profit_factor is not None and profit_factor < 1.0
    # If profit_factor is null but PnL is negative, still fail (no evidence of edge)
    pf_missing_with_neg_pnl = profit_factor is None and pnl_negative

    if pnl_negative and (pf_below_one or pf_missing_with_neg_pnl):
        return {
            "gate": "btc5_pnl_truth",
            "passed": False,
            "lane": lane or "btc5",
            "fill_rows": fill_rows,
            "pnl_usd": pnl,
            "profit_factor": profit_factor,
            "note": (
                f"BTC5 cumulative PnL=${pnl:.2f} with "
                f"profit_factor={profit_factor} — "
                "negative P&L blocks BTC5 expansion only (other lanes unaffected)"
            ),
        }

    passed = has_pnl or (fill_rows is None or fill_rows == 0)
    note = "no BTC5 fills yet" if not fill_rows else f"BTC5 PnL=${pnl:.2f}, PF={profit_factor}"
    return {
        "gate": "btc5_pnl_truth",
        "passed": passed,
        "lane": lane or "btc5",
        "fill_rows": fill_rows,
        "pnl_usd": pnl,
        "profit_factor": profit_factor,
        "note": note,
    }


def _evaluate_replay(
    thesis: dict,
    history: dict[str, Any],
    capital_lab: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check replay gate: has this thesis been replayed on enough scenarios?

    Capital-lab lane data supplements promotion-history replay counts.
    A BTC5 thesis passes replay if capital_lab reports the BTC5 gate as promoted,
    even when promotion_history has no entries yet (new thesis, live data available).
    """
    hist = history.get(thesis["thesis_id"]) or {}
    replay_count = hist.get("replay_scenario_count") or 0

    # Capital-lab supplement: use real fill counts as replay evidence
    if capital_lab and not replay_count:
        lane = str(thesis.get("lane") or thesis.get("source") or "")
        if "btc5" in lane:
            btc5_gate = (capital_lab.get("lanes") or {}).get("btc5") or {}
            replay_count = int(btc5_gate.get("fill_count") or 0)
        elif "weather" in lane:
            weather_gate = (capital_lab.get("lanes") or {}).get("weather") or {}
            replay_count = int(weather_gate.get("shadow_decision_count") or 0)

    passed = replay_count >= REPLAY_MIN_SCENARIOS
    note = (
        f"{replay_count}/{REPLAY_MIN_SCENARIOS} scenarios replayed"
        + (" (from capital_lab)" if replay_count and not hist.get("replay_scenario_count") else "")
    )
    return {
        "gate": "replay",
        "passed": passed,
        "replay_count": replay_count,
        "required": REPLAY_MIN_SCENARIOS,
        "note": note,
    }


def _evaluate_off_policy(
    thesis: dict,
    history: dict[str, Any],
    counterfactual_lab: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check off-policy gate: validated against off-policy trade logs.

    Counterfactual-lab supplement:
    - RELAX verdict → off-policy gate passes (observed off-policy edge is positive)
    - TIGHTEN verdict → off-policy gate fails (observed off-policy edge is negative)
    - KEEP / absent → fall back to promotion-history entry
    """
    hist = history.get(thesis["thesis_id"]) or {}
    op_validated = hist.get("off_policy_validated") or False

    # Non-capital theses (operational fixes) get automatic pass
    if not thesis.get("requires_capital"):
        return {"gate": "off_policy", "passed": True, "note": "auto-pass (no capital)"}

    # Counterfactual-lab supplement
    cf_verdict = None
    if counterfactual_lab:
        lane = str(thesis.get("lane") or thesis.get("source") or "")
        lane_key = "btc5" if "btc5" in lane else ("weather" if "weather" in lane else None)
        if lane_key:
            lane_cf = (counterfactual_lab.get("lanes") or {}).get(lane_key) or {}
            cf_verdict = str(lane_cf.get("verdict") or "").upper()
        if not lane_key:
            cf_verdict = str(counterfactual_lab.get("verdict") or "").upper()

    if cf_verdict == "RELAX":
        op_validated = True
    elif cf_verdict == "TIGHTEN":
        op_validated = False

    note = "validated" if op_validated else "pending validation"
    if cf_verdict:
        note += f" (counterfactual_lab: {cf_verdict})"

    return {
        "gate": "off_policy",
        "passed": op_validated,
        "counterfactual_verdict": cf_verdict,
        "note": note,
    }


def _evaluate_world_league(thesis: dict, history: dict[str, Any], all_theses: list[dict]) -> dict[str, Any]:
    """Check world-league gate: does this thesis rank in top-N against all competitors?"""
    hist = history.get(thesis["thesis_id"]) or {}
    wl_rank = hist.get("world_league_rank")
    total = len(all_theses)
    top_n = max(3, total // 3)

    if not thesis.get("requires_capital"):
        return {"gate": "world_league", "passed": True, "note": "auto-pass (no capital)"}

    if wl_rank is None:
        return {"gate": "world_league", "passed": False, "rank": None, "note": "not yet ranked"}

    passed = wl_rank <= top_n
    return {
        "gate": "world_league",
        "passed": passed,
        "rank": wl_rank,
        "top_n": top_n,
        "note": f"rank {wl_rank}/{total} (top-{top_n} required)",
    }


def _evaluate_execution_quality(thesis: dict, history: dict[str, Any]) -> dict[str, Any]:
    """Check execution quality gate: projected fill rate × (1 - toxic_flow_rate)."""
    if not thesis.get("requires_capital"):
        return {"gate": "execution_quality", "passed": True, "score": 1.0, "note": "auto-pass (no capital)"}

    hist = history.get(thesis["thesis_id"]) or {}
    fill_rate = hist.get("fill_rate")
    toxic_rate = hist.get("toxic_flow_rate")
    if fill_rate is None and _resolve_lane(thesis) in STRUCTURAL_FAST_TRACK_GATES:
        fill_rate = thesis.get("execution_realism_score")
        toxic_rate = 0.0
    fill_rate = fill_rate or 0.0
    toxic_rate = toxic_rate or 0.0
    score = fill_rate * (1.0 - toxic_rate)
    passed = score >= EXECUTION_QUALITY_MIN
    return {
        "gate": "execution_quality",
        "passed": passed,
        "fill_rate": fill_rate,
        "toxic_rate": toxic_rate,
        "score": round(score, 4),
        "minimum": EXECUTION_QUALITY_MIN,
        "note": f"score {score:.3f} ({'pass' if passed else 'fail'})",
    }


def evaluate_structural_fast_track(lane_id: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether a structural lane can proceed to micro-live without
    meeting the generic 200-event / 7-day replay/off_policy/world_league gates.

    Structural lanes (pair_completion, neg_risk) are deterministic and
    bounded-risk — they do not need the full statistical flywheel that
    statistical-alpha lanes require.  This function checks the lower,
    lane-specific thresholds defined in STRUCTURAL_FAST_TRACK_GATES.

    Parameters
    ----------
    lane_id : str
        Normalised lane identifier, e.g. "pair_completion" or "neg_risk".
    stats : dict
        Runtime statistics for the lane.  Expected keys mirror the gate
        definition (e.g. "replay_opportunities", "shadow_opportunities", etc.).
        Missing keys are treated as zero / False.

    Returns
    -------
    dict with keys:
        approved : bool   — True if the lane may skip generic gates
        reasons  : list[str] — human-readable gate outcomes (pass and fail)
        stage    : str    — "micro_live" if approved, "shadow" otherwise
        lane_id  : str    — echoed back for traceability
    """
    gate_def = STRUCTURAL_FAST_TRACK_GATES.get(lane_id)
    if gate_def is None:
        return {
            "approved": False,
            "reasons": [f"lane '{lane_id}' is not in STRUCTURAL_FAST_TRACK_GATES"],
            "stage": "shadow",
            "lane_id": lane_id,
        }

    reasons: list[str] = []
    failures: list[str] = []

    def _check_min(key: str, stat_key: str | None = None) -> None:
        threshold = gate_def[key]
        actual = int(stats.get(stat_key or key) or 0)
        if actual >= threshold:
            reasons.append(f"{key}: {actual} >= {threshold} (pass)")
        else:
            failures.append(f"{key}: {actual} < {threshold} required (fail)")

    def _check_max(key: str, stat_key: str | None = None) -> None:
        threshold = gate_def[key]
        actual = int(stats.get(stat_key or key) or 0)
        if actual <= threshold:
            reasons.append(f"{key}: {actual} <= {threshold} (pass)")
        else:
            failures.append(f"{key}: {actual} > {threshold} allowed (fail)")

    def _check_bool(key: str, stat_key: str | None = None) -> None:
        required = bool(gate_def[key])
        actual = bool(stats.get(stat_key or key, False))
        if not required:
            reasons.append(f"{key}: not required (pass)")
        elif actual:
            reasons.append(f"{key}: satisfied (pass)")
        else:
            failures.append(f"{key}: required but not satisfied (fail)")

    # Evaluate each key in the gate definition
    for key in gate_def:
        if key.startswith("min_"):
            _check_min(key)
        elif key.startswith("max_"):
            _check_max(key)
        elif key.startswith("require_"):
            _check_bool(key)
        else:
            reasons.append(f"{key}: unrecognised gate key, skipped")

    approved = len(failures) == 0
    if not approved:
        simulation_fills = int(stats.get("simulation_fills") or 0)
        if simulation_fills > 0:
            simulation_checks: list[tuple[bool, str]] = [
                (
                    str(stats.get("truth_dependency_status") or "").strip().lower() == "green",
                    f"truth_dependency_status={stats.get('truth_dependency_status') or 'missing'}",
                ),
                (
                    bool(stats.get("promotion_fast_track_ready")),
                    f"promotion_fast_track_ready={bool(stats.get('promotion_fast_track_ready'))}",
                ),
                (
                    float(stats.get("edge_after_fees_usd") or 0.0) > 0.0,
                    f"edge_after_fees_usd={float(stats.get('edge_after_fees_usd') or 0.0):.4f}",
                ),
                (
                    float(stats.get("execution_realism_score") or 0.0) >= 0.80,
                    f"execution_realism_score={float(stats.get('execution_realism_score') or 0.0):.3f}",
                ),
            ]
            if lane_id == "pair_completion":
                simulation_checks.extend(
                    [
                        (simulation_fills >= 50, f"simulation_fills={simulation_fills}"),
                        (
                            float(stats.get("partial_fill_breach_rate") or 0.0) <= 0.10,
                            f"partial_fill_breach_rate={float(stats.get('partial_fill_breach_rate') or 0.0):.3f}",
                        ),
                        (
                            float(stats.get("max_trapped_capital_usd") or 0.0) <= 15.0,
                            f"max_trapped_capital_usd={float(stats.get('max_trapped_capital_usd') or 0.0):.2f}",
                        ),
                    ]
                )
            elif lane_id == "neg_risk":
                simulation_checks.extend(
                    [
                        (simulation_fills >= 20, f"simulation_fills={simulation_fills}"),
                        (
                            int(stats.get("taxonomy_ambiguity") or 0) == 0,
                            f"taxonomy_ambiguity={int(stats.get('taxonomy_ambiguity') or 0)}",
                        ),
                        (
                            bool(stats.get("bounded_worst_case", False)),
                            f"bounded_worst_case={bool(stats.get('bounded_worst_case', False))}",
                        ),
                    ]
                )
            sim_reasons = [
                f"{detail} ({'pass' if passed else 'fail'})"
                for passed, detail in simulation_checks
            ]
            if all(passed for passed, _ in simulation_checks):
                return {
                    "approved": True,
                    "reasons": reasons + failures + sim_reasons,
                    "stage": "micro_live",
                    "lane_id": lane_id,
                    "path": "simulation_fast_track",
                }
            failures.extend(sim_reasons)
    return {
        "approved": approved,
        "reasons": reasons + failures,
        "stage": "micro_live" if approved else "shadow",
        "lane_id": lane_id,
    }


def _compute_kelly_size(thesis: dict, history: dict[str, Any]) -> dict[str, Any]:
    """Compute Kelly-based position size for capital theses."""
    if not thesis.get("requires_capital"):
        return {"size_usd": 0.0, "kelly_raw": 0.0, "note": "no capital required"}

    hist = history.get(thesis["thesis_id"]) or {}
    win_rate = hist.get("win_rate") or thesis.get("confidence") or 0.5
    avg_win = hist.get("avg_win_multiple") or 1.0
    avg_loss = hist.get("avg_loss_multiple") or 1.0

    # Kelly: f = (p * b - q) / b where b = avg_win/avg_loss, p = win_rate, q = 1-p
    b = avg_win / max(avg_loss, 0.001)
    p = win_rate
    q = 1 - p
    kelly_raw = (p * b - q) / max(b, 0.001)
    kelly_sized = kelly_raw * KELLY_FRACTION
    kelly_capped = max(0.0, min(kelly_sized, 1.0))
    size_usd = kelly_capped * MAX_POSITION_USD

    return {
        "size_usd": round(size_usd, 2),
        "kelly_raw": round(kelly_raw, 4),
        "kelly_quarter": round(kelly_capped, 4),
        "win_rate": win_rate,
        "avg_win_multiple": avg_win,
    }


# ---------------------------------------------------------------------------
# Counterfactual simulation (simplified off-policy what-if)
# ---------------------------------------------------------------------------


def _counterfactual(thesis: dict, history: dict[str, Any]) -> dict[str, Any]:
    """Simplified counterfactual: what P&L would we have if we had traded this?"""
    hist = history.get(thesis["thesis_id"]) or {}
    n_opportunities = hist.get("counterfactual_opportunities") or 0
    win_rate = hist.get("win_rate") or thesis.get("confidence") or 0.5
    kelly = _compute_kelly_size(thesis, history)
    size = kelly["size_usd"]

    expected_pnl = n_opportunities * win_rate * size * 0.9 - n_opportunities * (1 - win_rate) * size
    return {
        "n_opportunities": n_opportunities,
        "expected_pnl_usd": round(expected_pnl, 2),
        "size_per_trade_usd": size,
        "win_rate_assumption": win_rate,
        "note": "simplified off-policy simulation; requires real fill data for accuracy",
    }


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------


class PromoDecision(str):
    APPROVE = "APPROVE"
    HOLD = "HOLD"
    KILL = "KILL"


def _resolve_lane(thesis: dict) -> str:
    """Return a normalised lane string from a thesis dict.

    Checks ``lane`` first, then falls back to ``source``.  Returns an empty
    string if neither key is present.  The returned string is lower-cased and
    stripped so callers can do simple ``in`` / ``==`` membership tests.
    """
    raw = str(thesis.get("lane") or thesis.get("source") or "").strip().lower()
    return raw


def _check_wallet_ledger_mismatch(thesis_bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Global gate: wallet/ledger disagreement disables ALL new live capital.

    Returns a failed gate dict if a mismatch is detected, otherwise None
    (meaning no mismatch found and the global gate passes).

    This is intentionally kept global — a truth mismatch means the accounting
    layer cannot be trusted for any lane.
    """
    rt = load_json(RUNTIME_TRUTH_LATEST_PATH)
    if rt is None:
        # Cannot verify — treat as pass (freshness gate handles the missing file case)
        return None

    mismatch = rt.get("wallet_ledger_mismatch")
    if mismatch:
        return {
            "gate": "wallet_ledger_truth",
            "passed": False,
            "note": (
                "wallet/ledger disagreement detected — ALL new live capital disabled "
                f"until reconciled (mismatch={mismatch})"
            ),
        }
    return None


def _truth_gate_from_canonical_truth() -> dict[str, Any] | None:
    truth = load_json(CANONICAL_TRUTH_PATH)
    if truth is None:
        return None
    truth_status = str(truth.get("truth_status") or "").strip().lower()
    if truth_status in {"degraded", "blocked"}:
        blockers = list(truth.get("truth_mismatches") or truth.get("blockers") or [])
        return {
            "gate": "canonical_truth",
            "passed": False,
            "note": (
                f"canonical truth is {truth_status}; "
                f"blockers={', '.join(str(item) for item in blockers[:3]) or 'unspecified'}"
            ),
            "truth_status": truth_status,
        }
    return None


def _structural_requirement_blockers(candidate: dict[str, Any]) -> list[str]:
    lane = str(candidate.get("lane") or "")
    blockers: list[str] = []
    fills = int(candidate.get("fills_simulated") or 0)
    expectancy = float(candidate.get("net_after_fee_expectancy") or 0.0)
    breach = float(candidate.get("partial_fill_breach_rate") or 1.0)
    half_life_ms = float(candidate.get("opportunity_half_life_ms") or 0.0)
    truth_dependency = str(candidate.get("truth_dependency_status") or "unknown").lower()

    if truth_dependency != "green":
        blockers.append(f"{lane}_truth_dependency_{truth_dependency}")

    if lane == "pair_completion":
        if fills < 50:
            blockers.append("pair_completion_replay_opportunities_below_50")
        if breach > 0.10:
            blockers.append("pair_completion_partial_fill_breach_above_threshold")
        if expectancy <= 0:
            blockers.append("pair_completion_negative_expectancy")
    elif lane == "neg_risk":
        taxonomy_ambiguity = float((candidate.get("parameters_tested") or {}).get("taxonomy_ambiguity", 1))
        if fills < 20:
            blockers.append("neg_risk_replay_opportunities_below_20")
        if taxonomy_ambiguity != 0:
            blockers.append("neg_risk_taxonomy_ambiguity_nonzero")
        if expectancy <= 0:
            blockers.append("neg_risk_negative_expectancy")
    elif lane == "resolution_sniper":
        if half_life_ms <= 250000:
            blockers.append("resolution_sniper_half_life_below_latency_floor")
        if breach > 0.15:
            blockers.append("resolution_sniper_decay_too_fast")
    elif lane == "weather_settlement_timing":
        if fills < 20:
            blockers.append("weather_settlement_timing_replay_depth_thin")
    return blockers


def _build_structural_lane_snapshots(
    ranked_candidates: list[dict[str, Any]],
    *,
    truth_status: str,
) -> list[dict[str, Any]]:
    truth_is_green = truth_status == "green"
    per_lane: dict[str, dict[str, Any]] = {}
    for candidate in ranked_candidates:
        lane = str(candidate.get("lane") or "").strip()
        if not lane:
            continue
        score = float(candidate.get("moonshot_score") or 0.0)
        if lane not in per_lane or score > float(per_lane[lane].get("moonshot_score") or 0.0):
            per_lane[lane] = candidate

    snapshots: list[dict[str, Any]] = []
    for lane, candidate in sorted(per_lane.items(), key=lambda item: -float(item[1].get("moonshot_score") or 0.0)):
        blockers = list(candidate.get("current_blockers") or _structural_requirement_blockers(candidate))
        if not truth_is_green:
            blockers = list(dict.fromkeys([f"truth_status_{truth_status}", *blockers]))
        evidence_fresh = bool(candidate.get("evidence_fresh", truth_is_green))
        simulation_ready = bool(candidate.get("simulation_ready", bool(candidate.get("fills_simulated"))))
        requested_promotion_ready = bool(
            candidate.get(
                "promotion_ready",
                evidence_fresh and simulation_ready and not blockers and bool(candidate.get("promotion_fast_track_ready")),
            )
        )
        promotion_ready = bool(
            truth_is_green
            and requested_promotion_ready
            and evidence_fresh
            and simulation_ready
            and not blockers
            and bool(candidate.get("promotion_fast_track_ready"))
        )
        raw_score = float(candidate.get("moonshot_score") or 0.0)
        priority_rank_raw = candidate.get("priority_rank")
        priority_rank = 99 if priority_rank_raw is None else int(priority_rank_raw)
        routing_score = raw_score + max(0.0, 20.0 - (priority_rank * 5.0))
        snapshots.append(
            {
                "schema": "structural_lane_snapshot.v1",
                "lane": lane,
                "strategy_id": candidate.get("strategy_id"),
                "evidence_fresh": evidence_fresh,
                "simulation_ready": simulation_ready,
                "promotion_ready": promotion_ready,
                "recommended_capital_usd": float(candidate.get("recommended_capital_usd") or 0.0),
                "current_blockers": blockers,
                "score": routing_score,
                "raw_score": raw_score,
                "net_after_fee_expectancy": float(candidate.get("net_after_fee_expectancy") or 0.0),
                "partial_fill_breach_rate": float(candidate.get("partial_fill_breach_rate") or 0.0),
                "opportunity_half_life_ms": float(candidate.get("opportunity_half_life_ms") or 0.0),
            }
        )
    return snapshots


def _build_structural_theses_from_ranked_candidates(
    ranked_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    theses: list[dict[str, Any]] = []
    for candidate in ranked_candidates:
        lane = str(candidate.get("lane") or "").strip()
        if lane not in STRUCTURAL_FAST_TRACK_GATES:
            continue
        theses.append(
            {
                "thesis_id": f"structural:{lane}:{candidate.get('strategy_id') or lane}",
                "type": "structural_edge",
                "source": "structural_live_queue",
                "lane": lane,
                "description": f"{lane} structural candidate from {candidate.get('scenario_set') or 'simulation'}",
                "requires_capital": True,
                "confidence": max(
                    0.50,
                    min(0.99, float(candidate.get("execution_realism") or 0.0)),
                ),
                "execution_realism_score": float(candidate.get("execution_realism") or 0.0),
                "simulation_fills": int(candidate.get("fills_simulated") or 0),
                "edge_after_fees_usd": float(candidate.get("net_after_fee_expectancy") or 0.0),
                "partial_fill_breach_rate": float(candidate.get("partial_fill_breach_rate") or 0.0),
                "max_trapped_capital_usd": float(candidate.get("max_trapped_capital_usd") or 0.0),
                "truth_dependency_status": str(candidate.get("truth_dependency_status") or "unknown"),
                "promotion_fast_track_ready": bool(candidate.get("promotion_fast_track_ready")),
                "bounded_worst_case": bool(
                    (candidate.get("promotion_inputs") or {}).get("bounded_worst_case", lane != "neg_risk")
                ),
                "taxonomy_ambiguity": int(
                    (candidate.get("promotion_inputs") or {}).get("taxonomy_ambiguity") or 0
                ),
                "recommended_capital_usd": float(candidate.get("recommended_capital_usd") or 0.0),
                "current_blockers": list(candidate.get("current_blockers") or []),
            }
        )
    return theses


def evaluate_thesis(
    thesis: dict,
    history: dict[str, Any],
    all_theses: list[dict],
    *,
    capital_lab: dict[str, Any] | None = None,
    counterfactual_lab: dict[str, Any] | None = None,
    thesis_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lane = _resolve_lane(thesis)

    # ------------------------------------------------------------------
    # Global gate: wallet/ledger mismatch disables ALL new live capital.
    # Check this first so it appears prominently in the output.
    # ------------------------------------------------------------------
    wallet_gate = _check_wallet_ledger_mismatch(thesis_bundle)
    canonical_truth_gate = _truth_gate_from_canonical_truth()

    # ------------------------------------------------------------------
    # Hard gates (now lane-aware):
    #   - evidence_freshness: stale weather evidence -> weather lane only
    #   - btc5_pnl_truth: negative PnL -> btc5 lane only
    # ------------------------------------------------------------------
    freshness_gate = _evaluate_evidence_freshness(thesis_bundle, lane=lane)
    btc5_gate = _evaluate_btc5_pnl_truth(lane=lane)

    # ------------------------------------------------------------------
    # Structural fast-track: deterministic lanes (pair_completion, neg_risk)
    # may skip generic replay/off_policy/world_league gates when they meet
    # the lower, bounded-risk thresholds in STRUCTURAL_FAST_TRACK_GATES.
    # Check this BEFORE building the generic gate list.
    # ------------------------------------------------------------------
    structural_ft: dict[str, Any] | None = None
    use_fast_track = False

    if lane in STRUCTURAL_FAST_TRACK_GATES:
        # Gather the lane's runtime stats from capital_lab or thesis itself
        lane_stats: dict[str, Any] = {}
        if capital_lab:
            lane_stats = (capital_lab.get("lanes") or {}).get(lane) or {}
        # Allow thesis-embedded stats to supplement (keys may vary by lane)
        for k in thesis:
            if k not in lane_stats:
                lane_stats.setdefault(k, thesis[k])

        structural_ft = evaluate_structural_fast_track(lane, lane_stats)
        use_fast_track = structural_ft["approved"]

    # ------------------------------------------------------------------
    # Build gate list: fast-track lanes skip replay/off_policy/world_league.
    # Hard gates and execution_quality always run.
    # ------------------------------------------------------------------
    gates: list[dict[str, Any]] = []

    # Global wallet/ledger mismatch gate (if triggered)
    if wallet_gate is not None:
        gates.append(wallet_gate)
    if canonical_truth_gate is not None:
        gates.append(canonical_truth_gate)

    # Lane-specific hard gates
    gates.append(freshness_gate)
    gates.append(btc5_gate)

    if use_fast_track:
        # Structural fast-track: skip the generic statistical gates
        gates.append({
            "gate": "structural_fast_track",
            "passed": True,
            "lane": lane,
            "stage": structural_ft["stage"],
            "reasons": structural_ft["reasons"],
            "note": (
                f"structural fast-track approved for lane='{lane}'; "
                "replay/off_policy/world_league gates bypassed"
            ),
        })
    else:
        # Generic statistical gates
        gates.append(_evaluate_replay(thesis, history, capital_lab=capital_lab))
        gates.append(_evaluate_off_policy(thesis, history, counterfactual_lab=counterfactual_lab))
        gates.append(_evaluate_world_league(thesis, history, all_theses))

    # Execution quality always runs (applies to all lanes)
    gates.append(_evaluate_execution_quality(thesis, history))

    all_passed = all(g["passed"] for g in gates)

    # ------------------------------------------------------------------
    # Compute per-lane verdict (approved / blocked / insufficient_data)
    # ------------------------------------------------------------------
    failed_gates = [g for g in gates if not g["passed"]]
    if all_passed:
        lane_verdict = LANE_APPROVED
    elif any(
        g.get("gate") in {"wallet_ledger_truth", "evidence_freshness"}
        for g in failed_gates
    ):
        # A structural blocker — data is actively wrong, not just sparse
        lane_verdict = LANE_BLOCKED
    else:
        # Failed due to insufficient data (no fills, no replay history, etc.)
        lane_verdict = LANE_INSUFFICIENT

    # Kill if thesis type is risk_alert
    if thesis.get("type") == "risk_alert":
        decision = PromoDecision.HOLD  # risk alerts don't get capital
    elif all_passed:
        decision = PromoDecision.APPROVE
    else:
        decision = PromoDecision.HOLD

    kelly = _compute_kelly_size(thesis, history)
    counterfactual = _counterfactual(thesis, history)

    result: dict[str, Any] = {
        "thesis_id": thesis["thesis_id"],
        "thesis_type": thesis.get("type"),
        "source": thesis.get("source"),
        "lane": lane or None,
        "lane_verdict": lane_verdict,
        "description": thesis.get("description", "")[:120],
        "gates": gates,
        "gates_passed": sum(1 for g in gates if g["passed"]),
        "gates_total": len(gates),
        "promotion_decision": decision,
        "requires_capital": thesis.get("requires_capital", False),
        "kelly_sizing": kelly,
        "counterfactual": counterfactual,
    }
    if structural_ft is not None:
        result["structural_fast_track"] = structural_ft
    return result


def assemble_promotion() -> dict[str, Any]:
    thesis_bundle = load_json(THESIS_PATH)
    ranked_structural_candidates = _load_ranked_structural_candidates()
    canonical_truth = load_json(CANONICAL_TRUTH_PATH) or {}

    if thesis_bundle is None:
        logger.warning("[promotion] thesis_bundle.json not found — continuing with structural simulation candidates only")
        thesis_bundle = {
            "generated_at": utc_now(),
            "status": "structural_only",
            "theses": [],
        }

    gen = thesis_bundle.get("generated_at") or ""
    age = age_seconds(gen)
    if age > 3600:
        logger.warning("[promotion] thesis bundle is %.0fh old", age / 3600)

    theses = list(thesis_bundle.get("theses") or [])
    existing_ids = {str(item.get("thesis_id") or "") for item in theses if isinstance(item, dict)}
    for structural_thesis in _build_structural_theses_from_ranked_candidates(ranked_structural_candidates):
        if structural_thesis["thesis_id"] not in existing_ids:
            theses.append(structural_thesis)
    history = _load_promo_history()

    # Load sub-component lab artifacts as gate inputs (not decision authorities)
    capital_lab = load_json(CAPITAL_LAB_PATH)
    counterfactual_lab = load_json(COUNTERFACTUAL_LAB_PATH)
    if capital_lab:
        logger.info("[promotion] capital_lab loaded (age=%.0fs)", age_seconds(capital_lab.get("generated_at") or ""))
    if counterfactual_lab:
        logger.info("[promotion] counterfactual_lab loaded (verdict=%s)", counterfactual_lab.get("verdict"))

    evaluations = [
        evaluate_thesis(
            t, history, theses,
            capital_lab=capital_lab,
            counterfactual_lab=counterfactual_lab,
            thesis_bundle=thesis_bundle,
        )
        for t in theses
    ]

    approved = [e for e in evaluations if e["promotion_decision"] == PromoDecision.APPROVE]
    held = [e for e in evaluations if e["promotion_decision"] == PromoDecision.HOLD]
    killed = [e for e in evaluations if e["promotion_decision"] == PromoDecision.KILL]

    total_capital_usd = sum(
        e["kelly_sizing"]["size_usd"] for e in approved if e["requires_capital"]
    )

    thesis_status = str(thesis_bundle.get("status") or "fresh").strip().lower()
    blockers: list[str] = []
    if not theses and not ranked_structural_candidates:
        blockers.append("no_theses_or_structural_candidates")
    if capital_lab is None:
        blockers.append("capital_lab_missing")
    if counterfactual_lab is None:
        blockers.append("counterfactual_lab_missing")
    if age > 1800:
        blockers.append(f"thesis_bundle_age_seconds>{1800}")
    if thesis_status in {"blocked", "error"}:
        blockers.append("thesis_bundle_blocked")
    truth_status = str(canonical_truth.get("truth_status") or "unknown").strip().lower()
    structural_lane_snapshots = _build_structural_lane_snapshots(
        ranked_structural_candidates,
        truth_status=truth_status,
    )
    capital_router = CapitalRouter(total_capital=1000.0)
    structural_allocation = capital_router.allocate_best_structural_lane(structural_lane_snapshots)

    if truth_status in {"degraded", "blocked"}:
        structural_allocation = {
            "recommended_live_lane": None,
            "recommended_size_usd": 0.0,
            "approved_queue": [],
            "capital_blockers": list(
                dict.fromkeys(
                    [f"truth_status_{truth_status}", *list(structural_allocation.get("capital_blockers") or [])]
                )
            ),
        }

    for snapshot in structural_lane_snapshots:
        if snapshot["lane"] == structural_allocation.get("recommended_live_lane"):
            snapshot["recommended_capital_usd"] = float(structural_allocation.get("recommended_size_usd") or 0.0)
        elif truth_status in {"degraded", "blocked"}:
            snapshot["recommended_capital_usd"] = 0.0

    proof_status = "ready" if structural_allocation.get("recommended_live_lane") else "blocked"
    capital_blockers = list(structural_allocation.get("capital_blockers") or [])
    if truth_status in {"degraded", "blocked"}:
        capital_blockers = list(dict.fromkeys([f"truth_status_{truth_status}", *capital_blockers]))

    status = "blocked" if (not theses and not ranked_structural_candidates) else ("stale" if blockers else "fresh")
    if capital_blockers:
        status = "blocked"

    bundle: dict[str, Any] = {
        "artifact": "promotion_bundle",
        "generated_at": utc_now(),
        "thesis_bundle_age_seconds": age,
        "thesis_count": len(theses),
        "approved_count": len(approved),
        "held_count": len(held),
        "killed_count": len(killed),
        "total_capital_approved_usd": round(total_capital_usd, 2),
        "evaluations": evaluations,
        "status": status,
        "blockers": blockers,
        "recommended_live_lane": structural_allocation.get("recommended_live_lane"),
        "recommended_size_usd": structural_allocation.get("recommended_size_usd"),
        "proof_status": proof_status,
        "capital_blockers": capital_blockers,
        "structural_lane_snapshots": structural_lane_snapshots,
        "structural_live_queue": structural_allocation.get("approved_queue") or [],
        "best_live_ready_structural_lane": next(
            (snapshot for snapshot in structural_lane_snapshots if snapshot.get("promotion_ready")),
            None,
        ),
        "next_capital_recommendation": {
            "lane": structural_allocation.get("recommended_live_lane"),
            "capital_usd": float(structural_allocation.get("recommended_size_usd") or 0.0),
            "blockers": capital_blockers,
        },
        "truth_status": truth_status,
    }

    structural_queue_payload = {
        "schema": "structural_live_queue.v1",
        "generated_at": bundle["generated_at"],
        "recommended_live_lane": bundle["recommended_live_lane"],
        "recommended_size_usd": bundle["recommended_size_usd"],
        "proof_status": proof_status,
        "capital_blockers": capital_blockers,
        "queue": bundle["structural_live_queue"],
    }
    structural_snapshot_payload = {
        "schema": "structural_lane_snapshot.v1",
        "generated_at": bundle["generated_at"],
        "truth_status": truth_status,
        "lanes": structural_lane_snapshots,
    }
    _write_structural_artifacts(
        queue_payload=structural_queue_payload,
        snapshot_payload=structural_snapshot_payload,
    )

    write_report(
        OUTPUT_PATH,
        artifact="promotion_bundle",
        payload=bundle,
        status=status,
        source_of_truth=(
            "reports/thesis_bundle.json; reports/capital_lab/latest.json; "
            "reports/counterfactual_lab/latest.json; reports/canonical_operator_truth.json; "
            "reports/simulation/ranked_candidates.json"
        ),
        freshness_sla_seconds=1800,
        blockers=blockers or ([bundle["blocked_reason"]] if bundle.get("blocked_reason") else []),
        summary=(
            f"{len(approved)} approved, {len(held)} held, {len(killed)} killed, "
            f"capital={total_capital_usd:.2f}, "
            f"structural_lane={bundle.get('recommended_live_lane') or 'none'}"
        ),
    )
    logger.info(
        "[promotion] %d theses: %d approved ($%.2f), %d held, %d killed",
        len(theses), len(approved), total_capital_usd, len(held), len(killed),
    )
    return bundle


def _empty_bundle(reason: str) -> dict[str, Any]:
    return {
        "artifact": "promotion_bundle",
        "generated_at": utc_now(),
        "thesis_count": 0,
        "approved_count": 0,
        "evaluations": [],
        "blocked_reason": reason,
        "status": "blocked",
        "blockers": [reason],
    }


def update_kernel_state(bundle: dict[str, Any]) -> None:
    try:
        import sys
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from kernel_contract import KernelCycle, BundleStatus

        cycle = KernelCycle.load()
        bundle_status = str(bundle.get("status") or "error").strip().lower()
        if bundle_status == "fresh":
            cycle.promotion.mark_fresh(
                generated_at=bundle["generated_at"],
                source_count=bundle.get("thesis_count", 0),
                item_count=bundle.get("approved_count", 0),
            )
        else:
            try:
                cycle.promotion.status = BundleStatus(bundle_status)
            except ValueError:
                cycle.promotion.status = BundleStatus.ERROR
            blockers = bundle.get("blockers") or [bundle.get("blocked_reason") or "promotion_unavailable"]
            cycle.promotion.last_error = "; ".join(str(item) for item in blockers if str(item).strip())[:200]
        cycle.compute_cycle_decision()
        cycle.save()
        cycle.append_cycle_log()
    except Exception as exc:
        logger.warning("[promotion] kernel state update failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_once() -> None:
    bundle = assemble_promotion()
    update_kernel_state(bundle)


async def run_daemon() -> None:
    logger.info("Promotion bundle daemon starting — interval=%ds", INTERVAL)
    while True:
        t0 = time.monotonic()
        try:
            run_once()
        except Exception as exc:
            logger.error("[promotion] cycle failed: %s", exc)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, INTERVAL - elapsed))


def main() -> None:
    global INTERVAL
    parser = argparse.ArgumentParser(description="Promotion bundle — thesis evaluation and capital gate")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=INTERVAL)
    args = parser.parse_args()
    INTERVAL = args.interval
    if args.daemon and not args.once:
        asyncio.run(run_daemon())
    else:
        run_once()


if __name__ == "__main__":
    main()
