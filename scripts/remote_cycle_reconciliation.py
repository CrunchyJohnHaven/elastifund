from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.remote_cycle_common import dedupe_preserve_order, relative_path_text


RESEARCH_ARTIFACT_STALE_HOURS = 6.0


def _parse_datetime_like(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


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


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _remove_items(items: list[Any], blocked: set[str]) -> list[str]:
    return [
        str(item).strip()
        for item in items
        if str(item).strip() and str(item).strip() not in blocked
    ]


def _is_non_primary_service_noise(reason: str) -> bool:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return False
    noise_tokens = (
        "jj-live.service",
        "service_target_mismatch",
        "launch_blocked_but_service_running",
        "stale_service_file_with_fresh_btc5_probe",
        "service_status_stale",
    )
    return any(token in normalized for token in noise_tokens)


def _narrow_live_safety_blockers(reasons: list[Any]) -> list[str]:
    narrowed: list[str] = []
    for reason in reasons:
        text = str(reason).strip()
        if not text:
            continue
        if _is_non_primary_service_noise(text):
            continue
        narrowed.append(text)
    return dedupe_preserve_order(narrowed)


def _normalize_stale_check(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text
    if normalized.startswith("hold_repair:"):
        normalized = normalized[len("hold_repair:") :]
        normalized = normalized.split(":", 1)[0].strip()
    return normalized


def _is_stale_reason(value: Any) -> bool:
    normalized = _normalize_stale_check(value).lower()
    return bool(normalized and "stale" in normalized)


def _normalize_reason_token(value: Any) -> str:
    return str(value or "").strip().lower()


def _classify_blocker_scope(value: Any) -> str:
    normalized = _normalize_reason_token(value)
    if not normalized:
        return "unknown"
    baseline_tokens = (
        "launch_posture_not_clear",
        "service_state_not_running",
        "execution_mode_not_live",
        "paper_trading_enabled",
        "allow_order_submission_false",
        "order_submit_enabled_false",
        "baseline_live",
        "finance_gate_blocked",
    )
    if any(token in normalized for token in baseline_tokens):
        return "baseline_live"
    stage_tokens = (
        "stage_upgrade",
        "wallet_flow",
        "confirmation_",
        "trade_attribution",
        "signal_source_audit",
        "selected_runtime_package",
        "probe",
        "candidate",
    )
    if any(token in normalized for token in stage_tokens):
        return "stage_upgrade"
    capital_tokens = (
        "capital_expansion",
        "treasury",
        "next_100",
        "next_1000",
        "trailing_",
        "lmsr",
        "reserve",
        "allocation",
    )
    if any(token in normalized for token in capital_tokens):
        return "capital_expansion"
    return "unknown"


def _extract_signal_source_audit_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    state_improvement = dict(snapshot.get("state_improvement") or {})
    strategy = dict(state_improvement.get("strategy_recommendations") or {})
    control_plane = dict(strategy.get("control_plane_consistency") or {})
    capital_consistency = dict(control_plane.get("capital_consistency") or {})
    artifacts = dict(capital_consistency.get("artifacts") or {})
    audit = dict(artifacts.get("signal_source_audit") or {})
    return audit if isinstance(audit, dict) else {}


def _wallet_flow_disagreement_check(
    *,
    snapshot: dict[str, Any],
    stage_upgrade_checks: list[str],
    required_block_reasons: list[str],
) -> str | None:
    combined_checks = [
        str(item).strip()
        for item in [*list(stage_upgrade_checks or []), *list(required_block_reasons or [])]
        if str(item).strip()
    ]
    finance_or_stage_claims_wallet_not_ready = any(
        "wallet_flow_vs_llm_not_ready" in _normalize_reason_token(item)
        for item in combined_checks
    )
    if not finance_or_stage_claims_wallet_not_ready:
        return None

    audit = _extract_signal_source_audit_summary(snapshot)
    if not audit:
        return None
    wallet_flow_ready = _bool_or_none(audit.get("wallet_flow_confirmation_ready"))
    if wallet_flow_ready is not True:
        ready_sources = {
            _normalize_reason_token(item)
            for item in list(audit.get("confirmation_sources_ready") or [])
            if _normalize_reason_token(item)
        }
        if "wallet_flow" in ready_sources:
            wallet_flow_ready = True
    if wallet_flow_ready is True:
        return "wallet_flow_readiness_disagreement_finance_vs_signal_source"
    return None


def _resolve_canonical_live_profile_id(
    *,
    snapshot: dict[str, Any],
    champion_lane: dict[str, Any],
) -> str:
    """Resolve the single canonical live profile id.

    Precedence is deterministic:
    1. selected_active_profile_name from the BTC5 selected-package surface
       (this is the currently-running live profile)
    2. effective_runtime_profile / selected_runtime_profile
       (runtime truth fallbacks)
    3. selected_policy_id
    4. champion_lane.selected_profile_name
    5. selected_best_profile_name (frontier candidate — used only as
       last-resort label, NOT as a live-promotion signal)

    The launch-packet builder in remote_cycle_status_core.py MUST use
    the same precedence so both surfaces agree on the canonical id.
    """
    selected_package = dict(snapshot.get("btc5_selected_package") or {})
    candidates = (
        # --- currently-running live profile (highest priority) ---
        selected_package.get("selected_active_profile_name"),
        snapshot.get("effective_runtime_profile"),
        snapshot.get("selected_runtime_profile"),
        # --- policy / champion fallbacks ---
        snapshot.get("selected_policy_id"),
        champion_lane.get("selected_profile_name"),
        # --- frontier / best (label only, NOT promotion) ---
        snapshot.get("selected_best_profile"),
        selected_package.get("selected_best_profile_name"),
    )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return "active_profile"


def _resolve_canonical_live_package_hash(
    *,
    snapshot: dict[str, Any],
    canonical_live_profile_id: str,
) -> str | None:
    selected_package = dict(snapshot.get("btc5_selected_package") or {})
    candidates = (
        (
            str(selected_package.get("canonical_live_profile") or "").strip(),
            str(selected_package.get("canonical_live_package_hash") or "").strip(),
        ),
        (
            str(selected_package.get("selected_active_profile_name") or "").strip(),
            str(selected_package.get("selected_active_package_hash") or "").strip(),
        ),
        (
            str(selected_package.get("selected_best_profile_name") or "").strip(),
            str(selected_package.get("selected_best_package_hash") or "").strip(),
        ),
    )
    snapshot_hash = str(snapshot.get("canonical_live_package_hash") or "").strip()
    if snapshot_hash:
        return snapshot_hash
    for profile_name, package_hash in candidates:
        if profile_name and profile_name == canonical_live_profile_id and package_hash:
            return package_hash
    for _profile_name, package_hash in candidates:
        if package_hash:
            return package_hash
    return None


def _build_stale_hold_repair(
    *,
    stage_readiness: dict[str, Any],
    deployment_confidence: dict[str, Any],
    selected_package: dict[str, Any],
    wallet_reconciliation_summary: dict[str, Any],
    blocker_classes: dict[str, Any],
    required_block_reasons: list[str],
    retry_in_minutes: int,
) -> dict[str, Any]:
    stale_candidates: list[str] = []
    for bucket in blocker_classes.values():
        if not isinstance(bucket, dict):
            continue
        stale_candidates.extend(
            _normalize_stale_check(item) for item in list(bucket.get("checks") or [])
        )
    stale_candidates.extend(_normalize_stale_check(item) for item in list(required_block_reasons or []))
    stale_candidates.extend(
        _normalize_stale_check(item)
        for item in list(
            deployment_confidence.get("blocking_checks")
            or stage_readiness.get("stage_upgrade_trade_now_blocking_checks")
            or []
        )
    )
    stale_checks = dedupe_preserve_order(
        [
            item
            for item in stale_candidates
            if item and "stale" in item.lower() and not _is_non_primary_service_noise(item)
        ]
    )
    retry_at = (datetime.now(timezone.utc) + timedelta(minutes=retry_in_minutes)).isoformat()

    branches: list[dict[str, Any]] = []
    for check in stale_checks:
        source: str | None = None
        age_hours: float | None = None
        normalized = str(check).strip().lower()
        if normalized == "wallet_export_stale":
            source = (
                str(
                    wallet_reconciliation_summary.get("source_artifact")
                    or stage_readiness.get("source_artifact")
                    or "reports/wallet_reconciliation/latest.json"
                )
                .strip()
                or "reports/wallet_reconciliation/latest.json"
            )
            age_hours = _float_or_none(
                wallet_reconciliation_summary.get("source_age_hours")
            ) or _float_or_none(stage_readiness.get("wallet_export_freshness_hours"))
        elif normalized == "selected_runtime_package_stale":
            source = (
                str(
                    selected_package.get("path")
                    or selected_package.get("selection_source")
                    or selected_package.get("runtime_load_evidence_source")
                    or ((deployment_confidence.get("validated_package") or {}).get("source_artifact"))
                    or "reports/autoresearch/btc5_policy/latest.json"
                )
                .strip()
                or "reports/autoresearch/btc5_policy/latest.json"
            )
            age_hours = _float_or_none(selected_package.get("age_hours"))
        elif normalized == "stage_upgrade_probe_stale":
            source = (
                str(
                    stage_readiness.get("current_probe_artifact")
                    or "reports/btc5_autoresearch_current_probe/latest.json"
                )
                .strip()
                or "reports/btc5_autoresearch_current_probe/latest.json"
            )
            age_hours = _float_or_none(stage_readiness.get("probe_freshness_hours"))
        elif normalized == "strategy_scale_comparison_stale":
            source = (
                str(
                    stage_readiness.get("source_artifact")
                    or "reports/strategy_scale_comparison.json"
                )
                .strip()
                or "reports/strategy_scale_comparison.json"
            )
            age_hours = _float_or_none(stage_readiness.get("age_hours"))
        elif normalized == "signal_source_audit_stale":
            source = "reports/runtime/signals/signal_source_audit.json"
            age_hours = None
        else:
            source = (
                str(
                    stage_readiness.get("source_artifact")
                    or selected_package.get("path")
                    or "reports/runtime_truth_latest.json"
                )
                .strip()
                or "reports/runtime_truth_latest.json"
            )
            age_hours = _float_or_none(stage_readiness.get("age_hours")) or _float_or_none(
                selected_package.get("age_hours")
            )

        if normalized in {
            "selected_runtime_package_stale",
            "strategy_scale_comparison_stale",
            "signal_source_audit_stale",
            "stage_upgrade_probe_stale",
        } and age_hours is not None and age_hours <= RESEARCH_ARTIFACT_STALE_HOURS:
            continue

        age_text = f"{age_hours:.4f}" if age_hours is not None else "unknown"
        reason_label = (
            f"hold_repair:{check}:source={source}:age_hours={age_text}:retry_in_minutes={retry_in_minutes}"
        )
        branches.append(
            {
                "check": check,
                "source": source,
                "age_hours": round(age_hours, 4) if age_hours is not None else None,
                "status": "hold_repair",
                "retry_in_minutes": retry_in_minutes,
                "retry_at": retry_at,
                "reason_label": reason_label,
            }
        )

    return {
        "active": bool(branches),
        "status": "hold_repair" if branches else "clear",
        "retry_in_minutes": retry_in_minutes,
        "retry_at": retry_at if branches else None,
        "repair_branches": branches,
        "block_reasons": [branch["reason_label"] for branch in branches],
    }


def _reconcile_btc5_baseline_live(snapshot: dict[str, Any], launch_packet: dict[str, Any]) -> None:
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    finance_gate_payload = dict(launch_packet.get("finance_gate") or {})
    contract = dict(launch_packet.get("contract") or {})
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    launch_state = dict(snapshot.get("launch_state") or launch_packet.get("launch_state") or {})
    stage_state = dict(launch_state.get("stage") or {})
    btc5_stage_readiness = dict(snapshot.get("btc5_stage_readiness") or {})
    deployment_confidence = dict(snapshot.get("deployment_confidence") or {})
    accounting_reconciliation = dict(snapshot.get("accounting_reconciliation") or {})
    service = dict(snapshot.get("service") or {})
    state_improvement = dict(snapshot.get("state_improvement") or {})
    strategy = dict(state_improvement.get("strategy_recommendations") or {})
    champion = dict(strategy.get("champion_lane_contract") or {})
    blocker_classes = dict(champion.get("blocker_classes") or {})
    required_outputs = dict(champion.get("required_outputs") or {})
    candidate_recovery = dict(strategy.get("btc5_candidate_recovery") or {})

    finance_gate_pass = bool(mandatory_outputs.get("finance_gate_pass", True))
    treasury_gate_pass = bool(
        mandatory_outputs.get(
            "treasury_gate_pass",
            mandatory_outputs.get("finance_gate_pass", True),
        )
    )
    baseline_live_trading_pass = bool(
        mandatory_outputs.get(
            "finance_gate_pass",
            finance_gate_payload.get("pass", True),
        )
    )
    capital_expansion_only_hold = bool(
        finance_gate_payload.get("capital_expansion_only_hold")
        if "capital_expansion_only_hold" in finance_gate_payload
        else not treasury_gate_pass
    )
    launch_posture = str(launch_verdict.get("posture") or snapshot.get("launch_posture") or "blocked").strip().lower()
    service_state = str(
        contract.get("service_state")
        or snapshot.get("service_state")
        or service.get("status")
        or "unknown"
    ).strip().lower()
    expected_primary_service = "btc-5min-maker.service"
    observed_service_name = str(
        service.get("service_name")
        or snapshot.get("service_name")
        or snapshot.get("observed_service_name")
        or ""
    ).strip()
    service_name = observed_service_name or expected_primary_service
    service_name_resolution = (
        "observed_service_probe"
        if observed_service_name
        else "default_expected_service_non_safety_hold_repair"
    )
    execution_mode = str(
        contract.get("execution_mode")
        or snapshot.get("execution_mode")
        or "unknown"
    ).strip().lower()
    paper_trading = _bool_or_none(
        contract.get("paper_trading")
        if contract.get("paper_trading") is not None
        else snapshot.get("paper_trading")
    )
    allow_order_submission = bool(
        contract.get("allow_order_submission")
        if contract.get("allow_order_submission") is not None
        else snapshot.get("allow_order_submission")
    )
    order_submit_enabled = bool(
        contract.get("order_submit_enabled")
        if contract.get("order_submit_enabled") is not None
        else snapshot.get("order_submit_enabled")
    )

    # Baseline-live blockers are strictly safety-level checks plus the
    # finance gate.  Stale non-safety artifacts (wallet-flow disagreement,
    # candidate staleness, attribution gaps) MUST NOT appear here — they
    # are routed to hold_repair branches instead.
    baseline_live_blockers: list[str] = []
    if launch_posture != "clear":
        baseline_live_blockers.append(f"launch_posture_not_clear:{launch_posture or 'unknown'}")
    if service_state != "running":
        baseline_live_blockers.append(f"service_state_not_running:{service_state or 'unknown'}")
    if execution_mode != "live":
        baseline_live_blockers.append(f"execution_mode_not_live:{execution_mode or 'unknown'}")
    if paper_trading is True:
        baseline_live_blockers.append("paper_trading_enabled")
    if not allow_order_submission:
        baseline_live_blockers.append("allow_order_submission_false")
    if not order_submit_enabled:
        baseline_live_blockers.append("order_submit_enabled_false")
    # Finance gate blocks baseline only when the finance artifact explicitly
    # denies baseline-live permission.  If baseline_live_trading_pass is True
    # in the finance artifact but finance_gate_pass resolved False (e.g. due
    # to staleness or a treasury-level blocker), do NOT shut down the live
    # baseline — route the disagreement to hold_repair instead.
    if not finance_gate_pass and not baseline_live_trading_pass:
        baseline_live_blockers.append("finance_gate_blocked")

    baseline_live_allowed = not baseline_live_blockers
    stage_upgrade_can_trade_now = bool(
        deployment_confidence.get("stage_upgrade_can_trade_now")
        if "stage_upgrade_can_trade_now" in deployment_confidence
        else deployment_confidence.get("can_btc5_trade_now")
    )
    stage_upgrade_allowed = bool(stage_upgrade_can_trade_now)
    capital_expansion_allowed = bool(treasury_gate_pass)
    permission_states = {
        "baseline_live_allowed": baseline_live_allowed,
        "stage_upgrade_allowed": stage_upgrade_allowed,
        "capital_expansion_allowed": capital_expansion_allowed,
    }
    stage_upgrade_trade_now_status = "unblocked" if stage_upgrade_can_trade_now else "blocked"
    stage_upgrade_trade_now_blocking_checks = list(
        btc5_stage_readiness.get("stage_upgrade_trade_now_blocking_checks")
        or btc5_stage_readiness.get("deployment_trade_now_blocking_checks")
        or deployment_confidence.get("stage_1_blockers")
        or btc5_stage_readiness.get("blocking_checks")
        or []
    )
    if not stage_upgrade_trade_now_blocking_checks and not stage_upgrade_can_trade_now:
        stage_upgrade_trade_now_blocking_checks = ["stage_upgrade_blocked_by_deployment_confidence"]
    stage_upgrade_trade_now_reasons = list(
        btc5_stage_readiness.get("stage_upgrade_trade_now_reasons")
        or btc5_stage_readiness.get("deployment_trade_now_reasons")
        or btc5_stage_readiness.get("trade_now_reasons")
        or []
    )
    if not stage_upgrade_trade_now_reasons:
        stage_upgrade_trade_now_reasons = (
            [
                "BTC5 stage-upgrade progression is blocked by deployment confidence checks."
            ]
            if not stage_upgrade_can_trade_now
            else [
                "BTC5 stage-upgrade progression is currently unblocked."
            ]
        )
    btc5_stage_readiness.update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "baseline_live_status": "unblocked" if baseline_live_allowed else "blocked",
            "baseline_live_blocking_checks": list(baseline_live_blockers),
            "can_trade_now": baseline_live_allowed,
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "stage_upgrade_allowed": stage_upgrade_allowed,
            "capital_expansion_allowed": capital_expansion_allowed,
            "stage_upgrade_trade_now_status": stage_upgrade_trade_now_status,
            "stage_upgrade_trade_now_blocking_checks": list(stage_upgrade_trade_now_blocking_checks),
            "stage_upgrade_trade_now_reasons": list(stage_upgrade_trade_now_reasons),
            "trade_now_status": "unblocked" if baseline_live_allowed else "blocked",
            "trade_now_blocking_checks": list(baseline_live_blockers),
            "trade_now_reasons": (
                [
                    "BTC5 baseline live trading is permitted at flat stage-1 size while stage upgrades remain separately gated."
                ]
                if baseline_live_allowed
                else ["BTC5 baseline live trading is blocked by the launch/runtime/finance contract."]
            ),
        }
    )
    snapshot["btc5_stage_readiness"] = btc5_stage_readiness

    deployment_confidence.update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "baseline_live_status": "unblocked" if baseline_live_allowed else "blocked",
            "baseline_live_blocking_checks": list(baseline_live_blockers),
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "stage_upgrade_allowed": stage_upgrade_allowed,
            "capital_expansion_allowed": capital_expansion_allowed,
            "stage_upgrade_trade_now_reasons": stage_upgrade_trade_now_reasons,
        }
    )
    snapshot["deployment_confidence"] = deployment_confidence

    stage_state.update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "baseline_live_blocking_checks": list(baseline_live_blockers),
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "stage_upgrade_allowed": stage_upgrade_allowed,
            "capital_expansion_allowed": capital_expansion_allowed,
            "stage_upgrade_blocking_checks": list(
                btc5_stage_readiness.get("stage_upgrade_trade_now_blocking_checks") or []
            ),
            "can_trade_now": baseline_live_allowed,
            "blocking_checks": list(baseline_live_blockers),
        }
    )
    launch_state["stage"] = stage_state
    snapshot["launch_state"] = launch_state
    launch_packet.setdefault("launch_state", {})["stage"] = stage_state

    snapshot["can_btc5_trade_now"] = baseline_live_allowed
    snapshot["btc5_baseline_live_allowed"] = baseline_live_allowed
    snapshot["btc5_stage_upgrade_can_trade_now"] = stage_upgrade_can_trade_now
    snapshot.update(permission_states)
    snapshot["state_permissions"] = dict(permission_states)

    service_drift_reasons = {
        "Service-state drift: btc-5min-maker.service is running while launch posture remains blocked; confirm the remote mode is paper or shadow.",
    }
    stale_truth_blockers = set()
    if not accounting_reconciliation.get("drift_detected"):
        stale_truth_blockers.add("accounting_reconciliation_drift")
    if launch_posture == "clear" and service_state == "running":
        stale_truth_blockers.update({"service_status_stale", "stale_service_file_with_fresh_btc5_probe"})

    drift_payload = dict(snapshot.get("drift") or {})
    drift_reasons = [
        reason
        for reason in list(drift_payload.get("reasons") or [])
        if reason not in service_drift_reasons
        and not reason.startswith("finance_gate_blocked:")
        and not reason.startswith("Accounting drift: ")
    ]
    if accounting_reconciliation.get("drift_detected"):
        drift_reasons.extend(
            [
                reason
                for reason in list(drift_payload.get("reasons") or [])
                if str(reason).startswith("Accounting drift: ")
            ]
        )
    if not finance_gate_pass:
        drift_reasons.extend(
            [
                reason
                for reason in list(drift_payload.get("reasons") or [])
                if str(reason).startswith("finance_gate_blocked:")
            ]
        )
    drift_payload.update(
        {
            "service_running_while_launch_blocked": launch_posture != "clear" and service_state == "running",
            "reasons": _narrow_live_safety_blockers(drift_reasons),
        }
    )
    drift_payload["detected"] = bool(
        drift_payload.get("drift_kill_gate_triggered") or drift_payload.get("reasons")
    )
    snapshot["drift"] = drift_payload
    snapshot["drift_detected"] = bool(drift_payload["detected"])
    snapshot["service_drift_detected"] = bool(drift_payload["service_running_while_launch_blocked"])
    snapshot["accounting_drift_detected"] = bool(accounting_reconciliation.get("drift_detected"))

    service["drift_detected"] = bool(drift_payload["service_running_while_launch_blocked"])
    service["drift_reason"] = (
        "Service-state drift: btc-5min-maker.service is running while launch posture remains blocked; confirm the remote mode is paper or shadow."
        if service["drift_detected"]
        else None
    )
    service["service_name"] = service_name
    snapshot["service"] = service
    snapshot["service_name"] = service_name
    snapshot["service_name_resolution"] = service_name_resolution
    snapshot["expected_service_name"] = expected_primary_service
    snapshot["observed_service_name"] = observed_service_name or None
    snapshot["service_consistency"] = (
        "mismatch"
        if observed_service_name and observed_service_name != expected_primary_service
        else "consistent"
    )
    snapshot["baseline_live_trading_pass"] = baseline_live_trading_pass
    snapshot["capital_expansion_only_hold"] = capital_expansion_only_hold

    reconciliation = dict(snapshot.get("reconciliation") or {})
    if isinstance(reconciliation.get("service"), dict):
        reconciliation_service = dict(reconciliation.get("service") or {})
        reconciliation_service["drift_detected"] = service["drift_detected"]
        reconciliation_service["drift_reason"] = service["drift_reason"]
        reconciliation_service["service_name"] = service_name
        reconciliation["service"] = reconciliation_service
    snapshot["reconciliation"] = reconciliation

    launch_payload = dict(snapshot.get("launch") or {})
    launch_payload["posture"] = launch_posture
    launch_payload["live_launch_blocked"] = bool(launch_verdict.get("live_launch_blocked"))
    snapshot["launch"] = launch_payload

    summary = dict(snapshot.get("summary") or {})
    summary.update(
        {
            "btc5_can_trade_now": baseline_live_allowed,
            "btc5_baseline_live_allowed": baseline_live_allowed,
            "btc5_stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "baseline_live_allowed": baseline_live_allowed,
            "stage_upgrade_allowed": stage_upgrade_allowed,
            "capital_expansion_allowed": capital_expansion_allowed,
            "drift_detected": bool(drift_payload["detected"]),
        }
    )

    retry_minutes = (
        int(champion.get("finance_gate", {}).get("retry_in_minutes") or 0) or 10
    )
    retry_minutes = max(retry_minutes, 10)
    wallet_reconciliation_summary = dict(strategy.get("wallet_reconciliation_summary") or {})
    stale_hold_repair = _build_stale_hold_repair(
        stage_readiness=btc5_stage_readiness,
        deployment_confidence=deployment_confidence,
        selected_package=dict(snapshot.get("btc5_selected_package") or {}),
        wallet_reconciliation_summary=wallet_reconciliation_summary,
        blocker_classes=blocker_classes,
        required_block_reasons=list(required_outputs.get("block_reasons") or []),
        retry_in_minutes=retry_minutes,
    )
    wallet_flow_disagreement = _wallet_flow_disagreement_check(
        snapshot=snapshot,
        stage_upgrade_checks=list(stage_upgrade_trade_now_blocking_checks),
        required_block_reasons=list(required_outputs.get("block_reasons") or []),
    )
    if wallet_flow_disagreement:
        audit_summary = _extract_signal_source_audit_summary(snapshot)
        disagreement_source = str(
            audit_summary.get("path") or "reports/runtime/signals/signal_source_audit.json"
        ).strip() or "reports/runtime/signals/signal_source_audit.json"
        disagreement_age = _float_or_none(audit_summary.get("age_hours"))
        age_text = f"{disagreement_age:.4f}" if disagreement_age is not None else "unknown"
        reason_label = (
            "hold_repair:"
            f"{wallet_flow_disagreement}:source={disagreement_source}:age_hours={age_text}:retry_in_minutes={retry_minutes}"
        )
        existing_checks = {
            str(item.get("check")).strip()
            for item in list(stale_hold_repair.get("repair_branches") or [])
            if isinstance(item, dict) and str(item.get("check") or "").strip()
        }
        if wallet_flow_disagreement not in existing_checks:
            stale_hold_repair.setdefault("repair_branches", []).append(
                {
                    "check": wallet_flow_disagreement,
                    "source": disagreement_source,
                    "age_hours": round(disagreement_age, 4) if disagreement_age is not None else None,
                    "status": "hold_repair",
                    "retry_in_minutes": retry_minutes,
                    "retry_at": stale_hold_repair.get("retry_at"),
                    "reason_label": reason_label,
                }
            )
            stale_hold_repair.setdefault("block_reasons", []).append(reason_label)
        stale_hold_repair["active"] = bool(stale_hold_repair.get("repair_branches"))
        stale_hold_repair["status"] = "hold_repair" if stale_hold_repair["active"] else "clear"
        stale_hold_repair["block_reasons"] = dedupe_preserve_order(
            list(stale_hold_repair.get("block_reasons") or [])
        )
    stale_repair_checks = {
        str(item.get("check")).strip()
        for item in list(stale_hold_repair.get("repair_branches") or [])
        if isinstance(item, dict) and str(item.get("check") or "").strip()
    }
    stale_truth_blockers.update(stale_repair_checks)

    truth_bucket = dict(blocker_classes.get("truth") or {})
    truth_checks = _remove_items(list(truth_bucket.get("checks") or []), stale_truth_blockers)
    truth_bucket["checks"] = truth_checks
    truth_bucket["status"] = "blocked" if truth_checks else "clear"
    blocker_classes["truth"] = truth_bucket

    required_outputs["block_reasons"] = _remove_items(
        list(required_outputs.get("block_reasons") or []),
        stale_truth_blockers,
    )
    required_outputs["block_reasons"] = _narrow_live_safety_blockers(
        list(required_outputs.get("block_reasons") or [])
    )
    required_outputs["block_reasons"] = dedupe_preserve_order(
        list(required_outputs.get("block_reasons") or [])
        + list(stale_hold_repair.get("block_reasons") or [])
    )
    champion_lane = dict(champion.get("champion_lane") or {})
    champion_lane.update(
        {
            "can_trade_now": baseline_live_allowed,
            "baseline_live_allowed": baseline_live_allowed,
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
        }
    )
    champion["champion_lane"] = champion_lane
    champion["blocker_classes"] = blocker_classes
    champion["required_outputs"] = required_outputs
    champion["stale_hold_repair"] = stale_hold_repair
    champion["hold_repair"] = stale_hold_repair
    launch_packet["stale_hold_repair"] = stale_hold_repair
    launch_packet["hold_repair"] = stale_hold_repair
    launch_packet["state_permissions"] = dict(permission_states)
    launch_packet.setdefault("launch_verdict", {}).update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "stage_upgrade_allowed": stage_upgrade_allowed,
            "capital_expansion_allowed": capital_expansion_allowed,
        }
    )
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    mandatory_outputs["block_reasons"] = _narrow_live_safety_blockers(
        list(mandatory_outputs.get("block_reasons") or [])
    )
    mandatory_outputs["block_reasons"] = dedupe_preserve_order(
        list(mandatory_outputs.get("block_reasons") or [])
        + list(stale_hold_repair.get("block_reasons") or [])
    )
    launch_packet["mandatory_outputs"] = mandatory_outputs

    launch_allows_baseline = bool(launch_verdict.get("allow_execution")) and launch_posture == "clear"
    rollout_checks = {
        "baseline_live_permission_consensus": (
            baseline_live_allowed == launch_allows_baseline == finance_gate_pass
        ),
        "launch_packet_allows_baseline_live": launch_allows_baseline,
        "runtime_truth_allows_baseline_live": baseline_live_allowed,
        "finance_packet_allows_baseline_live": finance_gate_pass,
    }
    rollout_checks["mismatches"] = (
        []
        if rollout_checks["baseline_live_permission_consensus"]
        else [
            "baseline_live_permission_mismatch_across_truth_launch_finance",
        ]
    )
    launch_packet["rollout_checks"] = rollout_checks
    snapshot["rollout_checks"] = rollout_checks
    snapshot["stale_hold_repair"] = stale_hold_repair
    snapshot["hold_repair"] = stale_hold_repair

    safety_gate_prefixes = {
        "launch_posture_not_clear",
        "service_state_not_running",
        "execution_mode_not_live",
        "paper_trading_enabled",
        "allow_order_submission_false",
        "order_submit_enabled_false",
    }
    safety_blockers = [
        blocker
        for blocker in list(baseline_live_blockers)
        if str(blocker).split(":", 1)[0] in safety_gate_prefixes
    ]
    if not baseline_live_allowed and safety_blockers:
        operator_verdict_code = "stop_for_safety"
        operator_verdict_reason = (
            f"Stop live execution until safety blockers clear: {', '.join(safety_blockers)}."
        )
    elif baseline_live_allowed:
        operator_verdict_code = "continue_bounded_live"
        operator_verdict_reason = (
            "Baseline live is clear at flat stage-1 size; hold all profile/scale promotions until upgrade gates clear."
        )
    else:
        operator_verdict_code = "hold_profile_changes"
        operator_verdict_reason = (
            "Hold profile changes and continue repair branches until the baseline contract is explicitly clear."
        )
    if operator_verdict_code not in {
        "continue_bounded_live",
        "hold_profile_changes",
        "stop_for_safety",
    }:
        operator_verdict_code = "hold_profile_changes"
    operator_verdict = {
        "code": operator_verdict_code,
        "baseline_live_allowed": baseline_live_allowed,
        "stage_upgrade_allowed": stage_upgrade_allowed,
        "capital_expansion_allowed": capital_expansion_allowed,
        "profile_changes_allowed": bool(stage_upgrade_allowed and capital_expansion_allowed),
        "stale_hold_repair_active": bool(stale_hold_repair.get("active")),
        "reason": operator_verdict_reason,
    }
    snapshot["operator_verdict"] = operator_verdict
    snapshot["launch_operator_verdict"] = operator_verdict_code

    search_generated_at = _parse_datetime_like(candidate_recovery.get("generated_at"))
    search_stale = False
    if search_generated_at is not None:
        search_stale = (datetime.now(timezone.utc) - search_generated_at).total_seconds() > 6 * 3600

    canonical_live_profile_id = _resolve_canonical_live_profile_id(
        snapshot=snapshot,
        champion_lane=champion_lane,
    )
    canonical_live_package_hash = _resolve_canonical_live_package_hash(
        snapshot=snapshot,
        canonical_live_profile_id=canonical_live_profile_id,
    )
    champion_lane["selected_profile_name"] = canonical_live_profile_id
    champion["champion_lane"] = champion_lane
    snapshot["canonical_live_profile_id"] = canonical_live_profile_id
    snapshot["canonical_live_package_hash"] = canonical_live_package_hash

    stage_upgrade_blockers = dedupe_preserve_order(
        list(stage_upgrade_trade_now_blocking_checks or [])
        + list((blocker_classes.get("confirmation") or {}).get("checks") or [])
        + list((blocker_classes.get("candidate") or {}).get("checks") or [])
    )
    capital_expansion_blockers = dedupe_preserve_order(
        list((blocker_classes.get("capital") or {}).get("checks") or [])
        + [
            blocker
            for blocker in list(mandatory_outputs.get("block_reasons") or [])
            if _classify_blocker_scope(blocker) == "capital_expansion"
        ]
    )
    baseline_non_safety_blockers = [
        blocker for blocker in list(baseline_live_blockers) if blocker not in safety_blockers
    ]
    stage_non_stale_blockers = [
        blocker
        for blocker in stage_upgrade_blockers
        if str(blocker).strip() and not _is_stale_reason(blocker)
    ]
    capital_non_stale_blockers = [
        blocker
        for blocker in capital_expansion_blockers
        if str(blocker).strip() and not _is_stale_reason(blocker)
    ]
    stage_repair_branch_checks = [
        str(item.get("check")).strip()
        for item in list(stale_hold_repair.get("repair_branches") or [])
        if isinstance(item, dict)
        and str(item.get("check") or "").strip()
        and _classify_blocker_scope(item.get("check")) == "stage_upgrade"
    ]
    capital_repair_branch_checks = [
        str(item.get("check")).strip()
        for item in list(stale_hold_repair.get("repair_branches") or [])
        if isinstance(item, dict)
        and str(item.get("check") or "").strip()
        and _classify_blocker_scope(item.get("check")) == "capital_expansion"
    ]

    focus_scope = "clear"
    focus_reason = "stage_upgrade_blockers"
    if safety_blockers:
        focus_scope = "safety"
        focus_reason = str(safety_blockers[0])
    elif not baseline_live_allowed:
        focus_scope = "baseline_live"
        focus_reason = str(
            (baseline_non_safety_blockers or baseline_live_blockers or ["baseline_live_contract_blocked"])[0]
        )
    elif not stage_upgrade_can_trade_now:
        focus_scope = "stage_upgrade"
        focus_reason = str(
            (stage_non_stale_blockers or stage_repair_branch_checks or ["stage_upgrade_blockers"])[0]
        )
    elif not capital_expansion_allowed:
        focus_scope = "capital_expansion"
        focus_reason = str(
            (capital_non_stale_blockers or capital_repair_branch_checks or ["capital_expansion_blockers"])[0]
        )
    elif stale_hold_repair.get("active"):
        first_repair = next(
            (
                str(item.get("check")).strip()
                for item in list(stale_hold_repair.get("repair_branches") or [])
                if isinstance(item, dict) and str(item.get("check") or "").strip()
            ),
            "stale_artifact",
        )
        focus_scope = _classify_blocker_scope(first_repair)
        focus_reason = first_repair

    if baseline_live_allowed and not truth_checks and finance_gate_pass:
        champion["status"] = "candidate_ready"
        champion["decision_reason"] = (
            "btc5_baseline_live_allowed_stage_upgrade_blocked"
            if not stage_upgrade_can_trade_now
            else "btc5_is_the_only_tradeable_champion_lane"
        )
        if search_stale:
            champion.setdefault("notes", []).append(
                "fast_market_search_is_stale_do_not_let_old_search_blockers_override_the_live_baseline"
            )

    if focus_scope == "safety":
        next_action = (
            f"Stop live trading immediately; repair {focus_reason} and rerun the cycle packet in +{retry_minutes}m once safety is green."
        )
    elif focus_scope == "baseline_live" and not baseline_live_allowed:
        next_action = (
            f"Hold profile changes and repair {focus_reason} before resuming baseline live; rerun the cycle packet in +{retry_minutes}m."
        )
    elif focus_scope == "capital_expansion":
        next_action = (
            f"Keep BTC5 baseline live at flat stage-1 size via {canonical_live_profile_id}; "
            f"hold capital expansion while repairing {focus_reason} and rerun the cycle packet in +{retry_minutes}m."
        )
    elif baseline_live_allowed:
        next_action = (
            f"Keep BTC5 baseline live at flat stage-1 size via {canonical_live_profile_id}; "
            f"repair {focus_reason} before any stage upgrade or capital expansion and rerun the cycle packet in +{retry_minutes}m."
        )
    else:
        next_action = (
            f"Repair {focus_reason} and rerun the cycle packet in +{retry_minutes}m."
        )
    champion.setdefault("required_outputs", {})["one_next_cycle_action"] = next_action
    launch_packet.setdefault("mandatory_outputs", {})["one_next_cycle_action"] = next_action
    snapshot["one_next_cycle_action"] = next_action

    resolved_next_action = str(
        snapshot.get("one_next_cycle_action")
        or champion.get("required_outputs", {}).get("one_next_cycle_action")
        or launch_packet.get("mandatory_outputs", {}).get("one_next_cycle_action")
        or ""
    ).strip()
    if resolved_next_action:
        champion.setdefault("required_outputs", {})["one_next_cycle_action"] = resolved_next_action
        launch_packet.setdefault("mandatory_outputs", {})["one_next_cycle_action"] = resolved_next_action
        snapshot["one_next_cycle_action"] = resolved_next_action

    required_outputs_contract = {
        "candidate_delta_arr_bps": mandatory_outputs.get("candidate_delta_arr_bps"),
        "expected_improvement_velocity_delta": mandatory_outputs.get(
            "expected_improvement_velocity_delta"
        ),
        "arr_confidence_score": mandatory_outputs.get("arr_confidence_score"),
        "block_reasons": list(mandatory_outputs.get("block_reasons") or []),
        "finance_gate_pass": finance_gate_pass,
        "treasury_gate_pass": treasury_gate_pass,
        "one_next_cycle_action": snapshot.get("one_next_cycle_action"),
    }
    snapshot.update(required_outputs_contract)
    snapshot["required_outputs"] = dict(required_outputs_contract)
    launch_packet["required_outputs"] = dict(required_outputs_contract)

    launch_packet.update(
        {
            "service_name": service_name,
            "service_name_resolution": service_name_resolution,
            "allow_order_submission": allow_order_submission,
            "order_submit_enabled": order_submit_enabled,
            "canonical_live_profile_id": canonical_live_profile_id,
            "canonical_live_package_hash": canonical_live_package_hash,
            "launch_posture": launch_posture,
            "finance_gate_pass": finance_gate_pass,
            "baseline_live_trading_pass": baseline_live_trading_pass,
            "capital_expansion_only_hold": capital_expansion_only_hold,
            "treasury_gate_pass": treasury_gate_pass,
            "block_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "can_btc5_trade_now": baseline_live_allowed,
            "btc5_baseline_live_allowed": baseline_live_allowed,
            "btc5_stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "baseline_live_allowed": baseline_live_allowed,
            "stage_upgrade_allowed": stage_upgrade_allowed,
            "capital_expansion_allowed": capital_expansion_allowed,
            "candidate_delta_arr_bps": mandatory_outputs.get("candidate_delta_arr_bps"),
            "expected_improvement_velocity_delta": mandatory_outputs.get(
                "expected_improvement_velocity_delta"
            ),
            "arr_confidence_score": mandatory_outputs.get("arr_confidence_score"),
            "one_next_cycle_action": snapshot.get("one_next_cycle_action"),
            "operator_verdict": operator_verdict,
            "launch_operator_verdict": operator_verdict_code,
        }
    )

    summary["trading_cycle_status"] = champion.get("status", summary.get("trading_cycle_status"))
    summary["one_next_cycle_action"] = snapshot.get("one_next_cycle_action", summary.get("one_next_cycle_action"))
    snapshot["summary"] = summary
    snapshot["champion_lane_contract"] = champion
    snapshot["trading_cycle_status"] = champion.get("status", snapshot.get("trading_cycle_status"))

    strategy["champion_lane_contract"] = champion
    state_improvement["strategy_recommendations"] = strategy
    state_improvement["decision_status"] = champion.get("status")
    state_improvement["one_next_cycle_action"] = summary.get("one_next_cycle_action")
    snapshot["state_improvement"] = state_improvement


def apply_canonical_launch_packet(
    runtime_truth_snapshot: dict[str, Any],
    *,
    root: Path,
    launch_packet: dict[str, Any],
    launch_packet_latest_path: Path,
    launch_packet_timestamped_path: Path,
) -> dict[str, Any]:
    snapshot = dict(runtime_truth_snapshot)
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    treasury_gate_pass = bool(
        mandatory_outputs.get(
            "treasury_gate_pass",
            mandatory_outputs.get("finance_gate_pass", True),
        )
    )
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    drift_gate = dict(launch_packet.get("drift_kill_gate") or {})
    contract = dict(launch_packet.get("contract") or {})
    checks = list(contract.get("checks") or [])
    expected_primary_service = "btc-5min-maker.service"
    observed_service_name = str((snapshot.get("service") or {}).get("service_name") or "").strip() or None
    mode_alignment_check = next(
        (
            item
            for item in checks
            if isinstance(item, dict) and str(item.get("code") or "").strip() == "mode_alignment"
        ),
        {},
    )
    mode_alignment_status = (
        "pass"
        if bool(mode_alignment_check.get("pass"))
        else ("fail" if mode_alignment_check else "unknown")
    )

    snapshot["launch_packet"] = launch_packet
    snapshot["launch_state"] = dict(launch_packet.get("launch_state") or {})
    snapshot["launch_posture"] = str(launch_verdict.get("posture") or snapshot.get("launch_posture") or "blocked")
    snapshot["live_launch_blocked"] = bool(launch_verdict.get("live_launch_blocked"))
    snapshot["service_state"] = str(
        (launch_packet.get("contract") or {}).get("service_state")
        or snapshot.get("service_state")
        or "unknown"
    ).strip() or "unknown"
    launch_payload = dict(snapshot.get("launch") or {})
    launch_payload.update(
        {
            "posture": snapshot["launch_posture"],
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "blocked_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "blocked_checks": dedupe_preserve_order(
                [
                    *list(launch_payload.get("blocked_checks") or []),
                    *list((launch_packet.get("contract") or {}).get("failed_checks") or []),
                    "finance_gate_blocked" if not mandatory_outputs.get("finance_gate_pass", True) else "",
                ]
            ),
            "next_operator_action": mandatory_outputs.get("one_next_cycle_action"),
        }
    )
    launch_payload["blocked_checks"] = [item for item in launch_payload.get("blocked_checks") or [] if item]
    snapshot["launch"] = launch_payload
    if contract.get("agent_run_mode") is not None:
        snapshot["agent_run_mode"] = contract.get("agent_run_mode")
    if contract.get("execution_mode") is not None:
        snapshot["execution_mode"] = contract.get("execution_mode")
    if contract.get("paper_trading") is not None:
        snapshot["paper_trading"] = _bool_or_none(contract.get("paper_trading"))
    if contract.get("allow_order_submission") is not None:
        snapshot["allow_order_submission"] = bool(contract.get("allow_order_submission"))
    if contract.get("order_submit_enabled") is not None:
        snapshot["order_submit_enabled"] = bool(contract.get("order_submit_enabled"))
    snapshot["submission_contract_consensus"] = dict(
        launch_packet.get("submission_contract_consensus") or {}
    )
    snapshot["live_order_submission_allowed"] = bool(
        launch_packet.get("live_order_submission_allowed")
    )

    snapshot.setdefault("summary", {}).update(
        {
            "launch_posture": snapshot["launch_posture"],
            "live_launch_blocked": snapshot["live_launch_blocked"],
            "one_next_cycle_action": mandatory_outputs.get("one_next_cycle_action"),
            "service_status": snapshot["service_state"],
            "storage_state": ((snapshot.get("launch_state") or {}).get("storage") or {}).get("state"),
            "package_load_state": ((snapshot.get("launch_state") or {}).get("package_load") or {}).get("state"),
            "btc5_allowed_stage": ((snapshot.get("launch_state") or {}).get("stage") or {}).get(
                "allowed_stage_label"
            ),
            "drift_detected": bool(
                snapshot.get("summary", {}).get("drift_detected")
                or snapshot.get("drift", {}).get("detected")
                or drift_gate.get("triggered")
            ),
        }
    )
    snapshot["block_reasons"] = list(mandatory_outputs.get("block_reasons") or [])
    snapshot["finance_gate_pass"] = bool(mandatory_outputs.get("finance_gate_pass"))
    snapshot["treasury_gate_pass"] = treasury_gate_pass
    snapshot["stage1_live_trading_allowed"] = bool(mandatory_outputs.get("finance_gate_pass"))
    snapshot["treasury_expansion_allowed"] = treasury_gate_pass
    snapshot["capital_expansion_allowed"] = treasury_gate_pass
    snapshot["one_next_cycle_action"] = mandatory_outputs.get("one_next_cycle_action")
    snapshot["primary_service"] = expected_primary_service
    snapshot["expected_service_name"] = expected_primary_service
    snapshot["observed_service_name"] = observed_service_name
    snapshot["service_consistency"] = (
        "mismatch"
        if observed_service_name and observed_service_name != expected_primary_service
        else "consistent"
    )
    snapshot["mode_alignment"] = mode_alignment_status
    snapshot["runtime_contract"] = {
        "selected_runtime_profile": snapshot.get("selected_runtime_profile"),
        "effective_runtime_profile": snapshot.get("effective_runtime_profile"),
        "remote_runtime_profile": snapshot.get("remote_runtime_profile"),
        "agent_run_mode": snapshot.get("agent_run_mode"),
        "execution_mode": snapshot.get("execution_mode"),
        "paper_trading": snapshot.get("paper_trading"),
        "allow_order_submission": snapshot.get("allow_order_submission"),
        "order_submit_enabled": snapshot.get("order_submit_enabled"),
        "submission_contract_consensus": dict(
            launch_packet.get("submission_contract_consensus") or {}
        ),
        "live_order_submission_allowed": bool(
            launch_packet.get("live_order_submission_allowed")
        ),
        "primary_service": expected_primary_service,
        "observed_service_name": observed_service_name,
        "mode_alignment": mode_alignment_status,
    }

    drift_payload = dict(snapshot.get("drift") or {})
    drift_payload.update(
        {
            "detected": bool(drift_payload.get("detected") or drift_gate.get("triggered")),
            "drift_kill_gate_triggered": bool(drift_gate.get("triggered")),
            "reasons": dedupe_preserve_order(
                [
                    *list(drift_payload.get("reasons") or []),
                    *list(drift_gate.get("reasons") or []),
                    (
                        f"finance_gate_blocked:{(launch_packet.get('finance_gate') or {}).get('reason')}"
                        if not mandatory_outputs.get("finance_gate_pass", True)
                        and (launch_packet.get("finance_gate") or {}).get("reason")
                        else ""
                    ),
                ]
            ),
        }
    )
    drift_payload["reasons"] = [item for item in drift_payload.get("reasons") or [] if item]
    snapshot["drift"] = drift_payload
    _reconcile_btc5_baseline_live(snapshot, launch_packet)
    snapshot["service_name"] = str(
        snapshot.get("service_name")
        or (snapshot.get("service") or {}).get("service_name")
        or expected_primary_service
    ).strip() or expected_primary_service
    snapshot["service_name_resolution"] = str(
        snapshot.get("service_name_resolution")
        or (
            "observed_service_probe"
            if str(snapshot.get("observed_service_name") or "").strip()
            else "default_expected_service_non_safety_hold_repair"
        )
    ).strip()
    snapshot["operator_verdict"] = dict(snapshot.get("operator_verdict") or {})
    snapshot["launch_operator_verdict"] = (
        snapshot.get("launch_operator_verdict")
        or (snapshot.get("operator_verdict") or {}).get("code")
    )

    snapshot.setdefault("artifacts", {}).update(
        {
            "launch_packet_latest_json": relative_path_text(root, launch_packet_latest_path),
            "launch_packet_timestamped_json": relative_path_text(root, launch_packet_timestamped_path),
        }
    )
    return snapshot


def apply_canonical_launch_packet_to_status(
    status: dict[str, Any],
    *,
    launch_packet: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(status)
    canonical_launch_packet = deepcopy(launch_packet)
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    treasury_gate_pass = bool(
        mandatory_outputs.get(
            "treasury_gate_pass",
            mandatory_outputs.get("finance_gate_pass", True),
        )
    )
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    contract = dict(launch_packet.get("contract") or {})
    expected_primary_service = "btc-5min-maker.service"
    launch_packet_service_name = str(launch_packet.get("service_name") or "").strip() or None
    observed_service_name = (
        str((payload.get("service") or {}).get("service_name") or "").strip()
        or launch_packet_service_name
        or None
    )
    mode_alignment_check = next(
        (
            item
            for item in list(contract.get("checks") or [])
            if isinstance(item, dict) and str(item.get("code") or "").strip() == "mode_alignment"
        ),
        {},
    )
    mode_alignment_status = (
        "pass"
        if bool(mode_alignment_check.get("pass"))
        else ("fail" if mode_alignment_check else "unknown")
    )

    launch = dict(payload.get("launch") or {})
    launch.update(
        {
            "posture": launch_verdict.get("posture"),
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "blocked_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "blocked_checks": dedupe_preserve_order(
                [
                    *list(launch.get("blocked_checks") or []),
                    *list((launch_packet.get("contract") or {}).get("failed_checks") or []),
                    "finance_gate_blocked" if not mandatory_outputs.get("finance_gate_pass", True) else "",
                ]
            ),
            "next_operator_action": mandatory_outputs.get("one_next_cycle_action"),
        }
    )
    launch["blocked_checks"] = [item for item in launch.get("blocked_checks") or [] if item]

    payload["launch"] = launch
    payload["launch_posture"] = launch_verdict.get("posture")
    payload["live_launch_blocked"] = bool(launch_verdict.get("live_launch_blocked"))
    payload["launch_state"] = dict(launch_packet.get("launch_state") or {})
    payload["service_state"] = str(
        (launch_packet.get("contract") or {}).get("service_state")
        or payload.get("service_state")
        or "unknown"
    ).strip() or "unknown"
    payload["launch_packet"] = launch_packet
    if contract.get("agent_run_mode") is not None:
        payload["agent_run_mode"] = contract.get("agent_run_mode")
    if contract.get("execution_mode") is not None:
        payload["execution_mode"] = contract.get("execution_mode")
    if contract.get("paper_trading") is not None:
        payload["paper_trading"] = _bool_or_none(contract.get("paper_trading"))
    if contract.get("allow_order_submission") is not None:
        payload["allow_order_submission"] = bool(contract.get("allow_order_submission"))
    if contract.get("order_submit_enabled") is not None:
        payload["order_submit_enabled"] = bool(contract.get("order_submit_enabled"))
    payload["submission_contract_consensus"] = dict(
        launch_packet.get("submission_contract_consensus") or {}
    )
    payload["live_order_submission_allowed"] = bool(
        launch_packet.get("live_order_submission_allowed")
    )
    payload["finance_gate_pass"] = bool(mandatory_outputs.get("finance_gate_pass"))
    payload["treasury_gate_pass"] = treasury_gate_pass
    payload["stage1_live_trading_allowed"] = bool(mandatory_outputs.get("finance_gate_pass"))
    payload["treasury_expansion_allowed"] = treasury_gate_pass
    payload["capital_expansion_allowed"] = treasury_gate_pass
    payload["one_next_cycle_action"] = mandatory_outputs.get("one_next_cycle_action")
    payload["block_reasons"] = list(mandatory_outputs.get("block_reasons") or [])
    payload["primary_service"] = expected_primary_service
    payload["expected_service_name"] = expected_primary_service
    payload["observed_service_name"] = observed_service_name
    payload["service_consistency"] = (
        "mismatch"
        if observed_service_name and observed_service_name != expected_primary_service
        else "consistent"
    )
    payload["mode_alignment"] = mode_alignment_status
    payload["runtime_contract"] = {
        "selected_runtime_profile": (payload.get("runtime_mode") or {}).get("selected_runtime_profile"),
        "effective_runtime_profile": (payload.get("runtime_mode") or {}).get("effective_runtime_profile"),
        "remote_runtime_profile": (payload.get("runtime_truth") or {}).get("remote_runtime_profile"),
        "agent_run_mode": payload.get("agent_run_mode"),
        "execution_mode": payload.get("execution_mode"),
        "paper_trading": payload.get("paper_trading"),
        "allow_order_submission": payload.get("allow_order_submission"),
        "order_submit_enabled": payload.get("order_submit_enabled"),
        "submission_contract_consensus": dict(
            launch_packet.get("submission_contract_consensus") or {}
        ),
        "live_order_submission_allowed": bool(
            launch_packet.get("live_order_submission_allowed")
        ),
        "primary_service": expected_primary_service,
        "observed_service_name": observed_service_name,
        "mode_alignment": mode_alignment_status,
    }
    payload.setdefault("runtime_truth", {}).update(
        {
            "agent_run_mode": payload.get("agent_run_mode"),
            "execution_mode": payload.get("execution_mode"),
            "paper_trading": payload.get("paper_trading"),
            "allow_order_submission": payload.get("allow_order_submission"),
            "order_submit_enabled": payload.get("order_submit_enabled"),
            "submission_contract_consensus": dict(
                launch_packet.get("submission_contract_consensus") or {}
            ),
            "live_order_submission_allowed": bool(
                launch_packet.get("live_order_submission_allowed")
            ),
            "launch_posture": launch_verdict.get("posture"),
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "launch_packet": canonical_launch_packet,
            "launch_state": dict(canonical_launch_packet.get("launch_state") or {}),
            "finance_gate_pass": bool(mandatory_outputs.get("finance_gate_pass")),
            "treasury_gate_pass": treasury_gate_pass,
            "stage1_live_trading_allowed": bool(mandatory_outputs.get("finance_gate_pass")),
            "treasury_expansion_allowed": treasury_gate_pass,
            "one_next_cycle_action": mandatory_outputs.get("one_next_cycle_action"),
            "primary_service": expected_primary_service,
            "expected_service_name": expected_primary_service,
            "observed_service_name": observed_service_name,
            "service_consistency": (
                "mismatch"
                if observed_service_name and observed_service_name != expected_primary_service
                else "consistent"
            ),
            "mode_alignment": mode_alignment_status,
        }
    )
    runtime_truth = dict(payload.get("runtime_truth") or {})
    has_canonical_launch_fields = all(
        key in canonical_launch_packet
        for key in (
            "state_permissions",
            "hold_repair",
            "operator_verdict",
            "service_name",
            "service_name_resolution",
        )
    )
    if not has_canonical_launch_fields:
        _reconcile_btc5_baseline_live(runtime_truth, canonical_launch_packet)
    canonical_required_outputs = dict(
        canonical_launch_packet.get("required_outputs")
        or canonical_launch_packet.get("mandatory_outputs")
        or {}
    )
    if canonical_required_outputs:
        runtime_truth["required_outputs"] = dict(canonical_required_outputs)
        for key in (
            "candidate_delta_arr_bps",
            "expected_improvement_velocity_delta",
            "arr_confidence_score",
            "finance_gate_pass",
            "treasury_gate_pass",
            "one_next_cycle_action",
        ):
            if key in canonical_required_outputs:
                runtime_truth[key] = canonical_required_outputs.get(key)
        if "block_reasons" in canonical_required_outputs:
            runtime_truth["block_reasons"] = list(
                canonical_required_outputs.get("block_reasons") or []
            )
    for key in (
        "stale_hold_repair",
        "hold_repair",
        "rollout_checks",
        "state_permissions",
            "service_name",
            "service_name_resolution",
            "canonical_live_profile_id",
            "canonical_live_package_hash",
            "baseline_live_allowed",
            "stage_upgrade_allowed",
            "capital_expansion_allowed",
        "operator_verdict",
        "launch_operator_verdict",
    ):
        if key in canonical_launch_packet:
            runtime_truth[key] = deepcopy(canonical_launch_packet.get(key))
    payload["runtime_truth"] = runtime_truth
    payload["launch_state"] = dict(runtime_truth.get("launch_state") or payload.get("launch_state") or {})
    payload["btc5_stage_readiness"] = dict(runtime_truth.get("btc5_stage_readiness") or {})
    payload["deployment_confidence"] = dict(runtime_truth.get("deployment_confidence") or {})
    payload["can_btc5_trade_now"] = runtime_truth.get("can_btc5_trade_now")
    payload["btc5_baseline_live_allowed"] = runtime_truth.get("btc5_baseline_live_allowed")
    payload["btc5_stage_upgrade_can_trade_now"] = runtime_truth.get(
        "btc5_stage_upgrade_can_trade_now"
    )
    for key in (
        "baseline_live_allowed",
        "stage_upgrade_allowed",
        "capital_expansion_allowed",
        "state_permissions",
        "stale_hold_repair",
        "hold_repair",
        "rollout_checks",
        "candidate_delta_arr_bps",
        "expected_improvement_velocity_delta",
        "arr_confidence_score",
        "required_outputs",
    ):
        if key in runtime_truth:
            payload[key] = runtime_truth.get(key)
    for key in ("block_reasons", "finance_gate_pass", "treasury_gate_pass"):
        if key in runtime_truth:
            payload[key] = runtime_truth.get(key)
    payload["launch"] = {
        **dict(payload.get("launch") or {}),
        **dict(runtime_truth.get("launch") or {}),
    }
    payload["service"] = {
        **dict(payload.get("service") or {}),
        **dict(runtime_truth.get("service") or {}),
    }
    payload["state_improvement"] = {
        **dict(payload.get("state_improvement") or {}),
        **dict(runtime_truth.get("state_improvement") or {}),
    }
    payload["truth_gate_status"] = runtime_truth.get("truth_gate_status") or payload.get(
        "truth_gate_status"
    )
    payload["truth_gate_blocking_checks"] = list(
        runtime_truth.get("truth_gate_blocking_checks") or payload.get("truth_gate_blocking_checks") or []
    )
    payload["truth_lattice"] = dict(runtime_truth.get("truth_lattice") or payload.get("truth_lattice") or {})
    payload["truth_precedence"] = dict(
        runtime_truth.get("truth_precedence") or payload.get("truth_precedence") or {}
    )
    payload["champion_lane_contract"] = dict(
        (
            ((runtime_truth.get("state_improvement") or {}).get("strategy_recommendations") or {}).get(
                "champion_lane_contract"
            )
        )
        or payload.get("champion_lane_contract")
        or {}
    )
    payload["one_next_cycle_action"] = runtime_truth.get("one_next_cycle_action") or payload.get(
        "one_next_cycle_action"
    )
    payload["service_name"] = str(
        runtime_truth.get("service_name")
        or payload.get("service_name")
        or observed_service_name
        or expected_primary_service
    ).strip() or expected_primary_service
    payload["service_name_resolution"] = str(
        runtime_truth.get("service_name_resolution")
        or payload.get("service_name_resolution")
        or str(launch_packet.get("service_name_resolution") or "").strip()
        or (
            "observed_service_probe"
            if str(runtime_truth.get("observed_service_name") or observed_service_name or "").strip()
            else "default_expected_service_non_safety_hold_repair"
        )
    ).strip()
    payload["baseline_live_trading_pass"] = (
        runtime_truth.get("baseline_live_trading_pass")
        if runtime_truth.get("baseline_live_trading_pass") is not None
        else payload.get("finance_gate_pass")
    )
    payload["capital_expansion_only_hold"] = (
        runtime_truth.get("capital_expansion_only_hold")
        if runtime_truth.get("capital_expansion_only_hold") is not None
        else (not bool(payload.get("treasury_gate_pass")))
    )
    payload["operator_verdict"] = dict(runtime_truth.get("operator_verdict") or {})
    payload["launch_operator_verdict"] = (
        runtime_truth.get("launch_operator_verdict")
        or (payload.get("operator_verdict") or {}).get("code")
    )
    payload.setdefault("runtime_truth", {}).update(
        {
            "service_name": payload.get("service_name"),
            "service_name_resolution": payload.get("service_name_resolution"),
            "baseline_live_trading_pass": payload.get("baseline_live_trading_pass"),
            "capital_expansion_only_hold": payload.get("capital_expansion_only_hold"),
            "operator_verdict": payload.get("operator_verdict"),
            "launch_operator_verdict": payload.get("launch_operator_verdict"),
            "hold_repair": payload.get("hold_repair"),
            "required_outputs": payload.get("required_outputs"),
            "candidate_delta_arr_bps": payload.get("candidate_delta_arr_bps"),
            "expected_improvement_velocity_delta": payload.get(
                "expected_improvement_velocity_delta"
            ),
            "arr_confidence_score": payload.get("arr_confidence_score"),
            "block_reasons": payload.get("block_reasons"),
            "finance_gate_pass": payload.get("finance_gate_pass"),
            "treasury_gate_pass": payload.get("treasury_gate_pass"),
        }
    )
    return payload
