#!/usr/bin/env python3
"""Instance 2: BTC 5m maker bot (T-10s execution).

This runner targets Polymarket 5-minute BTC candle markets using maker-only
orders near close.

Flow per 5-minute window:
  1) Wait until T-10 seconds before close.
  2) Compare current Binance BTC spot to candle open.
  3) If |delta| >= threshold, select UP or DOWN outcome.
  4) Read CLOB top-of-book and place post-only BUY on winning token.
  5) Cancel unfilled order at T-2 seconds.
  6) Persist every decision in SQLite for fill/win-rate analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import math
import os
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiohttp

try:
    import websockets
except Exception:  # pragma: no cover - optional runtime dependency
    websockets = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - optional runtime dependency
    pass

try:
    from bot.polymarket_clob import build_authenticated_clob_client, parse_signature_type
except ImportError:
    from polymarket_clob import build_authenticated_clob_client, parse_signature_type  # type: ignore

logger = logging.getLogger("BTC5Maker")

WINDOW_SECONDS = 300
DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
CLOB_HARD_MIN_SHARES = 5.0
CLOB_HARD_MIN_NOTIONAL_USD = 5.0
PROBE_DEFAULT_UP_MAX_BUY_PRICE = 0.49
PROBE_DEFAULT_DOWN_MAX_BUY_PRICE = 0.51


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    parsed = _safe_float(raw, None)
    if parsed is None or parsed <= 0:
        return None
    return float(parsed)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _join_reasons(*parts: str | None) -> str | None:
    text = " | ".join(part for part in parts if part)
    return text or None


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def current_window_start(ts: float | None = None) -> int:
    now = int(ts if ts is not None else time.time())
    return now - (now % WINDOW_SECONDS)


def _round_down_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return round(price, 4)
    tick = Decimal(str(tick_size))
    steps = (Decimal(str(price)) / tick).to_integral_value(rounding=ROUND_FLOOR)
    return float(steps * tick)


def _round_up(value: float, decimals: int = 2) -> float:
    scale = 10 ** max(0, int(decimals))
    return math.ceil(max(0.0, float(value)) * scale - 1e-12) / scale


def clob_min_order_size(price: float, *, min_shares: float = CLOB_HARD_MIN_SHARES) -> float:
    price = max(0.0, float(price))
    required = max(float(min_shares), (CLOB_HARD_MIN_NOTIONAL_USD / price) if price > 0.0 else float(min_shares))
    return _round_up(required, decimals=2)


def _parse_order_size(value: Any) -> float | None:
    parsed = _safe_float(value, None)
    if parsed is None:
        return None
    text = str(value).strip().lower()
    if text and "." not in text and "e" not in text and abs(parsed) > 1000:
        # Official docs have shown both human-readable strings and 1e6-scaled
        # integers for order sizes. This bot only trades a few shares, so very
        # large integer payloads are safely treated as fixed-point quantities.
        return float(parsed) / 1_000_000.0
    return float(parsed)


def market_slug_for_window(window_start_ts: int) -> str:
    return f"btc-updown-5m-{int(window_start_ts)}"


def direction_from_prices(open_price: float, current_price: float, min_delta: float) -> tuple[str | None, float]:
    if open_price <= 0:
        return None, 0.0
    delta = (current_price - open_price) / open_price
    if abs(delta) < min_delta:
        return None, delta
    return ("UP" if delta > 0 else "DOWN"), delta


def choose_maker_buy_price(
    *,
    best_bid: float | None,
    best_ask: float | None,
    max_price: float,
    min_price: float,
    tick_size: float,
    aggression_ticks: int = 1,
) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    if best_ask > max_price:
        return None
    if best_ask <= 0 or best_bid < 0:
        return None

    min_valid = _round_down_to_tick(min_price, tick_size)
    max_valid = _round_down_to_tick(min(max_price, best_ask - tick_size), tick_size)
    if max_valid <= 0 or max_valid < min_valid:
        return None

    # Stay maker: bid below best ask. Improve by one tick from current best bid.
    quote_ticks = max(0, int(aggression_ticks))
    candidate = _round_down_to_tick(best_bid + (quote_ticks * tick_size), tick_size)
    price = min(max(candidate, min_valid), max_valid)
    if price >= best_ask:
        return None
    return price


def effective_max_buy_price(cfg: "MakerConfig", direction: str) -> float:
    normalized = str(direction or "").strip().upper()
    if normalized == "UP" and cfg.up_max_buy_price is not None:
        return float(cfg.up_max_buy_price)
    if normalized == "DOWN" and cfg.down_max_buy_price is not None:
        return float(cfg.down_max_buy_price)
    return float(cfg.max_buy_price)


def summarize_recent_direction_regime(
    rows: list[dict[str, Any]],
    *,
    default_quote_ticks: int,
    weaker_direction_quote_ticks: int,
    min_fills_per_direction: int,
    min_pnl_gap_usd: float,
) -> dict[str, Any] | None:
    if not rows:
        return None

    direction_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        direction = str(row.get("direction") or "").strip().upper()
        if direction not in {"UP", "DOWN"}:
            continue
        direction_groups.setdefault(direction, []).append(row)

    if not direction_groups:
        return None

    def _rollup(direction: str, group_rows: list[dict[str, Any]]) -> dict[str, Any]:
        fills = len(group_rows)
        pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in group_rows), 4)
        avg_pnl = round(pnl / fills, 4) if fills else 0.0
        avg_price = round(
            sum(_safe_float(row.get("order_price"), 0.0) for row in group_rows) / fills,
            4,
        ) if fills else 0.0
        return {
            "label": direction,
            "fills": fills,
            "pnl_usd": pnl,
            "avg_pnl_usd": avg_pnl,
            "avg_order_price": avg_price,
        }

    by_direction = sorted(
        (_rollup(direction, group_rows) for direction, group_rows in direction_groups.items()),
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    regime = {
        "fills_considered": sum(item["fills"] for item in by_direction),
        "default_quote_ticks": max(0, int(default_quote_ticks)),
        "weaker_direction_quote_ticks": max(0, int(weaker_direction_quote_ticks)),
        "min_fills_per_direction": max(1, int(min_fills_per_direction)),
        "min_pnl_gap_usd": round(max(0.0, float(min_pnl_gap_usd)), 4),
        "by_direction": by_direction,
        "triggered": False,
        "trigger_reason": "insufficient_directions",
        "direction_quote_ticks": {},
    }
    if len(by_direction) < 2:
        return regime

    favored = by_direction[0]
    weaker = by_direction[1]
    pnl_gap = round(favored["pnl_usd"] - weaker["pnl_usd"], 4)
    regime.update(
        {
            "favored_direction": favored["label"],
            "weaker_direction": weaker["label"],
            "pnl_gap_usd": pnl_gap,
        }
    )

    min_fills = regime["min_fills_per_direction"]
    if favored["fills"] < min_fills or weaker["fills"] < min_fills:
        regime["trigger_reason"] = "insufficient_fills"
        return regime
    if favored["avg_pnl_usd"] <= weaker["avg_pnl_usd"]:
        regime["trigger_reason"] = "no_avg_pnl_edge"
        return regime
    if pnl_gap < regime["min_pnl_gap_usd"]:
        regime["trigger_reason"] = "pnl_gap_below_threshold"
        return regime

    regime["triggered"] = True
    regime["trigger_reason"] = "weaker_direction_quote_tightened"
    regime["direction_quote_ticks"] = {
        favored["label"]: regime["default_quote_ticks"],
        weaker["label"]: regime["weaker_direction_quote_ticks"],
    }
    return regime


def effective_quote_ticks(
    cfg: "MakerConfig",
    direction: str,
    *,
    recent_regime: dict[str, Any] | None = None,
) -> int:
    normalized = str(direction or "").strip().upper()
    base_ticks = max(0, int(cfg.maker_improve_ticks))
    if not recent_regime or not recent_regime.get("triggered"):
        return base_ticks
    override = (recent_regime.get("direction_quote_ticks") or {}).get(normalized)
    if override is None:
        return base_ticks
    return max(0, int(override))


def calc_trade_size_usd(bankroll_usd: float, risk_fraction: float, max_trade_usd: float) -> float:
    if bankroll_usd <= 0 or risk_fraction <= 0 or max_trade_usd <= 0:
        return 0.0
    return round(min(bankroll_usd * risk_fraction, max_trade_usd), 2)


def deterministic_fill(window_start_ts: int, fill_probability: float) -> bool:
    p = max(0.0, min(1.0, fill_probability))
    digest = hashlib.sha256(str(window_start_ts).encode("utf-8")).hexdigest()
    sample = int(digest[:8], 16) / 0xFFFFFFFF
    return sample < p


def _normalize_outcome_label(label: str) -> str:
    text = (label or "").strip().lower()
    if not text:
        return ""
    if text in {"up", "yes", "true", "higher"}:
        return "UP"
    if text in {"down", "no", "false", "lower"}:
        return "DOWN"
    if "up" in text or "above" in text or "higher" in text:
        return "UP"
    if "down" in text or "below" in text or "lower" in text:
        return "DOWN"
    return text.upper()


def choose_token_id_for_direction(market: dict[str, Any], direction: str) -> str | None:
    want = direction.upper()

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for t in tokens:
            if not isinstance(t, dict):
                continue
            label = _normalize_outcome_label(str(t.get("outcome", "")))
            token_id = str(t.get("token_id") or t.get("clobTokenId") or t.get("id") or "")
            if label == want and token_id:
                return token_id

    outcomes = parse_json_list(market.get("outcomes"))
    token_ids = parse_json_list(market.get("clobTokenIds"))
    if outcomes and token_ids and len(outcomes) == len(token_ids):
        for out, tid in zip(outcomes, token_ids):
            if _normalize_outcome_label(str(out)) == want:
                token_id = str(tid)
                if token_id:
                    return token_id
        # Fallback for classic binary ordering: index 0=UP, 1=DOWN.
        if len(token_ids) == 2:
            return str(token_ids[0] if want == "UP" else token_ids[1])

    return None


@dataclass
class MakerConfig:
    paper_trading: bool = os.environ.get("BTC5_PAPER_TRADING", "true").lower() in {"1", "true", "yes"}
    bankroll_usd: float = float(os.environ.get("BTC5_BANKROLL_USD", "250"))
    risk_fraction: float = float(os.environ.get("BTC5_RISK_FRACTION", "0.02"))
    max_trade_usd: float = float(os.environ.get("BTC5_MAX_TRADE_USD", "5.00"))
    min_trade_usd: float = float(os.environ.get("BTC5_MIN_TRADE_USD", "5.00"))
    min_delta: float = float(os.environ.get("BTC5_MIN_DELTA", "0.0003"))
    max_abs_delta: float | None = _optional_env_float("BTC5_MAX_ABS_DELTA")
    maker_improve_ticks: int = int(os.environ.get("BTC5_MAKER_IMPROVE_TICKS", "1"))
    max_buy_price: float = float(os.environ.get("BTC5_MAX_BUY_PRICE", "0.95"))
    up_max_buy_price: float | None = _optional_env_float("BTC5_UP_MAX_BUY_PRICE")
    down_max_buy_price: float | None = _optional_env_float("BTC5_DOWN_MAX_BUY_PRICE")
    enable_recent_regime_skew: bool = os.environ.get("BTC5_ENABLE_RECENT_REGIME_SKEW", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    recent_regime_fills: int = int(os.environ.get("BTC5_RECENT_REGIME_FILLS", "12"))
    regime_min_fills_per_direction: int = int(os.environ.get("BTC5_REGIME_MIN_FILLS_PER_DIRECTION", "5"))
    regime_min_pnl_gap_usd: float = float(os.environ.get("BTC5_REGIME_MIN_PNL_GAP_USD", "20.0"))
    regime_weaker_direction_quote_ticks: int = int(
        os.environ.get("BTC5_REGIME_WEAKER_DIRECTION_QUOTE_TICKS", "0")
    )
    min_buy_price: float = float(os.environ.get("BTC5_MIN_BUY_PRICE", "0.90"))
    tick_size: float = float(os.environ.get("BTC5_TICK_SIZE", "0.01"))
    entry_seconds_before_close: int = int(os.environ.get("BTC5_ENTRY_SECONDS_BEFORE_CLOSE", "10"))
    cancel_seconds_before_close: int = int(os.environ.get("BTC5_CANCEL_SECONDS_BEFORE_CLOSE", "2"))
    daily_loss_limit_usd: float = float(os.environ.get("BTC5_DAILY_LOSS_LIMIT_USD", "247"))
    enable_probe_after_daily_loss: bool = _env_flag("BTC5_ENABLE_PROBE_AFTER_DAILY_LOSS", True)
    enable_probe_after_recent_loss: bool = _env_flag("BTC5_ENABLE_PROBE_AFTER_RECENT_LOSS", True)
    probe_recent_fills: int = int(os.environ.get("BTC5_PROBE_RECENT_FILLS", "8"))
    probe_recent_min_pnl_usd: float = float(os.environ.get("BTC5_PROBE_RECENT_MIN_PNL_USD", "0.0"))
    probe_min_delta_multiplier: float = float(os.environ.get("BTC5_PROBE_MIN_DELTA_MULTIPLIER", "1.0"))
    probe_quote_ticks: int = int(os.environ.get("BTC5_PROBE_QUOTE_TICKS", "0"))
    probe_max_abs_delta: float | None = _optional_env_float("BTC5_PROBE_MAX_ABS_DELTA")
    probe_up_max_buy_price: float | None = _optional_env_float("BTC5_PROBE_UP_MAX_BUY_PRICE")
    probe_down_max_buy_price: float | None = _optional_env_float("BTC5_PROBE_DOWN_MAX_BUY_PRICE")
    paper_fill_probability: float = float(os.environ.get("BTC5_PAPER_FILL_PROBABILITY", "0.20"))
    clob_fee_rate_bps: int = int(os.environ.get("BTC5_CLOB_FEE_RATE_BPS", "0"))
    request_timeout_sec: float = float(os.environ.get("BTC5_REQUEST_TIMEOUT_SEC", "8"))

    binance_ws_url: str = os.environ.get("BTC5_BINANCE_WS_URL", "wss://stream.binance.com:9443/ws/btcusdt@trade")
    binance_klines_url: str = os.environ.get(
        "BTC5_BINANCE_KLINES_URL",
        "https://api.binance.com/api/v3/klines",
    )
    binance_ticker_url: str = os.environ.get(
        "BTC5_BINANCE_TICKER_URL",
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    )
    gamma_markets_url: str = os.environ.get(
        "BTC5_GAMMA_MARKETS_URL",
        "https://gamma-api.polymarket.com/markets",
    )
    clob_book_url: str = os.environ.get(
        "BTC5_CLOB_BOOK_URL",
        "https://clob.polymarket.com/book",
    )
    db_path: Path = Path(os.environ.get("BTC5_DB_PATH", str(DEFAULT_DB_PATH)))


@dataclass(frozen=True)
class PlacementResult:
    order_id: str | None
    success: bool
    status: str | None
    error_msg: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveOrderState:
    order_id: str
    status: str | None
    original_size: float | None
    size_matched: float
    price: float | None
    raw: dict[str, Any] | None = None

    @property
    def normalized_status(self) -> str:
        return (self.status or "").strip().lower()

    @property
    def is_cancelled(self) -> bool:
        return self.normalized_status in {"cancelled", "canceled"}

    @property
    def is_live(self) -> bool:
        return self.normalized_status in {"live", "open", "delayed", "unmatched", "pending"}

    @property
    def fully_filled(self) -> bool:
        if self.normalized_status in {"matched", "filled", "completed"}:
            return self.size_matched > 0
        if self.original_size is None:
            return False
        return self.size_matched + 1e-9 >= self.original_size and self.size_matched > 0

    @property
    def partially_filled(self) -> bool:
        return self.size_matched > 0 and not self.fully_filled


class TradeDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS window_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    window_start_ts INTEGER NOT NULL UNIQUE,
                    window_end_ts INTEGER NOT NULL,
                    slug TEXT NOT NULL,
                    decision_ts INTEGER NOT NULL,
                    direction TEXT,
                    open_price REAL,
                    current_price REAL,
                    delta REAL,
                    token_id TEXT,
                    best_bid REAL,
                    best_ask REAL,
                    order_price REAL,
                    trade_size_usd REAL,
                    shares REAL,
                    order_id TEXT,
                    order_status TEXT NOT NULL,
                    filled INTEGER,
                    reason TEXT,
                    resolved_side TEXT,
                    won INTEGER,
                    pnl_usd REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_window_trades_decision_ts
                    ON window_trades(decision_ts);
                """
            )

    def window_exists(self, window_start_ts: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM window_trades WHERE window_start_ts = ?",
                (int(window_start_ts),),
            ).fetchone()
        return row is not None

    def upsert_window(self, row: dict[str, Any]) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "window_start_ts": int(row["window_start_ts"]),
            "window_end_ts": int(row["window_end_ts"]),
            "slug": str(row.get("slug") or market_slug_for_window(int(row["window_start_ts"]))),
            "decision_ts": int(row.get("decision_ts", time.time())),
            "direction": row.get("direction"),
            "open_price": row.get("open_price"),
            "current_price": row.get("current_price"),
            "delta": row.get("delta"),
            "token_id": row.get("token_id"),
            "best_bid": row.get("best_bid"),
            "best_ask": row.get("best_ask"),
            "order_price": row.get("order_price"),
            "trade_size_usd": row.get("trade_size_usd"),
            "shares": row.get("shares"),
            "order_id": row.get("order_id"),
            "order_status": row.get("order_status", "unknown"),
            "filled": row.get("filled"),
            "reason": row.get("reason"),
            "resolved_side": row.get("resolved_side"),
            "won": row.get("won"),
            "pnl_usd": row.get("pnl_usd"),
            "created_at": row.get("created_at") or now_iso,
            "updated_at": now_iso,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO window_trades (
                    window_start_ts, window_end_ts, slug, decision_ts, direction,
                    open_price, current_price, delta, token_id, best_bid, best_ask,
                    order_price, trade_size_usd, shares, order_id, order_status,
                    filled, reason, resolved_side, won, pnl_usd, created_at, updated_at
                ) VALUES (
                    :window_start_ts, :window_end_ts, :slug, :decision_ts, :direction,
                    :open_price, :current_price, :delta, :token_id, :best_bid, :best_ask,
                    :order_price, :trade_size_usd, :shares, :order_id, :order_status,
                    :filled, :reason, :resolved_side, :won, :pnl_usd, :created_at, :updated_at
                )
                ON CONFLICT(window_start_ts) DO UPDATE SET
                    decision_ts=excluded.decision_ts,
                    direction=excluded.direction,
                    open_price=excluded.open_price,
                    current_price=excluded.current_price,
                    delta=excluded.delta,
                    token_id=excluded.token_id,
                    best_bid=excluded.best_bid,
                    best_ask=excluded.best_ask,
                    order_price=excluded.order_price,
                    trade_size_usd=excluded.trade_size_usd,
                    shares=excluded.shares,
                    order_id=excluded.order_id,
                    order_status=excluded.order_status,
                    filled=excluded.filled,
                    reason=excluded.reason,
                    resolved_side=excluded.resolved_side,
                    won=excluded.won,
                    pnl_usd=excluded.pnl_usd,
                    updated_at=excluded.updated_at
                """,
                payload,
            )

    def unsettled_rows(self, max_window_start_ts: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM window_trades
                WHERE window_start_ts <= ?
                  AND resolved_side IS NULL
                ORDER BY window_start_ts ASC
                """,
                (int(max_window_start_ts),),
            ).fetchall()
        return rows

    def today_realized_pnl(self) -> float:
        now = datetime.now(timezone.utc)
        day_start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(pnl_usd), 0.0) AS pnl
                FROM window_trades
                WHERE decision_ts >= ?
                  AND pnl_usd IS NOT NULL
                """,
                (day_start,),
            ).fetchone()
        return float(row["pnl"] if row else 0.0)

    def recent_live_filled(self, *, limit: int) -> list[dict[str, Any]]:
        capped_limit = max(0, int(limit))
        if capped_limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    direction,
                    order_price,
                    pnl_usd
                FROM window_trades
                WHERE order_status = 'live_filled'
                ORDER BY id DESC
                LIMIT ?
                """,
                (capped_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def status_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS windows_seen,
                    SUM(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END) AS orders_placed,
                    SUM(CASE WHEN filled = 1 THEN 1 ELSE 0 END) AS fills,
                    SUM(CASE WHEN filled = 1 AND won IS NOT NULL THEN 1 ELSE 0 END) AS settled_fills,
                    SUM(CASE WHEN filled = 1 AND won = 1 THEN 1 ELSE 0 END) AS wins,
                    COALESCE(SUM(pnl_usd), 0.0) AS total_pnl
                FROM window_trades
                """
            ).fetchone()
        orders_placed = int(totals["orders_placed"] or 0)
        fills = int(totals["fills"] or 0)
        settled_fills = int(totals["settled_fills"] or 0)
        wins = int(totals["wins"] or 0)
        return {
            "windows_seen": int(totals["windows_seen"] or 0),
            "orders_placed": orders_placed,
            "fills": fills,
            "fill_rate": (fills / orders_placed) if orders_placed else 0.0,
            "settled_fills": settled_fills,
            "wins": wins,
            "win_rate": (wins / settled_fills) if settled_fills else 0.0,
            "total_pnl_usd": float(totals["total_pnl"] or 0.0),
            "today_pnl_usd": self.today_realized_pnl(),
        }


class BinancePriceCache:
    def __init__(self, maxlen: int = 6000):
        self._ticks: deque[tuple[int, float]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def add_tick(self, ts_sec: int, price: float) -> None:
        async with self._lock:
            self._ticks.append((ts_sec, price))

    async def latest(self) -> tuple[int, float] | None:
        async with self._lock:
            if not self._ticks:
                return None
            return self._ticks[-1]

    async def open_price_for_window(self, window_start_ts: int) -> float | None:
        upper = window_start_ts + 30
        async with self._lock:
            if not self._ticks:
                return None
            for ts, px in self._ticks:
                if window_start_ts <= ts <= upper:
                    return px
            # Fallback: nearest observed tick around the boundary.
            nearest = min(self._ticks, key=lambda item: abs(item[0] - window_start_ts))
            if abs(nearest[0] - window_start_ts) <= 180:
                return nearest[1]
        return None


class BinanceTradeFeed:
    def __init__(self, ws_url: str, cache: BinancePriceCache):
        self.ws_url = ws_url
        self.cache = cache

    async def run(self, stop_event: asyncio.Event) -> None:
        if websockets is None:
            logger.warning("websockets package missing; Binance trade stream disabled")
            return
        backoff = 1.0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Connected to Binance trade stream")
                    backoff = 1.0
                    async for raw in ws:
                        if stop_event.is_set():
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        price = _safe_float(payload.get("p"), None)
                        event_ms = _safe_float(payload.get("E"), None)
                        if price is None or event_ms is None:
                            continue
                        ts = int(event_ms // 1000)
                        await self.cache.add_tick(ts, float(price))
            except Exception as exc:
                logger.warning("Binance WS reconnect in %.1fs (%s)", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)


class MarketHttpClient:
    def __init__(self, cfg: MakerConfig, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.session = session

    async def fetch_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        # Primary path: explicit slug query.
        try:
            async with self.session.get(
                self.cfg.gamma_markets_url,
                params={"slug": slug, "limit": 5},
                timeout=timeout,
            ) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    markets = payload if isinstance(payload, list) else payload.get("data", [])
                    for m in markets:
                        if isinstance(m, dict) and str(m.get("slug", "")) == slug:
                            return m
        except Exception as exc:
            logger.warning("Gamma slug lookup failed for %s: %s", slug, exc)

        # Fallback: scan latest markets and match exact slug.
        try:
            async with self.session.get(
                self.cfg.gamma_markets_url,
                params={"limit": 400, "active": "true"},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                markets = payload if isinstance(payload, list) else payload.get("data", [])
                for m in markets:
                    if isinstance(m, dict) and str(m.get("slug", "")) == slug:
                        return m
        except Exception as exc:
            logger.warning("Gamma fallback scan failed: %s", exc)
        return None

    async def fetch_book(self, token_id: str) -> dict[str, Any] | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        try:
            async with self.session.get(
                self.cfg.clob_book_url,
                params={"token_id": token_id},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                return payload if isinstance(payload, dict) else None
        except Exception as exc:
            logger.warning("Book fetch failed for %s: %s", token_id[:12], exc)
            return None

    async def fetch_binance_window_open_close(self, window_start_ts: int) -> tuple[float, float] | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        params = {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "startTime": int(window_start_ts) * 1000,
            "limit": 1,
        }
        try:
            async with self.session.get(self.cfg.binance_klines_url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                if not isinstance(payload, list) or not payload:
                    return None
                row = payload[0]
                if not isinstance(row, list) or len(row) < 5:
                    return None
                open_px = _safe_float(row[1], None)
                close_px = _safe_float(row[4], None)
                if open_px is None or close_px is None:
                    return None
                return float(open_px), float(close_px)
        except Exception as exc:
            logger.warning("Binance kline fetch failed: %s", exc)
            return None

    async def fetch_binance_spot(self) -> float | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        try:
            async with self.session.get(self.cfg.binance_ticker_url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                return _safe_float(payload.get("price"), None)
        except Exception:
            return None

    @staticmethod
    def top_of_book(book: dict[str, Any]) -> tuple[float | None, float | None]:
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        def _best(levels: Iterable[dict[str, Any]], side: str) -> float | None:
            prices: list[float] = []
            for level in levels:
                if not isinstance(level, dict):
                    continue
                px = _safe_float(level.get("price"), None)
                if px is None:
                    continue
                prices.append(float(px))
            if not prices:
                return None
            return max(prices) if side == "bid" else min(prices)

        return _best(bids, "bid"), _best(asks, "ask")


class CLOBExecutor:
    def __init__(self, cfg: MakerConfig):
        self.cfg = cfg
        self.client = None

    @staticmethod
    def _signature_type() -> int:
        raw = os.environ.get("JJ_CLOB_SIGNATURE_TYPE", "1")
        parsed = parse_signature_type(raw, default=1)
        if str(raw).strip() not in {"0", "1", "2"}:
            logger.warning("Invalid JJ_CLOB_SIGNATURE_TYPE=%r; defaulting to 1", raw)
        return parsed

    def _init_client(self) -> Any:
        try:
            import py_clob_client  # noqa: F401
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("py_clob_client is required for live mode") from exc

        private_key = os.environ.get("POLY_PRIVATE_KEY", "") or os.environ.get("POLYMARKET_PK", "")
        safe_address = os.environ.get("POLY_SAFE_ADDRESS", "") or os.environ.get("POLYMARKET_FUNDER", "")
        if not private_key:
            raise RuntimeError("POLY_PRIVATE_KEY or POLYMARKET_PK is required for live mode")
        if not safe_address:
            raise RuntimeError("POLY_SAFE_ADDRESS or POLYMARKET_FUNDER is required for live mode")
        client, _, _ = build_authenticated_clob_client(
            private_key=private_key,
            safe_address=safe_address,
            configured_signature_type=self._signature_type(),
            logger=logger,
            log_prefix="BTC5",
        )
        return client

    def ensure_client(self) -> Any:
        if self.client is None:
            self.client = self._init_client()
        return self.client

    def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
        client = self.ensure_client()
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("py_clob_client imports unavailable at order time") from exc

        order_sig = inspect.signature(OrderArgs)
        kwargs: dict[str, Any] = {
            "token_id": token_id,
            "price": round(price, 2),
            "size": _round_up(shares, 2),
            "side": BUY,
        }

        signed = client.create_order(OrderArgs(**kwargs))
        try:
            resp = client.post_order(signed, OrderType.GTC, post_only=True)
        except TypeError:
            # Older client versions may not expose post_only.
            resp = client.post_order(signed, OrderType.GTC)

        if isinstance(resp, dict):
            order_id = str(resp.get("orderID") or resp.get("id") or "").strip() or None
            status = str(resp.get("status") or resp.get("orderStatus") or "").strip().lower() or None
            error_msg = str(resp.get("errorMsg") or resp.get("error") or "").strip() or None
            success = not bool(resp.get("error")) and bool(order_id)
            return PlacementResult(
                order_id=order_id,
                success=success,
                status=status,
                error_msg=error_msg,
                raw=resp,
            )
        return PlacementResult(
            order_id=None,
            success=bool(resp),
            status=None,
            raw={"response": resp},
        )

    def cancel_order(self, order_id: str) -> bool:
        if not order_id:
            return False
        client = self.ensure_client()
        try:
            resp = client.cancel(order_id)
            if isinstance(resp, dict):
                if resp.get("error"):
                    return False
                if resp.get("success") is False:
                    return False
            return True
        except Exception:
            return False

    def get_order_state(self, order_id: str) -> LiveOrderState | None:
        if not order_id:
            return None
        client = self.ensure_client()
        try:
            resp = client.get_order(order_id)
        except Exception:
            return None
        if not isinstance(resp, dict):
            return None

        payload = resp.get("order") if isinstance(resp.get("order"), dict) else resp
        status = str(payload.get("status") or payload.get("order_status") or "").strip() or None
        original_size = _parse_order_size(
            payload.get("original_size") or payload.get("size") or payload.get("order_size")
        )
        size_matched = _parse_order_size(
            payload.get("size_matched") or payload.get("filled_size") or payload.get("size_filled") or 0.0
        ) or 0.0
        price = _safe_float(payload.get("price") or payload.get("avg_price"), None)
        return LiveOrderState(
            order_id=order_id,
            status=status,
            original_size=original_size,
            size_matched=size_matched,
            price=price,
            raw=payload,
        )


class BTC5MinMakerBot:
    def __init__(self, cfg: MakerConfig):
        self.cfg = cfg
        self.db = TradeDB(cfg.db_path)
        self.cache = BinancePriceCache()
        self.clob = CLOBExecutor(cfg)

    def _recent_direction_regime(self) -> dict[str, Any] | None:
        if not self.cfg.enable_recent_regime_skew:
            return None
        rows = self.db.recent_live_filled(limit=self.cfg.recent_regime_fills)
        return summarize_recent_direction_regime(
            rows,
            default_quote_ticks=self.cfg.maker_improve_ticks,
            weaker_direction_quote_ticks=self.cfg.regime_weaker_direction_quote_ticks,
            min_fills_per_direction=self.cfg.regime_min_fills_per_direction,
            min_pnl_gap_usd=self.cfg.regime_min_pnl_gap_usd,
        )

    def _probe_max_buy_price(self, direction: str) -> float:
        normalized = str(direction or "").strip().upper()
        normal_cap = effective_max_buy_price(self.cfg, normalized)
        if normalized == "UP":
            probe_cap = self.cfg.probe_up_max_buy_price
            if probe_cap is None:
                probe_cap = PROBE_DEFAULT_UP_MAX_BUY_PRICE
            return min(normal_cap, float(probe_cap))
        if normalized == "DOWN":
            probe_cap = self.cfg.probe_down_max_buy_price
            if probe_cap is None:
                probe_cap = PROBE_DEFAULT_DOWN_MAX_BUY_PRICE
            return min(normal_cap, float(probe_cap))
        return normal_cap

    def _probe_mode(self, *, today_pnl: float) -> dict[str, Any] | None:
        reasons: list[str] = []
        hard_daily_loss_hit = today_pnl <= -abs(self.cfg.daily_loss_limit_usd)
        if hard_daily_loss_hit and self.cfg.enable_probe_after_daily_loss:
            reasons.append(
                f"probe_daily_loss today_pnl={today_pnl:.4f} limit={self.cfg.daily_loss_limit_usd:.2f}"
            )

        recent_rows = self.db.recent_live_filled(limit=self.cfg.probe_recent_fills)
        recent_pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in recent_rows), 4)
        if (
            self.cfg.enable_probe_after_recent_loss
            and self.cfg.probe_recent_fills > 0
            and len(recent_rows) >= self.cfg.probe_recent_fills
            and recent_pnl <= self.cfg.probe_recent_min_pnl_usd
        ):
            reasons.append(
                "probe_recent_live_pnl "
                f"recent_pnl={recent_pnl:.4f} fills={len(recent_rows)} "
                f"threshold={self.cfg.probe_recent_min_pnl_usd:.4f}"
            )

        if not reasons:
            return None

        effective_max_abs_delta = self.cfg.probe_max_abs_delta
        if self.cfg.max_abs_delta is not None:
            effective_max_abs_delta = (
                min(float(self.cfg.max_abs_delta), float(effective_max_abs_delta))
                if effective_max_abs_delta is not None
                else float(self.cfg.max_abs_delta)
            )

        return {
            "mode": "probe",
            "reason": _join_reasons(*reasons),
            "min_delta": max(
                float(self.cfg.min_delta),
                float(self.cfg.min_delta) * max(1.0, float(self.cfg.probe_min_delta_multiplier)),
            ),
            "max_abs_delta": effective_max_abs_delta,
            "quote_ticks": max(0, int(self.cfg.probe_quote_ticks)),
            "up_max_buy_price": self._probe_max_buy_price("UP"),
            "down_max_buy_price": self._probe_max_buy_price("DOWN"),
            "recent_live_pnl_usd": recent_pnl,
            "recent_live_fills": len(recent_rows),
            "hard_daily_loss_hit": hard_daily_loss_hit,
        }

    async def _resolve_unsettled(self, http: MarketHttpClient, through_window_start: int) -> None:
        rows = self.db.unsettled_rows(max_window_start_ts=through_window_start)
        for row in rows:
            kline = await http.fetch_binance_window_open_close(int(row["window_start_ts"]))
            if not kline:
                continue
            open_px, close_px = kline
            if close_px > open_px:
                resolved_side = "UP"
            elif close_px < open_px:
                resolved_side = "DOWN"
            else:
                resolved_side = "FLAT"

            filled = row["filled"]
            direction = str(row["direction"] or "")
            order_price = _safe_float(row["order_price"], 0.0) or 0.0
            shares = _safe_float(row["shares"], 0.0) or 0.0
            pnl = None
            won = None

            if filled == 1 and direction in {"UP", "DOWN"} and resolved_side in {"UP", "DOWN"}:
                won = 1 if direction == resolved_side else 0
                pnl = round(shares * (1.0 - order_price), 6) if won else round(-shares * order_price, 6)
            elif filled == 0:
                won = 0
                pnl = 0.0

            self.db.upsert_window(
                {
                    "window_start_ts": row["window_start_ts"],
                    "window_end_ts": row["window_end_ts"],
                    "slug": row["slug"],
                    "decision_ts": row["decision_ts"],
                    "direction": row["direction"],
                    "open_price": row["open_price"],
                    "current_price": row["current_price"],
                    "delta": row["delta"],
                    "token_id": row["token_id"],
                    "best_bid": row["best_bid"],
                    "best_ask": row["best_ask"],
                    "order_price": row["order_price"],
                    "trade_size_usd": row["trade_size_usd"],
                    "shares": row["shares"],
                    "order_id": row["order_id"],
                    "order_status": row["order_status"],
                    "filled": row["filled"],
                    "reason": row["reason"],
                    "resolved_side": resolved_side,
                    "won": won,
                    "pnl_usd": pnl,
                }
            )

    async def _get_open_and_current_price(
        self,
        *,
        window_start_ts: int,
        http: MarketHttpClient,
    ) -> tuple[float | None, float | None]:
        open_price = await self.cache.open_price_for_window(window_start_ts)
        latest = await self.cache.latest()
        current_price = latest[1] if latest else None

        # Fallback to Binance REST if WS data is sparse.
        if open_price is None:
            kline = await http.fetch_binance_window_open_close(window_start_ts)
            if kline:
                open_price = kline[0]
        if current_price is None:
            current_price = await http.fetch_binance_spot()

        return open_price, current_price

    async def _reconcile_live_order(
        self,
        *,
        order_id: str,
        requested_shares: float,
        window_end_ts: int,
    ) -> tuple[str, int | None, float | None, str | None]:
        cancel_at = window_end_ts - self.cfg.cancel_seconds_before_close
        wait_seconds = max(0.0, cancel_at - time.time())
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        before_cancel = self.clob.get_order_state(order_id)
        if before_cancel and before_cancel.fully_filled:
            return "live_filled", 1, before_cancel.size_matched or requested_shares, None
        if before_cancel and before_cancel.partially_filled and before_cancel.is_cancelled:
            return "live_partial_fill_cancelled", 1, before_cancel.size_matched, None
        if before_cancel and before_cancel.is_cancelled and before_cancel.size_matched <= 0:
            return "live_cancelled_unfilled", 0, 0.0, None

        cancelled = self.clob.cancel_order(order_id)
        after_cancel = self.clob.get_order_state(order_id)
        final_state = after_cancel or before_cancel

        if final_state:
            if final_state.fully_filled:
                return "live_filled", 1, final_state.size_matched or requested_shares, None
            if final_state.partially_filled:
                return (
                    "live_partial_fill_cancelled" if cancelled or final_state.is_cancelled else "live_partial_fill_open",
                    1,
                    final_state.size_matched,
                    None,
                )
            if final_state.is_cancelled:
                return "live_cancelled_unfilled", 0, 0.0, None
            if final_state.is_live:
                return "live_cancel_unknown", None, None, f"status={final_state.normalized_status}"

        if cancelled:
            return "live_cancelled_unfilled", 0, 0.0, None
        return "live_cancel_unknown", None, None, "order_status_unavailable"

    async def _process_window(self, *, window_start_ts: int, http: MarketHttpClient) -> dict[str, Any]:
        window_end_ts = window_start_ts + WINDOW_SECONDS
        slug = market_slug_for_window(window_start_ts)

        if self.db.window_exists(window_start_ts):
            return {"window_start_ts": window_start_ts, "status": "skip_already_processed"}

        # Resolve prior windows first so daily PnL gate uses latest info.
        await self._resolve_unsettled(http, through_window_start=window_start_ts - WINDOW_SECONDS)

        today_pnl = self.db.today_realized_pnl()
        probe_mode = self._probe_mode(today_pnl=today_pnl)
        hard_daily_loss_hit = today_pnl <= -abs(self.cfg.daily_loss_limit_usd)
        if hard_daily_loss_hit and probe_mode is None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "order_status": "skip_daily_loss_limit",
                "reason": f"today_pnl={today_pnl:.4f} limit={self.cfg.daily_loss_limit_usd:.2f}",
            }
            self.db.upsert_window(row)
            return {"window_start_ts": window_start_ts, "status": row["order_status"], "today_pnl": today_pnl}
        effective_min_delta = float(probe_mode["min_delta"]) if probe_mode else float(self.cfg.min_delta)
        effective_max_abs_delta = (
            _safe_float(probe_mode.get("max_abs_delta"), None)
            if probe_mode
            else self.cfg.max_abs_delta
        )
        probe_reason = probe_mode.get("reason") if probe_mode else None

        open_price, current_price = await self._get_open_and_current_price(window_start_ts=window_start_ts, http=http)
        if not open_price or not current_price:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "open_price": open_price,
                "current_price": current_price,
                "order_status": "skip_missing_price",
            }
            self.db.upsert_window(row)
            return {"window_start_ts": window_start_ts, "status": row["order_status"]}

        direction, delta = direction_from_prices(open_price, current_price, effective_min_delta)
        if direction is None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_delta_too_small",
                "reason": _join_reasons(
                    probe_reason,
                    f"abs(delta)={abs(delta):.6f} < {effective_min_delta:.6f}",
                ),
            }
            self.db.upsert_window(row)
            return {
                "window_start_ts": window_start_ts,
                "status": row["order_status"],
                "delta": delta,
                "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
            }

        if effective_max_abs_delta is not None and abs(delta) > effective_max_abs_delta:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_delta_too_large",
                "reason": _join_reasons(
                    probe_reason,
                    f"abs(delta)={abs(delta):.6f} > {effective_max_abs_delta:.6f}",
                ),
            }
            self.db.upsert_window(row)
            return {
                "window_start_ts": window_start_ts,
                "status": row["order_status"],
                "delta": delta,
                "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
            }

        market = await http.fetch_market_by_slug(slug)
        if not market:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_market_not_found",
            }
            self.db.upsert_window(row)
            return {"window_start_ts": window_start_ts, "status": row["order_status"]}

        token_id = choose_token_id_for_direction(market, direction)
        if not token_id:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_token_not_found",
            }
            self.db.upsert_window(row)
            return {"window_start_ts": window_start_ts, "status": row["order_status"]}

        book = await http.fetch_book(token_id)
        if not book:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "order_status": "skip_no_book",
            }
            self.db.upsert_window(row)
            return {"window_start_ts": window_start_ts, "status": row["order_status"]}

        recent_regime = self._recent_direction_regime()
        quote_ticks = effective_quote_ticks(self.cfg, direction, recent_regime=recent_regime)
        if probe_mode:
            quote_ticks = min(int(quote_ticks), int(probe_mode["quote_ticks"]))
        regime_reason = None
        if recent_regime and recent_regime.get("triggered"):
            favored = recent_regime.get("favored_direction") or "n/a"
            weaker = recent_regime.get("weaker_direction") or "n/a"
            regime_reason = (
                f"recent_regime favored={favored} weaker={weaker} "
                f"{direction}_quote_ticks={quote_ticks}"
            )
        mode_max_buy_price = (
            float(probe_mode["up_max_buy_price"])
            if probe_mode and direction == "UP"
            else float(probe_mode["down_max_buy_price"])
            if probe_mode and direction == "DOWN"
            else effective_max_buy_price(self.cfg, direction)
        )

        best_bid, best_ask = http.top_of_book(book)
        order_price = choose_maker_buy_price(
            best_bid=best_bid,
            best_ask=best_ask,
            max_price=mode_max_buy_price,
            min_price=self.cfg.min_buy_price,
            tick_size=self.cfg.tick_size,
            aggression_ticks=quote_ticks,
        )
        if order_price is None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_status": "skip_price_outside_guardrails",
                "reason": _join_reasons(probe_reason, regime_reason),
            }
            self.db.upsert_window(row)
            return {
                "window_start_ts": window_start_ts,
                "status": row["order_status"],
                "quote_ticks": quote_ticks,
                "regime_triggered": bool(recent_regime and recent_regime.get("triggered")),
                "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
            }

        size_usd = calc_trade_size_usd(self.cfg.bankroll_usd, self.cfg.risk_fraction, self.cfg.max_trade_usd)
        if size_usd < self.cfg.min_trade_usd:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_price": order_price,
                "trade_size_usd": size_usd,
                "order_status": "skip_size_too_small",
            }
            self.db.upsert_window(row)
            return {"window_start_ts": window_start_ts, "status": row["order_status"]}

        shares = _round_up(size_usd / max(order_price, 1e-6), 2)
        _btc5_min_shares = max(CLOB_HARD_MIN_SHARES, float(os.environ.get("JJ_POLY_MIN_ORDER_SHARES", "5.0")))
        required_shares = clob_min_order_size(order_price, min_shares=_btc5_min_shares)
        if shares < required_shares:
            bumped_usd = round(required_shares * order_price, 2)
            if bumped_usd > self.cfg.max_trade_usd * 2:
                logger.info(
                    "SKIP: %.2f shares / $%.2f below live min %.2f shares / $%.2f, bump $%.2f > 2x max",
                    shares,
                    shares * order_price,
                    required_shares,
                    CLOB_HARD_MIN_NOTIONAL_USD,
                    bumped_usd,
                )
                row = {
                    "window_start_ts": window_start_ts,
                    "window_end_ts": window_end_ts,
                    "slug": slug,
                    "direction": direction,
                    "open_price": open_price,
                    "current_price": current_price,
                    "delta": delta,
                    "token_id": token_id,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "order_price": order_price,
                    "trade_size_usd": size_usd,
                    "order_status": "skip_below_min_shares",
                }
                self.db.upsert_window(row)
                return {"window_start_ts": window_start_ts, "status": row["order_status"]}
            shares = required_shares
            size_usd = bumped_usd
        order_id = None
        filled: int | None = None
        order_status = "order_error"
        reason: str | None = regime_reason
        reason = _join_reasons(probe_reason, reason)
        executed_shares = shares

        if self.cfg.paper_trading:
            order_id = f"paper-{window_start_ts}"
            filled = 1 if deterministic_fill(window_start_ts, self.cfg.paper_fill_probability) else 0
            order_status = "paper_filled" if filled == 1 else "paper_unfilled"
            if filled == 0:
                executed_shares = 0.0
        else:
            try:
                placement = self.clob.place_post_only_buy(token_id=token_id, price=order_price, shares=shares)
                order_id = placement.order_id
                order_status = f"live_{placement.status}" if placement.status else "live_order_placed"
                reason = _join_reasons(reason, placement.error_msg or regime_reason)
            except Exception as exc:
                logger.error("Live order placement failed: %s", exc)
                placement = PlacementResult(
                    order_id=None,
                    success=False,
                    status="order_failed",
                    error_msg=str(exc),
                )
                order_status = "live_order_failed"
                reason = _join_reasons(reason, str(exc))

            if order_id and placement.success:
                order_status, filled, executed_shares, reconcile_reason = await self._reconcile_live_order(
                    order_id=order_id,
                    requested_shares=shares,
                    window_end_ts=window_end_ts,
                )
                reason = _join_reasons(reason, reconcile_reason)
            else:
                filled = 0
                executed_shares = 0.0

        row = {
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "slug": slug,
            "direction": direction,
            "open_price": open_price,
            "current_price": current_price,
            "delta": delta,
            "token_id": token_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "order_price": order_price,
            "trade_size_usd": round((executed_shares or 0.0) * order_price, 4) if filled == 1 else 0.0,
            "shares": executed_shares if filled == 1 else 0.0,
            "order_id": order_id,
            "filled": filled,
            "order_status": order_status,
            "reason": reason,
        }
        self.db.upsert_window(row)
        return {
            "window_start_ts": window_start_ts,
            "status": order_status,
            "direction": direction,
            "delta": delta,
            "order_id": order_id,
            "price": order_price,
            "size_usd": row["trade_size_usd"],
            "filled": filled,
            "reason": reason,
            "quote_ticks": quote_ticks,
            "regime_triggered": bool(recent_regime and recent_regime.get("triggered")),
            "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
        }

    async def run_windows(self, *, count: int, continuous: bool) -> None:
        stop_event = asyncio.Event()
        feed = BinanceTradeFeed(self.cfg.binance_ws_url, self.cache)
        feed_task = asyncio.create_task(feed.run(stop_event))

        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            http = MarketHttpClient(self.cfg, session)
            executed = 0

            try:
                while True:
                    now = time.time()
                    ws = current_window_start(now)
                    decision_ts = ws + WINDOW_SECONDS - self.cfg.entry_seconds_before_close
                    if now > decision_ts + 1:
                        ws += WINDOW_SECONDS
                        decision_ts = ws + WINDOW_SECONDS - self.cfg.entry_seconds_before_close
                    wait = max(0.0, decision_ts - time.time())
                    if wait > 0:
                        logger.info("Waiting %.1fs until decision time for window %s", wait, ws)
                        await asyncio.sleep(wait)

                    summary = await self._process_window(window_start_ts=ws, http=http)
                    logger.info("Window result: %s", json.dumps(summary, sort_keys=True))
                    executed += 1

                    if not continuous and executed >= count:
                        break
            finally:
                stop_event.set()
                await asyncio.sleep(0)
                feed_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await feed_task

        # Resolve the most recent completed window if possible.
        async with aiohttp.ClientSession(timeout=timeout) as session:
            http = MarketHttpClient(self.cfg, session)
            await self._resolve_unsettled(http, through_window_start=current_window_start() - WINDOW_SECONDS)

    async def run_now(self) -> dict[str, Any]:
        """Execute the decision pipeline immediately for the current 5m window."""
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            http = MarketHttpClient(self.cfg, session)
            ws = current_window_start()
            return await self._process_window(window_start_ts=ws, http=http)

    def print_status(self) -> None:
        status = self.db.status_summary()
        print(
            json.dumps(
                {
                    "paper_trading": self.cfg.paper_trading,
                    "db_path": str(self.cfg.db_path),
                    **status,
                },
                indent=2,
                sort_keys=True,
            )
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BTC 5m maker bot (Instance 2)")
    parser.add_argument("--continuous", action="store_true", help="Run indefinitely")
    parser.add_argument("--windows", type=int, default=1, help="Number of windows to process in non-continuous mode")
    parser.add_argument("--status", action="store_true", help="Print status summary from SQLite DB and exit")
    parser.add_argument("--paper", action="store_true", help="Force paper mode for this run")
    parser.add_argument("--live", action="store_true", help="Force live mode for this run")
    parser.add_argument("--run-now", action="store_true", help="Run immediately on current window (no T-10 wait)")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logs")
    return parser


async def _run(args: argparse.Namespace) -> None:
    cfg = MakerConfig()
    if args.paper and args.live:
        raise SystemExit("Use only one of --paper or --live")
    if args.paper:
        cfg.paper_trading = True
    if args.live:
        cfg.paper_trading = False

    if cfg.entry_seconds_before_close <= cfg.cancel_seconds_before_close:
        raise SystemExit("BTC5_ENTRY_SECONDS_BEFORE_CLOSE must be greater than BTC5_CANCEL_SECONDS_BEFORE_CLOSE")

    bot = BTC5MinMakerBot(cfg)
    if args.status:
        bot.print_status()
        return

    if args.run_now:
        summary = await bot.run_now()
        logger.info("Immediate run result: %s", json.dumps(summary, sort_keys=True))
        bot.print_status()
        return

    if not args.continuous and args.windows < 1:
        raise SystemExit("--windows must be >= 1")

    logger.info(
        "Starting BTC5 maker | mode=%s | bankroll=%.2f | risk_fraction=%.4f | max_trade=%.2f | max_abs_delta=%s | up_max=%.2f | down_max=%.2f | improve_ticks=%d | regime_skew=%s | probe_daily_loss=%s | probe_recent=%s",
        "paper" if cfg.paper_trading else "live",
        cfg.bankroll_usd,
        cfg.risk_fraction,
        cfg.max_trade_usd,
        "disabled" if cfg.max_abs_delta is None else f"{cfg.max_abs_delta:.6f}",
        effective_max_buy_price(cfg, "UP"),
        effective_max_buy_price(cfg, "DOWN"),
        max(0, int(cfg.maker_improve_ticks)),
        "enabled" if cfg.enable_recent_regime_skew else "disabled",
        "enabled" if cfg.enable_probe_after_daily_loss else "disabled",
        "enabled" if cfg.enable_probe_after_recent_loss else "disabled",
    )
    await bot.run_windows(count=args.windows, continuous=args.continuous)
    bot.print_status()


def main() -> None:
    args = build_arg_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
