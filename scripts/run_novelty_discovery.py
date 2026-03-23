#!/usr/bin/env python3
"""
Instance 3 — Novelty Discovery: source_observations → novelty_discovery + novel_edge artifacts.

Reads sensorium and autoresearch artifacts, synthesises structured novelty signals,
and writes two canonical artifacts consumed by run_research_os.py:

  reports/parallel/novelty_discovery.json   — typed discovery items
  reports/parallel/novel_edge.json          — actionable edge hypotheses

Key rule (Instance 3 plan):
  If a fresh sensorium artifact exists (age < SENSORIUM_STALENESS_SECS = 600),
  discovery is driven from that surface and `source` is set to "sensorium".
  Fallback discovery (derived from research_os + btc5_market heuristics) is used
  ONLY when no fresh sensorium is available, and is labelled `source: "fallback"`.
  Fallback must never be the default when fresh observations exist.

Inputs (all optional — graceful degradation):
  reports/parallel/instance01_sensorium_latest.json  — sensorium (Instance 1)
  reports/autoresearch/research_os/latest.json       — research-OS state (mutation waves)
  reports/autoresearch/thesis_candidates.json        — thesis candidates
  reports/autoresearch/btc5_market/latest.json       — market lane champion

Outputs:
  reports/parallel/novelty_discovery.json
  reports/parallel/novel_edge.json

Usage:
  python3 scripts/run_novelty_discovery.py [--dry-run] [--force-fallback]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PARALLEL = REPORTS / "parallel"

SENSORIUM_PATH      = PARALLEL / "instance01_sensorium_latest.json"
RESEARCH_OS_PATH    = REPORTS / "autoresearch" / "research_os" / "latest.json"
THESIS_PATH         = REPORTS / "autoresearch" / "thesis_candidates.json"
MARKET_LANE_PATH    = REPORTS / "autoresearch" / "btc5_market" / "latest.json"

OUT_NOVELTY_DISCOVERY = PARALLEL / "novelty_discovery.json"
OUT_NOVEL_EDGE        = PARALLEL / "novel_edge.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SENSORIUM_STALENESS_SECS = 600   # 10 min — fresh window for sensorium override

# Confidence tiers: sensorium signals carry higher base confidence than fallback heuristics
_SENSORIUM_CONF = 0.72
_FALLBACK_CONF  = 0.45

# Maximum items in output lists
MAX_DISCOVERIES = 20
MAX_EDGES       = 15

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [novelty_discovery] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("novelty_discovery")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _load_json(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        log.debug("optional input not found: %s (%s)", path, label)
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            log.warning("%s: expected dict, got %s — skipping", label, type(data).__name__)
            return None
        log.info("loaded %s (%d keys)", label, len(data))
        return data
    except Exception as exc:
        log.warning("could not load %s: %s", label, exc)
        return None


def _artifact_age_secs(data: dict[str, Any]) -> float:
    """Return how many seconds ago the artifact was generated (9999 if unknown)."""
    ts_str = data.get("generated_at") or data.get("timestamp") or data.get("run_at")
    if not ts_str:
        return 9999.0
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        age = time.time() - ts.timestamp()
        return max(0.0, age)
    except Exception:
        return 9999.0


def _short_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:8].upper()


# ---------------------------------------------------------------------------
# Sensorium-driven discovery
# ---------------------------------------------------------------------------

def _discoveries_from_sensorium(sensorium: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert sensorium signals into typed discovery items."""
    # Sensorium may use 'signals', 'observations', or 'items'
    raw_signals: list[Any] = (
        sensorium.get("signals")
        or sensorium.get("observations")
        or sensorium.get("items")
        or []
    )

    discoveries: list[dict[str, Any]] = []
    now = _now_iso()

    for sig in raw_signals[:MAX_DISCOVERIES]:
        if not isinstance(sig, dict):
            continue

        sig_type  = sig.get("type", "unknown")
        sig_value = sig.get("value") or sig.get("signal") or sig.get("summary") or ""
        sig_lane  = sig.get("lane") or sig.get("market") or "general"
        refs      = sig.get("evidence_refs") or sig.get("refs") or []
        conf      = float(sig.get("confidence") or _SENSORIUM_CONF)

        # Map sensorium type to our discovery taxonomy
        disc_type = _map_sig_type(sig_type)

        disc_id = f"DISC-{_short_id(str(sig))}"
        discoveries.append({
            "discovery_id":  disc_id,
            "type":          disc_type,
            "description":   str(sig_value)[:300],
            "lane":          _normalise_lane(str(sig_lane)),
            "confidence":    round(min(1.0, max(0.0, conf)), 3),
            "evidence_refs": list(refs)[:5],
            "generated_at":  now,
        })

    return discoveries


def _map_sig_type(raw: str) -> str:
    raw_lower = raw.lower()
    if any(k in raw_lower for k in ("birth", "new_market", "launch", "open")):
        return "market_birth"
    if any(k in raw_lower for k in ("diverge", "divergence", "spread", "gap", "price")):
        return "price_divergence"
    if any(k in raw_lower for k in ("pattern", "shift", "regime", "change")):
        return "pattern_shift"
    if any(k in raw_lower for k in ("strengthen", "strengthen_edge", "edge_up", "improving")):
        return "edge_strengthening"
    if any(k in raw_lower for k in ("weaken", "degrade", "decay", "edge_down", "kill")):
        return "edge_weakening"
    return "pattern_shift"


def _normalise_lane(raw: str) -> str:
    r = raw.lower()
    if "btc" in r or "5min" in r or "crypto" in r:
        return "btc5"
    if "weather" in r or "kalshi" in r:
        return "weather"
    if "alpaca" in r or "stock" in r or "equity" in r:
        return "alpaca"
    return "general"


# ---------------------------------------------------------------------------
# Fallback discovery (when sensorium unavailable/stale)
# ---------------------------------------------------------------------------

def _discoveries_fallback(
    research_os: dict[str, Any] | None,
    thesis: dict[str, Any] | None,
    market_lane: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Derive discoveries heuristically from static artifacts when no fresh sensorium."""
    discoveries: list[dict[str, Any]] = []
    now = _now_iso()

    # --- From research_os mutation waves ---
    if research_os:
        waves = research_os.get("mutation_waves") or research_os.get("opportunities") or []
        for wave in waves[:6]:
            if not isinstance(wave, dict):
                continue
            desc = wave.get("description") or wave.get("name") or str(wave)
            lane = _normalise_lane(str(wave.get("lane", "general")))
            disc_id = f"DISC-{_short_id(str(wave))}"
            discoveries.append({
                "discovery_id":  disc_id,
                "type":          "pattern_shift",
                "description":   str(desc)[:300],
                "lane":          lane,
                "confidence":    _FALLBACK_CONF,
                "evidence_refs": [],
                "generated_at":  now,
            })

    # --- From thesis candidates ---
    if thesis:
        candidates = thesis if isinstance(thesis, list) else thesis.get("candidates") or []
        for cand in candidates[:4]:
            if not isinstance(cand, dict):
                continue
            hyp = cand.get("hypothesis") or cand.get("name") or str(cand)
            lane = _normalise_lane(str(cand.get("lane", "btc5")))
            disc_id = f"DISC-{_short_id(str(cand))}"
            discoveries.append({
                "discovery_id":  disc_id,
                "type":          "edge_strengthening",
                "description":   f"Thesis candidate: {str(hyp)[:250]}",
                "lane":          lane,
                "confidence":    _FALLBACK_CONF,
                "evidence_refs": [],
                "generated_at":  now,
            })

    # --- From market lane champion ---
    if market_lane:
        champion = market_lane.get("champion") or {}
        if isinstance(champion, dict) and champion:
            hyp = champion.get("hypothesis") or champion.get("id") or "btc5 champion"
            disc_id = f"DISC-{_short_id(str(champion))}"
            discoveries.append({
                "discovery_id":  disc_id,
                "type":          "edge_strengthening",
                "description":   f"Market lane champion: {str(hyp)[:250]}",
                "lane":          "btc5",
                "confidence":    _FALLBACK_CONF + 0.05,
                "evidence_refs": [],
                "generated_at":  now,
            })

    return discoveries[:MAX_DISCOVERIES]


# ---------------------------------------------------------------------------
# Edge derivation (both paths)
# ---------------------------------------------------------------------------

def _edges_from_discoveries(
    discoveries: list[dict[str, Any]],
    research_os: dict[str, Any] | None,
    market_lane: dict[str, Any] | None,
    source: str,
) -> list[dict[str, Any]]:
    """Derive novel_edge items from discoveries + supplementary context."""
    edges: list[dict[str, Any]] = []
    now = _now_iso()

    # One edge per strengthening/divergence discovery
    for disc in discoveries:
        d_type = disc.get("type", "")
        if d_type not in ("edge_strengthening", "price_divergence", "market_birth"):
            continue
        conf  = float(disc.get("confidence") or _SENSORIUM_CONF)
        lane  = disc.get("lane") or "general"
        desc  = disc.get("description") or ""
        edge_id = f"EDGE-{_short_id(disc.get('discovery_id', '') + lane)}"

        # Estimate edge bps heuristically from confidence
        if conf >= 0.70:
            est_bps = 45
        elif conf >= 0.55:
            est_bps = 25
        else:
            est_bps = 10

        edges.append({
            "edge_id":             edge_id,
            "lane":                lane,
            "hypothesis":          f"Exploitable pattern from discovery: {desc[:200]}",
            "estimated_edge_bps":  est_bps,
            "confidence":          round(conf, 3),
            "requires_data":       _required_data_for_lane(lane),
            "status":              "observed",
            "discovery_source":    source,
        })

    # Supplement from research_os opportunity_exchange if available
    if research_os:
        opp_exchange = research_os.get("opportunity_exchange") or []
        for opp in opp_exchange[:4]:
            if not isinstance(opp, dict):
                continue
            priority = opp.get("estimated_priority") or "medium"
            if priority not in ("high", "critical"):
                continue
            edge_id = f"EDGE-{_short_id(str(opp))}"
            lane = _normalise_lane(str(opp.get("lane", "general")))
            edges.append({
                "edge_id":             edge_id,
                "lane":                lane,
                "hypothesis":          str(opp.get("description") or opp.get("opp_id"))[:250],
                "estimated_edge_bps":  30,
                "confidence":          0.55 if priority == "high" else 0.70,
                "requires_data":       _required_data_for_lane(lane),
                "status":              "observed",
                "discovery_source":    source,
            })

    # Champion lane edge
    if market_lane:
        champion = market_lane.get("champion") or {}
        if isinstance(champion, dict) and champion:
            hyp = champion.get("hypothesis") or champion.get("id") or "btc5 champion"
            edge_id = f"EDGE-{_short_id('champion-' + str(hyp))}"
            edges.append({
                "edge_id":             edge_id,
                "lane":                "btc5",
                "hypothesis":          f"Extend champion policy: {str(hyp)[:200]}",
                "estimated_edge_bps":  55,
                "confidence":          0.68,
                "requires_data":       ["btc5_fill_data", "delta_series", "et_hour"],
                "status":              "observed",
                "discovery_source":    source,
            })

    # Deduplicate by edge_id, preserve insertion order
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in edges:
        if e["edge_id"] not in seen:
            seen.add(e["edge_id"])
            deduped.append(e)

    # Sort: confidence desc, then bps desc
    deduped.sort(key=lambda x: (-x["confidence"], -x["estimated_edge_bps"]))
    return deduped[:MAX_EDGES]


def _required_data_for_lane(lane: str) -> list[str]:
    if lane == "btc5":
        return ["btc5_fill_data", "delta_series", "et_hour", "direction_label"]
    if lane == "weather":
        return ["kalshi_weather_markets", "nws_forecast"]
    if lane == "alpaca":
        return ["equity_price_series", "macro_indicators"]
    return ["polymarket_clob", "resolution_criteria"]


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(*, dry_run: bool = False, force_fallback: bool = False) -> tuple[dict, dict]:
    """Run novelty discovery. Returns (novelty_discovery_artifact, novel_edge_artifact)."""
    now = _now_iso()

    # Load all inputs
    sensorium   = _load_json(SENSORIUM_PATH,   "sensorium")
    research_os = _load_json(RESEARCH_OS_PATH, "research_os")
    thesis      = _load_json(THESIS_PATH,      "thesis_candidates")
    market_lane = _load_json(MARKET_LANE_PATH, "btc5_market")

    # Determine source path
    sensorium_age = _artifact_age_secs(sensorium) if sensorium else 9999.0
    sensorium_fresh = (
        not force_fallback
        and sensorium is not None
        and sensorium_age < SENSORIUM_STALENESS_SECS
    )

    if sensorium_fresh:
        source = "sensorium"
        log.info("sensorium is fresh (age=%.0fs) — using sensorium-driven discovery", sensorium_age)
        discoveries = _discoveries_from_sensorium(sensorium)  # type: ignore[arg-type]
    else:
        source = "fallback"
        reason = (
            "force_fallback flag set" if force_fallback
            else f"sensorium absent" if sensorium is None
            else f"sensorium stale (age={sensorium_age:.0f}s > {SENSORIUM_STALENESS_SECS}s)"
        )
        log.info("using fallback discovery — %s", reason)
        discoveries = _discoveries_fallback(research_os, thesis, market_lane)

    edges = _edges_from_discoveries(discoveries, research_os, market_lane, source)

    # Build novelty_discovery artifact
    novelty_discovery: dict[str, Any] = {
        "artifact":        "novelty_discovery_v1",
        "generated_at":    now,
        "discovery_count": len(discoveries),
        "source":          source,
        "sensorium_age_secs": round(sensorium_age, 1),
        "sensorium_fresh": sensorium_fresh,
        "discoveries":     discoveries,
    }

    # Build novel_edge artifact
    novel_edge: dict[str, Any] = {
        "artifact":     "novel_edge_v1",
        "generated_at": now,
        "edge_count":   len(edges),
        "edges":        edges,
    }

    if dry_run:
        log.info("[dry-run] would write %s", OUT_NOVELTY_DISCOVERY)
        log.info("[dry-run] would write %s", OUT_NOVEL_EDGE)
        print(json.dumps(novelty_discovery, indent=2))
        print(json.dumps(novel_edge, indent=2))
    else:
        PARALLEL.mkdir(parents=True, exist_ok=True)
        _atomic_write(OUT_NOVELTY_DISCOVERY, novelty_discovery)
        _atomic_write(OUT_NOVEL_EDGE, novel_edge)
        log.info("wrote novelty_discovery (%d items, source=%s)", len(discoveries), source)
        log.info("wrote novel_edge (%d edges)", len(edges))

    return novelty_discovery, novel_edge


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically (tmp → rename)."""
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(tmp_fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Instance 3: convert source_observations (sensorium) into "
            "novelty_discovery + novel_edge artifacts"
        )
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute artifacts and print to stdout; do not write files",
    )
    p.add_argument(
        "--force-fallback",
        action="store_true",
        help="Skip sensorium even if fresh; use fallback heuristics (for testing)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    nd, ne = run(dry_run=args.dry_run, force_fallback=args.force_fallback)
    if not args.dry_run:
        print(f"novelty_discovery → {OUT_NOVELTY_DISCOVERY}  ({nd['discovery_count']} items, source={nd['source']})")
        print(f"novel_edge        → {OUT_NOVEL_EDGE}  ({ne['edge_count']} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
