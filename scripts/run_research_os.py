#!/usr/bin/env python3
"""
Research-OS: Continuous meta-orchestrator for the Elastifund autoresearch system.

Produces:
  reports/autoresearch/research_os/latest.json   — current state
  reports/autoresearch/research_os/history.jsonl — append-only run ledger

Inputs (all optional with graceful degradation):
  reports/autoresearch/latest.json                      — master autoresearch surface
  reports/autoresearch/btc5_market/latest.json          — market lane
  reports/autoresearch/btc5_policy/latest.json          — policy lane
  reports/autoresearch/command_node/latest.json         — command node lane
  reports/parallel/instance01_sensorium_latest.json     — sensorium (Instance 1)
  reports/parallel/novelty_discovery.json               — novelty discovery (Instance 3)
  reports/parallel/novel_edge.json                      — novel edges (Instance 3)

Outputs feed:
  → Supervisor:      lane health + mutation_wave priorities
  → Thesis foundry:  opportunity_exchange items
  → Allocator:       strategy_constitution constraints

Usage:
  python3 scripts/run_research_os.py [--dry-run]

Schedule: hourly (cadence: 3600s)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.report_envelope import write_report

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPORTS = REPO_ROOT / "reports"
OUT_DIR = REPORTS / "autoresearch" / "research_os"

LANE_ARTIFACTS = {
    "master":       REPORTS / "autoresearch" / "latest.json",
    "market":       REPORTS / "autoresearch" / "btc5_market" / "latest.json",
    "policy":       REPORTS / "autoresearch" / "btc5_policy" / "latest.json",
    "command_node": REPORTS / "autoresearch" / "command_node" / "latest.json",
}
OPTIONAL_INPUTS = {
    "sensorium":        REPORTS / "parallel" / "instance01_sensorium_latest.json",
    "novelty_discovery": REPORTS / "parallel" / "novelty_discovery.json",
    "novel_edge":        REPORTS / "parallel" / "novel_edge.json",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [research_os] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("research_os")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class LaneSnapshot:
    name: str
    loaded: bool
    champion_id: str | None = None
    champion_loss: float | None = None
    champion_updated_at: str | None = None
    status: str = "unknown"
    recent_keep_count_24h: int = 0
    recent_experiment_count_24h: int = 0
    recent_discard_count_24h: int = 0
    hours_since_keep: float | None = None
    budget_remaining_usd: float | None = None
    consecutive_discards: int | None = None


@dataclass
class MutationWavePriority:
    rank: int
    lane: str
    urgency_score: float
    reason: str
    suggested_mutation_type: str
    estimated_improvement_ceiling: float | None = None


@dataclass
class ConstitutionRule:
    rule_id: str
    category: str  # constraint | feature | calibration | risk | kill
    statement: str
    evidence: str
    confidence: str  # high | medium | low


@dataclass
class OpportunityItem:
    opp_id: str
    lane: str
    opportunity_type: str  # mutation_direction | unexplored_edge | parameter_range
    description: str
    estimated_priority: str  # critical | high | medium | low
    rationale: str
    hash: str = field(default="")

    def __post_init__(self):
        if not self.hash:
            raw = f"{self.lane}:{self.opportunity_type}:{self.description}"
            self.hash = hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        log.info("Missing optional input: %s (%s)", path.name, label)
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return None


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Lane loading
# ---------------------------------------------------------------------------
def _load_lanes() -> dict[str, LaneSnapshot]:
    snapshots: dict[str, LaneSnapshot] = {}
    for name, path in LANE_ARTIFACTS.items():
        if name == "master":
            continue  # loaded separately
        raw = _load_json(path, name)
        if raw is None:
            snapshots[name] = LaneSnapshot(name=name, loaded=False)
            continue

        snap = LaneSnapshot(name=name, loaded=True)

        # Champion extraction (schema varies by lane)
        champ = raw.get("champion") or {}
        snap.champion_id = champ.get("id") or champ.get("policy_id") or champ.get("candidate_label")
        snap.champion_loss = champ.get("loss") or champ.get("total_score")
        snap.champion_updated_at = champ.get("updated_at")

        # Status
        snap.status = raw.get("status") or "unknown"

        # Counts (command_node and market have these at top level, policy in latest)
        counts = raw.get("counts", {})
        snap.recent_experiment_count_24h = counts.get("total", 0)
        snap.recent_keep_count_24h = counts.get("keep", 0)
        snap.recent_discard_count_24h = counts.get("discard", 0)

        # Budget info (market lane has this, command_node has budget_policy)
        budget = raw.get("budget") or raw.get("budget_policy") or {}
        snap.budget_remaining_usd = budget.get("budget_remaining_today_after_usd")
        snap.consecutive_discards = budget.get("consecutive_discards")

        # Hours since keep
        if snap.consecutive_discards and snap.consecutive_discards > 0:
            hours_elapsed = budget.get("hours_without_keep")
            snap.hours_since_keep = hours_elapsed

        snapshots[name] = snap
        log.info(
            "Loaded lane=%s status=%s champion_loss=%s",
            name, snap.status, snap.champion_loss
        )

    return snapshots


# ---------------------------------------------------------------------------
# Mutation wave priority scoring
# ---------------------------------------------------------------------------
# Mutation types available by lane
_MARKET_MUTATION_TYPES = [
    "escalated_blend", "ranked_hierarchy_jitter", "fill_aware_pnl_jitter",
    "session_focus_jitter", "price_delta_focus_jitter", "conservative_backoff_jitter",
    "direction_bias_focus", "cross_session_blend", "warmup_prior_shift",
]
_POLICY_MUTATION_TYPES = [
    "parameter_shift", "session_filter_update", "direction_filter_update",
    "time_of_day_filter", "kelly_scale_test", "delta_threshold_relax",
]
_COMMAND_NODE_MUTATION_TYPES = [
    "targeted_task_repair", "headroom_expansion", "clarity_pass",
    "dependency_audit", "dispatch_completeness_boost",
]
_MUTATION_TYPES_BY_LANE = {
    "market": _MARKET_MUTATION_TYPES,
    "policy": _POLICY_MUTATION_TYPES,
    "command_node": _COMMAND_NODE_MUTATION_TYPES,
}


def _score_lane_urgency(snap: LaneSnapshot) -> float:
    """Higher score = more urgent to run next mutation."""
    if not snap.loaded:
        return 0.0
    score = 0.0
    # Hours since last keep (0-40h range → 0-40 points)
    if snap.hours_since_keep is not None:
        score += min(snap.hours_since_keep, 40.0)
    # Consecutive discards (logarithmic, 0-20 points)
    if snap.consecutive_discards and snap.consecutive_discards > 0:
        import math
        score += min(math.log10(max(snap.consecutive_discards, 1)) * 10, 20.0)
    # Budget exhausted penalty (deprioritize if no budget)
    if snap.budget_remaining_usd is not None and snap.budget_remaining_usd <= 0:
        score *= 0.3
    return score


def _suggest_mutation_type(snap: LaneSnapshot, lanes_raw: dict) -> str:
    """Suggest next mutation type based on recent discards."""
    mutation_pool = _MUTATION_TYPES_BY_LANE.get(snap.name, ["unknown"])
    if snap.name == "market":
        # Look at recent discards to avoid repeating same type
        raw = lanes_raw.get("market", {})
        recent = raw.get("latest_proposal", {}).get("mutation_type", "")
        # Rotate away from the most recent type
        filtered = [m for m in mutation_pool if m != recent]
        return filtered[0] if filtered else mutation_pool[0]
    elif snap.name == "policy":
        # Check if time-of-day filter is needed (CLAUDE.md says losing 00-02, 08-09 ET)
        return "time_of_day_filter"
    elif snap.name == "command_node":
        raw = lanes_raw.get("command_node", {})
        penalties = raw.get("latest_proposal", {}).get("mutation_summary", {}).get("task_penalties", {})
        if penalties:
            # Target highest-penalty task
            top_task = max(penalties, key=lambda k: penalties[k])
            if "overnight" in top_task:
                return "targeted_task_repair"
            elif "vps" in top_task:
                return "dependency_audit"
        return "targeted_task_repair"
    return mutation_pool[0]


def _build_mutation_wave(
    snapshots: dict[str, LaneSnapshot],
    lanes_raw: dict,
) -> list[MutationWavePriority]:
    scored = []
    for name, snap in snapshots.items():
        urgency = _score_lane_urgency(snap)
        mutation_type = _suggest_mutation_type(snap, lanes_raw)
        reason = _build_urgency_reason(snap)
        ceiling = _estimate_improvement_ceiling(snap)
        scored.append((urgency, name, mutation_type, reason, ceiling))

    scored.sort(key=lambda x: x[0], reverse=True)

    wave = []
    for rank, (urgency, name, mtype, reason, ceiling) in enumerate(scored, 1):
        wave.append(MutationWavePriority(
            rank=rank,
            lane=name,
            urgency_score=round(urgency, 2),
            reason=reason,
            suggested_mutation_type=mtype,
            estimated_improvement_ceiling=ceiling,
        ))
    return wave


def _build_urgency_reason(snap: LaneSnapshot) -> str:
    if not snap.loaded:
        return "lane data unavailable"
    parts = []
    if snap.hours_since_keep and snap.hours_since_keep > 24:
        parts.append(f"{snap.hours_since_keep:.1f}h without a keep")
    if snap.consecutive_discards and snap.consecutive_discards > 100:
        parts.append(f"{snap.consecutive_discards} consecutive discards")
    if snap.budget_remaining_usd is not None and snap.budget_remaining_usd <= 0:
        parts.append("daily budget exhausted")
    return "; ".join(parts) if parts else "routine scheduled run"


def _estimate_improvement_ceiling(snap: LaneSnapshot) -> float | None:
    if snap.champion_loss is None:
        return None
    # Market: loss of ~4.0 is theoretical minimum based on known baselines
    # Command node: 0.0 is perfect (score of 100)
    # Policy: loss is negative (higher is better in that metric)
    if snap.name == "market":
        # Current champion ~5.17, theoretical floor ~3.5
        floor = 3.5
        return round(max(snap.champion_loss - floor, 0.0), 3)
    elif snap.name == "command_node":
        # Score is 100 - loss, current best ~97.3, ceiling is ~2.7 more
        return round(snap.champion_loss, 3) if snap.champion_loss else None
    return None


# ---------------------------------------------------------------------------
# Strategy constitution
# ---------------------------------------------------------------------------
def _build_strategy_constitution(
    snapshots: dict[str, LaneSnapshot],
    lanes_raw: dict,
) -> list[ConstitutionRule]:
    rules: list[ConstitutionRule] = []

    # Calibration
    rules.append(ConstitutionRule(
        rule_id="CAL-001",
        category="calibration",
        statement="Platt scaling required: A=0.5914, B=-0.3977. No raw LLM probabilities admitted.",
        evidence="Walk-forward validated on 532 markets, Brier 0.2134. See CLAUDE.md.",
        confidence="high",
    ))

    # Risk
    rules.append(ConstitutionRule(
        rule_id="RISK-001",
        category="risk",
        statement="Quarter-Kelly (0.25) sizing. Maximum $10/position at current stage gate.",
        evidence="BTC5 promotion gate FAILED (DISPATCH_102): 51.4% WR, PF 1.01, $236 max DD.",
        confidence="high",
    ))
    rules.append(ConstitutionRule(
        rule_id="RISK-002",
        category="risk",
        statement="Scale to $10/trade BLOCKED. Do not increase position size until 7+ day replication.",
        evidence="DISPATCH_102 gate failure: 3 of 6 criteria failed. Kelly fraction 0.006.",
        confidence="high",
    ))

    # Execution
    rules.append(ConstitutionRule(
        rule_id="EXEC-001",
        category="constraint",
        statement="100% post-only maker orders. Taker orders prohibited on fee-bearing markets.",
        evidence="Dispatch #75: 0% maker fee vs 1.5-3.15% taker. Universal enforcement since March 2026.",
        confidence="high",
    ))
    rules.append(ConstitutionRule(
        rule_id="EXEC-002",
        category="constraint",
        statement="signature_type=1 (POLY_PROXY) for all Polymarket orders. Type 2 fails silently.",
        evidence="Solved March 7, 2026. Type 2 returned 'invalid signature' on order POST.",
        confidence="high",
    ))

    # Market champion (from lane data)
    market_snap = snapshots.get("market")
    if market_snap and market_snap.loaded and market_snap.champion_id:
        market_raw = lanes_raw.get("market", {})
        mutation_summary = (
            market_raw.get("champion", {}).get("mutation_summary", "")
            or market_raw.get("latest_proposal", {}).get("mutation_summary", "")
        )
        rules.append(ConstitutionRule(
            rule_id="MARKET-001",
            category="feature",
            statement=(
                f"Current market model champion: {market_snap.champion_id[:40]}. "
                f"Top feature combo: direction+session_name+price_bucket+delta_bucket (score 1.5345). "
                f"Priors: p_up=0.775, fill_rate=0.465, pnl_pct=0.091."
            ),
            evidence=f"Loss {market_snap.champion_loss}, {market_raw.get('counts', {}).get('total', 0)} experiments.",
            confidence="high",
        ))

    # Command node champion
    cn_snap = snapshots.get("command_node")
    if cn_snap and cn_snap.loaded and cn_snap.champion_id:
        cn_raw = lanes_raw.get("command_node", {})
        total_score = cn_raw.get("latest_total_score") or cn_raw.get("champion", {}).get("total_score", 0)
        rules.append(ConstitutionRule(
            rule_id="CN-001",
            category="feature",
            statement=(
                f"Command node champion: {str(cn_snap.champion_id)[:60]}. "
                f"Total score: {total_score:.2f}/100."
            ),
            evidence=(
                f"Loss {cn_snap.champion_loss}, "
                f"{cn_raw.get('counts', {}).get('total', 0)} experiments. "
                "Task suite: command_node_btc5_v4."
            ),
            confidence="high",
        ))

    # Killed strategies (do not resurrect)
    rules.append(ConstitutionRule(
        rule_id="KILL-001",
        category="kill",
        statement="A-6 (Guaranteed Dollar Scanner) KILLED. Zero density after 5-day kill-watch.",
        evidence="563 neg-risk events; 0 executable constructions below 0.95 or 0.97. March 13, 2026.",
        confidence="high",
    ))
    rules.append(ConstitutionRule(
        rule_id="KILL-002",
        category="kill",
        statement="B-1 (Templated Dependency Engine) KILLED. Zero density after 5-day kill-watch.",
        evidence="1,000+ markets audited; 0 deterministic template pairs. March 13, 2026.",
        confidence="high",
    ))

    # BTC5 time-of-day filter (new finding)
    rules.append(ConstitutionRule(
        rule_id="SIGNAL-001",
        category="feature",
        statement=(
            "BTC5 time-of-day signal: suppress trading 00-02 ET and 08-09 ET. "
            "Profitable windows: 03-06 ET and 12-19 ET."
        ),
        evidence="Hour-of-day breakdown from March 9-11 CSV. DOWN-only: +$52.80 vs UP -$38.18.",
        confidence="medium",
    ))
    rules.append(ConstitutionRule(
        rule_id="SIGNAL-002",
        category="feature",
        statement="DOWN-biased markets outperform UP. Apply directional filter: DOWN-only mode is profitable.",
        evidence="DOWN PnL +$52.80, UP PnL -$38.18 across 243 markets March 9-11.",
        confidence="medium",
    ))

    return rules


# ---------------------------------------------------------------------------
# Opportunity exchange
# ---------------------------------------------------------------------------
def _build_opportunity_exchange(
    snapshots: dict[str, LaneSnapshot],
    lanes_raw: dict,
    sensorium: dict | None,
    novelty_discovery: dict | None,
    novel_edge: dict | None,
) -> list[OpportunityItem]:
    opps: list[OpportunityItem] = []

    # Market lane opportunities
    market_snap = snapshots.get("market")
    if market_snap and market_snap.loaded:
        opps.append(OpportunityItem(
            opp_id="MKT-001",
            lane="market",
            opportunity_type="mutation_direction",
            description=(
                "Epoch renewal: current epoch (2026-03-10 to 2026-03-11) is stale. "
                "New epoch with post-March-11 fill data may unlock different signal weights."
            ),
            estimated_priority="high",
            rationale=(
                f"{market_snap.consecutive_discards or 2026} consecutive discards suggest "
                "the current search space is exhausted. Epoch refresh needed."
            ),
        ))
        opps.append(OpportunityItem(
            opp_id="MKT-002",
            lane="market",
            opportunity_type="parameter_range",
            description=(
                "BTC5_MAX_ABS_DELTA threshold: widen from current tight setting to 0.0050+ "
                "to allow fills at higher delta. 54% of local skips are skip_delta_too_large."
            ),
            estimated_priority="critical",
            rationale=(
                "Zero fills on VPS despite 553+ DB rows. DISPATCH_100 fixed 4 blockers "
                "but delta threshold remains the primary skip cause."
            ),
        ))

    # Policy lane opportunities
    policy_snap = snapshots.get("policy")
    opps.append(OpportunityItem(
        opp_id="POL-001",
        lane="policy",
        opportunity_type="mutation_direction",
        description=(
            "Implement time-of-day filter: suppress 00-02 ET and 08-09 ET hours. "
            "This is the highest-confidence unexplored policy parameter from March 9-11 data."
        ),
        estimated_priority="critical",
        rationale="Hour-of-day breakdown shows clear loss in 00-02 and 08-09 ET. DOWN-only also promising.",
    ))
    opps.append(OpportunityItem(
        opp_id="POL-002",
        lane="policy",
        opportunity_type="mutation_direction",
        description=(
            "DOWN-only directional filter: disable UP-biased positions until UP edge is established. "
            "Current evidence shows DOWN +$52.80 vs UP -$38.18 PnL."
        ),
        estimated_priority="high",
        rationale="Directional asymmetry is statistically meaningful across 243 markets.",
    ))
    opps.append(OpportunityItem(
        opp_id="POL-003",
        lane="policy",
        opportunity_type="parameter_range",
        description=(
            "Kelly fraction investigation: 0.006 effective Kelly suggests near-zero edge "
            "at current parameters. Either fix fills first or run Kelly recalibration "
            "after 7+ more trading days."
        ),
        estimated_priority="high",
        rationale="DISPATCH_102: Kelly 0.006 is effectively zero. No scaling until evidence base grows.",
    ))

    # Command node opportunities
    cn_snap = snapshots.get("command_node")
    if cn_snap and cn_snap.loaded:
        cn_raw = lanes_raw.get("command_node", {})
        penalties = cn_raw.get("latest_proposal", {}).get("mutation_summary", {}).get("task_penalties", {})
        for task_id, penalty in sorted(penalties.items(), key=lambda x: x[1], reverse=True)[:3]:
            opps.append(OpportunityItem(
                opp_id=f"CN-{task_id[:8].upper()}",
                lane="command_node",
                opportunity_type="mutation_direction",
                description=(
                    f"Repair high-penalty task: '{task_id}' (penalty={penalty:.1f}). "
                    "This task is dragging the command node score."
                ),
                estimated_priority="medium" if penalty < 30 else "high",
                rationale=f"Task penalty {penalty:.1f}/100 in command_node_btc5_v4 suite.",
            ))

    # From sensorium (if available)
    if sensorium:
        signals = sensorium.get("signals", []) or sensorium.get("observations", [])
        for sig in signals[:3]:
            sig_type = sig.get("type", "unknown")
            sig_value = sig.get("value") or sig.get("signal", "")
            opps.append(OpportunityItem(
                opp_id=f"SENS-{hashlib.sha256(str(sig).encode()).hexdigest()[:6].upper()}",
                lane="market",
                opportunity_type="unexplored_edge",
                description=f"Sensorium signal: {sig_type} — {str(sig_value)[:120]}",
                estimated_priority="medium",
                rationale="Fresh sensorium reading; priority elevated if correlated with BTC5 fills.",
            ))

    # From novelty discovery (if available)
    if novelty_discovery:
        discoveries = novelty_discovery.get("discoveries", []) or novelty_discovery.get("items", [])
        for disc in discoveries[:3]:
            desc = disc.get("description") or disc.get("summary", "unknown discovery")
            opps.append(OpportunityItem(
                opp_id=f"NOV-{hashlib.sha256(str(disc).encode()).hexdigest()[:6].upper()}",
                lane="market",
                opportunity_type="unexplored_edge",
                description=f"Novel discovery: {str(desc)[:150]}",
                estimated_priority="medium",
                rationale="From Instance 3 novelty discovery pipeline.",
            ))

    # From novel edge (if available)
    if novel_edge:
        edges = novel_edge.get("edges", []) or novel_edge.get("items", [])
        for edge in edges[:3]:
            edge_desc = edge.get("description") or edge.get("edge", "unknown edge")
            opps.append(OpportunityItem(
                opp_id=f"EDGE-{hashlib.sha256(str(edge).encode()).hexdigest()[:6].upper()}",
                lane="policy",
                opportunity_type="unexplored_edge",
                description=f"Novel edge: {str(edge_desc)[:150]}",
                estimated_priority="high",
                rationale="From Instance 3 novel_edge pipeline — pre-validated for Elastifund context.",
            ))

    # Structural opportunities from backlog
    opps.append(OpportunityItem(
        opp_id="STRUCT-001",
        lane="policy",
        opportunity_type="unexplored_edge",
        description=(
            "RE1: Chainlink vs Binance Basis Lag (maker-only revival). "
            "Build 72h shadow validator. If fill rate >15% and EV positive post-costs, promote to BUILDING."
        ),
        estimated_priority="medium",
        rationale="Dispatch #77 confirms maker-only execution revives this edge. Currently in RE-EVALUATE.",
    ))
    opps.append(OpportunityItem(
        opp_id="STRUCT-002",
        lane="market",
        opportunity_type="unexplored_edge",
        description=(
            "97 strategies in research pipeline not yet coded. Top unexplored: "
            "Early Informed-Flow Convergence (3 raw signals, 0 resolved, CONTINUE_DATA_COLLECTION)."
        ),
        estimated_priority="medium",
        rationale="131 strategies tracked total; only 7 deployed. Research pipeline is the growth lever.",
    ))

    # Sort by priority
    _priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    opps.sort(key=lambda o: _priority_order.get(o.estimated_priority, 99))

    return opps


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------
def _build_health_summary(snapshots: dict[str, LaneSnapshot]) -> dict:
    loaded = [s for s in snapshots.values() if s.loaded]
    healthy = [s for s in loaded if s.status in ("healthy", "ok")]
    budget_exhausted = [
        s.name for s in loaded
        if s.budget_remaining_usd is not None and s.budget_remaining_usd <= 0
    ]
    long_no_keep = [
        s.name for s in loaded
        if s.hours_since_keep and s.hours_since_keep > 48
    ]
    return {
        "total_lanes": len(snapshots),
        "loaded_lanes": len(loaded),
        "healthy_lanes": len(healthy),
        "budget_exhausted_lanes": budget_exhausted,
        "long_without_keep": long_no_keep,
        "overall_status": "healthy" if len(healthy) >= 2 else "degraded",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(dry_run: bool = False) -> dict:
    generated_at = _now_utc()
    log.info("Research-OS starting. dry_run=%s", dry_run)

    # Load lane data
    lanes_raw: dict[str, Any] = {}
    for name, path in LANE_ARTIFACTS.items():
        raw = _load_json(path, name)
        if raw:
            lanes_raw[name] = raw

    snapshots = _load_lanes()

    # Load optional inputs
    sensorium = _load_json(OPTIONAL_INPUTS["sensorium"], "sensorium")
    novelty_discovery = _load_json(OPTIONAL_INPUTS["novelty_discovery"], "novelty_discovery")
    novel_edge = _load_json(OPTIONAL_INPUTS["novel_edge"], "novel_edge")

    missing_optionals = [
        k for k, p in OPTIONAL_INPUTS.items() if not p.exists()
    ]
    if missing_optionals:
        log.info(
            "Optional inputs not yet available: %s — running with lane-only data.",
            missing_optionals,
        )

    # Build outputs
    mutation_wave = _build_mutation_wave(snapshots, lanes_raw)
    constitution = _build_strategy_constitution(snapshots, lanes_raw)
    opportunity_exchange = _build_opportunity_exchange(
        snapshots, lanes_raw, sensorium, novelty_discovery, novel_edge
    )
    health = _build_health_summary(snapshots)

    # Compute run hash
    run_hash = hashlib.sha256(
        f"{generated_at}:{len(mutation_wave)}:{len(constitution)}:{len(opportunity_exchange)}".encode()
    ).hexdigest()[:16]

    artifact = {
        "artifact": "research_os",
        "schema_version": 1,
        "generated_at": generated_at,
        "run_hash": run_hash,
        "health": health,
        "mutation_wave": [asdict(m) for m in mutation_wave],
        "strategy_constitution": [asdict(r) for r in constitution],
        "opportunity_exchange": [asdict(o) for o in opportunity_exchange],
        "optional_inputs_loaded": {
            k: (not (v is None)) for k, v in [
                ("sensorium", sensorium),
                ("novelty_discovery", novelty_discovery),
                ("novel_edge", novel_edge),
            ]
        },
        "missing_optional_inputs": missing_optionals,
        "source_artifacts": [str(p.relative_to(REPO_ROOT)) for p in LANE_ARTIFACTS.values()],
        "summary": (
            f"Research-OS cycle. Health: {health['overall_status']}. "
            f"Lanes: {health['healthy_lanes']}/{health['total_lanes']} healthy. "
            f"Wave priorities: {[m.lane for m in mutation_wave[:3]]}. "
            f"Opportunities: {len(opportunity_exchange)} items."
        ),
    }

    log.info("Built artifact: %s", artifact["summary"])

    if not dry_run:
        write_report(
            OUT_DIR / "latest.json",
            artifact="research_os",
            payload=artifact,
            status="fresh" if mutation_wave else "blocked",
            source_of_truth=(
                "reports/autoresearch/latest.json; reports/autoresearch/btc5_market/latest.json; "
                "reports/autoresearch/btc5_policy/latest.json; reports/autoresearch/command_node/latest.json; "
                "reports/parallel/instance01_sensorium_latest.json; reports/parallel/novelty_discovery.json; "
                "reports/parallel/novel_edge.json"
            ),
            freshness_sla_seconds=3600,
            blockers=[] if mutation_wave else ["no_mutation_wave"],
            summary=artifact["summary"],
        )
        log.info("Wrote %s", OUT_DIR / "latest.json")

        ledger_record = {
            "generated_at": generated_at,
            "run_hash": run_hash,
            "health_status": health["overall_status"],
            "opportunity_count": len(opportunity_exchange),
            "constitution_rule_count": len(constitution),
            "top_wave_lane": mutation_wave[0].lane if mutation_wave else None,
            "missing_optionals": missing_optionals,
        }
        _append_jsonl(OUT_DIR / "history.jsonl", ledger_record)
        log.info("Appended to history.jsonl")
    else:
        log.info("[dry-run] Would write to %s", OUT_DIR / "latest.json")

    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-OS: meta-orchestrator for autoresearch.")
    parser.add_argument("--dry-run", action="store_true", help="Build artifact but do not write to disk.")
    args = parser.parse_args()

    try:
        artifact = run(dry_run=args.dry_run)
        print(json.dumps({"status": "ok", "summary": artifact["summary"]}, indent=2))
        sys.exit(0)
    except Exception as exc:
        log.exception("Research-OS failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
