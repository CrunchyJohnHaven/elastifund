#!/usr/bin/env python3
"""
Architecture Alpha Loop
=======================
Mines recent architecture decisions and produces a ranked constitution update.

Reads:
  reports/autoresearch/research_os/latest.json   — current research priorities
  reports/kernel/kernel_state.json               — current kernel state
  reports/autoresearch/thesis_candidates.json    — current thesis candidates

Writes:
  reports/architecture_alpha/latest.json         — ranked constitution candidates
  reports/architecture_alpha/history.jsonl       — append-only audit trail

Exit code is always 0 (non-fatal — constitution updates are advisory).

Usage
-----
    python3 scripts/run_architecture_alpha.py [--dry-run]

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.report_envelope import write_report

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

# Inputs
RESEARCH_OS_PATH = PROJECT_ROOT / "reports" / "autoresearch" / "research_os" / "latest.json"
KERNEL_STATE_PATH = PROJECT_ROOT / "reports" / "kernel" / "kernel_state.json"
THESIS_CANDIDATES_PATH = PROJECT_ROOT / "reports" / "autoresearch" / "thesis_candidates.json"

# Outputs
OUTPUT_DIR = PROJECT_ROOT / "reports" / "architecture_alpha"
OUTPUT_PATH = OUTPUT_DIR / "latest.json"
HISTORY_PATH = OUTPUT_DIR / "history.jsonl"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> tuple[dict[str, Any] | None, float]:
    """
    Load a JSON file.  Returns (parsed_dict, age_seconds).
    If the file is missing or malformed, returns (None, -1.0).
    Age is calculated from the 'generated_at' key if present; otherwise the
    file modification time is used.
    """
    if not path.exists():
        return None, -1.0

    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None, -1.0

    now = datetime.now(timezone.utc)
    age_seconds = -1.0

    # Try generated_at / run_at / updated_at keys first
    for ts_key in ("generated_at", "run_at", "updated_at"):
        ts_str = raw.get(ts_key, "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_seconds = (now - ts).total_seconds()
                break
            except ValueError:
                pass

    if age_seconds < 0:
        # Fall back to filesystem mtime
        try:
            mtime = path.stat().st_mtime
            age_seconds = now.timestamp() - mtime
        except OSError:
            age_seconds = -1.0

    return raw, age_seconds


def _next_cycle(history_path: Path) -> int:
    """Count existing history lines to derive the next cycle number."""
    if not history_path.exists():
        return 1
    try:
        lines = [line for line in history_path.read_text().splitlines() if line.strip()]
        return len(lines) + 1
    except OSError:
        return 1


# ---------------------------------------------------------------------------
# Candidate generators
# ---------------------------------------------------------------------------

def _make_candidate(
    candidate_id: str,
    candidate_type: str,
    description: str,
    rationale: str,
    estimated_impact_bps: int,
    confidence: float,
    status: str,
    source: str,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "type": candidate_type,
        "description": description,
        "rationale": rationale,
        "estimated_impact_bps": estimated_impact_bps,
        "confidence": round(confidence, 3),
        "status": status,
        "source": source,
    }


def _candidates_from_research_os(
    data: dict[str, Any] | None, age_seconds: float
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if data is None:
        return candidates

    # Detect high stale_fallback_rate anywhere in the research_os data.
    stale_rate = data.get("stale_fallback_rate", None)
    if stale_rate is None:
        # Try lane_summaries structure (autoresearch pattern)
        lane_summaries = data.get("lane_summaries", {})
        rates = []
        for lane_data in lane_summaries.values():
            if isinstance(lane_data, dict):
                r = lane_data.get("stale_fallback_rate", None)
                if r is not None:
                    rates.append(float(r))
        stale_rate = max(rates) if rates else None

    if stale_rate is not None and float(stale_rate) >= 0.3:
        candidates.append(_make_candidate(
            candidate_id="ros_add_evidence_source",
            candidate_type="module_addition",
            description="Add a new real-time evidence source to reduce stale fallback rate",
            rationale=(
                f"research_os reports stale_fallback_rate={stale_rate:.3f} (>=0.30). "
                "Adding a live evidence feed (e.g. Kalshi weather, intraday VIX) will "
                "reduce reliance on cached data and lower the stale fallback rate."
            ),
            estimated_impact_bps=12,
            confidence=0.65,
            status="proposed",
            source="research_os",
        ))

    # If the research_os artifact itself is stale (> 3 hours), flag a refresh.
    if age_seconds > 10800:
        candidates.append(_make_candidate(
            candidate_id="ros_artifact_refresh",
            candidate_type="routing_change",
            description="Trigger research_os regeneration — artifact is stale",
            rationale=(
                f"research_os latest.json is {age_seconds / 3600:.1f}h old. "
                "Stale research priorities corrupt candidate ranking downstream."
            ),
            estimated_impact_bps=5,
            confidence=0.80,
            status="proposed",
            source="research_os",
        ))

    return candidates


def _candidates_from_thesis(
    data: dict[str, Any] | None, age_seconds: float
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if data is None:
        return candidates

    # Normalise: thesis_candidates.json may be a list or a dict wrapping a list.
    items = data if isinstance(data, list) else data.get("theses", data.get("candidates", []))
    if not isinstance(items, list):
        items = []

    weather_entries = [
        item for item in items
        if isinstance(item, dict) and "weather" in str(item.get("id", "")).lower()
    ]

    if not weather_entries:
        # No weather lane present at all — propose refresh.
        candidates.append(_make_candidate(
            candidate_id="thesis_weather_lane_refresh",
            candidate_type="module_addition",
            description="Refresh weather lane — no weather theses found in thesis_candidates",
            rationale=(
                "thesis_candidates contains no weather-tagged entries. "
                "The Kalshi weather strategy lane (NWS divergence signal) "
                "should be generating candidates. Refresh the weather feed integration."
            ),
            estimated_impact_bps=8,
            confidence=0.55,
            status="proposed",
            source="thesis_candidates",
        ))
    else:
        # Check if the weather entries are stale.
        for entry in weather_entries:
            ts_str = entry.get("updated_at", entry.get("generated_at", ""))
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    entry_age = (datetime.now(timezone.utc) - ts).total_seconds()
                    if entry_age > 7200:
                        candidates.append(_make_candidate(
                            candidate_id=f"thesis_weather_stale_{entry.get('id', 'unknown')}",
                            candidate_type="routing_change",
                            description="Weather lane thesis is stale — trigger regeneration",
                            rationale=(
                                f"Weather thesis '{entry.get('id')}' is "
                                f"{entry_age / 3600:.1f}h old. "
                                "Stale theses degrade ranking quality."
                            ),
                            estimated_impact_bps=6,
                            confidence=0.60,
                            status="proposed",
                            source="thesis_candidates",
                        ))
                        break
                except ValueError:
                    pass

    return candidates


def _candidates_from_kernel(
    data: dict[str, Any] | None, age_seconds: float
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if data is None:
        return candidates

    decision = data.get("cycle_decision", "")
    notes = data.get("cycle_notes", [])

    if decision == "BLOCKED":
        evidence_status = data.get("evidence", {}).get("status", "")
        candidates.append(_make_candidate(
            candidate_id="kernel_unblock_evidence_generation",
            candidate_type="module_addition",
            description="Unblock evidence generation — kernel is in BLOCKED state",
            rationale=(
                f"kernel_state shows cycle_decision=BLOCKED (evidence.status={evidence_status}). "
                "Notes: " + "; ".join(str(n) for n in notes[:3]) + ". "
                "Likely cause: evidence bundle artifact missing or expired. "
                "Add a fallback evidence generator or extend freshness TTL."
            ),
            estimated_impact_bps=20,
            confidence=0.75,
            status="proposed",
            source="kernel_state",
        ))

    # Check concentration incidents.
    metrics = data.get("metrics", {})
    concentration = int(metrics.get("concentration_incidents_7d", 0))
    if concentration >= 2:
        candidates.append(_make_candidate(
            candidate_id="kernel_add_concentration_kill_rule",
            candidate_type="kill_rule",
            description="Add/tighten concentration kill rule — 7-day incidents elevated",
            rationale=(
                f"kernel_state reports {concentration} concentration incidents in 7 days. "
                "Add or tighten a kill rule: block promotion when a single asset "
                "exceeds 50% of portfolio weight."
            ),
            estimated_impact_bps=15,
            confidence=0.80,
            status="proposed",
            source="kernel_state",
        ))

    # Check execution quality.
    eq_score = float(metrics.get("execution_quality_score", 1.0))
    if eq_score < 0.5:
        candidates.append(_make_candidate(
            candidate_id="kernel_execution_quality_parameter_change",
            candidate_type="parameter_change",
            description="Lower fill rate threshold or widen delta guard — execution quality low",
            rationale=(
                f"execution_quality_score={eq_score:.3f} (< 0.50). "
                "Most skips are skip_delta_too_large. "
                "Widen BTC5_MAX_ABS_DELTA from current 0.0030 to 0.0050."
            ),
            estimated_impact_bps=25,
            confidence=0.70,
            status="proposed",
            source="kernel_state",
        ))

    return candidates


def _default_maintenance_candidate() -> dict[str, Any]:
    return _make_candidate(
        candidate_id="maintain_current_constitution",
        candidate_type="parameter_change",
        description="Maintain current system constitution — no structural changes indicated",
        rationale=(
            "No blockers, no stale fallbacks, no elevated concentration. "
            "Continue current parameter set. Re-evaluate after next 7-day window."
        ),
        estimated_impact_bps=0,
        confidence=0.90,
        status="proposed",
        source="kernel_state",
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_architecture_alpha(dry_run: bool) -> int:
    print("[architecture_alpha] starting run")

    # Load inputs
    research_os_data, research_os_age = _load_json(RESEARCH_OS_PATH)
    kernel_data, kernel_age = _load_json(KERNEL_STATE_PATH)
    thesis_data, thesis_age = _load_json(THESIS_CANDIDATES_PATH)

    source_freshness: dict[str, Any] = {
        "research_os": {
            "path": str(RESEARCH_OS_PATH),
            "found": research_os_data is not None,
            "age_seconds": round(research_os_age, 1),
        },
        "kernel_state": {
            "path": str(KERNEL_STATE_PATH),
            "found": kernel_data is not None,
            "age_seconds": round(kernel_age, 1),
        },
        "thesis_candidates": {
            "path": str(THESIS_CANDIDATES_PATH),
            "found": thesis_data is not None,
            "age_seconds": round(thesis_age, 1),
        },
    }

    print("[architecture_alpha] source freshness:")
    for src, info in source_freshness.items():
        found_str = "found" if info["found"] else "MISSING"
        age_str = f"{info['age_seconds']:.0f}s" if info["age_seconds"] >= 0 else "n/a"
        print(f"  {src}: {found_str}, age={age_str}")

    # Generate candidates
    constitution_candidates: list[dict[str, Any]] = []
    constitution_candidates.extend(_candidates_from_research_os(research_os_data, research_os_age))
    constitution_candidates.extend(_candidates_from_thesis(thesis_data, thesis_age))
    constitution_candidates.extend(_candidates_from_kernel(kernel_data, kernel_age))

    # If no signal-driven candidates, emit maintenance candidate
    if not constitution_candidates:
        constitution_candidates.append(_default_maintenance_candidate())

    # Sort by estimated_impact_bps descending, then confidence descending
    constitution_candidates.sort(
        key=lambda c: (c["estimated_impact_bps"], c["confidence"]), reverse=True
    )

    # System design candidates: structural (module_addition and kill_rule types)
    system_design_candidates = [
        c for c in constitution_candidates
        if c["type"] in ("module_addition", "kill_rule")
    ]

    cycle_number = _next_cycle(HISTORY_PATH)

    output: dict[str, Any] = {
        "artifact": "architecture_alpha_v1",
        "generated_at": _utc_now(),
        "cycle": cycle_number,
        "constitution_candidates": constitution_candidates,
        "system_design_candidates": system_design_candidates,
        "retained_outputs": [],
        "source_freshness": source_freshness,
    }

    if dry_run:
        print("[architecture_alpha] dry-run mode — not writing output files")
        print(json.dumps(output, indent=2, default=str))
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write latest.json
    write_report(
        OUTPUT_PATH,
        artifact="architecture_alpha_v1",
        payload=output,
        status="fresh" if constitution_candidates else "blocked",
        source_of_truth=(
            "reports/autoresearch/research_os/latest.json; reports/kernel/kernel_state.json; "
            "reports/autoresearch/thesis_candidates.json"
        ),
        freshness_sla_seconds=7200,
        blockers=[] if constitution_candidates else ["no_constitution_candidates"],
        summary=(
            f"cycle={cycle_number} candidates={len(constitution_candidates)} "
            f"system_design={len(system_design_candidates)}"
        ),
    )
    print(f"[architecture_alpha] latest.json written to {OUTPUT_PATH}")

    # Append to history.jsonl
    with HISTORY_PATH.open("a") as fh:
        fh.write(json.dumps(output, default=str) + "\n")
    print(f"[architecture_alpha] history entry appended to {HISTORY_PATH}")

    # Summary
    print(
        f"[architecture_alpha] cycle={cycle_number}, "
        f"{len(constitution_candidates)} constitution candidate(s), "
        f"{len(system_design_candidates)} system_design candidate(s)"
    )
    for c in constitution_candidates:
        print(
            f"  [{c['type']}] {c['candidate_id']}: {c['estimated_impact_bps']}bps "
            f"(confidence={c['confidence']:.2f})"
        )

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Architecture Alpha Loop — mines architecture decisions into constitution candidates"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print output to stdout instead of writing files",
    )
    args = parser.parse_args()
    return run_architecture_alpha(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
