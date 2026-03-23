#!/usr/bin/env python3
"""
Self-Improvement Kernel Cycle Orchestrator
==========================================
Ties together Evidence → Thesis → Promotion → Learning.

For each stage the orchestrator checks whether the current artifact is
within its TTL.  If not, it invokes the responsible generator script via
subprocess and updates the bundle descriptor.  At the end it calls
cycle.compute_cycle_decision() and saves kernel state.

Bundle TTLs:
  Evidence   300s  → scripts/run_sensorium.py
  Thesis     600s  → python3 -m bot.thesis_foundry
  Promotion 1800s  → assess reports/promotion_bundle.json (no generator)
  Learning  3600s  → scripts/run_research_os.py

Usage:
  python3 scripts/run_kernel_cycle.py               # one cycle
  python3 scripts/run_kernel_cycle.py --dry-run     # assess only, no subprocesses
  python3 scripts/run_kernel_cycle.py --daemon --interval-seconds 300

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kernel_contract import (  # noqa: E402
    BundleDescriptor,
    BundleStatus,
    KernelCycle,
    read_kernel_state,
    read_bundle_artifact,
    utc_now,
)

log = logging.getLogger("kernel_cycle")

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PROMOTION_BUNDLE_PATH = PROJECT_ROOT / "reports" / "promotion_bundle.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _artifact_age(path: Path) -> float:
    """Return age in seconds of the artifact at *path*, or -1 if absent/unparseable."""
    payload = _read_json_optional(path)
    if payload is None:
        return -1.0
    now = datetime.now(timezone.utc)
    for key in ("generated_at", "timestamp", "as_of"):
        ts = payload.get(key)
        if not ts:
            continue
        try:
            generated = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return (now - generated).total_seconds()
        except Exception:
            continue
    return -1.0


def _run_subprocess(cmd: list[str], stage: str, dry_run: bool) -> tuple[bool, str]:
    """
    Execute *cmd* in a subprocess.  Returns (success, error_message).
    In dry-run mode the command is logged but not executed.
    """
    cmd_str = " ".join(cmd)
    if dry_run:
        log.info("[dry-run] would execute: %s", cmd_str)
        return True, ""

    log.info("running: %s", cmd_str)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=300,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "")[:400].strip()
            log.warning("[%s] subprocess exited %d: %s", stage, result.returncode, err)
            return False, err
        out = (result.stdout or "").strip()
        if out:
            log.info("[%s] %s", stage, out[:300])
        return True, ""
    except subprocess.TimeoutExpired:
        msg = f"{stage} subprocess timed out after 300s"
        log.error(msg)
        return False, msg
    except Exception as exc:
        msg = f"{stage} subprocess error: {exc}"
        log.error(msg)
        return False, msg


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------


def _handle_evidence(cycle: KernelCycle, dry_run: bool) -> None:
    """Refresh the evidence bundle if stale or missing."""
    bundle = cycle.evidence
    artifact_path = PROJECT_ROOT / bundle.artifact_path

    age = _artifact_age(artifact_path)
    bundle.age_seconds = age

    if age >= 0 and age < bundle.freshness_ttl_seconds:
        bundle.status = BundleStatus.FRESH
        log.info("[evidence] fresh (age=%.0fs)", age)
        return

    reason = "age=%.0fs > TTL=%ds" % (age, bundle.freshness_ttl_seconds) if age >= 0 else "artifact absent"
    log.info("[evidence] %s — running sensorium", reason)

    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "run_sensorium.py")]
    ok, err = _run_subprocess(cmd, "evidence", dry_run)

    if dry_run:
        # In dry-run, treat as would-be-fresh so downstream stages can assess
        bundle.status = BundleStatus.STALE
        return

    if ok:
        new_age = _artifact_age(artifact_path)
        payload = _read_json_optional(artifact_path)
        source_count = payload.get("source_count", 0) if payload else 0
        observations = payload.get("observations", []) if payload else []
        obs_count = len(observations) if isinstance(observations, list) else 0
        ts = payload.get("generated_at", _iso_now()) if payload else _iso_now()
        bundle.mark_fresh(ts, source_count, obs_count)
        bundle.age_seconds = max(0.0, new_age)
        log.info("[evidence] refreshed — %d observations from %d sources", obs_count, source_count)
    else:
        bundle.mark_error(err)
        log.error("[evidence] sensorium failed: %s", err)


def _handle_thesis(cycle: KernelCycle, dry_run: bool) -> None:
    """Refresh the thesis bundle only when evidence is actionable."""
    bundle = cycle.thesis

    # thesis_foundry writes here; the kernel contract names a canonical alias
    THESIS_CANDIDATES_PATH = PROJECT_ROOT / "reports" / "autoresearch" / "thesis_candidates.json"
    THESIS_BUNDLE_PATH = PROJECT_ROOT / bundle.artifact_path  # reports/thesis_bundle.json

    # Use the foundry output path for freshness; fall back to kernel alias
    check_path = THESIS_CANDIDATES_PATH if THESIS_CANDIDATES_PATH.exists() else THESIS_BUNDLE_PATH

    if not cycle.evidence.is_actionable() and not dry_run:
        bundle.status = BundleStatus.BLOCKED
        log.info("[thesis] BLOCKED — evidence not actionable (%s)", cycle.evidence.status)
        return

    age = _artifact_age(check_path)
    bundle.age_seconds = age

    if age >= 0 and age < bundle.freshness_ttl_seconds:
        bundle.status = BundleStatus.FRESH
        if bundle.item_count == 0:
            payload = _read_json_optional(check_path)
            if payload:
                candidates = payload.get("candidates", [])
                bundle.item_count = len(candidates) if isinstance(candidates, list) else 0
                sources = payload.get("sources", [])
                bundle.source_count = len(sources) if isinstance(sources, list) else bundle.source_count
                bundle.generated_at = payload.get("generated_at", bundle.generated_at) or bundle.generated_at
        log.info("[thesis] fresh (age=%.0fs)", age)
        return

    reason = "age=%.0fs > TTL=%ds" % (age, bundle.freshness_ttl_seconds) if age >= 0 else "artifact absent"
    log.info("[thesis] %s — running thesis_foundry", reason)

    cmd = [sys.executable, "-m", "bot.thesis_foundry"]
    ok, err = _run_subprocess(cmd, "thesis", dry_run)

    if dry_run:
        bundle.status = BundleStatus.STALE
        return

    if ok:
        new_age = _artifact_age(THESIS_CANDIDATES_PATH)
        payload = _read_json_optional(THESIS_CANDIDATES_PATH)
        candidates = payload.get("candidates", []) if payload else []
        if not isinstance(candidates, list):
            candidates = []
        ts = payload.get("generated_at", _iso_now()) if payload else _iso_now()
        sources = payload.get("sources", []) if payload else []
        bundle.mark_fresh(ts, source_count=len(sources) if isinstance(sources, list) else 2,
                          item_count=len(candidates))
        bundle.age_seconds = max(0.0, new_age)
        # Mirror to canonical thesis_bundle.json for kernel contract alignment
        if payload and THESIS_CANDIDATES_PATH.exists():
            THESIS_BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
            THESIS_BUNDLE_PATH.write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
        log.info("[thesis] refreshed — %d candidates", len(candidates))
    else:
        bundle.mark_error(err)
        log.error("[thesis] thesis_foundry failed: %s", err)


def _handle_promotion(cycle: KernelCycle, dry_run: bool) -> None:  # noqa: ARG001
    """
    Assess promotion bundle status.  No generator script exists for this
    stage — the promotion bundle is assembled externally (e.g. by the
    supervisor or a dedicated promotion writer).  We just read whatever
    is on disk and label it FRESH / STALE / EMPTY accordingly.
    """
    bundle = cycle.promotion
    age = _artifact_age(PROMOTION_BUNDLE_PATH)
    bundle.age_seconds = age

    if age < 0:
        bundle.status = BundleStatus.EMPTY
        log.info("[promotion] artifact absent — EMPTY")
        return

    payload = _read_json_optional(PROMOTION_BUNDLE_PATH)
    ts = None
    if payload:
        for key in ("generated_at", "timestamp"):
            ts = payload.get(key)
            if ts:
                break

    if age < bundle.freshness_ttl_seconds:
        item_count = len(payload.get("promotions", [])) if payload else 0
        bundle.mark_fresh(ts or _iso_now(), source_count=1, item_count=item_count)
        log.info("[promotion] fresh (age=%.0fs, %d promotions)", age, item_count)
    else:
        bundle.status = BundleStatus.STALE
        log.info("[promotion] stale (age=%.0fs > TTL=%ds)", age, bundle.freshness_ttl_seconds)


def _handle_learning(cycle: KernelCycle, dry_run: bool) -> None:
    """Refresh the learning bundle (research_os) when stale."""
    bundle = cycle.learning
    LEARNING_BUNDLE_PATH = PROJECT_ROOT / bundle.artifact_path  # reports/learning_bundle.json

    # research_os writes here; kernel contract alias mirrors it
    RESEARCH_OS_PATH = PROJECT_ROOT / "reports" / "autoresearch" / "research_os" / "latest.json"

    check_path = RESEARCH_OS_PATH if RESEARCH_OS_PATH.exists() else LEARNING_BUNDLE_PATH
    age = _artifact_age(check_path)
    bundle.age_seconds = age

    if age >= 0 and age < bundle.freshness_ttl_seconds:
        bundle.status = BundleStatus.FRESH
        payload = _read_json_optional(check_path)
        ts = payload.get("generated_at", _iso_now()) if payload else _iso_now()
        if bundle.generated_at != ts:
            bundle.generated_at = ts
        log.info("[learning] fresh (age=%.0fs)", age)
        return

    reason = "age=%.0fs > TTL=%ds" % (age, bundle.freshness_ttl_seconds) if age >= 0 else "artifact absent"
    log.info("[learning] %s — running research_os", reason)

    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "run_research_os.py")]
    ok, err = _run_subprocess(cmd, "learning", dry_run)

    if dry_run:
        bundle.status = BundleStatus.STALE
        return

    if ok:
        new_age = _artifact_age(RESEARCH_OS_PATH)
        payload = _read_json_optional(RESEARCH_OS_PATH)
        ts = payload.get("generated_at", _iso_now()) if payload else _iso_now()
        oe = payload.get("opportunity_exchange", []) if payload else []
        item_count = len(oe) if isinstance(oe, list) else 0
        bundle.mark_fresh(ts, source_count=4, item_count=item_count)
        bundle.age_seconds = max(0.0, new_age)
        # Mirror to canonical learning_bundle.json for kernel contract alignment
        if payload:
            LEARNING_BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
            LEARNING_BUNDLE_PATH.write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
        log.info("[learning] refreshed — %d opportunity_exchange items", item_count)
    else:
        bundle.mark_error(err)
        log.error("[learning] research_os failed: %s", err)


# ---------------------------------------------------------------------------
# Cycle runner
# ---------------------------------------------------------------------------


def run_one_cycle(dry_run: bool = False) -> KernelCycle:
    cycle = read_kernel_state()
    cycle.cycle_id = _iso_now()
    cycle.generated_at = _iso_now()
    cycle.cycle_notes = []

    log.info("=== kernel cycle %s (dry_run=%s) ===", cycle.cycle_id, dry_run)

    # Stage 1: Evidence
    _handle_evidence(cycle, dry_run)

    # Stage 2: Thesis (requires fresh evidence)
    _handle_thesis(cycle, dry_run)

    # Stage 3: Promotion (assess only)
    _handle_promotion(cycle, dry_run)

    # Stage 4: Learning (runs opportunistically regardless of other stages)
    _handle_learning(cycle, dry_run)

    # Derive cycle decision
    decision = cycle.compute_cycle_decision()

    # Status summary
    statuses = {b.name: b.status.value for b in cycle.all_bundles()}
    log.info(
        "decision=%s  evidence=%s thesis=%s promotion=%s learning=%s",
        decision,
        statuses["evidence"],
        statuses["thesis"],
        statuses["promotion"],
        statuses["learning"],
    )

    if not dry_run:
        cycle.save()
        cycle.append_cycle_log()

    return cycle


def _compact_status_line(cycle: KernelCycle) -> str:
    b = {b.name: b for b in cycle.all_bundles()}

    def fmt(bd: BundleDescriptor) -> str:
        age = f"{bd.age_seconds:.0f}s" if bd.age_seconds >= 0 else "?"
        return f"{bd.status.value}({age})"

    return (
        f"[kernel] {cycle.cycle_id[:19]}  "
        f"decision={cycle.cycle_decision}  "
        f"E:{fmt(b['evidence'])}  "
        f"T:{fmt(b['thesis'])}  "
        f"P:{fmt(b['promotion'])}  "
        f"L:{fmt(b['learning'])}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Elastifund self-improvement kernel cycle orchestrator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Assess stage freshness without invoking generator scripts or writing state")
    parser.add_argument("--daemon", action="store_true",
                        help="Run continuously until interrupted")
    parser.add_argument("--interval-seconds", type=int, default=300,
                        help="Seconds between daemon cycles (default: 300)")
    args = parser.parse_args()

    if not args.daemon:
        cycle = run_one_cycle(dry_run=args.dry_run)
        print(_compact_status_line(cycle))
        return 0

    # Daemon loop
    log.info("daemon mode: interval=%ds  (ctrl-c to stop)", args.interval_seconds)
    cycle_count = 0
    try:
        while True:
            try:
                cycle = run_one_cycle(dry_run=args.dry_run)
                cycle_count += 1
                print(_compact_status_line(cycle))
            except Exception as exc:
                log.error("cycle %d failed: %s", cycle_count + 1, exc, exc_info=True)
            log.info("sleeping %ds before next cycle", args.interval_seconds)
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        log.info("daemon interrupted after %d cycles", cycle_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
