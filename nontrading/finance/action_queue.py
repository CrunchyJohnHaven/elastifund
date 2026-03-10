"""Queue manager for finance actions."""

from __future__ import annotations

from typing import Any

from nontrading.finance.models import utc_now
from nontrading.finance.models import FinanceAction
from nontrading.finance.store import FinanceStore


class FinanceActionQueue:
    """Persist and render queued finance actions."""

    def __init__(self, store: FinanceStore):
        self.store = store

    def sync_actions(self, actions: list[FinanceAction]) -> list[FinanceAction]:
        persisted: list[FinanceAction] = []
        for action in actions:
            persisted.append(self.store.upsert_action(action))
        return persisted

    def list_pending(self) -> list[FinanceAction]:
        return self.store.list_actions(statuses=("queued", "shadowed"))

    def build_report(self) -> dict[str, Any]:
        actions = self.store.list_actions()
        return {
            "schema_version": "finance_action_queue.v1",
            "generated_at": utc_now(),
            "summary": {
                "queued": sum(1 for action in actions if action.status == "queued"),
                "shadowed": sum(1 for action in actions if action.status == "shadowed"),
                "executed": sum(1 for action in actions if action.status == "executed"),
                "rejected": sum(1 for action in actions if action.status == "rejected"),
            },
            "actions": [action.__dict__ for action in actions],
        }
