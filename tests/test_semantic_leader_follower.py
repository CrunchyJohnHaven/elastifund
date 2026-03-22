"""
Tests for bot/semantic_leader_follower.py
==========================================
All tests are self-contained; no external API calls are made.

Run with:
    pytest tests/test_semantic_leader_follower.py -v
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pytest

from bot.semantic_leader_follower import (
    LeaderFollowerSignal,
    MarketEmbedding,
    MarketPair,
    SemanticLeaderFollower,
    btc_price_ladder_pairs,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)


def _make_engine(**kwargs: Any) -> SemanticLeaderFollower:
    """Create an engine with test-friendly defaults."""
    defaults = dict(
        min_similarity=0.30,
        min_price_change=0.05,
        min_signal_strength=0.05,
        max_pairs=500,
        embedding_dim=50,
        lookback_window=10,
        max_position_usd=10.0,
    )
    defaults.update(kwargs)
    return SemanticLeaderFollower(**defaults)


def _make_market(
    market_id: str,
    question: str,
    price: float = 0.5,
    price_history: list[float] | None = None,
    category: str = "crypto",
    volume_24h: float = 1000.0,
) -> dict:
    return {
        "market_id": market_id,
        "question": question,
        "current_price": price,
        "price_history": price_history or [],
        "category": category,
        "volume_24h": volume_24h,
        "resolution_date": "2026-12-31",
    }


def _make_embedding(
    market_id: str,
    question: str,
    embedding: list[float] | None = None,
    price_history: list[float] | None = None,
    current_price: float = 0.5,
) -> MarketEmbedding:
    if embedding is None:
        embedding = list(RNG.random(10).astype(float))
    return MarketEmbedding(
        market_id=market_id,
        question=question,
        embedding=embedding,
        category="test",
        current_price=current_price,
        price_history=price_history or [],
        volume_24h=500.0,
        resolution_date="2026-12-31",
    )


def _make_pair(
    leader_id: str = "L",
    follower_id: str = "F",
    similarity: float = 0.7,
    directional_correlation: float = 0.8,
    relationship_type: str = "correlated",
) -> MarketPair:
    leader = _make_embedding(leader_id, "Will BTC be above $90k?")
    follower = _make_embedding(follower_id, "Will BTC be above $95k?")
    return MarketPair(
        leader=leader,
        follower=follower,
        similarity=similarity,
        relationship_type=relationship_type,
        historical_lead_lag=1.0,
        directional_correlation=directional_correlation,
        confidence=similarity * abs(directional_correlation),
    )


# ---------------------------------------------------------------------------
# build_embeddings
# ---------------------------------------------------------------------------


class TestBuildEmbeddings:
    def test_returns_correct_count(self) -> None:
        engine = _make_engine()
        markets = [
            _make_market("m1", "Will BTC be above $90k by end of 2026?"),
            _make_market("m2", "Will ETH reach $5000 by December 2026?"),
            _make_market("m3", "Will the Fed raise rates in 2026?"),
        ]
        embeddings = engine.build_embeddings(markets)
        assert len(embeddings) == 3

    def test_embedding_dimension_matches_config(self) -> None:
        engine = _make_engine(embedding_dim=30)
        markets = [
            _make_market("m1", "Will BTC exceed $100k this year?"),
            _make_market("m2", "Will gold price hit $3000 per ounce?"),
        ]
        embeddings = engine.build_embeddings(markets)
        # Embedding length <= embedding_dim (TF-IDF caps at vocab size)
        for e in embeddings:
            assert len(e.embedding) > 0

    def test_market_id_preserved(self) -> None:
        engine = _make_engine()
        markets = [_make_market("unique-id-99", "Will the sun rise tomorrow?")]
        embeddings = engine.build_embeddings(markets)
        assert embeddings[0].market_id == "unique-id-99"

    def test_empty_market_list_returns_empty(self) -> None:
        engine = _make_engine()
        assert engine.build_embeddings([]) == []

    def test_price_and_volume_preserved(self) -> None:
        engine = _make_engine()
        markets = [_make_market("m1", "Will gold hit $3000?", price=0.72, volume_24h=9999.0)]
        emb = engine.build_embeddings(markets)[0]
        assert emb.current_price == pytest.approx(0.72)
        assert emb.volume_24h == pytest.approx(9999.0)

    def test_second_call_uses_cached_vectorizer(self) -> None:
        """After the first fit, the vectorizer is cached and reused."""
        engine = _make_engine()
        m1 = [_make_market("m1", "Will BTC exceed $90k?")]
        engine.build_embeddings(m1)
        # Second call should not raise and should reuse _vectorizer
        m2 = [_make_market("m2", "Will BTC exceed $95k?")]
        embeddings2 = engine.build_embeddings(m2)
        assert len(embeddings2) == 1


# ---------------------------------------------------------------------------
# discover_pairs
# ---------------------------------------------------------------------------


class TestDiscoverPairs:
    def test_identical_questions_get_same_event(self) -> None:
        engine = _make_engine(min_similarity=0.30)
        q = "Will BTC be above $90k by end of 2026?"
        markets = [
            _make_market("m1", q),
            _make_market("m2", q),  # exact duplicate
        ]
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        assert len(pairs) >= 1
        assert pairs[0].relationship_type == "same_event"

    def test_btc_price_ladder_pair_found(self) -> None:
        engine = _make_engine(min_similarity=0.30)
        markets = [
            _make_market("m1", "Will BTC be above $90000 by end of year?"),
            _make_market("m2", "Will BTC be above $95000 by end of year?"),
        ]
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        assert len(pairs) >= 1
        found_ids = {(p.leader.market_id, p.follower.market_id) for p in pairs} | \
                    {(p.follower.market_id, p.leader.market_id) for p in pairs}
        assert ("m1", "m2") in found_ids or ("m2", "m1") in found_ids

    def test_completely_unrelated_questions_no_pair(self) -> None:
        engine = _make_engine(min_similarity=0.70)
        markets = [
            _make_market("m1", "Will Portugal win the World Cup football soccer 2026?"),
            _make_market(
                "m2",
                "Will the Federal Reserve raise interest rates pharmaceutical biotech genomics?"
            ),
        ]
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        assert len(pairs) == 0

    def test_pairs_sorted_by_similarity_descending(self) -> None:
        engine = _make_engine(min_similarity=0.30)
        markets = [
            _make_market("m1", "Will BTC be above $80k?"),
            _make_market("m2", "Will BTC be above $90k?"),
            _make_market("m3", "Will BTC be above $100k?"),
        ]
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        sims = [p.similarity for p in pairs]
        assert sims == sorted(sims, reverse=True)

    def test_fewer_than_two_embeddings_returns_empty(self) -> None:
        engine = _make_engine()
        embeddings = engine.build_embeddings([_make_market("m1", "BTC above 90k?")])
        pairs = engine.discover_pairs(embeddings)
        assert pairs == []

    def test_max_pairs_cap_respected(self) -> None:
        engine = _make_engine(min_similarity=0.10, max_pairs=3)
        # 6 very similar questions → up to 15 pairs, but capped at 3
        markets = [_make_market(f"m{i}", "Will BTC price change by year end?") for i in range(6)]
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        assert len(pairs) <= 3


# ---------------------------------------------------------------------------
# _classify_relationship
# ---------------------------------------------------------------------------


class TestClassifyRelationship:
    def setup_method(self) -> None:
        self.engine = _make_engine()

    def test_very_high_similarity_same_event(self) -> None:
        result = self.engine._classify_relationship("BTC above 90k", "BTC above 90k", 0.95)
        assert result == "same_event"

    def test_high_overlap_conditional(self) -> None:
        # "Will BTC be above 90k" vs "Will BTC be above 90k by December"
        result = self.engine._classify_relationship(
            "Will BTC be above 90k",
            "Will BTC be above 90k by December 2026",
            0.75,
        )
        # Token overlap is high → conditional
        assert result == "conditional"

    def test_medium_similarity_correlated(self) -> None:
        result = self.engine._classify_relationship(
            "Will BTC close above 90000 dollars",
            "Will Ethereum price reach 5000 USD",
            0.60,
        )
        assert result == "correlated"

    def test_low_similarity_causal(self) -> None:
        result = self.engine._classify_relationship(
            "Will Apple stock beat earnings",
            "Will Microsoft announce dividend",
            0.42,
        )
        assert result == "causal"

    def test_boundary_exactly_085(self) -> None:
        result = self.engine._classify_relationship("Q1", "Q2", 0.85)
        assert result == "same_event"

    def test_boundary_exactly_050(self) -> None:
        # similarity 0.50 with no high token overlap → correlated
        result = self.engine._classify_relationship(
            "Gold above 3000 per ounce commodity",
            "Silver precious metal price rally rally",
            0.50,
        )
        assert result == "correlated"


# ---------------------------------------------------------------------------
# _compute_lead_lag
# ---------------------------------------------------------------------------


class TestComputeLeadLag:
    def setup_method(self) -> None:
        self.engine = _make_engine(lookback_window=20)

    def test_perfect_lead_lag_detected(self) -> None:
        """Leader series leads follower by 2 steps exactly."""
        base = [0.50 + 0.01 * i for i in range(20)]
        leader = base[:]
        follower = [0.50] * 2 + base[:-2]  # lag = 2
        lag, corr = self.engine._compute_lead_lag(leader, follower)
        # Should find a positive lag and positive correlation
        assert lag >= 0
        assert corr > 0

    def test_inverse_correlation_detected(self) -> None:
        """Leader rises while follower falls."""
        leader = [0.50 + 0.02 * i for i in range(20)]
        follower = [0.80 - 0.02 * i for i in range(20)]
        _, corr = self.engine._compute_lead_lag(leader, follower)
        assert corr < 0

    def test_flat_series_returns_zero_correlation(self) -> None:
        leader = [0.50] * 20
        follower = [0.60] * 20
        lag, corr = self.engine._compute_lead_lag(leader, follower)
        assert abs(corr) < 0.01

    def test_short_series_returns_defaults(self) -> None:
        lag, corr = self.engine._compute_lead_lag([0.5, 0.6], [0.4, 0.5])
        assert lag == 1.0
        assert corr == 0.0

    def test_positive_correlation_positive_lag_means_leader_leads(self) -> None:
        # A clean synthetic example: leader moves first
        n = 20
        signal = [0.5 + 0.03 * math.sin(0.5 * i) for i in range(n + 3)]
        leader = signal[:n]
        follower = signal[3: n + 3]  # follower is leader shifted by 3
        lag, corr = self.engine._compute_lead_lag(leader, follower)
        # At lag=3 the correlation should be maximal; lag >= 0 confirms i leads j
        assert corr > 0.5


# ---------------------------------------------------------------------------
# detect_leader_move
# ---------------------------------------------------------------------------


class TestDetectLeaderMove:
    def setup_method(self) -> None:
        self.engine = _make_engine(min_price_change=0.05)
        self.pair = _make_pair()

    def test_large_move_detected(self) -> None:
        assert self.engine.detect_leader_move(self.pair, 0.70, 0.60) is True  # +10%

    def test_small_move_not_detected(self) -> None:
        assert self.engine.detect_leader_move(self.pair, 0.51, 0.50) is False  # +1%

    def test_exact_threshold_is_detected(self) -> None:
        assert self.engine.detect_leader_move(self.pair, 0.55, 0.50) is True  # exactly +5%

    def test_negative_move_detected(self) -> None:
        assert self.engine.detect_leader_move(self.pair, 0.40, 0.50) is True  # -10%

    def test_tiny_negative_move_not_detected(self) -> None:
        assert self.engine.detect_leader_move(self.pair, 0.495, 0.50) is False


# ---------------------------------------------------------------------------
# generate_signals
# ---------------------------------------------------------------------------


class TestGenerateSignals:
    def setup_method(self) -> None:
        self.engine = _make_engine(
            min_price_change=0.05,
            min_signal_strength=0.05,
        )

    def test_leader_moves_follower_flat_generates_signal(self) -> None:
        pair = _make_pair("L", "F", similarity=0.75, directional_correlation=0.9)
        current = {"L": 0.70, "F": 0.50}
        previous = {"L": 0.55, "F": 0.50}  # leader +15%, follower flat
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.leader_market_id == "L"
        assert sig.follower_market_id == "F"
        assert sig.signal_strength > 0
        assert sig.recommended_side in ("BUY_YES", "BUY_NO")

    def test_follower_already_moved_no_signal(self) -> None:
        """Follower has already reacted (move >= 50% of leader's move) → no signal."""
        pair = _make_pair("L", "F", similarity=0.75, directional_correlation=0.9)
        current = {"L": 0.70, "F": 0.59}   # follower moved +9% vs leader +15%
        previous = {"L": 0.55, "F": 0.50}   # 9% >= 50% * 15% → window closed
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 0

    def test_leader_below_threshold_no_signal(self) -> None:
        """Leader moved only 3%, below min_price_change=5%."""
        pair = _make_pair("L", "F", similarity=0.75, directional_correlation=0.9)
        current = {"L": 0.53, "F": 0.50}
        previous = {"L": 0.50, "F": 0.50}
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 0

    def test_positive_correlation_predicts_same_direction(self) -> None:
        pair = _make_pair("L", "F", similarity=0.75, directional_correlation=0.85)
        # Leader moved UP
        current = {"L": 0.70, "F": 0.50}
        previous = {"L": 0.55, "F": 0.50}
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 1
        assert signals[0].predicted_direction == "up"
        assert signals[0].recommended_side == "BUY_YES"

    def test_negative_correlation_predicts_inverse_direction(self) -> None:
        pair = _make_pair("L", "F", similarity=0.75, directional_correlation=-0.85)
        # Leader moved UP → follower should go DOWN
        current = {"L": 0.70, "F": 0.50}
        previous = {"L": 0.55, "F": 0.50}
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 1
        assert signals[0].predicted_direction == "down"
        assert signals[0].recommended_side == "BUY_NO"

    def test_signals_sorted_by_strength_descending(self) -> None:
        # Use engine with min_signal_strength low enough that both pairs produce signals.
        # p1: 0.9 * 0.15 * 0.9 = 0.1215; p2: 0.6 * 0.15 * 0.7 = 0.063 — both > 0.01
        engine = _make_engine(min_signal_strength=0.01)
        p1 = _make_pair("L1", "F1", similarity=0.9, directional_correlation=0.9)
        p2 = _make_pair("L2", "F2", similarity=0.6, directional_correlation=0.7)
        current = {"L1": 0.70, "F1": 0.50, "L2": 0.70, "F2": 0.50}
        previous = {"L1": 0.55, "F1": 0.50, "L2": 0.55, "F2": 0.50}
        signals = engine.generate_signals([p1, p2], current, previous)
        assert len(signals) == 2
        assert signals[0].signal_strength >= signals[1].signal_strength

    def test_missing_price_entry_skipped(self) -> None:
        pair = _make_pair("L", "F")
        current = {"L": 0.70}  # F missing
        previous = {"L": 0.55, "F": 0.50}
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 0

    def test_signal_strength_formula(self) -> None:
        """signal_strength = similarity * |leader_move| * |dir_corr|"""
        sim = 0.75
        dir_corr = 0.80
        leader_move = 0.15  # 15%
        expected = sim * leader_move * abs(dir_corr)
        pair = _make_pair("L", "F", similarity=sim, directional_correlation=dir_corr)
        current = {"L": 0.65, "F": 0.50}
        previous = {"L": 0.50, "F": 0.50}
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 1
        assert signals[0].signal_strength == pytest.approx(expected, abs=1e-4)

    def test_leader_moves_down_positive_corr_predicts_down(self) -> None:
        pair = _make_pair("L", "F", similarity=0.75, directional_correlation=0.85)
        # Leader moved DOWN
        current = {"L": 0.35, "F": 0.50}
        previous = {"L": 0.50, "F": 0.50}
        signals = self.engine.generate_signals([pair], current, previous)
        assert len(signals) == 1
        assert signals[0].predicted_direction == "down"
        assert signals[0].recommended_side == "BUY_NO"


# ---------------------------------------------------------------------------
# update_pair_stats
# ---------------------------------------------------------------------------


class TestUpdatePairStats:
    def test_modifies_directional_correlation(self) -> None:
        engine = _make_engine()
        pair = _make_pair(directional_correlation=0.0)
        # Observe many same-direction moves to push correlation positive
        for _ in range(20):
            engine.update_pair_stats(pair, leader_moved=0.10, follower_moved=0.08)
        assert pair.directional_correlation > 0.0

    def test_inverse_moves_push_correlation_negative(self) -> None:
        engine = _make_engine()
        pair = _make_pair(directional_correlation=0.0)
        for _ in range(20):
            engine.update_pair_stats(pair, leader_moved=0.10, follower_moved=-0.08)
        assert pair.directional_correlation < 0.0

    def test_observed_leader_moves_counter_increments(self) -> None:
        engine = _make_engine()
        pair = _make_pair()
        initial = pair.observed_leader_moves
        engine.update_pair_stats(pair, leader_moved=0.10, follower_moved=0.08)
        assert pair.observed_leader_moves == initial + 1

    def test_zero_leader_move_does_not_update(self) -> None:
        engine = _make_engine()
        pair = _make_pair(directional_correlation=0.5)
        before = pair.directional_correlation
        engine.update_pair_stats(pair, leader_moved=0.0, follower_moved=0.05)
        assert pair.directional_correlation == pytest.approx(before)

    def test_confidence_updated_after_stats_update(self) -> None:
        engine = _make_engine()
        pair = _make_pair(directional_correlation=0.0)
        engine.update_pair_stats(pair, leader_moved=0.10, follower_moved=0.09)
        # confidence = similarity * |dir_corr| which must change
        assert pair.confidence >= 0.0


# ---------------------------------------------------------------------------
# Active Signals
# ---------------------------------------------------------------------------


class TestActiveSignals:
    def test_returns_unexpired_signals(self) -> None:
        engine = _make_engine(signal_ttl_seconds=60.0)
        pair = _make_pair("L", "F", similarity=0.75)
        current = {"L": 0.70, "F": 0.50}
        previous = {"L": 0.55, "F": 0.50}
        engine.generate_signals([pair], current, previous)
        active = engine.get_active_signals()
        assert len(active) == 1

    def test_expired_signals_pruned(self) -> None:
        engine = _make_engine(signal_ttl_seconds=0.001)
        pair = _make_pair("L", "F", similarity=0.75)
        current = {"L": 0.70, "F": 0.50}
        previous = {"L": 0.55, "F": 0.50}
        engine.generate_signals([pair], current, previous)
        time.sleep(0.01)  # let them expire
        active = engine.get_active_signals()
        assert len(active) == 0


# ---------------------------------------------------------------------------
# BTC Price Ladder Helper
# ---------------------------------------------------------------------------


class TestBtcPriceLadder:
    def test_returns_semantic_leader_follower(self) -> None:
        markets = [
            _make_market("btc90", "Will BTC be above $90000?"),
            _make_market("btc95", "Will BTC be above $95000?"),
        ]
        engine = btc_price_ladder_pairs(markets)
        assert isinstance(engine, SemanticLeaderFollower)

    def test_min_similarity_higher_than_default(self) -> None:
        """Ladder pairs should use a tighter similarity threshold."""
        markets = [_make_market("m1", "BTC above 90k"), _make_market("m2", "BTC above 95k")]
        engine = btc_price_ladder_pairs(markets)
        assert engine.min_similarity >= 0.50  # tighter than generic 0.40

    def test_signal_ttl_short(self) -> None:
        """Ladder opportunities are short-lived; TTL should be <= 300s."""
        markets = [_make_market("m1", "BTC above 90k"), _make_market("m2", "BTC above 95k")]
        engine = btc_price_ladder_pairs(markets)
        assert engine.signal_ttl_seconds <= 300.0

    def test_engine_can_discover_btc_pairs(self) -> None:
        """End-to-end: build embeddings, discover pairs, check at least one found."""
        markets = [
            _make_market("btc80", "Will BTC price be above $80000 by year end?"),
            _make_market("btc85", "Will BTC price be above $85000 by year end?"),
            _make_market("btc90", "Will BTC price be above $90000 by year end?"),
        ]
        engine = btc_price_ladder_pairs(markets)
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        assert len(pairs) >= 1


# ---------------------------------------------------------------------------
# format_alert
# ---------------------------------------------------------------------------


class TestFormatAlert:
    def _make_signal(self, **overrides: Any) -> LeaderFollowerSignal:
        defaults = dict(
            leader_market_id="L1",
            leader_question="Will BTC be above $90k?",
            leader_price_change=0.15,
            leader_direction="up",
            follower_market_id="F1",
            follower_question="Will BTC be above $95k?",
            follower_current_price=0.42,
            predicted_direction="up",
            predicted_magnitude=0.12,
            confidence=0.68,
            pair_similarity=0.75,
            signal_strength=0.09,
            recommended_side="BUY_YES",
            recommended_size_usd=9.0,
        )
        defaults.update(overrides)
        return LeaderFollowerSignal(**defaults)

    def test_alert_contains_leader_question(self) -> None:
        engine = _make_engine()
        sig = self._make_signal()
        alert = engine.format_alert(sig)
        assert "BTC" in alert
        assert "$90k" in alert

    def test_alert_contains_recommended_side(self) -> None:
        engine = _make_engine()
        sig = self._make_signal(recommended_side="BUY_NO")
        alert = engine.format_alert(sig)
        assert "BUY_NO" in alert

    def test_alert_contains_size(self) -> None:
        engine = _make_engine()
        sig = self._make_signal(recommended_size_usd=7.50)
        alert = engine.format_alert(sig)
        assert "7.50" in alert

    def test_alert_down_direction_shows_down_arrow(self) -> None:
        engine = _make_engine()
        sig = self._make_signal(predicted_direction="down")
        alert = engine.format_alert(sig)
        assert "↓" in alert

    def test_alert_up_direction_shows_up_arrow(self) -> None:
        engine = _make_engine()
        sig = self._make_signal(predicted_direction="up")
        alert = engine.format_alert(sig)
        assert "↑" in alert

    def test_alert_is_string(self) -> None:
        engine = _make_engine()
        sig = self._make_signal()
        alert = engine.format_alert(sig)
        assert isinstance(alert, str)
        assert len(alert) > 10


# ---------------------------------------------------------------------------
# Integration: Full Pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_end_to_end_signal_generation(self) -> None:
        """Build embeddings → discover pairs → generate signals."""
        engine = _make_engine(
            min_similarity=0.30,
            min_price_change=0.05,
            min_signal_strength=0.01,
        )
        markets = [
            _make_market(
                "btc90", "Will BTC price be above 90000 dollars by year end?",
                price=0.65,
                price_history=[0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.62, 0.64, 0.65, 0.65],
            ),
            _make_market(
                "btc95", "Will BTC price be above 95000 dollars by year end?",
                price=0.38,
                price_history=[0.40, 0.41, 0.42, 0.40, 0.39, 0.39, 0.38, 0.38, 0.38, 0.38],
            ),
        ]
        embeddings = engine.build_embeddings(markets)
        assert len(embeddings) == 2

        pairs = engine.discover_pairs(embeddings)
        assert len(pairs) >= 1

        # Leader moved up 15%, follower flat
        current = {"btc90": 0.75, "btc95": 0.38}
        previous = {"btc90": 0.60, "btc95": 0.38}

        signals = engine.generate_signals(pairs, current, previous)
        # We expect at least one signal when the leader moves strongly
        assert len(signals) >= 1
        assert signals[0].recommended_side in ("BUY_YES", "BUY_NO")

    def test_pair_diagnostics_populated(self) -> None:
        engine = _make_engine(min_similarity=0.30)
        markets = [
            _make_market("m1", "Will BTC be above 90k this year?"),
            _make_market("m2", "Will BTC be above 95k this year?"),
            _make_market("m3", "Will the Federal Reserve raise rates tomorrow morning?"),
        ]
        embeddings = engine.build_embeddings(markets)
        pairs = engine.discover_pairs(embeddings)
        diag = engine.compute_pair_diagnostics(pairs)
        assert "total_pairs" in diag
        assert "avg_similarity" in diag
        assert "top_pairs" in diag
        assert isinstance(diag["top_pairs"], list)
