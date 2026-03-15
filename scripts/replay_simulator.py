#!/usr/bin/env python3
"""
BTC5 Replay Simulator
=====================
Reads historical window_trades from DB using only pre-decision fields.
Applies configurable strategy params to compute simulated fills, WR, and PnL.
Compares up to 5 param configs side by side.

Anti-lookahead guarantee:
  Only fields available at decision time are used:
    direction, delta, best_ask, best_bid, window_start_ts
  Ground truth for outcome: resolved_outcome (post-hoc, used only for scoring)
  Explicitly excluded from decision logic: pnl_usd, won (from live fills)

Usage:
  python3 scripts/replay_simulator.py [--configs baseline alt1 alt2]
  python3 scripts/replay_simulator.py --db data/btc5_maker.db
  python3 scripts/replay_simulator.py --list-configs
"""

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config definitions
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    name: str
    down_max_buy_price: float    # max price to buy DOWN
    up_max_buy_price: float      # max price to buy UP (only used if direction not suppressed)
    min_buy_price: float         # floor: don't buy below this price (too cheap = too uncertain)
    min_delta: float             # minimum absolute delta to trigger
    max_delta: Optional[float]   # maximum absolute delta (None = no ceiling)
    directional_mode: str        # "down_only", "up_only", or "both"
    bankroll: float              # total bankroll in USD
    risk_fraction: float         # fraction of bankroll per trade
    min_trade_usd: float         # minimum trade size in USD
    max_trade_usd: float         # maximum trade size in USD

    @property
    def trade_size_usd(self) -> float:
        raw = self.bankroll * self.risk_fraction
        return max(self.min_trade_usd, min(self.max_trade_usd, raw))


DEFAULT_CONFIGS: dict[str, StrategyConfig] = {
    "baseline": StrategyConfig(
        name="baseline",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.50,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "conservative": StrategyConfig(
        name="conservative",
        down_max_buy_price=0.90,
        up_max_buy_price=0.90,
        min_buy_price=0.50,
        min_delta=0.0003,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.015,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "aggressive": StrategyConfig(
        name="aggressive",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.50,
        min_delta=0.00005,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.025,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    # H1: price-floor sweep — test whether edge is price-conditional
    "high_entry_085": StrategyConfig(
        name="high_entry_085",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.85,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_088": StrategyConfig(
        name="high_entry_088",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.88,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_090": StrategyConfig(
        name="high_entry_090",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.90,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_092": StrategyConfig(
        name="high_entry_092",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.92,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_094": StrategyConfig(
        name="high_entry_094",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.94,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_096": StrategyConfig(
        name="high_entry_096",
        down_max_buy_price=0.99,
        up_max_buy_price=0.99,
        min_buy_price=0.96,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_097": StrategyConfig(
        name="high_entry_097",
        down_max_buy_price=0.99,
        up_max_buy_price=0.99,
        min_buy_price=0.97,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "high_entry_098": StrategyConfig(
        name="high_entry_098",
        down_max_buy_price=0.99,
        up_max_buy_price=0.99,
        min_buy_price=0.98,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "f090_cap097": StrategyConfig(
        name="f090_cap097",
        down_max_buy_price=0.97,
        up_max_buy_price=0.95,
        min_buy_price=0.90,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "f090_cap098": StrategyConfig(
        name="f090_cap098",
        down_max_buy_price=0.98,
        up_max_buy_price=0.95,
        min_buy_price=0.90,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "f090_cap099": StrategyConfig(
        name="f090_cap099",
        down_max_buy_price=0.99,
        up_max_buy_price=0.95,
        min_buy_price=0.90,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "f092_cap097": StrategyConfig(
        name="f092_cap097",
        down_max_buy_price=0.97,
        up_max_buy_price=0.95,
        min_buy_price=0.92,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
    "f092_cap099": StrategyConfig(
        name="f092_cap099",
        down_max_buy_price=0.99,
        up_max_buy_price=0.95,
        min_buy_price=0.92,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=390.0,
        risk_fraction=0.02,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    ),
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def find_db(explicit_path: Optional[str] = None) -> str:
    if explicit_path:
        return explicit_path
    candidates = [
        "data/btc_5min_maker.db",
        "/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db",
        "data/btc5_maker.db",
        "/home/ubuntu/polymarket-trading-bot/data/btc5_maker.db",
    ]
    for c in candidates:
        # Skip empty stub files
        if os.path.exists(c) and os.path.getsize(c) > 0:
            return c
    raise FileNotFoundError(
        f"No DB found. Tried: {candidates}. Use --db to specify path."
    )


def load_windows(db_path: str) -> list[dict]:
    """
    Load window_trades rows using only pre-decision fields plus resolved_outcome
    and counterfactual_pnl_usd_std5 for scoring.

    Explicitly NOT loaded: pnl_usd, won (from live fills — these are lookahead for simulation)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Discover available columns to avoid hard failures on schema variations
    cur.execute("PRAGMA table_info(window_trades)")
    available_cols = {row["name"] for row in cur.fetchall()}

    # Required pre-decision fields
    required = {"direction", "delta", "best_ask", "best_bid", "window_start_ts", "resolved_outcome"}
    missing = required - available_cols
    if missing:
        raise ValueError(
            f"window_trades table missing required columns: {missing}. "
            f"Available: {sorted(available_cols)}"
        )

    # Optional scoring field
    cf_col = "counterfactual_pnl_usd_std5" if "counterfactual_pnl_usd_std5" in available_cols else None

    select_cols = [
        "direction",
        "delta",
        "best_ask",
        "best_bid",
        "window_start_ts",
        "resolved_outcome",
    ]
    if cf_col:
        select_cols.append(cf_col)

    query = f"SELECT {', '.join(select_cols)} FROM window_trades WHERE resolved_outcome IS NOT NULL"
    cur.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Decision logic (anti-lookahead)
# ---------------------------------------------------------------------------

def should_fill(window: dict, cfg: StrategyConfig) -> bool:
    """
    Apply strategy config to a window using only pre-decision fields.
    Returns True if the config would have placed an order on this window.

    Fields used: direction, delta, best_ask, best_bid
    Fields NOT used: resolved_outcome, pnl_usd, won, counterfactual_pnl_usd_std5
    """
    direction = window.get("direction")
    delta = window.get("delta")
    best_ask = window.get("best_ask")

    # Require valid pre-decision fields
    if direction is None or delta is None or best_ask is None:
        return False

    # Directional mode filter
    if cfg.directional_mode == "down_only" and direction != "DOWN":
        return False
    if cfg.directional_mode == "up_only" and direction != "UP":
        return False

    # Delta threshold
    abs_delta = abs(float(delta))
    if abs_delta < cfg.min_delta:
        return False
    if cfg.max_delta is not None and abs_delta > cfg.max_delta:
        return False

    # Price guardrails
    price = float(best_ask)
    if price < cfg.min_buy_price:
        return False

    if direction == "DOWN" and price > cfg.down_max_buy_price:
        return False
    if direction == "UP" and price > cfg.up_max_buy_price:
        return False

    # Trade size check
    if cfg.trade_size_usd < cfg.min_trade_usd:
        return False

    return True


def compute_pnl(window: dict, cfg: StrategyConfig) -> float:
    """
    Compute simulated PnL for a fill using resolved_outcome as ground truth.

    PnL formula:
      - If we bought at best_ask and outcome is a win (resolved_outcome == direction):
          pnl = trade_size × (1/best_ask - 1)  [bought tokens that paid out at $1]
      - If outcome is a loss:
          pnl = -trade_size                     [tokens expire worthless]

    Uses counterfactual_pnl_usd_std5 if available (preferred — accounts for actual
    market size), otherwise falls back to the formula above.
    """
    direction = window.get("direction")
    resolved_outcome = window.get("resolved_outcome")
    best_ask = float(window.get("best_ask", 0))
    cf_pnl = window.get("counterfactual_pnl_usd_std5")
    trade_size = cfg.trade_size_usd

    # Prefer counterfactual PnL if available (it uses actual market sizing)
    if cf_pnl is not None:
        # CF PnL is computed at a standard $5 size; scale to actual trade size
        cf_std_size = 5.0
        return float(cf_pnl) * (trade_size / cf_std_size)

    # Fallback: compute from resolved_outcome + best_ask
    if best_ask <= 0:
        return -trade_size

    # resolved_outcome is typically "YES"/"NO" or the direction string
    # Treat match with direction as a win
    won = (
        str(resolved_outcome).upper() == str(direction).upper()
        or str(resolved_outcome).upper() == "YES"
    )

    if won:
        # bought at best_ask, each token pays $1
        tokens = trade_size / best_ask
        pnl = tokens - trade_size  # net profit
    else:
        pnl = -trade_size  # full loss

    return pnl


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    config_name: str
    total_windows: int
    simulated_fills: int
    fill_rate: float
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    pnl_per_fill: float
    avg_entry: float
    trade_size_usd: float


def run_simulation(windows: list[dict], cfg: StrategyConfig) -> SimResult:
    fills = []
    for w in windows:
        if should_fill(w, cfg):
            fills.append(w)

    if not fills:
        return SimResult(
            config_name=cfg.name,
            total_windows=len(windows),
            simulated_fills=0,
            fill_rate=0.0,
            wins=0,
            losses=0,
            win_rate=0.0,
            total_pnl=0.0,
            pnl_per_fill=0.0,
            avg_entry=0.0,
            trade_size_usd=cfg.trade_size_usd,
        )

    pnls = [compute_pnl(w, cfg) for w in fills]
    wins = sum(1 for p in pnls if p > 0)
    total_pnl = sum(pnls)
    avg_entry = sum(float(w.get("best_ask", 0)) for w in fills) / len(fills)

    return SimResult(
        config_name=cfg.name,
        total_windows=len(windows),
        simulated_fills=len(fills),
        fill_rate=len(fills) / len(windows) if windows else 0.0,
        wins=wins,
        losses=len(fills) - wins,
        win_rate=wins / len(fills) if fills else 0.0,
        total_pnl=round(total_pnl, 4),
        pnl_per_fill=round(total_pnl / len(fills), 4) if fills else 0.0,
        avg_entry=round(avg_entry, 4),
        trade_size_usd=cfg.trade_size_usd,
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_table(results: list[SimResult]) -> None:
    headers = [
        "config_name",
        "simulated_fills",
        "fill_rate",
        "win_rate",
        "total_pnl",
        "pnl_per_fill",
        "avg_entry",
        "trade_size_usd",
    ]
    col_width = 16
    header_line = "  ".join(h.ljust(col_width) for h in headers)
    print()
    print(header_line)
    print("-" * len(header_line))
    for r in results:
        row = [
            r.config_name.ljust(col_width),
            str(r.simulated_fills).ljust(col_width),
            f"{r.fill_rate:.3f}".ljust(col_width),
            f"{r.win_rate:.3f}".ljust(col_width),
            f"${r.total_pnl:.4f}".ljust(col_width),
            f"${r.pnl_per_fill:.4f}".ljust(col_width),
            f"{r.avg_entry:.4f}".ljust(col_width),
            f"${r.trade_size_usd:.2f}".ljust(col_width),
        ]
        print("  ".join(row))
    print()


def print_config_details(cfg: StrategyConfig) -> None:
    print(f"  {cfg.name}:")
    print(f"    down_max_buy_price={cfg.down_max_buy_price}, up_max_buy_price={cfg.up_max_buy_price}")
    print(f"    min_delta={cfg.min_delta}, max_delta={cfg.max_delta}")
    print(f"    directional_mode={cfg.directional_mode}")
    print(f"    bankroll=${cfg.bankroll}, risk_fraction={cfg.risk_fraction}")
    print(f"    trade_size=${cfg.trade_size_usd:.2f} (min=${cfg.min_trade_usd}, max=${cfg.max_trade_usd})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="BTC5 Replay Simulator — compare strategy configs against historical windows"
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        default=["baseline", "conservative", "aggressive"],
        help="Config names to run (default: baseline conservative aggressive)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite DB (auto-detected if not specified)",
    )
    parser.add_argument(
        "--output",
        default="data/replay_results.json",
        help="Path to save JSON results (default: data/replay_results.json)",
    )
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="List all available configs and exit",
    )
    parser.add_argument(
        "--config-json",
        default=None,
        help="JSON dict of StrategyConfig fields to run as a single ad-hoc config",
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Print JSON result to stdout (single config) instead of human-readable table",
    )
    args = parser.parse_args()

    if args.list_configs:
        print("Available configs:")
        for name, cfg in DEFAULT_CONFIGS.items():
            print_config_details(cfg)
        sys.exit(0)

    # Handle ad-hoc JSON config (for programmatic use by autoresearch_deploy.py).
    if args.config_json:
        try:
            overrides = json.loads(args.config_json)
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid --config-json: {e}")
            sys.exit(1)
        base = DEFAULT_CONFIGS.get("high_entry_090")
        if base is None:
            base = list(DEFAULT_CONFIGS.values())[0]
        import dataclasses
        base_dict = dataclasses.asdict(base)
        base_dict.update({k: v for k, v in overrides.items() if k in base_dict})
        base_dict["name"] = overrides.get("name", "ad_hoc")
        adhoc_cfg = StrategyConfig(**base_dict)
        db_path = find_db(args.db)
        windows = load_windows(db_path)
        result = run_simulation(windows, adhoc_cfg)
        if args.output_json:
            print(json.dumps({
                "config_name": result.config_name,
                "total_fills": result.simulated_fills,
                "win_rate": result.win_rate,
                "total_pnl": result.total_pnl,
                "avg_entry": result.avg_entry,
                "total_windows": len(windows),
            }))
        else:
            print_table([result])
        sys.exit(0)

    # Resolve requested configs
    configs_to_run: list[StrategyConfig] = []
    for name in args.configs:
        if name not in DEFAULT_CONFIGS:
            print(f"ERROR: unknown config '{name}'. Available: {list(DEFAULT_CONFIGS.keys())}")
            sys.exit(1)
        configs_to_run.append(DEFAULT_CONFIGS[name])

    # Limit to 10
    if len(configs_to_run) > 10:
        print(f"WARNING: capping at 10 configs (got {len(configs_to_run)})")
        configs_to_run = configs_to_run[:10]

    # Load data
    try:
        db_path = find_db(args.db)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Loading windows from: {db_path}")
    try:
        windows = load_windows(db_path)
    except (sqlite3.OperationalError, ValueError) as e:
        print(f"ERROR loading data: {e}")
        sys.exit(1)

    print(f"Loaded {len(windows)} windows with resolved_outcome")
    if not windows:
        print("No data to simulate. Exiting.")
        sys.exit(0)

    # Run simulations
    results: list[SimResult] = []
    for cfg in configs_to_run:
        result = run_simulation(windows, cfg)
        results.append(result)
        print(f"  [{cfg.name}] fills={result.simulated_fills}, wr={result.win_rate:.3f}, pnl=${result.total_pnl:.4f}")

    # Print comparison table
    print("\n=== REPLAY SIMULATION RESULTS ===")
    print_table(results)

    # Annotate with break-even WR
    print("Break-even win rate analysis:")
    for r in results:
        if r.avg_entry > 0:
            print(f"  {r.config_name}: avg_entry={r.avg_entry:.4f} → break-even WR = {r.avg_entry:.4f} | actual WR = {r.win_rate:.3f} | delta = {r.win_rate - r.avg_entry:+.3f}")
    print()

    # Save results
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    output_data = {
        "generated": "2026-03-15",
        "db_path": db_path,
        "total_windows_in_db": len(windows),
        "configs_run": [cfg.name for cfg in configs_to_run],
        "results": [asdict(r) for r in results],
        "notes": [
            "Anti-lookahead enforced: decision logic uses only direction, delta, best_ask, best_bid",
            "resolved_outcome used only for scoring, not for decisions",
            "pnl_usd and won fields from live fills are not loaded",
            "PnL computed from counterfactual_pnl_usd_std5 if available, else from resolved_outcome + best_ask",
            "Polymarket maker rebates not modeled — PnL is slightly conservative",
        ],
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
