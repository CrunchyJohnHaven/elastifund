#!/usr/bin/env python3
"""Summarize threshold sensitivity from pipeline_refresh artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REPORTS_DIR = REPO_ROOT / "reports"
REPORT_PATH = REPORTS_DIR / "threshold_sensitivity_sweep.json"
PROFILE_ORDER = ("current", "aggressive", "wide_open")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def latest_pipeline_refresh_artifact(report_root: Path = REPORTS_DIR) -> Path:
    candidates = sorted(report_root.glob("pipeline_refresh_*.json"))
    if not candidates:
        raise FileNotFoundError("No reports/pipeline_refresh_*.json artifacts were found.")
    return candidates[-1]


def resolve_source_artifact(args: argparse.Namespace) -> tuple[Path, str]:
    if args.refresh_live:
        from src.pipeline_refresh import run_refresh

        artifact_path = run_refresh()
        return artifact_path.resolve(), "live_refresh"

    if args.artifact:
        artifact_path = Path(args.artifact).expanduser()
        if not artifact_path.is_absolute():
            artifact_path = (Path.cwd() / artifact_path).resolve()
        if not artifact_path.exists():
            raise FileNotFoundError(f"Pipeline refresh artifact not found: {artifact_path}")
        return artifact_path, "offline_artifact"

    return latest_pipeline_refresh_artifact().resolve(), "offline_artifact"


def _sample_is_reachable(sample: dict[str, Any]) -> bool:
    return (
        sample.get("required_calibrated_prob_yes") is not None
        or sample.get("required_raw_prob_yes") is not None
        or sample.get("max_calibrated_prob_no") is not None
        or sample.get("max_raw_prob_no") is not None
    )


def derive_fast_market_reachability(summary: dict[str, Any]) -> dict[str, Any]:
    upstream_tradeable = _as_int(summary.get("tradeable"))
    samples = summary.get("sample_windows") or []
    sample_windows = [sample for sample in samples if isinstance(sample, dict)]

    if len(sample_windows) == upstream_tradeable:
        return {
            "count": sum(1 for sample in sample_windows if _sample_is_reachable(sample)),
            "source": "sample_windows_exact",
            "inferred": False,
            "sample_windows_count": len(sample_windows),
        }

    return {
        "count": max(
            _as_int(summary.get("yes_reachable_markets")),
            _as_int(summary.get("no_reachable_markets")),
        ),
        "source": "side_reachability_max",
        "inferred": upstream_tradeable > 0,
        "sample_windows_count": len(sample_windows),
    }


def build_threshold_pairs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    threshold_sensitivity = payload.get("threshold_sensitivity") or {}
    if not isinstance(threshold_sensitivity, dict):
        raise ValueError("threshold_sensitivity was missing from the pipeline refresh artifact")

    new_viable_strategies = payload.get("new_viable_strategies") or []
    pipeline_tradeable = len(new_viable_strategies) if isinstance(new_viable_strategies, list) else 0

    pairs: list[dict[str, Any]] = []
    for profile_name in PROFILE_ORDER:
        summary = threshold_sensitivity.get(profile_name) or {}
        if not isinstance(summary, dict):
            raise ValueError(f"threshold_sensitivity.{profile_name} was missing from the pipeline refresh artifact")

        reachability = derive_fast_market_reachability(summary)
        pairs.append(
            {
                "profile": profile_name,
                "yes_threshold": round(_as_float(summary.get("yes")), 2),
                "no_threshold": round(_as_float(summary.get("no")), 2),
                "pipeline_refresh_tradeable_field": _as_int(summary.get("tradeable")),
                "fast_market_reachability": reachability["count"],
                "pipeline_tradeable": pipeline_tradeable,
                "yes_reachable_markets": _as_int(summary.get("yes_reachable_markets")),
                "no_reachable_markets": _as_int(summary.get("no_reachable_markets")),
                "reachability_count_source": reachability["source"],
                "reachability_count_inferred": reachability["inferred"],
                "sample_windows_count": reachability["sample_windows_count"],
            }
        )
    return pairs


def identify_breakpoints(results: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    breakpoints: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for result in results:
        current_count = _as_int(result.get(metric))
        if previous is not None:
            previous_count = _as_int(previous.get(metric))
            if current_count != previous_count:
                breakpoints.append(
                    {
                        "metric": metric,
                        "from_profile": str(previous["profile"]),
                        "to_profile": str(result["profile"]),
                        "yes_threshold": _as_float(result.get("yes_threshold")),
                        "no_threshold": _as_float(result.get("no_threshold")),
                        "previous_count": previous_count,
                        "current_count": current_count,
                        "delta": current_count - previous_count,
                    }
                )
        previous = result
    return breakpoints


def build_conclusion(results: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    current, aggressive, wide_open = results
    recommendation = str(payload.get("recommendation") or "unknown")
    aggressive_reachability = aggressive["fast_market_reachability"] > current["fast_market_reachability"]
    aggressive_pipeline = aggressive["pipeline_tradeable"] > current["pipeline_tradeable"]
    wide_open_reachability = wide_open["fast_market_reachability"] > aggressive["fast_market_reachability"]
    wide_open_pipeline = wide_open["pipeline_tradeable"] > aggressive["pipeline_tradeable"]

    if aggressive_reachability and not aggressive_pipeline:
        summary = (
            f"0.08/0.03 unlocks only reachability: fast-market reachability rises from "
            f"{current['fast_market_reachability']} to {aggressive['fast_market_reachability']}, "
            f"while pipeline_tradeable stays {aggressive['pipeline_tradeable']}. "
            f"The latest pipeline recommendation still reads {recommendation}."
        )
    elif aggressive_reachability and aggressive_pipeline:
        summary = (
            f"0.08/0.03 unlocks both reachability and validated pipeline trades: fast-market reachability "
            f"moves from {current['fast_market_reachability']} to {aggressive['fast_market_reachability']}, "
            f"and pipeline_tradeable moves from {current['pipeline_tradeable']} to "
            f"{aggressive['pipeline_tradeable']}."
        )
    elif aggressive_pipeline:
        summary = (
            f"0.08/0.03 changes only the validated pipeline output: pipeline_tradeable rises from "
            f"{current['pipeline_tradeable']} to {aggressive['pipeline_tradeable']}, while fast-market "
            f"reachability stays {aggressive['fast_market_reachability']}."
        )
    else:
        summary = (
            f"0.08/0.03 does not change either fast-market reachability "
            f"({current['fast_market_reachability']} -> {aggressive['fast_market_reachability']}) "
            f"or pipeline_tradeable ({current['pipeline_tradeable']} -> {aggressive['pipeline_tradeable']})."
        )

    if not wide_open_reachability and not wide_open_pipeline:
        summary += " 0.05/0.02 adds no further change beyond the aggressive profile."
    elif wide_open_reachability and not wide_open_pipeline:
        summary += (
            f" 0.05/0.02 widens reachability further to {wide_open['fast_market_reachability']}, "
            f"but pipeline_tradeable remains {wide_open['pipeline_tradeable']}."
        )
    elif wide_open_pipeline:
        summary += (
            f" 0.05/0.02 also changes pipeline_tradeable to {wide_open['pipeline_tradeable']}."
        )

    return {
        "plain_english": summary,
        "aggressive_pair_unlocks_reachability": aggressive_reachability,
        "aggressive_pair_unlocks_pipeline_tradeable": aggressive_pipeline,
        "wide_open_adds_reachability": wide_open_reachability,
        "wide_open_adds_pipeline_tradeable": wide_open_pipeline,
        "latest_pipeline_recommendation": recommendation,
    }


def build_report(
    *,
    generated_at: datetime,
    source_artifact: Path,
    source_mode: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    threshold_pairs = build_threshold_pairs(payload)
    return {
        "generated_at": generated_at.isoformat(),
        "source_artifact": {
            "path": repo_relative(source_artifact),
            "mode": source_mode,
            "artifact_timestamp": payload.get("timestamp"),
            "threshold_market_source": payload.get("threshold_market_source", "gamma_events_flattened"),
            "fast_markets_pulled": _as_int(payload.get("fast_markets_pulled")),
            "basic_filter_markets": _as_int(payload.get("basic_filter_markets")),
            "markets_in_allowed_categories": _as_int(payload.get("markets_in_allowed_categories")),
        },
        "metric_definition": {
            "pipeline_tradeable": (
                "Validated dispatchable markets inferred from pipeline_refresh.new_viable_strategies. "
                "This stays at 0 when the latest pipeline recommendation is REJECT ALL."
            ),
            "fast_market_reachability": (
                "Fast-market windows that can mathematically satisfy the profile's YES/NO reachability checks. "
                "Derived from threshold_sensitivity sample_windows when exact, otherwise from the side reachability counts."
            ),
            "pipeline_refresh_tradeable_field": (
                "Upstream threshold_sensitivity[*].tradeable value from src.pipeline_refresh. "
                "This is a category/basic-filter candidate count, not a validated live model-pass count."
            ),
        },
        "threshold_pairs_tested": threshold_pairs,
        "breakpoint_detection": {
            "fast_market_reachability": identify_breakpoints(threshold_pairs, "fast_market_reachability"),
            "pipeline_tradeable": identify_breakpoints(threshold_pairs, "pipeline_tradeable"),
        },
        "conclusion": build_conclusion(threshold_pairs, payload),
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    return path


def print_summary(report: dict[str, Any]) -> None:
    source = report["source_artifact"]
    print(
        "Source:",
        f"{source['path']} ({source['threshold_market_source']}, mode={source['mode']})",
    )
    for pair in report["threshold_pairs_tested"]:
        print(
            f"{pair['profile']}: YES {pair['yes_threshold']:.2f} / NO {pair['no_threshold']:.2f} "
            f"fast_market_reachability={pair['fast_market_reachability']} "
            f"pipeline_tradeable={pair['pipeline_tradeable']} "
            f"pipeline_refresh_tradeable_field={pair['pipeline_refresh_tradeable_field']}"
        )

    reachability_breaks = report["breakpoint_detection"]["fast_market_reachability"]
    if reachability_breaks:
        print(
            "Reachability breakpoints:",
            ", ".join(
                f"{item['from_profile']}->{item['to_profile']} ({item['delta']:+d})"
                for item in reachability_breaks
            ),
        )
    else:
        print("Reachability breakpoints: none")

    pipeline_breaks = report["breakpoint_detection"]["pipeline_tradeable"]
    if pipeline_breaks:
        print(
            "Pipeline breakpoints:",
            ", ".join(
                f"{item['from_profile']}->{item['to_profile']} ({item['delta']:+d})"
                for item in pipeline_breaks
            ),
        )
    else:
        print("Pipeline breakpoints: none")

    print("Conclusion:", report["conclusion"]["plain_english"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate reports/threshold_sensitivity_sweep.json from pipeline_refresh artifacts."
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--artifact",
        help="Path to an existing pipeline_refresh_*.json artifact. Defaults to the latest local artifact.",
    )
    source_group.add_argument(
        "--refresh-live",
        action="store_true",
        help="Regenerate a fresh pipeline_refresh artifact before building the threshold sweep report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_artifact, source_mode = resolve_source_artifact(args)
    payload = load_json(source_artifact)
    report = build_report(
        generated_at=utc_now(),
        source_artifact=source_artifact,
        source_mode=source_mode,
        payload=payload,
    )
    path = write_report(report)
    print_summary(report)
    print(path)


if __name__ == "__main__":
    main()
