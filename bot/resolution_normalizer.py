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
    (re.compile(r"court filing|court docket|court order|court record", re.IGNORECASE), "court"),
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
_CATCH_ALL_RE = re.compile(
    r"^\s*(other|all other|any other|everyone else|someone else|rest of field|the field|field|none of the above)\s*$",
    re.IGNORECASE,
)
_OFFICE_TERMS = {
    "president",
    "presidency",
    "governor",
    "governorship",
    "mayor",
    "mayoral",
    "senate",
    "senator",
    "senate seat",
    "house",
    "representative",
    "speaker",
    "prime minister",
    "minister",
    "chancellor",
    "attorney general",
    "secretary of state",
    "supreme court",
}
_KNOWN_GEOS = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
    "united states", "usa", "us", "u s", "uk", "united kingdom",
    "canada", "mexico", "france", "germany", "italy", "spain", "poland",
    "ukraine", "russia", "china", "taiwan", "japan", "india", "israel",
    "gaza", "iran", "turkey", "europe", "eu", "european union",
}
_DATEISH_TERMS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "today", "tomorrow",
    "yesterday",
}
_QUESTION_GENERIC_TERMS = _STOPWORDS | {
    "who", "what", "when", "where", "which", "wins", "win", "won", "will",
    "market", "race", "election", "candidate", "party", "office", "vote",
    "votes", "seat", "seats", "above", "below", "under", "over", "than",
}
_BINARY_ONTOLOGY = ("no", "yes")
_HARD_BLOCK_REASONS = {
    "source_mismatch",
    "cutoff_mismatch",
    "scope_mismatch",
    "geography_mismatch",
    "office_mismatch",
    "event_identity_mismatch",
    "ontology_mismatch",
    "ontology_kind_mismatch",
    "named_outcome_mapping_ambiguous",
    "augmented_outcome_blocked",
    "augmented_other_bucket_present",
    "augmented_placeholder_outcome_present",
    "augmented_catch_all_bucket_present",
    "augmented_named_outcome_missing",
}


@dataclass(frozen=True)
class ResolutionProfile:
    source: str
    cutoff_ts: int | None
    scope_fingerprint: tuple[str, ...]
    geography_scope: tuple[str, ...]
    office_scope: tuple[str, ...]
    event_identity: tuple[str, ...]
    ontology: tuple[str, ...]
    named_outcomes: tuple[str, ...]
    outcome_kind: str
    is_neg_risk: bool
    is_augmented_neg_risk: bool
    has_other_outcome: bool
    has_placeholder_outcome: bool
    has_catch_all_outcome: bool
    has_ambiguous_named_mapping: bool


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
    yes_token_id: str | None
    no_token_id: str | None
    tick_size: float
    min_order_size: float
    accepting_orders: bool
    enable_order_book: bool
    profile: ResolutionProfile
    resolution_key: str


@dataclass(frozen=True)
class ResolutionGateResult:
    passed: bool
    semantic_penalty: float
    reasons: tuple[str, ...]
    safety_status: str = "hard_blocked"


@dataclass(frozen=True)
class EventTradability:
    event_id: str
    status: str
    reasons: tuple[str, ...]
    named_outcomes: tuple[str, ...]
    tradable_outcomes: tuple[str, ...]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def is_catch_all_outcome(outcome: str) -> bool:
    return bool(_CATCH_ALL_RE.match(outcome.strip()))


def is_placeholder_outcome(outcome: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(outcome))


def is_named_outcome(outcome: str) -> bool:
    out = normalize_outcome_name(outcome)
    if not out:
        return False
    return not is_other_outcome(out) and not is_placeholder_outcome(out) and not is_catch_all_outcome(out)


def selected_outcome_for_market(market: NormalizedMarket) -> str:
    if market.outcome:
        return market.outcome
    if market.outcomes:
        return market.outcomes[0]
    return ""


def outcome_block_reasons(market: NormalizedMarket, outcome: str) -> tuple[str, ...]:
    out = normalize_outcome_name(outcome)
    if not out:
        return ("outcome_label_missing",)
    if market.profile.is_augmented_neg_risk:
        if is_other_outcome(out):
            return ("augmented_other_outcome_selected",)
        if is_placeholder_outcome(out):
            return ("augmented_placeholder_outcome_selected",)
        if is_catch_all_outcome(out):
            return ("augmented_catch_all_outcome_selected",)
        if not is_named_outcome(out):
            return ("augmented_named_outcome_required",)
    return tuple()


def is_tradable_outcome(market: NormalizedMarket, outcome: str) -> bool:
    """Apply Polymarket augmented neg-risk safety rule for basket legs."""
    return not outcome_block_reasons(market, outcome)


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


def _parse_clob_token_ids(raw: Any) -> tuple[str | None, str | None]:
    values: list[str] = []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None, None
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = [part.strip() for part in stripped.split(",") if part.strip()]
        if isinstance(decoded, list):
            values = [str(item).strip() for item in decoded if str(item).strip()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    if len(values) < 2:
        return None, None
    return values[0], values[1]


def _extract_office_scope(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    found = [office for office in sorted(_OFFICE_TERMS) if office in lowered]
    return tuple(found)


def _extract_geography_scope(text: str) -> tuple[str, ...]:
    lowered = _norm_text(text)
    matches = {geo for geo in _KNOWN_GEOS if geo in lowered}
    return tuple(sorted(matches))


def _extract_event_identity(question: str, outcomes: Sequence[str]) -> tuple[str, ...]:
    outcome_terms = {
        token
        for outcome in outcomes
        for token in normalize_outcome_name(outcome).split()
    }
    anchors = [
        token
        for token in _norm_text(question).split()
        if token
        and token not in _QUESTION_GENERIC_TERMS
        and token not in outcome_terms
        and token not in _DATEISH_TERMS
    ]
    if not anchors:
        return tuple()
    return tuple(sorted(set(anchors[:16])))


def _outcome_kind(ontology: Sequence[str], named_outcomes: Sequence[str]) -> str:
    ontology_tuple = tuple(sorted(set(ontology)))
    if ontology_tuple == _BINARY_ONTOLOGY:
        return "binary"
    if named_outcomes:
        return "named"
    if ontology_tuple:
        return "categorical"
    return "unknown"


def _has_ambiguous_named_mapping(named_outcomes: Sequence[str]) -> bool:
    normalized = [normalize_outcome_name(outcome) for outcome in named_outcomes if normalize_outcome_name(outcome)]
    return len(normalized) != len(set(normalized))


def _compare_named_outcome_mapping(markets: Sequence[NormalizedMarket]) -> tuple[str, ...]:
    if not markets:
        return tuple()

    named_ontologies = [
        tuple(sorted(market.profile.named_outcomes))
        for market in markets
        if market.profile.outcome_kind == "named"
    ]
    if not named_ontologies:
        return tuple()

    base = named_ontologies[0]
    for ontology in named_ontologies[1:]:
        if ontology != base:
            return ("named_outcome_mapping_ambiguous",)
    return tuple()


def _finalize_gate_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


def _classify_gate(reasons: Sequence[str]) -> str:
    unique = set(reasons)
    if not unique:
        return "tradable"
    if unique & _HARD_BLOCK_REASONS:
        return "hard_blocked"
    return "log_only"


def extract_resolution_profile(
    raw: Mapping[str, Any],
    *,
    question: str,
    outcomes: Sequence[str],
    resolution_text: str,
) -> ResolutionProfile:
    ontology = tuple(sorted(normalize_outcome_name(o) for o in outcomes if normalize_outcome_name(o)))
    named_outcomes = tuple(
        sorted(
            normalize_outcome_name(o)
            for o in outcomes
            if is_named_outcome(o)
        )
    )
    neg_risk = _as_bool(raw.get("negRisk") or raw.get("neg_risk"))
    augmented = _as_bool(raw.get("negRiskAugmented") or raw.get("neg_risk_augmented"))
    has_other = any(is_other_outcome(o) for o in ontology)
    has_placeholder = any(is_placeholder_outcome(o) for o in ontology)
    has_catch_all = any(is_catch_all_outcome(o) for o in ontology)
    question_scope = f"{question}\n{resolution_text}".strip()

    return ResolutionProfile(
        source=infer_resolution_source(resolution_text),
        cutoff_ts=parse_cutoff_timestamp(resolution_text),
        scope_fingerprint=_tokenize_scope(question_scope, max_tokens=18),
        geography_scope=_extract_geography_scope(question_scope),
        office_scope=_extract_office_scope(question_scope),
        event_identity=_extract_event_identity(question, outcomes),
        ontology=ontology,
        named_outcomes=named_outcomes,
        outcome_kind=_outcome_kind(ontology, named_outcomes),
        is_neg_risk=neg_risk,
        is_augmented_neg_risk=augmented,
        has_other_outcome=has_other,
        has_placeholder_outcome=has_placeholder,
        has_catch_all_outcome=has_catch_all,
        has_ambiguous_named_mapping=_has_ambiguous_named_mapping(named_outcomes),
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
    yes_token_id, no_token_id = _parse_clob_token_ids(raw.get("clobTokenIds"))

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
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        tick_size=max(0.001, _as_float(raw.get("orderPriceMinTickSize"), 0.01)),
        min_order_size=max(0.0, _as_float(raw.get("orderMinSize"), 0.0)),
        accepting_orders=_as_bool(raw.get("acceptingOrders", True)),
        enable_order_book=_as_bool(raw.get("enableOrderBook", True)),
        profile=profile,
        resolution_key=_resolution_key(event_id, profile),
    )


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    s1, s2 = set(left), set(right)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def _scope_conflict(left: Sequence[str], right: Sequence[str], reason: str) -> tuple[str, ...]:
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return tuple()
    if left_set != right_set:
        return (reason,)
    return tuple()


def resolution_equivalence_gate(
    markets: Sequence[NormalizedMarket],
    *,
    selected_outcomes: Mapping[str, str] | None = None,
    cutoff_tolerance_hours: int = 24,
) -> ResolutionGateResult:
    """Validate hard resolution equivalence constraints before adding graph edges."""
    if not markets:
        return ResolutionGateResult(False, 1.0, ("no_markets",), "hard_blocked")

    base = markets[0]
    reasons: list[str] = []
    penalty = 0.0

    for market in markets[1:]:
        if base.profile.source != market.profile.source:
            if "unknown" in {base.profile.source, market.profile.source}:
                penalty += 0.08
                reasons.append("source_uncertain")
            else:
                reasons.append("source_mismatch")

        b_cutoff, m_cutoff = base.profile.cutoff_ts, market.profile.cutoff_ts
        if b_cutoff and m_cutoff:
            delta_h = abs(b_cutoff - m_cutoff) / 3600.0
            if delta_h > cutoff_tolerance_hours:
                reasons.append("cutoff_mismatch")
        elif b_cutoff != m_cutoff:
            penalty += 0.06
            reasons.append("cutoff_uncertain")

        reasons.extend(_scope_conflict(base.profile.office_scope, market.profile.office_scope, "office_mismatch"))
        reasons.extend(
            _scope_conflict(base.profile.geography_scope, market.profile.geography_scope, "geography_mismatch")
        )

        scope_sim = _jaccard(base.profile.scope_fingerprint, market.profile.scope_fingerprint)
        # Within-event markets can differ by outcome label while still sharing identical resolution terms.
        if base.event_id != market.event_id and scope_sim < 0.55:
            reasons.append("scope_mismatch")

        if (
            base.profile.outcome_kind == "named"
            or market.profile.outcome_kind == "named"
        ) and base.event_id != market.event_id:
            reasons.append("event_identity_mismatch")

        if base.profile.outcome_kind != market.profile.outcome_kind:
            reasons.append("ontology_kind_mismatch")
        elif (
            base.profile.outcome_kind == "named"
            and base.profile.ontology
            and market.profile.ontology
            and set(base.profile.ontology) != set(market.profile.ontology)
        ):
            reasons.append("ontology_mismatch")

        identity_sim = _jaccard(base.profile.event_identity, market.profile.event_identity)
        if base.event_id != market.event_id and base.profile.event_identity and market.profile.event_identity and identity_sim < 0.35:
            reasons.append("event_identity_mismatch")

    selected_outcomes = selected_outcomes or {}
    for market in markets:
        if market.profile.is_augmented_neg_risk:
            if market.profile.has_other_outcome:
                reasons.append("augmented_other_bucket_present")
            if market.profile.has_placeholder_outcome:
                reasons.append("augmented_placeholder_outcome_present")
            if market.profile.has_catch_all_outcome:
                reasons.append("augmented_catch_all_bucket_present")
            if market.profile.has_ambiguous_named_mapping:
                reasons.append("named_outcome_mapping_ambiguous")

            selected = selected_outcomes.get(market.market_id) or selected_outcome_for_market(market)
            if not selected:
                reasons.append("augmented_named_outcome_missing")
            elif not is_tradable_outcome(market, selected):
                reasons.append("augmented_outcome_blocked")

    reasons.extend(_compare_named_outcome_mapping(markets))
    reasons = list(_finalize_gate_reasons(reasons))
    status = _classify_gate(reasons)

    if status == "hard_blocked":
        penalty = max(penalty, 0.35)
    elif status == "log_only":
        penalty = max(penalty, 0.18)

    return ResolutionGateResult(
        passed=status == "tradable",
        semantic_penalty=min(1.0, penalty),
        reasons=tuple(reasons),
        safety_status=status,
    )


def evaluate_event_tradability(markets: Sequence[NormalizedMarket]) -> EventTradability:
    if not markets:
        return EventTradability(
            event_id="unknown",
            status="hard_blocked",
            reasons=("no_markets",),
            named_outcomes=tuple(),
            tradable_outcomes=tuple(),
        )

    event_id = markets[0].event_id
    selected_outcomes = {
        market.market_id: selected_outcome_for_market(market)
        for market in markets
    }
    gate = resolution_equivalence_gate(markets, selected_outcomes=selected_outcomes)

    named_outcomes = tuple(
        sorted(
            {
                name
                for market in markets
                for name in market.profile.named_outcomes
            }
        )
    )
    tradable_outcomes = tuple(
        sorted(
            {
                normalize_outcome_name(selected)
                for market in markets
                for selected in [selected_outcome_for_market(market)]
                if selected and is_tradable_outcome(market, selected)
            }
        )
    )
    if gate.safety_status != "tradable":
        tradable_outcomes = tuple()

    return EventTradability(
        event_id=event_id,
        status=gate.safety_status,
        reasons=gate.reasons,
        named_outcomes=named_outcomes,
        tradable_outcomes=tradable_outcomes,
    )
