#!/usr/bin/env python3
"""Mid-sprint audit: compare old score vs new velocity-adjusted score.

Prints top 20 candidates showing:
- Old score (raw edge)
- New score (velocity-adjusted EV with capital lock-up penalty)
- Which markets got filtered/blocked by the penalty

Usage:
    python -m scripts.audit_velocity_scores [--max-days 14] [--top 20]

Requires ANTHROPIC_API_KEY in .env (or set in environment) for live scan,
but can also run with mock data for audit purposes.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.resolution_estimator import (
    capital_velocity_penalty,
    capital_velocity_score,
    velocity_adjusted_ev,
)
from src.scanner import MarketScanner


async def run_audit(max_days: float = 14.0, top_n: int = 20) -> None:
    """Scan live markets and compare old vs new scoring."""
    scanner = MarketScanner()
    print(f"\n{'='*90}")
    print(f"  CAPITAL VELOCITY AUDIT — max_days={max_days}, top_n={top_n}")
    print(f"{'='*90}\n")

    print("Fetching live markets from Gamma API...")
    try:
        opportunities = await scanner.scan_for_opportunities(
            min_volume=500.0, min_liquidity=200.0
        )
    except Exception as e:
        print(f"ERROR: Could not fetch markets: {e}")
        return
    finally:
        await scanner.close()

    if not opportunities:
        print("No opportunities found.")
        return

    print(f"Found {len(opportunities)} liquid opportunities.\n")

    # Simulate edge values (mock, since we can't call Claude without API key)
    # Use a range of realistic edges for demonstration
    import random
    random.seed(42)

    candidates = []
    for opp in opportunities:
        # Assign a mock edge for audit purposes (5-25% range)
        mock_edge = random.uniform(0.05, 0.25)
        est_days = opp.get("estimated_days", 14.0)
        bucket = opp.get("resolution_bucket", "?")

        # Old score: raw edge only (no velocity adjustment)
        old_score = mock_edge

        # New score: velocity-adjusted EV with penalty
        ev_info = velocity_adjusted_ev(
            edge=mock_edge,
            estimated_days=est_days,
            taker_fee=0.0,
            max_days=max_days,
        )

        candidates.append({
            "question": opp.get("question", "?")[:65],
            "market_id": opp.get("market_id", "?")[:12],
            "est_days": est_days,
            "bucket": bucket,
            "old_score": old_score,
            "new_score": ev_info["adjusted_ev"],
            "penalty": ev_info["penalty"],
            "blocked": ev_info["blocked"],
        })

    # Sort by old score descending for comparison
    candidates.sort(key=lambda c: c["old_score"], reverse=True)
    top = candidates[:top_n]

    # Print table header
    print(f"{'#':>2}  {'Question':<65}  {'Est Days':>8}  {'Bucket':>6}  "
          f"{'Old Edge':>9}  {'Penalty':>7}  {'New AdjEV':>9}  {'Status':>8}")
    print("-" * 140)

    blocked_count = 0
    penalized_count = 0
    for i, c in enumerate(top, 1):
        if c["blocked"]:
            status = "BLOCKED"
            blocked_count += 1
        elif c["penalty"] < 1.0:
            status = "PENALTY"
            penalized_count += 1
        else:
            status = "OK"

        print(
            f"{i:>2}  {c['question']:<65}  {c['est_days']:>8.1f}  {c['bucket']:>6}  "
            f"{c['old_score']:>8.1%}  {c['penalty']:>7.2f}  {c['new_score']:>9.1f}  {status:>8}"
        )

    # Summary
    print(f"\n{'='*90}")
    print(f"  SUMMARY")
    print(f"  Total candidates: {len(candidates)}")
    print(f"  Shown: {len(top)}")
    print(f"  Blocked by velocity filter: {sum(1 for c in candidates if c['blocked'])}/{len(candidates)}")
    print(f"  Penalized (penalty < 1.0): {sum(1 for c in candidates if not c['blocked'] and c['penalty'] < 1.0)}/{len(candidates)}")
    print(f"  Passed clean (penalty = 1.0): {sum(1 for c in candidates if c['penalty'] == 1.0)}/{len(candidates)}")
    print(f"{'='*90}\n")

    # Rank comparison: show which markets change rank most
    old_ranked = sorted(candidates, key=lambda c: c["old_score"], reverse=True)
    new_ranked = sorted(
        [c for c in candidates if not c["blocked"]],
        key=lambda c: c["new_score"],
        reverse=True,
    )

    old_rank_map = {c["market_id"]: i for i, c in enumerate(old_ranked)}
    new_rank_map = {c["market_id"]: i for i, c in enumerate(new_ranked)}

    print("  BIGGEST RANK CHANGES (old rank → new rank):")
    changes = []
    for mid, old_r in old_rank_map.items():
        new_r = new_rank_map.get(mid)
        if new_r is not None:
            changes.append((mid, old_r, new_r, new_r - old_r))
        else:
            changes.append((mid, old_r, None, 999))

    changes.sort(key=lambda x: abs(x[3]), reverse=True)
    for mid, old_r, new_r, delta in changes[:10]:
        q = next((c["question"] for c in candidates if c["market_id"] == mid), "?")
        if new_r is None:
            print(f"    {q[:55]}  #{old_r+1} → BLOCKED")
        else:
            arrow = "↑" if delta < 0 else "↓" if delta > 0 else "="
            print(f"    {q[:55]}  #{old_r+1} → #{new_r+1} ({arrow}{abs(delta)})")

    print()


def main():
    parser = argparse.ArgumentParser(description="Audit velocity scoring")
    parser.add_argument("--max-days", type=float, default=14.0,
                       help="Max days before penalty (default: 14)")
    parser.add_argument("--top", type=int, default=20,
                       help="Number of top candidates to show (default: 20)")
    args = parser.parse_args()

    asyncio.run(run_audit(max_days=args.max_days, top_n=args.top))


if __name__ == "__main__":
    main()
