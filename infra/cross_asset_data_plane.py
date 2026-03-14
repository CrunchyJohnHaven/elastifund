"""Canonical multi-venue data plane for cross-asset fast-market research."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

import httpx

try:  # pragma: no cover - optional runtime dependency
    import websockets
except Exception:  # pragma: no cover - optional runtime dependency
    websockets = None

try:  # pragma: no cover - optional runtime dependency
    import pandas as pd
except Exception:  # pragma: no cover - optional runtime dependency
    pd = None

try:  # pragma: no cover - optional runtime dependency
    import boto3
except Exception:  # pragma: no cover - optional runtime dependency
    boto3 = None


LOGGER = logging.getLogger("JJ.cross_asset_data_plane")

MARKET_ENVELOPE_SCHEMA = "market_envelope.v1"
VENUE_HEALTH_SCHEMA = "venue_health.v1"
CANDLE_ANCHOR_SCHEMA = "candle_anchor.v1"
DATA_PLANE_HEALTH_SCHEMA = "data_plane_health.v1"

DEFAULT_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
DEFAULT_ANCHOR_TIMEFRAMES = (60, 300, 900)

BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
}

COINBASE_PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
}

DERIBIT_INDEX_NAMES = {
    "BTC": "btc_usd",
    "ETH": "eth_usd",
}

VENUE_SUPPORTED_ASSETS = {
    "binance": DEFAULT_ASSETS,
    "coinbase": DEFAULT_ASSETS,
    "polymarket": DEFAULT_ASSETS,
    "deribit": tuple(DERIBIT_INDEX_NAMES.keys()),
}

POLY_ASSET_MARKERS: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin", "btc"),
    "ETH": ("ethereum", "eth"),
    "SOL": ("solana", "sol"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("doge", "dogecoin"),
}

_WS_READ_TIMEOUT_SECONDS = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(ts: float | None = None) -> str:
    if ts is None:
        return utc_now().isoformat()
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def utc_ms_now() -> int:
    return int(time.time() * 1000)


def parse_iso_to_ms(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_json(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _asset_from_symbol(symbol: str) -> str | None:
    upper = str(symbol or "").upper()
    for asset in DEFAULT_ASSETS:
        if upper.startswith(asset):
            return asset
    return None


def _compute_event_id(
    *,
    venue: str,
    venue_stream: str,
    asset: str,
    event_ts_ms: int,
    sequence: int | None,
    symbol: str,
    event_type: str,
    price: float | None,
    size: float | None,
) -> str:
    base = "|".join(
        [
            venue,
            venue_stream,
            asset,
            str(event_ts_ms),
            str(sequence) if sequence is not None else "",
            symbol,
            event_type,
            f"{price:.12f}" if isinstance(price, float) else "",
            f"{size:.12f}" if isinstance(size, float) else "",
        ]
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()  # noqa: S324
    return f"{venue}:{asset}:{digest}"


def build_market_envelope(
    *,
    venue: str,
    venue_stream: str,
    asset: str,
    symbol: str,
    event_type: str,
    event_ts_ms: int | None = None,
    sequence: int | None = None,
    price: float | None = None,
    size: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    mid: float | None = None,
    metadata: dict[str, Any] | None = None,
    raw: Any = None,
) -> dict[str, Any]:
    event_ts = int(event_ts_ms or utc_ms_now())
    final_mid = mid
    if final_mid is None and isinstance(bid, float) and isinstance(ask, float):
        final_mid = (bid + ask) / 2.0
    if final_mid is None and isinstance(price, float):
        final_mid = price
    observed_at = utc_iso()
    event_at = utc_iso(event_ts / 1000.0)
    event_id = _compute_event_id(
        venue=venue,
        venue_stream=venue_stream,
        asset=asset,
        event_ts_ms=event_ts,
        sequence=sequence,
        symbol=symbol,
        event_type=event_type,
        price=price,
        size=size,
    )
    return {
        "schema_version": MARKET_ENVELOPE_SCHEMA,
        "event_id": event_id,
        "observed_at": observed_at,
        "event_at": event_at,
        "event_ts_ms": event_ts,
        "venue": venue,
        "venue_stream": venue_stream,
        "asset": asset,
        "symbol": symbol,
        "event_type": event_type,
        "price": price,
        "size": size,
        "bid": bid,
        "ask": ask,
        "mid": final_mid,
        "sequence": sequence,
        "metadata": metadata or {},
        "raw": raw if raw is not None else {},
    }


def _parse_poly_asset(*, question: str, slug: str, tags: list[str]) -> str | None:
    haystack = " ".join([question, slug, " ".join(tags)]).lower()
    for asset, markers in POLY_ASSET_MARKERS.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", haystack) for marker in markers):
            return asset
    return None


def _parse_poly_timeframe(*, question: str, slug: str) -> str | None:
    haystack = f"{question} {slug}".lower()
    patterns = (
        (r"\b5m\b|\b5-minute\b|\b5 minute\b|updown-5m", "5m"),
        (r"\b15m\b|\b15-minute\b|\b15 minute\b|updown-15m", "15m"),
        (r"\b1h\b|\b1-hour\b|\b1 hour\b", "1h"),
        (r"\b4h\b|\b4-hour\b|\b4 hour\b|updown-4h", "4h"),
    )
    for pattern, label in patterns:
        if re.search(pattern, haystack):
            return label
    return None


def _parse_poly_token_ids(raw: Any) -> tuple[str | None, str | None]:
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
    if not isinstance(data, list) or len(data) < 2:
        return None, None
    return str(data[0]), str(data[1])


@dataclass
class CrossAssetDataPlaneConfig:
    db_path: Path = Path("state/cross_asset_ticks.db")
    parquet_root: Path = Path("state/cross_asset_ticks_parquet")
    health_latest_path: Path = Path("reports/data_plane_health/latest.json")
    assets: tuple[str, ...] = DEFAULT_ASSETS
    anchor_timeframes_seconds: tuple[int, ...] = DEFAULT_ANCHOR_TIMEFRAMES
    health_emit_seconds: int = 15
    max_staleness_seconds: int = 60
    polymarket_poll_seconds: int = 15
    rest_poll_seconds: int = 5
    websocket_backoff_seconds: float = 2.0
    enable_kinesis: bool = False
    kinesis_stream_name: str = "elastifund-cross-asset-envelope"
    kinesis_region: str = "us-east-1"

    @classmethod
    def from_env(cls) -> "CrossAssetDataPlaneConfig":
        db_path = Path(os.environ.get("JJ_CROSS_ASSET_DB_PATH", "state/cross_asset_ticks.db"))
        parquet_root = Path(os.environ.get("JJ_CROSS_ASSET_PARQUET_ROOT", "state/cross_asset_ticks_parquet"))
        health_latest_path = Path(os.environ.get("JJ_DATA_PLANE_HEALTH_PATH", "reports/data_plane_health/latest.json"))
        assets_raw = os.environ.get("JJ_CROSS_ASSET_UNIVERSE", ",".join(DEFAULT_ASSETS))
        assets = tuple(item.strip().upper() for item in assets_raw.split(",") if item.strip())
        if not assets:
            assets = DEFAULT_ASSETS
        return cls(
            db_path=db_path,
            parquet_root=parquet_root,
            health_latest_path=health_latest_path,
            assets=assets,
            anchor_timeframes_seconds=tuple(
                int(item.strip())
                for item in os.environ.get(
                    "JJ_CROSS_ASSET_ANCHOR_WINDOWS_SECONDS",
                    ",".join(str(value) for value in DEFAULT_ANCHOR_TIMEFRAMES),
                ).split(",")
                if item.strip()
            )
            or DEFAULT_ANCHOR_TIMEFRAMES,
            health_emit_seconds=max(5, int(os.environ.get("JJ_DATA_PLANE_HEALTH_EMIT_SECONDS", "15"))),
            max_staleness_seconds=max(10, int(os.environ.get("JJ_DATA_PLANE_MAX_STALENESS_SECONDS", "60"))),
            polymarket_poll_seconds=max(5, int(os.environ.get("JJ_POLYMARKET_POLL_SECONDS", "15"))),
            rest_poll_seconds=max(2, int(os.environ.get("JJ_REST_FALLBACK_POLL_SECONDS", "5"))),
            websocket_backoff_seconds=max(0.5, float(os.environ.get("JJ_WS_BACKOFF_SECONDS", "2.0"))),
            enable_kinesis=str(os.environ.get("JJ_DATA_PLANE_KINESIS_ENABLED", "")).strip().lower()
            in {"1", "true", "yes", "on"},
            kinesis_stream_name=os.environ.get("JJ_DATA_PLANE_KINESIS_STREAM", "elastifund-cross-asset-envelope"),
            kinesis_region=os.environ.get("AWS_REGION", "us-east-1"),
        )


@dataclass
class FeedState:
    venue: str
    asset: str
    venue_stream: str
    last_event_ts_ms: int = 0
    last_observed_ts_ms: int = 0
    last_sequence: int | None = None
    sequence_gap_count: int = 0
    reconnect_count: int = 0
    error_count: int = 0
    events_ingested: int = 0


class KinesisPublisher:
    """Best-effort Kinesis publisher for mirrored envelopes."""

    def __init__(
        self,
        *,
        enabled: bool,
        stream_name: str,
        region_name: str,
        logger: logging.Logger,
    ) -> None:
        self.enabled = bool(enabled)
        self.stream_name = stream_name
        self.region_name = region_name
        self.logger = logger
        self._client: Any = None
        self._init_error: str | None = None

        if not self.enabled:
            return
        if boto3 is None:
            self.enabled = False
            self._init_error = "boto3_unavailable"
            self.logger.warning("kinesis_disabled reason=%s", self._init_error)
            return
        try:  # pragma: no cover - depends on AWS auth at runtime
            self._client = boto3.client("kinesis", region_name=region_name)
        except Exception as exc:  # pragma: no cover - depends on AWS auth at runtime
            self.enabled = False
            self._init_error = str(exc)
            self.logger.warning("kinesis_disabled reason=%s", self._init_error)

    def publish(self, envelope: dict[str, Any]) -> tuple[bool, str]:
        if not self.enabled or self._client is None:
            return False, self._init_error or "kinesis_disabled"
        try:  # pragma: no cover - depends on AWS auth at runtime
            self._client.put_record(
                StreamName=self.stream_name,
                Data=(_to_json(envelope) + "\n").encode("utf-8"),
                PartitionKey=str(envelope.get("asset") or "UNKNOWN"),
            )
            return True, "published"
        except Exception as exc:  # pragma: no cover - depends on AWS auth at runtime
            return False, str(exc)


class CrossAssetDataPlane:
    """SQLite-first canonical cross-asset event store with health tracking."""

    def __init__(
        self,
        config: CrossAssetDataPlaneConfig | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config or CrossAssetDataPlaneConfig.from_env()
        self.logger = logger or LOGGER
        self.db_path = self.config.db_path
        self.parquet_root = self.config.parquet_root
        self.health_latest_path = self.config.health_latest_path
        self.health_dir = self.health_latest_path.parent
        self._states: dict[tuple[str, str, str], FeedState] = {}
        self._lock = asyncio.Lock()
        self.kinesis = KinesisPublisher(
            enabled=self.config.enable_kinesis,
            stream_name=self.config.kinesis_stream_name,
            region_name=self.config.kinesis_region,
            logger=self.logger,
        )
        self._ensure_dirs()
        self.initialize_db()

    def _ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.parquet_root.mkdir(parents=True, exist_ok=True)
        self.health_dir.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def initialize_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_envelopes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    schema_version TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    event_at TEXT NOT NULL,
                    event_ts_ms INTEGER NOT NULL,
                    venue TEXT NOT NULL,
                    venue_stream TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    price REAL,
                    size REAL,
                    bid REAL,
                    ask REAL,
                    mid REAL,
                    sequence INTEGER,
                    sequence_gap INTEGER NOT NULL DEFAULT 0,
                    staleness_ms INTEGER,
                    metadata_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    inserted_at_ts INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_market_envelopes_venue_asset_ts
                ON market_envelopes(venue, asset, event_ts_ms);

                CREATE INDEX IF NOT EXISTS idx_market_envelopes_event_ts
                ON market_envelopes(event_ts_ms);

                CREATE TABLE IF NOT EXISTS candle_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    timeframe_seconds INTEGER NOT NULL,
                    window_start_ts INTEGER NOT NULL,
                    window_end_ts INTEGER NOT NULL,
                    anchor_price REAL NOT NULL,
                    source_event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_candle_anchors_asset_window
                ON candle_anchors(asset, timeframe_seconds, window_start_ts);

                CREATE TABLE IF NOT EXISTS venue_health_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema_version TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    freshness_status TEXT NOT NULL,
                    staleness_seconds REAL,
                    sequence_gap_count INTEGER NOT NULL,
                    reconnect_count INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    events_ingested INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS parquet_compaction_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hour_start_ts INTEGER NOT NULL,
                    hour_end_ts INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    parquet_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _state_for(self, *, venue: str, asset: str, venue_stream: str) -> FeedState:
        key = (venue, asset, venue_stream)
        state = self._states.get(key)
        if state is None:
            state = FeedState(venue=venue, asset=asset, venue_stream=venue_stream)
            self._states[key] = state
        return state

    def record_reconnect(self, venue: str, *, asset: str | None = None, venue_stream: str = "default") -> None:
        targets = [asset] if asset else list(self.config.assets)
        for target_asset in targets:
            state = self._state_for(venue=venue, asset=target_asset, venue_stream=venue_stream)
            state.reconnect_count += 1

    def record_error(self, venue: str, *, asset: str | None = None, venue_stream: str = "default") -> None:
        targets = [asset] if asset else list(self.config.assets)
        for target_asset in targets:
            state = self._state_for(venue=venue, asset=target_asset, venue_stream=venue_stream)
            state.error_count += 1

    async def ingest_envelope(self, envelope: dict[str, Any]) -> bool:
        async with self._lock:
            return self._ingest_envelope_locked(envelope)

    def _ingest_envelope_locked(self, envelope: dict[str, Any]) -> bool:
        if str(envelope.get("schema_version") or "") != MARKET_ENVELOPE_SCHEMA:
            raise ValueError("envelope schema_version must be market_envelope.v1")
        venue = str(envelope.get("venue") or "").strip().lower()
        asset = str(envelope.get("asset") or "").strip().upper()
        venue_stream = str(envelope.get("venue_stream") or "default")
        symbol = str(envelope.get("symbol") or "")
        event_id = str(envelope.get("event_id") or "")
        if not venue or not asset or not symbol or not event_id:
            raise ValueError("envelope must include venue, asset, symbol, and event_id")
        if asset not in self.config.assets:
            return False

        event_ts_ms = _safe_int(envelope.get("event_ts_ms"))
        if event_ts_ms is None:
            event_ts_ms = parse_iso_to_ms(str(envelope.get("event_at") or ""))
        if event_ts_ms is None:
            event_ts_ms = utc_ms_now()
        now_ms = utc_ms_now()
        staleness_ms = max(0, now_ms - int(event_ts_ms))

        sequence = _safe_int(envelope.get("sequence"))
        sequence_gap = False
        state = self._state_for(venue=venue, asset=asset, venue_stream=venue_stream)
        if sequence is not None:
            if state.last_sequence is not None and sequence > state.last_sequence + 1:
                sequence_gap = True
                state.sequence_gap_count += sequence - state.last_sequence - 1
            if state.last_sequence is None or sequence > state.last_sequence:
                state.last_sequence = sequence

        row = (
            event_id,
            MARKET_ENVELOPE_SCHEMA,
            str(envelope.get("observed_at") or utc_iso()),
            str(envelope.get("event_at") or utc_iso(event_ts_ms / 1000.0)),
            int(event_ts_ms),
            venue,
            venue_stream,
            asset,
            symbol,
            str(envelope.get("event_type") or "unknown"),
            _safe_float(envelope.get("price")),
            _safe_float(envelope.get("size")),
            _safe_float(envelope.get("bid")),
            _safe_float(envelope.get("ask")),
            _safe_float(envelope.get("mid")),
            sequence,
            1 if sequence_gap else 0,
            staleness_ms,
            _to_json(envelope.get("metadata") or {}),
            _to_json(envelope.get("raw") or {}),
            int(time.time()),
        )
        inserted = False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO market_envelopes (
                    event_id, schema_version, observed_at, event_at, event_ts_ms,
                    venue, venue_stream, asset, symbol, event_type,
                    price, size, bid, ask, mid, sequence, sequence_gap,
                    staleness_ms, metadata_json, raw_json, inserted_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            inserted = (cursor.rowcount or 0) > 0
            if inserted:
                price = _safe_float(envelope.get("price"))
                mid = _safe_float(envelope.get("mid"))
                anchor_price = mid if isinstance(mid, float) else price
                if isinstance(anchor_price, float):
                    self._insert_candle_anchors(
                        conn=conn,
                        asset=asset,
                        event_ts_ms=int(event_ts_ms),
                        anchor_price=anchor_price,
                        source_event_id=event_id,
                    )

        if not inserted:
            return False

        state.events_ingested += 1
        state.last_event_ts_ms = max(state.last_event_ts_ms, int(event_ts_ms))
        state.last_observed_ts_ms = now_ms

        published, publish_reason = self.kinesis.publish(envelope)
        if self.kinesis.enabled and not published:
            state.error_count += 1
            self.logger.warning("kinesis_publish_failed event_id=%s reason=%s", event_id, publish_reason)
        return True

    def _insert_candle_anchors(
        self,
        *,
        conn: sqlite3.Connection,
        asset: str,
        event_ts_ms: int,
        anchor_price: float,
        source_event_id: str,
    ) -> None:
        event_ts = int(event_ts_ms // 1000)
        created_at = utc_iso()
        for timeframe_seconds in self.config.anchor_timeframes_seconds:
            window_start = event_ts - (event_ts % int(timeframe_seconds))
            window_end = window_start + int(timeframe_seconds)
            anchor_id = f"{asset}:{timeframe_seconds}:{window_start}"
            conn.execute(
                """
                INSERT OR IGNORE INTO candle_anchors (
                    anchor_id, schema_version, asset, timeframe_seconds, window_start_ts,
                    window_end_ts, anchor_price, source_event_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anchor_id,
                    CANDLE_ANCHOR_SCHEMA,
                    asset,
                    int(timeframe_seconds),
                    window_start,
                    window_end,
                    float(anchor_price),
                    source_event_id,
                    created_at,
                ),
            )

    def _aggregate_health_rows(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = defaultdict(dict)
        now_ms = utc_ms_now()
        for venue, supported_assets in VENUE_SUPPORTED_ASSETS.items():
            if venue == "deribit":
                assets = tuple(asset for asset in supported_assets if asset in self.config.assets)
            else:
                assets = tuple(asset for asset in self.config.assets if asset in supported_assets)
            for asset in assets:
                states = [
                    value
                    for (state_venue, state_asset, _stream), value in self._states.items()
                    if state_venue == venue and state_asset == asset
                ]
                if not states:
                    rows[venue][asset] = {
                        "freshness_status": "no_data",
                        "last_event_at": None,
                        "staleness_seconds": None,
                        "sequence_gap_count": 0,
                        "reconnect_count": 0,
                        "error_count": 0,
                        "events_ingested": 0,
                    }
                    continue

                last_event_ts_ms = max(state.last_event_ts_ms for state in states)
                staleness_seconds = max(0.0, (now_ms - last_event_ts_ms) / 1000.0)
                freshness_status = "fresh" if staleness_seconds <= self.config.max_staleness_seconds else "stale"
                rows[venue][asset] = {
                    "freshness_status": freshness_status,
                    "last_event_at": utc_iso(last_event_ts_ms / 1000.0),
                    "staleness_seconds": round(staleness_seconds, 3),
                    "sequence_gap_count": int(sum(state.sequence_gap_count for state in states)),
                    "reconnect_count": int(sum(state.reconnect_count for state in states)),
                    "error_count": int(sum(state.error_count for state in states)),
                    "events_ingested": int(sum(state.events_ingested for state in states)),
                }
        return rows

    def build_health_payload(self) -> dict[str, Any]:
        generated_at = utc_iso()
        venue_rows = self._aggregate_health_rows()

        global_asset_status: dict[str, dict[str, Any]] = {}
        fresh_assets = 0
        stale_assets: list[str] = []
        no_data_assets: list[str] = []

        for asset in self.config.assets:
            candidates: list[dict[str, Any]] = []
            for venue in venue_rows:
                if asset in venue_rows[venue]:
                    row = dict(venue_rows[venue][asset])
                    row["venue"] = venue
                    candidates.append(row)

            if not candidates:
                no_data_assets.append(asset)
                global_asset_status[asset] = {
                    "freshness_status": "no_data",
                    "best_venue": None,
                    "staleness_seconds": None,
                }
                continue

            ranked = sorted(
                candidates,
                key=lambda item: (
                    0 if item["freshness_status"] == "fresh" else 1,
                    float(item["staleness_seconds"] if item["staleness_seconds"] is not None else 1_000_000.0),
                ),
            )
            best = ranked[0]
            best_status = str(best.get("freshness_status") or "no_data")
            best_venue = best.get("venue") if best_status != "no_data" else None
            global_asset_status[asset] = {
                "freshness_status": best_status,
                "best_venue": best_venue,
                "staleness_seconds": best["staleness_seconds"],
            }
            if best_status == "fresh":
                fresh_assets += 1
            elif best_status == "stale":
                stale_assets.append(asset)
            else:
                no_data_assets.append(asset)

        fresh_coverage_ratio = fresh_assets / max(1, len(self.config.assets))
        polymarket_rows = venue_rows.get("polymarket", {})
        fresh_polymarket_assets: list[str] = []
        polymarket_altcoin_assets_with_data: list[str] = []
        best_venue_by_asset: dict[str, str | None] = {}

        for asset in self.config.assets:
            best_venue_by_asset[asset] = global_asset_status.get(asset, {}).get("best_venue")
            row = polymarket_rows.get(asset)
            if not isinstance(row, dict):
                continue
            if str(row.get("freshness_status") or "").lower() == "fresh":
                fresh_polymarket_assets.append(asset)
            has_data = bool(row.get("last_event_at")) or int(_safe_int(row.get("events_ingested"), 0) or 0) > 0
            if asset != "BTC" and has_data:
                polymarket_altcoin_assets_with_data.append(asset)

        payload = {
            "schema_version": DATA_PLANE_HEALTH_SCHEMA,
            "generated_at": generated_at,
            "source_of_truth": str(self.db_path),
            "freshness_target_seconds": int(self.config.max_staleness_seconds),
            "schemas": {
                "market_envelope": MARKET_ENVELOPE_SCHEMA,
                "venue_health": VENUE_HEALTH_SCHEMA,
                "candle_anchor": CANDLE_ANCHOR_SCHEMA,
            },
            "assets": list(self.config.assets),
            "venues": {
                venue: {
                    "schema_version": VENUE_HEALTH_SCHEMA,
                    "assets": venue_rows.get(venue, {}),
                }
                for venue in ("binance", "coinbase", "polymarket", "deribit")
            },
            "overall": {
                "fresh_asset_count": fresh_assets,
                "fresh_asset_coverage_ratio": round(fresh_coverage_ratio, 6),
                "stale_assets": stale_assets,
                "no_data_assets": no_data_assets,
                "global_asset_status": global_asset_status,
                "best_venue_by_asset": best_venue_by_asset,
                "fresh_polymarket_assets": sorted(fresh_polymarket_assets),
                "has_polymarket_altcoin_data": bool(polymarket_altcoin_assets_with_data),
                "kinesis_enabled": bool(self.kinesis.enabled),
            },
        }
        return payload

    def write_health_report(self) -> tuple[Path, Path, dict[str, Any]]:
        payload = self.build_health_payload()
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        timestamped_path = self.health_dir / f"data_plane_health_{stamp}.json"
        latest_path = self.health_latest_path
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        timestamped_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._persist_health_rows(payload)
        return latest_path, timestamped_path, payload

    def _persist_health_rows(self, payload: dict[str, Any]) -> None:
        generated_at = str(payload.get("generated_at") or utc_iso())
        rows: list[tuple[Any, ...]] = []
        venues = payload.get("venues") or {}
        for venue, venue_payload in venues.items():
            assets = (venue_payload or {}).get("assets") or {}
            for asset, row in assets.items():
                rows.append(
                    (
                        VENUE_HEALTH_SCHEMA,
                        generated_at,
                        str(venue),
                        str(asset),
                        str((row or {}).get("freshness_status") or "unknown"),
                        _safe_float((row or {}).get("staleness_seconds")),
                        int(_safe_int((row or {}).get("sequence_gap_count"), 0) or 0),
                        int(_safe_int((row or {}).get("reconnect_count"), 0) or 0),
                        int(_safe_int((row or {}).get("error_count"), 0) or 0),
                        int(_safe_int((row or {}).get("events_ingested"), 0) or 0),
                    )
                )
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO venue_health_samples (
                    schema_version, generated_at, venue, asset, freshness_status, staleness_seconds,
                    sequence_gap_count, reconnect_count, error_count, events_ingested
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def compact_completed_hours(self, *, now_ts: int | None = None) -> dict[str, Any]:
        now_seconds = int(now_ts or time.time())
        current_hour_start = now_seconds - (now_seconds % 3600)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(hour_start_ts) AS max_hour_start FROM parquet_compaction_runs "
                "WHERE status IN ('compacted', 'empty', 'skipped_no_engine')"
            ).fetchone()
        last_hour_start = _safe_int(row["max_hour_start"] if row else None, None)
        next_hour_start = current_hour_start - 3600 if last_hour_start is None else int(last_hour_start) + 3600

        if next_hour_start > current_hour_start - 3600:
            return {"status": "up_to_date", "hours_compacted": 0, "rows_compacted": 0}

        if pd is None:
            return {
                "status": "skipped_no_parquet_engine",
                "hours_compacted": 0,
                "rows_compacted": 0,
                "reason": "pandas_or_parquet_engine_missing",
            }

        hours_compacted = 0
        rows_compacted = 0
        details: list[dict[str, Any]] = []
        for hour_start in range(next_hour_start, current_hour_start, 3600):
            hour_end = hour_start + 3600
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        event_id, schema_version, observed_at, event_at, event_ts_ms, venue, venue_stream, asset,
                        symbol, event_type, price, size, bid, ask, mid, sequence, sequence_gap,
                        staleness_ms, metadata_json, raw_json, inserted_at_ts
                    FROM market_envelopes
                    WHERE event_ts_ms >= ? AND event_ts_ms < ?
                    ORDER BY event_ts_ms ASC, id ASC
                    """,
                    (hour_start * 1000, hour_end * 1000),
                ).fetchall()

            row_count = len(rows)
            status = "empty"
            parquet_path: str | None = None
            error: str | None = None
            if row_count > 0:
                dt = datetime.fromtimestamp(hour_start, tz=timezone.utc)
                output_dir = (
                    self.parquet_root
                    / f"year={dt.year:04d}"
                    / f"month={dt.month:02d}"
                    / f"day={dt.day:02d}"
                    / f"hour={dt.hour:02d}"
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / "market_envelopes.parquet"
                try:
                    dataframe = pd.DataFrame([dict(row) for row in rows])
                    dataframe.to_parquet(output_path, index=False)
                    parquet_path = str(output_path)
                    status = "compacted"
                    hours_compacted += 1
                    rows_compacted += row_count
                except Exception as exc:  # pragma: no cover - depends on parquet engine
                    error = str(exc)
                    lowered = error.lower()
                    if "usable engine" in lowered or "pyarrow" in lowered or "fastparquet" in lowered:
                        status = "skipped_no_engine"
                    else:
                        status = "failed"
                    self.logger.warning("parquet_compaction_failed hour_start=%s err=%s", hour_start, error)
            else:
                hours_compacted += 1

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO parquet_compaction_runs (
                        hour_start_ts, hour_end_ts, status, row_count, parquet_path, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hour_start,
                        hour_end,
                        status,
                        row_count,
                        parquet_path,
                        error,
                        utc_iso(),
                    ),
                )
            details.append(
                {
                    "hour_start_ts": hour_start,
                    "hour_end_ts": hour_end,
                    "status": status,
                    "row_count": row_count,
                    "parquet_path": parquet_path,
                    "error": error,
                }
            )

        overall_status = (
            "compacted"
            if all(item["status"] in {"compacted", "empty", "skipped_no_engine"} for item in details)
            else "partial"
        )
        return {
            "status": overall_status,
            "hours_compacted": hours_compacted,
            "rows_compacted": rows_compacted,
            "details": details,
        }

    def snapshot_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            envelopes = conn.execute("SELECT COUNT(*) AS count FROM market_envelopes").fetchone()
            anchors = conn.execute("SELECT COUNT(*) AS count FROM candle_anchors").fetchone()
        return {
            "market_envelopes": int(envelopes["count"] if envelopes else 0),
            "candle_anchors": int(anchors["count"] if anchors else 0),
        }


class BinanceAdapter:
    venue = "binance"
    ws_url = "wss://stream.binance.com:9443/stream"
    ticker_url = "https://api.binance.com/api/v3/ticker/bookTicker"

    def __init__(self, assets: tuple[str, ...]):
        self.assets = tuple(asset for asset in assets if asset in BINANCE_SYMBOLS)

    def _streams(self) -> list[str]:
        return [f"{BINANCE_SYMBOLS[asset].lower()}@trade" for asset in self.assets]

    def _build_ws_url(self) -> str:
        streams = "/".join(self._streams())
        return f"{self.ws_url}?streams={streams}"

    def parse_message(self, payload: Any) -> list[dict[str, Any]]:
        message = payload
        if isinstance(payload, str):
            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                return []

        data = message.get("data") if isinstance(message, dict) and "data" in message else message
        if not isinstance(data, dict):
            return []
        if str(data.get("e") or "").lower() != "trade":
            return []

        symbol = str(data.get("s") or "")
        asset = _asset_from_symbol(symbol)
        if asset is None or asset not in self.assets:
            return []

        price = _safe_float(data.get("p"))
        size = _safe_float(data.get("q"))
        sequence = _safe_int(data.get("t"))
        event_ts_ms = _safe_int(data.get("T")) or _safe_int(data.get("E")) or utc_ms_now()
        stream = str(message.get("stream") or f"{symbol.lower()}@trade")

        envelope = build_market_envelope(
            venue=self.venue,
            venue_stream=stream,
            asset=asset,
            symbol=symbol,
            event_type="trade",
            event_ts_ms=event_ts_ms,
            sequence=sequence,
            price=price,
            size=size,
            metadata={"is_buyer_maker": bool(data.get("m"))},
            raw=message,
        )
        return [envelope]

    async def poll_once(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        envelopes: list[dict[str, Any]] = []
        for asset in self.assets:
            symbol = BINANCE_SYMBOLS[asset]
            response = await client.get(self.ticker_url, params={"symbol": symbol})
            response.raise_for_status()
            payload = response.json()
            bid = _safe_float(payload.get("bidPrice"))
            ask = _safe_float(payload.get("askPrice"))
            sequence = _safe_int(payload.get("u"))
            event_ts_ms = utc_ms_now()
            envelopes.append(
                build_market_envelope(
                    venue=self.venue,
                    venue_stream="rest.bookTicker",
                    asset=asset,
                    symbol=symbol,
                    event_type="book_ticker",
                    event_ts_ms=event_ts_ms,
                    sequence=sequence,
                    bid=bid,
                    ask=ask,
                    mid=((bid + ask) / 2.0) if isinstance(bid, float) and isinstance(ask, float) else None,
                    metadata={"transport": "rest"},
                    raw=payload,
                )
            )
        return envelopes

    async def stream_loop(self, *, plane: CrossAssetDataPlane, stop_event: asyncio.Event) -> None:
        backoff = plane.config.websocket_backoff_seconds
        while not stop_event.is_set():
            if websockets is None:
                plane.record_error(self.venue, venue_stream="trade")
                await asyncio.sleep(max(plane.config.rest_poll_seconds, 2))
                continue
            try:  # pragma: no cover - network integration path
                async with websockets.connect(
                    self._build_ws_url(),
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**22,
                ) as ws:
                    plane.record_reconnect(self.venue, venue_stream="trade")
                    backoff = plane.config.websocket_backoff_seconds
                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=_WS_READ_TIMEOUT_SECONDS)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"op": "ping"}))
                            continue
                        for envelope in self.parse_message(raw):
                            await plane.ingest_envelope(envelope)
            except Exception as exc:  # pragma: no cover - network integration path
                plane.record_error(self.venue, venue_stream="trade")
                LOGGER.warning("binance_ws_error err=%s reconnect_in=%.2fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)


class CoinbaseAdapter:
    venue = "coinbase"
    ws_url = "wss://advanced-trade-ws.coinbase.com"
    ticker_url_template = "https://api.exchange.coinbase.com/products/{product}/ticker"

    def __init__(self, assets: tuple[str, ...]):
        self.assets = tuple(asset for asset in assets if asset in COINBASE_PRODUCTS)

    def subscribe_payload(self) -> dict[str, Any]:
        return {
            "type": "subscribe",
            "channel": "ticker",
            "product_ids": [COINBASE_PRODUCTS[asset] for asset in self.assets],
        }

    def parse_message(self, payload: Any) -> list[dict[str, Any]]:
        message = payload
        if isinstance(payload, str):
            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                return []
        if not isinstance(message, dict):
            return []

        envelopes: list[dict[str, Any]] = []
        message_type = str(message.get("type") or "")

        if message_type == "ticker":
            product_id = str(message.get("product_id") or "")
            asset = _asset_from_symbol(product_id.replace("-", ""))
            if asset and asset in self.assets:
                bid = _safe_float(message.get("best_bid"))
                ask = _safe_float(message.get("best_ask"))
                price = _safe_float(message.get("price"))
                sequence = _safe_int(message.get("sequence"))
                event_ts_ms = parse_iso_to_ms(str(message.get("time") or "")) or utc_ms_now()
                envelopes.append(
                    build_market_envelope(
                        venue=self.venue,
                        venue_stream="ws.ticker",
                        asset=asset,
                        symbol=product_id,
                        event_type="ticker",
                        event_ts_ms=event_ts_ms,
                        sequence=sequence,
                        price=price,
                        bid=bid,
                        ask=ask,
                        metadata={"transport": "ws"},
                        raw=message,
                    )
                )
            return envelopes

        channel = str(message.get("channel") or "")
        if channel != "ticker":
            return []
        events = message.get("events")
        if not isinstance(events, list):
            return []
        for event in events:
            if not isinstance(event, dict):
                continue
            tickers = event.get("tickers")
            if not isinstance(tickers, list):
                continue
            for ticker in tickers:
                if not isinstance(ticker, dict):
                    continue
                product_id = str(ticker.get("product_id") or "")
                asset = _asset_from_symbol(product_id.replace("-", ""))
                if asset is None or asset not in self.assets:
                    continue
                bid = _safe_float(ticker.get("best_bid"))
                ask = _safe_float(ticker.get("best_ask"))
                price = _safe_float(ticker.get("price"))
                sequence = _safe_int(ticker.get("sequence_num")) or _safe_int(ticker.get("sequence"))
                event_ts_ms = parse_iso_to_ms(str(ticker.get("time") or event.get("time") or "")) or utc_ms_now()
                envelopes.append(
                    build_market_envelope(
                        venue=self.venue,
                        venue_stream="ws.advanced_trade.ticker",
                        asset=asset,
                        symbol=product_id,
                        event_type="ticker",
                        event_ts_ms=event_ts_ms,
                        sequence=sequence,
                        price=price,
                        bid=bid,
                        ask=ask,
                        metadata={"transport": "ws"},
                        raw=message,
                    )
                )
        return envelopes

    async def poll_once(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        envelopes: list[dict[str, Any]] = []
        for asset in self.assets:
            product = COINBASE_PRODUCTS[asset]
            response = await client.get(self.ticker_url_template.format(product=product))
            response.raise_for_status()
            payload = response.json()
            bid = _safe_float(payload.get("bid"))
            ask = _safe_float(payload.get("ask"))
            price = _safe_float(payload.get("price"))
            sequence = _safe_int(payload.get("trade_id"))
            event_ts_ms = parse_iso_to_ms(str(payload.get("time") or "")) or utc_ms_now()
            envelopes.append(
                build_market_envelope(
                    venue=self.venue,
                    venue_stream="rest.ticker",
                    asset=asset,
                    symbol=product,
                    event_type="ticker",
                    event_ts_ms=event_ts_ms,
                    sequence=sequence,
                    price=price,
                    bid=bid,
                    ask=ask,
                    metadata={"transport": "rest"},
                    raw=payload,
                )
            )
        return envelopes

    async def stream_loop(self, *, plane: CrossAssetDataPlane, stop_event: asyncio.Event) -> None:
        backoff = plane.config.websocket_backoff_seconds
        while not stop_event.is_set():
            if websockets is None:
                plane.record_error(self.venue, venue_stream="ticker")
                await asyncio.sleep(max(plane.config.rest_poll_seconds, 2))
                continue
            try:  # pragma: no cover - network integration path
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**22,
                ) as ws:
                    await ws.send(json.dumps(self.subscribe_payload()))
                    plane.record_reconnect(self.venue, venue_stream="ticker")
                    backoff = plane.config.websocket_backoff_seconds
                    while not stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=_WS_READ_TIMEOUT_SECONDS)
                        for envelope in self.parse_message(raw):
                            await plane.ingest_envelope(envelope)
            except Exception as exc:  # pragma: no cover - network integration path
                plane.record_error(self.venue, venue_stream="ticker")
                LOGGER.warning("coinbase_ws_error err=%s reconnect_in=%.2fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)


class DeribitAdapter:
    venue = "deribit"
    ws_url = "wss://www.deribit.com/ws/api/v2"
    rest_url = "https://www.deribit.com/api/v2/public/get_index_price"

    def __init__(self, assets: tuple[str, ...]):
        self.assets = tuple(asset for asset in assets if asset in DERIBIT_INDEX_NAMES)

    def _channels(self) -> list[str]:
        return [f"deribit_price_index.{DERIBIT_INDEX_NAMES[asset]}" for asset in self.assets]

    def subscribe_payload(self) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "public/subscribe",
            "params": {"channels": self._channels()},
        }

    def parse_message(self, payload: Any) -> list[dict[str, Any]]:
        message = payload
        if isinstance(payload, str):
            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                return []
        if not isinstance(message, dict):
            return []
        params = message.get("params")
        if not isinstance(params, dict):
            return []
        channel = str(params.get("channel") or "")
        if not channel.startswith("deribit_price_index."):
            return []
        data = params.get("data")
        if not isinstance(data, dict):
            return []

        asset = None
        for candidate, index_name in DERIBIT_INDEX_NAMES.items():
            if index_name in channel:
                asset = candidate
                break
        if asset is None or asset not in self.assets:
            return []

        price = _safe_float(data.get("price")) or _safe_float(data.get("index_price")) or _safe_float(data.get("last_price"))
        bid = _safe_float(data.get("best_bid_price"))
        ask = _safe_float(data.get("best_ask_price"))
        event_ts_ms = _safe_int(data.get("timestamp")) or utc_ms_now()
        sequence = _safe_int(data.get("sequence")) or _safe_int(data.get("change_id"))
        envelope = build_market_envelope(
            venue=self.venue,
            venue_stream=channel,
            asset=asset,
            symbol=f"{asset}-USD",
            event_type="index",
            event_ts_ms=event_ts_ms,
            sequence=sequence,
            price=price,
            bid=bid,
            ask=ask,
            metadata={"transport": "ws"},
            raw=message,
        )
        return [envelope]

    async def poll_once(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        envelopes: list[dict[str, Any]] = []
        for asset in self.assets:
            index_name = DERIBIT_INDEX_NAMES[asset]
            response = await client.get(self.rest_url, params={"index_name": index_name})
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict):
                continue
            price = _safe_float(result.get("index_price"))
            event_ts_ms = utc_ms_now()
            envelopes.append(
                build_market_envelope(
                    venue=self.venue,
                    venue_stream="rest.index_price",
                    asset=asset,
                    symbol=f"{asset}-USD",
                    event_type="index",
                    event_ts_ms=event_ts_ms,
                    price=price,
                    metadata={"transport": "rest"},
                    raw=payload,
                )
            )
        return envelopes

    async def stream_loop(self, *, plane: CrossAssetDataPlane, stop_event: asyncio.Event) -> None:
        backoff = plane.config.websocket_backoff_seconds
        while not stop_event.is_set():
            if websockets is None:
                plane.record_error(self.venue, venue_stream="index")
                await asyncio.sleep(max(plane.config.rest_poll_seconds, 3))
                continue
            try:  # pragma: no cover - network integration path
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**22,
                ) as ws:
                    await ws.send(json.dumps(self.subscribe_payload()))
                    plane.record_reconnect(self.venue, venue_stream="index")
                    backoff = plane.config.websocket_backoff_seconds
                    while not stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=_WS_READ_TIMEOUT_SECONDS)
                        for envelope in self.parse_message(raw):
                            await plane.ingest_envelope(envelope)
            except Exception as exc:  # pragma: no cover - network integration path
                plane.record_error(self.venue, venue_stream="index")
                LOGGER.warning("deribit_ws_error err=%s reconnect_in=%.2fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 45.0)


class PolymarketAdapter:
    venue = "polymarket"
    gamma_url = "https://gamma-api.polymarket.com/markets"
    book_url = "https://clob.polymarket.com/book"

    def __init__(self, assets: tuple[str, ...]):
        self.assets = tuple(assets)

    async def _fetch_markets(self, client: httpx.AsyncClient, *, limit: int = 500) -> list[dict[str, Any]]:
        response = await client.get(self.gamma_url, params={"closed": "false", "active": "true", "limit": str(limit)})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    async def _fetch_book(self, client: httpx.AsyncClient, token_id: str) -> dict[str, Any] | None:
        try:
            response = await client.get(self.book_url, params={"token_id": token_id})
            response.raise_for_status()
        except Exception:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    async def poll_once(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        markets = await self._fetch_markets(client)
        envelopes: list[dict[str, Any]] = []

        by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for market in markets:
            question = str(market.get("question") or "")
            slug = str(market.get("slug") or "")
            tags = [str(item).lower() for item in (market.get("tags") or []) if isinstance(item, str)]
            asset = _parse_poly_asset(question=question, slug=slug, tags=tags)
            if asset is None or asset not in self.assets:
                continue
            if bool(market.get("closed")) or not bool(market.get("active", True)):
                continue
            timeframe = _parse_poly_timeframe(question=question, slug=slug)
            candidate = dict(market)
            candidate["_asset"] = asset
            candidate["_timeframe"] = timeframe
            by_asset[asset].append(candidate)

        selected_markets: list[dict[str, Any]] = []
        for asset in self.assets:
            rows = by_asset.get(asset) or []
            rows.sort(
                key=lambda row: (
                    0 if row.get("_timeframe") in {"5m", "15m"} else 1,
                    -float(_safe_float(row.get("liquidityClob") or row.get("liquidity"), 0.0) or 0.0),
                )
            )
            selected_markets.extend(rows[:3])

        for market in selected_markets:
            asset = str(market.get("_asset") or "")
            question = str(market.get("question") or "")
            slug = str(market.get("slug") or "")
            timeframe = market.get("_timeframe")
            condition_id = str(market.get("conditionId") or market.get("id") or "")
            yes_price = None
            no_price = None
            raw_outcome_prices = market.get("outcomePrices")
            if isinstance(raw_outcome_prices, str):
                try:
                    raw_outcome_prices = json.loads(raw_outcome_prices)
                except json.JSONDecodeError:
                    raw_outcome_prices = []
            if isinstance(raw_outcome_prices, list) and len(raw_outcome_prices) >= 2:
                yes_price = _safe_float(raw_outcome_prices[0])
                no_price = _safe_float(raw_outcome_prices[1])

            best_bid = _safe_float(market.get("bestBid"))
            best_ask = _safe_float(market.get("bestAsk"))
            yes_token_id, _no_token_id = _parse_poly_token_ids(market.get("clobTokenIds"))
            book = await self._fetch_book(client, yes_token_id) if yes_token_id else None

            if (best_bid is None or best_ask is None) and isinstance(book, dict):
                bids = list(book.get("bids") or [])
                asks = list(book.get("asks") or [])
                if best_bid is None and bids:
                    best_bid = _safe_float((bids[0] or {}).get("price"))
                if best_ask is None and asks:
                    best_ask = _safe_float((asks[0] or {}).get("price"))

            event_ts_ms = utc_ms_now()
            envelopes.append(
                build_market_envelope(
                    venue=self.venue,
                    venue_stream="rest.gamma_clob",
                    asset=asset,
                    symbol=condition_id or slug,
                    event_type="market_quote",
                    event_ts_ms=event_ts_ms,
                    price=yes_price,
                    bid=best_bid,
                    ask=best_ask,
                    mid=((best_bid + best_ask) / 2.0) if isinstance(best_bid, float) and isinstance(best_ask, float) else yes_price,
                    metadata={
                        "condition_id": condition_id,
                        "slug": slug,
                        "timeframe": timeframe,
                        "question": question,
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "source": "gamma+clob",
                    },
                    raw={"market": market, "book": book},
                )
            )

        return envelopes

    async def poll_loop(self, *, plane: CrossAssetDataPlane, stop_event: asyncio.Event) -> None:
        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while not stop_event.is_set():
                try:  # pragma: no cover - network integration path
                    envelopes = await self.poll_once(client)
                    for envelope in envelopes:
                        await plane.ingest_envelope(envelope)
                except Exception as exc:  # pragma: no cover - network integration path
                    plane.record_error(self.venue, venue_stream="gamma_clob")
                    LOGGER.warning("polymarket_poll_error err=%s", exc)
                await asyncio.sleep(plane.config.polymarket_poll_seconds)


class CrossAssetDataPlaneRunner:
    """Runtime orchestrator for websocket + polling adapters."""

    def __init__(
        self,
        *,
        plane: CrossAssetDataPlane,
        enable_websockets: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.plane = plane
        self.enable_websockets = bool(enable_websockets)
        self.logger = logger or LOGGER
        self.binance = BinanceAdapter(plane.config.assets)
        self.coinbase = CoinbaseAdapter(plane.config.assets)
        self.deribit = DeribitAdapter(plane.config.assets)
        self.polymarket = PolymarketAdapter(plane.config.assets)

    async def _rest_fallback_loop(self, *, stop_event: asyncio.Event) -> None:
        timeout = httpx.Timeout(15.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while not stop_event.is_set():
                for adapter in (self.binance, self.coinbase, self.deribit):
                    try:  # pragma: no cover - network integration path
                        envelopes = await adapter.poll_once(client)
                        for envelope in envelopes:
                            await self.plane.ingest_envelope(envelope)
                    except Exception as exc:  # pragma: no cover - network integration path
                        self.plane.record_error(adapter.venue, venue_stream="rest")
                        self.logger.warning("%s_rest_poll_error err=%s", adapter.venue, exc)
                await asyncio.sleep(self.plane.config.rest_poll_seconds)

    async def run_once(self) -> dict[str, Any]:
        timeout = httpx.Timeout(15.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            adapters = (self.binance, self.coinbase, self.deribit, self.polymarket)
            for adapter in adapters:
                try:
                    envelopes = await adapter.poll_once(client)
                    for envelope in envelopes:
                        await self.plane.ingest_envelope(envelope)
                except Exception as exc:
                    self.plane.record_error(adapter.venue, venue_stream="run_once")
                    self.logger.warning("%s_run_once_error err=%s", adapter.venue, exc)
        latest_path, timestamped_path, health_payload = self.plane.write_health_report()
        compaction = self.plane.compact_completed_hours()
        return {
            "health_latest_path": str(latest_path),
            "health_timestamped_path": str(timestamped_path),
            "health": health_payload,
            "compaction": compaction,
            "counts": self.plane.snapshot_counts(),
        }

    async def run(
        self,
        *,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task[Any]] = []

        async def _health_loop() -> None:
            while not stop_event.is_set():
                self.plane.write_health_report()
                await asyncio.sleep(self.plane.config.health_emit_seconds)

        async def _compaction_loop() -> None:
            while not stop_event.is_set():
                self.plane.compact_completed_hours()
                await asyncio.sleep(60)

        tasks.append(asyncio.create_task(_health_loop(), name="data-plane-health-loop"))
        tasks.append(asyncio.create_task(_compaction_loop(), name="data-plane-compaction-loop"))
        tasks.append(asyncio.create_task(self.polymarket.poll_loop(plane=self.plane, stop_event=stop_event), name="polymarket-poll-loop"))

        if self.enable_websockets:
            tasks.append(asyncio.create_task(self.binance.stream_loop(plane=self.plane, stop_event=stop_event), name="binance-ws-loop"))
            tasks.append(asyncio.create_task(self.coinbase.stream_loop(plane=self.plane, stop_event=stop_event), name="coinbase-ws-loop"))
            tasks.append(asyncio.create_task(self.deribit.stream_loop(plane=self.plane, stop_event=stop_event), name="deribit-ws-loop"))
            tasks.append(asyncio.create_task(self._rest_fallback_loop(stop_event=stop_event), name="rest-fallback-loop"))
        else:
            tasks.append(asyncio.create_task(self._rest_fallback_loop(stop_event=stop_event), name="rest-only-loop"))

        if duration_seconds is not None and duration_seconds > 0:
            async def _timer() -> None:
                await asyncio.sleep(duration_seconds)
                stop_event.set()

            tasks.append(asyncio.create_task(_timer(), name="duration-timer"))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception as exc:
            self.logger.warning("data_plane_runner_error err=%s", exc)
            stop_event.set()
        finally:
            stop_event.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        latest_path, timestamped_path, health_payload = self.plane.write_health_report()
        return {
            "health_latest_path": str(latest_path),
            "health_timestamped_path": str(timestamped_path),
            "health": health_payload,
            "counts": self.plane.snapshot_counts(),
            "compaction": self.plane.compact_completed_hours(),
        }


__all__ = [
    "MARKET_ENVELOPE_SCHEMA",
    "VENUE_HEALTH_SCHEMA",
    "CANDLE_ANCHOR_SCHEMA",
    "DATA_PLANE_HEALTH_SCHEMA",
    "CrossAssetDataPlaneConfig",
    "CrossAssetDataPlane",
    "CrossAssetDataPlaneRunner",
    "BinanceAdapter",
    "CoinbaseAdapter",
    "DeribitAdapter",
    "PolymarketAdapter",
    "build_market_envelope",
]
