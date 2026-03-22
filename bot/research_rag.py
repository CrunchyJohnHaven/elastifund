#!/usr/bin/env python3
"""
Research RAG — Retrieval-Augmented Generation over Dispatch Archive
====================================================================
Indexes the project's 95+ research dispatch files using TF-IDF
vectorization and cosine similarity. Retrieves the top-k most relevant
dispatch chunks to enrich LLM probability estimation context.

No external vector DB required. No GPU. scikit-learn TfidfVectorizer
with a pure-Python fallback for environments where sklearn is absent.

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine_similarity
    import numpy as np
    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SKLEARN_AVAILABLE = False
    TfidfVectorizer = None
    sk_cosine_similarity = None
    np = None

logger = logging.getLogger("JJ.research_rag")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DispatchChunk:
    dispatch_id: str          # e.g. "DISPATCH_102"
    file_path: str            # Relative path to the dispatch file
    title: str                # First heading or filename
    content: str              # Full text content of this chunk
    chunk_index: int          # Which chunk within the parent file
    embedding: dict           # TF-IDF vector stored as {term: weight} dict
    metadata: dict            # Extracted metadata (date, strategy, etc.)


@dataclass
class RetrievalResult:
    chunk: DispatchChunk
    similarity: float         # Cosine similarity score [0, 1]
    snippet: str              # Most relevant 200-char excerpt


# ---------------------------------------------------------------------------
# Pure-Python fallback (no sklearn)
# ---------------------------------------------------------------------------

class _BagOfWordsVectorizer:
    """
    Minimal TF-IDF replacement used when sklearn is not available.
    Implements term frequency weighting with IDF dampening.
    """

    def __init__(self, max_features: int = 5000):
        self.max_features = max_features
        self._vocab: dict[str, int] = {}
        self._idf: list[float] = []
        self._fitted = False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def fit(self, corpus: list[str]) -> "_BagOfWordsVectorizer":
        n_docs = len(corpus)
        df: dict[str, int] = {}
        for doc in corpus:
            for tok in set(self._tokenize(doc)):
                df[tok] = df.get(tok, 0) + 1

        # Sort by DF descending, keep max_features
        sorted_terms = sorted(df.items(), key=lambda x: x[1], reverse=True)
        top_terms = sorted_terms[: self.max_features]
        self._vocab = {t: i for i, (t, _) in enumerate(top_terms)}
        self._idf = [
            math.log((1.0 + n_docs) / (1.0 + df.get(t, 0))) + 1.0
            for t, _ in top_terms
        ]
        self._fitted = True
        return self

    def transform(self, corpus: list[str]) -> list[list[float]]:
        """Return dense TF-IDF vectors."""
        result = []
        vocab_size = len(self._vocab)
        for doc in corpus:
            tokens = self._tokenize(doc)
            tf: dict[int, float] = {}
            for tok in tokens:
                idx = self._vocab.get(tok)
                if idx is not None:
                    tf[idx] = tf.get(idx, 0.0) + 1.0
            # Normalise TF
            n = len(tokens) or 1
            vec = [0.0] * vocab_size
            for idx, count in tf.items():
                vec[idx] = (count / n) * self._idf[idx]
            # L2 normalise
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            result.append([v / norm for v in vec])
        return result

    def fit_transform(self, corpus: list[str]) -> list[list[float]]:
        self.fit(corpus)
        return self.transform(corpus)

    def get_feature_names_out(self) -> list[str]:
        return [t for t, _ in sorted(self._vocab.items(), key=lambda x: x[1])]


def _dot_product(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cosine_similarity_fallback(
    query_vec: list[float], matrix: list[list[float]]
) -> list[float]:
    """Pure-Python cosine similarity of one query vector against a matrix."""
    q_norm = math.sqrt(_dot_product(query_vec, query_vec)) or 1.0
    scores = []
    for doc_vec in matrix:
        d_norm = math.sqrt(_dot_product(doc_vec, doc_vec)) or 1.0
        scores.append(_dot_product(query_vec, doc_vec) / (q_norm * d_norm))
    return scores


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------

_DISPATCH_PATTERN = re.compile(r"DISPATCH[_\s-]?(\d{3,})", re.IGNORECASE)
_DATE_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)
_STRATEGY_KEYWORDS = [
    "BTC5", "VPIN", "maker", "taker", "Kelly", "calibration",
    "ensemble", "arbitrage", "structural alpha", "lead-lag",
]


def _extract_metadata(text: str, filename: str) -> dict:
    """Pull dispatch IDs, dates, and strategy tags from raw text."""
    meta: dict[str, Any] = {}

    # Dispatch ID
    m = _DISPATCH_PATTERN.search(text) or _DISPATCH_PATTERN.search(filename)
    if m:
        meta["dispatch_id"] = f"DISPATCH_{m.group(1)}"

    # Dates (first occurrence)
    dm = _DATE_PATTERN.search(text)
    if dm:
        meta["date"] = dm.group(0)

    # Strategy tags
    tags = [kw for kw in _STRATEGY_KEYWORDS if kw.lower() in text.lower()]
    if tags:
        meta["strategy_tags"] = tags

    return meta


def _extract_title(text: str, filename: str) -> str:
    """Return first # heading, or cleaned filename."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    # Fallback: clean filename
    stem = Path(filename).stem
    return stem.replace("_", " ").replace("-", " ")


def _extract_dispatch_id(text: str, filename: str) -> str:
    """Best-effort dispatch ID from content or filename."""
    m = _DISPATCH_PATTERN.search(filename)
    if m:
        return f"DISPATCH_{m.group(1).lstrip('0') or '0'}"
    m = _DISPATCH_PATTERN.search(text[:500])
    if m:
        return f"DISPATCH_{m.group(1).lstrip('0') or '0'}"
    return Path(filename).stem.upper()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _split_into_chunks(
    text: str, chunk_size: int, overlap: int
) -> list[str]:
    """
    Split text into chunks of at most chunk_size characters.
    Attempts to respect paragraph boundaries; falls back to hard split.
    Consecutive chunks share `overlap` characters.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)

    current = ""
    for para in paragraphs:
        if not para.strip():
            continue
        candidate = (current + "\n\n" + para).strip() if current else para.strip()
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Para itself may be too large — hard split with overlap
            if len(para) > chunk_size:
                start = 0
                while start < len(para):
                    end = start + chunk_size
                    chunks.append(para[start:end])
                    start += chunk_size - overlap
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    # Apply overlap between adjacent chunks if not already handled
    if overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = overlapped[-1][-overlap:]
            overlapped.append((tail + chunks[i]) if tail else chunks[i])
        return overlapped

    return chunks


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ResearchRAG:
    """
    TF-IDF RAG index over Elastifund research dispatch files.

    Usage:
        rag = ResearchRAG()
        rag.build_index()
        results = rag.retrieve("BTC 5-minute maker strategy", top_k=5)
        context = rag.get_context_prompt("Will BTC be above 70k in 5 minutes?")
    """

    def __init__(
        self,
        dispatch_dir: str = "research/dispatches",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        max_features: int = 5000,
        cache_path: Optional[str] = None,
    ):
        self.dispatch_dir = dispatch_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_features = max_features
        self.cache_path = cache_path

        self._chunks: list[DispatchChunk] = []
        self._matrix: Any = None          # np.ndarray or list[list[float]]
        self._vectorizer: Any = None       # TfidfVectorizer or _BagOfWordsVectorizer
        self._built = False
        self._num_files = 0

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def build_index(self, directory: Optional[str] = None) -> int:
        """
        Scan directory for .md files, chunk them, compute TF-IDF vectors.
        Returns number of chunks indexed.
        """
        target = Path(directory) if directory else Path(self.dispatch_dir)
        if not target.exists():
            logger.warning("Dispatch directory not found: %s", target)
            self._built = True
            return 0

        md_files = sorted(target.glob("*.md"))
        logger.info("Indexing %d markdown files from %s", len(md_files), target)

        raw_texts: list[str] = []
        proto_chunks: list[dict] = []
        self._num_files = 0

        for md_file in md_files:
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("Could not read %s: %s", md_file, exc)
                continue

            self._num_files += 1
            title = _extract_title(text, md_file.name)
            dispatch_id = _extract_dispatch_id(text, md_file.name)
            metadata = _extract_metadata(text, md_file.name)
            metadata.setdefault("dispatch_id", dispatch_id)

            sub_chunks = _split_into_chunks(text, self.chunk_size, self.chunk_overlap)
            for idx, chunk_text in enumerate(sub_chunks):
                proto_chunks.append(
                    {
                        "dispatch_id": dispatch_id,
                        "file_path": str(md_file),
                        "title": title,
                        "content": chunk_text,
                        "chunk_index": idx,
                        "metadata": dict(metadata),
                    }
                )
                raw_texts.append(chunk_text)

        if not raw_texts:
            logger.info("No content to index.")
            self._built = True
            return 0

        # Fit vectorizer
        self._vectorizer = self._make_vectorizer()
        if _SKLEARN_AVAILABLE:
            self._matrix = self._vectorizer.fit_transform(raw_texts)
        else:
            dense = self._vectorizer.fit_transform(raw_texts)
            self._matrix = dense

        # Build DispatchChunk objects with sparse embedding dicts
        vocab = self._get_vocab()
        self._chunks = []
        for i, proto in enumerate(proto_chunks):
            embedding = self._vector_to_dict(i, vocab)
            self._chunks.append(
                DispatchChunk(
                    dispatch_id=proto["dispatch_id"],
                    file_path=proto["file_path"],
                    title=proto["title"],
                    content=proto["content"],
                    chunk_index=proto["chunk_index"],
                    embedding=embedding,
                    metadata=proto["metadata"],
                )
            )

        self._built = True
        logger.info(
            "Index built: %d files, %d chunks, vocab=%d",
            self._num_files,
            len(self._chunks),
            len(vocab),
        )
        return len(self._chunks)

    def _make_vectorizer(self):
        if _SKLEARN_AVAILABLE:
            return TfidfVectorizer(
                max_features=self.max_features,
                stop_words="english",
                sublinear_tf=True,
                ngram_range=(1, 2),
            )
        return _BagOfWordsVectorizer(max_features=self.max_features)

    def _get_vocab(self) -> list[str]:
        if _SKLEARN_AVAILABLE:
            return self._vectorizer.get_feature_names_out().tolist()
        return self._vectorizer.get_feature_names_out()

    def _vector_to_dict(self, chunk_idx: int, vocab: list[str]) -> dict:
        """Convert the stored vector for chunk_idx to a {term: weight} dict."""
        if _SKLEARN_AVAILABLE:
            row = self._matrix[chunk_idx]
            # sparse row
            cx = row.tocoo()
            return {vocab[j]: float(v) for j, v in zip(cx.col, cx.data) if v > 0}
        else:
            vec = self._matrix[chunk_idx]
            return {vocab[j]: v for j, v in enumerate(vec) if v > 0}

    def _query_vector(self, query: str):
        """Transform query text into a vector using the fitted vectorizer."""
        if _SKLEARN_AVAILABLE:
            return self._vectorizer.transform([query])
        return self._vectorizer.transform([query])

    def _compute_similarities(self, query_vec) -> list[float]:
        """Return cosine similarity scores for all indexed chunks."""
        if _SKLEARN_AVAILABLE:
            scores = sk_cosine_similarity(query_vec, self._matrix)
            return scores[0].tolist()
        return _cosine_similarity_fallback(query_vec[0], self._matrix)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.05,
    ) -> list[RetrievalResult]:
        """
        Retrieve the most relevant dispatch chunks for a query string.
        Returns up to top_k RetrievalResult objects above min_similarity.
        """
        if not self._built or not self._chunks:
            logger.warning("Index not built or empty. Call build_index() first.")
            return []

        query_vec = self._query_vector(query)
        scores = self._compute_similarities(query_vec)

        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )

        results: list[RetrievalResult] = []
        for idx, score in ranked:
            if score < min_similarity:
                break
            if len(results) >= top_k:
                break
            chunk = self._chunks[idx]
            snippet = _extract_snippet(chunk.content, query)
            results.append(
                RetrievalResult(chunk=chunk, similarity=float(score), snippet=snippet)
            )

        return results

    # ------------------------------------------------------------------
    # Context prompt generation
    # ------------------------------------------------------------------

    def get_context_prompt(
        self,
        market_question: str,
        top_k: int = 3,
        max_tokens: int = 2000,
    ) -> str:
        """
        Format retrieved dispatch chunks into an LLM-injectable context block.

        Respects max_tokens by truncating snippets if necessary.
        Approximates tokens as chars / 4.
        """
        results = self.retrieve(market_question, top_k=top_k)
        if not results:
            return ""

        max_chars = max_tokens * 4
        header = "--- Relevant Research Context ---\n"
        footer = "\n---"
        body_parts: list[str] = []
        chars_used = len(header) + len(footer)

        for r in results:
            entry_header = f"\n[{r.chunk.dispatch_id}] {r.chunk.title}:\n"
            snippet_text = f'"{r.snippet}"\n'
            entry = entry_header + snippet_text
            if chars_used + len(entry) > max_chars:
                # Truncate snippet to fit
                available = max_chars - chars_used - len(entry_header) - 5
                if available > 50:
                    truncated = r.snippet[:available] + "..."
                    entry = entry_header + f'"{truncated}"\n'
                else:
                    break
            body_parts.append(entry)
            chars_used += len(entry)

        if not body_parts:
            return ""

        return header + "".join(body_parts) + footer

    # ------------------------------------------------------------------
    # Incremental update
    # ------------------------------------------------------------------

    def update_index(self, file_path: str) -> None:
        """
        Add or update a single file in the index without full rebuild.

        Rebuilds the TF-IDF matrix to incorporate new vocabulary.
        If the file already has chunks, they are replaced.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning("update_index: file not found: %s", file_path)
            return

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("update_index: could not read %s: %s", file_path, exc)
            return

        title = _extract_title(text, path.name)
        dispatch_id = _extract_dispatch_id(text, path.name)
        metadata = _extract_metadata(text, path.name)
        metadata.setdefault("dispatch_id", dispatch_id)

        # Remove stale chunks for this file
        abs_str = str(path.resolve())
        self._chunks = [
            c for c in self._chunks
            if str(Path(c.file_path).resolve()) != abs_str
        ]

        # Add new chunks
        sub_chunks = _split_into_chunks(text, self.chunk_size, self.chunk_overlap)
        for idx, chunk_text in enumerate(sub_chunks):
            self._chunks.append(
                DispatchChunk(
                    dispatch_id=dispatch_id,
                    file_path=str(path),
                    title=title,
                    content=chunk_text,
                    chunk_index=idx,
                    embedding={},
                    metadata=dict(metadata),
                )
            )

        # Refit on all content
        all_texts = [c.content for c in self._chunks]
        if not all_texts:
            return

        self._vectorizer = self._make_vectorizer()
        if _SKLEARN_AVAILABLE:
            self._matrix = self._vectorizer.fit_transform(all_texts)
        else:
            self._matrix = self._vectorizer.fit_transform(all_texts)

        vocab = self._get_vocab()
        for i, chunk in enumerate(self._chunks):
            chunk.embedding = self._vector_to_dict(i, vocab)

        self._num_files = len({c.file_path for c in self._chunks})
        logger.info(
            "update_index: %s added/updated. Total chunks: %d",
            path.name,
            len(self._chunks),
        )

    # ------------------------------------------------------------------
    # Metadata search
    # ------------------------------------------------------------------

    def search_by_metadata(self, **kwargs) -> list[DispatchChunk]:
        """
        Filter chunks by metadata fields.

        Supported kwargs:
          dispatch_id (str)         — exact match
          date_contains (str)       — substring match on metadata['date']
          strategy_tag (str)        — membership in metadata['strategy_tags']
          title_contains (str)      — substring match on chunk.title (case-insensitive)
        """
        results = self._chunks[:]

        if "dispatch_id" in kwargs:
            did = kwargs["dispatch_id"].upper()
            results = [c for c in results if c.dispatch_id.upper() == did]

        if "date_contains" in kwargs:
            val = kwargs["date_contains"]
            results = [
                c for c in results if val in c.metadata.get("date", "")
            ]

        if "strategy_tag" in kwargs:
            tag = kwargs["strategy_tag"].lower()
            results = [
                c for c in results
                if tag in [t.lower() for t in c.metadata.get("strategy_tags", [])]
            ]

        if "title_contains" in kwargs:
            substr = kwargs["title_contains"].lower()
            results = [c for c in results if substr in c.title.lower()]

        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_index(self, path: str) -> None:
        """Persist the TF-IDF vectorizer and chunk data to disk (pickle)."""
        payload = {
            "chunks": self._chunks,
            "matrix": self._matrix,
            "vectorizer": self._vectorizer,
            "num_files": self._num_files,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "max_features": self.max_features,
            "saved_at": time.time(),
        }
        with open(path, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Index saved to %s (%d chunks)", path, len(self._chunks))

    def load_index(self, path: str) -> None:
        """Load a previously saved index from disk."""
        with open(path, "rb") as fh:
            payload = pickle.load(fh)
        self._chunks = payload["chunks"]
        self._matrix = payload["matrix"]
        self._vectorizer = payload["vectorizer"]
        self._num_files = payload.get("num_files", 0)
        self._built = True
        logger.info(
            "Index loaded from %s (%d chunks, %d files)",
            path,
            len(self._chunks),
            self._num_files,
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return index statistics."""
        vocab_size = 0
        if self._vectorizer is not None:
            try:
                vocab_size = len(self._get_vocab())
            except Exception:
                vocab_size = 0

        files = len({c.file_path for c in self._chunks}) if self._chunks else 0
        return {
            "num_files": files,
            "num_chunks": len(self._chunks),
            "vocab_size": vocab_size,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "max_features": self.max_features,
            "built": self._built,
            "backend": "sklearn" if _SKLEARN_AVAILABLE else "fallback",
        }


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------

def _extract_snippet(text: str, query: str, max_len: int = 200) -> str:
    """
    Find the sentence in `text` most relevant to `query` and return a
    snippet of up to max_len characters centred on it.
    """
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)

    best_score = -1
    best_sentence = ""
    best_offset = 0
    current_offset = 0

    for sent in sentences:
        sent_terms = set(re.findall(r"[a-z0-9]+", sent.lower()))
        score = len(query_terms & sent_terms)
        if score > best_score:
            best_score = score
            best_sentence = sent
            best_offset = current_offset
        current_offset += len(sent) + 1

    if not best_sentence:
        return text[:max_len].strip()

    # Expand context around best sentence up to max_len
    start = max(0, best_offset - (max_len - len(best_sentence)) // 2)
    end = start + max_len
    if end > len(text):
        end = len(text)
        start = max(0, end - max_len)

    snippet = text[start:end].strip()
    return snippet
