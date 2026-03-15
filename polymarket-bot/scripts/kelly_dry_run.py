#!/usr/bin/env python3
"""Kelly sizing dry-run: 1-cycle audit printout.

Prints: candidate → p_true_raw → p_true_cal → fee → kelly_f → usd_size → decision

Usage:
    python -m scripts.kelly_dry_run
    # or from repo root:
    python scripts/kelly_dry_run.py
"""
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.risk.sizing import compute_sizing, SizingCaps, kelly_fraction, expected_edge_after_fee

# ── Configuration ──────────────────────────────────────────
BANKROLL = float(os.environ.get("BANKROLL", "75.0"))
FEE_RATE = float(os.environ.get("FEE_RATE", "0.02"))
MIN_EDGE_BUFFER = float(os.environ.get("MIN_EDGE_BUFFER", "0.005"))
MAX_POSITION_USD = float(os.environ.get("MAX_POSITION_USD", "10.0"))

# Simulated candidates: (market_id, question, p_market, p_estimated_raw, side, category)
CANDIDATES = [
    ("m001", "Will Trump win 2028 GOP primary?", 0.45, 0.72, "buy_yes", "Politics"),
    ("m002", "Bitcoin above $100K by June?", 0.65, 0.40, "buy_no", "Crypto"),
    ("m003", "Fed rate cut in March?", 0.30, 0.35, "buy_yes", "Fed Rates"),
    ("m004", "NYC snow > 6 inches this week?", 0.25, 0.60, "buy_yes", "Weather"),
    ("m005", "Lakers win NBA championship?", 0.12, 0.08, "buy_no", "Sports"),
    ("m006", "Ukraine ceasefire by April?", 0.20, 0.10, "buy_no", "Geopolitical"),
    ("m007", "S&P 500 above 6000 end of March?", 0.55, 0.70, "buy_yes", "Economic"),
    ("m008", "Will it rain in Miami tomorrow?", 0.40, 0.75, "buy_yes", "Weather"),
    ("m009", "US unemployment below 4%?",  0.60, 0.58, "buy_yes", "Economic"),
    ("m010", "Ethereum merge v2 by Q2?", 0.35, 0.20, "buy_no", "Crypto"),
]

# Simulate some open positions for category concentration test
OPEN_CATEGORY_COUNTS = {
    "Politics": 2,
    "Crypto": 4,  # >3 → haircut
    "Weather": 1,
    "Economic": 5,  # >3 → haircut
}


def run_dry_run():
    caps = SizingCaps(
        max_position_usd=MAX_POSITION_USD,
        min_edge_buffer=MIN_EDGE_BUFFER,
        fee_rate=FEE_RATE,
    )

    print("=" * 120)
    print(f"KELLY SIZING DRY RUN — Bankroll: ${BANKROLL:.2f} | Fee: {FEE_RATE:.1%} | Min Edge Buffer: {MIN_EDGE_BUFFER:.3f}")
    print(f"Open category counts: {OPEN_CATEGORY_COUNTS}")
    print("=" * 120)
    print()
    print(
        f"{'ID':<6} {'Question':<40} {'Side':<8} {'p_mkt':>6} {'p_est':>6} "
        f"{'Edge%':>6} {'EdgeFee':>8} {'KellyF':>8} {'Mult':>5} {'$Raw':>7} "
        f"{'Haircut':>7} {'$Size':>7} {'Decision':<10} {'Reason'}"
    )
    print("-" * 120)

    trades = 0
    skips = 0

    for mid, question, p_mkt, p_est, side, category in CANDIDATES:
        r = compute_sizing(
            market_id=mid,
            p_estimated=p_est,
            p_market=p_mkt,
            side=side,
            bankroll=BANKROLL,
            category=category,
            category_counts=OPEN_CATEGORY_COUNTS,
            caps=caps,
        )

        edge_pct = r.edge_raw * 100
        haircut_str = "YES" if r.category_haircut else "no"
        decision_marker = ">>> TRADE" if r.decision == "trade" else "    skip"
        reason = r.skip_reason if r.decision == "skip" else ""

        print(
            f"{mid:<6} {question[:38]:<40} {side:<8} {p_mkt:>6.2f} {p_est:>6.2f} "
            f"{edge_pct:>5.1f}% {r.edge_after_fee:>+7.4f} {r.kelly_f:>8.4f} "
            f"{r.kelly_mult:>5.2f} {r.raw_size_usd:>6.2f} "
            f"{haircut_str:>7} {r.final_size_usd:>6.2f} {decision_marker:<10} {reason}"
        )

        if r.decision == "trade":
            trades += 1
        else:
            skips += 1

    print("-" * 120)
    print(f"Summary: {trades} trades, {skips} skips out of {len(CANDIDATES)} candidates")
    total_deployed = sum(
        compute_sizing(
            market_id=mid, p_estimated=p_est, p_market=p_mkt, side=side,
            bankroll=BANKROLL, category=cat, category_counts=OPEN_CATEGORY_COUNTS, caps=caps,
        ).final_size_usd
        for mid, _, p_mkt, p_est, side, cat in CANDIDATES
    )
    print(f"Total capital to deploy: ${total_deployed:.2f} / ${BANKROLL:.2f} bankroll ({total_deployed/BANKROLL*100:.1f}%)")
    print()

    # ── Bankroll scaling demo ──
    print("=" * 80)
    print("BANKROLL SCALING DEMO (buy_yes, p_est=0.70, p_mkt=0.45)")
    print("=" * 80)
    for br in [50, 100, 150, 300, 500, 1000]:
        r = compute_sizing(
            market_id="demo", p_estimated=0.70, p_market=0.45, side="buy_yes",
            bankroll=float(br), caps=caps,
        )
        print(f"  Bankroll ${br:>6} → mult={r.kelly_mult:.2f}  kelly_f={r.kelly_f:.4f}  size=${r.final_size_usd:.2f}")

    print()
    print("=" * 80)
    print("ASYMMETRIC YES/NO DEMO (bankroll=$200, p_est=0.70, p_mkt=0.45)")
    print("=" * 80)
    for side in ["buy_yes", "buy_no"]:
        p_est = 0.70 if side == "buy_yes" else 0.30
        r = compute_sizing(
            market_id="demo", p_estimated=p_est, p_market=0.45, side=side,
            bankroll=200.0, caps=caps,
        )
        print(f"  {side:<8} → mult={r.kelly_mult:.2f}  kelly_f={r.kelly_f:.4f}  size=${r.final_size_usd:.2f}")


if __name__ == "__main__":
    run_dry_run()
