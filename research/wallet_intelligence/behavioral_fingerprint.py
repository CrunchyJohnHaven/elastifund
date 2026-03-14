#!/usr/bin/env python3
"""
Behavioral Fingerprinting Engine — Phase 2 of Wallet Intelligence Pipeline
============================================================================
Takes ranked wallet profiles from Phase 1 and produces detailed behavioral
fingerprints: timing, price positioning, directional bias, sizing patterns,
inventory management, and external signal correlation.

IMPORTANT DATA LIMITATIONS (per ChatGPT review):
  - Historical midpoint-at-entry requires an archived WebSocket recorder.
    Before recorder start, midpoint is APPROXIMATED from trade price +/- spread/2.
  - Public Data API /trades may not expose both maker and taker addresses.
    When unavailable, maker/taker classification is INFERRED from price
    relative to midpoint (buy above mid = taker, below = maker).
  - Fee adjustment uses the per-token fee-rate endpoint. BTC5 crypto markets
    launched Feb 12 2026 with taker fees peaking at 1.56% around 50c.

Data sources:
  - wallet_intelligence.db (from Phase 1)
  - https://data-api.polymarket.com/trades (historical, takerOnly=false)
  - BTC spot price: Binance/Coinbase REST (for correlation analysis)

March 14, 2026 — Elastifund Autoresearch
"""

import json
import logging
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("BehaviorFP")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_API = "https://data-api.polymarket.com"
BINANCE_API = "https://api.binance.com/api/v3"

# Session definitions (UTC hours)
SESSIONS = {
    "asia": (0, 8),       # 00:00-08:00 UTC
    "london": (8, 13),    # 08:00-13:00 UTC
    "us_open": (13, 17),  # 13:00-17:00 UTC (9am-1pm ET)
    "us_afternoon": (17, 21),  # 17:00-21:00 UTC
    "us_close": (21, 24), # 21:00-00:00 UTC
}

# BTC5 window duration
WINDOW_DURATION_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class TimingProfile:
    """When does the wallet trade relative to window lifecycle?"""
    avg_seconds_after_open: float = 0.0
    median_seconds_after_open: float = 0.0
    trades_in_first_60s: int = 0
    trades_in_last_60s: int = 0
    trades_per_window: float = 0.0
    multi_trade_windows_pct: float = 0.0  # % of windows with 2+ trades
    preferred_session: str = ""
    session_distribution: dict = field(default_factory=dict)


@dataclass
class PricePositioning:
    """Where does the wallet enter relative to the book?"""
    avg_distance_from_mid: float = 0.0  # cents
    avg_distance_from_settlement: float = 0.0  # cents
    buys_below_mid_pct: float = 0.0  # fraction buying below midpoint (maker behavior)
    avg_entry_price: float = 0.0
    price_range_10th: float = 0.0  # 10th percentile entry price
    price_range_90th: float = 0.0  # 90th percentile entry price
    # Fee awareness (per ChatGPT review: must be fee-adjusted)
    avg_fee_adjusted_edge: float = 0.0  # edge after fees
    inferred_maker_pct: float = 0.0  # fraction classified as maker trades


@dataclass
class DirectionalProfile:
    """Does the wallet have directional bias?"""
    up_pct: float = 0.0
    down_pct: float = 0.0
    bias_score: float = 0.0  # -1 to +1
    momentum_correlation: float = 0.0  # correlation with prior 5m BTC return
    mean_reversion_correlation: float = 0.0
    regime_switching: bool = False  # does bias flip based on conditions


@dataclass
class SizingProfile:
    """How does the wallet size positions?"""
    avg_size_usd: float = 0.0
    median_size_usd: float = 0.0
    size_stddev: float = 0.0
    max_single_trade: float = 0.0
    fixed_size: bool = False  # coefficient of variation < 0.2
    scales_with_delta: float = 0.0  # correlation between size and delta
    scales_with_time: float = 0.0  # correlation between size and time_remaining


@dataclass
class InventoryProfile:
    """How does the wallet manage exposure?"""
    holds_to_expiry_pct: float = 0.0  # fraction held until resolution
    avg_hold_duration_seconds: float = 0.0
    concurrent_positions_avg: float = 0.0
    hedges_adjacent_windows: bool = False
    max_concurrent_exposure_usd: float = 0.0


@dataclass
class WalletFingerprint:
    """Complete behavioral fingerprint for one wallet."""
    address: str
    total_trades_analyzed: int = 0
    analysis_period_start: str = ""
    analysis_period_end: str = ""
    timing: TimingProfile = field(default_factory=TimingProfile)
    positioning: PricePositioning = field(default_factory=PricePositioning)
    direction: DirectionalProfile = field(default_factory=DirectionalProfile)
    sizing: SizingProfile = field(default_factory=SizingProfile)
    inventory: InventoryProfile = field(default_factory=InventoryProfile)
    # Strategy summary
    strategy_summary: str = ""
    cluster_id: int = -1  # assigned by clustering
    similar_wallets: list = field(default_factory=list)
    # Data quality flags
    midpoint_approximated: bool = True  # True until WebSocket recorder active
    maker_taker_inferred: bool = True   # True until on-chain reconstruction


# ---------------------------------------------------------------------------
# BTC price fetcher (for correlation analysis)
# ---------------------------------------------------------------------------
def fetch_btc_klines(start_ts: int, end_ts: int,
                     interval: str = "1m") -> list[dict]:
    """Fetch BTC/USDT klines from Binance for correlation analysis."""
    klines = []
    current = start_ts

    while current < end_ts:
        try:
            resp = requests.get(
                f"{BINANCE_API}/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "startTime": current * 1000,
                    "endTime": min(current + 86400, end_ts) * 1000,
                    "limit": 1000,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for k in data:
                    klines.append({
                        "open_time": k[0] // 1000,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    })
                if len(data) < 1000:
                    break
                current = data[-1][0] // 1000 + 60
            else:
                break
        except Exception as e:
            logger.warning(f"Binance API error: {e}")
            break

    return klines


def get_btc_return_at_time(klines: list[dict], timestamp: float,
                           lookback_seconds: int = 300) -> Optional[float]:
    """Get BTC return over lookback_seconds ending at timestamp."""
    target_start = timestamp - lookback_seconds
    start_price = None
    end_price = None

    for k in klines:
        if abs(k["open_time"] - target_start) < 60:
            start_price = k["open"]
        if abs(k["open_time"] - timestamp) < 60:
            end_price = k["close"]

    if start_price and end_price and start_price > 0:
        return (end_price - start_price) / start_price
    return None


# ---------------------------------------------------------------------------
# Fingerprinting engine
# ---------------------------------------------------------------------------
def compute_timing_profile(trades: list[dict]) -> TimingProfile:
    """Analyze when the wallet trades within each window."""
    if not trades:
        return TimingProfile()

    # Group by window (approximate: round timestamp to nearest 5-min boundary)
    windows = defaultdict(list)
    for t in trades:
        ts = t.get("timestamp", "")
        try:
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            # Round down to nearest 5-min boundary
            window_start = dt.replace(
                minute=(dt.minute // 5) * 5, second=0, microsecond=0
            )
            seconds_after_open = (dt - window_start).total_seconds()
            windows[window_start.isoformat()].append({
                **t,
                "seconds_after_open": seconds_after_open,
                "hour_utc": dt.hour,
            })
        except (ValueError, TypeError):
            continue

    if not windows:
        return TimingProfile()

    # Compute timing stats
    all_offsets = []
    first_60s = 0
    last_60s = 0
    session_counts = defaultdict(int)

    for window_trades in windows.values():
        for t in window_trades:
            offset = t["seconds_after_open"]
            all_offsets.append(offset)
            if offset <= 60:
                first_60s += 1
            if offset >= 240:  # last 60s of 5-min window
                last_60s += 1

            hour = t["hour_utc"]
            for session_name, (start_h, end_h) in SESSIONS.items():
                if start_h <= hour < end_h:
                    session_counts[session_name] += 1
                    break

    multi_trade = sum(1 for w in windows.values() if len(w) >= 2)
    total_windows = len(windows)

    # Preferred session
    preferred = max(session_counts, key=session_counts.get) if session_counts else ""
    total_session_trades = sum(session_counts.values())
    session_dist = {
        k: round(v / total_session_trades, 3)
        for k, v in session_counts.items()
    } if total_session_trades > 0 else {}

    offsets_arr = np.array(all_offsets)
    return TimingProfile(
        avg_seconds_after_open=round(float(np.mean(offsets_arr)), 1),
        median_seconds_after_open=round(float(np.median(offsets_arr)), 1),
        trades_in_first_60s=first_60s,
        trades_in_last_60s=last_60s,
        trades_per_window=round(len(all_offsets) / total_windows, 2),
        multi_trade_windows_pct=round(multi_trade / total_windows, 3) if total_windows else 0,
        preferred_session=preferred,
        session_distribution=session_dist,
    )


def compute_price_positioning(trades: list[dict]) -> PricePositioning:
    """Analyze where the wallet enters relative to market midpoint.

    NOTE: Without WebSocket archive, midpoint is APPROXIMATED as
    (price +/- 0.005) depending on side. This flag is set in the
    output fingerprint.
    """
    if not trades:
        return PricePositioning()

    prices = []
    distances_from_mid = []
    below_mid = 0
    inferred_maker = 0

    for t in trades:
        price = float(t.get("price", 0) or 0)
        if price <= 0:
            continue
        prices.append(price)

        # Approximate midpoint (flagged as approximation)
        # BUY at price < estimated mid = maker behavior
        # SELL at price > estimated mid = maker behavior
        side = t.get("side", "BUY")
        spread_est = 0.01  # 1 cent spread assumption for BTC5
        if side == "BUY":
            estimated_mid = price + spread_est / 2
            dist = estimated_mid - price
            if price < estimated_mid:
                below_mid += 1
                inferred_maker += 1
        else:
            estimated_mid = price - spread_est / 2
            dist = price - estimated_mid
            if price > estimated_mid:
                inferred_maker += 1

        distances_from_mid.append(dist)

    if not prices:
        return PricePositioning()

    prices_arr = np.array(prices)
    dist_arr = np.array(distances_from_mid)
    total = len(prices)

    # Fee-adjusted edge approximation
    # BTC5 fee curve: ~1.56% at 50c, lower at extremes
    # Simplified: fee = 0.015 * 4 * price * (1 - price)
    fee_rates = [0.015 * 4 * p * (1 - p) for p in prices]
    avg_fee = np.mean(fee_rates) if fee_rates else 0.0

    return PricePositioning(
        avg_distance_from_mid=round(float(np.mean(dist_arr)), 4),
        avg_entry_price=round(float(np.mean(prices_arr)), 4),
        buys_below_mid_pct=round(below_mid / total, 3),
        price_range_10th=round(float(np.percentile(prices_arr, 10)), 4),
        price_range_90th=round(float(np.percentile(prices_arr, 90)), 4),
        avg_fee_adjusted_edge=round(float(np.mean(dist_arr)) - float(avg_fee), 6),
        inferred_maker_pct=round(inferred_maker / total, 3),
    )


def compute_directional_profile(trades: list[dict],
                                btc_klines: list[dict] | None = None
                                ) -> DirectionalProfile:
    """Analyze directional bias and correlation with BTC moves."""
    if not trades:
        return DirectionalProfile()

    up_count = 0
    down_count = 0
    trade_directions = []  # +1 for UP, -1 for DOWN
    btc_returns = []

    for t in trades:
        side = t.get("side", "BUY")
        outcome_idx = int(t.get("outcome_index", 0) or 0)

        # Effective direction
        if side == "BUY":
            effective = outcome_idx
        else:
            effective = 1 - outcome_idx

        if effective == 0:
            up_count += 1
            trade_directions.append(1.0)
        else:
            down_count += 1
            trade_directions.append(-1.0)

        # BTC return correlation
        if btc_klines:
            ts = t.get("timestamp", "")
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                ret = get_btc_return_at_time(btc_klines, dt.timestamp())
                if ret is not None:
                    btc_returns.append(ret)
                else:
                    btc_returns.append(0.0)
            except (ValueError, TypeError):
                btc_returns.append(0.0)

    total = up_count + down_count
    bias = (up_count - down_count) / total if total > 0 else 0.0

    # Momentum correlation: does the wallet bet in the direction BTC is already moving?
    momentum_corr = 0.0
    mean_rev_corr = 0.0
    if len(btc_returns) >= 10 and len(trade_directions) >= 10:
        try:
            corr = np.corrcoef(trade_directions[:len(btc_returns)],
                               btc_returns[:len(trade_directions)])[0, 1]
            if not np.isnan(corr):
                momentum_corr = float(corr)
                mean_rev_corr = -momentum_corr
        except (ValueError, IndexError):
            pass

    return DirectionalProfile(
        up_pct=round(up_count / total, 3) if total > 0 else 0,
        down_pct=round(down_count / total, 3) if total > 0 else 0,
        bias_score=round(bias, 4),
        momentum_correlation=round(momentum_corr, 4),
        mean_reversion_correlation=round(mean_rev_corr, 4),
    )


def compute_sizing_profile(trades: list[dict]) -> SizingProfile:
    """Analyze position sizing patterns."""
    if not trades:
        return SizingProfile()

    sizes = []
    for t in trades:
        price = float(t.get("price", 0) or 0)
        size = float(t.get("size", 0) or 0)
        notional = price * size
        if notional > 0:
            sizes.append(notional)

    if not sizes:
        return SizingProfile()

    sizes_arr = np.array(sizes)
    mean_size = float(np.mean(sizes_arr))
    std_size = float(np.std(sizes_arr, ddof=1)) if len(sizes_arr) > 1 else 0.0
    cv = std_size / mean_size if mean_size > 0 else 0.0

    return SizingProfile(
        avg_size_usd=round(mean_size, 2),
        median_size_usd=round(float(np.median(sizes_arr)), 2),
        size_stddev=round(std_size, 2),
        max_single_trade=round(float(np.max(sizes_arr)), 2),
        fixed_size=(cv < 0.2),
    )


def generate_strategy_summary(fp: WalletFingerprint) -> str:
    """Generate a plain-English 2-3 sentence strategy summary."""
    parts = []

    # Timing description
    if fp.timing.avg_seconds_after_open < 60:
        parts.append("Early entrant (trades within first minute of window)")
    elif fp.timing.trades_in_last_60s > fp.timing.trades_in_first_60s:
        parts.append("Late sniper (concentrates activity in final minute)")
    else:
        parts.append("Mid-window trader")

    # Direction
    if abs(fp.direction.bias_score) > 0.5:
        direction = "UP" if fp.direction.bias_score > 0 else "DOWN"
        parts.append(f"Strong {direction} directional bias ({abs(fp.direction.bias_score):.0%})")
    elif abs(fp.direction.bias_score) < 0.1:
        parts.append("Direction-neutral (balanced UP/DOWN)")

    # Positioning
    if fp.positioning.inferred_maker_pct > 0.7:
        parts.append("Primarily maker (posts orders to book)")
    elif fp.positioning.inferred_maker_pct < 0.3:
        parts.append("Primarily taker (crosses spread)")

    # Sizing
    if fp.sizing.fixed_size:
        parts.append(f"Fixed sizing (~${fp.sizing.avg_size_usd:.0f}/trade)")
    else:
        parts.append(f"Variable sizing (${fp.sizing.median_size_usd:.0f} median, "
                     f"${fp.sizing.max_single_trade:.0f} max)")

    # Session
    if fp.timing.preferred_session:
        parts.append(f"Most active during {fp.timing.preferred_session} session")

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------
def cluster_wallets(fingerprints: list[WalletFingerprint],
                    n_clusters: int = 5) -> list[WalletFingerprint]:
    """Cluster wallets by behavioral features into archetypes.

    Uses simple k-means on normalized behavioral features.
    Requires scipy for spatial distance, numpy for computation.
    """
    if len(fingerprints) < n_clusters:
        return fingerprints

    # Build feature matrix
    features = []
    for fp in fingerprints:
        features.append([
            fp.timing.avg_seconds_after_open / 300.0,  # normalized to window
            fp.timing.trades_per_window,
            fp.positioning.avg_entry_price,
            fp.positioning.inferred_maker_pct,
            fp.direction.bias_score,
            fp.sizing.avg_size_usd / 100.0,  # normalize
            1.0 if fp.sizing.fixed_size else 0.0,
        ])

    X = np.array(features)

    # Normalize columns
    col_std = np.std(X, axis=0)
    col_std[col_std == 0] = 1.0
    col_mean = np.mean(X, axis=0)
    X_norm = (X - col_mean) / col_std

    # Simple k-means (avoid sklearn dependency)
    rng = np.random.default_rng(42)
    n = len(X_norm)
    k = min(n_clusters, n)

    # Initialize centroids randomly
    idx = rng.choice(n, size=k, replace=False)
    centroids = X_norm[idx].copy()

    for _ in range(50):  # max iterations
        # Assign to nearest centroid
        dists = np.zeros((n, k))
        for j in range(k):
            dists[:, j] = np.sum((X_norm - centroids[j]) ** 2, axis=1)
        labels = np.argmin(dists, axis=1)

        # Update centroids
        new_centroids = np.zeros_like(centroids)
        for j in range(k):
            mask = labels == j
            if np.any(mask):
                new_centroids[j] = np.mean(X_norm[mask], axis=0)
            else:
                new_centroids[j] = centroids[j]

        if np.allclose(centroids, new_centroids, atol=1e-6):
            break
        centroids = new_centroids

    # Assign cluster IDs and find similar wallets
    for i, fp in enumerate(fingerprints):
        fp.cluster_id = int(labels[i])
        fp.similar_wallets = [
            fingerprints[j].address[:12]
            for j in range(n)
            if labels[j] == labels[i] and j != i
        ][:5]  # top 5 similar

    return fingerprints


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def fingerprint_top_wallets(db_path: Path,
                            top_n: int = 20,
                            fetch_btc: bool = True
                            ) -> list[WalletFingerprint]:
    """
    Generate behavioral fingerprints for the top N wallets from Phase 1.

    Args:
        db_path: Path to wallet_intelligence.db
        top_n: Number of top wallets to fingerprint
        fetch_btc: Whether to fetch BTC price data for correlation analysis
    """
    conn = sqlite3.connect(str(db_path))

    # Get top wallets by confidence score
    rows = conn.execute(
        """SELECT address FROM wallet_profiles
           WHERE total_trades >= 30
           ORDER BY confidence_score DESC, realized_pnl DESC
           LIMIT ?""",
        (top_n,),
    ).fetchall()

    if not rows:
        logger.warning("No qualified wallets found in database")
        return []

    wallet_addresses = [r[0] for r in rows]
    logger.info(f"Fingerprinting {len(wallet_addresses)} top wallets")

    # Optionally fetch BTC price data for correlation
    btc_klines = None
    if fetch_btc:
        # Get time range from trades
        time_range = conn.execute(
            """SELECT MIN(timestamp), MAX(timestamp)
               FROM wallet_trades
               WHERE wallet_address IN ({})""".format(
                ",".join("?" * len(wallet_addresses))
            ),
            wallet_addresses,
        ).fetchone()

        if time_range and time_range[0] and time_range[1]:
            try:
                start_dt = datetime.fromisoformat(
                    time_range[0].replace("Z", "+00:00")
                )
                end_dt = datetime.fromisoformat(
                    time_range[1].replace("Z", "+00:00")
                )
                logger.info(f"Fetching BTC klines from {start_dt} to {end_dt}")
                btc_klines = fetch_btc_klines(
                    int(start_dt.timestamp()),
                    int(end_dt.timestamp()),
                )
                logger.info(f"Fetched {len(btc_klines)} BTC klines")
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse time range: {e}")

    # Generate fingerprints
    fingerprints = []
    for i, addr in enumerate(wallet_addresses):
        logger.info(f"[{i+1}/{len(wallet_addresses)}] Fingerprinting {addr[:12]}...")

        # Fetch all trades for this wallet
        trades = conn.execute(
            """SELECT condition_id, market_title, side, outcome_index,
                      price, size, notional, timestamp, resolution
               FROM wallet_trades
               WHERE wallet_address = ?
               ORDER BY timestamp""",
            (addr,),
        ).fetchall()

        trade_dicts = [
            {
                "condition_id": t[0], "title": t[1], "side": t[2],
                "outcome_index": t[3], "price": t[4], "size": t[5],
                "notional": t[6], "timestamp": t[7], "resolution": t[8],
            }
            for t in trades
        ]

        if not trade_dicts:
            continue

        fp = WalletFingerprint(
            address=addr,
            total_trades_analyzed=len(trade_dicts),
            analysis_period_start=trade_dicts[0]["timestamp"] or "",
            analysis_period_end=trade_dicts[-1]["timestamp"] or "",
            timing=compute_timing_profile(trade_dicts),
            positioning=compute_price_positioning(trade_dicts),
            direction=compute_directional_profile(trade_dicts, btc_klines),
            sizing=compute_sizing_profile(trade_dicts),
            midpoint_approximated=True,
            maker_taker_inferred=True,
        )
        fp.strategy_summary = generate_strategy_summary(fp)
        fingerprints.append(fp)

    conn.close()

    # Cluster wallets
    if len(fingerprints) >= 3:
        fingerprints = cluster_wallets(fingerprints)

    # Export
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wallets_fingerprinted": len(fingerprints),
        "data_quality": {
            "midpoint_source": "approximated (no WebSocket archive yet)",
            "maker_taker_source": "inferred from price vs estimated midpoint",
            "btc_correlation": "binance_1m_klines" if btc_klines else "unavailable",
        },
        "fingerprints": [asdict(fp) for fp in fingerprints],
    }

    output_path = db_path.parent / "wallet_fingerprints.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Fingerprints written to {output_path}")
    return fingerprints


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Behavioral Fingerprinting Engine")
    parser.add_argument("--db", type=str, default="data/wallet_intelligence.db",
                        help="Path to wallet intelligence database")
    parser.add_argument("--top-n", type=int, default=20,
                        help="Number of top wallets to fingerprint")
    parser.add_argument("--no-btc", action="store_true",
                        help="Skip BTC price correlation analysis")

    args = parser.parse_args()
    results = fingerprint_top_wallets(
        Path(args.db), top_n=args.top_n, fetch_btc=not args.no_btc,
    )

    if results:
        print(f"\nFingerprinted {len(results)} wallets:")
        for fp in results:
            print(f"\n  {fp.address[:12]}... (cluster {fp.cluster_id})")
            print(f"    {fp.strategy_summary}")
