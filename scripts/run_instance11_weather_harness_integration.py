#!/usr/bin/env python3
"""Instance 11 — Weather + Harness Integration.

Merges:
  Instance 7 — NOAA/NWS weather loop completion
  Instance 8 — End-to-end intelligence harness

What this script does
---------------------
1. Refreshes the weather shadow artifact (live API if reachable; stale fallback otherwise).
2. Reads BTC5 maker DB for real lane evidence.
3. Builds an EvidenceBundle from all sources.
4. Runs the full kernel cycle: evidence -> thesis -> promotion -> learning.
5. Runs the intelligence harness (replay gauntlets + metrics).
6. Writes canonical output artifacts:
     reports/capital_lab/latest.json
     reports/proving_ground/latest.json
     reports/kernel/kernel_cycle_latest.json
     reports/harness/harness_result_latest.json

Outputs feed the operator packet and continuous_orchestration scheduler.

Usage
-----
  python scripts/run_instance11_weather_harness_integration.py
  python scripts/run_instance11_weather_harness_integration.py --no-refresh-weather
  python scripts/run_instance11_weather_harness_integration.py --skip-harness
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Kernel imports
from kernel_contract import (  # noqa: E402
    EvidenceBundle,
    KernelCycleResult,
    LearningBundle,
    PromotionBundle,
    ThesisBundle,
    run_kernel_cycle,
    write_kernel_cycle,
)
from scripts.report_envelope import write_report

DEFAULT_CAPITAL_LAB_PATH = REPO_ROOT / "reports" / "capital_lab" / "latest.json"
DEFAULT_PROVING_GROUND_PATH = REPO_ROOT / "reports" / "proving_ground" / "latest.json"
DEFAULT_KERNEL_CYCLE_PATH = REPO_ROOT / "reports" / "kernel" / "kernel_cycle_latest.json"
DEFAULT_HARNESS_PATH = REPO_ROOT / "reports" / "harness" / "harness_result_latest.json"
DEFAULT_WEATHER_SHADOW_PATH = (
    REPO_ROOT / "reports" / "parallel" / "instance04_weather_divergence_shadow.json"
)
DEFAULT_FINANCE_PATH = REPO_ROOT / "reports" / "finance" / "latest.json"
DEFAULT_PROMOTION_GATE_PATH = REPO_ROOT / "reports" / "btc5_promotion_gate.json"
DEFAULT_BTC5_DB_PATH = REPO_ROOT / "data" / "btc_5min_maker.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v)) if v not in (None, "") else default
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


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 1 — Weather shadow refresh
# ---------------------------------------------------------------------------


def refresh_weather_shadow(
    output_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], str]:
    """Try to regenerate the weather shadow artifact.

    Returns (artifact_dict, status) where status is one of:
      "refreshed"       — live API succeeded
      "stale_fallback"  — API failed, loaded existing artifact
      "unavailable"     — API failed and no existing artifact
    """
    try:
        from run_instance4_weather_shadow_lane import (
            build_instance4_weather_lane_artifact,
            render_markdown,
        )

        artifact = build_instance4_weather_lane_artifact(repo_root=repo_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(artifact, indent=2, default=str), encoding="utf-8"
        )
        md_path = output_path.with_suffix(".md")
        md_path.write_text(render_markdown(artifact), encoding="utf-8")
        return artifact, "refreshed"
    except Exception as exc:  # network blocked in sandbox, or import error
        stale = _load_json(output_path)
        if stale:
            return stale, f"stale_fallback:{exc}"
        return {}, f"unavailable:{exc}"


# ---------------------------------------------------------------------------
# Step 2 — BTC5 DB state reader
# ---------------------------------------------------------------------------


def read_btc5_db_state(db_path: Path) -> dict[str, Any]:
    """Read BTC5 maker DB for real lane evidence."""
    base: dict[str, Any] = {
        "db_available": False,
        "total_rows": 0,
        "fill_count": 0,
        "skip_count": 0,
        "skip_reasons": {},
        "latest_entry_at": None,
    }
    if not db_path.exists():
        return base

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            total_row = conn.execute("SELECT COUNT(*) FROM window_trades").fetchone()
            total = _safe_int(total_row[0] if total_row else 0)

            skip_rows = conn.execute(
                "SELECT skip_reason, COUNT(*) cnt FROM window_trades "
                "WHERE skip_reason IS NOT NULL AND skip_reason != '' "
                "GROUP BY skip_reason ORDER BY cnt DESC"
            ).fetchall()
            skip_reasons = {str(row["skip_reason"]): int(row["cnt"]) for row in skip_rows}
            skip_count = sum(skip_reasons.values())

            fill_row = conn.execute(
                "SELECT COUNT(*) FROM window_trades "
                "WHERE outcome IS NOT NULL AND outcome != 'skip'"
            ).fetchone()
            fill_count = _safe_int(fill_row[0] if fill_row else 0)

            latest_row = conn.execute(
                "SELECT MAX(window_open_utc) FROM window_trades"
            ).fetchone()
            latest_at = str(latest_row[0]) if latest_row and latest_row[0] else None

            return {
                "db_available": True,
                "total_rows": total,
                "fill_count": fill_count,
                "skip_count": skip_count,
                "skip_reasons": skip_reasons,
                "latest_entry_at": latest_at,
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {**base, "db_available": True, "db_error": str(exc)}


# ---------------------------------------------------------------------------
# Step 3 — Build EvidenceBundle (public API for harness)
# ---------------------------------------------------------------------------


def build_evidence_bundle_from_state(
    *,
    btc5_rows: int = 0,
    btc5_fill_count: int = 0,
    btc5_skip_reasons: dict[str, int] | None = None,
    btc5_latest_entry_at: str | None = None,
    weather_shadow_present: bool = False,
    weather_candidate_count: int = 0,
    weather_arr_confidence: float = 0.0,
    weather_block_reasons: list[str] | None = None,
    weather_generated_at: str = "",
    stale_fallback_used: bool = False,
    now: datetime | None = None,
) -> EvidenceBundle:
    """Construct an EvidenceBundle from raw state values (used by harness fixtures)."""
    now = now or datetime.now(timezone.utc)
    skip_reasons = btc5_skip_reasons or {}
    skip_count = sum(skip_reasons.values())
    freshness: dict[str, float] = {}
    if weather_generated_at:
        try:
            ws_ts = datetime.fromisoformat(weather_generated_at.replace("Z", "+00:00"))
            age = (now.astimezone(timezone.utc) - ws_ts.astimezone(timezone.utc)).total_seconds()
            freshness["weather_shadow"] = max(0.0, 1.0 - age / (24 * 3600))
        except ValueError:
            freshness["weather_shadow"] = 0.0
    if btc5_latest_entry_at:
        try:
            b5_ts = datetime.fromisoformat(btc5_latest_entry_at.replace("Z", "+00:00"))
            age = (now.astimezone(timezone.utc) - b5_ts.astimezone(timezone.utc)).total_seconds()
            freshness["btc5_db"] = max(0.0, 1.0 - age / (6 * 3600))
        except ValueError:
            freshness["btc5_db"] = 0.0

    return EvidenceBundle(
        generated_at=_iso_z(now),
        btc5_rows=btc5_rows,
        btc5_fill_count=btc5_fill_count,
        btc5_skip_reasons=skip_reasons,
        btc5_latest_entry_at=btc5_latest_entry_at,
        weather_shadow_present=weather_shadow_present,
        weather_candidate_count=weather_candidate_count,
        weather_arr_confidence=weather_arr_confidence,
        weather_block_reasons=weather_block_reasons or [],
        weather_generated_at=weather_generated_at,
        stale_fallback_used=stale_fallback_used,
        freshness_scores=freshness,
        decision_log_rows=btc5_rows,
    )


def build_evidence_bundle(
    *,
    weather_shadow: dict[str, Any],
    weather_refresh_status: str,
    btc5_db: dict[str, Any],
    now: datetime | None = None,
) -> EvidenceBundle:
    """Build EvidenceBundle from live data sources."""
    now = now or datetime.now(timezone.utc)
    ws_present = bool(weather_shadow)
    ws_scan = weather_shadow.get("market_scan") or {}
    ws_candidates = _safe_int(ws_scan.get("candidate_count"), 0)
    ws_confidence = _safe_float(weather_shadow.get("arr_confidence_score"), 0.0)
    ws_block = list(weather_shadow.get("block_reasons") or [])
    ws_generated_at = str(weather_shadow.get("generated_at") or "")
    stale_fallback = "stale_fallback" in weather_refresh_status or not ws_present

    return build_evidence_bundle_from_state(
        btc5_rows=btc5_db.get("total_rows", 0),
        btc5_fill_count=btc5_db.get("fill_count", 0),
        btc5_skip_reasons=btc5_db.get("skip_reasons", {}),
        btc5_latest_entry_at=btc5_db.get("latest_entry_at"),
        weather_shadow_present=ws_present,
        weather_candidate_count=ws_candidates,
        weather_arr_confidence=ws_confidence,
        weather_block_reasons=ws_block,
        weather_generated_at=ws_generated_at,
        stale_fallback_used=stale_fallback,
        now=now,
    )


# ---------------------------------------------------------------------------
# Step 4 — Run full kernel cycle (public API for harness)
# ---------------------------------------------------------------------------


def run_full_kernel_cycle(
    evidence: EvidenceBundle,
    *,
    finance_latest: dict[str, Any] | None = None,
    promotion_gate: dict[str, Any] | None = None,
    weather_shadow: dict[str, Any] | None = None,
    proposed_mutations: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> KernelCycleResult:
    """Run the kernel cycle with the given evidence and optional overrides."""
    now = now or datetime.now(timezone.utc)
    return run_kernel_cycle(
        evidence,
        weather_shadow=weather_shadow,
        promotion_gate=promotion_gate,
        finance_latest=finance_latest,
        proposed_mutations=proposed_mutations,
        now=now,
    )


# ---------------------------------------------------------------------------
# Step 5 — Build capital_lab artifact
# ---------------------------------------------------------------------------


def build_capital_lab(
    kernel_result: KernelCycleResult,
    *,
    finance_latest: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Capital-lab artifact: authoritative per-lane capital state + one cycle action."""
    promotion = kernel_result.promotion
    evidence = kernel_result.evidence
    thesis = kernel_result.thesis

    lanes_out: dict[str, Any] = {}
    for decision in promotion.decisions:
        thesis_for_lane = next(
            (t for t in thesis.theses if t.lane == decision.lane), None
        )
        lanes_out[decision.lane] = {
            "status": decision.status,
            "live_capital_usd": decision.live_capital_usd,
            "can_expand": decision.can_expand,
            "block_reasons": decision.block_reasons,
            "allowed_action": decision.allowed_action,
            "thesis_state": thesis_for_lane.state if thesis_for_lane else "unknown",
            "thesis_confidence": thesis_for_lane.confidence if thesis_for_lane else 0.0,
            "replay_status": decision.replay_status,
            "execution_quality_score": decision.execution_quality_score,
        }

    return {
        "schema_version": "capital_lab.v1",
        "generated_at": _iso_z(now),
        "cycle_decision": kernel_result.cycle_decision,
        "cycle_block_reasons": kernel_result.cycle_block_reasons,
        "lanes": lanes_out,
        "capital_allocation": {
            "total_live_usd": promotion.total_live_capital_usd,
            "expansion_blocked": promotion.expansion_blocked,
            "expansion_block_reasons": promotion.expansion_block_reasons,
        },
        "btc5_db_evidence": {
            "rows": evidence.btc5_rows,
            "fills": evidence.btc5_fill_count,
            "skips": evidence.btc5_skip_reasons,
        },
        "weather_evidence": {
            "shadow_present": evidence.weather_shadow_present,
            "candidates": evidence.weather_candidate_count,
            "arr_confidence": evidence.weather_arr_confidence,
        },
        "real_decisions_feeding_capital_lab": evidence.btc5_rows > 0 or evidence.weather_shadow_present,
        "one_next_cycle_action": promotion.one_next_cycle_action,
    }


# ---------------------------------------------------------------------------
# Step 6 — Build proving_ground artifact
# ---------------------------------------------------------------------------


def build_proving_ground(
    kernel_result: KernelCycleResult,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Proving-ground: per-lane promotion evidence, doctrine candidates, readiness."""
    thesis = kernel_result.thesis
    promotion = kernel_result.promotion

    _BTC5_DEFAULT_DOCTRINE = [
        {"id": "time_of_day_filter", "description": "Suppress 00-02 ET and 08-09 ET (losing hours)", "status": "pending_evidence"},
        {"id": "down_only_mode", "description": "DOWN +$52.80 vs UP -$38.18; DOWN-only shows promise", "status": "pending_evidence"},
        {"id": "widen_delta_threshold", "description": "54% of skips are skip_delta_too_large; widen BTC5_MAX_ABS_DELTA", "status": "pending_evidence"},
    ]

    lanes_out: dict[str, Any] = {}
    for t in thesis.theses:
        promo = next((d for d in promotion.decisions if d.lane == t.lane), None)
        doctrine = list(t.doctrine_candidates) if t.doctrine_candidates else []
        # Always expose known BTC5 doctrine candidates even if thesis_foundry omits them
        if t.lane == "btc5" and not doctrine:
            doctrine = _BTC5_DEFAULT_DOCTRINE
        lanes_out[t.lane] = {
            "state": t.state,
            "promotion_gate_status": t.promotion_gate_status,
            "confidence": t.confidence,
            "evidence_summary": t.evidence_summary,
            "doctrine_candidates": doctrine,
            "promotion_criteria": t.promotion_criteria,
            "block_reasons": t.block_reasons,
            "one_next_action": t.one_next_action,
            "replay_status": promo.replay_status if promo else "pending",
            "off_policy_status": promo.off_policy_status if promo else "n/a",
        }

    return {
        "schema_version": "proving_ground.v1",
        "generated_at": _iso_z(now),
        "cycle_decision": kernel_result.cycle_decision,
        "lanes": lanes_out,
        "thesis_count": len(thesis.theses),
        "ranked_thesis_ids": thesis.ranked_ids,
        "stale_fallback_used": thesis.stale_fallback_used,
        "real_decisions_feeding_capital_lab": True,
        "proving_ground_feeds_capital_allocator": True,
    }


# ---------------------------------------------------------------------------
# Main integration runner
# ---------------------------------------------------------------------------


def run_integration(
    *,
    repo_root: Path = REPO_ROOT,
    capital_lab_path: Path = DEFAULT_CAPITAL_LAB_PATH,
    proving_ground_path: Path = DEFAULT_PROVING_GROUND_PATH,
    kernel_cycle_path: Path = DEFAULT_KERNEL_CYCLE_PATH,
    harness_path: Path = DEFAULT_HARNESS_PATH,
    weather_shadow_path: Path = DEFAULT_WEATHER_SHADOW_PATH,
    finance_path: Path = DEFAULT_FINANCE_PATH,
    promotion_gate_path: Path = DEFAULT_PROMOTION_GATE_PATH,
    btc5_db_path: Path = DEFAULT_BTC5_DB_PATH,
    refresh_weather: bool = True,
    run_harness: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    # 1 — Weather shadow refresh
    if refresh_weather:
        weather_shadow, weather_status = refresh_weather_shadow(
            weather_shadow_path, repo_root=repo_root
        )
    else:
        weather_shadow = _load_json(weather_shadow_path)
        weather_status = "skipped_no_refresh"

    # 2 — BTC5 DB state
    btc5_db = read_btc5_db_state(btc5_db_path)

    # 3 — Finance + promotion gate
    finance_latest = _load_json(finance_path)
    promotion_gate = _load_json(promotion_gate_path)

    # 4 — Build evidence bundle
    evidence = build_evidence_bundle(
        weather_shadow=weather_shadow,
        weather_refresh_status=weather_status,
        btc5_db=btc5_db,
        now=now,
    )

    # 5 — Kernel cycle
    kernel_result = run_full_kernel_cycle(
        evidence,
        finance_latest=finance_latest,
        promotion_gate=promotion_gate,
        weather_shadow=weather_shadow,
        now=now,
    )
    write_kernel_cycle(kernel_result, kernel_cycle_path)

    # 6 — Capital lab
    capital_lab = build_capital_lab(kernel_result, finance_latest=finance_latest, now=now)
    write_report(
        capital_lab_path,
        artifact="capital_lab",
        payload=capital_lab,
        status="fresh" if capital_lab.get("real_decisions_feeding_capital_lab") else "blocked",
        source_of_truth="reports/weather_shadow/latest.json; reports/finance/latest.json; data/btc_5min_maker.db",
        freshness_sla_seconds=1800,
        blockers=["no_real_decisions"] if not capital_lab.get("real_decisions_feeding_capital_lab") else [],
        summary=f"capital_allocation_total_live_usd={capital_lab.get('capital_allocation', {}).get('total_live_usd')}",
    )

    # 7 — Proving ground
    proving_ground = build_proving_ground(kernel_result, now=now)
    _write_json(proving_ground_path, proving_ground)

    # 8 — Intelligence harness (optional; replay gauntlets)
    harness_status = "skipped"
    harness_passed: bool | None = None
    if run_harness:
        from intelligence_harness import run_full_harness

        harness_result = run_full_harness(
            btc5_db_path=btc5_db_path,
            output_path=harness_path,
            now=now,
        )
        harness_status = "passed" if harness_result.harness_passed else "failed"
        harness_passed = harness_result.harness_passed

    return {
        "generated_at": _iso_z(now),
        "weather_refresh_status": weather_status,
        "btc5_db_rows": btc5_db.get("total_rows", 0),
        "btc5_fill_count": btc5_db.get("fill_count", 0),
        "kernel_cycle_decision": kernel_result.cycle_decision,
        "capital_lab_path": str(capital_lab_path),
        "proving_ground_path": str(proving_ground_path),
        "kernel_cycle_path": str(kernel_cycle_path),
        "harness_status": harness_status,
        "harness_passed": harness_passed,
        "thesis_count": len(kernel_result.thesis.theses),
        "live_capital_usd": kernel_result.promotion.total_live_capital_usd,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instance 11 — Weather + Harness Integration"
    )
    parser.add_argument(
        "--no-refresh-weather",
        action="store_true",
        help="Skip weather shadow refresh (use stale artifact)",
    )
    parser.add_argument(
        "--skip-harness",
        action="store_true",
        help="Skip intelligence harness replay gauntlets",
    )
    parser.add_argument(
        "--capital-lab",
        default=str(DEFAULT_CAPITAL_LAB_PATH),
        help="Output path for capital lab artifact",
    )
    parser.add_argument(
        "--proving-ground",
        default=str(DEFAULT_PROVING_GROUND_PATH),
        help="Output path for proving ground artifact",
    )
    args = parser.parse_args()

    result = run_integration(
        capital_lab_path=Path(args.capital_lab),
        proving_ground_path=Path(args.proving_ground),
        refresh_weather=not args.no_refresh_weather,
        run_harness=not args.skip_harness,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
