import sqlite3
from pathlib import Path

from bot.momentum_streak import detect_streak


def _seed_rows(db_path: Path, resolved_sides: list[str | None]) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS window_trades (
                window_start_ts INTEGER NOT NULL,
                resolved_side TEXT
            )
            """
        )
        start_ts = 1_700_000_000
        for idx, side in enumerate(resolved_sides):
            conn.execute(
                "INSERT INTO window_trades(window_start_ts, resolved_side) VALUES (?, ?)",
                (start_ts + idx, side),
            )
        conn.commit()


def test_detect_streak_returns_matching_run_from_latest_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "streak.db"
    _seed_rows(db_path, ["DOWN", "UP", "UP", "UP", "UP"])

    direction, streak_length = detect_streak(db_path)

    assert direction == "UP"
    assert streak_length == 4


def test_detect_streak_returns_none_when_run_shorter_than_three(tmp_path: Path) -> None:
    db_path = tmp_path / "streak.db"
    _seed_rows(db_path, ["DOWN", "UP", "UP"])

    direction, streak_length = detect_streak(db_path)

    assert direction is None
    assert streak_length == 0


def test_detect_streak_returns_none_when_latest_side_unresolved(tmp_path: Path) -> None:
    db_path = tmp_path / "streak.db"
    _seed_rows(db_path, ["UP", "UP", "UP", None])

    direction, streak_length = detect_streak(db_path)

    assert direction is None
    assert streak_length == 0
