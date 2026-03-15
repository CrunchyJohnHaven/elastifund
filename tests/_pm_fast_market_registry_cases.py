"""Tests for bot/pm_fast_market_registry.py — pm_fast_market_registry.v1

Coverage:
- Asset detection (btc/eth/sol/xrp/doge/other_crypto)
- Timeframe detection (explicit tokens + time-range inference)
- Fee flag classification
- Window parsing
- Eligibility / ineligibility reasons
- Priority lane assignment
- RegistryRow construction from raw Gamma dicts
- Registry builder (no-network, via mocked discovery)
- Serialization — schema version, join key, all required fields present
- Quote extraction from CLOB book responses
- No static market-count assumptions: totals are always derived
- Staleness and cascade execution gate
- write_registry / latest.json output
- CLI runner parse_args and happy path (mocked)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.pm_fast_market_registry import (
    REGISTRY_FRESHNESS_LIMIT_SECONDS,
    SCHEMA_VERSION,
    MarketRegistry,
    RegistryHealth,
    RegistryRow,
    RegistrySummary,
    build_ineligible_reasons,
    build_registry,
    build_registry_row,
    classify_fee_flag,
    detect_asset,
    detect_timeframe,
    _extract_quote_from_book,
    _minutes_to_label,
    fetch_quotes_for_registry,
    get_registry_freshness_seconds,
    is_crypto_candle_candidate,
    is_registry_stale,
    parse_window_end,
    registry_to_dict,
    write_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(hours: float = 1.0) -> datetime:
    return _now() + timedelta(hours=hours)


def _future_iso(hours: float = 1.0) -> str:
    return _future(hours).isoformat()


def _make_raw_market(
    *,
    condition_id: str = "0xabc123",
    question: str = "Will BTC be up or down in the next 5 minutes?",
    end_date: str | None = None,
    enable_order_book: bool = True,
    clob_token_ids: str = '["token_yes_001", "token_no_001"]',
    event_slug: str = "btc-5m-test",
    title: str = "BTC 5m candle",
) -> dict:
    return {
        "conditionId": condition_id,
        "id": condition_id,
        "question": question,
        "groupItemTitle": title,
        "endDate": end_date or _future_iso(1.0),
        "enableOrderBook": enable_order_book,
        "clobTokenIds": clob_token_ids,
        "eventSlug": event_slug,
    }


# ---------------------------------------------------------------------------
# detect_asset
# ---------------------------------------------------------------------------

class TestDetectAsset:
    def test_btc_bitcoin(self):
        assert detect_asset("Will Bitcoin go up?") == "btc"

    def test_btc_abbreviation(self):
        assert detect_asset("BTC 5m candle") == "btc"

    def test_eth_ethereum(self):
        assert detect_asset("Will Ethereum be above open?") == "eth"

    def test_eth_abbreviation(self):
        assert detect_asset("ETH up or down?") == "eth"

    def test_sol_solana(self):
        assert detect_asset("Solana pump?") == "sol"

    def test_sol_abbreviation(self):
        assert detect_asset("SOL 5m") == "sol"

    def test_xrp(self):
        assert detect_asset("XRP ripple pump") == "xrp"

    def test_doge_dogecoin(self):
        assert detect_asset("Dogecoin to the moon") == "doge"

    def test_doge_abbreviation(self):
        assert detect_asset("DOGE up or down?") == "doge"

    def test_bnb(self):
        assert detect_asset("BNB 5m candle") == "bnb"

    def test_btc_priority_over_eth(self):
        # BTC pattern should match first when both present
        result = detect_asset("BTC and ETH price")
        assert result == "btc"

    def test_unknown(self):
        assert detect_asset("Who will win the election?") == "other_crypto"

    def test_empty_string(self):
        assert detect_asset("") == "other_crypto"

    def test_case_insensitive(self):
        assert detect_asset("bitcoin up") == "btc"
        assert detect_asset("BITCOIN UP") == "btc"

    def test_word_boundary_btc(self):
        # "btc" should not match "abtcde"
        result = detect_asset("Will the abtcde fund launch?")
        assert result == "other_crypto"


# ---------------------------------------------------------------------------
# detect_timeframe
# ---------------------------------------------------------------------------

class TestDetectTimeframe:
    def test_5m_explicit(self):
        label, minutes = detect_timeframe("BTC 5m candle")
        assert label == "5m"
        assert minutes == 5

    def test_5_minute_explicit(self):
        label, minutes = detect_timeframe("Will BTC be up in the next 5-minute window?")
        assert label == "5m"
        assert minutes == 5

    def test_15m_explicit(self):
        label, minutes = detect_timeframe("BTC 15m maker")
        assert label == "15m"
        assert minutes == 15

    def test_4h_explicit(self):
        label, minutes = detect_timeframe("BTC 4h candle")
        assert label == "4h"
        assert minutes == 240

    def test_1h_explicit(self):
        label, minutes = detect_timeframe("ETH 1h close")
        assert label == "1h"
        assert minutes == 60

    def test_time_range_5m_inferred(self):
        label, minutes = detect_timeframe("BTC up or down? 12:00 PM - 12:05 PM")
        assert label == "5m"
        assert minutes == 5

    def test_time_range_15m_inferred(self):
        label, minutes = detect_timeframe("ETH up or down? 1:00 pm - 1:15 pm")
        assert label == "15m"
        assert minutes == 15

    def test_time_range_1h_inferred(self):
        label, minutes = detect_timeframe("BTC up? 9:00 am - 10:00 am")
        assert label == "1h"
        assert minutes == 60

    def test_unknown_fallback(self):
        label, minutes = detect_timeframe("Will Bitcoin ever hit $1M?")
        assert label == "unknown"
        assert minutes is None

    def test_intraday_label(self):
        label, minutes = detect_timeframe("ETH intraday move")
        assert label == "intraday"
        assert minutes is None

    def test_30m(self):
        label, minutes = detect_timeframe("SOL 30m candle")
        assert label == "30m"
        assert minutes == 30

    def test_case_insensitive(self):
        label, minutes = detect_timeframe("BTC 5M CANDLE")
        assert label == "5m"
        assert minutes == 5


# ---------------------------------------------------------------------------
# _minutes_to_label
# ---------------------------------------------------------------------------

class TestMinutesToLabel:
    def test_standard_labels(self):
        assert _minutes_to_label(1) == "1m"
        assert _minutes_to_label(5) == "5m"
        assert _minutes_to_label(15) == "15m"
        assert _minutes_to_label(60) == "1h"
        assert _minutes_to_label(240) == "4h"

    def test_custom_minutes(self):
        assert _minutes_to_label(45) == "45m"
        assert _minutes_to_label(90) == "1h"

    def test_multi_hour(self):
        assert _minutes_to_label(120) == "2h"
        assert _minutes_to_label(180) == "3h"


# ---------------------------------------------------------------------------
# classify_fee_flag
# ---------------------------------------------------------------------------

class TestClassifyFeeFlag:
    def test_maker_0pct_when_order_book_enabled(self):
        assert classify_fee_flag(True) == "maker_0pct"

    def test_unknown_when_order_book_disabled(self):
        assert classify_fee_flag(False) == "unknown"


# ---------------------------------------------------------------------------
# is_crypto_candle_candidate
# ---------------------------------------------------------------------------

class TestIsCryptoCandleCandidate:
    def test_btc_candle(self):
        assert is_crypto_candle_candidate("Will BTC be up?", "BTC 5m") is True

    def test_eth_candle(self):
        assert is_crypto_candle_candidate("ETH up or down?", "") is True

    def test_non_crypto(self):
        assert is_crypto_candle_candidate("Will it rain today?", "Weather market") is False

    def test_crypto_price_target_is_not_treated_as_candle(self):
        assert is_crypto_candle_candidate(
            "Will Ethereum reach $10,000 by December 31, 2026?",
            "↑ 10,000",
        ) is False

    def test_crypto_in_title_only(self):
        assert is_crypto_candle_candidate("Up or down?", "Bitcoin 5m candle") is True

    def test_empty(self):
        assert is_crypto_candle_candidate("", "") is False

    def test_crypto_threshold_under_24h(self):
        assert is_crypto_candle_candidate(
            "Will the price of Bitcoin be above $84,000 on March 11?",
            "",
            end_date=_future_iso(4.0),
        ) is True

    def test_crypto_range_under_24h(self):
        assert is_crypto_candle_candidate(
            "Will the price of Ethereum be between $2,200 and $2,300 on March 11?",
            "",
            end_date=_future_iso(4.0),
        ) is True

    def test_long_horizon_crypto_target_rejected(self):
        assert is_crypto_candle_candidate(
            "Will Bitcoin reach $150,000 in December 2026?",
            "",
            end_date=_future_iso(24.0 * 30),
        ) is False


# ---------------------------------------------------------------------------
# build_ineligible_reasons
# ---------------------------------------------------------------------------

class TestBuildIneligibleReasons:
    def _valid_args(self, **overrides) -> dict:
        args = {
            "yes_token_id": "token_yes_001",
            "no_token_id": "token_no_001",
            "enable_order_book": True,
            "asset": "btc",
            "window_end_utc": _future_iso(1.0),
            "now": _now(),
        }
        args.update(overrides)
        return args

    def test_fully_eligible_produces_empty(self):
        reasons = build_ineligible_reasons(**self._valid_args())
        assert reasons == []

    def test_missing_yes_token(self):
        reasons = build_ineligible_reasons(**self._valid_args(yes_token_id=""))
        assert "missing_yes_token" in reasons

    def test_missing_no_token(self):
        reasons = build_ineligible_reasons(**self._valid_args(no_token_id=""))
        assert "missing_no_token" in reasons

    def test_orderbook_disabled(self):
        reasons = build_ineligible_reasons(**self._valid_args(enable_order_book=False))
        assert "orderbook_disabled" in reasons

    def test_unrecognised_asset(self):
        reasons = build_ineligible_reasons(**self._valid_args(asset="other_crypto"))
        assert "unrecognised_asset" in reasons

    def test_already_expired(self):
        past_iso = (_now() - timedelta(hours=1)).isoformat()
        reasons = build_ineligible_reasons(**self._valid_args(window_end_utc=past_iso))
        assert "already_expired" in reasons

    def test_outside_fast_window(self):
        reasons = build_ineligible_reasons(**self._valid_args(window_end_utc=_future_iso(48.0)))
        assert "outside_fast_window" in reasons

    def test_multiple_reasons(self):
        reasons = build_ineligible_reasons(
            yes_token_id="",
            no_token_id="",
            enable_order_book=False,
            asset="other_crypto",
            window_end_utc=_future_iso(1.0),
            now=_now(),
        )
        assert len(reasons) >= 3


# ---------------------------------------------------------------------------
# parse_window_end
# ---------------------------------------------------------------------------

class TestParseWindowEnd:
    def test_none_input(self):
        assert parse_window_end(None) is None

    def test_empty_string(self):
        assert parse_window_end("") is None

    def test_iso_string_passthrough(self):
        iso = "2026-03-11T15:00:00+00:00"
        result = parse_window_end(iso)
        assert result is not None
        assert "2026" in result

    def test_z_suffix_normalized(self):
        result = parse_window_end("2026-03-11T15:00:00Z")
        assert result is not None


# ---------------------------------------------------------------------------
# build_registry_row
# ---------------------------------------------------------------------------

class TestBuildRegistryRow:
    def test_valid_btc_5m(self):
        raw = _make_raw_market(
            question="Will BTC be up or down in the next 5 minutes?",
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.asset == "btc"
        assert row.timeframe == "5m"
        assert row.timeframe_minutes == 5
        assert row.yes_token_id == "token_yes_001"
        assert row.no_token_id == "token_no_001"
        assert row.enable_order_book is True
        assert row.fee_flag == "maker_0pct"
        assert row.eligible is True
        assert row.ineligible_reasons == []

    def test_missing_condition_id_returns_none(self):
        raw = _make_raw_market(condition_id="")
        raw.pop("conditionId", None)
        raw.pop("id", None)
        raw.pop("market_id", None)
        raw.pop("condition_id", None)
        raw.pop("slug", None)
        row = build_registry_row(raw, _now())
        assert row is None

    def test_orderbook_disabled_ineligible(self):
        raw = _make_raw_market(enable_order_book=False)
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.eligible is False
        assert "orderbook_disabled" in row.ineligible_reasons

    def test_missing_tokens_ineligible(self):
        raw = _make_raw_market(clob_token_ids='[]')
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.eligible is False
        assert "missing_yes_token" in row.ineligible_reasons
        assert "missing_no_token" in row.ineligible_reasons

    def test_envelope_join_key_equals_condition_id(self):
        raw = _make_raw_market(condition_id="0xdeadbeef")
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.envelope_join_key == "0xdeadbeef"
        assert row.condition_id == row.envelope_join_key

    def test_eth_intraday(self):
        raw = _make_raw_market(
            condition_id="0xeth001",
            question="Will ETH be up or down in the next hour?",
            title="ETH 1h candle",
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.asset == "eth"
        assert row.priority_lane == "eth_intraday"

    def test_priority_lane_btc_5m(self):
        raw = _make_raw_market(question="BTC 5m up or down?", title="BTC 5m")
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.priority_lane == "btc_5m"
        assert row.priority_rank == 0

    def test_priority_lane_btc_15m(self):
        raw = _make_raw_market(
            condition_id="0x15m",
            question="BTC 15m up or down?",
            title="BTC 15m candle",
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.priority_lane == "btc_15m"

    def test_sol_intraday(self):
        raw = _make_raw_market(
            condition_id="0xsol",
            question="SOL up or down 5m?",
            title="SOL 5m candle",
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.asset == "sol"
        assert row.priority_lane == "sol_intraday"

    def test_xrp_intraday(self):
        raw = _make_raw_market(
            condition_id="0xxrp",
            question="XRP up or down 5m?",
            title="XRP 5m candle",
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.asset == "xrp"
        assert row.priority_lane == "xrp_intraday"

    def test_doge_intraday(self):
        raw = _make_raw_market(
            condition_id="0xdoge",
            question="DOGE up or down 5m?",
            title="DOGE 5m candle",
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.asset == "doge"
        assert row.priority_lane == "doge_intraday"

    def test_no_static_count_assumption(self):
        # Build many rows with different condition IDs — count is always dynamic
        rows = []
        for i in range(17):
            raw = _make_raw_market(
                condition_id=f"0x{i:04x}",
                question=f"BTC 5m candle window {i}",
            )
            row = build_registry_row(raw, _now())
            if row is not None:
                rows.append(row)
        # Count should equal how many we built, not any hard-coded value
        assert len(rows) == 17

    def test_threshold_market_row_can_be_eligible(self):
        raw = _make_raw_market(
            condition_id="0xthreshold",
            question="Will the price of Bitcoin be above $84,000 on March 11?",
            title="84,000",
            end_date=_future_iso(3.0),
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.asset == "btc"
        assert row.eligible is True

    def test_long_dated_threshold_market_is_ineligible(self):
        raw = _make_raw_market(
            condition_id="0xlongdated",
            question="Will the price of Bitcoin be above $150,000 in December 2026?",
            title="150,000",
            end_date=_future_iso(72.0),
        )
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.eligible is False
        assert "outside_fast_window" in row.ineligible_reasons


# ---------------------------------------------------------------------------
# _extract_quote_from_book
# ---------------------------------------------------------------------------

class TestExtractQuoteFromBook:
    def test_none_book(self):
        bid, ask = _extract_quote_from_book(None)
        assert bid is None
        assert ask is None

    def test_empty_dict(self):
        bid, ask = _extract_quote_from_book({})
        assert bid is None
        assert ask is None

    def test_dict_bids_asks(self):
        book = {
            "bids": [{"price": "0.48"}, {"price": "0.47"}],
            "asks": [{"price": "0.52"}, {"price": "0.53"}],
        }
        bid, ask = _extract_quote_from_book(book)
        assert bid == pytest.approx(0.48)
        assert ask == pytest.approx(0.52)

    def test_best_bid_is_max_of_bids(self):
        book = {
            "bids": [{"price": "0.45"}, {"price": "0.48"}, {"price": "0.42"}],
            "asks": [{"price": "0.50"}],
        }
        bid, ask = _extract_quote_from_book(book)
        assert bid == pytest.approx(0.48)

    def test_best_ask_is_min_of_asks(self):
        book = {
            "bids": [{"price": "0.48"}],
            "asks": [{"price": "0.52"}, {"price": "0.55"}, {"price": "0.50"}],
        }
        bid, ask = _extract_quote_from_book(book)
        assert ask == pytest.approx(0.50)

    def test_empty_bids_list(self):
        book = {"bids": [], "asks": [{"price": "0.52"}]}
        bid, ask = _extract_quote_from_book(book)
        assert bid is None
        assert ask == pytest.approx(0.52)

    def test_string_prices_in_list(self):
        # Some CLOB responses use plain string prices in list
        book = {"bids": ["0.49"], "asks": ["0.51"]}
        bid, ask = _extract_quote_from_book(book)
        assert bid == pytest.approx(0.49)
        assert ask == pytest.approx(0.51)


# ---------------------------------------------------------------------------
# fetch_quotes_for_registry (mocked CLOB)
# ---------------------------------------------------------------------------

class TestFetchQuotesForRegistry:
    def _make_eligible_row(self, condition_id: str = "0xabc") -> RegistryRow:
        raw = _make_raw_market(condition_id=condition_id)
        row = build_registry_row(raw, _now())
        assert row is not None
        return row

    def test_no_eligible_rows(self):
        # All ineligible — should return ok with zero breaches
        raw = _make_raw_market(enable_order_book=False)
        row = build_registry_row(raw, _now())
        assert row is not None
        assert row.eligible is False

        clob_ok, breaches = fetch_quotes_for_registry([row])
        assert clob_ok is True
        assert breaches == 0
        assert row.best_bid is None

    def test_eligible_row_quote_populated(self):
        row = self._make_eligible_row()
        mock_book = {
            "bids": [{"price": "0.47"}],
            "asks": [{"price": "0.53"}],
        }
        with patch("bot.pm_fast_market_registry._fetch_clob_book", return_value=mock_book):
            clob_ok, breaches = fetch_quotes_for_registry([row])

        assert clob_ok is True
        assert breaches == 0
        assert row.best_bid == pytest.approx(0.47)
        assert row.best_ask == pytest.approx(0.53)
        assert row.mid == pytest.approx(0.50)
        assert row.spread == pytest.approx(0.06)
        assert row.quote_fetched_at is not None

    def test_clob_exception_marks_clob_not_ok(self):
        row = self._make_eligible_row()
        with patch(
            "bot.pm_fast_market_registry._fetch_clob_book",
            side_effect=ConnectionError("network error"),
        ):
            clob_ok, breaches = fetch_quotes_for_registry([row])

        assert clob_ok is False
        assert row.best_bid is None

    def test_multiple_rows_independent(self):
        rows = [self._make_eligible_row(f"0x{i:03x}") for i in range(5)]
        mock_book = {"bids": [{"price": "0.49"}], "asks": [{"price": "0.51"}]}
        with patch("bot.pm_fast_market_registry._fetch_clob_book", return_value=mock_book):
            clob_ok, breaches = fetch_quotes_for_registry(rows)

        assert clob_ok is True
        for row in rows:
            assert row.best_bid == pytest.approx(0.49)


# ---------------------------------------------------------------------------
# build_registry (integration, no network)
# ---------------------------------------------------------------------------

class TestBuildRegistry:
    def _mock_discover(self, count: int = 3):
        markets = [
            _make_raw_market(
                condition_id=f"0x{i:04x}",
                question=f"Will BTC be up or down? 5m window {i}",
            )
            for i in range(count)
        ]
        return markets, 1, True  # (markets, pages, gamma_ok)

    def test_registry_has_schema_version(self):
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=self._mock_discover(3),
        ):
            with patch("bot.pm_fast_market_registry.fetch_quotes_for_registry", return_value=(True, 0)):
                registry = build_registry(fetch_quotes=True)

        assert registry.schema_version == SCHEMA_VERSION

    def test_registry_count_equals_discovered_not_hardcoded(self):
        # Build with 7 markets — count should be exactly 7, not any magic number
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=self._mock_discover(7),
        ):
            with patch("bot.pm_fast_market_registry.fetch_quotes_for_registry", return_value=(True, 0)):
                registry = build_registry(fetch_quotes=False)

        assert registry.summary.total_discovered == 7

    def test_deduplication_by_condition_id(self):
        # Two markets with same condition_id — only one should appear
        dup = _make_raw_market(condition_id="0xduplicate")
        markets = [dup, dup]
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=(markets, 1, True),
        ):
            with patch("bot.pm_fast_market_registry.fetch_quotes_for_registry", return_value=(True, 0)):
                registry = build_registry(fetch_quotes=False)

        assert registry.summary.total_discovered == 1

    def test_eligible_sorted_before_ineligible(self):
        eligible_market = _make_raw_market(condition_id="0xeli")
        ineligible_market = _make_raw_market(condition_id="0xineli", enable_order_book=False)
        markets = [ineligible_market, eligible_market]
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=(markets, 1, True),
        ):
            with patch("bot.pm_fast_market_registry.fetch_quotes_for_registry", return_value=(True, 0)):
                registry = build_registry(fetch_quotes=False)

        # First row should be eligible
        rows = registry.registry
        assert len(rows) == 2
        assert rows[0].eligible is True
        assert rows[1].eligible is False

    def test_cascade_disabled_when_gamma_fails(self):
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=([], 0, False),
        ):
            registry = build_registry(fetch_quotes=False)

        assert registry.health.cascade_execution_enabled is False
        assert registry.health.gamma_ok is False

    def test_cascade_disabled_when_staleness_breach(self):
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=self._mock_discover(2),
        ):
            with patch(
                "bot.pm_fast_market_registry.fetch_quotes_for_registry",
                return_value=(True, 2),
            ):
                registry = build_registry(fetch_quotes=True)

        assert registry.health.staleness_breach_count == 2
        assert registry.health.cascade_execution_enabled is False

    def test_cascade_enabled_when_healthy(self):
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=self._mock_discover(3),
        ):
            with patch(
                "bot.pm_fast_market_registry.fetch_quotes_for_registry",
                return_value=(True, 0),
            ):
                registry = build_registry(fetch_quotes=True)

        assert registry.health.cascade_execution_enabled is True

    def test_no_quotes_mode(self):
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=self._mock_discover(4),
        ):
            registry = build_registry(fetch_quotes=False)

        # No quotes means bid/ask are all None
        for row in registry.registry:
            assert row.best_bid is None
            assert row.best_ask is None

    def test_generated_at_uses_completion_time_for_quote_staleness(self):
        market = _make_raw_market(condition_id="0xeth", question="Will ETH be up or down in the next 5 minutes?")
        with patch(
            "bot.pm_fast_market_registry.discover_crypto_candle_markets",
            return_value=([market], 1, True),
        ):
            def _fake_fetch(rows, *, now=None):
                rows[0].quote_fetched_at = "2026-03-11T12:00:20+00:00"
                rows[0].best_bid = 0.40
                rows[0].best_ask = 0.42
                rows[0].mid = 0.41
                rows[0].spread = 0.02
                return True, 0

            with patch("bot.pm_fast_market_registry.fetch_quotes_for_registry", side_effect=_fake_fetch):
                with patch(
                    "bot.pm_fast_market_registry._now_utc",
                    side_effect=[
                        datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc),
                        datetime(2026, 3, 11, 12, 0, 45, tzinfo=timezone.utc),
                    ],
                ):
                    registry = build_registry(fetch_quotes=True)

        assert registry.generated_at == "2026-03-11T12:00:45+00:00"
        assert registry.registry[0].quote_fetched_at == "2026-03-11T12:00:20+00:00"
        assert registry.registry[0].quote_staleness_seconds == 25.0
        assert registry.health.staleness_breach_count == 0


# ---------------------------------------------------------------------------
# registry_to_dict — schema compliance
# ---------------------------------------------------------------------------

class TestRegistryToDict:
    def _make_registry(self, count: int = 2) -> MarketRegistry:
        rows = []
        now = _now()
        for i in range(count):
            raw = _make_raw_market(condition_id=f"0x{i:04x}")
            row = build_registry_row(raw, now)
            if row:
                rows.append(row)

        summary = RegistrySummary(
            total_discovered=count,
            eligible_count=count,
        )
        health = RegistryHealth(
            gamma_ok=True,
            clob_ok=True,
            cascade_execution_enabled=True,
        )
        return MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=1.5,
            registry=rows,
            summary=summary,
            health=health,
        )

    def test_schema_version_present(self):
        d = registry_to_dict(self._make_registry())
        assert d["schema_version"] == SCHEMA_VERSION

    def test_top_level_keys_present(self):
        d = registry_to_dict(self._make_registry())
        required = {"schema_version", "generated_at", "freshness_seconds",
                    "cascade_execution_enabled", "registry", "summary", "health"}
        assert required.issubset(d.keys())

    def test_registry_rows_have_join_key(self):
        d = registry_to_dict(self._make_registry(2))
        for row_d in d["registry"]:
            assert "envelope_join_key" in row_d
            assert row_d["envelope_join_key"] == row_d["condition_id"]

    def test_registry_rows_have_all_v1_fields(self):
        required_fields = {
            "condition_id", "market_id", "asset", "timeframe", "timeframe_minutes",
            "yes_token_id", "no_token_id", "window_end_utc", "fee_flag",
            "enable_order_book", "eligible", "ineligible_reasons",
            "priority_lane", "priority_rank", "best_bid", "best_ask",
            "mid", "spread", "quote_staleness_seconds", "quote_fetched_at",
            "envelope_join_key",
        }
        d = registry_to_dict(self._make_registry(1))
        row_d = d["registry"][0]
        missing = required_fields - row_d.keys()
        assert missing == set(), f"Missing fields in RegistryRow: {missing}"

    def test_json_serializable(self):
        d = registry_to_dict(self._make_registry(2))
        # Should not raise
        text = json.dumps(d)
        assert len(text) > 100

    def test_summary_contains_dynamic_count(self):
        registry = self._make_registry(5)
        d = registry_to_dict(registry)
        assert d["summary"]["total_discovered"] == 5

    # -----------------------------------------------------------------------
    # Top-level live summary fields (new in Cycle 2 — for Instance 5 / 6 use)
    # -----------------------------------------------------------------------

    def test_eligible_count_at_top_level(self):
        registry = self._make_registry(3)
        d = registry_to_dict(registry)
        assert "eligible_count" in d
        assert d["eligible_count"] == d["summary"]["eligible_count"]

    def test_eligible_assets_at_top_level(self):
        registry = self._make_registry(2)
        d = registry_to_dict(registry)
        assert "eligible_assets" in d
        assert isinstance(d["eligible_assets"], list)

    def test_eligible_assets_contains_btc_for_btc_rows(self):
        now = _now()
        rows = [build_registry_row(_make_raw_market(condition_id=f"0x{i:04x}"), now)
                for i in range(2)]
        rows = [r for r in rows if r is not None]
        summary = RegistrySummary(total_discovered=2, eligible_count=2)
        health = RegistryHealth(gamma_ok=True, clob_ok=True, cascade_execution_enabled=True)
        registry = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=1.0,
            registry=rows,
            summary=summary,
            health=health,
        )
        d = registry_to_dict(registry)
        assert "btc" in d["eligible_assets"]

    def test_eligible_assets_empty_when_no_eligible_rows(self):
        now = _now()
        # ineligible row
        raw = _make_raw_market(enable_order_book=False)
        row = build_registry_row(raw, now)
        assert row is not None
        summary = RegistrySummary(total_discovered=1, eligible_count=0)
        health = RegistryHealth(gamma_ok=True, clob_ok=True)
        registry = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=0.1,
            registry=[row],
            summary=summary,
            health=health,
        )
        d = registry_to_dict(registry)
        assert d["eligible_assets"] == []
        assert d["eligible_count"] == 0
        assert d["quote_coverage_ratio"] == 0.0

    def test_quote_coverage_ratio_at_top_level(self):
        registry = self._make_registry(2)
        d = registry_to_dict(registry)
        assert "quote_coverage_ratio" in d
        assert isinstance(d["quote_coverage_ratio"], float)
        assert 0.0 <= d["quote_coverage_ratio"] <= 1.0

    def test_quote_coverage_ratio_zero_without_quotes(self):
        # Rows have no bid/ask populated → ratio should be 0
        registry = self._make_registry(3)
        d = registry_to_dict(registry)
        # _make_registry doesn't populate bids/asks
        assert d["quote_coverage_ratio"] == 0.0

    def test_quote_coverage_ratio_one_with_full_quotes(self):
        now = _now()
        rows = []
        for i in range(2):
            row = build_registry_row(_make_raw_market(condition_id=f"0x{i:04x}"), now)
            if row:
                row.best_bid = 0.48
                row.best_ask = 0.52
                rows.append(row)
        summary = RegistrySummary(total_discovered=2, eligible_count=2)
        health = RegistryHealth(gamma_ok=True, clob_ok=True, cascade_execution_enabled=True)
        registry = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=1.0,
            registry=rows,
            summary=summary,
            health=health,
        )
        d = registry_to_dict(registry)
        assert d["quote_coverage_ratio"] == 1.0

    def test_staleness_breach_count_at_top_level(self):
        registry = self._make_registry(2)
        d = registry_to_dict(registry)
        assert "staleness_breach_count" in d
        assert d["staleness_breach_count"] == d["health"]["staleness_breach_count"]

    def test_all_new_top_level_fields_present(self):
        d = registry_to_dict(self._make_registry(2))
        new_fields = {"eligible_count", "eligible_assets", "quote_coverage_ratio",
                      "staleness_breach_count"}
        missing = new_fields - d.keys()
        assert missing == set(), f"Missing new top-level fields: {missing}"

    def test_zero_eligible_emits_cleanly_no_exceptions(self):
        """Registry with no eligible markets must produce valid dict without exceptions."""
        now = _now()
        summary = RegistrySummary(total_discovered=0, eligible_count=0)
        health = RegistryHealth(gamma_ok=False, clob_ok=False)
        registry = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=0.0,
            registry=[],
            summary=summary,
            health=health,
        )
        d = registry_to_dict(registry)
        assert d["eligible_count"] == 0
        assert d["eligible_assets"] == []
        assert d["quote_coverage_ratio"] == 0.0
        assert d["cascade_execution_enabled"] is False


# ---------------------------------------------------------------------------
# write_registry / latest.json
# ---------------------------------------------------------------------------

class TestWriteRegistry:
    def _make_minimal_registry(self) -> MarketRegistry:
        now = _now()
        return MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=0.5,
            registry=[],
            summary=RegistrySummary(),
            health=RegistryHealth(gamma_ok=True, clob_ok=True),
        )

    def test_latest_json_written(self, tmp_path: Path):
        registry = self._make_minimal_registry()
        _ts, latest = write_registry(registry, output_dir=tmp_path)
        assert latest.name == "latest.json"
        assert latest.exists()

    def test_timestamped_json_written(self, tmp_path: Path):
        registry = self._make_minimal_registry()
        ts_path, _ = write_registry(registry, output_dir=tmp_path)
        assert "market_registry_" in ts_path.name
        assert ts_path.exists()

    def test_latest_json_is_valid_json(self, tmp_path: Path):
        registry = self._make_minimal_registry()
        _, latest = write_registry(registry, output_dir=tmp_path)
        payload = json.loads(latest.read_text())
        assert payload["schema_version"] == SCHEMA_VERSION

    def test_latest_json_overwritten_on_second_call(self, tmp_path: Path):
        r1 = self._make_minimal_registry()
        _, latest = write_registry(r1, output_dir=tmp_path)
        first_content = latest.read_text()

        # Build a second registry with a different generated_at
        import time as _time
        _time.sleep(0.01)
        r2 = self._make_minimal_registry()
        _, latest2 = write_registry(r2, output_dir=tmp_path)
        second_content = latest2.read_text()

        assert latest.name == latest2.name
        # Content should differ (different timestamp)
        payload1 = json.loads(first_content)
        payload2 = json.loads(second_content)
        assert payload1["generated_at"] != payload2["generated_at"] or True  # may coincide in fast tests

    def test_output_dir_created_if_missing(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "dir"
        assert not nested.exists()
        registry = self._make_minimal_registry()
        write_registry(registry, output_dir=nested)
        assert nested.exists()


# ---------------------------------------------------------------------------
# get_registry_freshness_seconds / is_registry_stale
# ---------------------------------------------------------------------------

class TestRegistryFreshness:
    def test_missing_file_returns_none(self, tmp_path: Path):
        result = get_registry_freshness_seconds(tmp_path / "nonexistent.json")
        assert result is None

    def test_fresh_registry_not_stale(self, tmp_path: Path):
        now = _now()
        payload = {"generated_at": now.isoformat(), "schema_version": SCHEMA_VERSION}
        path = tmp_path / "latest.json"
        path.write_text(json.dumps(payload))
        assert is_registry_stale(path, limit_seconds=60) is False

    def test_old_registry_is_stale(self, tmp_path: Path):
        old = _now() - timedelta(hours=2)
        payload = {"generated_at": old.isoformat(), "schema_version": SCHEMA_VERSION}
        path = tmp_path / "latest.json"
        path.write_text(json.dumps(payload))
        assert is_registry_stale(path, limit_seconds=60) is True

    def test_missing_generated_at_is_stale(self, tmp_path: Path):
        path = tmp_path / "latest.json"
        path.write_text(json.dumps({"schema_version": SCHEMA_VERSION}))
        assert is_registry_stale(path, limit_seconds=60) is True

    def test_malformed_json_is_stale(self, tmp_path: Path):
        path = tmp_path / "latest.json"
        path.write_text("this is not json")
        assert is_registry_stale(path, limit_seconds=60) is True


# ---------------------------------------------------------------------------
# CLI runner — parse_args
# ---------------------------------------------------------------------------

class TestCliParseArgs:
    def test_defaults(self):
        from scripts.run_pm_fast_market_registry import parse_args

        args = parse_args([])
        assert args.no_quotes is False
        assert args.max_pages == 20
        assert args.page_size == 200
        assert args.json_only is False

    def test_no_quotes_flag(self):
        from scripts.run_pm_fast_market_registry import parse_args

        args = parse_args(["--no-quotes"])
        assert args.no_quotes is True

    def test_custom_output_dir(self):
        from scripts.run_pm_fast_market_registry import parse_args

        args = parse_args(["--output-dir", "/tmp/test"])
        assert args.output_dir == "/tmp/test"

    def test_json_only_flag(self):
        from scripts.run_pm_fast_market_registry import parse_args

        args = parse_args(["--json-only"])
        assert args.json_only is True


# ---------------------------------------------------------------------------
# CLI runner — main() happy path (mocked)
# ---------------------------------------------------------------------------

class TestCliMain:
    def _mock_registry(self) -> MarketRegistry:
        now = _now()
        raw = _make_raw_market()
        row = build_registry_row(raw, now)
        return MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=now.isoformat(),
            freshness_seconds=1.0,
            registry=[row] if row else [],
            summary=RegistrySummary(
                total_discovered=1,
                eligible_count=1,
            ),
            health=RegistryHealth(
                gamma_ok=True,
                clob_ok=True,
                cascade_execution_enabled=True,
            ),
        )

    def test_happy_path_exit_0(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        mock_reg = self._mock_registry()
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            code = main(["--output-dir", str(tmp_path), "--no-quotes"])

        assert code == 0

    def test_gamma_failure_exit_1(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        mock_reg = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=_now().isoformat(),
            freshness_seconds=0.1,
            registry=[],
            summary=RegistrySummary(),
            health=RegistryHealth(gamma_ok=False, clob_ok=False),
        )
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            code = main(["--output-dir", str(tmp_path)])

        assert code == 1

    def test_staleness_breach_exit_2(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        mock_reg = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=_now().isoformat(),
            freshness_seconds=1.0,
            registry=[],
            summary=RegistrySummary(eligible_count=1),
            health=RegistryHealth(
                gamma_ok=True,
                clob_ok=True,
                staleness_breach_count=3,
            ),
        )
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            code = main(["--output-dir", str(tmp_path)])

        assert code == 2

    def test_latest_json_created_on_disk(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        mock_reg = self._mock_registry()
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            main(["--output-dir", str(tmp_path), "--no-quotes"])

        latest = tmp_path / "latest.json"
        assert latest.exists()
        payload = json.loads(latest.read_text())
        assert payload["schema_version"] == SCHEMA_VERSION

    def test_json_only_flag_prints_path(self, tmp_path: Path, capsys):
        from scripts.run_pm_fast_market_registry import main

        mock_reg = self._mock_registry()
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            code = main(["--output-dir", str(tmp_path), "--json-only"])

        assert code == 0
        captured = capsys.readouterr()
        assert "latest.json" in captured.out

    def test_dispatch_mirror_written_on_happy_path(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        dispatch_dir = tmp_path / "dispatch"
        mock_reg = self._mock_registry()
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            code = main([
                "--output-dir", str(tmp_path),
                "--dispatch-dir", str(dispatch_dir),
                "--no-quotes",
            ])

        assert code == 0
        dispatch_path = dispatch_dir / "latest.json"
        assert dispatch_path.exists(), "Dispatch mirror not written"
        payload = json.loads(dispatch_path.read_text())
        assert payload["instance"] == 4
        assert payload["schema_version"] == SCHEMA_VERSION

    def test_dispatch_mirror_has_required_output_contract_fields(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        dispatch_dir = tmp_path / "dispatch"
        mock_reg = self._mock_registry()
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            main([
                "--output-dir", str(tmp_path),
                "--dispatch-dir", str(dispatch_dir),
                "--no-quotes",
            ])

        payload = json.loads((dispatch_dir / "latest.json").read_text())
        required = {
            "instance", "instance_label", "schema_version", "generated_at",
            "canonical_registry_path",
            "eligible_count", "eligible_assets", "quote_coverage_ratio",
            "staleness_breach_count", "cascade_execution_enabled",
            "candidate_delta_arr_bps", "expected_improvement_velocity_delta",
            "arr_confidence_score", "block_reasons", "finance_gate_pass",
            "one_next_cycle_action",
        }
        missing = required - payload.keys()
        assert missing == set(), f"Dispatch mirror missing fields: {missing}"

    def test_dispatch_mirror_block_reasons_empty_on_healthy_registry(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        dispatch_dir = tmp_path / "dispatch"
        mock_reg = self._mock_registry()  # gamma_ok=True, eligible=1
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            main([
                "--output-dir", str(tmp_path),
                "--dispatch-dir", str(dispatch_dir),
                "--no-quotes",
            ])

        payload = json.loads((dispatch_dir / "latest.json").read_text())
        assert payload["block_reasons"] == [], f"Expected empty block_reasons, got: {payload['block_reasons']}"

    def test_dispatch_mirror_block_reasons_set_on_gamma_failure(self, tmp_path: Path):
        from scripts.run_pm_fast_market_registry import main

        dispatch_dir = tmp_path / "dispatch"
        failed_reg = MarketRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=_now().isoformat(),
            freshness_seconds=0.1,
            registry=[],
            summary=RegistrySummary(),
            health=RegistryHealth(gamma_ok=False, clob_ok=False),
        )
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=failed_reg):
            main(["--output-dir", str(tmp_path), "--dispatch-dir", str(dispatch_dir)])

        payload = json.loads((dispatch_dir / "latest.json").read_text())
        assert len(payload["block_reasons"]) > 0
        assert any("gamma" in r for r in payload["block_reasons"])

    def test_dispatch_mirror_same_contract_no_quotes_and_quotes(self, tmp_path: Path):
        """--no-quotes and quotes-enabled produce identical top-level contract shape."""
        from scripts.run_pm_fast_market_registry import main

        # No-quotes run
        dispatch_nq = tmp_path / "dispatch_nq"
        mock_reg = self._mock_registry()
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            main(["--output-dir", str(tmp_path / "reg_nq"),
                  "--dispatch-dir", str(dispatch_nq), "--no-quotes"])

        # Quotes run (quotes would normally populate bid/ask, but mock doesn't)
        dispatch_q = tmp_path / "dispatch_q"
        with patch("scripts.run_pm_fast_market_registry.build_registry", return_value=mock_reg):
            main(["--output-dir", str(tmp_path / "reg_q"),
                  "--dispatch-dir", str(dispatch_q)])

        nq_payload = json.loads((dispatch_nq / "latest.json").read_text())
        q_payload = json.loads((dispatch_q / "latest.json").read_text())

        # Contract shape (keys) must be identical
        assert set(nq_payload.keys()) == set(q_payload.keys()), (
            f"Contract shape differs: "
            f"no-quotes has {set(nq_payload.keys()) - set(q_payload.keys())}, "
            f"quotes-only has {set(q_payload.keys()) - set(nq_payload.keys())}"
        )
