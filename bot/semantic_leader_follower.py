#!/usr/bin/env python3
"""
Semantic Leader-Follower Arbitrage
====================================
Dispatch: IBM/Columbia paper arxiv 2512.02436

Discovers semantically related prediction markets and exploits the
leader-follower relationship between them.  When market A moves
significantly and market B is semantically related but has not moved yet,
trade B in the predicted direction.

The paper demonstrated ~20% average returns using this approach on
Polymarket data.  This implementation uses TF-IDF embeddings (no
external model required), cosine similarity for pair discovery, and
cross-correlation for lead-lag quantification.

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from sklearn.feature_extraction.text import TfidfVectorizer

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover – sklearn absent in some environments
    _SKLEARN_AVAILABLE = False

try:
    from bot import elastic_client  # type: ignore
except ImportError:  # pragma: no cover – script-style execution fallback
    try:
        import elastic_client  # type: ignore
    except ImportError:
        elastic_client = None  # type: ignore

logger = logging.getLogger("JJ.semantic_leader_follower")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class MarketEmbedding:
    """TF-IDF embedding and live state for a single prediction market."""

    market_id: str
    question: str
    embedding: list[float]
    category: str
    current_price: float
    price_history: list[float]  # Most recent prices, oldest first
    volume_24h: float
    resolution_date: str


@dataclass
class MarketPair:
    """A semantically related leader-follower market pair."""

    leader: MarketEmbedding
    follower: MarketEmbedding
    similarity: float  # Cosine similarity 0-1
    relationship_type: str  # "causal"|"correlated"|"conditional"|"same_event"
    historical_lead_lag: float  # Optimal lag in units of price history steps
    directional_correlation: float  # +1 same direction, -1 inverse
    confidence: float  # Overall reliability of the pair

    # Mutable stats updated as we observe more data
    observed_leader_moves: int = 0
    observed_follower_follows: int = 0


@dataclass
class LeaderFollowerSignal:
    """Actionable trading signal from the leader-follower engine."""

    leader_market_id: str
    leader_question: str
    leader_price_change: float
    leader_direction: str  # "up" or "down"

    follower_market_id: str
    follower_question: str
    follower_current_price: float
    predicted_direction: str  # "up" or "down"
    predicted_magnitude: float

    confidence: float
    pair_similarity: float
    signal_strength: float  # similarity * |leader_move| * |directional_corr|
    recommended_side: str  # "BUY_YES" or "BUY_NO"
    recommended_size_usd: float

    generated_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # Unix timestamp; 0 means no expiry set


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------


class SemanticLeaderFollower:
    """
    Discovers and trades semantic leader-follower relationships between
    prediction markets.

    Parameters
    ----------
    min_similarity:
        Minimum cosine similarity for a pair to be tracked (default 0.40).
    min_price_change:
        Minimum absolute price move for the leader to trigger a signal
        (default 0.05 = 5%).
    min_signal_strength:
        Minimum signal_strength score for a signal to be emitted
        (default 0.3).
    max_pairs:
        Maximum number of pairs to track at once (default 500).
    embedding_dim:
        Number of TF-IDF features (default 100).
    lookback_window:
        Number of historical price steps to use for lead-lag and correlation
        estimates (default 20).
    max_position_usd:
        Default maximum position size in USD (default 10.0).
    signal_ttl_seconds:
        How many seconds a signal remains active before expiry (default 300).
    """

    def __init__(
        self,
        min_similarity: float = 0.40,
        min_price_change: float = 0.05,
        min_signal_strength: float = 0.3,
        max_pairs: int = 500,
        embedding_dim: int = 100,
        lookback_window: int = 20,
        max_position_usd: float = 10.0,
        signal_ttl_seconds: float = 300.0,
    ) -> None:
        self.min_similarity = min_similarity
        self.min_price_change = min_price_change
        self.min_signal_strength = min_signal_strength
        self.max_pairs = max_pairs
        self.embedding_dim = embedding_dim
        self.lookback_window = lookback_window
        self.max_position_usd = max_position_usd
        self.signal_ttl_seconds = signal_ttl_seconds

        self._active_signals: list[LeaderFollowerSignal] = []
        self._vectorizer: Optional[object] = None  # TfidfVectorizer after fit

        logger.info(
            "SemanticLeaderFollower initialised: min_sim=%.2f min_move=%.2f "
            "max_pairs=%d embedding_dim=%d lookback=%d",
            min_similarity,
            min_price_change,
            max_pairs,
            embedding_dim,
            lookback_window,
        )

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _normalise_question(self, text: str) -> str:
        """Lower-case, strip punctuation, collapse whitespace."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _tfidf_embed(self, questions: list[str]) -> np.ndarray:
        """Fit (or use cached) TF-IDF vectorizer and return dense embedding matrix."""
        normalised = [self._normalise_question(q) for q in questions]

        if _SKLEARN_AVAILABLE:
            if self._vectorizer is None:
                self._vectorizer = TfidfVectorizer(
                    max_features=self.embedding_dim,
                    sublinear_tf=True,
                    ngram_range=(1, 2),
                )
                matrix = self._vectorizer.fit_transform(normalised)
            else:
                matrix = self._vectorizer.transform(normalised)  # type: ignore[attr-defined]

            # toarray() for scipy sparse; already dense for mock
            if hasattr(matrix, "toarray"):
                return matrix.toarray().astype(np.float32)
            return np.asarray(matrix, dtype=np.float32)

        # ------------------------------------------------------------------
        # Fallback: bag-of-words with IDF weighting (no sklearn)
        # ------------------------------------------------------------------
        return self._bow_embed(normalised)

    def _bow_embed(self, normalised: list[str]) -> np.ndarray:
        """Simple bag-of-words + IDF fallback when sklearn is unavailable."""
        tokenised = [q.split() for q in normalised]
        n_docs = len(tokenised)

        # Build vocabulary (up to embedding_dim most common terms)
        from collections import Counter

        all_tokens: list[str] = [t for toks in tokenised for t in toks]
        vocab_tokens = [t for t, _ in Counter(all_tokens).most_common(self.embedding_dim)]
        vocab = {t: i for i, t in enumerate(vocab_tokens)}
        dim = len(vocab)
        if dim == 0:
            return np.zeros((n_docs, 1), dtype=np.float32)

        # Document frequency for IDF
        df = np.zeros(dim, dtype=np.float32)
        for toks in tokenised:
            for t in set(toks):
                if t in vocab:
                    df[vocab[t]] += 1.0
        idf = np.log((n_docs + 1.0) / (df + 1.0)) + 1.0  # smooth IDF

        # TF * IDF
        matrix = np.zeros((n_docs, dim), dtype=np.float32)
        for i, toks in enumerate(tokenised):
            for t in toks:
                if t in vocab:
                    matrix[i, vocab[t]] += 1.0
            # TF normalisation (L1)
            row_sum = matrix[i].sum()
            if row_sum > 0:
                matrix[i] /= row_sum
        matrix *= idf
        return matrix

    def build_embeddings(self, markets: list[dict]) -> list[MarketEmbedding]:
        """
        Embed all market questions using TF-IDF vectorization.

        Parameters
        ----------
        markets:
            List of dicts with at least: market_id, question, current_price,
            volume_24h.  Optional keys: category, price_history,
            resolution_date.

        Returns
        -------
        List of MarketEmbedding objects, one per market.
        """
        if not markets:
            return []

        questions = [m.get("question", "") for m in markets]
        matrix = self._tfidf_embed(questions)

        embeddings: list[MarketEmbedding] = []
        for i, m in enumerate(markets):
            emb = MarketEmbedding(
                market_id=m.get("market_id", f"market_{i}"),
                question=m.get("question", ""),
                embedding=matrix[i].tolist(),
                category=m.get("category", "unknown"),
                current_price=float(m.get("current_price", 0.5)),
                price_history=list(m.get("price_history", [])),
                volume_24h=float(m.get("volume_24h", 0.0)),
                resolution_date=m.get("resolution_date", ""),
            )
            embeddings.append(emb)

        logger.debug("Built %d embeddings from %d markets", len(embeddings), len(markets))
        return embeddings

    # ------------------------------------------------------------------
    # Pair Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity_matrix(matrix: np.ndarray) -> np.ndarray:
        """Compute n×n cosine similarity matrix from row-stacked embeddings."""
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1e-10, norms)  # avoid division by zero
        normalised = matrix / norms
        return normalised @ normalised.T

    def discover_pairs(self, embeddings: list[MarketEmbedding]) -> list[MarketPair]:
        """
        Find semantically similar market pairs.

        Pairs are filtered by min_similarity, classified by relationship type,
        scored for directional correlation from price history, and returned
        sorted by similarity descending (capped at max_pairs).
        """
        if len(embeddings) < 2:
            return []

        matrix = np.array([e.embedding for e in embeddings], dtype=np.float32)
        sim_matrix = self._cosine_similarity_matrix(matrix)

        pairs: list[MarketPair] = []
        n = len(embeddings)

        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim < self.min_similarity:
                    continue

                emb_i, emb_j = embeddings[i], embeddings[j]
                rel_type = self._classify_relationship(
                    emb_i.question, emb_j.question, sim
                )

                # Determine lead-lag direction from price history
                hist_i = emb_i.price_history[-self.lookback_window :]
                hist_j = emb_j.price_history[-self.lookback_window :]

                if len(hist_i) >= 4 and len(hist_j) >= 4:
                    lag, dir_corr = self._compute_lead_lag(hist_i, hist_j)
                    # Assign leader as the market whose history predicts
                    # the other; positive lag means i leads j
                    if lag >= 0:
                        leader, follower = emb_i, emb_j
                    else:
                        leader, follower = emb_j, emb_i
                        lag = -lag
                        dir_corr = dir_corr  # direction unchanged
                else:
                    # No price history: use i as leader by default
                    leader, follower = emb_i, emb_j
                    lag = 1.0
                    dir_corr = 0.5  # weakly positive, unknown

                confidence = min(1.0, sim * abs(dir_corr))

                pair = MarketPair(
                    leader=leader,
                    follower=follower,
                    similarity=sim,
                    relationship_type=rel_type,
                    historical_lead_lag=float(lag),
                    directional_correlation=float(dir_corr),
                    confidence=confidence,
                )
                pairs.append(pair)

        # Sort by similarity descending, cap at max_pairs
        pairs.sort(key=lambda p: p.similarity, reverse=True)
        pairs = pairs[: self.max_pairs]

        logger.info(
            "Discovered %d pairs from %d embeddings (min_sim=%.2f)",
            len(pairs),
            len(embeddings),
            self.min_similarity,
        )
        return pairs

    def _classify_relationship(self, q1: str, q2: str, similarity: float) -> str:
        """
        Classify the relationship between two market questions.

        Rules (applied in priority order):
        - similarity >= 0.85  → "same_event"
        - token containment >= 70%  → "conditional"
        - similarity 0.50 – 0.85  → "correlated"
        - similarity 0.40 – 0.50  → "causal"
        """
        if similarity >= 0.85:
            return "same_event"

        toks1 = set(self._normalise_question(q1).split())
        toks2 = set(self._normalise_question(q2).split())

        if toks1 and toks2:
            smaller, larger = (
                (toks1, toks2) if len(toks1) <= len(toks2) else (toks2, toks1)
            )
            overlap_ratio = len(smaller & larger) / max(len(smaller), 1)
            if overlap_ratio >= 0.70:
                return "conditional"

        if similarity >= 0.50:
            return "correlated"

        return "causal"

    # ------------------------------------------------------------------
    # Lead-Lag Computation
    # ------------------------------------------------------------------

    def _compute_lead_lag(
        self,
        leader_prices: list[float],
        follower_prices: list[float],
    ) -> tuple[float, float]:
        """
        Compute lead-lag relationship from price histories using
        cross-correlation.

        Returns
        -------
        (optimal_lag, correlation_at_lag)
            optimal_lag > 0 means leader_prices leads follower_prices.
            correlation_at_lag is the Pearson r at that lag.
        """
        n = min(len(leader_prices), len(follower_prices))
        if n < 4:
            return (1.0, 0.0)

        a = np.array(leader_prices[-n:], dtype=np.float64)
        b = np.array(follower_prices[-n:], dtype=np.float64)

        # Demean
        a = a - a.mean()
        b = b - b.mean()

        std_a = a.std()
        std_b = b.std()
        if std_a < 1e-10 or std_b < 1e-10:
            return (1.0, 0.0)

        # Compute cross-correlation via numpy (full mode)
        # xcorr[k] corresponds to lag = k - (n-1) in "full" mode
        xcorr = np.correlate(a, b, mode="full")
        lags = np.arange(-(n - 1), n)

        # Normalise to [-1, +1]
        xcorr = xcorr / (n * std_a * std_b)

        # Only consider lags in [-lookback/2, +lookback/2]
        max_lag = max(1, self.lookback_window // 2)
        mask = (lags >= -max_lag) & (lags <= max_lag)
        xcorr_masked = xcorr[mask]
        lags_masked = lags[mask]

        best_idx = int(np.argmax(np.abs(xcorr_masked)))
        optimal_lag = float(lags_masked[best_idx])
        correlation = float(xcorr_masked[best_idx])

        return (optimal_lag, correlation)

    # ------------------------------------------------------------------
    # Signal Detection
    # ------------------------------------------------------------------

    def detect_leader_move(
        self,
        pair: MarketPair,
        leader_price_new: float,
        leader_price_old: float,
    ) -> bool:
        """
        Return True if the leader has made a significant move.

        |price_new - price_old| >= min_price_change
        """
        return abs(leader_price_new - leader_price_old) >= self.min_price_change

    def generate_signals(
        self,
        pairs: list[MarketPair],
        current_prices: dict[str, float],
        previous_prices: dict[str, float],
    ) -> list[LeaderFollowerSignal]:
        """
        Scan all pairs for leader moves and generate follower signals.

        For each pair:
        1. Check if the leader moved >= min_price_change.
        2. Check the follower has NOT yet moved (opportunity window open).
           Follower is considered already-moved if its absolute change is
           >= 50% of the leader's absolute change.
        3. Predict follower direction based on directional_correlation.
        4. Compute signal_strength = similarity * |leader_move| * |dir_corr|.
        5. Emit signal if signal_strength >= min_signal_strength.

        Returns signals sorted by signal_strength descending.
        """
        now = time.time()
        signals: list[LeaderFollowerSignal] = []

        for pair in pairs:
            lid = pair.leader.market_id
            fid = pair.follower.market_id

            l_new = current_prices.get(lid)
            l_old = previous_prices.get(lid)
            f_new = current_prices.get(fid)
            f_old = previous_prices.get(fid)

            if None in (l_new, l_old, f_new, f_old):
                continue

            l_new = float(l_new)  # type: ignore[arg-type]
            l_old = float(l_old)  # type: ignore[arg-type]
            f_new = float(f_new)  # type: ignore[arg-type]
            f_old = float(f_old)  # type: ignore[arg-type]

            leader_move = l_new - l_old
            if abs(leader_move) < self.min_price_change:
                continue  # Leader hasn't moved enough

            follower_move = abs(f_new - f_old)
            if follower_move >= 0.5 * abs(leader_move):
                # Follower already reacted — window closed
                continue

            # Predict direction
            dir_corr = pair.directional_correlation
            if dir_corr >= 0:
                predicted_direction = "up" if leader_move > 0 else "down"
            else:
                predicted_direction = "down" if leader_move > 0 else "up"

            predicted_magnitude = abs(leader_move) * abs(dir_corr)

            signal_strength = pair.similarity * abs(leader_move) * abs(dir_corr)

            if signal_strength < self.min_signal_strength:
                continue

            # Determine recommended side
            if predicted_direction == "up":
                recommended_side = "BUY_YES"
            else:
                recommended_side = "BUY_NO"

            # Size proportional to signal strength, capped at max_position_usd
            raw_size = self.max_position_usd * min(1.0, signal_strength)
            recommended_size_usd = round(max(1.0, raw_size), 2)

            confidence = min(1.0, pair.confidence * abs(dir_corr))

            sig = LeaderFollowerSignal(
                leader_market_id=lid,
                leader_question=pair.leader.question,
                leader_price_change=leader_move,
                leader_direction="up" if leader_move > 0 else "down",
                follower_market_id=fid,
                follower_question=pair.follower.question,
                follower_current_price=f_new,
                predicted_direction=predicted_direction,
                predicted_magnitude=predicted_magnitude,
                confidence=confidence,
                pair_similarity=pair.similarity,
                signal_strength=signal_strength,
                recommended_side=recommended_side,
                recommended_size_usd=recommended_size_usd,
                generated_at=now,
                expires_at=now + self.signal_ttl_seconds,
            )
            signals.append(sig)

        signals.sort(key=lambda s: s.signal_strength, reverse=True)
        self._active_signals.extend(signals)

        if signals:
            logger.info(
                "Generated %d leader-follower signal(s); top strength=%.3f",
                len(signals),
                signals[0].signal_strength,
            )

        return signals

    # ------------------------------------------------------------------
    # Online Update
    # ------------------------------------------------------------------

    def update_pair_stats(
        self,
        pair: MarketPair,
        leader_moved: float,
        follower_moved: float,
    ) -> None:
        """
        Update directional_correlation and lead-lag stats with new
        observed data.  Uses a simple exponential moving average so the
        estimate adapts over time without requiring the full history.

        leader_moved and follower_moved are signed price changes.
        """
        pair.observed_leader_moves += 1

        if abs(leader_moved) < 1e-8:
            return  # No meaningful move to learn from

        # Observed directional agreement: +1 same, -1 inverse
        observed_dir = math.copysign(1.0, leader_moved * follower_moved) if follower_moved != 0 else 0.0

        # Update directional correlation via EMA (alpha = 1/n clipped to 0.1–0.5)
        alpha = max(0.1, min(0.5, 1.0 / max(1, pair.observed_leader_moves)))
        pair.directional_correlation = (
            (1.0 - alpha) * pair.directional_correlation + alpha * observed_dir
        )

        if abs(follower_moved) >= 0.5 * abs(leader_moved):
            pair.observed_follower_follows += 1

        # Refresh confidence from updated stats
        pair.confidence = min(1.0, pair.similarity * abs(pair.directional_correlation))

        logger.debug(
            "Updated pair %s→%s dir_corr=%.3f (alpha=%.2f)",
            pair.leader.market_id,
            pair.follower.market_id,
            pair.directional_correlation,
            alpha,
        )

    # ------------------------------------------------------------------
    # Active Signals & Diagnostics
    # ------------------------------------------------------------------

    def get_active_signals(self) -> list[LeaderFollowerSignal]:
        """Return signals that have not yet expired."""
        now = time.time()
        live = [
            s for s in self._active_signals
            if s.expires_at == 0.0 or s.expires_at > now
        ]
        self._active_signals = live  # prune expired
        return list(live)

    def get_pair_diagnostics(self) -> dict:
        """
        Return summary statistics for monitoring.

        Keys: total_pairs, avg_similarity, top_pairs (list of dicts),
        active_signals, cached_vectorizer.
        """
        return {
            "total_pairs": 0,  # Populated by caller who holds the pair list
            "avg_similarity": 0.0,
            "active_signals": len(self.get_active_signals()),
            "cached_vectorizer": self._vectorizer is not None,
        }

    def compute_pair_diagnostics(self, pairs: list[MarketPair]) -> dict:
        """Compute diagnostics given an explicit pair list."""
        if not pairs:
            return {
                "total_pairs": 0,
                "avg_similarity": 0.0,
                "top_pairs": [],
                "active_signals": len(self.get_active_signals()),
                "cached_vectorizer": self._vectorizer is not None,
            }

        avg_sim = float(np.mean([p.similarity for p in pairs]))
        top = sorted(pairs, key=lambda p: p.similarity, reverse=True)[:5]
        top_list = [
            {
                "leader": p.leader.market_id,
                "follower": p.follower.market_id,
                "similarity": round(p.similarity, 4),
                "relationship_type": p.relationship_type,
                "directional_correlation": round(p.directional_correlation, 4),
            }
            for p in top
        ]

        return {
            "total_pairs": len(pairs),
            "avg_similarity": round(avg_sim, 4),
            "top_pairs": top_list,
            "active_signals": len(self.get_active_signals()),
            "cached_vectorizer": self._vectorizer is not None,
        }

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_alert(self, signal: LeaderFollowerSignal) -> str:
        """Format signal as a Telegram-ready plain-text alert."""
        arrow = "↑" if signal.predicted_direction == "up" else "↓"
        lines = [
            "LEADER-FOLLOWER SIGNAL",
            f"Leader:   {signal.leader_question[:60]}",
            f"  moved {signal.leader_price_change:+.1%} ({signal.leader_direction})",
            f"Follower: {signal.follower_question[:60]}",
            f"  current {signal.follower_current_price:.2f} → predicted {arrow} "
            f"{signal.predicted_magnitude:.1%}",
            f"Side: {signal.recommended_side}  Size: ${signal.recommended_size_usd:.2f}",
            f"Strength: {signal.signal_strength:.3f}  "
            f"Similarity: {signal.pair_similarity:.3f}  "
            f"Confidence: {signal.confidence:.3f}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience Factory
# ---------------------------------------------------------------------------


def btc_price_ladder_pairs(markets: list[dict]) -> SemanticLeaderFollower:
    """
    Pre-configured SemanticLeaderFollower for BTC price-level markets.

    BTC price ladder markets (e.g. "BTC above $85k", "BTC above $90k",
    "BTC above $95k") have natural ordering and predictable propagation:
    when the $85k market moves, the $90k market should follow.

    Returns a SemanticLeaderFollower tuned for tight semantic similarity
    and fast reaction windows.
    """
    engine = SemanticLeaderFollower(
        min_similarity=0.55,      # BTC price questions are very similar textually
        min_price_change=0.04,    # 4% leader move triggers search
        min_signal_strength=0.25, # Looser — ladder pairs are reliable
        max_pairs=200,
        embedding_dim=100,
        lookback_window=10,       # Shorter window; BTC moves fast
        max_position_usd=10.0,
        signal_ttl_seconds=180.0, # 3 min; ladder opportunities are short-lived
    )
    logger.info(
        "btc_price_ladder_pairs: initialised with %d markets",
        len(markets),
    )
    return engine
