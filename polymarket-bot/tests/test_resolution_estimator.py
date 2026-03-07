"""Tests for resolution_estimator: date parsing, penalty function, velocity scoring."""
import math
from datetime import datetime, timezone

import pytest

from src.resolution_estimator import (
    capital_velocity_penalty,
    capital_velocity_score,
    estimate_resolution_days,
    velocity_adjusted_ev,
    _parse_date_from_question,
    _parse_iso_date,
)


# ── Fixed "now" for deterministic tests ──────────────────────────────
NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)


# ── Date parsing tests ───────────────────────────────────────────────

class TestParseDateFromQuestion:
    """Tests for _parse_date_from_question and estimate_resolution_days."""

    def test_iso_date_in_question(self):
        q = "Will X happen by 2026-03-15?"
        result = _parse_date_from_question(q, NOW)
        assert result is not None
        assert result.month == 3
        assert result.day == 15

    def test_natural_date_by_month_day(self):
        q = "Will the bill pass by March 20?"
        result = _parse_date_from_question(q, NOW)
        assert result is not None
        assert result.month == 3
        assert result.day == 20

    def test_natural_date_with_year(self):
        q = "Will it resolve before April 1, 2026?"
        result = _parse_date_from_question(q, NOW)
        assert result is not None
        assert result.month == 4
        assert result.day == 1
        assert result.year == 2026

    def test_ordinal_date(self):
        q = "Will the market close on March 15th?"
        result = _parse_date_from_question(q, NOW)
        assert result is not None
        assert result.day == 15

    def test_no_date_returns_none(self):
        q = "Will Bitcoin reach $100K?"
        result = _parse_date_from_question(q, NOW)
        assert result is None

    def test_past_date_rolls_to_next_year(self):
        q = "Will it happen by January 15?"
        result = _parse_date_from_question(q, NOW)
        assert result is not None
        # Jan 15 2026 is before NOW (Mar 5 2026), so should roll to 2027
        assert result.year == 2027


class TestParseIsoDate:
    def test_full_iso(self):
        dt = _parse_iso_date("2026-03-31T12:00:00Z")
        assert dt is not None
        assert dt.month == 3
        assert dt.day == 31

    def test_date_only(self):
        dt = _parse_iso_date("2026-04-15")
        assert dt is not None
        assert dt.month == 4
        assert dt.day == 15

    def test_empty_string(self):
        assert _parse_iso_date("") is None

    def test_none(self):
        assert _parse_iso_date(None) is None

    def test_invalid(self):
        assert _parse_iso_date("not-a-date") is None


class TestEstimateResolutionDays:
    def test_end_date_from_api(self):
        result = estimate_resolution_days(
            "Will X happen?",
            end_date="2026-03-15T00:00:00Z",
            now=NOW,
        )
        assert result["method"] == "end_date"
        assert result["confidence"] == "high"
        assert 9.0 <= result["estimated_days"] <= 10.0  # ~10 days from Mar 5

    def test_today_keyword(self):
        result = estimate_resolution_days("Will it rain today?", now=NOW)
        assert result["method"] == "keyword_today"
        assert result["estimated_days"] == 0.5

    def test_tomorrow_keyword(self):
        result = estimate_resolution_days("Will the temp hit 80 tomorrow?", now=NOW)
        assert result["method"] == "keyword_tomorrow"
        assert result["estimated_days"] == 1.0

    def test_this_week_keyword(self):
        result = estimate_resolution_days("Will it snow this weekend?", now=NOW)
        assert result["method"] == "keyword_this_week"
        assert result["estimated_days"] == 5.0

    def test_weather_keyword(self):
        result = estimate_resolution_days("High temperature in Chicago?", now=NOW)
        assert result["method"] == "weather_category"
        assert result["estimated_days"] == 2.0

    def test_default_fallback(self):
        result = estimate_resolution_days("Will aliens arrive?", now=NOW)
        assert result["method"] == "default"
        assert result["estimated_days"] == 14.0
        assert result["confidence"] == "low"


# ── Capital velocity penalty tests ───────────────────────────────────

class TestCapitalVelocityPenalty:
    def test_under_threshold_no_penalty(self):
        assert capital_velocity_penalty(5.0, max_days=14.0) == 1.0
        assert capital_velocity_penalty(14.0, max_days=14.0) == 1.0

    def test_over_threshold_decays(self):
        p = capital_velocity_penalty(21.0, max_days=14.0, decay_rate=0.1)
        # 7 days over → exp(-0.7) ≈ 0.4966
        assert 0.49 < p < 0.51

    def test_far_over_threshold_nearly_zero(self):
        p = capital_velocity_penalty(45.0, max_days=14.0, decay_rate=0.1)
        # 31 days over → exp(-3.1) ≈ 0.045
        assert p < 0.05

    def test_zero_days_uses_floor(self):
        p = capital_velocity_penalty(0.0, max_days=14.0)
        assert p == 1.0  # 0.25 days < 14

    def test_negative_days_uses_floor(self):
        p = capital_velocity_penalty(-5.0, max_days=14.0)
        assert p == 1.0

    def test_custom_decay_rate(self):
        p_slow = capital_velocity_penalty(21.0, max_days=14.0, decay_rate=0.05)
        p_fast = capital_velocity_penalty(21.0, max_days=14.0, decay_rate=0.2)
        assert p_slow > p_fast  # Slower decay = less penalty

    def test_exact_threshold(self):
        assert capital_velocity_penalty(14.0, max_days=14.0) == 1.0

    def test_just_over_threshold(self):
        p = capital_velocity_penalty(14.1, max_days=14.0, decay_rate=0.1)
        # 0.1 days over → exp(-0.01) ≈ 0.99
        assert 0.98 < p < 1.0


# ── Capital velocity score tests ─────────────────────────────────────

class TestCapitalVelocityScore:
    def test_basic(self):
        score = capital_velocity_score(0.10, 7.0)
        assert score == pytest.approx(0.10 / 7.0 * 365.0)

    def test_zero_days_uses_floor(self):
        score = capital_velocity_score(0.10, 0.0)
        assert score == pytest.approx(0.10 / 0.25 * 365.0)

    def test_fast_resolution_high_score(self):
        fast = capital_velocity_score(0.10, 1.0)
        slow = capital_velocity_score(0.10, 30.0)
        assert fast > slow * 20  # 30x faster resolution


# ── Velocity-adjusted EV tests ───────────────────────────────────────

class TestVelocityAdjustedEV:
    def test_fast_market_no_penalty(self):
        result = velocity_adjusted_ev(
            edge=0.10, estimated_days=3.0, taker_fee=0.0, max_days=14.0,
        )
        assert result["penalty"] == 1.0
        assert result["blocked"] is False
        assert result["adjusted_ev"] > 0

    def test_slow_market_penalized(self):
        fast = velocity_adjusted_ev(
            edge=0.10, estimated_days=3.0, max_days=14.0,
        )
        slow = velocity_adjusted_ev(
            edge=0.10, estimated_days=30.0, max_days=14.0,
        )
        assert slow["adjusted_ev"] < fast["adjusted_ev"]
        assert slow["penalty"] < 1.0

    def test_very_slow_market_blocked(self):
        result = velocity_adjusted_ev(
            edge=0.10, estimated_days=60.0, max_days=14.0, decay_rate=0.1,
        )
        # 46 days over → exp(-4.6) ≈ 0.01 → blocked
        assert result["blocked"] is True

    def test_negative_edge_after_fees_blocked(self):
        result = velocity_adjusted_ev(
            edge=0.02, estimated_days=3.0, taker_fee=0.03,
        )
        assert result["blocked"] is True
        assert result["net_edge"] < 0

    def test_fee_subtraction(self):
        result = velocity_adjusted_ev(
            edge=0.10, estimated_days=5.0, taker_fee=0.02, max_days=14.0,
        )
        assert result["net_edge"] == pytest.approx(0.08)
        assert result["blocked"] is False

    def test_returns_all_fields(self):
        result = velocity_adjusted_ev(
            edge=0.10, estimated_days=5.0,
        )
        assert "net_edge" in result
        assert "penalty" in result
        assert "velocity_score" in result
        assert "adjusted_ev" in result
        assert "blocked" in result
