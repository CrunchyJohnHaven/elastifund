#!/usr/bin/env python3
"""Autoresearch edge optimizer — Karpathy-style self-improving loop.

Modify -> Run -> Measure -> Keep or Discard -> Repeat.

One fitness metric: net_improvement_usd (losses prevented minus profits blocked).
Fixed evaluation budget: one full CSV replay per iteration (~0.1 seconds).

Usage:
    python3 scripts/autoresearch_edge_loop.py --iterations 100
    python3 scripts/autoresearch_edge_loop.py --iterations 1000
    python3 scripts/autoresearch_edge_loop.py --show-best
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime
import json
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CSV_PATH = Path.home() / "Downloads" / "Polymarket-History-2026-03-21 (1).csv"
DATA_DIR = _REPO_ROOT / "data"
BEST_PATH = DATA_DIR / "autoresearch_edge_best.json"
LOG_PATH = DATA_DIR / "autoresearch_edge_log.jsonl"

# Eastern time (EDT = UTC-4, March 2026 post-DST)
ET = datetime.timezone(datetime.timedelta(hours=-4))

# Default structural gate config — starting point for optimization
DEFAULT_CONFIG: dict[str, Any] = {
    "time_kill_hours": [22, 23, 0, 1, 2, 3, 9, 10, 11],
    "max_token_buy_price": 0.60,
    "max_per_market_usd": 15.0,
    "resolution_sniper_threshold": 0.94,
    "min_profit_per_share": 0.03,
    "combined_cost_cap": 0.97,
    "partial_fill_ttl_seconds": 30,
    "per_market_cap_usd": 10.0,
    "max_markets": 6,
    "reserve_pct": 0.20,
}

# Parameter ranges for clamping after mutation
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "max_token_buy_price": (0.50, 0.80),
    "max_per_market_usd": (5.0, 50.0),
    "resolution_sniper_threshold": (0.90, 0.98),
    "min_profit_per_share": (0.01, 0.10),
    "combined_cost_cap": (0.93, 0.99),
    "partial_fill_ttl_seconds": (10.0, 300.0),
    "per_market_cap_usd": (5.0, 25.0),
    "max_markets": (2.0, 12.0),
    "reserve_pct": (0.10, 0.40),
}

# Integer parameters (mutated with additive noise, not multiplicative)
INT_PARAMS = {"partial_fill_ttl_seconds", "max_markets"}

# Set parameter — special mutation logic
SET_PARAMS = {"time_kill_hours"}

# Valid hours for the time_kill set
ALL_HOURS = list(range(24))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """Parsed trade row from the CSV."""
    market_name: str
    action: str         # Buy, Redeem, Maker Rebate, Deposit
    usdc_amount: float
    token_amount: float
    token_name: str     # Up, Down, Yes, No, or empty for Redeem
    timestamp: int
    tx_hash: str
    et_hour: int = 0
    token_price: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp > 0:
            self.et_hour = datetime.datetime.fromtimestamp(
                self.timestamp, tz=ET
            ).hour
        if self.token_amount > 0:
            self.token_price = self.usdc_amount / self.token_amount


def load_trades(path: Path = CSV_PATH) -> list[Trade]:
    """Load and parse the trade history CSV once."""
    if not path.exists():
        raise FileNotFoundError(f"Trade CSV not found: {path}")
    trades: list[Trade] = []
    with open(path, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            ts_str = row.get("timestamp", "")
            if not ts_str.isdigit():
                continue
            trades.append(Trade(
                market_name=row["marketName"],
                action=row["action"],
                usdc_amount=float(row["usdcAmount"]),
                token_amount=float(row["tokenAmount"]),
                token_name=row.get("tokenName", ""),
                timestamp=int(ts_str),
                tx_hash=row.get("hash", ""),
            ))
    return trades


def _is_btc5(market_name: str) -> bool:
    return "Bitcoin Up or Down" in market_name


# ---------------------------------------------------------------------------
# Market-level P&L computation (precompute once)
# ---------------------------------------------------------------------------

@dataclass
class MarketPnL:
    """Precomputed P&L for a single market from the CSV."""
    market_name: str
    total_buy_usdc: float
    total_redeem_usdc: float
    total_rebate_usdc: float
    net_pnl: float          # redeem + rebate - buy
    buy_trades: list[Trade] = field(default_factory=list)


def precompute_market_pnl(trades: list[Trade]) -> dict[str, MarketPnL]:
    """Group trades by market and compute net P&L per market."""
    buys: dict[str, list[Trade]] = {}
    redeems: dict[str, float] = {}
    rebates: dict[str, float] = {}

    for t in trades:
        if t.action == "Buy":
            buys.setdefault(t.market_name, []).append(t)
        elif t.action == "Redeem":
            redeems[t.market_name] = redeems.get(t.market_name, 0.0) + t.usdc_amount
        elif t.action == "Maker Rebate":
            rebates[t.market_name] = rebates.get(t.market_name, 0.0) + t.usdc_amount

    result: dict[str, MarketPnL] = {}
    for mkt, buy_list in buys.items():
        total_buy = sum(b.usdc_amount for b in buy_list)
        total_redeem = redeems.get(mkt, 0.0)
        total_rebate = rebates.get(mkt, 0.0)
        result[mkt] = MarketPnL(
            market_name=mkt,
            total_buy_usdc=total_buy,
            total_redeem_usdc=total_redeem,
            total_rebate_usdc=total_rebate,
            net_pnl=total_redeem + total_rebate - total_buy,
            buy_trades=buy_list,
        )
    return result


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

def evaluate(config: dict[str, Any], market_pnls: dict[str, MarketPnL]) -> dict[str, Any]:
    """Replay all markets through structural gates. Return fitness metrics.

    For each market's buy trades, apply gates in order:
    1. Time-of-day kill (any buy in a kill hour blocks the market)
    2. Token price too high (any buy above max_token_buy_price blocks it)
    3. Per-market USD cap exceeded
    4. BTC5 one-sided (no pair) — block if only Up or only Down

    A market is BLOCKED if ANY of its buy trades trigger a gate.
    This is conservative: if one trade in a market is bad, block all.

    Fitness = sum(pnl of blocked losing markets) - sum(|pnl| of blocked winning markets)
    i.e., how much loss the gates prevent minus how much profit they accidentally block.
    Higher is better.
    """
    kill_hours = set(config.get("time_kill_hours", []))
    max_price = config.get("max_token_buy_price", 1.0)
    max_per_market = config.get("max_per_market_usd", float("inf"))

    # For BTC5 pairing: determine which BTC5 markets have both directions
    btc5_directions: dict[str, set[str]] = {}
    for mkt, mpnl in market_pnls.items():
        if _is_btc5(mkt):
            for t in mpnl.buy_trades:
                btc5_directions.setdefault(mkt, set()).add(t.token_name)
    btc5_paired = {
        mkt for mkt, dirs in btc5_directions.items()
        if "Up" in dirs and "Down" in dirs
    }

    blocked_loss = 0.0    # losses prevented (positive contribution)
    blocked_profit = 0.0  # profits accidentally blocked (negative contribution)
    allowed_pnl = 0.0
    blocked_count = 0
    allowed_count = 0
    block_reasons: dict[str, int] = {}

    for mkt, mpnl in market_pnls.items():
        reason = _check_gates(
            mpnl, kill_hours, max_price, max_per_market, btc5_paired
        )
        if reason:
            blocked_count += 1
            block_reasons[reason] = block_reasons.get(reason, 0) + 1
            if mpnl.net_pnl < 0:
                blocked_loss += abs(mpnl.net_pnl)   # good: we prevented a loss
            else:
                blocked_profit += mpnl.net_pnl       # bad: we blocked a profit
        else:
            allowed_count += 1
            allowed_pnl += mpnl.net_pnl

    fitness = blocked_loss - blocked_profit

    return {
        "fitness": fitness,
        "blocked_loss_usd": blocked_loss,
        "blocked_profit_usd": blocked_profit,
        "allowed_pnl_usd": allowed_pnl,
        "blocked_count": blocked_count,
        "allowed_count": allowed_count,
        "block_reasons": block_reasons,
    }


def _check_gates(
    mpnl: MarketPnL,
    kill_hours: set[int],
    max_price: float,
    max_per_market: float,
    btc5_paired: set[str],
) -> str | None:
    """Check if a market should be blocked. Returns reason string or None."""

    # Gate 1: time-of-day kill — block if any buy is in a kill hour
    if kill_hours:
        for t in mpnl.buy_trades:
            if t.et_hour in kill_hours:
                return "time_of_day_kill"

    # Gate 2: token price too high
    for t in mpnl.buy_trades:
        if t.token_price > max_price and t.token_price == t.token_price:  # NaN check
            return "token_price_too_high"

    # Gate 3: per-market cap
    if mpnl.total_buy_usdc > max_per_market:
        return "per_market_cap_exceeded"

    # Gate 4: BTC5 one-sided
    if _is_btc5(mpnl.market_name) and mpnl.market_name not in btc5_paired:
        return "btc5_one_sided"

    return None


# ---------------------------------------------------------------------------
# Mutation operator
# ---------------------------------------------------------------------------

def mutate(config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Generate one random parameter mutation. Returns (new_config, description)."""
    new = copy.deepcopy(config)

    # Pick a random parameter to mutate
    param = random.choice(list(PARAM_RANGES.keys()) + list(SET_PARAMS))

    if param in SET_PARAMS:
        # time_kill_hours: add or remove one hour
        hours = set(new.get("time_kill_hours", []))
        if random.random() < 0.5 and len(hours) > 0:
            # Remove a random hour
            victim = random.choice(list(hours))
            hours.discard(victim)
            desc = f"time_kill_hours: removed hour {victim}"
        else:
            # Add a random hour not already present
            available = [h for h in ALL_HOURS if h not in hours]
            if available:
                added = random.choice(available)
                hours.add(added)
                desc = f"time_kill_hours: added hour {added}"
            else:
                desc = "time_kill_hours: no mutation (all hours already present)"
        new["time_kill_hours"] = sorted(hours)
    elif param in INT_PARAMS:
        old_val = new[param]
        delta = random.randint(-2, 2)
        lo, hi = PARAM_RANGES[param]
        new_val = max(int(lo), min(int(hi), int(old_val) + delta))
        desc = f"{param}: {old_val} -> {new_val}"
        new[param] = new_val
    else:
        # Float: multiply by uniform(0.85, 1.15)
        old_val = new[param]
        factor = random.uniform(0.85, 1.15)
        lo, hi = PARAM_RANGES[param]
        new_val = max(lo, min(hi, old_val * factor))
        new_val = round(new_val, 6)
        desc = f"{param}: {old_val:.6f} -> {new_val:.6f}"
        new[param] = new_val

    return new, desc


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_baseline() -> dict[str, Any]:
    """Load current best config, or return default."""
    if BEST_PATH.exists():
        with open(BEST_PATH) as fh:
            data = json.load(fh)
        return data.get("config", DEFAULT_CONFIG.copy())
    return DEFAULT_CONFIG.copy()


def save_baseline(config: dict[str, Any], fitness: float, iteration: int) -> None:
    """Save current best config."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "autoresearch_edge_best.v1",
        "saved_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "iteration": iteration,
        "fitness": fitness,
        "config": config,
    }
    with open(BEST_PATH, "w") as fh:
        json.dump(payload, fh, indent=2)


def append_log(entry: dict[str, Any]) -> None:
    """Append one iteration log to the JSONL file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(iterations: int, trades: list[Trade]) -> None:
    """The autoresearch loop: mutate -> evaluate -> keep or discard -> repeat."""
    market_pnls = precompute_market_pnl(trades)
    total_markets = len(market_pnls)
    total_baseline_pnl = sum(m.net_pnl for m in market_pnls.values())

    print(f"  Loaded {len(trades)} trades across {total_markets} markets")
    print(f"  Baseline P&L (no gates): ${total_baseline_pnl:.2f}")
    print()

    # Load or initialize baseline
    best_config = load_baseline()
    best_result = evaluate(best_config, market_pnls)
    best_fitness = best_result["fitness"]

    print(f"  Starting fitness: ${best_fitness:.2f}")
    print(f"    Blocked losses: ${best_result['blocked_loss_usd']:.2f}")
    print(f"    Blocked profits: ${best_result['blocked_profit_usd']:.2f}")
    print(f"    Allowed P&L: ${best_result['allowed_pnl_usd']:.2f}")
    print()

    last_improvement = 0
    kept = 0
    discarded = 0
    start_time = time.time()

    for i in range(1, iterations + 1):
        # Mutate
        candidate, mutation_desc = mutate(best_config)

        # Evaluate
        result = evaluate(candidate, market_pnls)
        candidate_fitness = result["fitness"]

        # Keep or discard
        if candidate_fitness > best_fitness:
            improvement = candidate_fitness - best_fitness
            best_config = candidate
            best_fitness = candidate_fitness
            best_result = result
            kept += 1
            last_improvement = i
            save_baseline(best_config, best_fitness, i)
            verdict = "KEEP"
        else:
            discarded += 1
            improvement = 0.0
            verdict = "DISCARD"

        # Log
        entry = {
            "iteration": i,
            "mutation": mutation_desc,
            "fitness": candidate_fitness,
            "best_fitness": best_fitness,
            "verdict": verdict,
            "improvement": improvement,
            "blocked_loss": result["blocked_loss_usd"],
            "blocked_profit": result["blocked_profit_usd"],
            "config": candidate,
            "timestamp": time.time(),
        }
        append_log(entry)

        # Print summary every 10 iterations
        if i % 10 == 0 or i == 1:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            stale = i - last_improvement
            print(
                f"  [{i:>5}/{iterations}]  "
                f"best=${best_fitness:>8.2f}  "
                f"current=${candidate_fitness:>8.2f}  "
                f"kept={kept}  disc={discarded}  "
                f"stale={stale}  "
                f"{rate:.0f} iter/s"
            )

    # Final summary
    elapsed = time.time() - start_time
    print()
    print("=" * 72)
    print("  AUTORESEARCH COMPLETE")
    print("=" * 72)
    print(f"  Iterations: {iterations}")
    print(f"  Elapsed: {elapsed:.1f}s ({iterations / elapsed:.0f} iter/s)")
    print(f"  Kept: {kept}  |  Discarded: {discarded}")
    print(f"  Last improvement at iteration: {last_improvement}")
    print()
    print(f"  Best fitness: ${best_fitness:.2f}")
    print(f"    Blocked losses: ${best_result['blocked_loss_usd']:.2f}")
    print(f"    Blocked profits: ${best_result['blocked_profit_usd']:.2f}")
    print(f"    Allowed P&L: ${best_result['allowed_pnl_usd']:.2f}")
    print(f"    Blocked markets: {best_result['blocked_count']} / {total_markets}")
    print(f"    Block reasons: {best_result['block_reasons']}")
    print()
    print("  Best config:")
    for k, v in sorted(best_config.items()):
        print(f"    {k}: {v}")
    print()
    print(f"  Best saved to: {BEST_PATH}")
    print(f"  Log at: {LOG_PATH}")
    print("=" * 72)


def show_best() -> None:
    """Display the current best configuration."""
    if not BEST_PATH.exists():
        print("  No best config found. Run --iterations first.")
        return
    with open(BEST_PATH) as fh:
        data = json.load(fh)
    print()
    print("=" * 72)
    print("  CURRENT BEST AUTORESEARCH CONFIG")
    print("=" * 72)
    print(f"  Saved at: {data.get('saved_at', 'unknown')}")
    print(f"  Iteration: {data.get('iteration', 'unknown')}")
    print(f"  Fitness: ${data.get('fitness', 0):.2f}")
    print()
    for k, v in sorted(data.get("config", {}).items()):
        print(f"    {k}: {v}")
    print("=" * 72)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autoresearch edge optimizer — Karpathy-style self-improving loop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--iterations", type=int, default=100,
        help="Number of mutation-evaluate cycles (default: 100)",
    )
    parser.add_argument(
        "--show-best", action="store_true",
        help="Show current best config and exit",
    )
    parser.add_argument(
        "--csv", type=Path, default=CSV_PATH,
        help=f"Path to trade history CSV (default: {CSV_PATH})",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    if args.show_best:
        show_best()
        return

    if args.seed is not None:
        random.seed(args.seed)

    print()
    print("=" * 72)
    print("  AUTORESEARCH EDGE OPTIMIZER")
    print("  Karpathy-style: mutate -> evaluate -> keep or discard -> repeat")
    print("=" * 72)
    print()

    trades = load_trades(args.csv)
    run_loop(args.iterations, trades)


if __name__ == "__main__":
    main()
