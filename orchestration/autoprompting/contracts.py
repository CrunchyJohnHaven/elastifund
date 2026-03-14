"""Autoprompt control-plane guardrail contracts for bounded autonomy."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Sequence


FIRST_CLASS_ADAPTERS: dict[str, dict[str, Any]] = {
    "codex_local": {
        "adapter": "codex_local",
        "kind": "local_cli",
        "enabled": True,
        "default_budget_tier": "medium",
        "allowed_tiers": [0, 1, 2, 3],
    },
    "claude_code_cli": {
        "adapter": "claude_code_cli",
        "kind": "local_cli",
        "enabled": True,
        "default_budget_tier": "medium",
        "allowed_tiers": [0, 1, 2, 3],
    },
    "openai_api": {
        "adapter": "openai_api",
        "kind": "remote_api",
        "enabled": True,
        "default_budget_tier": "high",
        "allowed_tiers": [0, 1, 2, 3],
    },
    "anthropic_api": {
        "adapter": "anthropic_api",
        "kind": "remote_api",
        "enabled": True,
        "default_budget_tier": "high",
        "allowed_tiers": [0, 1, 2, 3],
    },
}

SEAT_BRIDGE_ADAPTER: dict[str, Any] = {
    "adapter": "browser_seat_bridge",
    "kind": "seat_bridge",
    "enabled": False,
    "enabled_by_default": False,
    "allowed_tiers": [1, 2],
    "allowed_lane_classes": ["research", "docs"],
    "notes": "Disabled by default and never eligible for governance authority.",
}

PROVIDER_DENYLIST = {
    "openclaw",
    "openclaw_benchmark",
    "hermes",
    "hermes_supervisor",
}

RESEARCH_DOC_TOKENS = {
    "research",
    "docs",
    "operator",
    "packet",
    "sync",
}

TIER3_PREFIXES = (
    "bot/",
    "execution/",
    "strategies/",
    "signals/",
    "nontrading/finance/",
)

TIER1_PREFIXES = (
    "docs/",
    "research/",
    "reports/",
)

TIER2_PREFIXES = (
    "scripts/",
    "src/",
    "backtest/",
    "simulator/",
    "orchestration/",
    "hub/",
    "data_layer/",
    "inventory/",
)


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_path(path: str) -> str:
    cleaned = str(path or "").strip().replace("\\", "/")
    if not cleaned:
        return ""
    return str(PurePosixPath(cleaned.lstrip("./")))


def classify_path_tier(path: str) -> int:
    """Classify a repository path into an autonomy tier."""

    normalized = _normalize_path(path)
    if not normalized:
        return 0
    if any(normalized.startswith(prefix) for prefix in TIER3_PREFIXES):
        return 3
    if any(normalized.startswith(prefix) for prefix in TIER1_PREFIXES):
        return 1
    if any(normalized.startswith(prefix) for prefix in TIER2_PREFIXES):
        return 2
    return 2


def infer_autonomy_tier(changed_paths: Sequence[str]) -> int:
    """Return the strictest tier implied by the changed path set."""

    if not changed_paths:
        return 0
    return max(classify_path_tier(path) for path in changed_paths)


def _lane_class(lane_name: str, changed_paths: Sequence[str]) -> str:
    normalized_lane = str(lane_name or "").strip().lower()
    if any(token in normalized_lane for token in RESEARCH_DOC_TOKENS):
        return "research" if "research" in normalized_lane else "docs"
    if changed_paths and all(classify_path_tier(path) == 1 for path in changed_paths):
        if all(_normalize_path(path).startswith("docs/") for path in changed_paths):
            return "docs"
        return "research"
    return "implementation"


def build_worker_adapter_contract() -> dict[str, Any]:
    """Return the canonical worker adapter contract payload."""

    return {
        "schema_version": "worker_adapter.v1",
        "first_class_adapters": {
            key: dict(value)
            for key, value in FIRST_CLASS_ADAPTERS.items()
        },
        "restricted_adapters": {
            "browser_seat_bridge": dict(SEAT_BRIDGE_ADAPTER),
        },
        "provider_boundary": {
            "openclaw_mode": "comparison_only",
            "openclaw_allocator_eligible": False,
            "supervisor_governance_authority": False,
            "governance_lock": {
                "truth_precedence": "elastifund_control_plane_only",
                "live_risk_policy": "elastifund_control_plane_only",
                "merge_policy": "elastifund_control_plane_only",
                "treasury_policy": "elastifund_control_plane_only",
            },
            "forbidden_governors": ["openclaw", "hermes_like", "browser_seat_bridge"],
        },
    }


def evaluate_worker_adapter(
    *,
    adapter: str,
    lane_name: str,
    changed_paths: Sequence[str],
    seat_bridge_enabled: bool = False,
) -> dict[str, Any]:
    """Evaluate whether a worker adapter can run in the current lane/tier."""

    requested = str(adapter or "").strip().lower()
    tier = infer_autonomy_tier(changed_paths)
    lane_class = _lane_class(lane_name=lane_name, changed_paths=changed_paths)
    reasons: list[str] = []

    if requested in PROVIDER_DENYLIST:
        reasons.append("provider_is_comparison_or_supervisor_only")
        return {
            "schema_version": "worker_adapter.v1",
            "adapter": requested,
            "allowed": False,
            "lane_class": lane_class,
            "effective_tier": tier,
            "reasons": reasons,
        }

    if requested == "browser_seat_bridge":
        if not seat_bridge_enabled:
            reasons.append("seat_bridge_disabled_by_default")
        if tier not in {1, 2}:
            reasons.append("seat_bridge_tier_restricted")
        if lane_class not in {"research", "docs"}:
            reasons.append("seat_bridge_lane_restricted")
        return {
            "schema_version": "worker_adapter.v1",
            "adapter": requested,
            "allowed": not reasons,
            "lane_class": lane_class,
            "effective_tier": tier,
            "reasons": reasons,
        }

    adapter_contract = FIRST_CLASS_ADAPTERS.get(requested)
    if adapter_contract is None:
        reasons.append("adapter_not_supported")
        return {
            "schema_version": "worker_adapter.v1",
            "adapter": requested,
            "allowed": False,
            "lane_class": lane_class,
            "effective_tier": tier,
            "reasons": reasons,
        }

    if tier not in set(adapter_contract.get("allowed_tiers") or []):
        reasons.append("adapter_tier_restricted")

    return {
        "schema_version": "worker_adapter.v1",
        "adapter": requested,
        "allowed": not reasons,
        "lane_class": lane_class,
        "effective_tier": tier,
        "reasons": reasons,
    }


def build_merge_authority_matrix() -> dict[str, Any]:
    """Return path-aware merge rules by autonomy tier."""

    return {
        "schema_version": "merge_authority_matrix.v1",
        "path_tiers": [
            {
                "tier": 3,
                "prefixes": list(TIER3_PREFIXES),
                "rule": "Never autonomous deploy in phase 1; require tests + artifacts + no-risk-delta + judge approval.",
            },
            {
                "tier": 2,
                "prefixes": list(TIER2_PREFIXES),
                "rule": "Auto-merge allowed when deterministic checks pass.",
            },
            {
                "tier": 1,
                "prefixes": list(TIER1_PREFIXES),
                "rule": "Auto-merge allowed when checks pass and scope is bounded.",
            },
        ],
        "tier_merge_rules": {
            "0": {
                "checks_required": ["artifact_contract_pass"],
                "decision_if_pass": "auto_merge",
                "decision_if_fail": "hold_for_human",
            },
            "1": {
                "checks_required": ["tests_pass", "artifact_contract_pass"],
                "decision_if_pass": "auto_merge",
                "decision_if_fail": "hold_for_human",
            },
            "2": {
                "checks_required": ["tests_pass", "artifact_contract_pass", "no_risk_delta_pass"],
                "decision_if_pass": "auto_merge",
                "decision_if_fail": "hold_for_human",
            },
            "3": {
                "checks_required": [
                    "tests_pass",
                    "artifact_contract_pass",
                    "no_risk_delta_pass",
                    "judge_approved",
                ],
                "decision_if_pass": "gated_merge",
                "decision_if_fail": "hold_for_human",
            },
        },
        "phase1_bounds": {
            "autonomous_deploy_tier3": False,
            "openclaw_comparison_only": True,
            "supervisor_may_not_govern": True,
        },
    }


def build_merge_decision(
    *,
    changed_paths: Sequence[str],
    adapter_allowed: bool,
    tests_pass: bool,
    artifact_contract_pass: bool,
    policy_boundary_pass: bool,
    no_risk_delta_pass: bool,
    judge_approved: bool,
    overlapping_pending_work: bool = False,
) -> dict[str, Any]:
    """Build a deterministic merge decision for one worker run."""

    tier = infer_autonomy_tier(changed_paths)
    missing: list[str] = []

    if not adapter_allowed:
        missing.append("adapter_not_allowed")
    if not policy_boundary_pass:
        missing.append("policy_boundary_failed")
    if not tests_pass:
        missing.append("tests_failed")
    if not artifact_contract_pass:
        missing.append("artifact_contract_failed")
    if tier >= 2 and not no_risk_delta_pass:
        missing.append("no_risk_delta_failed")
    if tier == 3 and not judge_approved:
        missing.append("judge_not_approved")
    if overlapping_pending_work:
        missing.append("overlapping_pending_work")

    decision = "hold_for_human"
    merge_class = "no_merge"

    if not missing:
        if tier <= 2:
            decision = "merge_now"
            merge_class = "auto_merge"
        else:
            decision = "open_pr_and_hold"
            merge_class = "gated_merge"
    elif missing == ["overlapping_pending_work"]:
        decision = "merge_after_queue"
        merge_class = "queued_merge"

    return {
        "schema_version": "merge_decision.v1",
        "tier": tier,
        "changed_paths": [_normalize_path(path) for path in changed_paths],
        "decision": decision,
        "merge_class": merge_class,
        "missing_requirements": missing,
        "autonomous_deploy_allowed": False if tier == 3 else True,
    }


def build_judge_verdict(
    *,
    run_id: str,
    adapter: str,
    lane_name: str,
    changed_paths: Sequence[str],
    in_scope_pass: bool,
    tests_pass: bool,
    artifact_contract_pass: bool,
    policy_boundary_pass: bool,
    no_risk_delta_pass: bool,
    run_status: str = "ok",
    seat_bridge_enabled: bool = False,
    overlapping_pending_work: bool = False,
) -> dict[str, Any]:
    """Build the normalized judge verdict for a worker run."""

    adapter_eval = evaluate_worker_adapter(
        adapter=adapter,
        lane_name=lane_name,
        changed_paths=changed_paths,
        seat_bridge_enabled=seat_bridge_enabled,
    )
    adapter_allowed = bool(adapter_eval.get("allowed"))
    tier = int(adapter_eval.get("effective_tier") or infer_autonomy_tier(changed_paths))

    run_status_normalized = str(run_status or "ok").strip().lower()
    reasons: list[str] = []
    if run_status_normalized == "crash":
        reasons.append("worker_crash")
    if run_status_normalized == "blocked":
        reasons.append("worker_blocked")
    if not in_scope_pass:
        reasons.append("lane_scope_violation")
    reasons.extend(str(reason) for reason in (adapter_eval.get("reasons") or []))

    judge_approved = (
        adapter_allowed
        and in_scope_pass
        and tests_pass
        and artifact_contract_pass
        and policy_boundary_pass
        and (no_risk_delta_pass or tier < 2)
        and run_status_normalized not in {"crash", "blocked"}
    )

    merge = build_merge_decision(
        changed_paths=changed_paths,
        adapter_allowed=adapter_allowed,
        tests_pass=tests_pass,
        artifact_contract_pass=artifact_contract_pass,
        policy_boundary_pass=policy_boundary_pass,
        no_risk_delta_pass=no_risk_delta_pass,
        judge_approved=judge_approved,
        overlapping_pending_work=overlapping_pending_work,
    )

    if run_status_normalized == "crash":
        decision = "crash"
    elif run_status_normalized == "blocked" or not adapter_allowed or not in_scope_pass:
        decision = "blocked"
    elif judge_approved:
        decision = "keep"
    else:
        decision = "discard"

    return {
        "schema_version": "judge_verdict.v1",
        "generated_at": utc_now_iso(),
        "run_id": str(run_id),
        "lane_name": str(lane_name),
        "adapter": str(adapter),
        "tier": tier,
        "decision": decision,
        "judge_approved": judge_approved,
        "reason_codes": reasons,
        "checks": {
            "in_scope_pass": bool(in_scope_pass),
            "tests_pass": bool(tests_pass),
            "artifact_contract_pass": bool(artifact_contract_pass),
            "policy_boundary_pass": bool(policy_boundary_pass),
            "no_risk_delta_pass": bool(no_risk_delta_pass),
            "adapter_allowed": bool(adapter_allowed),
            "run_status": run_status_normalized,
        },
        "adapter_evaluation": adapter_eval,
        "merge_decision": merge,
    }


def build_provider_boundary_matrix() -> dict[str, Any]:
    """Return provider-boundary governance locks for instance4."""

    return {
        "schema_version": "provider_boundary.v1",
        "openclaw": {
            "mode": "comparison_only",
            "allocator_eligible": False,
            "wallet_access": "none",
            "shared_state_access": "none",
            "governance_authority": False,
        },
        "hermes_like_supervisors": {
            "role": "worker_substrate_only",
            "governance_authority": False,
            "merge_authority": False,
            "truth_precedence": False,
            "live_risk_policy": False,
            "treasury_policy": False,
        },
        "browser_seat_bridge": {
            "enabled_by_default": False,
            "allowed_tiers_when_enabled": [1, 2],
            "allowed_lane_classes": ["research", "docs"],
            "governance_authority": False,
        },
    }
