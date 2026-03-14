from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nontrading.finance.model_budget import build_model_budget_plan
from nontrading.finance.model_budget import utc_now

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FINANCE_LATEST = ROOT / "reports" / "finance" / "latest.json"
DEFAULT_ACTION_QUEUE = ROOT / "reports" / "finance" / "action_queue.json"
DEFAULT_RUNTIME_TRUTH = ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_OUTPUT = ROOT / "reports" / "finance" / "model_budget_plan.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_action_queue(
    *,
    action_queue: dict[str, Any],
    queued_actions: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    existing_actions = action_queue.get("actions")
    actions = [deepcopy(item) for item in existing_actions] if isinstance(existing_actions, list) else []
    by_key: dict[str, dict[str, Any]] = {}
    next_id = 1

    for action in actions:
        if not isinstance(action, dict):
            continue
        action_id = action.get("id")
        if isinstance(action_id, int):
            next_id = max(next_id, action_id + 1)
        key = str(action.get("action_key") or "")
        if key:
            by_key[key] = action

    for queued_action in queued_actions:
        record = deepcopy(queued_action)
        key = record["action_key"]
        existing = by_key.get(key)
        if existing is not None:
            preserved_id = existing.get("id")
            preserved_created_at = existing.get("created_at") or generated_at
            preserved_executed_at = existing.get("executed_at")
            record["id"] = preserved_id
            record["created_at"] = preserved_created_at
            record["executed_at"] = preserved_executed_at
        else:
            record["id"] = next_id
            next_id += 1
            record["created_at"] = generated_at
            record["executed_at"] = None
            actions.append(record)
        record["updated_at"] = generated_at
        if existing is not None:
            existing.clear()
            existing.update(record)
        else:
            by_key[key] = record

    summary = {"queued": 0, "shadowed": 0, "executed": 0, "rejected": 0}
    for action in actions:
        if not isinstance(action, dict):
            continue
        status = str(action.get("status") or "").lower()
        if status in summary:
            summary[status] += 1

    return {
        "schema_version": "finance_action_queue.v1",
        "generated_at": generated_at,
        "summary": summary,
        "actions": actions,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finance-latest", type=Path, default=DEFAULT_FINANCE_LATEST)
    parser.add_argument("--action-queue", type=Path, default=DEFAULT_ACTION_QUEUE)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_at = utc_now()
    finance_latest = load_json(args.finance_latest, {})
    action_queue = load_json(args.action_queue, {"schema_version": "finance_action_queue.v1", "actions": []})
    runtime_truth = load_json(args.runtime_truth, {})

    plan, queued_actions = build_model_budget_plan(
        finance_latest=finance_latest,
        action_queue=action_queue,
        runtime_truth=runtime_truth,
        now=generated_at,
    )
    updated_queue = update_action_queue(
        action_queue=action_queue,
        queued_actions=queued_actions,
        generated_at=generated_at,
    )

    write_json(args.output, plan)
    write_json(args.action_queue, updated_queue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
