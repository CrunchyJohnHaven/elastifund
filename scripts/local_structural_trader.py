#!/usr/bin/env python3
"""Local structural trader for Polymarket.

Runs on John's Mac. Scans ALL active Polymarket markets for resolution-sniper
opportunities (YES or NO priced >= 0.95) and places POST-ONLY maker BUY orders
directly via the CLOB client.

Usage:
    python3 scripts/local_structural_trader.py              # continuous, paper mode
    python3 scripts/local_structural_trader.py --live        # continuous, real orders
    python3 scripts/local_structural_trader.py --once        # single cycle, paper
    python3 scripts/local_structural_trader.py --interval 60 # configurable interval

Author: JJ (autonomous)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any

import aiohttp

# ---------------------------------------------------------------------------
# Ensure project root is importable
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
DEFAULT_INTERVAL = 60
MAX_GAMMA_PAGES = 200
GAMMA_PAGE_SIZE = 100
REQUEST_TIMEOUT = 15

# Trading thresholds (tighter than scanner)
RESOLUTION_SNIPER_THRESHOLD = 0.94  # Lower to catch more opportunities
MIN_CONFIDENCE = 0.90
MIN_PROFIT_PER_SHARE = 0.03  # after 2% winner fee
WINNER_FEE = 0.02

# Safety rails
MAX_USD_PER_TRADE = 10.0
MAX_TRADES_PER_CYCLE = 5
MAX_TOTAL_DEPLOYED = 100.0
MIN_VOLUME_24H = 50.0  # Lower for structural — near-certain markets have thin volume
MIN_HOURS_TO_RESOLUTION = 6.0  # Tighter — still need time for resolution
DAILY_LOSS_LIMIT = 20.0

# DB path
DB_PATH = PROJECT_ROOT / "data" / "structural_trades.db"

logger = logging.getLogger("JJ.structural_trader")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ParsedMarket:
    market_id: str
    condition_id: str
    question: str
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    volume_24h: float
    liquidity: float
    end_date: str
    hours_to_resolution: float


@dataclass
class Opportunity:
    market_id: str
    question: str
    direction: str  # "YES" | "NO"
    token_id: str
    entry_price: float
    expected_profit_per_share: float
    confidence: float
    evidence: str


# ---------------------------------------------------------------------------
# Helpers (replicated from scanner to stay self-contained)
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


def parse_market(raw: dict[str, Any]) -> ParsedMarket | None:
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
    liquidity = _safe_float(raw.get("liquidity"), 0.0)

    return ParsedMarket(
        market_id=market_id,
        condition_id=condition_id,
        question=question,
        yes_price=yes_price,
        no_price=no_price,
        yes_token_id=yes_token,
        no_token_id=no_token,
        volume_24h=volume_24h,
        liquidity=liquidity,
        end_date=end_date_str,
        hours_to_resolution=hours,
    )


# ---------------------------------------------------------------------------
# Market fetching
# ---------------------------------------------------------------------------


async def fetch_all_markets(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
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
                GAMMA_URL, params=params, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
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


async def fetch_book(
    session: aiohttp.ClientSession,
    token_id: str,
) -> dict[str, Any] | None:
    """Fetch order book for a single token."""
    if not token_id:
        return None
    try:
        async with session.get(
            CLOB_BOOK_URL,
            params={"token_id": token_id},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception as exc:
        logger.debug("Book fetch failed for %s: %s", token_id[:16], exc)
        return None


# ---------------------------------------------------------------------------
# Resolution sniper detection
# ---------------------------------------------------------------------------


def scan_resolution_sniper(markets: list[ParsedMarket]) -> list[Opportunity]:
    """Find markets where YES or NO is priced >= 0.95."""
    opportunities: list[Opportunity] = []

    for m in markets:
        if m.volume_24h < MIN_VOLUME_24H:
            continue
        if m.hours_to_resolution < MIN_HOURS_TO_RESOLUTION:
            continue
        # Skip fully resolved markets (price exactly at 1.0 or 0.0)
        if m.yes_price >= 0.999 or m.no_price >= 0.999:
            continue

        # Check YES side
        if m.yes_price >= RESOLUTION_SNIPER_THRESHOLD and m.yes_token_id:
            gross_profit = 1.0 - m.yes_price
            net_profit = gross_profit - WINNER_FEE
            if net_profit < MIN_PROFIT_PER_SHARE:
                continue
            confidence = min(0.99, 0.85 + (m.yes_price - 0.94) * 2.5)
            if confidence < MIN_CONFIDENCE:
                continue
            opportunities.append(Opportunity(
                market_id=m.market_id,
                question=m.question,
                direction="YES",
                token_id=m.yes_token_id,
                entry_price=m.yes_price,
                expected_profit_per_share=round(net_profit, 4),
                confidence=round(confidence, 3),
                evidence=(
                    f"YES @ {m.yes_price:.3f}, net profit {net_profit:.4f}/share, "
                    f"vol24h=${m.volume_24h:.0f}, resolves in {m.hours_to_resolution:.0f}h"
                ),
            ))

        # Check NO side
        if m.no_price >= RESOLUTION_SNIPER_THRESHOLD and m.no_token_id:
            gross_profit = 1.0 - m.no_price
            net_profit = gross_profit - WINNER_FEE
            if net_profit < MIN_PROFIT_PER_SHARE:
                continue
            confidence = min(0.99, 0.85 + (m.no_price - 0.94) * 2.5)
            if confidence < MIN_CONFIDENCE:
                continue
            opportunities.append(Opportunity(
                market_id=m.market_id,
                question=m.question,
                direction="NO",
                token_id=m.no_token_id,
                entry_price=m.no_price,
                expected_profit_per_share=round(net_profit, 4),
                confidence=round(confidence, 3),
                evidence=(
                    f"NO @ {m.no_price:.3f}, net profit {net_profit:.4f}/share, "
                    f"vol24h=${m.volume_24h:.0f}, resolves in {m.hours_to_resolution:.0f}h"
                ),
            ))

    # Sort by profit descending
    opportunities.sort(key=lambda o: o.expected_profit_per_share, reverse=True)
    return opportunities


# ---------------------------------------------------------------------------
# SQLite position tracker
# ---------------------------------------------------------------------------


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS structural_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            question TEXT,
            direction TEXT,
            token_id TEXT,
            order_price REAL,
            shares REAL,
            size_usd REAL,
            order_id TEXT,
            status TEXT DEFAULT 'pending',
            pnl_usd REAL,
            created_at TEXT,
            resolved_at TEXT
        )
    """)
    conn.commit()
    return conn


def get_total_deployed(conn: sqlite3.Connection) -> float:
    """Sum of size_usd for all non-resolved positions."""
    row = conn.execute(
        "SELECT COALESCE(SUM(size_usd), 0) FROM structural_trades "
        "WHERE status IN ('pending', 'filled')"
    ).fetchone()
    return float(row[0])


def get_daily_realized_loss(conn: sqlite3.Connection) -> float:
    """Sum of negative pnl_usd for today (UTC)."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) FROM structural_trades "
        "WHERE status = 'resolved' AND pnl_usd < 0 AND resolved_at LIKE ?",
        (f"{today}%",),
    ).fetchone()
    return abs(float(row[0]))


def get_open_market_ids(conn: sqlite3.Connection) -> set[str]:
    """Market IDs with open positions."""
    rows = conn.execute(
        "SELECT DISTINCT market_id FROM structural_trades "
        "WHERE status IN ('pending', 'filled')"
    ).fetchall()
    return {r[0] for r in rows}


def record_trade(
    conn: sqlite3.Connection,
    opp: Opportunity,
    order_price: float,
    shares: float,
    size_usd: float,
    order_id: str,
    status: str = "pending",
) -> int:
    cur = conn.execute(
        "INSERT INTO structural_trades "
        "(market_id, question, direction, token_id, order_price, shares, size_usd, "
        "order_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            opp.market_id,
            opp.question[:200],
            opp.direction,
            opp.token_id,
            order_price,
            shares,
            size_usd,
            order_id,
            status,
            datetime.now(tz=timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# CLOB client setup
# ---------------------------------------------------------------------------


def build_clob_client():
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
        log_prefix="[structural]",
    )
    logger.info(
        "CLOB client ready: signature_type=%d, probes=%s",
        selected_sig_type,
        json.dumps(probes, default=str),
    )
    return client


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------


def place_maker_order(
    clob: Any,
    opp: Opportunity,
    best_bid: float,
    *,
    paper: bool = True,
) -> tuple[str, float, float]:
    """Place a POST-ONLY maker BUY order. Returns (order_id, price, shares).

    Order price = best_bid + 0.01 (one tick), capped at entry_price.
    Size = $10 / price, rounded to 2 decimals.
    """
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    # Price: best_bid + 1 tick, but never cross the entry_price (our max)
    order_price = round(best_bid + 0.01, 2)
    if order_price > opp.entry_price:
        order_price = round(opp.entry_price, 2)
    # Sanity: price must be between 0.01 and 0.99
    order_price = max(0.01, min(0.99, order_price))

    shares = round(MAX_USD_PER_TRADE / order_price, 2)
    if shares < 1.0:
        shares = 1.0
    size_usd = round(shares * order_price, 2)

    if paper:
        logger.info(
            "  [PAPER] Would BUY %s %.2f shares @ %.2f ($%.2f) -- %s",
            opp.direction, shares, order_price, size_usd,
            opp.question[:60],
        )
        return "paper", order_price, shares

    # Live order
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
                opp.direction, shares, order_price, size_usd,
                order_id[:16], opp.question[:60],
            )
        else:
            logger.warning("  [LIVE] Order rejected: %s", result)
    else:
        logger.warning("  [LIVE] Unexpected result type: %s", type(result))

    return order_id, order_price, shares


# ---------------------------------------------------------------------------
# Main scan + trade cycle
# ---------------------------------------------------------------------------


async def run_cycle(
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    clob: Any,
    *,
    paper: bool = True,
) -> dict[str, Any]:
    """Execute one scan + trade cycle. Returns stats dict."""
    cycle_start = time.monotonic()

    # 1. Check daily loss limit
    daily_loss = get_daily_realized_loss(conn)
    if daily_loss >= DAILY_LOSS_LIMIT:
        logger.warning(
            "Daily loss limit reached ($%.2f >= $%.2f). Skipping cycle.",
            daily_loss, DAILY_LOSS_LIMIT,
        )
        return {"skipped": True, "reason": "daily_loss_limit", "daily_loss": daily_loss}

    # 2. Check total deployed
    total_deployed = get_total_deployed(conn)
    if total_deployed >= MAX_TOTAL_DEPLOYED:
        logger.warning(
            "Max deployment reached ($%.2f >= $%.2f). Skipping cycle.",
            total_deployed, MAX_TOTAL_DEPLOYED,
        )
        return {"skipped": True, "reason": "max_deployed", "total_deployed": total_deployed}

    remaining_budget = MAX_TOTAL_DEPLOYED - total_deployed

    # 3. Fetch all markets
    raw_markets = await fetch_all_markets(session)
    parsed: list[ParsedMarket] = []
    for raw in raw_markets:
        m = parse_market(raw)
        if m is not None:
            parsed.append(m)

    # 4. Run resolution sniper
    opportunities = scan_resolution_sniper(parsed)

    # 5. Filter out markets we already have positions in
    open_markets = get_open_market_ids(conn)
    opportunities = [o for o in opportunities if o.market_id not in open_markets]

    logger.info(
        "Cycle: %d markets scanned, %d parsed, %d opportunities (after dedup)",
        len(raw_markets), len(parsed), len(opportunities),
    )

    # 6. Place orders on top opportunities
    trades_placed = 0
    cycle_deployed = 0.0

    for opp in opportunities:
        if trades_placed >= MAX_TRADES_PER_CYCLE:
            logger.info("  Hit max trades per cycle (%d)", MAX_TRADES_PER_CYCLE)
            break
        if cycle_deployed + MAX_USD_PER_TRADE > remaining_budget:
            logger.info("  Budget exhausted for this cycle ($%.2f remaining)", remaining_budget - cycle_deployed)
            break

        # Fetch order book to find best bid
        book_data = await fetch_book(session, opp.token_id)
        if book_data is None:
            logger.debug("  Skipping %s -- no book data", opp.market_id[:16])
            continue

        raw_bids = book_data.get("bids") or []
        best_bid = 0.0
        for level in raw_bids:
            if isinstance(level, dict):
                p = _safe_float(level.get("price"))
                if p > best_bid:
                    best_bid = p

        if best_bid <= 0.0:
            logger.debug("  Skipping %s -- no bids in book", opp.market_id[:16])
            continue

        # Place the order
        try:
            order_id, order_price, shares = place_maker_order(
                clob, opp, best_bid, paper=paper,
            )
        except Exception as exc:
            logger.error("  Order failed for %s: %s", opp.market_id[:16], exc)
            continue

        size_usd = round(shares * order_price, 2)
        status = "paper" if paper else "pending"
        record_trade(conn, opp, order_price, shares, size_usd, order_id, status)

        trades_placed += 1
        cycle_deployed += size_usd

    cycle_duration = time.monotonic() - cycle_start
    total_deployed_after = get_total_deployed(conn)

    stats = {
        "markets_fetched": len(raw_markets),
        "markets_parsed": len(parsed),
        "opportunities": len(opportunities),
        "trades_placed": trades_placed,
        "cycle_deployed_usd": round(cycle_deployed, 2),
        "total_deployed_usd": round(total_deployed_after, 2),
        "daily_loss_usd": round(daily_loss, 2),
        "cycle_seconds": round(cycle_duration, 2),
        "paper": paper,
    }

    logger.info(
        "Cycle complete: %d trades placed ($%.2f deployed), "
        "total deployed $%.2f/$%.2f, daily loss $%.2f/$%.2f, "
        "%.1fs elapsed",
        trades_placed, cycle_deployed,
        total_deployed_after, MAX_TOTAL_DEPLOYED,
        daily_loss, DAILY_LOSS_LIMIT,
        cycle_duration,
    )

    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main_loop(
    interval: int,
    once: bool,
    paper: bool,
) -> None:
    conn = init_db(DB_PATH)
    logger.info("SQLite DB: %s", DB_PATH)

    # Build CLOB client (even in paper mode, to validate credentials)
    clob = None
    if not paper:
        try:
            clob = build_clob_client()
        except Exception as exc:
            logger.error("Failed to build CLOB client: %s. Falling back to paper mode.", exc)
            paper = True

    mode_label = "PAPER" if paper else "LIVE"
    logger.info(
        "Starting structural trader: mode=%s interval=%ds once=%s "
        "max_per_trade=$%.0f max_deployed=$%.0f daily_loss_limit=$%.0f",
        mode_label, interval, once,
        MAX_USD_PER_TRADE, MAX_TOTAL_DEPLOYED, DAILY_LOSS_LIMIT,
    )

    connector = aiohttp.TCPConnector(limit=30)
    backoff = 1

    async with aiohttp.ClientSession(connector=connector) as session:
        cycle_num = 0
        while True:
            cycle_num += 1
            logger.info("--- Cycle %d [%s] ---", cycle_num, mode_label)
            try:
                await run_cycle(session, conn, clob, paper=paper)
                backoff = 1
            except aiohttp.ClientResponseError as exc:
                if exc.status == 429:
                    backoff = min(backoff * 2, 120)
                    logger.warning("Rate limited. Backing off %ds.", backoff)
                    await asyncio.sleep(backoff)
                    continue
                else:
                    logger.error("HTTP error in cycle %d: %s", cycle_num, exc)
            except Exception as exc:
                logger.error("Cycle %d failed: %s", cycle_num, exc, exc_info=True)

            if once:
                break

            await asyncio.sleep(interval)

    conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local structural trader for Polymarket. "
        "Scans for resolution-sniper opportunities and places maker orders."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable real order placement (default: paper trading).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between cycles (default: {DEFAULT_INTERVAL}).",
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

    # Paper mode unless --live AND env var STRUCTURAL_PAPER is not "true"
    paper = True
    if args.live:
        env_paper = os.environ.get("STRUCTURAL_PAPER", "false").strip().lower()
        if env_paper in ("true", "1", "yes"):
            logger.warning("--live flag set but STRUCTURAL_PAPER=true in env. Running in PAPER mode.")
        else:
            paper = False

    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down.", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(main_loop(args.interval, args.once, paper))
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Structural trader stopped.")
    finally:
        loop.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
