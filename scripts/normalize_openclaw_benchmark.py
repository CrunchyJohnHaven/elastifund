#!/usr/bin/env python3
"""Normalize OpenClaw diagnostics into the shared benchmark evidence plane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inventory.systems.openclaw.adapter import (
    OPENCLAW_AUDITED_COMMIT,
    build_openclaw_benchmark_packet,
    load_jsonl_events,
    load_outcome_comparisons,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize OpenClaw diagnostics into a comparison-only evidence packet.",
    )
    parser.add_argument(
        "--diagnostics",
        required=True,
        help="Path to the OpenClaw diagnostic JSONL export.",
    )
    parser.add_argument(
        "--comparison",
        help="Optional JSON or JSONL file containing shared outcome comparisons.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Destination path for the normalized JSON artifact.",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Stable benchmark run identifier.",
    )
    parser.add_argument(
        "--namespace",
        default="openclaw-benchmark",
        help="Isolated AWS/Kubernetes namespace name.",
    )
    parser.add_argument(
        "--log-index-prefix",
        default="elastifund-openclaw-benchmark",
        help="Elastic/OpenTelemetry log index prefix reserved for this sibling stack.",
    )
    parser.add_argument(
        "--upstream-commit",
        default=OPENCLAW_AUDITED_COMMIT,
        help="Pinned upstream commit hash.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diagnostics_path = Path(args.diagnostics)
    comparison_path = Path(args.comparison) if args.comparison else None
    output_path = Path(args.output)

    diagnostics_events = load_jsonl_events(diagnostics_path)
    comparison_rows = load_outcome_comparisons(comparison_path) if comparison_path else []
    source_artifacts = [str(diagnostics_path)]
    if comparison_path is not None:
        source_artifacts.append(str(comparison_path))

    packet = build_openclaw_benchmark_packet(
        run_id=args.run_id,
        diagnostics_events=diagnostics_events,
        outcome_comparisons=comparison_rows,
        namespace=args.namespace,
        log_index_prefix=args.log_index_prefix,
        source_artifacts=source_artifacts,
        upstream_commit=args.upstream_commit,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet.to_dict(), indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "run_id": packet.run_id,
                "decision_count": packet.telemetry.decision_count,
                "total_cost_usd": packet.telemetry.total_cost_usd,
                "comparison_count": len(packet.outcome_comparisons),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
