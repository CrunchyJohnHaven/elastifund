#!/usr/bin/env python3
"""Audit the current neg-risk universe for cheapest guaranteed-dollar constructions."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.clob_ws import BestBidAskStore
from signals.sum_violation.guaranteed_dollar import (
    GuaranteedDollarConfig,
    GuaranteedDollarPlan,
    GuaranteedDollarRanker,
    plan_to_dict,
)
from signals.sum_violation.sum_discovery import A6PriceSnapshotter, GammaEventDiscovery


EXCLUDED_CATEGORY_TERMS = (
    "sport",
    "crypto",
    "financial",
    "finance",
    "stock",
    "equity",
    "forex",
)
EXCLUDED_TAG_TERMS = (
    "sports",
    "nba",
    "nfl",
    "nhl",
    "mlb",
    "soccer",
    "basketball",
    "football",
    "baseball",
    "crypto",
    "bitcoin",
    "ethereum",
)
EXCLUDED_TITLE_TERMS = (
    "nba",
    "nfl",
    "nhl",
    "mlb",
    "fifa",
    "world cup",
    "division winner",
    "group a winner",
    "group b winner",
    "group c winner",
    "group d winner",
    "market cap",
    " ipo ",
    "ipo ",
    " bitcoin ",
    " ethereum ",
)


def _category(raw_event: dict[str, Any]) -> str:
    return str(raw_event.get("eventCategory") or raw_event.get("category") or "").strip()


def _allowed_event(raw_event: dict[str, Any]) -> bool:
    category = _category(raw_event).lower()
    if any(term in category for term in EXCLUDED_CATEGORY_TERMS):
        return False

    title = f" {str(raw_event.get('title') or '').lower()} "
    slug = f" {str(raw_event.get('slug') or '').lower()} "
    if any(term in title or term in slug for term in EXCLUDED_TITLE_TERMS):
        return False

    tags = raw_event.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            haystack = " ".join(
                str(tag.get(key) or "").lower()
                for key in ("label", "slug")
            )
            if any(term in haystack for term in EXCLUDED_TAG_TERMS):
                return False
    return True


def _build_rows(plans: list[GuaranteedDollarPlan], watches: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for plan in plans:
        watch = watches[plan.event_id]
        category = _category(watch.raw_event)
        best = plan.best_construction
        row = {
            "event_id": plan.event_id,
            "title": plan.title,
            "category": category,
            "legs": len(watch.legs),
            "full_basket_cost": round(plan.full_basket_cost or 0.0, 6) if plan.full_basket_cost is not None else "",
            "best_type": best.construction_type if best else "",
            "best_label": best.label if best else "",
            "best_cost": round(best.top_of_book_cost, 6) if best else "",
            "best_maker_cost": round(best.maker_quote_cost, 6) if best else "",
            "gross_edge": round(best.gross_edge, 6) if best else "",
            "maker_gross_edge": round(best.maker_gross_edge, 6) if best else "",
            "ready": bool(best.readiness.ready) if best else False,
            "readiness_reasons": "|".join(best.readiness.reasons) if best else "",
            "size_verified": bool(best.readiness.size_verified) if best else False,
        }
        rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "event_id",
        "title",
        "category",
        "legs",
        "full_basket_cost",
        "best_type",
        "best_label",
        "best_cost",
        "best_maker_cost",
        "gross_edge",
        "maker_gross_edge",
        "ready",
        "readiness_reasons",
        "size_verified",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, plans: list[GuaranteedDollarPlan]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [plan_to_dict(plan) for plan in plans]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, rows: list[dict[str, Any]], plans: list[GuaranteedDollarPlan]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    type_counts: dict[str, int] = {}
    ready_count = 0
    executable_count = 0
    for plan in plans:
        best = plan.best_construction
        if best is None:
            continue
        type_counts[best.construction_type] = type_counts.get(best.construction_type, 0) + 1
        if best.readiness.ready:
            ready_count += 1
        if best.executable:
            executable_count += 1

    lines = [
        "# Guaranteed Dollar Audit",
        "",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Summary",
        "",
        f"- Allowed neg-risk events audited: {len(plans)}",
        f"- Executable-at-threshold events: {executable_count}",
        f"- Readiness-passing events: {ready_count}",
    ]
    for key in sorted(type_counts):
        lines.append(f"- Best construction `{key}`: {type_counts[key]}")

    lines.extend(
        [
            "",
            "## Top Events",
            "",
            "| Event | Category | Best Type | Cost | Edge | Ready | Reasons |",
            "|---|---|---|---:|---:|---|---|",
        ]
    )
    for row in sorted(rows, key=lambda item: (-(float(item["gross_edge"] or 0.0)), str(item["best_type"])))[:25]:
        lines.append(
            f"| {row['title'][:72]} "
            f"| {row['category'] or 'unknown'} "
            f"| {row['best_type'] or '-'} "
            f"| {row['best_cost'] or '-'} "
            f"| {row['gross_edge'] or '-'} "
            f"| {'yes' if row['ready'] else 'no'} "
            f"| {row['readiness_reasons'] or '-'} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-csv", default="reports/guaranteed_dollar_audit.csv")
    parser.add_argument("--output-json", default="reports/guaranteed_dollar_audit.json")
    parser.add_argument("--output-md", default="reports/guaranteed_dollar_audit.md")
    parser.add_argument("--detect-threshold", type=float, default=0.95)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--require-size-support", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    discovery = GammaEventDiscovery(max_pages=args.max_pages, page_size=args.page_size)
    snapshotter = A6PriceSnapshotter(use_book_fallback=False)
    quote_store = BestBidAskStore()
    watches = [watch for watch in discovery.build_watchlist() if _allowed_event(watch.raw_event)]
    snapshotter.refresh_store_with_no_tokens(watches, quote_store)

    ranker = GuaranteedDollarRanker(
        GuaranteedDollarConfig(
            detect_threshold=args.detect_threshold,
            require_size_support=bool(args.require_size_support),
        )
    )
    now_ts = time.time()
    plans = [ranker.evaluate_event(watch, quote_store, now_ts=now_ts) for watch in watches]
    plans = [plan for plan in plans if plan.best_construction is not None]
    rows = _build_rows(plans, {watch.event_id: watch for watch in watches})

    _write_csv(Path(args.output_csv), rows)
    _write_json(Path(args.output_json), plans)
    _write_markdown(Path(args.output_md), rows, plans)

    print(json.dumps(
        {
            "events_audited": len(watches),
            "plans_emitted": len(plans),
            "output_csv": args.output_csv,
            "output_json": args.output_json,
            "output_md": args.output_md,
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
