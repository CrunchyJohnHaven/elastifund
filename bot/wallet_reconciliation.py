"""Mirror remote Polymarket wallet truth into SQLite and score ledger drift."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterable, Mapping, Sequence

import requests
from scripts.report_envelope import write_report

try:  # pragma: no cover - unix-only
    import fcntl
except Exception:  # pragma: no cover - windows fallback
    fcntl = None


POSITIONS_URL = "https://data-api.polymarket.com/positions"
CLOSED_POSITIONS_URL = "https://data-api.polymarket.com/closed-positions"

REQUESTS_PER_WINDOW = 150
WINDOW_SECONDS = 10.0
MAX_RETRIES = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    value = dt or _utc_now()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_hex_like(value: Any) -> str:
    text = _normalize_text(value).lower()
    if text.startswith("0x"):
        return text
    if len(text) >= 4 and all(ch in "0123456789abcdef" for ch in text):
        return f"0x{text}"
    return text


def _stable_row_key(parts: Iterable[Any]) -> str:
    payload = "|".join(_normalize_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_market_key(value: Any) -> str:
    text = _normalize_text(value).lower()
    if not text:
        return ""
    normalized_chars = [ch if ch.isalnum() else " " for ch in text]
    return " ".join("".join(normalized_chars).split())


def _parse_datetime_like(value: Any) -> datetime | None:
    text = _normalize_text(value)
    if not text:
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _looks_like_btc_title(value: Any) -> bool:
    text = _normalize_market_key(value)
    return "bitcoin" in text or " btc " in f" {text} "


def _row_value(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


@dataclass(frozen=True)
class RemotePositionRow:
    row_key: str
    condition_id: str
    market_id: str
    token_id: str
    title: str
    outcome: str
    size: float
    avg_price: float
    current_value: float
    current_price: float
    realized_pnl: float
    transaction_hash: str
    settled_at: str
    raw_json: str


@dataclass(frozen=True)
class ReconciliationSummary:
    checked_at: str
    user_address: str
    open_positions_count: int
    closed_positions_count: int
    local_trade_count: int
    matched_local_open_trades: int
    matched_local_closed_trades: int
    remote_closed_local_open_mismatches: int
    phantom_local_open_trade_ids: list[str]
    matched_remote_open_positions: int
    matched_remote_closed_positions: int
    unmatched_remote_open_positions: int
    unmatched_remote_closed_positions: int
    snapshot_precision: float
    classification_precision: float
    status: str = "drift_detected"
    unmatched_open_positions: dict[str, int] = field(default_factory=dict)
    unmatched_closed_positions: dict[str, int] = field(default_factory=dict)
    remote_closed_local_open_trade_ids: list[str] = field(default_factory=list)
    local_fixes: dict[str, int] = field(default_factory=dict)
    recommendation: str = ""
    report_path: str | None = None


@dataclass(frozen=True)
class WalletExportRow:
    market_name: str
    action: str
    usdc_amount: float
    token_amount: float
    token_name: str
    timestamp: str
    tx_hash: str
    market_key: str


class TokenBucket:
    def __init__(
        self,
        *,
        capacity: int = REQUESTS_PER_WINDOW,
        refill_window_seconds: float = WINDOW_SECONDS,
    ) -> None:
        self.capacity = max(1, int(capacity))
        self.refill_window_seconds = max(0.1, float(refill_window_seconds))
        self.tokens = float(self.capacity)
        self.updated_at = time.monotonic()

    def consume(self, amount: float = 1.0) -> None:
        needed = max(0.0, float(amount))
        while True:
            now = time.monotonic()
            elapsed = max(0.0, now - self.updated_at)
            refill_rate = float(self.capacity) / self.refill_window_seconds
            self.tokens = min(float(self.capacity), self.tokens + (elapsed * refill_rate))
            self.updated_at = now
            if self.tokens >= needed:
                self.tokens -= needed
                return
            wait_seconds = max(0.01, (needed - self.tokens) / refill_rate)
            time.sleep(wait_seconds)


@contextmanager
def sqlite_file_lock(db_path: Path):
    lock_path = db_path.with_name(f"{db_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:  # pragma: no branch
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:  # pragma: no branch
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class PolymarketWalletReconciler:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
        page_limit: int = 200,
        max_pages: int = 20,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.page_limit = max(1, min(500, int(page_limit)))
        self.max_pages = max(1, int(max_pages))
        self.rate_limiter = rate_limiter or TokenBucket()

    def close(self) -> None:
        self.session.close()

    def fetch_open_positions(self, user_address: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while len(rows) < (self.page_limit * self.max_pages):
            payload = self._request_json(
                POSITIONS_URL,
                params={
                    "user": user_address,
                    "limit": self.page_limit,
                    "offset": offset,
                    "sizeThreshold": ".01",
                },
            )
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []
            filtered = [row for row in batch if isinstance(row, dict)]
            rows.extend(filtered)
            if len(filtered) < self.page_limit:
                break
            offset += len(filtered)
        return rows

    def fetch_closed_positions(self, user_address: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        for _ in range(self.max_pages):
            payload = self._request_json(
                CLOSED_POSITIONS_URL,
                params={
                    "user": user_address,
                    "limit": self.page_limit,
                    "offset": offset,
                },
            )
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []
            filtered = [row for row in batch if isinstance(row, dict)]
            rows.extend(filtered)
            if len(filtered) < self.page_limit:
                break
            offset += len(filtered)
        return rows

    def reconcile_to_sqlite(
        self,
        *,
        user_address: str,
        db_path: Path,
        report_path: Path | None = None,
        open_positions: list[dict[str, Any]] | None = None,
        closed_positions: list[dict[str, Any]] | None = None,
        apply_local_fixes: bool = False,
        purge_phantom_open_trades: bool = False,
    ) -> ReconciliationSummary:
        normalized_user = _normalize_hex_like(user_address)
        checked_at = _iso()
        remote_open = [self._normalize_position(row) for row in (open_positions or self.fetch_open_positions(normalized_user))]
        remote_closed = [self._normalize_position(row) for row in (closed_positions or self.fetch_closed_positions(normalized_user))]

        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_file_lock(db_path):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                self._create_tables(conn)
                self._replace_remote_rows(conn, normalized_user, checked_at, remote_open, remote_closed)
                summary = self._reconcile_local_trades(
                    conn,
                    user_address=normalized_user,
                    checked_at=checked_at,
                    remote_open=remote_open,
                    remote_closed=remote_closed,
                    apply_local_fixes=apply_local_fixes,
                    purge_phantom_open_trades=purge_phantom_open_trades,
                )
                self._record_run(conn, summary)
                conn.commit()
            finally:
                conn.close()

        payload = asdict(summary)
        if report_path is not None:
            report_payload = dict(payload)
            report_payload["report_path"] = str(report_path)
            write_report(
                report_path,
                artifact="wallet_reconciliation",
                payload=report_payload,
                status="fresh" if summary.status == "reconciled" else "blocked",
                source_of_truth="Polymarket data-api; local jj_trades.db; wallet export CSV",
                freshness_sla_seconds=1800,
                blockers=[] if summary.status == "reconciled" else [summary.recommendation or summary.status],
                summary=(
                    f"open_positions={summary.open_positions_count} "
                    f"closed_positions={summary.closed_positions_count} "
                    f"status={summary.status}"
                ),
            )
            summary = ReconciliationSummary(**report_payload)
        return summary

    def _request_json(self, url: str, *, params: dict[str, Any]) -> Any:
        backoff_seconds = 0.5
        last_error: str | None = None
        for _ in range(MAX_RETRIES):
            self.rate_limiter.consume()
            response = self.session.get(url, params=params, timeout=self.timeout_seconds)
            status_code = int(getattr(response, "status_code", 200) or 200)
            if status_code == 429 or status_code >= 500:
                last_error = f"http_{status_code}"
                time.sleep(backoff_seconds)
                backoff_seconds = min(8.0, backoff_seconds * 2.0)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"wallet_reconciliation_request_failed:{last_error or 'unknown'}")

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wallet_open_positions (
                user_address TEXT NOT NULL,
                row_key TEXT NOT NULL,
                condition_id TEXT,
                market_id TEXT,
                token_id TEXT,
                title TEXT,
                outcome TEXT,
                size REAL NOT NULL DEFAULT 0.0,
                avg_price REAL,
                current_value REAL,
                current_price REAL,
                realized_pnl REAL,
                transaction_hash TEXT,
                settled_at TEXT,
                raw_json TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY (user_address, row_key)
            );
            CREATE TABLE IF NOT EXISTS wallet_closed_positions (
                user_address TEXT NOT NULL,
                row_key TEXT NOT NULL,
                condition_id TEXT,
                market_id TEXT,
                token_id TEXT,
                title TEXT,
                outcome TEXT,
                size REAL NOT NULL DEFAULT 0.0,
                avg_price REAL,
                current_value REAL,
                current_price REAL,
                realized_pnl REAL,
                transaction_hash TEXT,
                settled_at TEXT,
                raw_json TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY (user_address, row_key)
            );
            CREATE TABLE IF NOT EXISTS wallet_trade_reconciliation (
                user_address TEXT NOT NULL,
                local_trade_id TEXT NOT NULL,
                local_status TEXT NOT NULL,
                remote_status TEXT NOT NULL,
                matched_by TEXT,
                remote_row_key TEXT,
                checked_at TEXT NOT NULL,
                PRIMARY KEY (user_address, local_trade_id)
            );
            CREATE TABLE IF NOT EXISTS wallet_reconciliation_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                user_address TEXT NOT NULL,
                open_positions_count INTEGER NOT NULL,
                closed_positions_count INTEGER NOT NULL,
                local_trade_count INTEGER NOT NULL,
                matched_local_open_trades INTEGER NOT NULL,
                matched_local_closed_trades INTEGER NOT NULL,
                remote_closed_local_open_mismatches INTEGER NOT NULL,
                phantom_local_open_count INTEGER NOT NULL,
                matched_remote_open_positions INTEGER NOT NULL,
                matched_remote_closed_positions INTEGER NOT NULL,
                unmatched_remote_open_positions INTEGER NOT NULL,
                unmatched_remote_closed_positions INTEGER NOT NULL,
                snapshot_precision REAL NOT NULL,
                classification_precision REAL NOT NULL,
                report_json TEXT NOT NULL
            );
            """
        )

    def _replace_remote_rows(
        self,
        conn: sqlite3.Connection,
        user_address: str,
        checked_at: str,
        remote_open: list[RemotePositionRow],
        remote_closed: list[RemotePositionRow],
    ) -> None:
        conn.execute("DELETE FROM wallet_open_positions WHERE user_address = ?", (user_address,))
        conn.execute("DELETE FROM wallet_closed_positions WHERE user_address = ?", (user_address,))
        conn.execute("DELETE FROM wallet_trade_reconciliation WHERE user_address = ?", (user_address,))
        conn.executemany(
            """
            INSERT INTO wallet_open_positions (
                user_address, row_key, condition_id, market_id, token_id, title, outcome,
                size, avg_price, current_value, current_price, realized_pnl,
                transaction_hash, settled_at, raw_json, seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_address,
                    row.row_key,
                    row.condition_id,
                    row.market_id,
                    row.token_id,
                    row.title,
                    row.outcome,
                    row.size,
                    row.avg_price,
                    row.current_value,
                    row.current_price,
                    row.realized_pnl,
                    row.transaction_hash,
                    row.settled_at,
                    row.raw_json,
                    checked_at,
                )
                for row in remote_open
            ],
        )
        conn.executemany(
            """
            INSERT INTO wallet_closed_positions (
                user_address, row_key, condition_id, market_id, token_id, title, outcome,
                size, avg_price, current_value, current_price, realized_pnl,
                transaction_hash, settled_at, raw_json, seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_address,
                    row.row_key,
                    row.condition_id,
                    row.market_id,
                    row.token_id,
                    row.title,
                    row.outcome,
                    row.size,
                    row.avg_price,
                    row.current_value,
                    row.current_price,
                    row.realized_pnl,
                    row.transaction_hash,
                    row.settled_at,
                    row.raw_json,
                    checked_at,
                )
                for row in remote_closed
            ],
        )

    def _reconcile_local_trades(
        self,
        conn: sqlite3.Connection,
        *,
        user_address: str,
        checked_at: str,
        remote_open: list[RemotePositionRow],
        remote_closed: list[RemotePositionRow],
        apply_local_fixes: bool,
        purge_phantom_open_trades: bool,
    ) -> ReconciliationSummary:
        local_rows = self._load_local_trades(conn)
        open_index = self._index_remote(remote_open)
        closed_index = self._index_remote(remote_closed)
        matched_remote_open: set[str] = set()
        matched_remote_closed: set[str] = set()
        trade_columns = self._trade_columns(conn)

        matched_local_open = 0
        matched_local_closed = 0
        remote_closed_local_open = 0
        remote_closed_local_open_trade_ids: list[str] = []
        phantom_local_open_trade_ids: list[str] = []
        local_fixes = {
            "closed_trades_backfilled": 0,
            "phantom_open_trades_deleted": 0,
        }

        for row in local_rows:
            local_trade_id = _normalize_text(_row_value(row, "id")) or _stable_row_key(
                (
                    _row_value(row, "market_id"),
                    _row_value(row, "token_id"),
                    _row_value(row, "outcome"),
                )
            )
            local_status = "open" if not _normalize_text(_row_value(row, "outcome")) else "closed"
            remote_row, matched_by, remote_status = self._match_remote_row(
                row=row,
                open_index=open_index,
                closed_index=closed_index,
            )
            remote_row_key = remote_row.row_key if remote_row is not None else None
            if remote_status == "open" and local_status == "open":
                matched_local_open += 1
            elif remote_status == "closed" and local_status == "closed":
                matched_local_closed += 1
            elif remote_status == "closed" and local_status == "open":
                fixed = 0
                if apply_local_fixes and remote_row is not None:
                    fixed = self._backfill_closed_trade(
                        conn,
                        row=row,
                        remote_row=remote_row,
                        checked_at=checked_at,
                        trade_columns=trade_columns,
                    )
                    local_fixes["closed_trades_backfilled"] += fixed
                if fixed:
                    matched_local_closed += 1
                else:
                    remote_closed_local_open += 1
                    remote_closed_local_open_trade_ids.append(local_trade_id)
            elif remote_status == "missing" and local_status == "open":
                purged = False
                if purge_phantom_open_trades and self._purge_phantom_open_trade(
                    conn,
                    row=row,
                    trade_columns=trade_columns,
                ):
                    local_fixes["phantom_open_trades_deleted"] += 1
                    purged = True
                if not purged:
                    phantom_local_open_trade_ids.append(local_trade_id)

            if remote_status == "open" and remote_row is not None:
                matched_remote_open.add(remote_row.row_key)
            elif remote_status == "closed" and remote_row is not None:
                matched_remote_closed.add(remote_row.row_key)

            conn.execute(
                """
                INSERT INTO wallet_trade_reconciliation (
                    user_address, local_trade_id, local_status, remote_status, matched_by, remote_row_key, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_address,
                    local_trade_id,
                    local_status,
                    remote_status,
                    matched_by,
                    remote_row_key,
                    checked_at,
                ),
            )

        effective_local_rows = (
            self._load_local_trades(conn)
            if (apply_local_fixes or purge_phantom_open_trades)
            else local_rows
        )
        local_open_count = sum(
            1 for row in effective_local_rows if not _normalize_text(_row_value(row, "outcome"))
        )
        local_closed_count = max(0, len(effective_local_rows) - local_open_count)
        open_rows_written = int(
            conn.execute(
                "SELECT COUNT(*) FROM wallet_open_positions WHERE user_address = ?",
                (user_address,),
            ).fetchone()[0]
        )
        closed_rows_written = int(
            conn.execute(
                "SELECT COUNT(*) FROM wallet_closed_positions WHERE user_address = ?",
                (user_address,),
            ).fetchone()[0]
        )
        expected_open = len(remote_open)
        expected_closed = len(remote_closed)
        open_precision = 1.0 if expected_open == 0 else min(open_rows_written, expected_open) / float(expected_open)
        closed_precision = 1.0 if expected_closed == 0 else min(closed_rows_written, expected_closed) / float(expected_closed)
        snapshot_precision = round((open_precision + closed_precision) / 2.0, 6)

        local_trade_count = len(effective_local_rows)
        classification_hits = matched_local_open + matched_local_closed
        classification_precision = round(
            1.0 if local_trade_count == 0 else (classification_hits / float(local_trade_count)),
            6,
        )
        unmatched_open_positions = {
            "local_ledger": int(local_open_count),
            "remote_wallet": int(expected_open),
            "delta_remote_minus_local": int(expected_open - local_open_count),
            "absolute_delta": int(abs(expected_open - local_open_count)),
        }
        unmatched_closed_positions = {
            "local_ledger": int(local_closed_count),
            "remote_wallet": int(expected_closed),
            "delta_remote_minus_local": int(expected_closed - local_closed_count),
            "absolute_delta": int(abs(expected_closed - local_closed_count)),
        }
        status = (
            "reconciled"
            if remote_closed_local_open == 0
            and not phantom_local_open_trade_ids
            and unmatched_open_positions["absolute_delta"] == 0
            and unmatched_closed_positions["absolute_delta"] == 0
            and snapshot_precision >= 0.99
            and classification_precision >= 0.95
            else "drift_detected"
        )
        if status == "reconciled":
            recommendation = "ready_for_launch_gate"
        elif phantom_local_open_trade_ids:
            recommendation = "purge_phantom_open_trades"
        elif remote_closed_local_open_trade_ids:
            recommendation = "apply_local_closure_backfill"
        else:
            recommendation = "review_wallet_reconciliation"
        summary = ReconciliationSummary(
            checked_at=checked_at,
            user_address=user_address,
            open_positions_count=expected_open,
            closed_positions_count=expected_closed,
            local_trade_count=local_trade_count,
            matched_local_open_trades=matched_local_open,
            matched_local_closed_trades=matched_local_closed,
            remote_closed_local_open_mismatches=remote_closed_local_open,
            phantom_local_open_trade_ids=phantom_local_open_trade_ids,
            matched_remote_open_positions=len(matched_remote_open),
            matched_remote_closed_positions=len(matched_remote_closed),
            unmatched_remote_open_positions=max(0, expected_open - len(matched_remote_open)),
            unmatched_remote_closed_positions=max(0, expected_closed - len(matched_remote_closed)),
            snapshot_precision=snapshot_precision,
            classification_precision=classification_precision,
            status=status,
            unmatched_open_positions=unmatched_open_positions,
            unmatched_closed_positions=unmatched_closed_positions,
            remote_closed_local_open_trade_ids=remote_closed_local_open_trade_ids,
            local_fixes=local_fixes,
            recommendation=recommendation,
        )
        return summary

    def _load_local_trades(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trades'"
        ).fetchone()
        if table_exists is None:
            return []
        return conn.execute(
            """
            SELECT *
            FROM trades
            """
        ).fetchall()

    def _trade_columns(self, conn: sqlite3.Connection) -> set[str]:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trades'"
        ).fetchone()
        if table_exists is None:
            return set()
        rows = conn.execute("PRAGMA table_info(trades)").fetchall()
        return {str(row[1]) for row in rows}

    def _backfill_closed_trade(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        remote_row: RemotePositionRow,
        checked_at: str,
        trade_columns: set[str],
    ) -> int:
        updates: dict[str, Any] = {}
        if "outcome" in trade_columns and not _normalize_text(_row_value(row, "outcome")):
            # Best-effort inference: redeemed positions with non-positive realized
            # PnL behaved as losses; positive realized PnL behaved as wins.
            updates["outcome"] = "won" if float(remote_row.realized_pnl) > 0.0 else "lost"
        if "resolved_at" in trade_columns:
            updates["resolved_at"] = remote_row.settled_at or checked_at
        if "pnl" in trade_columns:
            updates["pnl"] = float(remote_row.realized_pnl)
        if not updates:
            return 0
        trade_id = _normalize_text(_row_value(row, "id"))
        if not trade_id:
            return 0
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [trade_id]
        conn.execute(f"UPDATE trades SET {assignments} WHERE id = ?", values)
        return 1

    def _purge_phantom_open_trade(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        trade_columns: set[str],
    ) -> bool:
        if "transaction_hash" in trade_columns:
            tx_hash = _normalize_text(_row_value(row, "transaction_hash"))
            if tx_hash:
                return False
        trade_id = _normalize_text(_row_value(row, "id"))
        if not trade_id:
            return False
        deleted = conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,)).rowcount
        return bool(deleted)

    def _match_remote_row(
        self,
        *,
        row: sqlite3.Row,
        open_index: dict[str, RemotePositionRow],
        closed_index: dict[str, RemotePositionRow],
    ) -> tuple[RemotePositionRow | None, str | None, str]:
        identifiers = (
            ("token_id", _normalize_hex_like(_row_value(row, "token_id"))),
            ("market_id", _normalize_hex_like(_row_value(row, "market_id"))),
            ("market_id", _normalize_text(_row_value(row, "market_id"))),
        )
        for label, key in identifiers:
            if not key:
                continue
            if key in open_index:
                return open_index[key], label, "open"
            if key in closed_index:
                return closed_index[key], label, "closed"
        return None, None, "missing"

    def _index_remote(self, rows: list[RemotePositionRow]) -> dict[str, RemotePositionRow]:
        index: dict[str, RemotePositionRow] = {}
        for row in rows:
            for key in (row.token_id, row.condition_id, row.market_id):
                normalized = _normalize_hex_like(key)
                if normalized and normalized not in index:
                    index[normalized] = row
                raw = _normalize_text(key)
                if raw and raw not in index:
                    index[raw] = row
        return index

    def _record_run(self, conn: sqlite3.Connection, summary: ReconciliationSummary) -> None:
        conn.execute(
            """
            INSERT INTO wallet_reconciliation_runs (
                checked_at,
                user_address,
                open_positions_count,
                closed_positions_count,
                local_trade_count,
                matched_local_open_trades,
                matched_local_closed_trades,
                remote_closed_local_open_mismatches,
                phantom_local_open_count,
                matched_remote_open_positions,
                matched_remote_closed_positions,
                unmatched_remote_open_positions,
                unmatched_remote_closed_positions,
                snapshot_precision,
                classification_precision,
                report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.checked_at,
                summary.user_address,
                summary.open_positions_count,
                summary.closed_positions_count,
                summary.local_trade_count,
                summary.matched_local_open_trades,
                summary.matched_local_closed_trades,
                summary.remote_closed_local_open_mismatches,
                len(summary.phantom_local_open_trade_ids),
                summary.matched_remote_open_positions,
                summary.matched_remote_closed_positions,
                summary.unmatched_remote_open_positions,
                summary.unmatched_remote_closed_positions,
                summary.snapshot_precision,
                summary.classification_precision,
                json.dumps(asdict(summary), sort_keys=True),
            ),
        )

    def _normalize_position(self, row: Mapping[str, Any]) -> RemotePositionRow:
        condition_id = _normalize_hex_like(
            row.get("conditionId") or row.get("condition_id") or row.get("market")
        )
        market_id = _normalize_text(row.get("market") or row.get("market_id") or condition_id)
        token_id = _normalize_hex_like(
            row.get("asset")
            or row.get("assetId")
            or row.get("asset_id")
            or row.get("tokenId")
            or row.get("token_id")
        )
        outcome = _normalize_text(row.get("outcome") or row.get("position"))
        transaction_hash = _normalize_hex_like(
            row.get("transactionHash") or row.get("transaction_hash") or row.get("hash")
        )
        settled_at = _normalize_text(
            row.get("resolvedAt")
            or row.get("resolved_at")
            or row.get("endDate")
            or row.get("updatedAt")
            or row.get("updated_at")
        )
        row_key = _stable_row_key(
            (
                condition_id,
                market_id,
                token_id,
                outcome,
                transaction_hash,
                settled_at,
            )
        )
        return RemotePositionRow(
            row_key=row_key,
            condition_id=condition_id,
            market_id=market_id,
            token_id=token_id,
            title=_normalize_text(row.get("title") or row.get("question") or row.get("marketTitle")),
            outcome=outcome,
            size=_as_float(row.get("size"), 0.0),
            avg_price=_as_float(row.get("avgPrice") or row.get("averagePrice"), 0.0),
            current_value=_as_float(row.get("currentValue") or row.get("value"), 0.0),
            current_price=_as_float(row.get("currentPrice") or row.get("markPrice") or row.get("price"), 0.0),
            realized_pnl=_as_float(row.get("realizedPnl"), 0.0),
            transaction_hash=transaction_hash,
            settled_at=settled_at,
            raw_json=json.dumps(dict(row), sort_keys=True),
        )


def load_wallet_export_csv(csv_path: Path) -> dict[str, Any]:
    if not csv_path.exists():
        return {
            "available": False,
            "path": str(csv_path),
            "rows": [],
            "row_count": 0,
            "market_rollup": {},
            "open_market_keys": [],
            "redeemed_market_keys": [],
            "latest_timestamp": None,
        }

    parsed_rows: list[WalletExportRow] = []
    market_rollup: dict[str, dict[str, Any]] = {}
    latest_ts: datetime | None = None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            if not isinstance(raw_row, dict):
                continue
            market_name = _normalize_text(raw_row.get("marketName") or raw_row.get("market") or raw_row.get("title"))
            action = _normalize_text(raw_row.get("action")).lower()
            if not market_name or not action:
                continue
            parsed = WalletExportRow(
                market_name=market_name,
                action=action,
                usdc_amount=_as_float(raw_row.get("usdcAmount"), 0.0),
                token_amount=_as_float(raw_row.get("tokenAmount"), 0.0),
                token_name=_normalize_text(raw_row.get("tokenName")),
                timestamp=_normalize_text(raw_row.get("timestamp")),
                tx_hash=_normalize_text(raw_row.get("hash")),
                market_key=_normalize_market_key(market_name),
            )
            parsed_rows.append(parsed)
            bucket = market_rollup.setdefault(
                parsed.market_key,
                {
                    "market_name": parsed.market_name,
                    "buy_count": 0,
                    "buy_usdc_total": 0.0,
                    "redeem_count": 0,
                    "redeem_usdc_total": 0.0,
                    "actions": set(),
                },
            )
            bucket["actions"].add(parsed.action)
            if parsed.action == "buy":
                bucket["buy_count"] = int(bucket["buy_count"]) + 1
                bucket["buy_usdc_total"] = round(_as_float(bucket["buy_usdc_total"]) + parsed.usdc_amount, 6)
            elif parsed.action == "redeem":
                bucket["redeem_count"] = int(bucket["redeem_count"]) + 1
                bucket["redeem_usdc_total"] = round(_as_float(bucket["redeem_usdc_total"]) + parsed.usdc_amount, 6)

            ts = _parse_datetime_like(parsed.timestamp)
            if ts is not None and (latest_ts is None or ts > latest_ts):
                latest_ts = ts

    open_market_keys = sorted(
        key
        for key, bucket in market_rollup.items()
        if int(bucket.get("buy_count") or 0) > int(bucket.get("redeem_count") or 0)
    )
    redeemed_market_keys = sorted(
        key for key, bucket in market_rollup.items() if int(bucket.get("redeem_count") or 0) > 0
    )
    serialized_rollup = {
        key: {
            **{k: v for k, v in bucket.items() if k != "actions"},
            "actions": sorted(str(item) for item in bucket.get("actions") or []),
        }
        for key, bucket in market_rollup.items()
    }
    return {
        "available": True,
        "path": str(csv_path),
        "rows": [asdict(row) for row in parsed_rows],
        "row_count": len(parsed_rows),
        "market_rollup": serialized_rollup,
        "open_market_keys": open_market_keys,
        "redeemed_market_keys": redeemed_market_keys,
        "latest_timestamp": _iso(latest_ts) if latest_ts is not None else None,
    }


def _remote_market_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _normalize_market_key(row.get("title") or row.get("question") or row.get("market") or row.get("slug"))
        if not key:
            continue
        index.setdefault(key, []).append(dict(row))
    return index


def classify_btc_open_positions(
    open_positions: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    stale_after_hours: float = 24.0,
) -> dict[str, Any]:
    now_utc = now or _utc_now()
    stale_cutoff = now_utc - timedelta(hours=max(1.0, float(stale_after_hours)))
    btc_rows = [dict(row) for row in open_positions if _looks_like_btc_title(row.get("title"))]
    intentional: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for row in btc_rows:
        end_ts = _parse_datetime_like(row.get("endDate") or row.get("resolvedAt") or row.get("updatedAt"))
        redeemable = bool(row.get("redeemable"))
        entry = {
            "condition_id": _normalize_hex_like(row.get("conditionId") or row.get("condition_id")),
            "token_id": _normalize_hex_like(row.get("asset") or row.get("tokenId") or row.get("token_id")),
            "title": _normalize_text(row.get("title") or row.get("question")),
            "outcome": _normalize_text(row.get("outcome")),
            "size": _as_float(row.get("size"), 0.0),
            "end_date": _iso(end_ts) if end_ts is not None else None,
            "redeemable": redeemable,
            "initial_value_usd": round(_as_float(row.get("initialValue"), 0.0), 6),
            "current_value_usd": round(_as_float(row.get("currentValue"), 0.0), 6),
        }
        stale_reasons: list[str] = []
        # A redeemable position is only stale after the configured time window.
        # Freshly-resolved markets can be intentionally open while settlement finalizes.
        if end_ts is not None and end_ts <= stale_cutoff:
            stale_reasons.append("end_date_older_than_stale_threshold")
            if redeemable:
                stale_reasons.append("redeemable_true")
        if stale_reasons:
            stale.append({**entry, "stale_reasons": stale_reasons})
        else:
            intentional.append({**entry, "classification": "intentional_open"})
    return {
        "btc_open_positions_total": len(btc_rows),
        "btc_open_positions_intentional": len(intentional),
        "btc_open_positions_stale": len(stale),
        "intentional_positions": intentional,
        "stale_positions": stale,
    }


def _looks_like_non_btc_fast_market(title: Any) -> bool:
    text = _normalize_market_key(title)
    if not text or "bitcoin" in text or " btc " in f" {text} ":
        return False
    has_crypto_asset = any(
        token in text
        for token in ("ethereum", " eth ", "solana", " sol ", "xrp", "ripple", "dogecoin", " doge ")
    )
    has_fast_shape = (
        "up or down" in text
        or bool(re.search(r"\b\d{1,2} \d{2}(?:am|pm)\b", text))
        or bool(re.search(r"\b(?:5m|15m|30m|1h|2h|3h|4h)\b", text))
    )
    return has_crypto_asset and has_fast_shape


def build_open_position_inventory(
    open_positions: Sequence[Mapping[str, Any]],
    *,
    btc_open_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    btc_status = dict(btc_open_status or {})
    intentional_token_ids = {
        _normalize_hex_like(item.get("token_id"))
        for item in btc_status.get("intentional_positions") or []
        if _normalize_hex_like(item.get("token_id"))
    }
    stale_token_ids = {
        _normalize_hex_like(item.get("token_id"))
        for item in btc_status.get("stale_positions") or []
        if _normalize_hex_like(item.get("token_id"))
    }

    rows: list[dict[str, Any]] = []
    sleeve_counts: dict[str, int] = {}
    policy_counts: dict[str, int] = {}
    open_book_cost_usd = 0.0
    open_book_mark_usd = 0.0

    for raw_row in open_positions:
        row = dict(raw_row)
        token_id = _normalize_hex_like(row.get("asset") or row.get("tokenId") or row.get("token_id"))
        title = _normalize_text(row.get("title") or row.get("question"))
        initial_value_usd = round(_as_float(row.get("initialValue"), 0.0), 6)
        current_value_usd = round(_as_float(row.get("currentValue"), 0.0), 6)
        unrealized_pnl_usd = round(current_value_usd - initial_value_usd, 6)

        if token_id in intentional_token_ids:
            sleeve = "btc5_intentional"
            policy_state = "managed_btc5"
            exit_owner = "btc5_runtime"
            exit_rule = "Redeem on settlement or next redeem batch; no discretionary adds outside BTC5 policy."
        elif token_id in stale_token_ids:
            sleeve = "btc5_intentional"
            policy_state = "close_only"
            exit_owner = "btc5_runtime"
            exit_rule = "Redeem immediately; stale BTC5 carry is not allowed to stay open."
        elif _looks_like_non_btc_fast_market(title):
            sleeve = "non_btc_fast"
            policy_state = "close_only"
            exit_owner = "operator"
            exit_rule = "No new orders. Reduce or redeem on the next available liquidity batch; do not average down."
        else:
            sleeve = "long_dated_discretionary"
            policy_state = "inventory_only"
            exit_owner = "operator"
            exit_rule = "Track separately from BTC5. Manual hold-or-reduce only; excluded from fast-lane diagnosis."

        rows.append(
            {
                "condition_id": _normalize_hex_like(row.get("conditionId") or row.get("condition_id")),
                "token_id": token_id,
                "title": title,
                "outcome": _normalize_text(row.get("outcome")),
                "end_date": _normalize_text(row.get("endDate") or row.get("end_date")),
                "redeemable": bool(row.get("redeemable")),
                "size": round(_as_float(row.get("size"), 0.0), 6),
                "initial_value_usd": initial_value_usd,
                "current_value_usd": current_value_usd,
                "unrealized_pnl_usd": unrealized_pnl_usd,
                "sleeve": sleeve,
                "policy_state": policy_state,
                "exit_owner": exit_owner,
                "exit_rule": exit_rule,
            }
        )
        sleeve_counts[sleeve] = sleeve_counts.get(sleeve, 0) + 1
        policy_counts[policy_state] = policy_counts.get(policy_state, 0) + 1
        open_book_cost_usd += initial_value_usd
        open_book_mark_usd += current_value_usd

    rows.sort(
        key=lambda item: (
            {"btc5_intentional": 0, "non_btc_fast": 1, "long_dated_discretionary": 2}.get(item["sleeve"], 9),
            -float(item["current_value_usd"]),
            item["title"],
        )
    )
    return {
        "rows": rows,
        "summary": {
            "open_positions_total": len(rows),
            "sleeve_counts": sleeve_counts,
            "policy_counts": policy_counts,
            "open_position_cost_usd": round(open_book_cost_usd, 6),
            "open_position_mark_to_market_usd": round(open_book_mark_usd, 6),
            "open_position_unrealized_pnl_usd": round(open_book_mark_usd - open_book_cost_usd, 6),
            "non_btc_fast_close_only": sleeve_counts.get("non_btc_fast", 0) > 0,
        },
    }


def build_closed_winners_summary(
    closed_positions: Sequence[Mapping[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = []
    for row in closed_positions:
        rows.append(
            {
                "condition_id": _normalize_hex_like(row.get("conditionId") or row.get("condition_id")),
                "token_id": _normalize_hex_like(row.get("asset") or row.get("tokenId") or row.get("token_id")),
                "title": _normalize_text(row.get("title") or row.get("question")),
                "outcome": _normalize_text(row.get("outcome")),
                "realized_pnl_usd": round(_as_float(row.get("realizedPnl") or row.get("realized_pnl_usd"), 0.0), 6),
                "end_date": _normalize_text(row.get("endDate") or row.get("end_date")),
                "timestamp": _normalize_text(row.get("timestamp")),
            }
        )
    rows.sort(key=lambda item: (-float(item["realized_pnl_usd"]), item["title"]))
    return rows[: max(1, int(limit))]


def cross_reference_wallet_export(
    *,
    wallet_export_summary: Mapping[str, Any],
    open_positions: Sequence[Mapping[str, Any]],
    closed_positions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    csv_open_keys = {str(item) for item in wallet_export_summary.get("open_market_keys") or []}
    csv_redeemed_keys = {str(item) for item in wallet_export_summary.get("redeemed_market_keys") or []}
    remote_open_index = _remote_market_index(open_positions)
    remote_closed_index = _remote_market_index(closed_positions)
    remote_open_keys = set(remote_open_index)
    remote_closed_keys = set(remote_closed_index)

    orphan_remote_open_keys = sorted(key for key in remote_open_keys if key not in csv_open_keys)
    phantom_csv_open_keys = sorted(key for key in csv_open_keys if key not in remote_open_keys)
    remote_closed_missing_redeem_keys = sorted(key for key in remote_closed_keys if key not in csv_redeemed_keys)

    return {
        "csv_open_market_count": len(csv_open_keys),
        "csv_redeemed_market_count": len(csv_redeemed_keys),
        "remote_open_market_count": len(remote_open_keys),
        "remote_closed_market_count": len(remote_closed_keys),
        "orphan_remote_open_market_count": len(orphan_remote_open_keys),
        "orphan_remote_open_market_keys": orphan_remote_open_keys,
        "phantom_csv_open_market_count": len(phantom_csv_open_keys),
        "phantom_csv_open_market_keys": phantom_csv_open_keys,
        "remote_closed_missing_redeem_count": len(remote_closed_missing_redeem_keys),
        "remote_closed_missing_redeem_market_keys": remote_closed_missing_redeem_keys,
    }


def build_capital_attribution_summary(
    *,
    open_positions: Sequence[Mapping[str, Any]],
    wallet_value_usd: float,
    free_collateral_usd: float,
    reserved_order_usd: float,
) -> dict[str, Any]:
    open_position_costs_usd = round(
        sum(_as_float(row.get("initialValue"), 0.0) for row in open_positions),
        6,
    )
    open_position_current_value_usd = round(
        sum(_as_float(row.get("currentValue"), 0.0) for row in open_positions),
        6,
    )
    component_expected_total_usd = round(
        free_collateral_usd + reserved_order_usd + open_position_current_value_usd,
        6,
    )
    component_mark_to_market_delta_usd = round(wallet_value_usd - component_expected_total_usd, 6)
    wallet_minus_open_costs_usd = round(wallet_value_usd - open_position_costs_usd, 6)
    free_collateral_discrepancy_usd = round(wallet_minus_open_costs_usd - free_collateral_usd, 6)
    formula_value_usd = round(
        wallet_value_usd - open_position_costs_usd - free_collateral_discrepancy_usd,
        6,
    )
    capital_accounting_delta_usd = round(formula_value_usd - free_collateral_usd, 6)
    return {
        "wallet_value_usd": round(wallet_value_usd, 6),
        "free_collateral_usd": round(free_collateral_usd, 6),
        "reserved_order_usd": round(reserved_order_usd, 6),
        "open_position_costs_usd": open_position_costs_usd,
        "open_position_current_value_usd": open_position_current_value_usd,
        "component_expected_total_usd": component_expected_total_usd,
        "component_mark_to_market_delta_usd": component_mark_to_market_delta_usd,
        "capital_accounting_delta_usd": capital_accounting_delta_usd,
        "wallet_minus_open_position_costs_usd": wallet_minus_open_costs_usd,
        "free_collateral_discrepancy_usd": free_collateral_discrepancy_usd,
        "formula_wallet_minus_open_costs_minus_discrepancy_usd": formula_value_usd,
    }


def apply_wallet_reconciliation_to_runtime_truth(
    *,
    runtime_truth_path: Path,
    reconciliation_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if runtime_truth_path.exists():
        runtime_truth = json.loads(runtime_truth_path.read_text(encoding="utf-8"))
        if not isinstance(runtime_truth, dict):
            runtime_truth = {}
    else:
        runtime_truth = {}

    wallet_summary = dict(reconciliation_payload.get("wallet_reconciliation_summary") or {})
    cross_reference = dict(reconciliation_payload.get("cross_reference") or {})
    capital_summary = dict(reconciliation_payload.get("capital_attribution") or {})
    btc_open_status = dict(reconciliation_payload.get("btc_open_status") or {})
    open_position_inventory = dict(reconciliation_payload.get("open_position_inventory") or {})
    inventory_summary = dict(open_position_inventory.get("summary") or {})
    sleeve_counts = dict(inventory_summary.get("sleeve_counts") or {})
    policy_counts = dict(inventory_summary.get("policy_counts") or {})

    capital = runtime_truth.setdefault("capital", {})
    capital["polymarket_accounting_delta_usd"] = round(
        _as_float(capital_summary.get("capital_accounting_delta_usd"), 0.0),
        6,
    )
    capital["polymarket_accounting_expected_total_usd"] = round(
        _as_float(capital_summary.get("component_expected_total_usd"), 0.0),
        6,
    )
    capital["polymarket_actual_deployable_usd"] = round(
        _as_float(capital_summary.get("free_collateral_usd"), 0.0),
        6,
    )
    capital["polymarket_reserved_order_usd"] = round(
        _as_float(capital_summary.get("reserved_order_usd"), 0.0),
        6,
    )
    capital["polymarket_positions_initial_value_usd"] = round(
        _as_float(capital_summary.get("open_position_costs_usd"), 0.0),
        6,
    )
    capital["polymarket_positions_current_value_usd"] = round(
        _as_float(capital_summary.get("open_position_current_value_usd"), 0.0),
        6,
    )
    capital["polymarket_observed_total_usd"] = round(
        _as_float(capital_summary.get("wallet_value_usd"), 0.0),
        6,
    )

    runtime_truth["wallet_reconciliation_status"] = wallet_summary.get("status") or "unknown"
    runtime_truth["wallet_reconciliation"] = dict(reconciliation_payload)

    scoreboard = (
        runtime_truth.setdefault("state_improvement", {})
        .setdefault("strategy_recommendations", {})
        .setdefault("public_performance_scoreboard", {})
        .setdefault("wallet_reconciliation_summary", {})
    )
    scoreboard.update(
        {
            "source_class": "wallet_reconciliation_api_csv",
            "source_artifact": wallet_summary.get("wallet_export_path"),
            "reporting_precedence": "wallet_reconciliation",
            "reporting_precedence_reason": wallet_summary.get("reconciliation_reason") or "api_csv_cross_reference",
            "wallet_export_freshness_label": wallet_summary.get("wallet_export_freshness_label"),
            "source_age_hours": wallet_summary.get("wallet_export_age_hours"),
            "btc_open_markets": _as_int(btc_open_status.get("btc_open_positions_total"), 0),
            "btc_open_markets_intentional": _as_int(btc_open_status.get("btc_open_positions_intentional"), 0),
            "btc_open_markets_stale": _as_int(btc_open_status.get("btc_open_positions_stale"), 0),
            "remote_open_market_count": _as_int(cross_reference.get("remote_open_market_count"), 0),
            "remote_closed_market_count": _as_int(cross_reference.get("remote_closed_market_count"), 0),
            "open_inventory_positions": _as_int(inventory_summary.get("open_positions_total"), 0),
            "btc5_intentional_open_positions": _as_int(sleeve_counts.get("btc5_intentional"), 0),
            "non_btc_fast_open_positions": _as_int(sleeve_counts.get("non_btc_fast"), 0),
            "long_dated_discretionary_open_positions": _as_int(sleeve_counts.get("long_dated_discretionary"), 0),
            "close_only_open_positions": _as_int(policy_counts.get("close_only"), 0),
            "open_inventory_mark_to_market_usd": round(
                _as_float(inventory_summary.get("open_position_mark_to_market_usd"), 0.0),
                6,
            ),
            "open_inventory_unrealized_pnl_usd": round(
                _as_float(inventory_summary.get("open_position_unrealized_pnl_usd"), 0.0),
                6,
            ),
        }
    )

    runtime_truth_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_truth_path.write_text(
        json.dumps(runtime_truth, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return runtime_truth
