"""Deterministic local embeddings for semantic niche matching."""

from __future__ import annotations

import hashlib
import math
import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def build_embedding(text: str, dimensions: int = 768) -> tuple[float, ...]:
    """Create a deterministic hash embedding without external ML services."""
    dims = max(8, int(dimensions))
    vector = [0.0] * dims
    tokens = TOKEN_PATTERN.findall(str(text or "").lower())
    if not tokens:
        return tuple(vector)

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        sign = -1.0 if digest[4] & 1 else 1.0
        weight = 1.0 + min(len(token), 12) / 12.0
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return tuple(vector)
    return tuple(round(value / norm, 6) for value in vector)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimension mismatch.")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    return round(dot / (left_norm * right_norm), 6)
