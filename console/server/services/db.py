from __future__ import annotations
import os
import sqlite3
import logging
from typing import Optional
from server.config import REPO_ROOT, DATA_DIR

logger = logging.getLogger(__name__)

_DB_CANDIDATES = [
    os.path.join(DATA_DIR, 'btc_5min_maker.db'),
    os.path.join(DATA_DIR, 'local_btc_5min_maker.db'),
    os.path.join(REPO_ROOT, 'bot', 'data', 'btc_5min_maker.db'),
    os.path.join(REPO_ROOT, 'btc_5min_maker.db'),
]


def _find_db() -> Optional[str]:
    for candidate in _DB_CANDIDATES:
        if os.path.isfile(candidate):
            logger.debug(f"Found DB at {candidate}")
            return candidate
    logger.warning("btc_5min_maker.db not found in any candidate location")
    return None


def _get_connection() -> Optional[sqlite3.Connection]:
    path = _find_db()
    if not path:
        return None
    try:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to DB: {e}")
        return None


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def get_cohort_fills(cohort_start_ts: int) -> list[dict]:
    conn = _get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM window_trades
            WHERE direction = 'DOWN'
              AND order_status LIKE 'live_%'
              AND order_status NOT LIKE '%shadow%'
              AND order_status NOT LIKE '%skip%'
              AND resolved_side IS NOT NULL
              AND decision_ts >= ?
            ORDER BY decision_ts ASC
            """,
            (cohort_start_ts,),
        )
        rows = cursor.fetchall()
        return _rows_to_dicts(rows)
    except Exception as e:
        logger.error(f"get_cohort_fills error: {e}")
        return []
    finally:
        conn.close()


def get_recent_fills(limit: int = 50) -> list[dict]:
    conn = _get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM window_trades
            ORDER BY decision_ts DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return _rows_to_dicts(rows)
    except Exception as e:
        logger.error(f"get_recent_fills error: {e}")
        return []
    finally:
        conn.close()


def get_pnl_timeseries() -> list[dict]:
    conn = _get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT decision_ts, pnl, direction, order_status, resolved_side
            FROM window_trades
            WHERE resolved_side IS NOT NULL
            ORDER BY decision_ts ASC
            """
        )
        rows = cursor.fetchall()
        result = []
        cumulative = 0.0
        for row in rows:
            d = dict(row)
            pnl = d.get('pnl') or 0.0
            cumulative += float(pnl)
            d['cumulative_pnl'] = round(cumulative, 4)
            result.append(d)
        return result
    except Exception as e:
        logger.error(f"get_pnl_timeseries error: {e}")
        return []
    finally:
        conn.close()


def get_fill_count() -> int:
    conn = _get_connection()
    if not conn:
        return 0
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM window_trades")
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"get_fill_count error: {e}")
        return 0
    finally:
        conn.close()
