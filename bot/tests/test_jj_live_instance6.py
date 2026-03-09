#!/usr/bin/env python3
"""Regression tests for Stream 6 live-bot wiring."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.jj_live import (  # noqa: E402
    AdaptivePlattCalibrator,
    JJLive,
    RollingNotionalBudgetTracker,
    TradeDatabase,
    build_trade_record,
    clob_min_order_size,
    extract_signal_source_components,
    extract_probability_fields,
    signal_has_source,
)


def test_jj_live_imports_after_root_src_is_preloaded():
    repo_root = Path(__file__).resolve().parent.parent.parent
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(repo_root)
        if not existing_pythonpath
        else f"{repo_root}{os.pathsep}{existing_pythonpath}"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path\n"
                "import src\n"
                f"repo_root = Path({str(repo_root)!r})\n"
                "assert Path(src.__file__).resolve() == repo_root / 'src' / '__init__.py'\n"
                "import bot.jj_live as jj_live\n"
                "assert str((repo_root / 'polymarket-bot' / 'src').resolve()) in "
                "{str(Path(p).resolve()) for p in src.__path__}\n"
                "assert jj_live.MarketScanner.__module__ == 'src.scanner'\n"
                "assert jj_live.ClaudeAnalyzer.__module__ == 'src.claude_analyzer'\n"
            ),
        ],
        capture_output=True,
        check=False,
        cwd=repo_root,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout


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


def test_clob_min_order_size_enforces_five_dollar_notional():
    assert clob_min_order_size(0.93) == 5.38
    assert clob_min_order_size(0.30) == 16.67


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
            "source_components": ["llm", "wallet_flow"],
            "source_combo": "llm+wallet_flow",
            "n_sources": 2,
            "n_models": 3,
            "model_spread": 0.08,
            "model_stddev": 0.04,
            "agreement": 0.81,
            "confidence_multiplier": 1.0,
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
    assert record["source_combo"] == "llm+wallet_flow"
    assert record["source_components"] == ["llm", "wallet_flow"]
    assert record["source_count"] == 2
    assert record["n_models"] == 3
    assert record["models_agree"] is True
    assert record["search_context_used"] is True
    assert record["kelly_multiplier"] == 1.0
    assert record["platt_mode"] == "rolling"
    assert record["platt_a"] == 0.55
    assert record["platt_b"] == -0.31


def test_signal_source_helpers_preserve_component_sets():
    payload = {
        "source": "llm",
        "source_combo": "llm+wallet_flow",
        "source_components": ["llm", "wallet_flow", "llm"],
    }

    assert extract_signal_source_components(payload) == ["llm", "wallet_flow"]
    assert signal_has_source(payload, "wallet-flow") is True
    assert signal_has_source(payload, "lead_lag") is False


def test_trade_db_logs_stream6_fields_and_calibrator_ignores_untracked_rows(tmp_path):
    db = TradeDatabase(tmp_path / "jj_instance6.db")

    columns = {
        row[1]
        for row in db.conn.execute("PRAGMA table_info(trades)").fetchall()
    }
    for name in {
        "source",
        "source_combo",
        "source_components_json",
        "source_count",
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
            "source_combo": "llm+wallet_flow",
            "source_components": ["llm", "wallet_flow"],
            "source_count": 2,
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
        SELECT raw_prob, calibrated_prob, source, source_combo, source_components_json,
               source_count, n_models, agreement, disagreement_kelly_fraction,
               platt_mode, platt_a, platt_b
        FROM trades
        WHERE id = ?
        """,
        (tracked_id,),
    ).fetchone()

    assert row["raw_prob"] == 0.74
    assert row["calibrated_prob"] == 0.62
    assert row["source"] == "llm"
    assert row["source_combo"] == "llm+wallet_flow"
    assert row["source_components_json"] == "[\"llm\", \"wallet_flow\"]"
    assert row["source_count"] == 2
    assert row["n_models"] == 3
    assert row["agreement"] == 0.84
    assert row["disagreement_kelly_fraction"] == 0.20
    assert row["platt_mode"] == "rolling"
    assert row["platt_a"] == 0.58
    assert row["platt_b"] == -0.35

    breakdown = db.get_source_breakdown(limit=5)
    assert breakdown[0]["source_label"] == "llm+wallet_flow"
    assert breakdown[0]["total_trades"] == 1

    calibrator = AdaptivePlattCalibrator(db, enabled=True)
    recent = calibrator._recent_resolved_rows()

    assert recent == [(0.74, 1)]


def test_pm_campaign_budget_tracker_enforces_rolling_hourly_cap():
    tracker = RollingNotionalBudgetTracker(cap_usd=50.0, window_seconds=3600)

    ok, reason, remaining = tracker.can_spend(30.0, now_ts=1000.0)
    assert ok is True
    assert reason == "pm_campaign_ok"
    assert remaining == 50.0

    tracker.record_spend(30.0, now_ts=1000.0)
    assert tracker.snapshot(now_ts=1001.0)["used_usd"] == 30.0
    assert tracker.snapshot(now_ts=1001.0)["remaining_usd"] == 20.0

    ok, reason, _remaining = tracker.can_spend(25.0, now_ts=1002.0)
    assert ok is False
    assert reason == "pm_campaign_budget_exceeded"

    # First spend is out of window after one hour + 1s, so budget resets.
    ok, reason, _remaining = tracker.can_spend(25.0, now_ts=4601.0)
    assert ok is True
    assert reason == "pm_campaign_ok"


def test_pm_campaign_gate_rejects_long_or_unknown_resolution():
    live = JJLive.__new__(JJLive)
    live.pm_hourly_campaign_enabled = True
    live.pm_campaign_max_resolution_hours = 24.0
    live.pm_campaign_budget = RollingNotionalBudgetTracker(cap_usd=50.0, window_seconds=3600)

    allowed, reason = live._check_pm_campaign_gate(
        signal={"market_id": "m1", "resolution_hours": None},
        size_usd=10.0,
    )
    assert allowed is False
    assert reason == "pm_campaign_resolution_unknown"

    allowed, reason = live._check_pm_campaign_gate(
        signal={"market_id": "m2", "resolution_hours": 26.0},
        size_usd=10.0,
    )
    assert allowed is False
    assert reason == "pm_campaign_resolution_too_long"

    allowed, reason = live._check_pm_campaign_gate(
        signal={"market_id": "m3", "resolution_hours": 12.0},
        size_usd=10.0,
    )
    assert allowed is True
    assert reason == "pm_campaign_ok"
