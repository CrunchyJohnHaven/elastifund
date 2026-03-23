#!/usr/bin/env python3
"""
Sensorium — Evidence Layer Aggregator (Instance 1)
====================================================
Reads all available lane artifacts and distills them into a single
evidence bundle for the self-improvement kernel.

Inputs (all optional, graceful degradation):
  reports/canonical_operator_truth.json
  reports/parallel/instance04_weather_divergence_shadow.json
  reports/autoresearch/btc5_market/latest.json
  reports/autoresearch/command_node/latest.json
  reports/wallet_reconciliation/latest.json
  reports/finance/latest.json

Output:
  reports/parallel/instance01_sensorium_latest.json

Usage:
  python3 scripts/run_sensorium.py
  python3 scripts/run_sensorium.py --check-only

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_PATH = PROJECT_ROOT / "reports" / "parallel" / "instance01_sensorium_latest.json"

# ---------------------------------------------------------------------------
# Source artifact registry
# ---------------------------------------------------------------------------
SOURCES: dict[str, Path] = {
    "canonical_operator_truth":     PROJECT_ROOT / "reports" / "canonical_operator_truth.json",
    "weather_divergence_shadow":     PROJECT_ROOT / "reports" / "parallel" / "instance04_weather_divergence_shadow.json",
    "btc5_market":                   PROJECT_ROOT / "reports" / "autoresearch" / "btc5_market" / "latest.json",
    "btc5_command_node":             PROJECT_ROOT / "reports" / "autoresearch" / "command_node" / "latest.json",
    "wallet_reconciliation":         PROJECT_ROOT / "reports" / "wallet_reconciliation" / "latest.json",
    "finance":                       PROJECT_ROOT / "reports" / "finance" / "latest.json",
}

# Seconds before an artifact is considered stale for sensorium purposes
STALE_THRESHOLDS: dict[str, int] = {
    "canonical_operator_truth":  3600,
    "weather_divergence_shadow": 7200,
    "btc5_market":               86400,
    "btc5_command_node":         86400,
    "wallet_reconciliation":     3600,
    "finance":                   7200,
}

log = logging.getLogger("sensorium")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        log.warning("Failed to parse %s: %s", path.name, exc)
        return {}


def _artifact_age_seconds(payload: dict[str, Any]) -> float:
    """Return seconds since artifact's generated_at, or -1.0 if unknown."""
    now = _utc_now()
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


def _obs(
    obs_id: str,
    category: str,
    signal: str,
    value: float,
    confidence: float,
    source: str,
    age_seconds: float,
    stale_threshold: int,
) -> dict[str, Any]:
    return {
        "obs_id": obs_id,
        "category": category,
        "signal": signal,
        "value": round(value, 6),
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "source": source,
        "age_seconds": round(age_seconds, 1) if age_seconds >= 0 else -1,
        "stale": age_seconds < 0 or age_seconds > stale_threshold,
    }


# ---------------------------------------------------------------------------
# Per-source extraction functions
# ---------------------------------------------------------------------------

def _extract_capital_observations(
    canonical: dict[str, Any],
    wallet_recon: dict[str, Any],
    finance: dict[str, Any],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []

    # --- wallet P&L trend from wallet_reconciliation ---
    wr_age = _artifact_age_seconds(wallet_recon)
    wr_stale_threshold = STALE_THRESHOLDS["wallet_reconciliation"]

    summary = wallet_recon.get("wallet_reconciliation_summary", {})
    total_pnl = summary.get("total_pnl_usd")
    if total_pnl is None:
        # Fall back to capital_attribution
        attr = wallet_recon.get("capital_attribution", {})
        total_pnl = attr.get("realized_pnl_usd", 0.0)

    if total_pnl is not None:
        signal = "positive" if total_pnl > 5 else ("negative" if total_pnl < -5 else "flat")
        observations.append(_obs(
            obs_id="wallet:pnl_trend",
            category="capital",
            signal=signal,
            value=float(total_pnl),
            confidence=0.95 if wr_age >= 0 and wr_age < wr_stale_threshold else 0.4,
            source="wallet_reconciliation",
            age_seconds=wr_age,
            stale_threshold=wr_stale_threshold,
        ))

    # --- open position count from wallet_reconciliation ---
    open_positions = wallet_recon.get("open_positions", {})
    open_count = open_positions.get("count", 0) if isinstance(open_positions, dict) else 0
    if open_count > 0 or wallet_recon:
        signal = "positive" if 1 <= open_count <= 10 else ("negative" if open_count > 20 else "flat")
        observations.append(_obs(
            obs_id="wallet:open_position_count",
            category="capital",
            signal=signal,
            value=float(open_count),
            confidence=0.9 if wr_age >= 0 and wr_age < wr_stale_threshold else 0.3,
            source="wallet_reconciliation",
            age_seconds=wr_age,
            stale_threshold=wr_stale_threshold,
        ))

    # --- finance gate pass/fail ---
    fin_age = _artifact_age_seconds(finance)
    fin_stale_threshold = STALE_THRESHOLDS["finance"]
    gate = finance.get("finance_gate", {})
    gate_pass = gate.get("pass", False)
    if finance:
        observations.append(_obs(
            obs_id="finance:gate_pass",
            category="capital",
            signal="positive" if gate_pass else "negative",
            value=1.0 if gate_pass else 0.0,
            confidence=0.85 if fin_age >= 0 and fin_age < fin_stale_threshold else 0.3,
            source="finance",
            age_seconds=fin_age,
            stale_threshold=fin_stale_threshold,
        ))

    # --- arr_confidence_score from finance ---
    arr_score = finance.get("arr_confidence_score")
    if arr_score is not None:
        observations.append(_obs(
            obs_id="finance:arr_confidence_score",
            category="capital",
            signal="positive" if arr_score >= 0.7 else ("negative" if arr_score < 0.4 else "flat"),
            value=float(arr_score),
            confidence=0.8 if fin_age >= 0 and fin_age < fin_stale_threshold else 0.25,
            source="finance",
            age_seconds=fin_age,
            stale_threshold=fin_stale_threshold,
        ))

    # --- canonical operator truth: posture/mode ---
    can_age = _artifact_age_seconds(canonical)
    can_stale_threshold = STALE_THRESHOLDS["canonical_operator_truth"]
    if canonical:
        mode = canonical.get("trading_mode") or canonical.get("mode") or "unknown"
        posture = canonical.get("posture") or canonical.get("execution_posture") or "unknown"
        observations.append(_obs(
            obs_id="canonical:trading_mode",
            category="posture",
            signal="positive" if mode not in ("unknown", "paper", "blocked") else "flat",
            value=0.0,
            confidence=0.9 if can_age >= 0 and can_age < can_stale_threshold else 0.2,
            source="canonical_operator_truth",
            age_seconds=can_age,
            stale_threshold=can_stale_threshold,
        ))

    return observations


def _extract_weather_observations(weather: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    if not weather:
        return observations

    age = _artifact_age_seconds(weather)
    stale_threshold = STALE_THRESHOLDS["weather_divergence_shadow"]

    market_scan = weather.get("market_scan", {})
    candidate_rows = market_scan.get("candidate_rows", []) if market_scan else []
    candidate_count = market_scan.get("candidate_count", len(candidate_rows)) if market_scan else 0

    # Signal: number of active weather candidates
    observations.append(_obs(
        obs_id="weather:candidate_count",
        category="weather",
        signal="positive" if candidate_count >= 2 else ("negative" if candidate_count == 0 else "flat"),
        value=float(candidate_count),
        confidence=0.8 if age >= 0 and age < stale_threshold else 0.2,
        source="weather_divergence_shadow",
        age_seconds=age,
        stale_threshold=stale_threshold,
    ))

    # Best edge from candidate rows
    if candidate_rows:
        edges = []
        for row in candidate_rows:
            edge_info = row.get("edge") or {}
            spread_adj = edge_info.get("spread_adjusted_edge")
            if spread_adj is not None:
                edges.append(float(spread_adj))
        if edges:
            best_edge = max(edges)
            observations.append(_obs(
                obs_id="weather:best_spread_adjusted_edge",
                category="weather",
                signal="positive" if best_edge > 0.15 else ("negative" if best_edge < 0 else "flat"),
                value=best_edge,
                confidence=0.75 if age >= 0 and age < stale_threshold else 0.2,
                source="weather_divergence_shadow",
                age_seconds=age,
                stale_threshold=stale_threshold,
            ))

    # Finance gate pass for weather lane
    finance_gate_pass = weather.get("finance_gate_pass")
    if finance_gate_pass is not None:
        observations.append(_obs(
            obs_id="weather:finance_gate_pass",
            category="weather",
            signal="positive" if finance_gate_pass else "negative",
            value=1.0 if finance_gate_pass else 0.0,
            confidence=0.85 if age >= 0 and age < stale_threshold else 0.2,
            source="weather_divergence_shadow",
            age_seconds=age,
            stale_threshold=stale_threshold,
        ))

    return observations


def _extract_btc5_observations(
    btc5_market: dict[str, Any],
    btc5_command_node: dict[str, Any],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []

    mkt_age = _artifact_age_seconds(btc5_market.get("champion", {}))
    if mkt_age < 0:
        # Try epoch_id as fallback timestamp
        epoch = btc5_market.get("epoch_id", "")
        if epoch:
            try:
                # epoch_id format: "2026-03-10T10:55:00Z__2026-03-11T15:20:00Z"
                end_ts = epoch.split("__")[-1]
                generated = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                mkt_age = (_utc_now() - generated).total_seconds()
            except Exception:
                pass

    mkt_stale_threshold = STALE_THRESHOLDS["btc5_market"]

    # Model quality: champion loss (lower is better; threshold ~6 = moderate quality)
    champion = btc5_market.get("champion", {})
    champion_loss = champion.get("loss")
    if champion_loss is not None:
        signal = "positive" if champion_loss < 5.0 else ("negative" if champion_loss > 7.0 else "flat")
        observations.append(_obs(
            obs_id="btc5:market_model_loss",
            category="btc5",
            signal=signal,
            value=float(champion_loss),
            confidence=0.8 if mkt_age >= 0 and mkt_age < mkt_stale_threshold else 0.2,
            source="btc5_market",
            age_seconds=mkt_age,
            stale_threshold=mkt_stale_threshold,
        ))

    # Counts: keep vs discard ratio
    counts = btc5_market.get("counts", {})
    keep = counts.get("keep", 0)
    total = counts.get("total", 0)
    if total > 0:
        keep_rate = keep / total
        observations.append(_obs(
            obs_id="btc5:market_keep_rate",
            category="btc5",
            signal="positive" if keep_rate > 0.005 else "negative",
            value=keep_rate,
            confidence=0.75 if mkt_age >= 0 and mkt_age < mkt_stale_threshold else 0.2,
            source="btc5_market",
            age_seconds=mkt_age,
            stale_threshold=mkt_stale_threshold,
        ))

    # Command node: latest status
    cn_age = _artifact_age_seconds(btc5_command_node.get("champion", {}))
    cn_stale_threshold = STALE_THRESHOLDS["btc5_command_node"]
    latest_status = btc5_command_node.get("latest_status")
    if latest_status is not None:
        signal = "positive" if latest_status == "keep" else "negative"
        observations.append(_obs(
            obs_id="btc5:command_node_latest_status",
            category="btc5",
            signal=signal,
            value=1.0 if latest_status == "keep" else 0.0,
            confidence=0.7 if cn_age >= 0 and cn_age < cn_stale_threshold else 0.2,
            source="btc5_command_node",
            age_seconds=cn_age,
            stale_threshold=cn_stale_threshold,
        ))

    # Command node counts
    cn_counts = btc5_command_node.get("counts", {})
    cn_keep = cn_counts.get("keep", 0)
    cn_total = cn_counts.get("total", 0)
    if cn_total > 0:
        cn_keep_rate = cn_keep / cn_total
        observations.append(_obs(
            obs_id="btc5:command_node_keep_rate",
            category="btc5",
            signal="positive" if cn_keep_rate > 0.003 else "negative",
            value=cn_keep_rate,
            confidence=0.7 if cn_age >= 0 and cn_age < cn_stale_threshold else 0.2,
            source="btc5_command_node",
            age_seconds=cn_age,
            stale_threshold=cn_stale_threshold,
        ))

    return observations


def _extract_concentration_observation(wallet_recon: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    wr_age = _artifact_age_seconds(wallet_recon)
    stale_threshold = STALE_THRESHOLDS["wallet_reconciliation"]

    open_positions = wallet_recon.get("open_positions", {})
    if not isinstance(open_positions, dict):
        return observations

    rows = open_positions.get("rows", [])
    open_count = open_positions.get("count", len(rows))

    if rows and open_count > 0:
        # Total mark value
        total_mark = sum(r.get("current_value_usd", 0.0) for r in rows if isinstance(r, dict))
        max_single = max(
            (r.get("current_value_usd", 0.0) for r in rows if isinstance(r, dict)),
            default=0.0,
        )
        concentration = max_single / total_mark if total_mark > 0 else 0.0
        signal = "negative" if concentration > 0.5 else ("positive" if concentration < 0.25 else "flat")
        observations.append(_obs(
            obs_id="wallet:position_concentration",
            category="capital",
            signal=signal,
            value=round(concentration, 4),
            confidence=0.9 if wr_age >= 0 and wr_age < stale_threshold else 0.3,
            source="wallet_reconciliation",
            age_seconds=wr_age,
            stale_threshold=stale_threshold,
        ))

    return observations


# ---------------------------------------------------------------------------
# Tape snapshot
# ---------------------------------------------------------------------------

def _build_tape_snapshot(
    btc5_market: dict[str, Any],
    btc5_command_node: dict[str, Any],
    wallet_recon: dict[str, Any],
) -> dict[str, Any]:
    open_positions = wallet_recon.get("open_positions", {})
    open_count = open_positions.get("count", 0) if isinstance(open_positions, dict) else 0

    counts = btc5_market.get("counts", {})
    keep = counts.get("keep", 0)
    total = counts.get("total", 0)
    skip_rate = round(1.0 - (keep / total), 4) if total > 0 else None
    fill_rate = round(keep / total, 4) if total > 0 else None

    return {
        "btc5_skip_rate": skip_rate,
        "btc5_fill_rate": fill_rate,
        "btc5_market_total_experiments": total,
        "btc5_command_node_latest_status": btc5_command_node.get("latest_status"),
        "open_positions": open_count,
    }


# ---------------------------------------------------------------------------
# Settlement truth
# ---------------------------------------------------------------------------

def _build_settlement_truth(wallet_recon: dict[str, Any]) -> dict[str, Any]:
    summary = wallet_recon.get("wallet_reconciliation_summary", {})
    attr = wallet_recon.get("capital_attribution", {})
    open_positions = wallet_recon.get("open_positions", {})

    closed_positions = wallet_recon.get("closed_positions", {})
    closed_count = closed_positions.get("count", 0) if isinstance(closed_positions, dict) else 0

    return {
        "user_address": wallet_recon.get("user_address"),
        "total_pnl_usd": summary.get("total_pnl_usd") or attr.get("realized_pnl_usd"),
        "open_count": open_positions.get("count", 0) if isinstance(open_positions, dict) else 0,
        "closed_count": closed_count,
        "wallet_reconciliation_status": wallet_recon.get("status"),
        "generated_at": wallet_recon.get("generated_at"),
    }


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

def _build_lifecycle_events(
    finance: dict[str, Any],
    weather: dict[str, Any],
    btc5_command_node: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    now_iso = _iso_now()

    # Finance gate changes
    gate = finance.get("finance_gate", {})
    gate_reason = gate.get("reason", "")
    if gate_reason:
        events.append({
            "event_id": "finance:gate_reason",
            "at": finance.get("generated_at", now_iso),
            "type": "gate_status",
            "description": gate_reason[:200],
            "source": "finance",
        })

    # Weather lane execution policy
    exec_policy = weather.get("execution_policy")
    if exec_policy:
        events.append({
            "event_id": "weather:execution_policy",
            "at": weather.get("generated_at", now_iso),
            "type": "lane_policy",
            "description": str(exec_policy)[:200],
            "source": "weather_divergence_shadow",
        })

    # BTC5 command node latest decision
    decision_reason = btc5_command_node.get("latest_decision_reason")
    if decision_reason:
        events.append({
            "event_id": "btc5:command_node_decision",
            "at": now_iso,
            "type": "model_decision",
            "description": str(decision_reason)[:200],
            "source": "btc5_command_node",
        })

    return events


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------

def build_sensorium(check_only: bool = False) -> dict[str, Any]:
    now_iso = _iso_now()
    decision_log: list[dict[str, Any]] = []

    def log_decision(action: str, reason: str) -> None:
        decision_log.append({"at": _iso_now(), "action": action, "reason": reason})

    # --- Load all sources ---
    loaded: dict[str, dict[str, Any]] = {}
    for name, path in SOURCES.items():
        payload = _read_json(path)
        loaded[name] = payload
        if payload:
            log_decision(f"loaded:{name}", f"found {len(payload)} keys")
        else:
            log_decision(f"skipped:{name}", "file missing or empty — graceful degradation")

    source_count = sum(1 for v in loaded.values() if v)

    canonical  = loaded["canonical_operator_truth"]
    weather    = loaded["weather_divergence_shadow"]
    btc5_mkt   = loaded["btc5_market"]
    btc5_cn    = loaded["btc5_command_node"]
    wr         = loaded["wallet_reconciliation"]
    fin        = loaded["finance"]

    # --- Build observations ---
    observations: list[dict[str, Any]] = []
    observations.extend(_extract_capital_observations(canonical, wr, fin))
    observations.extend(_extract_weather_observations(weather))
    observations.extend(_extract_btc5_observations(btc5_mkt, btc5_cn))
    observations.extend(_extract_concentration_observation(wr))

    log_decision("observations_built", f"{len(observations)} observations extracted from {source_count} sources")

    # --- Tape snapshot ---
    tape = _build_tape_snapshot(btc5_mkt, btc5_cn, wr)
    log_decision("tape_snapshot_built", "btc5 skip/fill rates and open positions summarised")

    # --- Settlement truth ---
    settlement = _build_settlement_truth(wr)
    log_decision("settlement_truth_built", "wallet reconciliation condensed")

    # --- Lifecycle events ---
    lifecycle = _build_lifecycle_events(fin, weather, btc5_cn)
    log_decision("lifecycle_events_built", f"{len(lifecycle)} lifecycle events extracted")

    artifact: dict[str, Any] = {
        "artifact": "sensorium_v1",
        "generated_at": now_iso,
        "source_count": source_count,
        "sources_attempted": list(SOURCES.keys()),
        "sources_loaded": [k for k, v in loaded.items() if v],
        "observations": observations,
        "lifecycle_events": lifecycle,
        "settlement_truth": settlement,
        "tape_snapshot": tape,
        "decision_log": decision_log,
    }

    return artifact


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Sensorium — evidence layer aggregator")
    parser.add_argument("--check-only", action="store_true",
                        help="Print summary without writing output file")
    args = parser.parse_args()

    artifact = build_sensorium(check_only=args.check_only)
    obs_count = len(artifact["observations"])
    source_count = artifact["source_count"]

    if args.check_only:
        print(json.dumps(artifact, indent=2, default=str))
        log.info("check-only: %d observations from %d sources (no write)", obs_count, source_count)
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialised = json.dumps(artifact, indent=2, default=str)
    OUTPUT_PATH.write_text(serialised, encoding="utf-8")

    # Also write to the canonical kernel evidence_bundle path so that
    # run_kernel_cycle.py can discover freshness from its artifact_path.
    EVIDENCE_BUNDLE_PATH = PROJECT_ROOT / "reports" / "evidence_bundle.json"
    EVIDENCE_BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_BUNDLE_PATH.write_text(serialised, encoding="utf-8")

    # Compact status line
    signals = [o["signal"] for o in artifact["observations"]]
    positive = signals.count("positive")
    negative = signals.count("negative")
    stale_obs = sum(1 for o in artifact["observations"] if o["stale"])
    print(
        f"[sensorium] {obs_count} obs | sources={source_count}/6 "
        f"| +{positive} -{negative} stale={stale_obs} "
        f"| -> {OUTPUT_PATH.relative_to(PROJECT_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
