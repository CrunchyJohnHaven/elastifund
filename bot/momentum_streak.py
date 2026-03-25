from __future__ import annotations

import sqlite3
from pathlib import Path


def detect_streak(db_path: str | Path) -> tuple[str | None, int]:
    """Return (direction, streak_length) for the latest resolved-side streak.

    The streak is measured over the most recent rows in ``window_trades`` by
    scanning ``resolved_side`` values from newest to oldest and counting the
    consecutive matching run at the top. Only UP/DOWN streaks with length >= 3
    are returned; otherwise ``(None, 0)`` is returned.
    """

    path = Path(db_path)
    if not path.exists():
        return None, 0

    try:
        conn = sqlite3.connect(str(path), timeout=30)
    except sqlite3.Error:
        return None, 0

    try:
        # Exclude pending_reservation rows (inserted by reserve_window before any order is placed)
        # so they don't interfere with streak detection. Fall back to unfiltered query if the
        # order_status column does not exist (e.g. in test environments with minimal schemas).
        try:
            rows = conn.execute(
                """
                SELECT resolved_side
                FROM window_trades
                WHERE order_status != 'pending_reservation'
                ORDER BY window_start_ts DESC
                LIMIT 10
                """
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                """
                SELECT resolved_side
                FROM window_trades
                ORDER BY window_start_ts DESC
                LIMIT 10
                """
            ).fetchall()
    except sqlite3.Error:
        return None, 0
    finally:
        conn.close()

    if not rows:
        return None, 0

    head = str(rows[0][0] or "").strip().upper()
    if head not in {"UP", "DOWN"}:
        return None, 0

    streak_length = 0
    for row in rows:
        side = str(row[0] or "").strip().upper()
        if side != head:
            break
        streak_length += 1

    if streak_length >= 3:
        return head, streak_length
    return None, 0
