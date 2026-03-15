from __future__ import annotations

from datetime import datetime, timezone

from scripts.crypto_category_audit import (
    build_crypto_category_audit,
    classify_crypto_market,
    market_passes_thresholds,
)


def _market(question: str, *, slug: str, tags: list[str], price: float = 0.55) -> dict:
    return {
        "id": slug,
        "conditionId": slug,
        "slug": slug,
        "question": question,
        "tags": tags,
        "outcomePrices": [price, round(1.0 - price, 4)],
        "endDate": "2026-03-09T12:00:00+00:00",
        "active": True,
        "acceptingOrders": True,
        "closed": False,
    }


def test_classify_crypto_market_distinguishes_candles_altcoins_and_degenerate() -> None:
    assert classify_crypto_market(
        _market(
            "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-1",
            tags=["crypto"],
        )
    ) == "btc_candle"
    assert classify_crypto_market(
        _market(
            "Will Ethereum be above $4,000 on March 31?",
            slug="eth-above-4000",
            tags=["crypto"],
        )
    ) == "eth_candle"
    assert classify_crypto_market(
        _market(
            "Will Solana hit $300 by June 30?",
            slug="sol-hit-300",
            tags=["crypto"],
        )
    ) == "altcoin"
    assert classify_crypto_market(
        _market(
            "Will Pump.fun perform an airdrop by March 31?",
            slug="pumpfun-airdrop",
            tags=["crypto", "pre-market"],
        )
    ) == "meme_degenerate"


def test_market_passes_thresholds_uses_price_window_and_horizon() -> None:
    now = datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc)
    assert market_passes_thresholds(
        _market(
            "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-1",
            tags=["crypto"],
            price=0.55,
        ),
        now=now,
    ) is True
    assert market_passes_thresholds(
        _market(
            "Bitcoin Up or Down - March 12, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-2",
            tags=["crypto"],
            price=0.95,
        )
        | {"endDate": "2026-03-12T12:00:00+00:00"},
        now=now,
    ) is False


def test_build_crypto_category_audit_flags_non_btc_tradeable_markets() -> None:
    now = datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc)
    payload = build_crypto_category_audit(
        [
            _market(
                "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
                slug="btc-updown-5m-1",
                tags=["crypto"],
                price=0.55,
            ),
            _market(
                "Will Solana hit $300 by June 30?",
                slug="sol-hit-300",
                tags=["crypto"],
                price=0.40,
            ),
        ],
        now=now,
        fast_overlay=[],
    )

    assert payload["classification_counts"]["btc_candle"] == 1
    assert payload["classification_counts"]["altcoin"] == 1
    assert len(payload["tradeable_at_008"]) == 2
    assert payload["recommendation"] == "ADD_SUBCATEGORY_FILTER"
