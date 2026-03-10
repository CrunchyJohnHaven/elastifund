#!/usr/bin/env python3
"""Commit and push ARR promotion artifacts when BTC5 autoresearch promotes a profile."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_btc5_autoresearch_cycle import render_strategy_env  # noqa: E402


DEFAULT_CYCLE_JSON = ROOT / "reports" / "btc5_autoresearch" / "latest.json"
DEFAULT_BASE_ENV = ROOT / "config" / "btc5_strategy.env"
DEFAULT_ALLOWED_PATHS = [
    "config/btc5_strategy.env",
    "research/btc5_arr_progress.tsv",
    "research/btc5_arr_progress.svg",
    "research/btc5_arr_summary.md",
    "research/btc5_arr_latest.json",
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def _dirty_paths() -> list[str]:
    result = _run(["git", "status", "--porcelain"])
    paths: list[str] = []
    for line in (result.stdout or "").splitlines():
        if not line:
            continue
        paths.append(line[3:])
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-json", type=Path, default=DEFAULT_CYCLE_JSON)
    parser.add_argument("--base-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--allow-path",
        action="append",
        default=[],
        help="Allowlisted path that may be staged and committed by this hook.",
    )
    return parser.parse_args()


def _apply_session_policy_line(env_text: str, session_policy: list[dict[str, object]]) -> str:
    lines = [line for line in env_text.splitlines() if not line.startswith("BTC5_SESSION_POLICY_JSON=")]
    if session_policy:
        lines.append(
            "BTC5_SESSION_POLICY_JSON="
            + json.dumps(session_policy, separators=(",", ":"))
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    payload = json.loads(args.cycle_json.read_text())
    decision = payload.get("decision") or {}
    best_candidate = payload.get("best_candidate") or {}
    best_runtime_package = payload.get("selected_best_runtime_package") or payload.get("best_runtime_package") or {}
    package_session_policy = list((best_runtime_package.get("session_policy") or []))
    package_already_loaded = bool(
        ((payload.get("capital_scale_recommendation") or {}).get("promoted_package_selected"))
    )
    best_profile = best_candidate.get("profile") or {}
    median_arr_delta_pct = float(decision.get("median_arr_delta_pct") or 0.0)
    if decision.get("action") != "promote":
        print(json.dumps({"status": "noop", "reason": "decision_not_promote"}, indent=2))
        return 0
    if median_arr_delta_pct <= 0:
        print(json.dumps({"status": "noop", "reason": "arr_delta_not_positive"}, indent=2))
        return 0

    allowed = {str(Path(path)) for path in (DEFAULT_ALLOWED_PATHS + list(args.allow_path))}
    dirty_paths = _dirty_paths()
    blocked = [path for path in dirty_paths if path not in allowed]
    if blocked:
        print(json.dumps({"status": "skipped", "reason": "dirty_worktree", "blocked_paths": blocked}, indent=2))
        return 0

    env_text = render_strategy_env(
        best_candidate,
        {
            "generated_at": str(payload.get("generated_at") or ""),
            "reason": str(decision.get("reason") or ""),
        },
    )
    env_text = _apply_session_policy_line(env_text, package_session_policy)
    args.base_env.write_text(env_text)

    stage_paths = [path for path in allowed if (ROOT / path).exists()]
    if not stage_paths:
        print(json.dumps({"status": "skipped", "reason": "no_allowlisted_artifacts"}, indent=2))
        return 0
    _run(["git", "add", *stage_paths])
    commit_message = (
        "Promote BTC5 ARR profile "
        + str(best_profile.get("name") or "candidate")
        + f" ({median_arr_delta_pct:.2f}pp)"
    )
    commit = _run(["git", "commit", "-m", commit_message])
    if commit.returncode != 0 and "nothing to commit" in (commit.stdout or commit.stderr):
        print(json.dumps({"status": "noop", "reason": "nothing_to_commit"}, indent=2))
        return 0
    if commit.returncode != 0:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "git_commit_failed",
                    "stdout_tail": (commit.stdout or "").strip()[-500:],
                    "stderr_tail": (commit.stderr or "").strip()[-500:],
                },
                indent=2,
            )
        )
        return 1
    push = _run(["git", "push", "origin", args.branch])
    if push.returncode != 0:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "git_push_failed",
                    "stdout_tail": (push.stdout or "").strip()[-500:],
                    "stderr_tail": (push.stderr or "").strip()[-500:],
                },
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "pushed",
                "branch": args.branch,
                "commit_message": commit_message,
                "profile": best_profile,
                "median_arr_delta_pct": round(median_arr_delta_pct, 4),
                "session_policy_records": len(package_session_policy),
                "promoted_package_already_loaded": package_already_loaded,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
