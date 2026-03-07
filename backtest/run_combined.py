#!/usr/bin/env python3
"""Combined backtest re-run — single source of truth metrics.

Runs baseline, calibrated, calibrated+selective, NO-only, and top variants
in one deterministic pass.  Applies taker fees via fee(p) = p*(1-p)*r with
configurable r.  Produces:
    backtest/results/combined_results.json   (machine-readable)
    backtest/results/combined_results.md     (human-readable summary)

Usage:
    python backtest/run_combined.py                    # defaults
    python backtest/run_combined.py --fee-rate 0.02    # custom fee rate
    python backtest/run_combined.py --entry 0.50       # custom entry price
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BACKTEST_DIR, "data")
RESULTS_DIR = os.path.join(BACKTEST_DIR, "results")

RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# Category classifier (simple keyword match)
# ---------------------------------------------------------------------------
SKIP_CATEGORIES = {"crypto", "sports", "fed_rates"}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
               "dogecoin", "doge", "nft", "defi", "blockchain", "coinbase",
               "binance", "altcoin", "token"],
    "sports": ["nba", "nfl", "mlb", "nhl", "premier league", "champions league",
               "world cup", "super bowl", "playoff", "mvp", "touchdown",
               "slam dunk", "home run", "la liga", "serie a", "bundesliga",
               "ufc", "boxing", "tennis", "golf", "f1", "formula 1"],
    "fed_rates": ["federal reserve", "fed rate", "fed funds", "fomc",
                  "interest rate cut", "interest rate hike", "basis points"],
    "politics": ["president", "election", "congress", "senate", "democrat",
                 "republican", "vote", "primary", "governor", "mayor",
                 "supreme court", "impeach", "legislation", "ballot"],
    "weather": ["temperature", "rain", "snow", "weather", "hurricane",
                "tornado", "flood", "heat wave", "cold front", "noaa"],
}


def classify_market(question: str) -> str:
    """Return best-guess category for a market question."""
    q = question.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return cat
    return "other"


# ---------------------------------------------------------------------------
# Taker fee model
# ---------------------------------------------------------------------------

def taker_fee(p: float, r: float) -> float:
    """Polymarket taker fee: fee(p) = p * (1 - p) * r.

    Parameters
    ----------
    p : float
        Market probability (0-1) at which the trade is executed.
    r : float
        Fee rate parameter (e.g., 0.02 = 2%).

    Returns
    -------
    float
        Fee as a fraction of notional.
    """
    return p * (1.0 - p) * r


# ---------------------------------------------------------------------------
# Calibration (re-use existing, import-safe)
# ---------------------------------------------------------------------------

def _build_calibrator():
    """Build CalibrationV2 from cached data, deterministic."""
    sys.path.insert(0, BACKTEST_DIR)
    from calibration import CalibrationV2, load_calibration_samples

    samples = load_calibration_samples()
    cal = CalibrationV2(method="auto", seed=RANDOM_SEED)
    cal.fit_from_data(samples)
    return cal


# ---------------------------------------------------------------------------
# Data loading with integrity hash
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_data() -> tuple[list[dict], dict, dict[str, str]]:
    """Load markets + cache, return (markets, cache, hashes)."""
    markets_path = os.path.join(DATA_DIR, "historical_markets.json")
    cache_path = os.path.join(DATA_DIR, "claude_cache.json")

    if not os.path.exists(markets_path):
        raise FileNotFoundError(f"Missing {markets_path}. Run collector first.")
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"Missing {cache_path}. Run backtest engine first.")

    hashes = {
        "historical_markets.json": _sha256_file(markets_path),
        "claude_cache.json": _sha256_file(cache_path),
    }

    with open(markets_path) as f:
        markets = json.load(f)["markets"]
    with open(cache_path) as f:
        cache = json.load(f)

    return markets, cache, hashes


def _cache_key(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Strategy simulation
# ---------------------------------------------------------------------------

@dataclass
class VariantConfig:
    """Configuration for a strategy variant."""
    name: str
    yes_threshold: float = 0.05
    no_threshold: float = 0.05
    entry_price: float = 0.50
    size: float = 2.0
    use_calibration: bool = False
    no_only: bool = False
    use_category_filter: bool = False
    fee_rate: float = 0.0
    use_confidence_sizing: bool = False


@dataclass
class TradeRecord:
    question: str
    direction: str
    entry_price: float
    claude_prob: float
    calibrated_prob: Optional[float]
    actual_outcome: str
    won: bool
    size: float
    gross_pnl: float
    fee: float
    net_pnl: float
    edge: float
    category: str


def simulate_variant(
    markets: list[dict],
    cache: dict,
    config: VariantConfig,
    calibrator=None,
) -> dict:
    """Run a single variant.  Returns a results dict with all required keys."""

    rng = random.Random(RANDOM_SEED)  # deterministic if any randomness needed

    trades: list[TradeRecord] = []
    brier_scores: list[float] = []
    markets_eligible = 0
    markets_filtered = 0

    for m in markets:
        question = m["question"]
        actual = m["actual_outcome"]
        key = _cache_key(question)
        est = cache.get(key)
        if not est:
            continue

        raw_prob = est["probability"]
        category = classify_market(question)

        # Category filter
        if config.use_category_filter and category in SKIP_CATEGORIES:
            markets_filtered += 1
            continue

        markets_eligible += 1

        # Calibrate
        if config.use_calibration and calibrator is not None:
            cal_prob = calibrator.correct(raw_prob)
        else:
            cal_prob = raw_prob

        # Brier on the prob that will drive decisions
        actual_binary = 1.0 if actual == "YES_WON" else 0.0
        brier_scores.append((cal_prob - actual_binary) ** 2)

        # Edge & direction
        entry = config.entry_price
        edge = cal_prob - entry

        if edge > 0:
            direction = "buy_yes"
            abs_edge = edge
            if abs_edge < config.yes_threshold:
                continue
        else:
            direction = "buy_no"
            abs_edge = abs(edge)
            if abs_edge < config.no_threshold:
                continue

        # NO-only filter
        if config.no_only and direction == "buy_yes":
            continue

        # Confidence sizing
        trade_size = config.size
        if config.use_confidence_sizing and calibrator is not None:
            mult = calibrator.get_sizing_multiplier(raw_prob)
            trade_size = config.size * mult

        # Resolve trade
        if direction == "buy_yes":
            won = actual == "YES_WON"
            gross_pnl = (trade_size / entry) - trade_size if won else -trade_size
        else:
            no_price = 1.0 - entry
            won = actual == "NO_WON"
            gross_pnl = (trade_size / no_price) - trade_size if won else -trade_size

        # Taker fee (applied to entry notional)
        fee_amount = taker_fee(entry, config.fee_rate) * trade_size
        net_pnl = gross_pnl - fee_amount

        trades.append(TradeRecord(
            question=question,
            direction=direction,
            entry_price=entry,
            claude_prob=raw_prob,
            calibrated_prob=cal_prob if config.use_calibration else None,
            actual_outcome=actual,
            won=won,
            size=trade_size,
            gross_pnl=gross_pnl,
            fee=fee_amount,
            net_pnl=net_pnl,
            edge=abs_edge,
            category=category,
        ))

    # ---- Compute summary metrics ----
    n = len(trades)
    if n == 0:
        return _empty_result(config.name, markets_eligible, markets_filtered)

    wins = sum(1 for t in trades if t.won)
    win_rate = wins / n

    total_gross = sum(t.gross_pnl for t in trades)
    total_fees = sum(t.fee for t in trades)
    total_net = sum(t.net_pnl for t in trades)
    avg_net = total_net / n

    # Drawdown (on net P&L stream)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t.net_pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    # Sharpe (daily, annualized, assume 5 trades/day)
    pnls = [t.net_pnl for t in trades]
    pnl_std = float(np.std(pnls)) if n > 1 else 1.0
    sharpe = (avg_net / pnl_std) * math.sqrt(252 * 5) if pnl_std > 0 else 0.0

    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else 0.5

    # Direction breakdown
    yes_trades = [t for t in trades if t.direction == "buy_yes"]
    no_trades = [t for t in trades if t.direction == "buy_no"]
    yes_wr = (sum(1 for t in yes_trades if t.won) / len(yes_trades)) if yes_trades else 0.0
    no_wr = (sum(1 for t in no_trades if t.won) / len(no_trades)) if no_trades else 0.0

    # ARR at several frequencies
    def arr(tpd: int, capital: float = 75.0, infra: float = 20.0) -> float:
        monthly_net = (avg_net * tpd * 30) - infra
        return (monthly_net * 12 / capital) * 100

    return {
        "variant": config.name,
        "markets_eligible": markets_eligible,
        "markets_filtered_by_category": markets_filtered,
        "trades": n,
        "wins": wins,
        "win_rate": round(win_rate, 4),
        "total_gross_pnl": round(total_gross, 2),
        "total_fees": round(total_fees, 2),
        "total_net_pnl": round(total_net, 2),
        "avg_net_pnl": round(avg_net, 4),
        "max_drawdown": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "brier": round(avg_brier, 4),
        "yes_trades": len(yes_trades),
        "yes_win_rate": round(yes_wr, 4),
        "no_trades": len(no_trades),
        "no_win_rate": round(no_wr, 4),
        "arr_3": round(arr(3), 0),
        "arr_5": round(arr(5), 0),
        "arr_8": round(arr(8), 0),
    }


def _empty_result(name: str, eligible: int, filtered: int) -> dict:
    return {
        "variant": name,
        "markets_eligible": eligible,
        "markets_filtered_by_category": filtered,
        "trades": 0, "wins": 0, "win_rate": 0.0,
        "total_gross_pnl": 0.0, "total_fees": 0.0, "total_net_pnl": 0.0,
        "avg_net_pnl": 0.0, "max_drawdown": 0.0, "sharpe": 0.0,
        "brier": 0.0,
        "yes_trades": 0, "yes_win_rate": 0.0,
        "no_trades": 0, "no_win_rate": 0.0,
        "arr_3": 0, "arr_5": 0, "arr_8": 0,
    }


# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

def build_variants(entry: float, fee_rate: float) -> list[VariantConfig]:
    """Define the canonical set of variants."""
    return [
        VariantConfig(
            name="Baseline (5% symmetric)",
            entry_price=entry, fee_rate=fee_rate,
        ),
        VariantConfig(
            name="Baseline + Fees Only",
            entry_price=entry, fee_rate=fee_rate,
        ),
        VariantConfig(
            name="NO-only",
            entry_price=entry, fee_rate=fee_rate,
            no_only=True,
        ),
        VariantConfig(
            name="Calibrated (5% symmetric)",
            entry_price=entry, fee_rate=fee_rate,
            use_calibration=True,
        ),
        VariantConfig(
            name="Calibrated + Asymmetric (YES 15%, NO 5%)",
            entry_price=entry, fee_rate=fee_rate,
            use_calibration=True,
            yes_threshold=0.15, no_threshold=0.05,
        ),
        VariantConfig(
            name="Calibrated + NO-only",
            entry_price=entry, fee_rate=fee_rate,
            use_calibration=True, no_only=True,
        ),
        VariantConfig(
            name="Calibrated + Selective (Cat Filter + Asym)",
            entry_price=entry, fee_rate=fee_rate,
            use_calibration=True,
            use_category_filter=True,
            yes_threshold=0.15, no_threshold=0.05,
        ),
        VariantConfig(
            name="Calibrated + Confidence Sizing",
            entry_price=entry, fee_rate=fee_rate,
            use_calibration=True,
            use_confidence_sizing=True,
        ),
        VariantConfig(
            name="Cal + Asym + Confidence + CatFilter",
            entry_price=entry, fee_rate=fee_rate,
            use_calibration=True,
            use_category_filter=True,
            yes_threshold=0.15, no_threshold=0.05,
            use_confidence_sizing=True,
        ),
        VariantConfig(
            name="High Threshold (10% symmetric)",
            entry_price=entry, fee_rate=fee_rate,
            yes_threshold=0.10, no_threshold=0.10,
        ),
    ]


# ---------------------------------------------------------------------------
# Output generators
# ---------------------------------------------------------------------------

def generate_json(results: list[dict], meta: dict) -> dict:
    """Build the combined_results.json payload."""
    return {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": RANDOM_SEED,
        "parameters": meta,
        "variants": results,
    }


def generate_markdown(payload: dict) -> str:
    """Build human-readable combined_results.md from JSON payload."""
    lines: list[str] = []
    meta = payload["parameters"]
    variants = payload["variants"]

    lines.append("# Combined Backtest Results")
    lines.append("")
    lines.append(f"**Generated:** {payload['run_at']}")
    lines.append(f"**Seed:** {payload['seed']}")
    lines.append(f"**Entry Price:** {meta['entry_price']}")
    lines.append(f"**Fee Rate (r):** {meta['fee_rate']}")
    lines.append(f"**Markets in dataset:** {meta['total_markets']}")
    lines.append(f"**Input hashes:** markets={meta['hashes']['historical_markets.json'][:12]}... "
                 f"cache={meta['hashes']['claude_cache.json'][:12]}...")
    lines.append("")

    # Summary table
    lines.append("## Strategy Comparison")
    lines.append("")
    header = (
        f"| {'Variant':<45s} | {'Trades':>6s} | {'Win%':>6s} | "
        f"{'GrossPnL':>9s} | {'Fees':>6s} | {'NetPnL':>9s} | "
        f"{'AvgNet':>8s} | {'MaxDD':>6s} | {'Sharpe':>6s} | "
        f"{'Brier':>6s} | {'YES_WR':>6s} | {'NO_WR':>6s} | {'ARR@5':>7s} |"
    )
    lines.append(header)
    sep = "|" + "|".join(["-" * 47] + ["-" * 8] * 2 + ["-" * 11] + ["-" * 8] + ["-" * 11] +
                         ["-" * 10, "-" * 8, "-" * 8, "-" * 8, "-" * 8, "-" * 8, "-" * 9]) + "|"
    lines.append(sep)

    for v in variants:
        lines.append(
            f"| {v['variant']:<45s} | {v['trades']:>6d} | {v['win_rate']:>5.1%} | "
            f"${v['total_gross_pnl']:>8.2f} | ${v['total_fees']:>5.2f} | "
            f"${v['total_net_pnl']:>8.2f} | "
            f"${v['avg_net_pnl']:>7.4f} | ${v['max_drawdown']:>5.2f} | "
            f"{v['sharpe']:>6.2f} | "
            f"{v['brier']:>6.4f} | {v['yes_win_rate']:>5.1%} | "
            f"{v['no_win_rate']:>5.1%} | {v['arr_5']:>+6.0f}% |"
        )
    lines.append("")

    # Best variant
    best = max(variants, key=lambda v: v["arr_5"])
    lines.append("## Best Variant")
    lines.append("")
    lines.append(f"**{best['variant']}**")
    lines.append(f"- Win Rate: {best['win_rate']:.1%}")
    lines.append(f"- Net P&L: ${best['total_net_pnl']:+.2f}")
    lines.append(f"- Sharpe: {best['sharpe']:.2f}")
    lines.append(f"- ARR @5/day: {best['arr_5']:+.0f}%")
    lines.append("")

    # Fee impact
    if meta["fee_rate"] > 0:
        baseline = next((v for v in variants if "Baseline" in v["variant"] and "Fees" not in v["variant"]), None)
        if baseline:
            lines.append("## Fee Impact")
            lines.append("")
            lines.append(f"- Total fees across baseline: ${baseline['total_fees']:.2f}")
            lines.append(f"- Fee as % of gross P&L: "
                         f"{(baseline['total_fees'] / baseline['total_gross_pnl'] * 100):.1f}%"
                         if baseline['total_gross_pnl'] > 0 else "N/A")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by `backtest/run_combined.py`*")
    return "\n".join(lines)


def print_topline_table(variants: list[dict]):
    """Print a compact top-line table to stdout (mid-sprint audit)."""
    print()
    print("=" * 120)
    print("  COMBINED BACKTEST — TOP-LINE TABLE")
    print("=" * 120)
    print(f"  {'Variant':<45s} {'Trades':>6s} {'Win%':>7s} {'NetPnL':>9s} "
          f"{'AvgNet':>8s} {'Fees':>7s} {'Sharpe':>7s} {'ARR@5':>8s}")
    print("-" * 120)
    for v in variants:
        print(f"  {v['variant']:<45s} {v['trades']:>6d} {v['win_rate']:>6.1%} "
              f"${v['total_net_pnl']:>8.2f} ${v['avg_net_pnl']:>7.4f} "
              f"${v['total_fees']:>6.2f} {v['sharpe']:>7.2f} {v['arr_5']:>+7.0f}%")
    print("=" * 120)

    best = max(variants, key=lambda v: v["arr_5"])
    print(f"\n  BEST: {best['variant']}  |  Win: {best['win_rate']:.1%}  |  "
          f"Sharpe: {best['sharpe']:.2f}  |  ARR@5: {best['arr_5']:+.0f}%")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Combined backtest re-run")
    parser.add_argument("--entry", type=float, default=0.50,
                        help="Simulated entry price (default 0.50)")
    parser.add_argument("--fee-rate", type=float, default=0.02,
                        help="Taker fee rate r in fee(p)=p*(1-p)*r (default 0.02)")
    parser.add_argument("--no-save", action="store_true",
                        help="Skip writing result files")
    args = parser.parse_args()

    print(f"Loading data from {DATA_DIR}...")
    markets, cache, hashes = load_data()
    print(f"  {len(markets)} markets, {len(cache)} cache entries")
    print(f"  Markets hash: {hashes['historical_markets.json'][:16]}...")
    print(f"  Cache hash:   {hashes['claude_cache.json'][:16]}...")

    print(f"\nFitting calibration (seed={RANDOM_SEED})...")
    calibrator = _build_calibrator()

    print(f"\nRunning variants (entry={args.entry}, fee_rate={args.fee_rate})...")
    variants = build_variants(entry=args.entry, fee_rate=args.fee_rate)

    all_results: list[dict] = []
    for cfg in variants:
        r = simulate_variant(markets, cache, cfg, calibrator=calibrator)
        all_results.append(r)
        print(f"  {cfg.name:<45s}  trades={r['trades']:>4d}  win={r['win_rate']:>5.1%}  "
              f"net=${r['total_net_pnl']:>8.2f}  fees=${r['total_fees']:>5.2f}")

    # Mid-sprint audit: print top-line table
    print_topline_table(all_results)

    # Build output payload
    meta = {
        "entry_price": args.entry,
        "fee_rate": args.fee_rate,
        "total_markets": len(markets),
        "total_cache_entries": len(cache),
        "hashes": hashes,
    }
    payload = generate_json(all_results, meta)
    md_content = generate_markdown(payload)

    if not args.no_save:
        os.makedirs(RESULTS_DIR, exist_ok=True)

        json_path = os.path.join(RESULTS_DIR, "combined_results.json")
        with open(json_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nSaved JSON: {json_path}")

        md_path = os.path.join(RESULTS_DIR, "combined_results.md")
        with open(md_path, "w") as f:
            f.write(md_content)
        print(f"Saved MD:   {md_path}")

    return payload


if __name__ == "__main__":
    main()
