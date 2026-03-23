#!/usr/bin/env python3
"""
Novelty Discovery — Source Observations → Novel-Edge Artifacts
===============================================================
Synthesizes existing source observations (wallet flow signals, signal source
audits, closed trade patterns, autoresearch latest) into two artifacts:

  reports/novelty_discovery.json  — what's new or surprising since last run
  reports/novel_edge.json         — actionable edge candidates extracted
                                    from novel observations

These artifacts are consumed by the research-OS mutation loop and the
supervisor's thesis foundry.  When fresh source observations are available,
this script supersedes fallback discovery modes.

Source priority (highest to lowest)
------------------------------------
1. reports/local_shadow/sensorium.json        (live market observations)
2. reports/wallet_intelligence_prior_latest.json (wallet flow priors)
3. reports/signal_source_audit.json            (signal source diagnostics)
4. reports/autoresearch/latest.json            (last autoresearch surface)
5. reports/local_monitor_state.json            (local monitor snapshot)

Usage
-----
  python3 scripts/novelty_discovery.py           # run once
  python3 scripts/novelty_discovery.py --daemon  # continuous loop

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("JJ.novelty")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS = PROJECT_ROOT / "reports"

NOVELTY_PATH = REPORTS / "novelty_discovery.json"
NOVEL_EDGE_PATH = REPORTS / "novel_edge.json"

INTERVAL_SECONDS = int(os.environ.get("NOVELTY_INTERVAL_SECONDS", "600"))


# ---------------------------------------------------------------------------
# Source loaders
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_sources() -> dict[str, Any]:
    sources: dict[str, Any] = {}

    sensorium = _load(REPORTS / "local_shadow" / "sensorium.json")
    if sensorium:
        sources["sensorium"] = sensorium

    wallet_prior = _load(REPORTS / "wallet_intelligence_prior_latest.json")
    if wallet_prior:
        sources["wallet_prior"] = wallet_prior

    signal_audit = _load(REPORTS / "signal_source_audit.json")
    if signal_audit:
        sources["signal_audit"] = signal_audit

    autoresearch = _load(REPORTS / "autoresearch" / "latest.json")
    if autoresearch:
        sources["autoresearch"] = autoresearch

    monitor_state = _load(PROJECT_ROOT / "data" / "local_monitor_state.json")
    if monitor_state:
        sources["monitor_state"] = monitor_state

    return sources


# ---------------------------------------------------------------------------
# Novelty extraction
# ---------------------------------------------------------------------------


def _extract_market_novelty(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify novel market observations from sensorium."""
    findings: list[dict[str, Any]] = []
    sensorium = sources.get("sensorium") or {}
    observations = sensorium.get("observations") or []

    for obs in observations:
        if obs.get("type") == "market_census":
            by_tag = obs.get("by_tag") or {}
            total = obs.get("total_active", 0)
            # Flag if any single tag dominates more than 40% of markets
            for tag, count in by_tag.items():
                if total > 0 and count / total > 0.4:
                    findings.append({
                        "type": "market_concentration",
                        "tag": tag,
                        "count": count,
                        "fraction": round(count / total, 3),
                        "signal": "high_category_concentration",
                        "note": f"Tag '{tag}' holds {count}/{total} active markets",
                    })

        if obs.get("type") == "wallet_activity":
            recent = obs.get("recent_trade_count", 0)
            if recent == 0:
                findings.append({
                    "type": "wallet_silence",
                    "signal": "zero_recent_trades",
                    "note": "No recent wallet activity — bot may be blocked or in skip mode",
                })
            elif recent > 15:
                findings.append({
                    "type": "high_activity",
                    "signal": "elevated_trade_count",
                    "recent_trades": recent,
                    "note": f"Elevated wallet activity: {recent} trades",
                })

    return findings


def _extract_skip_novelty(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Find dominant skip reasons in monitor state."""
    findings: list[dict[str, Any]] = []
    state = sources.get("monitor_state") or {}

    vps = state.get("vps_status") or {}
    skip_breakdown = vps.get("skip_breakdown") or {}
    total_skips = sum(skip_breakdown.values()) if skip_breakdown else 0

    if total_skips > 0:
        for reason, count in sorted(skip_breakdown.items(), key=lambda x: -x[1]):
            pct = count / total_skips
            if pct > 0.4:
                findings.append({
                    "type": "dominant_skip_reason",
                    "reason": reason,
                    "count": count,
                    "fraction": round(pct, 3),
                    "signal": "blocker_candidate",
                    "note": f"Skip reason '{reason}' accounts for {pct*100:.0f}% of all skips",
                })
                break  # report only the top blocker

    return findings


def _extract_signal_novelty(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Find signals from signal source audit."""
    findings: list[dict[str, Any]] = []
    audit = sources.get("signal_audit") or {}

    # If any signal source is consistently 0-contribution, flag it
    sources_list = audit.get("signal_sources") or audit.get("sources") or []
    for src in sources_list:
        contribution = src.get("contribution") or src.get("weight") or 0
        if contribution == 0:
            findings.append({
                "type": "dead_signal_source",
                "source": src.get("name") or src.get("source"),
                "signal": "zero_contribution",
                "note": f"Signal source '{src.get('name')}' has zero contribution",
            })

    return findings


def _extract_autoresearch_novelty(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract champion / regression news from autoresearch latest."""
    findings: list[dict[str, Any]] = []
    ar = sources.get("autoresearch") or {}

    champions = ar.get("current_champions") or {}
    for lane, champ in champions.items():
        loss = champ.get("loss")
        updated = champ.get("updated_at") or ""
        if loss is not None and updated:
            findings.append({
                "type": "autoresearch_champion",
                "lane": lane,
                "champion_id": champ.get("id") or champ.get("model_name"),
                "loss": loss,
                "updated_at": updated,
                "signal": "champion_state",
            })

    # Flag if autoresearch is stale (> 24h old)
    gen = ar.get("generated_at") or ""
    if gen:
        try:
            ts = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_hours > 24:
                findings.append({
                    "type": "stale_autoresearch",
                    "age_hours": round(age_hours, 1),
                    "signal": "autoresearch_loop_may_be_dead",
                    "note": f"Autoresearch latest.json is {age_hours:.0f}h old — loop may need restart",
                })
        except Exception:
            pass

    return findings


def extract_all_novelty(sources: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    findings.extend(_extract_market_novelty(sources))
    findings.extend(_extract_skip_novelty(sources))
    findings.extend(_extract_signal_novelty(sources))
    findings.extend(_extract_autoresearch_novelty(sources))
    return findings


# ---------------------------------------------------------------------------
# Edge candidate extraction
# ---------------------------------------------------------------------------


_EDGE_SIGNALS = {
    "dominant_skip_reason": "fix_skip_filter",
    "wallet_silence": "diagnose_execution_block",
    "stale_autoresearch": "restart_autoresearch_loop",
    "market_concentration": "target_concentrated_category",
    "dead_signal_source": "remove_or_recalibrate_signal",
}


def extract_novel_edges(novelty: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert novelty findings into actionable edge candidates."""
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    for finding in novelty:
        sig = finding.get("signal") or ""
        action = _EDGE_SIGNALS.get(finding.get("type") or "", None)
        if action and action not in seen:
            seen.add(action)
            edges.append({
                "edge_id": f"novel_{finding['type']}_{len(edges)+1:02d}",
                "action": action,
                "priority": "high" if finding.get("type") in (
                    "dominant_skip_reason", "wallet_silence", "stale_autoresearch"
                ) else "medium",
                "source_finding": finding,
                "note": finding.get("note") or sig,
            })

    # Sort: high priority first
    edges.sort(key=lambda e: (0 if e["priority"] == "high" else 1))
    return edges


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once() -> None:
    sources = load_sources()
    source_names = list(sources.keys())
    logger.info("loaded %d source(s): %s", len(source_names), source_names)

    if not sources:
        logger.warning("no source observations found — skipping novelty generation")
        return

    novelty = extract_all_novelty(sources)
    edges = extract_novel_edges(novelty)

    novelty_payload: dict[str, Any] = {
        "artifact": "novelty_discovery",
        "generated_at": utc_now(),
        "source_count": len(source_names),
        "sources_used": source_names,
        "finding_count": len(novelty),
        "findings": novelty,
    }

    edge_payload: dict[str, Any] = {
        "artifact": "novel_edge",
        "generated_at": utc_now(),
        "source_count": len(source_names),
        "edge_count": len(edges),
        "edges": edges,
    }

    NOVELTY_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOVELTY_PATH.write_text(json.dumps(novelty_payload, indent=2, default=str))
    NOVEL_EDGE_PATH.write_text(json.dumps(edge_payload, indent=2, default=str))

    logger.info(
        "novelty_discovery: %d findings → %d edge candidates",
        len(novelty),
        len(edges),
    )
    for edge in edges[:5]:
        logger.info("  edge [%s] %s — %s", edge["priority"], edge["action"], edge["note"][:80])


async def run_daemon() -> None:
    logger.info("Novelty discovery daemon starting — interval=%ds", INTERVAL_SECONDS)
    while True:
        t0 = time.monotonic()
        try:
            run_once()
        except Exception as exc:
            logger.error("cycle failed: %s", exc)
        elapsed = time.monotonic() - t0
        sleep = max(0.0, INTERVAL_SECONDS - elapsed)
        await asyncio.sleep(sleep)


def main() -> None:
    global INTERVAL_SECONDS
    parser = argparse.ArgumentParser(description="Novelty discovery — source_obs → novel_edge")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument(
        "--interval",
        type=int,
        default=INTERVAL_SECONDS,
        help="Seconds between daemon cycles",
    )
    args = parser.parse_args()

    INTERVAL_SECONDS = args.interval

    if args.daemon:
        asyncio.run(run_daemon())
    else:
        run_once()


if __name__ == "__main__":
    main()
