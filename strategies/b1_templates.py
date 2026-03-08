"""High-precision template matcher for the initial B-1 dependency scope."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from strategies.b1_dependency_graph import MarketMeta


_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_COMPOSITE_RE = re.compile(
    r"will\s+(?P<actor>.+?)\s+(?P<verb>win|wins|control|controls)\s+both\s+(?P<first>.+?)\s+and\s+(?P<second>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_WIN_MARGIN_RE = re.compile(
    r"will\s+(?P<actor>.+?)\s+win(?:\s+[^?]*)?\s+by\s+(?:more than|at least|over)?\s*(?P<threshold>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_WINNER_RE = re.compile(r"will\s+(?P<actor>.+?)\s+win(?:\s+[^?]*)?(?:\?|$)", re.IGNORECASE)
_STATE_RE = re.compile(
    r"\b(alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|"
    r"illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
    r"mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|"
    r"north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|"
    r"tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    lowered = (text or "").lower().strip()
    lowered = _NON_ALNUM_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", lowered).strip()


@dataclass(frozen=True)
class TemplateDescriptor:
    family: str
    actor: str | None
    context: str
    threshold: float | None
    components: tuple[str, ...]
    raw_question: str


@dataclass(frozen=True)
class TemplateCompatibility:
    family: str
    label: str
    left_market_id: str
    right_market_id: str
    matrix: dict[str, bool]
    rationale: str


def describe_market(market: MarketMeta) -> TemplateDescriptor | None:
    question = market.question or ""
    normalized = _normalize(question)

    composite = _COMPOSITE_RE.search(question)
    if composite:
        actor = _normalize(composite.group("actor"))
        verb = _normalize(composite.group("verb"))
        first = _normalize(composite.group("first"))
        second = _normalize(composite.group("second"))
        family = "wins_both_composite"
        if "popular vote" in first or "popular vote" in second or "electoral college" in first or "electoral college" in second:
            family = "winner_popular_vote_ec"
        elif "house" in first or "senate" in first or "congress" in first or "house" in second or "senate" in second or "congress" in second:
            family = "winner_balance_of_power"
        components = (
            _normalize(f"{actor} {verb} {first}"),
            _normalize(f"{actor} {verb} {second}"),
        )
        return TemplateDescriptor(
            family=family,
            actor=actor,
            context=_normalize(f"{actor} {verb}"),
            threshold=None,
            components=components,
            raw_question=question,
        )

    winner_margin = _WIN_MARGIN_RE.search(question)
    if winner_margin:
        actor = _normalize(winner_margin.group("actor"))
        context = actor
        state_match = _STATE_RE.search(question)
        family = "state_winner_margin" if state_match else "winner_margin"
        if state_match:
            context = _normalize(f"{actor} {state_match.group(0)}")
        return TemplateDescriptor(
            family=family,
            actor=actor,
            context=context,
            threshold=float(winner_margin.group("threshold")),
            components=tuple(),
            raw_question=question,
        )

    winner = _WINNER_RE.search(question)
    if winner:
        actor = _normalize(winner.group("actor"))
        context = actor
        state_match = _STATE_RE.search(question)
        family = "state_winner_margin" if state_match else "winner_margin"
        if state_match:
            context = _normalize(f"{actor} {state_match.group(0)}")
        return TemplateDescriptor(
            family=family,
            actor=actor,
            context=context,
            threshold=None,
            components=tuple(),
            raw_question=question,
        )

    if "popular vote" in normalized or "electoral college" in normalized:
        return TemplateDescriptor(
            family="winner_popular_vote_ec",
            actor=None,
            context=normalized,
            threshold=None,
            components=tuple(),
            raw_question=question,
        )

    if "senate" in normalized or "house" in normalized or "congress" in normalized:
        return TemplateDescriptor(
            family="winner_balance_of_power",
            actor=None,
            context=normalized,
            threshold=None,
            components=tuple(),
            raw_question=question,
        )

    return None


def infer_pair_compatibility(left: MarketMeta, right: MarketMeta) -> TemplateCompatibility | None:
    left_desc = describe_market(left)
    right_desc = describe_market(right)
    if left_desc is None or right_desc is None:
        return None

    compatibility = _winner_margin_compatibility(left, right, left_desc, right_desc)
    if compatibility is not None:
        return compatibility

    compatibility = _composite_compatibility(left, right, left_desc, right_desc)
    if compatibility is not None:
        return compatibility

    return None


def build_templated_pairs(markets: Iterable[MarketMeta]) -> list[TemplateCompatibility]:
    market_list = list(markets)
    pairs: list[TemplateCompatibility] = []
    seen: set[tuple[str, str]] = set()
    for idx, left in enumerate(market_list):
        for right in market_list[idx + 1 :]:
            compatibility = infer_pair_compatibility(left, right)
            if compatibility is None:
                continue
            key = tuple(sorted((compatibility.left_market_id, compatibility.right_market_id)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append(compatibility)
    return pairs


def _winner_margin_compatibility(
    left: MarketMeta,
    right: MarketMeta,
    left_desc: TemplateDescriptor,
    right_desc: TemplateDescriptor,
) -> TemplateCompatibility | None:
    families = {left_desc.family, right_desc.family}
    if not families <= {"winner_margin", "state_winner_margin"}:
        return None
    if left_desc.context != right_desc.context:
        return None
    if left_desc.threshold is None and right_desc.threshold is None:
        return None

    if left_desc.threshold is None:
        label = "B_implies_A"
        rationale = "Winning by a threshold implies winning outright."
        matrix = {"YY": True, "YN": True, "NY": False, "NN": True}
    elif right_desc.threshold is None:
        label = "A_implies_B"
        rationale = "Winning by a threshold implies winning outright."
        matrix = {"YY": True, "YN": False, "NY": True, "NN": True}
    else:
        if abs(left_desc.threshold - right_desc.threshold) < 1e-9:
            return None
        if left_desc.threshold > right_desc.threshold:
            label = "A_implies_B"
            rationale = "A higher winning-margin threshold implies the lower one."
            matrix = {"YY": True, "YN": False, "NY": True, "NN": True}
        else:
            label = "B_implies_A"
            rationale = "A higher winning-margin threshold implies the lower one."
            matrix = {"YY": True, "YN": True, "NY": False, "NN": True}

    return TemplateCompatibility(
        family=left_desc.family if left_desc.family == right_desc.family else "winner_margin",
        label=label,
        left_market_id=left.market_id,
        right_market_id=right.market_id,
        matrix=matrix,
        rationale=rationale,
    )


def _composite_compatibility(
    left: MarketMeta,
    right: MarketMeta,
    left_desc: TemplateDescriptor,
    right_desc: TemplateDescriptor,
) -> TemplateCompatibility | None:
    if left_desc.components:
        right_norm = _normalize(right.question)
        if any(component in right_norm for component in left_desc.components):
            return TemplateCompatibility(
                family=left_desc.family,
                label="A_implies_B",
                left_market_id=left.market_id,
                right_market_id=right.market_id,
                matrix={"YY": True, "YN": False, "NY": True, "NN": True},
                rationale="The composite market resolving YES forces the component market to resolve YES.",
            )
    if right_desc.components:
        left_norm = _normalize(left.question)
        if any(component in left_norm for component in right_desc.components):
            return TemplateCompatibility(
                family=right_desc.family,
                label="B_implies_A",
                left_market_id=left.market_id,
                right_market_id=right.market_id,
                matrix={"YY": True, "YN": True, "NY": False, "NN": True},
                rationale="The composite market resolving YES forces the component market to resolve YES.",
            )
    return None
