from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.kalshi_opportunity_scanner import (
    ScanConfig,
    build_opportunity_record,
    infer_llm_edge_category,
    scan_kalshi_opportunities,
)


def test_infer_llm_edge_category_from_category_and_keywords() -> None:
    assert infer_llm_edge_category("Will CPI beat expectations?", "Economics") == "economic"
    assert infer_llm_edge_category("Will it rain in NYC tomorrow?", "Other") == "weather"
    assert infer_llm_edge_category("Will sanctions hit Russian banks?", "World") == "geopolitical"
    assert infer_llm_edge_category("Will this team win tonight?", "Sports") is None


def test_build_opportunity_record_rejects_markets_beyond_horizon() -> None:
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    event = {
        "event_ticker": "KXTEST",
        "title": "Will CPI be above 3%?",
        "category": "Economics",
    }
    market = {
        "ticker": "KXTEST-26MAR20-T3",
        "title": "Will CPI be above 3% on Mar 20?",
        "close_time": (now + timedelta(hours=120)).isoformat(),
        "yes_bid": 47,
        "yes_ask": 49,
        "no_bid": 51,
        "no_ask": 53,
    }
    record = build_opportunity_record(
        market=market,
        event=event,
        now=now,
        max_hours_to_resolution=72.0,
    )
    assert record is None


def test_build_opportunity_record_schema_with_dollar_quotes() -> None:
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    event = {
        "event_ticker": "KXWEATHERNYC",
        "title": "Will it rain in NYC tomorrow?",
        "category": "Climate and Weather",
    }
    market = {
        "ticker": "KXRAINNYCM-26MAR-15",
        "title": "Rain in NYC tomorrow?",
        "close_time": (now + timedelta(hours=18)).isoformat(),
        "yes_bid_dollars": "0.41",
        "yes_ask_dollars": "0.44",
        "no_bid_dollars": "0.56",
        "no_ask_dollars": "0.59",
        "volume_dollars": "4250.50",
        "open_interest_fp": "5100",
    }
    record = build_opportunity_record(
        market=market,
        event=event,
        now=now,
        max_hours_to_resolution=72.0,
    )
    assert record is not None
    assert record["ticker"] == "KXRAINNYCM-26MAR-15"
    assert record["category"] == "weather"
    assert record["hours_to_resolution"] == 18.0
    assert record["yes_ask"] == 0.44
    assert record["velocity_score"] > 0
    assert record["confidence"] > 0


def test_scan_kalshi_opportunities_ranks_and_recommends_when_sparse() -> None:
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "event_ticker": "KXPOL-1",
            "title": "Will candidate X win the debate?",
            "category": "Politics",
        },
        {
            "event_ticker": "KXWEATHER-1",
            "title": "Will it snow in Denver tomorrow?",
            "category": "Climate and Weather",
        },
    ]
    markets_by_event = {
        "KXPOL-1": [
            {
                "ticker": "KXPOL-1-M1",
                "title": "Will candidate X win the debate?",
                "close_time": (now + timedelta(hours=60)).isoformat(),
                "yes_bid": 44,
                "yes_ask": 48,
                "no_bid": 52,
                "no_ask": 56,
                "volume": 600,
            }
        ],
        "KXWEATHER-1": [
            {
                "ticker": "KXWEATHER-1-M1",
                "title": "Will it snow in Denver tomorrow?",
                "close_time": (now + timedelta(hours=12)).isoformat(),
                "yes_bid": 35,
                "yes_ask": 39,
                "no_bid": 61,
                "no_ask": 65,
                "volume": 1200,
            }
        ],
    }

    payload = scan_kalshi_opportunities(
        config=ScanConfig(
            max_event_pages=1,
            max_hours_to_resolution=72.0,
            top_n=20,
            per_request_sleep_seconds=0.0,
        ),
        now=now,
        events=events,
        event_markets_loader=lambda event_ticker: markets_by_event.get(event_ticker, []),
    )

    assert payload["total_events_scanned"] == 2
    assert payload["total_markets"] == 2
    assert payload["passing_filters"] == 2
    assert payload["passing_filters_top_n"] == 2
    assert payload["opportunities"][0]["ticker"] == "KXWEATHER-1-M1"
    assert len(payload["next_cycle_actions"]) >= 1

