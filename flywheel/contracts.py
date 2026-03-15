"""Typed contracts for flywheel cycle packets and promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_REQUIRED_SNAPSHOT_FIELDS = (
    "snapshot_date",
    "starting_bankroll",
    "ending_bankroll",
    "realized_pnl",
    "unrealized_pnl",
    "open_positions",
    "closed_trades",
    "max_drawdown_pct",
    "kill_events",
)


@dataclass(frozen=True)
class SnapshotRecord:
    """Normalized deployment snapshot attached to one cycle packet."""

    snapshot_date: str
    starting_bankroll: float
    ending_bankroll: float
    realized_pnl: float
    unrealized_pnl: float
    open_positions: int
    closed_trades: int
    max_drawdown_pct: float
    kill_events: int
    win_rate: float | None = None
    fill_rate: float | None = None
    avg_slippage_bps: float | None = None
    rolling_brier: float | None = None
    rolling_ece: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotRecord":
        missing = [key for key in _REQUIRED_SNAPSHOT_FIELDS if key not in payload]
        if missing:
            raise ValueError(f"snapshot missing required fields: {', '.join(missing)}")
        return cls(
            snapshot_date=str(payload["snapshot_date"]),
            starting_bankroll=float(payload["starting_bankroll"]),
            ending_bankroll=float(payload["ending_bankroll"]),
            realized_pnl=float(payload["realized_pnl"]),
            unrealized_pnl=float(payload["unrealized_pnl"]),
            open_positions=int(payload["open_positions"]),
            closed_trades=int(payload["closed_trades"]),
            win_rate=_float_or_none(payload.get("win_rate")),
            fill_rate=_float_or_none(payload.get("fill_rate")),
            avg_slippage_bps=_float_or_none(payload.get("avg_slippage_bps")),
            rolling_brier=_float_or_none(payload.get("rolling_brier")),
            rolling_ece=_float_or_none(payload.get("rolling_ece")),
            max_drawdown_pct=float(payload["max_drawdown_pct"]),
            kill_events=int(payload["kill_events"]),
            metrics=_dict_or_empty(payload.get("metrics")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_date": self.snapshot_date,
            "starting_bankroll": self.starting_bankroll,
            "ending_bankroll": self.ending_bankroll,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "open_positions": self.open_positions,
            "closed_trades": self.closed_trades,
            "win_rate": self.win_rate,
            "fill_rate": self.fill_rate,
            "avg_slippage_bps": self.avg_slippage_bps,
            "rolling_brier": self.rolling_brier,
            "rolling_ece": self.rolling_ece,
            "max_drawdown_pct": self.max_drawdown_pct,
            "kill_events": self.kill_events,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True)
class DeploymentRecord:
    """Normalized deployment record inside one strategy packet."""

    environment: str
    capital_cap_usd: float
    status: str = "active"
    notes: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    snapshot: SnapshotRecord | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeploymentRecord":
        snapshot_payload = payload.get("snapshot")
        return cls(
            environment=str(payload["environment"]),
            capital_cap_usd=float(payload.get("capital_cap_usd", 0.0)),
            status=str(payload.get("status", "active")),
            notes=None if payload.get("notes") is None else str(payload.get("notes")),
            metrics=_dict_or_empty(payload.get("metrics")),
            snapshot=None
            if snapshot_payload is None
            else SnapshotRecord.from_dict(_dict_or_empty(snapshot_payload)),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "environment": self.environment,
            "capital_cap_usd": self.capital_cap_usd,
            "status": self.status,
        }
        if self.notes is not None:
            data["notes"] = self.notes
        if self.metrics:
            data["metrics"] = dict(self.metrics)
        if self.snapshot is not None:
            data["snapshot"] = self.snapshot.to_dict()
        return data


@dataclass(frozen=True)
class StrategyRecord:
    """Normalized strategy record in one cycle packet."""

    strategy_key: str
    version_label: str
    lane: str
    deployments: list[DeploymentRecord]
    status: str = "candidate"
    artifact_uri: str | None = None
    git_sha: str | None = None
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StrategyRecord":
        deployments = [
            DeploymentRecord.from_dict(_dict_or_empty(item))
            for item in list(payload.get("deployments") or [])
            if isinstance(item, dict)
        ]
        return cls(
            strategy_key=str(payload["strategy_key"]),
            version_label=str(payload["version_label"]),
            lane=str(payload["lane"]),
            deployments=deployments,
            status=str(payload.get("status", "candidate")),
            artifact_uri=None if payload.get("artifact_uri") is None else str(payload.get("artifact_uri")),
            git_sha=None if payload.get("git_sha") is None else str(payload.get("git_sha")),
            config=_dict_or_empty(payload.get("config")),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "strategy_key": self.strategy_key,
            "version_label": self.version_label,
            "lane": self.lane,
            "status": self.status,
            "deployments": [item.to_dict() for item in self.deployments],
        }
        if self.artifact_uri is not None:
            data["artifact_uri"] = self.artifact_uri
        if self.git_sha is not None:
            data["git_sha"] = self.git_sha
        if self.config:
            data["config"] = dict(self.config)
        return data


@dataclass(frozen=True)
class CyclePacket:
    """Canonical input packet for one flywheel control-plane cycle."""

    cycle_key: str | None
    strategies: list[StrategyRecord]
    control_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CyclePacket":
        if not isinstance(payload, dict):
            raise ValueError("cycle packet must be a JSON object")
        strategies_raw = payload.get("strategies")
        if strategies_raw is None:
            strategies_raw = []
        if not isinstance(strategies_raw, list):
            raise ValueError("cycle packet field 'strategies' must be a list")
        strategies = [
            StrategyRecord.from_dict(_dict_or_empty(item))
            for item in strategies_raw
            if isinstance(item, dict)
        ]
        return cls(
            cycle_key=None if payload.get("cycle_key") in {None, ""} else str(payload.get("cycle_key")),
            strategies=strategies,
            control_context=_dict_or_empty(payload.get("control_context")),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "strategies": [item.to_dict() for item in self.strategies],
        }
        if self.cycle_key is not None:
            data["cycle_key"] = self.cycle_key
        if self.control_context:
            data["control_context"] = dict(self.control_context)
        return data


@dataclass(frozen=True)
class PromotionDecisionRecord:
    """Canonical decision record emitted by flywheel policy."""

    id: int | None
    strategy_key: str
    version_label: str
    decision: str
    from_stage: str
    to_stage: str
    reason_code: str
    notes: str | None
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "strategy_key": self.strategy_key,
            "version_label": self.version_label,
            "decision": self.decision,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "reason_code": self.reason_code,
            "notes": self.notes,
            "priority": self.priority,
        }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
