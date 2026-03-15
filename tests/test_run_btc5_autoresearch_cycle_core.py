from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import scripts.run_btc5_autoresearch_cycle_core as core


def _candidate(
    *,
    name: str,
    max_abs_delta: float,
    up: float,
    down: float,
    family: str = "global_profile",
) -> dict[str, object]:
    return {
        "candidate_family": family,
        "profile": {
            "name": name,
            "max_abs_delta": max_abs_delta,
            "up_max_buy_price": up,
            "down_max_buy_price": down,
        },
        "base_profile": {
            "name": name,
            "max_abs_delta": max_abs_delta,
            "up_max_buy_price": up,
            "down_max_buy_price": down,
        },
        "session_overrides": [],
    }


def test_dedupe_candidate_evaluations_skips_semantic_duplicates() -> None:
    current = _candidate(name="current", max_abs_delta=0.00015, up=0.49, down=0.51)
    duplicate = _candidate(name="duplicate_name_only", max_abs_delta=0.00015, up=0.49, down=0.51)
    unique = _candidate(name="unique", max_abs_delta=0.00010, up=0.48, down=0.50)
    dedup_index = {"version": 1, "seen": {}}

    kept, skipped, kept_hashes = core._dedupe_candidate_evaluations(
        [
            ("active_profile", current),
            ("global_best_candidate", duplicate),
            ("regime_best_candidate", unique),
        ],
        dedup_index=dedup_index,
    )

    assert [source for source, _ in kept] == ["active_profile", "regime_best_candidate"]
    assert len(kept_hashes) == 2
    assert skipped[0]["source"] == "global_best_candidate"
    assert skipped[0]["reason"] == "duplicate_in_cycle"
    assert len(dedup_index["seen"]) == 2


def test_fill_feedback_summary_uses_db_rows_since_last_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "btc_5min_maker.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE window_trades (
                window_start_ts INTEGER,
                updated_at TEXT,
                created_at TEXT,
                order_status TEXT,
                direction TEXT,
                won INTEGER,
                pnl_usd REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO window_trades(window_start_ts, updated_at, created_at, order_status, direction, won, pnl_usd)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (100, "2026-03-15T00:00:00+00:00", "2026-03-15T00:00:00+00:00", "live_filled", "DOWN", 1, 1.25),
                (110, "2026-03-15T00:05:00+00:00", "2026-03-15T00:05:00+00:00", "skip_price_outside_guardrails", "DOWN", None, 0.0),
                (120, "2026-03-15T00:10:00+00:00", "2026-03-15T00:10:00+00:00", "live_filled", "UP", 0, -0.50),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    feedback_state = tmp_path / "feedback_state.json"
    feedback_state.write_text(
        json.dumps(
            {
                "last_cycle_completed_at": "2026-03-14T23:59:00+00:00",
                "last_window_start_ts": 105,
                "last_updated_at": "2026-03-15T00:02:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cycles_jsonl = tmp_path / "autoresearch_cycles.jsonl"
    best_candidate = {
        "historical": {"replay_live_filled_rows": 20, "replay_live_filled_pnl_usd": 10.0},
        "monte_carlo": {"profit_probability": 0.55},
    }
    selected_frontier_item = {"fill_retention_ratio": 0.45}
    decision = {"fill_retention_ratio": 0.40}

    feedback, state_after = core._fill_feedback_summary(
        db_path=db_path,
        feedback_state_path=feedback_state,
        cycles_jsonl_path=cycles_jsonl,
        best_candidate=best_candidate,
        selected_frontier_item=selected_frontier_item,
        decision=decision,
        generated_at="2026-03-15T00:15:00+00:00",
    )

    assert feedback["actual_metrics"]["fills"] == 1
    assert feedback["actual_metrics"]["total_rows_considered"] == 2
    assert feedback["actual_metrics"]["fill_rate"] == 0.5
    assert feedback["predicted_metrics"]["fill_rate"] == 0.45
    assert feedback["metric_deltas"]["fill_rate"] == 0.05
    assert state_after["last_window_start_ts"] == 120
