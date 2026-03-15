from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.scan_llm_velocity_windows import (
    evaluate_market,
    evaluate_windows,
    parse_horizons,
)


def _market(
    *,
    question: str,
    category: str,
    yes_price: float,
    end_in_hours: float | None,
    slug: str = "",
) -> dict:
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    end_date = None
    if end_in_hours is not None:
        end_date = (now + timedelta(hours=end_in_hours)).isoformat().replace("+00:00", "Z")
    return {
        "id": f"id-{question[:8]}",
        "conditionId": f"cond-{question[:8]}",
        "question": question,
        "slug": slug,
        "category": category,
        "endDate": end_date,
        "tokens": [
            {"token_id": "yes-token", "outcome": "Yes", "price": yes_price},
            {"token_id": "no-token", "outcome": "No", "price": round(1.0 - yes_price, 4)},
        ],
    }


def test_parse_horizons_sorts_and_deduplicates():
    assert parse_horizons("72,24,72,168") == [24.0, 72.0, 168.0]


def test_evaluate_market_blocks_category_and_unknown_resolution():
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    category_priority = {
        "politics": 3,
        "weather": 3,
        "economic": 2,
        "crypto": 0,
        "sports": 0,
        "financial_speculation": 0,
        "geopolitical": 1,
        "fed_rates": 0,
        "unknown": 0,
    }

    row, reason = evaluate_market(
        _market(
            question="Will BTC be up?",
            category="crypto",
            yes_price=0.45,
            end_in_hours=6,
        ),
        now=now,
        max_resolution_hours=24.0,
        category_priority=category_priority,
        min_category_priority=1,
    )
    assert row is None
    assert reason == "category"

    row, reason = evaluate_market(
        _market(
            question="Will inflation cool this week?",
            category="economic",
            yes_price=0.52,
            end_in_hours=None,
        ),
        now=now,
        max_resolution_hours=24.0,
        category_priority=category_priority,
        min_category_priority=1,
    )
    assert row is None
    assert reason == "unknown_resolution"


def test_evaluate_windows_recommends_wider_horizon_when_24h_empty():
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    markets = [
        _market(
            question="Will CPI print below 3.0% this month?",
            category="economic",
            yes_price=0.40,
            end_in_hours=30.0,
        ),
        _market(
            question="Will parliament pass bill X by Friday?",
            category="politics",
            yes_price=0.60,
            end_in_hours=60.0,
        ),
        _market(
            question="Will Team A beat Team B?",
            category="sports",
            yes_price=0.55,
            end_in_hours=12.0,
        ),
    ]

    report = evaluate_windows(
        markets,
        now=now,
        horizons=[24.0, 72.0, 168.0],
        top_n=5,
    )

    assert report["windows"]["24h"]["passing_count"] == 0
    assert report["windows"]["72h"]["passing_count"] == 2
    assert report["recommended_window"] in {"72h", "168h"}


def test_evaluate_windows_returns_none_when_all_windows_empty():
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    markets = [
        _market(
            question="Will Team A beat Team B?",
            category="sports",
            yes_price=0.55,
            end_in_hours=4.0,
        ),
        _market(
            question="Will BTC close green?",
            category="crypto",
            yes_price=0.52,
            end_in_hours=6.0,
        ),
    ]
    report = evaluate_windows(
        markets,
        now=now,
        horizons=[24.0, 72.0, 168.0],
        top_n=5,
    )
    assert report["recommended_window"] is None
    assert report["recommendation_reason"] == "no_eligible_markets"
