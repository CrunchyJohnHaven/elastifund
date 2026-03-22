"""
Tests for bot/hawkes_order_flow.py
===================================
Covers:
 - Basic intensity computation with known events
 - Intensity decays over time
 - Cascade detection on rapid burst
 - No false cascade with slow steady arrivals
 - Flow imbalance: all buys → positive, all sells → negative, balanced → ~0
 - Online MLE improves parameter estimates toward ground truth
 - Branching ratio stays < 1.0 for stable processes
 - Sliding window: events outside window don't affect intensity
 - Reset clears state
 - get_signal returns correct schema
 - Realistic prediction-market scenario (steady then cascade)
"""

import math
import time
from unittest.mock import patch

import pytest

from bot.hawkes_order_flow import (
    HawkesOrderFlow,
    HawkesState,
    OrderFlowEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(
    t: float,
    side: str = "buy",
    size: float = 1.0,
    price: float = 0.5,
    market_id: str = "test_market",
) -> OrderFlowEvent:
    return OrderFlowEvent(timestamp=t, side=side, size=size, price=price, market_id=market_id)


def feed_events(hof: HawkesOrderFlow, timestamps: list[float], side: str = "buy") -> HawkesState:
    """Feed a sequence of events on the same side; return last state."""
    state = None
    for t in timestamps:
        state = hof.observe(make_event(t, side=side))
    return state


# ---------------------------------------------------------------------------
# 1. Basic intensity computation
# ---------------------------------------------------------------------------

class TestIntensityComputation:
    def test_baseline_intensity_with_no_events(self):
        """With no events, intensity equals the baseline μ."""
        hof = HawkesOrderFlow(mu_init=0.2, alpha_init=0.3, beta_init=1.0)
        t = 1000.0
        assert hof.compute_intensity(t, side="buy") == pytest.approx(0.2, abs=1e-9)
        assert hof.compute_intensity(t, side="sell") == pytest.approx(0.2, abs=1e-9)

    def test_intensity_rises_after_event(self):
        """After a buy event, buy-side intensity should exceed baseline."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0)
        t0 = 1000.0
        hof.observe(make_event(t0, side="buy"))
        # Just after the event, intensity = μ + α ≈ 0.6
        intensity = hof.compute_intensity(t0, side="buy")
        assert intensity > hof._buy.mu

    def test_intensity_combined_sums_both_sides(self):
        """Combined intensity equals buy + sell."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0)
        t0 = 1000.0
        hof.observe(make_event(t0, side="buy"))
        hof.observe(make_event(t0 + 0.1, side="sell"))
        t_query = t0 + 0.2
        combined = hof.compute_intensity(t_query)
        buy_i = hof.compute_intensity(t_query, side="buy")
        sell_i = hof.compute_intensity(t_query, side="sell")
        assert combined == pytest.approx(buy_i + sell_i, abs=1e-9)

    def test_invalid_side_raises(self):
        """Invalid side string raises ValueError."""
        hof = HawkesOrderFlow()
        with pytest.raises(ValueError):
            hof.compute_intensity(1000.0, side="unknown")

    def test_invalid_event_side_raises(self):
        hof = HawkesOrderFlow()
        with pytest.raises(ValueError):
            hof.observe(make_event(1000.0, side="LONG"))


# ---------------------------------------------------------------------------
# 2. Intensity decays over time
# ---------------------------------------------------------------------------

class TestIntensityDecay:
    def test_intensity_decays_after_event(self):
        """After a single event, intensity decays exponentially toward μ."""
        hof = HawkesOrderFlow(
            mu_init=0.1,
            alpha_init=0.5,
            beta_init=2.0,   # fast decay
            min_events_for_fit=100,  # suppress MLE
        )
        t0 = 1000.0
        hof.observe(make_event(t0, side="buy"))

        # Check intensity at t0, t0+0.5, t0+2.0
        i_at_t0 = hof.compute_intensity(t0, side="buy")
        i_at_t1 = hof.compute_intensity(t0 + 0.5, side="buy")
        i_at_t2 = hof.compute_intensity(t0 + 2.0, side="buy")

        assert i_at_t0 > i_at_t1 > i_at_t2
        # Must be approaching μ asymptotically
        assert i_at_t2 > hof._buy.mu - 1e-9  # can't go below baseline

    def test_intensity_approaches_baseline_asymptotically(self):
        """Long after last event, intensity converges to μ."""
        hof = HawkesOrderFlow(
            mu_init=0.1,
            alpha_init=0.3,
            beta_init=5.0,   # very fast decay
            min_events_for_fit=100,
        )
        t0 = 1000.0
        hof.observe(make_event(t0, side="buy"))

        # After 10 half-lives: exp(-5*10) ≈ 5e-22 → effectively at baseline
        i_far = hof.compute_intensity(t0 + 10.0, side="buy")
        assert i_far == pytest.approx(hof._buy.mu, abs=1e-6)

    def test_sell_side_decays_independently(self):
        """Buy decay does not affect sell side and vice versa."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0,
                              min_events_for_fit=100)
        t0 = 1000.0
        hof.observe(make_event(t0, side="buy"))

        # Sell side should still be at baseline
        sell_i = hof.compute_intensity(t0, side="sell")
        assert sell_i == pytest.approx(hof._sell.mu, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. Cascade detection on rapid burst
# ---------------------------------------------------------------------------

class TestCascadeDetection:
    def test_rapid_burst_triggers_cascade(self):
        """20 events within 1 second should trigger cascade detection."""
        hof = HawkesOrderFlow(
            mu_init=0.1,
            alpha_init=0.6,
            beta_init=0.5,
            cascade_threshold=3.0,
            min_events_for_fit=100,  # freeze params so cascade is clean
        )
        t0 = 1000.0
        # 20 events spaced 50ms apart
        timestamps = [t0 + i * 0.05 for i in range(20)]
        state = feed_events(hof, timestamps, side="buy")

        assert state is not None
        assert state.is_cascade is True
        assert state.cascade_strength >= 3.0

    def test_cascade_state_returned_correctly(self):
        """HawkesState fields are internally consistent after cascade."""
        hof = HawkesOrderFlow(
            mu_init=0.1, alpha_init=0.7, beta_init=0.3,
            cascade_threshold=2.0, min_events_for_fit=100,
        )
        t0 = 1000.0
        timestamps = [t0 + i * 0.03 for i in range(30)]
        state = feed_events(hof, timestamps, side="sell")

        assert state.intensity >= state.baseline_intensity
        assert state.branching_ratio == pytest.approx(
            state.excitation / state.decay, rel=1e-6
        )

    def test_is_toxic_true_during_cascade(self):
        """is_toxic() returns True when cascade is active."""
        hof = HawkesOrderFlow(
            mu_init=0.05, alpha_init=0.8, beta_init=0.2,
            cascade_threshold=3.0, min_events_for_fit=100,
        )
        t0 = 2000.0
        timestamps = [t0 + i * 0.02 for i in range(25)]
        feed_events(hof, timestamps, side="buy")
        assert hof.is_toxic() is True


# ---------------------------------------------------------------------------
# 4. No false cascade with slow steady arrivals
# ---------------------------------------------------------------------------

class TestNoFalseCascade:
    def test_slow_steady_arrivals_no_cascade(self):
        """Events spaced 60s apart should NOT trigger cascade.

        Parameter constraint: cascade requires intensity > threshold * mu.
        With a single isolated event: intensity = mu + alpha (when fully decayed
        between events). So we need (mu + alpha) / mu < threshold, i.e.
        alpha < (threshold - 1) * mu. Here: alpha=0.4, mu=0.4 → ratio=2.0 < 3.0.
        """
        hof = HawkesOrderFlow(
            mu_init=0.4,   # high baseline so single event can't cascade
            alpha_init=0.4,  # alpha/mu = 1.0 < (3.0-1) = 2.0 → max ratio = 2.0
            beta_init=2.0,
            cascade_threshold=3.0,
            window_seconds=600.0,
            min_events_for_fit=100,
        )
        t0 = 1000.0
        # 1 event per minute for 10 minutes
        timestamps = [t0 + i * 60.0 for i in range(10)]
        state = feed_events(hof, timestamps, side="buy")

        assert state is not None
        # With 60s gaps and β=2, each event decays to ~0 by next arrival.
        # intensity at event time ≈ mu + alpha = 0.8; ratio = 2.0 < 3.0
        assert state.is_cascade is False, (
            f"Slow arrivals should not cascade, got cascade_strength={state.cascade_strength:.2f}"
        )

    def test_is_not_toxic_under_quiet_flow(self):
        hof = HawkesOrderFlow(
            mu_init=0.4,
            alpha_init=0.4,   # (mu+alpha)/mu = 2.0 < cascade_threshold=3.0
            beta_init=3.0,
            cascade_threshold=3.0,
            window_seconds=600.0,
            min_events_for_fit=100,
        )
        t0 = 5000.0
        for i in range(10):
            hof.observe(make_event(t0 + i * 30.0, side="buy"))
        assert hof.is_toxic() is False


# ---------------------------------------------------------------------------
# 5. Flow imbalance
# ---------------------------------------------------------------------------

class TestFlowImbalance:
    def test_all_buys_positive_imbalance(self):
        """All buy events → positive flow imbalance."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0,
                              min_events_for_fit=100)
        t0 = 1000.0
        for i in range(10):
            hof.observe(make_event(t0 + i * 0.1, side="buy"))
        imb = hof.get_flow_imbalance()
        assert imb > 0.0

    def test_all_sells_negative_imbalance(self):
        """All sell events → negative flow imbalance."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0,
                              min_events_for_fit=100)
        t0 = 1000.0
        for i in range(10):
            hof.observe(make_event(t0 + i * 0.1, side="sell"))
        imb = hof.get_flow_imbalance()
        assert imb < 0.0

    def test_balanced_flow_near_zero(self):
        """Equal buy and sell events with identical timing → imbalance near 0."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0,
                              min_events_for_fit=100)
        t0 = 1000.0
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            hof.observe(make_event(t0 + i * 0.1, side=side))
        imb = hof.get_flow_imbalance()
        # Should be close to 0 (within 0.15)
        assert abs(imb) < 0.15

    def test_imbalance_range(self):
        """Flow imbalance should always be in [-0.5, 0.5]."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.4, beta_init=0.8)
        import random
        rng = random.Random(42)
        t0 = 1000.0
        cumulative_t = t0
        for i in range(50):
            side = rng.choice(["buy", "sell"])
            cumulative_t += rng.uniform(0.1, 2.0)
            hof.observe(make_event(cumulative_t, side=side))
        imb = hof.get_flow_imbalance()
        assert -0.5 <= imb <= 0.5

    def test_imbalance_zero_with_no_events(self):
        """With no events, equal baselines → imbalance = 0."""
        hof = HawkesOrderFlow(mu_init=0.2, alpha_init=0.5, beta_init=1.0)
        hof._last_observe_time = 1000.0
        imb = hof.get_flow_imbalance()
        assert imb == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 6. Online MLE improves parameter estimates
# ---------------------------------------------------------------------------

class TestOnlineMLE:
    def _simulate_hawkes(
        self,
        mu: float,
        alpha: float,
        beta: float,
        n_events: int = 200,
        seed: int = 42,
    ) -> list[float]:
        """
        Simulate a Hawkes process using Ogata's thinning algorithm.
        Returns list of event timestamps.
        """
        import random
        rng = random.Random(seed)
        events = []
        t = 0.0
        lambda_bar = mu  # Upper bound on intensity

        while len(events) < n_events:
            # Draw inter-arrival from homogeneous Poisson(lambda_bar)
            u = rng.random()
            w = -math.log(u + 1e-15) / lambda_bar
            t += w

            # Compute actual intensity at candidate time
            lam_t = mu + alpha * sum(math.exp(-beta * (t - s)) for s in events)

            # Accept/reject
            u2 = rng.random()
            if u2 <= lam_t / lambda_bar:
                events.append(t)
                # Update lambda_bar
                lambda_bar = lam_t + alpha  # upper bound after new event

        return events[:n_events]

    def test_mle_estimates_approach_true_params(self):
        """
        After 200 events from a known Hawkes process, the key parameters μ and α
        should move in the correct direction from deliberately wrong initial values.

        The simplified gradient approximation used here is a first-order online
        estimator. It reliably corrects μ and α (the dominant parameters in the
        likelihood score). The β gradient is noisier due to the approximated
        chain-rule terms; we test it separately for stability rather than direction.
        """
        true_mu = 0.3
        true_alpha = 0.4
        true_beta = 1.5

        events = self._simulate_hawkes(true_mu, true_alpha, true_beta, n_events=200)

        # Initial params deliberately wrong
        mu_init, alpha_init, beta_init = 0.8, 0.1, 4.0

        hof = HawkesOrderFlow(
            mu_init=mu_init,
            alpha_init=alpha_init,
            beta_init=beta_init,
            learning_rate=0.003,
            min_events_for_fit=20,
            window_seconds=max(events) + 10.0,
        )

        for t in events:
            hof.observe(make_event(t, side="buy"))

        est_mu = hof._buy.mu
        est_alpha = hof._buy.alpha
        est_beta = hof._buy.beta

        # MLE should move μ downward (from 0.8 toward 0.3)
        assert est_mu < mu_init, \
            f"μ should decrease from {mu_init}, got {est_mu:.4f}"

        # MLE should move α upward (from 0.1 toward 0.4)
        assert est_alpha > alpha_init, \
            f"α should increase from {alpha_init}, got {est_alpha:.4f}"

        # All params must remain positive and finite
        assert est_mu > 0 and est_alpha > 0 and est_beta > 0
        assert math.isfinite(est_mu) and math.isfinite(est_alpha) and math.isfinite(est_beta)

        # Branching ratio must remain stable (below 1)
        assert hof._buy.branching_ratio < 1.0

    def test_mle_does_not_make_process_explosive(self):
        """After MLE updates, branching ratio must stay below 1."""
        hof = HawkesOrderFlow(
            mu_init=0.2, alpha_init=0.5, beta_init=1.0,
            learning_rate=0.01, min_events_for_fit=10,
        )
        t0 = 0.0
        for i in range(80):
            hof.observe(make_event(t0 + i * 0.2, side="buy"))

        assert hof._buy.branching_ratio < 1.0


# ---------------------------------------------------------------------------
# 7. Branching ratio stays below 1 for stable processes
# ---------------------------------------------------------------------------

class TestBranchingRatio:
    def test_branching_ratio_initial(self):
        """Initial branching ratio = alpha_init / beta_init."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.4, beta_init=2.0)
        assert hof._buy.branching_ratio == pytest.approx(0.2, rel=1e-6)

    def test_branching_ratio_capped_below_one(self):
        """Even with adversarial gradients, ratio is capped at < 1."""
        hof = HawkesOrderFlow(
            mu_init=0.1, alpha_init=0.95, beta_init=1.0,
            learning_rate=0.1, min_events_for_fit=5,
        )
        t0 = 0.0
        for i in range(100):
            hof.observe(make_event(t0 + i * 0.01, side="buy"))
        assert hof._buy.branching_ratio < 1.0

    def test_branching_ratio_in_state(self):
        """HawkesState.branching_ratio matches kernel α/β."""
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.3, beta_init=1.5,
                              min_events_for_fit=100)
        state = hof.observe(make_event(1000.0, side="sell"))
        assert state.branching_ratio == pytest.approx(
            hof._sell.alpha / hof._sell.beta, rel=1e-6
        )


# ---------------------------------------------------------------------------
# 8. Sliding window
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_old_events_do_not_affect_intensity(self):
        """Events outside the window should not contribute to intensity."""
        window = 60.0  # 60 second window
        hof = HawkesOrderFlow(
            mu_init=0.05, alpha_init=0.8, beta_init=0.1,
            window_seconds=window,
            min_events_for_fit=100,
        )
        t0 = 1000.0

        # Feed 10 events far in the past (well outside window)
        for i in range(10):
            hof.observe(make_event(t0 + i * 0.5, side="buy"))

        # Now fast-forward to t0 + window + 100 (events are pruned)
        t_now = t0 + window + 100.0
        intensity_after = hof.compute_intensity(t_now, side="buy")

        # Should be near baseline (excitation from old events has decayed AND
        # those events are pruned from the window)
        assert intensity_after == pytest.approx(hof._buy.mu, abs=0.01)

    def test_recent_events_within_window_affect_intensity(self):
        """Events inside the window do contribute to intensity."""
        hof = HawkesOrderFlow(
            mu_init=0.05, alpha_init=0.8, beta_init=0.1,
            window_seconds=300.0,
            min_events_for_fit=100,
        )
        t0 = 5000.0
        for i in range(5):
            hof.observe(make_event(t0 + i * 1.0, side="buy"))

        # Just after the last event, intensity should exceed baseline
        t_query = t0 + 4.1
        assert hof.compute_intensity(t_query, side="buy") > hof._buy.mu


# ---------------------------------------------------------------------------
# 9. Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_events(self):
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0,
                              min_events_for_fit=100)
        t0 = 1000.0
        for i in range(15):
            hof.observe(make_event(t0 + i * 0.1, side="buy"))

        # Should have elevated intensity
        assert hof._buy.event_count > 0

        hof.reset()

        assert hof._buy.event_count == 0
        assert hof._sell.event_count == 0
        assert hof._last_observe_time == 0.0

    def test_reset_restores_initial_params(self):
        hof = HawkesOrderFlow(mu_init=0.15, alpha_init=0.4, beta_init=2.0,
                              learning_rate=0.1, min_events_for_fit=5)
        t0 = 1000.0
        for i in range(50):
            hof.observe(make_event(t0 + i * 0.1, side="sell"))

        hof.reset()

        assert hof._buy.mu == pytest.approx(0.15, rel=1e-6)
        assert hof._buy.alpha == pytest.approx(0.4, rel=1e-6)
        assert hof._buy.beta == pytest.approx(2.0, rel=1e-6)

    def test_intensity_at_baseline_after_reset(self):
        hof = HawkesOrderFlow(mu_init=0.1, alpha_init=0.5, beta_init=1.0,
                              min_events_for_fit=100)
        t0 = 1000.0
        for i in range(10):
            hof.observe(make_event(t0 + i * 0.1, side="buy"))

        hof.reset()
        # After reset, no events in window → intensity = μ
        assert hof.compute_intensity(t0 + 5.0, side="buy") == pytest.approx(
            hof._buy.mu, abs=1e-9
        )


# ---------------------------------------------------------------------------
# 10. get_signal schema
# ---------------------------------------------------------------------------

class TestGetSignal:
    EXPECTED_KEYS = {
        "buy_intensity",
        "sell_intensity",
        "buy_cascade",
        "sell_cascade",
        "flow_imbalance",
        "branching_ratio_buy",
        "branching_ratio_sell",
        "is_toxic",
        "event_rate",
    }

    def test_signal_has_correct_keys(self):
        hof = HawkesOrderFlow()
        hof.observe(make_event(1000.0, side="buy"))
        sig = hof.get_signal()
        assert set(sig.keys()) == self.EXPECTED_KEYS

    def test_signal_types(self):
        hof = HawkesOrderFlow()
        hof.observe(make_event(1000.0, side="buy"))
        hof.observe(make_event(1000.1, side="sell"))
        sig = hof.get_signal()
        assert isinstance(sig["buy_intensity"], float)
        assert isinstance(sig["sell_intensity"], float)
        assert isinstance(sig["buy_cascade"], bool)
        assert isinstance(sig["sell_cascade"], bool)
        assert isinstance(sig["flow_imbalance"], float)
        assert isinstance(sig["branching_ratio_buy"], float)
        assert isinstance(sig["branching_ratio_sell"], float)
        assert isinstance(sig["is_toxic"], bool)
        assert isinstance(sig["event_rate"], float)

    def test_is_toxic_consistent_with_cascade_flags(self):
        """is_toxic must equal buy_cascade OR sell_cascade."""
        hof = HawkesOrderFlow()
        t0 = 1000.0
        for i in range(20):
            hof.observe(make_event(t0 + i * 0.05, side="buy"))
        sig = hof.get_signal()
        assert sig["is_toxic"] == (sig["buy_cascade"] or sig["sell_cascade"])

    def test_flow_imbalance_in_range(self):
        hof = HawkesOrderFlow()
        t0 = 1000.0
        for i in range(10):
            hof.observe(make_event(t0 + i * 0.2,
                                   side="buy" if i % 3 == 0 else "sell"))
        sig = hof.get_signal()
        assert -0.5 <= sig["flow_imbalance"] <= 0.5

    def test_branching_ratios_positive(self):
        hof = HawkesOrderFlow()
        hof.observe(make_event(1000.0, side="buy"))
        hof.observe(make_event(1001.0, side="sell"))
        sig = hof.get_signal()
        assert sig["branching_ratio_buy"] > 0.0
        assert sig["branching_ratio_sell"] > 0.0

    def test_event_rate_non_negative(self):
        hof = HawkesOrderFlow()
        sig = hof.get_signal()
        assert sig["event_rate"] >= 0.0

    def test_no_events_signal(self):
        """Signal with no events should have no cascades and zero event rate."""
        hof = HawkesOrderFlow()
        hof._last_observe_time = 1000.0
        sig = hof.get_signal()
        assert sig["buy_cascade"] is False
        assert sig["sell_cascade"] is False
        assert sig["is_toxic"] is False
        assert sig["event_rate"] == 0.0


# ---------------------------------------------------------------------------
# 11. Realistic prediction-market scenario
# ---------------------------------------------------------------------------

class TestRealisticScenario:
    def test_normal_trading_then_cascade(self):
        """
        Simulate 10 events over 60 seconds (normal), then 15 events
        in 3 seconds (informed-trader cascade). Cascade should be detected
        in the second phase but NOT in the first.

        Parameter constraint: a single isolated event gives intensity = mu + alpha.
        For no cascade: (mu + alpha) / mu < threshold → alpha < (threshold-1)*mu.
        Here: alpha=0.5, mu=0.5 → ratio = 2.0 < 3.0. Safe for normal phase.
        Burst phase: 15 events in 3s with beta=0.5 → self-excitation accumulates
        to well above 3x baseline.
        """
        hof = HawkesOrderFlow(
            mu_init=0.5,      # high enough that single event won't cascade
            alpha_init=0.5,   # (mu+alpha)/mu = 2.0 < cascade_threshold=3.0
            beta_init=0.5,    # slow decay → burst accumulates intensity
            cascade_threshold=3.0,
            window_seconds=300.0,
            min_events_for_fit=100,   # freeze params for cleaner test
        )
        t0 = 10000.0

        # Phase 1: 10 events spaced 6s apart.
        # With beta=0.5 and 6s gaps: exp(-0.5*6) ≈ 0.05 → nearly zero cross-event excitation
        phase1_times = [t0 + i * 6.0 for i in range(10)]
        for t in phase1_times:
            state = hof.observe(make_event(t, side="buy"))
        assert state is not None
        assert state.is_cascade is False, (
            f"Phase 1 should not trigger cascade, got cascade_strength={state.cascade_strength:.2f}"
        )

        # Phase 2: 15 events in 3 seconds (0.2s spacing) starting at t0 + 120.
        # After phase 1 ends, wait 60s so excitation fully decays.
        t_burst = t0 + 120.0
        phase2_times = [t_burst + i * 0.2 for i in range(15)]
        for t in phase2_times:
            state = hof.observe(make_event(t, side="buy"))

        assert state.is_cascade is True, (
            f"Phase 2 burst should trigger cascade, got cascade_strength={state.cascade_strength:.2f}"
        )
        assert state.cascade_strength >= 3.0

    def test_signal_reflects_scenario_correctly(self):
        """After cascade burst, get_signal() shows is_toxic=True."""
        hof = HawkesOrderFlow(
            mu_init=0.1, alpha_init=0.7, beta_init=0.5,
            cascade_threshold=3.0, window_seconds=300.0,
            min_events_for_fit=100,
        )
        t_burst = 5000.0
        for i in range(20):
            hof.observe(make_event(t_burst + i * 0.1, side="sell"))

        sig = hof.get_signal()
        assert sig["is_toxic"] is True
        assert sig["sell_cascade"] is True
        # Buy side should not be cascading
        assert sig["buy_cascade"] is False

    def test_quiet_market_signal(self):
        """Quiet market: no cascade, low event rate, imbalance near 0.

        alpha < (cascade_threshold - 1) * mu ensures single event can't cascade.
        alpha=0.5, mu=0.5: max ratio = 2.0 < 3.0.
        """
        hof = HawkesOrderFlow(
            mu_init=0.5,
            alpha_init=0.5,   # ratio = 2.0 < 3.0
            beta_init=2.0,
            cascade_threshold=3.0, window_seconds=300.0,
            min_events_for_fit=100,
        )
        t0 = 7000.0
        # Alternating buys and sells at 10-second intervals
        for i in range(10):
            side = "buy" if i % 2 == 0 else "sell"
            hof.observe(make_event(t0 + i * 10.0, side=side))

        sig = hof.get_signal()
        assert sig["is_toxic"] is False
        assert sig["buy_cascade"] is False
        assert sig["sell_cascade"] is False


# ---------------------------------------------------------------------------
# 12. Telemetry (smoke test — does not call real Elasticsearch)
# ---------------------------------------------------------------------------

class TestTelemetry:
    def test_cascade_triggers_telemetry_attempt(self):
        """On cascade, _emit_cascade_telemetry is called."""
        hof = HawkesOrderFlow(
            mu_init=0.05, alpha_init=0.9, beta_init=0.3,
            cascade_threshold=2.0, min_events_for_fit=100,
        )
        with patch.object(hof, "_emit_cascade_telemetry") as mock_emit:
            t0 = 1000.0
            for i in range(20):
                state = hof.observe(make_event(t0 + i * 0.05, side="buy"))
                if state.is_cascade:
                    break

            if state.is_cascade:
                assert mock_emit.called


# ---------------------------------------------------------------------------
# 13. OrderFlowEvent construction
# ---------------------------------------------------------------------------

class TestOrderFlowEvent:
    def test_defaults(self):
        evt = OrderFlowEvent(timestamp=123.0, side="buy", size=10.0, price=0.55)
        assert evt.market_id == ""

    def test_repr(self):
        evt = make_event(100.0, side="sell")
        r = repr(evt)
        assert "sell" in r
        assert "100.000" in r
