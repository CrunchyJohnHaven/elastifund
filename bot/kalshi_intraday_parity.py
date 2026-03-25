"""Kalshi intraday parity surface + cross-venue match audit (Instance #4)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from bot.kalshi_auth import load_kalshi_credentials
from bot.cross_platform_arb import fetch_polymarket_markets, title_similarity
from kalshi.weather_arb import fetch_open_markets, get_kalshi_client

REPORTS_DIR = Path("reports")
TITLE_MATCH_THRESHOLD = 0.70
MAX_ACCEPTED_SPREAD = 0.12
MIN_VISIBLE_VOLUME = 100.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_suffix(now: Optional[datetime] = None) -> str:
    return (now or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_prob(value: Any) -> Optional[float]:
    raw = _safe_float(value, default=-1.0)
    if raw < 0.0:
        return None
    if raw > 1.0:
        raw = raw / 100.0
    return max(0.0, min(1.0, raw))


def parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def infer_asset(text: str) -> Optional[str]:
    lowered = text.lower()
    if "bitcoin" in lowered or re.search(r"\bbtc\b", lowered):
        return "BTC"
    if "ethereum" in lowered or re.search(r"\beth\b", lowered):
        return "ETH"
    if "crypto" in lowered:
        return "CRYPTO"
    return None


def classify_contract_shape(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("between", "or lower", "or higher", "above", "below", ">=", "<=")):
        return "range"
    return "binary"


def horizon_bucket(hours: float) -> Optional[str]:
    if hours <= 0:
        return None
    if hours <= 3.0:
        return "3h"
    if hours <= 24.0:
        return "24h"
    return None


def infer_intraday_hours_from_text(text: str) -> Optional[float]:
    lowered = text.lower()
    if any(token in lowered for token in ("5m", "5 min", "5-minute")):
        return 5.0 / 60.0
    if any(token in lowered for token in ("15m", "15 min", "15-minute")):
        return 15.0 / 60.0
    if any(token in lowered for token in ("hourly", "1h", "1 hour", "every hour")):
        return 1.0
    if "intraday" in lowered or "today" in lowered:
        return 12.0
    if "tomorrow" in lowered:
        return 24.0
    return None


def _priority_rank(asset: str, text: str) -> int:
    lowered = text.lower()
    btc_hourly = asset == "BTC" and (
        "hourly" in lowered or re.search(r"\b1h\b", lowered) or "hour" in lowered
    )
    btc_15m = asset == "BTC" and (
        "15m" in lowered or "15 min" in lowered or "15-minute" in lowered
    )
    if btc_hourly:
        return 0
    if btc_15m:
        return 1
    if asset == "BTC":
        return 2
    if asset == "ETH":
        return 3
    return 4


def compute_route_score_inputs(
    *,
    spread: float,
    visible_volume: float,
    horizon_hours: float,
    priority_rank: int,
) -> dict[str, float]:
    spread_quality = max(0.0, 1.0 - min(1.0, spread / 0.20))
    liquidity_score = min(1.0, visible_volume / 2000.0)
    horizon_quality = max(0.0, 1.0 - min(1.0, horizon_hours / 24.0))
    priority_boost = max(0.0, 1.0 - min(1.0, priority_rank / 5.0))
    return {
        "spread_quality": round(spread_quality, 6),
        "liquidity_score": round(liquidity_score, 6),
        "horizon_quality": round(horizon_quality, 6),
        "priority_boost": round(priority_boost, 6),
    }


def compute_route_score(inputs: dict[str, float]) -> float:
    score = (
        0.35 * float(inputs.get("spread_quality", 0.0))
        + 0.35 * float(inputs.get("liquidity_score", 0.0))
        + 0.20 * float(inputs.get("horizon_quality", 0.0))
        + 0.10 * float(inputs.get("priority_boost", 0.0))
    )
    return round(100.0 * score, 3)


def build_kalshi_candidate_record(raw_market: Any, *, now: datetime) -> Optional[dict[str, Any]]:
    ticker = str(_field(raw_market, "ticker", "") or "").strip()
    title = str(_field(raw_market, "title", "") or _field(raw_market, "subtitle", "") or ticker).strip()
    if not ticker or not title:
        return None

    combined_text = f"{ticker} {title}"
    asset = infer_asset(combined_text)
    if asset is None:
        return None

    close_time = parse_datetime(
        _field(raw_market, "close_time")
        or _field(raw_market, "expiration_time")
        or _field(raw_market, "settlement_time")
    )
    if close_time is not None:
        horizon_hours_value = (close_time - now).total_seconds() / 3600.0
    else:
        inferred_hours = infer_intraday_hours_from_text(combined_text)
        if inferred_hours is None:
            return None
        horizon_hours_value = inferred_hours
        close_time = now + timedelta(hours=inferred_hours)

    bucket = horizon_bucket(horizon_hours_value)
    if bucket is None:
        return None

    yes_bid = _to_prob(_field(raw_market, "yes_bid"))
    yes_ask = _to_prob(_field(raw_market, "yes_ask"))
    no_bid = _to_prob(_field(raw_market, "no_bid"))
    no_ask = _to_prob(_field(raw_market, "no_ask"))
    if yes_ask is None and no_ask is None:
        return None

    if yes_ask is None and no_bid is not None:
        yes_ask = max(0.01, min(0.99, 1.0 - no_bid))
    if no_ask is None and yes_bid is not None:
        no_ask = max(0.01, min(0.99, 1.0 - yes_bid))
    if yes_ask is None or no_ask is None:
        return None

    if yes_bid is None:
        yes_bid = max(0.0, min(yes_ask, yes_ask - 0.01))
    if no_bid is None:
        no_bid = max(0.0, min(no_ask, no_ask - 0.01))

    spread = max(0.0, yes_ask - yes_bid, no_ask - no_bid)
    visible_volume = _safe_float(_field(raw_market, "volume", 0.0), 0.0)
    if visible_volume <= 0:
        visible_volume = _safe_float(_field(raw_market, "open_interest", 0.0), 0.0)

    priority_rank = _priority_rank(asset, combined_text)
    route_score_inputs = compute_route_score_inputs(
        spread=spread,
        visible_volume=visible_volume,
        horizon_hours=horizon_hours_value,
        priority_rank=priority_rank,
    )

    return {
        "venue": "kalshi",
        "ticker": ticker,
        "title": title,
        "resolution_time": close_time.isoformat(),
        "resolution_horizon_hours": round(horizon_hours_value, 4),
        "horizon_bucket": bucket,
        "asset": asset,
        "best_yes": round(yes_ask, 6),
        "best_no": round(no_ask, 6),
        "spread": round(spread, 6),
        "visible_volume": round(visible_volume, 6),
        "fee_model": "kalshi_taker_fee=0.07*p*(1-p),maker=0",
        "route_score_inputs": route_score_inputs,
        "route_score": compute_route_score(route_score_inputs),
        "contract_shape": classify_contract_shape(combined_text),
        "liquidity_ok": spread <= MAX_ACCEPTED_SPREAD and visible_volume >= MIN_VISIBLE_VOLUME,
    }


def inspect_kalshi_market_rejection_reason(raw_market: Any, *, now: datetime) -> str:
    ticker = str(_field(raw_market, "ticker", "") or "").strip()
    title = str(_field(raw_market, "title", "") or _field(raw_market, "subtitle", "") or ticker).strip()
    if not ticker or not title:
        return "missing_identity"

    combined_text = f"{ticker} {title}"
    if infer_asset(combined_text) is None:
        return "non_crypto"

    close_time = parse_datetime(
        _field(raw_market, "close_time")
        or _field(raw_market, "expiration_time")
        or _field(raw_market, "settlement_time")
    )
    if close_time is not None:
        horizon_hours_value = (close_time - now).total_seconds() / 3600.0
    else:
        inferred = infer_intraday_hours_from_text(combined_text)
        if inferred is None:
            return "missing_resolution"
        horizon_hours_value = inferred

    if horizon_bucket(horizon_hours_value) is None:
        return "horizon_out_of_scope"

    yes_ask = _to_prob(_field(raw_market, "yes_ask"))
    no_ask = _to_prob(_field(raw_market, "no_ask"))
    yes_bid = _to_prob(_field(raw_market, "yes_bid"))
    no_bid = _to_prob(_field(raw_market, "no_bid"))

    can_derive_yes = yes_ask is None and no_bid is not None
    can_derive_no = no_ask is None and yes_bid is not None
    if (yes_ask is None and not can_derive_yes) or (no_ask is None and not can_derive_no):
        return "missing_prices"

    return "candidate"


def _build_polymarket_candidate_records(now: datetime, poly_markets: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for market in poly_markets:
        question = str(getattr(market, "title", "") or "").strip()
        market_id = str(getattr(market, "market_id", "") or "").strip()
        if not question or not market_id:
            continue
        asset = infer_asset(question)
        if asset is None:
            continue
        end_dt = parse_datetime(getattr(market, "end_date", None))
        if end_dt is None:
            continue
        horizon_hours_value = (end_dt - now).total_seconds() / 3600.0
        bucket = horizon_bucket(horizon_hours_value)
        if bucket is None:
            continue
        yes_ask = float(getattr(market, "yes_ask", 0.0) or 0.0)
        no_ask = float(getattr(market, "no_ask", 0.0) or 0.0)
        spread = max(
            0.0,
            float(getattr(market, "yes_ask", 0.0) or 0.0) - float(getattr(market, "yes_bid", 0.0) or 0.0),
            float(getattr(market, "no_ask", 0.0) or 0.0) - float(getattr(market, "no_bid", 0.0) or 0.0),
        )
        visible_volume = float(getattr(market, "volume", 0.0) or 0.0)
        candidates.append(
            {
                "venue": "polymarket",
                "ticker": market_id,
                "title": question,
                "resolution_time": end_dt.isoformat(),
                "resolution_horizon_hours": round(horizon_hours_value, 4),
                "horizon_bucket": bucket,
                "asset": asset,
                "best_yes": round(yes_ask, 6),
                "best_no": round(no_ask, 6),
                "spread": round(spread, 6),
                "visible_volume": round(visible_volume, 6),
                "contract_shape": classify_contract_shape(question),
                "normalized_title": str(getattr(market, "normalized_title", "")),
            }
        )
    return candidates


def _reason_key(record: dict[str, Any]) -> str:
    return f"{record.get('venue')}:{record.get('ticker')}"


def audit_crossvenue_matching(
    *,
    kalshi_candidates: list[dict[str, Any]],
    polymarket_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    title_matching_failures: list[dict[str, Any]] = []
    resolution_mismatch: list[dict[str, Any]] = []
    liquidity_failures: list[dict[str, Any]] = []
    contract_shape_mismatch: list[dict[str, Any]] = []
    viable_pairs: list[dict[str, Any]] = []

    for kalshi in kalshi_candidates:
        if not kalshi.get("liquidity_ok", False):
            liquidity_failures.append(
                {
                    "key": _reason_key(kalshi),
                    "spread": kalshi.get("spread"),
                    "visible_volume": kalshi.get("visible_volume"),
                }
            )

        peers = [pm for pm in polymarket_candidates if pm.get("asset") == kalshi.get("asset")]
        if not peers:
            title_matching_failures.append(
                {
                    "key": _reason_key(kalshi),
                    "reason": "no_polymarket_peer_for_asset",
                }
            )
            continue

        best_peer = None
        best_score = -1.0
        for peer in peers:
            score = title_similarity(kalshi.get("title", "").lower(), peer.get("title", "").lower())
            if score > best_score:
                best_score = score
                best_peer = peer

        if best_peer is None or best_score < TITLE_MATCH_THRESHOLD:
            title_matching_failures.append(
                {
                    "key": _reason_key(kalshi),
                    "best_score": round(max(best_score, 0.0), 4),
                    "peer": best_peer.get("ticker") if best_peer else None,
                }
            )
            continue

        kalshi_time = parse_datetime(kalshi.get("resolution_time"))
        poly_time = parse_datetime(best_peer.get("resolution_time"))
        resolution_delta_minutes = None
        if kalshi_time is not None and poly_time is not None:
            resolution_delta_minutes = abs((kalshi_time - poly_time).total_seconds()) / 60.0
            if resolution_delta_minutes > 45.0:
                resolution_mismatch.append(
                    {
                        "key": _reason_key(kalshi),
                        "peer": best_peer.get("ticker"),
                        "resolution_delta_minutes": round(resolution_delta_minutes, 3),
                    }
                )

        if kalshi.get("contract_shape") != best_peer.get("contract_shape"):
            contract_shape_mismatch.append(
                {
                    "key": _reason_key(kalshi),
                    "peer": best_peer.get("ticker"),
                    "kalshi_shape": kalshi.get("contract_shape"),
                    "polymarket_shape": best_peer.get("contract_shape"),
                }
            )

        if (
            bool(kalshi.get("liquidity_ok"))
            and (resolution_delta_minutes is None or resolution_delta_minutes <= 45.0)
            and kalshi.get("contract_shape") == best_peer.get("contract_shape")
        ):
            viable_pairs.append(
                {
                    "kalshi_ticker": kalshi.get("ticker"),
                    "polymarket_market_id": best_peer.get("ticker"),
                    "title_similarity": round(best_score, 4),
                    "resolution_delta_minutes": (
                        round(resolution_delta_minutes, 3) if resolution_delta_minutes is not None else None
                    ),
                }
            )

    return {
        "summary": {
            "kalshi_candidate_count": len(kalshi_candidates),
            "polymarket_candidate_count": len(polymarket_candidates),
            "viable_pair_count": len(viable_pairs),
            "low_value_or_zero_value": len(viable_pairs) == 0,
            "title_matching_failures": len(title_matching_failures),
            "resolution_normalization_failures": len(resolution_mismatch),
            "liquidity_filter_failures": len(liquidity_failures),
            "contract_shape_mismatch_failures": len(contract_shape_mismatch),
        },
        "title_matching": title_matching_failures[:25],
        "resolution_normalization": resolution_mismatch[:25],
        "liquidity_filters": liquidity_failures[:25],
        "contract_shape_mismatch": contract_shape_mismatch[:25],
        "viable_pairs": viable_pairs[:25],
    }


def validate_kalshi_auth_dryrun(*, max_pages: int = 1) -> dict[str, Any]:
    credentials_exist = load_kalshi_credentials().configured

    if not credentials_exist:
        return {
            "credentials_present": False,
            "status": "skipped_no_credentials",
            "details": (
                "KALSHI_API_KEY_ID and private key material are not both present; "
                "using public scan path."
            ),
        }

    try:
        session = get_kalshi_client(execute=False)
        markets = fetch_open_markets(session, max_pages=max_pages)
    except Exception as exc:  # pragma: no cover - network/auth variability
        return {
            "credentials_present": True,
            "status": "failed_dry_run",
            "details": f"dry-run auth validation failed: {exc}",
        }

    return {
        "credentials_present": True,
        "status": "ok_dry_run",
        "details": f"dry-run auth call succeeded; fetched {len(markets)} markets without placing orders.",
    }


@dataclass
class IntradayParityOutputs:
    surface_path: Path
    audit_path: Path
    surface_payload: dict[str, Any]
    audit_payload: dict[str, Any]


def run_intraday_parity(*, kalshi_pages: int = 2, polymarket_pages: int = 2) -> IntradayParityOutputs:
    now = utc_now()
    stamp = timestamp_suffix(now)

    session = get_kalshi_client(execute=False)
    raw_markets = fetch_open_markets(session, max_pages=kalshi_pages)
    rejection_counts: dict[str, int] = {}
    for raw_market in raw_markets:
        reason = inspect_kalshi_market_rejection_reason(raw_market, now=now)
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    kalshi_candidates = [
        candidate
        for candidate in (
            build_kalshi_candidate_record(raw_market, now=now) for raw_market in raw_markets
        )
        if candidate is not None
    ]
    kalshi_candidates.sort(
        key=lambda row: (_priority_rank(str(row.get("asset", "")), str(row.get("title", ""))), -float(row["route_score"]))
    )

    polymarket_raw = asyncio.run(fetch_polymarket_markets(max_pages=polymarket_pages))
    polymarket_candidates = _build_polymarket_candidate_records(now, polymarket_raw)
    audit = audit_crossvenue_matching(
        kalshi_candidates=kalshi_candidates,
        polymarket_candidates=polymarket_candidates,
    )
    auth_validation = validate_kalshi_auth_dryrun(max_pages=1)
    filter_rejection_total = sum(
        count
        for reason, count in rejection_counts.items()
        if reason in {"non_crypto", "missing_resolution", "horizon_out_of_scope", "missing_prices", "missing_identity"}
    )
    scanner_broken = len(raw_markets) == 0
    genuinely_not_tradeable = len(raw_markets) > 0 and len(kalshi_candidates) == 0 and filter_rejection_total > 0

    surface_payload = {
        "generated_at": now.isoformat(),
        "horizons": ["3h", "24h"],
        "priority_order": ["BTC_hourly", "BTC_15m", "BTC_other_intraday", "ETH_intraday", "other_crypto_intraday"],
        "counts": {
            "raw_open_markets": len(raw_markets),
            "intraday_candidates": len(kalshi_candidates),
            "bucket_3h": sum(1 for candidate in kalshi_candidates if candidate.get("horizon_bucket") == "3h"),
            "bucket_24h": sum(1 for candidate in kalshi_candidates if candidate.get("horizon_bucket") == "24h"),
        },
        "discovery_diagnostics": {
            "scanner_or_transport_broken": scanner_broken,
            "genuinely_not_tradeable_under_filters": genuinely_not_tradeable,
            "rejection_counts": rejection_counts,
        },
        "auth_validation": auth_validation,
        "candidates": kalshi_candidates,
    }

    category_assessment = {
        "title_matching": {
            "status": "not_evaluable" if len(kalshi_candidates) == 0 else "evaluated",
            "reason": (
                "no Kalshi intraday crypto candidates remained after discovery filters"
                if len(kalshi_candidates) == 0
                else "evaluated against Polymarket peers"
            ),
        },
        "resolution_normalization": {
            "status": "not_evaluable" if len(kalshi_candidates) == 0 else "evaluated",
            "reason": (
                "no matched candidate pairs to compare resolution clocks"
                if len(kalshi_candidates) == 0
                else "resolution deltas computed for title-matched pairs"
            ),
        },
        "liquidity_filters": {
            "status": "not_evaluable" if len(kalshi_candidates) == 0 else "evaluated",
            "reason": (
                "liquidity checks were skipped because candidate surface was empty"
                if len(kalshi_candidates) == 0
                else "spread/volume thresholds applied to each Kalshi candidate"
            ),
        },
        "contract_shape_mismatch": {
            "status": "not_evaluable" if len(kalshi_candidates) == 0 else "evaluated",
            "reason": (
                "no candidate pair survived to contract-shape comparison"
                if len(kalshi_candidates) == 0
                else "binary vs range mismatch audit applied to matched pairs"
            ),
        },
    }

    audit_payload = {
        "generated_at": now.isoformat(),
        "scope": "kalshi_intraday_vs_polymarket_intraday",
        "thresholds": {
            "title_match_threshold": TITLE_MATCH_THRESHOLD,
            "max_resolution_delta_minutes": 45.0,
            "max_spread": MAX_ACCEPTED_SPREAD,
            "min_visible_volume": MIN_VISIBLE_VOLUME,
        },
        "discovery_diagnostics": {
            "raw_open_markets": len(raw_markets),
            "rejection_counts": rejection_counts,
            "scanner_or_transport_broken": scanner_broken,
            "genuinely_not_tradeable_under_filters": genuinely_not_tradeable,
        },
        "category_assessment": category_assessment,
        "auth_validation": auth_validation,
        "audit": audit,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    surface_path = REPORTS_DIR / f"kalshi_intraday_surface_{stamp}.json"
    audit_path = REPORTS_DIR / f"crossvenue_match_audit_{stamp}.json"
    surface_path.write_text(json.dumps(surface_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return IntradayParityOutputs(
        surface_path=surface_path,
        audit_path=audit_path,
        surface_payload=surface_payload,
        audit_payload=audit_payload,
    )
