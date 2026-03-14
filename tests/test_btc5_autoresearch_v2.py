"""Tests for btc5_autoresearch_v2 — evidence-informed hypothesis generation,
kill list, row-hash caching, and adaptive Monte Carlo paths."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from scripts.btc5_autoresearch_v2 import (
    KILL_COOLDOWN_HOURS,
    KILL_MAX_NEGATIVE_PNL,
    KILL_MAX_WIN_RATE,
    KILL_MIN_FILLS,
    KILL_MIN_PROFIT_FACTOR,
    MC_PATHS_FRESH,
    MC_PATHS_NORMAL,
    MC_PATHS_STALE,
    adaptive_mc_paths,
    build_evidence_weights,
    compute_row_hash,
    enhanced_cadence_decision,
    evidence_weight_for_hypothesis,
    is_hypothesis_killed,
    load_kill_list,
    load_row_hash_cache,
    save_evidence_cache,
    save_kill_list,
    save_row_hash_cache,
    should_skip_cycle,
    v2_cycle_metadata,
)


def _make_row(
    *,
    pnl: float = 1.0,
    direction: str = "DOWN",
    session_name: str = "open_et",
    abs_delta: float = 0.0001,
    order_status: str = "live_filled",
    created_at: str = "2026-03-10T12:00:00+00:00",
) -> dict[str, Any]:
    return {
        "pnl_usd": pnl,
        "direction": direction,
        "session_name": session_name,
        "abs_delta": abs_delta,
        "order_status": order_status,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Row-hash tests
# ---------------------------------------------------------------------------


class TestComputeRowHash:
    def test_empty_rows(self):
        h = compute_row_hash([])
        assert isinstance(h, str)
        assert len(h) == 16

    def test_deterministic(self):
        rows = [_make_row(), _make_row(pnl=-0.5)]
        assert compute_row_hash(rows) == compute_row_hash(rows)

    def test_changes_with_new_data(self):
        rows_a = [_make_row()]
        rows_b = [_make_row(), _make_row(pnl=2.0)]
        assert compute_row_hash(rows_a) != compute_row_hash(rows_b)


class TestShouldSkipCycle:
    def test_no_cache_no_skip(self, tmp_path: Path):
        cache_path = tmp_path / "hash.json"
        skip, h = should_skip_cycle([_make_row()], cache_path)
        assert not skip

    def test_skip_when_hash_matches(self, tmp_path: Path):
        cache_path = tmp_path / "hash.json"
        rows = [_make_row()]
        _, h = should_skip_cycle(rows, cache_path)
        save_row_hash_cache(h, None, cache_path)
        skip, _ = should_skip_cycle(rows, cache_path)
        assert skip

    def test_no_skip_when_data_changes(self, tmp_path: Path):
        cache_path = tmp_path / "hash.json"
        rows = [_make_row()]
        _, h = should_skip_cycle(rows, cache_path)
        save_row_hash_cache(h, None, cache_path)
        rows.append(_make_row(pnl=5.0))
        skip, _ = should_skip_cycle(rows, cache_path)
        assert not skip


# ---------------------------------------------------------------------------
# Adaptive Monte Carlo paths
# ---------------------------------------------------------------------------


class TestAdaptiveMcPaths:
    def test_fresh_fills_increase_paths(self):
        paths = adaptive_mc_paths(
            live_fill_delta=3,
            validation_delta=2,
            probe_freshness_hours=0.5,
        )
        assert paths >= MC_PATHS_NORMAL

    def test_stale_reduces_paths(self):
        paths = adaptive_mc_paths(
            live_fill_delta=0,
            validation_delta=0,
            probe_freshness_hours=24.0,
        )
        assert paths <= MC_PATHS_STALE

    def test_normal_when_recent_no_fills(self):
        paths = adaptive_mc_paths(
            live_fill_delta=0,
            validation_delta=0,
            probe_freshness_hours=3.0,
        )
        assert paths == MC_PATHS_NORMAL

    def test_none_freshness_treated_as_stale(self):
        paths = adaptive_mc_paths(
            live_fill_delta=0,
            validation_delta=0,
            probe_freshness_hours=None,
        )
        assert paths <= MC_PATHS_STALE


# ---------------------------------------------------------------------------
# Evidence weights
# ---------------------------------------------------------------------------


class TestBuildEvidenceWeights:
    def test_empty_rows(self):
        weights = build_evidence_weights([])
        assert "direction" in weights
        assert "session" in weights
        assert "delta_bucket" in weights

    def test_winning_direction_boosted(self):
        rows = [_make_row(direction="DOWN", pnl=2.0) for _ in range(10)]
        rows.extend([_make_row(direction="UP", pnl=-1.0) for _ in range(10)])
        weights = build_evidence_weights(rows)
        assert weights["direction"]["DOWN"] > 1.0
        assert weights["direction"]["UP"] < 1.0

    def test_skips_non_filled(self):
        rows = [_make_row(order_status="shadow_only") for _ in range(5)]
        weights = build_evidence_weights(rows)
        assert weights["direction"] == {}


class TestEvidenceWeightForHypothesis:
    def test_known_winning_direction(self):
        weights = {"direction": {"DOWN": 1.8}, "session": {}, "delta_bucket": {}}
        w = evidence_weight_for_hypothesis(
            weights, direction="DOWN", session_name="any", max_abs_delta=None
        )
        assert w == 1.8

    def test_unknown_direction_neutral(self):
        weights = {"direction": {}, "session": {}, "delta_bucket": {}}
        w = evidence_weight_for_hypothesis(
            weights, direction="DOWN", session_name="any", max_abs_delta=None
        )
        assert w == 1.0

    def test_combined_weights(self):
        weights = {
            "direction": {"DOWN": 1.5},
            "session": {"open_et": 1.3},
            "delta_bucket": {"medium": 1.2},
        }
        w = evidence_weight_for_hypothesis(
            weights, direction="DOWN", session_name="open_et", max_abs_delta=0.0001
        )
        assert w == round(1.5 * 1.3 * 1.2, 4)


class TestSaveLoadEvidenceCache:
    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        weights = {"direction": {"DOWN": 1.5}, "session": {}, "delta_bucket": {}}
        save_evidence_cache(weights, path)
        from scripts.btc5_autoresearch_v2 import load_evidence_cache
        loaded = load_evidence_cache(path)
        assert loaded["direction"]["DOWN"] == 1.5


# ---------------------------------------------------------------------------
# Kill list
# ---------------------------------------------------------------------------


class TestKillList:
    def test_load_empty(self, tmp_path: Path):
        path = tmp_path / "kill.json"
        kl = load_kill_list(path)
        assert kl == {"killed": {}, "version": 1}

    def test_save_and_load(self, tmp_path: Path):
        path = tmp_path / "kill.json"
        kl = {"killed": {"hyp_test": {"killed_at": "2026-03-10T00:00:00+00:00"}}, "version": 1}
        save_kill_list(kl, path)
        loaded = load_kill_list(path)
        assert "hyp_test" in loaded["killed"]

    def test_is_killed_within_cooldown(self):
        now = datetime.now(timezone.utc)
        kl = {
            "killed": {
                "hyp_test": {"killed_at": now.isoformat()},
            }
        }
        assert is_hypothesis_killed(kl, "hyp_test")

    def test_not_killed_if_absent(self):
        kl = {"killed": {}}
        assert not is_hypothesis_killed(kl, "hyp_test")

    def test_not_killed_after_cooldown(self):
        from datetime import timedelta
        old = datetime.now(timezone.utc) - timedelta(hours=KILL_COOLDOWN_HOURS + 1)
        kl = {"killed": {"hyp_test": {"killed_at": old.isoformat()}}}
        assert not is_hypothesis_killed(kl, "hyp_test")


class TestEvaluateForKill:
    def test_not_enough_fills(self):
        from scripts.btc5_autoresearch_v2 import evaluate_for_kill
        rows = [_make_row(pnl=-1.0) for _ in range(5)]
        result = evaluate_for_kill(rows, "hyp_test")
        assert result is None  # Not enough fills

    def test_kills_consistent_loser(self):
        from scripts.btc5_autoresearch_v2 import evaluate_for_kill
        # Create rows that match default hypothesis (no filters)
        rows = [_make_row(pnl=-0.5) for _ in range(KILL_MIN_FILLS + 5)]
        result = evaluate_for_kill(rows, "hyp_test")
        assert result is not None
        assert len(result["kill_reasons"]) > 0

    def test_does_not_kill_winner(self):
        from scripts.btc5_autoresearch_v2 import evaluate_for_kill
        rows = [_make_row(pnl=1.0) for _ in range(KILL_MIN_FILLS + 5)]
        result = evaluate_for_kill(rows, "hyp_test")
        assert result is None


# ---------------------------------------------------------------------------
# Enhanced cadence
# ---------------------------------------------------------------------------


class TestEnhancedCadence:
    def test_accelerates_on_new_fills(self):
        entry = {
            "current_probe": {
                "live_filled_rows_delta": 3,
                "validation_live_filled_rows_delta": 1,
                "probe_freshness_hours": 0.5,
            },
            "validation_live_filled_rows": 130,
        }
        result = enhanced_cadence_decision(
            entry=entry,
            previous_entry=None,
            base_interval_seconds=300,
        )
        assert result["mode"] == "accelerated"
        assert result["recommended_interval_seconds"] < 300

    def test_deep_sleep_when_very_stale(self):
        entry = {
            "current_probe": {
                "live_filled_rows_delta": 0,
                "validation_live_filled_rows_delta": 0,
                "probe_freshness_hours": 24.0,
            },
            "validation_live_filled_rows": 100,
        }
        result = enhanced_cadence_decision(
            entry=entry,
            previous_entry=None,
            base_interval_seconds=300,
            consecutive_no_evidence_cycles=10,
        )
        assert result["mode"] == "deep_sleep"
        assert result["recommended_interval_seconds"] > 300

    def test_trading_hours_watch(self):
        entry = {
            "current_probe": {
                "live_filled_rows_delta": 0,
                "validation_live_filled_rows_delta": 0,
                "probe_freshness_hours": 0.5,
            },
            "validation_live_filled_rows": 100,
        }
        with mock.patch(
            "scripts.btc5_autoresearch_v2._now_utc",
            return_value=datetime(2026, 3, 14, 16, 0, tzinfo=timezone.utc),
        ):
            result = enhanced_cadence_decision(
                entry=entry,
                previous_entry=None,
                base_interval_seconds=300,
            )
        assert result["mode"] == "trading_hours_watch"

    def test_progressive_backoff(self):
        entry = {
            "current_probe": {
                "live_filled_rows_delta": 0,
                "validation_live_filled_rows_delta": 0,
                "probe_freshness_hours": 3.0,
            },
            "validation_live_filled_rows": 100,
        }
        r1 = enhanced_cadence_decision(
            entry=entry,
            previous_entry=None,
            base_interval_seconds=300,
            consecutive_no_evidence_cycles=1,
        )
        r2 = enhanced_cadence_decision(
            entry=entry,
            previous_entry=None,
            base_interval_seconds=300,
            consecutive_no_evidence_cycles=5,
        )
        assert r2["recommended_interval_seconds"] >= r1["recommended_interval_seconds"]


# ---------------------------------------------------------------------------
# v2 cycle metadata
# ---------------------------------------------------------------------------


class TestV2CycleMetadata:
    def test_builds_metadata(self):
        meta = v2_cycle_metadata(
            rows=[_make_row()],
            kill_list={"killed": {"hyp_a": {}}},
            evidence_weights={"direction": {"DOWN": 1.5}},
            row_hash="abc123",
            skipped=False,
            mc_paths=2000,
            newly_killed=[],
        )
        assert meta["v2_version"] == "2.0.0"
        assert meta["killed_hypotheses_total"] == 1
        assert meta["mc_paths_used"] == 2000
        assert not meta["cycle_skipped"]
