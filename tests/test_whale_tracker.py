"""
Tests for bot/whale_tracker.py

Run with:  pytest tests/test_whale_tracker.py -v

All tests use mock / injected data — zero live API calls.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import pytest

from bot.whale_tracker import (
    FRESHNESS_HALF_LIFE_SECONDS,
    FRESHNESS_WINDOW_HOURS_DEFAULT,
    ConsensusSignal,
    WalletProfile,
    WhaleAlert,
    WhaleTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW: float = 1_700_000_000.0  # arbitrary fixed epoch


def make_tracker(**kwargs: Any) -> WhaleTracker:
    """Return a WhaleTracker with a frozen clock and sensible defaults."""
    kwargs.setdefault("_now_fn", lambda: FIXED_NOW)
    return WhaleTracker(**kwargs)


def make_trade(
    wallet: str = "0xabc",
    market_id: str = "mkt-1",
    question: str = "Will BTC go up?",
    side: str = "BUY",
    outcome: str = "YES",
    price: float = 0.60,
    size: float = 2000.0,  # → $1200 at default price
    timestamp: float = FIXED_NOW,
    **extra: Any,
) -> dict:
    return {
        "taker_address": wallet,
        "maker_address": wallet,
        "market_id": market_id,
        "market_question": question,
        "side": side,
        "outcome": outcome,
        "price": price,
        "size": size,
        "timestamp": timestamp,
        **extra,
    }


# ---------------------------------------------------------------------------
# score_wallet tests
# ---------------------------------------------------------------------------


class TestScoreWallet:
    def test_fresh_wallet_high_freshness(self) -> None:
        tracker = make_tracker()
        # Wallet created 1 hour ago → very fresh
        one_hour_ago = FIXED_NOW - 3600
        trades = [
            {
                "market_id": "mkt-1",
                "price": 0.60,
                "size": 5000.0,
                "timestamp": one_hour_ago,
            }
        ]
        profile = tracker.score_wallet("0xfresh", trades)
        assert profile.freshness_score > 0.9, f"Expected freshness > 0.9, got {profile.freshness_score}"

    def test_old_wallet_low_freshness(self) -> None:
        tracker = make_tracker()
        # Wallet 60 days old
        sixty_days_ago = FIXED_NOW - 60 * 24 * 3600
        trades = [
            {
                "market_id": f"mkt-{i}",
                "price": 0.5,
                "size": 10.0,
                "timestamp": sixty_days_ago,
            }
            for i in range(20)
        ]
        profile = tracker.score_wallet("0xold", trades)
        assert profile.freshness_score < 0.05, f"Expected freshness < 0.05, got {profile.freshness_score}"

    def test_concentrated_wallet_high_concentration(self) -> None:
        tracker = make_tracker()
        trades = [
            {"market_id": "mkt-1", "price": 0.6, "size": 500.0, "timestamp": FIXED_NOW}
            for _ in range(10)
        ]
        profile = tracker.score_wallet("0xconc", trades)
        # All trades in one market → concentration = 1 / sqrt(1) = 1.0
        assert profile.concentration_score == pytest.approx(1.0), profile.concentration_score

    def test_diverse_wallet_lower_concentration(self) -> None:
        tracker = make_tracker()
        trades = [
            {"market_id": f"mkt-{i}", "price": 0.5, "size": 50.0, "timestamp": FIXED_NOW}
            for i in range(25)
        ]
        profile = tracker.score_wallet("0xdiverse", trades)
        # 25 unique markets → score = 1/sqrt(25) = 0.2
        assert profile.concentration_score == pytest.approx(1.0 / math.sqrt(25), abs=1e-6)

    def test_suspicious_flag_fresh_concentrated_large(self) -> None:
        tracker = make_tracker()
        # Fresh (1 hour old), single market, huge size
        trades = [
            {
                "market_id": "mkt-1",
                "price": 0.60,
                "size": 10_000.0,  # $6000 USD
                "timestamp": FIXED_NOW - 3600,
            }
        ]
        profile = tracker.score_wallet("0xsuspect", trades)
        assert profile.is_suspicious is True
        assert "fresh_wallet" in profile.tags
        assert "high_concentration" in profile.tags

    def test_not_suspicious_old_diverse_small(self) -> None:
        tracker = make_tracker()
        thirty_days_ago = FIXED_NOW - 30 * 24 * 3600
        trades = [
            {
                "market_id": f"mkt-{i}",
                "price": 0.5,
                "size": 20.0,  # $10 each — tiny
                "timestamp": thirty_days_ago + i * 3600,
            }
            for i in range(15)
        ]
        profile = tracker.score_wallet("0xclean", trades)
        assert profile.is_suspicious is False

    def test_mega_trade_triggers_suspicious(self) -> None:
        tracker = make_tracker()
        trades = [
            {
                "market_id": "mkt-1",
                "price": 0.5,
                "size": 50_000.0,  # $25000 — above LARGE_SINGLE_TRADE_USD
                "timestamp": FIXED_NOW - 7 * 24 * 3600,
            }
        ]
        profile = tracker.score_wallet("0xmega", trades)
        assert profile.is_suspicious is True
        assert "mega_trade" in profile.tags

    def test_empty_trades_returns_profile(self) -> None:
        tracker = make_tracker()
        profile = tracker.score_wallet("0xnew", [])
        assert profile.address == "0xnew"
        assert profile.total_trades == 0
        assert profile.freshness_score == 1.0  # no history → treat as new

    def test_win_rate_from_resolved_trades(self) -> None:
        tracker = make_tracker()
        trades = [
            {"market_id": "mkt-1", "price": 0.5, "size": 100.0, "timestamp": FIXED_NOW, "_resolved_win": True},
            {"market_id": "mkt-2", "price": 0.5, "size": 100.0, "timestamp": FIXED_NOW, "_resolved_win": True},
            {"market_id": "mkt-3", "price": 0.5, "size": 100.0, "timestamp": FIXED_NOW, "_resolved_win": False},
            {"market_id": "mkt-4", "price": 0.5, "size": 100.0, "timestamp": FIXED_NOW, "_resolved_win": False},
        ]
        profile = tracker.score_wallet("0xwintest", trades)
        assert profile.win_rate == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# ingest_trade tests
# ---------------------------------------------------------------------------


class TestIngestTrade:
    def test_large_fresh_wallet_returns_alert(self) -> None:
        tracker = make_tracker(min_trade_size_usd=500.0, anomaly_threshold=0.3)
        # Fresh wallet (just now), single market, large trade
        trade = make_trade(
            wallet="0xfresh",
            price=0.60,
            size=2000.0,  # $1200
            timestamp=FIXED_NOW,
        )
        alert = tracker.ingest_trade(trade)
        assert alert is not None
        assert isinstance(alert, WhaleAlert)
        assert alert.wallet == "0xfresh"
        assert alert.side in ("YES", "NO")

    def test_small_trade_returns_none(self) -> None:
        tracker = make_tracker(min_trade_size_usd=1000.0)
        trade = make_trade(price=0.50, size=1.0)  # $0.50
        result = tracker.ingest_trade(trade)
        assert result is None

    def test_old_wallet_small_trade_returns_none(self) -> None:
        tracker = make_tracker(min_trade_size_usd=100.0, anomaly_threshold=0.9)
        # Build up an old diverse wallet first
        old_ts = FIXED_NOW - 45 * 24 * 3600
        for i in range(10):
            tracker.ingest_trade(
                make_trade(
                    wallet="0xold",
                    market_id=f"mkt-{i}",
                    price=0.5,
                    size=10.0,
                    timestamp=old_ts,
                )
            )
        # Now tiny trade on new market — should not fire at threshold 0.9
        result = tracker.ingest_trade(
            make_trade(wallet="0xold", market_id="mkt-99", price=0.5, size=200.0, timestamp=FIXED_NOW)
        )
        # With high threshold (0.9) it should not fire
        assert result is None

    def test_ingest_updates_wallet_profile(self) -> None:
        tracker = make_tracker(min_trade_size_usd=10.0, anomaly_threshold=0.99)
        trade = make_trade(wallet="0xtrade", price=0.5, size=100.0)
        tracker.ingest_trade(trade)
        assert "0xtrade" in tracker.wallet_profiles
        profile = tracker.wallet_profiles["0xtrade"]
        assert profile.total_trades == 1
        assert profile.total_volume_usd == pytest.approx(50.0, abs=0.01)

    def test_sell_side_sets_correct_direction(self) -> None:
        tracker = make_tracker(min_trade_size_usd=100.0, anomaly_threshold=0.99)
        trade = make_trade(wallet="0xsell", side="SELL", outcome="YES", price=0.6, size=1000.0)
        tracker.ingest_trade(trade)
        # SELL YES → direction = NO
        positions = tracker._market_positions.get("mkt-1", {})
        assert positions.get("0xsell", {}).get("side") == "NO"

    def test_alerts_list_grows(self) -> None:
        tracker = make_tracker(min_trade_size_usd=100.0, anomaly_threshold=0.01)
        for i in range(3):
            tracker.ingest_trade(make_trade(wallet=f"0x{i:04d}", price=0.6, size=1000.0))
        assert len(tracker.alerts) == 3

    def test_trade_below_threshold_not_added_to_profiles(self) -> None:
        tracker = make_tracker(min_trade_size_usd=5000.0)
        trade = make_trade(wallet="0xsmall", price=0.5, size=1.0)
        tracker.ingest_trade(trade)
        assert "0xsmall" not in tracker.wallet_profiles


# ---------------------------------------------------------------------------
# compute_anomaly_score tests
# ---------------------------------------------------------------------------


class TestComputeAnomalyScore:
    def test_known_inputs_produce_expected_range(self) -> None:
        tracker = make_tracker()
        # A very fresh wallet
        profile = WalletProfile(
            address="0xtest",
            freshness_score=1.0,
            concentration_score=1.0,
            avg_trade_size_usd=100.0,
        )
        trade = {
            "size": 10_000.0,
            "price": 0.60,
            "market_daily_volume": 0.0,  # unknown → niche component = 0.5
        }
        score, reasons = tracker.compute_anomaly_score(profile, trade)
        assert 0.0 <= score <= 1.0
        # Fresh + concentrated → score should be high
        assert score >= 0.5

    def test_niche_market_elevates_score(self) -> None:
        tracker = make_tracker()
        profile = WalletProfile(
            address="0xtest",
            freshness_score=0.5,
            concentration_score=0.5,
            avg_trade_size_usd=500.0,
        )
        trade_niche = {"size": 1000.0, "price": 0.6, "market_daily_volume": 10_000.0}
        trade_liquid = {"size": 1000.0, "price": 0.6, "market_daily_volume": 500_000.0}
        score_niche, _ = tracker.compute_anomaly_score(profile, trade_niche)
        score_liquid, _ = tracker.compute_anomaly_score(profile, trade_liquid)
        assert score_niche > score_liquid

    def test_pre_resolution_timing_elevates_score(self) -> None:
        tracker = make_tracker()
        profile = WalletProfile(
            address="0xtest",
            freshness_score=0.5,
            concentration_score=0.5,
            avg_trade_size_usd=500.0,
        )
        # Resolution in 2 hours
        trade_pre = {
            "size": 1000.0,
            "price": 0.6,
            "market_daily_volume": 100_000.0,
            "expected_resolution_ts": FIXED_NOW + 2 * 3600,
        }
        trade_far = {
            "size": 1000.0,
            "price": 0.6,
            "market_daily_volume": 100_000.0,
            "expected_resolution_ts": FIXED_NOW + 72 * 3600,
        }
        score_pre, reasons_pre = tracker.compute_anomaly_score(profile, trade_pre)
        score_far, _ = tracker.compute_anomaly_score(profile, trade_far)
        assert score_pre > score_far
        assert "pre_resolution_timing" in reasons_pre

    def test_size_spike_reason_added(self) -> None:
        tracker = make_tracker()
        profile = WalletProfile(
            address="0xtest",
            freshness_score=0.1,
            concentration_score=0.2,
            avg_trade_size_usd=100.0,
        )
        trade = {"size": 10_000.0, "price": 0.5, "market_daily_volume": 0.0}
        _, reasons = tracker.compute_anomaly_score(profile, trade)
        assert "size_spike" in reasons

    def test_returns_tuple_score_and_list(self) -> None:
        tracker = make_tracker()
        profile = WalletProfile(address="0xtest")
        trade = {"size": 100.0, "price": 0.5}
        result = tracker.compute_anomaly_score(profile, trade)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], list)


# ---------------------------------------------------------------------------
# get_consensus_signals tests
# ---------------------------------------------------------------------------


class TestGetConsensusSignals:
    def _setup_wallets_on_market(
        self,
        tracker: WhaleTracker,
        market_id: str,
        yes_count: int,
        no_count: int,
        price: float = 0.6,
        size: float = 2000.0,
    ) -> None:
        """Helper: populate market positions directly."""
        tracker._market_positions[market_id] = {}
        for i in range(yes_count):
            wallet = f"0xyes{i:04d}"
            size_usd = size * price
            tracker._market_positions[market_id][wallet] = {
                "side": "YES",
                "size_usd": size_usd,
                "question": f"Will thing happen? ({market_id})",
            }
            tracker.wallet_profiles[wallet] = WalletProfile(
                address=wallet,
                profitability_score=0.6,
                freshness_score=0.9,
                concentration_score=0.9,
                avg_trade_size_usd=size_usd,
            )
        for i in range(no_count):
            wallet = f"0xno{i:04d}"
            size_usd = size * price
            tracker._market_positions[market_id][wallet] = {
                "side": "NO",
                "size_usd": size_usd,
                "question": f"Will thing happen? ({market_id})",
            }
            tracker.wallet_profiles[wallet] = WalletProfile(
                address=wallet,
                profitability_score=0.4,
                freshness_score=0.2,
                avg_trade_size_usd=size_usd,
            )

    def test_4_of_5_agree_yes_generates_signal(self) -> None:
        tracker = make_tracker(consensus_threshold=0.7)
        self._setup_wallets_on_market(tracker, "mkt-1", yes_count=4, no_count=1)
        signals = tracker.get_consensus_signals()
        assert len(signals) == 1
        sig = signals[0]
        assert sig.direction == "YES"
        assert sig.agreeing_wallets == 4
        assert sig.total_tracked == 5
        assert sig.consensus_pct == pytest.approx(0.8, abs=1e-9)

    def test_3_yes_2_no_below_70_threshold_no_signal(self) -> None:
        tracker = make_tracker(consensus_threshold=0.7)
        self._setup_wallets_on_market(tracker, "mkt-2", yes_count=3, no_count=2)
        signals = tracker.get_consensus_signals()
        # 3/5 = 60% < 70%
        assert len(signals) == 0

    def test_below_minimum_wallets_no_signal(self) -> None:
        tracker = make_tracker(consensus_threshold=0.7)
        self._setup_wallets_on_market(tracker, "mkt-3", yes_count=2, no_count=0)
        # Only 2 wallets, MIN_CONSENSUS_WALLETS = 3
        signals = tracker.get_consensus_signals()
        assert len(signals) == 0

    def test_signal_sorted_by_confidence(self) -> None:
        tracker = make_tracker(consensus_threshold=0.5)
        self._setup_wallets_on_market(tracker, "mkt-A", yes_count=5, no_count=0)
        self._setup_wallets_on_market(tracker, "mkt-B", yes_count=3, no_count=2)
        signals = tracker.get_consensus_signals()
        confidences = [s.confidence for s in signals]
        assert confidences == sorted(confidences, reverse=True)

    def test_signal_recommended_size_capped(self) -> None:
        tracker = make_tracker(consensus_threshold=0.5)
        self._setup_wallets_on_market(tracker, "mkt-1", yes_count=10, no_count=0)
        signals = tracker.get_consensus_signals()
        if signals:
            assert signals[0].recommended_size_usd <= 50.0

    def test_exact_threshold_boundary(self) -> None:
        # 70% exactly should pass when threshold=0.7
        tracker = make_tracker(consensus_threshold=0.7)
        self._setup_wallets_on_market(tracker, "mkt-x", yes_count=7, no_count=3)
        signals = tracker.get_consensus_signals()
        assert len(signals) == 1
        assert signals[0].consensus_pct == pytest.approx(0.7, abs=1e-9)


# ---------------------------------------------------------------------------
# add_known_wallet tests
# ---------------------------------------------------------------------------


class TestAddKnownWallet:
    def test_add_creates_profile(self) -> None:
        tracker = make_tracker()
        tracker.add_known_wallet("0xknown", label="top_trader", trust_score=0.9)
        assert "0xknown" in tracker.wallet_profiles

    def test_add_stores_label_and_trust(self) -> None:
        tracker = make_tracker()
        tracker.add_known_wallet("0xknown", label="whale_1", trust_score=0.85)
        profile = tracker.wallet_profiles["0xknown"]
        assert profile._label == "whale_1"
        assert profile._trust_score == pytest.approx(0.85)

    def test_add_existing_wallet_updates_label(self) -> None:
        tracker = make_tracker()
        tracker.add_known_wallet("0xknown", label="old")
        tracker.add_known_wallet("0xknown", label="new", trust_score=0.99)
        assert tracker.wallet_profiles["0xknown"]._label == "new"

    def test_get_top_wallets_includes_known(self) -> None:
        tracker = make_tracker()
        tracker.add_known_wallet("0xknown", trust_score=0.9)
        result = tracker.get_top_wallets(k=10)
        addresses = [p.address for p in result]
        assert "0xknown" in addresses


# ---------------------------------------------------------------------------
# get_top_wallets tests
# ---------------------------------------------------------------------------


class TestGetTopWallets:
    def test_returns_sorted_by_profitability(self) -> None:
        tracker = make_tracker()
        for i, score in enumerate([0.2, 0.8, 0.5, 0.9, 0.1]):
            p = WalletProfile(address=f"0x{i:04d}", profitability_score=score)
            tracker.wallet_profiles[f"0x{i:04d}"] = p
        top = tracker.get_top_wallets(k=3)
        assert top[0].profitability_score >= top[1].profitability_score >= top[2].profitability_score

    def test_k_limits_result(self) -> None:
        tracker = make_tracker()
        for i in range(10):
            tracker.wallet_profiles[f"0x{i:04d}"] = WalletProfile(
                address=f"0x{i:04d}", profitability_score=float(i) / 10
            )
        result = tracker.get_top_wallets(k=5)
        assert len(result) == 5

    def test_returns_empty_when_no_wallets(self) -> None:
        tracker = make_tracker()
        result = tracker.get_top_wallets()
        assert result == []


# ---------------------------------------------------------------------------
# get_market_whale_activity tests
# ---------------------------------------------------------------------------


class TestGetMarketWhaleActivity:
    def test_summary_schema(self) -> None:
        tracker = make_tracker(min_trade_size_usd=100.0, anomaly_threshold=0.01)
        for i in range(3):
            tracker.ingest_trade(make_trade(wallet=f"0x{i:04d}", size=1000.0, price=0.6))
        result = tracker.get_market_whale_activity("mkt-1")
        assert "total_whale_volume" in result
        assert "dominant_side" in result
        assert "num_whales" in result
        assert "alerts" in result

    def test_unknown_market_returns_zeros(self) -> None:
        tracker = make_tracker()
        result = tracker.get_market_whale_activity("nonexistent-mkt")
        assert result["total_whale_volume"] == 0.0
        assert result["num_whales"] == 0

    def test_dominant_side_reflects_volume(self) -> None:
        tracker = make_tracker()
        tracker._market_positions["mkt-1"] = {
            "0xA": {"side": "YES", "size_usd": 5000.0, "question": "test"},
            "0xB": {"side": "NO", "size_usd": 1000.0, "question": "test"},
        }
        result = tracker.get_market_whale_activity("mkt-1")
        assert result["dominant_side"] == "YES"
        assert result["total_whale_volume"] == pytest.approx(6000.0)


# ---------------------------------------------------------------------------
# export / import watchlist tests
# ---------------------------------------------------------------------------


class TestWatchlistRoundtrip:
    def test_export_import_roundtrip(self) -> None:
        tracker = make_tracker()
        tracker.wallet_profiles["0xA"] = WalletProfile(
            address="0xA",
            total_trades=10,
            total_volume_usd=5000.0,
            win_rate=0.7,
            profitability_score=0.65,
            is_suspicious=True,
            tags=["fresh_wallet"],
        )
        exported = tracker.export_watchlist()
        assert len(exported) == 1

        tracker2 = make_tracker()
        count = tracker2.import_watchlist(exported)
        assert count == 1
        assert "0xA" in tracker2.wallet_profiles
        restored = tracker2.wallet_profiles["0xA"]
        assert restored.total_trades == 10
        assert restored.total_volume_usd == pytest.approx(5000.0)
        assert restored.win_rate == pytest.approx(0.7)
        assert restored.is_suspicious is True
        assert "fresh_wallet" in restored.tags

    def test_import_skips_missing_address(self) -> None:
        tracker = make_tracker()
        count = tracker.import_watchlist([{"total_trades": 5}])  # no address
        assert count == 0

    def test_export_excludes_private_fields(self) -> None:
        tracker = make_tracker()
        tracker.wallet_profiles["0xB"] = WalletProfile(address="0xB")
        exported = tracker.export_watchlist()
        for key in exported[0]:
            assert not key.startswith("_"), f"Private field leaked: {key}"

    def test_import_multiple(self) -> None:
        tracker = make_tracker()
        wallets = [{"address": f"0x{i:04d}"} for i in range(5)]
        count = tracker.import_watchlist(wallets)
        assert count == 5
        assert len(tracker.wallet_profiles) == 5


# ---------------------------------------------------------------------------
# diagnostics tests
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_returns_correct_schema(self) -> None:
        tracker = make_tracker()
        d = tracker.diagnostics()
        expected_keys = {
            "wallets_tracked",
            "alerts_generated",
            "signals_emitted",
            "trades_ingested",
            "suspicious_wallets",
            "markets_with_positions",
            "top_wallet_by_profitability",
            "min_trade_size_usd",
            "anomaly_threshold",
            "consensus_threshold",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_diagnostics_counts_increment(self) -> None:
        tracker = make_tracker(min_trade_size_usd=10.0, anomaly_threshold=0.01)
        assert tracker.diagnostics()["wallets_tracked"] == 0
        assert tracker.diagnostics()["trades_ingested"] == 0
        tracker.ingest_trade(make_trade(price=0.5, size=1000.0))
        d = tracker.diagnostics()
        assert d["wallets_tracked"] == 1
        assert d["trades_ingested"] == 1

    def test_diagnostics_suspicious_count(self) -> None:
        tracker = make_tracker()
        tracker.wallet_profiles["0xA"] = WalletProfile(address="0xA", is_suspicious=True)
        tracker.wallet_profiles["0xB"] = WalletProfile(address="0xB", is_suspicious=False)
        d = tracker.diagnostics()
        assert d["suspicious_wallets"] == 1

    def test_diagnostics_top_wallet_none_when_empty(self) -> None:
        tracker = make_tracker()
        d = tracker.diagnostics()
        assert d["top_wallet_by_profitability"] is None


# ---------------------------------------------------------------------------
# min_trade_size filtering
# ---------------------------------------------------------------------------


class TestMinTradeSizeFilter:
    def test_exactly_at_threshold_passes(self) -> None:
        tracker = make_tracker(min_trade_size_usd=600.0, anomaly_threshold=0.0)
        trade = make_trade(price=0.6, size=1000.0)  # 600.0 USD exactly
        alert = tracker.ingest_trade(trade)
        assert alert is not None

    def test_just_below_threshold_skipped(self) -> None:
        tracker = make_tracker(min_trade_size_usd=600.01)
        trade = make_trade(price=0.6, size=1000.0)  # 600.0 USD
        result = tracker.ingest_trade(trade)
        assert result is None

    def test_large_min_filters_everything(self) -> None:
        tracker = make_tracker(min_trade_size_usd=1_000_000.0)
        for _ in range(5):
            tracker.ingest_trade(make_trade(price=0.5, size=10_000.0))
        assert len(tracker.wallet_profiles) == 0


# ---------------------------------------------------------------------------
# Freshness decay over time
# ---------------------------------------------------------------------------


class TestFreshnessDecay:
    def test_freshness_at_zero_age_is_one(self) -> None:
        tracker = make_tracker()
        trades = [{"market_id": "m", "price": 0.5, "size": 10.0, "timestamp": FIXED_NOW}]
        profile = tracker.score_wallet("0xnew", trades)
        assert profile.freshness_score == pytest.approx(1.0, abs=1e-6)

    def test_freshness_at_half_life_is_half(self) -> None:
        tracker = make_tracker()
        half_life_ago = FIXED_NOW - FRESHNESS_HALF_LIFE_SECONDS
        trades = [{"market_id": "m", "price": 0.5, "size": 10.0, "timestamp": half_life_ago}]
        profile = tracker.score_wallet("0xhalf", trades)
        assert profile.freshness_score == pytest.approx(0.5, abs=0.01)

    def test_freshness_decreases_with_age(self) -> None:
        tracker = make_tracker()
        scores = []
        for days in [0, 3, 7, 14, 30]:
            ts = FIXED_NOW - days * 24 * 3600
            trades = [{"market_id": "m", "price": 0.5, "size": 10.0, "timestamp": ts}]
            profile = tracker.score_wallet(f"0x{days}", trades)
            scores.append(profile.freshness_score)
        # Should be strictly decreasing
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1], f"scores[{i}]={scores[i]} not > scores[{i+1}]={scores[i+1]}"


# ---------------------------------------------------------------------------
# async fetch_recent_trades (injection path)
# ---------------------------------------------------------------------------


class TestFetchRecentTrades:
    def test_injected_data_returned_without_network(self) -> None:
        tracker = make_tracker()
        injected = [make_trade(wallet="0xinj")]

        async def _run() -> list[dict]:
            return await tracker.fetch_recent_trades(_injected=injected)

        result = asyncio.run(_run())
        assert result == injected

    def test_empty_injection_returns_empty(self) -> None:
        tracker = make_tracker()

        async def _run() -> list[dict]:
            return await tracker.fetch_recent_trades(_injected=[])

        result = asyncio.run(_run())
        assert result == []
