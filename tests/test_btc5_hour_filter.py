"""Tests for BTC5 time-of-day filter (configurable suppress/boost hours).

Tests the helper functions and MakerConfig parsing for the hour filter
feature added in Instance 4.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

from bot.btc_5min_maker import (
    _hour_filter_status,
    _parse_hour_set,
)


# ---------------------------------------------------------------------------
# _parse_hour_set
# ---------------------------------------------------------------------------


class TestParseHourSet:
    def test_empty_string(self):
        assert _parse_hour_set("") == frozenset()

    def test_none(self):
        assert _parse_hour_set(None) == frozenset()

    def test_single_hour(self):
        assert _parse_hour_set("5") == frozenset({5})

    def test_multiple_hours(self):
        assert _parse_hour_set("0,1,2,8,9") == frozenset({0, 1, 2, 8, 9})

    def test_spaces_in_list(self):
        assert _parse_hour_set(" 3 , 4 , 5 ") == frozenset({3, 4, 5})

    def test_out_of_range_ignored(self):
        result = _parse_hour_set("0,24,25,-1,23")
        assert result == frozenset({0, 23})

    def test_non_numeric_ignored(self):
        result = _parse_hour_set("1,foo,3,bar")
        assert result == frozenset({1, 3})

    def test_duplicates_collapsed(self):
        result = _parse_hour_set("5,5,5,5")
        assert result == frozenset({5})

    def test_all_hours(self):
        all_hours = ",".join(str(h) for h in range(24))
        result = _parse_hour_set(all_hours)
        assert result == frozenset(range(24))


# ---------------------------------------------------------------------------
# _hour_filter_status
# ---------------------------------------------------------------------------


class TestHourFilterStatus:
    def test_disabled_returns_neutral(self):
        assert _hour_filter_status(
            2, enabled=False, suppress=frozenset({2}), boost=frozenset({3})
        ) == "neutral"

    def test_suppressed_hour(self):
        assert _hour_filter_status(
            2, enabled=True, suppress=frozenset({0, 1, 2}), boost=frozenset()
        ) == "suppressed"

    def test_boosted_hour(self):
        assert _hour_filter_status(
            5, enabled=True, suppress=frozenset(), boost=frozenset({3, 4, 5})
        ) == "boosted"

    def test_neutral_hour(self):
        assert _hour_filter_status(
            12, enabled=True, suppress=frozenset({0, 1, 2}), boost=frozenset({3, 4, 5})
        ) == "neutral"

    def test_empty_suppress_no_skipping(self):
        # Even if enabled, empty suppress set means nothing gets suppressed
        for h in range(24):
            assert _hour_filter_status(
                h, enabled=True, suppress=frozenset(), boost=frozenset()
            ) == "neutral"

    def test_suppress_takes_priority_over_boost(self):
        # If somehow an hour is in both sets, suppress wins
        assert _hour_filter_status(
            5, enabled=True, suppress=frozenset({5}), boost=frozenset({5})
        ) == "suppressed"


# ---------------------------------------------------------------------------
# MakerConfig parsing (env-driven)
# ---------------------------------------------------------------------------


class TestMakerConfigHourFilter:
    """Test that MakerConfig correctly parses hour filter env vars.

    Note: hour_filter_enabled is a dataclass field default evaluated at class
    definition time.  To test env-driven parsing we set the env var, then
    construct an instance with an explicit override via __post_init__ re-read,
    or we directly test the suppress/boost sets which ARE parsed in __post_init__.
    """

    def test_suppress_hours_parsed_in_post_init(self):
        """suppress_hours_et and boost_hours_et are parsed in __post_init__."""
        from bot.btc_5min_maker import MakerConfig

        with mock.patch.dict(os.environ, {
            "BTC5_SUPPRESS_HOURS_ET": "0,1,2,8,9",
            "BTC5_BOOST_HOURS_ET": "3,4,5",
        }, clear=False):
            cfg = MakerConfig()
            assert cfg.suppress_hours_et == frozenset({0, 1, 2, 8, 9})
            assert cfg.boost_hours_et == frozenset({3, 4, 5})

    def test_empty_hours_default(self):
        from bot.btc_5min_maker import MakerConfig

        with mock.patch.dict(os.environ, {
            "BTC5_SUPPRESS_HOURS_ET": "",
            "BTC5_BOOST_HOURS_ET": "",
        }, clear=False):
            cfg = MakerConfig()
            assert cfg.suppress_hours_et == frozenset()
            assert cfg.boost_hours_et == frozenset()

    def test_hour_filter_enabled_field_overridable(self):
        """The hour_filter_enabled field can be set post-construction."""
        from bot.btc_5min_maker import MakerConfig

        cfg = MakerConfig()
        # Default is False (from class definition time env)
        # We can override it to test the filter logic
        object.__setattr__(cfg, "hour_filter_enabled", True)
        assert cfg.hour_filter_enabled is True


# ---------------------------------------------------------------------------
# ET timezone conversion correctness
# ---------------------------------------------------------------------------


class TestETTimezoneConversion:
    """Verify that the ET hour computation matches expectations."""

    def test_utc_to_et_standard_time(self):
        """During EST (UTC-5), 10 UTC = 5 AM ET."""
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        ET_ZONE = ZoneInfo("America/New_York")
        # Jan 15 2026 at 10:00 UTC (EST, so UTC-5)
        ts = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        et_hour = ts.astimezone(ET_ZONE).hour
        assert et_hour == 5

    def test_utc_to_et_daylight_time(self):
        """During EDT (UTC-4), 10 UTC = 6 AM ET."""
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        ET_ZONE = ZoneInfo("America/New_York")
        # Jul 15 2026 at 10:00 UTC (EDT, so UTC-4)
        ts = datetime(2026, 7, 15, 10, 0, 0, tzinfo=timezone.utc)
        et_hour = ts.astimezone(ET_ZONE).hour
        assert et_hour == 6
