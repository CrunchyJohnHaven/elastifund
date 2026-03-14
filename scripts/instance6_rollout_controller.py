#!/usr/bin/env python3
"""Instance 6: Rollout control, finance gating, and rollback automation.

Controls the cross-asset cascade rollout ladder:
  Stage 0 — shadow_replay            (no live intents, collectors only)
  Stage 1 — shadow_live_intents      (intents generated, not executed)
  Stage 2 — single_follower_micro_live  ($5/trade, one follower asset)
  Stage 3 — two_asset_basket         ($5/trade, two follower assets)
  Stage 4 — four_asset_basket        ($5/trade, four follower assets)

Reads all node artifacts, checks staleness, enforces finance caps,
emits one operator packet with the six mandatory Instance 6 output fields.

Blocker classification:
  missing_artifact:<name>       — artifact file does not exist (resolved via fallback if available)
  stale_artifact:<name>         — artifact exists but older than freshness threshold
  no_follower_universe          — registry has no live follower rows
  negative_signal_quality:<asset> — follower win_rate < WIN_RATE_FLOOR or post_cost_ev <= 0
  stale_finance_inputs          — finance/remote-cycle artifacts are stale; hold until refreshed
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from infra.cross_asset_artifact_paths import CrossAssetArtifactPaths

# ── Finance policy caps ────────────────────────────────────────────────────────
SINGLE_ACTION_CAP_USD: float = 250.0
MONTHLY_NEW_COMMITMENT_CAP_USD: float = 1000.0
RESERVE_FLOOR_MONTHS: float = 1.0
CONFIDENCE_FLOOR: float = 0.6

# ── Rollout ladder ────────────────────────────────────────────────────────────
STAGE_SHADOW_REPLAY = 0
STAGE_SHADOW_LIVE_INTENTS = 1
STAGE_SINGLE_FOLLOWER_MICRO = 2
STAGE_TWO_ASSET_BASKET = 3
STAGE_FOUR_ASSET_BASKET = 4

STAGE_NAMES: dict[int, str] = {
    0: "shadow_replay",
    1: "shadow_live_intents",
    2: "single_follower_micro_live",
    3: "two_asset_basket",
    4: "four_asset_basket",
}
STAGE_MAX_NOTIONAL_USD: dict[int, float] = {
    0: 0.0,
    1: 0.0,
    2: 5.0,
    3: 10.0,
    4: 20.0,
}
FOLLOWER_ASSETS = ["ETH", "SOL", "XRP", "DOGE"]
STAGE_FOLLOWER_COUNTS: dict[int, int] = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4}

# Min consecutive positive-intent cycles before promotion from stage 1 → 2
MIN_POSITIVE_INTENT_CYCLES = 2
# Min candle-sets before promoting from stage 2 → 3
MIN_CANDLE_SETS_FOR_BASKET = 50
# Min win-rate to remain in live stages
WIN_RATE_FLOOR = 0.55
# Staleness thresholds (seconds)
STALE_DATA_PLANE_SECS = 60
STALE_MARKET_REGISTRY_SECS = 60
STALE_CASCADE_SIGNAL_SECS = 120
STALE_MONTE_CARLO_SECS = 360
STALE_REMOTE_CYCLE_SECS = 300
STALE_WALLET_RECONCILIATION_SECS = 900
# Wallet truth thresholds required before any live cross-asset promotion.
WALLET_SNAPSHOT_PRECISION_FLOOR = 0.99
WALLET_CLASSIFICATION_PRECISION_FLOOR = 0.95
# Retry ETA for repair branches (minutes)
REPAIR_RETRY_MINUTES = 5

# ── Artifact paths ─────────────────────────────────────────────────────────────
REPORTS = REPO_ROOT / "reports"
STATE_DIR = REPO_ROOT / "state"
PATHS = CrossAssetArtifactPaths.for_repo(REPO_ROOT)

ARTIFACT_PATHS: dict[str, tuple[Path, float]] = {
    "data_plane_health": (PATHS.data_plane_health_latest, STALE_DATA_PLANE_SECS),
    "market_registry": (REPORTS / "market_registry" / "latest.json", STALE_MARKET_REGISTRY_SECS),
    "cross_asset_cascade": (REPORTS / "cross_asset_cascade" / "latest.json", STALE_CASCADE_SIGNAL_SECS),
    "cross_asset_mc": (REPORTS / "cross_asset_mc" / "latest.json", STALE_MONTE_CARLO_SECS),
    "remote_cycle_status": (REPORTS / "remote_cycle_status.json", STALE_REMOTE_CYCLE_SECS),
    "wallet_reconciliation": (
        REPORTS / "wallet_reconciliation" / "latest.json",
        STALE_WALLET_RECONCILIATION_SECS,
    ),
    "btc5_rollout_latest": (REPORTS / "btc5_rollout_latest.json", 3600.0),
    "vendor_stack": (REPORTS / "vendor_stack" / "latest.json", 3600.0),
    "finance_latest": (REPORTS / "finance" / "latest.json", 3600.0),
    "finance_action_queue": (REPORTS / "finance" / "action_queue.json", 3600.0),
    "instance1_artifact": (PATHS.instance1_artifact_latest_json, 3600.0),
    "instance2_artifact": (REPORTS / "instance2_btc5_baseline" / "latest.json", 3600.0),
    "instance3_artifact": (REPORTS / "instance3_vendor_backfill" / "latest.json", 3600.0),
    "instance4_artifact": (REPORTS / "instance4_registry" / "latest.json", 3600.0),
    "instance5_artifact": (REPORTS / "instance5_cascade_mc" / "latest.json", 3600.0),
}

ROLLOUT_STATE_PATH = STATE_DIR / "instance6_rollout_state.json"
OUTPUT_DIR = REPORTS / "instance6_rollout_control"
OUTPUT_PATH = OUTPUT_DIR / "latest.json"
# Mirror path — one stable alias consumed by run_instance6_rollout_finance_dispatch and ops docs
MIRROR_PATH = REPORTS / "rollout_control" / "latest.json"

# ── Fallback paths (parallel → canonical for one-cycle compatibility) ───────────
# Key: same key as ARTIFACT_PATHS; Value: fallback path tried when canonical is absent.
FALLBACK_PATHS: dict[str, Path] = {
    "instance1_artifact": REPORTS / "parallel" / "instance1_multi_asset_data_plane_latest.json",
    "instance3_artifact": REPORTS / "parallel" / "instance03_cross_asset_vendor_dispatch.json",
    "instance4_artifact": REPORTS / "instance4_artifact.json",
}


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ArtifactStatus:
    name: str
    path: str
    exists: bool
    age_seconds: float | None
    stale: bool
    blocker: str | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinanceGateResult:
    passed: bool
    block_reasons: list[str] = field(default_factory=list)
    monthly_committed_usd: float = 0.0
    single_action_remaining_usd: float = SINGLE_ACTION_CAP_USD
    reserve_floor_ok: bool = True
    autonomy_mode: str = "shadow"


@dataclass
class RolloutState:
    current_stage: int = STAGE_SHADOW_REPLAY
    active_followers: list[str] = field(default_factory=list)
    cycles_at_stage: int = 0
    positive_intent_cycles: int = 0
    last_promotion_ts: str | None = None
    last_demotion_ts: str | None = None
    last_cycle_ts: str | None = None
    cumulative_candle_sets: dict[str, int] = field(default_factory=dict)


@dataclass
class RepairBranch:
    artifact: str
    blocker: str
    retry_eta_minutes: int
    action: str


@dataclass
class OperatorPacket:
    # Mandatory 6 fields (Instance 6 output contract)
    candidate_delta_arr_bps: float
    expected_improvement_velocity_delta: float
    arr_confidence_score: float
    block_reasons: list[str]
    finance_gate_pass: bool
    one_next_cycle_action: str
    # Operator decision fields
    action: str  # "promote", "hold", "demote", "rollback", "repair"
    current_stage: int
    current_stage_name: str
    target_stage: int | None
    target_stage_name: str | None
    approved_max_notional_usd: float
    active_followers: list[str]
    stale_artifacts: list[str]
    repair_branches: list[dict[str, Any]]
    finance_summary: dict[str, Any]
    wallet_reconciliation_summary: dict[str, Any]
    baseline_btc5_status: str
    cascade_trigger_score: float | None
    mc_tail_breach: bool
    generated_at: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _age_seconds(path: Path) -> float | None:
    """Seconds since file was last modified. None if file absent."""
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    now = datetime.now(timezone.utc).timestamp()
    return max(0.0, now - mtime)


def _artifact_generated_at_age(data: dict[str, Any], path: Path) -> float | None:
    """Try to read age from generated_at field; fall back to mtime."""
    gat = data.get("generated_at") or data.get("timestamp") or data.get("ts")
    if gat:
        try:
            dt = datetime.fromisoformat(str(gat))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, datetime.now(timezone.utc).timestamp() - dt.timestamp())
        except Exception:
            pass
    return _age_seconds(path)


# ── Artifact loading ───────────────────────────────────────────────────────────

def _resolve_path_spec(spec: "ArtifactPathSpec") -> Path:
    """Resolve a path spec (single Path or tuple of candidates) to the first existing path."""
    if isinstance(spec, tuple):
        for candidate in spec:
            if candidate.exists():
                return candidate
        # No candidate exists; return the first (canonical) for error reporting
        return spec[0]
    return spec


def load_all_artifacts() -> dict[str, ArtifactStatus]:
    statuses: dict[str, ArtifactStatus] = {}
    for name, (path_spec, threshold) in ARTIFACT_PATHS.items():
        # Resolve tuple-of-candidates to the first existing path
        resolved = _resolve_path_spec(path_spec)

        # If resolved canonical doesn't exist, also try explicit FALLBACK_PATHS
        if not resolved.exists() and name in FALLBACK_PATHS and FALLBACK_PATHS[name].exists():
            path = FALLBACK_PATHS[name]
        else:
            path = resolved

        exists = path.exists()
        data: dict[str, Any] = {}
        age: float | None = None
        stale = False
        blocker: str | None = None
        if exists:
            data = _load_json(path)
            age = _artifact_generated_at_age(data, path)
            if age is not None and age > threshold:
                stale = True
                blocker = (
                    f"stale_artifact:{name}:{age:.0f}s_old_threshold_{threshold:.0f}s"
                )
        else:
            blocker = f"missing_artifact:{name}"
        statuses[name] = ArtifactStatus(
            name=name,
            path=str(path),
            exists=exists,
            age_seconds=age,
            stale=stale,
            blocker=blocker,
            data=data,
        )
    return statuses


# ── Finance gate ───────────────────────────────────────────────────────────────

def _parse_finance_latest(data: dict[str, Any]) -> dict[str, Any]:
    """Extract key finance fields with safe defaults."""
    return {
        "autonomy_mode": str(data.get("autonomy_mode") or "shadow"),
        "monthly_new_committed_usd": float(data.get("monthly_new_committed_usd") or 0.0),
        "monthly_new_commitment_cap_usd": float(
            data.get("monthly_new_commitment_cap_usd") or MONTHLY_NEW_COMMITMENT_CAP_USD
        ),
        "single_action_cap_usd": float(
            data.get("single_action_cap_usd") or SINGLE_ACTION_CAP_USD
        ),
        "reserve_floor_ok": bool(data.get("reserve_floor_ok", True)),
        "cash_reserve_months": float(data.get("cash_reserve_months") or 0.0),
        "min_cash_reserve_months": float(
            data.get("min_cash_reserve_months") or RESERVE_FLOOR_MONTHS
        ),
    }


def run_finance_gate(
    artifacts: dict[str, ArtifactStatus],
    *,
    proposed_action_usd: float = 0.0,
    vendor_monthly_usd: float = 0.0,
) -> FinanceGateResult:
    """Enforce finance caps. Returns FinanceGateResult."""
    fin = _parse_finance_latest(artifacts["finance_latest"].data)
    action_queue = artifacts["finance_action_queue"].data

    blocks: list[str] = []
    autonomy = fin["autonomy_mode"]

    # Autonomy mode — shadow blocks all live-spend actions
    if autonomy == "shadow" and proposed_action_usd > 0:
        blocks.append(
            f"finance_autonomy_mode=shadow; proposed_action_usd={proposed_action_usd:.2f} blocked"
        )

    # Single-action cap
    cap = fin["single_action_cap_usd"]
    if proposed_action_usd > cap:
        blocks.append(
            f"proposed_action_usd={proposed_action_usd:.2f} exceeds single_action_cap={cap:.2f}"
        )

    # Monthly net-new commitment cap
    monthly_committed = fin["monthly_new_committed_usd"]
    monthly_cap = fin["monthly_new_commitment_cap_usd"]
    total_proposed_monthly = monthly_committed + vendor_monthly_usd
    if total_proposed_monthly > monthly_cap:
        blocks.append(
            f"monthly_committed={monthly_committed:.2f} + vendor={vendor_monthly_usd:.2f}"
            f" = {total_proposed_monthly:.2f} exceeds monthly_cap={monthly_cap:.2f}"
        )

    # Reserve floor
    reserve_ok = fin["reserve_floor_ok"]
    reserve_months = fin["cash_reserve_months"]
    min_reserve = fin["min_cash_reserve_months"]
    if not reserve_ok or (reserve_months > 0 and reserve_months < min_reserve):
        blocks.append(
            f"cash_reserve_months={reserve_months:.2f} below floor={min_reserve:.2f}"
        )
        reserve_ok = False

    # Queued actions that exceed caps
    queued_actions = action_queue.get("actions") or []
    for qa in queued_actions:
        qa_usd = float(qa.get("amount_usd") or 0.0)
        if qa_usd > cap:
            blocks.append(
                f"queued_action '{qa.get('description', '?')}' "
                f"amount={qa_usd:.2f} exceeds single_action_cap={cap:.2f}"
            )

    return FinanceGateResult(
        passed=len(blocks) == 0,
        block_reasons=blocks,
        monthly_committed_usd=monthly_committed,
        single_action_remaining_usd=max(0.0, cap - proposed_action_usd),
        reserve_floor_ok=reserve_ok,
        autonomy_mode=autonomy,
    )


# ── Rollout state ─────────────────────────────────────────────────────────────

def load_rollout_state() -> RolloutState:
    data = _load_json(ROLLOUT_STATE_PATH)
    return RolloutState(
        current_stage=int(data.get("current_stage") or STAGE_SHADOW_REPLAY),
        active_followers=list(data.get("active_followers") or []),
        cycles_at_stage=int(data.get("cycles_at_stage") or 0),
        positive_intent_cycles=int(data.get("positive_intent_cycles") or 0),
        last_promotion_ts=data.get("last_promotion_ts"),
        last_demotion_ts=data.get("last_demotion_ts"),
        last_cycle_ts=data.get("last_cycle_ts"),
        cumulative_candle_sets=dict(data.get("cumulative_candle_sets") or {}),
    )


def save_rollout_state(state: RolloutState) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(ROLLOUT_STATE_PATH, asdict(state))


# ── Baseline BTC5 health ───────────────────────────────────────────────────────

def check_btc5_baseline(artifacts: dict[str, ArtifactStatus]) -> tuple[str, bool]:
    """Return (status_label, is_healthy)."""
    cycle = artifacts["remote_cycle_status"].data
    rollout = artifacts["btc5_rollout_latest"].data
    instance2 = artifacts["instance2_artifact"].data

    if not cycle and not rollout:
        return "unknown_missing_artifacts", False

    baseline_contract = (
        instance2.get("baseline_contract") if isinstance(instance2.get("baseline_contract"), dict) else {}
    )
    if baseline_contract:
        baseline_status = str(baseline_contract.get("baseline_status") or "").strip().lower()
        finance_gate_pass = bool(
            baseline_contract.get("finance_gate_pass")
            if baseline_contract.get("finance_gate_pass") is not None
            else (instance2.get("required_outputs") or {}).get("finance_gate_pass", True)
        )
        if not finance_gate_pass:
            return "btc5_baseline_finance_gate_fail", False
        if baseline_status in {"baseline_live_ok", "baseline_shadow_only"}:
            return "btc5_running", True
        if baseline_status:
            return baseline_status, False

    # BTC5 considered healthy if service is running and stage >= 0
    service_running = bool(
        cycle.get("btc5_service_running")
        or rollout.get("service_running")
        or rollout.get("deploy_mode") in {"live_stage1", "shadow_probe"}
    )
    if not service_running:
        return "btc5_service_not_running", False

    # Check that baseline is not regressed
    if instance2:
        base_pass = bool(instance2.get("finance_gate_pass", True))
        if not base_pass:
            return "btc5_baseline_finance_gate_fail", False

    return "btc5_running", True


# ── Cascade & MC health ────────────────────────────────────────────────────────

def _cascade_trigger_score(artifacts: dict[str, ArtifactStatus]) -> float | None:
    data = artifacts["cross_asset_cascade"].data
    if not data:
        return None
    score = data.get("trigger_score")
    if score is None:
        return None
    return float(score)


def _mc_tail_breach(artifacts: dict[str, ArtifactStatus]) -> bool:
    data = artifacts["cross_asset_mc"].data
    if not data:
        return False
    return bool(data.get("tail_breach") or data.get("drawdown_stress_breach") or False)


def _shadow_intended_notional(artifacts: dict[str, ArtifactStatus]) -> float:
    cascade = artifacts["cross_asset_cascade"].data
    if not cascade:
        return 0.0
    intents = cascade.get("shadow_intended_notional_usd")
    if intents is None:
        return 0.0
    return float(intents)


def _follower_stats(artifacts: dict[str, ArtifactStatus]) -> dict[str, dict[str, Any]]:
    """Extract per-follower win_rate, candle_sets, post_cost_ev from cascade artifact."""
    cascade = artifacts["cross_asset_cascade"].data
    if not cascade:
        return {}
    follower_data = cascade.get("followers") or {}
    result: dict[str, dict[str, Any]] = {}
    for asset in FOLLOWER_ASSETS:
        info = follower_data.get(asset) or {}
        post_cost_ev = info.get("post_cost_ev")
        if post_cost_ev is None:
            post_cost_ev = float(info.get("post_cost_ev_bps") or 0.0) / 10_000.0
        result[asset] = {
            "win_rate": float(info.get("win_rate") or 0.0),
            "candle_sets": int(info.get("candle_sets") or 0),
            "post_cost_ev": float(post_cost_ev or 0.0),
            "auto_killed": bool(info.get("auto_killed") or False),
        }
    return result


def _wallet_reconciliation_summary(artifacts: dict[str, ArtifactStatus]) -> dict[str, Any]:
    artifact = artifacts.get("wallet_reconciliation")
    data = dict((artifact.data if artifact is not None else {}) or {})
    phantom_ids = [
        str(item)
        for item in list(data.get("phantom_local_open_trade_ids") or [])
        if str(item).strip()
    ]
    snapshot_precision = float(data.get("snapshot_precision") or 0.0)
    classification_precision = float(data.get("classification_precision") or 0.0)
    ready = (
        artifact is not None
        and artifact.exists
        and not artifact.stale
        and snapshot_precision >= WALLET_SNAPSHOT_PRECISION_FLOOR
        and classification_precision >= WALLET_CLASSIFICATION_PRECISION_FLOOR
        and not phantom_ids
    )
    return {
        "exists": bool(artifact and artifact.exists),
        "stale": bool(artifact and artifact.stale),
        "age_seconds": artifact.age_seconds if artifact is not None else None,
        "snapshot_precision": snapshot_precision,
        "classification_precision": classification_precision,
        "phantom_local_open_trade_ids": phantom_ids,
        "phantom_local_open_trade_count": len(phantom_ids),
        "ready": ready,
    }


def _wallet_reconciliation_blockers(artifacts: dict[str, ArtifactStatus]) -> list[str]:
    summary = _wallet_reconciliation_summary(artifacts)
    blockers: list[str] = []
    if not summary["exists"]:
        return blockers
    if summary["stale"]:
        return blockers
    if summary["snapshot_precision"] < WALLET_SNAPSHOT_PRECISION_FLOOR:
        blockers.append(
            "wallet_reconciliation_not_ready:"
            f"snapshot_precision={summary['snapshot_precision']:.3f}"
        )
    if summary["classification_precision"] < WALLET_CLASSIFICATION_PRECISION_FLOOR:
        blockers.append(
            "wallet_reconciliation_not_ready:"
            f"classification_precision={summary['classification_precision']:.3f}"
        )
    phantom_count = int(summary["phantom_local_open_trade_count"])
    if phantom_count > 0:
        blockers.append(
            "wallet_reconciliation_not_ready:"
            f"phantom_open_trades={phantom_count}"
        )
    return blockers


def _pick_best_follower(follower_stats: dict[str, dict[str, Any]]) -> str | None:
    """Pick the follower with the highest win_rate that hasn't been auto-killed."""
    candidates = [
        (asset, s)
        for asset, s in follower_stats.items()
        if not s["auto_killed"] and s["win_rate"] >= WIN_RATE_FLOOR and s["post_cost_ev"] > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[1]["win_rate"])[0]


# ── Promotion/demotion logic ───────────────────────────────────────────────────

def evaluate_stage_transition(
    state: RolloutState,
    artifacts: dict[str, ArtifactStatus],
    finance: FinanceGateResult,
    *,
    dry_run: bool = False,
) -> tuple[str, int | None, list[str]]:
    """
    Returns (action, target_stage, block_reasons).
    action is one of: "promote", "hold", "demote", "rollback", "repair".
    target_stage is the proposed next stage, or None if holding.
    """
    stage = state.current_stage
    blocks: list[str] = []

    # Collect stale artifacts that block execution
    stale_names = [
        name
        for name, s in artifacts.items()
        if s.blocker and s.stale
    ]
    missing_critical = [
        name
        for name in ("data_plane_health", "market_registry")
        if not artifacts[name].exists
    ]

    # --- Failsafe: MC tail breach → rollback to stage 0 ---
    if _mc_tail_breach(artifacts) and stage >= STAGE_SINGLE_FOLLOWER_MICRO:
        blocks.append("mc_tail_breach: cut sizing to zero, revert to BTC5 baseline")
        return "rollback", STAGE_SHADOW_REPLAY, blocks

    # --- Failsafe: BTC5 baseline must stay running ---
    baseline_status, baseline_ok = check_btc5_baseline(artifacts)
    if not baseline_ok and stage >= STAGE_SHADOW_LIVE_INTENTS:
        blocks.append(f"btc5_baseline_unhealthy: {baseline_status}")
        return "demote", STAGE_SHADOW_REPLAY, blocks

    # --- Repair branch: missing critical artifacts (highest priority) ---
    if missing_critical:
        for name in missing_critical:
            blocks.append(f"missing_artifact:{name}")
        return "repair", None, blocks

    # --- Stale finance / remote-cycle inputs → explicit hold_repair, 5-min retry ---
    stale_finance = [
        name
        for name in ("finance_latest", "finance_action_queue", "remote_cycle_status")
        if artifacts[name].stale
    ]
    if stale_finance:
        for sf in stale_finance:
            blocks.append(f"stale_finance_inputs:{sf}")
        return "repair", None, blocks

    if stale_names:
        # Stale artifacts in live stages → demote to shadow
        if stage >= STAGE_SINGLE_FOLLOWER_MICRO:
            for sn in stale_names:
                blocks.append(f"stale_artifact:{sn}_in_live_stage")
            return "demote", STAGE_SHADOW_LIVE_INTENTS, blocks
        # In shadow stages, just hold with repair
        for sn in stale_names:
            blocks.append(f"stale_artifact:{sn}_blocks_promotion")
        return "repair", None, blocks

    wallet_reconciliation = _wallet_reconciliation_summary(artifacts)
    wallet_blockers = _wallet_reconciliation_blockers(artifacts)
    if stage >= STAGE_SINGLE_FOLLOWER_MICRO and not wallet_reconciliation["ready"]:
        if not wallet_reconciliation["exists"]:
            blocks.append("missing_artifact:wallet_reconciliation")
        else:
            blocks.extend(wallet_blockers or ["wallet_reconciliation_not_ready"])
        return "demote", STAGE_SHADOW_LIVE_INTENTS, blocks

    # --- Promotion evaluation ---
    if stage == STAGE_SHADOW_REPLAY:
        # Promote to shadow_live_intents when:
        # cascade + MC artifacts exist and are fresh, correlation valid, no baseline regression
        cascade_ok = artifacts["cross_asset_cascade"].exists and not artifacts["cross_asset_cascade"].stale
        mc_ok = artifacts["cross_asset_mc"].exists and not artifacts["cross_asset_mc"].stale
        registry_ok = artifacts["market_registry"].exists and not artifacts["market_registry"].stale
        if cascade_ok and mc_ok and registry_ok:
            return "promote", STAGE_SHADOW_LIVE_INTENTS, []
        if not cascade_ok:
            blocks.append("cross_asset_cascade not ready or stale")
        if not mc_ok:
            blocks.append("cross_asset_mc not ready or stale")
        if not registry_ok:
            blocks.append("market_registry not ready or stale")
        return "hold", None, blocks

    if stage == STAGE_SHADOW_LIVE_INTENTS:
        # Promote to single_follower_micro_live when:
        # 2+ consecutive positive-intent cycles, finance gate passes, BTC5 baseline running
        shadow_notional = _shadow_intended_notional(artifacts)
        if shadow_notional > 0:
            new_pos_cycles = state.positive_intent_cycles + 1
        else:
            new_pos_cycles = 0

        if new_pos_cycles >= MIN_POSITIVE_INTENT_CYCLES and baseline_ok:
            if not wallet_reconciliation["exists"]:
                blocks.append("missing_artifact:wallet_reconciliation")
                return "repair", None, blocks
            if not wallet_reconciliation["ready"]:
                blocks.extend(wallet_blockers or ["wallet_reconciliation_not_ready"])
                return "hold", None, blocks
            # Finance gate for live execution
            if not finance.passed:
                blocks.extend(finance.block_reasons)
                return "hold", None, blocks
            follower_stats = _follower_stats(artifacts)
            best = _pick_best_follower(follower_stats)
            if best is None:
                # Distinguish between no followers at all vs quality failures
                if not any(s["candle_sets"] > 0 for s in follower_stats.values()):
                    blocks.append("no_follower_universe")
                else:
                    for asset, s in follower_stats.items():
                        if s["candle_sets"] > 0 and not s["auto_killed"]:
                            if s["win_rate"] < WIN_RATE_FLOOR or s["post_cost_ev"] <= 0:
                                blocks.append(f"negative_signal_quality:{asset}")
                    if not blocks:
                        blocks.append("no_follower_passes_win_rate_and_ev_thresholds")
                return "hold", None, blocks
            return "promote", STAGE_SINGLE_FOLLOWER_MICRO, []

        if new_pos_cycles < MIN_POSITIVE_INTENT_CYCLES:
            blocks.append(
                f"positive_intent_cycles={new_pos_cycles} < required={MIN_POSITIVE_INTENT_CYCLES}"
            )
        if not baseline_ok:
            blocks.append(f"btc5_baseline_required: {baseline_status}")
        return "hold", None, blocks

    if stage == STAGE_SINGLE_FOLLOWER_MICRO:
        # Promote to two_asset_basket when:
        # 50+ candle-sets on active follower, win_rate >= 55%, post_cost EV > 0, finance gate
        follower_stats = _follower_stats(artifacts)
        active = state.active_followers
        if not active:
            blocks.append("no_active_follower_in_single_follower_stage")
            return "hold", None, blocks

        lead = active[0]
        stats = follower_stats.get(lead) or {}
        candle_sets = state.cumulative_candle_sets.get(lead, 0) + stats.get("candle_sets", 0)
        win_rate = stats.get("win_rate", 0.0)
        post_cost_ev = stats.get("post_cost_ev", 0.0)
        auto_killed = stats.get("auto_killed", False)

        if auto_killed:
            blocks.append(f"active_follower_{lead}_auto_killed")
            return "demote", STAGE_SHADOW_LIVE_INTENTS, blocks

        if win_rate < WIN_RATE_FLOOR:
            blocks.append(f"{lead}_win_rate={win_rate:.3f} < floor={WIN_RATE_FLOOR}")
        if post_cost_ev <= 0:
            blocks.append(f"{lead}_post_cost_ev={post_cost_ev:.4f} not positive")
        if candle_sets < MIN_CANDLE_SETS_FOR_BASKET:
            blocks.append(
                f"{lead}_candle_sets={candle_sets} < required={MIN_CANDLE_SETS_FOR_BASKET}"
            )

        if not blocks and not finance.passed:
            blocks.extend(finance.block_reasons)

        if not blocks:
            # Find a second follower
            second = _pick_best_follower({a: s for a, s in follower_stats.items() if a != lead})
            if second is None:
                blocks.append("no_second_follower_passes_thresholds_for_two_asset_basket")
                return "hold", None, blocks
            return "promote", STAGE_TWO_ASSET_BASKET, []
        return "hold", None, blocks

    if stage == STAGE_TWO_ASSET_BASKET:
        # Promote to four_asset_basket when:
        # both active followers pass win_rate and EV, no correlation collapse, finance gate
        follower_stats = _follower_stats(artifacts)
        cascade = artifacts["cross_asset_cascade"].data
        correlation_collapse = bool(cascade.get("correlation_collapse") or False)

        if correlation_collapse:
            blocks.append("correlation_collapse_detected: demoting to shadow_live_intents")
            return "demote", STAGE_SHADOW_LIVE_INTENTS, blocks

        active = state.active_followers
        fail_count = 0
        for asset in active[:2]:
            stats = follower_stats.get(asset) or {}
            if stats.get("auto_killed"):
                blocks.append(f"{asset}_auto_killed")
                fail_count += 1
            elif stats.get("win_rate", 0.0) < WIN_RATE_FLOOR:
                blocks.append(f"{asset}_win_rate={stats.get('win_rate', 0):.3f} < floor")
                fail_count += 1
            elif stats.get("post_cost_ev", 0.0) <= 0:
                blocks.append(f"{asset}_post_cost_ev not positive")
                fail_count += 1

        if fail_count >= 2:
            return "demote", STAGE_SHADOW_LIVE_INTENTS, blocks

        if blocks:
            return "hold", None, blocks

        if not finance.passed:
            blocks.extend(finance.block_reasons)
            return "hold", None, blocks

        # Need all 4 followers to pass for promotion
        viable = [
            a for a in FOLLOWER_ASSETS
            if not (follower_stats.get(a) or {}).get("auto_killed")
            and (follower_stats.get(a) or {}).get("win_rate", 0.0) >= WIN_RATE_FLOOR
            and (follower_stats.get(a) or {}).get("post_cost_ev", 0.0) > 0
        ]
        if len(viable) < 4:
            blocks.append(
                f"only_{len(viable)}_of_4_followers_pass_thresholds_for_four_asset_basket"
            )
            return "hold", None, blocks
        return "promote", STAGE_FOUR_ASSET_BASKET, []

    # Already at max stage: hold
    return "hold", None, []


# ── State update ───────────────────────────────────────────────────────────────

def apply_transition(
    state: RolloutState,
    action: str,
    target_stage: int | None,
    artifacts: dict[str, ArtifactStatus],
) -> RolloutState:
    """Return updated RolloutState after applying the transition."""
    now = _utc_now()
    stage = state.current_stage

    if action == "promote" and target_stage is not None and target_stage > stage:
        follower_stats = _follower_stats(artifacts)
        # Determine active followers for new stage
        n_followers = STAGE_FOLLOWER_COUNTS.get(target_stage, 0)
        viable = [
            a for a in FOLLOWER_ASSETS
            if not (follower_stats.get(a) or {}).get("auto_killed")
            and (
                target_stage <= STAGE_SHADOW_LIVE_INTENTS
                or (
                    (follower_stats.get(a) or {}).get("win_rate", 0.0) >= WIN_RATE_FLOOR
                    and (follower_stats.get(a) or {}).get("post_cost_ev", 0.0) > 0
                )
            )
        ]
        active = viable[:n_followers]
        return RolloutState(
            current_stage=target_stage,
            active_followers=active,
            cycles_at_stage=0,
            positive_intent_cycles=state.positive_intent_cycles,
            last_promotion_ts=now,
            last_demotion_ts=state.last_demotion_ts,
            last_cycle_ts=now,
            cumulative_candle_sets=dict(state.cumulative_candle_sets),
        )

    if action in ("demote", "rollback") and target_stage is not None and target_stage < stage:
        return RolloutState(
            current_stage=target_stage,
            active_followers=[],
            cycles_at_stage=0,
            positive_intent_cycles=0,
            last_promotion_ts=state.last_promotion_ts,
            last_demotion_ts=now,
            last_cycle_ts=now,
            cumulative_candle_sets=dict(state.cumulative_candle_sets),
        )

    # hold / repair: tick cycle count and update intent cycles
    shadow_notional = _shadow_intended_notional(artifacts)
    new_pos = (state.positive_intent_cycles + 1) if shadow_notional > 0 else 0

    # Update candle sets for active followers
    follower_stats = _follower_stats(artifacts)
    updated_candle_sets = dict(state.cumulative_candle_sets)
    for asset in state.active_followers:
        delta = (follower_stats.get(asset) or {}).get("candle_sets", 0)
        updated_candle_sets[asset] = updated_candle_sets.get(asset, 0) + delta

    return RolloutState(
        current_stage=stage,
        active_followers=list(state.active_followers),
        cycles_at_stage=state.cycles_at_stage + 1,
        positive_intent_cycles=new_pos,
        last_promotion_ts=state.last_promotion_ts,
        last_demotion_ts=state.last_demotion_ts,
        last_cycle_ts=now,
        cumulative_candle_sets=updated_candle_sets,
    )


# ── Repair branches ────────────────────────────────────────────────────────────

def build_repair_branches(
    artifacts: dict[str, ArtifactStatus],
    action: str,
) -> list[RepairBranch]:
    branches: list[RepairBranch] = []
    if action not in ("repair", "hold"):
        return branches
    for name, status in artifacts.items():
        if status.blocker:
            if not status.exists:
                repair_action = f"run_{name}_collector_to_generate_artifact"
            elif status.stale:
                repair_action = f"refresh_{name}_within_{REPAIR_RETRY_MINUTES}min"
            else:
                repair_action = f"investigate_{name}_blocker"
            branches.append(
                RepairBranch(
                    artifact=name,
                    blocker=status.blocker,
                    retry_eta_minutes=REPAIR_RETRY_MINUTES,
                    action=repair_action,
                )
            )
    return branches


# ── ARR estimate ──────────────────────────────────────────────────────────────

def estimate_arr_delta(stage: int, target_stage: int | None, finance: FinanceGateResult) -> float:
    """Rough estimate of ARR delta in bps from moving to target stage."""
    if target_stage is None or target_stage <= stage:
        return 0.0
    # Stage 2 adds ~1 follower × $5 × ~60% WR × 288 candles/day × 365 days
    # Approximate at 150 bps ARR uplift per follower per stage step
    n_new_followers = STAGE_FOLLOWER_COUNTS.get(target_stage, 0) - STAGE_FOLLOWER_COUNTS.get(stage, 0)
    if n_new_followers <= 0:
        return 0.0
    arr_bps_per_follower = 150.0
    return round(n_new_followers * arr_bps_per_follower, 1)


def estimate_confidence(artifacts: dict[str, ArtifactStatus], stage: int) -> float:
    """Aggregate confidence score from instance artifacts."""
    scores: list[float] = []
    for inst_name in ("instance1_artifact", "instance2_artifact", "instance4_artifact", "instance5_artifact"):
        data = artifacts[inst_name].data
        score = data.get("arr_confidence_score")
        if score is not None:
            try:
                scores.append(float(score))
            except (TypeError, ValueError):
                pass
    if not scores:
        # Fall back: lower confidence for higher stages without upstream attestation
        return max(0.0, 0.7 - stage * 0.1)
    return round(sum(scores) / len(scores), 3)


def improvement_velocity_delta(artifacts: dict[str, ArtifactStatus]) -> float:
    """Sum of improvement velocity deltas from all instance artifacts."""
    total = 0.0
    for inst_name in ("instance1_artifact", "instance2_artifact", "instance3_artifact",
                      "instance4_artifact", "instance5_artifact"):
        data = artifacts[inst_name].data
        delta = data.get("expected_improvement_velocity_delta")
        if delta is not None:
            try:
                total += float(delta)
            except (TypeError, ValueError):
                pass
    return round(total, 4)


# ── Vendor finance check ───────────────────────────────────────────────────────

def _vendor_monthly_usd(artifacts: dict[str, ArtifactStatus]) -> float:
    data = artifacts["vendor_stack"].data
    if not data:
        return 0.0
    rec = data.get("recommended_vendor") or {}
    return float(rec.get("monthly_usd") or 0.0)


# ── Main run ───────────────────────────────────────────────────────────────────

def run(
    *,
    dry_run: bool = False,
    force_stage: int | None = None,
    output_path: Path = OUTPUT_PATH,
) -> OperatorPacket:
    now = _utc_now()

    # 1. Load artifacts
    artifacts = load_all_artifacts()

    # 2. Load persistent rollout state
    state = load_rollout_state()
    if force_stage is not None:
        state = RolloutState(current_stage=force_stage)

    # 3. Finance gate
    vendor_monthly = _vendor_monthly_usd(artifacts)
    proposed_usd = STAGE_MAX_NOTIONAL_USD.get(state.current_stage + 1, 0.0)
    finance = run_finance_gate(
        artifacts,
        proposed_action_usd=proposed_usd,
        vendor_monthly_usd=vendor_monthly,
    )

    # 4. Stage transition
    action, target_stage, block_reasons = evaluate_stage_transition(
        state, artifacts, finance, dry_run=dry_run
    )

    # Merge finance blocks into block_reasons if gate failed
    if not finance.passed and action not in ("rollback", "repair", "demote"):
        for b in finance.block_reasons:
            if b not in block_reasons:
                block_reasons.append(b)

    # 5. Repair branches (populated on repair/hold only)
    repair_branches = build_repair_branches(artifacts, action)

    # 6. Compute stale artifact list
    stale_artifacts = [name for name, s in artifacts.items() if s.stale]

    # 7. Cascade metrics
    trigger_score = _cascade_trigger_score(artifacts)
    mc_tail = _mc_tail_breach(artifacts)

    # 8. ARR / confidence / velocity
    arr_delta = estimate_arr_delta(state.current_stage, target_stage, finance)
    confidence = estimate_confidence(artifacts, state.current_stage)
    vel_delta = improvement_velocity_delta(artifacts)
    wallet_reconciliation = _wallet_reconciliation_summary(artifacts)

    # 9. Baseline status
    baseline_status, _ = check_btc5_baseline(artifacts)

    # 10. Approved notional for current stage
    approved_notional = STAGE_MAX_NOTIONAL_USD.get(state.current_stage, 0.0)

    # 11. Active followers at current stage
    active_followers = list(state.active_followers)
    if not active_followers and state.current_stage >= STAGE_SINGLE_FOLLOWER_MICRO:
        follower_stats = _follower_stats(artifacts)
        n = STAGE_FOLLOWER_COUNTS.get(state.current_stage, 0)
        viable = [
            a for a in FOLLOWER_ASSETS
            if not (follower_stats.get(a) or {}).get("auto_killed")
        ]
        active_followers = viable[:n]

    # 12. One next-cycle action
    if action == "promote" and target_stage is not None:
        next_action = (
            f"advance_rollout_from_{STAGE_NAMES[state.current_stage]}"
            f"_to_{STAGE_NAMES[target_stage]}"
        )
    elif action in ("demote", "rollback") and target_stage is not None:
        next_action = (
            f"revert_rollout_to_{STAGE_NAMES[target_stage]}_and_audit_blockers"
        )
    elif action == "repair":
        top = repair_branches[0].action if repair_branches else "refresh_stale_artifacts"
        next_action = f"repair: {top}"
    else:
        next_action = (
            f"hold_at_{STAGE_NAMES[state.current_stage]}_"
            f"cycles={state.cycles_at_stage + 1}_"
            f"await_{"positive_intents" if state.current_stage == STAGE_SHADOW_LIVE_INTENTS else "thresholds"}"
        )

    packet = OperatorPacket(
        candidate_delta_arr_bps=arr_delta,
        expected_improvement_velocity_delta=vel_delta,
        arr_confidence_score=confidence,
        block_reasons=block_reasons,
        finance_gate_pass=finance.passed,
        one_next_cycle_action=next_action,
        action=action,
        current_stage=state.current_stage,
        current_stage_name=STAGE_NAMES[state.current_stage],
        target_stage=target_stage,
        target_stage_name=STAGE_NAMES[target_stage] if target_stage is not None else None,
        approved_max_notional_usd=approved_notional,
        active_followers=active_followers,
        stale_artifacts=stale_artifacts,
        repair_branches=[asdict(b) for b in repair_branches],
        finance_summary={
            "autonomy_mode": finance.autonomy_mode,
            "monthly_committed_usd": finance.monthly_committed_usd,
            "single_action_remaining_usd": finance.single_action_remaining_usd,
            "reserve_floor_ok": finance.reserve_floor_ok,
            "vendor_monthly_usd_proposed": vendor_monthly,
        },
        wallet_reconciliation_summary=wallet_reconciliation,
        baseline_btc5_status=baseline_status,
        cascade_trigger_score=trigger_score,
        mc_tail_breach=mc_tail,
        generated_at=now,
    )

    # 13. Persist updated state (unless dry_run)
    if not dry_run:
        new_state = apply_transition(state, action, target_stage, artifacts)
        save_rollout_state(new_state)
        payload = asdict(packet)
        payload["schema"] = "instance6_rollout_control.v2"
        _write_json(output_path, payload)
        # Mirror to reports/rollout_control/latest.json (consumed by finance dispatch + ops docs)
        _write_json(MIRROR_PATH, payload)

    return packet


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Instance 6: Rollout controller, finance gating, and rollback automation."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate transitions without persisting state or writing artifacts.",
    )
    p.add_argument(
        "--force-stage",
        type=int,
        choices=list(STAGE_NAMES.keys()),
        default=None,
        metavar="N",
        help="Override current stage for this run only (0–4).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output JSON path (default: {OUTPUT_PATH})",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    packet = run(
        dry_run=args.dry_run,
        force_stage=args.force_stage,
        output_path=args.output,
    )

    print(json.dumps(asdict(packet), indent=2, sort_keys=True))

    # Exit non-zero if we are blocked on critical issues
    if packet.action == "repair" and not packet.block_reasons:
        return 0
    if packet.action in ("rollback", "demote"):
        return 2
    if packet.block_reasons:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
