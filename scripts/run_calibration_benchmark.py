#!/usr/bin/env python3
"""Run the frozen calibration benchmark and emit a benchmark packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.calibration_v1.benchmark import (  # noqa: E402
    default_artifact_paths,
    run_benchmark,
    write_benchmark_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the immutable calibration benchmark.")
    parser.add_argument(
        "--manifest",
        default="benchmarks/calibration_v1/manifest.json",
        help="Path to the frozen benchmark manifest",
    )
    parser.add_argument(
        "--output-dir",
        default="research/results/calibration/packets",
        help="Directory for generated benchmark packets",
    )
    parser.add_argument(
        "--slug",
        help="Optional packet basename without extension",
    )
    parser.add_argument(
        "--json-out",
        help="Optional explicit JSON output path",
    )
    parser.add_argument(
        "--summary-out",
        help="Optional explicit markdown summary output path",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Free-text description stored in the packet",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packet = run_benchmark(args.manifest, description=args.description)
    if args.json_out and args.summary_out:
        json_path = Path(args.json_out)
        summary_path = Path(args.summary_out)
    else:
        json_path, summary_path = default_artifact_paths(args.output_dir, slug=args.slug)
    paths = write_benchmark_artifacts(
        packet,
        json_path=json_path,
        summary_path=summary_path,
    )
    result = {
        "benchmark_id": packet["benchmark_id"],
        "selected_variant": packet["selected_variant"]["name"],
        "benchmark_score": packet["selected_variant"]["benchmark_score"],
        "brier": packet["selected_variant"]["brier"],
        "ece": packet["selected_variant"]["ece"],
        "log_loss": packet["selected_variant"]["log_loss"],
        **paths,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
