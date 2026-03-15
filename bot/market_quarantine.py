"""Market quarantine manager for graceful CLOB 404 handling.

Tracks token_ids and market_ids that return errors (404, 5xx, timeouts)
and quarantines them for a configurable period before retrying. Persists
quarantine state in SQLite so it survives restarts.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/edge_discovery.db"
DEFAULT_QUARANTINE_SECONDS = 3600  # 1 hour
MAX_STRIKES = 5  # After this many consecutive failures, quarantine extends


@dataclass(frozen=True)
class QuarantineEntry:
    identifier: str
    id_type: str  # "token_id" or "market_id"
    reason: str
    strikes: int
    quarantined_at: float
    expires_at: float


class MarketQuarantine:
    """Manages quarantine state for failed token/market lookups."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        default_duration_seconds: int = DEFAULT_QUARANTINE_SECONDS,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_duration = default_duration_seconds
        self._init_table()
        self._memory_cache: dict[str, QuarantineEntry] = {}
        self._load_active()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_quarantine (
                    identifier TEXT PRIMARY KEY,
                    id_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    strikes INTEGER NOT NULL DEFAULT 1,
                    quarantined_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_quarantine_expires
                ON market_quarantine(expires_at)
            """)

    def _load_active(self) -> None:
        """Load non-expired quarantine entries into memory cache."""
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT identifier, id_type, reason, strikes, quarantined_at, expires_at "
                "FROM market_quarantine WHERE expires_at > ?",
                (now,),
            ).fetchall()
        for row in rows:
            entry = QuarantineEntry(
                identifier=row[0],
                id_type=row[1],
                reason=row[2],
                strikes=row[3],
                quarantined_at=row[4],
                expires_at=row[5],
            )
            self._memory_cache[entry.identifier] = entry
        if rows:
            logger.info("quarantine_loaded count=%d", len(rows))

    def is_quarantined(self, identifier: str) -> bool:
        """Check if a token_id or market_id is currently quarantined."""
        entry = self._memory_cache.get(identifier)
        if entry is None:
            return False
        if time.time() >= entry.expires_at:
            del self._memory_cache[identifier]
            return False
        return True

    def quarantine(
        self,
        identifier: str,
        id_type: str = "token_id",
        reason: str = "http_404",
    ) -> QuarantineEntry:
        """Add or extend quarantine for an identifier.

        Duration escalates with consecutive strikes:
          strike 1: 1× default (1 hour)
          strike 2: 2× default (2 hours)
          strike 3+: min(strike × default, 24 hours)
        """
        now = time.time()
        existing = self._memory_cache.get(identifier)
        strikes = (existing.strikes + 1) if existing else 1

        multiplier = min(strikes, 24)  # Cap at 24× (24 hours if default=1h)
        duration = self.default_duration * multiplier
        expires_at = now + duration

        entry = QuarantineEntry(
            identifier=identifier,
            id_type=id_type,
            reason=reason,
            strikes=strikes,
            quarantined_at=now,
            expires_at=expires_at,
        )

        self._memory_cache[identifier] = entry

        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO market_quarantine "
                "(identifier, id_type, reason, strikes, quarantined_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, id_type, reason, strikes, now, expires_at),
            )

        logger.info(
            "quarantined id=%s type=%s reason=%s strikes=%d duration=%.1fh",
            identifier[:16], id_type, reason, strikes, duration / 3600,
        )
        return entry

    def release(self, identifier: str) -> bool:
        """Manually release an identifier from quarantine."""
        removed = self._memory_cache.pop(identifier, None)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM market_quarantine WHERE identifier = ?",
                (identifier,),
            )
        if removed:
            logger.info("quarantine_released id=%s", identifier[:16])
        return removed is not None

    def get_quarantined_ids(self, id_type: Optional[str] = None) -> set[str]:
        """Return set of currently quarantined identifiers."""
        now = time.time()
        expired = [
            k for k, v in self._memory_cache.items()
            if v.expires_at <= now
        ]
        for k in expired:
            del self._memory_cache[k]

        if id_type:
            return {
                k for k, v in self._memory_cache.items()
                if v.id_type == id_type
            }
        return set(self._memory_cache.keys())

    def cleanup_expired(self) -> int:
        """Remove expired entries from DB. Returns count removed."""
        now = time.time()
        # Clean memory cache
        expired = [
            k for k, v in self._memory_cache.items()
            if v.expires_at <= now
        ]
        for k in expired:
            del self._memory_cache[k]

        # Clean DB
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM market_quarantine WHERE expires_at <= ?",
                (now,),
            )
            count = cursor.rowcount
        if count:
            logger.info("quarantine_cleanup removed=%d", count)
        return count

    def stats(self) -> dict:
        """Return quarantine statistics."""
        now = time.time()
        active = [v for v in self._memory_cache.values() if v.expires_at > now]
        return {
            "active_count": len(active),
            "token_ids": sum(1 for v in active if v.id_type == "token_id"),
            "market_ids": sum(1 for v in active if v.id_type == "market_id"),
            "max_strikes": max((v.strikes for v in active), default=0),
        }
