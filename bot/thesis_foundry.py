#!/usr/bin/env python3
"""Thesis Foundry: converts lane shadow artifacts into ranked thesis candidates.

Reads:
- reports/parallel/instance04_weather_divergence_shadow.json  (weather shadow)
- reports/autoresearch/latest.json                             (BTC5 autoresearch)

Produces:
- reports/autoresearch/thesis_candidates.json

Each thesis candidate is a concrete, ranked trade hypothesis from a specific lane.
The supervisor reads this artifact to select which candidates to route for execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_WEATHER_SHADOW_PATH = (
    REPO_ROOT / "reports" / "parallel" / "instance04_weather_divergence_shadow.json"
)
DEFAULT_BTC5_AUTORESEARCH_PATH = REPO_ROOT / "reports" / "autoresearch" / "latest.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "autoresearch" / "thesis_candidates.json"

# Artifacts older than this are flagged stale (2 hours)
WEATHER_STALE_THRESHOLD_SECONDS = 7200
BTC5_STALE_THRESHOLD_SECONDS = 86400


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _artifact_age_seconds(payload: dict[str, Any], now: datetime) -> float | None:
    ts = payload.get("generated_at")
    if not ts:
        return None
    try:
        generated = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (now - generated).total_seconds()
    except Exception:
        return None


def _weather_to_theses(payload: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    age = _artifact_age_seconds(payload, now)
    stale = age is not None and age > WEATHER_STALE_THRESHOLD_SECONDS

    candidate_rows = (payload.get("market_scan") or {}).get("candidate_rows") or []
    theses: list[dict[str, Any]] = []

    for row in candidate_rows:
        edge_info = row.get("edge") or {}
        spread_adj_edge = edge_info.get("spread_adjusted_edge")
        if spread_adj_edge is None:
            continue

        ticker = str(row.get("ticker") or "")
        thesis: dict[str, Any] = {
            "thesis_id": f"weather:kalshi:{ticker}",
            "lane": "weather",
            "venue": "kalshi",
            "ticker": ticker,
            "event_ticker": row.get("event_ticker"),
            "title": row.get("title"),
            "side": edge_info.get("preferred_side"),
            "model_probability": row.get("model_probability"),
            "market_type": row.get("market_type"),
            "target_date": row.get("target_date"),
            "spread_adjusted_edge": spread_adj_edge,
            "execution_mode": "shadow",
            "source_artifact": "instance04_weather_divergence_shadow",
            "artifact_age_seconds": round(age, 1) if age is not None else None,
            "artifact_stale": stale,
            "city": (row.get("settlement_source") or {}).get("city"),
            "generated_at": _iso_z(now),
            "rank_score": float(spread_adj_edge),
        }
        theses.append(thesis)

    return sorted(theses, key=lambda t: t["rank_score"], reverse=True)


def _btc5_to_thesis(payload: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    age = _artifact_age_seconds(payload, now)
    stale = age is not None and age > BTC5_STALE_THRESHOLD_SECONDS

    policy_champion = (payload.get("current_champions") or {}).get("policy") or {}
    if not policy_champion:
        return []

    return [
        {
            "thesis_id": f"btc5:policy:{policy_champion.get('id', 'unknown')}",
            "lane": "btc5",
            "venue": "polymarket",
            "ticker": "BTC_5MIN",
            "event_ticker": None,
            "title": "BTC 5-minute maker strategy",
            "side": "down_biased",
            "model_probability": None,
            "market_type": "crypto_maker",
            "target_date": None,
            "spread_adjusted_edge": None,
            "execution_mode": "live",
            "source_artifact": "btc5_dual_autoresearch_surface",
            "artifact_age_seconds": round(age, 1) if age is not None else None,
            "artifact_stale": stale,
            "city": None,
            "generated_at": _iso_z(now),
            "rank_score": 0.05,
            "policy_champion_loss": policy_champion.get("loss"),
            "policy_champion_updated_at": policy_champion.get("updated_at"),
        }
    ]


def build_thesis_candidates(
    *,
    weather_shadow_path: Path = DEFAULT_WEATHER_SHADOW_PATH,
    btc5_autoresearch_path: Path = DEFAULT_BTC5_AUTORESEARCH_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    weather_payload = _read_json(weather_shadow_path)
    btc5_payload = _read_json(btc5_autoresearch_path)

    weather_theses = _weather_to_theses(weather_payload, now)
    btc5_theses = _btc5_to_thesis(btc5_payload, now)

    all_theses = weather_theses + btc5_theses
    all_theses.sort(key=lambda t: float(t.get("rank_score") or 0.0), reverse=True)

    lane_summaries: dict[str, Any] = {}
    for thesis in all_theses:
        lane = thesis["lane"]
        if lane not in lane_summaries:
            lane_summaries[lane] = {
                "count": 0,
                "top_edge": None,
                "execution_mode": thesis["execution_mode"],
            }
        lane_summaries[lane]["count"] += 1
        edge = thesis.get("rank_score")
        if edge is not None:
            current = lane_summaries[lane]["top_edge"]
            if current is None or edge > current:
                lane_summaries[lane]["top_edge"] = edge

    weather_age = _artifact_age_seconds(weather_payload, now)
    btc5_age = _artifact_age_seconds(btc5_payload, now)

    return {
        "artifact": "thesis_candidates.v1",
        "generated_at": _iso_z(now),
        "thesis_count": len(all_theses),
        "lane_summaries": lane_summaries,
        "candidates": all_theses,
        "sources": {
            "weather_shadow": {
                "path": str(weather_shadow_path),
                "loaded": bool(weather_payload),
                "artifact_name": weather_payload.get("artifact"),
                "age_seconds": round(weather_age, 1) if weather_age is not None else None,
                "stale": weather_age is not None and weather_age > WEATHER_STALE_THRESHOLD_SECONDS,
            },
            "btc5_autoresearch": {
                "path": str(btc5_autoresearch_path),
                "loaded": bool(btc5_payload),
                "artifact_name": btc5_payload.get("artifact"),
                "age_seconds": round(btc5_age, 1) if btc5_age is not None else None,
                "stale": btc5_age is not None and btc5_age > BTC5_STALE_THRESHOLD_SECONDS,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-shadow", type=Path, default=DEFAULT_WEATHER_SHADOW_PATH)
    parser.add_argument("--btc5-autoresearch", type=Path, default=DEFAULT_BTC5_AUTORESEARCH_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    payload = build_thesis_candidates(
        weather_shadow_path=args.weather_shadow,
        btc5_autoresearch_path=args.btc5_autoresearch,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lane_str = ", ".join(
        f"{lane}={info['count']}" for lane, info in payload["lane_summaries"].items()
    )
    print(f"Wrote {args.output} — {payload['thesis_count']} candidates ({lane_str})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
