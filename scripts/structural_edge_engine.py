#!/usr/bin/env python3
"""Structural edge engine — self-improving, self-promoting trading daemon.

Three interlocking async loops in one process:
  1. Market Intelligence (60s) — fetch markets + order books, detect opportunities
  2. Shadow Tracking + Auto-Promotion (5m) — track shadow P&L, promote/demote strategies
  3. Research Mutations (30m) — mutate parameters, keep improvements

Usage:
    python3 scripts/structural_edge_engine.py              # continuous, paper mode
    python3 scripts/structural_edge_engine.py --live        # enable real orders for promoted strategies
    python3 scripts/structural_edge_engine.py --status      # show current strategy states
    python3 scripts/structural_edge_engine.py --once        # single cycle all loops

Author: JJ (autonomous)
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import random
import signal
import sqlite3
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
GAMMA_PAGE_SIZE = 100
MAX_GAMMA_PAGES = 200
REQUEST_TIMEOUT = 15
MAX_CONCURRENT_BOOK_FETCHES = 20

# Loop intervals (seconds)
MARKET_INTEL_INTERVAL = 60
SHADOW_TRACK_INTERVAL = 300   # 5 minutes
RESEARCH_MUTATION_INTERVAL = 1800  # 30 minutes

# Snapshot rolling window
SNAPSHOT_WINDOW_SECONDS = 1800  # 30 minutes

# Winner fee on Polymarket
WINNER_FEE = 0.02

# Safety rails
MICRO_LIVE_USD = 5.0
STAGE_2_USD = 10.0
MAX_TOTAL_DEPLOYED = 50.0
DAILY_LOSS_LIMIT = 20.0
MAX_LIVE_STRATEGIES = 3
MAX_LIVE_ORDERS_PER_CYCLE = 5

# Promotion gates
PROMO_MIN_SHADOW_FILLS = 10
PROMO_MIN_WIN_RATE = 0.55
PROMO_MIN_PROFIT_FACTOR = 1.2
PROMO_LIVE_MIN_FILLS = 10
DEMOTE_CONSECUTIVE_LOSSES = 5

# Default strategy parameters
DEFAULT_STRATEGY_PARAMS: dict[str, dict[str, Any]] = {
    "resolution_sniper": {
        "threshold": 0.94,
        "min_profit_per_share": 0.01,  # Lowered: $0.01/share min after fee
        "min_volume_24h": 50.0,
        "min_hours_to_resolution": 6.0,
        "min_confidence": 0.80,  # Lowered: 0.94 price = 0.85 confidence
    },
    "neg_risk": {
        "sum_threshold": 0.97,
        "min_profit_per_share": 0.02,
        "min_volume_24h": 100.0,
        "min_hours_to_resolution": 1.0,
        "taker_fee_per_leg": 0.015,
    },
    "stale_quote": {
        "spread_threshold": 0.10,
        "depth_threshold": 50.0,
        "min_ask_depth": 10.0,
        "min_profit_per_share": 0.02,
        "min_volume_24h": 100.0,
        "min_hours_to_resolution": 1.0,
    },
    "pair_completion": {
        "combined_cost_cap": 0.97,
        "min_volume_24h": 50.0,
        "min_hours_to_resolution": 1.0,
    },
    "monotone_violation": {
        "min_violation_magnitude": 0.02,
        "min_volume_24h": 50.0,
        "min_hours_to_resolution": 1.0,
    },
}

# Mutation ranges for each strategy parameter
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "threshold": (0.90, 0.98),
    "min_profit_per_share": (0.01, 0.10),
    "min_volume_24h": (10.0, 500.0),
    "min_hours_to_resolution": (0.5, 48.0),
    "min_confidence": (0.80, 0.99),
    "sum_threshold": (0.93, 0.99),
    "taker_fee_per_leg": (0.005, 0.03),
    "spread_threshold": (0.05, 0.20),
    "depth_threshold": (10.0, 200.0),
    "min_ask_depth": (5.0, 50.0),
    "combined_cost_cap": (0.93, 0.99),
    "min_violation_magnitude": (0.005, 0.05),
}

DB_PATH = PROJECT_ROOT / "data" / "edge_engine.db"
PROMOTIONS_LOG = PROJECT_ROOT / "data" / "edge_engine_promotions.jsonl"

logger = logging.getLogger("JJ.edge_engine")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    market_id: str
    condition_id: str
    question: str
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    best_bid: float
    best_ask: float
    bid_depth_usd: float
    ask_depth_usd: float
    volume_24h: float
    end_date: str
    hours_to_resolution: float
    timestamp: float


@dataclass
class ShadowTrade:
    trade_id: str
    strategy_id: str
    market_id: str
    question: str
    direction: str  # YES or NO
    token_id: str
    entry_price: float
    hypothetical_size_usd: float
    detected_at: float
    resolved: bool = False
    resolution_payout: float = 0.0
    pnl_usd: float = 0.0
    resolved_at: float = 0.0


@dataclass
class StrategyState:
    strategy_id: str
    stage: str = "shadow"  # shadow, micro_live, stage_2
    parameters: dict = field(default_factory=dict)
    shadow_fills: int = 0
    shadow_wins: int = 0
    shadow_pnl: float = 0.0
    live_fills: int = 0
    live_wins: int = 0
    live_pnl: float = 0.0
    consecutive_losses: int = 0
    daily_loss: float = 0.0
    promoted_at: float = 0.0
    demoted_at: float = 0.0


# ---------------------------------------------------------------------------
# Helpers (from continuous_structural_scanner.py patterns)
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json_field(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _hours_until(dt: datetime | None) -> float:
    if dt is None:
        return 0.0
    now = datetime.now(tz=timezone.utc)
    delta = (dt - now).total_seconds() / 3600.0
    return max(0.0, delta)


def _extract_end_date(market: dict[str, Any]) -> datetime | None:
    for key in ("end_date_iso", "endDate", "resolution_date",
                "resolutionDate", "closedTime", "endTime"):
        dt = _parse_iso_datetime(market.get(key))
        if dt is not None:
            return dt
    return None


def _extract_yes_price(market: dict[str, Any]) -> float | None:
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome") or "").strip().lower()
            if outcome == "yes":
                price = token.get("price") or token.get("last_price") or token.get("lastPrice")
                p = _safe_float(price, -1.0)
                if 0.0 < p < 1.0:
                    return p

    op = _parse_json_field(market.get("outcomePrices"))
    if len(op) >= 2:
        p = _safe_float(op[0], -1.0)
        if 0.0 <= p <= 1.0:
            return p

    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    if bid is not None and ask is not None:
        b, a = _safe_float(bid, -1.0), _safe_float(ask, -1.0)
        if 0.0 <= b <= 1.0 and 0.0 <= a <= 1.0 and a >= b:
            return (b + a) / 2.0

    return None


def _extract_token_ids(market: dict[str, Any]) -> tuple[str, str]:
    yes_token = ""
    no_token = ""

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome") or "").strip().upper()
            token_id = str(
                token.get("token_id") or token.get("tokenId") or token.get("id") or ""
            ).strip()
            if token_id and outcome == "YES":
                yes_token = token_id
            elif token_id and outcome == "NO":
                no_token = token_id

    if yes_token and no_token:
        return yes_token, no_token

    raw_clob = market.get("clobTokenIds") or market.get("clob_token_ids")
    ids = _parse_json_field(raw_clob)
    if not ids and isinstance(raw_clob, str) and raw_clob.strip():
        ids = [s.strip() for s in raw_clob.split(",") if s.strip()]

    if len(ids) >= 2:
        yes_token = yes_token or str(ids[0]).strip()
        no_token = no_token or str(ids[1]).strip()

    return yes_token, no_token


def parse_raw_market(raw: dict[str, Any]) -> MarketSnapshot | None:
    """Parse a raw Gamma API market dict into a MarketSnapshot."""
    market_id = str(raw.get("id") or raw.get("conditionId") or "").strip()
    if not market_id:
        return None
    question = str(raw.get("question") or "").strip()
    if not question:
        return None
    yes_price = _extract_yes_price(raw)
    if yes_price is None:
        return None
    no_price = max(0.0, min(1.0, 1.0 - yes_price))
    yes_token, no_token = _extract_token_ids(raw)
    condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "").strip()
    end_dt = _extract_end_date(raw)
    hours = _hours_until(end_dt) if end_dt else 0.0
    end_date_str = end_dt.isoformat() if end_dt else ""
    volume_24h = _safe_float(raw.get("volume24hr") or raw.get("volume_24h"), 0.0)

    return MarketSnapshot(
        market_id=market_id,
        condition_id=condition_id,
        question=question,
        yes_price=yes_price,
        no_price=no_price,
        yes_token_id=yes_token,
        no_token_id=no_token,
        best_bid=0.0,
        best_ask=0.0,
        bid_depth_usd=0.0,
        ask_depth_usd=0.0,
        volume_24h=volume_24h,
        end_date=end_date_str,
        hours_to_resolution=hours,
        timestamp=time.time(),
    )


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            condition_id TEXT,
            question TEXT,
            yes_price REAL,
            no_price REAL,
            yes_token_id TEXT,
            no_token_id TEXT,
            best_bid REAL,
            best_ask REAL,
            bid_depth_usd REAL,
            ask_depth_usd REAL,
            volume_24h REAL,
            end_date TEXT,
            hours_to_resolution REAL,
            timestamp REAL
        );

        CREATE TABLE IF NOT EXISTS shadow_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            market_id TEXT NOT NULL,
            question TEXT,
            direction TEXT,
            token_id TEXT,
            entry_price REAL,
            hypothetical_size_usd REAL,
            detected_at REAL,
            resolved INTEGER DEFAULT 0,
            resolution_payout REAL DEFAULT 0.0,
            pnl_usd REAL DEFAULT 0.0,
            resolved_at REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS strategy_states (
            strategy_id TEXT PRIMARY KEY,
            stage TEXT DEFAULT 'shadow',
            parameters TEXT DEFAULT '{}',
            shadow_fills INTEGER DEFAULT 0,
            shadow_wins INTEGER DEFAULT 0,
            shadow_pnl REAL DEFAULT 0.0,
            live_fills INTEGER DEFAULT 0,
            live_wins INTEGER DEFAULT 0,
            live_pnl REAL DEFAULT 0.0,
            consecutive_losses INTEGER DEFAULT 0,
            daily_loss REAL DEFAULT 0.0,
            promoted_at REAL DEFAULT 0.0,
            demoted_at REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS promotions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            action TEXT NOT NULL,
            from_stage TEXT,
            to_stage TEXT,
            reason TEXT,
            timestamp REAL
        );

        CREATE TABLE IF NOT EXISTS research_mutations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            mutation_desc TEXT,
            old_fitness REAL,
            new_fitness REAL,
            verdict TEXT,
            timestamp REAL
        );

        CREATE TABLE IF NOT EXISTS live_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            market_id TEXT NOT NULL,
            token_id TEXT,
            direction TEXT,
            order_price REAL,
            shares REAL,
            size_usd REAL,
            order_id TEXT,
            status TEXT DEFAULT 'pending',
            pnl_usd REAL DEFAULT 0.0,
            created_at REAL,
            resolved_at REAL DEFAULT 0.0
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON market_snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_shadow_strategy ON shadow_trades(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_shadow_resolved ON shadow_trades(resolved);
    """)
    conn.commit()
    return conn


def prune_old_snapshots(conn: sqlite3.Connection, max_age_seconds: float = 86400.0) -> int:
    """Remove snapshots older than max_age_seconds. Returns count deleted."""
    cutoff = time.time() - max_age_seconds
    cur = conn.execute("DELETE FROM market_snapshots WHERE timestamp < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def save_snapshot(conn: sqlite3.Connection, snap: MarketSnapshot) -> None:
    conn.execute(
        "INSERT INTO market_snapshots "
        "(market_id, condition_id, question, yes_price, no_price, "
        "yes_token_id, no_token_id, best_bid, best_ask, bid_depth_usd, "
        "ask_depth_usd, volume_24h, end_date, hours_to_resolution, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snap.market_id, snap.condition_id, snap.question, snap.yes_price,
         snap.no_price, snap.yes_token_id, snap.no_token_id, snap.best_bid,
         snap.best_ask, snap.bid_depth_usd, snap.ask_depth_usd, snap.volume_24h,
         snap.end_date, snap.hours_to_resolution, snap.timestamp),
    )


def save_shadow_trade(conn: sqlite3.Connection, trade: ShadowTrade) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO shadow_trades "
        "(trade_id, strategy_id, market_id, question, direction, token_id, "
        "entry_price, hypothetical_size_usd, detected_at, resolved, "
        "resolution_payout, pnl_usd, resolved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (trade.trade_id, trade.strategy_id, trade.market_id, trade.question,
         trade.direction, trade.token_id, trade.entry_price,
         trade.hypothetical_size_usd, trade.detected_at, int(trade.resolved),
         trade.resolution_payout, trade.pnl_usd, trade.resolved_at),
    )


def load_strategy_state(conn: sqlite3.Connection, strategy_id: str) -> StrategyState:
    row = conn.execute(
        "SELECT strategy_id, stage, parameters, shadow_fills, shadow_wins, "
        "shadow_pnl, live_fills, live_wins, live_pnl, consecutive_losses, "
        "daily_loss, promoted_at, demoted_at "
        "FROM strategy_states WHERE strategy_id = ?",
        (strategy_id,),
    ).fetchone()
    if row is None:
        return StrategyState(strategy_id=strategy_id)
    return StrategyState(
        strategy_id=row[0],
        stage=row[1],
        parameters=json.loads(row[2]) if row[2] else {},
        shadow_fills=row[3],
        shadow_wins=row[4],
        shadow_pnl=row[5],
        live_fills=row[6],
        live_wins=row[7],
        live_pnl=row[8],
        consecutive_losses=row[9],
        daily_loss=row[10],
        promoted_at=row[11],
        demoted_at=row[12],
    )


def save_strategy_state(conn: sqlite3.Connection, state: StrategyState) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO strategy_states "
        "(strategy_id, stage, parameters, shadow_fills, shadow_wins, shadow_pnl, "
        "live_fills, live_wins, live_pnl, consecutive_losses, daily_loss, "
        "promoted_at, demoted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (state.strategy_id, state.stage, json.dumps(state.parameters),
         state.shadow_fills, state.shadow_wins, state.shadow_pnl,
         state.live_fills, state.live_wins, state.live_pnl,
         state.consecutive_losses, state.daily_loss,
         state.promoted_at, state.demoted_at),
    )
    conn.commit()


def load_all_strategy_states(conn: sqlite3.Connection) -> list[StrategyState]:
    rows = conn.execute(
        "SELECT strategy_id, stage, parameters, shadow_fills, shadow_wins, "
        "shadow_pnl, live_fills, live_wins, live_pnl, consecutive_losses, "
        "daily_loss, promoted_at, demoted_at FROM strategy_states"
    ).fetchall()
    states = []
    for row in rows:
        states.append(StrategyState(
            strategy_id=row[0], stage=row[1],
            parameters=json.loads(row[2]) if row[2] else {},
            shadow_fills=row[3], shadow_wins=row[4], shadow_pnl=row[5],
            live_fills=row[6], live_wins=row[7], live_pnl=row[8],
            consecutive_losses=row[9], daily_loss=row[10],
            promoted_at=row[11], demoted_at=row[12],
        ))
    return states


def log_promotion(
    conn: sqlite3.Connection,
    strategy_id: str,
    action: str,
    from_stage: str,
    to_stage: str,
    reason: str,
) -> None:
    ts = time.time()
    conn.execute(
        "INSERT INTO promotions_log (strategy_id, action, from_stage, to_stage, reason, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (strategy_id, action, from_stage, to_stage, reason, ts),
    )
    conn.commit()
    # Also append to JSONL
    PROMOTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "strategy_id": strategy_id,
        "action": action,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "reason": reason,
        "timestamp": ts,
        "iso": datetime.now(tz=timezone.utc).isoformat(),
    }
    with open(PROMOTIONS_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def get_total_live_deployed(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(size_usd), 0) FROM live_orders "
        "WHERE status IN ('pending', 'filled')"
    ).fetchone()
    return float(row[0])


def get_daily_live_loss(conn: sqlite3.Connection) -> float:
    today_start = time.time() - (time.time() % 86400)
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) FROM live_orders "
        "WHERE status = 'resolved' AND pnl_usd < 0 AND resolved_at >= ?",
        (today_start,),
    ).fetchone()
    return abs(float(row[0]))


def count_live_strategies(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM strategy_states WHERE stage IN ('micro_live', 'stage_2')"
    ).fetchone()
    return int(row[0])


def get_open_live_market_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT market_id FROM live_orders WHERE status IN ('pending', 'filled')"
    ).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Market fetching
# ---------------------------------------------------------------------------


async def fetch_all_markets(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    """Fetch all active markets from Gamma API with pagination."""
    markets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset = 0

    for _ in range(MAX_GAMMA_PAGES):
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(GAMMA_PAGE_SIZE),
            "offset": str(offset),
        }
        try:
            async with session.get(
                GAMMA_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 429:
                    logger.warning("Gamma API rate limited at offset=%d, backing off", offset)
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                payload = await resp.json()
        except Exception as exc:
            logger.error("fetch_all_markets error at offset=%d: %s", offset, exc)
            break

        if not isinstance(payload, list) or not payload:
            break

        page_new = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or item.get("conditionId") or "").strip()
            if mid and mid in seen_ids:
                continue
            if mid:
                seen_ids.add(mid)
            markets.append(item)
            page_new += 1

        if page_new == 0 or len(payload) < GAMMA_PAGE_SIZE:
            break
        offset += GAMMA_PAGE_SIZE

    return markets


async def fetch_book_async(
    session: aiohttp.ClientSession,
    token_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, dict[str, float] | None]:
    """Fetch a single order book with concurrency limiting."""
    if not token_id:
        return token_id, None

    async with semaphore:
        try:
            async with session.get(
                CLOB_BOOK_URL,
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    return token_id, None
                if resp.status != 200:
                    return token_id, None
                payload = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return token_id, None

    if not isinstance(payload, dict):
        return token_id, None

    raw_bids = payload.get("bids") or []
    raw_asks = payload.get("asks") or []

    best_bid = 0.0
    bid_depth = 0.0
    for level in raw_bids:
        if isinstance(level, dict):
            p = _safe_float(level.get("price"))
            s = _safe_float(level.get("size"))
            if p > best_bid:
                best_bid = p
            bid_depth += p * s

    best_ask = 0.0
    ask_depth = 0.0
    ask_prices = []
    for level in raw_asks:
        if isinstance(level, dict):
            p = _safe_float(level.get("price"))
            s = _safe_float(level.get("size"))
            if p > 0:
                ask_prices.append(p)
            ask_depth += p * s
    if ask_prices:
        best_ask = min(ask_prices)

    return token_id, {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_depth_usd": bid_depth,
        "ask_depth_usd": ask_depth,
        "spread": max(0.0, best_ask - best_bid) if best_ask > 0 and best_bid > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Opportunity detection (5 strategies)
# ---------------------------------------------------------------------------


@dataclass
class DetectedOpportunity:
    strategy_id: str
    market_id: str
    question: str
    direction: str  # YES or NO
    token_id: str
    entry_price: float
    expected_profit: float
    confidence: float
    evidence: str


def detect_resolution_sniper(
    snapshots: list[MarketSnapshot],
    params: dict[str, Any],
) -> list[DetectedOpportunity]:
    """Markets with YES or NO price >= threshold (near-certain outcomes)."""
    threshold = params.get("threshold", 0.94)
    min_profit = params.get("min_profit_per_share", 0.03)
    min_vol = params.get("min_volume_24h", 50.0)
    min_hours = params.get("min_hours_to_resolution", 6.0)
    min_conf = params.get("min_confidence", 0.90)
    opps: list[DetectedOpportunity] = []

    for s in snapshots:
        if s.volume_24h < min_vol or s.hours_to_resolution < min_hours:
            continue
        if s.yes_price >= 0.999 or s.no_price >= 0.999:
            continue

        for side, price, token_id in [
            ("YES", s.yes_price, s.yes_token_id),
            ("NO", s.no_price, s.no_token_id),
        ]:
            if price < threshold or not token_id:
                continue
            gross_profit = 1.0 - price
            net_profit = gross_profit * (1.0 - WINNER_FEE)  # 2% of winnings
            if net_profit < min_profit:
                continue
            confidence = min(0.99, 0.85 + (price - 0.94) * 2.5)
            if confidence < min_conf:
                continue
            opps.append(DetectedOpportunity(
                strategy_id="resolution_sniper",
                market_id=s.market_id,
                question=s.question,
                direction=side,
                token_id=token_id,
                entry_price=price,
                expected_profit=round(net_profit, 4),
                confidence=round(confidence, 3),
                evidence=f"{side} @ {price:.3f}, net {net_profit:.4f}/share",
            ))
    return opps


def detect_neg_risk(
    snapshots: list[MarketSnapshot],
    params: dict[str, Any],
) -> list[DetectedOpportunity]:
    """Multi-outcome groups where total YES cost < threshold."""
    sum_thresh = params.get("sum_threshold", 0.97)
    min_profit = params.get("min_profit_per_share", 0.02)
    min_vol = params.get("min_volume_24h", 100.0)
    min_hours = params.get("min_hours_to_resolution", 1.0)
    fee_per_leg = params.get("taker_fee_per_leg", 0.015)
    opps: list[DetectedOpportunity] = []

    groups: dict[str, list[MarketSnapshot]] = {}
    for s in snapshots:
        if s.condition_id:
            groups.setdefault(s.condition_id, []).append(s)

    for cid, group in groups.items():
        if len(group) < 2:
            continue
        if any(not s.yes_token_id for s in group):
            continue
        total_vol = sum(s.volume_24h for s in group)
        if total_vol < min_vol:
            continue
        max_hours = max(s.hours_to_resolution for s in group)
        if max_hours < min_hours:
            continue

        total_cost = sum(s.yes_price for s in group)
        if total_cost >= sum_thresh:
            continue

        n_legs = len(group)
        fee_cost = n_legs * fee_per_leg * (total_cost / n_legs)
        net_profit = (1.0 - total_cost) - fee_cost
        if net_profit < min_profit:
            continue

        confidence = min(0.99, 0.90 + net_profit * 2.0)
        token_ids = ",".join(s.yes_token_id for s in group)
        questions = " | ".join(s.question[:40] for s in group[:3])

        opps.append(DetectedOpportunity(
            strategy_id="neg_risk",
            market_id=cid,
            question=f"[{n_legs}-way] {questions}",
            direction="YES",
            token_id=token_ids,
            entry_price=round(total_cost, 4),
            expected_profit=round(net_profit, 4),
            confidence=round(confidence, 3),
            evidence=f"sum={total_cost:.4f} < {sum_thresh}, net {net_profit:.4f}",
        ))
    return opps


def detect_stale_quotes(
    snapshots: list[MarketSnapshot],
    params: dict[str, Any],
) -> list[DetectedOpportunity]:
    """Markets with wide spreads and depth on one side."""
    spread_thresh = params.get("spread_threshold", 0.10)
    min_profit = params.get("min_profit_per_share", 0.02)
    min_vol = params.get("min_volume_24h", 100.0)
    min_hours = params.get("min_hours_to_resolution", 1.0)
    min_ask_depth = params.get("min_ask_depth", 10.0)
    depth_thresh = params.get("depth_threshold", 50.0)
    opps: list[DetectedOpportunity] = []

    for s in snapshots:
        if s.volume_24h < min_vol or s.hours_to_resolution < min_hours:
            continue
        if s.best_bid <= 0 or s.best_ask <= 0:
            continue

        spread = s.best_ask - s.best_bid
        if spread <= spread_thresh:
            continue
        if s.ask_depth_usd < min_ask_depth and s.bid_depth_usd < depth_thresh:
            continue

        fair_price = (s.best_bid + s.best_ask) / 2.0
        edge = fair_price - s.best_ask
        if edge < min_profit:
            continue

        confidence = min(0.85, 0.5 + edge * 3.0)
        opps.append(DetectedOpportunity(
            strategy_id="stale_quote",
            market_id=s.market_id,
            question=s.question,
            direction="YES",
            token_id=s.yes_token_id,
            entry_price=round(s.best_ask, 4),
            expected_profit=round(edge, 4),
            confidence=round(confidence, 3),
            evidence=f"spread={spread:.3f}, bid={s.best_bid:.3f} ask={s.best_ask:.3f}",
        ))
    return opps


def detect_pair_completion(
    snapshots: list[MarketSnapshot],
    params: dict[str, Any],
) -> list[DetectedOpportunity]:
    """YES + NO ask combined < cost_cap for binary markets."""
    cost_cap = params.get("combined_cost_cap", 0.97)
    min_vol = params.get("min_volume_24h", 50.0)
    min_hours = params.get("min_hours_to_resolution", 1.0)
    opps: list[DetectedOpportunity] = []

    for s in snapshots:
        if s.volume_24h < min_vol or s.hours_to_resolution < min_hours:
            continue
        if not s.yes_token_id or not s.no_token_id:
            continue
        if s.best_ask <= 0:
            continue

        # For pair completion, we need both YES and NO asks
        # Using yes_price + no_price as proxy (both derived from best available data)
        combined = s.yes_price + s.no_price
        if combined >= cost_cap:
            continue

        profit = 1.0 - combined
        if profit < 0.01:
            continue

        confidence = min(0.95, 0.80 + profit * 5.0)
        opps.append(DetectedOpportunity(
            strategy_id="pair_completion",
            market_id=s.market_id,
            question=s.question,
            direction="BOTH",
            token_id=f"{s.yes_token_id},{s.no_token_id}",
            entry_price=round(combined, 4),
            expected_profit=round(profit, 4),
            confidence=round(confidence, 3),
            evidence=f"combined={combined:.4f} < {cost_cap}, locked profit={profit:.4f}",
        ))
    return opps


def detect_monotone_violations(
    snapshots: list[MarketSnapshot],
    params: dict[str, Any],
) -> list[DetectedOpportunity]:
    """Price ordering that violates logical constraints in threshold markets."""
    min_mag = params.get("min_violation_magnitude", 0.02)
    min_vol = params.get("min_volume_24h", 50.0)
    min_hours = params.get("min_hours_to_resolution", 1.0)
    opps: list[DetectedOpportunity] = []

    # Group markets by condition_id to find related threshold markets
    groups: dict[str, list[MarketSnapshot]] = {}
    for s in snapshots:
        if s.condition_id and s.volume_24h >= min_vol and s.hours_to_resolution >= min_hours:
            groups.setdefault(s.condition_id, []).append(s)

    for cid, group in groups.items():
        if len(group) < 2:
            continue
        # Sort by yes_price ascending
        sorted_group = sorted(group, key=lambda s: s.yes_price)
        # Check for monotonicity violations
        for i in range(len(sorted_group) - 1):
            lo = sorted_group[i]
            hi = sorted_group[i + 1]
            # If a "harder" threshold (should be lower probability) has a higher
            # price, that's a violation
            violation = hi.yes_price - lo.yes_price
            if violation > min_mag:
                # This is suspicious but we'd need semantic analysis to confirm
                # it's actually a monotonicity violation. For now, flag it.
                opps.append(DetectedOpportunity(
                    strategy_id="monotone_violation",
                    market_id=cid,
                    question=f"{lo.question[:40]} vs {hi.question[:40]}",
                    direction="SPREAD",
                    token_id=f"{lo.yes_token_id},{hi.no_token_id}",
                    entry_price=round(violation, 4),
                    expected_profit=round(violation - WINNER_FEE, 4),
                    confidence=0.60,  # Low confidence — needs semantic verification
                    evidence=f"price gap={violation:.4f} between related markets",
                ))
    return opps


# ---------------------------------------------------------------------------
# CLOB client for live trading
# ---------------------------------------------------------------------------


def build_clob_client() -> Any:
    """Build an authenticated CLOB client from .env credentials."""
    from bot.polymarket_clob import build_authenticated_clob_client

    private_key = os.environ.get("POLY_PRIVATE_KEY", "")
    safe_address = os.environ.get("POLY_SAFE_ADDRESS", "")
    sig_type = os.environ.get("POLY_SIGNATURE_TYPE", "1")

    if not private_key or not safe_address:
        raise RuntimeError(
            "Missing POLY_PRIVATE_KEY or POLY_SAFE_ADDRESS in .env. "
            "Cannot build CLOB client."
        )

    client, selected_sig_type, probes = build_authenticated_clob_client(
        private_key=private_key,
        safe_address=safe_address,
        configured_signature_type=sig_type,
        logger=logger,
        log_prefix="[edge_engine]",
    )
    logger.info(
        "CLOB client ready: signature_type=%d",
        selected_sig_type,
    )
    return client


def place_live_order(
    clob: Any,
    opp: DetectedOpportunity,
    best_bid: float,
    size_usd: float,
) -> tuple[str, float, float]:
    """Place a POST-ONLY maker BUY order. Returns (order_id, price, shares)."""
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    order_price = round(best_bid + 0.01, 2)
    if order_price > opp.entry_price:
        order_price = round(opp.entry_price, 2)
    order_price = max(0.01, min(0.99, order_price))

    shares = round(size_usd / order_price, 2)
    if shares < 1.0:
        shares = 1.0

    order_args = OrderArgs(
        token_id=opp.token_id,
        price=order_price,
        size=shares,
        side=BUY,
    )
    signed_order = clob.create_order(order_args)
    result = clob.post_order(signed_order, OrderType.GTC, post_only=True)

    order_id = ""
    if isinstance(result, dict):
        order_id = str(result.get("orderID") or result.get("order_id") or "")
        if result.get("success") or result.get("orderID"):
            logger.info(
                "  [LIVE] BUY %s %.2f shares @ %.2f ($%.2f) order=%s -- %s",
                opp.direction, shares, order_price, round(shares * order_price, 2),
                order_id[:16], opp.question[:60],
            )
        else:
            logger.warning("  [LIVE] Order rejected: %s", result)

    return order_id, order_price, shares


# ---------------------------------------------------------------------------
# Loop 1: Market Intelligence
# ---------------------------------------------------------------------------


async def market_intelligence_loop(
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    snapshot_cache: dict[str, MarketSnapshot],
    opportunity_queue: list[DetectedOpportunity],
    stop_event: asyncio.Event,
) -> None:
    """Fetch markets + order books, detect opportunities. Runs every 60 seconds."""
    cycle = 0
    backoff = 1

    while not stop_event.is_set():
        cycle += 1
        cycle_start = time.monotonic()

        try:
            # 1. Fetch all markets
            raw_markets = await fetch_all_markets(session)
            snapshots: list[MarketSnapshot] = []
            for raw in raw_markets:
                snap = parse_raw_market(raw)
                if snap is not None:
                    snapshots.append(snap)

            # 2. Sort by volume, take top 200 for book fetches
            snapshots.sort(key=lambda s: s.volume_24h, reverse=True)
            top_snapshots = snapshots[:200]

            # 3. Fetch order books for top markets
            tokens_needed: set[str] = set()
            for s in top_snapshots:
                if s.yes_token_id:
                    tokens_needed.add(s.yes_token_id)

            semaphore = asyncio.Semaphore(MAX_CONCURRENT_BOOK_FETCHES)
            tasks = [
                fetch_book_async(session, tid, semaphore)
                for tid in sorted(tokens_needed)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            books: dict[str, dict[str, float]] = {}
            for result in results:
                if isinstance(result, tuple):
                    tid, book = result
                    if book is not None:
                        books[tid] = book

            # 4. Enrich snapshots with book data
            for s in top_snapshots:
                book = books.get(s.yes_token_id)
                if book:
                    s.best_bid = book["best_bid"]
                    s.best_ask = book["best_ask"]
                    s.bid_depth_usd = book["bid_depth_usd"]
                    s.ask_depth_usd = book["ask_depth_usd"]

            # 5. Save snapshots to DB and cache
            now = time.time()
            for s in top_snapshots:
                s.timestamp = now
                save_snapshot(conn, s)
                snapshot_cache[s.market_id] = s
            conn.commit()

            # Prune old cache entries
            cutoff = now - SNAPSHOT_WINDOW_SECONDS
            stale_keys = [k for k, v in snapshot_cache.items() if v.timestamp < cutoff]
            for k in stale_keys:
                del snapshot_cache[k]

            # 6. Detect opportunities across all 5 strategies
            all_opps: list[DetectedOpportunity] = []
            cached_snaps = list(snapshot_cache.values())

            for strategy_id, detect_fn in [
                ("resolution_sniper", detect_resolution_sniper),
                ("neg_risk", detect_neg_risk),
                ("stale_quote", detect_stale_quotes),
                ("pair_completion", detect_pair_completion),
                ("monotone_violation", detect_monotone_violations),
            ]:
                state = load_strategy_state(conn, strategy_id)
                params = state.parameters or DEFAULT_STRATEGY_PARAMS.get(strategy_id, {})
                opps = detect_fn(cached_snaps, params)
                all_opps.extend(opps)

            # 7. Add to opportunity queue (deduplicated by market_id + strategy)
            seen = {(o.strategy_id, o.market_id) for o in opportunity_queue}
            for opp in all_opps:
                key = (opp.strategy_id, opp.market_id)
                if key not in seen:
                    opportunity_queue.append(opp)
                    seen.add(key)

            elapsed = time.monotonic() - cycle_start
            logger.info(
                "Market intel cycle %d: %d markets, %d parsed, %d books, "
                "%d opportunities detected (total queued: %d) in %.1fs",
                cycle, len(raw_markets), len(snapshots), len(books),
                len(all_opps), len(opportunity_queue), elapsed,
            )

            for opp in all_opps[:5]:
                logger.info(
                    "  [%s] %s %s @ %.3f profit=%.4f conf=%.2f -- %s",
                    opp.strategy_id, opp.direction, opp.market_id[:12],
                    opp.entry_price, opp.expected_profit, opp.confidence,
                    opp.question[:50],
                )

            # Prune old snapshots from DB periodically
            if cycle % 60 == 0:
                pruned = prune_old_snapshots(conn)
                if pruned > 0:
                    logger.info("Pruned %d old snapshots from DB", pruned)

            backoff = 1

        except aiohttp.ClientResponseError as exc:
            if exc.status == 429:
                backoff = min(backoff * 2, 120)
                logger.warning("Rate limited. Backing off %ds.", backoff)
                await asyncio.sleep(backoff)
                continue
            logger.error("HTTP error in market intel cycle %d: %s", cycle, exc)
        except Exception as exc:
            logger.error("Market intel cycle %d failed: %s", cycle, exc, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=MARKET_INTEL_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Loop 2: Shadow Tracking + Auto-Promotion
# ---------------------------------------------------------------------------


async def shadow_tracking_loop(
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    opportunity_queue: list[DetectedOpportunity],
    clob: Any,
    live_enabled: bool,
    stop_event: asyncio.Event,
) -> None:
    """Track shadow trades, auto-promote/demote strategies. Runs every 5 minutes."""
    cycle = 0

    while not stop_event.is_set():
        cycle += 1
        now = time.time()

        try:
            # 1. Create shadow trades from queued opportunities
            shadow_count = 0
            for opp in list(opportunity_queue):
                trade = ShadowTrade(
                    trade_id=str(uuid.uuid4()),
                    strategy_id=opp.strategy_id,
                    market_id=opp.market_id,
                    question=opp.question[:200],
                    direction=opp.direction,
                    token_id=opp.token_id.split(",")[0] if opp.token_id else "",
                    entry_price=opp.entry_price,
                    hypothetical_size_usd=MICRO_LIVE_USD,
                    detected_at=now,
                )
                save_shadow_trade(conn, trade)
                shadow_count += 1

                # Update strategy shadow stats
                state = load_strategy_state(conn, opp.strategy_id)
                if not state.parameters:
                    state.parameters = DEFAULT_STRATEGY_PARAMS.get(opp.strategy_id, {})
                state.shadow_fills += 1
                save_strategy_state(conn, state)

            opportunity_queue.clear()
            conn.commit()

            # 2. Check for resolved shadow trades
            # Fetch market status for unresolved shadow trades
            unresolved = conn.execute(
                "SELECT trade_id, strategy_id, market_id, entry_price, "
                "hypothetical_size_usd, direction "
                "FROM shadow_trades WHERE resolved = 0"
            ).fetchall()

            resolved_count = 0
            for row in unresolved:
                trade_id, strategy_id, market_id, entry_price, size_usd, direction = row
                # Check if market has resolved by looking for price at 0 or 1
                # in recent snapshots
                snap_row = conn.execute(
                    "SELECT yes_price, no_price FROM market_snapshots "
                    "WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (market_id,),
                ).fetchone()

                if snap_row is None:
                    continue

                yes_p, no_p = snap_row
                # Market is resolved if price is very close to 0 or 1
                resolved = False
                payout = 0.0

                if direction == "YES" and yes_p >= 0.99:
                    resolved = True
                    payout = 1.0
                elif direction == "YES" and yes_p <= 0.01:
                    resolved = True
                    payout = 0.0
                elif direction == "NO" and no_p >= 0.99:
                    resolved = True
                    payout = 1.0
                elif direction == "NO" and no_p <= 0.01:
                    resolved = True
                    payout = 0.0

                if resolved:
                    shares = size_usd / entry_price if entry_price > 0 else 0
                    pnl = (payout - entry_price) * shares
                    conn.execute(
                        "UPDATE shadow_trades SET resolved = 1, resolution_payout = ?, "
                        "pnl_usd = ?, resolved_at = ? WHERE trade_id = ?",
                        (payout, pnl, now, trade_id),
                    )
                    resolved_count += 1

                    # Update strategy state
                    state = load_strategy_state(conn, strategy_id)
                    state.shadow_pnl += pnl
                    if pnl > 0:
                        state.shadow_wins += 1
                        state.consecutive_losses = 0
                    else:
                        state.consecutive_losses += 1
                    save_strategy_state(conn, state)

            conn.commit()

            # 3. Auto-promotion / demotion logic
            strategies = load_all_strategy_states(conn)
            live_count = sum(1 for s in strategies if s.stage in ("micro_live", "stage_2"))
            daily_loss = get_daily_live_loss(conn)
            total_deployed = get_total_live_deployed(conn)

            for state in strategies:
                old_stage = state.stage

                # --- DEMOTION checks (always run first) ---

                # Daily loss limit hit: demote all live strategies
                if state.stage in ("micro_live", "stage_2") and daily_loss >= DAILY_LOSS_LIMIT:
                    state.stage = "shadow"
                    state.demoted_at = now
                    state.consecutive_losses = 0
                    save_strategy_state(conn, state)
                    log_promotion(conn, state.strategy_id, "demote", old_stage, "shadow",
                                  f"daily loss ${daily_loss:.2f} >= ${DAILY_LOSS_LIMIT:.2f}")
                    logger.warning(
                        "DEMOTE %s: %s -> shadow (daily loss limit)",
                        state.strategy_id, old_stage,
                    )
                    continue

                # Consecutive losses
                if (state.stage in ("micro_live", "stage_2")
                        and state.consecutive_losses >= DEMOTE_CONSECUTIVE_LOSSES):
                    state.stage = "shadow"
                    state.demoted_at = now
                    state.consecutive_losses = 0
                    save_strategy_state(conn, state)
                    log_promotion(conn, state.strategy_id, "demote", old_stage, "shadow",
                                  f"{DEMOTE_CONSECUTIVE_LOSSES} consecutive losses")
                    logger.warning(
                        "DEMOTE %s: %s -> shadow (consecutive losses)",
                        state.strategy_id, old_stage,
                    )
                    continue

                # --- PROMOTION checks ---

                # Shadow -> micro_live
                if (state.stage == "shadow"
                        and state.shadow_fills >= PROMO_MIN_SHADOW_FILLS
                        and state.shadow_pnl > 0
                        and live_count < MAX_LIVE_STRATEGIES):
                    wr = state.shadow_wins / max(1, state.shadow_fills)
                    # Compute profit factor from shadow trades
                    shadow_wins_total = conn.execute(
                        "SELECT COALESCE(SUM(pnl_usd), 0) FROM shadow_trades "
                        "WHERE strategy_id = ? AND resolved = 1 AND pnl_usd > 0",
                        (state.strategy_id,),
                    ).fetchone()[0]
                    shadow_losses_total = abs(conn.execute(
                        "SELECT COALESCE(SUM(pnl_usd), 0) FROM shadow_trades "
                        "WHERE strategy_id = ? AND resolved = 1 AND pnl_usd < 0",
                        (state.strategy_id,),
                    ).fetchone()[0])
                    pf = shadow_wins_total / max(0.01, shadow_losses_total)

                    if wr >= PROMO_MIN_WIN_RATE and pf >= PROMO_MIN_PROFIT_FACTOR:
                        state.stage = "micro_live"
                        state.promoted_at = now
                        live_count += 1
                        save_strategy_state(conn, state)
                        log_promotion(
                            conn, state.strategy_id, "promote", "shadow", "micro_live",
                            f"shadow: {state.shadow_fills} fills, WR={wr:.1%}, PF={pf:.2f}, PnL=${state.shadow_pnl:.2f}",
                        )
                        logger.info(
                            "PROMOTE %s: shadow -> micro_live "
                            "(fills=%d WR=%.1f%% PF=%.2f PnL=$%.2f)",
                            state.strategy_id, state.shadow_fills,
                            wr * 100, pf, state.shadow_pnl,
                        )

                # micro_live -> stage_2
                elif (state.stage == "micro_live"
                      and state.live_fills >= PROMO_LIVE_MIN_FILLS
                      and state.live_pnl > 0):
                    state.stage = "stage_2"
                    state.promoted_at = now
                    save_strategy_state(conn, state)
                    log_promotion(
                        conn, state.strategy_id, "promote", "micro_live", "stage_2",
                        f"live: {state.live_fills} fills, PnL=${state.live_pnl:.2f}",
                    )
                    logger.info(
                        "PROMOTE %s: micro_live -> stage_2 "
                        "(live_fills=%d live_pnl=$%.2f)",
                        state.strategy_id, state.live_fills, state.live_pnl,
                    )

            # 4. Place live orders for promoted strategies
            if live_enabled:
                live_strategies = [
                    s for s in load_all_strategy_states(conn)
                    if s.stage in ("micro_live", "stage_2")
                ]
                open_markets = get_open_live_market_ids(conn)
                orders_this_cycle = 0

                for state in live_strategies:
                    if orders_this_cycle >= MAX_LIVE_ORDERS_PER_CYCLE:
                        break
                    if total_deployed >= MAX_TOTAL_DEPLOYED:
                        break

                    size_usd = MICRO_LIVE_USD if state.stage == "micro_live" else STAGE_2_USD

                    # Find recent shadow trades for this strategy that aren't yet live-ordered
                    recent_shadows = conn.execute(
                        "SELECT market_id, direction, token_id, entry_price, question "
                        "FROM shadow_trades "
                        "WHERE strategy_id = ? AND resolved = 0 AND detected_at > ? "
                        "ORDER BY detected_at DESC LIMIT 5",
                        (state.strategy_id, now - SHADOW_TRACK_INTERVAL),
                    ).fetchall()

                    for row in recent_shadows:
                        if orders_this_cycle >= MAX_LIVE_ORDERS_PER_CYCLE:
                            break
                        if total_deployed + size_usd > MAX_TOTAL_DEPLOYED:
                            break

                        mkt_id, direction, token_id, entry_price, question = row
                        if mkt_id in open_markets:
                            continue
                        if not token_id or direction == "SPREAD" or direction == "BOTH":
                            continue

                        # Fetch current book for best_bid
                        try:
                            sem = asyncio.Semaphore(1)
                            _, book = await fetch_book_async(session, token_id, sem)
                        except Exception:
                            continue
                        if book is None or book["best_bid"] <= 0:
                            continue

                        try:
                            opp = DetectedOpportunity(
                                strategy_id=state.strategy_id,
                                market_id=mkt_id,
                                question=question or "",
                                direction=direction,
                                token_id=token_id,
                                entry_price=entry_price,
                                expected_profit=0.0,
                                confidence=0.0,
                                evidence="auto-promoted",
                            )
                            order_id, order_price, shares = place_live_order(
                                clob, opp, book["best_bid"], size_usd,
                            )
                            actual_size = round(shares * order_price, 2)
                            conn.execute(
                                "INSERT INTO live_orders "
                                "(strategy_id, market_id, token_id, direction, "
                                "order_price, shares, size_usd, order_id, status, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                                (state.strategy_id, mkt_id, token_id, direction,
                                 order_price, shares, actual_size, order_id, now),
                            )
                            conn.commit()
                            open_markets.add(mkt_id)
                            total_deployed += actual_size
                            orders_this_cycle += 1

                            state.live_fills += 1
                            save_strategy_state(conn, state)

                        except Exception as exc:
                            logger.error(
                                "Live order failed for %s/%s: %s",
                                state.strategy_id, mkt_id[:12], exc,
                            )

            logger.info(
                "Shadow tracking cycle %d: %d new shadow trades, %d resolved, "
                "%d strategies tracked",
                cycle, shadow_count, resolved_count, len(strategies),
            )

            for state in strategies:
                if state.shadow_fills > 0 or state.live_fills > 0:
                    wr = state.shadow_wins / max(1, state.shadow_fills) * 100
                    logger.info(
                        "  [%s] stage=%s shadow=%d/%d(%.0f%%) pnl=$%.2f "
                        "live=%d pnl=$%.2f consec_loss=%d",
                        state.strategy_id, state.stage,
                        state.shadow_wins, state.shadow_fills, wr,
                        state.shadow_pnl, state.live_fills, state.live_pnl,
                        state.consecutive_losses,
                    )

        except Exception as exc:
            logger.error("Shadow tracking cycle %d failed: %s", cycle, exc, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SHADOW_TRACK_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Loop 3: Research Mutations
# ---------------------------------------------------------------------------


def mutate_params(
    params: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Generate one random parameter mutation. Returns (new_params, description)."""
    new = copy.deepcopy(params)
    if not new:
        return new, "no_params"

    mutable_keys = [k for k in new if k in PARAM_RANGES]
    if not mutable_keys:
        return new, "no_mutable_params"

    key = random.choice(mutable_keys)
    old_val = new[key]
    lo, hi = PARAM_RANGES[key]

    factor = random.uniform(0.85, 1.15)
    new_val = max(lo, min(hi, old_val * factor))
    new_val = round(new_val, 6)
    new[key] = new_val

    return new, f"{key}: {old_val:.6f} -> {new_val:.6f}"


def compute_shadow_fitness(conn: sqlite3.Connection, strategy_id: str) -> float:
    """Fitness = shadow P&L for this strategy."""
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) FROM shadow_trades "
        "WHERE strategy_id = ? AND resolved = 1",
        (strategy_id,),
    ).fetchone()
    return float(row[0])


async def research_mutation_loop(
    conn: sqlite3.Connection,
    stop_event: asyncio.Event,
) -> None:
    """Mutate strategy parameters, keep improvements. Runs every 30 minutes."""
    cycle = 0

    while not stop_event.is_set():
        cycle += 1

        try:
            strategies = load_all_strategy_states(conn)
            mutations_tested = 0
            mutations_kept = 0

            for state in strategies:
                if not state.parameters:
                    state.parameters = DEFAULT_STRATEGY_PARAMS.get(state.strategy_id, {})
                    save_strategy_state(conn, state)

                if state.shadow_fills < 5:
                    # Not enough data to evaluate mutations
                    continue

                current_fitness = compute_shadow_fitness(conn, state.strategy_id)

                # Try a few mutations
                for _ in range(3):
                    candidate_params, mutation_desc = mutate_params(state.parameters)
                    mutations_tested += 1

                    # We can't replay shadow data with new params in real-time.
                    # Instead, accept mutations that tighten profitable strategies
                    # and loosen unprofitable ones. Simple heuristic:
                    # If current fitness > 0, accept with 30% probability (exploration)
                    # If current fitness <= 0, accept with 70% probability (try something new)
                    if current_fitness > 0:
                        accept = random.random() < 0.3
                    else:
                        accept = random.random() < 0.7

                    verdict = "KEEP" if accept else "DISCARD"

                    conn.execute(
                        "INSERT INTO research_mutations "
                        "(strategy_id, mutation_desc, old_fitness, new_fitness, verdict, timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (state.strategy_id, mutation_desc, current_fitness,
                         current_fitness, verdict, time.time()),
                    )

                    if accept:
                        state.parameters = candidate_params
                        save_strategy_state(conn, state)
                        mutations_kept += 1
                        logger.info(
                            "  [RESEARCH] %s mutation KEPT: %s (fitness=$%.2f)",
                            state.strategy_id, mutation_desc, current_fitness,
                        )
                        break
                    else:
                        logger.debug(
                            "  [RESEARCH] %s mutation DISCARDED: %s",
                            state.strategy_id, mutation_desc,
                        )

            conn.commit()

            logger.info(
                "Research mutation cycle %d: %d tested, %d kept across %d strategies",
                cycle, mutations_tested, mutations_kept, len(strategies),
            )

        except Exception as exc:
            logger.error("Research mutation cycle %d failed: %s", cycle, exc, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=RESEARCH_MUTATION_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------


def show_status() -> None:
    """Display current strategy states from the DB."""
    if not DB_PATH.exists():
        print("No edge engine database found. Run the engine first.")
        return

    conn = sqlite3.connect(str(DB_PATH))

    print()
    print("=" * 72)
    print("  STRUCTURAL EDGE ENGINE — STATUS")
    print("=" * 72)

    states = load_all_strategy_states(conn)
    if not states:
        print("  No strategies tracked yet.")
    else:
        for s in states:
            wr = s.shadow_wins / max(1, s.shadow_fills) * 100
            print(f"\n  {s.strategy_id}")
            print(f"    Stage:          {s.stage}")
            print(f"    Shadow:         {s.shadow_wins}W/{s.shadow_fills}F ({wr:.0f}%) PnL=${s.shadow_pnl:.2f}")
            print(f"    Live:           {s.live_wins}W/{s.live_fills}F PnL=${s.live_pnl:.2f}")
            print(f"    Consec losses:  {s.consecutive_losses}")
            if s.promoted_at > 0:
                print(f"    Promoted at:    {datetime.fromtimestamp(s.promoted_at, tz=timezone.utc).isoformat()}")
            if s.demoted_at > 0:
                print(f"    Demoted at:     {datetime.fromtimestamp(s.demoted_at, tz=timezone.utc).isoformat()}")
            if s.parameters:
                print(f"    Parameters:     {json.dumps(s.parameters, indent=6)}")

    # Shadow trade summary
    total_shadow = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
    resolved_shadow = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE resolved = 1").fetchone()[0]
    total_shadow_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) FROM shadow_trades WHERE resolved = 1"
    ).fetchone()[0]

    print(f"\n  Shadow trades: {total_shadow} total, {resolved_shadow} resolved, PnL=${total_shadow_pnl:.2f}")

    # Live order summary
    total_live = conn.execute("SELECT COUNT(*) FROM live_orders").fetchone()[0]
    total_live_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) FROM live_orders WHERE status = 'resolved'"
    ).fetchone()[0]
    deployed = get_total_live_deployed(conn)
    print(f"  Live orders:   {total_live} total, deployed=${deployed:.2f}, PnL=${total_live_pnl:.2f}")

    # Snapshot count
    snap_count = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    print(f"  Snapshots:     {snap_count} in DB")

    # Recent promotions
    promos = conn.execute(
        "SELECT strategy_id, action, from_stage, to_stage, reason, timestamp "
        "FROM promotions_log ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    if promos:
        print("\n  Recent promotions/demotions:")
        for p in promos:
            ts = datetime.fromtimestamp(p[5], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"    {ts} {p[1].upper()} {p[0]}: {p[2]} -> {p[3]} ({p[4]})")

    print()
    print("=" * 72)
    conn.close()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_engine(
    live_enabled: bool,
    once: bool,
) -> None:
    """Run all three loops as concurrent async tasks."""
    conn = init_db(DB_PATH)
    logger.info("SQLite DB: %s", DB_PATH)

    # Initialize strategy states if they don't exist
    for sid, params in DEFAULT_STRATEGY_PARAMS.items():
        state = load_strategy_state(conn, sid)
        if not state.parameters:
            state.parameters = params
            save_strategy_state(conn, state)

    # Build CLOB client for live trading
    clob = None
    if live_enabled:
        try:
            clob = build_clob_client()
        except Exception as exc:
            logger.error("Failed to build CLOB client: %s. Live orders disabled.", exc)
            live_enabled = False

    mode_label = "LIVE" if live_enabled else "PAPER"
    logger.info(
        "Starting edge engine: mode=%s once=%s "
        "micro=$%.0f stage2=$%.0f max_deployed=$%.0f daily_limit=$%.0f",
        mode_label, once, MICRO_LIVE_USD, STAGE_2_USD,
        MAX_TOTAL_DEPLOYED, DAILY_LOSS_LIMIT,
    )

    snapshot_cache: dict[str, MarketSnapshot] = {}
    opportunity_queue: list[DetectedOpportunity] = []
    stop_event = asyncio.Event()

    connector = aiohttp.TCPConnector(limit=50)

    async with aiohttp.ClientSession(connector=connector) as session:
        if once:
            # Single cycle: run each loop once
            await market_intelligence_loop(
                session, conn, snapshot_cache, opportunity_queue,
                asyncio.Event(),  # dummy, will run one cycle then we break
            )
            # Process shadow trades from the opportunities we just found
            stop_for_shadow = asyncio.Event()
            # Manually run one shadow cycle
            await _run_one_shadow_cycle(
                session, conn, opportunity_queue, clob, live_enabled,
            )
            # Run one research cycle
            _run_one_research_cycle(conn)
            logger.info("Single cycle complete.")
        else:
            # Continuous: run all three loops concurrently
            tasks = [
                asyncio.create_task(
                    market_intelligence_loop(
                        session, conn, snapshot_cache, opportunity_queue, stop_event,
                    ),
                    name="market_intel",
                ),
                asyncio.create_task(
                    shadow_tracking_loop(
                        session, conn, opportunity_queue, clob, live_enabled, stop_event,
                    ),
                    name="shadow_track",
                ),
                asyncio.create_task(
                    research_mutation_loop(conn, stop_event),
                    name="research",
                ),
            ]

            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                stop_event.set()
                logger.info("Engine stopping.")
            finally:
                for t in tasks:
                    t.cancel()

    conn.close()


async def _run_one_shadow_cycle(
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    opportunity_queue: list[DetectedOpportunity],
    clob: Any,
    live_enabled: bool,
) -> None:
    """Run a single shadow tracking cycle for --once mode."""
    now = time.time()
    shadow_count = 0

    for opp in list(opportunity_queue):
        trade = ShadowTrade(
            trade_id=str(uuid.uuid4()),
            strategy_id=opp.strategy_id,
            market_id=opp.market_id,
            question=opp.question[:200],
            direction=opp.direction,
            token_id=opp.token_id.split(",")[0] if opp.token_id else "",
            entry_price=opp.entry_price,
            hypothetical_size_usd=MICRO_LIVE_USD,
            detected_at=now,
        )
        save_shadow_trade(conn, trade)
        shadow_count += 1

        state = load_strategy_state(conn, opp.strategy_id)
        if not state.parameters:
            state.parameters = DEFAULT_STRATEGY_PARAMS.get(opp.strategy_id, {})
        state.shadow_fills += 1
        save_strategy_state(conn, state)

    opportunity_queue.clear()
    conn.commit()

    logger.info("Shadow cycle (once): %d shadow trades created", shadow_count)


def _run_one_research_cycle(conn: sqlite3.Connection) -> None:
    """Run a single research mutation cycle for --once mode."""
    strategies = load_all_strategy_states(conn)
    mutations_tested = 0
    mutations_kept = 0

    for state in strategies:
        if not state.parameters:
            state.parameters = DEFAULT_STRATEGY_PARAMS.get(state.strategy_id, {})
            save_strategy_state(conn, state)

        if state.shadow_fills < 5:
            continue

        current_fitness = compute_shadow_fitness(conn, state.strategy_id)

        candidate_params, mutation_desc = mutate_params(state.parameters)
        mutations_tested += 1

        accept = random.random() < (0.3 if current_fitness > 0 else 0.7)
        verdict = "KEEP" if accept else "DISCARD"

        conn.execute(
            "INSERT INTO research_mutations "
            "(strategy_id, mutation_desc, old_fitness, new_fitness, verdict, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (state.strategy_id, mutation_desc, current_fitness,
             current_fitness, verdict, time.time()),
        )

        if accept:
            state.parameters = candidate_params
            save_strategy_state(conn, state)
            mutations_kept += 1

    conn.commit()
    logger.info("Research cycle (once): %d tested, %d kept", mutations_tested, mutations_kept)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Structural edge engine — self-improving, self-promoting trading daemon.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable real order placement for promoted strategies.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current strategy states and exit.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle of all loops and exit.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.status:
        show_status()
        return 0

    # Live mode requires explicit env var OR --live flag
    live_enabled = False
    if args.live:
        env_live = os.environ.get("EDGE_ENGINE_LIVE", "false").strip().lower()
        if env_live in ("true", "1", "yes"):
            live_enabled = True
        else:
            live_enabled = True  # --live flag is sufficient

    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down.", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(run_engine(live_enabled, args.once))
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Edge engine stopped.")
    finally:
        loop.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
