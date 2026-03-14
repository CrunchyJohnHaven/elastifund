#!/usr/bin/env python3
"""Rank BTC5 runtime-package candidates by the market-backed policy benchmark."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_policy_benchmark import (
    DEFAULT_MARKET_LATEST_JSON,
    DEFAULT_MARKET_POLICY_HANDOFF,
    POLICY_KEEP_EPSILON,
    evaluate_runtime_package_against_market,
    load_market_policy_handoff,
    runtime_package_hash,
    runtime_package_id,
    safe_float,
)

DEFAULT_CYCLE_JSON = ROOT / "reports" / "btc5_autoresearch" / "latest.json"
DEFAULT_REPORT_DIR = ROOT / "reports" / "btc5_market_policy_frontier"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-json", default=str(DEFAULT_CYCLE_JSON), help="BTC5 cycle artifact path.")
    parser.add_argument(
        "--market-policy-handoff",
        default=str(DEFAULT_MARKET_POLICY_HANDOFF),
        help="Market-to-policy handoff artifact path.",
    )
    parser.add_argument(
        "--market-latest-json",
        default=str(DEFAULT_MARKET_LATEST_JSON),
        help="Market benchmark latest summary path.",
    )
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Output directory.")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = int(round((len(ordered) - 1) * (pct / 100.0)))
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _bootstrap_mean_ci(
    values: list[float],
    *,
    alpha: float = 0.05,
    samples: int = 400,
) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        single = float(values[0])
        return (single, single)
    means: list[float] = []
    population = list(values)
    rng = random.Random(7)
    for _ in range(max(1, int(samples))):
        drawn = [population[rng.randrange(len(population))] for _ in range(len(population))]
        means.append(_mean(drawn))
    lower_pct = max(0.0, (alpha / 2.0) * 100.0)
    upper_pct = min(100.0, (1.0 - alpha / 2.0) * 100.0)
    return (_percentile(means, lower_pct), _percentile(means, upper_pct))


def _fold_delta_summary(candidate: dict[str, Any], incumbent: dict[str, Any] | None) -> dict[str, Any]:
    incumbent_folds = {
        str(item.get("fold_id")): item
        for item in ((incumbent or {}).get("fold_results") or [])
        if isinstance(item, dict) and str(item.get("fold_id") or "").strip()
    }
    candidate_folds = [
        item
        for item in (candidate.get("fold_results") or [])
        if isinstance(item, dict) and str(item.get("fold_id") or "").strip()
    ]
    if not incumbent_folds or not candidate_folds:
        return {
            "fold_count": 0,
            "fold_win_count_vs_incumbent": 0,
            "fold_win_rate_vs_incumbent": None,
            "mean_fold_loss_improvement": None,
            "bootstrap_ci_low": None,
            "bootstrap_ci_high": None,
            "confidence_method": None,
        }
    improvements: list[float] = []
    for candidate_fold in candidate_folds:
        incumbent_fold = incumbent_folds.get(str(candidate_fold.get("fold_id")))
        if not isinstance(incumbent_fold, dict):
            continue
        candidate_loss = safe_float(candidate_fold.get("policy_loss"), None)
        incumbent_loss = safe_float(incumbent_fold.get("policy_loss"), None)
        if candidate_loss is None or incumbent_loss is None:
            continue
        improvements.append(float(incumbent_loss - candidate_loss))
    if not improvements:
        return {
            "fold_count": 0,
            "fold_win_count_vs_incumbent": 0,
            "fold_win_rate_vs_incumbent": None,
            "mean_fold_loss_improvement": None,
            "bootstrap_ci_low": None,
            "bootstrap_ci_high": None,
            "confidence_method": None,
        }
    ci_low, ci_high = _bootstrap_mean_ci(improvements)
    win_count = sum(1 for value in improvements if value > 0.0)
    return {
        "fold_count": len(improvements),
        "fold_win_count_vs_incumbent": win_count,
        "fold_win_rate_vs_incumbent": round(win_count / float(len(improvements) or 1), 4),
        "mean_fold_loss_improvement": round(_mean(improvements), 4),
        "bootstrap_ci_low": round(ci_low, 4),
        "bootstrap_ci_high": round(ci_high, 4),
        "confidence_method": "bootstrap_mean_fold_loss_improvement_v1",
    }


def _candidate_runtime_packages(cycle_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    def record(runtime_package: dict[str, Any] | None, source: str) -> None:
        if not isinstance(runtime_package, dict):
            return
        profile = runtime_package.get("profile") if isinstance(runtime_package.get("profile"), dict) else {}
        if not profile:
            return
        package_hash = runtime_package_hash(runtime_package)
        entry = candidates.setdefault(
            package_hash,
            {
                "runtime_package": runtime_package,
                "policy_id": runtime_package_id(runtime_package),
                "sources": [],
            },
        )
        if source not in entry["sources"]:
            entry["sources"].append(source)

    record(cycle_payload.get("active_runtime_package"), "active_runtime_package")
    record(cycle_payload.get("selected_active_runtime_package"), "selected_active_runtime_package")
    record(cycle_payload.get("best_runtime_package"), "best_runtime_package")
    record(cycle_payload.get("selected_best_runtime_package"), "selected_best_runtime_package")

    ranked_packages = (cycle_payload.get("package_ranking") or {}).get("ranked_packages") or []
    for index, item in enumerate(ranked_packages, start=1):
        if not isinstance(item, dict):
            continue
        record(item.get("runtime_package"), f"package_ranking[{index}]")

    return list(candidates.values())


def build_frontier_report(
    *,
    cycle_payload: dict[str, Any],
    market_policy_handoff: Path,
    market_latest_json: Path,
) -> dict[str, Any]:
    handoff = load_market_policy_handoff(
        handoff_path=market_policy_handoff,
        market_latest_path=market_latest_json,
    )
    current_market_model_version = str(handoff.get("market_model_version") or "").strip() or None
    candidates = _candidate_runtime_packages(cycle_payload)
    ranked: list[dict[str, Any]] = []
    stale_ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        runtime_package = candidate["runtime_package"]
        evaluation = evaluate_runtime_package_against_market(
            runtime_package,
            handoff_path=market_policy_handoff,
            market_latest_path=market_latest_json,
        )
        benchmark = evaluation.get("policy_benchmark") if isinstance(evaluation.get("policy_benchmark"), dict) else {}
        item = {
            "policy_id": candidate["policy_id"],
            "package_hash": runtime_package_hash(runtime_package),
            "sources": list(candidate["sources"]),
            "runtime_package": runtime_package,
            "policy_loss": round(safe_float(benchmark.get("policy_loss"), 0.0) or 0.0, 4),
            "median_30d_return_pct": round(safe_float(benchmark.get("median_30d_return_pct"), 0.0) or 0.0, 4),
            "p05_30d_return_pct": round(safe_float(benchmark.get("p05_30d_return_pct"), 0.0) or 0.0, 4),
            "fill_retention_ratio": round(safe_float(benchmark.get("fill_retention_ratio"), 1.0) or 1.0, 4),
            "policy_components": dict(benchmark),
            "fold_results": list(evaluation.get("fold_results") or []),
            "confidence_summary": dict(evaluation.get("confidence_summary") or {}),
            "evaluation_source": evaluation.get("evaluation_source"),
            "simulator_champion_id": evaluation.get("simulator_champion_id"),
            "market_epoch_id": evaluation.get("market_epoch_id"),
            "market_model_version": evaluation.get("market_model_version"),
            "hard_block_reasons": [],
            "soft_block_reasons": [],
        }
        if current_market_model_version and item["market_model_version"] not in {None, current_market_model_version}:
            stale_ranked.append(item)
            continue
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            safe_float(item.get("policy_loss"), 0.0) or 0.0,
            str(item.get("policy_id") or ""),
        )
    )

    incumbent_package = cycle_payload.get("selected_active_runtime_package") or cycle_payload.get("active_runtime_package") or {}
    incumbent_id = runtime_package_id(incumbent_package)
    incumbent_hash = runtime_package_hash(incumbent_package) if isinstance(incumbent_package, dict) and incumbent_package else None
    selected_package = cycle_payload.get("selected_best_runtime_package") or cycle_payload.get("best_runtime_package") or {}
    selected_id = runtime_package_id(selected_package)
    selected_hash = runtime_package_hash(selected_package) if isinstance(selected_package, dict) and selected_package else None
    incumbent = next((item for item in ranked if item["package_hash"] == incumbent_hash), None)
    selected = next((item for item in ranked if item["package_hash"] == selected_hash), None)
    best = ranked[0] if ranked else None

    for item in ranked:
        comparison = _fold_delta_summary(item, incumbent)
        item["loss_improvement_vs_incumbent"] = (
            round((safe_float((incumbent or {}).get("policy_loss"), 0.0) or 0.0) - (safe_float(item.get("policy_loss"), 0.0) or 0.0), 4)
            if incumbent is not None
            else None
        )
        item.update(comparison)

    incumbent_loss = safe_float((incumbent or {}).get("policy_loss"), 0.0) or 0.0
    selected_loss = safe_float((selected or {}).get("policy_loss"), 0.0) or 0.0
    best_loss = safe_float((best or {}).get("policy_loss"), 0.0) or 0.0
    return {
        "updated_at": str(cycle_payload.get("generated_at") or cycle_payload.get("updated_at") or ""),
        "incumbent_policy_id": incumbent_id or None,
        "incumbent_package_hash": incumbent_hash,
        "incumbent_policy_loss": round(incumbent_loss, 4) if incumbent else None,
        "selected_policy_id": selected_id or None,
        "selected_package_hash": selected_hash,
        "selected_policy_loss": round(selected_loss, 4) if selected else None,
        "best_market_policy_id": (best or {}).get("policy_id"),
        "best_market_package_hash": (best or {}).get("package_hash"),
        "best_market_policy_loss": round(best_loss, 4) if best else None,
        "current_market_model_version": current_market_model_version,
        "best_market_model_version": (best or {}).get("market_model_version"),
        "loss_improvement_vs_incumbent": (
            round(incumbent_loss - best_loss, 4) if incumbent and best else None
        ),
        "selected_loss_gap_vs_best": (
            round(selected_loss - best_loss, 4) if selected and best else None
        ),
        "selection_recommendation": {
            "policy_id": (best or {}).get("policy_id"),
            "package_hash": (best or {}).get("package_hash"),
            "selection_source": "frontier_policy_loss",
            "loss_improvement_vs_incumbent": (
                round(incumbent_loss - best_loss, 4) if incumbent and best else None
            ),
        },
        "beats_incumbent_by_keep_epsilon": (
            (incumbent_loss - best_loss) > float(POLICY_KEEP_EPSILON) if incumbent and best else False
        ),
        "ranked_policies": ranked,
        "stale_ranked_policies": stale_ranked,
        "artifacts": {
            "cycle_json": _relative(Path(cycle_payload.get("artifacts", {}).get("latest_json") or DEFAULT_CYCLE_JSON)),
            "market_policy_handoff": _relative(market_policy_handoff),
            "market_latest_json": _relative(market_latest_json),
        },
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    ranked = payload.get("ranked_policies") if isinstance(payload.get("ranked_policies"), list) else []
    top_lines = []
    for item in ranked[:5]:
        if not isinstance(item, dict):
            continue
        top_lines.append(
            "- "
            f"`{item.get('policy_id')}` loss `{item.get('policy_loss')}` "
            f"fold_win `{item.get('fold_win_rate_vs_incumbent')}` "
            f"ci `[{item.get('bootstrap_ci_low')}, {item.get('bootstrap_ci_high')}]` "
            f"median30 `{item.get('median_30d_return_pct')}` "
            f"p05 `{item.get('p05_30d_return_pct')}` "
            f"sources `{','.join(item.get('sources') or [])}`"
        )
    lines = [
        "# BTC5 Market-Backed Policy Frontier",
        "",
        f"- Incumbent: `{payload.get('incumbent_policy_id') or 'n/a'}`",
        f"- Incumbent loss: `{payload.get('incumbent_policy_loss')}`",
        f"- Selected package: `{payload.get('selected_policy_id') or 'n/a'}`",
        f"- Selected loss: `{payload.get('selected_policy_loss')}`",
        f"- Best market-backed package: `{payload.get('best_market_policy_id') or 'n/a'}`",
        f"- Best market-backed loss: `{payload.get('best_market_policy_loss')}`",
        f"- Improvement vs incumbent: `{payload.get('loss_improvement_vs_incumbent')}`",
        f"- Selected gap vs best: `{payload.get('selected_loss_gap_vs_best')}`",
        f"- Beats keep epsilon: `{payload.get('beats_incumbent_by_keep_epsilon')}`",
        "",
        "## Top Ranked",
        "",
        *top_lines,
        "",
        "Benchmark progress only, not realized P&L.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    cycle_json = Path(args.cycle_json)
    market_policy_handoff = Path(args.market_policy_handoff)
    market_latest_json = Path(args.market_latest_json)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    payload = build_frontier_report(
        cycle_payload=_load_json(cycle_json),
        market_policy_handoff=market_policy_handoff,
        market_latest_json=market_latest_json,
    )
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown(latest_md, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
