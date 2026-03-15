from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.scan_live_markets_now import (
    BookMetrics,
    compute_velocity_score,
    normalize_category,
    ranked_market_rows,
    to_candidate,
)


def test_normalize_category():
    assert normalize_category("Financial Speculation") == "financial_speculation"
    assert normalize_category(None) == "unknown"


def test_to_candidate_filters_and_scores():
    now = datetime(2026, 3, 9, tzinfo=timezone.utc)
    market = {
        "question": "Will BTC be above 120k at 14:00?",
        "slug": "btc-above-120k-14",
        "category": "crypto",
        "end_date_iso": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "conditionId": "cond-1",
        "tokens": [
            {"token_id": "yes-1", "outcome": "Yes", "price": 0.42},
            {"token_id": "no-1", "outcome": "No", "price": 0.58},
        ],
    }

    candidate = to_candidate(market, now)
    assert candidate is not None
    assert candidate.recommended_side == "YES"
    assert candidate.velocity_score == compute_velocity_score(0.42, 2.0)


def test_to_candidate_rejects_disallowed_category_and_price_window():
    now = datetime(2026, 3, 9, tzinfo=timezone.utc)
    sports_market = {
        "question": "Will Team A win?",
        "slug": "team-a-win",
        "category": "sports",
        "end_date_iso": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "tokens": [
            {"token_id": "yes-1", "outcome": "Yes", "price": 0.40},
            {"token_id": "no-1", "outcome": "No", "price": 0.60},
        ],
    }
    assert to_candidate(sports_market, now) is None

    bad_price_market = {
        "question": "Will CPI print?",
        "slug": "cpi-print",
        "category": "economic",
        "end_date_iso": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "tokens": [
            {"token_id": "yes-2", "outcome": "Yes", "price": 0.99},
            {"token_id": "no-2", "outcome": "No", "price": 0.01},
        ],
    }
    assert to_candidate(bad_price_market, now) is None


def test_ranked_market_rows_orders_by_velocity_desc():
    now = datetime(2026, 3, 9, tzinfo=timezone.utc)
    m1 = {
        "question": "Will BTC be above 100k at 12:05?",
        "slug": "btc-1",
        "category": "crypto",
        "end_date_iso": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "conditionId": "a",
        "tokens": [
            {"token_id": "yes-a", "outcome": "Yes", "price": 0.30},
            {"token_id": "no-a", "outcome": "No", "price": 0.70},
        ],
    }
    m2 = {
        "question": "Will inflation cool?",
        "slug": "econ-1",
        "category": "economic",
        "end_date_iso": (now + timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
        "conditionId": "b",
        "tokens": [
            {"token_id": "yes-b", "outcome": "Yes", "price": 0.45},
            {"token_id": "no-b", "outcome": "No", "price": 0.55},
        ],
    }

    c1 = to_candidate(m1, now)
    c2 = to_candidate(m2, now)
    assert c1 is not None and c2 is not None

    rows = ranked_market_rows(
        [c1, c2],
        {
            "yes-a": BookMetrics(best_bid=0.29, best_ask=0.31, bid_depth_usd=50.0, ask_depth_usd=70.0),
            "no-a": BookMetrics(best_bid=0.69, best_ask=0.71, bid_depth_usd=40.0, ask_depth_usd=60.0),
            "yes-b": BookMetrics(best_bid=0.44, best_ask=0.46, bid_depth_usd=25.0, ask_depth_usd=25.0),
            "no-b": BookMetrics(best_bid=0.54, best_ask=0.56, bid_depth_usd=25.0, ask_depth_usd=25.0),
        },
    )

    assert len(rows) == 2
    assert rows[0]["slug"] == "btc-1"
    assert rows[0]["recommended_price"] == 0.3
