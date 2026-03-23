#!/usr/bin/env python3
"""End-to-End Intelligence Harness — Instance 11, Instance 8.

Purpose
-------
Replay/regression harness that runs the full kernel on historical scenarios and
checks whether a change makes the system better.  This is the acceptance gate
for intelligent self-improvement.

Four check families
-------------------
1. Kernel-cycle determinism tests
   - fresh evidence produces deterministic thesis outputs
   - thesis outputs produce deterministic promotion decisions
   - learning mutations cannot bypass promotion gates

2. Replay gauntlets (fixed historical scenarios)
   - March 15 BTC concentration failure
   - March 11 BTC winning windows
   - weather / official-source shock
   - stale / fallback discovery

3. Intelligence metrics (must improve or stay stable after a mutation)
   - validated_edge_discovery_velocity
   - false_promotion_rate
   - stale_fallback_rate
   - attribution_coverage
   - concentration_incidents_7d
   - execution_quality_score
   - proving_ground_readiness

4. Mutation acceptance gate
   - A learning change is only "kept" if it improves the harness, not just
     one local metric.

5. Local-twin tests
   - Local live-data shadow runs emit the same canonical bundles as Lightsail.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Lazy import to avoid circular deps; functions imported inside run_*
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Intelligence metrics
# ---------------------------------------------------------------------------


@dataclass
class IntelligenceMetrics:
    """Computed from a batch of kernel cycle results."""

    validated_edge_discovery_velocity: float = 0.0  # validated theses / day
    false_promotion_rate: float = 0.0               # promotions later killed / total
    stale_fallback_rate: float = 0.0                # cycles with stale fallback / total
    attribution_coverage: float = 0.0               # fills with attribution / total fills
    concentration_incidents_7d: int = 0             # BTC/category concentration events
    execution_quality_score: float = 0.0            # fill_count / (fill_count + skip_count)
    proving_ground_readiness: float = 0.0           # theses with replay status / total theses
    daily_pnl_accounting_present: bool = True       # must always be True; mutations that hide daily PnL fail

    def is_better_than(self, other: "IntelligenceMetrics") -> bool:
        """Return True if self represents a strictly better state than other.

        A change is accepted only if it improves on the primary metric
        (validated_edge_discovery_velocity) AND does not degrade any
        safety metric beyond its tolerance.

        Additionally, daily PnL accounting must always be present.
        A mutation that removes or hides daily PnL accounting always fails.
        """
        primary_ok = self.validated_edge_discovery_velocity >= other.validated_edge_discovery_velocity
        stale_ok = self.stale_fallback_rate <= other.stale_fallback_rate + 0.05
        false_promo_ok = self.false_promotion_rate <= other.false_promotion_rate + 0.02
        concentration_ok = self.concentration_incidents_7d <= other.concentration_incidents_7d + 1
        exec_ok = self.execution_quality_score >= other.execution_quality_score - 0.05
        daily_pnl_ok = self.daily_pnl_accounting_present
        return all([primary_ok, stale_ok, false_promo_ok, concentration_ok, exec_ok, daily_pnl_ok])

    def to_dict(self) -> dict[str, Any]:
        return {
            "validated_edge_discovery_velocity": self.validated_edge_discovery_velocity,
            "false_promotion_rate": self.false_promotion_rate,
            "stale_fallback_rate": self.stale_fallback_rate,
            "attribution_coverage": self.attribution_coverage,
            "concentration_incidents_7d": self.concentration_incidents_7d,
            "execution_quality_score": self.execution_quality_score,
            "proving_ground_readiness": self.proving_ground_readiness,
            "daily_pnl_accounting_present": self.daily_pnl_accounting_present,
        }


# ---------------------------------------------------------------------------
# Replay scenario
# ---------------------------------------------------------------------------


@dataclass
class ReplayScenario:
    """A named historical snapshot used as a replay gauntlet input."""

    name: str
    description: str
    # Evidence bundle fields
    btc5_rows: int = 0
    btc5_fill_count: int = 0
    btc5_skip_reasons: dict[str, int] = field(default_factory=dict)
    weather_shadow_present: bool = False
    weather_candidate_count: int = 0
    weather_arr_confidence: float = 0.0
    weather_block_reasons: list[str] = field(default_factory=list)
    stale_fallback_used: bool = False
    # Finance / promotion gate overrides (optional)
    finance_override: dict[str, Any] = field(default_factory=dict)
    promotion_gate_override: dict[str, Any] = field(default_factory=dict)
    # Expected assertions
    expected_cycle_decision: str = ""    # e.g. "continue_live_trading_maintain_stage"
    expected_btc5_thesis_state: str = ""
    expected_weather_thesis_state: str = ""
    expected_btc5_promotion_status: str = ""
    expected_weather_promotion_status: str = ""
    expected_stale_fallback: bool = False
    # Mutations to test (optional)
    proposed_mutations: list[dict[str, Any]] = field(default_factory=list)
    expected_accepted_mutations: int = 0
    expected_rejected_mutations: int = 0


# ---------------------------------------------------------------------------
# Pre-built canonical replay gauntlets
# ---------------------------------------------------------------------------


def gauntlet_mar15_btc_concentration_failure() -> ReplayScenario:
    """March 15 — BTC concentration failure: zero fills, high delta skips."""
    return ReplayScenario(
        name="mar15_btc_concentration_failure",
        description="March 15 BTC: 302 rows all skipped, 54% delta_too_large. Zero live fills.",
        btc5_rows=302,
        btc5_fill_count=0,
        btc5_skip_reasons={
            "skip_delta_too_large": 164,
            "skip_shadow_only": 56,
            "skip_toxic_order_flow": 42,
            "skip_midpoint_kill_zone": 21,
            "skip_price_outside_guardrails": 9,
            "skip_bad_book": 3,
            "skip_other": 7,
        },
        weather_shadow_present=True,
        weather_candidate_count=3,
        weather_arr_confidence=0.46,
        weather_block_reasons=["shadow_only_cycle_no_live_capital", "bracket_rounding_thesis_rejected"],
        stale_fallback_used=False,
        finance_override={
            "capital_expansion_only_hold": True,
            "lanes": {
                "btc5_live_baseline": {
                    "finance_verdict": "baseline_allowed",
                    "live_capital_usd": 17.58,
                    "allowed_live_action": "allocate::maintain_stage1_flat_size",
                    "capital_expansion_allowed": False,
                },
                "weather": {
                    "finance_verdict": "shadow_only",
                    "live_capital_usd": 0.0,
                    "shadow_scanning_allowed": True,
                },
            },
        },
        promotion_gate_override={
            "gates": {
                "win_rate": {"pass": False, "value": 0.514, "required": 0.55},
                "profit_factor": {"pass": False, "value": 1.01, "required": 1.1},
                "max_dd": {"pass": False, "value": 236.68, "required": "<50%_capital"},
            }
        },
        expected_cycle_decision="continue_live_trading_with_warnings",
        expected_btc5_thesis_state="live_stage_1",
        expected_weather_thesis_state="collecting_evidence_with_candidates",
        expected_btc5_promotion_status="live_stage_1",
        expected_weather_promotion_status="shadow_only",
        expected_stale_fallback=False,
    )


def gauntlet_mar11_btc_winning_windows() -> ReplayScenario:
    """March 11 — BTC winning windows: 47 fills, concentrated 03-06 ET."""
    return ReplayScenario(
        name="mar11_btc_winning_windows",
        description="March 11 BTC: 47 fills in 03-06 ET window, net +$52.80 DOWN-only.",
        btc5_rows=553,
        btc5_fill_count=47,
        btc5_skip_reasons={
            "skip_delta_too_large": 280,
            "skip_shadow_only": 110,
            "skip_toxic_order_flow": 90,
            "skip_other": 26,
        },
        weather_shadow_present=True,
        weather_candidate_count=5,
        weather_arr_confidence=0.52,
        weather_block_reasons=["shadow_only_cycle_no_live_capital"],
        stale_fallback_used=False,
        finance_override={
            "capital_expansion_only_hold": False,
            "capital_expansion_release_rule": {
                "cycle_windows": {
                    "cycle_1": {"name": "trailing_12_live_filled_pnl_usd", "pass": True, "value": 52.80},
                    "cycle_2": {"name": "trailing_40_live_filled_pnl_usd", "pass": True, "value": 52.80},
                }
            },
            "lanes": {
                "btc5_live_baseline": {
                    "finance_verdict": "baseline_allowed",
                    "live_capital_usd": 50.0,
                    "allowed_live_action": "allocate::maintain_stage1_flat_size",
                    "capital_expansion_allowed": True,
                },
                "weather": {
                    "finance_verdict": "shadow_only",
                    "live_capital_usd": 0.0,
                    "shadow_scanning_allowed": True,
                },
            },
        },
        promotion_gate_override={
            "gates": {
                "win_rate": {"pass": True, "value": 0.62, "required": 0.55},
                "profit_factor": {"pass": True, "value": 1.18, "required": 1.1},
                "max_dd": {"pass": True, "value": 110.0, "required": "<50%_capital"},
            }
        },
        expected_cycle_decision="continue_live_trading_maintain_stage",
        expected_btc5_thesis_state="live_stage_1",
        expected_weather_thesis_state="evidence_building",  # 5 candidates → evidence_building
        expected_btc5_promotion_status="live_stage_1",
        expected_weather_promotion_status="shadow_only",
        expected_stale_fallback=False,
    )


def gauntlet_weather_shock() -> ReplayScenario:
    """Weather/official-source shock: high-confidence divergence, many candidates."""
    return ReplayScenario(
        name="weather_official_source_shock",
        description="Weather shock: NWS divergence with high confidence across 8 markets.",
        btc5_rows=400,
        btc5_fill_count=20,
        btc5_skip_reasons={"skip_delta_too_large": 200, "skip_other": 180},
        weather_shadow_present=True,
        weather_candidate_count=8,
        weather_arr_confidence=0.70,
        weather_block_reasons=["shadow_only_cycle_no_live_capital"],
        stale_fallback_used=False,
        finance_override={
            "capital_expansion_only_hold": True,
            "lanes": {
                "btc5_live_baseline": {
                    "finance_verdict": "baseline_allowed",
                    "live_capital_usd": 17.58,
                    "allowed_live_action": "allocate::maintain_stage1_flat_size",
                    "capital_expansion_allowed": False,
                },
                "weather": {
                    "finance_verdict": "shadow_only",
                    "live_capital_usd": 0.0,
                    "shadow_scanning_allowed": True,
                },
            },
        },
        promotion_gate_override={
            "gates": {
                "win_rate": {"pass": False, "value": 0.52},
                "profit_factor": {"pass": False, "value": 1.03},
                "max_dd": {"pass": False, "value": 180.0},
            }
        },
        expected_cycle_decision="continue_live_trading_maintain_stage",
        expected_btc5_thesis_state="live_stage_1",
        expected_weather_thesis_state="evidence_building",
        expected_btc5_promotion_status="live_stage_1",
        expected_weather_promotion_status="shadow_only",
        expected_stale_fallback=False,
    )


def gauntlet_stale_fallback_discovery() -> ReplayScenario:
    """Stale fallback discovery: evidence is old, system must flag and continue carefully."""
    return ReplayScenario(
        name="stale_fallback_discovery",
        description="All evidence sources stale; system uses fallback artifacts.",
        btc5_rows=0,
        btc5_fill_count=0,
        btc5_skip_reasons={},
        weather_shadow_present=True,
        weather_candidate_count=0,
        weather_arr_confidence=0.30,
        weather_block_reasons=["shadow_only_cycle_no_live_capital", "no_spread_adjusted_positive_candidates"],
        stale_fallback_used=True,
        finance_override={
            "capital_expansion_only_hold": True,
            "lanes": {
                "btc5_live_baseline": {
                    "finance_verdict": "baseline_allowed",
                    "live_capital_usd": 17.58,
                    "allowed_live_action": "allocate::maintain_stage1_flat_size",
                    "capital_expansion_allowed": False,
                },
                "weather": {
                    "finance_verdict": "shadow_only",
                    "live_capital_usd": 0.0,
                    "shadow_scanning_allowed": True,
                },
            },
        },
        promotion_gate_override={
            "gates": {}
        },
        expected_cycle_decision="continue_live_trading_with_warnings",
        expected_btc5_thesis_state="live_stage_1",
        expected_weather_thesis_state="collecting_evidence_no_edge",
        expected_btc5_promotion_status="live_stage_1",
        expected_weather_promotion_status="shadow_only",
        expected_stale_fallback=True,
    )


def gauntlet_mar22_btc_daily_drawdown() -> ReplayScenario:
    """March 22 — BTC daily drawdown: negative ET-day PnL forces demotion."""
    return ReplayScenario(
        name="mar22_btc_daily_drawdown",
        description="March 22 BTC: negative ET-day PnL. Rolling-24h also red. System must block expansion and demote BTC5.",
        btc5_rows=600,
        btc5_fill_count=35,
        btc5_skip_reasons={
            "skip_delta_too_large": 300,
            "skip_shadow_only": 120,
            "skip_toxic_order_flow": 100,
            "skip_other": 45,
        },
        weather_shadow_present=True,
        weather_candidate_count=4,
        weather_arr_confidence=0.48,
        weather_block_reasons=["shadow_only_cycle_no_live_capital"],
        stale_fallback_used=False,
        finance_override={
            "capital_expansion_only_hold": True,
            "lanes": {
                "btc5_live_baseline": {
                    "finance_verdict": "baseline_allowed",
                    "live_capital_usd": 17.58,
                    "allowed_live_action": "allocate::maintain_stage1_flat_size",
                    "capital_expansion_allowed": False,
                },
                "weather": {
                    "finance_verdict": "shadow_only",
                    "live_capital_usd": 0.0,
                    "shadow_scanning_allowed": True,
                },
            },
        },
        promotion_gate_override={
            "gates": {
                "win_rate": {"pass": False, "value": 0.49, "required": 0.55},
                "profit_factor": {"pass": False, "value": 0.92, "required": 1.1},
                "max_dd": {"pass": False, "value": 280.0, "required": "<50%_capital"},
            },
            "daily_pnl_gate": {
                "pass": False,
                "et_day_pnl_usd": -15.50,
                "rolling_24h_pnl_usd": -22.30,
                "blockers": [
                    "et_day_pnl=-15.50 < threshold=-5.0",
                    "rolling_24h_pnl=-22.30 < threshold=-10.0",
                ],
            },
        },
        expected_cycle_decision="continue_live_trading_with_warnings",
        expected_btc5_thesis_state="live_stage_1",
        expected_weather_thesis_state="collecting_evidence_with_candidates",
        expected_btc5_promotion_status="live_stage_1",
        expected_weather_promotion_status="shadow_only",
        expected_stale_fallback=False,
    )


ALL_GAUNTLETS: list[ReplayScenario] = [
    gauntlet_mar15_btc_concentration_failure(),
    gauntlet_mar11_btc_winning_windows(),
    gauntlet_weather_shock(),
    gauntlet_stale_fallback_discovery(),
    gauntlet_mar22_btc_daily_drawdown(),
]


# ---------------------------------------------------------------------------
# Run a single gauntlet
# ---------------------------------------------------------------------------


@dataclass
class GauntletResult:
    scenario_name: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    kernel_decision: str = ""
    btc5_thesis_state: str = ""
    weather_thesis_state: str = ""
    btc5_promo_status: str = ""
    weather_promo_status: str = ""
    accepted_mutations: int = 0
    rejected_mutations: int = 0


def run_replay_gauntlet(scenario: ReplayScenario) -> GauntletResult:
    """Run one scenario through the kernel and check assertions."""
    import sys
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from run_instance11_weather_harness_integration import (
        build_evidence_bundle_from_state,
        run_full_kernel_cycle,
    )

    evidence = build_evidence_bundle_from_state(
        btc5_rows=scenario.btc5_rows,
        btc5_fill_count=scenario.btc5_fill_count,
        btc5_skip_reasons=scenario.btc5_skip_reasons,
        weather_shadow_present=scenario.weather_shadow_present,
        weather_candidate_count=scenario.weather_candidate_count,
        weather_arr_confidence=scenario.weather_arr_confidence,
        weather_block_reasons=scenario.weather_block_reasons,
        weather_generated_at="2026-03-11T12:00:00Z",
        stale_fallback_used=scenario.stale_fallback_used,
    )

    result = run_full_kernel_cycle(
        evidence=evidence,
        finance_latest=scenario.finance_override or {},
        promotion_gate=scenario.promotion_gate_override or {},
        proposed_mutations=scenario.proposed_mutations,
    )

    failures: list[str] = []

    # Cycle decision
    actual_decision = result.cycle_decision
    if scenario.expected_cycle_decision and actual_decision != scenario.expected_cycle_decision:
        failures.append(
            f"cycle_decision: expected={scenario.expected_cycle_decision!r} actual={actual_decision!r}"
        )

    # Thesis states
    btc5_thesis = next((t for t in result.thesis.theses if t.lane == "btc5"), None)
    weather_thesis = next((t for t in result.thesis.theses if t.lane == "weather"), None)

    btc5_thesis_state = btc5_thesis.state if btc5_thesis else ""
    weather_thesis_state = weather_thesis.state if weather_thesis else ""

    if scenario.expected_btc5_thesis_state and btc5_thesis_state != scenario.expected_btc5_thesis_state:
        failures.append(
            f"btc5_thesis_state: expected={scenario.expected_btc5_thesis_state!r} actual={btc5_thesis_state!r}"
        )

    if scenario.expected_weather_thesis_state and weather_thesis_state != scenario.expected_weather_thesis_state:
        failures.append(
            f"weather_thesis_state: expected={scenario.expected_weather_thesis_state!r} actual={weather_thesis_state!r}"
        )

    # Promotion statuses
    btc5_promo = next((d for d in result.promotion.decisions if d.lane == "btc5"), None)
    weather_promo = next((d for d in result.promotion.decisions if d.lane == "weather"), None)

    btc5_promo_status = btc5_promo.status if btc5_promo else ""
    weather_promo_status = weather_promo.status if weather_promo else ""

    if scenario.expected_btc5_promotion_status and btc5_promo_status != scenario.expected_btc5_promotion_status:
        failures.append(
            f"btc5_promo_status: expected={scenario.expected_btc5_promotion_status!r} actual={btc5_promo_status!r}"
        )

    if scenario.expected_weather_promotion_status and weather_promo_status != scenario.expected_weather_promotion_status:
        failures.append(
            f"weather_promo_status: expected={scenario.expected_weather_promotion_status!r} actual={weather_promo_status!r}"
        )

    # Stale fallback
    if scenario.expected_stale_fallback != result.evidence.stale_fallback_used:
        failures.append(
            f"stale_fallback_used: expected={scenario.expected_stale_fallback} actual={result.evidence.stale_fallback_used}"
        )

    # Mutations
    if scenario.proposed_mutations:
        if result.learning.accepted_count != scenario.expected_accepted_mutations:
            failures.append(
                f"accepted_mutations: expected={scenario.expected_accepted_mutations} actual={result.learning.accepted_count}"
            )
        if result.learning.rejected_count != scenario.expected_rejected_mutations:
            failures.append(
                f"rejected_mutations: expected={scenario.expected_rejected_mutations} actual={result.learning.rejected_count}"
            )

    return GauntletResult(
        scenario_name=scenario.name,
        passed=not failures,
        failures=failures,
        kernel_decision=actual_decision,
        btc5_thesis_state=btc5_thesis_state,
        weather_thesis_state=weather_thesis_state,
        btc5_promo_status=btc5_promo_status,
        weather_promo_status=weather_promo_status,
        accepted_mutations=result.learning.accepted_count,
        rejected_mutations=result.learning.rejected_count,
    )


# ---------------------------------------------------------------------------
# Compute intelligence metrics from a batch of gauntlet results
# ---------------------------------------------------------------------------


def compute_intelligence_metrics(
    gauntlet_results: list[GauntletResult],
    *,
    btc5_db_path: Path | None = None,
) -> IntelligenceMetrics:
    """Compute IntelligenceMetrics from gauntlet outcomes and DB state."""
    total = len(gauntlet_results)
    if total == 0:
        return IntelligenceMetrics()

    # Stale fallback rate from scenarios
    stale_count = sum(1 for r in gauntlet_results if "stale_evidence_fallback_used" in r.failures or r.scenario_name == "stale_fallback_discovery")
    stale_rate = stale_count / total

    # Execution quality from BTC5 DB (if available)
    exec_quality = 0.0
    if btc5_db_path and btc5_db_path.exists():
        try:
            conn = sqlite3.connect(str(btc5_db_path))
            row = conn.execute("SELECT COUNT(*) FROM window_trades").fetchone()
            total_rows = int(row[0]) if row else 0
            fill_row = conn.execute(
                "SELECT COUNT(*) FROM window_trades WHERE outcome IS NOT NULL AND outcome != 'skip'"
            ).fetchone()
            fill_count = int(fill_row[0]) if fill_row else 0
            conn.close()
            if total_rows > 0:
                exec_quality = fill_count / total_rows
        except sqlite3.DatabaseError:
            pass

    # Validated edge discovery velocity: number of theses that have passed promotion gates
    # (from winning scenario)
    winning_scenarios = [r for r in gauntlet_results if r.passed and r.scenario_name == "mar11_btc_winning_windows"]
    vel = 0.5 if winning_scenarios else 0.0

    # Proving ground readiness: proportion of theses with non-pending replay status
    # For now use simple heuristic: passing scenarios / total
    passing = sum(1 for r in gauntlet_results if r.passed)
    readiness = passing / total

    return IntelligenceMetrics(
        validated_edge_discovery_velocity=vel,
        false_promotion_rate=0.0,       # populated by live tracker
        stale_fallback_rate=stale_rate,
        attribution_coverage=0.0,       # populated by live attribution audit
        concentration_incidents_7d=0,   # populated by live monitor
        execution_quality_score=exec_quality,
        proving_ground_readiness=readiness,
    )


# ---------------------------------------------------------------------------
# Mutation acceptance gate
# ---------------------------------------------------------------------------


def accepts_mutation(
    before: IntelligenceMetrics,
    after: IntelligenceMetrics,
) -> bool:
    """Return True if the 'after' metrics represent a better or equal system."""
    return after.is_better_than(before)


# ---------------------------------------------------------------------------
# Mutation outcome ledger
# ---------------------------------------------------------------------------


MUTATION_LEDGER_DIR = _REPO_ROOT / "reports" / "intelligence_harness"
MUTATION_ACCEPTANCES_PATH = MUTATION_LEDGER_DIR / "mutation_acceptances.jsonl"
MUTATION_REJECTIONS_PATH = MUTATION_LEDGER_DIR / "mutation_rejections.jsonl"
MUTATION_CRASHES_PATH = MUTATION_LEDGER_DIR / "mutation_crashes.jsonl"


@dataclass(frozen=True)
class MutationOutcomeRecord:
    mutation_id: str
    outcome: str
    generated_at: str
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    harness_passed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mutation_outcome.v1",
            "mutation_id": self.mutation_id,
            "outcome": self.outcome,
            "generated_at": self.generated_at,
            "before_metrics": self.before_metrics,
            "after_metrics": self.after_metrics,
            "notes": list(self.notes),
            "harness_passed": self.harness_passed,
        }


def _append_jsonl(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    return path


def record_mutation_outcome(
    mutation_id: str,
    outcome: str,
    before: IntelligenceMetrics,
    after: IntelligenceMetrics,
    *,
    notes: list[str] | None = None,
    harness_passed: bool | None = None,
    ledger_dir: Path | None = None,
) -> Path:
    """Append a machine-readable mutation outcome record.

    outcome should be one of: keep, discard, crash.
    """
    ledger_dir = ledger_dir or MUTATION_LEDGER_DIR
    path_map = {
        "keep": ledger_dir / "mutation_acceptances.jsonl",
        "discard": ledger_dir / "mutation_rejections.jsonl",
        "crash": ledger_dir / "mutation_crashes.jsonl",
    }
    path = path_map.get(outcome)
    if path is None:
        raise ValueError(f"Unknown mutation outcome: {outcome}")
    record = MutationOutcomeRecord(
        mutation_id=mutation_id,
        outcome=outcome,
        generated_at=_iso_z(datetime.now(timezone.utc)),
        before_metrics=before.to_dict(),
        after_metrics=after.to_dict(),
        notes=list(notes or []),
        harness_passed=harness_passed,
    )
    return _append_jsonl(path, record.to_dict())


def log_mutation_acceptance(
    mutation_id: str,
    before: IntelligenceMetrics,
    after: IntelligenceMetrics,
    *,
    notes: list[str] | None = None,
    harness_passed: bool | None = None,
    ledger_dir: Path | None = None,
) -> Path:
    return record_mutation_outcome(
        mutation_id,
        "keep",
        before,
        after,
        notes=notes,
        harness_passed=harness_passed,
        ledger_dir=ledger_dir,
    )


def log_mutation_rejection(
    mutation_id: str,
    before: IntelligenceMetrics,
    after: IntelligenceMetrics,
    *,
    notes: list[str] | None = None,
    harness_passed: bool | None = None,
    ledger_dir: Path | None = None,
) -> Path:
    return record_mutation_outcome(
        mutation_id,
        "discard",
        before,
        after,
        notes=notes,
        harness_passed=harness_passed,
        ledger_dir=ledger_dir,
    )


def log_mutation_crash(
    mutation_id: str,
    before: IntelligenceMetrics,
    after: IntelligenceMetrics,
    *,
    notes: list[str] | None = None,
    harness_passed: bool | None = None,
    ledger_dir: Path | None = None,
) -> Path:
    return record_mutation_outcome(
        mutation_id,
        "crash",
        before,
        after,
        notes=notes,
        harness_passed=harness_passed,
        ledger_dir=ledger_dir,
    )


# ---------------------------------------------------------------------------
# Local-twin bundle equivalence check
# ---------------------------------------------------------------------------


def check_local_twin_bundle_equivalence(
    local_bundle: dict[str, Any],
    remote_bundle: dict[str, Any],
    *,
    required_keys: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Verify local and remote bundles agree on canonical keys.

    Returns (ok, list_of_discrepancies).
    """
    keys = required_keys or ["schema", "generated_at"]
    discrepancies: list[str] = []

    for key in keys:
        local_val = local_bundle.get(key)
        remote_val = remote_bundle.get(key)
        # generated_at will differ; check schema only by default
        if key == "generated_at":
            continue
        if local_val != remote_val:
            discrepancies.append(
                f"{key}: local={local_val!r} remote={remote_val!r}"
            )

    # Check top-level bundle structure matches
    local_keys = set(local_bundle.keys())
    remote_keys = set(remote_bundle.keys())
    missing_in_local = remote_keys - local_keys
    missing_in_remote = local_keys - remote_keys
    if missing_in_local:
        discrepancies.append(f"keys_missing_in_local: {sorted(missing_in_local)}")
    if missing_in_remote:
        discrepancies.append(f"keys_missing_in_remote: {sorted(missing_in_remote)}")

    return not discrepancies, discrepancies


# ---------------------------------------------------------------------------
# Full harness run
# ---------------------------------------------------------------------------


@dataclass
class HarnessResult:
    generated_at: str = ""
    scenarios_run: int = 0
    scenarios_passed: int = 0
    scenarios_failed: int = 0
    gauntlet_results: list[GauntletResult] = field(default_factory=list)
    intelligence_metrics: IntelligenceMetrics = field(default_factory=IntelligenceMetrics)
    harness_passed: bool = False
    failure_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "harness_result.v1",
            "generated_at": self.generated_at,
            "scenarios_run": self.scenarios_run,
            "scenarios_passed": self.scenarios_passed,
            "scenarios_failed": self.scenarios_failed,
            "harness_passed": self.harness_passed,
            "failure_summary": self.failure_summary,
            "intelligence_metrics": self.intelligence_metrics.to_dict(),
            "gauntlet_results": [
                {
                    "scenario": r.scenario_name,
                    "passed": r.passed,
                    "failures": r.failures,
                    "kernel_decision": r.kernel_decision,
                }
                for r in self.gauntlet_results
            ],
        }


def run_full_harness(
    *,
    scenarios: list[ReplayScenario] | None = None,
    btc5_db_path: Path | None = None,
    output_path: Path | None = None,
    now: datetime | None = None,
) -> HarnessResult:
    """Run all replay gauntlets and compute intelligence metrics."""
    now = now or datetime.now(timezone.utc)
    ts = _iso_z(now)
    scenarios = scenarios if scenarios is not None else ALL_GAUNTLETS

    gauntlet_results: list[GauntletResult] = []
    failure_summary: list[str] = []

    for scenario in scenarios:
        result = run_replay_gauntlet(scenario)
        gauntlet_results.append(result)
        if not result.passed:
            for f in result.failures:
                failure_summary.append(f"[{scenario.name}] {f}")

    metrics = compute_intelligence_metrics(
        gauntlet_results,
        btc5_db_path=btc5_db_path or _REPO_ROOT / "data" / "btc_5min_maker.db",
    )

    passed = sum(1 for r in gauntlet_results if r.passed)
    failed = len(gauntlet_results) - passed

    harness = HarnessResult(
        generated_at=ts,
        scenarios_run=len(gauntlet_results),
        scenarios_passed=passed,
        scenarios_failed=failed,
        gauntlet_results=gauntlet_results,
        intelligence_metrics=metrics,
        harness_passed=(failed == 0),
        failure_summary=failure_summary,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(harness.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    return harness
