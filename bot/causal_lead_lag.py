#!/usr/bin/env python3
"""
Causal Lead-Lag Discovery via PCMCI
====================================
Replaces Granger causality in lead_lag_engine.py with proper causal discovery
based on the PCMCI algorithm (Runge et al., 2019).

Discovers genuine causal relationships between prediction markets by:
1. PC stage: Iterative conditioning to eliminate spurious associations
2. MCI stage: Momentary conditional independence controlling for
   autocorrelation and indirect effects

The key distinction from Granger causality:
- Granger: Does X help predict Y? (temporal correlation, not causation)
- PCMCI/MCI: Is X -> Y a genuine causal link after conditioning on ALL
  confounders and the full causal graph? (far fewer false positives)

Reference: Runge et al. (2019), "Detecting and quantifying causal associations
in large nonlinear time series datasets", Science Advances.

Author: JJ (autonomous)
Date: 2026-03-21
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger("JJ.causal_lead_lag")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CausalLink:
    """A directed causal link between two markets at a specific lag."""
    source_market: str      # Market ID of the cause
    target_market: str      # Market ID of the effect
    lag: int                # Time lag (in observation steps)
    strength: float         # Partial correlation coefficient
    p_value: float          # Statistical significance
    direction: str          # "positive" or "negative"
    is_significant: bool    # p_value < alpha


@dataclass
class CausalGraph:
    """Full causal graph discovered by PCMCI over a set of markets."""
    links: list[CausalLink]
    markets: list[str]
    max_lag: int
    alpha: float            # Significance level used

    def get_leaders(self, target_market: str) -> list[CausalLink]:
        """Return all significant causal parents of target_market."""
        return [
            lk for lk in self.links
            if lk.target_market == target_market and lk.is_significant
        ]

    def get_followers(self, source_market: str) -> list[CausalLink]:
        """Return all significant causal children of source_market."""
        return [
            lk for lk in self.links
            if lk.source_market == source_market and lk.is_significant
        ]

    def strongest_link(self) -> Optional["CausalLink"]:
        """Return the link with highest absolute strength among significant links."""
        sig = [lk for lk in self.links if lk.is_significant]
        if not sig:
            return None
        return max(sig, key=lambda lk: abs(lk.strength))

    def to_adjacency_dict(self) -> dict:
        """Return {target: [(source, lag, strength), ...]} dict for significant links."""
        result: dict[str, list[tuple[str, int, float]]] = {m: [] for m in self.markets}
        for lk in self.links:
            if lk.is_significant:
                result[lk.target_market].append(
                    (lk.source_market, lk.lag, lk.strength)
                )
        return result


# ---------------------------------------------------------------------------
# Core PCMCI implementation
# ---------------------------------------------------------------------------

class CausalLeadLag:
    """
    Self-contained PCMCI causal discovery for prediction market time series.

    The algorithm has two stages:
    1. PC (Peter-Clark) stage: For each (target, source, lag) candidate,
       find the minimal conditioning set that makes the link conditionally
       independent. Reject the link if such a set exists.

    2. MCI (Momentary Conditional Independence) stage: Re-test surviving
       links while conditioning on the full discovered parent sets of both
       the target AND the source. This additional conditioning controls for
       autocorrelation-induced false positives that survive the PC stage.

    No tigramite dependency. Uses numpy OLS residuals + Fisher z-transform
    for partial correlations.
    """

    def __init__(
        self,
        max_lag: int = 5,
        alpha: float = 0.05,
        max_conds_dim: Optional[int] = None,
        min_observations: int = 50,
    ):
        """
        Args:
            max_lag: Maximum lag to test (in time steps)
            alpha: p-value threshold for significance
            max_conds_dim: Limit on conditioning set size (None = auto from data)
            min_observations: Minimum time steps required to run
        """
        self.max_lag = max_lag
        self.alpha = alpha
        self.max_conds_dim = max_conds_dim
        self.min_observations = min_observations

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        data: dict[str, list[float]],
        market_names: Optional[dict[str, str]] = None,
    ) -> CausalGraph:
        """Run PCMCI on multivariate time series data.

        Args:
            data: {market_id: [price_series]} — all series must be same length
            market_names: {market_id: human_readable_name} optional, unused
                          in computation but logged for readability

        Returns:
            CausalGraph with all significant links found by PCMCI
        """
        markets = list(data.keys())
        n_vars = len(markets)

        if n_vars < 2:
            logger.warning("causal_lead_lag.fit: need at least 2 markets, got %d", n_vars)
            return CausalGraph(links=[], markets=markets, max_lag=self.max_lag, alpha=self.alpha)

        # Validate all series same length
        lengths = [len(v) for v in data.values()]
        if len(set(lengths)) != 1:
            raise ValueError(
                f"All series must have equal length; got lengths {dict(zip(markets, lengths))}"
            )

        T = lengths[0]
        if T < self.min_observations:
            logger.warning(
                "causal_lead_lag.fit: only %d observations, minimum is %d — returning empty graph",
                T, self.min_observations,
            )
            return CausalGraph(links=[], markets=markets, max_lag=self.max_lag, alpha=self.alpha)

        # Stack into (T, N) array
        data_array = np.column_stack([np.array(data[m], dtype=np.float64) for m in markets])

        logger.info(
            "causal_lead_lag.fit: T=%d, N=%d markets, max_lag=%d, alpha=%.3f",
            T, n_vars, self.max_lag, self.alpha,
        )

        # PC stage: discover parent sets
        parents = self._pc_stage(data_array)

        # MCI stage: test each surviving link with full conditioning
        links_raw = self._mci_stage(data_array, parents)

        # Build CausalLink objects referencing market IDs
        links = []
        for (j, i, lag), (pcorr, pval) in links_raw.items():
            is_sig = pval < self.alpha
            links.append(CausalLink(
                source_market=markets[i],
                target_market=markets[j],
                lag=lag,
                strength=pcorr,
                p_value=pval,
                direction="positive" if pcorr >= 0 else "negative",
                is_significant=is_sig,
            ))

        sig_count = sum(1 for lk in links if lk.is_significant)
        logger.info(
            "causal_lead_lag.fit: %d links tested, %d significant at alpha=%.3f",
            len(links), sig_count, self.alpha,
        )

        return CausalGraph(
            links=links,
            markets=markets,
            max_lag=self.max_lag,
            alpha=self.alpha,
        )

    def incremental_update(
        self,
        data: dict[str, list[float]],
        previous_graph: CausalGraph,
    ) -> CausalGraph:
        """Re-run PCMCI with warm start from previous graph.

        In the current implementation this does a full refit (the computational
        cost of PCMCI is dominated by the number of markets, not by the number
        of previously discovered links). The warm-start optimization — only
        re-testing links whose series have changed significantly — is noted as
        a future improvement.

        Args:
            data: Fresh time series data for all markets
            previous_graph: Result from previous fit() call

        Returns:
            New CausalGraph (full refit)
        """
        logger.info("causal_lead_lag.incremental_update: warm-start refit")
        return self.fit(data)

    def get_trading_signals(
        self,
        graph: CausalGraph,
        current_prices: dict[str, float],
        price_history: Optional[dict[str, list[float]]] = None,
    ) -> list[dict]:
        """Given a causal graph and current prices, identify trading opportunities.

        For each significant link (A -> B at lag L):
        If A has moved significantly in the last L steps and B hasn't yet,
        predict B will follow and return a signal.

        Args:
            graph: CausalGraph from fit()
            current_prices: {market_id: current_price}
            price_history: {market_id: [recent_prices]} for movement calculation.
                           If None, signals cannot be computed (returns empty list).

        Returns:
            list of signal dicts with keys:
              target_market, predicted_direction, confidence,
              source_market, lag, causal_strength
        """
        if price_history is None:
            logger.warning("get_trading_signals: price_history required, returning empty")
            return []

        signals = []
        MOVEMENT_THRESHOLD = 0.02  # 2% minimum move to trigger signal

        for link in graph.get_leaders.__func__(graph, "__all__") if False else [
            lk for lk in graph.links if lk.is_significant
        ]:
            source = link.source_market
            target = link.target_market
            lag = link.lag

            src_hist = price_history.get(source, [])
            tgt_hist = price_history.get(target, [])

            if len(src_hist) < lag + 1 or len(tgt_hist) < 2:
                continue

            # Leader move over the lag window
            src_move = src_hist[-1] - src_hist[-1 - lag] if len(src_hist) > lag else 0.0
            # Follower recent move (last 1 step)
            tgt_move = tgt_hist[-1] - tgt_hist[-2] if len(tgt_hist) >= 2 else 0.0

            if abs(src_move) < MOVEMENT_THRESHOLD:
                continue

            # Expected direction on target
            if link.direction == "positive":
                expected_direction = "up" if src_move > 0 else "down"
            else:
                expected_direction = "down" if src_move > 0 else "up"

            # Has follower already moved in the expected direction?
            expected_sign = 1 if expected_direction == "up" else -1
            follower_already_moved = (tgt_move * expected_sign) > MOVEMENT_THRESHOLD * 0.5

            if follower_already_moved:
                continue  # opportunity has passed

            confidence = min(1.0, abs(link.strength) * (abs(src_move) / MOVEMENT_THRESHOLD))

            signals.append({
                "target_market": target,
                "predicted_direction": expected_direction,
                "confidence": float(confidence),
                "source_market": source,
                "lag": lag,
                "causal_strength": float(link.strength),
            })

        return signals

    # ------------------------------------------------------------------
    # Internal: partial correlation
    # ------------------------------------------------------------------

    def _partial_correlation(
        self,
        x: np.ndarray,
        y: np.ndarray,
        z: np.ndarray,
    ) -> tuple[float, float]:
        """Compute partial correlation between x and y given z.

        Uses regression-based approach:
        1. Regress x on z, get residuals r_x
        2. Regress y on z, get residuals r_y
        3. Pearson correlation of (r_x, r_y) is the partial correlation

        p-value via Fisher z-transform of the partial correlation.

        Args:
            x: (n,) array
            y: (n,) array
            z: (n, k) conditioning array; if k=0 this reduces to regular correlation

        Returns:
            (partial_corr, p_value)
        """
        n = len(x)

        if z.ndim == 1:
            z = z.reshape(-1, 1)

        k = z.shape[1] if z.ndim == 2 else 0

        if k == 0 or z.shape[1] == 0:
            # No conditioning — use regular Pearson correlation
            r_x = x - x.mean()
            r_y = y - y.mean()
        else:
            # Regress x on z
            r_x = self._ols_residuals(z, x)
            r_y = self._ols_residuals(z, y)

        # Pearson correlation of residuals
        denom_x = np.sqrt(np.sum(r_x ** 2))
        denom_y = np.sqrt(np.sum(r_y ** 2))

        if denom_x < 1e-10 or denom_y < 1e-10:
            return 0.0, 1.0

        pcorr = float(np.dot(r_x, r_y) / (denom_x * denom_y))
        # Clamp for numerical safety
        pcorr = max(-1.0 + 1e-10, min(1.0 - 1e-10, pcorr))

        # Fisher z-transform for p-value
        # Effective degrees of freedom: n - k - 2 (k conditioning variables)
        df = n - k - 2
        if df < 1:
            return pcorr, 1.0

        z_score = 0.5 * math.log((1 + pcorr) / (1 - pcorr))
        se = 1.0 / math.sqrt(df - 1) if df > 1 else 1.0
        t_stat = z_score / se if se > 0 else 0.0

        # Two-tailed p-value from standard normal approximation
        p_value = _normal_two_tailed_p(t_stat)

        return pcorr, p_value

    @staticmethod
    def _ols_residuals(X: np.ndarray, y: np.ndarray) -> np.ndarray:
        """OLS regression y ~ X, return residuals. Adds intercept column."""
        n = len(y)
        X_with_intercept = np.column_stack([X, np.ones(n)])
        try:
            beta, _, _, _ = np.linalg.lstsq(X_with_intercept, y, rcond=None)
            return y - X_with_intercept @ beta
        except np.linalg.LinAlgError:
            return y - y.mean()

    # ------------------------------------------------------------------
    # Internal: build lagged embedding
    # ------------------------------------------------------------------

    def _get_lagged_slice(
        self,
        data: np.ndarray,
        var_idx: int,
        lag: int,
        start_row: int,
    ) -> np.ndarray:
        """Extract lagged column of variable var_idx at lag `lag`, aligned to rows [start_row:].

        For a T x N array, row t in output corresponds to data[t + start_row - lag, var_idx].
        Returns empty array (length 0) if the lag exceeds available data.
        """
        T = data.shape[0]
        n_rows = T - start_row  # number of target rows
        if lag > start_row or n_rows <= 0:
            return np.empty(0)
        return data[start_row - lag: T - lag, var_idx]

    def _build_conditioning_matrix(
        self,
        data: np.ndarray,
        cond_set: list[tuple[int, int]],
        start_row: int,
    ) -> np.ndarray:
        """Build conditioning matrix from a list of (var_idx, lag) tuples.

        Silently drops any conditioning variable whose lagged slice has the
        wrong length (e.g. lag > start_row after lag-shifting in MCI stage).
        """
        n_rows = data.shape[0] - start_row
        if not cond_set:
            return np.empty((n_rows, 0))
        cols = []
        for vi, lag in cond_set:
            col = self._get_lagged_slice(data, vi, lag, start_row)
            if len(col) == n_rows:
                cols.append(col)
        if not cols:
            return np.empty((n_rows, 0))
        return np.column_stack(cols)

    # ------------------------------------------------------------------
    # Internal: PC stage
    # ------------------------------------------------------------------

    def _pc_stage(self, data: np.ndarray) -> dict[int, list[tuple[int, int]]]:
        """PC algorithm for condition selection.

        For each target variable j and each (source i, lag) pair:
        Start with an empty conditioning set. Iteratively add the strongest
        partial-correlated variable from the current parent set until the
        candidate link is conditionally independent at alpha, or the maximum
        conditioning depth is reached.

        Returns:
            parents: {target_j: [(source_i, lag), ...]} — preliminary parent
                     sets (links that survived conditioning)
        """
        T, N = data.shape
        max_lag = self.max_lag
        start_row = max_lag  # We always condition on enough rows for full lag

        # Determine max conditioning dimension
        max_conds = self.max_conds_dim
        if max_conds is None:
            # Auto: limit to min(N-1, sqrt(T/10)) to keep computation tractable
            max_conds = max(1, min(N - 1, int(math.sqrt(T / 10))))

        # Initial parent sets: all (source, lag) combinations except self at lag 0
        parents: dict[int, list[tuple[int, int]]] = {}
        for j in range(N):
            candidates = []
            for i in range(N):
                for lag in range(1, max_lag + 1):
                    if i == j and lag == 0:
                        continue
                    candidates.append((i, lag))
            parents[j] = candidates

        # PC iterations: iteratively remove conditionally independent links
        for cond_dim in range(max_conds + 1):
            changed = False
            for j in range(N):
                surviving = []
                target = data[start_row:, j]

                for (i, lag) in parents[j]:
                    source = self._get_lagged_slice(data, i, lag, start_row)

                    # Try to find a conditioning set of size cond_dim from
                    # the other current parents that makes (i,lag) -> j independent
                    other_parents = [(pi, pl) for (pi, pl) in parents[j] if (pi, pl) != (i, lag)]

                    if cond_dim == 0:
                        # Unconditional test
                        Z = np.empty((len(target), 0))
                        pcorr, pval = self._partial_correlation(source, target, Z)
                        if pval >= self.alpha:
                            # Link is independent — remove from parent set
                            changed = True
                            continue
                    else:
                        if len(other_parents) < cond_dim:
                            # Not enough parents to form conditioning set of this size
                            surviving.append((i, lag))
                            continue

                        # Try the best conditioning set of size cond_dim
                        # (greedy: pick top cond_dim by unconditional partial corr with target)
                        scored = []
                        for (pi, pl) in other_parents:
                            ps = self._get_lagged_slice(data, pi, pl, start_row)
                            Z_empty = np.empty((len(target), 0))
                            pc, _ = self._partial_correlation(ps, target, Z_empty)
                            scored.append((abs(pc), (pi, pl)))
                        scored.sort(reverse=True)
                        best_cond_set = [sp[1] for sp in scored[:cond_dim]]

                        Z = self._build_conditioning_matrix(data, best_cond_set, start_row)
                        pcorr, pval = self._partial_correlation(source, target, Z)

                        if pval >= self.alpha:
                            changed = True
                            continue

                    surviving.append((i, lag))

                parents[j] = surviving

            if not changed:
                break  # Converged

        logger.debug(
            "PC stage complete: parent set sizes = %s",
            {j: len(ps) for j, ps in parents.items()},
        )
        return parents

    # ------------------------------------------------------------------
    # Internal: MCI stage
    # ------------------------------------------------------------------

    def _mci_stage(
        self,
        data: np.ndarray,
        parents: dict[int, list[tuple[int, int]]],
    ) -> dict[tuple[int, int, int], tuple[float, float]]:
        """MCI test for each candidate link surviving the PC stage.

        For each candidate link (source i, lag) -> target j:
        Condition on:
          - All other parents of j (from PC stage) excluding (i, lag)
          - All parents of i at lag `lag` (i.e., parents of the lagged source)

        This controls for:
          - Common confounders driving both i and j
          - Autocorrelation in j
          - Indirect paths through other variables

        Returns:
            {(target_j, source_i, lag): (partial_corr, p_value)}
        """
        T, N = data.shape
        start_row = self.max_lag
        results: dict[tuple[int, int, int], tuple[float, float]] = {}

        for j in range(N):
            target = data[start_row:, j]

            for (i, lag) in parents[j]:
                source = self._get_lagged_slice(data, i, lag, start_row)

                # Conditioning set 1: other parents of j (excluding (i, lag))
                cond_j = [(pi, pl) for (pi, pl) in parents[j] if (pi, pl) != (i, lag)]

                # Conditioning set 2: parents of i at the specified lag
                # i.e., the variables that "parent" i's state at time t-lag
                # We approximate this by taking parents[i] and shifting them
                # by an additional `lag` steps
                cond_i_at_lag = []
                for (pi, pl) in parents[i]:
                    shifted_lag = pl + lag
                    if shifted_lag <= self.max_lag * 2:  # guard against excessive lags
                        cond_i_at_lag.append((pi, shifted_lag))

                full_cond_set = cond_j + cond_i_at_lag

                # Deduplicate, enforce max_conds_dim
                seen = set()
                deduped = []
                for entry in full_cond_set:
                    if entry not in seen and entry != (i, lag):
                        seen.add(entry)
                        deduped.append(entry)

                # Cap at max_conds_dim
                max_conds = self.max_conds_dim
                if max_conds is None:
                    max_conds = max(1, min(N - 1, int(math.sqrt(T / 10))))
                deduped = deduped[:max_conds * 2]  # generous cap for MCI

                # Filter out any cond entries that would exceed data bounds
                valid_cond = []
                for (pi, pl) in deduped:
                    if pl <= T - start_row - 1:
                        valid_cond.append((pi, pl))

                Z = self._build_conditioning_matrix(data, valid_cond, start_row)
                pcorr, pval = self._partial_correlation(source, target, Z)

                results[(j, i, lag)] = (pcorr, pval)

        return results


# ---------------------------------------------------------------------------
# Statistical utilities
# ---------------------------------------------------------------------------

def _normal_two_tailed_p(z: float) -> float:
    """Two-tailed p-value from standard normal distribution.

    Uses math.erfc which is in Python's standard library and accurate to
    machine precision. No scipy dependency required.

    For the standard normal: P(|Z| > z) = erfc(z / sqrt(2)).
    """
    if not math.isfinite(z):
        return 1.0
    az = abs(z)
    if az > 38.0:
        return 0.0
    return math.erfc(az / math.sqrt(2.0))
