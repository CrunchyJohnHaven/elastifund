"""A-6 state helpers: quarantine persistence and linked-leg snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any

from execution.multileg_executor import MultiLegAttempt


@dataclass(frozen=True)
class QuarantineRecord:
    token_id: str
    failures: int
    next_retry_ts: float
    last_reason: str
    last_status_code: int | None
    updated_ts: float


class A6QuarantineCache:
    """Persist token-level orderbook failures with exponential backoff."""

    BACKOFF_SECONDS = (600.0, 3600.0, 21600.0)

    def __init__(self, path: str | Path = Path("data") / "a6_quarantine_tokens.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, QuarantineRecord] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return

        records = payload.get("records", payload)
        if not isinstance(records, dict):
            return
        for token_id, raw in records.items():
            if not isinstance(raw, dict):
                continue
            try:
                self._records[str(token_id)] = QuarantineRecord(
                    token_id=str(token_id),
                    failures=int(raw.get("failures") or 0),
                    next_retry_ts=float(raw.get("next_retry_ts") or 0.0),
                    last_reason=str(raw.get("last_reason") or ""),
                    last_status_code=int(raw["last_status_code"]) if raw.get("last_status_code") is not None else None,
                    updated_ts=float(raw.get("updated_ts") or 0.0),
                )
            except (TypeError, ValueError):
                continue

    def save(self) -> None:
        payload = {
            "updated_ts": time.time(),
            "records": {
                token_id: {
                    "failures": record.failures,
                    "next_retry_ts": record.next_retry_ts,
                    "last_reason": record.last_reason,
                    "last_status_code": record.last_status_code,
                    "updated_ts": record.updated_ts,
                }
                for token_id, record in sorted(self._records.items())
            },
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def is_quarantined(self, token_id: str, *, now_ts: float | None = None) -> bool:
        record = self._records.get(str(token_id))
        if record is None:
            return False
        return (now_ts or time.time()) < record.next_retry_ts

    def mark_failure(
        self,
        token_id: str,
        *,
        reason: str,
        status_code: int | None = None,
        now_ts: float | None = None,
    ) -> QuarantineRecord:
        token_id = str(token_id)
        now = float(now_ts or time.time())
        prev = self._records.get(token_id)
        failures = 1 if prev is None else prev.failures + 1
        idx = min(len(self.BACKOFF_SECONDS) - 1, max(0, failures - 1))
        record = QuarantineRecord(
            token_id=token_id,
            failures=failures,
            next_retry_ts=now + self.BACKOFF_SECONDS[idx],
            last_reason=str(reason),
            last_status_code=status_code,
            updated_ts=now,
        )
        self._records[token_id] = record
        self.save()
        return record

    def mark_success(self, token_id: str) -> None:
        if str(token_id) in self._records:
            self._records.pop(str(token_id), None)
            self.save()

    def snapshot(self) -> dict[str, QuarantineRecord]:
        return dict(self._records)


def attempt_to_linked_state(attempt: MultiLegAttempt) -> dict[str, Any]:
    """Serialize a multi-leg attempt into `jj_state.json` friendly data."""
    return {
        "attempt_id": attempt.attempt_id,
        "strategy_id": attempt.strategy_id,
        "group_id": attempt.group_id,
        "state": attempt.state.value,
        "created_ts": attempt.created_ts,
        "signal_ts": attempt.signal_ts,
        "orders_live_ts": attempt.orders_live_ts,
        "fill_ttl_seconds": attempt.fill_ttl_seconds,
        "unwind_started_ts": attempt.unwind_started_ts,
        "frozen_reason": attempt.frozen_reason,
        "metadata": dict(attempt.metadata),
        "legs": [
            {
                "leg_id": leg.spec.leg_id,
                "market_id": leg.spec.market_id,
                "token_id": leg.spec.token_id,
                "side": leg.spec.side,
                "price": leg.spec.price,
                "size": leg.spec.size,
                "tick_size": leg.spec.tick_size,
                "min_size": leg.spec.min_size,
                "order_id": leg.order_id,
                "unwind_order_id": leg.unwind_order_id,
                "filled_size": leg.filled_size,
                "avg_fill_price": leg.avg_fill_price,
                "status": leg.status,
                "last_update_ts": leg.last_update_ts,
            }
            for leg in attempt.legs
        ],
    }
