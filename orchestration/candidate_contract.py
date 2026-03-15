"""Canonical cross-venue candidate, routing, lifecycle, and attribution contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
import json
import random
from typing import Any, Mapping


class ThesisFamily(str, Enum):
    """Canonical thesis family labels across fast-flow and narrative lanes."""

    WALLET_FLOW = "wallet_flow"
    LMSR_GAP = "lmsr_gap"
    NARRATIVE_NO_BIAS = "narrative_no_bias"
    CROSS_VENUE = "cross_venue"
    STRUCTURAL = "structural"

    @classmethod
    def normalize(cls, value: str | None, *, default: "ThesisFamily") -> "ThesisFamily":
        normalized = str(value or default.value).strip().lower()
        aliases = {
            "wallet": cls.WALLET_FLOW,
            "walletflow": cls.WALLET_FLOW,
            "lmsr": cls.LMSR_GAP,
            "lmsr_gap": cls.LMSR_GAP,
            "narrative": cls.NARRATIVE_NO_BIAS,
            "narrative_no": cls.NARRATIVE_NO_BIAS,
            "crossvenue": cls.CROSS_VENUE,
            "cross_venue": cls.CROSS_VENUE,
            "structural_alpha": cls.STRUCTURAL,
        }
        candidate = aliases.get(normalized, normalized)
        for member in cls:
            if member.value == candidate:
                return member
        return default


class LifecycleState(str, Enum):
    """Canonical trade lifecycle states shared by paper/shadow/live traces."""

    DISCOVERED = "discovered"
    ROUTED = "routed"
    RESTING = "resting"
    FILLED = "filled"
    PARTIAL = "partial"
    EXPIRED = "expired"
    RESOLVED = "resolved"
    ATTRIBUTED = "attributed"


_ALLOWED_LIFECYCLE_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.DISCOVERED: {LifecycleState.ROUTED},
    LifecycleState.ROUTED: {LifecycleState.RESTING},
    LifecycleState.RESTING: {LifecycleState.FILLED, LifecycleState.PARTIAL, LifecycleState.EXPIRED},
    LifecycleState.PARTIAL: {LifecycleState.RESOLVED},
    LifecycleState.FILLED: {LifecycleState.RESOLVED},
    LifecycleState.EXPIRED: set(),
    LifecycleState.RESOLVED: {LifecycleState.ATTRIBUTED},
    LifecycleState.ATTRIBUTED: set(),
}


def is_valid_lifecycle_transition(
    previous_state: LifecycleState,
    next_state: LifecycleState,
) -> bool:
    return next_state in _ALLOWED_LIFECYCLE_TRANSITIONS.get(previous_state, set())


@dataclass(frozen=True)
class CandidateRecord:
    """Canonical venue-agnostic candidate schema."""

    venue: str
    market_id: str
    title: str
    ticker: str | None
    resolution_time: str | None
    thesis_family: ThesisFamily
    fair_probability: float
    market_probability: float
    fee_adjusted_edge: float
    fill_probability: float
    toxicity: float
    route_score: float
    route_score_inputs: dict[str, float] = field(default_factory=dict)
    data_quality_flags: list[str] = field(default_factory=list)
    narrative_heat: float | None = None
    yes_crowding: float | None = None
    base_rate_gap: float | None = None
    no_bias_prior: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", str(self.venue).strip().lower())
        object.__setattr__(self, "market_id", str(self.market_id).strip())
        object.__setattr__(self, "title", str(self.title).strip())
        object.__setattr__(self, "ticker", None if self.ticker is None else str(self.ticker).strip())
        object.__setattr__(
            self,
            "thesis_family",
            self.thesis_family
            if isinstance(self.thesis_family, ThesisFamily)
            else ThesisFamily.normalize(str(self.thesis_family), default=ThesisFamily.WALLET_FLOW),
        )
        object.__setattr__(self, "fair_probability", _clamp_01(self.fair_probability))
        object.__setattr__(self, "market_probability", _clamp_01(self.market_probability))
        object.__setattr__(self, "fee_adjusted_edge", float(self.fee_adjusted_edge))
        object.__setattr__(self, "fill_probability", _clamp_01(self.fill_probability))
        object.__setattr__(self, "toxicity", _clamp_01(self.toxicity))
        object.__setattr__(self, "route_score", float(self.route_score))
        object.__setattr__(self, "route_score_inputs", _normalize_float_mapping(self.route_score_inputs))
        object.__setattr__(
            self,
            "data_quality_flags",
            sorted({str(flag).strip() for flag in self.data_quality_flags if str(flag).strip()}),
        )
        object.__setattr__(self, "narrative_heat", _optional_clamp_01(self.narrative_heat))
        object.__setattr__(self, "yes_crowding", _optional_clamp_01(self.yes_crowding))
        object.__setattr__(self, "base_rate_gap", _optional_clamp_signed(self.base_rate_gap))
        object.__setattr__(self, "no_bias_prior", _optional_clamp_01(self.no_bias_prior))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def opportunity_key(self) -> str:
        ticker = self.ticker or "na"
        return f"{self.venue}:{ticker}:{self.market_id}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["thesis_family"] = self.thesis_family.value
        return payload


@dataclass(frozen=True)
class RouteDecision:
    """Allocator routing decision for one canonical candidate."""

    opportunity_key: str
    venue: str
    market_id: str
    accepted: bool
    reason: str
    route_score: float
    route_score_inputs: dict[str, float] = field(default_factory=dict)
    selected_notional_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeLifecycleEvent:
    """Lifecycle event for one routed opportunity."""

    event_ts: str
    state: LifecycleState
    venue: str
    market_id: str
    side: str
    quantity: float
    price: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", LifecycleState(self.state))
        object.__setattr__(self, "venue", str(self.venue).strip().lower())
        object.__setattr__(self, "market_id", str(self.market_id).strip())
        object.__setattr__(self, "side", str(self.side).strip().upper())
        object.__setattr__(self, "quantity", max(0.0, float(self.quantity)))
        object.__setattr__(self, "price", None if self.price is None else _clamp_01(self.price))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True)
class ClosedTradeAttribution:
    """Closed-trade attribution record for venue/thesis performance accounting."""

    trade_id: str
    venue: str
    market_id: str
    thesis_family: ThesisFamily
    expected_edge: float
    realized_spread: float
    fill_quality: float
    markout_5s: float
    markout_30s: float
    markout_2m: float
    shadow_live_divergence: float
    resolution_pnl: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", str(self.venue).strip().lower())
        object.__setattr__(self, "market_id", str(self.market_id).strip())
        object.__setattr__(
            self,
            "thesis_family",
            self.thesis_family
            if isinstance(self.thesis_family, ThesisFamily)
            else ThesisFamily.normalize(str(self.thesis_family), default=ThesisFamily.WALLET_FLOW),
        )
        object.__setattr__(self, "fill_quality", _clamp_01(self.fill_quality))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["thesis_family"] = self.thesis_family.value
        return payload


def compute_route_score(candidate: Mapping[str, Any]) -> tuple[float, dict[str, float]]:
    """Route-score formula: flow/microstructure terms dominate now; narrative is opt-in."""
    fee_adjusted_edge = float(candidate.get("fee_adjusted_edge", 0.0) or 0.0)
    fill_probability = _clamp_01(candidate.get("fill_probability", 0.0) or 0.0)
    toxicity = _clamp_01(candidate.get("toxicity", 1.0) or 1.0)
    wallet_consensus = _clamp_01(candidate.get("wallet_consensus_score", 0.0) or 0.0)
    lmsr_gap = _clamp_signed(candidate.get("lmsr_gap", 0.0) or 0.0)
    vpin = _clamp_01(candidate.get("vpin", 0.0) or 0.0)
    ofi = _clamp_signed(candidate.get("ofi", 0.0) or 0.0)
    spread_bps = max(0.0, float(candidate.get("spread_bps", 0.0) or 0.0))
    data_quality_penalty = -6.0 * len(candidate.get("data_quality_flags") or [])

    edge_term = 120.0 * fee_adjusted_edge
    fill_term = 25.0 * fill_probability
    toxicity_term = -20.0 * toxicity
    wallet_term = 14.0 * wallet_consensus
    lmsr_term = 10.0 * max(0.0, lmsr_gap)
    microstructure_term = 8.0 * max(0.0, ofi) - 8.0 * vpin - min(10.0, spread_bps / 4.0)

    narrative_terms_present = any(
        candidate.get(key) is not None
        for key in ("narrative_heat", "yes_crowding", "base_rate_gap", "no_bias_prior")
    )
    narrative_term = 0.0
    if narrative_terms_present:
        narrative_heat = _clamp_01(candidate.get("narrative_heat"))
        yes_crowding = _clamp_01(candidate.get("yes_crowding"))
        base_rate_gap = _clamp_signed(candidate.get("base_rate_gap"))
        no_bias_prior = _clamp_01(candidate.get("no_bias_prior"))
        narrative_term = (
            6.0 * narrative_heat
            + 4.0 * yes_crowding
            + 8.0 * max(0.0, -base_rate_gap)
            + 4.0 * no_bias_prior
        )

    score = (
        edge_term
        + fill_term
        + toxicity_term
        + wallet_term
        + lmsr_term
        + microstructure_term
        + narrative_term
        + data_quality_penalty
    )
    inputs = {
        "edge_term": round(edge_term, 6),
        "fill_term": round(fill_term, 6),
        "toxicity_term": round(toxicity_term, 6),
        "wallet_term": round(wallet_term, 6),
        "lmsr_term": round(lmsr_term, 6),
        "microstructure_term": round(microstructure_term, 6),
        "narrative_term": round(narrative_term, 6),
        "data_quality_penalty": round(data_quality_penalty, 6),
    }
    return round(score, 6), inputs


def normalize_candidate_record(
    raw: Mapping[str, Any],
    *,
    venue_hint: str,
    thesis_hint: ThesisFamily,
) -> CandidateRecord:
    """Normalize loosely structured venue payloads into CandidateRecord."""
    venue = str(raw.get("venue") or venue_hint).strip().lower()
    market_id = str(
        raw.get("market_id")
        or raw.get("id")
        or raw.get("condition_id")
        or raw.get("ticker")
        or raw.get("title")
        or "unknown-market"
    ).strip()
    title = str(raw.get("title") or raw.get("question") or market_id).strip()
    ticker = _optional_text(raw.get("ticker") or raw.get("slug"))
    resolution_time = _optional_text(
        raw.get("resolution_time")
        or raw.get("end_date_iso")
        or raw.get("market_end_time")
    )
    thesis_family = ThesisFamily.normalize(raw.get("thesis_family"), default=thesis_hint)

    fair_probability = _coerce_probability(
        raw.get("fair_probability"),
        fallback=_coerce_probability(raw.get("model_probability"), fallback=0.5),
    )
    market_probability = _coerce_probability(
        raw.get("market_probability"),
        fallback=_coerce_probability(raw.get("best_yes"), fallback=0.5),
    )

    fee_adjusted_edge = float(
        raw.get("fee_adjusted_edge")
        or raw.get("fee_adjusted_expected_edge")
        or raw.get("expected_edge")
        or (fair_probability - market_probability)
    )
    fill_probability = _coerce_probability(
        raw.get("fill_probability"),
        fallback=_coerce_probability(raw.get("expected_maker_fill_probability"), fallback=0.0),
    )
    toxicity = _coerce_probability(
        raw.get("toxicity"),
        fallback=_coerce_probability(raw.get("vpin"), fallback=0.0),
    )

    score, inputs = compute_route_score(
        {
            "fee_adjusted_edge": fee_adjusted_edge,
            "fill_probability": fill_probability,
            "toxicity": toxicity,
            "wallet_consensus_score": raw.get("wallet_consensus_score", 0.0),
            "lmsr_gap": raw.get("lmsr_gap", 0.0),
            "vpin": raw.get("vpin", 0.0),
            "ofi": raw.get("ofi", 0.0),
            "spread_bps": raw.get("spread_bps", 0.0),
            "narrative_heat": raw.get("narrative_heat"),
            "yes_crowding": raw.get("yes_crowding"),
            "base_rate_gap": raw.get("base_rate_gap"),
            "no_bias_prior": raw.get("no_bias_prior"),
            "data_quality_flags": raw.get("data_quality_flags") or [],
        }
    )
    route_score = float(raw.get("route_score", score))
    route_score_inputs = raw.get("route_score_inputs") if isinstance(raw.get("route_score_inputs"), Mapping) else inputs

    return CandidateRecord(
        venue=venue,
        market_id=market_id,
        title=title,
        ticker=ticker,
        resolution_time=resolution_time,
        thesis_family=thesis_family,
        fair_probability=fair_probability,
        market_probability=market_probability,
        fee_adjusted_edge=fee_adjusted_edge,
        fill_probability=fill_probability,
        toxicity=toxicity,
        route_score=route_score,
        route_score_inputs=dict(route_score_inputs),
        data_quality_flags=list(raw.get("data_quality_flags") or []),
        narrative_heat=_optional_float(raw.get("narrative_heat")),
        yes_crowding=_optional_float(raw.get("yes_crowding")),
        base_rate_gap=_optional_float(raw.get("base_rate_gap")),
        no_bias_prior=_optional_float(raw.get("no_bias_prior")),
        metadata={
            "raw_reject_reason": raw.get("reject_reason"),
            "raw_toxicity_state": raw.get("toxicity_state"),
            "raw_source": raw.get("source"),
        },
    )


def load_candidate_records(
    *,
    reports_dir: Path,
    polymarket_path: Path | None = None,
    kalshi_path: Path | None = None,
) -> tuple[list[CandidateRecord], dict[str, Any]]:
    """Load latest venue candidate exports into canonical CandidateRecord objects."""
    poly_path = polymarket_path or _latest_report(reports_dir, "poly_fastlane_candidates_*.json")
    kalshi_path = kalshi_path or _latest_report(reports_dir, "kalshi_intraday_surface_*.json")
    diagnostics: dict[str, Any] = {
        "polymarket_source": str(poly_path) if poly_path else None,
        "kalshi_source": str(kalshi_path) if kalshi_path else None,
        "parse_errors": [],
    }
    records: list[CandidateRecord] = []

    for source_path, venue_hint, thesis_hint in (
        (poly_path, "polymarket", ThesisFamily.WALLET_FLOW),
        (kalshi_path, "kalshi", ThesisFamily.CROSS_VENUE),
    ):
        if source_path is None:
            continue
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive parsing path
            diagnostics["parse_errors"].append({"path": str(source_path), "error": str(exc)})
            continue

        for item in _extract_candidate_rows(payload):
            if not isinstance(item, Mapping):
                continue
            records.append(
                normalize_candidate_record(item, venue_hint=venue_hint, thesis_hint=thesis_hint)
            )

    diagnostics["candidate_count"] = len(records)
    return records, diagnostics


def simulate_closed_trade_flywheel(
    candidates: list[CandidateRecord],
    *,
    horizon_hours: int = 24,
    seed: int = 42,
) -> dict[str, Any]:
    """Simulate 24-hour closed-trade density and attribution for normalized candidates."""
    rng = random.Random(seed)
    now = datetime.now(UTC)
    lifecycle_events: list[TradeLifecycleEvent] = []
    attributions: list[ClosedTradeAttribution] = []
    route_decisions: list[RouteDecision] = []
    transitions_valid = True

    routed = 0
    filled = 0
    partial = 0
    expired = 0

    for index, candidate in enumerate(candidates):
        accepted = (
            candidate.route_score > 0.0
            and candidate.fee_adjusted_edge > 0.0
            and candidate.fill_probability > 0.05
            and not candidate.data_quality_flags
        )
        reason = "accepted" if accepted else "blocked_by_score_or_quality"
        route_decisions.append(
            RouteDecision(
                opportunity_key=candidate.opportunity_key,
                venue=candidate.venue,
                market_id=candidate.market_id,
                accepted=accepted,
                reason=reason,
                route_score=candidate.route_score,
                route_score_inputs=dict(candidate.route_score_inputs),
                selected_notional_usd=5.0 if accepted else 0.0,
            )
        )
        if not accepted:
            continue
        routed += 1

        attempts = max(1, min(6, int(abs(candidate.route_score) / 18.0) + 1))
        for attempt in range(attempts):
            trade_id = f"{candidate.venue}:{candidate.market_id}:{index}:{attempt}"
            discovered_ts = (now + timedelta(minutes=(index * 9) + attempt)).isoformat()
            states: list[LifecycleState] = [
                LifecycleState.DISCOVERED,
                LifecycleState.ROUTED,
                LifecycleState.RESTING,
            ]
            draw = rng.random()
            fill_roll = candidate.fill_probability
            if draw <= fill_roll * 0.7:
                states.extend([LifecycleState.FILLED, LifecycleState.RESOLVED, LifecycleState.ATTRIBUTED])
                filled += 1
                fill_quality = min(1.0, candidate.fill_probability + rng.uniform(-0.1, 0.1))
            elif draw <= fill_roll:
                states.extend([LifecycleState.PARTIAL, LifecycleState.RESOLVED, LifecycleState.ATTRIBUTED])
                partial += 1
                fill_quality = min(1.0, candidate.fill_probability * rng.uniform(0.3, 0.8))
            else:
                states.append(LifecycleState.EXPIRED)
                expired += 1
                fill_quality = 0.0

            previous_state = states[0]
            for step_index, state in enumerate(states):
                if step_index > 0 and not is_valid_lifecycle_transition(previous_state, state):
                    transitions_valid = False
                lifecycle_events.append(
                    TradeLifecycleEvent(
                        event_ts=(now + timedelta(minutes=(index * 7) + attempt + step_index)).isoformat(),
                        state=state,
                        venue=candidate.venue,
                        market_id=candidate.market_id,
                        side="NO" if candidate.fair_probability < candidate.market_probability else "YES",
                        quantity=5.0 if state is LifecycleState.FILLED else 2.5,
                        price=candidate.market_probability,
                        reason="simulation",
                    )
                )
                previous_state = state

            if states[-1] is LifecycleState.ATTRIBUTED:
                realized_spread = candidate.fee_adjusted_edge + rng.uniform(-0.02, 0.02)
                resolution_pnl = 5.0 * realized_spread
                attributions.append(
                    ClosedTradeAttribution(
                        trade_id=trade_id,
                        venue=candidate.venue,
                        market_id=candidate.market_id,
                        thesis_family=candidate.thesis_family,
                        expected_edge=candidate.fee_adjusted_edge,
                        realized_spread=realized_spread,
                        fill_quality=fill_quality,
                        markout_5s=realized_spread + rng.uniform(-0.01, 0.01),
                        markout_30s=realized_spread + rng.uniform(-0.015, 0.015),
                        markout_2m=realized_spread + rng.uniform(-0.02, 0.02),
                        shadow_live_divergence=abs(rng.uniform(0.0, 0.03)),
                        resolution_pnl=resolution_pnl,
                        metadata={"horizon_hours": horizon_hours},
                    )
                )

    by_venue: dict[str, dict[str, float]] = {}
    by_thesis: dict[str, dict[str, float]] = {}
    for item in attributions:
        venue_bucket = by_venue.setdefault(item.venue, {"count": 0.0, "pnl_usd": 0.0})
        venue_bucket["count"] += 1.0
        venue_bucket["pnl_usd"] += item.resolution_pnl
        thesis_key = item.thesis_family.value
        thesis_bucket = by_thesis.setdefault(thesis_key, {"count": 0.0, "pnl_usd": 0.0})
        thesis_bucket["count"] += 1.0
        thesis_bucket["pnl_usd"] += item.resolution_pnl

    closed_trade_density_per_hour = 0.0 if horizon_hours <= 0 else len(attributions) / float(horizon_hours)
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_hours": int(horizon_hours),
        "seed": int(seed),
        "candidates_considered": len(candidates),
        "route_decisions": [item.to_dict() for item in route_decisions],
        "route_decision_summary": {
            "accepted": routed,
            "rejected": max(0, len(route_decisions) - routed),
        },
        "lifecycle_event_count": len(lifecycle_events),
        "lifecycle_transitions_valid": transitions_valid,
        "state_counts": {
            "filled": filled,
            "partial": partial,
            "expired": expired,
            "resolved": len(attributions),
            "attributed": len(attributions),
        },
        "closed_trade_density_per_hour": round(closed_trade_density_per_hour, 6),
        "closed_trade_attributions": [item.to_dict() for item in attributions],
        "summary": {
            "total_closed_trades": len(attributions),
            "total_resolution_pnl_usd": round(
                sum(item.resolution_pnl for item in attributions),
                6,
            ),
            "mean_realized_spread": round(
                _safe_mean([item.realized_spread for item in attributions]),
                6,
            ),
            "mean_fill_quality": round(
                _safe_mean([item.fill_quality for item in attributions]),
                6,
            ),
        },
        "by_venue": by_venue,
        "by_thesis_family": by_thesis,
    }


def build_allocator_contract_snapshot(
    candidates: list[CandidateRecord],
    *,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    """Serialize canonical interface definitions plus normalized candidate samples."""
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interfaces": {
            "CandidateRecord": {
                "required_fields": [
                    "venue",
                    "market_id",
                    "title",
                    "thesis_family",
                    "fair_probability",
                    "market_probability",
                    "fee_adjusted_edge",
                    "fill_probability",
                    "toxicity",
                    "route_score",
                    "data_quality_flags",
                ],
                "optional_narrative_fields": [
                    "narrative_heat",
                    "yes_crowding",
                    "base_rate_gap",
                    "no_bias_prior",
                ],
            },
            "RouteDecision": {
                "required_fields": [
                    "opportunity_key",
                    "venue",
                    "market_id",
                    "accepted",
                    "reason",
                    "route_score",
                    "route_score_inputs",
                ],
            },
            "TradeLifecycleEvent": {
                "states": [state.value for state in LifecycleState],
                "transition_rules": {
                    src.value: sorted(dst.value for dst in allowed)
                    for src, allowed in _ALLOWED_LIFECYCLE_TRANSITIONS.items()
                },
            },
            "ClosedTradeAttribution": {
                "required_fields": [
                    "trade_id",
                    "venue",
                    "market_id",
                    "thesis_family",
                    "expected_edge",
                    "realized_spread",
                    "fill_quality",
                    "markout_5s",
                    "markout_30s",
                    "markout_2m",
                    "shadow_live_divergence",
                    "resolution_pnl",
                ],
            },
        },
        "route_score_formula": {
            "description": (
                "Fast-flow terms (fee-adjusted edge, fill probability, toxicity, wallet flow, "
                "LMSR gap, OFI/VPIN/spread) drive score now. Narrative terms are opt-in and "
                "remain zero unless populated."
            ),
            "terms": {
                "edge_term": "120 * fee_adjusted_edge",
                "fill_term": "25 * fill_probability",
                "toxicity_term": "-20 * toxicity",
                "wallet_term": "14 * wallet_consensus_score",
                "lmsr_term": "10 * max(0, lmsr_gap)",
                "microstructure_term": "8 * max(0, ofi) - 8 * vpin - min(10, spread_bps/4)",
                "narrative_term": "only active when narrative fields are populated",
                "data_quality_penalty": "-6 * len(data_quality_flags)",
            },
        },
        "data_sources": dict(diagnostics),
        "candidate_counts": {
            "total": len(candidates),
            "by_venue": _count_by(candidates, key=lambda item: item.venue),
            "by_thesis_family": _count_by(candidates, key=lambda item: item.thesis_family.value),
        },
        "candidate_sample": [item.to_dict() for item in candidates[:10]],
    }


def _latest_report(reports_dir: Path, pattern: str) -> Path | None:
    matches = sorted(reports_dir.glob(pattern))
    return matches[-1] if matches else None


def _extract_candidate_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("candidates", "markets", "rows", "opportunities"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    if "market_id" in payload or "title" in payload:
        return [dict(payload)]
    return []


def _coerce_probability(value: Any, *, fallback: float) -> float:
    if value is None:
        return _clamp_01(fallback)
    try:
        return _clamp_01(float(value))
    except (TypeError, ValueError):
        return _clamp_01(fallback)


def _normalize_float_mapping(payload: Mapping[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, value in dict(payload or {}).items():
        try:
            normalized[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _count_by(items: list[CandidateRecord], *, key) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        group = str(key(item))
        counts[group] = counts.get(group, 0) + 1
    return counts


def _clamp_01(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def _optional_clamp_01(value: float | None) -> float | None:
    if value is None:
        return None
    return _clamp_01(value)


def _clamp_signed(value: Any) -> float:
    return max(-1.0, min(1.0, float(value)))


def _optional_clamp_signed(value: float | None) -> float | None:
    if value is None:
        return None
    return _clamp_signed(value)

