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

INTERVAL = int(os.environ.get("PROMOTION_INTERVAL_SECONDS", "1800"))

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
) -> dict[str, Any]:
    """Hard gate: evidence bundle and runtime truth must be fresh enough.

    Checks two things:
    1. thesis_bundle was generated within EVIDENCE_FRESHNESS_MAX_AGE (24h default)
    2. runtime_truth_latest.json exists and was generated within RUNTIME_TRUTH_MAX_AGE (6h default)

    This gate runs BEFORE replay and off_policy gates.  If evidence is stale,
    nothing downstream can be trusted.
    """
    reasons: list[str] = []

    # --- thesis bundle freshness ---
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

    # --- runtime truth freshness ---
    rt = load_json(RUNTIME_TRUTH_LATEST_PATH)
    if rt is None:
        reasons.append("runtime_truth_latest.json missing")
    else:
        rt_gen = rt.get("generated_at") or ""
        rt_age = age_seconds(rt_gen)
        if rt_age < 0:
            reasons.append("runtime_truth_latest.json has no valid generated_at timestamp")
        elif rt_age > RUNTIME_TRUTH_MAX_AGE:
            reasons.append(
                f"runtime_truth_latest.json is {rt_age / 3600:.1f}h old "
                f"(max {RUNTIME_TRUTH_MAX_AGE / 3600:.0f}h)"
            )

    passed = len(reasons) == 0
    return {
        "gate": "evidence_freshness",
        "passed": passed,
        "reasons": reasons,
        "note": "fresh" if passed else "; ".join(reasons),
    }


def _evaluate_btc5_pnl_truth() -> dict[str, Any]:
    """Hard gate: BTC5 PnL must be present and non-negative for promotion.

    Reads runtime_truth_latest.json and checks:
    1. If fills exist but PnL is null/missing -> FAIL (data integrity)
    2. If cumulative PnL is negative AND profit_factor < 1.0 -> FAIL (promotion blocked)

    A negative-PnL failure blocks promotion but does NOT trigger demotion —
    the strategy stays at its current stage.
    """
    rt = load_json(RUNTIME_TRUTH_LATEST_PATH)
    if rt is None:
        return {
            "gate": "btc5_pnl_truth",
            "passed": False,
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
            "fill_rows": fill_rows,
            "pnl_usd": None,
            "profit_factor": profit_factor,
            "note": (
                f"BTC5 has {fill_rows} fills but PnL is null — "
                "data integrity failure, promotion blocked"
            ),
        }

    # Gate 2: negative cumulative PnL AND profit_factor < 1.0 -> promotion blocked
    has_pnl = pnl is not None
    pnl_negative = has_pnl and pnl < 0
    pf_below_one = profit_factor is not None and profit_factor < 1.0
    # If profit_factor is null but PnL is negative, still fail (no evidence of edge)
    pf_missing_with_neg_pnl = profit_factor is None and pnl_negative

    if pnl_negative and (pf_below_one or pf_missing_with_neg_pnl):
        return {
            "gate": "btc5_pnl_truth",
            "passed": False,
            "fill_rows": fill_rows,
            "pnl_usd": pnl,
            "profit_factor": profit_factor,
            "note": (
                f"BTC5 cumulative PnL=${pnl:.2f} with "
                f"profit_factor={profit_factor} — "
                "negative P&L blocks promotion (strategy holds at current stage)"
            ),
        }

    passed = has_pnl or (fill_rows is None or fill_rows == 0)
    note = "no BTC5 fills yet" if not fill_rows else f"BTC5 PnL=${pnl:.2f}, PF={profit_factor}"
    return {
        "gate": "btc5_pnl_truth",
        "passed": passed,
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
    fill_rate = hist.get("fill_rate") or 0.0
    toxic_rate = hist.get("toxic_flow_rate") or 0.0
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


def evaluate_thesis(
    thesis: dict,
    history: dict[str, Any],
    all_theses: list[dict],
    *,
    capital_lab: dict[str, Any] | None = None,
    counterfactual_lab: dict[str, Any] | None = None,
    thesis_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gates = [
        # Hard gates first — stale evidence or negative PnL blocks everything
        _evaluate_evidence_freshness(thesis_bundle),
        _evaluate_btc5_pnl_truth(),
        # Standard promotion gates
        _evaluate_replay(thesis, history, capital_lab=capital_lab),
        _evaluate_off_policy(thesis, history, counterfactual_lab=counterfactual_lab),
        _evaluate_world_league(thesis, history, all_theses),
        _evaluate_execution_quality(thesis, history),
    ]
    all_passed = all(g["passed"] for g in gates)
    any_failed = any(not g["passed"] for g in gates)

    # Kill if thesis type is risk_alert and concentration > 40%
    if thesis.get("type") == "risk_alert":
        decision = PromoDecision.HOLD  # risk alerts don't get capital
    elif all_passed:
        decision = PromoDecision.APPROVE
    else:
        decision = PromoDecision.HOLD

    kelly = _compute_kelly_size(thesis, history)
    counterfactual = _counterfactual(thesis, history)

    return {
        "thesis_id": thesis["thesis_id"],
        "thesis_type": thesis.get("type"),
        "source": thesis.get("source"),
        "description": thesis.get("description", "")[:120],
        "gates": gates,
        "gates_passed": sum(1 for g in gates if g["passed"]),
        "gates_total": len(gates),
        "promotion_decision": decision,
        "requires_capital": thesis.get("requires_capital", False),
        "kelly_sizing": kelly,
        "counterfactual": counterfactual,
    }


def assemble_promotion() -> dict[str, Any]:
    thesis_bundle = load_json(THESIS_PATH)
    if thesis_bundle is None:
        logger.warning("[promotion] thesis_bundle.json not found — skipping")
        bundle = _empty_bundle("thesis_bundle missing")
        write_report(
            OUTPUT_PATH,
            artifact="promotion_bundle",
            payload=bundle,
            status="blocked",
            source_of_truth="reports/thesis_bundle.json; reports/capital_lab/latest.json; reports/counterfactual_lab/latest.json",
            freshness_sla_seconds=1800,
            blockers=[bundle["blocked_reason"]],
            summary="promotion bundle blocked: thesis bundle missing",
        )
        return bundle

    gen = thesis_bundle.get("generated_at") or ""
    age = age_seconds(gen)
    if age > 3600:
        logger.warning("[promotion] thesis bundle is %.0fh old", age / 3600)

    theses = thesis_bundle.get("theses") or []
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
    if not theses:
        blockers.append("no_theses")
    if capital_lab is None:
        blockers.append("capital_lab_missing")
    if counterfactual_lab is None:
        blockers.append("counterfactual_lab_missing")
    if age > 1800:
        blockers.append(f"thesis_bundle_age_seconds>{1800}")
    if thesis_status in {"blocked", "error"}:
        blockers.append("thesis_bundle_blocked")
    status = "blocked" if not theses or thesis_status in {"blocked", "error"} else ("stale" if blockers else "fresh")

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
    }

    write_report(
        OUTPUT_PATH,
        artifact="promotion_bundle",
        payload=bundle,
        status=status,
        source_of_truth=(
            "reports/thesis_bundle.json; reports/capital_lab/latest.json; "
            "reports/counterfactual_lab/latest.json"
        ),
        freshness_sla_seconds=1800,
        blockers=blockers or ([bundle["blocked_reason"]] if bundle.get("blocked_reason") else []),
        summary=(
            f"{len(approved)} approved, {len(held)} held, {len(killed)} killed, "
            f"capital={total_capital_usd:.2f}"
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
