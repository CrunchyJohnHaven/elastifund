from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.kalshi_intraday_parity import (
    audit_crossvenue_matching,
    build_kalshi_candidate_record,
    horizon_bucket,
    inspect_kalshi_market_rejection_reason,
)


def test_horizon_bucket_boundaries() -> None:
    assert horizon_bucket(0.5) == "3h"
    assert horizon_bucket(3.0) == "3h"
    assert horizon_bucket(3.01) == "24h"
    assert horizon_bucket(24.0) == "24h"
    assert horizon_bucket(24.01) is None


def test_build_kalshi_candidate_record_schema() -> None:
    now = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)
    market = {
        "ticker": "KXBTC-26MAR09-H1300",
        "title": "Will Bitcoin be above $85,000 at 1 PM ET?",
        "yes_bid": 45,
        "yes_ask": 47,
        "no_bid": 53,
        "no_ask": 55,
        "volume": 1250,
        "close_time": (now + timedelta(hours=1)).isoformat(),
    }

    candidate = build_kalshi_candidate_record(market, now=now)
    assert candidate is not None
    assert candidate["venue"] == "kalshi"
    assert candidate["ticker"] == "KXBTC-26MAR09-H1300"
    assert candidate["horizon_bucket"] == "3h"
    assert candidate["asset"] == "BTC"
    assert candidate["fee_model"].startswith("kalshi_taker_fee")
    assert isinstance(candidate["route_score_inputs"], dict)
    assert "liquidity_score" in candidate["route_score_inputs"]
    assert isinstance(candidate["route_score"], float)


def test_build_candidate_supports_text_horizon_inference() -> None:
    now = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)
    market = {
        "ticker": "KXBTC-15M-TEST",
        "title": "Will BTC be up in the next 15m?",
        "yes_bid": 40,
        "yes_ask": 44,
        "no_bid": 56,
        "no_ask": 60,
        "volume": 900,
    }
    candidate = build_kalshi_candidate_record(market, now=now)
    assert candidate is not None
    assert candidate["horizon_bucket"] == "3h"


def test_crossvenue_audit_classifies_failure_reasons() -> None:
    kalshi_candidates = [
        {
            "venue": "kalshi",
            "ticker": "KXBTC-1",
            "title": "Will Bitcoin close above 85k by 1 PM?",
            "resolution_time": "2026-03-09T13:00:00+00:00",
            "asset": "BTC",
            "spread": 0.2,
            "visible_volume": 50.0,
            "liquidity_ok": False,
            "contract_shape": "binary",
        },
        {
            "venue": "kalshi",
            "ticker": "KXETH-1",
            "title": "Will Ethereum close above 5000 by 1 PM?",
            "resolution_time": "2026-03-09T13:00:00+00:00",
            "asset": "ETH",
            "spread": 0.04,
            "visible_volume": 500.0,
            "liquidity_ok": True,
            "contract_shape": "binary",
        },
    ]
    polymarket_candidates = [
        {
            "venue": "polymarket",
            "ticker": "poly-btc-1",
            "title": "Will Bitcoin close above $85k at 1 PM?",
            "resolution_time": "2026-03-09T15:00:00+00:00",
            "asset": "BTC",
            "contract_shape": "range",
        },
        {
            "venue": "polymarket",
            "ticker": "poly-eth-1",
            "title": "Will Ethereum close above $5000 at 1 PM?",
            "resolution_time": "2026-03-09T13:00:00+00:00",
            "asset": "ETH",
            "contract_shape": "binary",
        },
    ]

    audit = audit_crossvenue_matching(
        kalshi_candidates=kalshi_candidates,
        polymarket_candidates=polymarket_candidates,
    )
    summary = audit["summary"]
    assert summary["kalshi_candidate_count"] == 2
    assert summary["liquidity_filter_failures"] >= 1
    assert summary["resolution_normalization_failures"] >= 1
    assert summary["contract_shape_mismatch_failures"] >= 1


def test_rejection_reason_classifies_missing_resolution() -> None:
    now = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)
    market = {
        "ticker": "KXBTC-UNKNOWN",
        "title": "Will Bitcoin reach 90k eventually?",
        "yes_bid": 40,
        "yes_ask": 44,
        "no_bid": 56,
        "no_ask": 60,
        "volume": 900,
    }
    reason = inspect_kalshi_market_rejection_reason(market, now=now)
    assert reason == "missing_resolution"
