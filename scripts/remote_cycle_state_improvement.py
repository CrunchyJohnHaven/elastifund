from __future__ import annotations

from typing import Any, Callable

from scripts.remote_cycle_common import float_or_none


def count_recent_cap_breaches(
    *,
    btc5_maker: dict[str, Any],
    max_position_usd: float | None,
) -> tuple[int, int]:
    if max_position_usd is None or max_position_usd <= 0:
        return (0, 0)
    recent_rows = list(btc5_maker.get("recent_live_filled") or [])
    if not recent_rows:
        latest_trade = btc5_maker.get("latest_trade")
        if isinstance(latest_trade, dict):
            recent_rows = [latest_trade]
    checked_rows = 0
    breach_count = 0
    for row in recent_rows:
        if not isinstance(row, dict):
            continue
        trade_size = float_or_none(row.get("trade_size_usd"))
        if trade_size is None:
            continue
        checked_rows += 1
        if trade_size > float(max_position_usd):
            breach_count += 1
    return (breach_count, checked_rows)


def build_state_improvement_truth_precedence(
    *,
    runtime_truth_snapshot: dict[str, Any],
    expected_service_name: str,
    observed_service_name: str | None,
) -> dict[str, Any]:
    source_precedence = dict(runtime_truth_snapshot.get("source_precedence") or {})
    fallback_domains = {
        "launch": {
            "selected_source": "reports/launch_packet_latest.json",
            "reason": "canonical_launch_packet_contract",
        },
        "stage": {
            "selected_source": "reports/strategy_scale_comparison.json",
            "reason": "stage_readiness_with_probe_guardrails",
        },
        "pnl": {
            "selected_source": (
                ((runtime_truth_snapshot.get("btc_5min_maker") or {}).get("source"))
                or ((runtime_truth_snapshot.get("btc_5min_maker") or {}).get("db_path"))
                or "data/btc_5min_maker.db"
            ),
            "reason": "freshest_live_fill_surface",
        },
        "candidate_flow": {
            "selected_source": "reports/fast_market_search/latest.json",
            "reason": "lane_candidates_and_blockers",
        },
        "capital": {
            "selected_source": "remote_wallet",
            "reason": "remote_wallet_for_live_capital_truth",
        },
    }
    domains = dict(source_precedence.get("truth_domains") or {})
    for key, value in fallback_domains.items():
        domains.setdefault(key, value)
    domains["launch"]["selected_value"] = {
        "launch_posture": runtime_truth_snapshot.get("launch_posture"),
        "live_launch_blocked": runtime_truth_snapshot.get("live_launch_blocked"),
        "expected_service_name": expected_service_name,
        "observed_service_name": observed_service_name,
    }
    return {
        "rule": str(source_precedence.get("rule") or "").strip(),
        "domains": domains,
        "stale_input_fields": list(source_precedence.get("stale_input_fields") or []),
    }


def build_state_improvement_evidence_freshness(
    *,
    runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    source_precedence = dict(runtime_truth_snapshot.get("source_precedence") or {})
    stale_field_rows: list[dict[str, Any]] = []
    for item in list(source_precedence.get("fields") or []):
        if not isinstance(item, dict):
            continue
        freshness = str(item.get("freshness") or "unknown").strip().lower()
        if freshness != "stale":
            continue
        stale_field_rows.append(
            {
                "field": item.get("field"),
                "selected_source": item.get("selected_source"),
                "freshness": freshness,
            }
        )

    selected_package = dict(runtime_truth_snapshot.get("btc5_selected_package") or {})
    stage_readiness = dict(runtime_truth_snapshot.get("btc5_stage_readiness") or {})
    staged_labels = {
        "selected_package_freshness": str(selected_package.get("freshness") or "unknown").strip().lower(),
        "stage_artifact_freshness": str(stage_readiness.get("freshness") or "unknown").strip().lower(),
        "probe_freshness": str(stage_readiness.get("current_probe_freshness") or "unknown").strip().lower(),
    }
    if staged_labels["selected_package_freshness"] == "stale":
        stale_field_rows.append(
            {
                "field": "btc5_selected_package",
                "selected_source": selected_package.get("path") or selected_package.get("selection_source"),
                "freshness": "stale",
            }
        )
    if staged_labels["probe_freshness"] == "stale":
        stale_field_rows.append(
            {
                "field": "btc5_stage_probe",
                "selected_source": stage_readiness.get("current_probe_artifact"),
                "freshness": "stale",
            }
        )

    intraday = ((runtime_truth_snapshot.get("btc_5min_maker") or {}).get("intraday_live_summary") or {})
    mixed_freshness_labels: list[str] = []
    if (
        staged_labels["selected_package_freshness"] == "stale"
        and staged_labels["probe_freshness"] in {"fresh", "aging"}
        and float_or_none(intraday.get("recent_12_pnl_usd")) is not None
    ):
        mixed_freshness_labels.append("selected_package_stale_with_fresh_or_aging_probe")

    return {
        "wrapper_generated_at": runtime_truth_snapshot.get("generated_at"),
        "fresh_wrapper_stale_input": bool(stale_field_rows),
        "stale_inputs": stale_field_rows,
        "freshness_labels": staged_labels,
        "mixed_freshness_labels": mixed_freshness_labels,
    }


def hydrate_state_improvement_from_launch_contract(
    report: dict[str, Any],
    *,
    launch_packet: dict[str, Any],
    runtime_truth_snapshot: dict[str, Any],
    build_operator_digest: Callable[[dict[str, Any], dict[str, Any]], str],
) -> dict[str, Any]:
    payload = dict(report)
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    launch_payload = dict(runtime_truth_snapshot.get("launch") or {})
    contract = dict(launch_packet.get("contract") or {})
    checks = list(contract.get("checks") or [])

    launch_payload.update(
        {
            "posture": launch_verdict.get("posture") or launch_payload.get("posture") or "blocked",
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "blocked_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "next_operator_action": mandatory_outputs.get("one_next_cycle_action"),
        }
    )

    strategy = dict(payload.get("strategy_recommendations") or {})
    control_plane_consistency = dict(strategy.get("control_plane_consistency") or {})
    service_consistency = dict(control_plane_consistency.get("service_consistency") or {})
    expected_service_name = str(
        service_consistency.get("expected_primary_service") or "btc-5min-maker.service"
    ).strip() or "btc-5min-maker.service"
    observed_service_name = str(
        service_consistency.get("observed_service_name")
        or ((runtime_truth_snapshot.get("service") or {}).get("service_name"))
        or ""
    ).strip() or None

    mode_alignment_check = next(
        (
            item
            for item in checks
            if isinstance(item, dict) and str(item.get("code") or "").strip() == "mode_alignment"
        ),
        {},
    )
    failed_checks = [item for item in checks if isinstance(item, dict) and not bool(item.get("pass"))]
    contract_mismatch_count = len(failed_checks)

    max_position_usd = float_or_none((payload.get("active_thresholds") or {}).get("max_position_usd"))
    cap_breach_count, cap_breach_rows_checked = count_recent_cap_breaches(
        btc5_maker=dict(runtime_truth_snapshot.get("btc_5min_maker") or {}),
        max_position_usd=max_position_usd,
    )
    next_cycle_metrics = {
        "contract_mismatch_count": contract_mismatch_count,
        "contract_mismatch_codes": [
            str(item.get("code"))
            for item in failed_checks
            if str(item.get("code") or "").strip()
        ],
        "cap_breach_count": cap_breach_count,
        "cap_breach_rows_checked": cap_breach_rows_checked,
        "cap_breach_max_position_usd": max_position_usd,
    }

    payload.update(
        {
            "launch": launch_payload,
            "launch_posture": launch_payload.get("posture"),
            "candidate_delta_arr_bps": mandatory_outputs.get("candidate_delta_arr_bps"),
            "expected_improvement_velocity_delta": mandatory_outputs.get("expected_improvement_velocity_delta"),
            "arr_confidence_score": mandatory_outputs.get("arr_confidence_score"),
            "block_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "finance_gate_pass": bool(mandatory_outputs.get("finance_gate_pass")),
            "treasury_gate_pass": bool(
                mandatory_outputs.get(
                    "treasury_gate_pass",
                    mandatory_outputs.get("finance_gate_pass", True),
                )
            ),
            "stage1_live_trading_allowed": bool(mandatory_outputs.get("finance_gate_pass")),
            "treasury_expansion_allowed": bool(
                mandatory_outputs.get(
                    "treasury_gate_pass",
                    mandatory_outputs.get("finance_gate_pass", True),
                )
            ),
            "one_next_cycle_action": mandatory_outputs.get("one_next_cycle_action"),
            "primary_service": expected_service_name,
            "expected_service_name": expected_service_name,
            "observed_service_name": observed_service_name,
            "service_consistency": str(
                service_consistency.get("status")
                or ("mismatch" if observed_service_name and observed_service_name != expected_service_name else "consistent")
            ),
            "mode_alignment": (
                "pass"
                if bool(mode_alignment_check.get("pass"))
                else ("fail" if mode_alignment_check else "unknown")
            ),
            "runtime_contract": {
                "selected_runtime_profile": runtime_truth_snapshot.get("selected_runtime_profile"),
                "effective_runtime_profile": runtime_truth_snapshot.get("effective_runtime_profile"),
                "remote_runtime_profile": runtime_truth_snapshot.get("remote_runtime_profile"),
                "agent_run_mode": runtime_truth_snapshot.get("agent_run_mode"),
                "execution_mode": runtime_truth_snapshot.get("execution_mode"),
                "paper_trading": runtime_truth_snapshot.get("paper_trading"),
                "allow_order_submission": runtime_truth_snapshot.get("allow_order_submission"),
                "primary_service": expected_service_name,
                "observed_service_name": observed_service_name,
            },
            "next_cycle_metrics": next_cycle_metrics,
            "truth_precedence": build_state_improvement_truth_precedence(
                runtime_truth_snapshot=runtime_truth_snapshot,
                expected_service_name=expected_service_name,
                observed_service_name=observed_service_name,
            ),
            "evidence_freshness": build_state_improvement_evidence_freshness(
                runtime_truth_snapshot=runtime_truth_snapshot,
            ),
        }
    )
    if launch_payload.get("live_launch_blocked"):
        payload["launch_posture"] = "blocked"
    payload["operator_digest"] = build_operator_digest(payload, launch_payload)
    return payload
