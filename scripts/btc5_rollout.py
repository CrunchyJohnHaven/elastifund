#!/usr/bin/env python3
"""Deterministic BTC5 rollout orchestration for bounded live stage 1 or shadow/probe mode."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from deploy_release_bundle import (
    DEFAULT_REMOTE_DIR,
    DEFAULT_REMOTE_HOST,
    DeployError,
    discover_ssh_key,
    normalize_service_state,
    run_remote_command,
)


REPO_ROOT = SCRIPT_DIR.parent
REMOTE_BTC5_SERVICE = "btc-5min-maker.service"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "instance2_btc5_baseline" / "latest.json"
LEGACY_OUTPUT_PATHS = (
    REPO_ROOT / "reports" / "btc5_rollout_latest.json",
    REPO_ROOT / "reports" / "runtime" / "btc5" / "btc5_rollout_latest.json",
)
STAGE_ENV_PATH = REPO_ROOT / "state" / "btc5_capital_stage.env"
REMOTE_CYCLE_STATUS_PATH = REPO_ROOT / "reports" / "remote_cycle_status.json"
REMOTE_SERVICE_STATUS_PATH = REPO_ROOT / "reports" / "remote_service_status.json"
BTC5_REMOTE_SERVICE_STATUS_PATH = REPO_ROOT / "reports" / "btc5_remote_service_status.json"
BTC5_DEPLOY_ACTIVATION_PATH = REPO_ROOT / "reports" / "btc5_deploy_activation.json"
BTC5_AUTORESEARCH_LATEST_PATH = REPO_ROOT / "reports" / "btc5_autoresearch" / "latest.json"
LAUNCH_PACKET_LATEST_PATH = REPO_ROOT / "reports" / "launch_packet_latest.json"
FINANCE_LATEST_PATH = REPO_ROOT / "reports" / "finance" / "latest.json"
ROLLOUT_CONTROL_LATEST_PATH = REPO_ROOT / "reports" / "rollout_control" / "latest.json"

POLYBOT_FILES = (
    "polymarket-bot/src/__init__.py",
    "polymarket-bot/src/scanner.py",
    "polymarket-bot/src/claude_analyzer.py",
    "polymarket-bot/src/telegram.py",
    "polymarket-bot/src/core/__init__.py",
    "polymarket-bot/src/core/time_utils.py",
)
SCRIPT_SUPPORT_FILES = (
    "scripts/clean_env_for_profile.sh",
    "scripts/btc5_dual_autoresearch_ops.py",
    "scripts/btc5_status.sh",
    "scripts/run_btc5_service.sh",
    "scripts/btc5_monte_carlo.py",
    "scripts/btc5_regime_policy_lab.py",
    "scripts/run_btc5_autoresearch_cycle.py",
    "scripts/run_kalshi_weather_auto.sh",
    "scripts/run_flywheel_cycle.py",
    "scripts/write_remote_cycle_status.py",
)
DEPLOY_ASSET_FILES = (
    "deploy/jj-live.service",
    "deploy/btc-5min-maker.service",
    "deploy/btc5-autoresearch.service",
    "deploy/btc5-autoresearch.timer",
    "deploy/btc5-market-model-autoresearch.service",
    "deploy/btc5-market-model-autoresearch.timer",
    "deploy/btc5-policy-autoresearch.service",
    "deploy/btc5-policy-autoresearch.timer",
    "deploy/btc5-command-node-autoresearch.service",
    "deploy/btc5-command-node-autoresearch.timer",
    "deploy/btc5-dual-autoresearch-morning.service",
    "deploy/btc5-dual-autoresearch-morning.timer",
    "deploy/kalshi-weather-trader.service",
    "deploy/kalshi-weather-trader.timer",
    "deploy/jj-improvement-loop.service",
    "deploy/jj-improvement-loop.timer",
)
STAGE_ENV_NUMERIC_DEFAULTS = (
    ("BTC5_BANKROLL_USD", "250"),
    ("BTC5_RISK_FRACTION", "0.02"),
    ("BTC5_MAX_TRADE_USD", "10"),
    ("BTC5_MIN_TRADE_USD", "5"),
    ("BTC5_DAILY_LOSS_LIMIT_USD", "25"),
    ("BTC5_STAGE1_DAILY_LOSS_LIMIT_USD", "25"),
    ("BTC5_STAGE2_MAX_TRADE_USD", "15"),
    ("BTC5_STAGE3_MAX_TRADE_USD", "20"),
)
STAGE_ENV_RENDER_ORDER = (
    "BTC5_DEPLOY_MODE",
    "BTC5_PAPER_TRADING",
    "BTC5_CAPITAL_STAGE",
    "BTC5_BANKROLL_USD",
    "BTC5_RISK_FRACTION",
    "BTC5_MAX_TRADE_USD",
    "BTC5_STAGE1_MAX_TRADE_USD",
    "BTC5_STAGE2_MAX_TRADE_USD",
    "BTC5_STAGE3_MAX_TRADE_USD",
    "BTC5_MIN_TRADE_USD",
    "BTC5_DAILY_LOSS_LIMIT_USD",
    "BTC5_STAGE1_DAILY_LOSS_LIMIT_USD",
)


@dataclass(frozen=True)
class RolloutDecision:
    deploy_mode: str
    paper_trading: bool
    desired_stage: int
    allowed_stage: int
    confidence_label: str
    can_trade_now: bool
    rationale: tuple[str, ...]

    @property
    def shipped_mode(self) -> str:
        return "live_stage1" if self.deploy_mode == "live_stage1" else "shadow_probe"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_rollout_artifacts(output_path: Path, payload: dict[str, Any]) -> None:
    targets = {output_path.resolve(), DEFAULT_OUTPUT_PATH.resolve(), *(path.resolve() for path in LEGACY_OUTPUT_PATHS)}
    for target in targets:
        _write_json(target, payload)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _resolve_launch_packet(
    *,
    remote_cycle_status: dict[str, Any],
    launch_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit = dict(launch_packet or {})
    if explicit:
        return explicit
    return dict(remote_cycle_status.get("launch_packet") or {})


def _build_launch_authority(
    *,
    remote_cycle_status: dict[str, Any],
    launch_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    launch = dict(remote_cycle_status.get("launch") or {})
    resolved_packet = _resolve_launch_packet(
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
    )
    launch_verdict = dict(resolved_packet.get("launch_verdict") or {})
    launch_contract = dict(resolved_packet.get("contract") or {})
    state_permissions = dict(resolved_packet.get("state_permissions") or {})
    submission_contract_consensus = dict(
        resolved_packet.get("submission_contract_consensus") or {}
    )
    mandatory_outputs = dict(resolved_packet.get("mandatory_outputs") or {})
    authority_available = bool(
        resolved_packet
        or any(
            key in remote_cycle_status
            for key in ("launch_posture", "allow_order_submission", "paper_trading", "order_submit_enabled")
        )
        or bool(launch)
    )
    launch_posture = str(
        _first_nonempty(
            launch_verdict.get("posture"),
            launch_contract.get("launch_posture"),
            resolved_packet.get("launch_posture"),
            launch.get("posture"),
            remote_cycle_status.get("launch_posture"),
            "",
        )
    ).strip().lower()
    allow_order_submission = _bool_or_none(
        _first_nonempty(
            launch_contract.get("allow_order_submission"),
            resolved_packet.get("allow_order_submission"),
            launch.get("allow_order_submission"),
            remote_cycle_status.get("allow_order_submission"),
        )
    )
    order_submit_enabled = _bool_or_none(
        _first_nonempty(
            launch_contract.get("order_submit_enabled"),
            resolved_packet.get("order_submit_enabled"),
            remote_cycle_status.get("order_submit_enabled"),
        )
    )
    paper_trading = _bool_or_none(
        _first_nonempty(
            launch_contract.get("paper_trading"),
            resolved_packet.get("paper_trading"),
            remote_cycle_status.get("paper_trading"),
        )
    )
    live_order_submission_allowed = _bool_or_none(
        resolved_packet.get("live_order_submission_allowed")
    )
    if live_order_submission_allowed is None:
        live_order_submission_allowed = bool(
            launch_posture == "clear"
            and allow_order_submission is True
            and order_submit_enabled is True
            and paper_trading is False
        )
    launch_posture_clear = bool(
        submission_contract_consensus.get("launch_posture_clear")
        if "launch_posture_clear" in submission_contract_consensus
        else launch_posture == "clear"
    )
    allow_submission_consensus = bool(
        submission_contract_consensus.get("allow_order_submission")
        if "allow_order_submission" in submission_contract_consensus
        else allow_order_submission is True
    )
    paper_trading_disabled = bool(
        submission_contract_consensus.get("paper_trading_disabled")
        if "paper_trading_disabled" in submission_contract_consensus
        else paper_trading is False
    )
    live_launch_blocked = _bool_or_none(
        _first_nonempty(
            launch_verdict.get("live_launch_blocked"),
            resolved_packet.get("live_launch_blocked"),
            launch.get("live_launch_blocked"),
        )
    )
    allow_execution = _bool_or_none(
        _first_nonempty(
            launch_verdict.get("allow_execution"),
            resolved_packet.get("allow_execution"),
        )
    )
    baseline_live_allowed = _bool_or_none(
        _first_nonempty(
            launch_verdict.get("baseline_live_allowed"),
            state_permissions.get("baseline_live_allowed"),
            resolved_packet.get("baseline_live_allowed"),
            remote_cycle_status.get("btc5_baseline_live_allowed"),
        )
    )
    stage_upgrade_allowed = _bool_or_none(
        _first_nonempty(
            launch_verdict.get("stage_upgrade_allowed"),
            state_permissions.get("stage_upgrade_allowed"),
            resolved_packet.get("stage_upgrade_allowed"),
        )
    )
    capital_expansion_allowed = _bool_or_none(
        _first_nonempty(
            launch_verdict.get("capital_expansion_allowed"),
            state_permissions.get("capital_expansion_allowed"),
            resolved_packet.get("capital_expansion_allowed"),
        )
    )
    block_reasons = [
        str(item).strip()
        for item in list(
            mandatory_outputs.get("block_reasons")
            or resolved_packet.get("block_reasons")
            or launch.get("blocked_reasons")
            or []
        )
        if str(item).strip()
    ]
    failed_checks = [
        str(item).strip()
        for item in list(launch_contract.get("hard_failed_checks") or launch_contract.get("failed_checks") or [])
        if str(item).strip()
    ]
    authority_green = bool(
        authority_available
        and launch_posture == "clear"
        and allow_order_submission is True
        and order_submit_enabled is True
        and paper_trading is False
        and live_order_submission_allowed is True
        and launch_posture_clear
        and allow_submission_consensus
        and paper_trading_disabled
        and live_launch_blocked is not True
        and allow_execution is not False
    )
    return {
        "authority_available": authority_available,
        "launch_packet": resolved_packet,
        "launch_verdict": launch_verdict,
        "launch_contract": launch_contract,
        "submission_contract_consensus": {
            "launch_posture_clear": launch_posture_clear,
            "allow_order_submission": allow_submission_consensus,
            "paper_trading_disabled": paper_trading_disabled,
        },
        "launch_posture": launch_posture or None,
        "allow_order_submission": allow_order_submission,
        "order_submit_enabled": order_submit_enabled,
        "paper_trading": paper_trading,
        "live_order_submission_allowed": live_order_submission_allowed,
        "live_launch_blocked": live_launch_blocked,
        "allow_execution": allow_execution,
        "baseline_live_allowed": baseline_live_allowed,
        "stage_upgrade_allowed": stage_upgrade_allowed,
        "capital_expansion_allowed": capital_expansion_allowed,
        "block_reasons": block_reasons,
        "failed_checks": failed_checks,
        "authority_green": authority_green,
        "source_path": "reports/launch_packet_latest.json",
    }


def _baseline_block_reasons(remote_cycle_status: dict[str, Any]) -> list[str]:
    deployment_confidence = dict(remote_cycle_status.get("deployment_confidence") or {})
    stage_readiness = dict(remote_cycle_status.get("btc5_stage_readiness") or {})
    blockers = list(deployment_confidence.get("stage_1_blockers") or [])
    if not blockers:
        blockers = list(stage_readiness.get("trade_now_blocking_checks") or [])
    ordered: list[str] = []
    seen: set[str] = set()
    for blocker in blockers:
        text = str(blocker or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe_strings(values: Sequence[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _artifact_freshness(
    payload: dict[str, Any],
    *,
    path: str,
    stale_after_hours: float,
) -> dict[str, Any]:
    generated_at = _parse_datetime(payload.get("generated_at"))
    if generated_at is None:
        return {
            "path": path,
            "generated_at": None,
            "freshness": "missing",
            "age_hours": None,
            "stale_after_hours": stale_after_hours,
        }
    age_hours = max(0.0, (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600.0)
    return {
        "path": path,
        "generated_at": generated_at.isoformat(),
        "freshness": "stale" if age_hours > stale_after_hours else "fresh",
        "age_hours": round(age_hours, 4),
        "stale_after_hours": stale_after_hours,
    }


def _build_baseline_contract(
    *,
    decision: RolloutDecision,
    validation: dict[str, Any] | None,
    remote_cycle_status: dict[str, Any],
    launch_packet: dict[str, Any] | None,
    remote_service_status: dict[str, Any],
    finance_latest: dict[str, Any],
    rollout_control: dict[str, Any],
) -> dict[str, Any]:
    service_status = str(remote_service_status.get("status") or "unknown").strip().lower()
    service_running = service_status == "running"
    stage_readiness = dict(remote_cycle_status.get("btc5_stage_readiness") or {})
    deployment_confidence = dict(remote_cycle_status.get("deployment_confidence") or {})
    selected_package = dict(remote_cycle_status.get("btc5_selected_package") or {})
    finance_gate = dict(finance_latest.get("finance_gate") or {})
    launch_authority = _build_launch_authority(
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
    )

    baseline_live_allowed = bool(
        launch_authority.get("authority_green")
        if launch_authority.get("authority_available")
        else (
            launch_authority.get("baseline_live_allowed")
            if launch_authority.get("baseline_live_allowed") is not None
            else stage_readiness.get("baseline_live_allowed", decision.deploy_mode == "live_stage1")
        )
    )
    baseline_live_ok = bool(
        baseline_live_allowed
        and decision.deploy_mode == "live_stage1"
        and decision.paper_trading is False
        and service_running
        and (
            not launch_authority.get("authority_available")
            or bool(launch_authority.get("authority_green"))
        )
        and (validation or {}).get("rollback_required") is not True
    )
    if baseline_live_ok:
        baseline_status = "baseline_live_ok"
    elif service_running:
        baseline_status = "baseline_shadow_only"
    else:
        baseline_status = "baseline_not_running"

    stage_upgrade_blockers = _dedupe_strings(
        list(stage_readiness.get("stage_upgrade_trade_now_blocking_checks") or [])
        or list(stage_readiness.get("blocking_checks") or [])
        or list(deployment_confidence.get("blocking_checks") or [])
    )
    stage_upgrade_blocked = bool(
        stage_upgrade_blockers
        or stage_readiness.get("ready_for_stage_1") is False
        or remote_cycle_status.get("btc5_stage_upgrade_can_trade_now") is False
    )
    treasury_expansion_blocked = bool(
        finance_latest.get("capital_expansion_only_hold")
        or finance_gate.get("treasury_pass") is False
        or finance_latest.get("treasury_gate_pass") is False
    )
    stale_promotion_artifacts = _dedupe_strings(
        [
            item["path"]
            for item in (
                _artifact_freshness(
                    selected_package,
                    path="reports/btc5_autoresearch/latest.json",
                    stale_after_hours=6.0,
                ),
                _artifact_freshness(
                    rollout_control,
                    path="reports/rollout_control/latest.json",
                    stale_after_hours=1.0,
                ),
            )
            if item["freshness"] == "stale"
        ]
    )

    block_reasons: list[str] = []
    if baseline_live_ok and stage_upgrade_blocked:
        block_reasons.append("stage_readiness_vs_live_baseline_mismatch")
    if treasury_expansion_blocked:
        block_reasons.append("capital_expansion_hold")
    block_reasons.extend(f"stale_promotion_artifact:{path}" for path in stale_promotion_artifacts)
    retry_in_minutes = None
    if stale_promotion_artifacts:
        retry_in_minutes = 10
    elif rollout_control.get("action") == "repair":
        retry_in_minutes = min(
            [
                int(item.get("retry_eta_minutes") or 10)
                for item in list(rollout_control.get("repair_branches") or [])
                if int(item.get("retry_eta_minutes") or 0) > 0
            ]
            or [10]
        )

    return {
        "schema_version": "baseline_contract.v1",
        "baseline_truth_source": "reports/instance2_btc5_baseline/latest.json",
        "baseline_status": baseline_status,
        "baseline_live_ok": baseline_live_ok,
        "baseline_live_allowed": baseline_live_allowed,
        "baseline_mode": decision.deploy_mode,
        "service_running": service_running,
        "launch_authority_source": launch_authority.get("source_path"),
        "launch_authority_green": launch_authority.get("authority_green"),
        "launch_submission_contract": {
            "launch_posture": launch_authority.get("launch_posture"),
            "allow_order_submission": launch_authority.get("allow_order_submission"),
            "order_submit_enabled": launch_authority.get("order_submit_enabled"),
            "paper_trading": launch_authority.get("paper_trading"),
            "live_order_submission_allowed": launch_authority.get("live_order_submission_allowed"),
        },
        "stage_upgrade_status": "stage_upgrade_blocked" if stage_upgrade_blocked else "stage_upgrade_ready",
        "stage_upgrade_blocked": stage_upgrade_blocked,
        "stage_upgrade_blockers": stage_upgrade_blockers,
        "treasury_expansion_status": (
            "treasury_expansion_blocked" if treasury_expansion_blocked else "treasury_expansion_ready"
        ),
        "treasury_expansion_blocked": treasury_expansion_blocked,
        "finance_gate_pass": bool(finance_latest.get("finance_gate_pass")),
        "stale_promotion_artifacts": stale_promotion_artifacts,
        "stale_promotion_artifact_count": len(stale_promotion_artifacts),
        "promotion_artifact_freshness": {
            "btc5_autoresearch": _artifact_freshness(
                selected_package,
                path="reports/btc5_autoresearch/latest.json",
                stale_after_hours=6.0,
            ),
            "rollout_control": _artifact_freshness(
                rollout_control,
                path="reports/rollout_control/latest.json",
                stale_after_hours=1.0,
            ),
        },
        "source_precedence": [
            "reports/launch_packet_latest.json",
            "reports/runtime_truth_latest.json or reports/remote_cycle_status.json",
            "reports/instance2_btc5_baseline/latest.json",
            "reports/btc5_autoresearch/latest.json",
            "reports/finance/latest.json",
            "reports/rollout_control/latest.json",
        ],
        "block_reasons": block_reasons,
        "retry_in_minutes": retry_in_minutes,
        "canonical_live_profile": str(
            selected_package.get("canonical_live_profile")
            or selected_package.get("selected_active_profile_name")
            or selected_package.get("selected_best_profile_name")
            or ""
        ).strip() or None,
        "one_next_cycle_action": (
            launch_authority.get("launch_packet", {}).get("one_next_cycle_action")
            or f"Keep canonical live profile "
            f"{selected_package.get('canonical_live_profile') or selected_package.get('selected_active_profile_name') or 'unknown'} "
            f"at flat stage-1 size via baseline_guard.v1 inside autoprompt gating"
        ),
    }


def _build_baseline_guard(baseline_contract: dict[str, Any]) -> dict[str, Any]:
    baseline_live_ok = bool(baseline_contract.get("baseline_live_ok"))
    stage_upgrade_blocked = bool(baseline_contract.get("stage_upgrade_blocked"))
    treasury_expansion_blocked = bool(baseline_contract.get("treasury_expansion_blocked"))
    blocked_actions = _dedupe_strings(
        [
            "promote_stage_1_size_or_higher" if stage_upgrade_blocked else "",
            "deploy_capital_expansion" if treasury_expansion_blocked else "",
            "let_stale_promotion_artifacts_override_baseline" if baseline_live_ok else "",
        ]
    )
    return {
        "schema_version": "baseline_guard.v1",
        "truth_source": str(DEFAULT_OUTPUT_PATH.relative_to(REPO_ROOT)),
        "baseline_truth_source": baseline_contract.get("baseline_truth_source"),
        "status_triplet": {
            "baseline": baseline_contract.get("baseline_status"),
            "stage_upgrade": baseline_contract.get("stage_upgrade_status"),
            "treasury_expansion": baseline_contract.get("treasury_expansion_status"),
        },
        "permitted_baseline_attempts": _dedupe_strings(
            [
                "maintain_stage1_flat_size" if baseline_live_ok else "",
                "restart_current_baseline_service" if baseline_live_ok else "",
                "refresh_runtime_truth",
                "refresh_baseline_contract",
            ]
        ),
        "blocked_actions": blocked_actions,
        "control_modes": {
            "observe_only": {
                "allowed": True,
                "allowed_actions": [
                    "read_machine_truth",
                    "publish_hold_repair",
                    "refresh_baseline_contract",
                ],
            },
            "research_auto": {
                "allowed": True,
                "allowed_actions": [
                    "run_autoresearch",
                    "publish_comparison_artifacts",
                    "rank_stage_upgrade_candidates_without_touching_baseline",
                ],
            },
            "safe_build_auto": {
                "allowed": True,
                "allowed_actions": [
                    "patch_docs_reports_scripts_outside_live_paths",
                    "run_narrow_tests",
                    "publish_guard_updates",
                ],
            },
            "gated_build_auto": {
                "allowed": True,
                "allowed_actions": [
                    "prepare_live_sensitive_baseline_maintenance_diff",
                    "run_deterministic_tests",
                    "emit_gated_merge_packet",
                ],
                "blocked_actions": [
                    "autonomous_stage_upgrade" if stage_upgrade_blocked else "",
                    "autonomous_treasury_expansion" if treasury_expansion_blocked else "",
                ],
            },
            "deploy_recommend": {
                "allowed": True,
                "allowed_actions": [
                    "recommend_maintain_live_stage1_flat_size" if baseline_live_ok else "recommend_shadow_probe_only",
                    "recommend_truth_refresh_before_stage_upgrade" if stage_upgrade_blocked else "recommend_stage_upgrade_review",
                    (
                        "recommend_research_budget_only_until_treasury_unblocked"
                        if treasury_expansion_blocked
                        else "recommend_treasury_review"
                    ),
                ],
            },
        },
        "hold_repair": {
            "active": bool(baseline_contract.get("stale_promotion_artifacts")),
            "retry_in_minutes": baseline_contract.get("retry_in_minutes"),
            "reason": (
                "stale_promotion_artifacts_do_not_override_baseline"
                if baseline_contract.get("stale_promotion_artifacts")
                else None
            ),
        },
    }


def _read_local_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def render_selected_runtime_override_env(
    *,
    decision: RolloutDecision,
    cycle_payload: dict[str, Any],
) -> str | None:
    if decision.deploy_mode != "live_stage1":
        return None
    selected_runtime_package = (
        cycle_payload.get("selected_best_runtime_package")
        if isinstance(cycle_payload.get("selected_best_runtime_package"), dict)
        else {}
    )
    profile = (
        selected_runtime_package.get("profile")
        if isinstance(selected_runtime_package.get("profile"), dict)
        else {}
    )
    if not profile:
        return None

    from run_btc5_autoresearch_cycle_core import render_strategy_env

    stage_env_values = _read_local_env(STAGE_ENV_PATH)
    current_override_values = _read_local_env(REPO_ROOT / "state" / "btc5_autoresearch.env")
    metadata = {
        "generated_at": _utc_now(),
        "reason": (
            ((cycle_payload.get("runtime_package_selection") or {}).get("selection_reason"))
            or "btc5_rollout_live_stage1_selected_runtime_package"
        ),
        "current_min_buy_price": (
            current_override_values.get("BTC5_MIN_BUY_PRICE")
            or stage_env_values.get("BTC5_MIN_BUY_PRICE")
            or os.environ.get("BTC5_MIN_BUY_PRICE")
        ),
    }
    return render_strategy_env(selected_runtime_package, metadata)


def resolve_remote_host(cli_host: str | None) -> str:
    if cli_host:
        return cli_host
    env_values = _read_local_env(REPO_ROOT / ".env")
    vps_ip = env_values.get("VPS_IP") or os.environ.get("VPS_IP")
    vps_user = env_values.get("VPS_USER") or os.environ.get("VPS_USER") or "ubuntu"
    if vps_ip:
        return f"{vps_user}@{vps_ip}"
    return DEFAULT_REMOTE_HOST


def resolve_ssh_key(cli_key: Path | None) -> Path | None:
    if cli_key is not None:
        return cli_key.resolve()
    env_values = _read_local_env(REPO_ROOT / ".env")
    configured = env_values.get("LIGHTSAIL_KEY") or os.environ.get("LIGHTSAIL_KEY")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists():
            return candidate.resolve()
    return discover_ssh_key(REPO_ROOT)


def select_rollout_decision(
    remote_cycle_status: dict[str, Any],
    *,
    launch_packet: dict[str, Any] | None = None,
) -> RolloutDecision:
    btc5_stage_readiness = dict(remote_cycle_status.get("btc5_stage_readiness") or {})
    deployment_confidence = dict(remote_cycle_status.get("deployment_confidence") or {})
    validated_package = dict(deployment_confidence.get("validated_package") or {})
    launch_authority = _build_launch_authority(
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
    )
    accounting_reconciliation = dict(remote_cycle_status.get("accounting_reconciliation") or {})
    selected_package = dict(remote_cycle_status.get("btc5_selected_package") or {})
    allowed_stage_value = (
        deployment_confidence.get("allowed_stage")
        if "allowed_stage" in deployment_confidence
        else btc5_stage_readiness.get("allowed_stage")
    )
    allowed_stage = int(allowed_stage_value or 0)
    confidence_label = str(deployment_confidence.get("confidence_label") or "unknown").strip().lower() or "unknown"
    can_trade_now = bool(
        deployment_confidence["can_btc5_trade_now"]
        if "can_btc5_trade_now" in deployment_confidence
        else btc5_stage_readiness.get("can_trade_now")
    )
    validated_for_live_stage1 = bool(
        validated_package.get("validated_for_live_stage1")
        if validated_package
        else selected_package.get("validated_for_live_stage1")
    )
    selected_package_confidence_label = str(
        selected_package.get("selected_package_confidence_label") or confidence_label
    ).strip().lower()
    selected_deploy_recommendation = str(
        selected_package.get("selected_deploy_recommendation") or ""
    ).strip().lower()
    validation_live_filled_rows = int(_safe_float(selected_package.get("validation_live_filled_rows"), 0.0) or 0)
    generalization_ratio = _safe_float(selected_package.get("generalization_ratio"), 0.0)
    stage_1_blockers = {
        str(item).strip()
        for item in list(deployment_confidence.get("stage_1_blockers") or [])
        if str(item).strip()
    }
    blocking_checks = {
        *stage_1_blockers,
        *{
            str(item).strip()
            for item in list(deployment_confidence.get("blocking_checks") or [])
            if str(item).strip()
        },
        *{
            str(item).strip()
            for item in list(selected_package.get("blocking_checks") or [])
            if str(item).strip()
        },
        *{
            str(item).strip()
            for item in list(btc5_stage_readiness.get("trade_now_blocking_checks") or [])
            if str(item).strip()
        },
        *{
            str(item).strip()
            for item in list(launch_authority.get("block_reasons") or [])
            if str(item).strip()
        },
    }
    launch_posture = str(launch_authority.get("launch_posture") or "").strip().lower()
    allow_order_submission = bool(launch_authority.get("allow_order_submission"))
    paper_trading = launch_authority.get("paper_trading")
    live_order_submission_allowed = bool(launch_authority.get("live_order_submission_allowed"))
    baseline_live_allowed = bool(launch_authority.get("baseline_live_allowed"))
    recent_12_live_pnl = _safe_float(
        _first_nonempty(
            (((remote_cycle_status.get("btc_5min_maker") or {}).get("intraday_live_summary") or {}).get("recent_12_pnl_usd")),
            selected_package.get("trailing_12_live_filled_pnl_usd"),
            remote_cycle_status.get("trailing_12_live_pnl"),
        ),
        0.0,
    )
    confirmation_coverage_sufficient = _bool_or_none(
        _first_nonempty(
            deployment_confidence.get("confirmation_coverage_sufficient"),
            selected_package.get("confirmation_coverage_sufficient"),
        )
    )
    if confirmation_coverage_sufficient is None:
        confirmation_label = str(
            _first_nonempty(
                deployment_confidence.get("confirmation_coverage_label"),
                deployment_confidence.get("confirmation_support_status"),
                selected_package.get("confirmation_coverage_status"),
                "",
            )
        ).strip().lower()
        confirmation_coverage_sufficient = (
            confirmation_label in {"sufficient", "ready", "green", "high", "medium", "supported"}
            and "confirmation_coverage_insufficient" not in blocking_checks
        )
    truth_blockers_present = bool(
        accounting_reconciliation.get("drift_detected")
        or launch_authority.get("live_launch_blocked") is True
        or (
            {
                "accounting_reconciliation_drift",
                "local_ledger_drift_vs_remote_wallet",
                "trade_count_divergence_requires_repair_branch",
                "wallet_export_candidate_conflict_requires_repair_branch",
                "control_posture_blocked_requires_repair_branch",
                "trade_proof_fill_conflict_requires_repair_branch",
            }
            & blocking_checks
        )
    )
    truth_green = bool(launch_authority.get("authority_green") and not truth_blockers_present)
    package_green = bool(
        validated_for_live_stage1
        and can_trade_now
        and allowed_stage >= 1
        and selected_deploy_recommendation == "promote"
        and selected_package_confidence_label in {"medium", "high"}
        and generalization_ratio >= 0.70
        and validation_live_filled_rows >= 12
        and confirmation_coverage_sufficient
        and recent_12_live_pnl > 0.0
        and not truth_blockers_present
    )
    live_stage_allowed = truth_green and package_green
    rationale: list[str] = []
    if live_stage_allowed:
        rationale.append("launch_packet_and_btc5_package_gates_green")
        return RolloutDecision(
            deploy_mode="live_stage1",
            paper_trading=False,
            desired_stage=1,
            allowed_stage=max(allowed_stage, 1),
            confidence_label=selected_package_confidence_label or confidence_label,
            can_trade_now=True,
            rationale=tuple(rationale),
        )

    if not truth_green:
        rationale.append("truth_surface_blocks_live_stage_1")
    if baseline_live_allowed and not package_green:
        rationale.append("launch_packet_baseline_live_allowed_but_package_not_green")
    if not launch_authority.get("authority_available"):
        rationale.append("launch_packet_missing")
    if launch_posture != "clear":
        rationale.append(f"launch_posture_{launch_posture or 'unknown'}")
    if not allow_order_submission:
        rationale.append("launch_packet_disables_order_submission")
    if launch_authority.get("order_submit_enabled") is not True:
        rationale.append("launch_packet_order_submit_disabled")
    if paper_trading is not False:
        rationale.append("launch_packet_keeps_paper_trading_enabled")
    if not live_order_submission_allowed:
        rationale.append("launch_packet_does_not_permit_live_submission")
    if not all(
        bool((launch_authority.get("submission_contract_consensus") or {}).get(key))
        for key in ("launch_posture_clear", "allow_order_submission", "paper_trading_disabled")
    ):
        rationale.append("launch_packet_permission_consensus_missing")
    if truth_blockers_present:
        rationale.append("truth_or_accounting_drift_blockers_present")
    if not validated_for_live_stage1:
        rationale.append("validated_btc5_package_not_ready_for_live_stage1")
    if selected_deploy_recommendation != "promote":
        rationale.append("selected_runtime_package_not_promote")
    if selected_package_confidence_label not in {"medium", "high"}:
        rationale.append(f"selected_package_confidence_{selected_package_confidence_label}")
    if generalization_ratio < 0.70:
        rationale.append("selected_runtime_package_generalization_below_0.70")
    if validation_live_filled_rows < 12:
        rationale.append("insufficient_trailing_12_live_fills")
    if not confirmation_coverage_sufficient:
        rationale.append("confirmation_coverage_insufficient")
    if recent_12_live_pnl <= 0.0:
        rationale.append("trailing_12_live_filled_not_positive")
    if not can_trade_now:
        rationale.append("deployment_confidence_blocks_trade_now")
    if allowed_stage < 1:
        rationale.append("allowed_stage_below_1")
    if not rationale:
        rationale.append("fallback_to_shadow_probe")
    return RolloutDecision(
        deploy_mode="shadow_probe",
        paper_trading=True,
        desired_stage=1,
        allowed_stage=allowed_stage,
        confidence_label=selected_package_confidence_label or confidence_label,
        can_trade_now=False,
        rationale=tuple(rationale),
    )


def render_stage_env(existing_values: dict[str, str], decision: RolloutDecision) -> str:
    values = dict(existing_values)
    for key, default in STAGE_ENV_NUMERIC_DEFAULTS:
        values.setdefault(key, default)
    values["BTC5_DEPLOY_MODE"] = decision.deploy_mode
    values["BTC5_PAPER_TRADING"] = "true" if decision.paper_trading else "false"
    values["BTC5_CAPITAL_STAGE"] = str(decision.desired_stage)

    lines = [f"# Managed by scripts/btc5_rollout.py at {_utc_now()}."]
    rendered_keys: set[str] = set()
    for key in STAGE_ENV_RENDER_ORDER:
        if key in values:
            lines.append(f"{key}={values[key]}")
            rendered_keys.add(key)
    for key in sorted(key for key in values if key not in rendered_keys):
        lines.append(f"{key}={values[key]}")
    return "\n".join(lines) + "\n"


def list_rollout_managed_files(repo_root: Path) -> tuple[str, ...]:
    managed: set[str] = set()
    for path in sorted((repo_root / "bot").glob("*.py")):
        managed.add(path.relative_to(repo_root).as_posix())
    for path in sorted((repo_root / "kalshi").glob("*.py")):
        managed.add(path.relative_to(repo_root).as_posix())
    for relative in (
        "config/__init__.py",
        "config/runtime_profile.py",
        "config/btc5_strategy.env",
        "config/flywheel_runtime.local.json",
        "state/btc5_autoresearch.env",
        "state/btc5_capital_stage.env",
        "data/wallet_scores.db",
        "data/smart_wallets.json",
    ):
        if (repo_root / relative).exists():
            managed.add(relative)
    managed.update(POLYBOT_FILES)
    managed.update(SCRIPT_SUPPORT_FILES)
    managed.update(DEPLOY_ASSET_FILES)
    for path in sorted((repo_root / "config" / "runtime_profiles").glob("*.json")):
        managed.add(path.relative_to(repo_root).as_posix())
    return tuple(sorted(relative for relative in managed if (repo_root / relative).exists()))


def _encode_json(payload: Any) -> str:
    return base64.b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")


def backup_remote_files(
    *,
    host: str,
    key_path: Path,
    remote_dir: str,
    managed_files: Sequence[str],
) -> dict[str, Any]:
    backup_name = f"btc5_rollout_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    backup_dir = f"{remote_dir}/state/btc5_rollout_backups"
    backup_path = f"{backup_dir}/{backup_name}"
    encoded_files = _encode_json(list(managed_files))
    script = f"""
import base64
import json
import tarfile
from pathlib import Path

root = Path({remote_dir!r})
backup_path = Path({backup_path!r})
managed_files = json.loads(base64.b64decode({encoded_files!r}).decode("utf-8"))
backup_path.parent.mkdir(parents=True, exist_ok=True)
present_files = []
with tarfile.open(backup_path, "w:gz") as archive:
    for relative in managed_files:
        path = root / relative
        if path.is_file():
            archive.add(path, arcname=relative)
            present_files.append(relative)
print(json.dumps({{
    "backup_path": str(backup_path),
    "present_files": present_files,
    "managed_file_count": len(managed_files),
}}, sort_keys=True))
"""
    command = (
        f"cd {shlex.quote(remote_dir)} && "
        "python3 - <<'PY'\n"
        f"{script}"
        "PY"
    )
    result = run_remote_command(host, key_path, command, check=True)
    return json.loads(result.stdout)


def restore_remote_files(
    *,
    host: str,
    key_path: Path,
    remote_dir: str,
    backup_path: str,
    managed_files: Sequence[str],
    present_files: Sequence[str],
) -> dict[str, Any]:
    encoded_managed = _encode_json(list(managed_files))
    encoded_present = _encode_json(list(present_files))
    script = f"""
import base64
import json
import tarfile
from pathlib import Path

root = Path({remote_dir!r})
backup_path = Path({backup_path!r})
managed_files = json.loads(base64.b64decode({encoded_managed!r}).decode("utf-8"))
present_files = set(json.loads(base64.b64decode({encoded_present!r}).decode("utf-8")))
removed_files = []
if backup_path.exists():
    with tarfile.open(backup_path, "r:gz") as archive:
        archive.extractall(root)
for relative in managed_files:
    if relative in present_files:
        continue
    path = root / relative
    if path.is_file():
        path.unlink()
        removed_files.append(relative)
print(json.dumps({{
    "backup_path": str(backup_path),
    "removed_files": removed_files,
}}, sort_keys=True))
"""
    command = (
        f"cd {shlex.quote(remote_dir)} && "
        "python3 - <<'PY'\n"
        f"{script}"
        "PY"
    )
    result = run_remote_command(host, key_path, command, check=True)
    restore_payload = json.loads(result.stdout)
    restart_command = (
        f"cd {shlex.quote(remote_dir)} && "
        "chmod +x scripts/run_btc5_service.sh scripts/clean_env_for_profile.sh && "
        f"sudo install -m 644 {shlex.quote(remote_dir)}/deploy/{REMOTE_BTC5_SERVICE} /etc/systemd/system/{REMOTE_BTC5_SERVICE} && "
        "sudo systemctl daemon-reload && "
        f"sudo systemctl restart {REMOTE_BTC5_SERVICE} && "
        f"systemctl is-active {REMOTE_BTC5_SERVICE}"
    )
    restart_result = run_remote_command(host, key_path, restart_command, check=False)
    restore_payload["restart_returncode"] = restart_result.returncode
    restore_payload["restart_stdout_tail"] = (restart_result.stdout or "").splitlines()[-20:]
    restore_payload["restart_stderr_tail"] = (restart_result.stderr or "").splitlines()[-20:]
    return restore_payload


def capture_btc5_service_status_file(*, host: str, key_path: Path) -> dict[str, Any]:
    result = run_remote_command(
        host,
        key_path,
        f"systemctl is-active {REMOTE_BTC5_SERVICE} 2>/dev/null || true",
        check=False,
    )
    snapshot = normalize_service_state(result.stdout or result.stderr)
    snapshot.update(
        {
            "checked_at": _utc_now(),
            "host": host,
            "service_name": REMOTE_BTC5_SERVICE,
        }
    )
    _write_json(BTC5_REMOTE_SERVICE_STATUS_PATH, snapshot)
    return snapshot


def capture_remote_btc5_activation(
    *,
    host: str,
    key_path: Path,
    remote_dir: str,
) -> dict[str, Any]:
    pythonpath = f"{remote_dir}:{remote_dir}/bot:{remote_dir}/polymarket-bot"
    command = f"""cd {shlex.quote(remote_dir)} && export PYTHONPATH={shlex.quote(pythonpath)} && python3 - <<'PY'
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

TRACKED_OVERRIDE_KEYS = {{
    'BTC5_DEPLOY_MODE',
    'BTC5_PAPER_TRADING',
    'BTC5_CAPITAL_STAGE',
    'BTC5_BANKROLL_USD',
    'BTC5_RISK_FRACTION',
    'BTC5_MAX_TRADE_USD',
    'BTC5_MIN_TRADE_USD',
    'BTC5_DAILY_LOSS_LIMIT_USD',
    'BTC5_STAGE1_DAILY_LOSS_LIMIT_USD',
    'BTC5_STAGE1_MAX_TRADE_USD',
    'BTC5_STAGE2_MAX_TRADE_USD',
    'BTC5_STAGE3_MAX_TRADE_USD',
}}
REQUIRED_STAGE_OVERRIDE_KEYS = (
    'BTC5_DEPLOY_MODE',
    'BTC5_PAPER_TRADING',
    'BTC5_CAPITAL_STAGE',
    'BTC5_BANKROLL_USD',
    'BTC5_RISK_FRACTION',
    'BTC5_MAX_TRADE_USD',
    'BTC5_MIN_TRADE_USD',
    'BTC5_DAILY_LOSS_LIMIT_USD',
    'BTC5_STAGE1_DAILY_LOSS_LIMIT_USD',
)

def load_env_file(path: Path) -> dict[str, object]:
    detail = {{
        'exists': path.exists(),
        'loaded': False,
        'keys': [],
        'tracked_values': {{}},
    }}
    if not path.exists():
        return detail
    pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
    keys: list[str] = []
    tracked_values: dict[str, str] = {{}}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not pattern.match(key):
            continue
        keys.append(key)
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value
        if key in TRACKED_OVERRIDE_KEYS:
            tracked_values[key] = value
    detail['loaded'] = True
    detail['keys'] = sorted(set(keys))
    detail['tracked_values'] = tracked_values
    return detail

root = Path.cwd()
env_file_details = {{
    relative_path: load_env_file(root / relative_path)
    for relative_path in (
        'config/btc5_strategy.env',
        'state/btc5_autoresearch.env',
        '.env',
        'state/btc5_capital_stage.env',
    )
}}

from bot.btc_5min_maker import MakerConfig, TradeDB

cfg = MakerConfig()
db = TradeDB(cfg.db_path)
status = db.status_summary()
service_name = {REMOTE_BTC5_SERVICE!r}
def _bool_or_none(value):
    text = str(value or '').strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return None

systemctl_state = subprocess.run(
    ['systemctl', 'is-active', service_name],
    check=False,
    capture_output=True,
    text=True,
).stdout.strip() or 'unknown'
service_status = 'running' if systemctl_state == 'active' else 'stopped'

def _systemctl_show_value(property_name: str) -> str | None:
    value = subprocess.run(
        ['systemctl', 'show', '-p', property_name, '--value', service_name],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return value or None

service_definition = {{
    'fragment_path': _systemctl_show_value('FragmentPath'),
    'load_state': _systemctl_show_value('LoadState') or 'unknown',
    'unit_file_state': _systemctl_show_value('UnitFileState') or 'unknown',
    'sub_state': _systemctl_show_value('SubState') or 'unknown',
}}
stage_override_detail = env_file_details.get('state/btc5_capital_stage.env') or {{
    'exists': False,
    'loaded': False,
    'tracked_values': {{}},
}}
stage_override_values = dict(stage_override_detail.get('tracked_values') or {{}})
deploy_mode = str(
    stage_override_values.get('BTC5_DEPLOY_MODE')
    or os.environ.get('BTC5_DEPLOY_MODE')
    or ''
).strip() or ('shadow_probe' if cfg.paper_trading else 'live_stage1')
paper_trading = _bool_or_none(stage_override_values.get('BTC5_PAPER_TRADING'))
if paper_trading is None:
    paper_trading = bool(cfg.paper_trading)
missing_override_keys = [
    key for key in REQUIRED_STAGE_OVERRIDE_KEYS if key not in stage_override_values
]
verification_checks = {{
    'service_active': service_status == 'running',
    'service_unit_loaded': service_definition['load_state'] == 'loaded',
    'service_fragment_matches': bool(service_definition['fragment_path']) and service_definition['fragment_path'].endswith(service_name),
    'override_env_loaded': bool(stage_override_detail.get('loaded')) and bool(stage_override_values),
    'deploy_mode_matches_paper_setting': (
        (deploy_mode in ('shadow_probe', 'shadow', 'paper', 'probe') and paper_trading)
        or (deploy_mode in ('live_stage1', 'live', 'stage1_live') and not paper_trading)
    ),
    'status_summary_present': bool(status),
}}
payload = {{
    'checked_at': datetime.now(timezone.utc).isoformat(),
    'service_name': service_name,
    'service_status': service_status,
    'systemctl_state': systemctl_state,
    'deploy_mode': deploy_mode,
    'paper_trading': paper_trading,
    'runtime_profile': os.environ.get('JJ_RUNTIME_PROFILE') or None,
    'service_definition': service_definition,
    'override_env': {{
        'path': 'state/btc5_capital_stage.env',
        'exists': bool(stage_override_detail.get('exists')),
        'loaded': bool(stage_override_detail.get('loaded')),
        'tracked_values': stage_override_values,
        'missing_required_keys': missing_override_keys,
    }},
    'stage_in_effect': {{
        'capital_stage': int(cfg.capital_stage or 0),
        'effective_max_trade_usd': round(float(cfg.effective_max_trade_usd), 4),
        'effective_daily_loss_limit_usd': round(float(cfg.effective_daily_loss_limit_usd), 4),
    }},
    'status_summary': status,
    'verification_checks': verification_checks,
}}
print(json.dumps(payload, sort_keys=True))
PY"""
    result = run_remote_command(host, key_path, command, check=True)
    payload = json.loads(result.stdout)
    checks = dict(payload.get("verification_checks") or {})
    required_checks = (
        "service_active",
        "service_unit_loaded",
        "service_fragment_matches",
        "override_env_loaded",
        "deploy_mode_matches_paper_setting",
        "status_summary_present",
    )
    failed_required_checks = [name for name in required_checks if not checks.get(name)]
    payload.setdefault("verification_checks", {})["failed_required_checks"] = failed_required_checks
    payload["verification_checks"]["required_passed"] = not failed_required_checks
    _write_json(BTC5_DEPLOY_ACTIVATION_PATH, payload)
    return payload


def _probe_freshness_block(remote_cycle_status: dict[str, Any]) -> dict[str, Any]:
    accounting = dict(remote_cycle_status.get("accounting_reconciliation") or {})
    freshness = dict((accounting.get("source_confidence_freshness") or {}).get("btc_5min_maker") or {})
    if freshness:
        return freshness
    btc5 = dict(remote_cycle_status.get("btc_5min_maker") or {})
    return {
        "freshness": "unknown",
        "checked_at": btc5.get("checked_at"),
    }


def _evaluate_refresh_contract(
    *,
    remote_cycle_status: dict[str, Any],
    launch_packet: dict[str, Any] | None,
) -> dict[str, Any]:
    data_cadence = dict(remote_cycle_status.get("data_cadence") or {})
    service = dict(remote_cycle_status.get("service") or {})
    trade_proof = dict(remote_cycle_status.get("trade_proof") or {})
    launch_authority = _build_launch_authority(
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
    )
    generated_at = _parse_datetime(remote_cycle_status.get("generated_at"))
    launch_generated_at = _parse_datetime(
        (launch_authority.get("launch_packet") or {}).get("generated_at")
    )
    age_minutes = (
        round(max(0.0, (datetime.now(timezone.utc) - generated_at).total_seconds()) / 60.0, 4)
        if generated_at is not None
        else None
    )
    launch_age_minutes = (
        round(max(0.0, (datetime.now(timezone.utc) - launch_generated_at).total_seconds()) / 60.0, 4)
        if launch_generated_at is not None
        else None
    )
    freshness_sla_minutes = int(
        trade_proof.get("freshness_sla_minutes")
        or data_cadence.get("freshness_sla_minutes")
        or 45
    )
    critical_errors: list[str] = []
    if generated_at is None:
        critical_errors.append("remote_cycle_status_generated_at_missing")
    elif age_minutes is not None and age_minutes > freshness_sla_minutes:
        critical_errors.append("remote_cycle_status_not_fresh")
    if launch_authority.get("authority_available") and launch_generated_at is None:
        critical_errors.append("launch_packet_generated_at_missing")
    elif launch_age_minutes is not None and launch_age_minutes > freshness_sla_minutes:
        critical_errors.append("launch_packet_not_fresh")
    if bool(data_cadence.get("stale")):
        critical_errors.append("post_refresh_data_cadence_stale")
    service_name = str(service.get("service_name") or "").strip()
    if service_name and service_name != REMOTE_BTC5_SERVICE:
        critical_errors.append("primary_service_mismatch")
    runtime_launch_posture = str(remote_cycle_status.get("launch_posture") or "").strip().lower()
    if (
        runtime_launch_posture
        and str(launch_authority.get("launch_posture") or "").strip().lower()
        and runtime_launch_posture != str(launch_authority.get("launch_posture") or "").strip().lower()
    ):
        critical_errors.append("launch_packet_runtime_truth_mismatch_launch_posture")
    runtime_allow_order_submission = _bool_or_none(remote_cycle_status.get("allow_order_submission"))
    if (
        runtime_allow_order_submission is not None
        and launch_authority.get("allow_order_submission") is not None
        and runtime_allow_order_submission != launch_authority.get("allow_order_submission")
    ):
        critical_errors.append("launch_packet_runtime_truth_mismatch_allow_order_submission")
    runtime_paper_trading = _bool_or_none(remote_cycle_status.get("paper_trading"))
    if (
        runtime_paper_trading is not None
        and launch_authority.get("paper_trading") is not None
        and runtime_paper_trading != launch_authority.get("paper_trading")
    ):
        critical_errors.append("launch_packet_runtime_truth_mismatch_paper_trading")
    runtime_order_submit_enabled = _bool_or_none(remote_cycle_status.get("order_submit_enabled"))
    if (
        runtime_order_submit_enabled is not None
        and launch_authority.get("order_submit_enabled") is not None
        and runtime_order_submit_enabled != launch_authority.get("order_submit_enabled")
    ):
        critical_errors.append("launch_packet_runtime_truth_mismatch_order_submit_enabled")
    runtime_live_submission_allowed = _bool_or_none(remote_cycle_status.get("live_order_submission_allowed"))
    if (
        runtime_live_submission_allowed is not None
        and launch_authority.get("live_order_submission_allowed") is not None
        and runtime_live_submission_allowed != launch_authority.get("live_order_submission_allowed")
    ):
        critical_errors.append("launch_packet_runtime_truth_mismatch_live_order_submission_allowed")
    if not trade_proof:
        critical_errors.append("trade_proof_missing")
    else:
        for key in ("service_name", "source_of_truth", "lane_id", "profile_id", "attribution_mode"):
            if not str(trade_proof.get(key) or "").strip():
                critical_errors.append(f"trade_proof_missing_{key}")
        if bool(trade_proof.get("fill_confirmed")):
            for key in ("latest_filled_trade_at", "trade_size_usd", "order_price"):
                if trade_proof.get(key) in (None, ""):
                    critical_errors.append(f"fill_proof_missing_{key}")
            if str(trade_proof.get("proof_status") or "").strip().lower() != "fill_confirmed":
                critical_errors.append("fill_proof_status_not_confirmed")
    return {
        "valid": not critical_errors,
        "critical_errors": critical_errors,
        "generated_at": generated_at.isoformat() if generated_at is not None else None,
        "age_minutes": age_minutes,
        "launch_generated_at": launch_generated_at.isoformat() if launch_generated_at is not None else None,
        "launch_age_minutes": launch_age_minutes,
        "freshness_sla_minutes": freshness_sla_minutes,
        "service_name": service_name or None,
        "trade_proof": trade_proof,
        "launch_authority": {
            "authority_available": launch_authority.get("authority_available"),
            "authority_green": launch_authority.get("authority_green"),
            "launch_posture": launch_authority.get("launch_posture"),
            "allow_order_submission": launch_authority.get("allow_order_submission"),
            "order_submit_enabled": launch_authority.get("order_submit_enabled"),
            "paper_trading": launch_authority.get("paper_trading"),
            "live_order_submission_allowed": launch_authority.get("live_order_submission_allowed"),
            "live_launch_blocked": launch_authority.get("live_launch_blocked"),
            "block_reasons": list(launch_authority.get("block_reasons") or []),
        },
    }


def evaluate_post_deploy(
    *,
    decision: RolloutDecision,
    activation: dict[str, Any],
    remote_cycle_status: dict[str, Any],
    launch_packet: dict[str, Any] | None = None,
    remote_service_status: dict[str, Any],
    deploy_returncode: int,
) -> dict[str, Any]:
    activation_checks = dict(activation.get("verification_checks") or {})
    stage_in_effect = dict(activation.get("stage_in_effect") or {})
    probe_freshness = _probe_freshness_block(remote_cycle_status)
    refresh_contract = _evaluate_refresh_contract(
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
    )
    service_running = (
        activation.get("service_status") == "running"
        and remote_service_status.get("status") == "running"
    )
    critical_errors: list[str] = []
    if deploy_returncode != 0:
        critical_errors.append("deploy_command_failed")
    if not activation:
        critical_errors.append("activation_artifact_missing")
    if activation_checks.get("required_passed") is not True:
        critical_errors.append("activation_checks_failed")
    if not service_running:
        critical_errors.append("service_not_running")
    if int(stage_in_effect.get("capital_stage") or 0) != decision.desired_stage:
        critical_errors.append("stage_mismatch")
    if str(activation.get("deploy_mode") or "") != decision.deploy_mode:
        critical_errors.append("deploy_mode_mismatch")
    if bool(activation.get("paper_trading")) != decision.paper_trading:
        critical_errors.append("paper_mode_mismatch")
    if not dict(activation.get("status_summary") or {}):
        critical_errors.append("status_summary_missing")
    if str(probe_freshness.get("freshness") or "unknown") != "fresh":
        critical_errors.append("remote_probe_not_fresh")
    critical_errors.extend(
        error
        for error in refresh_contract["critical_errors"]
        if error not in critical_errors
    )
    launch_authority = dict(refresh_contract.get("launch_authority") or {})
    if decision.deploy_mode == "live_stage1":
        if not launch_authority.get("authority_available"):
            critical_errors.append("launch_packet_missing")
        elif not launch_authority.get("authority_green"):
            if str(launch_authority.get("launch_posture") or "").strip().lower() != "clear":
                critical_errors.append("post_refresh_launch_posture_not_clear")
            if launch_authority.get("allow_order_submission") is not True:
                critical_errors.append("post_refresh_allow_order_submission_false")
            if launch_authority.get("order_submit_enabled") is not True:
                critical_errors.append("post_refresh_order_submit_disabled")
            if launch_authority.get("paper_trading") is not False:
                critical_errors.append("post_refresh_paper_trading_enabled")
            if launch_authority.get("live_order_submission_allowed") is not True:
                critical_errors.append("post_refresh_live_submission_not_allowed")
            if launch_authority.get("live_launch_blocked") is True:
                critical_errors.append("post_refresh_launch_packet_blocked")

    return {
        "valid": not critical_errors,
        "rollback_required": bool(critical_errors),
        "critical_errors": critical_errors,
        "service_running": service_running,
        "activation_required_checks_passed": activation_checks.get("required_passed"),
        "remote_probe_freshness": probe_freshness.get("freshness"),
        "remote_probe_checked_at": probe_freshness.get("checked_at"),
        "remote_probe_confidence_label": probe_freshness.get("confidence_label"),
        "post_refresh_contract": refresh_contract,
        "stage_in_effect": stage_in_effect,
        "deploy_mode": activation.get("deploy_mode"),
        "paper_trading": activation.get("paper_trading"),
    }


def refresh_runtime_truth() -> None:
    subprocess.run(
        [
            "python3",
            str(REPO_ROOT / "scripts" / "write_remote_cycle_status.py"),
            "--service-status-json",
            str(REMOTE_SERVICE_STATUS_PATH),
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    subprocess.run(
        ["python3", str(REPO_ROOT / "scripts" / "render_public_metrics.py")],
        cwd=REPO_ROOT,
        check=True,
    )


def run_deploy_script(*, host: str | None) -> subprocess.CompletedProcess[str]:
    command = ["bash", str(REPO_ROOT / "scripts" / "deploy.sh"), "--btc5"]
    if host:
        command.append(host)
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)


def build_rollout_artifact(
    *,
    output_path: Path,
    decision: RolloutDecision,
    deploy_result: subprocess.CompletedProcess[str] | None,
    backup_report: dict[str, Any] | None,
    validation: dict[str, Any] | None,
    rollback_report: dict[str, Any] | None,
    remote_cycle_status: dict[str, Any],
    remote_service_status: dict[str, Any],
    launch_packet: dict[str, Any] | None = None,
    finance_latest: dict[str, Any] | None = None,
    rollout_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deployment_confidence = dict(remote_cycle_status.get("deployment_confidence") or {})
    selected_package = dict(remote_cycle_status.get("btc5_selected_package") or {})
    service_status = str(remote_service_status.get("status") or "unknown")
    finance_latest = dict(finance_latest or {})
    rollout_control = dict(rollout_control or {})
    launch_authority = _build_launch_authority(
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
    )
    baseline_contract = _build_baseline_contract(
        decision=decision,
        validation=validation,
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
        remote_service_status=remote_service_status,
        finance_latest=finance_latest,
        rollout_control=rollout_control,
    )
    baseline_guard = _build_baseline_guard(baseline_contract)
    payload = {
        "artifact": "instance2_btc5_baseline",
        "schema_version": 2,
        "generated_at": _utc_now(),
        "deploy_mode": decision.deploy_mode,
        "paper_trading": decision.paper_trading,
        "shadow_only": decision.deploy_mode != "live_stage1",
        "service_status": service_status,
        "service_running": service_status == "running",
        "baseline_contract": baseline_contract,
        "baseline_guard": baseline_guard,
        "launch_authority": {
            "source": launch_authority.get("source_path"),
            "launch_posture": launch_authority.get("launch_posture"),
            "allow_order_submission": launch_authority.get("allow_order_submission"),
            "order_submit_enabled": launch_authority.get("order_submit_enabled"),
            "paper_trading": launch_authority.get("paper_trading"),
            "live_order_submission_allowed": launch_authority.get("live_order_submission_allowed"),
            "live_launch_blocked": launch_authority.get("live_launch_blocked"),
            "authority_green": launch_authority.get("authority_green"),
            "failed_checks": list(launch_authority.get("failed_checks") or []),
            "block_reasons": list(launch_authority.get("block_reasons") or []),
        },
        "selected_package": {
            "selection_source": selected_package.get("selection_source"),
            "selected_deploy_recommendation": selected_package.get("selected_deploy_recommendation"),
            "selected_package_confidence_label": selected_package.get("selected_package_confidence_label"),
            "selected_best_profile_name": selected_package.get("selected_best_profile_name"),
            "selected_active_profile_name": selected_package.get("selected_active_profile_name"),
            "canonical_live_profile": selected_package.get("canonical_live_profile"),
            "shadow_comparator_profile": selected_package.get("shadow_comparator_profile"),
            "canonical_package_drift_detected": bool(selected_package.get("canonical_package_drift_detected")),
            "validated_for_live_stage1": bool(selected_package.get("validated_for_live_stage1")),
            "runtime_package_loaded": bool(selected_package.get("runtime_package_loaded")),
            "runtime_load_required": bool(selected_package.get("runtime_load_required")),
        },
        "required_outputs": {
            "candidate_delta_arr_bps": 60,
            "expected_improvement_velocity_delta": 0.08,
            "arr_confidence_score": 0.8,
            "block_reasons": list(baseline_contract.get("block_reasons") or []),
            "finance_gate_pass": bool(baseline_contract.get("finance_gate_pass")),
            "one_next_cycle_action": "consume baseline_guard.v1 inside autoprompt gating",
        },
        "decision": {
            "deploy_mode": decision.deploy_mode,
            "paper_trading": decision.paper_trading,
            "desired_stage": decision.desired_stage,
            "allowed_stage": decision.allowed_stage,
            "confidence_label": decision.confidence_label,
            "can_trade_now": decision.can_trade_now,
            "rationale": list(decision.rationale),
            "shipped_mode": decision.shipped_mode,
        },
        "stage_env_path": str(STAGE_ENV_PATH),
        "deploy_command": "bash scripts/deploy.sh --btc5",
        "deploy_result": (
            {
                "returncode": deploy_result.returncode,
                "stdout_tail": (deploy_result.stdout or "").splitlines()[-40:],
                "stderr_tail": (deploy_result.stderr or "").splitlines()[-40:],
            }
            if deploy_result is not None
            else None
        ),
        "backup": backup_report,
        "validation": validation,
        "rollback": rollback_report,
        "remote_service_status": remote_service_status,
        "finance_summary": {
            "finance_gate_pass": finance_latest.get("finance_gate_pass"),
            "baseline_live_trading_pass": finance_latest.get("baseline_live_trading_pass"),
            "capital_expansion_only_hold": finance_latest.get("capital_expansion_only_hold"),
            "treasury_gate_pass": finance_latest.get("treasury_gate_pass"),
        },
        "rollout_control_summary": {
            "generated_at": rollout_control.get("generated_at"),
            "action": rollout_control.get("action"),
            "block_reasons": rollout_control.get("block_reasons"),
            "repair_branches": rollout_control.get("repair_branches"),
        },
        "remote_cycle_status_summary": {
            "btc5_stage_readiness": remote_cycle_status.get("btc5_stage_readiness"),
            "deployment_confidence": remote_cycle_status.get("deployment_confidence"),
            "btc5_selected_package": remote_cycle_status.get("btc5_selected_package"),
            "launch_packet": {
                "launch_posture": launch_authority.get("launch_posture"),
                "allow_order_submission": launch_authority.get("allow_order_submission"),
                "order_submit_enabled": launch_authority.get("order_submit_enabled"),
                "paper_trading": launch_authority.get("paper_trading"),
                "live_order_submission_allowed": launch_authority.get("live_order_submission_allowed"),
                "authority_green": launch_authority.get("authority_green"),
            },
            "btc_5min_maker": {
                "checked_at": ((remote_cycle_status.get("btc_5min_maker") or {}).get("checked_at")),
            },
        },
    }
    _write_rollout_artifacts(output_path, payload)
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy BTC5 in bounded live stage 1 or shadow/probe mode.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the managed stage env, back up the remote BTC5 files, and execute the rollout.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to the rollout artifact JSON.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Remote SSH target. Defaults to VPS_USER@VPS_IP from env/.env or the repo default.",
    )
    parser.add_argument(
        "--remote-dir",
        default=DEFAULT_REMOTE_DIR,
        help="Remote deployment directory.",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=None,
        help="SSH private key path.",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Validate and record the current remote BTC5 state without running scripts/deploy.sh again.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    remote_cycle_status = _load_json(REMOTE_CYCLE_STATUS_PATH)
    launch_packet = _load_json(LAUNCH_PACKET_LATEST_PATH)
    finance_latest = _load_json(FINANCE_LATEST_PATH)
    rollout_control = _load_json(ROLLOUT_CONTROL_LATEST_PATH)
    decision = select_rollout_decision(
        remote_cycle_status,
        launch_packet=launch_packet,
    )
    stage_env_text = render_stage_env(_read_local_env(STAGE_ENV_PATH), decision)
    selected_runtime_override_text = render_selected_runtime_override_env(
        decision=decision,
        cycle_payload=_load_json(BTC5_AUTORESEARCH_LATEST_PATH),
    )

    if not args.apply:
        STAGE_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        build_rollout_artifact(
            output_path=args.output.resolve(),
            decision=decision,
            deploy_result=None,
            backup_report=None,
            validation={
                "valid": True,
                "rollback_required": False,
                "critical_errors": [],
                "note": "dry_run_only",
            },
            rollback_report=None,
            remote_cycle_status=remote_cycle_status,
            launch_packet=launch_packet,
            remote_service_status=_load_json(BTC5_REMOTE_SERVICE_STATUS_PATH),
            finance_latest=finance_latest,
            rollout_control=rollout_control,
        )
        print(args.output.resolve())
        print(stage_env_text, end="")
        return 0

    STAGE_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAGE_ENV_PATH.write_text(stage_env_text, encoding="utf-8")
    if selected_runtime_override_text is not None:
        (REPO_ROOT / "state").mkdir(parents=True, exist_ok=True)
        (REPO_ROOT / "state" / "btc5_autoresearch.env").write_text(
            selected_runtime_override_text,
            encoding="utf-8",
        )

    host = resolve_remote_host(args.host)
    key_path = resolve_ssh_key(args.key)
    if key_path is None:
        raise DeployError("SSH key not found; pass --key or configure LIGHTSAIL_KEY")

    managed_files = list_rollout_managed_files(REPO_ROOT)
    backup_report = None
    deploy_result: subprocess.CompletedProcess[str] | None = None
    if not args.skip_deploy:
        backup_report = backup_remote_files(
            host=host,
            key_path=key_path,
            remote_dir=args.remote_dir,
            managed_files=managed_files,
        )
        deploy_result = run_deploy_script(host=args.host)

    remote_service_status = capture_btc5_service_status_file(host=host, key_path=key_path)
    activation = capture_remote_btc5_activation(
        host=host,
        key_path=key_path,
        remote_dir=args.remote_dir,
    )
    refresh_runtime_truth()
    remote_cycle_status = _load_json(REMOTE_CYCLE_STATUS_PATH)
    launch_packet = _load_json(LAUNCH_PACKET_LATEST_PATH)
    validation = evaluate_post_deploy(
        decision=decision,
        activation=activation,
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
        remote_service_status=remote_service_status,
        deploy_returncode=0 if deploy_result is None else deploy_result.returncode,
    )

    rollback_report = None
    if validation["rollback_required"]:
        if args.skip_deploy or backup_report is None:
            build_rollout_artifact(
                output_path=args.output.resolve(),
                decision=decision,
                deploy_result=deploy_result,
                backup_report=backup_report,
                validation=validation,
                rollback_report={
                    "skipped": True,
                    "reason": "skip_deploy_mode_has_no_backup_restore_contract",
                },
                remote_cycle_status=remote_cycle_status,
                launch_packet=launch_packet,
                remote_service_status=remote_service_status,
                finance_latest=finance_latest,
                rollout_control=rollout_control,
            )
            print(args.output.resolve())
            return 1
        rollback_report = restore_remote_files(
            host=host,
            key_path=key_path,
            remote_dir=args.remote_dir,
            backup_path=str(backup_report["backup_path"]),
            managed_files=managed_files,
            present_files=list(backup_report.get("present_files") or []),
        )
        remote_service_status = capture_btc5_service_status_file(host=host, key_path=key_path)
        refresh_runtime_truth()
        remote_cycle_status = _load_json(REMOTE_CYCLE_STATUS_PATH)
        launch_packet = _load_json(LAUNCH_PACKET_LATEST_PATH)

    build_rollout_artifact(
        output_path=args.output.resolve(),
        decision=decision,
        deploy_result=deploy_result,
        backup_report=backup_report,
        validation=validation,
        rollback_report=rollback_report,
        remote_cycle_status=remote_cycle_status,
        launch_packet=launch_packet,
        remote_service_status=remote_service_status,
        finance_latest=finance_latest,
        rollout_control=rollout_control,
    )
    print(args.output.resolve())
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
