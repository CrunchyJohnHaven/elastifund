#!/usr/bin/env python3
"""Run one BTC5 policy benchmark iteration and manage shadow/live promotion state."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_policy_benchmark import (  # noqa: E402
    DEFAULT_MARKET_LATEST_JSON,
    DEFAULT_MARKET_POLICY_HANDOFF,
    POLICY_KEEP_EPSILON,
    PROMOTION_FILL_RETENTION_FLOOR,
    evaluate_runtime_package_against_market,
    load_market_policy_handoff,
    runtime_package_hash,
    runtime_package_id,
    safe_float,
)
from scripts.run_btc5_autoresearch_cycle import render_strategy_env  # noqa: E402


DEFAULT_CYCLE_JSON = ROOT / "reports" / "btc5_autoresearch" / "latest.json"
DEFAULT_PORTFOLIO_JSON = ROOT / "reports" / "btc5_portfolio_expectation" / "latest.json"
DEFAULT_RUNTIME_TRUTH = ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_MARKET_HANDOFF_JSON = DEFAULT_MARKET_POLICY_HANDOFF
DEFAULT_MARKET_LATEST_SUMMARY = DEFAULT_MARKET_LATEST_JSON
DEFAULT_FRONTIER_JSON = ROOT / "reports" / "btc5_market_policy_frontier" / "latest.json"
DEFAULT_RESULTS = ROOT / "reports" / "autoresearch" / "btc5_policy" / "results.jsonl"
DEFAULT_RUNS_DIR = ROOT / "reports" / "autoresearch" / "btc5_policy" / "runs"
DEFAULT_CHAMPION = ROOT / "reports" / "autoresearch" / "btc5_policy" / "champion.json"
DEFAULT_PROMOTION_DECISION_JSON = ROOT / "reports" / "autoresearch" / "btc5_policy" / "promotion_decision.json"
DEFAULT_LATEST_JSON = ROOT / "reports" / "autoresearch" / "btc5_policy" / "latest.json"
DEFAULT_LATEST_MD = ROOT / "reports" / "autoresearch" / "btc5_policy" / "latest.md"
DEFAULT_ACTIVE_ENV = ROOT / "state" / "btc5_autoresearch.env"
DEFAULT_ACTIVE_JSON = ROOT / "reports" / "autoresearch" / "btc5_policy" / "active_candidate.json"
DEFAULT_STAGED_ENV = ROOT / "reports" / "autoresearch" / "btc5_policy" / "staged_candidate.env"
DEFAULT_STAGED_JSON = ROOT / "reports" / "autoresearch" / "btc5_policy" / "staged_candidate.json"
DEFAULT_CYCLE_COMMAND = (
    sys.executable,
    str(ROOT / "scripts" / "run_btc5_autoresearch_cycle.py"),
    "--db-path",
    "data/btc_5min_maker.db",
    "--strategy-env",
    "config/btc5_strategy.env",
    "--override-env",
    "state/btc5_autoresearch.env",
    "--report-dir",
    "reports/btc5_autoresearch",
    "--paths",
    "10",
    "--block-size",
    "1",
    "--top-grid-candidates",
    "1",
    "--min-replay-fills",
    "2",
    "--regime-max-session-overrides",
    "1",
    "--regime-top-single-overrides-per-session",
    "1",
    "--regime-max-composed-candidates",
    "0",
)
DEFAULT_PORTFOLIO_COMMAND = (
    sys.executable,
    str(ROOT / "scripts" / "btc5_portfolio_expectation.py"),
)
DEFAULT_FRONTIER_STAGE_EPSILON = 100.0
PROMOTION_STATES = {"shadow_updated", "live_promoted", "live_activated", "rollback_triggered"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-cycle", action="store_true", help="Use existing artifacts instead of running a new cycle.")
    parser.add_argument("--cycle-json", default=str(DEFAULT_CYCLE_JSON), help="BTC5 cycle artifact path.")
    parser.add_argument(
        "--portfolio-json",
        default=str(DEFAULT_PORTFOLIO_JSON),
        help="Portfolio expectation artifact path.",
    )
    parser.add_argument(
        "--runtime-truth",
        default=str(DEFAULT_RUNTIME_TRUTH),
        help="Runtime truth artifact path.",
    )
    parser.add_argument(
        "--market-policy-handoff",
        default=str(DEFAULT_MARKET_HANDOFF_JSON),
        help="Market-to-policy handoff artifact path.",
    )
    parser.add_argument(
        "--market-latest-json",
        default=str(DEFAULT_MARKET_LATEST_SUMMARY),
        help="Market benchmark latest summary path.",
    )
    parser.add_argument(
        "--frontier-json",
        default=str(DEFAULT_FRONTIER_JSON),
        help="Market-backed policy frontier JSON used for best-candidate pass-through.",
    )
    parser.add_argument("--results-ledger", default=str(DEFAULT_RESULTS), help="Append-only policy ledger.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Per-run packet directory.")
    parser.add_argument("--champion-out", default=str(DEFAULT_CHAMPION), help="Champion registry output.")
    parser.add_argument(
        "--promotion-decision-json",
        default=str(DEFAULT_PROMOTION_DECISION_JSON),
        help="Per-cycle authoritative policy decision packet output.",
    )
    parser.add_argument("--latest-json", default=str(DEFAULT_LATEST_JSON), help="Latest summary JSON output.")
    parser.add_argument("--latest-md", default=str(DEFAULT_LATEST_MD), help="Latest summary markdown output.")
    parser.add_argument(
        "--active-env",
        default=str(DEFAULT_ACTIVE_ENV),
        help="Live override env package written on activation.",
    )
    parser.add_argument(
        "--active-package-json",
        default=str(DEFAULT_ACTIVE_JSON),
        help="Live package JSON mirror written on activation.",
    )
    parser.add_argument(
        "--staged-env",
        default=str(DEFAULT_STAGED_ENV),
        help="Shadow-staged env package path.",
    )
    parser.add_argument(
        "--staged-package-json",
        default=str(DEFAULT_STAGED_JSON),
        help="Shadow-staged package JSON path.",
    )
    parser.add_argument(
        "--keep-epsilon",
        type=float,
        default=POLICY_KEEP_EPSILON,
        help="Minimum policy-loss improvement required to replace the incumbent.",
    )
    parser.add_argument(
        "--rollback-loss-increase",
        type=float,
        default=0.0,
        help="Rollback when live policy loss increases by more than this amount.",
    )
    parser.add_argument(
        "--frontier-stage-epsilon",
        type=float,
        default=DEFAULT_FRONTIER_STAGE_EPSILON,
        help="Minimum frontier-improvement threshold required to override the cycle-selected candidate.",
    )
    parser.add_argument("--description", default="", help="Optional operator note recorded in the run packet.")
    return parser.parse_args()


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _market_model_version(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    version = str(payload.get("market_model_version") or "").strip()
    if version:
        return version
    simulator_id = payload.get("simulator_champion_id")
    simulator_hash = str(payload.get("simulator_candidate_hash") or "").strip()
    if simulator_id is not None or simulator_hash:
        return f"{simulator_id}:{simulator_hash}"
    market_epoch_id = str(payload.get("market_epoch_id") or "").strip()
    return market_epoch_id or None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _session_policy_shape_signature(session_policy: list[dict[str, Any]] | None) -> tuple[tuple[Any, ...], ...]:
    items = session_policy if isinstance(session_policy, list) else []
    normalized: list[tuple[Any, ...]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            (
                tuple(sorted(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int))),
                safe_float(item.get("max_abs_delta"), None),
                safe_float(item.get("up_max_buy_price"), None),
                safe_float(item.get("down_max_buy_price"), None),
            )
        )
    normalized.sort()
    return tuple(normalized)


def _runtime_package_shape_signature(runtime_package: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if not isinstance(runtime_package, dict):
        return None
    profile = runtime_package.get("profile") if isinstance(runtime_package.get("profile"), dict) else {}
    if not profile:
        return None
    return (
        safe_float(profile.get("max_abs_delta"), None),
        safe_float(profile.get("up_max_buy_price"), None),
        safe_float(profile.get("down_max_buy_price"), None),
        _session_policy_shape_signature(runtime_package.get("session_policy")),
    )


def _session_policy_match(
    *,
    session_policy: list[dict[str, Any]] | None,
    candidate_item: dict[str, Any],
) -> dict[str, Any] | None:
    candidate_hours = tuple(sorted(int(hour) for hour in (candidate_item.get("et_hours") or []) if isinstance(hour, int)))
    for item in session_policy if isinstance(session_policy, list) else []:
        if not isinstance(item, dict):
            continue
        item_hours = tuple(sorted(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int)))
        if item_hours == candidate_hours:
            return item
    return None


def _profile_relaxes(reference: dict[str, Any], candidate: dict[str, Any]) -> bool:
    reference_delta = safe_float(reference.get("max_abs_delta"), None)
    candidate_delta = safe_float(candidate.get("max_abs_delta"), None)
    reference_up = safe_float(reference.get("up_max_buy_price"), None)
    candidate_up = safe_float(candidate.get("up_max_buy_price"), None)
    reference_down = safe_float(reference.get("down_max_buy_price"), None)
    candidate_down = safe_float(candidate.get("down_max_buy_price"), None)
    return bool(
        (reference_delta is not None and candidate_delta is not None and candidate_delta > reference_delta)
        or (reference_up is not None and candidate_up is not None and candidate_up > reference_up)
        or (reference_down is not None and candidate_down is not None and candidate_down > reference_down)
    )


def _runtime_package_relaxes_live_envelope(
    candidate_runtime_package: dict[str, Any] | None,
    active_runtime_package: dict[str, Any] | None,
) -> bool:
    if not isinstance(candidate_runtime_package, dict) or not isinstance(active_runtime_package, dict):
        return False
    active_profile = active_runtime_package.get("profile") if isinstance(active_runtime_package.get("profile"), dict) else {}
    candidate_profile = (
        candidate_runtime_package.get("profile")
        if isinstance(candidate_runtime_package.get("profile"), dict)
        else {}
    )
    if active_profile and candidate_profile and _profile_relaxes(active_profile, candidate_profile):
        return True

    active_session_policy = (
        active_runtime_package.get("session_policy")
        if isinstance(active_runtime_package.get("session_policy"), list)
        else []
    )
    candidate_session_policy = (
        candidate_runtime_package.get("session_policy")
        if isinstance(candidate_runtime_package.get("session_policy"), list)
        else []
    )
    for candidate_item in candidate_session_policy:
        if not isinstance(candidate_item, dict):
            continue
        reference_item = _session_policy_match(
            session_policy=active_session_policy,
            candidate_item=candidate_item,
        )
        reference_profile = reference_item if isinstance(reference_item, dict) else active_profile
        if reference_profile and _profile_relaxes(reference_profile, candidate_item):
            return True
    return False


def _canonicalize_live_package_alias(
    *,
    live_package: dict[str, Any] | None,
    champion_record: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(live_package, dict):
        return live_package
    if not isinstance(champion_record, dict):
        return live_package

    live_runtime_package = (
        live_package.get("runtime_package") if isinstance(live_package.get("runtime_package"), dict) else None
    )
    champion_runtime_package = (
        champion_record.get("runtime_package")
        if isinstance(champion_record.get("runtime_package"), dict)
        else None
    )
    if not live_runtime_package or not champion_runtime_package:
        return live_package

    live_signature = _runtime_package_shape_signature(live_runtime_package)
    champion_signature = _runtime_package_shape_signature(champion_runtime_package)
    if not live_signature or live_signature != champion_signature:
        return live_package

    live_policy_id = str(live_package.get("policy_id") or "").strip()
    champion_policy_id = str(champion_record.get("policy_id") or "").strip()
    if not live_policy_id or not champion_policy_id or live_policy_id == champion_policy_id:
        return live_package

    canonicalized = dict(live_package)
    canonicalized["policy_id"] = champion_policy_id
    canonicalized["package_hash"] = champion_record.get("package_hash")
    canonicalized["runtime_package"] = dict(champion_runtime_package)
    canonicalized["source_artifact"] = (
        champion_record.get("source_artifact")
        or live_package.get("source_artifact")
    )
    return canonicalized


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "keep": sum(1 for row in rows if row.get("status") == "keep"),
        "discard": sum(1 for row in rows if row.get("status") == "discard"),
        "crash": sum(1 for row in rows if row.get("status") == "crash"),
        "shadow_updated": sum(1 for row in rows if row.get("promotion_state") == "shadow_updated"),
        "live_promoted": sum(1 for row in rows if row.get("promotion_state") == "live_promoted"),
        "live_activated": sum(1 for row in rows if row.get("promotion_state") == "live_activated"),
        "rollback_triggered": sum(1 for row in rows if row.get("promotion_state") == "rollback_triggered"),
    }


def _decision_action(*, status: str, promotion_state: str | None) -> str:
    normalized_promotion = str(promotion_state or "").strip().lower()
    if normalized_promotion in PROMOTION_STATES:
        return normalized_promotion
    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"keep", "discard", "crash"}:
        return normalized_status
    return "discard"


def _decision_subject(package: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(package, dict):
        return None
    return {
        "policy_id": package.get("policy_id"),
        "package_hash": package.get("package_hash"),
        "policy_loss": package.get("policy_loss"),
        "promotion_state": package.get("promotion_state"),
        "simulator_champion_id": package.get("simulator_champion_id"),
        "market_epoch_id": package.get("market_epoch_id"),
        "market_model_version": package.get("market_model_version"),
    }


def _build_decision_packet(
    *,
    generated_at: str,
    experiment_id: int,
    status: str,
    action: str,
    decision_reason: str,
    launch_posture: str,
    safety_gates: dict[str, Any],
    candidate: dict[str, Any] | None,
    incumbent: dict[str, Any] | None,
    champion_after: dict[str, Any] | None,
    live_after: dict[str, Any] | None,
    staged_after: dict[str, Any] | None,
    policy_loss_contract_version: Any,
    policy_loss_formula: Any,
    evaluation_source: Any,
    simulator_champion_id: Any,
    market_epoch_id: Any,
    artifact_paths: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "experiment_id": experiment_id,
        "status": status,
        "action": action,
        "decision_reason": decision_reason,
        "launch_posture": launch_posture,
        "safety_gates": dict(safety_gates or {}),
        "candidate": _decision_subject(candidate),
        "incumbent": _decision_subject(incumbent),
        "champion_after": _decision_subject(champion_after),
        "live_after": _decision_subject(live_after),
        "staged_after": _decision_subject(staged_after),
        "policy_loss_contract_version": policy_loss_contract_version,
        "policy_loss_formula": policy_loss_formula,
        "evaluation_source": evaluation_source,
        "simulator_champion_id": simulator_champion_id,
        "market_epoch_id": market_epoch_id,
        "artifact_paths": dict(artifact_paths),
    }


def _run_command(command: tuple[str, ...], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _policy_evaluation(
    *,
    runtime_package: dict[str, Any],
    market_policy_handoff: Path,
    market_latest_json: Path,
) -> dict[str, Any]:
    return evaluate_runtime_package_against_market(
        runtime_package,
        handoff_path=market_policy_handoff,
        market_latest_path=market_latest_json,
    )


def _safety_gate_snapshot(
    *,
    cycle_payload: dict[str, Any],
    runtime_truth: dict[str, Any],
    market_context: dict[str, Any],
) -> dict[str, Any]:
    handoff_meta = market_context if isinstance(market_context, dict) else {}
    market_latest = handoff_meta.get("market_latest") if isinstance(handoff_meta.get("market_latest"), dict) else {}
    gates = {
        "market_policy_handoff_fresh": bool(market_latest.get("is_fresh")),
        "market_epoch_active": bool(handoff_meta.get("market_epoch_active")),
        "cycle_artifact_present": bool(cycle_payload),
        "runtime_truth_present": bool(runtime_truth),
    }
    gates["all_green"] = all(gates.values())
    return gates


def _runtime_package_from_payload(payload: dict[str, Any], *, best: bool) -> dict[str, Any]:
    keys = (
        ("selected_best_runtime_package", "best_runtime_package")
        if best
        else ("selected_active_runtime_package", "active_runtime_package")
    )
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict) and value.get("profile"):
            return value
    return {}


def _frontier_best_candidate(
    frontier_payload: dict[str, Any] | None,
    *,
    current_market_model_version: str | None,
    minimum_improvement: float,
) -> dict[str, Any] | None:
    if not isinstance(frontier_payload, dict):
        return None
    ranked = frontier_payload.get("ranked_policies") if isinstance(frontier_payload.get("ranked_policies"), list) else []
    if not ranked:
        return None
    best = ranked[0] if isinstance(ranked[0], dict) else None
    if not isinstance(best, dict):
        return None
    frontier_version = str(best.get("market_model_version") or "").strip() or None
    if current_market_model_version and frontier_version not in {None, current_market_model_version}:
        return None
    improvement_vs_incumbent = safe_float(frontier_payload.get("loss_improvement_vs_incumbent"), None)
    if improvement_vs_incumbent is None or improvement_vs_incumbent <= float(minimum_improvement):
        return None
    runtime_package = best.get("runtime_package") if isinstance(best.get("runtime_package"), dict) else {}
    if not runtime_package.get("profile"):
        return None
    return {
        "policy_id": best.get("policy_id"),
        "package_hash": best.get("package_hash"),
        "policy_loss": best.get("policy_loss"),
        "policy_components": dict(best.get("policy_components") or {}),
        "market_model_version": frontier_version,
        "runtime_package": runtime_package,
        "loss_improvement_vs_incumbent": round(improvement_vs_incumbent, 4),
    }


def _candidate_target_from_runtime_package(runtime_package: dict[str, Any]) -> dict[str, Any]:
    profile = dict(runtime_package.get("profile") or {})
    if not profile.get("name"):
        profile["name"] = runtime_package_id(runtime_package)
    session_overrides: list[dict[str, Any]] = []
    for item in list(runtime_package.get("session_policy") or []):
        if not isinstance(item, dict):
            continue
        hours = [int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int)]
        if not hours:
            continue
        override_profile = {
            "name": str(item.get("name") or profile.get("name") or "session_policy").strip(),
            "max_abs_delta": (
                safe_float(item.get("max_abs_delta"), None)
                if item.get("max_abs_delta") is not None
                else profile.get("max_abs_delta")
            ),
            "up_max_buy_price": (
                safe_float(item.get("up_max_buy_price"), None)
                if item.get("up_max_buy_price") is not None
                else profile.get("up_max_buy_price")
            ),
            "down_max_buy_price": (
                safe_float(item.get("down_max_buy_price"), None)
                if item.get("down_max_buy_price") is not None
                else profile.get("down_max_buy_price")
            ),
        }
        session_overrides.append(
            {
                "session_name": str(item.get("name") or override_profile["name"]).strip() or "session_policy",
                "et_hours": hours,
                "profile": override_profile,
            }
        )
    return {
        "profile": dict(profile),
        "base_profile": dict(profile),
        "session_overrides": session_overrides,
    }


def _package_record(
    *,
    runtime_package: dict[str, Any],
    policy_loss: float,
    generated_at: str,
    source_artifact: Path,
    promotion_state: str | None,
    deploy_recommendation: str | None,
    package_env_path: Path | None = None,
    package_json_path: Path | None = None,
    policy_components: dict[str, float] | None = None,
    policy_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evaluation = policy_evaluation if isinstance(policy_evaluation, dict) else {}
    benchmark = evaluation.get("policy_benchmark") if isinstance(evaluation.get("policy_benchmark"), dict) else {}
    return {
        "policy_id": runtime_package_id(runtime_package),
        "package_hash": runtime_package_hash(runtime_package),
        "policy_loss": round(policy_loss, 4),
        "policy_components": dict(policy_components or {}),
        "fold_results": list(evaluation.get("fold_results") or []),
        "confidence_summary": dict(evaluation.get("confidence_summary") or {}),
        "policy_loss_contract_version": evaluation.get("policy_loss_contract_version"),
        "policy_loss_formula": evaluation.get("policy_loss_formula"),
        "evaluation_source": evaluation.get("evaluation_source"),
        "simulator_champion_id": evaluation.get("simulator_champion_id"),
        "market_epoch_id": evaluation.get("market_epoch_id"),
        "market_model_version": evaluation.get("market_model_version"),
        "expected_fills_per_day": benchmark.get("expected_fills_per_day"),
        "fill_retention_ratio": benchmark.get("fill_retention_ratio"),
        "runtime_package": dict(runtime_package),
        "generated_at": generated_at,
        "source_artifact": _relative(source_artifact),
        "promotion_state": promotion_state,
        "deploy_recommendation": deploy_recommendation,
        "package_env_path": _relative(package_env_path) if package_env_path is not None else None,
        "package_json_path": _relative(package_json_path) if package_json_path is not None else None,
    }


def _policy_evaluation_from_package_record(package: dict[str, Any] | None) -> dict[str, Any]:
    payload = package if isinstance(package, dict) else {}
    return {
        "policy_loss_contract_version": payload.get("policy_loss_contract_version"),
        "policy_loss_formula": payload.get("policy_loss_formula"),
        "evaluation_source": payload.get("evaluation_source"),
        "simulator_champion_id": payload.get("simulator_champion_id"),
        "market_epoch_id": payload.get("market_epoch_id"),
        "market_model_version": payload.get("market_model_version"),
        "policy_benchmark": dict(payload.get("policy_components") or {}),
        "fold_results": list(payload.get("fold_results") or []),
        "confidence_summary": dict(payload.get("confidence_summary") or {}),
    }


def _hydrate_package_record(
    target: dict[str, Any] | None,
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    hydrated = dict(target or {})
    source_payload = dict(source or {})
    if not hydrated or not source_payload:
        return hydrated
    if hydrated.get("package_hash") != source_payload.get("package_hash"):
        return hydrated
    fill_if_missing = (
        "market_model_version",
        "policy_loss_contract_version",
        "policy_loss_formula",
        "evaluation_source",
        "simulator_champion_id",
        "market_epoch_id",
        "expected_fills_per_day",
        "fill_retention_ratio",
    )
    for key in fill_if_missing:
        if hydrated.get(key) in (None, "", []):
            hydrated[key] = source_payload.get(key)
    if not hydrated.get("fold_results"):
        hydrated["fold_results"] = list(source_payload.get("fold_results") or [])
    if not hydrated.get("confidence_summary"):
        hydrated["confidence_summary"] = dict(source_payload.get("confidence_summary") or {})
    if not hydrated.get("policy_components"):
        hydrated["policy_components"] = dict(source_payload.get("policy_components") or {})
    return hydrated


def _candidate_vs_incumbent_summary(
    candidate: dict[str, Any] | None,
    incumbent: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_folds = {
        str(item.get("fold_id")): item
        for item in ((candidate or {}).get("fold_results") or [])
        if isinstance(item, dict) and str(item.get("fold_id") or "").strip()
    }
    incumbent_folds = {
        str(item.get("fold_id")): item
        for item in ((incumbent or {}).get("fold_results") or [])
        if isinstance(item, dict) and str(item.get("fold_id") or "").strip()
    }
    improvements: list[float] = []
    for fold_id, candidate_fold in candidate_folds.items():
        incumbent_fold = incumbent_folds.get(fold_id)
        if not isinstance(incumbent_fold, dict):
            continue
        candidate_loss = safe_float(candidate_fold.get("policy_loss"), None)
        incumbent_loss = safe_float(incumbent_fold.get("policy_loss"), None)
        if candidate_loss is None or incumbent_loss is None:
            continue
        improvements.append(float(incumbent_loss - candidate_loss))
    if not improvements:
        return {
            "fold_count": 0,
            "fold_win_count": 0,
            "fold_win_rate": None,
            "mean_fold_loss_improvement": None,
            "bootstrap_ci_low": None,
            "bootstrap_ci_high": None,
            "confidence_method": None,
        }
    ordered = sorted(improvements)
    lower_index = max(0, int(round((len(ordered) - 1) * 0.025)))
    upper_index = max(0, int(round((len(ordered) - 1) * 0.975)))
    win_count = sum(1 for value in improvements if value > 0.0)
    return {
        "fold_count": len(improvements),
        "fold_win_count": win_count,
        "fold_win_rate": round(win_count / float(len(improvements) or 1), 4),
        "mean_fold_loss_improvement": round(sum(improvements) / float(len(improvements) or 1), 4),
        "bootstrap_ci_low": round(ordered[lower_index], 4),
        "bootstrap_ci_high": round(ordered[upper_index], 4),
        "confidence_method": "empirical_fold_loss_improvement_band_v1",
    }


def _write_package_files(
    *,
    runtime_package: dict[str, Any],
    policy_loss: float,
    generated_at: str,
    source_artifact: Path,
    reason: str,
    env_path: Path,
    json_path: Path,
    deploy_recommendation: str | None,
    promotion_state: str,
    policy_components: dict[str, float],
    policy_evaluation: dict[str, Any],
) -> dict[str, Any]:
    target = _candidate_target_from_runtime_package(runtime_package)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(
        render_strategy_env(
            target,
            {
                "generated_at": generated_at,
                "reason": reason,
            },
        ),
        encoding="utf-8",
    )
    package_payload = _package_record(
        runtime_package=runtime_package,
        policy_loss=policy_loss,
        generated_at=generated_at,
        source_artifact=source_artifact,
        promotion_state=promotion_state,
        deploy_recommendation=deploy_recommendation,
        package_env_path=env_path,
        package_json_path=json_path,
        policy_components=policy_components,
        policy_evaluation=policy_evaluation,
    )
    _write_json(json_path, package_payload)
    return package_payload


def _write_latest_markdown(path: Path, payload: dict[str, Any]) -> None:
    champion = payload.get("champion") if isinstance(payload.get("champion"), dict) else {}
    live = payload.get("live_package") if isinstance(payload.get("live_package"), dict) else {}
    staged = payload.get("staged_package") if isinstance(payload.get("staged_package"), dict) else {}
    latest = payload.get("latest_experiment") if isinstance(payload.get("latest_experiment"), dict) else {}
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    comparison = (
        latest.get("candidate_vs_incumbent_summary")
        if isinstance(latest.get("candidate_vs_incumbent_summary"), dict)
        else {}
    )
    lines = [
        "# BTC5 Policy Autoresearch",
        "",
        f"- Champion: `{payload.get('champion_id') or 'n/a'}`",
        f"- Champion policy loss: `{payload.get('loss')}`",
        f"- Live package: `{live.get('policy_id') or 'n/a'}`",
        f"- Staged package: `{staged.get('policy_id') or 'n/a'}`",
        f"- Launch posture: `{payload.get('launch_posture') or 'unknown'}`",
        f"- Submission policy: `{payload.get('submission_policy') or 'unknown'}`",
        f"- Total experiments: `{counts.get('total', 0)}`",
        f"- Kept: `{counts.get('keep', 0)}`",
        f"- Discarded: `{counts.get('discard', 0)}`",
        f"- Crashes: `{counts.get('crash', 0)}`",
        f"- Shadow stages: `{counts.get('shadow_updated', 0)}`",
        f"- Live promotions: `{counts.get('live_promoted', 0) + counts.get('live_activated', 0)}`",
        f"- Rollbacks: `{counts.get('rollback_triggered', 0)}`",
        f"- Latest status: `{latest.get('status') or 'n/a'}`",
        f"- Latest promotion state: `{latest.get('promotion_state') or 'n/a'}`",
        f"- Latest decision reason: `{latest.get('decision_reason') or 'n/a'}`",
        f"- Latest fold win rate vs incumbent: `{comparison.get('fold_win_rate')}`",
        f"- Latest fold loss-improvement CI: `[{comparison.get('bootstrap_ci_low')}, {comparison.get('bootstrap_ci_high')}]`",
        "",
        "Benchmark progress only, not realized P&L.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _crash_summary(
    *,
    existing_rows: list[dict[str, Any]],
    champion_registry: dict[str, Any] | None,
    latest_row: dict[str, Any],
    latest_out: Path,
    latest_md: Path,
) -> dict[str, Any]:
    champion = (champion_registry or {}).get("champion") if isinstance((champion_registry or {}).get("champion"), dict) else {}
    live_package = (
        (champion_registry or {}).get("live_package")
        if isinstance((champion_registry or {}).get("live_package"), dict)
        else {}
    )
    staged_package = (
        (champion_registry or {}).get("staged_package")
        if isinstance((champion_registry or {}).get("staged_package"), dict)
        else {}
    )
    summary = {
        "updated_at": latest_row.get("evaluated_at"),
        "champion_id": champion.get("policy_id"),
        "loss": champion.get("policy_loss"),
        "champion": champion,
        "live_package": live_package,
        "staged_package": staged_package,
        "latest_experiment": latest_row,
        "counts": _counts(existing_rows),
        "submission_policy": "shadow_only",
        "launch_posture": latest_row.get("launch_posture"),
        "artifacts": {
            "results_ledger": _relative(Path(latest_row["artifact_paths"]["results_ledger"])),
            "latest_run": latest_row["artifact_paths"]["run_json"],
        },
    }
    _write_json(latest_out, summary)
    _write_latest_markdown(latest_md, summary)
    return summary


def main() -> int:
    args = parse_args()
    cycle_json = Path(args.cycle_json)
    portfolio_json = Path(args.portfolio_json)
    runtime_truth_path = Path(args.runtime_truth)
    market_policy_handoff = Path(args.market_policy_handoff)
    market_latest_json = Path(args.market_latest_json)
    frontier_json = Path(args.frontier_json)
    results_ledger = Path(args.results_ledger)
    runs_dir = Path(args.runs_dir)
    champion_out = Path(args.champion_out)
    promotion_decision_json = Path(args.promotion_decision_json)
    latest_out = Path(args.latest_json)
    latest_md = Path(args.latest_md)
    active_env = Path(args.active_env)
    active_package_json = Path(args.active_package_json)
    staged_env = Path(args.staged_env)
    staged_package_json = Path(args.staged_package_json)
    runs_dir.mkdir(parents=True, exist_ok=True)

    cycle_result: subprocess.CompletedProcess[str] | None = None
    portfolio_result: subprocess.CompletedProcess[str] | None = None
    if not args.skip_cycle:
        cycle_result = _run_command(DEFAULT_CYCLE_COMMAND, timeout=600)
        if cycle_result.returncode == 0:
            portfolio_result = _run_command(DEFAULT_PORTFOLIO_COMMAND, timeout=180)

    cycle_payload = _load_json(cycle_json) or {}
    runtime_truth = _load_json(runtime_truth_path) or {}
    existing_rows = _load_jsonl(results_ledger)
    experiment_id = len(existing_rows) + 1
    run_path = runs_dir / f"experiment_{experiment_id:04d}.json"
    generated_at = str(cycle_payload.get("generated_at") or _now_iso())
    launch_posture = str(
        runtime_truth.get("launch_posture")
        or runtime_truth.get("launch", {}).get("posture")
        or "unknown"
    ).strip() or "unknown"

    candidate_runtime_package = _runtime_package_from_payload(cycle_payload, best=True)
    active_runtime_package = _runtime_package_from_payload(cycle_payload, best=False)
    deploy_recommendation = str(
        cycle_payload.get("selected_deploy_recommendation")
        or cycle_payload.get("deploy_recommendation")
        or "hold"
    ).strip() or "hold"
    package_confidence_label = str(
        cycle_payload.get("selected_package_confidence_label")
        or cycle_payload.get("package_confidence_label")
        or "low"
    ).strip() or "low"

    crash_reason: str | None = None
    if cycle_result is not None and cycle_result.returncode != 0:
        crash_reason = "cycle_command_failed"
    elif not candidate_runtime_package:
        crash_reason = "missing_candidate_runtime_package"
    elif not active_runtime_package:
        crash_reason = "missing_active_runtime_package"

    champion_registry = _load_json(champion_out) or {}
    market_handoff_payload: dict[str, Any] | None = None
    frontier_payload: dict[str, Any] | None = _load_json(frontier_json) or {}
    current_evaluation: dict[str, Any] | None = None
    candidate_evaluation: dict[str, Any] | None = None
    safety_gates: dict[str, Any] = {}
    frontier_override: dict[str, Any] | None = None
    if crash_reason is None:
        try:
            market_handoff_payload = load_market_policy_handoff(
                handoff_path=market_policy_handoff,
                market_latest_path=market_latest_json,
            )
            current_market_model_version = _market_model_version(
                {
                    "market_model_version": (market_handoff_payload or {}).get("market_model_version"),
                    "market_epoch_id": (market_handoff_payload or {}).get("market_epoch_id"),
                    "simulator_champion_id": ((market_handoff_payload or {}).get("market_champion") or {}).get("id"),
                    "simulator_candidate_hash": ((market_handoff_payload or {}).get("market_champion") or {}).get(
                        "candidate_hash"
                    ),
                }
            )
            frontier_override = _frontier_best_candidate(
                frontier_payload,
                current_market_model_version=current_market_model_version,
                minimum_improvement=float(args.frontier_stage_epsilon),
            )
            if frontier_override is not None:
                candidate_runtime_package = dict(frontier_override.get("runtime_package") or candidate_runtime_package)
                if deploy_recommendation not in {"promote", "shadow_only"}:
                    deploy_recommendation = "shadow_only"
            current_evaluation = _policy_evaluation(
                runtime_package=active_runtime_package,
                market_policy_handoff=market_policy_handoff,
                market_latest_json=market_latest_json,
            )
            candidate_evaluation = _policy_evaluation(
                runtime_package=candidate_runtime_package,
                market_policy_handoff=market_policy_handoff,
                market_latest_json=market_latest_json,
            )
            baseline_expected_fills = safe_float(
                (((current_evaluation or {}).get("policy_benchmark") or {}).get("expected_fills_per_day")),
                0.0,
            ) or 0.0
            candidate_expected_fills = safe_float(
                (((candidate_evaluation or {}).get("policy_benchmark") or {}).get("expected_fills_per_day")),
                0.0,
            ) or 0.0
            fill_retention_ratio = (
                candidate_expected_fills / baseline_expected_fills
                if baseline_expected_fills > 0.0
                else 1.0
            )
            if isinstance(current_evaluation.get("policy_benchmark"), dict):
                current_evaluation["policy_benchmark"]["fill_retention_ratio"] = 1.0
            if isinstance(candidate_evaluation.get("policy_benchmark"), dict):
                candidate_evaluation["policy_benchmark"]["fill_retention_ratio"] = round(fill_retention_ratio, 4)
            safety_gates = _safety_gate_snapshot(
                cycle_payload=cycle_payload,
                runtime_truth=runtime_truth,
                market_context=market_handoff_payload or {},
            )
        except Exception as exc:
            crash_reason = f"market_policy_benchmark_failed:{type(exc).__name__}:{exc}"

    if crash_reason is not None:
        candidate_id = runtime_package_id(candidate_runtime_package or active_runtime_package)
        crash_artifact_paths = {
            "results_ledger": _relative(results_ledger),
            "run_json": _relative(run_path),
            "champion_registry": _relative(champion_out),
            "market_policy_handoff": _relative(market_policy_handoff) if market_policy_handoff.exists() else None,
            "market_latest_json": _relative(market_latest_json) if market_latest_json.exists() else None,
        }
        row = {
            "experiment_id": experiment_id,
            "evaluated_at": generated_at,
            "status": "crash",
            "promotion_state": None,
            "decision_reason": crash_reason,
            "candidate_policy": candidate_id,
            "policy_loss": None,
            "champion_id": ((champion_registry.get("champion") or {}).get("policy_id") if champion_registry else None),
            "launch_posture": launch_posture,
            "policy_loss_contract_version": ((market_handoff_payload or {}).get("policy_benchmark") or {}).get(
                "policy_loss_contract_version"
            ),
            "evaluation_source": ((market_handoff_payload or {}).get("policy_benchmark") or {}).get("evaluation_source"),
            "market_epoch_id": (market_handoff_payload or {}).get("market_epoch_id"),
            "simulator_champion_id": ((market_handoff_payload or {}).get("market_champion") or {}).get("id"),
            "safety_gates": safety_gates,
            "artifact_paths": {
                "run_json": _relative(run_path),
                "results_ledger": str(results_ledger),
                "market_policy_handoff": _relative(market_policy_handoff) if market_policy_handoff.exists() else None,
                "market_latest_json": _relative(market_latest_json) if market_latest_json.exists() else None,
            },
            "cycle_returncode": None if cycle_result is None else cycle_result.returncode,
            "cycle_stdout_tail": ((cycle_result.stdout or "").strip()[-500:] if cycle_result is not None else ""),
            "cycle_stderr_tail": ((cycle_result.stderr or "").strip()[-500:] if cycle_result is not None else ""),
            "portfolio_returncode": None if portfolio_result is None else portfolio_result.returncode,
            "portfolio_stdout_tail": ((portfolio_result.stdout or "").strip()[-500:] if portfolio_result is not None else ""),
            "portfolio_stderr_tail": ((portfolio_result.stderr or "").strip()[-500:] if portfolio_result is not None else ""),
        }
        decision_packet = _build_decision_packet(
            generated_at=generated_at,
            experiment_id=experiment_id,
            status="crash",
            action=_decision_action(status="crash", promotion_state=None),
            decision_reason=crash_reason,
            launch_posture=launch_posture,
            safety_gates=safety_gates,
            candidate={
                "policy_id": candidate_id,
                "package_hash": runtime_package_hash(candidate_runtime_package or active_runtime_package),
                "policy_loss": None,
                "promotion_state": None,
                "simulator_champion_id": ((market_handoff_payload or {}).get("market_champion") or {}).get("id"),
                "market_epoch_id": (market_handoff_payload or {}).get("market_epoch_id"),
            },
            incumbent=(champion_registry.get("champion") if isinstance(champion_registry.get("champion"), dict) else None),
            champion_after=(champion_registry.get("champion") if isinstance(champion_registry.get("champion"), dict) else None),
            live_after=(champion_registry.get("live_package") if isinstance(champion_registry.get("live_package"), dict) else None),
            staged_after=(champion_registry.get("staged_package") if isinstance(champion_registry.get("staged_package"), dict) else None),
            policy_loss_contract_version=((market_handoff_payload or {}).get("policy_benchmark") or {}).get("policy_loss_contract_version"),
            policy_loss_formula=((market_handoff_payload or {}).get("policy_benchmark") or {}).get("policy_loss_formula"),
            evaluation_source=((market_handoff_payload or {}).get("policy_benchmark") or {}).get("evaluation_source"),
            simulator_champion_id=((market_handoff_payload or {}).get("market_champion") or {}).get("id"),
            market_epoch_id=(market_handoff_payload or {}).get("market_epoch_id"),
            artifact_paths=crash_artifact_paths,
        )
        row["decision"] = {
            "status": decision_packet["status"],
            "action": decision_packet["action"],
            "reason": decision_packet["decision_reason"],
        }
        _append_jsonl(results_ledger, row)
        _write_json(run_path, row)
        _write_json(promotion_decision_json, decision_packet)
        rows_after = _load_jsonl(results_ledger)
        summary = _crash_summary(
            existing_rows=rows_after,
            champion_registry=champion_registry,
            latest_row=row,
            latest_out=latest_out,
            latest_md=latest_md,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1

    assert current_evaluation is not None
    assert candidate_evaluation is not None
    if deploy_recommendation == "promote" and _runtime_package_relaxes_live_envelope(
        candidate_runtime_package,
        active_runtime_package,
    ):
        deploy_recommendation = "shadow_only"
    current_components = dict(current_evaluation.get("policy_benchmark") or {})
    candidate_components = dict(candidate_evaluation.get("policy_benchmark") or {})
    current_loss = safe_float(current_components.get("policy_loss"), 0.0) or 0.0
    candidate_loss = safe_float(candidate_components.get("policy_loss"), 0.0) or 0.0

    live_registry = champion_registry.get("live_package") if isinstance(champion_registry.get("live_package"), dict) else None
    champion = champion_registry.get("champion") if isinstance(champion_registry.get("champion"), dict) else None
    staged = champion_registry.get("staged_package") if isinstance(champion_registry.get("staged_package"), dict) else None
    previous_live = champion_registry.get("previous_live_package") if isinstance(champion_registry.get("previous_live_package"), dict) else None

    observed_live = _package_record(
        runtime_package=active_runtime_package,
        policy_loss=current_loss,
        generated_at=generated_at,
        source_artifact=cycle_json,
        promotion_state="observed_live",
        deploy_recommendation=str(cycle_payload.get("selected_deploy_recommendation") or cycle_payload.get("deploy_recommendation") or "hold"),
        package_env_path=active_env,
        package_json_path=active_package_json,
        policy_components=current_components,
        policy_evaluation=current_evaluation,
    )
    current_market_model_version = str(current_evaluation.get("market_model_version") or "").strip() or None
    champion_version = str((champion or {}).get("market_model_version") or "").strip() or None
    staged_version = str((staged or {}).get("market_model_version") or "").strip() or None
    if champion is None or champion_version != current_market_model_version:
        champion = dict(observed_live)
        champion["promotion_state"] = "baseline_frontier"
    if staged is not None and staged_version != current_market_model_version:
        staged = None
    if live_registry is None:
        live_registry = dict(observed_live)
        live_registry["promotion_state"] = "live_current"
    live_registry = _hydrate_package_record(live_registry, champion)
    live_registry = _hydrate_package_record(live_registry, staged)
    prior_live_registry_hash = str(live_registry.get("package_hash") or "").strip()
    observed_live_hash = str(observed_live.get("package_hash") or "").strip()
    if (
        prior_live_registry_hash
        and observed_live_hash
        and prior_live_registry_hash != observed_live_hash
    ):
        live_registry = dict(observed_live)
        live_registry["promotion_state"] = "live_current"
        if (
            champion is not None
            and str(champion.get("package_hash") or "").strip() == prior_live_registry_hash
            and str(champion.get("deploy_recommendation") or "hold").strip().lower() != "promote"
        ):
            champion = dict(champion)
            champion["promotion_state"] = "shadow_updated"
            if staged is None or str(staged.get("package_hash") or "").strip() != prior_live_registry_hash:
                staged = dict(champion)

    candidate_record = _package_record(
        runtime_package=candidate_runtime_package,
        policy_loss=candidate_loss,
        generated_at=generated_at,
        source_artifact=cycle_json,
        promotion_state=None,
        deploy_recommendation=deploy_recommendation,
        policy_components=candidate_components,
        policy_evaluation=candidate_evaluation,
    )

    keep = False
    status = "discard"
    promotion_state: str | None = None
    decision_reason = "candidate_not_better_than_incumbent"
    staged_because: str | None = None
    live_package = dict(live_registry)
    champion_record = dict(champion)
    staged_package = dict(staged) if isinstance(staged, dict) else None
    previous_live_package = dict(previous_live) if isinstance(previous_live, dict) else None

    rollback_threshold = float(args.rollback_loss_increase)
    live_matches_observed = live_registry.get("package_hash") == observed_live.get("package_hash")
    policy_min_improvement = max(float(args.keep_epsilon), float(POLICY_KEEP_EPSILON))
    comparison_incumbent = (
        champion_record
        if str(champion_record.get("market_model_version") or "").strip() == current_market_model_version
        else observed_live
    )
    incumbent_metrics = dict((comparison_incumbent.get("policy_components") or {}))
    candidate_vs_incumbent = _candidate_vs_incumbent_summary(candidate_record, comparison_incumbent)
    candidate_fill_retention = safe_float(candidate_components.get("fill_retention_ratio"), 1.0) or 1.0
    incumbent_p05 = safe_float(incumbent_metrics.get("p05_30d_return_pct"), current_components.get("p05_30d_return_pct")) or 0.0
    incumbent_median = safe_float(
        incumbent_metrics.get("median_30d_return_pct"),
        current_components.get("median_30d_return_pct"),
    ) or 0.0
    if (
        previous_live_package
        and live_matches_observed
        and current_loss > ((safe_float(live_registry.get("policy_loss"), 0.0) or 0.0) + rollback_threshold)
    ):
        restored = _write_package_files(
            runtime_package=dict(previous_live_package.get("runtime_package") or {}),
            policy_loss=(safe_float(previous_live_package.get("policy_loss"), 0.0) or 0.0),
            generated_at=generated_at,
            source_artifact=cycle_json,
            reason="post_promotion_policy_loss_degraded",
            env_path=active_env,
            json_path=active_package_json,
            deploy_recommendation=str(previous_live_package.get("deploy_recommendation") or "hold"),
            promotion_state="rollback_triggered",
            policy_components=dict(previous_live_package.get("policy_components") or {}),
            policy_evaluation=_policy_evaluation_from_package_record(previous_live_package),
        )
        live_package = dict(restored)
        live_package["promotion_state"] = "rollback_triggered"
        staged_package = dict(champion_record)
        staged_package["promotion_state"] = "shadow_updated"
        decision_reason = "post_promotion_policy_loss_degraded"
        promotion_state = "rollback_triggered"
    elif (
        launch_posture == "clear"
        and safety_gates.get("all_green")
        and staged_package
        and str(staged_package.get("market_model_version") or "").strip() == current_market_model_version
        and staged_package.get("package_hash") != live_registry.get("package_hash")
    ):
        activated = _write_package_files(
            runtime_package=dict(staged_package.get("runtime_package") or {}),
            policy_loss=(safe_float(staged_package.get("policy_loss"), 0.0) or 0.0),
            generated_at=generated_at,
            source_artifact=cycle_json,
            reason="launch_posture_cleared_activate_staged_champion",
            env_path=active_env,
            json_path=active_package_json,
            deploy_recommendation=str(staged_package.get("deploy_recommendation") or "shadow_only"),
            promotion_state="live_activated",
            policy_components=dict(staged_package.get("policy_components") or {}),
            policy_evaluation=_policy_evaluation_from_package_record(staged_package),
        )
        previous_live_package = dict(live_registry)
        live_package = dict(activated)
        live_package["promotion_state"] = "live_activated"
        staged_package = None
        keep = True
        status = "keep"
        promotion_state = "live_activated"
        decision_reason = "launch_posture_cleared_activate_staged_champion"
    else:
        actionable_candidate = deploy_recommendation in {"promote", "shadow_only"}
        live_promote_eligible = deploy_recommendation == "promote"
        incumbent_loss = safe_float(comparison_incumbent.get("policy_loss"), 0.0) or 0.0
        policy_improved = candidate_loss < (incumbent_loss - policy_min_improvement)
        median_improved = (safe_float(candidate_components.get("median_30d_return_pct"), 0.0) or 0.0) > incumbent_median
        p05_not_worse = (safe_float(candidate_components.get("p05_30d_return_pct"), 0.0) or 0.0) >= incumbent_p05
        fill_retention_ok = candidate_fill_retention >= float(PROMOTION_FILL_RETENTION_FLOOR)
        better_than_incumbent = actionable_candidate and policy_improved and median_improved and p05_not_worse and fill_retention_ok
        if better_than_incumbent:
            keep = True
            status = "keep"
            champion_record = dict(candidate_record)
            if live_promote_eligible and launch_posture == "clear" and safety_gates.get("all_green"):
                activated = _write_package_files(
                    runtime_package=candidate_runtime_package,
                    policy_loss=candidate_loss,
                    generated_at=generated_at,
                    source_artifact=cycle_json,
                    reason="launch_posture_clear_live_promote",
                    env_path=active_env,
                    json_path=active_package_json,
                    deploy_recommendation=deploy_recommendation,
                    promotion_state="live_promoted",
                    policy_components=candidate_components,
                    policy_evaluation=candidate_evaluation,
                )
                previous_live_package = dict(live_registry)
                live_package = dict(activated)
                live_package["promotion_state"] = "live_promoted"
                champion_record = dict(activated)
                champion_record["promotion_state"] = "live_promoted"
                staged_package = None
                promotion_state = "live_promoted"
                decision_reason = "champion_policy_loss_improved_live_promote"
            elif live_promote_eligible and launch_posture == "clear" and not safety_gates.get("all_green"):
                keep = False
                status = "discard"
                champion_record = dict(champion)
                promotion_state = None
                decision_reason = "non_posture_safety_interlocks_not_green"
            else:
                staged_saved = _write_package_files(
                    runtime_package=candidate_runtime_package,
                    policy_loss=candidate_loss,
                    generated_at=generated_at,
                    source_artifact=cycle_json,
                    reason="launch_posture_blocked_shadow_stage",
                    env_path=staged_env,
                    json_path=staged_package_json,
                    deploy_recommendation=deploy_recommendation,
                    promotion_state="shadow_updated",
                    policy_components=candidate_components,
                    policy_evaluation=candidate_evaluation,
                )
                champion_record = dict(staged_saved)
                champion_record["promotion_state"] = "shadow_updated"
                staged_package = dict(staged_saved)
                promotion_state = "shadow_updated"
                decision_reason = "champion_policy_loss_improved_shadow_stage"
                if (frontier_override or {}).get("package_hash") == candidate_record.get("package_hash"):
                    staged_because = "frontier_best"
        elif not actionable_candidate:
            decision_reason = "selected_policy_not_actionable"
        elif not policy_improved:
            decision_reason = "policy_loss_not_improved"
        elif not median_improved:
            decision_reason = "median_30d_return_not_improved"
        elif not p05_not_worse:
            decision_reason = "p05_30d_return_worsened"
        elif not fill_retention_ok:
            decision_reason = "fill_retention_ratio_below_threshold"
        elif not safety_gates.get("all_green"):
            decision_reason = "non_posture_safety_interlocks_not_green"

    champion_payload = {
        "updated_at": generated_at,
        "champion": champion_record,
        "live_package": live_package,
        "staged_package": staged_package,
        "previous_live_package": previous_live_package,
    }
    _write_json(champion_out, champion_payload)

    run_payload = {
        "experiment_id": experiment_id,
        "generated_at": generated_at,
        "description": str(args.description or "").strip(),
        "launch_posture": launch_posture,
        "selected_deploy_recommendation": deploy_recommendation,
        "selected_package_confidence_label": package_confidence_label,
        "candidate_policy": candidate_record["policy_id"],
        "candidate_package_hash": candidate_record["package_hash"],
        "candidate_policy_loss": round(candidate_loss, 4),
        "candidate_policy_components": candidate_components,
        "policy_loss_contract_version": current_evaluation.get("policy_loss_contract_version"),
        "policy_loss_formula": current_evaluation.get("policy_loss_formula"),
        "evaluation_source": current_evaluation.get("evaluation_source"),
        "simulator_champion_id": current_evaluation.get("simulator_champion_id"),
        "market_epoch_id": current_evaluation.get("market_epoch_id"),
        "market_model_version": current_market_model_version,
        "frontier_best_package_hash": (frontier_override or {}).get("package_hash"),
        "frontier_best_policy_id": (frontier_override or {}).get("policy_id"),
        "frontier_improvement_vs_incumbent": (frontier_override or {}).get("loss_improvement_vs_incumbent"),
        "staged_because": staged_because,
        "incumbent_policy": comparison_incumbent.get("policy_id") if isinstance(comparison_incumbent, dict) else observed_live["policy_id"],
        "incumbent_policy_loss": round((safe_float((comparison_incumbent or {}).get("policy_loss"), current_loss) or 0.0), 4),
        "current_live_policy": observed_live["policy_id"],
        "current_live_policy_loss": round(current_loss, 4),
        "policy_loss_delta": round(((safe_float((comparison_incumbent or {}).get("policy_loss"), current_loss) or 0.0) - candidate_loss), 4),
        "candidate_fill_retention_ratio": candidate_components.get("fill_retention_ratio"),
        "candidate_expected_fills_per_day": candidate_components.get("expected_fills_per_day"),
        "incumbent_fill_retention_ratio": incumbent_metrics.get("fill_retention_ratio", 1.0),
        "incumbent_expected_fills_per_day": incumbent_metrics.get("expected_fills_per_day"),
        "candidate_fold_results": candidate_record.get("fold_results") or [],
        "incumbent_fold_results": comparison_incumbent.get("fold_results") if isinstance(comparison_incumbent, dict) else [],
        "candidate_vs_incumbent_summary": candidate_vs_incumbent,
        "safety_gates": safety_gates,
        "status": status,
        "keep": keep,
        "promotion_state": promotion_state,
        "decision_reason": decision_reason,
        "champion_id": champion_record.get("policy_id"),
        "artifact_paths": {
            "run_json": _relative(run_path),
            "results_ledger": str(results_ledger),
            "cycle_json": _relative(cycle_json),
            "portfolio_json": _relative(portfolio_json) if portfolio_json.exists() else None,
            "market_policy_handoff": _relative(market_policy_handoff) if market_policy_handoff.exists() else None,
            "market_latest_json": _relative(market_latest_json) if market_latest_json.exists() else None,
            "champion_json": _relative(champion_out),
            "active_env": _relative(active_env),
            "active_package_json": _relative(active_package_json),
            "staged_env": _relative(staged_env),
            "staged_package_json": _relative(staged_package_json),
        },
        "cycle_returncode": None if cycle_result is None else cycle_result.returncode,
        "cycle_stdout_tail": ((cycle_result.stdout or "").strip()[-500:] if cycle_result is not None else ""),
        "cycle_stderr_tail": ((cycle_result.stderr or "").strip()[-500:] if cycle_result is not None else ""),
        "portfolio_returncode": None if portfolio_result is None else portfolio_result.returncode,
        "portfolio_stdout_tail": ((portfolio_result.stdout or "").strip()[-500:] if portfolio_result is not None else ""),
        "portfolio_stderr_tail": ((portfolio_result.stderr or "").strip()[-500:] if portfolio_result is not None else ""),
    }
    decision_artifact_paths = {
        "results_ledger": _relative(results_ledger),
        "run_json": _relative(run_path),
        "champion_registry": _relative(champion_out),
        "market_policy_handoff": _relative(market_policy_handoff) if market_policy_handoff.exists() else None,
        "market_latest_json": _relative(market_latest_json) if market_latest_json.exists() else None,
    }
    decision_packet = _build_decision_packet(
        generated_at=generated_at,
        experiment_id=experiment_id,
        status=status,
        action=_decision_action(status=status, promotion_state=promotion_state),
        decision_reason=decision_reason,
        launch_posture=launch_posture,
        safety_gates=safety_gates,
        candidate=candidate_record,
        incumbent=comparison_incumbent,
        champion_after=champion_record,
        live_after=live_package,
        staged_after=staged_package,
        policy_loss_contract_version=current_evaluation.get("policy_loss_contract_version"),
        policy_loss_formula=current_evaluation.get("policy_loss_formula"),
        evaluation_source=current_evaluation.get("evaluation_source"),
        simulator_champion_id=current_evaluation.get("simulator_champion_id"),
        market_epoch_id=current_evaluation.get("market_epoch_id"),
        artifact_paths=decision_artifact_paths,
    )
    run_payload["decision"] = {
        "status": decision_packet["status"],
        "action": decision_packet["action"],
        "reason": decision_packet["decision_reason"],
    }
    _append_jsonl(results_ledger, run_payload)
    _write_json(run_path, run_payload)
    _write_json(promotion_decision_json, decision_packet)

    rows_after = _load_jsonl(results_ledger)
    canonical_live_package = _canonicalize_live_package_alias(
        live_package=live_package,
        champion_record=champion_record,
    )
    canonical_active_runtime_package = (
        dict((canonical_live_package or {}).get("runtime_package") or {})
        if isinstance((canonical_live_package or {}).get("runtime_package"), dict)
        else active_runtime_package
    )
    selected_best_profile_name = runtime_package_id(candidate_runtime_package) if candidate_runtime_package else None
    selected_active_profile_name = (
        runtime_package_id(canonical_active_runtime_package)
        if canonical_active_runtime_package
        else None
    )
    selected_best_package_hash = (
        runtime_package_hash(candidate_runtime_package)
        if candidate_runtime_package
        else None
    )
    selected_active_package_hash = str(
        (canonical_live_package or {}).get("package_hash")
        or (live_package or {}).get("package_hash")
        or (
            runtime_package_hash(canonical_active_runtime_package)
            if canonical_active_runtime_package
            else ""
        )
        or ""
    ).strip() or None
    canonical_live_profile = (
        selected_active_profile_name
        or selected_best_profile_name
    )
    canonical_live_package_hash = (
        selected_active_package_hash
        or selected_best_package_hash
    )
    shadow_comparator_profile = (
        selected_best_profile_name
        if selected_best_profile_name and selected_best_profile_name != canonical_live_profile
        else None
    )

    summary = {
        "updated_at": generated_at,
        "champion_id": champion_record.get("policy_id"),
        "loss": champion_record.get("policy_loss"),
        "latest_policy_loss": candidate_loss,
        "launch_posture": launch_posture,
        "submission_policy": "shadow_only" if launch_posture != "clear" else "auto_promote_when_champion_improves",
        "selected_deploy_recommendation": deploy_recommendation,
        "policy_loss_contract_version": current_evaluation.get("policy_loss_contract_version"),
        "policy_loss_formula": current_evaluation.get("policy_loss_formula"),
        "evaluation_source": current_evaluation.get("evaluation_source"),
        "simulator_champion_id": current_evaluation.get("simulator_champion_id"),
        "market_epoch_id": current_evaluation.get("market_epoch_id"),
        "market_model_version": current_market_model_version,
        "market_policy_handoff": market_handoff_payload,
        "frontier_best_candidate": frontier_override,
        "staged_because": staged_because,
        "candidate_vs_incumbent_summary": candidate_vs_incumbent,
        "safety_gates": safety_gates,
        "champion": champion_record,
        "live_package": canonical_live_package,
        "staged_package": staged_package,
        "latest_experiment": run_payload,
        "counts": _counts(rows_after),
        "selected_active_profile_name": selected_active_profile_name,
        "selected_best_profile_name": selected_best_profile_name,
        "selected_active_package_hash": selected_active_package_hash,
        "selected_best_package_hash": selected_best_package_hash,
        "canonical_live_profile": canonical_live_profile,
        "canonical_live_package_hash": canonical_live_package_hash,
        "shadow_comparator_profile": shadow_comparator_profile,
        "canonical_package_drift_detected": bool(shadow_comparator_profile),
        "best_runtime_package": candidate_runtime_package,
        "selected_best_runtime_package": candidate_runtime_package,
        "active_runtime_package": canonical_active_runtime_package,
        "selected_active_runtime_package": canonical_active_runtime_package,
        "artifacts": {
            "results_ledger": _relative(results_ledger),
            "latest_run": _relative(run_path),
            "champion_json": _relative(champion_out),
            "promotion_decision_json": _relative(promotion_decision_json),
            "cycle_json": _relative(cycle_json),
            "portfolio_json": _relative(portfolio_json) if portfolio_json.exists() else None,
            "market_policy_handoff": _relative(market_policy_handoff) if market_policy_handoff.exists() else None,
            "market_latest_json": _relative(market_latest_json) if market_latest_json.exists() else None,
        },
    }
    _write_json(latest_out, summary)
    _write_latest_markdown(latest_md, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
