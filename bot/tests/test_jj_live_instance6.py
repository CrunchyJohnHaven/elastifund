#!/usr/bin/env python3
"""Regression tests for Stream 6 live-bot wiring."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.jj_live import (  # noqa: E402
    AdaptivePlattCalibrator,
    TradeDatabase,
    build_trade_record,
    extract_probability_fields,
)


def test_extract_probability_fields_keeps_raw_and_calibrated_separate():
    fields = extract_probability_fields(
        {
            "probability": 0.72,
            "calibrated_probability": 0.61,
        }
    )

    assert fields["raw_prob"] == 0.72
    assert fields["calibrated_prob"] == 0.61
    assert fields["execution_prob"] == 0.61
    assert fields["already_calibrated"] is False


def test_build_trade_record_preserves_stream6_metadata():
    record = build_trade_record(
        {
            "question": "Will X happen?",
            "direction": "buy_yes",
            "estimated_prob": 0.61,
            "raw_prob": 0.72,
            "calibrated_prob": 0.61,
            "edge": 0.11,
            "confidence": 0.8,
            "source": "llm",
            "n_models": 3,
            "model_spread": 0.08,
            "model_stddev": 0.04,
            "agreement": 0.81,
            "kelly_multiplier": 1.0,
            "disagreement_kelly_fraction": 0.25,
            "models_agree": True,
            "search_context_used": True,
            "counter_shift": 0.07,
            "counter_fragile": False,
            "platt_mode": "rolling",
            "platt_a": 0.55,
            "platt_b": -0.31,
        },
        market_id="m1",
        category="politics",
        entry_price=0.52,
        position_size_usd=1.25,
        token_id="token-1",
    )

    assert record["raw_prob"] == 0.72
    assert record["calibrated_prob"] == 0.61
    assert record["source"] == "llm"
    assert record["n_models"] == 3
    assert record["models_agree"] is True
    assert record["search_context_used"] is True
    assert record["platt_mode"] == "rolling"
    assert record["platt_a"] == 0.55
    assert record["platt_b"] == -0.31


def test_trade_db_logs_stream6_fields_and_calibrator_ignores_untracked_rows(tmp_path):
    db = TradeDatabase(tmp_path / "jj_instance6.db")

    columns = {
        row[1]
        for row in db.conn.execute("PRAGMA table_info(trades)").fetchall()
    }
    for name in {
        "source",
        "n_models",
        "model_spread",
        "model_stddev",
        "agreement",
        "kelly_multiplier",
        "disagreement_kelly_fraction",
        "models_agree",
        "search_context_used",
        "counter_shift",
        "counter_fragile",
        "platt_mode",
        "platt_a",
        "platt_b",
    }:
        assert name in columns

    tracked_id = db.log_trade(
        {
            "market_id": "tracked",
            "question": "Tracked market",
            "direction": "buy_yes",
            "entry_price": 0.50,
            "raw_prob": 0.74,
            "calibrated_prob": 0.62,
            "edge": 0.12,
            "position_size_usd": 1.00,
            "source": "llm",
            "n_models": 3,
            "agreement": 0.84,
            "disagreement_kelly_fraction": 0.20,
            "counter_shift": 0.04,
            "counter_fragile": False,
            "platt_mode": "rolling",
            "platt_a": 0.58,
            "platt_b": -0.35,
        }
    )
    db.log_trade(
        {
            "market_id": "untracked",
            "question": "Legacy row without platt metadata",
            "direction": "buy_yes",
            "entry_price": 0.50,
            "raw_prob": 0.91,
            "calibrated_prob": 0.66,
            "edge": 0.16,
            "position_size_usd": 1.00,
            "source": "wallet_flow",
        }
    )

    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        """
        UPDATE trades
        SET outcome = ?, resolution_price = ?, resolved_at = ?
        WHERE market_id = ?
        """,
        ("won", 1.0, now, "tracked"),
    )
    db.conn.execute(
        """
        UPDATE trades
        SET outcome = ?, resolution_price = ?, resolved_at = ?
        WHERE market_id = ?
        """,
        ("won", 1.0, now, "untracked"),
    )
    db.conn.commit()

    row = db.conn.execute(
        """
        SELECT raw_prob, calibrated_prob, source, n_models, agreement,
               disagreement_kelly_fraction, platt_mode, platt_a, platt_b
        FROM trades
        WHERE id = ?
        """,
        (tracked_id,),
    ).fetchone()

    assert row["raw_prob"] == 0.74
    assert row["calibrated_prob"] == 0.62
    assert row["source"] == "llm"
    assert row["n_models"] == 3
    assert row["agreement"] == 0.84
    assert row["disagreement_kelly_fraction"] == 0.20
    assert row["platt_mode"] == "rolling"
    assert row["platt_a"] == 0.58
    assert row["platt_b"] == -0.35

    calibrator = AdaptivePlattCalibrator(db, enabled=True)
    recent = calibrator._recent_resolved_rows()

    assert recent == [(0.74, 1)]

