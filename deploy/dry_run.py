#!/usr/bin/env python3
"""Repo-local entrypoint for the VPS deploy dry-run."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.deploy_release_bundle import (
    _run_bridge_pull_only,
    _timestamped_deploy_report_path,
    discover_ssh_key,
    main as deploy_main,
    parse_args,
    write_release_manifest,
)


def _annotate_report(report_path: Path, bridge_returncode: int) -> None:
    if not report_path.exists():
        return
    payload = json.loads(report_path.read_text())
    payload["bridge_refresh_attempted"] = True
    notes = list(payload.get("notes") or [])
    notes.append(f"pre_manifest_bridge_pull_only_returncode={bridge_returncode}")
    payload["notes"] = notes
    if bridge_returncode == 0:
        actions_taken = list(payload.get("actions_taken") or [])
        if "Bridge pull-only refresh completed before manifest generation." not in actions_taken:
            actions_taken.insert(0, "Bridge pull-only refresh completed before manifest generation.")
        payload["actions_taken"] = actions_taken
    else:
        blocked_actions = list(payload.get("blocked_actions") or [])
        if "Bridge pull-only refresh failed before manifest generation." not in blocked_actions:
            blocked_actions.insert(0, "Bridge pull-only refresh failed before manifest generation.")
        payload["blocked_actions"] = blocked_actions
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def run(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv or sys.argv[1:])
    args = parse_args(raw_args)
    if args.write_manifest or args.skip_bridge_refresh:
        return deploy_main(raw_args)

    key_path = args.key.resolve() if args.key else discover_ssh_key(REPO_ROOT)
    if key_path is None:
        return deploy_main(raw_args)

    bridge_result = _run_bridge_pull_only(key_path)
    manifest_path = args.manifest.resolve()
    write_release_manifest(REPO_ROOT, manifest_path)

    report_path = args.output.resolve() if args.output else _timestamped_deploy_report_path()
    forwarded_args = [*raw_args, "--skip-bridge-refresh", "--output", str(report_path)]
    exit_code = deploy_main(forwarded_args)
    _annotate_report(report_path, bridge_result.returncode)
    print(report_path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
