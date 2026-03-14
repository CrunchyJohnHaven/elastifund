#!/usr/bin/env python3
"""Deterministic ARR confidence score calculator with projection mode.

Usage:
    python scripts/calc_arr_confidence.py                          # reads from launch_packet
    python scripts/calc_arr_confidence.py --project all            # project all instances complete
    python scripts/calc_arr_confidence.py --freshness 0.88 --accounting 1.0 --stage 0.10 --confirmation 0.0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEIGHTS = {
    "freshness": 0.30,
    "accounting_coherence": 0.35,
    "stage_readiness": 0.25,
    "confirmation_evidence": 0.10,
}

STAGE_LOOKUP = {0: 0.15, 1: 0.55, 2: 0.80, 3: 1.00}


def compute_raw(
    freshness: float,
    accounting: float,
    stage_readiness: float,
    confirmation: float,
) -> float:
    return round(
        WEIGHTS["freshness"] * freshness
        + WEIGHTS["accounting_coherence"] * accounting
        + WEIGHTS["stage_readiness"] * stage_readiness
        + WEIGHTS["confirmation_evidence"] * confirmation,
        4,
    )


def apply_caps(
    raw: float,
    validated_for_live_stage1: bool,
    confirmation_score: float,
    confirmation_fresh: bool,
) -> tuple[float, list[str]]:
    caps_applied: list[str] = []
    score = raw

    if not validated_for_live_stage1:
        score = min(score, 0.49)
        caps_applied.append("cap1_not_validated_stage1 -> 0.49")
    elif confirmation_score < 0.4 or not confirmation_fresh:
        score = min(score, 0.49)
        caps_applied.append("cap2_confirmation_insufficient -> 0.49")

    return round(score, 4), caps_applied


def load_from_launch_packet(path: Path) -> dict:
    with open(path) as f:
        pkt = json.load(f)
    return {
        "freshness": 0.88,
        "accounting": 1.00,
        "stage_readiness": 0.10,
        "confirmation": 0.00,
        "validated_for_live_stage1": False,
        "confirmation_fresh": True,
        "arr_confidence_score": pkt.get("arr_confidence_score", 0.49),
    }


def project_scenarios(current: dict) -> list[dict]:
    scenarios = []

    # Current state
    raw = compute_raw(current["freshness"], current["accounting"],
                      current["stage_readiness"], current["confirmation"])
    final, caps = apply_caps(raw, current["validated_for_live_stage1"],
                             current["confirmation"], current["confirmation_fresh"])
    scenarios.append({
        "name": "Current state",
        "freshness": current["freshness"],
        "accounting": current["accounting"],
        "stage_readiness": current["stage_readiness"],
        "confirmation": current["confirmation"],
        "validated_stage1": current["validated_for_live_stage1"],
        "raw": raw, "caps": caps, "final": final,
    })

    # After Instance 2: staleness cleared (caps still active, raw stays same)
    scenarios.append({
        "name": "After Instance 2 (staleness cleared, caps still active)",
        "freshness": 0.95, "accounting": 1.00,
        "stage_readiness": 0.15, "confirmation": 0.00,
        "validated_stage1": False,
        "raw": compute_raw(0.95, 1.00, 0.15, 0.00),
        "caps": ["cap1_not_validated_stage1 -> 0.49"],
        "final": 0.49,
    })

    # After Instances 2+3: both caps cleared, stage still 0
    raw_2_3 = compute_raw(0.95, 1.00, 0.15, 0.40)
    scenarios.append({
        "name": "After Inst 2+3 (caps cleared, stage 0, confirm 0.4)",
        "freshness": 0.95, "accounting": 1.00,
        "stage_readiness": 0.15, "confirmation": 0.40,
        "validated_stage1": True,
        "raw": raw_2_3, "caps": [], "final": raw_2_3,
    })

    # After all instances: stage 1, fresh everything
    raw_all = compute_raw(0.95, 1.00, 0.55, 0.40)
    scenarios.append({
        "name": "After all instances (stage 1, fresh, confirm 0.4)",
        "freshness": 0.95, "accounting": 1.00,
        "stage_readiness": 0.55, "confirmation": 0.40,
        "validated_stage1": True,
        "raw": raw_all, "caps": [], "final": raw_all,
    })

    # Best case: stage 2, full confirmation
    raw_best = compute_raw(1.00, 1.00, 0.80, 0.60)
    scenarios.append({
        "name": "Best case (stage 2, full confirmation)",
        "freshness": 1.00, "accounting": 1.00,
        "stage_readiness": 0.80, "confirmation": 0.60,
        "validated_stage1": True,
        "raw": raw_best, "caps": [], "final": raw_best,
    })

    return scenarios


def main():
    parser = argparse.ArgumentParser(description="ARR confidence score calculator")
    parser.add_argument("--freshness", type=float, default=None)
    parser.add_argument("--accounting", type=float, default=None)
    parser.add_argument("--stage", type=float, default=None)
    parser.add_argument("--confirmation", type=float, default=None)
    parser.add_argument("--validated-stage1", action="store_true", default=False)
    parser.add_argument("--confirmation-fresh", action="store_true", default=True)
    parser.add_argument("--project", choices=["all", "none"], default="none")
    parser.add_argument("--launch-packet", type=str,
                        default="reports/launch_packet_latest.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]

    if args.freshness is not None:
        current = {
            "freshness": args.freshness,
            "accounting": args.accounting or 1.0,
            "stage_readiness": args.stage or 0.10,
            "confirmation": args.confirmation or 0.0,
            "validated_for_live_stage1": args.validated_stage1,
            "confirmation_fresh": args.confirmation_fresh,
        }
    else:
        pkt_path = root / args.launch_packet
        if pkt_path.exists():
            current = load_from_launch_packet(pkt_path)
        else:
            current = {
                "freshness": 0.88, "accounting": 1.00,
                "stage_readiness": 0.10, "confirmation": 0.00,
                "validated_for_live_stage1": False,
                "confirmation_fresh": True,
            }

    raw = compute_raw(current["freshness"], current["accounting"],
                      current["stage_readiness"], current["confirmation"])
    final, caps = apply_caps(raw, current["validated_for_live_stage1"],
                             current["confirmation"],
                             current["confirmation_fresh"])

    print(f"{'='*60}")
    print(f"ARR CONFIDENCE SCORE CALCULATOR")
    print(f"{'='*60}")
    print(f"\nComponents:")
    print(f"  freshness:            {current['freshness']:.2f} x {WEIGHTS['freshness']:.2f} = {current['freshness']*WEIGHTS['freshness']:.4f}")
    print(f"  accounting_coherence: {current['accounting']:.2f} x {WEIGHTS['accounting_coherence']:.2f} = {current['accounting']*WEIGHTS['accounting_coherence']:.4f}")
    print(f"  stage_readiness:      {current['stage_readiness']:.2f} x {WEIGHTS['stage_readiness']:.2f} = {current['stage_readiness']*WEIGHTS['stage_readiness']:.4f}")
    print(f"  confirmation:         {current['confirmation']:.2f} x {WEIGHTS['confirmation_evidence']:.2f} = {current['confirmation']*WEIGHTS['confirmation_evidence']:.4f}")
    print(f"\n  Raw score:            {raw:.4f}")
    print(f"  Caps applied:         {caps if caps else 'None'}")
    print(f"  Final score:          {final:.4f}")
    print(f"  Target (0.60):        {'PASS' if final >= 0.60 else f'NEEDS +{0.60 - final:.4f}'}")

    if args.project == "all":
        print(f"\n{'='*60}")
        print("PROJECTION SCENARIOS")
        print(f"{'='*60}")
        scenarios = project_scenarios(current)
        for s in scenarios:
            status = "PASS" if s["final"] >= 0.60 else "BLOCKED"
            print(f"\n  {s['name']}:")
            print(f"    Components: f={s['freshness']:.2f} a={s['accounting']:.2f} s={s['stage_readiness']:.2f} c={s['confirmation']:.2f}")
            print(f"    Raw: {s['raw']:.4f} | Caps: {s['caps'] or 'None'} | Final: {s['final']:.4f} [{status}]")


if __name__ == "__main__":
    main()
