#!/usr/bin/env python3
"""Generate a public-safe JJ-N report artifact for the website."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.offers.website_growth_audit import website_growth_audit_offer
from nontrading.store import RevenueStore


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "revenue_agent.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_public_report.json"


def _headline(snapshot: dict[str, Any]) -> str:
    phase = snapshot["phase"]["current_phase"]
    if phase == "phase_0_revenue_evidence":
        return "JJ-N has repo-tracked revenue evidence and a live fulfillment queue to manage."
    if phase == "phase_0_offer_ready":
        return "JJ-N has a priced offer, proposal flow, and fulfillment telemetry, but closed-won revenue is still pending."
    if phase == "phase_0_outreach_active":
        return "JJ-N has a working outreach funnel and dashboard visibility, with revenue claims still blocked."
    if phase == "phase_0_pipeline_seeded":
        return "JJ-N is qualifying targets and instrumenting the first revenue wedge before live launch."
    if phase == "phase_0_research_active":
        return "JJ-N has researched accounts and a visible first wedge, but qualification, outreach, and revenue claims remain pre-launch."
    return "JJ-N is in setup mode with the Website Growth Audit as the first launch wedge."


def build_public_report(store: RevenueStore) -> dict[str, Any]:
    snapshot = store.public_report_snapshot()
    offer = website_growth_audit_offer()
    funnel = snapshot["funnel"]
    commercial = snapshot["commercial"]
    phase = snapshot["phase"]

    wedge_status = "launch_prep"
    if commercial["revenue_won_usd"] > 0:
        wedge_status = "revenue_evidence"
    elif funnel["proposals_sent"] > 0:
        wedge_status = "proposal_ready"
    elif funnel["delivered_messages"] > 0:
        wedge_status = "outreach_active"
    elif funnel["qualified_accounts"] > 0:
        wedge_status = "qualified_pipeline_seeded"

    return {
        **snapshot,
        "headline": {
            "title": "JJ-N Website Growth Audit",
            "summary": _headline(snapshot),
            "current_phase": phase["current_phase"],
            "claim_status": phase["claim_status"],
        },
        "wedge": {
            "offer_name": offer.name,
            "offer_slug": offer.slug,
            "description": offer.description,
            "price_range_usd": {"low": offer.price_range[0], "high": offer.price_range[1]},
            "delivery_days": offer.delivery_days,
            "fulfillment_type": offer.fulfillment_type,
            "funnel_stages": list(offer.funnel_stages),
            "provisioning": dict(offer.fulfillment_provisioning),
            "status": wedge_status,
            "live_send_status": snapshot["fulfillment"]["delivery_claim_status"],
            "claim_status": phase["claim_status"],
        },
        "source_artifacts": {
            "primary_store": snapshot["source_snapshot"]["db_path"],
            "telemetry_dataset": snapshot["source_snapshot"]["telemetry_dataset"],
            "report_artifact": str(DEFAULT_OUTPUT_PATH),
        },
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to the JJ-N revenue SQLite database.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Where to write the public-safe report artifact (default: {DEFAULT_OUTPUT_PATH}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = RevenueStore(args.db_path)
    report = build_public_report(store)
    write_report(report, args.output)
    print(f"Wrote JJ-N public report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
