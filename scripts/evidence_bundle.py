#!/usr/bin/env python3
"""
Evidence Bundle — Authoritative Hot-Layer Evidence Unification
===============================================================
The first stage of the self-improvement kernel.

Collects and normalizes all hot-layer evidence sources into one canonical
evidence_bundle.json artifact.  Downstream consumers (thesis_bundle,
learning_bundle) MUST use this artifact, not the raw sources directly.

Evidence sources (priority order)
-----------------------------------
  1. sensorium            — live market census, wallet activity, open positions
  2. resolution_intel     — settlement truth, recent market resolutions
  3. btc5_shadow          — BTC5 skip breakdown and signal decisions (local)
  4. novelty_discovery    — novel findings extracted from source observations
  5. weather_divergence   — NOAA/NWS vs Kalshi shadow divergence (if present)
  6. lifecycle_events     — market births, expirations, category shifts
  7. decision_log         — last N trade decisions with attribution

Output: reports/evidence_bundle.json
Kernel: updates reports/kernel/kernel_state.json evidence bundle status

Usage
-----
  python3 scripts/evidence_bundle.py           # run once
  python3 scripts/evidence_bundle.py --daemon  # continuous (default 5min)
  python3 scripts/evidence_bundle.py --once    # alias for single run

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
import urllib.request
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
logger = logging.getLogger("JJ.evidence")

PROJECT_ROOT = REPO_ROOT
REPORTS = PROJECT_ROOT / "reports"
SHADOW = REPORTS / "local_shadow"
OUTPUT_PATH = REPORTS / "evidence_bundle.json"

PROXY_WALLET = os.environ.get(
    "POLY_DATA_API_ADDRESS", "0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5"
)
DATA_API = "https://data-api.polymarket.com"
INTERVAL = int(os.environ.get("EVIDENCE_INTERVAL_SECONDS", "300"))


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


def fetch_json(url: str, timeout: int = 12) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "elastifund-evidence/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Source collectors
# ---------------------------------------------------------------------------


def collect_sensorium() -> dict[str, Any] | None:
    """Load pre-computed sensorium artifact or generate a minimal live snapshot."""
    cached = load_json(SHADOW / "sensorium.json")
    if cached:
        gen = cached.get("generated_at") or ""
        age = age_seconds(gen) if gen else 9999
        if age < 600:  # fresh enough (< 10 min)
            return {"source": "sensorium_cache", "age_seconds": age, "data": cached}
        logger.info("[evidence] sensorium cache stale (%.0fs) — fetching live snapshot", age)

    # Minimal live snapshot
    try:
        raw = fetch_json(f"{DATA_API}/markets?active=true&closed=false&limit=100")
        markets = raw if isinstance(raw, list) else raw.get("data") or raw.get("markets") or []
        total = len(markets)
        by_tag: dict[str, int] = {}
        for m in markets:
            for tag in (m.get("tags") or []):
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return {
            "source": "sensorium_live",
            "age_seconds": 0.0,
            "data": {
                "artifact": "sensorium",
                "generated_at": utc_now(),
                "observations": [{"type": "market_census", "total_active": total, "by_tag": by_tag}],
            },
        }
    except Exception as exc:
        logger.warning("[evidence] live sensorium fetch failed: %s", exc)
        return None


def collect_resolution_intel() -> dict[str, Any] | None:
    """Recent market resolutions — settlement truth."""
    try:
        raw = fetch_json(
            f"{DATA_API}/markets?active=false&closed=true&limit=30&order=closeTime&ascending=false"
        )
        resolved = raw if isinstance(raw, list) else raw.get("data") or raw.get("markets") or []
        return {
            "source": "resolution_intel_live",
            "age_seconds": 0.0,
            "data": {
                "artifact": "resolution_intel",
                "generated_at": utc_now(),
                "resolved_count": len(resolved),
                "resolutions": [
                    {
                        "question": m.get("question"),
                        "resolution": m.get("resolution") or m.get("outcome"),
                        "close_time": m.get("closedTime") or m.get("endDate"),
                    }
                    for m in resolved[:10]
                ],
            },
        }
    except Exception as exc:
        logger.warning("[evidence] resolution intel fetch failed: %s", exc)
        return None


def collect_btc5_shadow() -> dict[str, Any] | None:
    cached = load_json(SHADOW / "btc5_shadow.json")
    if cached:
        gen = cached.get("generated_at") or ""
        age = age_seconds(gen) if gen else 9999
        return {"source": "btc5_shadow_cache", "age_seconds": age, "data": cached}
    return None


def collect_novelty() -> dict[str, Any] | None:
    path = REPORTS / "novelty_discovery.json"
    cached = load_json(path)
    if cached:
        gen = cached.get("generated_at") or ""
        age = age_seconds(gen) if gen else 9999
        return {"source": "novelty_discovery", "age_seconds": age, "data": cached}
    return None


def collect_weather_divergence() -> dict[str, Any] | None:
    # Weather lane is KILLED — include if artifact exists but flag accordingly
    path = REPORTS / "parallel" / "instance04_weather_divergence_shadow.json"
    cached = load_json(path)
    if cached:
        gen = cached.get("generated_at") or cached.get("timestamp") or ""
        age = age_seconds(gen) if gen else 9999
        return {
            "source": "weather_divergence_shadow",
            "age_seconds": age,
            "killed": True,  # lane formally killed; included for historical context only
            "data": cached,
        }
    return None


def collect_decision_log() -> dict[str, Any] | None:
    """Last N trade decisions from local monitor state."""
    state = load_json(PROJECT_ROOT / "data" / "local_monitor_state.json")
    if not state:
        return None
    closed = state.get("closed_trades") or []
    recent_decisions = [
        {
            "market": t.get("market") or "",
            "outcome": t.get("outcome") or "",
            "pnl": t.get("pnl") or 0,
            "is_btc5": t.get("is_btc5") or False,
        }
        for t in (closed[-20:] if isinstance(closed, list) else [])
    ]
    return {
        "source": "decision_log",
        "age_seconds": 0.0,
        "data": {
            "artifact": "decision_log",
            "generated_at": utc_now(),
            "decision_count": len(recent_decisions),
            "decisions": recent_decisions,
        },
    }


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------


def assemble_evidence() -> dict[str, Any]:
    """Collect all evidence sources and produce the canonical bundle."""
    logger.info("[evidence] assembling evidence bundle")

    collectors = [
        ("sensorium", collect_sensorium),
        ("resolution_intel", collect_resolution_intel),
        ("btc5_shadow", collect_btc5_shadow),
        ("novelty_discovery", collect_novelty),
        ("weather_divergence", collect_weather_divergence),
        ("decision_log", collect_decision_log),
    ]

    items: list[dict[str, Any]] = []
    sources_used: list[str] = []
    stale_sources: list[str] = []
    collector_failures: list[str] = []

    for name, fn in collectors:
        try:
            result = fn()
            if result is None:
                continue
            items.append({"name": name, **result})
            sources_used.append(name)
            age = result.get("age_seconds", 0)
            if age > 900:  # > 15 min old
                stale_sources.append(name)
        except Exception as exc:
            collector_failures.append(f"{name}:{type(exc).__name__}")
            logger.warning("[evidence] collector %s failed: %s", name, exc)

    status = "blocked" if not items else ("stale" if collector_failures or stale_sources else "fresh")
    blockers = list(collector_failures)
    blockers.extend(f"stale_source:{name}" for name in stale_sources)
    if not items:
        blockers.append("all_sources_unavailable")

    bundle: dict[str, Any] = {
        "generated_at": utc_now(),
        "source_count": len(items),
        "sources_used": sources_used,
        "stale_sources": stale_sources,
        "collector_failures": collector_failures,
        "is_fallback": len(items) == 0,
        "items": items,
        "status": status,
        "blockers": blockers,
    }

    write_report(
        OUTPUT_PATH,
        artifact="evidence_bundle",
        payload=bundle,
        status=status,
        source_of_truth=(
            "reports/parallel/instance01_sensorium_latest.json; "
            "reports/parallel/instance04_weather_divergence_shadow.json; "
            "reports/autoresearch/btc5_market/latest.json; "
            "reports/autoresearch/command_node/latest.json; "
            "reports/wallet_reconciliation/latest.json; "
            "reports/finance/latest.json"
        ),
        freshness_sla_seconds=300,
        blockers=blockers,
        summary=(
            f"{len(items)} evidence items from {len(sources_used)} sources"
            + (f" ({len(stale_sources)} stale)" if stale_sources else "")
        ),
    )
    logger.info(
        "[evidence] bundle written: %d sources (%d stale)",
        len(items),
        len(stale_sources),
    )
    return bundle


def update_kernel_state(bundle: dict[str, Any]) -> None:
    """Update the kernel's evidence bundle descriptor."""
    try:
        # Lazy import to avoid circular reference during standalone runs
        import sys
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from kernel_contract import KernelCycle, BundleStatus

        cycle = KernelCycle.load()
        cycle.generated_at = utc_now()
        bundle_status = str(bundle.get("status") or "error").strip().lower()
        if bundle_status == "fresh":
            cycle.evidence.mark_fresh(
                generated_at=bundle["generated_at"],
                source_count=bundle["source_count"],
                item_count=len(bundle.get("items") or []),
            )
        else:
            try:
                cycle.evidence.status = BundleStatus(bundle_status)
            except ValueError:
                cycle.evidence.status = BundleStatus.ERROR
            cycle.evidence.last_error = "; ".join(str(item) for item in (bundle.get("blockers") or []))[:200]
        cycle.save()
    except Exception as exc:
        logger.warning("[evidence] kernel state update failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_once() -> None:
    bundle = assemble_evidence()
    update_kernel_state(bundle)


async def run_daemon() -> None:
    logger.info("Evidence bundle daemon starting — interval=%ds", INTERVAL)
    while True:
        t0 = time.monotonic()
        try:
            run_once()
        except Exception as exc:
            logger.error("[evidence] cycle failed: %s", exc)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, INTERVAL - elapsed))


def main() -> None:
    global INTERVAL
    parser = argparse.ArgumentParser(description="Evidence bundle — authoritative evidence layer")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--once", action="store_true", help="Single cycle then exit")
    parser.add_argument("--interval", type=int, default=INTERVAL)
    args = parser.parse_args()

    INTERVAL = args.interval

    if args.daemon and not args.once:
        asyncio.run(run_daemon())
    else:
        run_once()


if __name__ == "__main__":
    main()
