"""Forecast and recurring-monitor helpers for the JJ-N ARR lab."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nontrading.offers.website_growth_audit import ServiceOffer

UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_arr_lab" / "latest.json"
DEFAULT_LAUNCH_BRIDGE_PATH = PROJECT_ROOT / "reports" / "nontrading" / "revenue_audit_launch_bridge.json"
DEFAULT_LAUNCH_BATCH_SEED_PATH = PROJECT_ROOT / "reports" / "nontrading" / "revenue_audit_launch_batch_seed.json"
DEFAULT_CYCLE_REPORT_PATH = PROJECT_ROOT / "reports" / "nontrading" / "website_growth_audit_cycle_reports.jsonl"
DEFAULT_RECURRING_MONITOR_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_recurring_monitor" / "latest.json"
SCHEMA_VERSION = "nontrading_arr_lab.v1"
RECURRING_MONITOR_SCHEMA_VERSION = "nontrading_recurring_monitor.v1"
SIMULATION_SEED = 20260310
SIMULATION_TRIALS = 2000
DEFAULT_GROSS_MARGIN_PCT = 0.60
DEFAULT_OPERATING_COST_USD_30D = 12.0


def utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _round_rate(value: float) -> float:
    return round(float(value), 6)


def _canonical_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        host = parsed.netloc.strip().lower()
        path = parsed.path.strip().rstrip("/")
        if host.startswith("www."):
            host = host[4:]
        return f"{host}{path}"
    return text.replace("www.", "").rstrip("/")


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    if not payload.get("source_artifact"):
        payload["source_artifact"] = str(path)
    return payload


def load_launch_bridge_payload(path: Path = DEFAULT_LAUNCH_BRIDGE_PATH) -> dict[str, Any] | None:
    return _load_optional_json(path)


def load_recurring_monitor_payload(path: Path = DEFAULT_RECURRING_MONITOR_OUTPUT_PATH) -> dict[str, Any] | None:
    return _load_optional_json(path)


def load_cycle_reports(path: Path = DEFAULT_CYCLE_REPORT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_seed_records(path: Path = DEFAULT_LAUNCH_BATCH_SEED_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def _enrich_bridge_prospects(prospects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seed_records = _load_seed_records()
    seed_by_url = {_canonical_key(record.get("website_url")): record for record in seed_records}
    seed_by_company = {_canonical_key(record.get("company_name")): record for record in seed_records}
    enriched: list[dict[str, Any]] = []
    for raw in prospects:
        prospect = dict(raw)
        seed = seed_by_url.get(_canonical_key(prospect.get("website_url"))) or seed_by_company.get(
            _canonical_key(prospect.get("company_name"))
        )
        if seed:
            for key in ("segment", "city", "state", "country_code"):
                if not prospect.get(key) and seed.get(key):
                    prospect[key] = seed[key]
        enriched.append(prospect)
    return enriched


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return _round_money(ordered[0])
    index = int(round((len(ordered) - 1) * _clamp(q)))
    return _round_money(ordered[index])


def _rate_band(base: float, *, down: float, up: float, low: float = 0.0, high: float = 1.0) -> dict[str, float]:
    return {
        "p05": _round_rate(_clamp(base * down, low, high)),
        "p50": _round_rate(_clamp(base, low, high)),
        "p95": _round_rate(_clamp(base * up, low, high)),
    }


def _currency_band(base: float, *, down: float, up: float, low: float = 0.0) -> dict[str, float]:
    return {
        "p05": _round_money(max(low, base * down)),
        "p50": _round_money(max(low, base)),
        "p95": _round_money(max(low, base * up)),
    }


def _confidence_label(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _prospect_pool(
    *,
    snapshot: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    bridge_payload: Mapping[str, Any] | None,
    offer: ServiceOffer,
) -> dict[str, Any]:
    raw_prospects = (
        bridge_payload.get("prospects", [])
        if isinstance(bridge_payload, Mapping) and isinstance(bridge_payload.get("prospects"), Sequence)
        else []
    )
    prospects = _enrich_bridge_prospects(
        [item for item in raw_prospects if isinstance(item, Mapping)]
    )
    fallback_count = max(
        1,
        _safe_int(snapshot.get("funnel", {}).get("qualified_accounts")),
        _safe_int(launch_summary.get("selected_prospects")),
    )
    if not prospects:
        prospects = [
            {
                "company_name": f"Qualified prospect {index + 1}",
                "fit_score": 72.0,
                "estimated_value_usd": float(sum(offer.price_range) / 2),
                "recommended_price_tier": {
                    "label": "standard",
                    "price_usd": float(sum(offer.price_range) / 2),
                },
                "segment": "unknown",
                "city": None,
                "state": None,
                "country_code": "US",
                "evidence": (),
            }
            for index in range(fallback_count)
        ]

    normalized_prospects: list[dict[str, Any]] = []
    segment_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    city_counts: Counter[str] = Counter()
    price_counts: Counter[str] = Counter()
    price_total = 0.0
    fit_total = 0.0
    value_total = 0.0
    fit_segment_totals: dict[str, float] = {}
    value_segment_totals: dict[str, float] = {}
    count_segment_totals: dict[str, int] = {}

    for raw in prospects:
        tier = raw.get("recommended_price_tier") if isinstance(raw.get("recommended_price_tier"), Mapping) else {}
        price = _safe_float(tier.get("price_usd"), float(sum(offer.price_range) / 2))
        price = max(price, float(offer.price_range[0]))
        label = str(tier.get("label") or ("premium" if price >= offer.price_range[1] else "standard")).strip().lower()
        fit_score = _clamp(_safe_float(raw.get("fit_score"), 72.0), 0.0, 100.0)
        evidence_items = raw.get("evidence")
        evidence_count = (
            len(evidence_items)
            if isinstance(evidence_items, Sequence) and not isinstance(evidence_items, (str, bytes))
            else 0
        )
        estimated_value = max(_safe_float(raw.get("estimated_value_usd"), price), price)
        value_ratio = _clamp(estimated_value / max(price, 1.0), 0.8, 1.35)
        segment = str(raw.get("segment") or "unknown").strip().lower() or "unknown"
        city = str(raw.get("city") or "unknown").strip().title() or "Unknown"
        state = str(raw.get("state") or "unknown").strip().upper() or "UNKNOWN"

        normalized = {
            "company_name": str(raw.get("company_name") or "").strip() or "Unknown prospect",
            "fit_score": round(fit_score, 2),
            "estimated_value_usd": _round_money(estimated_value),
            "value_ratio": _round_rate(value_ratio),
            "price_usd": _round_money(price),
            "price_label": label,
            "evidence_count": evidence_count,
            "segment": segment,
            "city": city,
            "state": state,
        }
        normalized_prospects.append(normalized)
        segment_counts[segment] += 1
        city_counts[city] += 1
        state_counts[state] += 1
        price_counts[label] += 1
        fit_total += fit_score
        value_total += estimated_value
        price_total += price
        fit_segment_totals[segment] = fit_segment_totals.get(segment, 0.0) + fit_score
        value_segment_totals[segment] = value_segment_totals.get(segment, 0.0) + estimated_value
        count_segment_totals[segment] = count_segment_totals.get(segment, 0) + 1

    selected_prospects = max(len(normalized_prospects), _safe_int(launch_summary.get("selected_prospects")))
    curated_candidates = max(
        selected_prospects,
        _safe_int((bridge_payload or {}).get("curated_candidates")),
        _safe_int(launch_summary.get("curated_candidates")),
    )
    segments = [
        {
            "segment": segment,
            "count": count_segment_totals[segment],
            "share": _round_rate(count_segment_totals[segment] / max(len(normalized_prospects), 1)),
            "avg_fit_score": round(fit_segment_totals[segment] / count_segment_totals[segment], 2),
            "avg_estimated_value_usd": _round_money(value_segment_totals[segment] / count_segment_totals[segment]),
        }
        for segment in sorted(count_segment_totals)
    ]
    return {
        "prospects": normalized_prospects,
        "selected_prospects": selected_prospects,
        "curated_candidates": curated_candidates,
        "price_mix": {
            label: {
                "count": count,
                "share": _round_rate(count / max(len(normalized_prospects), 1)),
            }
            for label, count in sorted(price_counts.items())
        },
        "average_fit_score": round(fit_total / max(len(normalized_prospects), 1), 2),
        "average_price_usd": _round_money(price_total / max(len(normalized_prospects), 1)),
        "average_estimated_value_usd": _round_money(value_total / max(len(normalized_prospects), 1)),
        "segment_mix": segments,
        "city_mix": dict(city_counts),
        "state_mix": dict(state_counts),
        "price_counts": dict(price_counts),
    }


def _cycle_history_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cycles = [dict(row) for row in rows if isinstance(row, Mapping)]
    total_cycles = len(cycles)
    sums = {
        "accounts_researched": 0.0,
        "qualified_accounts": 0.0,
        "outreach_sent": 0.0,
        "meetings_booked": 0.0,
        "proposals_sent": 0.0,
        "outcomes_won": 0.0,
        "scanned_leads": 0.0,
        "skipped_existing": 0.0,
    }
    for row in cycles:
        for key in sums:
            sums[key] += _safe_float(row.get(key))
    qualified_accounts = sums["qualified_accounts"]
    proposals_sent = sums["proposals_sent"]
    outcomes_won = sums["outcomes_won"]
    meetings_booked = sums["meetings_booked"]
    return {
        "cycles_observed": total_cycles,
        "accounts_researched": _safe_int(sums["accounts_researched"]),
        "qualified_accounts": _safe_int(qualified_accounts),
        "outreach_sent": _safe_int(sums["outreach_sent"]),
        "meetings_booked": _safe_int(meetings_booked),
        "proposals_sent": _safe_int(proposals_sent),
        "outcomes_won": _safe_int(outcomes_won),
        "scanned_leads": _safe_int(sums["scanned_leads"]),
        "skipped_existing": _safe_int(sums["skipped_existing"]),
        "proposal_rate_observed": (
            _round_rate(proposals_sent / qualified_accounts) if qualified_accounts else None
        ),
        "meeting_rate_observed": (
            _round_rate(meetings_booked / qualified_accounts) if qualified_accounts else None
        ),
        "win_rate_observed": _round_rate(outcomes_won / proposals_sent) if proposals_sent else None,
    }


def build_recurring_monitor_summary(
    *,
    snapshot: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    offer: ServiceOffer,
    bridge_payload: Mapping[str, Any] | None = None,
    existing_payload: Mapping[str, Any] | None = None,
    output_path: Path = DEFAULT_RECURRING_MONITOR_OUTPUT_PATH,
) -> dict[str, Any]:
    pool = _prospect_pool(
        snapshot=snapshot,
        launch_summary=launch_summary,
        bridge_payload=bridge_payload,
        offer=offer,
    )
    existing = dict(existing_payload or {})
    monitor_runs_completed = max(
        _safe_int(snapshot.get("fulfillment", {}).get("monitor_runs_completed")),
        _safe_int(launch_summary.get("monitor_runs_completed")),
        _safe_int(existing.get("monitor_runs_completed")),
    )
    delivery_count = max(
        _safe_int(snapshot.get("fulfillment", {}).get("delivered_jobs")),
        _safe_int(launch_summary.get("delivery_artifacts_generated")),
        _safe_int(existing.get("delivered_audits")),
    )
    weighted_audit_price = max(pool["average_price_usd"], float(sum(offer.price_range) / 2))
    monthly_price = _safe_float(
        existing.get("monthly_price_usd"),
        round(max(149.0, min(699.0, round((weighted_audit_price * 0.20) / 50.0) * 50.0))),
    )
    active_enrollments = max(
        _safe_int(existing.get("active_enrollments")),
        _safe_int(existing.get("active_subscriptions")),
    )
    current_mrr = _safe_float(existing.get("current_mrr_usd"), active_enrollments * monthly_price)
    current_arr = _safe_float(existing.get("current_arr_usd"), current_mrr * 12.0)
    observed_upsell_rate = (
        _round_rate(monitor_runs_completed / delivery_count) if delivery_count else None
    )
    upsell_rate = observed_upsell_rate
    if upsell_rate is None:
        upsell_rate = _round_rate(0.22 if bool(launch_summary.get("launchable")) else 0.18)
    churn_rate_30d = _round_rate(_safe_float(existing.get("churn_rate_30d"), 0.08))
    refund_rate = _round_rate(_safe_float(existing.get("refund_rate"), 0.0))
    status = str(existing.get("status") or "").strip().lower()
    if not status:
        status = "live_contract" if active_enrollments > 0 else "assumption_only"

    return {
        "schema_version": RECURRING_MONITOR_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "status": status,
        "active_enrollments": active_enrollments,
        "monitor_runs_completed": monitor_runs_completed,
        "delivered_audits": delivery_count,
        "monthly_price_usd": _round_money(monthly_price),
        "current_mrr_usd": _round_money(current_mrr),
        "current_arr_usd": _round_money(current_arr),
        "refund_rate": refund_rate,
        "assumptions": {
            "upsell_rate": upsell_rate,
            "churn_rate_30d": churn_rate_30d,
            "price_anchor_ratio_to_audit": _round_rate(monthly_price / max(weighted_audit_price, 1.0)),
        },
        "source_artifact": str(existing.get("source_artifact") or output_path),
    }


def _launch_delay_days(launch_summary: Mapping[str, Any]) -> float:
    delay = 0.0
    if not bool(launch_summary.get("checkout_ready")):
        delay += 2.0
    if not bool(launch_summary.get("webhook_ready")):
        delay += 2.0
    if not bool(launch_summary.get("manual_close_ready")):
        delay += 1.5
    if not bool(launch_summary.get("fulfillment_ready")):
        delay += 1.0
    return round(delay, 2)


def _base_assumptions(
    *,
    snapshot: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    cycle_summary: Mapping[str, Any],
    pool: Mapping[str, Any],
    recurring_monitor_payload: Mapping[str, Any],
    offer: ServiceOffer,
) -> dict[str, Any]:
    commercial = dict(snapshot.get("commercial") or {})
    launch_mode = str(launch_summary.get("launch_mode") or "manual_close_only").strip().lower()
    avg_fit = _safe_float(pool.get("average_fit_score"), 72.0) / 100.0
    avg_value = _safe_float(pool.get("average_estimated_value_usd"), float(sum(offer.price_range) / 2))
    avg_price = _safe_float(pool.get("average_price_usd"), float(sum(offer.price_range) / 2))
    value_ratio = _clamp(avg_value / max(avg_price, 1.0), 0.8, 1.35)
    proposal_rate_observed = cycle_summary.get("proposal_rate_observed")
    proposal_prior = 0.24 + (avg_fit * 0.08)
    proposal_rate = (
        (0.7 * _safe_float(proposal_rate_observed)) + (0.3 * proposal_prior)
        if proposal_rate_observed is not None
        else proposal_prior
    )
    proposal_rate = _clamp(proposal_rate, 0.12, 0.55)

    checkout_sessions = _safe_int(launch_summary.get("checkout_sessions_created"))
    paid_orders_seen = _safe_int(launch_summary.get("paid_orders_seen"))
    payment_conversion_observed = (
        _safe_float(paid_orders_seen / checkout_sessions)
        if checkout_sessions > 0
        else None
    )
    payment_proxy = _clamp(0.16 + (avg_fit * 0.26) + ((value_ratio - 1.0) * 0.18), 0.12, 0.52)
    proposal_to_payment_rate = (
        _clamp((0.65 * _safe_float(payment_conversion_observed)) + (0.35 * payment_proxy), 0.12, 0.65)
        if payment_conversion_observed is not None
        else payment_proxy
    )

    refund_rate = launch_summary.get("refund_rate")
    if refund_rate is None:
        refund_rate = 0.03 if paid_orders_seen > 0 else 0.05
    refund_rate = _clamp(_safe_float(refund_rate), 0.0, 0.3)

    gross_margin_pct = _safe_float(commercial.get("gross_margin_pct"), DEFAULT_GROSS_MARGIN_PCT)
    if gross_margin_pct <= 0:
        gross_margin_pct = DEFAULT_GROSS_MARGIN_PCT
    gross_margin_pct = _clamp(gross_margin_pct, 0.2, 0.9)

    launch_delay_days = _launch_delay_days(launch_summary)
    base_close_days = 5.0 if launch_mode == "manual_close_only" else 6.0
    observed_time_to_cash_days = _safe_float(commercial.get("time_to_first_dollar_hours"), 0.0) / 24.0
    time_to_cash_days = observed_time_to_cash_days if observed_time_to_cash_days > 0 else base_close_days + launch_delay_days
    time_to_cash_days = max(1.0, time_to_cash_days)

    operating_cost_usd_30d = max(
        DEFAULT_OPERATING_COST_USD_30D,
        _safe_float(launch_summary.get("operating_cost_usd_30d"), DEFAULT_OPERATING_COST_USD_30D),
    )
    monthly_monitor_price = max(99.0, _safe_float(recurring_monitor_payload.get("monthly_price_usd"), 0.0))
    monitor_upsell_rate = _clamp(
        _safe_float(
            recurring_monitor_payload.get("assumptions", {}).get("upsell_rate"),
            0.18,
        ),
        0.05,
        0.6,
    )
    churn_rate_30d = _clamp(
        _safe_float(
            recurring_monitor_payload.get("assumptions", {}).get("churn_rate_30d"),
            0.08,
        ),
        0.0,
        0.3,
    )
    execution_fraction = _clamp((30.0 - launch_delay_days) / 30.0, 0.2, 1.0)

    return {
        "proposal_rate": proposal_rate,
        "proposal_to_payment_rate": proposal_to_payment_rate,
        "refund_rate": refund_rate,
        "gross_margin_pct": gross_margin_pct,
        "time_to_cash_days": time_to_cash_days,
        "launch_delay_days": launch_delay_days,
        "execution_fraction": execution_fraction,
        "monitor_upsell_rate": monitor_upsell_rate,
        "monitor_monthly_price_usd": monthly_monitor_price,
        "monitor_churn_rate_30d": churn_rate_30d,
        "operating_cost_usd_30d": operating_cost_usd_30d,
    }


def _working_prospects(pool: Mapping[str, Any]) -> list[dict[str, Any]]:
    prospects = [dict(item) for item in pool.get("prospects", []) if isinstance(item, Mapping)]
    if not prospects:
        return []
    target = max(
        len(prospects),
        _safe_int(pool.get("selected_prospects")) + max(
            0,
            round(
                (
                    _safe_int(pool.get("curated_candidates")) - _safe_int(pool.get("selected_prospects"))
                )
                * 0.5
            ),
        ),
    )
    working = sorted(prospects, key=lambda item: (_safe_float(item.get("fit_score")), _safe_float(item.get("price_usd"))), reverse=True)
    while len(working) < target:
        working.append(dict(working[len(working) % max(len(prospects), 1)]))
    return working[:target]


def _simulate_distribution(
    *,
    snapshot: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    pool: Mapping[str, Any],
    recurring_monitor_payload: Mapping[str, Any],
    assumptions: Mapping[str, Any],
    offer: ServiceOffer,
) -> dict[str, Any]:
    commercial = dict(snapshot.get("commercial") or {})
    working_prospects = _working_prospects(pool)
    rng = random.Random(SIMULATION_SEED)
    baseline_cash = max(
        _safe_float(commercial.get("gross_margin_usd")),
        _safe_float(launch_summary.get("paid_revenue_usd")) * _safe_float(assumptions.get("gross_margin_pct"), DEFAULT_GROSS_MARGIN_PCT),
    )
    baseline_arr = _safe_float(recurring_monitor_payload.get("current_arr_usd"))
    baseline_mrr = _safe_float(recurring_monitor_payload.get("current_mrr_usd"))

    cash_results: list[float] = []
    arr_results: list[float] = []
    one_time_results: list[float] = []
    recurring_cash_results: list[float] = []
    orders_results: list[float] = []
    monitor_results: list[float] = []
    mrr_results: list[float] = []

    for _ in range(SIMULATION_TRIALS):
        proposal_rate = rng.triangular(
            _safe_float(assumptions["proposal_rate"]) * 0.65,
            _safe_float(assumptions["proposal_rate"]) * 1.25,
            _safe_float(assumptions["proposal_rate"]),
        )
        proposal_rate = _clamp(proposal_rate, 0.05, 0.95)
        payment_rate = rng.triangular(
            _safe_float(assumptions["proposal_to_payment_rate"]) * 0.7,
            _safe_float(assumptions["proposal_to_payment_rate"]) * 1.25,
            _safe_float(assumptions["proposal_to_payment_rate"]),
        )
        payment_rate = _clamp(payment_rate, 0.05, 0.95)
        refund_rate = rng.triangular(
            _safe_float(assumptions["refund_rate"]) * 0.5,
            _safe_float(assumptions["refund_rate"]) * 1.5,
            _safe_float(assumptions["refund_rate"]),
        )
        refund_rate = _clamp(refund_rate, 0.0, 0.5)
        upsell_rate = rng.triangular(
            _safe_float(assumptions["monitor_upsell_rate"]) * 0.6,
            _safe_float(assumptions["monitor_upsell_rate"]) * 1.5,
            _safe_float(assumptions["monitor_upsell_rate"]),
        )
        upsell_rate = _clamp(upsell_rate, 0.01, 0.9)
        churn_rate = rng.triangular(
            _safe_float(assumptions["monitor_churn_rate_30d"]) * 0.6,
            _safe_float(assumptions["monitor_churn_rate_30d"]) * 1.4,
            _safe_float(assumptions["monitor_churn_rate_30d"]),
        )
        churn_rate = _clamp(churn_rate, 0.0, 0.4)
        monthly_monitor_price = rng.triangular(
            _safe_float(assumptions["monitor_monthly_price_usd"]) * 0.85,
            _safe_float(assumptions["monitor_monthly_price_usd"]) * 1.15,
            _safe_float(assumptions["monitor_monthly_price_usd"]),
        )
        time_to_cash_days = rng.triangular(
            max(1.0, _safe_float(assumptions["time_to_cash_days"]) * 0.6),
            min(30.0, _safe_float(assumptions["time_to_cash_days"]) * 1.5),
            _safe_float(assumptions["time_to_cash_days"]),
        )

        one_time_cash = 0.0
        recurring_cash = 0.0
        arr_total = baseline_arr
        mrr_total = baseline_mrr
        orders = 0
        monitor_signups = 0

        for prospect in working_prospects:
            fit_modifier = 0.75 + (_safe_float(prospect.get("fit_score"), 72.0) / 100.0) * 0.45
            evidence_modifier = 0.92 + min(_safe_int(prospect.get("evidence_count")), 4) * 0.03
            price_modifier = 0.93 if str(prospect.get("price_label")) == "premium" else 1.03
            value_modifier = 0.9 + min(_safe_float(prospect.get("value_ratio"), 1.0), 1.25) * 0.15
            proposal_probability = _clamp(
                proposal_rate * fit_modifier * evidence_modifier * _safe_float(assumptions["execution_fraction"]),
                0.01,
                0.95,
            )
            if rng.random() >= proposal_probability:
                continue

            payment_probability = _clamp(
                payment_rate * fit_modifier * price_modifier * value_modifier,
                0.01,
                0.95,
            )
            if rng.random() >= payment_probability:
                continue

            cash_day = _safe_float(assumptions["launch_delay_days"]) + time_to_cash_days
            if cash_day > 30.0:
                continue

            orders += 1
            sale_cash = _safe_float(prospect.get("price_usd")) * _safe_float(assumptions["gross_margin_pct"])
            if rng.random() < refund_rate:
                sale_cash = 0.0
            one_time_cash += sale_cash

            if cash_day + offer.delivery_days > 30.0:
                continue

            upsell_probability = _clamp(
                upsell_rate * fit_modifier * (0.98 if str(prospect.get("price_label")) == "premium" else 1.02),
                0.01,
                0.9,
            )
            if rng.random() >= upsell_probability:
                continue

            monitor_signups += 1
            recurring_cash += monthly_monitor_price
            if rng.random() >= churn_rate:
                mrr_total += monthly_monitor_price
                arr_total += monthly_monitor_price * 12.0

        total_cash = baseline_cash + one_time_cash + recurring_cash - _safe_float(assumptions["operating_cost_usd_30d"])
        cash_results.append(total_cash)
        arr_results.append(arr_total)
        one_time_results.append(one_time_cash)
        recurring_cash_results.append(recurring_cash)
        orders_results.append(float(orders))
        monitor_results.append(float(monitor_signups))
        mrr_results.append(mrr_total)

    def _scenario(q: float) -> dict[str, Any]:
        return {
            "net_cash_30d": _quantile(cash_results, q),
            "arr_usd": _quantile(arr_results, q),
            "mrr_usd": _quantile(mrr_results, q),
            "one_time_cash_30d": _quantile(one_time_results, q),
            "recurring_cash_30d": _quantile(recurring_cash_results, q),
            "orders": _quantile(orders_results, q),
            "monitor_signups": _quantile(monitor_results, q),
        }

    def _mean(values: Sequence[float]) -> float:
        if not values:
            return 0.0
        return _round_money(sum(values) / len(values))

    return {
        "trials": SIMULATION_TRIALS,
        "seed": SIMULATION_SEED,
        "expected": {
            "net_cash_30d": _mean(cash_results),
            "arr_usd": _mean(arr_results),
            "mrr_usd": _mean(mrr_results),
            "one_time_cash_30d": _mean(one_time_results),
            "recurring_cash_30d": _mean(recurring_cash_results),
            "orders": _mean(orders_results),
            "monitor_signups": _mean(monitor_results),
        },
        "scenarios": {
            "p05": _scenario(0.05),
            "p50": _scenario(0.50),
            "p95": _scenario(0.95),
        },
    }


def _expected_values(
    *,
    prospects: Sequence[Mapping[str, Any]],
    assumptions: Mapping[str, Any],
    recurring_monitor_payload: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, float]:
    commercial = dict(snapshot.get("commercial") or {})
    baseline_cash = max(
        _safe_float(commercial.get("gross_margin_usd")),
        _safe_float(launch_summary.get("paid_revenue_usd")) * _safe_float(assumptions.get("gross_margin_pct"), DEFAULT_GROSS_MARGIN_PCT),
    )
    baseline_arr = _safe_float(recurring_monitor_payload.get("current_arr_usd"))
    baseline_mrr = _safe_float(recurring_monitor_payload.get("current_mrr_usd"))

    expected_orders = 0.0
    expected_monitor_signups = 0.0
    expected_one_time_cash = 0.0
    expected_recurring_cash = 0.0
    for raw in prospects:
        prospect = dict(raw)
        fit_modifier = 0.75 + (_safe_float(prospect.get("fit_score"), 72.0) / 100.0) * 0.45
        evidence_modifier = 0.92 + min(_safe_int(prospect.get("evidence_count")), 4) * 0.03
        price_modifier = 0.93 if str(prospect.get("price_label")) == "premium" else 1.03
        value_modifier = 0.9 + min(_safe_float(prospect.get("value_ratio"), 1.0), 1.25) * 0.15
        proposal_probability = _clamp(
            _safe_float(assumptions["proposal_rate"]) * fit_modifier * evidence_modifier * _safe_float(assumptions["execution_fraction"]),
            0.01,
            0.95,
        )
        payment_probability = _clamp(
            _safe_float(assumptions["proposal_to_payment_rate"]) * fit_modifier * price_modifier * value_modifier,
            0.01,
            0.95,
        )
        order_probability = proposal_probability * payment_probability
        expected_orders += order_probability
        sale_cash = _safe_float(prospect.get("price_usd")) * _safe_float(assumptions["gross_margin_pct"]) * (1.0 - _safe_float(assumptions["refund_rate"]))
        expected_one_time_cash += order_probability * sale_cash
        upsell_probability = _clamp(
            _safe_float(assumptions["monitor_upsell_rate"]) * fit_modifier * (0.98 if str(prospect.get("price_label")) == "premium" else 1.02),
            0.01,
            0.9,
        )
        expected_monitor_signups += order_probability * upsell_probability
        expected_recurring_cash += (
            order_probability
            * upsell_probability
            * _safe_float(assumptions["monitor_monthly_price_usd"])
        )
    mrr = baseline_mrr + (expected_monitor_signups * _safe_float(assumptions["monitor_monthly_price_usd"]) * (1.0 - _safe_float(assumptions["monitor_churn_rate_30d"])))
    arr = baseline_arr + (mrr - baseline_mrr) * 12.0
    return {
        "net_cash_30d": _round_money(
            baseline_cash + expected_one_time_cash + expected_recurring_cash - _safe_float(assumptions["operating_cost_usd_30d"])
        ),
        "arr_usd": _round_money(arr),
        "mrr_usd": _round_money(mrr),
        "orders": _round_money(expected_orders),
        "monitor_signups": _round_money(expected_monitor_signups),
    }


def _confidence(
    *,
    snapshot: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    pool: Mapping[str, Any],
    cycle_summary: Mapping[str, Any],
    recurring_monitor_payload: Mapping[str, Any],
) -> dict[str, Any]:
    commercial = dict(snapshot.get("commercial") or {})
    blocker_count = len(launch_summary.get("blocking_reasons") or [])
    score = 0.12
    score += min(0.22, _safe_int(pool.get("selected_prospects")) / 40.0)
    score += min(0.18, _safe_int(cycle_summary.get("cycles_observed")) / 150.0)
    if cycle_summary.get("proposal_rate_observed") is not None:
        score += 0.08
    if _safe_int(launch_summary.get("paid_orders_seen")) > 0:
        score += 0.18
    if _safe_float(commercial.get("revenue_won_usd")) > 0.0:
        score += 0.18
    if _safe_int(recurring_monitor_payload.get("active_enrollments")) > 0:
        score += 0.10
    score += 0.05 if bool(launch_summary.get("launchable")) else 0.0
    score -= min(0.22, blocker_count * 0.06)
    if str(recurring_monitor_payload.get("status") or "").strip().lower() == "assumption_only":
        score -= 0.08
    final_score = _round_rate(_clamp(score, 0.05, 0.95))

    drivers: list[str] = []
    if _safe_int(pool.get("selected_prospects")) > 0:
        drivers.append(f"{_safe_int(pool.get('selected_prospects'))} staged prospects are already in the bridge artifact.")
    if _safe_int(cycle_summary.get("cycles_observed")) > 0:
        drivers.append(f"{_safe_int(cycle_summary.get('cycles_observed'))} cycle reports anchor the funnel-rate assumptions.")
    if blocker_count > 0:
        drivers.append(f"{blocker_count} launch blockers still widen the time-to-cash spread.")
    if _safe_int(launch_summary.get("paid_orders_seen")) == 0:
        drivers.append("No paid checkout evidence exists yet, so conversion remains partially assumption-driven.")
    if str(recurring_monitor_payload.get("status") or "").strip().lower() == "assumption_only":
        drivers.append("Recurring-monitor ARR is still modeled from an assumption-only contract.")

    return {
        "score": final_score,
        "label": _confidence_label(final_score),
        "drivers": drivers,
    }


def _rank_experiments(
    *,
    prospects: Sequence[Mapping[str, Any]],
    assumptions: Mapping[str, Any],
    recurring_monitor_payload: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    baseline = _expected_values(
        prospects=prospects,
        assumptions=assumptions,
        recurring_monitor_payload=recurring_monitor_payload,
        launch_summary=launch_summary,
        snapshot=snapshot,
    )

    def _with_updates(**updates: Any) -> dict[str, Any]:
        return {**assumptions, **updates}

    price_improved_prospects: list[dict[str, Any]] = []
    for raw in prospects:
        prospect = dict(raw)
        if str(prospect.get("price_label")) == "standard":
            prospect["price_label"] = "premium"
            prospect["price_usd"] = _round_money(_safe_float(prospect.get("price_usd")) * 1.25)
            prospect["estimated_value_usd"] = _round_money(_safe_float(prospect.get("estimated_value_usd")) * 1.12)
        price_improved_prospects.append(prospect)

    more_prospects = list(prospects)
    if more_prospects:
        while len(more_prospects) < len(prospects) + max(3, round(len(prospects) * 0.5)):
            more_prospects.append(dict(more_prospects[len(more_prospects) % len(prospects)]))

    segment_mix = [item for item in pool.get("segment_mix", []) if isinstance(item, Mapping) and str(item.get("segment")) != "unknown"]
    top_segment = None
    if segment_mix:
        top_segment = max(
            segment_mix,
            key=lambda item: (_safe_float(item.get("avg_fit_score")), _safe_float(item.get("avg_estimated_value_usd"))),
        )
    segment_prospects = list(prospects)
    if top_segment is not None:
        segment_name = str(top_segment.get("segment"))
        segment_candidates = [dict(item) for item in prospects if str(item.get("segment")) == segment_name]
        if segment_candidates:
            segment_prospects = [dict(segment_candidates[index % len(segment_candidates)]) for index in range(len(prospects))]

    experiment_specs = [
        {
            "experiment_key": "more_prospects",
            "label": "Expand the staged prospect pool",
            "assumptions": assumptions,
            "prospects": more_prospects,
            "information_gain": 0.48 if _safe_int(pool.get("curated_candidates")) < 20 else 0.32,
            "reason": "More curated prospects increase order surface area without changing the current offer.",
        },
        {
            "experiment_key": "better_price_mix",
            "label": "Improve the price mix",
            "assumptions": _with_updates(
                proposal_to_payment_rate=_clamp(_safe_float(assumptions["proposal_to_payment_rate"]) * 0.97, 0.05, 0.95),
            ),
            "prospects": price_improved_prospects,
            "information_gain": 0.34,
            "reason": "Moving more wins into premium pricing grows cash faster but slightly tests close-rate elasticity.",
        },
        {
            "experiment_key": "better_conversion_packet",
            "label": "Tighten the teaser and proposal packet",
            "assumptions": _with_updates(
                proposal_rate=_clamp(_safe_float(assumptions["proposal_rate"]) * 1.22, 0.05, 0.95),
                proposal_to_payment_rate=_clamp(_safe_float(assumptions["proposal_to_payment_rate"]) * 1.18, 0.05, 0.95),
                time_to_cash_days=max(1.0, _safe_float(assumptions["time_to_cash_days"]) * 0.9),
            ),
            "prospects": prospects,
            "information_gain": 0.72 if _safe_int(launch_summary.get("paid_orders_seen")) == 0 else 0.40,
            "reason": "The current bridge already has evidence-backed prospects, so better pre-payment packaging has the shortest path to first cash.",
        },
        {
            "experiment_key": "better_monitor_upsell",
            "label": "Strengthen the recurring-monitor upsell",
            "assumptions": _with_updates(
                monitor_upsell_rate=_clamp(_safe_float(assumptions["monitor_upsell_rate"]) * 1.55, 0.01, 0.95),
                monitor_monthly_price_usd=_safe_float(assumptions["monitor_monthly_price_usd"]) * 1.1,
            ),
            "prospects": prospects,
            "information_gain": 0.68 if str(recurring_monitor_payload.get("status")) == "assumption_only" else 0.38,
            "reason": "Recurring-monitor ARR remains the least proven part of the wedge, so even small win-rate improvements compound into ARR quickly.",
        },
        {
            "experiment_key": "better_segment",
            "label": "Concentrate on the strongest segment",
            "assumptions": _with_updates(
                proposal_rate=_clamp(_safe_float(assumptions["proposal_rate"]) * 1.08, 0.05, 0.95),
                proposal_to_payment_rate=_clamp(_safe_float(assumptions["proposal_to_payment_rate"]) * 1.08, 0.05, 0.95),
            ),
            "prospects": segment_prospects,
            "information_gain": 0.64 if top_segment is not None else 0.42,
            "reason": (
                f"Current seeds suggest {top_segment.get('segment')} is the strongest segment to double down on."
                if top_segment is not None
                else "Segment metadata is still thin, so a targeted segment pass is mostly an information-gain play."
            ),
        },
    ]

    ranked: list[dict[str, Any]] = []
    for spec in experiment_specs:
        expected = _expected_values(
            prospects=spec["prospects"],
            assumptions=spec["assumptions"],
            recurring_monitor_payload=recurring_monitor_payload,
            launch_summary=launch_summary,
            snapshot=snapshot,
        )
        arr_lift = _round_money(expected["arr_usd"] - baseline["arr_usd"])
        cash_lift = _round_money(expected["net_cash_30d"] - baseline["net_cash_30d"])
        ranked.append(
            {
                "experiment_key": spec["experiment_key"],
                "label": spec["label"],
                "expected_arr_lift_usd": arr_lift,
                "expected_net_cash_lift_usd_30d": cash_lift,
                "information_gain": _round_rate(spec["information_gain"]),
                "reason": spec["reason"],
            }
        )

    ranked.sort(
        key=lambda item: (
            _safe_float(item.get("expected_arr_lift_usd")),
            _safe_float(item.get("expected_net_cash_lift_usd_30d")),
            _safe_float(item.get("information_gain")),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    recommended = ranked[0] if ranked else {}
    return ranked, recommended


def build_arr_lab(
    *,
    snapshot: Mapping[str, Any],
    operations: Mapping[str, Any],
    launch_summary: Mapping[str, Any],
    offer: ServiceOffer,
    launch_bridge_payload: Mapping[str, Any] | None = None,
    cycle_reports: Sequence[Mapping[str, Any]] | None = None,
    recurring_monitor_payload: Mapping[str, Any] | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    bridge_payload = dict(launch_bridge_payload or load_launch_bridge_payload() or {})
    cycle_rows = list(cycle_reports) if cycle_reports is not None else load_cycle_reports()
    recurring_payload = dict(recurring_monitor_payload or {})
    pool = _prospect_pool(
        snapshot=snapshot,
        launch_summary=launch_summary,
        bridge_payload=bridge_payload,
        offer=offer,
    )
    cycle_summary = _cycle_history_summary(cycle_rows)
    assumptions = _base_assumptions(
        snapshot=snapshot,
        launch_summary=launch_summary,
        cycle_summary=cycle_summary,
        pool=pool,
        recurring_monitor_payload=recurring_payload,
        offer=offer,
    )
    simulation = _simulate_distribution(
        snapshot=snapshot,
        launch_summary=launch_summary,
        pool=pool,
        recurring_monitor_payload=recurring_payload,
        assumptions=assumptions,
        offer=offer,
    )
    experiments, recommended = _rank_experiments(
        prospects=[dict(item) for item in _working_prospects(pool)],
        assumptions=assumptions,
        recurring_monitor_payload=recurring_payload,
        launch_summary=launch_summary,
        snapshot=snapshot,
        pool=pool,
    )
    confidence = _confidence(
        snapshot=snapshot,
        launch_summary=launch_summary,
        pool=pool,
        cycle_summary=cycle_summary,
        recurring_monitor_payload=recurring_payload,
    )

    scenarios = simulation["scenarios"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "status": "forecast_ready",
        "window_days": 30,
        "confidence": confidence,
        "inputs": {
            "launch_truth": {
                "status": str(snapshot.get("first_dollar_readiness", {}).get("status") or "setup_only"),
                "launch_mode": str(launch_summary.get("launch_mode") or "manual_close_only"),
                "launchable": bool(launch_summary.get("launchable")),
                "blocking_reasons": list(launch_summary.get("blocking_reasons") or []),
                "launch_delay_days": _round_money(_safe_float(assumptions["launch_delay_days"])),
            },
            "prospect_pool": {
                "selected_prospects": _safe_int(pool.get("selected_prospects")),
                "curated_candidates": _safe_int(pool.get("curated_candidates")),
                "average_fit_score": _safe_float(pool.get("average_fit_score")),
                "average_price_usd": _safe_float(pool.get("average_price_usd")),
                "average_estimated_value_usd": _safe_float(pool.get("average_estimated_value_usd")),
                "price_mix": pool.get("price_mix", {}),
                "segment_mix": pool.get("segment_mix", []),
            },
            "cycle_history": cycle_summary,
            "operations": {
                "deliverability_status": operations.get("deliverability_status"),
                "latest_cycle_time_seconds": operations.get("revenue_pipeline", {}).get("latest_cycle_time_seconds"),
                "monitor_runs_completed": _safe_int(recurring_payload.get("monitor_runs_completed")),
            },
            "recurring_monitor": {
                "status": recurring_payload.get("status"),
                "monthly_price_usd": recurring_payload.get("monthly_price_usd"),
                "current_arr_usd": recurring_payload.get("current_arr_usd"),
            },
        },
        "assumptions": {
            "proposal_rate": _rate_band(_safe_float(assumptions["proposal_rate"]), down=0.65, up=1.25, low=0.05, high=0.95),
            "proposal_to_payment_rate": _rate_band(
                _safe_float(assumptions["proposal_to_payment_rate"]),
                down=0.7,
                up=1.25,
                low=0.05,
                high=0.95,
            ),
            "refund_rate": _rate_band(_safe_float(assumptions["refund_rate"]), down=0.5, up=1.5, low=0.0, high=0.5),
            "gross_margin_pct": _rate_band(_safe_float(assumptions["gross_margin_pct"]), down=0.9, up=1.05, low=0.2, high=0.9),
            "time_to_cash_days": _currency_band(_safe_float(assumptions["time_to_cash_days"]), down=0.6, up=1.5, low=1.0),
            "launch_delay_days": _currency_band(_safe_float(assumptions["launch_delay_days"]), down=0.75, up=1.25, low=0.0),
            "monitor_upsell_rate": _rate_band(
                _safe_float(assumptions["monitor_upsell_rate"]),
                down=0.6,
                up=1.5,
                low=0.01,
                high=0.95,
            ),
            "monitor_monthly_price_usd": _currency_band(
                _safe_float(assumptions["monitor_monthly_price_usd"]),
                down=0.85,
                up=1.15,
                low=99.0,
            ),
            "monitor_churn_rate_30d": _rate_band(
                _safe_float(assumptions["monitor_churn_rate_30d"]),
                down=0.6,
                up=1.4,
                low=0.0,
                high=0.4,
            ),
            "operating_cost_usd_30d": _currency_band(
                _safe_float(assumptions["operating_cost_usd_30d"]),
                down=0.9,
                up=1.1,
                low=DEFAULT_OPERATING_COST_USD_30D,
            ),
        },
        "simulation": simulation,
        "summary": {
            "p05_net_cash_30d": scenarios["p05"]["net_cash_30d"],
            "p50_net_cash_30d": scenarios["p50"]["net_cash_30d"],
            "p95_net_cash_30d": scenarios["p95"]["net_cash_30d"],
            "p05_arr_usd": scenarios["p05"]["arr_usd"],
            "p50_arr_usd": scenarios["p50"]["arr_usd"],
            "p95_arr_usd": scenarios["p95"]["arr_usd"],
            "recommended_experiment": recommended.get("experiment_key"),
        },
        "experiments": experiments,
        "recommended_next_experiment": recommended,
        "allocator_metadata": {
            "forecast_net_cash_30d_p50": scenarios["p50"]["net_cash_30d"],
            "forecast_arr_usd_p50": scenarios["p50"]["arr_usd"],
            "forecast_confidence": confidence["score"],
            "forecast_confidence_label": confidence["label"],
            "recommended_experiment": recommended.get("experiment_key"),
        },
        "source_artifacts": {
            "launch_summary": str(launch_summary.get("source_artifact") or ""),
            "launch_bridge": str(bridge_payload.get("source_artifact") or DEFAULT_LAUNCH_BRIDGE_PATH),
            "cycle_reports": str(DEFAULT_CYCLE_REPORT_PATH),
            "recurring_monitor": str(recurring_payload.get("source_artifact") or DEFAULT_RECURRING_MONITOR_OUTPUT_PATH),
            "public_report": str(output_path.parent.parent / "nontrading_public_report.json"),
            "arr_lab": str(output_path),
        },
    }


def write_json_artifact(payload: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
