#!/usr/bin/env python3
"""Audit live template density for the narrowed B-1 dependency scope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.constraint_arb_engine import fetch_gamma_markets
from strategies.b1_dependency_graph import DependencyGraphBuilder
from strategies.b1_templates import build_templated_pairs, describe_market


EXCLUDED_CATEGORY_TERMS = ("sport", "crypto", "financial", "finance", "stock", "equity", "forex")


def _allowed(raw_market: dict[str, Any]) -> bool:
    category = str(raw_market.get("category") or raw_market.get("eventCategory") or "").lower()
    return not any(term in category for term in EXCLUDED_CATEGORY_TERMS)


def _write_json(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, rows: list[dict[str, Any]], family_counts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# B-1 Template Audit",
        "",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Summary",
        "",
        f"- Template-compatible pairs: {len(rows)}",
    ]
    for family in sorted(family_counts):
        lines.append(f"- `{family}`: {family_counts[family]}")

    lines.extend(
        [
            "",
            "## Pairs",
            "",
            "| Family | Label | Market A | Market B | Rationale |",
            "|---|---|---|---|---|",
        ]
    )
    for row in rows[:50]:
        lines.append(
            f"| {row['family']} | {row['label']} | {row['left_title'][:60]} | {row['right_title'][:60]} | {row['rationale']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", default="reports/b1_template_audit.json")
    parser.add_argument("--output-md", default="reports/b1_template_audit.md")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--page-limit", type=int, default=200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_markets = [row for row in fetch_gamma_markets(max_pages=args.max_pages, page_limit=args.page_limit) if _allowed(row)]
    builder = DependencyGraphBuilder()
    metas = builder.refresh_markets(raw_markets)

    templated = build_templated_pairs(metas)
    rows: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    market_lookup = {meta.market_id: meta for meta in metas}
    for pair in templated:
        family_counts[pair.family] = family_counts.get(pair.family, 0) + 1
        rows.append(
            {
                "family": pair.family,
                "label": pair.label,
                "left_market_id": pair.left_market_id,
                "right_market_id": pair.right_market_id,
                "left_title": market_lookup[pair.left_market_id].question,
                "right_title": market_lookup[pair.right_market_id].question,
                "matrix": pair.matrix,
                "rationale": pair.rationale,
            }
        )

    template_market_counts: dict[str, int] = {}
    for meta in metas:
        descriptor = describe_market(meta)
        if descriptor is None:
            continue
        template_market_counts[descriptor.family] = template_market_counts.get(descriptor.family, 0) + 1

    payload = {
        "template_markets": template_market_counts,
        "template_pairs": rows,
    }
    _write_json(Path(args.output_json), payload)
    _write_markdown(Path(args.output_md), rows, family_counts)

    print(json.dumps(
        {
            "markets_scanned": len(metas),
            "template_pairs": len(rows),
            "output_json": args.output_json,
            "output_md": args.output_md,
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
