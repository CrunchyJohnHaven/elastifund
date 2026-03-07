#!/usr/bin/env python3
"""Deterministic template engine for narrow B-1 dependency families."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

try:
    from bot.resolution_normalizer import NormalizedMarket
except ImportError:  # pragma: no cover - direct script mode
    from resolution_normalizer import NormalizedMarket  # type: ignore


_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
}

_MARGIN_RE = re.compile(r"\bby\s+\d+(?:\.\d+)?\s+(?:point|points|pct|%)|\bmargin\b", re.IGNORECASE)
_WIN_RE = re.compile(r"\bwin\b|\bwins\b|\bwinner\b", re.IGNORECASE)
_BOTH_RE = re.compile(r"\bboth\b|\band\b", re.IGNORECASE)
_POPULAR_VOTE_RE = re.compile(r"popular vote", re.IGNORECASE)
_ELECTORAL_COLLEGE_RE = re.compile(r"electoral college", re.IGNORECASE)
_HOUSE_RE = re.compile(r"\bhouse\b", re.IGNORECASE)
_SENATE_RE = re.compile(r"\bsenate\b", re.IGNORECASE)


@dataclass(frozen=True)
class TemplateMatch:
    family: str
    relation_type: str
    confidence: float
    compatibility_matrix: dict[str, bool]
    rationale: str


def compatibility_matrix_for_relation(relation_type: str) -> dict[str, bool]:
    if relation_type == "A_implies_B":
        return {"YY": True, "YN": False, "NY": True, "NN": True}
    if relation_type == "B_implies_A":
        return {"YY": True, "YN": True, "NY": False, "NN": True}
    if relation_type == "mutually_exclusive":
        return {"YY": False, "YN": True, "NY": True, "NN": True}
    if relation_type == "complementary":
        return {"YY": False, "YN": True, "NY": True, "NN": False}
    return {"YY": True, "YN": True, "NY": True, "NN": True}


def _norm_question(market: NormalizedMarket) -> str:
    return re.sub(r"\s+", " ", market.question.lower()).strip()


def _extract_geo(text: str) -> str | None:
    for state in sorted(_STATE_NAMES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(state)}\b", text):
            return state
    return None


def _subject_tokens(text: str) -> set[str]:
    tokens = {
        token
        for token in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
        if token not in {
            "will", "the", "a", "an", "of", "for", "by", "in", "both", "and", "party",
            "win", "wins", "winner", "vote", "popular", "electoral", "college",
            "house", "senate", "state", "margin", "control",
        }
    }
    return tokens


def _same_subject(left: str, right: str) -> bool:
    left_tokens = _subject_tokens(left)
    right_tokens = _subject_tokens(right)
    return bool(left_tokens and right_tokens and (left_tokens & right_tokens))


def _has_margin(text: str) -> bool:
    return bool(_MARGIN_RE.search(text))


def _has_winner(text: str) -> bool:
    return bool(_WIN_RE.search(text))


def _is_pop_vote_ec_composite(text: str) -> bool:
    return bool(_POPULAR_VOTE_RE.search(text) and _ELECTORAL_COLLEGE_RE.search(text) and _BOTH_RE.search(text))


def _is_balance_of_power_composite(text: str) -> bool:
    return bool(_HOUSE_RE.search(text) and _SENATE_RE.search(text) and _BOTH_RE.search(text))


def match_template_pair(market_a: NormalizedMarket, market_b: NormalizedMarket) -> TemplateMatch | None:
    left = _norm_question(market_a)
    right = _norm_question(market_b)
    same_geo = _extract_geo(left) == _extract_geo(right)
    same_subject = _same_subject(left, right)

    if same_subject and same_geo and _has_margin(left) and _has_winner(right):
        return TemplateMatch(
            family="state_winner_margin",
            relation_type="A_implies_B",
            confidence=0.95,
            compatibility_matrix=compatibility_matrix_for_relation("A_implies_B"),
            rationale="State margin market implies the same candidate wins the state.",
        )
    if same_subject and same_geo and _has_winner(left) and _has_margin(right):
        return TemplateMatch(
            family="state_winner_margin",
            relation_type="B_implies_A",
            confidence=0.95,
            compatibility_matrix=compatibility_matrix_for_relation("B_implies_A"),
            rationale="State margin market implies the same candidate wins the state.",
        )
    if same_subject and _has_margin(left) and _has_winner(right):
        return TemplateMatch(
            family="winner_margin",
            relation_type="A_implies_B",
            confidence=0.92,
            compatibility_matrix=compatibility_matrix_for_relation("A_implies_B"),
            rationale="Candidate margin market implies the same candidate wins.",
        )
    if same_subject and _has_winner(left) and _has_margin(right):
        return TemplateMatch(
            family="winner_margin",
            relation_type="B_implies_A",
            confidence=0.92,
            compatibility_matrix=compatibility_matrix_for_relation("B_implies_A"),
            rationale="Candidate margin market implies the same candidate wins.",
        )
    if _is_pop_vote_ec_composite(left) and (_POPULAR_VOTE_RE.search(right) or _ELECTORAL_COLLEGE_RE.search(right)):
        return TemplateMatch(
            family="winner_popular_vote_ec",
            relation_type="A_implies_B",
            confidence=0.94,
            compatibility_matrix=compatibility_matrix_for_relation("A_implies_B"),
            rationale="Composite popular-vote/electoral-college market implies each component.",
        )
    if _is_pop_vote_ec_composite(right) and (_POPULAR_VOTE_RE.search(left) or _ELECTORAL_COLLEGE_RE.search(left)):
        return TemplateMatch(
            family="winner_popular_vote_ec",
            relation_type="B_implies_A",
            confidence=0.94,
            compatibility_matrix=compatibility_matrix_for_relation("B_implies_A"),
            rationale="Composite popular-vote/electoral-college market implies each component.",
        )
    if _is_balance_of_power_composite(left) and (_HOUSE_RE.search(right) or _SENATE_RE.search(right)):
        return TemplateMatch(
            family="winner_balance_of_power",
            relation_type="A_implies_B",
            confidence=0.93,
            compatibility_matrix=compatibility_matrix_for_relation("A_implies_B"),
            rationale="Balance-of-power composite implies the underlying chamber control market.",
        )
    if _is_balance_of_power_composite(right) and (_HOUSE_RE.search(left) or _SENATE_RE.search(left)):
        return TemplateMatch(
            family="winner_balance_of_power",
            relation_type="B_implies_A",
            confidence=0.93,
            compatibility_matrix=compatibility_matrix_for_relation("B_implies_A"),
            rationale="Balance-of-power composite implies the underlying chamber control market.",
        )
    if same_subject and "both" in left and _has_winner(right):
        return TemplateMatch(
            family="wins_both_composite",
            relation_type="A_implies_B",
            confidence=0.90,
            compatibility_matrix=compatibility_matrix_for_relation("A_implies_B"),
            rationale="A wins-both composite implies its component winner market.",
        )
    if same_subject and "both" in right and _has_winner(left):
        return TemplateMatch(
            family="wins_both_composite",
            relation_type="B_implies_A",
            confidence=0.90,
            compatibility_matrix=compatibility_matrix_for_relation("B_implies_A"),
            rationale="A wins-both composite implies its component winner market.",
        )
    return None


def filter_template_candidates(markets: Sequence[NormalizedMarket]) -> list[tuple[NormalizedMarket, NormalizedMarket, TemplateMatch]]:
    candidates: list[tuple[NormalizedMarket, NormalizedMarket, TemplateMatch]] = []
    ordered = list(markets)
    for idx, market_a in enumerate(ordered):
        for market_b in ordered[idx + 1:]:
            match = match_template_pair(market_a, market_b)
            if match is None:
                continue
            candidates.append((market_a, market_b, match))
    return candidates
