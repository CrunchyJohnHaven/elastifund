from __future__ import annotations

from scripts.canonical_truth_writer import build_canonical_truth


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
