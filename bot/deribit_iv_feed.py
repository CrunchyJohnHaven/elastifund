#!/usr/bin/env python3
"""Deribit options IV / skew / vol-index feed for BTC signal enrichment.

Connects to Deribit's WebSocket API v2 and streams:
  - BTC implied-volatility index (``deribit_volatility_index``)
  - Mark-price + greeks for front-month BTC options
  - Ticker snapshots for put/call skew computation

The feed exposes a thread-safe snapshot via :meth:`DeribitIVFeed.snapshot`
that BTC5Maker (or any consumer) can poll each candle cycle.

Auth is optional — public channels stream without credentials.  When
``DERIBIT_CLIENT_ID`` and ``DERIBIT_CLIENT_SECRET`` are present in the
environment the feed authenticates to unlock private rate-limit tiers
(the free tier is plenty for our ~12 reads/minute cadence, but auth
lets us add private channels later without reconnecting).

Env vars consumed
-----------------
DERIBIT_CLIENT_ID       : API key id  (optional for public-only mode)
DERIBIT_CLIENT_SECRET   : API secret  (optional for public-only mode)
DERIBIT_WS_URL          : WebSocket endpoint (default wss://www.deribit.com/ws/api/v2)
DERIBIT_TESTNET         : set "true" to target test.deribit.com
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any

try:
    import websockets
    from websockets.exceptions import WebSocketException
except ImportError:  # pragma: no cover
    websockets = None
    WebSocketException = Exception  # type: ignore[assignment,misc]

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger("JJ.deribit_iv")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_WS_URL = "wss://www.deribit.com/ws/api/v2"
_TESTNET_WS_URL = "wss://test.deribit.com/ws/api/v2"


def _ws_url() -> str:
    if os.environ.get("DERIBIT_TESTNET", "").lower() in {"1", "true", "yes"}:
        return _TESTNET_WS_URL
    return os.environ.get("DERIBIT_WS_URL", _DEFAULT_WS_URL)


# Channels we subscribe to (all public — no auth required).
# deribit_volatility_index.{index_name} — DVOL real-time
# markprice.options.{index_name}        — bulk mark-price for all options
# deribit_price_index.{index_name}      — live BTC index price
# Deribit uses index names like "btc_usd", not bare currencies.
_VOLINDEX_CHANNEL = "deribit_volatility_index.btc_usd"
_MARKPRICE_CHANNEL = "markprice.options.btc_usd"
_PRICE_INDEX_CHANNEL = "deribit_price_index.btc_usd"

# How many front-month strikes we track for skew (put + call at each).
_STRIKE_DEPTH = 6

# Reconnect back-off.
_RECONNECT_BASE_S = 2.0
_RECONNECT_MAX_S = 60.0
_HEARTBEAT_INTERVAL_S = 15.0

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class OptionSnapshot:
    """Single option mark-price + greeks snapshot."""
    instrument: str
    mark_iv: float
    underlying_price: float
    strike: float
    option_type: str  # "call" or "put"
    delta: float
    gamma: float
    vega: float
    theta: float
    timestamp_ms: int


@dataclass
class IVSnapshot:
    """Thread-safe aggregate snapshot polled by consumers."""
    dvol: float | None = None
    dvol_ts: float = 0.0

    atm_iv_call: float | None = None
    atm_iv_put: float | None = None
    put_call_skew: float | None = None  # ATM put IV - ATM call IV

    front_puts: list[OptionSnapshot] = field(default_factory=list)
    front_calls: list[OptionSnapshot] = field(default_factory=list)

    underlying_price: float | None = None
    last_update_ts: float = 0.0
    connected: bool = False
    authenticated: bool = False
    error: str | None = None

    # 25-delta risk reversal: IV(25d put) - IV(25d call)
    rr_25d: float | None = None
    # Butterfly: 0.5*(IV(25d put)+IV(25d call)) - ATM IV
    bf_25d: float | None = None

    def age_seconds(self) -> float:
        if self.last_update_ts == 0.0:
            return float("inf")
        return time.time() - self.last_update_ts

    def is_stale(self, max_age_s: float = 30.0) -> bool:
        return self.age_seconds() > max_age_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "dvol": self.dvol,
            "dvol_ts": self.dvol_ts,
            "atm_iv_call": self.atm_iv_call,
            "atm_iv_put": self.atm_iv_put,
            "put_call_skew": self.put_call_skew,
            "rr_25d": self.rr_25d,
            "bf_25d": self.bf_25d,
            "underlying_price": self.underlying_price,
            "last_update_ts": self.last_update_ts,
            "connected": self.connected,
            "authenticated": self.authenticated,
            "age_s": round(self.age_seconds(), 1),
            "error": self.error,
            "front_puts_count": len(self.front_puts),
            "front_calls_count": len(self.front_calls),
        }


# ---------------------------------------------------------------------------
# Feed implementation
# ---------------------------------------------------------------------------

class DeribitIVFeed:
    """Async WebSocket feed that maintains a live IVSnapshot.

    Usage::

        feed = DeribitIVFeed()
        asyncio.create_task(feed.run_forever())
        # ... later, from any coroutine or thread ...
        snap = feed.snapshot()
        if snap.dvol and not snap.is_stale():
            print(f"BTC DVOL={snap.dvol:.1f}  skew={snap.put_call_skew}")
    """

    def __init__(self) -> None:
        self._snap = IVSnapshot()
        self._lock = threading.Lock()
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._running = False
        self._ws: Any = None

        # Option chain state keyed by instrument name.
        self._option_marks: dict[str, OptionSnapshot] = {}

    # -- public API --

    def snapshot(self) -> IVSnapshot:
        """Return a copy of the current snapshot (thread-safe)."""
        with self._lock:
            # Shallow copy is fine — lists are replaced, not mutated.
            import copy
            return copy.copy(self._snap)

    async def run_forever(self) -> None:
        """Connect, subscribe, and reconnect on failures."""
        self._running = True
        backoff = _RECONNECT_BASE_S
        while self._running:
            try:
                await self._connect_and_stream()
                backoff = _RECONNECT_BASE_S  # reset on clean disconnect
            except Exception as exc:
                logger.warning("deribit ws error: %s — reconnecting in %.0fs", exc, backoff)
                with self._lock:
                    self._snap.connected = False
                    self._snap.error = str(exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_S)

    def stop(self) -> None:
        self._running = False

    # -- internals --

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send(self, ws: Any, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and await the response."""
        msg_id = self._next_id()
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params:
            payload["params"] = params
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await ws.send(json.dumps(payload))
        try:
            deadline = time.monotonic() + 10.0
            while not fut.done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                self._handle_message(raw)
            return fut.result()
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise

    async def _authenticate(self, ws: Any) -> bool:
        """Authenticate if credentials available.  Returns True on success."""
        client_id = os.environ.get("DERIBIT_CLIENT_ID", "")
        client_secret = os.environ.get("DERIBIT_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            logger.info("deribit: no credentials, running public-only")
            return False
        try:
            result = await self._send(ws, "public/auth", {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            })
            if result and "access_token" in result:
                logger.info("deribit: authenticated (scope=%s)", result.get("scope", "?"))
                return True
            logger.warning("deribit: auth response missing access_token: %s", result)
            return False
        except Exception as exc:
            logger.warning("deribit: auth failed: %s — continuing public-only", exc)
            return False

    async def _subscribe(self, ws: Any) -> None:
        """Subscribe to public channels."""
        channels = [_VOLINDEX_CHANNEL, _MARKPRICE_CHANNEL, _PRICE_INDEX_CHANNEL]
        await self._send(ws, "public/subscribe", {"channels": channels})
        logger.info("deribit: subscribed to %s", channels)

    async def _connect_and_stream(self) -> None:
        url = _ws_url()
        logger.info("deribit: connecting to %s", url)
        async with websockets.connect(url, ping_interval=_HEARTBEAT_INTERVAL_S) as ws:
            self._ws = ws
            with self._lock:
                self._snap.connected = True
                self._snap.error = None

            authed = await self._authenticate(ws)
            with self._lock:
                self._snap.authenticated = authed

            await self._subscribe(ws)

            async for raw in ws:
                self._handle_message(raw)

    def _handle_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        # JSON-RPC response to a request we sent.
        if "id" in msg and msg["id"] in self._pending:
            fut = self._pending.pop(msg["id"])
            if not fut.done():
                if "error" in msg:
                    fut.set_exception(RuntimeError(msg["error"]))
                else:
                    fut.set_result(msg.get("result"))
            return

        # Subscription notification.
        if msg.get("method") == "subscription":
            params = msg.get("params", {})
            channel = params.get("channel", "")
            data = params.get("data", {})
            if channel == _VOLINDEX_CHANNEL:
                self._on_volindex(data)
            elif channel == _MARKPRICE_CHANNEL:
                self._on_markprice(data)
            elif channel == _PRICE_INDEX_CHANNEL:
                self._on_price_index(data)

    def _on_volindex(self, data: Any) -> None:
        """Handle DVOL tick."""
        if not isinstance(data, dict):
            return
        dvol = data.get("volatility")
        ts = data.get("timestamp", 0)
        if dvol is None:
            return
        with self._lock:
            self._snap.dvol = float(dvol)
            self._snap.dvol_ts = float(ts) / 1000.0 if ts > 1e12 else float(ts)
            self._snap.last_update_ts = time.time()
        logger.debug("dvol=%.2f", dvol)

    def _on_markprice(self, data: Any) -> None:
        """Handle bulk mark-price update for all BTC options.

        The ``markprice.options.btc`` channel delivers a list of
        mark-price records for every live BTC option instrument.
        Each record: [instrument_name, mark_price, iv, ...]
        Format per Deribit docs (list of lists):
          [[instrument, mark_price, iv], ...]
        Or sometimes a flat dict — handle both.
        """
        now = time.time()

        if isinstance(data, list):
            for row in data:
                self._ingest_markprice_row(row)
        elif isinstance(data, dict):
            self._ingest_markprice_row(data)

        self._recompute_skew()
        with self._lock:
            self._snap.last_update_ts = now

    def _on_price_index(self, data: Any) -> None:
        """Handle live BTC index-price updates."""
        if not isinstance(data, dict):
            return
        price = _to_float(data.get("price"))
        if price is None:
            return
        with self._lock:
            self._snap.underlying_price = price
            self._snap.last_update_ts = time.time()

    def _ingest_markprice_row(self, row: Any) -> None:
        """Parse a single mark-price row into the option chain."""
        # Deribit markprice.options sends lists:
        #   [instrument, mark_price, iv]
        # or sometimes richer dicts with greeks.
        if isinstance(row, (list, tuple)) and len(row) >= 3:
            instrument = str(row[0])
            mark_iv = _to_float(row[2])
            if mark_iv is None:
                return
            parsed = _parse_instrument(instrument)
            if parsed is None:
                return
            strike, opt_type = parsed
            self._option_marks[instrument] = OptionSnapshot(
                instrument=instrument,
                mark_iv=mark_iv,
                underlying_price=0.0,  # filled by ticker if available
                strike=strike,
                option_type=opt_type,
                delta=0.0, gamma=0.0, vega=0.0, theta=0.0,
                timestamp_ms=int(time.time() * 1000),
            )
        elif isinstance(row, dict):
            instrument = row.get("instrument_name", "")
            mark_iv = _to_float(row.get("mark_iv") or row.get("iv"))
            if not instrument or mark_iv is None:
                return
            parsed = _parse_instrument(instrument)
            if parsed is None:
                return
            strike, opt_type = parsed
            self._option_marks[instrument] = OptionSnapshot(
                instrument=instrument,
                mark_iv=mark_iv,
                underlying_price=_to_float(row.get("underlying_price")) or 0.0,
                strike=strike,
                option_type=opt_type,
                delta=_to_float(row.get("delta")) or 0.0,
                gamma=_to_float(row.get("gamma")) or 0.0,
                vega=_to_float(row.get("vega")) or 0.0,
                theta=_to_float(row.get("theta")) or 0.0,
                timestamp_ms=int(row.get("timestamp", time.time() * 1000)),
            )

    def _recompute_skew(self) -> None:
        """Recompute ATM IV, put/call skew, 25d risk reversal from option chain."""
        if not self._option_marks:
            return

        # Find underlying price from any recent option with it populated.
        underlying = 0.0
        for opt in self._option_marks.values():
            if opt.underlying_price > 0:
                underlying = opt.underlying_price
                break

        if underlying <= 0:
            # Fall back to the strike nearest to the median of all strikes.
            strikes = sorted(set(o.strike for o in self._option_marks.values()))
            if strikes:
                underlying = strikes[len(strikes) // 2]
            else:
                return

        # Find nearest front-month expiry (shortest-dated instruments).
        # Deribit instrument format: BTC-28MAR26-90000-C
        expiries: dict[str, list[OptionSnapshot]] = {}
        for opt in self._option_marks.values():
            parts = opt.instrument.split("-")
            if len(parts) >= 4:
                exp = parts[1]  # e.g. "28MAR26"
                expiries.setdefault(exp, []).append(opt)

        if not expiries:
            return

        # Pick the expiry with the most instruments (likely front-month).
        front_exp = max(expiries, key=lambda e: len(expiries[e]))
        front_options = expiries[front_exp]

        # Split into puts and calls.
        puts = sorted([o for o in front_options if o.option_type == "put"],
                      key=lambda o: abs(o.strike - underlying))
        calls = sorted([o for o in front_options if o.option_type == "call"],
                       key=lambda o: abs(o.strike - underlying))

        # ATM = nearest strike to underlying.
        atm_call_iv = calls[0].mark_iv if calls else None
        atm_put_iv = puts[0].mark_iv if puts else None

        skew = None
        if atm_put_iv is not None and atm_call_iv is not None:
            skew = atm_put_iv - atm_call_iv

        # 25-delta risk reversal approximation:
        # Use options roughly 25% OTM.  For a quick proxy, pick the
        # strike ~3-5 away from ATM in the sorted list.
        rr_25d = None
        bf_25d = None
        if len(puts) >= 4 and len(calls) >= 4:
            put_25d_iv = puts[3].mark_iv   # OTM put
            call_25d_iv = calls[3].mark_iv  # OTM call
            rr_25d = put_25d_iv - call_25d_iv
            if atm_call_iv is not None:
                bf_25d = 0.5 * (put_25d_iv + call_25d_iv) - atm_call_iv

        with self._lock:
            self._snap.atm_iv_call = atm_call_iv
            self._snap.atm_iv_put = atm_put_iv
            self._snap.put_call_skew = skew
            self._snap.rr_25d = rr_25d
            self._snap.bf_25d = bf_25d
            self._snap.underlying_price = underlying
            self._snap.front_puts = puts[:_STRIKE_DEPTH]
            self._snap.front_calls = calls[:_STRIKE_DEPTH]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_instrument(name: str) -> tuple[float, str] | None:
    """Parse 'BTC-28MAR26-90000-C' into (90000.0, 'call')."""
    parts = name.split("-")
    if len(parts) < 4:
        return None
    try:
        strike = float(parts[2])
    except (ValueError, IndexError):
        return None
    opt_char = parts[3].upper()
    if opt_char == "C":
        return strike, "call"
    elif opt_char == "P":
        return strike, "put"
    return None


# ---------------------------------------------------------------------------
# Standalone test mode
# ---------------------------------------------------------------------------

async def _main() -> None:
    """Quick diagnostic — connect, stream for 60s, print snapshots."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    feed = DeribitIVFeed()
    task = asyncio.create_task(feed.run_forever())

    for i in range(12):
        await asyncio.sleep(5)
        snap = feed.snapshot()
        logger.info(
            "[%02d] dvol=%s  atm_call=%s  atm_put=%s  skew=%s  rr25=%s  "
            "underlying=%s  connected=%s  auth=%s  age=%.1fs  puts=%d  calls=%d",
            i,
            f"{snap.dvol:.1f}" if snap.dvol else "—",
            f"{snap.atm_iv_call:.1f}" if snap.atm_iv_call else "—",
            f"{snap.atm_iv_put:.1f}" if snap.atm_iv_put else "—",
            f"{snap.put_call_skew:.2f}" if snap.put_call_skew is not None else "—",
            f"{snap.rr_25d:.2f}" if snap.rr_25d is not None else "—",
            f"{snap.underlying_price:.0f}" if snap.underlying_price else "—",
            snap.connected,
            snap.authenticated,
            snap.age_seconds(),
            len(snap.front_puts),
            len(snap.front_calls),
        )

    feed.stop()
    task.cancel()
    logger.info("diagnostic done")


if __name__ == "__main__":
    asyncio.run(_main())
