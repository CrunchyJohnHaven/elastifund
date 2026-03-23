#!/usr/bin/env python3
"""
RTDS Latency Surface Measurement Harness
=========================================
DISPATCH_110

Subscribes to two Polymarket WebSocket feeds simultaneously:
  1. RTDS channel "crypto_prices" — truth feed from Binance / Chainlink
  2. Market channel "best_bid_ask" — execution microstructure

Records every event with nanosecond-precision local timestamps (time.monotonic_ns).
Computes the price error surface: mid(market) - fair(RTDS).
Stores distributions of lag, stale-quote risk, and estimated maker EV in SQLite.

Kill conditions (checked after 48 h):
  H1 FAIL: median truth-to-market lag < 100 ms
  H2 FAIL: stale-quote rate (lag > 1000 ms) < 5 %
  H3 FAIL: estimated maker EV < 25 bps after fees

Author: JJ (autonomous)
Date:   2026-03-23
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import statistics
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import websockets
    from websockets.exceptions import WebSocketException, ConnectionClosed
except ImportError:  # pragma: no cover - optional dep guard for test isolation
    websockets = None  # type: ignore[assignment]
    WebSocketException = Exception  # type: ignore[assignment,misc]
    ConnectionClosed = Exception  # type: ignore[assignment]

logger = logging.getLogger("JJ.rtds_latency_harness")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

RTDS_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/rtds"
MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Reconnection parameters
_BACKOFF_BASE_S: float = 1.0
_BACKOFF_MAX_S: float = 60.0
_BACKOFF_FACTOR: float = 2.0

# Performance
_DB_FLUSH_INTERVAL: int = 100  # flush after this many events

# Kill-condition thresholds (checked after 48 h of data)
KILL_MEDIAN_LAG_MS: float = 100.0          # H1: must exceed this
KILL_STALE_QUOTE_RATE: float = 0.05        # H2: must exceed this
KILL_MAKER_EV_BPS: float = 25.0            # H3: must exceed this
KILL_EVALUATION_HOURS: float = 48.0        # when to first evaluate


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TruthTick:
    """One crypto price update from the RTDS feed."""

    symbol: str                # e.g. "BTC"
    source: str                # "binance" | "chainlink" | "unknown"
    price: float               # USD price as reported by RTDS
    rtds_timestamp: float      # timestamp embedded in RTDS payload (epoch s or ms, normalised to s)
    local_recv_ts: int         # time.monotonic_ns() at message receipt (nanoseconds)
    local_wall_ts: float       # time.time() at message receipt (epoch seconds)


@dataclass
class MarketTick:
    """One market data update from the CLOB market channel."""

    token_id: str              # Polymarket condition token ID
    channel: str               # "best_bid_ask" | "last_trade_price" | "book"
    best_bid: Optional[float]
    best_ask: Optional[float]
    last_trade_price: Optional[float]
    market_timestamp: Optional[float]  # timestamp from payload, normalised to epoch s
    local_recv_ts: int         # time.monotonic_ns() (nanoseconds)
    local_wall_ts: float       # time.time() (epoch seconds)


@dataclass
class PriceError:
    """Price error computed at one point in time."""

    token_id: str
    symbol: str
    fair_value: float          # derived from RTDS truth price
    venue_mid: float           # (best_bid + best_ask) / 2
    price_error: float         # venue_mid - fair_value  (signed)
    truth_age_ms: float        # age of the latest TruthTick at computation time (ms)
    market_age_ms: float       # age of the latest MarketTick at computation time (ms)
    computed_at: int           # time.monotonic_ns() (nanoseconds)


# ---------------------------------------------------------------------------
# SQLite storage
# ---------------------------------------------------------------------------

class LatencySurfaceDB:
    """
    Persistent storage for the RTDS latency harness.

    Uses WAL mode so concurrent analysis queries don't block writes.
    All writes are batched; call flush() to commit.
    """

    def __init__(self, db_path: str | Path = "bot/data/rtds_latency.db") -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        self._pending: int = 0

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS truth_ticks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                source          TEXT    NOT NULL,
                price           REAL    NOT NULL,
                rtds_timestamp  REAL,
                local_recv_ns   INTEGER NOT NULL,
                local_wall_ts   REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tt_symbol
                ON truth_ticks (symbol);
            CREATE INDEX IF NOT EXISTS idx_tt_recv
                ON truth_ticks (local_recv_ns);

            CREATE TABLE IF NOT EXISTS market_ticks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id            TEXT    NOT NULL,
                channel             TEXT    NOT NULL,
                best_bid            REAL,
                best_ask            REAL,
                last_trade_price    REAL,
                market_timestamp    REAL,
                local_recv_ns       INTEGER NOT NULL,
                local_wall_ts       REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mt_token
                ON market_ticks (token_id);
            CREATE INDEX IF NOT EXISTS idx_mt_recv
                ON market_ticks (local_recv_ns);

            CREATE TABLE IF NOT EXISTS price_errors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id        TEXT    NOT NULL,
                symbol          TEXT    NOT NULL,
                fair_value      REAL    NOT NULL,
                venue_mid       REAL    NOT NULL,
                price_error     REAL    NOT NULL,
                truth_age_ms    REAL    NOT NULL,
                market_age_ms   REAL    NOT NULL,
                computed_at_ns  INTEGER NOT NULL,
                wall_time       TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pe_token
                ON price_errors (token_id);
            CREATE INDEX IF NOT EXISTS idx_pe_computed
                ON price_errors (computed_at_ns);
            CREATE INDEX IF NOT EXISTS idx_pe_wall
                ON price_errors (wall_time);

            CREATE TABLE IF NOT EXISTS hourly_stats (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                hour                    TEXT    NOT NULL,
                symbol                  TEXT    NOT NULL,
                token_id                TEXT    NOT NULL,
                n_truth_ticks           INTEGER NOT NULL DEFAULT 0,
                n_market_ticks          INTEGER NOT NULL DEFAULT 0,
                n_price_errors          INTEGER NOT NULL DEFAULT 0,
                median_lag_ms           REAL,
                p95_lag_ms              REAL,
                p99_lag_ms              REAL,
                mean_abs_price_error    REAL,
                stale_quote_rate        REAL,
                estimated_maker_ev_bps  REAL
            );
            CREATE INDEX IF NOT EXISTS idx_hs_hour
                ON hourly_stats (hour);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Insert helpers
    # ------------------------------------------------------------------

    def insert_truth_tick(self, tick: TruthTick) -> None:
        self._conn.execute(
            """INSERT INTO truth_ticks
               (symbol, source, price, rtds_timestamp, local_recv_ns, local_wall_ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tick.symbol, tick.source, tick.price, tick.rtds_timestamp,
             tick.local_recv_ts, tick.local_wall_ts),
        )
        self._pending += 1

    def insert_market_tick(self, tick: MarketTick) -> None:
        self._conn.execute(
            """INSERT INTO market_ticks
               (token_id, channel, best_bid, best_ask, last_trade_price,
                market_timestamp, local_recv_ns, local_wall_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tick.token_id, tick.channel, tick.best_bid, tick.best_ask,
             tick.last_trade_price, tick.market_timestamp,
             tick.local_recv_ts, tick.local_wall_ts),
        )
        self._pending += 1

    def insert_price_error(self, pe: PriceError) -> None:
        self._conn.execute(
            """INSERT INTO price_errors
               (token_id, symbol, fair_value, venue_mid, price_error,
                truth_age_ms, market_age_ms, computed_at_ns, wall_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pe.token_id, pe.symbol, pe.fair_value, pe.venue_mid, pe.price_error,
             pe.truth_age_ms, pe.market_age_ms, pe.computed_at,
             datetime.now(timezone.utc).isoformat()),
        )
        self._pending += 1

    def insert_hourly_stats(self, stats: dict) -> None:
        self._conn.execute(
            """INSERT INTO hourly_stats
               (hour, symbol, token_id, n_truth_ticks, n_market_ticks, n_price_errors,
                median_lag_ms, p95_lag_ms, p99_lag_ms, mean_abs_price_error,
                stale_quote_rate, estimated_maker_ev_bps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (stats.get("hour"), stats.get("symbol"), stats.get("token_id", ""),
             stats.get("n_truth_ticks", 0), stats.get("n_market_ticks", 0),
             stats.get("n_price_errors", 0),
             stats.get("median_lag_ms"), stats.get("p95_lag_ms"),
             stats.get("p99_lag_ms"), stats.get("mean_abs_price_error"),
             stats.get("stale_quote_rate"), stats.get("estimated_maker_ev_bps")),
        )
        self._pending += 1

    def flush(self) -> None:
        self._conn.commit()
        self._pending = 0

    def maybe_flush(self, threshold: int = _DB_FLUSH_INTERVAL) -> None:
        if self._pending >= threshold:
            self.flush()

    def close(self) -> None:
        self.flush()
        self._conn.close()

    # ------------------------------------------------------------------
    # Read helpers (used by analysis)
    # ------------------------------------------------------------------

    def fetch_price_errors_since(
        self, since_wall: str, token_id: Optional[str] = None
    ) -> list[tuple]:
        """Return (truth_age_ms, market_age_ms, price_error) rows since a wall timestamp."""
        if token_id:
            cur = self._conn.execute(
                "SELECT truth_age_ms, market_age_ms, price_error "
                "FROM price_errors WHERE wall_time >= ? AND token_id = ?",
                (since_wall, token_id),
            )
        else:
            cur = self._conn.execute(
                "SELECT truth_age_ms, market_age_ms, price_error "
                "FROM price_errors WHERE wall_time >= ?",
                (since_wall,),
            )
        return cur.fetchall()

    def count_truth_ticks_since(self, since_wall_ts: float) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM truth_ticks WHERE local_wall_ts >= ?",
            (since_wall_ts,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def count_market_ticks_since(self, since_wall_ts: float, token_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM market_ticks WHERE local_wall_ts >= ? AND token_id = ?",
            (since_wall_ts, token_id),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _normalise_ts(raw) -> Optional[float]:
    """Convert exchange timestamp to epoch seconds regardless of unit."""
    v = _safe_float(raw, -1.0)
    if v <= 0:
        return None
    if v > 1e15:       # microseconds
        return v / 1_000_000.0
    if v > 1e12:       # milliseconds
        return v / 1_000.0
    return v           # already seconds


def _percentile_from_sorted(values: list[float], pct: float) -> float:
    """Return percentile value (pct in 0.0-1.0) from an already-sorted list."""
    if not values:
        return 0.0
    n = len(values)
    if n == 1:
        return values[0]
    rank = pct * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    w = rank - lo
    return values[lo] * (1.0 - w) + values[hi] * w


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

class RTDSLatencyHarness:
    """
    Runs both RTDS and market WebSocket connections concurrently and records
    every event with nanosecond-precision local timestamps.

    Parameters
    ----------
    token_ids:
        Polymarket condition token IDs to subscribe on the market channel.
    symbol:
        Crypto symbol to request from RTDS (e.g. "BTC").
    db_path:
        SQLite database path.  Parent directory is created if absent.
    fair_value_model:
        "passthrough" — use RTDS price directly as fair mid (raw spread measurement).
        Future: "barrier" for Black-Scholes barrier crossing probability.
    websocket_connect:
        Injection point for tests; defaults to websockets.connect.
    """

    def __init__(
        self,
        token_ids: list[str],
        symbol: str = "BTC",
        db_path: str | Path = "bot/data/rtds_latency.db",
        fair_value_model: str = "passthrough",
        *,
        websocket_connect=None,
        _clock=None,
        _monotonic_ns=None,
    ) -> None:
        if not token_ids:
            raise ValueError("token_ids must be non-empty")

        self.token_ids = list(token_ids)
        self.symbol = symbol.upper()
        self.fair_value_model = fair_value_model
        self.db = LatencySurfaceDB(db_path)

        # Allow injection for tests
        self._ws_connect = websocket_connect
        self._clock = _clock or time.time
        self._monotonic_ns = _monotonic_ns or time.monotonic_ns

        # Runtime state
        self._latest_truth: Optional[TruthTick] = None
        self._latest_market: dict[str, MarketTick] = {}
        self._event_count: int = 0

        # Counters for hourly stats
        self._hour_truth_count: int = 0
        self._hour_market_count: int = 0
        self._hour_start_wall: float = self._clock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, duration_hours: float = 24.0) -> None:
        """Run both WS connections for the specified duration, then stop."""
        if websockets is None:
            raise RuntimeError("websockets library is required; install it with pip")

        end_time = self._clock() + duration_hours * 3600.0
        logger.info(
            "RTDS harness starting: symbol=%s tokens=%d duration=%.1fh",
            self.symbol, len(self.token_ids), duration_hours,
        )

        try:
            await asyncio.gather(
                self._run_rtds_connection(end_time),
                self._run_market_connection(end_time),
                self._periodic_stats(interval_seconds=3600, end_time=end_time),
            )
        finally:
            self.db.flush()
            logger.info("RTDS harness finished, DB flushed.")

    # ------------------------------------------------------------------
    # WebSocket connection loops
    # ------------------------------------------------------------------

    async def _run_rtds_connection(self, end_time: float) -> None:
        """Subscribe to wss://…/rtds channel 'crypto_prices'."""
        backoff = _BACKOFF_BASE_S
        connect_fn = self._ws_connect or websockets.connect

        while self._clock() < end_time:
            try:
                async with connect_fn(RTDS_WS_URL) as ws:
                    backoff = _BACKOFF_BASE_S  # reset on successful connect
                    sub = json.dumps({
                        "type": "subscribe",
                        "channel": "crypto_prices",
                        "symbols": [self.symbol],
                    })
                    await ws.send(sub)
                    logger.info("RTDS: subscribed to crypto_prices for %s", self.symbol)

                    async for raw in ws:
                        if self._clock() >= end_time:
                            return
                        recv_ns = self._monotonic_ns()
                        wall_ts = self._clock()
                        self._process_rtds_message(raw, recv_ns, wall_ts)

            except asyncio.CancelledError:
                return
            except (WebSocketException, ConnectionClosed, OSError) as exc:
                logger.warning("RTDS WS disconnected: %s — backoff %.1fs", exc, backoff)
            except Exception as exc:
                logger.error("RTDS unexpected error: %s — backoff %.1fs", exc, backoff)

            if self._clock() < end_time:
                await asyncio.sleep(min(backoff, _BACKOFF_MAX_S))
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX_S)

    async def _run_market_connection(self, end_time: float) -> None:
        """Subscribe to wss://…/market channel 'best_bid_ask' for all token_ids."""
        backoff = _BACKOFF_BASE_S
        connect_fn = self._ws_connect or websockets.connect

        while self._clock() < end_time:
            try:
                async with connect_fn(MARKET_WS_URL) as ws:
                    backoff = _BACKOFF_BASE_S
                    for token_id in self.token_ids:
                        sub = json.dumps({
                            "type": "subscribe",
                            "channel": "best_bid_ask",
                            "assets_ids": [token_id],
                        })
                        await ws.send(sub)
                    logger.info(
                        "Market WS: subscribed best_bid_ask for %d tokens",
                        len(self.token_ids),
                    )

                    async for raw in ws:
                        if self._clock() >= end_time:
                            return
                        recv_ns = self._monotonic_ns()
                        wall_ts = self._clock()
                        self._process_market_message(raw, recv_ns, wall_ts)

            except asyncio.CancelledError:
                return
            except (WebSocketException, ConnectionClosed, OSError) as exc:
                logger.warning("Market WS disconnected: %s — backoff %.1fs", exc, backoff)
            except Exception as exc:
                logger.error("Market WS unexpected error: %s — backoff %.1fs", exc, backoff)

            if self._clock() < end_time:
                await asyncio.sleep(min(backoff, _BACKOFF_MAX_S))
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX_S)

    # ------------------------------------------------------------------
    # Message parsers
    # ------------------------------------------------------------------

    def _process_rtds_message(self, raw: str | bytes, recv_ns: int, wall_ts: float) -> None:
        """Parse one RTDS message, update truth state, and trigger price-error computation."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("RTDS: JSON parse failed: %s", exc)
            return

        if not isinstance(data, dict):
            logger.debug("RTDS: unexpected message type %s: %r", type(data).__name__, data)
            return

        # The RTDS schema is undocumented; we log unknown shapes and gracefully skip.
        # Known shape: {"symbol": "BTC", "price": 87432.5, "timestamp": 1711234567890, "source": "binance"}
        # Some messages are list-wrapped: [{"symbol": ...}]
        if isinstance(data, list):
            for item in data:
                self._process_rtds_message(json.dumps(item), recv_ns, wall_ts)
            return

        price_raw = data.get("price") or data.get("close") or data.get("last")
        if price_raw is None:
            # Could be a heartbeat or subscription ack — log at DEBUG only
            logger.debug("RTDS: no price field in message: %s", list(data.keys()))
            return

        price = _safe_float(price_raw, 0.0)
        if price <= 0.0:
            logger.debug("RTDS: non-positive price %r — skipping", price_raw)
            return

        symbol = str(data.get("symbol") or data.get("asset") or self.symbol).upper()
        source = str(data.get("source") or data.get("feed") or "unknown")
        rtds_ts = _normalise_ts(data.get("timestamp") or data.get("ts") or data.get("time")) or wall_ts

        tick = TruthTick(
            symbol=symbol,
            source=source,
            price=price,
            rtds_timestamp=rtds_ts,
            local_recv_ts=recv_ns,
            local_wall_ts=wall_ts,
        )
        self._latest_truth = tick
        self.db.insert_truth_tick(tick)
        self._hour_truth_count += 1
        self._event_count += 1
        self.db.maybe_flush(_DB_FLUSH_INTERVAL)
        self._maybe_compute_price_error()

    def _process_market_message(self, raw: str | bytes, recv_ns: int, wall_ts: float) -> None:
        """Parse one market-channel message, update market state, and trigger price-error computation."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("Market WS: JSON parse failed: %s", exc)
            return

        if not isinstance(data, dict):
            logger.debug("Market WS: unexpected message type %s: %r", type(data).__name__, data)
            return

        token_id = str(data.get("asset_id") or data.get("token_id") or data.get("id") or "")
        if not token_id:
            logger.debug("Market WS: no token_id field in message: %s", list(data.keys()))
            return

        channel = str(data.get("event_type") or data.get("channel") or "best_bid_ask")
        best_bid = _safe_float(data["best_bid"]) if "best_bid" in data else None
        best_ask = _safe_float(data["best_ask"]) if "best_ask" in data else None
        last_trade = (
            _safe_float(data["last_trade_price"])
            if "last_trade_price" in data
            else (_safe_float(data["price"]) if "price" in data else None)
        )
        mkt_ts = _normalise_ts(
            data.get("timestamp") or data.get("ts") or data.get("time")
        )

        tick = MarketTick(
            token_id=token_id,
            channel=channel,
            best_bid=best_bid,
            best_ask=best_ask,
            last_trade_price=last_trade,
            market_timestamp=mkt_ts,
            local_recv_ts=recv_ns,
            local_wall_ts=wall_ts,
        )
        self._latest_market[token_id] = tick
        self.db.insert_market_tick(tick)
        self._hour_market_count += 1
        self._event_count += 1
        self.db.maybe_flush(_DB_FLUSH_INTERVAL)
        self._maybe_compute_price_error(token_id)

    # ------------------------------------------------------------------
    # Price error computation
    # ------------------------------------------------------------------

    def _maybe_compute_price_error(self, token_id: Optional[str] = None) -> None:
        """
        Compute and store a PriceError when both truth and market are available.

        If token_id is given, only that token is evaluated; otherwise all monitored tokens.
        """
        if self._latest_truth is None:
            return

        now_ns = self._monotonic_ns()
        tokens = [token_id] if token_id else self.token_ids

        for tid in tokens:
            mt = self._latest_market.get(tid)
            if mt is None:
                continue
            if mt.best_bid is None or mt.best_ask is None:
                continue
            if mt.best_bid <= 0 or mt.best_ask <= 0:
                continue

            venue_mid = (mt.best_bid + mt.best_ask) / 2.0
            fair_value = self._compute_fair_value(self._latest_truth.price)

            # Ages in milliseconds (monotonic nanoseconds -> ms)
            truth_age_ms = (now_ns - self._latest_truth.local_recv_ts) / 1_000_000.0
            market_age_ms = (now_ns - mt.local_recv_ts) / 1_000_000.0

            pe = PriceError(
                token_id=tid,
                symbol=self._latest_truth.symbol,
                fair_value=fair_value,
                venue_mid=venue_mid,
                price_error=venue_mid - fair_value,
                truth_age_ms=truth_age_ms,
                market_age_ms=market_age_ms,
                computed_at=now_ns,
            )
            self.db.insert_price_error(pe)

    def _compute_fair_value(self, truth_price: float) -> float:
        """
        Derive fair value for the watched contract from the RTDS truth price.

        "passthrough": use RTDS price as the raw mid (measures spread / lag directly).
        Future models (barrier crossing probability etc.) can be added here.
        """
        if self.fair_value_model == "passthrough":
            return truth_price
        # Fallback — unknown model, pass through
        logger.warning(
            "Unknown fair_value_model %r — using passthrough", self.fair_value_model
        )
        return truth_price

    # ------------------------------------------------------------------
    # Hourly stats
    # ------------------------------------------------------------------

    async def _periodic_stats(self, interval_seconds: int = 3600, end_time: float = 0.0) -> None:
        """Compute and persist hourly statistics, then sleep until the next interval."""
        while True:
            await asyncio.sleep(interval_seconds)
            if end_time and self._clock() >= end_time:
                break
            self._compute_hourly_stats()

    def _compute_hourly_stats(self) -> None:
        """
        Query the last hour of price_errors, compute distributions, and write to hourly_stats.

        Uses pure-Python percentile (no numpy dependency required at runtime).
        """
        hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")
        hour_ago_wall = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        ).isoformat()

        rows = self.db.fetch_price_errors_since(hour_ago_wall)
        if not rows:
            logger.info("Hourly stats: no price error data for %s", hour)
            return

        # Each row: (truth_age_ms, market_age_ms, price_error)
        lags = sorted(r[0] for r in rows)          # truth_age_ms as lag proxy
        errors = [abs(r[2]) for r in rows]

        n = len(rows)
        median_lag = _percentile_from_sorted(lags, 0.50)
        p95_lag = _percentile_from_sorted(lags, 0.95)
        p99_lag = _percentile_from_sorted(lags, 0.99)
        mean_abs_err = statistics.mean(errors) if errors else 0.0
        stale_quote_rate = sum(1 for l in lags if l > 1000.0) / n if n else 0.0

        # Naive maker EV estimate: mean |price_error| minus 0 maker fee, penalised by stale rate
        # Real EV requires fill rate; this is an upper bound in basis points
        estimated_ev_bps = (mean_abs_err / 1.0) * 10_000.0 * (1.0 - stale_quote_rate)

        # Aggregate across all tokens for per-symbol stats
        for token_id in (self.token_ids or [""]):
            n_truth = self._hour_truth_count
            n_market = self._hour_market_count

            stats = {
                "hour": hour,
                "symbol": self.symbol,
                "token_id": token_id,
                "n_truth_ticks": n_truth,
                "n_market_ticks": n_market,
                "n_price_errors": n,
                "median_lag_ms": round(median_lag, 3),
                "p95_lag_ms": round(p95_lag, 3),
                "p99_lag_ms": round(p99_lag, 3),
                "mean_abs_price_error": round(mean_abs_err, 6),
                "stale_quote_rate": round(stale_quote_rate, 4),
                "estimated_maker_ev_bps": round(estimated_ev_bps, 2),
            }
            self.db.insert_hourly_stats(stats)
            logger.info(
                "Hourly stats [%s/%s]: lag p50=%.0fms p95=%.0fms p99=%.0fms "
                "err=%.4f stale=%.1f%% ev=%.1f bps",
                self.symbol, token_id[:8],
                median_lag, p95_lag, p99_lag,
                mean_abs_err, stale_quote_rate * 100, estimated_ev_bps,
            )

        self.db.flush()
        # Reset hourly accumulators
        self._hour_truth_count = 0
        self._hour_market_count = 0


# ---------------------------------------------------------------------------
# Post-collection analysis
# ---------------------------------------------------------------------------

def analyse_latency_surface(
    db_path: str | Path,
    min_samples: int = 1000,
    eval_hours: float = KILL_EVALUATION_HOURS,
) -> dict:
    """
    Read collected data and produce a verdict against the three kill conditions.

    Returns a dict with:
        verdict: "CONTINUE" | "KILL_H1" | "KILL_H2" | "KILL_H3" | "INSUFFICIENT_DATA"
        h1_pass, h2_pass, h3_pass: bool
        median_lag_ms, stale_quote_rate, estimated_ev_bps: float
        n_samples: int
        summary: str
    """
    conn = sqlite3.connect(str(db_path))
    try:
        # Use all data collected so far
        rows = conn.execute(
            "SELECT truth_age_ms, market_age_ms, price_error FROM price_errors"
        ).fetchall()
    finally:
        conn.close()

    n = len(rows)
    if n < min_samples:
        return {
            "verdict": "INSUFFICIENT_DATA",
            "n_samples": n,
            "min_samples": min_samples,
            "h1_pass": False,
            "h2_pass": False,
            "h3_pass": False,
            "median_lag_ms": 0.0,
            "stale_quote_rate": 0.0,
            "estimated_ev_bps": 0.0,
            "summary": f"Only {n} samples collected; need {min_samples} before evaluation.",
        }

    lags = sorted(r[0] for r in rows)
    errors = [abs(r[2]) for r in rows]

    median_lag = _percentile_from_sorted(lags, 0.50)
    stale_rate = sum(1 for l in lags if l > 1000.0) / n
    mean_err = statistics.mean(errors)
    ev_bps = (mean_err / 1.0) * 10_000.0 * (1.0 - stale_rate)

    h1 = median_lag >= KILL_MEDIAN_LAG_MS
    h2 = stale_rate >= KILL_STALE_QUOTE_RATE
    h3 = ev_bps >= KILL_MAKER_EV_BPS

    if not h1:
        verdict = "KILL_H1"
    elif not h2:
        verdict = "KILL_H2"
    elif not h3:
        verdict = "KILL_H3"
    else:
        verdict = "CONTINUE"

    summary = (
        f"Samples: {n} | Median lag: {median_lag:.1f} ms (need >={KILL_MEDIAN_LAG_MS}) "
        f"[{'PASS' if h1 else 'FAIL'}] | "
        f"Stale-quote rate: {stale_rate*100:.1f}% (need >={KILL_STALE_QUOTE_RATE*100:.0f}%) "
        f"[{'PASS' if h2 else 'FAIL'}] | "
        f"Est. maker EV: {ev_bps:.1f} bps (need >={KILL_MAKER_EV_BPS}) "
        f"[{'PASS' if h3 else 'FAIL'}] | "
        f"Verdict: {verdict}"
    )

    return {
        "verdict": verdict,
        "n_samples": n,
        "h1_pass": h1,
        "h2_pass": h2,
        "h3_pass": h3,
        "median_lag_ms": round(median_lag, 2),
        "stale_quote_rate": round(stale_rate, 4),
        "estimated_ev_bps": round(ev_bps, 2),
        "summary": summary,
    }
