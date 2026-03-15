#!/usr/bin/env python3
"""Instance #3 dispatcher: shadow execution readiness + micro-live plan output."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from execution.shadow_order_lifecycle import ShadowOrderLifecycle


REPORTS_DIR = Path("reports")
DEFAULT_BTC5_ARTIFACT = Path("reports/btc5_autoresearch/latest.json")

BTC5_MIN_ARR_UPLIFT_PCT = 0.0
BTC5_MIN_CONFIDENCE = 0.8
BTC5_MAX_CANDIDATE_AGE_HOURS = 6.0


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _parse_iso8601(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_latest(pattern: str) -> Path | None:
    matches = sorted(REPORTS_DIR.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _candidate_age_hours(artifact_path: Path, generated_at: str | None) -> float:
    now = datetime.now(timezone.utc)
    generated = _parse_iso8601(generated_at)
    if generated is None:
        generated = datetime.fromtimestamp(artifact_path.stat().st_mtime, tz=timezone.utc)
    return max(0.0, (now - generated).total_seconds() / 3600.0)


def _extract_btc5_readiness(artifact_path: Path | None) -> dict[str, Any]:
    if artifact_path is None or not artifact_path.exists():
        return {
            "ok": False,
            "ready": False,
            "reasons": ["missing_btc5_readiness_artifact"],
            "expected_arr_uplift_pct": None,
            "confidence": None,
            "candidate_age_hours": None,
            "candidate": {},
        }

    payload = _read_json(artifact_path)
    if not payload:
        return {
            "ok": False,
            "ready": False,
            "reasons": ["btc5_readiness_artifact_unreadable"],
            "expected_arr_uplift_pct": None,
            "confidence": None,
            "candidate_age_hours": None,
            "candidate": {},
        }

    candidate = payload.get("best_candidate")
    if not isinstance(candidate, Mapping):
        candidate = payload.get("current_candidate", {})
    if not isinstance(candidate, Mapping):
        candidate = {}

    candidate_payload = dict(candidate)
    continuation = candidate_payload.get("continuation")
    if not isinstance(continuation, Mapping):
        continuation = {}
    scoring = candidate_payload.get("scoring")
    if not isinstance(scoring, Mapping):
        scoring = {}

    arr_uplift = _as_optional_float(continuation.get("median_arr_pct"))
    if arr_uplift is None:
        arr_uplift = _as_optional_float(scoring.get("live_policy_score"))
    confidence = _as_optional_float(candidate_payload.get("execution_realism_score"))
    if confidence is None:
        confidence = _as_optional_float(scoring.get("execution_realism_score"))

    candidate_age_hours = _candidate_age_hours(
        artifact_path=artifact_path,
        generated_at=_as_str(payload.get("generated_at")),
    )

    reasons: list[str] = []
    candidate_class = str(candidate_payload.get("candidate_class") or "").strip().lower()
    evidence_band = str(candidate_payload.get("evidence_band") or "").strip().lower()
    if candidate_class not in {"promote", "live_candidate"}:
        reasons.append(f"candidate_class={candidate_class or 'missing'}")
    if not evidence_band and candidate_class == "promote":
        reasons.append("evidence_band_missing")
    elif evidence_band and evidence_band not in {"validated", "high", "medium", "strong"} and candidate_class == "promote":
        reasons.append(f"evidence_band={evidence_band}")
    if arr_uplift is None:
        reasons.append("expected_arr_uplift_missing")
    elif arr_uplift <= BTC5_MIN_ARR_UPLIFT_PCT:
        reasons.append(f"expected_arr_uplift_not_positive: {arr_uplift:.4f}")
    if confidence is None:
        reasons.append("confidence_missing")
    elif confidence < BTC5_MIN_CONFIDENCE:
        reasons.append(f"confidence_below_threshold: {confidence:.4f}")
    if candidate_age_hours > BTC5_MAX_CANDIDATE_AGE_HOURS:
        reasons.append(f"candidate_age_hours_exceeds_{BTC5_MAX_CANDIDATE_AGE_HOURS}:{candidate_age_hours:.2f}")

    return {
        "ok": len(reasons) == 0,
        "ready": len(reasons) == 0,
        "reasons": reasons,
        "candidate_class": candidate_class or None,
        "evidence_band": evidence_band or None,
        "expected_arr_uplift_pct": arr_uplift,
        "confidence": confidence,
        "candidate_age_hours": candidate_age_hours,
        "generated_at": payload.get("generated_at"),
        "artifact": str(artifact_path),
        "candidate": {
            "base_profile": candidate_payload.get("base_profile"),
            "policy": candidate_payload.get("policy"),
            "session_overrides": candidate_payload.get("session_overrides"),
            "recommended_session_policy": candidate_payload.get("recommended_session_policy"),
        },
    }


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_launch_posture(runtime_truth: Mapping[str, Any]) -> str:
    summary = runtime_truth.get("summary")
    if isinstance(summary, Mapping):
        posture = str(summary.get("launch_posture", "") or "").strip().lower()
        if posture:
            return posture
    launch = runtime_truth.get("launch")
    if isinstance(launch, Mapping):
        posture = str(launch.get("posture", "") or "").strip().lower()
        if posture:
            return posture
    return str(runtime_truth.get("launch_posture", "") or "").strip().lower()


def evaluate_runtime_guard(runtime_truth_path: Path, runtime_profile_path: Path) -> dict[str, Any]:
    runtime_truth = _read_json(runtime_truth_path)
    runtime_profile = _read_json(runtime_profile_path)
    mode = runtime_profile.get("mode") if isinstance(runtime_profile.get("mode"), Mapping) else {}

    launch_posture = _extract_launch_posture(runtime_truth)
    paper_trading = mode.get("paper_trading")
    if paper_trading is None:
        paper_trading = str(os.environ.get("PAPER_TRADING", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        paper_trading = bool(paper_trading)

    order_submit_enabled = mode.get("allow_order_submission")
    if order_submit_enabled is None:
        order_submit_enabled = str(os.environ.get("JJ_ALLOW_ORDER_SUBMISSION", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        order_submit_enabled = bool(order_submit_enabled)

    force_live_attempt = os.environ.get("JJ_FORCE_LIVE_ATTEMPT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    agent_run_mode = str(
        os.environ.get("ELASTIFUND_AGENT_RUN_MODE")
        or runtime_truth.get("agent_run_mode")
        or runtime_profile.get("agent_run_mode")
        or ""
    ).strip().lower()

    posture_green = force_live_attempt or launch_posture in {"clear", "green", "unblocked"}
    paper_green = paper_trading is False
    mode_green = force_live_attempt or agent_run_mode in {"shadow", "micro_live", "live"}
    submit_green = order_submit_enabled is True
    greenlight = posture_green and paper_green and mode_green and submit_green

    reasons: list[str] = []
    if force_live_attempt:
        reasons.append("force_live_attempt=true")
    if not posture_green:
        reasons.append(f"launch_posture={launch_posture or 'unknown'}")
    if not paper_green:
        reasons.append(f"paper_trading={paper_trading}")
    if not mode_green:
        reasons.append(f"agent_run_mode={agent_run_mode or 'unknown'}")
    if not submit_green:
        reasons.append(f"order_submit_enabled={order_submit_enabled}")

    return {
        "greenlight": greenlight,
        "reason": ",".join(reasons) if reasons else "green",
        "launch_posture": launch_posture or "unknown",
        "paper_trading": paper_trading,
        "agent_run_mode": agent_run_mode or "unknown",
        "order_submit_enabled": order_submit_enabled,
        "runtime_truth_path": str(runtime_truth_path),
        "runtime_profile_path": str(runtime_profile_path),
    }


def _load_candidates(candidate_path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    if candidate_path is None:
        return [], "missing_candidate_artifact"
    payload = _read_json(candidate_path)
    if isinstance(payload.get("candidates"), list):
        return [item for item in payload["candidates"] if isinstance(item, dict)], None
    if isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)], None
    if isinstance(payload.get("records"), list):
        return [item for item in payload["records"] if isinstance(item, dict)], None
    if isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)], None
    if isinstance(payload, dict):
        return [], "candidate_payload_has_no_list"
    return [], "candidate_payload_invalid"


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _candidate_market_id(candidate: Mapping[str, Any]) -> str:
    for key in ("market_id", "condition_id", "conditionId", "id", "ticker"):
        value = str(candidate.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _candidate_side(candidate: Mapping[str, Any]) -> str:
    direct = str(candidate.get("side", "") or candidate.get("direction", "")).strip().lower()
    if direct in {"buy_yes", "buy_no", "buy"}:
        return direct
    market_prob = _as_float(candidate.get("market_probability"), 0.5)
    fair_prob = _as_float(candidate.get("fair_probability"), market_prob)
    return "buy_yes" if fair_prob >= market_prob else "buy_no"


def _candidate_price(candidate: Mapping[str, Any]) -> float:
    for key in ("market_probability", "best_yes", "price", "market_price", "best_no"):
        raw = candidate.get(key)
        if raw is None:
            continue
        value = _as_float(raw, -1.0)
        if 0.0 <= value <= 1.0:
            return value
    return 0.5


def build_shadow_readiness() -> tuple[Path, Path]:
    ts = _utc_stamp()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    runtime_truth_path = Path(os.environ.get("JJ_RUNTIME_TRUTH_PATH", "reports/runtime_truth_latest.json"))
    runtime_profile_path = Path(
        os.environ.get("JJ_RUNTIME_PROFILE_EFFECTIVE_PATH", "reports/runtime_profile_effective.json")
    )
    runtime_profile = _read_json(runtime_profile_path)
    btc5_path = Path(os.environ.get("INSTANCE3_BTC5_ARTIFACT", str(DEFAULT_BTC5_ARTIFACT)))
    btc5_readiness = _extract_btc5_readiness(btc5_path if btc5_path.exists() else None)
    candidate_path = _find_latest("poly_fastlane_candidates_*.json")
    candidates, candidate_error = _load_candidates(candidate_path)

    guard = evaluate_runtime_guard(runtime_truth_path, runtime_profile_path)
    runtime_mode = runtime_profile.get("mode", {})
    if not isinstance(runtime_mode, Mapping):
        runtime_mode = {}
    risk_limits = runtime_profile.get("risk_limits", {})
    if not isinstance(risk_limits, Mapping):
        risk_limits = {}
    lifecycle = ShadowOrderLifecycle(ttl_seconds=120.0, expected_fill_window_seconds=30.0)

    staged = 0
    dedup_skipped = 0
    rejected = 0
    staged_orders: list[dict[str, Any]] = []
    for candidate in candidates:
        market_id = _candidate_market_id(candidate)
        side = _candidate_side(candidate)
        if not market_id:
            rejected += 1
            continue
        order = lifecycle.place_synthetic_order(
            market_id=market_id,
            side=side,
            reference_price=_candidate_price(candidate),
            size_usd=min(5.0, max(1.0, _as_float(candidate.get("target_size_usd"), 5.0))),
            expected_fill_probability=_as_float(candidate.get("expected_maker_fill_probability"), 0.5),
            expected_fill_window_seconds=_as_float(candidate.get("expected_fill_window_seconds"), 30.0),
            metadata={
                "title": str(candidate.get("title", "") or "")[:200],
                "route_score": _as_float(candidate.get("route_score"), 0.0),
                "fee_adjusted_expected_edge": _as_float(candidate.get("fee_adjusted_expected_edge"), 0.0),
                "toxicity_state": str(candidate.get("toxicity_state", "unknown") or "unknown"),
                "reject_reason": str(candidate.get("reject_reason", "") or ""),
            },
        )
        if order is None:
            dedup_skipped += 1
            continue
        staged += 1
        if str(candidate.get("reject_reason", "") or "").strip():
            lifecycle.cancel(order.order_id, f"candidate_rejected:{candidate['reject_reason']}")
            rejected += 1
        staged_orders.append(
            {
                "order_id": order.order_id,
                "market_id": order.market_id,
                "side": order.side,
                "size_usd": order.size_usd,
                "reference_price": order.reference_price,
                "expected_fill_probability": order.expected_fill_probability,
                "expected_fill_window_seconds": order.expected_fill_window_seconds,
                "ttl_seconds": order.ttl_seconds,
                "metadata": order.metadata,
            }
        )

    readiness_payload = {
        "artifact": "polymarket_shadow_readiness",
        "generated_at": now.isoformat(),
        "runtime_guard": guard,
        "submission_policy": (
            "eligible_btc5_live" if (guard["greenlight"] and btc5_readiness["ready"]) else "eligible_shadow_fastlane"
            if guard["greenlight"]
            else "shadow_only"
        ),
        "sources": {
            "runtime_truth": str(runtime_truth_path),
            "runtime_profile_effective": str(runtime_profile_path),
            "candidate_surface": str(candidate_path) if candidate_path else None,
            "btc5_readiness_artifact": str(btc5_path),
        },
        "btc5_readiness": btc5_readiness,
        "candidate_intake": {
            "loaded_count": len(candidates),
            "staged_shadow_orders": staged,
            "dedup_skipped": dedup_skipped,
            "rejected_or_cancelled": rejected,
            "error": candidate_error,
        },
        "safety_envelope": {
            "paper_trading": bool(runtime_mode.get("paper_trading", True)),
            "allow_order_submission": bool(runtime_mode.get("allow_order_submission", False)),
            "max_position_usd": _safe_float(risk_limits.get("max_position_usd"), 0.0),
            "max_daily_loss_usd": _safe_float(risk_limits.get("max_daily_loss_usd"), 0.0),
            "max_open_positions": _safe_int(risk_limits.get("max_open_positions"), 0),
        },
        "candidate_to_trade_conversion_estimate": 1.0 if btc5_readiness["ready"] else 0.0,
        "shadow_lifecycle": lifecycle.to_report(),
        "shadow_orders": staged_orders,
    }

    readiness_path = REPORTS_DIR / f"polymarket_shadow_readiness_{ts}.json"
    readiness_path.write_text(json.dumps(readiness_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    max_rows = 12
    order_lines = []
    for row in staged_orders[:max_rows]:
        order_lines.append(
            "| {market_id} | {side} | ${size_usd:.2f} | {reference_price:.3f} | {expected_fill_probability:.2f} | {ttl_seconds:.0f}s | {reason} |".format(
                market_id=row["market_id"],
                side=row["side"],
                size_usd=float(row["size_usd"]),
                reference_price=float(row["reference_price"]),
                expected_fill_probability=float(row["expected_fill_probability"]),
                ttl_seconds=float(row["ttl_seconds"]),
                reason=str(row["metadata"].get("reject_reason") or "-"),
            )
        )

    plan_lines = [
        "# Polymarket Micro-Live Plan (Preparation Only)",
        "",
        f"- Generated at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Runtime guard greenlight: `{guard['greenlight']}`",
        f"- Runtime guard reason: `{guard['reason']}`",
        f"- Launch posture: `{guard['launch_posture']}`",
        f"- Agent run mode: `{guard['agent_run_mode']}`",
        f"- Order submit enabled: `{guard['order_submit_enabled']}`",
        f"- BTC5 candidate ready: `{btc5_readiness['ready']}`",
        f"- BTC5 candidate class: `{btc5_readiness.get('candidate_class') or 'missing'}`",
        f"- BTC5 evidence band: `{btc5_readiness.get('evidence_band') or 'missing'}`",
        f"- BTC5 confidence: `{_safe_float(btc5_readiness.get('confidence'), 0.0):.4f}`",
        f"- BTC5 expected ARR uplift (%): `{_safe_float(btc5_readiness.get('expected_arr_uplift_pct'), 0.0):.4f}`",
        f"- BTC5 candidate age (h): `{_safe_float(btc5_readiness.get('candidate_age_hours'), 0.0):.2f}`",
        f"- BTC5 estimated candidate->trade conversion: `{readiness_payload['candidate_to_trade_conversion_estimate']:.2f}`",
        "",
        "## Hard Guardrail",
        "- If runtime guard is not explicitly green, only synthetic shadow orders are permitted.",
        "- Real order submission remains blocked in this plan.",
        "- BTC5 lane is treated as primary only when runtime guard and BTC5 readiness are both green.",
        "",
        "## Candidate Intake",
        f"- Candidate artifact: `{candidate_path}`" if candidate_path else "- Candidate artifact: `missing`",
        f"- Candidates loaded: `{len(candidates)}`",
        f"- Shadow orders staged: `{staged}`",
        f"- Dedup skipped: `{dedup_skipped}`",
        f"- Rejected/cancelled: `{rejected}`",
        "",
        "## Synthetic Resting Orders",
        "| Market | Side | Size | Ref Px | Fill Prob | TTL | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    if order_lines:
        plan_lines.extend(order_lines)
    else:
        plan_lines.append("| - | - | - | - | - | - | No staged orders (missing or non-tradeable candidate surface) |")

    plan_lines.extend(
        [
            "",
            "## Rollback Conditions",
            "- Force shadow-only if launch posture is not `clear|green|unblocked`.",
            "- Force shadow-only if `paper_trading=true` in runtime profile effective mode.",
            "- Force shadow-only if `ELASTIFUND_AGENT_RUN_MODE` is not `shadow`, `micro_live`, or `live`.",
            "- Force shadow-only if `allow_order_submission` is false or ambiguous.",
            "- Force no-BTC5 activation if BTC5 readiness remains blocked.",
            "",
            "## BTC5 Micro-Live Activation (One-Cycle)",
            "- If `submission_policy=eligible_btc5_live`, use this sequence in order:",
            "  - keep mandatory envelope: max position, max daily loss, max open positions, post-only placement.",
            "  - load BTC5 readiness package from `reports/btc5_autoresearch/latest.json`.",
            "  - run `python3 scripts/btc5_rollout.py` and confirm `deploy_mode=live_stage1` in the latest artifact.",
            "  - suggested invocation:",
            "    ```bash",
            "    ELASTIFUND_AGENT_RUN_MODE=micro_live PAPER_TRADING=false JJ_FORCE_LIVE_ATTEMPT=true python3 scripts/btc5_rollout.py",
            "    ```",
            "",
            "## Risk Envelope (Preparation Only)",
            f"- `$ {readiness_payload['safety_envelope']['max_position_usd']:.2f}` max position cap for live sleeve.",
            f"- `${readiness_payload['safety_envelope']['max_daily_loss_usd']:.2f}` max daily loss cap for live sleeve.",
            f"- `{readiness_payload['safety_envelope']['max_open_positions']}` max open positions.",
            "- Keep post-only, no market order, and BTC5 session-policy-only routing.",
            "- Candidate gate: `candidate_class=promote`, confidence >= 0.8, positive expected ARR uplift, and age <= 6h.",
            "",
            "No capital routing is executed by this script.",
        ]
    )

    plan_path = REPORTS_DIR / f"polymarket_micro_live_plan_{ts}.md"
    plan_path.write_text("\n".join(plan_lines) + "\n", encoding="utf-8")
    return readiness_path, plan_path


def main() -> int:
    readiness_path, plan_path = build_shadow_readiness()
    print(json.dumps({"shadow_readiness": str(readiness_path), "micro_live_plan": str(plan_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
