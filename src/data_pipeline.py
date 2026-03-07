"""Data pipeline for collecting Polymarket Chainlink-cluster crypto data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AppConfig


SLUG_PATTERN = re.compile(r"^btc-updown-(5m|15m|4h)-(\d+)$")


def utc_ts() -> int:
    return int(time.time())


def utc_iso(ts: int | None = None) -> str:
    ts = ts if ts is not None else utc_ts()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@dataclass
class PipelineSummary:
    markets_seen: int = 0
    market_snapshots: int = 0
    trade_rows: int = 0
    book_snapshots: int = 0
    btc_points: int = 0
    quality_issues: int = 0
    degraded_mode: bool = False


class HttpClient:
    """Retrying JSON HTTP client with minimal dependencies."""

    def __init__(self, timeout_seconds: int, retries: int, backoff_seconds: float, logger: logging.Logger):
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.logger = logger

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        final_url = f"{url}{query}"
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                req = Request(final_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                with urlopen(req, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body)
            except HTTPError as exc:
                last_error = exc
                # Client errors like 404 are typically permanent for this request.
                if exc.code in (400, 401, 403, 404):
                    raise
                self.logger.warning(
                    "HTTP request failed (attempt %s/%s): %s %s",
                    attempt,
                    self.retries,
                    final_url,
                    exc,
                )
                time.sleep(self.backoff_seconds * attempt)
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                self.logger.warning(
                    "HTTP request failed (attempt %s/%s): %s %s",
                    attempt,
                    self.retries,
                    final_url,
                    exc,
                )
                time.sleep(self.backoff_seconds * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unexpected HTTP client state")


class DataPipeline:
    """Collect and persist Polymarket + Binance data into SQLite."""

    def __init__(self, config: AppConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.db_path = Path(config.system.db_path)
        self.snapshot_dir = self.db_path.parent / "snapshots"
        self.cache_dir = self.db_path.parent / "cache"
        self.http = HttpClient(
            timeout_seconds=config.collector.http_timeout_seconds,
            retries=config.collector.http_retries,
            backoff_seconds=config.collector.retry_backoff_seconds,
            logger=self.logger,
        )
        self._btc_stop_event = threading.Event()
        self._btc_thread: threading.Thread | None = None
        self._book_unavailable_tokens: set[str] = set()

        self._ensure_dirs()
        self.initialize_db()

    def _ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        Path(self.config.system.report_root).mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def initialize_db(self) -> None:
        """Create tables required by the research pipeline."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS markets (
                    market_id TEXT PRIMARY KEY,
                    condition_id TEXT UNIQUE,
                    slug TEXT UNIQUE,
                    timeframe TEXT,
                    question TEXT,
                    resolution_source TEXT,
                    window_start_ts INTEGER,
                    window_end_ts INTEGER,
                    market_start_ts INTEGER,
                    market_end_ts INTEGER,
                    opening_price REAL,
                    final_resolution TEXT,
                    active INTEGER,
                    closed INTEGER,
                    yes_token_id TEXT,
                    no_token_id TEXT,
                    updated_at_ts INTEGER,
                    raw_json TEXT
                );

                CREATE TABLE IF NOT EXISTS market_prices (
                    condition_id TEXT,
                    timestamp_ts INTEGER,
                    yes_price REAL,
                    no_price REAL,
                    source TEXT,
                    PRIMARY KEY (condition_id, timestamp_ts)
                );

                CREATE TABLE IF NOT EXISTS btc_spot (
                    timestamp_ts INTEGER PRIMARY KEY,
                    price REAL,
                    source TEXT
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    condition_id TEXT,
                    timestamp_ts INTEGER,
                    side TEXT,
                    outcome TEXT,
                    price REAL,
                    size REAL,
                    wallet TEXT,
                    tx_hash TEXT,
                    raw_json TEXT
                );

                CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    condition_id TEXT,
                    token_id TEXT,
                    timestamp_ts INTEGER,
                    bid_1_price REAL,
                    bid_1_size REAL,
                    bid_2_price REAL,
                    bid_2_size REAL,
                    bid_3_price REAL,
                    bid_3_size REAL,
                    bid_4_price REAL,
                    bid_4_size REAL,
                    bid_5_price REAL,
                    bid_5_size REAL,
                    ask_1_price REAL,
                    ask_1_size REAL,
                    ask_2_price REAL,
                    ask_2_size REAL,
                    ask_3_price REAL,
                    ask_3_size REAL,
                    ask_4_price REAL,
                    ask_4_size REAL,
                    ask_5_price REAL,
                    ask_5_size REAL,
                    raw_json TEXT
                );

                CREATE TABLE IF NOT EXISTS data_quality_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_ts INTEGER,
                    severity TEXT,
                    event_type TEXT,
                    details TEXT
                );

                CREATE TABLE IF NOT EXISTS run_audit (
                    run_id TEXT PRIMARY KEY,
                    timestamp_ts INTEGER,
                    summary_json TEXT
                );
                """
            )

    def collect_once(self) -> PipelineSummary:
        """Collect one synchronous cycle of all available data."""
        summary = PipelineSummary()
        now = utc_ts()
        degraded = False

        try:
            candidate_slugs = self.discover_candidate_slugs(now)
            markets = self.fetch_markets_by_slugs(candidate_slugs)
            summary.markets_seen = len(markets)
        except Exception as exc:
            self.log_quality_event("error", "market_discovery_failed", str(exc))
            self.logger.exception("Market discovery failed")
            markets = self.load_recent_markets_from_cache()
            degraded = True

        if not markets:
            self.log_quality_event("warning", "no_markets", "No target markets discovered")
            summary.degraded_mode = True
            return summary

        with self._connect() as conn:
            condition_ids: set[str] = set()
            for market in markets:
                if not self._is_target_market(market):
                    continue
                self._upsert_market(conn, market)

                if self._store_market_price_snapshot(conn, market, now):
                    summary.market_snapshots += 1

                condition_id = market.get("conditionId")
                if condition_id:
                    condition_ids.add(str(condition_id))

                summary.book_snapshots += self._collect_orderbook(conn, market, now)

            summary.trade_rows += self._collect_recent_trades_for_conditions(conn, condition_ids)
            repaired = self._repair_trade_condition_ids(conn)
            if repaired > 0:
                self.logger.warning("trade_condition_repair_applied rows=%s", repaired)
            conn.commit()

        summary.btc_points += self.collect_binance_spot_once()
        summary.quality_issues = self.run_quality_checks()
        summary.degraded_mode = degraded

        if now % (self.config.collector.snapshot_every_minutes * 60) < max(
            self.config.collector.market_poll_seconds, 30
        ):
            self.create_snapshot(reason="scheduled")

        self._write_run_audit(summary)
        return summary

    def discover_candidate_slugs(self, now_ts: int) -> list[str]:
        """Discover likely active market slugs using trade tape + deterministic probes."""
        slugs: set[str] = set()

        trades = self.http.get_json(
            self.config.sources.trade_api,
            {"limit": self.config.collector.max_recent_trades},
        )
        self._cache_json("recent_trades.json", trades)
        for row in trades:
            trade_ts = int(row.get("timestamp") or 0)
            if trade_ts and now_ts - trade_ts > 8 * 3600:
                continue
            slug = str(row.get("eventSlug") or row.get("slug") or "")
            if SLUG_PATTERN.match(slug):
                slugs.add(slug)

        for timeframe, seconds in (("5m", 300), ("15m", 900), ("4h", 14_400)):
            floor = now_ts - (now_ts % seconds)
            for i in range(-self.config.collector.slug_probe_windows, 2):
                start_ts = floor + (i * seconds)
                if start_ts <= 0:
                    continue
                slugs.add(f"btc-updown-{timeframe}-{start_ts}")

        scored: list[tuple[int, str]] = []
        for slug in slugs:
            match = SLUG_PATTERN.match(slug)
            if not match:
                continue
            start_ts = int(match.group(2))
            scored.append((abs(start_ts - now_ts), slug))
        scored.sort(key=lambda x: x[0])
        return [slug for _, slug in scored[:120]]

    def fetch_markets_by_slugs(self, slugs: list[str]) -> list[dict[str, Any]]:
        """Load market records from Gamma API for each discovered slug."""
        markets: list[dict[str, Any]] = []
        for slug in slugs:
            try:
                rows = self.http.get_json(self.config.sources.gamma_api, {"slug": slug})
                if isinstance(rows, list) and rows:
                    markets.append(rows[0])
            except Exception as exc:
                self.logger.debug("Skipping slug %s due to error: %s", slug, exc)

        self._cache_json("recent_markets.json", markets)
        return markets

    def _is_target_market(self, market: dict[str, Any]) -> bool:
        slug = str(market.get("slug") or "")
        question = str(market.get("question") or "").lower()
        resolution = str(market.get("resolutionSource") or "").lower()

        if not SLUG_PATTERN.match(slug):
            return False
        if "bitcoin up or down" not in question and "btc" not in slug:
            return False
        required = self.config.markets.required_resolution_source_contains.lower()
        if required and required not in resolution:
            return False
        return True

    def _extract_timeframe(self, slug: str) -> tuple[str, int | None]:
        match = SLUG_PATTERN.match(slug)
        if not match:
            return "unknown", None
        return match.group(1), int(match.group(2))

    def _parse_ts(self, value: str | None) -> int | None:
        if not value:
            return None
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None

    def _parse_outcome_prices(self, value: Any) -> tuple[float | None, float | None]:
        try:
            if isinstance(value, str):
                parsed = json.loads(value)
            elif isinstance(value, list):
                parsed = value
            else:
                return None, None
            if len(parsed) < 2:
                return None, None
            return float(parsed[0]), float(parsed[1])
        except Exception:
            return None, None

    def _parse_token_ids(self, value: Any) -> tuple[str | None, str | None]:
        try:
            tokens = json.loads(value) if isinstance(value, str) else value
            if not isinstance(tokens, list) or len(tokens) < 2:
                return None, None
            return str(tokens[0]), str(tokens[1])
        except Exception:
            return None, None

    def _infer_final_resolution(self, market: dict[str, Any]) -> str | None:
        if not bool(market.get("closed")):
            return None
        yes, no = self._parse_outcome_prices(market.get("outcomePrices"))
        if yes is None or no is None:
            return None
        if yes >= 0.99:
            return "UP"
        if no >= 0.99:
            return "DOWN"
        return None

    def _upsert_market(self, conn: sqlite3.Connection, market: dict[str, Any]) -> None:
        slug = str(market.get("slug") or "")
        timeframe, window_start_ts = self._extract_timeframe(slug)
        market_start_ts = self._parse_ts(str(market.get("startDate") or ""))
        market_end_ts = self._parse_ts(str(market.get("endDate") or ""))
        yes_token, no_token = self._parse_token_ids(market.get("clobTokenIds"))

        conn.execute(
            """
            INSERT INTO markets (
                market_id, condition_id, slug, timeframe, question, resolution_source,
                window_start_ts, window_end_ts, market_start_ts, market_end_ts,
                opening_price, final_resolution, active, closed, yes_token_id,
                no_token_id, updated_at_ts, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                condition_id=excluded.condition_id,
                slug=excluded.slug,
                timeframe=excluded.timeframe,
                question=excluded.question,
                resolution_source=excluded.resolution_source,
                window_start_ts=excluded.window_start_ts,
                window_end_ts=excluded.window_end_ts,
                market_start_ts=excluded.market_start_ts,
                market_end_ts=excluded.market_end_ts,
                final_resolution=COALESCE(excluded.final_resolution, markets.final_resolution),
                active=excluded.active,
                closed=excluded.closed,
                yes_token_id=excluded.yes_token_id,
                no_token_id=excluded.no_token_id,
                updated_at_ts=excluded.updated_at_ts,
                raw_json=excluded.raw_json
            """,
            (
                str(market.get("id") or ""),
                str(market.get("conditionId") or ""),
                slug,
                timeframe,
                str(market.get("question") or ""),
                str(market.get("resolutionSource") or ""),
                window_start_ts,
                market_end_ts,
                market_start_ts,
                market_end_ts,
                None,
                self._infer_final_resolution(market),
                int(bool(market.get("active"))),
                int(bool(market.get("closed"))),
                yes_token,
                no_token,
                utc_ts(),
                json.dumps(market),
            ),
        )

    def _store_market_price_snapshot(self, conn: sqlite3.Connection, market: dict[str, Any], ts: int) -> bool:
        condition_id = str(market.get("conditionId") or "")
        yes, no = self._parse_outcome_prices(market.get("outcomePrices"))
        if not condition_id or yes is None or no is None:
            return False

        closed = bool(market.get("closed"))
        if not closed and not (0.01 <= yes <= 0.99 and 0.01 <= no <= 0.99):
            self.logger.warning("bad_tick condition=%s yes=%s no=%s", condition_id, yes, no)
            return False

        conn.execute(
            """
            INSERT OR IGNORE INTO market_prices (condition_id, timestamp_ts, yes_price, no_price, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (condition_id, ts, yes, no, "gamma"),
        )
        return True

    def _collect_recent_trades_for_conditions(self, conn: sqlite3.Connection, condition_ids: set[str]) -> int:
        if not condition_ids:
            return 0

        page_size = 100
        max_rows = max(page_size, int(self.config.collector.max_recent_trades))
        inserted = 0
        filtered_out = 0

        for offset in range(0, max_rows, page_size):
            rows = self.http.get_json(self.config.sources.trade_api, {"limit": page_size, "offset": offset})
            if not isinstance(rows, list) or not rows:
                break

            for row in rows:
                row_condition = str(row.get("conditionId") or "")
                if row_condition not in condition_ids:
                    filtered_out += 1
                    continue
                if self._store_trade_row(conn, row, row_condition):
                    inserted += 1

            if len(rows) < page_size:
                break

        if inserted == 0:
            self.logger.warning(
                "no_condition_trades_in_recent_tape tracked_conditions=%s max_rows=%s",
                len(condition_ids),
                max_rows,
            )
        elif filtered_out > 0:
            self.logger.debug("trade_filter_summary inserted=%s filtered_out=%s", inserted, filtered_out)

        return inserted

    def _store_trade_row(self, conn: sqlite3.Connection, row: dict[str, Any], condition_id: str) -> bool:
        ts = int(row.get("timestamp") or 0)
        if ts <= 0:
            return False
        price = float(row.get("price") or 0.0)
        if price <= 0.0 or price >= 1.0:
            return False

        tx_hash = str(row.get("transactionHash") or "")
        wallet = str(row.get("proxyWallet") or row.get("wallet") or "")
        trade_id = tx_hash or f"{condition_id}:{ts}:{wallet}:{row.get('price')}:{row.get('size')}"

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO trades (
                trade_id, condition_id, timestamp_ts, side, outcome, price, size,
                wallet, tx_hash, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                condition_id,
                ts,
                str(row.get("side") or ""),
                str(row.get("outcome") or ""),
                price,
                float(row.get("size") or 0.0),
                wallet,
                tx_hash,
                json.dumps(row),
            ),
        )
        return (cursor.rowcount or 0) > 0

    def _repair_trade_condition_ids(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            UPDATE trades
            SET condition_id = json_extract(raw_json, '$.conditionId')
            WHERE raw_json IS NOT NULL
              AND json_extract(raw_json, '$.conditionId') IS NOT NULL
              AND json_extract(raw_json, '$.conditionId') != condition_id
            """
        )
        return row.rowcount or 0

    def _collect_orderbook(self, conn: sqlite3.Connection, market: dict[str, Any], ts: int) -> int:
        condition_id = str(market.get("conditionId") or "")
        yes_token, no_token = self._parse_token_ids(market.get("clobTokenIds"))
        rows = 0
        for token_id in (yes_token, no_token):
            if not token_id:
                continue
            if token_id in self._book_unavailable_tokens:
                continue
            try:
                book = self.http.get_json(self.config.sources.clob_api, {"token_id": token_id})
            except HTTPError as exc:
                if exc.code == 404:
                    self._book_unavailable_tokens.add(token_id)
                self.logger.warning("book_fetch_failed token=%s err=%s", token_id, exc)
                continue
            except Exception as exc:
                self.logger.warning("book_fetch_failed token=%s err=%s", token_id, exc)
                continue

            bids = list(book.get("bids") or [])[:5]
            asks = list(book.get("asks") or [])[:5]
            values: list[float | str | int] = [
                f"{condition_id}:{token_id}:{ts}",
                condition_id,
                token_id,
                ts,
            ]

            for level in range(5):
                b = bids[level] if level < len(bids) else {}
                values.append(float(b.get("price") or 0.0))
                values.append(float(b.get("size") or 0.0))

            for level in range(5):
                a = asks[level] if level < len(asks) else {}
                values.append(float(a.get("price") or 0.0))
                values.append(float(a.get("size") or 0.0))

            values.append(json.dumps(book))

            conn.execute(
                """
                INSERT OR REPLACE INTO orderbook_snapshots (
                    snapshot_id, condition_id, token_id, timestamp_ts,
                    bid_1_price, bid_1_size, bid_2_price, bid_2_size,
                    bid_3_price, bid_3_size, bid_4_price, bid_4_size,
                    bid_5_price, bid_5_size, ask_1_price, ask_1_size,
                    ask_2_price, ask_2_size, ask_3_price, ask_3_size,
                    ask_4_price, ask_4_size, ask_5_price, ask_5_size,
                    raw_json
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?
                )
                """,
                values,
            )
            rows += 1

        return rows

    def collect_binance_spot_once(self) -> int:
        """Collect one BTC spot point, preferring ticker endpoint."""
        ts = utc_ts()
        price: float | None = None

        try:
            payload = self.http.get_json(self.config.sources.binance_ticker_api)
            price = float(payload.get("price"))
        except Exception as exc:
            self.log_quality_event("warning", "binance_ticker_failed", str(exc))

        if price is None:
            try:
                rows = self.http.get_json(self.config.sources.binance_klines_api)
                if rows and isinstance(rows, list):
                    price = float(rows[-1][4])
            except Exception as exc:
                self.log_quality_event("error", "binance_fallback_failed", str(exc))

        if price is None or price <= 0.0:
            return 0

        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO btc_spot (timestamp_ts, price, source) VALUES (?, ?, ?)",
                (ts, price, "binance_rest"),
            )
        return 1

    def start_btc_stream(self) -> None:
        """Start background BTC collection loop with graceful fallback behavior."""
        if self._btc_thread and self._btc_thread.is_alive():
            return

        self._btc_stop_event.clear()
        self._btc_thread = threading.Thread(target=self._btc_stream_loop, name="btc-stream", daemon=True)
        self._btc_thread.start()

    def stop_btc_stream(self) -> None:
        self._btc_stop_event.set()
        if self._btc_thread and self._btc_thread.is_alive():
            self._btc_thread.join(timeout=5)

    def _btc_stream_loop(self) -> None:
        interval = max(1, self.config.collector.btc_poll_seconds)
        while not self._btc_stop_event.is_set():
            try:
                self.collect_binance_spot_once()
            except Exception as exc:
                self.log_quality_event("error", "btc_stream_error", str(exc))
            self._btc_stop_event.wait(interval)

    def run_quality_checks(self) -> int:
        """Detect missing snapshots and duplicate timestamp anomalies."""
        issues = 0
        now = utc_ts()
        with self._connect() as conn:
            btc_rows = conn.execute(
                "SELECT timestamp_ts FROM btc_spot WHERE timestamp_ts >= ? ORDER BY timestamp_ts DESC LIMIT 300",
                (now - 900,),
            ).fetchall()
            if len(btc_rows) >= 2:
                latest = btc_rows[0][0]
                prev = btc_rows[1][0]
                if latest - prev > self.config.collector.btc_poll_seconds * 3:
                    self.log_quality_event("warning", "missing_btc_ticks", f"gap_seconds={latest - prev}")
                    issues += 1

            market_rows = conn.execute(
                """
                SELECT mp.condition_id, MAX(mp.timestamp_ts) AS last_ts
                FROM market_prices mp
                JOIN markets m ON m.condition_id = mp.condition_id
                WHERE (m.closed = 0 OR m.active = 1)
                  AND COALESCE(m.market_end_ts, m.window_end_ts, 0) >= ?
                GROUP BY mp.condition_id
                """,
                (now - 3600,),
            ).fetchall()
            for condition_id, last_ts in market_rows:
                if now - int(last_ts) > self.config.collector.market_poll_seconds * 4:
                    self.log_quality_event(
                        "warning",
                        "missing_market_snapshots",
                        f"condition={condition_id} gap_seconds={now - int(last_ts)}",
                    )
                    issues += 1
        return issues

    def create_snapshot(self, reason: str = "manual") -> Path:
        """Create reproducible DB snapshot and metadata manifest."""
        ts = utc_ts()
        stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        db_snapshot = self.snapshot_dir / f"edge_discovery_{stamp}.db"
        manifest = self.snapshot_dir / f"edge_discovery_{stamp}.json"

        if self.db_path.exists():
            shutil.copy2(self.db_path, db_snapshot)

        payload = {
            "timestamp": utc_iso(ts),
            "reason": reason,
            "db_snapshot": str(db_snapshot),
            "source": "edge_discovery_system",
        }
        manifest.write_text(json.dumps(payload, indent=2))
        return db_snapshot

    def load_recent_markets_from_cache(self) -> list[dict[str, Any]]:
        path = self.cache_dir / "recent_markets.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return []

    def _cache_json(self, name: str, payload: Any) -> None:
        path = self.cache_dir / name
        path.write_text(json.dumps(payload))

    def _write_run_audit(self, summary: PipelineSummary) -> None:
        run_id = f"run-{utc_ts()}"
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO run_audit (run_id, timestamp_ts, summary_json) VALUES (?, ?, ?)",
                (run_id, utc_ts(), json.dumps(summary.__dict__)),
            )

    def log_quality_event(self, severity: str, event_type: str, details: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO data_quality_events (timestamp_ts, severity, event_type, details) VALUES (?, ?, ?, ?)",
                    (utc_ts(), severity, event_type, details[:3000]),
                )
        except sqlite3.OperationalError:
            # Avoid cascading failures when logging from inside another write transaction.
            self.logger.warning("quality_log_db_locked event_type=%s details=%s", event_type, details[:300])
        self.logger.log(
            logging.ERROR if severity == "error" else logging.WARNING,
            "%s: %s",
            event_type,
            details,
        )

    def collect_loop(self, stop_event: threading.Event) -> None:
        """Continuous data collection loop for standalone collector runs."""
        interval = max(5, self.config.collector.market_poll_seconds)
        while not stop_event.is_set():
            try:
                self.collect_once()
            except Exception as exc:
                self.log_quality_event("error", "collect_loop_failure", str(exc))
            stop_event.wait(interval)
