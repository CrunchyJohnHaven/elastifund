#!/usr/bin/env python3
"""
Reflexion Memory — Episodic trade reflection storage and retrieval for JJ.
===========================================================================
Implements episodic memory for trade reflections, inspired by the Reflexion
paper (noahshinn/reflexion). After every resolved trade, the system generates
a natural-language self-critique and stores it. Before making future
probability estimates, the most relevant past reflections are retrieved by
semantic similarity via TF-IDF cosine distance.

Architecture:
  - TradeReflection: dataclass for a single episodic memory unit
  - ReflexionMemory: SQLite-backed store with TF-IDF retrieval

Storage layout:
  Table `reflections` — all fields, embedding as JSON list
  Table `vectorizer_state` — pickled TF-IDF vocabulary and IDF weights

Usage:
  mem = ReflexionMemory("reflexion_memory.db")
  r = mem.generate_reflection("t-001", "BTC UP 5m?", 0.62, 0.55, True, 1.20)
  mem.store_reflection(r)
  similar = mem.retrieve_similar("BTC 5 minute directional", top_k=3)
  prompt_ctx = mem.get_context_prompt("Will BTC go up in next 5 minutes?")

March 2026 — Elastifund / JJ
"""

from __future__ import annotations

import json
import logging
import math
import pickle
import re
import sqlite3
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from bot import elastic_client
except ImportError:
    try:
        import elastic_client  # type: ignore[no-redef]
    except ImportError:
        elastic_client = None  # type: ignore[assignment]

logger = logging.getLogger("JJ.reflexion_memory")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TradeReflection:
    trade_id: str
    market_id: str
    market_question: str
    predicted_prob: float
    market_price: float
    outcome: bool            # True = YES won, False = NO won
    pnl: float
    reflection_text: str
    embedding: list[float]
    timestamp: float         # Unix timestamp
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TF-IDF helpers (no external model dependency)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall can cannot in on at to for "
    "of and or but not with this that it its by from as if then than "
    "i we you he she they our your his her their what how when where why "
    "up or down go goes going".split()
)


def _tokenize(text: str) -> list[str]:
    """Lower-case, strip punctuation, remove stop-words, return token list."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


class _TFIDFVectorizer:
    """
    Minimal streaming TF-IDF vectorizer that can serialize/deserialize its
    vocabulary state as a plain dict (JSON-safe) or as a pickle blob.

    Vocabulary is built incrementally: each call to `fit_transform` or `fit`
    adds new terms. `transform` only uses known vocabulary.
    """

    def __init__(self) -> None:
        self.vocab: dict[str, int] = {}          # term → column index
        self.idf: dict[str, float] = {}          # term → idf weight
        self._doc_freq: dict[str, int] = {}      # term → document count
        self._n_docs: int = 0

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        state = {
            "vocab": self.vocab,
            "idf": self.idf,
            "_doc_freq": self._doc_freq,
            "_n_docs": self._n_docs,
        }
        return pickle.dumps(state)

    @classmethod
    def from_bytes(cls, data: bytes) -> "_TFIDFVectorizer":
        obj = cls()
        state = pickle.loads(data)  # noqa: S301
        obj.vocab = state["vocab"]
        obj.idf = state["idf"]
        obj._doc_freq = state["_doc_freq"]
        obj._n_docs = state["_n_docs"]
        return obj

    # ------------------------------------------------------------------
    # Core vectorizer interface
    # ------------------------------------------------------------------

    def _update_vocab(self, tokens: list[str]) -> None:
        for t in set(tokens):
            if t not in self.vocab:
                self.vocab[t] = len(self.vocab)
            self._doc_freq[t] = self._doc_freq.get(t, 0) + 1

    def _recompute_idf(self) -> None:
        n = max(self._n_docs, 1)
        for term, df in self._doc_freq.items():
            self.idf[term] = math.log((n + 1) / (df + 1)) + 1.0

    def fit(self, texts: list[str]) -> None:
        for text in texts:
            tokens = _tokenize(text)
            self._n_docs += 1
            self._update_vocab(tokens)
        self._recompute_idf()

    def partial_fit(self, text: str) -> None:
        tokens = _tokenize(text)
        self._n_docs += 1
        self._update_vocab(tokens)
        self._recompute_idf()

    def transform(self, text: str) -> list[float]:
        """Return a dense TF-IDF vector over the known vocabulary."""
        tokens = _tokenize(text)
        if not tokens or not self.vocab:
            return [0.0] * max(len(self.vocab), 1)
        tf = Counter(tokens)
        total = len(tokens)
        vec = [0.0] * len(self.vocab)
        for term, cnt in tf.items():
            if term in self.vocab:
                idx = self.vocab[term]
                tf_weight = cnt / total
                idf_weight = self.idf.get(term, 1.0)
                vec[idx] = tf_weight * idf_weight
        return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a < 1e-12 or mag_b < 1e-12:
        return 0.0
    return dot / (mag_a * mag_b)


def _pad_or_trim(vec: list[float], target_len: int) -> list[float]:
    """Extend with zeros or trim to match target dimensionality."""
    if len(vec) == target_len:
        return vec
    if len(vec) < target_len:
        return vec + [0.0] * (target_len - len(vec))
    return vec[:target_len]


# ---------------------------------------------------------------------------
# Reflection generation helpers
# ---------------------------------------------------------------------------

def _describe_tags(tags: list[str]) -> str:
    if not tags:
        return "no tags recorded"
    return ", ".join(tags)


def _generate_win_text(
    market_question: str,
    predicted_prob: float,
    market_price: float,
    outcome: bool,
    pnl: float,
    tags: list[str],
) -> str:
    outcome_str = "YES" if outcome else "NO"
    edge = round(predicted_prob - market_price, 4) if outcome else round((1.0 - predicted_prob) - (1.0 - market_price), 4)
    tag_summary = _describe_tags(tags)
    return (
        f"WIN on: {market_question}. "
        f"Predicted {predicted_prob:.3f}, market was {market_price:.3f}, outcome {outcome_str}. "
        f"Earned ${pnl:.2f}. "
        f"Edge at entry: {edge:+.3f}. "
        f"Context tags: {tag_summary}. "
        f"Lesson: edge estimate was accurate; monitor for similar tag combinations."
    )


def _generate_loss_text(
    market_question: str,
    predicted_prob: float,
    market_price: float,
    outcome: bool,
    pnl: float,
    tags: list[str],
) -> str:
    outcome_str = "YES" if outcome else "NO"
    overestimate = round(abs(predicted_prob - (1.0 if outcome else 0.0)), 4)
    tag_summary = _describe_tags(tags)
    return (
        f"LOSS on: {market_question}. "
        f"Predicted {predicted_prob:.3f} but outcome was {outcome_str}. "
        f"Overestimated by {overestimate:.3f}. "
        f"Lost ${abs(pnl):.2f}. "
        f"Contributing factors: {tag_summary}. "
        f"Lesson: review calibration assumptions for these tag combinations."
    )


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reflections (
    trade_id        TEXT PRIMARY KEY,
    market_id       TEXT NOT NULL,
    market_question TEXT NOT NULL,
    predicted_prob  REAL NOT NULL,
    market_price    REAL NOT NULL,
    outcome         INTEGER NOT NULL,
    pnl             REAL NOT NULL,
    reflection_text TEXT NOT NULL,
    embedding       TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    tags            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reflections_market_id
    ON reflections (market_id);

CREATE INDEX IF NOT EXISTS idx_reflections_timestamp
    ON reflections (timestamp);

CREATE TABLE IF NOT EXISTS vectorizer_state (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    blob    BLOB NOT NULL
);
"""


class ReflexionMemory:
    """
    Episodic memory for trade reflections.

    Stores structured self-critiques keyed by trade_id in SQLite. Retrieval
    is done by TF-IDF cosine similarity over reflection text, with the
    vectorizer state persisted in the same database.
    """

    def __init__(self, db_path: str = "reflexion_memory.db") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self._vectorizer = self._load_vectorizer()

    # ------------------------------------------------------------------
    # Schema / lifecycle
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._save_vectorizer()
        self._conn.close()

    def __enter__(self) -> "ReflexionMemory":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Vectorizer persistence
    # ------------------------------------------------------------------

    def _load_vectorizer(self) -> _TFIDFVectorizer:
        row = self._conn.execute(
            "SELECT blob FROM vectorizer_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return _TFIDFVectorizer()
        try:
            return _TFIDFVectorizer.from_bytes(bytes(row["blob"]))
        except Exception:
            logger.warning("Vectorizer state corrupt; starting fresh.")
            return _TFIDFVectorizer()

    def _save_vectorizer(self) -> None:
        blob = self._vectorizer.to_bytes()
        self._conn.execute(
            "INSERT OR REPLACE INTO vectorizer_state (id, blob) VALUES (1, ?)",
            (blob,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def _compute_embedding(self, text: str) -> list[float]:
        return self._vectorizer.transform(text)

    def _reembed_all(self) -> None:
        """Recompute embeddings for all rows after vocabulary changes."""
        rows = self._conn.execute(
            "SELECT trade_id, reflection_text FROM reflections"
        ).fetchall()
        for row in rows:
            new_emb = self._vectorizer.transform(row["reflection_text"])
            self._conn.execute(
                "UPDATE reflections SET embedding = ? WHERE trade_id = ?",
                (json.dumps(new_emb), row["trade_id"]),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_reflection(self, reflection: TradeReflection) -> None:
        """
        Persist a trade reflection. If a reflection with the same trade_id
        already exists it is replaced (upsert semantics).
        """
        # Update vectorizer with new text
        old_n_docs = self._vectorizer._n_docs
        self._vectorizer.partial_fit(reflection.reflection_text)

        vocab_grew = len(self._vectorizer.vocab) > len(reflection.embedding)
        if vocab_grew:
            # Re-embed all stored reflections at new dimensionality
            self._reembed_all()
            # Recompute embedding for the incoming reflection
            reflection = TradeReflection(
                trade_id=reflection.trade_id,
                market_id=reflection.market_id,
                market_question=reflection.market_question,
                predicted_prob=reflection.predicted_prob,
                market_price=reflection.market_price,
                outcome=reflection.outcome,
                pnl=reflection.pnl,
                reflection_text=reflection.reflection_text,
                embedding=self._vectorizer.transform(reflection.reflection_text),
                timestamp=reflection.timestamp,
                tags=reflection.tags,
            )
        else:
            # Existing vocab sufficient; just pad if needed
            target = len(self._vectorizer.vocab)
            padded = _pad_or_trim(reflection.embedding, target)
            reflection = TradeReflection(
                trade_id=reflection.trade_id,
                market_id=reflection.market_id,
                market_question=reflection.market_question,
                predicted_prob=reflection.predicted_prob,
                market_price=reflection.market_price,
                outcome=reflection.outcome,
                pnl=reflection.pnl,
                reflection_text=reflection.reflection_text,
                embedding=padded,
                timestamp=reflection.timestamp,
                tags=reflection.tags,
            )

        self._conn.execute(
            """
            INSERT OR REPLACE INTO reflections
                (trade_id, market_id, market_question, predicted_prob,
                 market_price, outcome, pnl, reflection_text, embedding,
                 timestamp, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reflection.trade_id,
                reflection.market_id,
                reflection.market_question,
                float(reflection.predicted_prob),
                float(reflection.market_price),
                1 if reflection.outcome else 0,
                float(reflection.pnl),
                reflection.reflection_text,
                json.dumps(reflection.embedding),
                float(reflection.timestamp),
                json.dumps(reflection.tags),
            ),
        )
        self._conn.commit()
        self._save_vectorizer()

        logger.debug(
            "Stored reflection trade_id=%s market_id=%s pnl=%.4f",
            reflection.trade_id,
            reflection.market_id,
            reflection.pnl,
        )

        # Telemetry (best-effort)
        if elastic_client is not None:
            try:
                elastic_client.index_signal(
                    {
                        "event": "reflexion_memory.store",
                        "trade_id": reflection.trade_id,
                        "market_id": reflection.market_id,
                        "pnl": reflection.pnl,
                        "outcome": reflection.outcome,
                        "timestamp": reflection.timestamp,
                    }
                )
            except Exception:
                pass

    def retrieve_similar(
        self,
        query_text: str,
        top_k: int = 5,
        min_similarity: float = 0.1,
    ) -> list[TradeReflection]:
        """
        Return up to top_k reflections most similar to query_text,
        filtered by min_similarity threshold.
        """
        rows = self._conn.execute(
            "SELECT * FROM reflections ORDER BY timestamp DESC"
        ).fetchall()

        if not rows:
            return []

        vocab_size = len(self._vectorizer.vocab)
        if vocab_size == 0:
            return []

        query_vec = self._vectorizer.transform(query_text)

        scored: list[tuple[float, TradeReflection]] = []
        for row in rows:
            try:
                stored_emb: list[float] = json.loads(row["embedding"])
            except (json.JSONDecodeError, TypeError):
                stored_emb = []

            # Align dimensionality
            stored_emb = _pad_or_trim(stored_emb, vocab_size)
            q_vec = _pad_or_trim(query_vec, vocab_size)

            sim = _cosine_similarity(q_vec, stored_emb)
            if sim >= min_similarity:
                scored.append((sim, _row_to_reflection(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def generate_reflection(
        self,
        trade_id: str,
        market_question: str,
        predicted_prob: float,
        market_price: float,
        outcome: bool,
        pnl: float,
        tags: list[str] | None = None,
        market_id: str | None = None,
    ) -> TradeReflection:
        """
        Generate a structured TradeReflection from raw trade outcome data.

        This produces a templated self-critique. For LLM-generated critiques,
        pass the text in externally and call store_reflection directly.
        """
        effective_tags: list[str] = tags or []
        effective_market_id: str = market_id or f"unknown-{uuid.uuid4().hex[:8]}"

        if pnl >= 0.0:
            text = _generate_win_text(
                market_question, predicted_prob, market_price,
                outcome, pnl, effective_tags,
            )
        else:
            text = _generate_loss_text(
                market_question, predicted_prob, market_price,
                outcome, pnl, effective_tags,
            )

        # Compute embedding with current vectorizer (will be updated on store)
        self._vectorizer.partial_fit(text)
        embedding = self._vectorizer.transform(text)

        return TradeReflection(
            trade_id=trade_id,
            market_id=effective_market_id,
            market_question=market_question,
            predicted_prob=float(predicted_prob),
            market_price=float(market_price),
            outcome=outcome,
            pnl=float(pnl),
            reflection_text=text,
            embedding=embedding,
            timestamp=time.time(),
            tags=effective_tags,
        )

    def get_context_prompt(
        self,
        current_market_question: str,
        top_k: int = 5,
    ) -> str:
        """
        Return a formatted string of relevant past reflections suitable for
        injection into an LLM probability estimation prompt.

        Returns an empty string if no relevant reflections exist.
        """
        similar = self.retrieve_similar(current_market_question, top_k=top_k)
        if not similar:
            return ""

        lines: list[str] = [
            "### Relevant past trade reflections (most similar first):",
            "",
        ]
        for i, r in enumerate(similar, start=1):
            outcome_str = "YES" if r.outcome else "NO"
            tag_str = ", ".join(r.tags) if r.tags else "none"
            lines.append(
                f"{i}. [{outcome_str} | PnL: ${r.pnl:+.2f} | pred: {r.predicted_prob:.3f} | "
                f"price: {r.market_price:.3f} | tags: {tag_str}]"
            )
            lines.append(f"   Q: {r.market_question}")
            lines.append(f"   Reflection: {r.reflection_text}")
            lines.append("")

        lines.append(
            "Use these reflections to calibrate your probability estimate. "
            "Pay attention to recurring patterns in wins and losses."
        )
        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        """
        Return summary statistics over all stored reflections:
          total, win_count, loss_count, win_rate, avg_pnl, total_pnl,
          avg_predicted_prob, avg_market_price, most_common_tags.
        """
        rows = self._conn.execute(
            "SELECT outcome, pnl, predicted_prob, market_price, tags FROM reflections"
        ).fetchall()

        if not rows:
            return {
                "total": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "total_pnl": 0.0,
                "avg_predicted_prob": 0.0,
                "avg_market_price": 0.0,
                "most_common_tags": [],
            }

        wins = [r for r in rows if r["outcome"] == 1]
        losses = [r for r in rows if r["outcome"] == 0]
        total = len(rows)
        pnls = [r["pnl"] for r in rows]
        preds = [r["predicted_prob"] for r in rows]
        prices = [r["market_price"] for r in rows]

        tag_counter: Counter[str] = Counter()
        for r in rows:
            try:
                tag_list: list[str] = json.loads(r["tags"])
                tag_counter.update(tag_list)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "total": total,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": len(wins) / total if total > 0 else 0.0,
            "avg_pnl": sum(pnls) / total,
            "total_pnl": sum(pnls),
            "avg_predicted_prob": sum(preds) / total,
            "avg_market_price": sum(prices) / total,
            "most_common_tags": tag_counter.most_common(10),
        }


# ---------------------------------------------------------------------------
# Row conversion helper
# ---------------------------------------------------------------------------

def _row_to_reflection(row: sqlite3.Row) -> TradeReflection:
    try:
        embedding: list[float] = json.loads(row["embedding"])
    except (json.JSONDecodeError, TypeError):
        embedding = []
    try:
        tags: list[str] = json.loads(row["tags"])
    except (json.JSONDecodeError, TypeError):
        tags = []
    return TradeReflection(
        trade_id=row["trade_id"],
        market_id=row["market_id"],
        market_question=row["market_question"],
        predicted_prob=float(row["predicted_prob"]),
        market_price=float(row["market_price"]),
        outcome=bool(row["outcome"]),
        pnl=float(row["pnl"]),
        reflection_text=row["reflection_text"],
        embedding=embedding,
        timestamp=float(row["timestamp"]),
        tags=tags,
    )
