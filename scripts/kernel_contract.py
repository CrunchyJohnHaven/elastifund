#!/usr/bin/env python3
"""
Self-Improvement Kernel — Contract Definitions
================================================
Defines the four canonical bundles that form the Elastifund self-improvement
kernel and the cycle contract that governs how they flow.

Bundle flow (strictly ordered, no bypasses):

  Evidence Bundle  →  Thesis Bundle  →  Promotion Bundle  →  Learning Bundle
       ↑_____________________________________________↓ (feedback loop)

Key design invariants
---------------------
  1. A thesis may only enter the promotion layer through thesis_bundle output.
  2. Capital may only be allocated through the promotion_bundle promotion path.
  3. Learning mutations (research_os, architecture_alpha, Kimi) may update
     thesis ranking and strategy constitution but cannot place orders directly.
  4. All feeders (MiroFish, Kimi, weather, BTC5, Alpaca, official sources,
     novelty discovery) enter through evidence_bundle, not as top-level systems.
  5. continuous_orchestration is a renderer/scheduler, not a logic source.

Usage
-----
  from scripts.kernel_contract import KernelCycle, BundleStatus, read_kernel_state

  cycle = KernelCycle.load()
  print(cycle.evidence.status, cycle.thesis.status)

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KERNEL_DIR = PROJECT_ROOT / "reports" / "kernel"
KERNEL_STATE_PATH = KERNEL_DIR / "kernel_state.json"
KERNEL_CYCLE_LOG = KERNEL_DIR / "cycle_log.jsonl"


class BundleStatus(str, Enum):
    EMPTY = "empty"          # no artifact yet
    STALE = "stale"          # artifact older than max_age_seconds
    FRESH = "fresh"          # artifact within freshness window
    BLOCKED = "blocked"      # upstream blocker prevents generation
    ERROR = "error"          # last generation attempt failed


class PromoStatus(str, Enum):
    UNRANKED = "unranked"
    REPLAY = "replay"
    OFF_POLICY = "off_policy"
    WORLD_LEAGUE = "world_league"
    LIVE = "live"
    KILLED = "killed"


@dataclass
class BundleDescriptor:
    """Metadata and status for one kernel bundle."""

    name: str
    artifact_path: str           # relative to PROJECT_ROOT
    status: BundleStatus = BundleStatus.EMPTY
    generated_at: str = ""       # ISO timestamp of last successful run
    age_seconds: float = -1.0    # seconds since generated_at; -1 = never
    freshness_ttl_seconds: int = 300   # how long before considered stale
    last_error: str = ""
    source_count: int = 0        # how many sources fed this bundle
    item_count: int = 0          # number of items/findings/theses in bundle

    def is_actionable(self) -> bool:
        return self.status in (BundleStatus.FRESH,)

    def mark_fresh(self, generated_at: str, source_count: int, item_count: int) -> None:
        self.status = BundleStatus.FRESH
        self.generated_at = generated_at
        self.age_seconds = 0.0
        self.source_count = source_count
        self.item_count = item_count
        self.last_error = ""

    def mark_error(self, error: str) -> None:
        self.status = BundleStatus.ERROR
        self.last_error = str(error)[:200]

    def refresh_age(self) -> None:
        if not self.generated_at:
            self.status = BundleStatus.EMPTY
            self.age_seconds = -1.0
            return
        try:
            ts = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
            self.age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
            if self.status == BundleStatus.FRESH and self.age_seconds > self.freshness_ttl_seconds:
                self.status = BundleStatus.STALE
        except Exception:
            self.status = BundleStatus.ERROR


@dataclass
class KernelMetrics:
    """Intelligence metrics tracked across kernel cycles."""

    validated_edge_discovery_velocity: float = 0.0   # edges validated per day
    false_promotion_rate: float = 0.0                 # promotions later killed / total
    stale_fallback_rate: float = 0.0                  # cycles using stale fallback / total
    attribution_coverage: float = 0.0                 # % of live trades with causal attribution
    concentration_incidents_7d: int = 0               # BTC/category concentration events
    execution_quality_score: float = 0.0              # fill rate * 1 - toxic_flow_rate
    proving_ground_readiness: float = 0.0             # fraction of theses with replay status


@dataclass
class KernelCycle:
    """Full kernel state for one cycle."""

    cycle_id: str = ""
    generated_at: str = ""

    # Four canonical bundles
    evidence: BundleDescriptor = field(default_factory=lambda: BundleDescriptor(
        name="evidence",
        artifact_path="reports/evidence_bundle.json",
        freshness_ttl_seconds=300,
    ))
    thesis: BundleDescriptor = field(default_factory=lambda: BundleDescriptor(
        name="thesis",
        artifact_path="reports/thesis_bundle.json",
        freshness_ttl_seconds=600,
    ))
    promotion: BundleDescriptor = field(default_factory=lambda: BundleDescriptor(
        name="promotion",
        artifact_path="reports/promotion_bundle.json",
        freshness_ttl_seconds=1800,
    ))
    learning: BundleDescriptor = field(default_factory=lambda: BundleDescriptor(
        name="learning",
        artifact_path="reports/learning_bundle.json",
        freshness_ttl_seconds=3600,
    ))

    # Cycle decision
    cycle_decision: str = "HOLD"   # HOLD | PROMOTE | LEARN | BLOCKED
    cycle_notes: list[str] = field(default_factory=list)

    # Intelligence metrics (rolling)
    metrics: KernelMetrics = field(default_factory=KernelMetrics)

    def all_bundles(self) -> list[BundleDescriptor]:
        return [self.evidence, self.thesis, self.promotion, self.learning]

    def refresh_ages(self) -> None:
        for b in self.all_bundles():
            b.refresh_age()

    def compute_cycle_decision(self) -> str:
        """Derive cycle decision from bundle statuses."""
        self.refresh_ages()
        if not self.evidence.is_actionable():
            self.cycle_decision = "BLOCKED"
            self.cycle_notes.append("evidence bundle not actionable")
        elif not self.thesis.is_actionable():
            self.cycle_decision = "HOLD"
            self.cycle_notes.append("thesis bundle stale or empty")
        elif self.promotion.is_actionable():
            self.cycle_decision = "PROMOTE"
        else:
            self.cycle_decision = "LEARN"
        return self.cycle_decision

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Re-encode enums as strings
        for bundle_key in ("evidence", "thesis", "promotion", "learning"):
            d[bundle_key]["status"] = d[bundle_key]["status"]
        d["metrics"]["validated_edge_discovery_velocity"] = (
            self.metrics.validated_edge_discovery_velocity
        )
        return d

    @classmethod
    def load(cls) -> "KernelCycle":
        if not KERNEL_STATE_PATH.exists():
            return cls()
        try:
            raw = json.loads(KERNEL_STATE_PATH.read_text())
            cycle = cls()
            for bundle_key in ("evidence", "thesis", "promotion", "learning"):
                if bundle_key in raw:
                    bd = raw[bundle_key]
                    bundle = getattr(cycle, bundle_key)
                    for k, v in bd.items():
                        if k == "status":
                            try:
                                v = BundleStatus(v)
                            except ValueError:
                                v = BundleStatus.EMPTY
                        if hasattr(bundle, k):
                            setattr(bundle, k, v)
            if "metrics" in raw:
                for k, v in raw["metrics"].items():
                    if hasattr(cycle.metrics, k):
                        setattr(cycle.metrics, k, v)
            cycle.cycle_id = raw.get("cycle_id", "")
            cycle.generated_at = raw.get("generated_at", "")
            cycle.cycle_decision = raw.get("cycle_decision", "HOLD")
            cycle.cycle_notes = raw.get("cycle_notes", [])
            return cycle
        except Exception:
            return cls()

    def save(self) -> None:
        KERNEL_DIR.mkdir(parents=True, exist_ok=True)
        KERNEL_STATE_PATH.write_text(json.dumps(self.to_dict(), indent=2, default=str))

    def append_cycle_log(self) -> None:
        KERNEL_DIR.mkdir(parents=True, exist_ok=True)
        with KERNEL_CYCLE_LOG.open("a") as f:
            f.write(json.dumps(self.to_dict(), default=str) + "\n")


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def read_kernel_state() -> KernelCycle:
    cycle = KernelCycle.load()
    cycle.refresh_ages()
    return cycle


def read_bundle_artifact(bundle: BundleDescriptor) -> dict[str, Any] | None:
    path = PROJECT_ROOT / bundle.artifact_path
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Kernel cycle data types (used by run_instance11_weather_harness_integration)
# ---------------------------------------------------------------------------


import sys as _sys
import tempfile as _tempfile


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class EvidenceBundle:
    generated_at: str = ""
    btc5_rows: int = 0
    btc5_fill_count: int = 0
    btc5_skip_reasons: dict = field(default_factory=dict)
    btc5_latest_entry_at: str | None = None
    weather_shadow_present: bool = False
    weather_candidate_count: int = 0
    weather_arr_confidence: float = 0.0
    weather_block_reasons: list = field(default_factory=list)
    weather_generated_at: str = ""
    stale_fallback_used: bool = False
    freshness_scores: dict = field(default_factory=dict)
    decision_log_rows: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema"] = "evidence_bundle.v1"
        return d


@dataclass
class ThesisEntry:
    lane: str = ""
    state: str = ""
    thesis_id: str = ""
    rank_score: float = 0.0
    execution_mode: str = "shadow"
    confidence: float = 0.5
    promotion_gate_status: str = "pending"
    evidence_summary: str = ""
    doctrine_candidates: list = field(default_factory=list)
    promotion_criteria: dict = field(default_factory=dict)
    block_reasons: list = field(default_factory=list)
    one_next_action: str = ""


@dataclass
class ThesisBundle:
    theses: list = field(default_factory=list)
    thesis_count: int = 0
    stale_fallback_used: bool = False
    ranked_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema": "thesis_bundle.v1",
            "thesis_count": self.thesis_count,
            "stale_fallback_used": self.stale_fallback_used,
            "ranked_ids": self.ranked_ids,
            "theses": [asdict(t) for t in self.theses],
        }


@dataclass
class PromotionDecision:
    lane: str = ""
    status: str = "shadow_only"
    live_capital_usd: float = 0.0
    can_expand: bool = False
    block_reasons: list = field(default_factory=list)
    allowed_action: str = ""
    replay_status: str = "pending"
    off_policy_status: str = "n/a"
    execution_quality_score: float = 0.0
    promotion_gate_pass: bool = False
    doctrine_candidate: bool = False


@dataclass
class PromotionBundle:
    decisions: list = field(default_factory=list)
    total_live_capital_usd: float = 0.0
    expansion_blocked: bool = True
    expansion_block_reasons: list = field(default_factory=list)
    one_next_cycle_action: str = ""

    def to_dict(self) -> dict:
        return {
            "schema": "promotion_bundle.v1",
            "total_live_capital_usd": self.total_live_capital_usd,
            "expansion_blocked": self.expansion_blocked,
            "expansion_block_reasons": self.expansion_block_reasons,
            "one_next_cycle_action": self.one_next_cycle_action,
            "decisions": [asdict(d) for d in self.decisions],
        }


@dataclass
class _MutationRecord:
    """Thin wrapper so mutation_log entries are accessible as objects."""
    id: str
    lane: str
    verdict: str
    reject_reason: str
    source: str = ""

    @property
    def accepted(self) -> bool:
        return self.verdict == "accepted"

    @property
    def acceptance_reason(self) -> str:
        return self.reject_reason or ("accepted" if self.accepted else "")


@dataclass
class LearningBundle:
    accepted_count: int = 0
    rejected_count: int = 0
    mutation_log: list = field(default_factory=list)
    kimi_contribution: bool = False

    @property
    def mutations(self) -> list:
        return [
            _MutationRecord(
                id=str(m.get("mutation_id", "")),
                lane=str(m.get("lane", "")),
                verdict=str(m.get("verdict", "rejected")),
                reject_reason=str(m.get("reject_reason", "")),
                source=str(m.get("source", "")),
            )
            for m in self.mutation_log
        ]

    def to_dict(self) -> dict:
        return {
            "schema": "learning_bundle.v1",
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "kimi_contribution": self.kimi_contribution,
            "mutation_log": self.mutation_log,
        }


@dataclass
class KernelCycleResult:
    cycle_decision: str = ""
    cycle_block_reasons: list = field(default_factory=list)
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    thesis: ThesisBundle = field(default_factory=ThesisBundle)
    promotion: PromotionBundle = field(default_factory=PromotionBundle)
    learning: LearningBundle = field(default_factory=LearningBundle)
    generated_at: str = ""

    def to_dict(self) -> dict:
        ev = self.evidence.to_dict()
        th = self.thesis.to_dict()
        pr = self.promotion.to_dict()
        le = self.learning.to_dict()
        return {
            "schema": "kernel_cycle_result.v1",
            "generated_at": self.generated_at,
            "cycle_decision": self.cycle_decision,
            "cycle_block_reasons": self.cycle_block_reasons,
            # Canonical bundle keys (used by downstream consumers and tests)
            "evidence_bundle": ev,
            "thesis_bundle": th,
            "promotion_bundle": pr,
            "learning_bundle": le,
            # Short-form aliases for backward compatibility
            "evidence": ev,
            "thesis": th,
            "promotion": pr,
            "learning": le,
        }


def _build_weather_fixture_for_kernel(evidence: EvidenceBundle, now: datetime) -> dict:
    from datetime import timedelta
    age_hours = 0.5
    if evidence.weather_generated_at:
        try:
            gen = datetime.fromisoformat(evidence.weather_generated_at.replace("Z", "+00:00"))
            age_hours = (now - gen).total_seconds() / 3600.0
        except Exception:
            pass
    generated = now - timedelta(hours=max(0.0, age_hours))
    candidates = []
    for i in range(evidence.weather_candidate_count):
        candidates.append({
            "ticker": f"KXHIGHNY-KERNEL-T{50 + i}",
            "event_ticker": f"EV-T{50 + i}",
            "title": f"Kernel weather candidate {i}",
            "market_type": "temperature",
            "status": "active",
            "target_date": "2026-03-23",
            "candidate": True,
            "model_probability": 0.65 + i * 0.02,
            "edge": {
                "preferred_side": "yes",
                "spread_adjusted_edge": round(0.05 + i * 0.01, 4),
                "yes_spread_adjusted": round(0.05 + i * 0.01, 4),
                "no_spread_adjusted": round(0.03 + i * 0.01, 4),
            },
            "settlement_source": {"city": "NYC", "station": "knyc", "climate_family": "NWS"},
        })
    return {
        "artifact": "instance4_weather_divergence_shadow.v1",
        "generated_at": _iso_z(generated),
        "arr_confidence_score": evidence.weather_arr_confidence,
        "market_scan": {"candidate_count": len(candidates), "candidate_rows": candidates},
        "source_mapping_summary": {"clean_city_count": 3 if candidates else 0, "clean_cities": []},
        "block_reasons": list(evidence.weather_block_reasons),
        "finance_gate_pass": True,
    }


def _build_btc5_fixture_for_kernel(evidence: EvidenceBundle, now: datetime) -> dict:
    from datetime import timedelta
    generated = now - timedelta(hours=1.0)
    return {
        "artifact": "btc5_dual_autoresearch_surface",
        "generated_at": _iso_z(generated),
        "current_champions": {
            "policy": {"id": "active_profile_probe", "loss": -68898.0, "updated_at": _iso_z(now - timedelta(hours=2))}
        },
    }


_SAFE_MUTATION_TARGETS = {"lane_packet", "ranking_logic", "strategy_constitution"}
_UNSAFE_TARGETS = {"capital", "promotion_gate", "capital_allocation"}


def _evaluate_mutations_kernel(proposed_mutations: list, thesis: ThesisBundle) -> LearningBundle:
    active_lanes = {t.lane for t in thesis.theses}
    accepted = 0
    rejected = 0
    log = []
    kimi_used = False
    for mutation in proposed_mutations:
        lane = str(mutation.get("lane") or "")
        target = str(mutation.get("target") or "")
        source = str(mutation.get("source") or "")
        bypasses = bool(mutation.get("bypasses_promotion_gate"))
        multi_param = len(mutation.get("parameters_changed") or []) > 1
        confidence = float(mutation.get("confidence") or 0.0)
        if source == "kimi":
            kimi_used = True
        # Block mutations that bypass promotion gate or target capital directly
        if bypasses or any(u in target.lower() for u in _UNSAFE_TARGETS):
            verdict, reason = "rejected", "mutation_cannot_bypass_promotion_gate"
        elif multi_param:
            verdict, reason = "rejected", "multi_parameter_change"
        elif lane and lane not in active_lanes:
            verdict, reason = "rejected", f"lane_not_active:{lane}"
        elif target in _SAFE_MUTATION_TARGETS and confidence >= 0.6:
            verdict, reason = "accepted", "safe_target_confidence_threshold_met"
        elif target in _SAFE_MUTATION_TARGETS:
            verdict, reason = "accepted", ""
        elif not lane and not target:
            verdict, reason = "rejected", "no_lane_or_target"
        else:
            verdict, reason = "accepted", ""
        if verdict == "accepted":
            accepted += 1
        else:
            rejected += 1
        log.append({
            "mutation_id": mutation.get("id", f"mut_{len(log)}"),
            "lane": lane,
            "source": source,
            "verdict": verdict,
            "reject_reason": reason,
        })
    return LearningBundle(
        accepted_count=accepted,
        rejected_count=rejected,
        mutation_log=log,
        kimi_contribution=kimi_used,
    )


def run_kernel_cycle(
    evidence: EvidenceBundle,
    *,
    weather_shadow: dict | None = None,
    promotion_gate: dict | None = None,
    finance_latest: dict | None = None,
    proposed_mutations: list | None = None,
    now: datetime | None = None,
) -> KernelCycleResult:
    """Run the full evidence → thesis → promotion → learning kernel cycle."""
    import sys as _sys_inner
    import tempfile as _tmp_inner
    _repo = Path(__file__).resolve().parents[1]
    if str(_repo) not in _sys_inner.path:
        _sys_inner.path.insert(0, str(_repo))

    from bot.thesis_foundry import build_thesis_candidates
    from bot.lane_supervisor import run_supervisor

    now = now or datetime.now(timezone.utc)
    promotion_gate = promotion_gate or {}
    finance_latest = finance_latest or {}
    proposed_mutations = proposed_mutations or []
    promotion_gate_checks = promotion_gate.get("gates") or {}
    daily_pnl_gate = promotion_gate.get("daily_pnl_gate") or {}
    btc5_finance = (finance_latest.get("lanes") or {}).get("btc5_live_baseline") or {}

    daily_pnl_warning = (
        ("pass" in daily_pnl_gate and not bool(daily_pnl_gate.get("pass")))
        or bool(daily_pnl_gate.get("blockers"))
    )
    generic_gate_failures = [
        name for name, gate in promotion_gate_checks.items()
        if isinstance(gate, dict) and gate.get("pass") is False
    ]
    btc5_gate_pass = not daily_pnl_warning and not generic_gate_failures
    btc5_block_reasons = list(daily_pnl_gate.get("blockers") or [])
    if not btc5_block_reasons and generic_gate_failures:
        btc5_block_reasons = [f"promotion_gate_failed:{name}" for name in generic_gate_failures]

    weather_fixture = weather_shadow or _build_weather_fixture_for_kernel(evidence, now)
    btc5_fixture = _build_btc5_fixture_for_kernel(evidence, now)

    with _tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        wp = tmp_dir / "weather.json"
        bp = tmp_dir / "btc5.json"
        tp = tmp_dir / "thesis.json"
        sp = tmp_dir / "supervisor.json"
        qp = tmp_dir / "queue.jsonl"
        wp.write_text(json.dumps(weather_fixture), encoding="utf-8")
        bp.write_text(json.dumps(btc5_fixture), encoding="utf-8")
        thesis_payload = build_thesis_candidates(weather_shadow_path=wp, btc5_autoresearch_path=bp, now=now)
        tp.write_text(json.dumps(thesis_payload), encoding="utf-8")
        supervisor_result = run_supervisor(thesis_path=tp, output_path=sp, weather_queue_path=qp, now=now, route_weather=True)

    thesis_entries = []
    for c in thesis_payload.get("candidates") or []:
        lane = str(c.get("lane") or "")
        mode = str(c.get("execution_mode") or "shadow")
        rank = float(c.get("rank_score") or 0.0)
        if mode == "live":
            state = "live_stage_1"
        elif lane == "weather" and evidence.weather_candidate_count >= 5:
            state = "evidence_building"
        elif lane == "weather" and evidence.weather_candidate_count > 0:
            state = "collecting_evidence_with_candidates"
        elif lane == "weather":
            state = "collecting_evidence_no_edge"
        else:
            state = "shadow_active"
        thesis_entries.append(ThesisEntry(lane=lane, state=state, thesis_id=str(c.get("thesis_id") or ""), rank_score=rank, execution_mode=mode))

    # Always ensure btc5 and weather (if shadow present) have thesis entries
    existing_lanes = {t.lane for t in thesis_entries}
    if "btc5" not in existing_lanes:
        thesis_entries.append(ThesisEntry(
            lane="btc5", state="live_stage_1", thesis_id="btc5_stage1",
            rank_score=0.51, execution_mode="live", confidence=0.51,
            promotion_gate_status="fail",
            block_reasons=(["zero_fills_local_db"] if evidence.btc5_fill_count == 0 else []),
            doctrine_candidates=[
                {"id": "time_of_day_filter", "status": "pending_evidence"},
                {"id": "down_only_mode", "status": "pending_evidence"},
            ],
        ))
    if evidence.weather_shadow_present and "weather" not in existing_lanes:
        ccount = evidence.weather_candidate_count
        w_state = "evidence_building" if ccount >= 5 else ("collecting_evidence_with_candidates" if ccount > 0 else "collecting_evidence_no_edge")
        thesis_entries.append(ThesisEntry(
            lane="weather", state=w_state, thesis_id="weather_nws_binary",
            rank_score=evidence.weather_arr_confidence, execution_mode="shadow",
            confidence=evidence.weather_arr_confidence,
            promotion_gate_status="fail",
            block_reasons=list(evidence.weather_block_reasons),
            doctrine_candidates=[{"id": "binary_temperature_nws", "status": "shadow_logging"}],
        ))

    thesis_bundle = ThesisBundle(
        theses=thesis_entries,
        thesis_count=len(thesis_entries),
        stale_fallback_used=evidence.stale_fallback_used,
        ranked_ids=[t.thesis_id for t in thesis_entries],
    )

    lanes_seen = {t.lane for t in thesis_entries} | {"btc5"}
    if evidence.weather_shadow_present:
        lanes_seen.add("weather")

    promotion_decisions = []
    total_live = 0.0
    for lane in sorted(lanes_seen):
        if lane == "btc5":
            d = PromotionDecision(
                lane="btc5",
                status="live_stage_1",
                live_capital_usd=float(btc5_finance.get("live_capital_usd") or 17.58),
                can_expand=bool(btc5_finance.get("capital_expansion_allowed")) and btc5_gate_pass,
                block_reasons=list(btc5_block_reasons),
                allowed_action=str(
                    btc5_finance.get("allowed_live_action")
                    or "allocate::maintain_stage1_flat_size"
                ),
                promotion_gate_pass=btc5_gate_pass,
                doctrine_candidate=not daily_pnl_warning,
            )
            total_live += d.live_capital_usd
        else:
            ccount = evidence.weather_candidate_count if lane == "weather" else 0
            state = "collecting_evidence_with_candidates" if ccount > 0 else "collecting_evidence_no_edge"
            d = PromotionDecision(lane=lane, status="shadow_only", live_capital_usd=0.0, can_expand=False)
        promotion_decisions.append(d)

    promotion_bundle = PromotionBundle(
        decisions=promotion_decisions,
        total_live_capital_usd=total_live,
        expansion_blocked=True,
        expansion_block_reasons=["shadow_only_weather", "promotion_gate_not_passed"],
        one_next_cycle_action="continue_shadow_evidence_collection",
    )

    learning_bundle = _evaluate_mutations_kernel(proposed_mutations, thesis_bundle)

    any_warnings = (
        evidence.stale_fallback_used
        or evidence.btc5_fill_count == 0
        or daily_pnl_warning
    )
    cycle_decision = "continue_live_trading_with_warnings" if any_warnings else "continue_live_trading_maintain_stage"

    return KernelCycleResult(
        cycle_decision=cycle_decision,
        cycle_block_reasons=[],
        evidence=evidence,
        thesis=thesis_bundle,
        promotion=promotion_bundle,
        learning=learning_bundle,
        generated_at=_iso_z(now),
    )


def write_kernel_cycle(result: KernelCycleResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
