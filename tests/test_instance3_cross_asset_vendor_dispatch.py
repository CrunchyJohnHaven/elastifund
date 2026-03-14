from __future__ import annotations

import json
from pathlib import Path

from src.cross_asset_vendor_dispatch import (
    FeatureFlags,
    build_instance_artifact,
    emit_finance_action_queue,
    build_vendor_stack,
    ensure_history_store,
    insert_reference_bars,
    summarize_history_store,
)


def test_vendor_stack_recommends_coinapi_when_1m_ready_and_1s_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD", "1000")
    flags = FeatureFlags(
        coingecko_enabled=True,
        coinapi_enabled=False,
        glassnode_enabled=False,
        nansen_enabled=False,
        auto_buy_coinapi=True,
        backfill_days=30,
    )
    coverage = {
        "assets": [],
        "complete_assets_1m": 5,
        "complete_assets_1s": 0,
        "missing_assets_1m": [],
        "missing_assets_1s": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
    }
    finance_latest = {
        "finance_gate_pass": True,
        "finance_gate": {"reason": "queue_ready"},
        "cycle_budget_ledger": {"dollars": {"single_action_cap_usd": 250.0}},
    }
    action_queue = {"actions": []}

    report = build_vendor_stack(
        coverage=coverage,
        finance_latest=finance_latest,
        action_queue=action_queue,
        flags=flags,
    )

    assert report["recommendation"] == "buy_coinapi_startup"
    assert report["recommended_vendor"]["vendor"] == "coinapi"
    assert report["monthly_commitment_impact_usd"] == 79.0


def test_vendor_stack_holds_when_finance_gate_fails(monkeypatch) -> None:
    monkeypatch.setenv("JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD", "1000")
    flags = FeatureFlags(
        coingecko_enabled=True,
        coinapi_enabled=False,
        glassnode_enabled=False,
        nansen_enabled=False,
        auto_buy_coinapi=True,
        backfill_days=30,
    )
    coverage = {
        "assets": [],
        "complete_assets_1m": 5,
        "complete_assets_1s": 0,
        "missing_assets_1m": [],
        "missing_assets_1s": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
    }
    finance_latest = {
        "finance_gate_pass": False,
        "finance_gate": {"reason": "policy_hold"},
        "cycle_budget_ledger": {"dollars": {"single_action_cap_usd": 250.0}},
    }
    action_queue = {"actions": []}

    report = build_vendor_stack(
        coverage=coverage,
        finance_latest=finance_latest,
        action_queue=action_queue,
        flags=flags,
    )

    assert report["recommendation"] == "hold_free_stack"
    assert "finance_gate_blocked:policy_hold" in report["block_reasons"]


def test_history_store_summary_marks_1m_ready_and_1s_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "cross_asset_history.db"
    ensure_history_store(db_path)
    inserted = insert_reference_bars(
        db_path,
        [
            {
                "venue": "binance",
                "asset": "BTC",
                "interval": "1m",
                "open_time_ms": 1_700_000_000_000,
                "close_time_ms": 1_700_000_060_000,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100.0,
                "source": "test",
                "inserted_at": "2026-03-11T00:00:00+00:00",
            }
        ],
    )
    assert inserted == 1

    summary = summarize_history_store(db_path, assets=("BTC",))

    assert summary["complete_assets_1m"] == 1
    assert summary["complete_assets_1s"] == 0
    assert summary["assets"][0]["intervals"]["1m"]["status"] == "ready"
    assert summary["assets"][0]["intervals"]["1s"]["status"] == "missing"


def test_instance_artifact_uses_vendor_stack_and_state_improvement() -> None:
    artifact = build_instance_artifact(
        coverage={
            "assets": [
                {
                    "asset": asset,
                    "intervals": {
                        "1m": {"status": "ready", "row_count": 10, "venues": ["binance"]},
                        "1s": {"status": "missing", "row_count": 0, "venues": []},
                    },
                }
                for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE")
            ],
            "complete_assets_1m": 5,
            "complete_assets_1s": 0,
            "missing_assets_1m": [],
            "missing_assets_1s": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
        },
        vendor_stack={
            "recommendation": "buy_coinapi_startup",
            "recommendation_reason": "need 1s history",
            "block_reasons": ["1s_history_missing_on_free_stack"],
            "recommended_vendor": {"vendor": "coinapi", "expected_arr_lift_bps": 180},
        },
        finance_latest={"finance_gate_pass": True},
        state_improvement={"coinapi_enabled": False, "coinapi_configured": False},
    )

    assert artifact["candidate_delta_arr_bps"] == 180
    assert artifact["finance_gate_pass"] is True
    assert artifact["expected_improvement_velocity_delta"] == 0.20
    assert artifact["arr_confidence_score"] == 0.76
    assert artifact["block_reasons"] == ["coinapi_not_enabled_or_not_configured"]
    assert artifact["details"]["one_second_coverage_by_asset"]["BTC"]["row_count"] == 0


def test_emit_finance_action_queue_is_idempotent() -> None:
    finance_latest = {"finance_gate_pass": True}
    vendor_stack = {
        "recommendation": "buy_coinapi_startup",
        "recommendation_reason": "Need 1-second history.",
        "monthly_commitment_impact_usd": 79.0,
        "block_reasons": [],
    }
    action_queue = {"actions": []}

    updated, emission = emit_finance_action_queue(
        action_queue=action_queue,
        finance_latest=finance_latest,
        vendor_stack=vendor_stack,
    )
    repeated, repeated_emission = emit_finance_action_queue(
        action_queue=updated,
        finance_latest=finance_latest,
        vendor_stack=vendor_stack,
    )

    assert emission["emitted"] is True
    assert repeated_emission["emitted"] is False
    actions = [row for row in repeated["actions"] if row["action_key"] == "subscribe::coinapi_startup"]
    assert len(actions) == 1
    assert actions[0]["monthly_commitment_usd"] == 79.0
