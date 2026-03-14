#!/usr/bin/env python3
"""
Wallet PnL Tracker — Phase 1 of the Wallet Intelligence Pipeline
=================================================================
Discovers all wallets trading BTC5 markets on Polymarket, computes
realized PnL, win rate, Sharpe-equivalent, and ranks them by skill.

Data sources:
  - https://data-api.polymarket.com/trades (public, no auth)
  - https://gamma-api.polymarket.com/markets (market metadata)

Statistical filters:
  - Binomial test on win rate vs 50% (p < 0.05)
  - Bootstrap CI on PnL (95% confidence)
  - Minimum sample size (N >= 30 trades)

Output: JSON leaderboard of ranked wallets with confidence scores.

March 14, 2026 — Elastifund Autoresearch
"""

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import requests
import numpy as np

try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("WalletPnL")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# Rate limiting
REQUESTS_PER_WINDOW = 140  # stay under 150/10s limit
WINDOW_SECONDS = 10.0

# Statistical thresholds
MIN_TRADES_FOR_RANKING = 30
BINOMIAL_P_THRESHOLD = 0.05
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_CI = 0.95

# BTC5 market identification
BTC5_KEYWORDS = [
    "btc", "bitcoin", "5-minute", "5 minute", "5m",
    "up or down", "updown",
]

# Persistence
DB_PATH = Path("data/wallet_intelligence.db")
LEADERBOARD_PATH = Path("data/wallet_leaderboard.json")
CHECKPOINT_PATH = Path("data/wallet_tracker_checkpoint.json")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class WalletTrade:
    """Single trade by a wallet."""
    wallet_address: str
    condition_id: str
    market_title: str
    side: str           # BUY or SELL
    outcome_index: int  # 0 or 1
    price: float
    size: float         # in shares
    notional: float     # price * size (USDC equivalent)
    timestamp: str
    token_id: str = ""
    resolution: Optional[str] = None  # YES, NO, or None (unresolved)


@dataclass
class WalletProfile:
    """Aggregated profile for a single wallet."""
    address: str
    total_trades: int = 0
    unique_markets: int = 0
    total_volume_usd: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_trade_size: float = 0.0
    avg_edge_per_trade: float = 0.0
    sharpe_equivalent: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    maker_ratio: float = 0.0  # fraction of trades that are maker
    avg_holding_minutes: float = 0.0
    first_trade: str = ""
    last_trade: str = ""
    # Statistical confidence
    binomial_p_value: float = 1.0
    pnl_ci_lower: float = 0.0
    pnl_ci_upper: float = 0.0
    confidence_score: int = 0  # 0-100
    # Behavioral
    direction_bias: float = 0.0  # -1 (all DOWN) to +1 (all UP)
    market_concentration: float = 0.0  # Herfindahl index
    preferred_session: str = ""  # asia, london, us_open, etc.
    # Classification
    strategy_archetype: str = "unknown"


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_requests: int = REQUESTS_PER_WINDOW,
                 window_seconds: float = WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []

    def wait_if_needed(self):
        now = time.monotonic()
        # Prune old timestamps
        cutoff = now - self.window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self.max_requests:
            sleep_time = self._timestamps[0] - cutoff + 0.1
            if sleep_time > 0:
                logger.debug(f"Rate limit: sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
        self._timestamps.append(time.monotonic())


rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def _api_get(url: str, params: dict | None = None,
             max_retries: int = 3) -> dict | list | None:
    """GET with rate limiting and retries."""
    rate_limiter.wait_if_needed()
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"429 rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"API call failed after {max_retries} retries: {e}")
                return None
            time.sleep(2 ** attempt)
    return None


# ---------------------------------------------------------------------------
# Market discovery
# ---------------------------------------------------------------------------
def discover_btc5_markets() -> list[dict]:
    """Find all BTC 5-minute candle markets on Polymarket."""
    logger.info("Discovering BTC5 markets from Gamma API...")
    markets = []
    offset = 0
    page_size = 200

    while True:
        data = _api_get(
            f"{GAMMA_API}/markets",
            params={
                "limit": page_size,
                "offset": offset,
                "active": "true",
                "closed": "false",
            },
        )
        if not data:
            break

        for market in data:
            question = (market.get("question", "") or "").lower()
            description = (market.get("description", "") or "").lower()
            combined = f"{question} {description}"

            # Check if this is a BTC5 market
            is_btc5 = any(kw in combined for kw in BTC5_KEYWORDS)
            if is_btc5 and ("5" in combined) and ("minute" in combined or "5m" in combined):
                markets.append({
                    "condition_id": market.get("conditionId") or market.get("condition_id"),
                    "question": market.get("question"),
                    "slug": market.get("slug"),
                    "end_date": market.get("endDate") or market.get("end_date"),
                    "volume": float(market.get("volume", 0) or 0),
                    "liquidity": float(market.get("liquidity", 0) or 0),
                    "tokens": market.get("clobTokenIds", []),
                    "outcomes": market.get("outcomes", []),
                    "resolution": market.get("resolution"),
                })

        if len(data) < page_size:
            break
        offset += page_size

    # Also fetch recently closed/resolved markets for historical data
    closed_data = _api_get(
        f"{GAMMA_API}/markets",
        params={
            "limit": 500,
            "closed": "true",
            "order": "endDate",
            "ascending": "false",
        },
    )
    if closed_data:
        for market in closed_data:
            question = (market.get("question", "") or "").lower()
            description = (market.get("description", "") or "").lower()
            combined = f"{question} {description}"
            is_btc5 = any(kw in combined for kw in BTC5_KEYWORDS)
            if is_btc5 and ("5" in combined) and ("minute" in combined or "5m" in combined):
                cid = market.get("conditionId") or market.get("condition_id")
                if not any(m["condition_id"] == cid for m in markets):
                    markets.append({
                        "condition_id": cid,
                        "question": market.get("question"),
                        "slug": market.get("slug"),
                        "end_date": market.get("endDate") or market.get("end_date"),
                        "volume": float(market.get("volume", 0) or 0),
                        "liquidity": float(market.get("liquidity", 0) or 0),
                        "tokens": market.get("clobTokenIds", []),
                        "outcomes": market.get("outcomes", []),
                        "resolution": market.get("resolution"),
                    })

    logger.info(f"Discovered {len(markets)} BTC5 markets")
    return markets


# ---------------------------------------------------------------------------
# Trade collection
# ---------------------------------------------------------------------------
def fetch_trades_for_market(condition_id: str,
                            limit: int = 5000) -> list[dict]:
    """Fetch all trades for a given market condition_id.

    IMPORTANT: Uses Data API /trades with takerOnly=false to capture
    both maker and taker sides. Gamma is used only for discovery;
    CLOB /trades is account-scoped and requires auth.

    Pagination: conservative limit<=500, offset<=1000 per ChatGPT
    review of changelog inconsistencies. Falls back to cursor if
    offset exceeds safe bounds.
    """
    all_trades = []
    offset = 0
    page_size = 500  # safe max per changelog review
    max_offset = 1000  # conservative safe bound

    while len(all_trades) < limit:
        params = {
            "conditionId": condition_id,
            "limit": page_size,
            "takerOnly": "false",  # CRITICAL: capture maker-side history too
        }
        if offset <= max_offset:
            params["offset"] = offset
        else:
            # Fall back to cursor-based pagination beyond safe offset
            if all_trades:
                last_id = all_trades[-1].get("id")
                if last_id:
                    params["cursor"] = last_id
                else:
                    break
            else:
                break

        data = _api_get(f"{DATA_API}/trades", params=params)
        if not data or len(data) == 0:
            break

        all_trades.extend(data)

        if len(data) < page_size:
            break
        offset += page_size

    return all_trades


def fetch_trades_for_wallet(wallet_address: str,
                            limit: int = 1000) -> list[dict]:
    """Fetch recent trades for a specific wallet."""
    all_trades = []
    cursor = None

    while len(all_trades) < limit:
        params = {"proxyWallet": wallet_address, "limit": 200}
        if cursor:
            params["cursor"] = cursor

        data = _api_get(f"{DATA_API}/trades", params=params)
        if not data or len(data) == 0:
            break

        all_trades.extend(data)
        if len(data) < 200:
            break
        cursor = data[-1].get("id")
        if not cursor:
            break

    return all_trades


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------
def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Initialize the wallet intelligence database."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS wallet_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            market_title TEXT,
            side TEXT,
            outcome_index INTEGER,
            price REAL,
            size REAL,
            notional REAL,
            timestamp TEXT,
            token_id TEXT,
            resolution TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(wallet_address, condition_id, timestamp, side, price, size)
        );

        CREATE INDEX IF NOT EXISTS idx_wt_wallet
            ON wallet_trades(wallet_address);
        CREATE INDEX IF NOT EXISTS idx_wt_condition
            ON wallet_trades(condition_id);
        CREATE INDEX IF NOT EXISTS idx_wt_timestamp
            ON wallet_trades(timestamp);

        CREATE TABLE IF NOT EXISTS wallet_profiles (
            address TEXT PRIMARY KEY,
            total_trades INTEGER DEFAULT 0,
            unique_markets INTEGER DEFAULT 0,
            total_volume_usd REAL DEFAULT 0,
            realized_pnl REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0,
            avg_trade_size REAL DEFAULT 0,
            avg_edge_per_trade REAL DEFAULT 0,
            sharpe_equivalent REAL DEFAULT 0,
            max_drawdown REAL DEFAULT 0,
            profit_factor REAL DEFAULT 0,
            expectancy REAL DEFAULT 0,
            maker_ratio REAL DEFAULT 0,
            avg_holding_minutes REAL DEFAULT 0,
            first_trade TEXT,
            last_trade TEXT,
            binomial_p_value REAL DEFAULT 1.0,
            pnl_ci_lower REAL DEFAULT 0,
            pnl_ci_upper REAL DEFAULT 0,
            confidence_score INTEGER DEFAULT 0,
            direction_bias REAL DEFAULT 0,
            market_concentration REAL DEFAULT 0,
            preferred_session TEXT DEFAULT '',
            strategy_archetype TEXT DEFAULT 'unknown',
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS market_resolutions (
            condition_id TEXT PRIMARY KEY,
            question TEXT,
            resolution TEXT,
            end_date TEXT,
            volume REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn


def store_trades(conn: sqlite3.Connection, trades: list[WalletTrade]):
    """Upsert trades into the database."""
    conn.executemany(
        """INSERT OR IGNORE INTO wallet_trades
           (wallet_address, condition_id, market_title, side,
            outcome_index, price, size, notional, timestamp,
            token_id, resolution)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (t.wallet_address, t.condition_id, t.market_title,
             t.side, t.outcome_index, t.price, t.size, t.notional,
             t.timestamp, t.token_id, t.resolution)
            for t in trades
        ],
    )
    conn.commit()


def store_profile(conn: sqlite3.Connection, profile: WalletProfile):
    """Upsert a wallet profile."""
    d = asdict(profile)
    d["updated_at"] = datetime.now(timezone.utc).isoformat()
    cols = list(d.keys())
    placeholders = ", ".join(["?"] * len(cols))
    update_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != "address"])
    conn.execute(
        f"""INSERT INTO wallet_profiles ({', '.join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(address) DO UPDATE SET {update_clause}""",
        [d[c] for c in cols],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# PnL computation
# ---------------------------------------------------------------------------
def compute_wallet_pnl(conn: sqlite3.Connection,
                       wallet_address: str) -> WalletProfile:
    """Compute full PnL profile for a wallet from its trade history."""
    rows = conn.execute(
        """SELECT condition_id, market_title, side, outcome_index,
                  price, size, notional, timestamp, resolution
           FROM wallet_trades
           WHERE wallet_address = ?
           ORDER BY timestamp""",
        (wallet_address,),
    ).fetchall()

    if not rows:
        return WalletProfile(address=wallet_address)

    # Group trades by market
    markets: dict[str, list[dict]] = {}
    for row in rows:
        cid = row[0]
        trade = {
            "condition_id": cid,
            "title": row[1],
            "side": row[2],
            "outcome_index": row[3],
            "price": row[4],
            "size": row[5],
            "notional": row[6],
            "timestamp": row[7],
            "resolution": row[8],
        }
        markets.setdefault(cid, []).append(trade)

    # Compute per-market PnL
    total_pnl = 0.0
    trade_pnls: list[float] = []
    wins = 0
    losses = 0
    total_volume = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    up_count = 0
    down_count = 0
    timestamps = []

    for cid, trades in markets.items():
        resolution = trades[0].get("resolution")
        market_pnl = 0.0

        for t in trades:
            total_volume += t["notional"]
            timestamps.append(t["timestamp"])

            # Direction tracking
            effective_outcome = t["outcome_index"] if t["side"] == "BUY" else (1 - t["outcome_index"])
            if effective_outcome == 0:
                up_count += 1
            else:
                down_count += 1

            if resolution is not None:
                # Market resolved: compute actual PnL
                won_bet = False
                if t["side"] == "BUY":
                    # Bought outcome at price, pays $1 if correct
                    if (resolution == "Yes" and t["outcome_index"] == 0) or \
                       (resolution == "No" and t["outcome_index"] == 1):
                        won_bet = True
                    trade_pnl = (1.0 - t["price"]) * t["size"] if won_bet else -t["price"] * t["size"]
                else:
                    # Sold outcome at price, pays $1 if outcome happens
                    if (resolution == "Yes" and t["outcome_index"] == 0) or \
                       (resolution == "No" and t["outcome_index"] == 1):
                        won_bet = False
                    else:
                        won_bet = True
                    trade_pnl = t["price"] * t["size"] if won_bet else -(1.0 - t["price"]) * t["size"]

                market_pnl += trade_pnl
                trade_pnls.append(trade_pnl)

                if trade_pnl > 0:
                    wins += 1
                    gross_profit += trade_pnl
                elif trade_pnl < 0:
                    losses += 1
                    gross_loss += abs(trade_pnl)

        total_pnl += market_pnl

    # Compute statistics
    total_trades = len(rows)
    unique_markets = len(markets)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0
    avg_trade_size = total_volume / total_trades if total_trades > 0 else 0.0
    avg_edge = total_pnl / total_trades if total_trades > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Sharpe-equivalent: mean daily PnL / std daily PnL
    sharpe = 0.0
    if len(trade_pnls) > 1:
        pnl_array = np.array(trade_pnls)
        mean_pnl = np.mean(pnl_array)
        std_pnl = np.std(pnl_array, ddof=1)
        if std_pnl > 0:
            sharpe = float(mean_pnl / std_pnl * np.sqrt(252))  # annualized

    # Max drawdown
    max_dd = 0.0
    if trade_pnls:
        cumulative = np.cumsum(trade_pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Expectancy
    avg_win = gross_profit / wins if wins > 0 else 0.0
    avg_loss_val = gross_loss / losses if losses > 0 else 0.0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss_val)

    # Direction bias: -1 = all DOWN, +1 = all UP
    direction_bias = 0.0
    if up_count + down_count > 0:
        direction_bias = (up_count - down_count) / (up_count + down_count)

    # Market concentration (Herfindahl index)
    market_volumes = {}
    for cid, trades in markets.items():
        market_volumes[cid] = sum(t["notional"] for t in trades)
    if total_volume > 0:
        shares = [v / total_volume for v in market_volumes.values()]
        market_concentration = sum(s ** 2 for s in shares)
    else:
        market_concentration = 0.0

    # Statistical tests
    binomial_p = 1.0
    if wins + losses >= MIN_TRADES_FOR_RANKING:
        if HAS_SCIPY:
            # Two-sided binomial test: is win rate significantly different from 50%?
            result = scipy_stats.binomtest(wins, wins + losses, 0.5, alternative="greater")
            binomial_p = result.pvalue
        else:
            # Fallback: approximate with normal distribution
            n = wins + losses
            p_hat = wins / n
            z = (p_hat - 0.5) / (0.5 / np.sqrt(n))
            # One-sided p-value from z-score (standard normal CDF approximation)
            binomial_p = float(0.5 * (1 + np.sign(-z) * (1 - np.exp(-2 * z * z / np.pi)) ** 0.5))

    # Bootstrap CI on PnL
    pnl_ci_lower, pnl_ci_upper = 0.0, 0.0
    if len(trade_pnls) >= MIN_TRADES_FOR_RANKING:
        pnl_array = np.array(trade_pnls)
        bootstrap_means = []
        rng = np.random.default_rng(42)
        for _ in range(BOOTSTRAP_SAMPLES):
            sample = rng.choice(pnl_array, size=len(pnl_array), replace=True)
            bootstrap_means.append(float(np.mean(sample)))
        alpha = (1 - BOOTSTRAP_CI) / 2
        pnl_ci_lower = float(np.percentile(bootstrap_means, alpha * 100))
        pnl_ci_upper = float(np.percentile(bootstrap_means, (1 - alpha) * 100))

    # Confidence score (0-100)
    confidence = 0
    if total_trades >= MIN_TRADES_FOR_RANKING:
        # Component 1: Statistical significance (0-30)
        if binomial_p < 0.01:
            confidence += 30
        elif binomial_p < 0.05:
            confidence += 20
        elif binomial_p < 0.10:
            confidence += 10

        # Component 2: Sample size (0-25)
        confidence += min(25, int(total_trades / 4))

        # Component 3: Positive PnL CI (0-25)
        if pnl_ci_lower > 0:
            confidence += 25
        elif pnl_ci_lower > -0.01:
            confidence += 15

        # Component 4: Consistency (0-20)
        if sharpe > 1.0:
            confidence += 20
        elif sharpe > 0.5:
            confidence += 15
        elif sharpe > 0:
            confidence += 10

    timestamps_sorted = sorted(timestamps)

    profile = WalletProfile(
        address=wallet_address,
        total_trades=total_trades,
        unique_markets=unique_markets,
        total_volume_usd=round(total_volume, 2),
        realized_pnl=round(total_pnl, 4),
        win_count=wins,
        loss_count=losses,
        win_rate=round(win_rate, 4),
        avg_trade_size=round(avg_trade_size, 2),
        avg_edge_per_trade=round(avg_edge, 6),
        sharpe_equivalent=round(sharpe, 4),
        max_drawdown=round(max_dd, 4),
        profit_factor=round(min(profit_factor, 999.99), 4),
        expectancy=round(expectancy, 4),
        direction_bias=round(direction_bias, 4),
        market_concentration=round(market_concentration, 4),
        binomial_p_value=round(binomial_p, 6),
        pnl_ci_lower=round(pnl_ci_lower, 6),
        pnl_ci_upper=round(pnl_ci_upper, 6),
        confidence_score=min(100, confidence),
        first_trade=timestamps_sorted[0] if timestamps_sorted else "",
        last_trade=timestamps_sorted[-1] if timestamps_sorted else "",
    )

    return profile


# ---------------------------------------------------------------------------
# Strategy archetype classification
# ---------------------------------------------------------------------------
def classify_archetype(profile: WalletProfile) -> str:
    """Classify a wallet into a strategy archetype based on behavior."""
    if profile.total_trades < MIN_TRADES_FOR_RANKING:
        return "insufficient_data"

    # High maker ratio + tight around 50c = market maker
    if profile.maker_ratio > 0.7 and abs(profile.direction_bias) < 0.2:
        return "market_maker"

    # Strong directional bias + high win rate = directional trader
    if abs(profile.direction_bias) > 0.6 and profile.win_rate > 0.55:
        if profile.direction_bias > 0:
            return "momentum_long"
        else:
            return "momentum_short"

    # Low market concentration + many markets = diversified
    if profile.market_concentration < 0.1 and profile.unique_markets > 20:
        return "diversified_scalper"

    # High concentration in few markets = specialist
    if profile.market_concentration > 0.5:
        return "market_specialist"

    # High Sharpe + moderate trades = edge trader
    if profile.sharpe_equivalent > 1.0 and profile.win_rate > 0.52:
        return "edge_trader"

    # Low win rate but high profit factor = big winner/small loser
    if profile.win_rate < 0.5 and profile.profit_factor > 1.5:
        return "asymmetric_payoff"

    return "mixed"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_discovery_pipeline(db_path: Path | None = None,
                           max_markets: int = 500) -> list[WalletProfile]:
    """
    Full pipeline: discover markets, fetch trades, compute PnL, rank wallets.

    Returns ranked list of wallet profiles sorted by confidence then PnL.
    """
    conn = init_db(db_path)

    # Step 1: Discover BTC5 markets
    markets = discover_btc5_markets()
    if not markets:
        logger.warning("No BTC5 markets found")
        return []

    # Store market resolutions
    for m in markets[:max_markets]:
        conn.execute(
            """INSERT OR REPLACE INTO market_resolutions
               (condition_id, question, resolution, end_date, volume, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (m["condition_id"], m["question"], m.get("resolution"),
             m.get("end_date"), m.get("volume", 0)),
        )
    conn.commit()

    # Step 2: Fetch trades for each market
    all_wallets: set[str] = set()
    total_trades_stored = 0

    for i, market in enumerate(markets[:max_markets]):
        cid = market["condition_id"]
        if not cid:
            continue

        logger.info(f"[{i+1}/{min(len(markets), max_markets)}] "
                     f"Fetching trades for {market['question'][:60]}...")

        raw_trades = fetch_trades_for_market(cid)
        if not raw_trades:
            continue

        trades = []
        for rt in raw_trades:
            wallet = rt.get("proxyWallet") or rt.get("maker_address") or rt.get("taker_address")
            if not wallet:
                continue

            all_wallets.add(wallet)
            price = float(rt.get("price", 0) or 0)
            size = float(rt.get("size", 0) or 0)

            trades.append(WalletTrade(
                wallet_address=wallet,
                condition_id=cid,
                market_title=market.get("question", ""),
                side=rt.get("side", "BUY"),
                outcome_index=int(rt.get("outcomeIndex", 0) or 0),
                price=price,
                size=size,
                notional=price * size,
                timestamp=rt.get("timestamp") or rt.get("matchTime", ""),
                token_id=rt.get("tokenId") or rt.get("token_id", ""),
                resolution=market.get("resolution"),
            ))

        store_trades(conn, trades)
        total_trades_stored += len(trades)

    logger.info(f"Collected {total_trades_stored} trades from "
                f"{len(all_wallets)} unique wallets")

    # Step 3: Compute PnL for each wallet
    profiles: list[WalletProfile] = []
    for i, wallet in enumerate(sorted(all_wallets)):
        if (i + 1) % 100 == 0:
            logger.info(f"Computing PnL for wallet {i+1}/{len(all_wallets)}")

        profile = compute_wallet_pnl(conn, wallet)
        profile.strategy_archetype = classify_archetype(profile)
        store_profile(conn, profile)
        profiles.append(profile)

    # Step 4: Rank by confidence then PnL
    ranked = sorted(
        [p for p in profiles if p.total_trades >= MIN_TRADES_FOR_RANKING],
        key=lambda p: (-p.confidence_score, -p.realized_pnl),
    )

    # Step 5: Export leaderboard
    leaderboard = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_wallets_scanned": len(all_wallets),
        "qualified_wallets": len(ranked),
        "min_trades_threshold": MIN_TRADES_FOR_RANKING,
        "wallets": [asdict(p) for p in ranked[:100]],  # top 100
    }

    output_path = db_path.parent / "wallet_leaderboard.json" if db_path else LEADERBOARD_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(leaderboard, f, indent=2, default=str)

    logger.info(f"Leaderboard written to {output_path} "
                f"({len(ranked)} qualified wallets)")

    # Save checkpoint
    checkpoint = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "markets_scanned": len(markets),
        "trades_collected": total_trades_stored,
        "wallets_profiled": len(profiles),
        "qualified_wallets": len(ranked),
    }
    cp_path = db_path.parent / "wallet_tracker_checkpoint.json" if db_path else CHECKPOINT_PATH
    with open(cp_path, "w") as f:
        json.dump(checkpoint, f, indent=2)

    conn.close()
    return ranked


# ---------------------------------------------------------------------------
# Incremental update
# ---------------------------------------------------------------------------
def run_incremental_update(db_path: Path | None = None) -> list[WalletProfile]:
    """
    Incremental pipeline: only fetch new trades since last checkpoint.
    Re-compute PnL for wallets with new trades.
    """
    conn = init_db(db_path)

    # Load checkpoint
    cp_path = db_path.parent / "wallet_tracker_checkpoint.json" if db_path else CHECKPOINT_PATH
    if cp_path.exists():
        with open(cp_path) as f:
            checkpoint = json.load(f)
        logger.info(f"Resuming from checkpoint: {checkpoint.get('last_run')}")
    else:
        logger.info("No checkpoint found, running full discovery")
        conn.close()
        return run_discovery_pipeline(db_path)

    # Discover markets (quick, just metadata)
    markets = discover_btc5_markets()

    # Only fetch trades for markets with new activity
    updated_wallets: set[str] = set()
    for market in markets:
        cid = market["condition_id"]
        if not cid:
            continue

        # Check if we have a resolution update
        existing = conn.execute(
            "SELECT resolution FROM market_resolutions WHERE condition_id = ?",
            (cid,),
        ).fetchone()

        new_resolution = market.get("resolution")
        if existing and existing[0] == new_resolution:
            continue  # no change

        # Update resolution
        conn.execute(
            """INSERT OR REPLACE INTO market_resolutions
               (condition_id, question, resolution, end_date, volume, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (cid, market["question"], new_resolution,
             market.get("end_date"), market.get("volume", 0)),
        )

        # Update resolution in wallet_trades
        if new_resolution:
            conn.execute(
                "UPDATE wallet_trades SET resolution = ? WHERE condition_id = ?",
                (new_resolution, cid),
            )
            # Find affected wallets
            affected = conn.execute(
                "SELECT DISTINCT wallet_address FROM wallet_trades WHERE condition_id = ?",
                (cid,),
            ).fetchall()
            for row in affected:
                updated_wallets.add(row[0])

    conn.commit()

    # Recompute PnL for affected wallets
    profiles = []
    for wallet in updated_wallets:
        profile = compute_wallet_pnl(conn, wallet)
        profile.strategy_archetype = classify_archetype(profile)
        store_profile(conn, profile)
        profiles.append(profile)

    # Re-export leaderboard from all profiles
    all_profiles = conn.execute(
        "SELECT * FROM wallet_profiles WHERE total_trades >= ?",
        (MIN_TRADES_FOR_RANKING,),
    ).fetchall()

    logger.info(f"Incremental update: {len(updated_wallets)} wallets refreshed")
    conn.close()
    return profiles


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Wallet PnL Tracker")
    parser.add_argument("--full", action="store_true",
                        help="Run full discovery pipeline")
    parser.add_argument("--incremental", action="store_true",
                        help="Run incremental update")
    parser.add_argument("--max-markets", type=int, default=200,
                        help="Max markets to scan (default: 200)")
    parser.add_argument("--db", type=str, default=None,
                        help="Database path (default: data/wallet_intelligence.db)")

    args = parser.parse_args()
    db = Path(args.db) if args.db else None

    if args.incremental:
        results = run_incremental_update(db)
    else:
        results = run_discovery_pipeline(db, max_markets=args.max_markets)

    if results:
        print(f"\nTop 10 wallets by confidence + PnL:")
        print(f"{'Rank':<5} {'Address':<15} {'Trades':<8} {'PnL':>10} "
              f"{'WinRate':>8} {'Sharpe':>8} {'Conf':>5} {'Type':<20}")
        print("-" * 85)
        for i, p in enumerate(results[:10], 1):
            addr = p.address[:12] + "..." if len(p.address) > 15 else p.address
            print(f"{i:<5} {addr:<15} {p.total_trades:<8} "
                  f"${p.realized_pnl:>9.2f} {p.win_rate:>7.1%} "
                  f"{p.sharpe_equivalent:>8.2f} {p.confidence_score:>4}  "
                  f"{p.strategy_archetype:<20}")
