"""Deterministic pruning for B-1 dependency graph candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence


_STOPWORDS = {
    "the", "will", "be", "a", "an", "and", "or", "of", "in", "on", "to", "by", "for", "if",
    "yes", "no", "market", "markets", "than", "with", "is", "are",
}


def _norm(text: str) -> str:
    value = re.sub(r"[^a-z0-9\s]", " ", str(text).lower())
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: str) -> set[str]:
    return {tok for tok in _norm(text).split() if tok and tok not in _STOPWORDS}


def _parse_tags(raw: Mapping[str, Any]) -> set[str]:
    tags = raw.get("tags") or raw.get("tag_ids") or raw.get("tagIds") or []
    out: set[str] = set()
    if isinstance(tags, str):
        tags = [chunk.strip() for chunk in tags.split(",") if chunk.strip()]
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, Mapping):
                value = item.get("id") or item.get("slug") or item.get("name")
            else:
                value = item
            if value is not None:
                out.add(str(value).strip().lower())
    return out


def _parse_end_date(raw: Mapping[str, Any]) -> datetime | None:
    value = raw.get("endDate") or raw.get("end_date")
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _slug(raw: Mapping[str, Any]) -> str:
    return str(raw.get("slug") or raw.get("event_slug") or raw.get("eventSlug") or "").strip().lower()


def _score_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    left_q = str(left.get("question") or left.get("title") or "")
    right_q = str(right.get("question") or right.get("title") or "")
    left_tokens = _tokens(left_q)
    right_tokens = _tokens(right_q)
    token_overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens) or 1
    lexical_score = token_overlap / union

    left_tags = _parse_tags(left)
    right_tags = _parse_tags(right)
    tag_overlap = len(left_tags & right_tags)

    slug_score = 1.0 if _slug(left) and _slug(left) == _slug(right) else 0.0
    score = lexical_score + (0.35 if tag_overlap else 0.0) + (0.25 * slug_score)
    return score, {
        "lexical_score": lexical_score,
        "token_overlap": token_overlap,
        "tag_overlap": tag_overlap,
        "slug_match": bool(slug_score),
    }


@dataclass(frozen=True)
class CandidatePair:
    a_market: dict[str, Any]
    b_market: dict[str, Any]
    score: float
    features: dict[str, Any]


class DepCandidatePairGenerator:
    """Cheap, cacheable reduction from N^2 to N*K."""

    def __init__(
        self,
        *,
        top_k: int = 30,
        resolution_window_days: int = 90,
        min_entity_overlap: int = 1,
        min_score: float = 0.12,
    ) -> None:
        self.top_k = max(1, int(top_k))
        self.resolution_window_days = max(1, int(resolution_window_days))
        self.min_entity_overlap = max(0, int(min_entity_overlap))
        self.min_score = float(min_score)

    def generate(self, markets: Sequence[Mapping[str, Any]]) -> list[CandidatePair]:
        rows = [dict(row) for row in markets if isinstance(row, Mapping)]
        ranked_by_market: dict[str, list[CandidatePair]] = {}

        for idx, left in enumerate(rows):
            left_id = str(left.get("id") or left.get("market_id") or "")
            if not left_id:
                continue
            for right in rows[idx + 1 :]:
                if not self._basic_filter(left, right):
                    continue
                score, features = _score_pair(left, right)
                if features["token_overlap"] < self.min_entity_overlap and features["tag_overlap"] == 0 and not features["slug_match"]:
                    continue
                if score < self.min_score:
                    continue
                pair = CandidatePair(a_market=dict(left), b_market=dict(right), score=score, features=features)
                ranked_by_market.setdefault(left_id, []).append(pair)
                right_id = str(right.get("id") or right.get("market_id") or "")
                if right_id:
                    ranked_by_market.setdefault(right_id, []).append(pair)

        out: list[CandidatePair] = []
        seen: set[tuple[str, str]] = set()
        for market_id, pairs in ranked_by_market.items():
            del market_id
            pairs.sort(key=lambda item: item.score, reverse=True)
            for pair in pairs[: self.top_k]:
                key = tuple(
                    sorted(
                        (
                            str(pair.a_market.get("id") or pair.a_market.get("market_id") or ""),
                            str(pair.b_market.get("id") or pair.b_market.get("market_id") or ""),
                        )
                    )
                )
                if key in seen:
                    continue
                seen.add(key)
                out.append(pair)

        out.sort(key=lambda item: item.score, reverse=True)
        return out

    def _basic_filter(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        left_cat = str(left.get("category") or left.get("eventCategory") or "").strip().lower()
        right_cat = str(right.get("category") or right.get("eventCategory") or "").strip().lower()
        if left_cat and right_cat and left_cat != right_cat:
            left_tags = _parse_tags(left)
            right_tags = _parse_tags(right)
            if not (left_tags & right_tags):
                return False

        left_end = _parse_end_date(left)
        right_end = _parse_end_date(right)
        if left_end is not None and right_end is not None:
            delta_days = abs((left_end - right_end).total_seconds()) / 86400.0
            if delta_days > self.resolution_window_days:
                return False
        return True
