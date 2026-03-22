#!/usr/bin/env python3
"""
Tests for bot/causal_lead_lag.py
==================================
Covers:
- Known causal structure discovery (X_t-2 → Y_t)
- Spurious correlation rejection (common hidden cause Z)
- Autocorrelation handling (AR(1) self-causation)
- _partial_correlation correctness against known values
- CausalGraph.get_leaders / get_followers
- Multivariate (3+ markets) handling
- min_observations guard
- incremental_update consistency
- get_trading_signals format
- All-independent markets → empty graph
"""

import sys
import os
import math

import numpy as np
import pytest

# Allow imports from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.causal_lead_lag import (
    CausalGraph,
    CausalLeadLag,
    CausalLink,
    _normal_two_tailed_p,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_causal_series(
    T: int = 300,
    lag: int = 2,
    coeff: float = 0.6,
    noise_x: float = 0.1,
    noise_y: float = 0.15,
    seed: int = 42,
) -> tuple[list[float], list[float]]:
    """Generate X and Y where X_t-lag causes Y_t.

    X is AR(1) plus noise. Y is driven by X at the specified lag plus noise.
    Returns (X_series, Y_series).
    """
    rng = np.random.default_rng(seed)
    X = np.zeros(T)
    Y = np.zeros(T)

    for t in range(1, T):
        X[t] = 0.5 * X[t - 1] + rng.normal(0, noise_x)

    for t in range(lag, T):
        Y[t] = coeff * X[t - lag] + 0.3 * Y[t - 1] + rng.normal(0, noise_y)

    return X.tolist(), Y.tolist()


def make_common_cause_series(
    T: int = 300,
    noise: float = 0.2,
    seed: int = 42,
) -> tuple[list[float], list[float], list[float]]:
    """X and Y both caused by Z (at the same time). No X→Y or Y→X link.

    Z is AR(1). X_t = 0.7*Z_t + noise. Y_t = 0.7*Z_t + noise.
    Returns (X, Y, Z).
    """
    rng = np.random.default_rng(seed)
    Z = np.zeros(T)
    for t in range(1, T):
        Z[t] = 0.6 * Z[t - 1] + rng.normal(0, 0.1)

    X = 0.7 * Z + rng.normal(0, noise, T)
    Y = 0.7 * Z + rng.normal(0, noise, T)
    return X.tolist(), Y.tolist(), Z.tolist()


def make_ar1_series(T: int = 300, phi: float = 0.9, seed: int = 42) -> list[float]:
    """Generate a single AR(1) series with no cross-variable causality."""
    rng = np.random.default_rng(seed)
    X = np.zeros(T)
    for t in range(1, T):
        X[t] = phi * X[t - 1] + rng.normal(0, 0.1)
    return X.tolist()


def make_independent_series(
    T: int = 200,
    n: int = 3,
    seed: int = 42,
) -> dict[str, list[float]]:
    """Generate n independent white-noise series."""
    rng = np.random.default_rng(seed)
    return {f"m{k}": rng.normal(0, 1, T).tolist() for k in range(n)}


# ---------------------------------------------------------------------------
# Test: known causal link discovery
# ---------------------------------------------------------------------------

class TestKnownCausalStructure:
    """PCMCI should discover X_t-2 → Y_t with reasonable power."""

    def test_discovers_causal_link_at_correct_lag(self):
        """The true lag-2 link from X to Y should appear in the output graph."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=1)
        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y})

        # Must have some links
        assert len(graph.links) > 0, "No links discovered at all"

        sig_links = [lk for lk in graph.links if lk.is_significant]
        assert len(sig_links) > 0, "No significant links discovered"

        # The true X->Y link at lag 2 must be significant
        xy_lag2 = [
            lk for lk in sig_links
            if lk.source_market == "X" and lk.target_market == "Y" and lk.lag == 2
        ]
        assert len(xy_lag2) == 1, (
            f"Expected X->Y at lag 2 to be significant; significant links = {sig_links}"
        )

    def test_discovered_link_direction_is_positive(self):
        """X causes Y with positive coefficient — direction must be 'positive'."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=2)
        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y})

        xy_sig = [
            lk for lk in graph.links
            if lk.source_market == "X" and lk.target_market == "Y"
            and lk.is_significant
        ]
        assert len(xy_sig) > 0, "No significant X->Y links"
        assert xy_sig[0].direction == "positive", (
            f"Expected positive direction, got {xy_sig[0].direction}"
        )

    def test_causal_link_strength_is_nonzero(self):
        """Significant link must have nonzero partial correlation."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=3)
        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y})

        sig_links = [lk for lk in graph.links if lk.is_significant]
        for lk in sig_links:
            assert abs(lk.strength) > 1e-6, "Significant link has near-zero strength"

    def test_p_value_below_alpha_for_true_link(self):
        """True causal link should have p_value < alpha."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.8, seed=4)
        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y})

        xy_lag2 = [
            lk for lk in graph.links
            if lk.source_market == "X" and lk.target_market == "Y" and lk.lag == 2
        ]
        assert len(xy_lag2) == 1
        assert xy_lag2[0].p_value < 0.05, (
            f"True link p_value = {xy_lag2[0].p_value:.4f}, expected < 0.05"
        )


# ---------------------------------------------------------------------------
# Test: spurious correlation rejection
# ---------------------------------------------------------------------------

class TestSpuriousCorrelationRejection:
    """When X and Y are both caused by Z at the same time, PCMCI should
    NOT find a significant X->Y or Y->X cross-market link."""

    def test_common_cause_no_direct_link_xy(self):
        """X->Y should NOT be significant when Z is the common driver."""
        X, Y, Z = make_common_cause_series(T=400, seed=10)
        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y, "Z": Z})

        # The cross-market links between X and Y should not survive
        xy_sig = [
            lk for lk in graph.links
            if lk.source_market == "X" and lk.target_market == "Y" and lk.is_significant
        ]
        yx_sig = [
            lk for lk in graph.links
            if lk.source_market == "Y" and lk.target_market == "X" and lk.is_significant
        ]

        # Allow at most 1 false positive (α=0.05 means ~5% false discovery rate)
        total_spurious = len(xy_sig) + len(yx_sig)
        assert total_spurious <= 1, (
            f"Expected spurious links suppressed; got {total_spurious} (X->Y: {xy_sig}, Y->X: {yx_sig})"
        )

    def test_bivariate_spurious_correlation_suppressed(self):
        """In a bivariate setting without Z, X and Y have contemporaneous correlation
        but no lagged causal structure. PCMCI should find no significant lagged links."""
        rng = np.random.default_rng(99)
        # Pure contemporaneous correlation — no lagged lead-lag
        Z = rng.normal(0, 1, 300)
        X = 0.8 * Z + rng.normal(0, 0.3, 300)
        Y = 0.8 * Z + rng.normal(0, 0.3, 300)

        cll = CausalLeadLag(max_lag=5, alpha=0.01, min_observations=50)
        graph = cll.fit({"X": X.tolist(), "Y": Y.tolist()})

        # With alpha=0.01 and no lagged structure, false positives should be rare
        sig_links = [lk for lk in graph.links if lk.is_significant]
        # Allow at most 2 false positives (there are 10 candidate lagged links per direction)
        assert len(sig_links) <= 2, (
            f"Too many spurious links found: {sig_links}"
        )


# ---------------------------------------------------------------------------
# Test: autocorrelation handling
# ---------------------------------------------------------------------------

class TestAutocorrelationHandling:
    """AR(1) series should not generate spurious self-causation across markets."""

    def test_two_ar1_series_no_cross_link(self):
        """Two independent AR(1) series should not show significant cross-market links."""
        rng = np.random.default_rng(55)
        # Completely independent AR(1) processes
        X = make_ar1_series(T=300, phi=0.8, seed=55)
        Y = np.zeros(300)
        Y[0] = rng.normal()
        for t in range(1, 300):
            Y[t] = 0.8 * Y[t - 1] + rng.normal(0, 0.1)
        Y_list = Y.tolist()

        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y_list})

        # Cross-market links (X->Y or Y->X) should all be insignificant
        cross_sig = [
            lk for lk in graph.links
            if lk.source_market != lk.target_market and lk.is_significant
        ]
        # α=0.05 with 8 candidate cross-market links → expect ~0.4 FP on average.
        # Allow up to 2 to avoid flaky tests (3-sigma tolerance).
        assert len(cross_sig) <= 2, (
            f"Got {len(cross_sig)} spurious cross-market links in independent AR(1) pair"
        )

    def test_ar1_self_lag_not_in_cross_links(self):
        """AR(1) autocorrelation should not appear as a false X->Y link."""
        X = make_ar1_series(T=250, phi=0.95, seed=77)
        # Y is white noise, no relationship with X
        rng = np.random.default_rng(77)
        Y = rng.normal(0, 1, 250).tolist()

        cll = CausalLeadLag(max_lag=5, alpha=0.05, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y})

        xy_sig = [lk for lk in graph.links if lk.source_market == "X" and lk.target_market == "Y" and lk.is_significant]
        assert len(xy_sig) == 0, (
            f"AR(1) X should not cause white-noise Y; got {xy_sig}"
        )


# ---------------------------------------------------------------------------
# Test: _partial_correlation correctness
# ---------------------------------------------------------------------------

class TestPartialCorrelation:
    """Verify partial_correlation against known analytical values."""

    def test_perfect_correlation_without_conditioning(self):
        """Perfectly correlated x, y with empty Z → partial corr ≈ 1."""
        cll = CausalLeadLag()
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 200)
        y = x.copy()  # perfect correlation
        Z = np.empty((200, 0))
        pcorr, pval = cll._partial_correlation(x, y, Z)
        assert abs(pcorr - 1.0) < 0.001, f"Expected ~1.0, got {pcorr}"
        assert pval < 0.001

    def test_zero_correlation_without_conditioning(self):
        """Orthogonal x, y → partial corr ≈ 0."""
        cll = CausalLeadLag()
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 500)
        y = rng.normal(0, 1, 500)  # independent
        Z = np.empty((500, 0))
        pcorr, pval = cll._partial_correlation(x, y, Z)
        assert abs(pcorr) < 0.15, f"Expected near-zero corr, got {pcorr}"
        assert pval > 0.05, f"Expected non-significant, p={pval}"

    def test_partial_correlation_removes_confound(self):
        """When both x and y are driven by z, partial corr(x,y|z) ≈ 0."""
        cll = CausalLeadLag()
        rng = np.random.default_rng(2)
        N = 500
        z = rng.normal(0, 1, N)
        x = 0.9 * z + rng.normal(0, 0.2, N)
        y = 0.9 * z + rng.normal(0, 0.2, N)

        # Without conditioning: high correlation
        Z_empty = np.empty((N, 0))
        pcorr_raw, _ = cll._partial_correlation(x, y, Z_empty)
        assert abs(pcorr_raw) > 0.5, "Expected high raw correlation"

        # With conditioning on z: near-zero partial correlation
        pcorr_cond, pval_cond = cll._partial_correlation(x, y, z.reshape(-1, 1))
        assert abs(pcorr_cond) < 0.25, (
            f"Expected near-zero partial corr after conditioning, got {pcorr_cond}"
        )

    def test_known_partial_correlation_value(self):
        """Analytical check: construct data with known partial correlation."""
        rng = np.random.default_rng(3)
        N = 1000
        z = rng.normal(0, 1, N)
        x = 0.5 * z + rng.normal(0, 1, N)
        # y depends on both z and x directly with coeff 0.4
        y = 0.4 * x + 0.5 * z + rng.normal(0, 1, N)

        cll = CausalLeadLag()
        pcorr, pval = cll._partial_correlation(x, y, z.reshape(-1, 1))

        # Partial correlation between x and y controlling for z should be positive
        # (because y = 0.4*x + ...) — exact value varies but should be clearly positive
        assert pcorr > 0.1, f"Expected positive partial correlation, got {pcorr}"
        assert pval < 0.05, f"Expected significant, got p={pval}"

    def test_p_value_is_in_valid_range(self):
        """p-value must always be in [0, 1]."""
        cll = CausalLeadLag()
        rng = np.random.default_rng(4)
        for _ in range(20):
            n = rng.integers(50, 300)
            x = rng.normal(0, 1, n)
            y = rng.normal(0, 1, n)
            Z = np.empty((n, 0))
            _, pval = cll._partial_correlation(x, y, Z)
            assert 0.0 <= pval <= 1.0, f"p_value={pval} out of [0,1]"


# ---------------------------------------------------------------------------
# Test: CausalGraph methods
# ---------------------------------------------------------------------------

class TestCausalGraphMethods:
    """Test CausalGraph.get_leaders, get_followers, strongest_link, to_adjacency_dict."""

    def _make_graph(self) -> CausalGraph:
        """Construct a small graph manually for method testing."""
        links = [
            CausalLink("A", "B", lag=1, strength=0.6, p_value=0.01, direction="positive", is_significant=True),
            CausalLink("A", "C", lag=2, strength=0.4, p_value=0.03, direction="positive", is_significant=True),
            CausalLink("B", "C", lag=1, strength=-0.3, p_value=0.04, direction="negative", is_significant=True),
            CausalLink("A", "C", lag=3, strength=0.1, p_value=0.30, direction="positive", is_significant=False),
        ]
        return CausalGraph(links=links, markets=["A", "B", "C"], max_lag=3, alpha=0.05)

    def test_get_leaders_returns_parents_only(self):
        graph = self._make_graph()
        leaders_c = graph.get_leaders("C")
        # Should return A->C (lag 2) and B->C (lag 1) but not A->C (lag 3, insignificant)
        assert len(leaders_c) == 2
        sources = {lk.source_market for lk in leaders_c}
        assert sources == {"A", "B"}

    def test_get_leaders_excludes_insignificant(self):
        graph = self._make_graph()
        leaders_c = graph.get_leaders("C")
        for lk in leaders_c:
            assert lk.is_significant, "get_leaders should only return significant links"

    def test_get_followers_returns_children_only(self):
        graph = self._make_graph()
        followers_a = graph.get_followers("A")
        # A -> B (lag 1) and A -> C (lag 2) are significant
        assert len(followers_a) == 2
        targets = {lk.target_market for lk in followers_a}
        assert targets == {"B", "C"}

    def test_get_followers_excludes_insignificant(self):
        graph = self._make_graph()
        followers_a = graph.get_followers("A")
        for lk in followers_a:
            assert lk.is_significant

    def test_strongest_link_returns_max_abs_strength(self):
        graph = self._make_graph()
        strongest = graph.strongest_link()
        assert strongest is not None
        assert strongest.source_market == "A"
        assert strongest.target_market == "B"
        assert abs(strongest.strength - 0.6) < 1e-6

    def test_strongest_link_empty_graph(self):
        graph = CausalGraph(links=[], markets=["A", "B"], max_lag=3, alpha=0.05)
        assert graph.strongest_link() is None

    def test_to_adjacency_dict_structure(self):
        graph = self._make_graph()
        adj = graph.to_adjacency_dict()
        assert set(adj.keys()) == {"A", "B", "C"}
        # B has one significant parent: A at lag 1
        assert len(adj["B"]) == 1
        assert adj["B"][0][0] == "A"
        assert adj["B"][0][1] == 1
        # C has two significant parents: A at lag 2, B at lag 1
        assert len(adj["C"]) == 2
        # A has no parents
        assert len(adj["A"]) == 0

    def test_to_adjacency_dict_strength_values(self):
        graph = self._make_graph()
        adj = graph.to_adjacency_dict()
        b_entry = adj["B"][0]
        assert abs(b_entry[2] - 0.6) < 1e-6


# ---------------------------------------------------------------------------
# Test: multivariate (3+ markets)
# ---------------------------------------------------------------------------

class TestMultivariateHandling:
    """Verify correct behavior with 3+ markets."""

    def test_three_market_chain_discovers_direct_link(self):
        """In A -> B -> C chain, should find A->B and B->C at correct lags."""
        rng = np.random.default_rng(30)
        T = 350
        A = np.zeros(T)
        B = np.zeros(T)
        C = np.zeros(T)

        for t in range(1, T):
            A[t] = 0.5 * A[t - 1] + rng.normal(0, 0.1)
        for t in range(2, T):
            B[t] = 0.65 * A[t - 2] + 0.3 * B[t - 1] + rng.normal(0, 0.12)
        for t in range(2, T):
            C[t] = 0.65 * B[t - 2] + 0.3 * C[t - 1] + rng.normal(0, 0.12)

        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit({
            "A": A.tolist(),
            "B": B.tolist(),
            "C": C.tolist(),
        })

        assert "A" in graph.markets
        assert "B" in graph.markets
        assert "C" in graph.markets

        # A -> B link should be discovered
        ab_sig = [lk for lk in graph.links if lk.source_market == "A" and lk.target_market == "B" and lk.is_significant]
        assert len(ab_sig) > 0, "Expected A->B link in chain"

        # B -> C link should be discovered
        bc_sig = [lk for lk in graph.links if lk.source_market == "B" and lk.target_market == "C" and lk.is_significant]
        assert len(bc_sig) > 0, "Expected B->C link in chain"

    def test_three_market_returns_correct_market_list(self):
        data = make_independent_series(T=100, n=3, seed=5)
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        graph = cll.fit(data)
        assert set(graph.markets) == {"m0", "m1", "m2"}


# ---------------------------------------------------------------------------
# Test: min_observations guard
# ---------------------------------------------------------------------------

class TestMinObservationsGuard:
    """fit() should return empty graph when data is too short."""

    def test_too_few_observations_returns_empty_graph(self):
        rng = np.random.default_rng(50)
        short_data = {
            "A": rng.normal(0, 1, 20).tolist(),
            "B": rng.normal(0, 1, 20).tolist(),
        }
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        graph = cll.fit(short_data)

        assert len(graph.links) == 0, "Expected empty graph for insufficient data"
        assert set(graph.markets) == {"A", "B"}

    def test_exactly_at_min_observations_runs(self):
        """At exactly min_observations, fit should proceed (not return empty)."""
        T = 50
        X, Y = make_causal_series(T=T, lag=1, coeff=0.8, seed=60)
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=T)
        # Should not raise; may or may not find links depending on sample
        graph = cll.fit({"X": X, "Y": Y})
        assert isinstance(graph, CausalGraph)

    def test_mismatched_series_lengths_raises(self):
        """Mismatched series lengths should raise ValueError."""
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        with pytest.raises(ValueError, match="equal length"):
            cll.fit({
                "A": [0.5] * 100,
                "B": [0.5] * 80,
            })

    def test_single_market_returns_empty_graph(self):
        """Only one market — can't compute cross links."""
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        graph = cll.fit({"A": list(range(100))})
        assert len(graph.links) == 0


# ---------------------------------------------------------------------------
# Test: incremental_update consistency
# ---------------------------------------------------------------------------

class TestIncrementalUpdate:
    """incremental_update should produce results consistent with full refit."""

    def test_incremental_update_same_markets(self):
        """incremental_update with identical data should return same market list."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=70)
        data = {"X": X, "Y": Y}

        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph1 = cll.fit(data)
        graph2 = cll.incremental_update(data, graph1)

        assert set(graph1.markets) == set(graph2.markets)

    def test_incremental_update_similar_significant_links(self):
        """incremental_update on same data should find same or similar significant links."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=71)
        data = {"X": X, "Y": Y}

        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph1 = cll.fit(data)
        graph2 = cll.incremental_update(data, graph1)

        sig1 = {(lk.source_market, lk.target_market, lk.lag) for lk in graph1.links if lk.is_significant}
        sig2 = {(lk.source_market, lk.target_market, lk.lag) for lk in graph2.links if lk.is_significant}

        # Overlap should be high (same data, deterministic algorithm)
        overlap = len(sig1 & sig2)
        union = len(sig1 | sig2)
        jaccard = overlap / union if union > 0 else 1.0
        assert jaccard >= 0.5 or (len(sig1) == 0 and len(sig2) == 0), (
            f"Incremental update gave very different result: sig1={sig1}, sig2={sig2}"
        )

    def test_incremental_update_returns_causal_graph(self):
        """Return type should be CausalGraph."""
        X, Y = make_causal_series(T=200, lag=1, coeff=0.6, seed=72)
        data = {"X": X, "Y": Y}
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        prev_graph = cll.fit(data)
        new_graph = cll.incremental_update(data, prev_graph)
        assert isinstance(new_graph, CausalGraph)


# ---------------------------------------------------------------------------
# Test: get_trading_signals format
# ---------------------------------------------------------------------------

class TestGetTradingSignals:
    """get_trading_signals should return correctly structured dicts."""

    REQUIRED_KEYS = {
        "target_market",
        "predicted_direction",
        "confidence",
        "source_market",
        "lag",
        "causal_strength",
    }

    def _make_graph_with_link(self) -> CausalGraph:
        links = [
            CausalLink(
                source_market="X",
                target_market="Y",
                lag=2,
                strength=0.6,
                p_value=0.01,
                direction="positive",
                is_significant=True,
            )
        ]
        return CausalGraph(links=links, markets=["X", "Y"], max_lag=4, alpha=0.05)

    def test_signal_has_all_required_keys(self):
        graph = self._make_graph_with_link()
        cll = CausalLeadLag()
        # X moved up significantly; Y hasn't moved yet
        X_hist = [0.0] * 10 + [0.1]   # moved +0.1 in last step from lag-2 position
        Y_hist = [0.5] * 12
        # Align lengths
        price_history = {"X": [0.0] * 3 + [0.1] * 8, "Y": [0.5] * 11}
        current_prices = {"X": 0.1, "Y": 0.5}

        signals = cll.get_trading_signals(graph, current_prices, price_history)
        if signals:
            for s in signals:
                missing = self.REQUIRED_KEYS - set(s.keys())
                assert not missing, f"Signal missing keys: {missing}"

    def test_no_price_history_returns_empty(self):
        graph = self._make_graph_with_link()
        cll = CausalLeadLag()
        current_prices = {"X": 0.6, "Y": 0.4}
        signals = cll.get_trading_signals(graph, current_prices, price_history=None)
        assert signals == []

    def test_signal_direction_values(self):
        """predicted_direction must be 'up' or 'down'."""
        graph = self._make_graph_with_link()
        cll = CausalLeadLag()
        # Build history where X made a big move
        rng = np.random.default_rng(80)
        base = rng.normal(0.5, 0.01, 15).tolist()
        X_hist = base[:-1] + [base[-1] + 0.10]  # big up move
        Y_hist = rng.normal(0.4, 0.005, 15).tolist()
        price_history = {"X": X_hist, "Y": Y_hist}
        current_prices = {"X": X_hist[-1], "Y": Y_hist[-1]}

        signals = cll.get_trading_signals(graph, current_prices, price_history)
        for s in signals:
            assert s["predicted_direction"] in ("up", "down"), (
                f"Invalid direction: {s['predicted_direction']}"
            )

    def test_signal_confidence_in_range(self):
        """confidence must be in [0, 1]."""
        graph = self._make_graph_with_link()
        cll = CausalLeadLag()
        rng = np.random.default_rng(81)
        X_hist = rng.normal(0.5, 0.01, 15).tolist()
        X_hist[-1] = X_hist[-3] + 0.15  # large move at lag 2
        Y_hist = rng.normal(0.4, 0.005, 15).tolist()
        price_history = {"X": X_hist, "Y": Y_hist}
        current_prices = {"X": X_hist[-1], "Y": Y_hist[-1]}

        signals = cll.get_trading_signals(graph, current_prices, price_history)
        for s in signals:
            assert 0.0 <= s["confidence"] <= 1.0, f"Confidence out of range: {s['confidence']}"

    def test_empty_graph_produces_no_signals(self):
        """Empty graph → no signals."""
        graph = CausalGraph(links=[], markets=["X", "Y"], max_lag=3, alpha=0.05)
        cll = CausalLeadLag()
        current_prices = {"X": 0.5, "Y": 0.5}
        price_history = {"X": [0.5] * 10, "Y": [0.5] * 10}
        signals = cll.get_trading_signals(graph, current_prices, price_history)
        assert signals == []


# ---------------------------------------------------------------------------
# Test: all-independent markets → empty or near-empty graph
# ---------------------------------------------------------------------------

class TestAllIndependentMarkets:
    """When all markets are independent white noise, PCMCI should return
    an empty or near-empty graph (very few false positives)."""

    def test_independent_markets_mostly_empty_graph(self):
        """3 independent markets with 200 obs should produce few significant links."""
        data = make_independent_series(T=200, n=3, seed=42)
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        graph = cll.fit(data)

        sig_links = [lk for lk in graph.links if lk.is_significant]
        # With 3 markets, max_lag=3: 3*2*3 = 18 candidate links
        # Expected false positives at α=0.05: ~0.9 on average
        # Allow up to 3 to avoid flaky tests
        assert len(sig_links) <= 3, (
            f"Too many false positive links in independent data: {len(sig_links)}"
        )

    def test_five_independent_markets_graph_size(self):
        """5 independent markets — check false positive rate stays reasonable."""
        data = make_independent_series(T=250, n=5, seed=43)
        cll = CausalLeadLag(max_lag=3, alpha=0.05, min_observations=50)
        graph = cll.fit(data)

        total_candidate_links = 5 * 4 * 3  # N*(N-1)*max_lag
        sig_links = [lk for lk in graph.links if lk.is_significant]
        fpr = len(sig_links) / total_candidate_links
        # Allow 3x the nominal alpha as tolerance (PCMCI controls FWER not FDR)
        assert fpr <= 0.20, (
            f"FPR too high: {fpr:.3f} ({len(sig_links)} / {total_candidate_links})"
        )


# ---------------------------------------------------------------------------
# Test: _normal_two_tailed_p utility
# ---------------------------------------------------------------------------

class TestNormalTwoTailedP:
    """Verify the p-value utility function."""

    def test_z_zero_gives_p_one(self):
        p = _normal_two_tailed_p(0.0)
        assert abs(p - 1.0) < 0.01

    def test_large_z_gives_small_p(self):
        p = _normal_two_tailed_p(10.0)
        assert p < 1e-6

    def test_negative_z_same_as_positive(self):
        """Two-tailed p-value is symmetric."""
        p1 = _normal_two_tailed_p(2.0)
        p2 = _normal_two_tailed_p(-2.0)
        assert abs(p1 - p2) < 1e-6

    def test_z_196_gives_approximately_005(self):
        """z=1.96 should give p ≈ 0.05."""
        p = _normal_two_tailed_p(1.96)
        assert abs(p - 0.05) < 0.005, f"Expected ~0.05, got {p}"

    def test_z_258_gives_approximately_001(self):
        """z=2.576 should give p ≈ 0.01."""
        p = _normal_two_tailed_p(2.576)
        assert abs(p - 0.01) < 0.003, f"Expected ~0.01, got {p}"


# ---------------------------------------------------------------------------
# Test: CausalLink dataclass
# ---------------------------------------------------------------------------

class TestCausalLink:
    def test_causal_link_fields(self):
        lk = CausalLink(
            source_market="market_a",
            target_market="market_b",
            lag=3,
            strength=0.45,
            p_value=0.02,
            direction="positive",
            is_significant=True,
        )
        assert lk.source_market == "market_a"
        assert lk.target_market == "market_b"
        assert lk.lag == 3
        assert abs(lk.strength - 0.45) < 1e-9
        assert abs(lk.p_value - 0.02) < 1e-9
        assert lk.direction == "positive"
        assert lk.is_significant is True

    def test_negative_direction_link(self):
        lk = CausalLink(
            source_market="X",
            target_market="Y",
            lag=1,
            strength=-0.3,
            p_value=0.04,
            direction="negative",
            is_significant=True,
        )
        assert lk.direction == "negative"
        assert lk.strength < 0


# ---------------------------------------------------------------------------
# Integration: end-to-end with realistic data
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Smoke test: run full pipeline on non-trivial synthetic data."""

    def test_full_pipeline_runs_without_error(self):
        """Full pipeline must run from fit() to get_trading_signals() without error."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=100)
        rng = np.random.default_rng(100)
        Z = (rng.normal(0, 1, 300) * 0.05 + 0.5).tolist()

        data = {"BTC": X, "ETH": Y, "SOL": Z}

        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph = cll.fit(data)

        assert isinstance(graph, CausalGraph)
        assert set(graph.markets) == {"BTC", "ETH", "SOL"}

        current_prices = {"BTC": X[-1], "ETH": Y[-1], "SOL": Z[-1]}
        price_history = {"BTC": X[-20:], "ETH": Y[-20:], "SOL": Z[-20:]}

        signals = cll.get_trading_signals(graph, current_prices, price_history)
        assert isinstance(signals, list)
        for s in signals:
            assert "target_market" in s
            assert "predicted_direction" in s
            assert "confidence" in s

    def test_causal_graph_alpha_stored_correctly(self):
        X, Y = make_causal_series(T=200, lag=1, coeff=0.6, seed=101)
        cll = CausalLeadLag(max_lag=3, alpha=0.01, min_observations=50)
        graph = cll.fit({"X": X, "Y": Y})
        assert abs(graph.alpha - 0.01) < 1e-9
        assert graph.max_lag == 3

    def test_incremental_update_on_new_data_runs(self):
        """incremental_update with extended data should run without error."""
        X, Y = make_causal_series(T=300, lag=2, coeff=0.7, seed=102)
        cll = CausalLeadLag(max_lag=4, alpha=0.05, min_observations=50)
        graph1 = cll.fit({"X": X, "Y": Y})

        # Extend data
        X2, Y2 = make_causal_series(T=350, lag=2, coeff=0.7, seed=102)
        graph2 = cll.incremental_update({"X": X2, "Y": Y2}, graph1)
        assert isinstance(graph2, CausalGraph)
