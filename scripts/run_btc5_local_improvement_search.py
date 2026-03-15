#!/usr/bin/env python3
"""Run local BTC5 mutation lanes until a quantified improvement is found or limits are hit."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTIER_JSON = ROOT / "reports" / "btc5_market_policy_frontier" / "latest.json"


@dataclass(frozen=True)
class LaneConfig:
    key: str
    latest_path: str
    runner_relpath: str


LANES: dict[str, LaneConfig] = {
    "market": LaneConfig(
        key="market",
        latest_path="reports/autoresearch/btc5_market/latest.json",
        runner_relpath="scripts/run_btc5_market_model_autoresearch.py",
    ),
    "command_node": LaneConfig(
        key="command_node",
        latest_path="reports/autoresearch/command_node/latest.json",
        runner_relpath="scripts/run_btc5_command_node_autoresearch.py",
    ),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(ROOT),
        help="Repo root used to resolve lane artifacts and runner scripts",
    )
    parser.add_argument(
        "--lanes",
        default="market,command_node",
        help="Comma-separated lane list to search locally",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=12,
        help="Maximum round-robin rounds to run before stopping",
    )
    parser.add_argument(
        "--stop-on-first-improvement",
        action="store_true",
        default=True,
        help="Stop as soon as any selected lane keeps a new champion",
    )
    parser.add_argument(
        "--continue-after-improvement",
        action="store_true",
        help="Keep running after improvements instead of stopping on the first keep",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously until interrupted or --max-duration-seconds is reached",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=300.0,
        help="Sleep interval between full round-robin passes when --daemon is set",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=float,
        default=0.0,
        help="Total daemon runtime limit; <=0 means run until interrupted",
    )
    parser.add_argument(
        "--proposer-profile",
        choices=("auto", "aggressive"),
        default="aggressive",
        help="Local proposer profile; aggressive forces the strongest built-in proposer tier immediately",
    )
    parser.add_argument(
        "--market-command",
        default="",
        help="Optional shell-style override for the market lane command",
    )
    parser.add_argument(
        "--command-node-command",
        default="",
        help="Optional shell-style override for the command-node lane command",
    )
    parser.add_argument(
        "--latest-out",
        default="reports/autoresearch/local_improvement_search/latest.json",
        help="Latest search summary JSON",
    )
    parser.add_argument(
        "--latest-md",
        default="reports/autoresearch/local_improvement_search/latest.md",
        help="Latest search summary markdown",
    )
    parser.add_argument(
        "--history-jsonl",
        default="reports/autoresearch/local_improvement_search/history.jsonl",
        help="Append-only attempt ledger",
    )
    parser.add_argument(
        "--frontier-json",
        default=str(DEFAULT_FRONTIER_JSON),
        help="Optional frontier JSON used to seed local search metadata",
    )
    parser.add_argument(
        "--frontier-top-k",
        type=int,
        default=5,
        help="Number of frontier seeds to rotate through in local search metadata",
    )
    return parser.parse_args(argv)


def _resolve(repo_root: Path, path_value: str | Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _lane_command(repo_root: Path, lane_key: str, override: str) -> list[str]:
    if override.strip():
        return shlex.split(override)
    runner = _resolve(repo_root, LANES[lane_key].runner_relpath)
    return [sys.executable, str(runner)]


def _lane_command_with_profile(
    repo_root: Path,
    lane_key: str,
    override: str,
    proposer_profile: str,
    description: str = "",
) -> list[str]:
    command = _lane_command(repo_root, lane_key, override)
    if override.strip():
        return command
    if proposer_profile != "aggressive":
        return [*command, "--description", description] if description else command
    if lane_key == "market":
        command = [*command, "--force-proposer-tier", "expensive"]
    elif lane_key == "command_node":
        command = [*command, "--force-proposer-tier", "escalated"]
    if description:
        command = [*command, "--description", description]
    return command


def _frontier_seed_pool(repo_root: Path, frontier_json: str, top_k: int) -> list[dict[str, Any]]:
    payload = _read_json(_resolve(repo_root, frontier_json))
    ranked = payload.get("ranked_policies") if isinstance(payload.get("ranked_policies"), list) else []
    seeds: list[dict[str, Any]] = []
    for item in ranked[: max(0, int(top_k))]:
        if not isinstance(item, dict):
            continue
        seeds.append(
            {
                "policy_id": item.get("policy_id"),
                "package_hash": item.get("package_hash"),
                "policy_loss": item.get("policy_loss"),
            }
        )
    return seeds


def _load_lane_latest(repo_root: Path, lane_key: str) -> dict[str, Any]:
    return _read_json(_resolve(repo_root, LANES[lane_key].latest_path))


def _extract_champion(lane_key: str, latest: dict[str, Any]) -> dict[str, Any] | None:
    champion = latest.get("champion")
    if not isinstance(champion, dict):
        return None
    if lane_key == "market":
        return {
            "id": _coerce_int(champion.get("experiment_id")),
            "label": champion.get("candidate_model_name") or champion.get("candidate_hash"),
            "loss": _coerce_float(champion.get("loss")),
            "updated_at": champion.get("generated_at"),
            "candidate_hash": champion.get("candidate_hash"),
        }
    return {
        "id": _coerce_int(champion.get("experiment_id")),
        "label": champion.get("candidate_label") or champion.get("prompt_hash"),
        "loss": _coerce_float(champion.get("loss")),
        "total_score": _coerce_float(champion.get("total_score")),
        "updated_at": champion.get("updated_at"),
        "candidate_hash": champion.get("candidate_hash") or champion.get("prompt_hash"),
    }


def _extract_latest_result(lane_key: str, latest: dict[str, Any]) -> dict[str, Any]:
    if lane_key == "market":
        latest_experiment = dict(latest.get("latest_experiment") or {})
        return {
            "status": latest_experiment.get("status"),
            "decision_reason": latest_experiment.get("decision_reason"),
            "proposal_id": latest_experiment.get("proposal_id"),
            "proposer_model": latest_experiment.get("proposer_model"),
            "estimated_llm_cost_usd": _coerce_float(latest_experiment.get("estimated_llm_cost_usd")),
            "loss": _coerce_float(latest_experiment.get("loss")),
            "keep": bool(latest_experiment.get("keep")) if latest_experiment.get("keep") is not None else None,
        }
    latest_proposal = dict(latest.get("latest_proposal") or {})
    return {
        "status": latest.get("latest_status"),
        "decision_reason": latest.get("latest_decision_reason"),
        "proposal_id": latest.get("latest_proposal_id"),
        "proposer_model": latest_proposal.get("proposer_model"),
        "estimated_llm_cost_usd": _coerce_float(latest_proposal.get("estimated_llm_cost_usd")),
        "loss": _coerce_float(latest.get("latest_loss")),
        "total_score": _coerce_float(latest.get("latest_total_score")),
    }


def _quantify_improvement(
    lane_key: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not before or not after:
        return None
    before_id = before.get("id")
    after_id = after.get("id")
    if before_id == after_id:
        return None
    before_loss = _coerce_float(before.get("loss"))
    after_loss = _coerce_float(after.get("loss"))
    improvement: dict[str, Any] = {
        "lane": lane_key,
        "champion_before_id": before_id,
        "champion_after_id": after_id,
    }
    if before_loss is not None and after_loss is not None:
        loss_improvement = round(before_loss - after_loss, 6)
        improvement["loss_before"] = before_loss
        improvement["loss_after"] = after_loss
        improvement["loss_improvement"] = loss_improvement
        if before_loss != 0:
            improvement["loss_improvement_pct"] = round((loss_improvement / abs(before_loss)) * 100.0, 6)
    if lane_key == "command_node":
        before_score = _coerce_float(before.get("total_score"))
        after_score = _coerce_float(after.get("total_score"))
        if before_score is not None and after_score is not None:
            improvement["total_score_before"] = before_score
            improvement["total_score_after"] = after_score
            improvement["total_score_improvement"] = round(after_score - before_score, 6)
    return improvement


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# BTC5 Local Improvement Search",
        "",
        f"- Generated at: `{summary.get('generated_at')}`",
        f"- Stop reason: `{summary.get('stop_reason')}`",
        f"- Improvement found: `{summary.get('improvement_found')}`",
        f"- Winning lane: `{summary.get('winning_lane') or 'n/a'}`",
        f"- Rounds completed: `{summary.get('rounds_completed')}`",
        f"- Daemon mode: `{summary.get('daemon_mode', False)}`",
        "",
    ]
    best = summary.get("best_improvement") or {}
    if best:
        lines.extend(
            [
                "## Best Improvement",
                "",
                f"- Lane: `{best.get('lane')}`",
                f"- Champion before: `{best.get('champion_before_id')}`",
                f"- Champion after: `{best.get('champion_after_id')}`",
            ]
        )
        if best.get("loss_improvement") is not None:
            lines.append(f"- Loss improvement: `{best.get('loss_improvement')}`")
        if best.get("loss_improvement_pct") is not None:
            lines.append(f"- Loss improvement pct: `{best.get('loss_improvement_pct')}`")
        if best.get("total_score_improvement") is not None:
            lines.append(f"- Total score improvement: `{best.get('total_score_improvement')}`")
        lines.append("")
    lines.append("## Lane Summaries")
    lines.append("")
    for lane_key, lane in (summary.get("lane_summaries") or {}).items():
        lines.append(
            f"- {lane_key}: attempts=`{lane.get('attempts', 0)}` "
            f"last_status=`{lane.get('last_status') or 'n/a'}` "
            f"decision_reason=`{lane.get('last_decision_reason') or 'n/a'}` "
            f"improvement_found=`{lane.get('improvement_found', False)}` "
            f"seed=`{lane.get('last_seed_policy_id') or 'n/a'}`"
        )
    lines.append("")
    lines.append("Local benchmark improvement is benchmark evidence, not realized P&L.")
    return "\n".join(lines) + "\n"


def _selected_lanes(text: str) -> list[str]:
    lanes = [item.strip() for item in text.split(",") if item.strip()]
    invalid = [lane for lane in lanes if lane not in LANES]
    if invalid:
        raise SystemExit(f"Unknown lanes: {', '.join(invalid)}")
    if not lanes:
        raise SystemExit("At least one lane is required")
    return lanes


def _build_summary(
    *,
    repo_root: Path,
    lanes: list[str],
    args: argparse.Namespace,
    rounds_completed: int,
    stop_reason: str,
    best_improvement: dict[str, Any] | None,
    winning_lane: str | None,
    lane_summaries: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": _utc_now().isoformat(),
        "repo_root": str(repo_root),
        "config": {
            "lanes": lanes,
            "max_rounds": int(args.max_rounds),
            "stop_on_first_improvement": bool(args.stop_on_first_improvement and not args.continue_after_improvement),
            "daemon": bool(args.daemon),
            "interval_seconds": float(args.interval_seconds),
            "max_duration_seconds": float(args.max_duration_seconds),
            "proposer_profile": str(args.proposer_profile),
            "frontier_json": str(args.frontier_json),
            "frontier_top_k": int(args.frontier_top_k),
        },
        "daemon_mode": bool(args.daemon),
        "rounds_completed": rounds_completed,
        "stop_reason": stop_reason,
        "improvement_found": best_improvement is not None,
        "winning_lane": winning_lane,
        "best_improvement": best_improvement,
        "frontier_seed_pool": _frontier_seed_pool(repo_root, str(args.frontier_json), int(args.frontier_top_k)),
        "lane_summaries": lane_summaries,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _resolve(ROOT, args.repo_root)
    lanes = _selected_lanes(args.lanes)
    latest_out = _resolve(repo_root, args.latest_out)
    latest_md = _resolve(repo_root, args.latest_md)
    history_jsonl = _resolve(repo_root, args.history_jsonl)

    overrides = {
        "market": args.market_command,
        "command_node": args.command_node_command,
    }
    frontier_seeds = _frontier_seed_pool(repo_root, str(args.frontier_json), int(args.frontier_top_k))

    lane_summaries: dict[str, Any] = {
        lane_key: {
            "attempts": 0,
            "improvement_found": False,
            "last_status": None,
            "last_decision_reason": None,
            "last_proposal_id": None,
            "last_estimated_llm_cost_usd": None,
            "last_champion_before": None,
            "last_champion_after": None,
            "last_quantified_improvement": None,
            "last_seed_policy_id": None,
            "last_seed_package_hash": None,
        }
        for lane_key in lanes
    }

    best_improvement: dict[str, Any] | None = None
    rounds_completed = 0
    stop_reason = "max_rounds_reached"
    winning_lane: str | None = None
    search_start = time.monotonic()
    stop_on_first_improvement = bool(args.stop_on_first_improvement and not args.continue_after_improvement)
    max_rounds = max(1, int(args.max_rounds))
    round_index = 0

    while True:
        if not args.daemon and round_index >= max_rounds:
            stop_reason = "max_rounds_reached"
            break
        if args.daemon and float(args.max_duration_seconds) > 0 and (time.monotonic() - search_start) >= float(args.max_duration_seconds):
            stop_reason = "max_duration_reached"
            break
        round_index += 1
        rounds_completed = round_index
        for lane_key in lanes:
            seed = (
                frontier_seeds[((round_index - 1) * max(1, len(lanes)) + lanes.index(lane_key)) % len(frontier_seeds)]
                if frontier_seeds
                else None
            )
            description = (
                f"frontier_seed:{seed.get('policy_id')}:{seed.get('package_hash')}"
                if isinstance(seed, dict) and seed.get("policy_id") and seed.get("package_hash")
                else ""
            )
            before_latest = _load_lane_latest(repo_root, lane_key)
            before_champion = _extract_champion(lane_key, before_latest)
            command = _lane_command_with_profile(
                repo_root,
                lane_key,
                overrides.get(lane_key, ""),
                str(args.proposer_profile),
                description,
            )
            completed = subprocess.run(
                command,
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            after_latest = _load_lane_latest(repo_root, lane_key)
            after_champion = _extract_champion(lane_key, after_latest)
            latest_result = _extract_latest_result(lane_key, after_latest)
            quantified = _quantify_improvement(lane_key, before_champion, after_champion)
            improved = quantified is not None

            lane_summary = lane_summaries[lane_key]
            lane_summary["attempts"] = int(lane_summary["attempts"]) + 1
            lane_summary["improvement_found"] = lane_summary["improvement_found"] or improved
            lane_summary["last_status"] = latest_result.get("status")
            lane_summary["last_decision_reason"] = latest_result.get("decision_reason")
            lane_summary["last_proposal_id"] = latest_result.get("proposal_id")
            lane_summary["last_estimated_llm_cost_usd"] = latest_result.get("estimated_llm_cost_usd")
            lane_summary["last_champion_before"] = before_champion
            lane_summary["last_champion_after"] = after_champion
            lane_summary["last_quantified_improvement"] = quantified
            lane_summary["last_seed_policy_id"] = (seed or {}).get("policy_id") if isinstance(seed, dict) else None
            lane_summary["last_seed_package_hash"] = (seed or {}).get("package_hash") if isinstance(seed, dict) else None

            attempt_payload = {
                "generated_at": _utc_now().isoformat(),
                "round": round_index,
                "lane": lane_key,
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-20:]),
                "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-20:]),
                "before_champion": before_champion,
                "after_champion": after_champion,
                "latest_status": latest_result.get("status"),
                "decision_reason": latest_result.get("decision_reason"),
                "proposal_id": latest_result.get("proposal_id"),
                "estimated_llm_cost_usd": latest_result.get("estimated_llm_cost_usd"),
                "frontier_seed": seed,
                "improved": improved,
                "quantified_improvement": quantified,
            }
            _append_jsonl(history_jsonl, attempt_payload)

            if improved:
                best_improvement = quantified
                winning_lane = lane_key
                stop_reason = "improvement_found"
                if stop_on_first_improvement:
                    summary = _build_summary(
                        repo_root=repo_root,
                        lanes=lanes,
                        args=args,
                        rounds_completed=rounds_completed,
                        stop_reason=stop_reason,
                        best_improvement=best_improvement,
                        winning_lane=winning_lane,
                        lane_summaries=lane_summaries,
                    )
                    _write_json(latest_out, summary)
                    latest_md.parent.mkdir(parents=True, exist_ok=True)
                    latest_md.write_text(_render_markdown(summary), encoding="utf-8")
                    print(json.dumps(summary, indent=2, sort_keys=True))
                    return 0
        summary = _build_summary(
            repo_root=repo_root,
            lanes=lanes,
            args=args,
            rounds_completed=rounds_completed,
            stop_reason="running" if args.daemon else stop_reason,
            best_improvement=best_improvement,
            winning_lane=winning_lane,
            lane_summaries=lane_summaries,
        )
        _write_json(latest_out, summary)
        latest_md.parent.mkdir(parents=True, exist_ok=True)
        latest_md.write_text(_render_markdown(summary), encoding="utf-8")
        if args.daemon and float(args.interval_seconds) > 0:
            time.sleep(float(args.interval_seconds))

    summary = _build_summary(
        repo_root=repo_root,
        lanes=lanes,
        args=args,
        rounds_completed=rounds_completed,
        stop_reason=stop_reason,
        best_improvement=best_improvement,
        winning_lane=winning_lane,
        lane_summaries=lane_summaries,
    )
    _write_json(latest_out, summary)
    latest_md.parent.mkdir(parents=True, exist_ok=True)
    latest_md.write_text(_render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
