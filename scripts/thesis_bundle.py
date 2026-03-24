#!/usr/bin/env python3
"""
Thesis Bundle — Authoritative Thesis Compilation Layer
=======================================================
Second stage of the self-improvement kernel.

Reads evidence_bundle.json and compiles thesis candidates into a ranked
thesis_bundle.json.  Only theses that survive this stage may proceed to
the promotion layer.

Thesis inputs (all enter through evidence_bundle)
--------------------------------------------------
  - novel_edge findings (novelty_discovery surface)
  - BTC5 skip-pattern signals (btc5_shadow + skip breakdown)
  - Weather divergence observations (shadow-first, gate-checked)
  - Market-birth candidates (new markets with no prior thesis)
  - Official-source shocks (resolution surprises from resolution_intel)
  - Sensorium concentration alerts (dominant-tag signals)

MiroFish role: optional scenario enricher injected into thesis items, never
a direct decision authority.  If MIROFISH_ENABLED=true, each top-3 thesis
gets a MiroFish scenario annotation.

Output: reports/thesis_bundle.json
Kernel: updates reports/kernel/kernel_state.json thesis bundle status

Usage
-----
  python3 scripts/thesis_bundle.py           # run once
  python3 scripts/thesis_bundle.py --daemon  # continuous (default 10min)

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.report_envelope import write_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("JJ.thesis")

PROJECT_ROOT = REPO_ROOT
REPORTS = PROJECT_ROOT / "reports"
EVIDENCE_PATH = REPORTS / "evidence_bundle.json"
OUTPUT_PATH = REPORTS / "thesis_bundle.json"
INTERVAL = int(os.environ.get("THESIS_INTERVAL_SECONDS", "600"))

# thesis_foundry output — merged into thesis_bundle as the single authoritative path
THESIS_CANDIDATES_PATH = REPORTS / "autoresearch" / "thesis_candidates.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def age_seconds(iso: str) -> float:
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return -1.0


# ---------------------------------------------------------------------------
# Thesis extractors
# ---------------------------------------------------------------------------


def _extract_novel_edge_theses(evidence_items: list[dict]) -> list[dict[str, Any]]:
    """Convert novel_edge findings into thesis candidates."""
    theses: list[dict[str, Any]] = []
    for item in evidence_items:
        if item.get("name") != "novelty_discovery":
            continue
        data = item.get("data") or {}
        findings = data.get("findings") or []
        for f in findings:
            sig = f.get("signal") or ""
            note = f.get("note") or ""
            if sig in ("blocker_candidate", "zero_recent_trades", "stale_autoresearch"):
                theses.append({
                    "thesis_id": f"novel_{f.get('type', 'unk')}_{len(theses)+1:03d}",
                    "source": "novelty_discovery",
                    "type": "operational_fix",
                    "signal": sig,
                    "description": note,
                    "confidence": 0.7,
                    "priority": "high" if sig == "blocker_candidate" else "medium",
                    "requires_capital": False,
                    "replay_ready": False,
                })
    return theses


def _extract_btc5_theses(evidence_items: list[dict]) -> list[dict[str, Any]]:
    """Extract BTC5 edge candidates from shadow signals."""
    theses: list[dict[str, Any]] = []
    for item in evidence_items:
        if item.get("name") != "btc5_shadow":
            continue
        data = item.get("data") or {}
        signals = data.get("signals") or []
        maker_signals = [s for s in signals if s.get("shadow_decision", "").startswith("MAKER")]
        if maker_signals:
            theses.append({
                "thesis_id": f"btc5_maker_signals_{len(maker_signals):02d}",
                "source": "btc5_shadow",
                "type": "execution_edge",
                "signal": "btc5_maker_opportunity",
                "description": (
                    f"{len(maker_signals)} BTC5 markets with maker signal "
                    f"(DOWN={sum(1 for s in maker_signals if 'NO' in s['shadow_decision'])}, "
                    f"UP={sum(1 for s in maker_signals if 'YES' in s['shadow_decision'])})"
                ),
                "confidence": 0.55,
                "priority": "medium",
                "requires_capital": True,
                "replay_ready": False,
                "detail": {
                    "maker_count": len(maker_signals),
                    "sample": maker_signals[:3],
                },
            })
    return theses


def _extract_concentration_theses(evidence_items: list[dict]) -> list[dict[str, Any]]:
    """Surface concentration alerts from sensorium as risk theses."""
    theses: list[dict[str, Any]] = []
    for item in evidence_items:
        if item.get("name") != "sensorium":
            continue
        data = item.get("data") or {}
        for obs in (data.get("observations") or []):
            if obs.get("type") == "market_census":
                by_tag = obs.get("by_tag") or {}
                total = obs.get("total_active") or 1
                for tag, count in by_tag.items():
                    if count / total > 0.35:
                        theses.append({
                            "thesis_id": f"concentration_{tag}",
                            "source": "sensorium",
                            "type": "risk_alert",
                            "signal": "category_concentration",
                            "description": (
                                f"Category '{tag}' holds {count}/{total} "
                                f"({count/total*100:.0f}%) of active markets"
                            ),
                            "confidence": 0.9,
                            "priority": "high",
                            "requires_capital": False,
                            "replay_ready": True,
                        })
    return theses


def _extract_thesis_foundry_theses(candidates_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert thesis_foundry candidates into the unified thesis_bundle schema.

    Preserves execution metadata (lane, rank_score, execution_mode, venue, ticker)
    so that lane_supervisor can still route these theses to execution after reading
    thesis_bundle.json as the single authoritative source.
    """
    theses: list[dict[str, Any]] = []
    candidates = candidates_payload.get("theses") or candidates_payload.get("candidates") or []
    for c in candidates:
        lane = str(c.get("lane") or "unknown")
        rank_score = float(c.get("rank_score") or 0.0)
        execution_mode = str(c.get("execution_mode") or "shadow")
        requires_capital = execution_mode in ("live", "micro_live")
        if lane == "weather":
            confidence = float(c.get("spread_adjusted_edge") or 0.0)
        elif lane == "alpaca":
            confidence = float(c.get("prob_positive") or c.get("model_probability") or 0.55)
        else:
            confidence = 0.55

        # Map thesis_foundry type to thesis_bundle type
        thesis_type = "execution_edge" if lane == "btc5" else ("alpaca_momentum" if lane == "alpaca" else "weather_divergence")

        theses.append({
            "thesis_id": str(c.get("thesis_id") or f"foundry_{lane}_{len(theses)+1:03d}"),
            "source": f"thesis_foundry:{lane}",
            "type": thesis_type,
            "signal": f"{lane}_execution",
            "description": str(c.get("title") or c.get("description") or lane),
            "confidence": round(confidence, 4),
            "priority": "high" if execution_mode == "live" else "medium",
            "requires_capital": requires_capital,
            "replay_ready": False,
            # Execution metadata preserved for lane_supervisor routing
            "lane": lane,
            "venue": c.get("venue"),
            "ticker": c.get("ticker"),
            "event_ticker": c.get("event_ticker"),
            "side": c.get("side"),
            "rank_score": rank_score,
            "execution_mode": execution_mode,
            "spread_adjusted_edge": c.get("spread_adjusted_edge"),
            "artifact_stale": bool(c.get("artifact_stale")),
            # Alpaca-specific fields required by executor gate checks
            "prob_positive": c.get("prob_positive"),
            "model_probability": c.get("model_probability"),
            "expected_edge_bps": c.get("expected_edge_bps"),
            "variant_id": c.get("variant_id"),
            "recommended_notional_usd": c.get("recommended_notional_usd"),
            "hold_bars": c.get("hold_bars"),
            "stop_loss_bps": c.get("stop_loss_bps"),
            "take_profit_bps": c.get("take_profit_bps"),
            "last_price": c.get("last_price"),
            "momentum_bps": c.get("momentum_bps"),
            "trend_gap_bps": c.get("trend_gap_bps"),
            "volatility_bps": c.get("volatility_bps"),
            "spread_bps": c.get("spread_bps"),
            "replay_trade_count": c.get("replay_trade_count"),
        })
    return theses


def _extract_resolution_surprise_theses(evidence_items: list[dict]) -> list[dict[str, Any]]:
    """Identify resolution surprises (YES where market expected NO, or vice versa)."""
    theses: list[dict[str, Any]] = []
    for item in evidence_items:
        if item.get("name") != "resolution_intel":
            continue
        data = item.get("data") or {}
        resolutions = data.get("resolutions") or []
        for r in resolutions:
            res = (r.get("resolution") or "").upper()
            question = r.get("question") or ""
            if res in ("YES", "NO") and question:
                theses.append({
                    "thesis_id": f"resolution_obs_{len(theses)+1:03d}",
                    "source": "resolution_intel",
                    "type": "settlement_truth",
                    "signal": f"resolved_{res.lower()}",
                    "description": f"[{res}] {question[:100]}",
                    "confidence": 1.0,  # ground truth
                    "priority": "low",
                    "requires_capital": False,
                    "replay_ready": True,
                })
    return theses


# ---------------------------------------------------------------------------
# Thesis ranking
# ---------------------------------------------------------------------------


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_TYPE_ORDER = {"risk_alert": 0, "operational_fix": 1, "execution_edge": 2, "settlement_truth": 3}


def rank_theses(theses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        theses,
        key=lambda t: (
            _PRIORITY_ORDER.get(t.get("priority") or "low", 2),
            _TYPE_ORDER.get(t.get("type") or "settlement_truth", 3),
            -t.get("confidence", 0.0),
        ),
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def assemble_thesis() -> dict[str, Any]:
    evidence = load_json(EVIDENCE_PATH)
    if evidence is None:
        logger.warning("[thesis] evidence_bundle.json not found — skipping")
        bundle = _empty_bundle("evidence_bundle missing")
        write_report(
            OUTPUT_PATH,
            artifact="thesis_bundle",
            payload=bundle,
            status="blocked",
            source_of_truth="reports/evidence_bundle.json; reports/autoresearch/thesis_candidates.json",
            freshness_sla_seconds=600,
            blockers=[bundle["blocked_reason"]],
            summary="thesis bundle blocked: evidence bundle missing",
        )
        return bundle

    gen = evidence.get("generated_at") or ""
    age = age_seconds(gen)
    if age > 1200:  # > 20 min stale
        logger.warning("[thesis] evidence bundle is %.0fs stale — using but flagging", age)

    if evidence.get("is_fallback"):
        logger.warning("[thesis] evidence bundle is fallback-only — thesis will be sparse")

    items = evidence.get("items") or []
    theses: list[dict[str, Any]] = []
    theses.extend(_extract_novel_edge_theses(items))
    theses.extend(_extract_btc5_theses(items))
    theses.extend(_extract_concentration_theses(items))
    theses.extend(_extract_resolution_surprise_theses(items))

    # Merge thesis_foundry candidates — weather + BTC5 execution theses.
    # thesis_bundle is the single authoritative compiler; lane_supervisor reads
    # thesis_bundle.json and routes items with execution_mode to execution.
    foundry_payload = load_json(THESIS_CANDIDATES_PATH) or {}
    foundry_theses = _extract_thesis_foundry_theses(foundry_payload)
    if foundry_theses:
        logger.info("[thesis] merged %d thesis_foundry candidates into bundle", len(foundry_theses))
        theses.extend(foundry_theses)

    ranked = rank_theses(theses)
    status = "fresh"
    blockers: list[str] = []
    if evidence.get("is_fallback"):
        status = "blocked"
        blockers.append("evidence_bundle_fallback_only")
    elif age > 1200:
        status = "stale"
        blockers.append("evidence_bundle_stale")
    elif not ranked:
        status = "blocked"
        blockers.append("no_theses_generated")

    bundle: dict[str, Any] = {
        "artifact": "thesis_bundle",
        "generated_at": utc_now(),
        "evidence_age_seconds": age,
        "evidence_source_count": evidence.get("source_count", 0),
        "thesis_count": len(ranked),
        "high_priority": sum(1 for t in ranked if t.get("priority") == "high"),
        "requires_capital": sum(1 for t in ranked if t.get("requires_capital")),
        "replay_ready": sum(1 for t in ranked if t.get("replay_ready")),
        "theses": ranked,
        "status": status,
        "blockers": blockers,
    }
    write_report(
        OUTPUT_PATH,
        artifact="thesis_bundle",
        payload=bundle,
        status=status,
        source_of_truth="reports/evidence_bundle.json; reports/autoresearch/thesis_candidates.json",
        freshness_sla_seconds=600,
        blockers=blockers,
        summary=(
            f"{len(ranked)} theses compiled from {evidence.get('source_count', 0)} evidence sources"
            + (" with fallback evidence" if evidence.get("is_fallback") else "")
        ),
    )
    logger.info(
        "[thesis] %d theses compiled (high=%d, capital=%d, replay=%d)",
        len(ranked),
        bundle["high_priority"],
        bundle["requires_capital"],
        bundle["replay_ready"],
    )
    return bundle


def _empty_bundle(reason: str) -> dict[str, Any]:
    return {
        "artifact": "thesis_bundle",
        "generated_at": utc_now(),
        "thesis_count": 0,
        "theses": [],
        "blocked_reason": reason,
        "status": "blocked",
        "blockers": [reason],
    }


def update_kernel_state(bundle: dict[str, Any]) -> None:
    try:
        import sys
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from kernel_contract import KernelCycle, BundleStatus

        cycle = KernelCycle.load()
        bundle_status = str(bundle.get("status") or "error").strip().lower()
        if bundle_status == "fresh":
            cycle.thesis.mark_fresh(
                generated_at=bundle["generated_at"],
                source_count=bundle.get("evidence_source_count", 0),
                item_count=bundle["thesis_count"],
            )
        else:
            try:
                cycle.thesis.status = BundleStatus(bundle_status)
            except ValueError:
                cycle.thesis.status = BundleStatus.ERROR
            blockers = bundle.get("blockers") or [bundle.get("blocked_reason") or "thesis_unavailable"]
            cycle.thesis.last_error = "; ".join(str(item) for item in blockers if str(item).strip())[:200]
        cycle.compute_cycle_decision()
        cycle.save()
    except Exception as exc:
        logger.warning("[thesis] kernel state update failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_once() -> None:
    bundle = assemble_thesis()
    update_kernel_state(bundle)


async def run_daemon() -> None:
    logger.info("Thesis bundle daemon starting — interval=%ds", INTERVAL)
    while True:
        t0 = time.monotonic()
        try:
            run_once()
        except Exception as exc:
            logger.error("[thesis] cycle failed: %s", exc)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, INTERVAL - elapsed))


def main() -> None:
    global INTERVAL
    parser = argparse.ArgumentParser(description="Thesis bundle — evidence-to-thesis compilation")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=INTERVAL)
    args = parser.parse_args()
    INTERVAL = args.interval
    if args.daemon and not args.once:
        asyncio.run(run_daemon())
    else:
        run_once()


if __name__ == "__main__":
    main()
