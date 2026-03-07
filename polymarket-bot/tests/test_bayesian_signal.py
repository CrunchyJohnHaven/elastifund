"""Tests for Bayesian signal processing module."""
import os
import math
import time
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("POLYMARKET_PRIVATE_KEY", "test")
os.environ.setdefault("POLYMARKET_FUNDER_ADDRESS", "test")

from src.bayesian_signal import (
    BayesianSignalProcessor,
    BeliefState,
    Evidence,
    evidence_from_claude,
    evidence_from_price_move,
    evidence_from_news_sentiment,
    evidence_from_volume_spike,
)


class TestEvidence:
    """Tests for Evidence dataclass."""

    def test_log_likelihood_ratio_neutral(self):
        """Equal likelihoods → LLR = 0."""
        ev = Evidence(source="test", likelihood_yes=0.5, likelihood_no=0.5)
        assert abs(ev.log_likelihood_ratio) < 1e-10

    def test_log_likelihood_ratio_positive(self):
        """P(D|YES) > P(D|NO) → positive LLR (evidence for YES)."""
        ev = Evidence(source="test", likelihood_yes=0.8, likelihood_no=0.2)
        assert ev.log_likelihood_ratio > 0

    def test_log_likelihood_ratio_negative(self):
        """P(D|YES) < P(D|NO) → negative LLR (evidence for NO)."""
        ev = Evidence(source="test", likelihood_yes=0.2, likelihood_no=0.8)
        assert ev.log_likelihood_ratio < 0

    def test_extreme_likelihood_capped(self):
        """Zero likelihood should be capped, not inf."""
        ev = Evidence(source="test", likelihood_yes=1.0, likelihood_no=0.0)
        assert ev.log_likelihood_ratio == 30.0
        ev2 = Evidence(source="test", likelihood_yes=0.0, likelihood_no=1.0)
        assert ev2.log_likelihood_ratio == -30.0


class TestBeliefState:
    """Tests for BeliefState dataclass."""

    def test_uninformative_prior(self):
        """log_odds=0 → P(YES)=0.5."""
        belief = BeliefState(market_id="test", log_odds=0.0)
        assert abs(belief.probability_yes - 0.5) < 1e-10
        assert abs(belief.probability_no - 0.5) < 1e-10

    def test_positive_log_odds(self):
        """Positive log-odds → P(YES) > 0.5."""
        belief = BeliefState(market_id="test", log_odds=2.0)
        assert belief.probability_yes > 0.5
        assert belief.probability_no < 0.5

    def test_negative_log_odds(self):
        """Negative log-odds → P(YES) < 0.5."""
        belief = BeliefState(market_id="test", log_odds=-2.0)
        assert belief.probability_yes < 0.5

    def test_extreme_log_odds_bounded(self):
        """Extreme log-odds should produce valid probabilities."""
        belief = BeliefState(market_id="test", log_odds=100.0)
        assert 0 < belief.probability_yes <= 1.0
        belief2 = BeliefState(market_id="test", log_odds=-100.0)
        assert 0 <= belief2.probability_yes < 1.0

    def test_probabilities_sum_to_one(self):
        """P(YES) + P(NO) = 1."""
        for lo in [-5, -1, 0, 1, 5]:
            belief = BeliefState(market_id="test", log_odds=lo)
            assert abs(belief.probability_yes + belief.probability_no - 1.0) < 1e-10


class TestBayesianSignalProcessor:
    """Tests for the main processor."""

    def test_create_belief_default_prior(self):
        """Default prior should be 50/50."""
        proc = BayesianSignalProcessor()
        belief = proc.get_or_create_belief("mkt_001")
        assert abs(belief.probability_yes - 0.5) < 0.01

    def test_create_belief_custom_prior(self):
        """Custom prior should be respected."""
        proc = BayesianSignalProcessor()
        belief = proc.get_or_create_belief("mkt_001", prior_yes=0.7)
        assert abs(belief.probability_yes - 0.7) < 0.01

    def test_update_moves_belief(self):
        """Evidence for YES should increase P(YES)."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001")

        ev = Evidence(
            source="test",
            likelihood_yes=0.8,
            likelihood_no=0.2,
            timestamp=time.time(),
        )
        belief = proc.update("mkt_001", ev)
        assert belief.probability_yes > 0.5
        assert belief.evidence_count == 1

    def test_multiple_updates_accumulate(self):
        """Multiple YES evidence should keep increasing P(YES)."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001")

        probs = [0.5]
        for _ in range(5):
            ev = Evidence(source="test", likelihood_yes=0.7, likelihood_no=0.3,
                         timestamp=time.time())
            belief = proc.update("mkt_001", ev)
            probs.append(belief.probability_yes)

        # Each update should increase probability
        for i in range(1, len(probs)):
            assert probs[i] >= probs[i-1]

    def test_contradictory_evidence_moves_back(self):
        """NO evidence after YES evidence should move belief back."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001")

        # Push toward YES
        ev_yes = Evidence(source="test", likelihood_yes=0.9, likelihood_no=0.1,
                         timestamp=time.time())
        proc.update("mkt_001", ev_yes)
        p_after_yes = proc._beliefs["mkt_001"].probability_yes

        # Push back toward NO
        ev_no = Evidence(source="test", likelihood_yes=0.1, likelihood_no=0.9,
                        timestamp=time.time())
        proc.update("mkt_001", ev_no)
        p_after_no = proc._beliefs["mkt_001"].probability_yes

        assert p_after_no < p_after_yes

    def test_log_odds_clamped(self):
        """Log-odds should be clamped to prevent extreme beliefs."""
        proc = BayesianSignalProcessor(max_log_odds=3.0)
        proc.get_or_create_belief("mkt_001")

        # Massive evidence for YES
        for _ in range(100):
            ev = Evidence(source="test", likelihood_yes=0.99, likelihood_no=0.01,
                         timestamp=time.time())
            proc.update("mkt_001", ev)

        assert proc._beliefs["mkt_001"].log_odds <= 3.0
        assert proc._beliefs["mkt_001"].probability_yes < 1.0

    def test_batch_update(self):
        """batch_update should process all evidence."""
        proc = BayesianSignalProcessor()
        evidences = [
            Evidence(source="a", likelihood_yes=0.8, likelihood_no=0.2, timestamp=time.time()),
            Evidence(source="b", likelihood_yes=0.7, likelihood_no=0.3, timestamp=time.time()),
            Evidence(source="c", likelihood_yes=0.6, likelihood_no=0.4, timestamp=time.time()),
        ]
        belief = proc.batch_update("mkt_001", evidences)
        assert belief.evidence_count == 3
        assert belief.probability_yes > 0.5

    def test_expected_value(self):
        """EV = p_hat - p_market."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001", prior_yes=0.7)
        ev = proc.expected_value("mkt_001", market_price=0.5)
        assert abs(ev - 0.2) < 0.01  # 0.7 - 0.5 = 0.2

    def test_expected_value_no_belief(self):
        """EV with no belief state → 0."""
        proc = BayesianSignalProcessor()
        assert proc.expected_value("nonexistent", 0.5) == 0.0

    def test_get_signal_buy_yes(self):
        """Strong YES belief + low market price → buy_yes signal."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001", prior_yes=0.8)
        signal = proc.get_signal("mkt_001", market_price=0.4, min_edge=0.05)
        assert signal["direction"] == "buy_yes"
        assert signal["edge"] > 0

    def test_get_signal_buy_no(self):
        """Strong NO belief + high market price → buy_no signal."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001", prior_yes=0.2)
        signal = proc.get_signal("mkt_001", market_price=0.6, min_edge=0.05)
        assert signal["direction"] == "buy_no"
        assert signal["edge"] > 0

    def test_get_signal_hold(self):
        """Small edge → hold."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001", prior_yes=0.52)
        signal = proc.get_signal("mkt_001", market_price=0.50, min_edge=0.05)
        assert signal["direction"] == "hold"

    def test_reset_belief(self):
        """Reset should clear belief state."""
        proc = BayesianSignalProcessor()
        proc.get_or_create_belief("mkt_001", prior_yes=0.8)
        proc.reset_belief("mkt_001")
        assert "mkt_001" not in proc._beliefs


class TestEvidenceFactory:
    """Tests for evidence factory functions."""

    def test_evidence_from_claude(self):
        """Claude estimate should create valid evidence."""
        ev = evidence_from_claude(0.75, confidence=0.9)
        assert ev.source == "claude"
        assert ev.likelihood_yes == 0.75
        assert ev.likelihood_no == 0.25
        assert ev.weight > 0.5  # High confidence = high weight

    def test_evidence_from_claude_low_confidence(self):
        """Low confidence → lower weight."""
        ev_high = evidence_from_claude(0.75, confidence=0.9)
        ev_low = evidence_from_claude(0.75, confidence=0.1)
        assert ev_high.weight > ev_low.weight

    def test_evidence_from_price_move_up(self):
        """Positive price move → evidence for YES."""
        ev = evidence_from_price_move(0.05)  # 5% up
        assert ev.likelihood_yes > ev.likelihood_no

    def test_evidence_from_price_move_down(self):
        """Negative price move → evidence for NO."""
        ev = evidence_from_price_move(-0.05)  # 5% down
        assert ev.likelihood_no > ev.likelihood_yes

    def test_evidence_from_news_positive(self):
        """Positive sentiment → evidence for YES."""
        ev = evidence_from_news_sentiment(0.8, relevance=0.7)
        assert ev.likelihood_yes > ev.likelihood_no

    def test_evidence_from_news_negative(self):
        """Negative sentiment → evidence for NO."""
        ev = evidence_from_news_sentiment(-0.8, relevance=0.7)
        assert ev.likelihood_no > ev.likelihood_yes

    def test_evidence_from_volume_spike_up(self):
        """Volume spike with positive price → YES evidence."""
        ev = evidence_from_volume_spike(3.0, price_direction=1.0)
        assert ev.likelihood_yes > ev.likelihood_no
        assert ev.weight > 0

    def test_evidence_from_volume_normal(self):
        """Normal volume → no signal."""
        ev = evidence_from_volume_spike(1.0, price_direction=1.0)
        assert ev.weight == 0.0


class TestResolutionKellyDampener:
    """Tests for time-aware Kelly dampener in sizing."""

    def test_short_horizon_dampened(self):
        """Short-horizon market should have low Kelly cap."""
        from src.risk.sizing import resolution_kelly_cap
        cap = resolution_kelly_cap(0.1)  # 6 minutes
        assert cap <= 0.05

    def test_medium_horizon(self):
        """Medium-horizon market should have moderate cap."""
        from src.risk.sizing import resolution_kelly_cap
        cap = resolution_kelly_cap(6.0)  # 6 hours
        assert 0.10 <= cap <= 0.25

    def test_long_horizon_no_dampening(self):
        """Long-horizon market should have no dampening."""
        from src.risk.sizing import resolution_kelly_cap
        cap = resolution_kelly_cap(500.0)  # ~3 weeks
        assert cap == 1.0

    def test_none_no_dampening(self):
        """None (unknown) → no dampening."""
        from src.risk.sizing import resolution_kelly_cap
        cap = resolution_kelly_cap(None)
        assert cap == 1.0

    def test_sizing_with_dampener(self):
        """SizingCaps with hours_to_resolution should reduce position size."""
        from src.risk.sizing import compute_sizing, SizingCaps

        caps_long = SizingCaps(hours_to_resolution=None)
        caps_short = SizingCaps(hours_to_resolution=0.5)  # 30 min

        r_long = compute_sizing(
            market_id="t1", p_estimated=0.80, p_market=0.50,
            side="buy_yes", bankroll=100.0, caps=caps_long,
        )
        r_short = compute_sizing(
            market_id="t2", p_estimated=0.80, p_market=0.50,
            side="buy_yes", bankroll=100.0, caps=caps_short,
        )

        # Short-horizon should produce equal or smaller position
        assert r_short.final_size_usd <= r_long.final_size_usd
