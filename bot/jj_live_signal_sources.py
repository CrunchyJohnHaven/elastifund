#!/usr/bin/env python3
"""Signal-source attribution helpers for JJ live trading."""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping


def extract_signal_source_components(
    payload: Mapping[str, Any] | None,
    *,
    canonical_source_key_fn: Callable[[str | None], str],
    normalize_source_components_fn: Callable[[Any], tuple[str, ...]],
) -> list[str]:
    """Return a stable, de-duplicated ordered source list for a signal payload."""
    if not isinstance(payload, Mapping):
        return []

    raw_components = payload.get("source_components")
    if raw_components in (None, "", [], (), set()):
        raw_components = payload.get("signal_sources")
    if raw_components in (None, "", [], (), set()):
        raw_components = payload.get("source_combo") or payload.get("source") or ""
    raw_iterable = normalize_source_components_fn(raw_components)

    components: list[str] = []
    seen: set[str] = set()
    for item in raw_iterable:
        normalized = canonical_source_key_fn(str(item or "").strip())
        if not normalized or normalized == "unknown":
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        components.append(normalized)
    return components


def extract_signal_sources(
    payload: Mapping[str, Any] | None,
    *,
    canonical_source_key_fn: Callable[[str | None], str],
    normalize_source_components_fn: Callable[[Any], tuple[str, ...]],
) -> list[str]:
    """Return canonical source aliases for persisted trade state."""
    return extract_signal_source_components(
        payload,
        canonical_source_key_fn=canonical_source_key_fn,
        normalize_source_components_fn=normalize_source_components_fn,
    )


def extract_signal_metadata(
    payload: Mapping[str, Any] | None,
    *,
    safe_float_fn: Callable[[Any, float | None], float | None],
    canonical_source_key_fn: Callable[[str | None], str],
    normalize_source_components_fn: Callable[[Any], tuple[str, ...]],
) -> dict[str, Any]:
    """Collect additive attribution metadata from a signal or trade payload."""
    if not isinstance(payload, Mapping):
        return {}

    metadata: dict[str, Any] = {}
    existing = payload.get("signal_metadata")
    if isinstance(existing, Mapping):
        for key, value in existing.items():
            if value is None:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            metadata[str(key)] = value

    sources = set(
        extract_signal_sources(
            payload,
            canonical_source_key_fn=canonical_source_key_fn,
            normalize_source_components_fn=normalize_source_components_fn,
        )
    )
    estimated_prob = safe_float_fn(payload.get("estimated_prob"), None)
    calibrated_prob = safe_float_fn(payload.get("calibrated_prob"), estimated_prob)
    raw_prob = safe_float_fn(payload.get("raw_prob"), None)
    confidence = safe_float_fn(payload.get("confidence"), None)
    edge = safe_float_fn(payload.get("edge"), None)

    if "llm" in sources:
        if calibrated_prob is not None:
            metadata.setdefault("llm_prob", round(calibrated_prob, 6))
        if raw_prob is not None:
            metadata.setdefault("llm_raw_prob", round(raw_prob, 6))

    if "wallet_flow" in sources:
        if confidence is not None:
            metadata.setdefault("wallet_consensus", round(confidence, 6))
        wallet_consensus_wallets = payload.get("wallet_consensus_wallets")
        if wallet_consensus_wallets is not None:
            try:
                metadata.setdefault(
                    "wallet_consensus_wallets",
                    int(float(wallet_consensus_wallets)),
                )
            except (TypeError, ValueError):
                pass
        wallet_consensus_notional_usd = safe_float_fn(
            payload.get("wallet_consensus_notional_usd"),
            None,
        )
        if wallet_consensus_notional_usd is not None:
            metadata.setdefault(
                "wallet_consensus_notional_usd",
                round(wallet_consensus_notional_usd, 6),
            )
        wallet_consensus_share = safe_float_fn(
            payload.get("wallet_consensus_share"),
            None,
        )
        if wallet_consensus_share is not None:
            metadata.setdefault(
                "wallet_consensus_share",
                round(wallet_consensus_share, 6),
            )
        wallet_opposition_wallets = payload.get("wallet_opposition_wallets")
        if wallet_opposition_wallets is not None:
            try:
                metadata.setdefault(
                    "wallet_opposition_wallets",
                    int(float(wallet_opposition_wallets)),
                )
            except (TypeError, ValueError):
                pass
        wallet_opposition_notional_usd = safe_float_fn(
            payload.get("wallet_opposition_notional_usd"),
            None,
        )
        if wallet_opposition_notional_usd is not None:
            metadata.setdefault(
                "wallet_opposition_notional_usd",
                round(wallet_opposition_notional_usd, 6),
            )
        wallet_signal_age_seconds = safe_float_fn(
            payload.get("wallet_signal_age_seconds"),
            None,
        )
        if wallet_signal_age_seconds is not None:
            metadata.setdefault(
                "wallet_signal_age_seconds",
                round(wallet_signal_age_seconds, 6),
            )
        wallet_window_start_ts = str(payload.get("wallet_window_start_ts") or "").strip()
        if wallet_window_start_ts:
            metadata.setdefault("wallet_window_start_ts", wallet_window_start_ts)
        wallet_window_minutes = payload.get("wallet_window_minutes")
        if wallet_window_minutes is not None:
            try:
                metadata.setdefault(
                    "wallet_window_minutes",
                    int(float(wallet_window_minutes)),
                )
            except (TypeError, ValueError):
                pass
        wallet_conflict_resolution = payload.get("wallet_conflict_resolution")
        if isinstance(wallet_conflict_resolution, Mapping):
            metadata.setdefault(
                "wallet_conflict_resolution",
                dict(wallet_conflict_resolution),
            )
        wallet_hydration_source = str(payload.get("wallet_hydration_source") or "").strip()
        if wallet_hydration_source:
            metadata.setdefault("wallet_hydration_source", wallet_hydration_source)
        wallet_hydrated_market_id = str(payload.get("wallet_hydrated_market_id") or "").strip()
        if wallet_hydrated_market_id:
            metadata.setdefault("wallet_hydrated_market_id", wallet_hydrated_market_id)

    if "lmsr" in sources and estimated_prob is not None:
        metadata.setdefault("lmsr_prob", round(estimated_prob, 6))

    if "lead_lag" in sources and confidence is not None:
        metadata.setdefault("lead_lag_confidence", round(confidence, 6))

    if "cross_platform_arb" in sources:
        if confidence is not None:
            metadata.setdefault("arb_match_score", round(confidence, 6))
        if edge is not None:
            metadata.setdefault("arb_net_profit_pct", round(edge, 6))
        arb_details = payload.get("arb_details")
        if isinstance(arb_details, Mapping):
            total_cost = safe_float_fn(arb_details.get("total_cost"), None)
            net_profit = safe_float_fn(arb_details.get("net_profit"), None)
            if total_cost is not None:
                metadata.setdefault("arb_total_cost", round(total_cost, 6))
            if net_profit is not None:
                metadata.setdefault("arb_net_profit", round(net_profit, 6))
            kalshi_ticker = str(arb_details.get("kalshi_ticker", "") or "").strip()
            if kalshi_ticker:
                metadata.setdefault("kalshi_ticker", kalshi_ticker)
            kalshi_side = str(arb_details.get("kalshi_side", "") or "").strip()
            if kalshi_side:
                metadata.setdefault("kalshi_side", kalshi_side)

    return metadata


def merge_signal_metadata(
    payloads: list[Mapping[str, Any] | None],
    *,
    safe_float_fn: Callable[[Any, float | None], float | None],
    canonical_source_key_fn: Callable[[str | None], str],
    normalize_source_components_fn: Callable[[Any], tuple[str, ...]],
) -> dict[str, Any]:
    """Merge per-source metadata across all confirming signal payloads."""
    merged: dict[str, Any] = {}
    for payload in payloads:
        merged.update(
            extract_signal_metadata(
                payload,
                safe_float_fn=safe_float_fn,
                canonical_source_key_fn=canonical_source_key_fn,
                normalize_source_components_fn=normalize_source_components_fn,
            )
        )
    return merged


def signal_has_source(
    payload: Mapping[str, Any] | None,
    source: str,
    *,
    canonical_source_key_fn: Callable[[str | None], str],
    normalize_source_components_fn: Callable[[Any], tuple[str, ...]],
) -> bool:
    """Check whether a signal payload contains a given source in its attribution set."""
    target = canonical_source_key_fn(source)
    if not target:
        return False
    return target in set(
        extract_signal_source_components(
            payload,
            canonical_source_key_fn=canonical_source_key_fn,
            normalize_source_components_fn=normalize_source_components_fn,
        )
    )
