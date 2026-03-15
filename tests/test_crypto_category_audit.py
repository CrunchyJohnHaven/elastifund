from __future__ import annotations

from datetime import datetime, timezone

from scripts.crypto_category_audit import build_crypto_category_audit, classify_audit_category


def _market(
    market_id: str,
    question: str,
    *,
    slug: str,
    tags: list[str],
    yes_price: float = 0.55,
    resolution_hours: float = 2.0,
    source: str = "test",
) -> dict:
    return {
        "id": market_id,
        "conditionId": market_id,
        "slug": slug,
        "question": question,
        "tags": tags,
        "yes_price": yes_price,
        "resolution_hours": resolution_hours,
        "source": source,
    }


def test_classify_audit_category_distinguishes_task_classes() -> None:
    assert classify_audit_category(
        _market(
            "btc-1",
            "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-1",
            tags=["crypto"],
        )
    ) == "btc_candle"
    assert classify_audit_category(
        _market(
            "eth-1",
            "Ethereum Up or Down - March 9, 12:00PM-12:15PM ET",
            slug="eth-updown-15m-1",
            tags=["crypto"],
        )
    ) == "eth_candle"
    assert classify_audit_category(
        _market(
            "meme-1",
            "Will Pump.fun perform an airdrop by March 31?",
            slug="pumpfun-airdrop",
            tags=["crypto", "pre-market"],
        )
    ) == "altcoin_meme"
    assert classify_audit_category(
        _market(
            "other-1",
            "Will USDC hit 50% of USDT market cap by December 31, 2026?",
            slug="usdc-vs-usdt",
            tags=["crypto", "stablecoins"],
        )
    ) == "crypto_other"


def test_build_crypto_category_audit_separates_broad_universe_from_fast_tradeable_set() -> None:
    now = datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc)
    broad_markets = [
        _market(
            "btc-1",
            "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-1",
            tags=["crypto"],
        ),
        _market(
            "eth-1",
            "Ethereum Up or Down - March 9, 12:00PM-12:15PM ET",
            slug="eth-updown-15m-1",
            tags=["crypto"],
        ),
        _market(
            "meme-1",
            "Will Pump.fun perform an airdrop by March 31?",
            slug="pumpfun-airdrop",
            tags=["crypto", "pre-market"],
            resolution_hours=24.0,
        ),
        _market(
            "other-1",
            "Will USDC hit 50% of USDT market cap by December 31, 2026?",
            slug="usdc-vs-usdt",
            tags=["crypto", "stablecoins"],
            resolution_hours=48.0,
        ),
    ]
    fast_overlay = [
        _market(
            "btc-1",
            "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-1",
            tags=["crypto"],
            source="fast_market_discovery",
        ),
        _market(
            "eth-1",
            "Ethereum Up or Down - March 9, 12:00PM-12:15PM ET",
            slug="eth-updown-15m-1",
            tags=["crypto"],
            source="fast_market_discovery",
        ),
    ]

    payload = build_crypto_category_audit(
        broad_markets,
        now=now,
        fast_overlay=fast_overlay,
        tagged_event_count=4,
    )

    assert payload["classification_schema"] == [
        "btc_candle",
        "eth_candle",
        "altcoin_meme",
        "crypto_other",
    ]
    broad = payload["broad_crypto_tagged_universe"]
    assert broad["tagged_event_count"] == 4
    assert broad["market_count"] == 4
    assert broad["counts_by_class"] == {
        "btc_candle": 1,
        "eth_candle": 1,
        "altcoin_meme": 1,
        "crypto_other": 1,
    }

    fast = payload["fast_market_tradeable_set"]
    assert fast["discovered_market_count"] == 2
    assert fast["tradeable_market_count"] == 2
    assert fast["counts_by_class"] == {
        "btc_candle": 1,
        "eth_candle": 1,
        "altcoin_meme": 0,
        "crypto_other": 0,
    }
    assert {row["market_id"] for row in fast["markets"]} == {"btc-1", "eth-1"}
    assert payload["recommendation"] == "APPROVE_BTC_CANDLES_ONLY"


def test_build_crypto_category_audit_flags_non_candle_fast_market_entries() -> None:
    now = datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc)
    broad_markets = [
        _market(
            "btc-1",
            "Bitcoin Up or Down - March 9, 12:00PM-12:05PM ET",
            slug="btc-updown-5m-1",
            tags=["crypto"],
        ),
        _market(
            "sol-1",
            "Will Solana hit $300 by June 30?",
            slug="solana-hit-300",
            tags=["crypto"],
            resolution_hours=36.0,
        ),
    ]
    fast_overlay = [
        _market(
            "sol-1",
            "Will Solana hit $300 by June 30?",
            slug="solana-hit-300",
            tags=["crypto"],
            resolution_hours=36.0,
            source="fast_market_discovery",
        )
    ]

    payload = build_crypto_category_audit(
        broad_markets,
        now=now,
        fast_overlay=fast_overlay,
        tagged_event_count=2,
    )

    fast = payload["fast_market_tradeable_set"]
    assert fast["counts_by_class"]["altcoin_meme"] == 1
    assert payload["recommendation"] == "ADD_SUBCATEGORY_FILTER"
