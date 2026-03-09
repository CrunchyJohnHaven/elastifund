from __future__ import annotations

from bot.polymarket_clob import (
    micro_usdc_to_usd,
    select_signature_probe,
    signature_type_candidates,
)


def test_signature_type_candidates_prefers_configured_value() -> None:
    assert signature_type_candidates(2) == [2, 1, 0]
    assert signature_type_candidates("1") == [1, 2, 0]
    assert signature_type_candidates("bad") == [1, 2, 0]


def test_select_signature_probe_prefers_positive_balance() -> None:
    selected = select_signature_probe(
        [
            {"signature_type": 2, "auth_ok": True, "balance_usd": 0.0},
            {"signature_type": 1, "auth_ok": True, "balance_usd": 197.85},
            {"signature_type": 0, "auth_ok": False, "balance_usd": 0.0},
        ],
        configured_signature_type=2,
    )

    assert selected["signature_type"] == 1


def test_select_signature_probe_falls_back_to_configured_auth_mode() -> None:
    selected = select_signature_probe(
        [
            {"signature_type": 2, "auth_ok": True, "balance_usd": 0.0},
            {"signature_type": 1, "auth_ok": True, "balance_usd": 0.0},
        ],
        configured_signature_type=2,
    )

    assert selected["signature_type"] == 2


def test_micro_usdc_to_usd_scales_balance() -> None:
    assert micro_usdc_to_usd("197852208") == 197.852208
    assert micro_usdc_to_usd(None) == 0.0
