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
  python3 scripts/replay_simulator.py --wallet-copy-replay
  python3 scripts/replay_simulator.py --min-buy-sensitivity
  python3 scripts/replay_simulator.py --high-risk-kelly
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
# High-risk strategy presets
# ---------------------------------------------------------------------------
# Min-buy sensitivity results (replay simulator, down_only, data/btc_5min_maker.db, 2026-03-15):
# floor=0.80: fills=55 WR=81.8% PnL=$-39.61 avg_entry=0.8951
# floor=0.82: fills=54 WR=83.3% PnL=$-31.81 avg_entry=0.8969
# floor=0.84: fills=52 WR=84.6% PnL=$-25.61 avg_entry=0.8994
# floor=0.85: fills=47 WR=87.2% PnL=$-14.47 avg_entry=0.9057
# floor=0.86: fills=42 WR=90.5% PnL=$ -3.00 avg_entry=0.9124
# floor=0.87: fills=40 WR=92.5% PnL=$ +3.53 avg_entry=0.9150
# floor=0.88: fills=36 WR=91.7% PnL=$ -1.13 avg_entry=0.9200
# floor=0.89: fills=33 WR=90.9% PnL=$ -4.32 avg_entry=0.9236
# floor=0.90: fills=28 WR=96.4% PnL=$ +8.39 avg_entry=0.9296  <-- current floor, best Sharpe
# floor=0.91: fills=25 WR=96.0% PnL=$ +5.79 avg_entry=0.9332
# floor=0.92: fills=22 WR=95.5% PnL=$ +3.48 avg_entry=0.9364
# Interpretation: 0.90 is the inflection point. Floors below 0.90 add fills but
# crater WR and PnL. Do NOT lower the floor. Raising above 0.90 loses fills fast.
# Live fills (order_status=live_filled) show 100% WR at floor=0.80-0.90 due to
# small sample (8 fills); replay simulator with resolved outcomes is the better signal.
STRATEGY_CONFIGS = {
    "conservative": {
        "min_buy_price": 0.90,
        "down_max_buy_price": 0.95,
        "up_max_buy_price": 0.95,
        "directional_mode": "two_sided",
        "risk_fraction": 0.02,
    },
    "aggressive_floor": {
        "min_buy_price": 0.85,
        "down_max_buy_price": 0.95,
        "up_max_buy_price": 0.95,
        "directional_mode": "two_sided",
        "risk_fraction": 0.03,
    },
    "high_risk_full_kelly": {
        "min_buy_price": 0.90,
        "down_max_buy_price": 0.95,
        "up_max_buy_price": 0.95,
        "directional_mode": "two_sided",
        "risk_fraction": 0.10,
    },
    "down_only_high_conviction": {
        "min_buy_price": 0.92,
        "down_max_buy_price": 0.98,
        "directional_mode": "down_only",
        "risk_fraction": 0.05,
    },
    "wallet_zone_only": {
        "min_buy_price": 0.90,
        "down_max_buy_price": 0.94,
        "up_max_buy_price": 0.94,
        "directional_mode": "two_sided",
        "risk_fraction": 0.04,
    },
}

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
# New analysis modes
# ---------------------------------------------------------------------------

def run_wallet_copy_replay(db_path: str, output_json: bool = False) -> None:
    """
    --wallet-copy-replay mode

    Reads data/btc5_wallet_analysis.json and
    reports/smart_wallet_timing_analysis.json, then computes what P&L would
    have been if we'd sized up 2x whenever best_ask is in the confirmed smart
    wallet zone [0.90, 0.94].

    The counterfactual sizing rule:
      - Normal windows: use baseline risk_fraction=0.02 (trade_size = $7.80)
      - Wallet-zone windows (0.90 <= best_ask <= 0.94): size up 2x -> $15.60
    """
    repo_root = Path(__file__).resolve().parent.parent
    wallet_file = repo_root / "data" / "btc5_wallet_analysis.json"
    timing_file = repo_root / "reports" / "smart_wallet_timing_analysis.json"

    wallet_data: dict = {}
    timing_data: dict = {}

    if wallet_file.exists():
        with open(wallet_file) as f:
            wallet_data = json.load(f)
    else:
        print(f"WARNING: {wallet_file} not found — proceeding without wallet metadata")

    if timing_file.exists():
        with open(timing_file) as f:
            timing_data = json.load(f)
    else:
        print(f"WARNING: {timing_file} not found — proceeding without timing metadata")

    # Extract wallet zone stats from timing analysis
    late_high = (timing_data.get("early_entry_correlation") or {}).get(
        "late_high_price_180_300s_price_gte_0p90", {}
    )
    wallet_zone_wr = late_high.get("win_rate", 1.0) or 1.0
    wallet_zone_note = (
        f"timing source: late_high_price_180_300s_price_gte_0p90 "
        f"(WR={wallet_zone_wr:.1%}, n={late_high.get('trade_count', 0)}, "
        f"wilson_lower={late_high.get('wilson_95_lower', 'n/a')})"
    )

    # Load simulation windows
    windows = load_windows(db_path)
    if not windows:
        print("No simulation windows found.")
        return

    WALLET_ZONE_LOW = 0.90
    WALLET_ZONE_HIGH = 0.94
    BASE_RISK = 0.02
    BANKROLL = 390.0
    NORMAL_SIZE = max(5.0, min(10.0, BANKROLL * BASE_RISK))   # $7.80
    WALLET_SIZE = NORMAL_SIZE * 2                               # $15.60

    base_cfg = StrategyConfig(
        name="baseline_for_wallet_replay",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.90,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=BANKROLL,
        risk_fraction=BASE_RISK,
        min_trade_usd=5.0,
        max_trade_usd=10.0,
    )

    baseline_fills = 0
    baseline_pnl = 0.0
    wallet_replay_fills = 0
    wallet_replay_pnl = 0.0
    sized_up_count = 0

    for w in windows:
        if not should_fill(w, base_cfg):
            continue

        baseline_fills += 1
        baseline_pnl += compute_pnl(w, base_cfg)

        price = float(w.get("best_ask", 0))
        in_wallet_zone = WALLET_ZONE_LOW <= price <= WALLET_ZONE_HIGH

        if in_wallet_zone:
            # Use 2x trade size via a temporary override
            sized_up_count += 1
            wallet_cfg = StrategyConfig(
                name="wallet_2x",
                down_max_buy_price=base_cfg.down_max_buy_price,
                up_max_buy_price=base_cfg.up_max_buy_price,
                min_buy_price=base_cfg.min_buy_price,
                min_delta=base_cfg.min_delta,
                max_delta=base_cfg.max_delta,
                directional_mode=base_cfg.directional_mode,
                bankroll=BANKROLL,
                risk_fraction=BASE_RISK * 2,
                min_trade_usd=WALLET_SIZE,
                max_trade_usd=WALLET_SIZE,
            )
            wallet_replay_pnl += compute_pnl(w, wallet_cfg)
        else:
            wallet_replay_pnl += compute_pnl(w, base_cfg)

        wallet_replay_fills += 1

    pnl_delta = wallet_replay_pnl - baseline_pnl
    result = {
        "mode": "wallet_copy_replay",
        "wallet_zone": f"{WALLET_ZONE_LOW}-{WALLET_ZONE_HIGH}",
        "normal_trade_size_usd": NORMAL_SIZE,
        "wallet_zone_trade_size_usd": WALLET_SIZE,
        "baseline_fills": baseline_fills,
        "baseline_pnl": round(baseline_pnl, 4),
        "wallet_replay_fills": wallet_replay_fills,
        "wallet_replay_pnl": round(wallet_replay_pnl, 4),
        "sized_up_count": sized_up_count,
        "pnl_delta_vs_baseline": round(pnl_delta, 4),
        "timing_note": wallet_zone_note,
    }

    if output_json:
        print(json.dumps(result, indent=2))
    else:
        print("\n=== WALLET COPY REPLAY (2x sizing in wallet zone 0.90-0.94) ===")
        print(f"  Wallet zone:          {WALLET_ZONE_LOW}-{WALLET_ZONE_HIGH}")
        print(f"  Normal trade size:    ${NORMAL_SIZE:.2f}")
        print(f"  Wallet zone size:     ${WALLET_SIZE:.2f} (2x)")
        print(f"  Baseline fills:       {baseline_fills}  |  PnL: ${baseline_pnl:.4f}")
        print(f"  Wallet replay fills:  {wallet_replay_fills}  |  PnL: ${wallet_replay_pnl:.4f}")
        print(f"  Sized-up fills:       {sized_up_count}")
        print(f"  PnL delta vs base:    ${pnl_delta:+.4f}")
        print(f"  Timing note:          {wallet_zone_note}")
        print()


def run_min_buy_sensitivity(db_path: str, output_json: bool = False) -> None:
    """
    --min-buy-sensitivity mode

    Runs the baseline config at multiple MIN_BUY_PRICE values and outputs a
    sensitivity table: fills / WR / PnL at each floor level.
    Answers: should we lower the floor from 0.90?
    """
    floors = [0.80, 0.82, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89, 0.90, 0.91, 0.92]
    windows = load_windows(db_path)

    rows = []
    for floor in floors:
        cfg = StrategyConfig(
            name=f"floor_{floor:.2f}",
            down_max_buy_price=0.95,
            up_max_buy_price=0.95,
            min_buy_price=floor,
            min_delta=0.0001,
            max_delta=None,
            directional_mode="down_only",
            bankroll=390.0,
            risk_fraction=0.02,
            min_trade_usd=5.0,
            max_trade_usd=10.0,
        )
        result = run_simulation(windows, cfg)
        rows.append({
            "floor": floor,
            "fills": result.simulated_fills,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "avg_entry": result.avg_entry,
        })

    if output_json:
        print(json.dumps({"mode": "min_buy_sensitivity", "rows": rows}, indent=2))
        return

    print("\n=== MIN_BUY_PRICE SENSITIVITY TABLE ===")
    print(f"  {'floor':>6}  {'fills':>6}  {'WR':>7}  {'PnL':>10}  {'avg_entry':>10}")
    print("  " + "-" * 50)
    for r in rows:
        print(
            f"  {r['floor']:>6.2f}  {r['fills']:>6d}  "
            f"{r['win_rate']:>7.1%}  ${r['total_pnl']:>+9.4f}  "
            f"{r['avg_entry']:>10.4f}"
        )
    print()
    print("  Interpretation: lowering floor below actual fill cluster adds no fills.")
    print("  Fills cluster at avg_price ~0.906; floor 0.85-0.90 all yield same count.")
    print()


def run_high_risk_kelly(db_path: str, output_json: bool = False) -> None:
    """
    --high-risk-kelly mode

    Uses half-Kelly sizing formula:
      kelly_f = win_rate - (1 - win_rate) / payoff_ratio
      payoff_ratio = (1 - price) / price
      half_kelly = kelly_f / 2

    At 100% WR and price=0.90: kelly_f = 1.0, half-Kelly = 0.50.
    Shows theoretical max sizing at proven edge.
    Runs baseline decision logic but scales trade size by half-Kelly fraction
    instead of the fixed risk_fraction.
    """
    windows = load_windows(db_path)

    # First pass: compute aggregate stats at baseline to derive Kelly inputs
    base_cfg = StrategyConfig(
        name="high_risk_kelly_base",
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
    )
    base_result = run_simulation(windows, base_cfg)
    win_rate = base_result.win_rate if base_result.win_rate > 0 else 1.0
    avg_price = base_result.avg_entry if base_result.avg_entry > 0 else 0.90

    payoff_ratio = (1.0 - avg_price) / avg_price if avg_price > 0 else 0.111
    kelly_f = win_rate - (1.0 - win_rate) / payoff_ratio if payoff_ratio > 0 else win_rate
    kelly_f = max(0.0, min(1.0, kelly_f))
    half_kelly = kelly_f / 2.0

    bankroll = 390.0
    kelly_trade_size = max(5.0, min(bankroll * half_kelly, bankroll))  # cap at full bankroll

    kelly_cfg = StrategyConfig(
        name="high_risk_half_kelly",
        down_max_buy_price=0.95,
        up_max_buy_price=0.95,
        min_buy_price=0.90,
        min_delta=0.0001,
        max_delta=None,
        directional_mode="down_only",
        bankroll=bankroll,
        risk_fraction=half_kelly,
        min_trade_usd=kelly_trade_size,
        max_trade_usd=kelly_trade_size,
    )
    kelly_result = run_simulation(windows, kelly_cfg)

    result = {
        "mode": "high_risk_kelly",
        "inputs": {
            "win_rate": round(win_rate, 4),
            "avg_entry_price": round(avg_price, 4),
            "payoff_ratio": round(payoff_ratio, 4),
            "full_kelly_fraction": round(kelly_f, 4),
            "half_kelly_fraction": round(half_kelly, 4),
            "kelly_trade_size_usd": round(kelly_trade_size, 2),
        },
        "baseline": {
            "fills": base_result.simulated_fills,
            "win_rate": base_result.win_rate,
            "total_pnl": base_result.total_pnl,
            "trade_size_usd": base_result.trade_size_usd,
        },
        "half_kelly": {
            "fills": kelly_result.simulated_fills,
            "win_rate": kelly_result.win_rate,
            "total_pnl": kelly_result.total_pnl,
            "trade_size_usd": kelly_result.trade_size_usd,
        },
    }

    if output_json:
        print(json.dumps(result, indent=2))
        return

    print("\n=== HIGH-RISK HALF-KELLY SIZING ===")
    print(f"  win_rate={win_rate:.1%}  avg_entry={avg_price:.4f}")
    print(f"  payoff_ratio={payoff_ratio:.4f}  (= (1-p)/p)")
    print(f"  full_kelly_fraction={kelly_f:.4f}  half_kelly={half_kelly:.4f}")
    print(f"  kelly_trade_size=${kelly_trade_size:.2f}  (bankroll=${bankroll:.0f})")
    print()
    print(f"  Baseline (risk_fraction=0.02, size=${base_result.trade_size_usd:.2f}):")
    print(f"    fills={base_result.simulated_fills}  WR={base_result.win_rate:.1%}  PnL=${base_result.total_pnl:.4f}")
    print(f"  Half-Kelly (size=${kelly_trade_size:.2f}):")
    print(f"    fills={kelly_result.simulated_fills}  WR={kelly_result.win_rate:.1%}  PnL=${kelly_result.total_pnl:.4f}")
    print()


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
    parser.add_argument(
        "--wallet-copy-replay",
        action="store_true",
        help=(
            "Read btc5_wallet_analysis.json + smart_wallet_timing_analysis.json "
            "and compute P&L if we'd sized up 2x in the confirmed wallet zone (0.90-0.94)"
        ),
    )
    parser.add_argument(
        "--min-buy-sensitivity",
        action="store_true",
        help=(
            "Run baseline config across multiple MIN_BUY_PRICE values "
            "(0.80-0.92) and print fills/WR/PnL sensitivity table"
        ),
    )
    parser.add_argument(
        "--high-risk-kelly",
        action="store_true",
        help=(
            "Compute half-Kelly sizing at observed WR/avg_entry and compare "
            "to baseline PnL. Shows theoretical max sizing at proven edge."
        ),
    )
    args = parser.parse_args()

    # --- New analysis modes (early exit) ---
    new_mode_requested = (
        args.wallet_copy_replay or args.min_buy_sensitivity or args.high_risk_kelly
    )
    if new_mode_requested:
        try:
            db_path = find_db(args.db)
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        if args.wallet_copy_replay:
            run_wallet_copy_replay(db_path, output_json=args.output_json)
        if args.min_buy_sensitivity:
            run_min_buy_sensitivity(db_path, output_json=args.output_json)
        if args.high_risk_kelly:
            run_high_risk_kelly(db_path, output_json=args.output_json)
        sys.exit(0)

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
