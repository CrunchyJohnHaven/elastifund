from __future__ import annotations

from scripts.canonical_truth_writer import (
    build_canonical_truth,
    build_wallet_truth_snapshot_payload,
)


def test_build_canonical_truth_blocks_trade_proof_mismatch() -> None:
    truth = build_canonical_truth(
        wallet="0xabc",
        positions=[],
        closed=[],
        runtime_truth={
            "generated_at": "2026-03-22T18:00:00+00:00",
            "trade_proof": {
                "proof_status": "no_fill_yet",
                "latest_filled_trade_at": "2026-03-22T17:55:00+00:00",
            },
        },
        finance_gate={},
        initial_deposit=100.0,
    )

    assert truth["truth_status"] == "blocked"
    assert "trade_proof_latest_fill_conflicts_with_no_fill_yet" in truth["truth_mismatches"]
    assert truth["capital_live"] is False


def test_build_canonical_truth_degraded_when_runtime_truth_missing_age() -> None:
    truth = build_canonical_truth(
        wallet="0xabc",
        positions=[],
        closed=[],
        runtime_truth={},
        finance_gate={},
        initial_deposit=100.0,
    )

    assert truth["truth_status"] in {"degraded", "blocked"}


def test_build_canonical_truth_prefers_remote_wallet_counts(monkeypatch) -> None:
    monkeypatch.setattr("scripts.canonical_truth_writer._read_btc5_deploy_mode", lambda: "live_stage1")

    truth = build_canonical_truth(
        wallet="0xabc",
        positions=[],
        closed=[{"realizedPnl": "12.34"}],
        runtime_truth={
            "generated_at": "2026-03-23T12:55:00+00:00",
            "agent_run_mode": "live",
            "execution_mode": "shadow",
            "allow_order_submission": False,
            "accounting_reconciliation": {
                "remote_wallet_counts": {
                    "free_collateral_usd": 1095.822387,
                    "total_wallet_value_usd": 1162.8814,
                }
            },
        },
        finance_gate={},
        initial_deposit=100.0,
    )

    assert truth["closed_pnl_usd"] == 12.34
    assert truth["estimated_total_value_usd"] == 1162.8814
    assert truth["available_cash_usd"] == 1095.8224
    assert truth["estimated_total_value_method"] == "remote_wallet_counts"
    assert truth["control_posture"] == "blocked"
    assert truth["capital_live"] is False


def test_build_wallet_truth_snapshot_payload_surfaces_hash_and_blockers() -> None:
    payload = build_wallet_truth_snapshot_payload(
        {
            "checked_at": "2026-03-24T08:20:00Z",
            "wallet_address": "0xabc",
            "control_posture": "blocked",
            "truth_status": "blocked",
            "open_positions_count": 1,
            "closed_positions_count": 5,
            "estimated_total_value_usd": 1106.78,
            "available_cash_usd": 1059.0,
            "capital_live": False,
            "blockers": ["runtime_truth_stale"],
            "truth_mismatches": ["wallet_balance_drift"],
            "btc5_deploy_mode": "shadow",
            "execution_mode": "shadow",
            "agent_run_mode": "shadow",
            "estimated_total_value_method": "remote_wallet_counts",
            "runtime_truth_age_seconds": 120.0,
        }
    )

    assert payload["snapshot_id"]
    assert payload["truth_status"] == "blocked"
    assert payload["blockers"] == ["runtime_truth_stale"]
    assert payload["mismatches"] == ["wallet_balance_drift"]
