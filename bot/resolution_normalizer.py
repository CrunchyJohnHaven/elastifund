#!/usr/bin/env python3
"""Resolution normalization and equivalence gates for structural arbitrage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


_STOPWORDS = {
    "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "by", "with",
    "will", "be", "is", "are", "this", "that", "as", "at", "from", "if", "than",
}

_SOURCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"associated press|\bap\b", re.IGNORECASE), "ap"),
    (re.compile(r"decision desk|\bddhq\b", re.IGNORECASE), "ddhq"),
    (re.compile(r"election assistance commission|\beac\b", re.IGNORECASE), "eac"),
    (re.compile(r"nws|national weather service", re.IGNORECASE), "nws"),
    (re.compile(r"coinbase", re.IGNORECASE), "coinbase"),
    (re.compile(r"binance", re.IGNORECASE), "binance"),
    (re.compile(r"federal reserve|bls|bureau of labor statistics", re.IGNORECASE), "official_stats"),
    (re.compile(r"polymarket", re.IGNORECASE), "polymarket"),
    (re.compile(r"official results|official filing", re.IGNORECASE), "official_source"),
]

_ISO_DT = re.compile(
    r"\b(?P<y>20\d{2})-(?P<m>\d{2})-(?P<d>\d{2})(?:[ T](?P<h>\d{1,2}):(?P<mm>\d{2})(?::\d{2})?)?(?:Z| UTC)?\b",
    re.IGNORECASE,
)

_MONTH_DT = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)\s+"
    r"(?P<d>\d{1,2}),?\s+(?P<y>20\d{2})(?:\s+at\s+(?P<h>\d{1,2})(?::(?P<mm>\d{2}))?\s*(?P<ampm>am|pm)?)?",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(r"placeholder|to be announced|tbd|outcome\s*\d+", re.IGNORECASE)
_OTHER_RE = re.compile(r"^\s*other\s*$|^\s*all other\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ResolutionProfile:
    source: str
    cutoff_ts: int | None
    scope_fingerprint: tuple[str, ...]
    ontology: tuple[str, ...]
    is_neg_risk: bool
    is_augmented_neg_risk: bool
    has_other_outcome: bool


@dataclass(frozen=True)
class NormalizedMarket:
    market_id: str
    event_id: str
    question: str
    category: str
    outcomes: tuple[str, ...]
    outcome: str | None
    resolution_text: str
    is_multi_outcome: bool
    profile: ResolutionProfile
    resolution_key: str


@dataclass(frozen=True)
class ResolutionGateResult:
    passed: bool
    semantic_penalty: float
    reasons: tuple[str, ...]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _norm_text(value: str) -> str:
    txt = value.lower().strip()
    txt = re.sub(r"[^a-z0-9\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _tokenize_scope(text: str, max_tokens: int = 14) -> tuple[str, ...]:
    toks = [tok for tok in _norm_text(text).split() if tok and tok not in _STOPWORDS]
    if not toks:
        return tuple()
    return tuple(sorted(set(toks[:max_tokens])))


def _month_to_int(name: str) -> int:
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    return months[name.lower()]


def parse_cutoff_timestamp(text: str) -> int | None:
    """Extract a UTC cutoff timestamp from free-form resolution text."""
    if not text:
        return None

    iso = _ISO_DT.search(text)
    if iso:
        y = int(iso.group("y"))
        m = int(iso.group("m"))
        d = int(iso.group("d"))
        h = int(iso.group("h") or 23)
        mm = int(iso.group("mm") or 59)
        dt = datetime(y, m, d, h, mm, tzinfo=timezone.utc)
        return int(dt.timestamp())

    month = _MONTH_DT.search(text)
    if month:
        y = int(month.group("y"))
        m = _month_to_int(month.group("month"))
        d = int(month.group("d"))
        h = int(month.group("h") or 23)
        mm = int(month.group("mm") or 59)
        ampm = (month.group("ampm") or "").lower()
        if ampm == "pm" and h < 12:
            h += 12
        if ampm == "am" and h == 12:
            h = 0
        dt = datetime(y, m, d, h, mm, tzinfo=timezone.utc)
        return int(dt.timestamp())

    return None


def infer_resolution_source(text: str) -> str:
    """Infer canonical resolution source label from market text."""
    if not text:
        return "unknown"
    for pattern, source in _SOURCE_PATTERNS:
        if pattern.search(text):
            return source
    return "unknown"


def normalize_outcome_name(outcome: str) -> str:
    return _norm_text(outcome)


def is_other_outcome(outcome: str) -> bool:
    return bool(_OTHER_RE.match(outcome.strip()))


def is_placeholder_outcome(outcome: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(outcome))


def is_named_outcome(outcome: str) -> bool:
    out = normalize_outcome_name(outcome)
    if not out:
        return False
    return not is_other_outcome(out) and not is_placeholder_outcome(out)


def is_tradable_outcome(market: NormalizedMarket, outcome: str) -> bool:
    """Apply Polymarket augmented neg-risk safety rule for basket legs."""
    out = normalize_outcome_name(outcome)
    if market.profile.is_augmented_neg_risk:
        return is_named_outcome(out)
    return bool(out)


def _extract_outcomes(raw: Mapping[str, Any]) -> list[str]:
    outcomes = raw.get("outcomes")
    if isinstance(outcomes, str):
        try:
            decoded = json.loads(outcomes)
            if isinstance(decoded, list):
                outcomes = decoded
        except Exception:
            outcomes = [chunk.strip() for chunk in outcomes.split(",") if chunk.strip()]

    parsed: list[str] = []
    if isinstance(outcomes, list):
        for item in outcomes:
            if isinstance(item, str):
                parsed.append(item.strip())
            elif isinstance(item, Mapping):
                label = item.get("name") or item.get("label") or item.get("outcome")
                if isinstance(label, str) and label.strip():
                    parsed.append(label.strip())

    if not parsed:
        for key in ("outcomeName", "outcome", "title"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                parsed.append(val.strip())
                break

    return parsed


def _extract_event_id(raw: Mapping[str, Any], market_id: str) -> str:
    """Prefer explicit event identifiers, then Gamma `events[]`, then fallback."""
    direct = (
        raw.get("event_id")
        or raw.get("eventId")
        or raw.get("event_slug")
        or raw.get("eventSlug")
        or raw.get("series_slug")
        or raw.get("seriesSlug")
    )
    if direct:
        value = str(direct).strip()
        if value:
            return value

    events = raw.get("events")
    if isinstance(events, list) and events:
        first = events[0]
        if isinstance(first, Mapping):
            for key in ("id", "slug", "ticker"):
                value = first.get(key)
                if value:
                    v = str(value).strip()
                    if v:
                        return v
        elif isinstance(first, str):
            value = first.strip()
            if value:
                return value

    fallback = raw.get("questionID") or raw.get("questionId") or market_id
    return str(fallback).strip() or market_id


def _extract_primary_outcome(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("outcome") or raw.get("outcomeName")
    if isinstance(value, str):
        out = value.strip()
        if out:
            return out

    # For neg-risk groups, Gamma often sets outcome=None and stores label here.
    group_item_title = raw.get("groupItemTitle")
    if isinstance(group_item_title, str):
        out = re.sub(r"^[\s:\-–—]+", "", group_item_title).strip()
        if out:
            return out
    return None


def extract_resolution_profile(
    raw: Mapping[str, Any],
    *,
    question: str,
    outcomes: Sequence[str],
    resolution_text: str,
) -> ResolutionProfile:
    ontology = tuple(sorted(normalize_outcome_name(o) for o in outcomes if normalize_outcome_name(o)))
    neg_risk = _as_bool(raw.get("negRisk") or raw.get("neg_risk"))
    augmented = _as_bool(raw.get("negRiskAugmented") or raw.get("neg_risk_augmented"))
    has_other = any(is_other_outcome(o) for o in ontology)

    return ResolutionProfile(
        source=infer_resolution_source(resolution_text),
        cutoff_ts=parse_cutoff_timestamp(resolution_text),
        scope_fingerprint=_tokenize_scope(question),
        ontology=ontology,
        is_neg_risk=neg_risk,
        is_augmented_neg_risk=augmented,
        has_other_outcome=has_other,
    )


def _resolution_key(event_id: str, profile: ResolutionProfile) -> str:
    payload = "|".join(
        [
            event_id,
            profile.source,
            str(profile.cutoff_ts or ""),
            ",".join(profile.scope_fingerprint),
            ",".join(profile.ontology),
            "1" if profile.is_neg_risk else "0",
            "1" if profile.is_augmented_neg_risk else "0",
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def normalize_market(raw: Mapping[str, Any]) -> NormalizedMarket:
    """Normalize polymarket/gamma metadata into a resolution-aware object."""
    market_id = str(
        raw.get("market_id")
        or raw.get("id")
        or raw.get("conditionId")
        or raw.get("condition_id")
        or raw.get("slug")
        or ""
    )
    event_id = _extract_event_id(raw, market_id)
    question = str(raw.get("question") or raw.get("title") or raw.get("name") or "").strip()
    category = str(raw.get("category") or raw.get("eventCategory") or "unknown").strip().lower()
    outcomes = _extract_outcomes(raw)
    outcome = _extract_primary_outcome(raw)

    resolution_parts = [
        str(raw.get("resolutionSource") or ""),
        str(raw.get("resolveBy") or ""),
        str(raw.get("endDate") or raw.get("end_date") or ""),
        str(raw.get("rules") or raw.get("description") or ""),
    ]
    resolution_text = "\n".join(part for part in resolution_parts if part).strip()

    is_multi_outcome = _as_bool(raw.get("isMultiOutcome")) or len(outcomes) > 2

    profile = extract_resolution_profile(
        raw,
        question=question,
        outcomes=outcomes,
        resolution_text=resolution_text,
    )

    return NormalizedMarket(
        market_id=market_id,
        event_id=event_id,
        question=question,
        category=category,
        outcomes=tuple(outcomes),
        outcome=outcome,
        resolution_text=resolution_text,
        is_multi_outcome=is_multi_outcome,
        profile=profile,
        resolution_key=_resolution_key(event_id, profile),
    )


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    s1, s2 = set(left), set(right)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def resolution_equivalence_gate(
    markets: Sequence[NormalizedMarket],
    *,
    selected_outcomes: Mapping[str, str] | None = None,
    cutoff_tolerance_hours: int = 24,
) -> ResolutionGateResult:
    """Validate hard resolution equivalence constraints before adding graph edges."""
    if not markets:
        return ResolutionGateResult(False, 1.0, ("no_markets",))

    base = markets[0]
    reasons: list[str] = []
    penalty = 0.0
    passed = True

    for market in markets[1:]:
        if base.profile.source != market.profile.source:
            if "unknown" in {base.profile.source, market.profile.source}:
                penalty += 0.08
                reasons.append("source_uncertain")
            else:
                passed = False
                reasons.append("source_mismatch")

        b_cutoff, m_cutoff = base.profile.cutoff_ts, market.profile.cutoff_ts
        if b_cutoff and m_cutoff:
            delta_h = abs(b_cutoff - m_cutoff) / 3600.0
            if delta_h > cutoff_tolerance_hours:
                passed = False
                reasons.append("cutoff_mismatch")
        elif b_cutoff != m_cutoff:
            penalty += 0.06
            reasons.append("cutoff_uncertain")

        if base.profile.ontology and market.profile.ontology:
            if set(base.profile.ontology) != set(market.profile.ontology):
                passed = False
                reasons.append("ontology_mismatch")

        scope_sim = _jaccard(base.profile.scope_fingerprint, market.profile.scope_fingerprint)
        # Within-event markets can differ by outcome label while still sharing identical resolution terms.
        if base.event_id != market.event_id and scope_sim < 0.55:
            passed = False
            reasons.append("scope_mismatch")

    selected_outcomes = selected_outcomes or {}
    for market in markets:
        if market.profile.is_augmented_neg_risk:
            selected = selected_outcomes.get(market.market_id) or market.outcome or ""
            if not selected or not is_tradable_outcome(market, selected):
                passed = False
                reasons.append("augmented_outcome_blocked")

    if not passed:
        penalty = max(penalty, 0.35)

    # Keep deterministic ordering while preserving detail.
    dedup_reasons = tuple(dict.fromkeys(reasons))
    return ResolutionGateResult(
        passed=passed,
        semantic_penalty=min(1.0, penalty),
        reasons=dedup_reasons,
    )
