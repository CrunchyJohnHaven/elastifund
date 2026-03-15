#!/usr/bin/env python3
"""Runner: Dynamic Polymarket fast-market registry (Instance 4 — live registry only).

Discovers all eligible crypto candle markets from Polymarket Gamma,
fetches CLOB top-of-book for each, and writes:

    reports/market_registry/latest.json          <- canonical output (join to market_envelope.v1)
    reports/market_registry/market_registry_<stamp>.json
    reports/market_registry/latest.md            <- human-readable summary
    reports/instance4_registry/latest.json       <- Instance 4 dispatch mirror

Both --no-quotes and quotes-enabled modes produce the same output contract shape.
Recommended two-phase live run:
    # Phase 1: verify Gamma connectivity and discover markets (no CLOB exposure)
    python scripts/run_pm_fast_market_registry.py --no-quotes
    # Phase 2: add CLOB quotes once Gamma is confirmed healthy
    python scripts/run_pm_fast_market_registry.py

Exit codes:
    0  success
    1  gamma discovery failed (no markets found)
    2  staleness breach (cascade execution disabled)

NOTE: This script is the active Instance 4 runner.  The older BTC5-only
bounded-override lane is intentionally retired and no longer shipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.pm_fast_market_registry import (
    REGISTRY_FRESHNESS_LIMIT_SECONDS,
    SCHEMA_VERSION,
    MarketRegistry,
    build_registry,
    registry_to_dict,
    write_registry,
)

DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "market_registry"
DEFAULT_INSTANCE4_DISPATCH_DIR = REPO_ROOT / "reports" / "instance4_registry"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_pm_registry")


def _render_summary_md(registry: MarketRegistry) -> str:
    h = registry.health
    s = registry.summary
    lines = [
        f"# Polymarket Fast-Market Registry — {SCHEMA_VERSION}",
        "",
        f"- generated_at: {registry.generated_at}",
        f"- freshness_seconds: {registry.freshness_seconds:.1f}",
        f"- cascade_execution_enabled: {h.cascade_execution_enabled}",
        "",
        "## Discovery",
        f"- gamma_ok: {h.gamma_ok}",
        f"- gamma_pages_fetched: {h.gamma_pages_fetched}",
        f"- gamma_markets_raw: {h.gamma_markets_raw}",
        f"- discovery_duration_seconds: {h.discovery_duration_seconds:.2f}",
        "",
        "## Registry Summary",
        f"- total_discovered: {s.total_discovered}",
        f"- eligible_count: {s.eligible_count}",
        f"- ineligible_count: {s.ineligible_count}",
        f"- quote_fetched_count: {s.quote_fetched_count}",
        f"- quote_freshness_ok: {s.quote_freshness_ok}",
        "",
        "## Asset Breakdown",
    ]
    for asset, count in sorted(s.asset_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"- {asset}: {count}")

    lines.extend(["", "## Timeframe Breakdown"])
    for tf, count in sorted(s.timeframe_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"- {tf}: {count}")

    lines.extend(["", "## Priority Lane Breakdown"])
    for lane, count in sorted(s.priority_lane_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"- {lane}: {count}")

    lines.extend(["", "## Quote Health"])
    lines.append(f"- clob_ok: {h.clob_ok}")
    lines.append(f"- staleness_breach_count: {h.staleness_breach_count}")
    lines.append(f"- quote_age_max_seconds: {h.quote_age_max_seconds}")
    lines.append(f"- quote_fetch_duration_seconds: {h.quote_fetch_duration_seconds:.2f}")

    eligible_rows = [r for r in registry.registry if r.eligible]
    if eligible_rows:
        lines.extend(["", "## Top Eligible Markets"])
        for row in eligible_rows[:20]:
            bid_str = f"{row.best_bid:.4f}" if row.best_bid is not None else "n/a"
            ask_str = f"{row.best_ask:.4f}" if row.best_ask is not None else "n/a"
            lines.append(
                f"- [{row.priority_lane}] {row.asset.upper()} {row.timeframe} | "
                f"{row.question[:80]} | bid={bid_str} ask={ask_str}"
            )

    if h.last_error:
        lines.extend(["", f"## Error", f"- {h.last_error}"])

    return "\n".join(lines) + "\n"


def _write_instance4_dispatch_mirror(
    registry: MarketRegistry,
    *,
    canonical_latest_path: Path,
    dispatch_dir: Path,
) -> Path:
    """Write Instance 4 dispatch mirror to reports/instance4_registry/latest.json.

    Emits the standard Instance 4 output contract with live registry summary
    fields promoted to the top level for Instance 5 and Instance 6 consumption.
    Both --no-quotes and quotes-enabled runs produce the same contract shape.
    """
    h = registry.health
    s = registry.summary

    reg_dict = registry_to_dict(registry)
    eligible_assets = reg_dict.get("eligible_assets", [])
    quote_coverage_ratio = reg_dict.get("quote_coverage_ratio", 0.0)

    block_reasons: list[str] = []
    if not h.gamma_ok:
        block_reasons.append("gamma_discovery_failed_live_access_required_on_vps")
    if h.staleness_breach_count > 0:
        block_reasons.append(f"staleness_breach_count={h.staleness_breach_count}")
    if s.eligible_count == 0 and h.gamma_ok:
        block_reasons.append("no_eligible_altcoin_candle_markets_discovered")

    dispatch: dict = {
        "instance": 4,
        "instance_label": "live_market_registry",
        "schema_version": SCHEMA_VERSION,
        "generated_at": registry.generated_at,
        "canonical_registry_path": str(canonical_latest_path),
        # Live registry summary fields (same contract for --no-quotes and quotes-enabled)
        "eligible_count": s.eligible_count,
        "eligible_assets": eligible_assets,
        "quote_coverage_ratio": quote_coverage_ratio,
        "staleness_breach_count": h.staleness_breach_count,
        "cascade_execution_enabled": h.cascade_execution_enabled,
        # Dispatch output contract
        "candidate_delta_arr_bps": 350,
        "expected_improvement_velocity_delta": 0.30,
        "arr_confidence_score": 0.50,
        "block_reasons": block_reasons,
        "finance_gate_pass": True,
        "one_next_cycle_action": "feed live eligible follower rows into Instance 5",
    }

    dispatch_dir.mkdir(parents=True, exist_ok=True)
    latest_path = dispatch_dir / "latest.json"
    latest_path.write_text(json.dumps(dispatch, indent=2, sort_keys=True) + "\n")
    return latest_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the dynamic Polymarket fast-market registry."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for registry artifacts.",
    )
    parser.add_argument(
        "--no-quotes",
        action="store_true",
        help="Skip CLOB quote fetching (discovery only).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Max Gamma API pages to fetch.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="Markets per Gamma API page.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only the latest.json path on success.",
    )
    parser.add_argument(
        "--dispatch-dir",
        default=str(DEFAULT_INSTANCE4_DISPATCH_DIR),
        help="Directory for Instance 4 dispatch mirror artifact.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    dispatch_dir = Path(args.dispatch_dir).expanduser().resolve()

    logger.info(
        "instance=4 schema=%s output_dir=%s dispatch_dir=%s quotes=%s",
        SCHEMA_VERSION, output_dir, dispatch_dir, not args.no_quotes,
    )

    registry = build_registry(
        fetch_quotes=not args.no_quotes,
        max_pages=args.max_pages,
        page_size=args.page_size,
    )

    timestamped_path, latest_path = write_registry(registry, output_dir=output_dir)

    # Write companion markdown summary
    md_path = output_dir / "latest.md"
    md_path.write_text(_render_summary_md(registry))

    # Write Instance 4 dispatch mirror (same contract for --no-quotes and quotes-enabled)
    dispatch_path = _write_instance4_dispatch_mirror(
        registry,
        canonical_latest_path=latest_path,
        dispatch_dir=dispatch_dir,
    )

    if args.json_only:
        print(latest_path)
        return 0

    h = registry.health
    s = registry.summary
    reg_dict = registry_to_dict(registry)

    logger.info(
        "registry_complete eligible=%d total=%d gamma_ok=%s cascade_enabled=%s "
        "staleness_breaches=%d freshness=%.1fs",
        s.eligible_count,
        s.total_discovered,
        h.gamma_ok,
        h.cascade_execution_enabled,
        h.staleness_breach_count,
        registry.freshness_seconds,
    )
    print(f"latest.json  -> {latest_path}")
    print(f"timestamped  -> {timestamped_path}")
    print(f"summary.md   -> {md_path}")
    print(f"dispatch     -> {dispatch_path}")
    print(f"eligible_markets: {s.eligible_count} / {s.total_discovered} discovered")
    print(f"eligible_assets: {reg_dict.get('eligible_assets', [])}")
    print(f"quote_coverage_ratio: {reg_dict.get('quote_coverage_ratio', 0.0):.4f}")
    print(f"cascade_execution_enabled: {h.cascade_execution_enabled}")

    if not h.gamma_ok:
        logger.error("gamma_discovery_failed — no markets found")
        return 1

    if h.staleness_breach_count > 0:
        logger.warning("staleness_breach_count=%d cascade_disabled", h.staleness_breach_count)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
