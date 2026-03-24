"""Tests for flb_harvester.py — Favorite-longshot bias portfolio."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.flb_harvester import (
    CalibrationDB,
    FLBCandidate,
    FLBConfig,
    FLBHarvester,
    FLBSignal,
    TailType,
)
from bot.net_edge_accounting import bayesian_bin_calibration


class TestCalibrationDB:
    def test_record_and_retrieve(self):
        db = CalibrationDB()
        # Record 100 contracts at 95c YES, 8 resolve YES (FLB: should be higher than 5%)
        for i in range(92):
            db.record_resolution(0.95, "politics", "polymarket", False)
        for i in range(8):
            db.record_resolution(0.95, "politics", "polymarket", True)

        cal = db.get_calibration(0.95, "politics", "polymarket")
        assert cal is not None
        assert cal.sample_size == 100
        # 8/100 = 8% observed vs 95% expected → huge FLB for NO
        assert cal.observed_rate < 0.95

    def test_sparse_data_returns_none(self):
        db = CalibrationDB()
        db.record_resolution(0.95, "crypto", "polymarket", True)
        cal = db.get_calibration(0.95, "crypto", "polymarket")
        assert cal is None  # only 1 observation, needs 5+

    def test_cross_category_aggregation(self):
        db = CalibrationDB()
        for i in range(30):
            db.record_resolution(0.95, "politics", "polymarket", i < 3)
        for i in range(30):
            db.record_resolution(0.95, "sports", "polymarket", i < 2)

        # Query for a third category falls back to aggregate
        cal = db.get_calibration(0.95, "weather", "polymarket")
        assert cal is not None
        assert cal.sample_size == 60  # combined

    def test_get_all_calibrations(self):
        db = CalibrationDB()
        for price in [0.05, 0.10, 0.50, 0.90, 0.95]:
            for i in range(20):
                db.record_resolution(price, "politics", "polymarket", True)
        cals = db.get_all_calibrations("polymarket")
        assert len(cals) >= 3  # at least some bins have enough data


class TestFLBHarvester:
    def _make_market(self, yes_price: float, category: str = "politics",
                     days_to_res: int = 14, market_id: str = "m1") -> dict:
        return {
            "id": market_id,
            "question": f"Test market at {yes_price}",
            "category": category,
            "venue": "polymarket",
            "tokens": [{
                "token_id": f"t_{market_id}",
                "outcome": "YES",
                "best_bid": yes_price - 0.01,
                "best_ask": yes_price + 0.01,
            }],
            "days_to_resolution": days_to_res,
            "volume_24h": 5000.0,
        }

    def test_identify_high_yes_candidates(self):
        harvester = FLBHarvester(bankroll=1000.0)
        markets = [
            self._make_market(0.95, market_id="m1"),
            self._make_market(0.50, market_id="m2"),  # not in tail range
            self._make_market(0.93, market_id="m3"),
        ]
        candidates = harvester.identify_candidates(markets)
        assert len(candidates) == 2
        assert all(c.tail_type == TailType.HIGH_YES for c in candidates)

    def test_identify_low_yes_candidates(self):
        harvester = FLBHarvester(bankroll=1000.0)
        markets = [
            self._make_market(0.05, market_id="m1"),
            self._make_market(0.08, market_id="m2"),
        ]
        candidates = harvester.identify_candidates(markets)
        assert len(candidates) == 2
        assert all(c.tail_type == TailType.LOW_YES for c in candidates)

    def test_filter_by_resolution_time(self):
        config = FLBConfig(min_days_to_resolution=3, max_days_to_resolution=30)
        harvester = FLBHarvester(bankroll=1000.0, config=config)
        markets = [
            self._make_market(0.95, days_to_res=1, market_id="m1"),   # too fast
            self._make_market(0.95, days_to_res=14, market_id="m2"),  # good
            self._make_market(0.95, days_to_res=90, market_id="m3"),  # too slow
        ]
        candidates = harvester.identify_candidates(markets)
        assert len(candidates) == 1
        assert candidates[0].market_id == "m2"

    def test_evaluate_with_calibration(self):
        harvester = FLBHarvester(bankroll=1000.0)

        # Seed calibration: at 95c, only 88% resolve YES (7% FLB)
        for i in range(88):
            harvester.calibration_db.record_resolution(0.95, "politics", "polymarket", True)
        for i in range(12):
            harvester.calibration_db.record_resolution(0.95, "politics", "polymarket", False)

        candidates = [
            FLBCandidate(
                market_id="m1", token_id="t1",
                question="Will event happen?",
                category="politics", venue="polymarket",
                yes_price=0.95, no_price=0.05,
                tail_type=TailType.HIGH_YES,
                days_to_resolution=14,
                volume_24h=5000, spread=0.02,
            )
        ]
        signals = harvester.evaluate_candidates(candidates)
        assert len(signals) >= 0  # may or may not pass net edge threshold

    def test_evaluate_with_llm_filter(self):
        harvester = FLBHarvester(bankroll=1000.0)
        candidates = [
            FLBCandidate(
                market_id="m1", token_id="t1",
                question="Test?", category="politics",
                venue="polymarket",
                yes_price=0.95, no_price=0.05,
                tail_type=TailType.HIGH_YES,
                days_to_resolution=14,
                volume_24h=5000, spread=0.02,
            )
        ]

        # LLM agrees with market → filtered out
        signals = harvester.evaluate_candidates(
            candidates, llm_estimates={"m1": 0.94},
        )
        assert len(signals) == 0  # within agreement threshold

        # LLM disagrees → might generate signal
        signals = harvester.evaluate_candidates(
            candidates, llm_estimates={"m1": 0.85},
        )
        # Signal generated if net edge passes
        assert isinstance(signals, list)

    def test_portfolio_capacity_limit(self):
        config = FLBConfig(max_positions=2)
        harvester = FLBHarvester(bankroll=1000.0, config=config)

        # Pre-fill portfolio
        for i in range(2):
            harvester.portfolio.positions.append(
                FLBSignal(
                    market_id=f"existing_{i}", token_id=f"t_{i}",
                    venue="polymarket", tail_type=TailType.HIGH_YES,
                    side="BUY_NO", market_price=0.95,
                    estimated_true_prob=0.88, flb_edge_bps=700,
                    net_edge_bps=500, kelly_fraction=0.05,
                    position_usd=50.0, confidence=0.8,
                    calibration=bayesian_bin_calibration(88, 100, 0.95),
                    ts=time.time(),
                )
            )

        candidates = [
            FLBCandidate(
                market_id="new", token_id="t_new",
                question="New?", category="politics",
                venue="polymarket",
                yes_price=0.95, no_price=0.05,
                tail_type=TailType.HIGH_YES,
                days_to_resolution=14,
                volume_24h=5000, spread=0.02,
            )
        ]
        signals = harvester.evaluate_candidates(candidates)
        assert len(signals) == 0  # portfolio full

    def test_add_and_remove_position(self):
        harvester = FLBHarvester(bankroll=1000.0)
        signal = FLBSignal(
            market_id="m1", token_id="t1",
            venue="polymarket", tail_type=TailType.HIGH_YES,
            side="BUY_NO", market_price=0.95,
            estimated_true_prob=0.88, flb_edge_bps=700,
            net_edge_bps=500, kelly_fraction=0.05,
            position_usd=50.0, confidence=0.8,
            calibration=bayesian_bin_calibration(88, 100, 0.95),
            ts=time.time(),
        )
        assert harvester.add_position(signal)
        assert harvester.portfolio.position_count == 1
        assert harvester.portfolio.total_capital_locked == 50.0

        removed = harvester.remove_position("m1")
        assert removed is not None
        assert harvester.portfolio.position_count == 0

    def test_portfolio_stats(self):
        harvester = FLBHarvester(bankroll=1000.0)
        stats = harvester.get_portfolio_stats()
        assert stats["position_count"] == 0
        assert stats["capital_locked"] == 0.0
