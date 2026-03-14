#!/usr/bin/env python3
"""
Wallet-Informed Hypothesis Generator — Phase 3 of Wallet Intelligence Pipeline
================================================================================
Bridges wallet intelligence (Phases 1-2) into the existing Elastifund
autoresearch loop. Generates testable trading hypotheses derived from
observed top-wallet behavior patterns.

Integration points:
  - Reads: wallet_leaderboard.json (Phase 1), wallet_fingerprints.json (Phase 2)
  - Writes: hypotheses compatible with btc5_autoresearch_v2.py format
  - Feeds: scripts/run_btc5_autoresearch_cycle_core.py

Each hypothesis is structured as:
  - plain_english: Human-readable description
  - entry_rules: Dict of parameter name -> value
  - market_type: btc5, weather, arb, or other
  - predicted_edge_cents: Expected edge in cents per dollar
  - source_wallets: List of wallet addresses that inspired this hypothesis
  - data_dependency: "backfillable" or "forward_only" (per ChatGPT review)

March 14, 2026 — Elastifund Autoresearch
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("HypothesisGen")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class TradingHypothesis:
    """A testable trading strategy hypothesis."""
    hypothesis_id: str
    plain_english: str
    entry_rules: dict = field(default_factory=dict)
    exit_rules: dict = field(default_factory=dict)
    market_type: str = "btc5"
    predicted_edge_cents: float = 0.0
    confidence: float = 0.0  # 0-1
    source_wallets: list = field(default_factory=list)
    source_cluster: int = -1
    data_dependency: str = "backfillable"  # or "forward_only"
    archetype: str = ""
    generated_at: str = ""
    status: str = "generated"  # generated, backtested, validated, shadow, live


# ---------------------------------------------------------------------------
# Hypothesis templates
# ---------------------------------------------------------------------------
def _generate_early_maker_hypothesis(fingerprints: list[dict],
                                      cluster_id: int) -> list[TradingHypothesis]:
    """Generate hypotheses from early-entry maker wallets."""
    cluster_fps = [fp for fp in fingerprints if fp.get("cluster_id") == cluster_id]
    if not cluster_fps:
        return []

    # Aggregate cluster behavior
    avg_entry_time = sum(
        fp.get("timing", {}).get("avg_seconds_after_open", 150)
        for fp in cluster_fps
    ) / len(cluster_fps)

    avg_entry_price = sum(
        fp.get("positioning", {}).get("avg_entry_price", 0.5)
        for fp in cluster_fps
    ) / len(cluster_fps)

    maker_pct = sum(
        fp.get("positioning", {}).get("inferred_maker_pct", 0.5)
        for fp in cluster_fps
    ) / len(cluster_fps)

    if avg_entry_time > 120 or maker_pct < 0.5:
        return []  # Not an early maker cluster

    hypotheses = []

    # Hypothesis: Post maker order within first N seconds, at specific price level
    hypotheses.append(TradingHypothesis(
        hypothesis_id=f"wh_early_maker_c{cluster_id}_v1",
        plain_english=(
            f"Post maker order within {int(avg_entry_time)}s of window open, "
            f"at price near {avg_entry_price:.2f}. Based on {len(cluster_fps)} "
            f"wallets that enter early and post to the book (maker ratio "
            f"{maker_pct:.0%})."
        ),
        entry_rules={
            "max_seconds_after_open": int(avg_entry_time * 1.2),
            "order_type": "maker",
            "target_price_range": [
                round(avg_entry_price - 0.03, 2),
                round(avg_entry_price + 0.03, 2),
            ],
            "min_book_depth": 2,  # require some liquidity
        },
        exit_rules={
            "hold_to_expiry": True,
        },
        market_type="btc5",
        predicted_edge_cents=round(
            sum(fp.get("positioning", {}).get("avg_fee_adjusted_edge", 0)
                for fp in cluster_fps) / len(cluster_fps) * 100, 2
        ),
        source_wallets=[fp["address"][:12] for fp in cluster_fps],
        source_cluster=cluster_id,
        data_dependency="backfillable",
        archetype="early_maker",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ))

    return hypotheses


def _generate_late_sniper_hypothesis(fingerprints: list[dict],
                                      cluster_id: int) -> list[TradingHypothesis]:
    """Generate hypotheses from late-entry sniper wallets."""
    cluster_fps = [fp for fp in fingerprints if fp.get("cluster_id") == cluster_id]
    if not cluster_fps:
        return []

    avg_last_60s = sum(
        fp.get("timing", {}).get("trades_in_last_60s", 0)
        for fp in cluster_fps
    ) / len(cluster_fps)

    avg_first_60s = sum(
        fp.get("timing", {}).get("trades_in_first_60s", 0)
        for fp in cluster_fps
    ) / len(cluster_fps)

    if avg_last_60s <= avg_first_60s:
        return []  # Not a late sniper cluster

    hypotheses = []

    # Hypothesis: Wait until last 60s, then take based on BTC price vs strike
    hypotheses.append(TradingHypothesis(
        hypothesis_id=f"wh_late_sniper_c{cluster_id}_v1",
        plain_english=(
            f"Wait until final 60 seconds of window. Place taker order when "
            f"BTC spot is clearly above/below the strike, capturing convergence "
            f"to settlement. Based on {len(cluster_fps)} wallets that "
            f"concentrate activity in the last minute."
        ),
        entry_rules={
            "min_seconds_after_open": 240,  # last 60s of 5-min window
            "order_type": "taker",
            "min_price_distance_from_50": 0.15,  # only enter when outcome clear
            "max_spread": 0.03,
        },
        exit_rules={
            "hold_to_expiry": True,
        },
        market_type="btc5",
        predicted_edge_cents=2.0,  # convergence edge
        source_wallets=[fp["address"][:12] for fp in cluster_fps],
        source_cluster=cluster_id,
        data_dependency="forward_only",  # needs real-time BTC price
        archetype="late_sniper",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ))

    return hypotheses


def _generate_momentum_hypothesis(fingerprints: list[dict],
                                   cluster_id: int) -> list[TradingHypothesis]:
    """Generate hypotheses from directional/momentum wallets."""
    cluster_fps = [fp for fp in fingerprints if fp.get("cluster_id") == cluster_id]
    if not cluster_fps:
        return []

    avg_bias = sum(
        fp.get("direction", {}).get("bias_score", 0)
        for fp in cluster_fps
    ) / len(cluster_fps)

    avg_momentum_corr = sum(
        fp.get("direction", {}).get("momentum_correlation", 0)
        for fp in cluster_fps
    ) / len(cluster_fps)

    if abs(avg_bias) < 0.3:
        return []  # Not directional enough

    hypotheses = []
    direction = "UP" if avg_bias > 0 else "DOWN"

    if abs(avg_momentum_corr) > 0.1:
        strategy_type = "momentum" if avg_momentum_corr > 0 else "mean_reversion"

        hypotheses.append(TradingHypothesis(
            hypothesis_id=f"wh_{strategy_type}_c{cluster_id}_v1",
            plain_english=(
                f"{strategy_type.replace('_', ' ').title()} strategy: "
                f"{'Follow' if strategy_type == 'momentum' else 'Fade'} "
                f"the prior 5-minute BTC move. Preferred direction: {direction}. "
                f"BTC return correlation: {avg_momentum_corr:.3f}. "
                f"Based on {len(cluster_fps)} wallets."
            ),
            entry_rules={
                "direction": direction,
                "strategy": strategy_type,
                "min_btc_5m_return": 0.001 if strategy_type == "momentum" else -0.001,
                "max_btc_5m_return": 0.01 if strategy_type == "momentum" else -0.0001,
                "order_type": "maker",
            },
            exit_rules={
                "hold_to_expiry": True,
            },
            market_type="btc5",
            predicted_edge_cents=1.5,
            source_wallets=[fp["address"][:12] for fp in cluster_fps],
            source_cluster=cluster_id,
            data_dependency="forward_only",  # needs real-time BTC price
            archetype=strategy_type,
            generated_at=datetime.now(timezone.utc).isoformat(),
        ))

    return hypotheses


def _generate_session_specialist_hypothesis(
    fingerprints: list[dict], cluster_id: int
) -> list[TradingHypothesis]:
    """Generate hypotheses from session-specific trading patterns."""
    cluster_fps = [fp for fp in fingerprints if fp.get("cluster_id") == cluster_id]
    if not cluster_fps:
        return []

    # Find dominant session
    session_totals = {}
    for fp in cluster_fps:
        dist = fp.get("timing", {}).get("session_distribution", {})
        for session, pct in dist.items():
            session_totals[session] = session_totals.get(session, 0) + pct

    if not session_totals:
        return []

    dominant_session = max(session_totals, key=session_totals.get)
    concentration = session_totals[dominant_session] / sum(session_totals.values())

    if concentration < 0.5:
        return []  # Not session-concentrated enough

    hypotheses = []
    hypotheses.append(TradingHypothesis(
        hypothesis_id=f"wh_session_{dominant_session}_c{cluster_id}_v1",
        plain_english=(
            f"Trade only during {dominant_session} session "
            f"({concentration:.0%} of top-wallet activity concentrated here). "
            f"Based on {len(cluster_fps)} wallets that specialize in this "
            f"time window."
        ),
        entry_rules={
            "required_session": dominant_session,
            "session_concentration_threshold": 0.5,
        },
        exit_rules={
            "hold_to_expiry": True,
        },
        market_type="btc5",
        predicted_edge_cents=1.0,
        source_wallets=[fp["address"][:12] for fp in cluster_fps],
        source_cluster=cluster_id,
        data_dependency="backfillable",
        archetype="session_specialist",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ))

    return hypotheses


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate_hypotheses(
    leaderboard_path: Path,
    fingerprints_path: Path,
    kill_list_path: Optional[Path] = None,
) -> list[TradingHypothesis]:
    """
    Generate trading hypotheses from wallet intelligence data.

    Reads Phase 1 leaderboard and Phase 2 fingerprints, applies template
    generators per cluster archetype, filters against kill list.
    """
    # Load inputs
    with open(leaderboard_path) as f:
        leaderboard = json.load(f)

    with open(fingerprints_path) as f:
        fp_data = json.load(f)

    fingerprints = fp_data.get("fingerprints", [])
    if not fingerprints:
        logger.warning("No fingerprints found")
        return []

    # Load kill list (hypotheses that have already been tested and rejected)
    killed_ids = set()
    if kill_list_path and kill_list_path.exists():
        with open(kill_list_path) as f:
            kill_list = json.load(f)
        killed_ids = {k.get("hypothesis_id") for k in kill_list if k.get("hypothesis_id")}

    # Find unique clusters
    cluster_ids = set(fp.get("cluster_id", -1) for fp in fingerprints)
    logger.info(f"Found {len(cluster_ids)} wallet clusters from "
                f"{len(fingerprints)} fingerprints")

    # Generate hypotheses per cluster using all templates
    all_hypotheses = []
    generators = [
        _generate_early_maker_hypothesis,
        _generate_late_sniper_hypothesis,
        _generate_momentum_hypothesis,
        _generate_session_specialist_hypothesis,
    ]

    for cluster_id in cluster_ids:
        for generator in generators:
            hypotheses = generator(fingerprints, cluster_id)
            for h in hypotheses:
                if h.hypothesis_id not in killed_ids:
                    all_hypotheses.append(h)
                else:
                    logger.info(f"Skipping killed hypothesis: {h.hypothesis_id}")

    logger.info(f"Generated {len(all_hypotheses)} hypotheses "
                f"({len(killed_ids)} killed)")

    # Export
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_leaderboard": str(leaderboard_path),
        "source_fingerprints": str(fingerprints_path),
        "hypotheses_count": len(all_hypotheses),
        "hypotheses": [asdict(h) for h in all_hypotheses],
    }

    output_path = fingerprints_path.parent / "wallet_hypotheses.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Hypotheses written to {output_path}")
    return all_hypotheses


# ---------------------------------------------------------------------------
# Autoresearch integration: convert to btc5_autoresearch_v2 format
# ---------------------------------------------------------------------------
def convert_to_autoresearch_candidates(
    hypotheses: list[TradingHypothesis],
) -> list[dict]:
    """
    Convert wallet-derived hypotheses into the format expected by
    btc5_autoresearch_v2.py and run_btc5_autoresearch_cycle_core.py.

    Returns list of dicts with fields:
      - package_id: str
      - params: dict (runtime profile overrides)
      - source: "wallet_intelligence"
      - hypothesis_text: str
    """
    candidates = []
    for h in hypotheses:
        # Map hypothesis entry rules to runtime profile params
        params = {}

        # Direction mapping
        if "direction" in h.entry_rules:
            direction = h.entry_rules["direction"]
            if direction == "UP":
                params["btc5_directional_mode"] = "up_only"
            elif direction == "DOWN":
                params["btc5_directional_mode"] = "down_only"

        # Timing mapping
        if "min_seconds_after_open" in h.entry_rules:
            params["btc5_min_window_age_seconds"] = h.entry_rules["min_seconds_after_open"]
        if "max_seconds_after_open" in h.entry_rules:
            params["btc5_max_window_age_seconds"] = h.entry_rules["max_seconds_after_open"]

        # Price mapping
        if "target_price_range" in h.entry_rules:
            lo, hi = h.entry_rules["target_price_range"]
            params["btc5_min_buy_price"] = lo
            params["btc5_max_buy_price"] = hi

        # Session mapping
        if "required_session" in h.entry_rules:
            params["btc5_required_session"] = h.entry_rules["required_session"]

        candidates.append({
            "package_id": h.hypothesis_id,
            "params": params,
            "source": "wallet_intelligence",
            "hypothesis_text": h.plain_english,
            "predicted_edge_cents": h.predicted_edge_cents,
            "data_dependency": h.data_dependency,
            "archetype": h.archetype,
        })

    return candidates


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Wallet-Informed Hypothesis Generator")
    parser.add_argument("--leaderboard", type=str,
                        default="data/wallet_leaderboard.json")
    parser.add_argument("--fingerprints", type=str,
                        default="data/wallet_fingerprints.json")
    parser.add_argument("--kill-list", type=str, default=None)

    args = parser.parse_args()

    hypotheses = generate_hypotheses(
        Path(args.leaderboard),
        Path(args.fingerprints),
        Path(args.kill_list) if args.kill_list else None,
    )

    if hypotheses:
        print(f"\nGenerated {len(hypotheses)} hypotheses:")
        for h in hypotheses:
            print(f"\n  [{h.hypothesis_id}] ({h.archetype})")
            print(f"    {h.plain_english[:100]}...")
            print(f"    Edge: {h.predicted_edge_cents}c | "
                  f"Data: {h.data_dependency} | "
                  f"Wallets: {len(h.source_wallets)}")

        # Convert and show autoresearch candidates
        candidates = convert_to_autoresearch_candidates(hypotheses)
        print(f"\n{len(candidates)} candidates ready for autoresearch loop")
