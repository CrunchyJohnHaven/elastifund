from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


BENCHMARK_EVIDENCE_SPEC_VERSION = "2026.03-openclaw1"
COMPARISON_ONLY_MODE = "comparison_only"


def _round_optional(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _normalize_winner(value: str | None) -> str:
    normalized = str(value or "undetermined").strip().lower().replace("-", "_")
    aliases = {
        "elastifund": "reference",
        "primary": "reference",
        "candidate": "comparison",
        "openclaw": "comparison",
        "secondary": "comparison",
        "draw": "tie",
        "unknown": "undetermined",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"reference", "comparison", "tie", "undetermined"}:
        raise ValueError(f"Unsupported comparison winner: {value}")
    return normalized


@dataclass(frozen=True)
class OutcomeComparison:
    """One benchmark case normalized into the shared comparison contract."""

    case_id: str
    reference_system_id: str = "elastifund"
    comparison_system_id: str = "openclaw"
    reference_value: Any = None
    comparison_value: Any = None
    comparator: str = "manual_review"
    winner: str = "undetermined"
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        case_id = str(self.case_id).strip()
        if not case_id:
            raise ValueError("case_id is required")
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "reference_system_id", str(self.reference_system_id).strip() or "elastifund")
        object.__setattr__(self, "comparison_system_id", str(self.comparison_system_id).strip() or "openclaw")
        object.__setattr__(self, "comparator", str(self.comparator).strip() or "manual_review")
        object.__setattr__(self, "winner", _normalize_winner(self.winner))
        object.__setattr__(self, "notes", None if self.notes is None else str(self.notes).strip() or None)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        reference_system_id: str = "elastifund",
        comparison_system_id: str = "openclaw",
    ) -> "OutcomeComparison":
        data = dict(payload)
        return cls(
            case_id=str(data.get("case_id") or data.get("id") or ""),
            reference_system_id=str(
                data.get("reference_system_id")
                or data.get("reference_system")
                or reference_system_id
            ),
            comparison_system_id=str(
                data.get("comparison_system_id")
                or data.get("comparison_system")
                or comparison_system_id
            ),
            reference_value=data.get("reference_value", data.get("elastifund_value")),
            comparison_value=data.get("comparison_value", data.get("openclaw_value")),
            comparator=str(data.get("comparator") or "manual_review"),
            winner=str(data.get("winner") or "undetermined"),
            notes=data.get("notes"),
            metadata=data.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "reference_system_id": self.reference_system_id,
            "comparison_system_id": self.comparison_system_id,
            "reference_value": self.reference_value,
            "comparison_value": self.comparison_value,
            "comparator": self.comparator,
            "winner": self.winner,
            "notes": self.notes,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BenchmarkTelemetrySummary:
    """Operational metrics required by the shared benchmark evidence plane."""

    decision_count: int = 0
    completed_decision_count: int = 0
    skipped_decision_count: int = 0
    error_decision_count: int = 0
    webhook_count: int = 0
    model_usage_events: int = 0
    avg_cycle_time_ms: float | None = None
    p95_cycle_time_ms: float | None = None
    avg_model_duration_ms: float | None = None
    total_cost_usd: float = 0.0
    max_lane_queue_size: int = 0
    heartbeat_max_active: int = 0
    heartbeat_max_waiting: int = 0
    heartbeat_max_queued: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_count", max(0, int(self.decision_count)))
        object.__setattr__(
            self,
            "completed_decision_count",
            max(0, int(self.completed_decision_count)),
        )
        object.__setattr__(
            self,
            "skipped_decision_count",
            max(0, int(self.skipped_decision_count)),
        )
        object.__setattr__(self, "error_decision_count", max(0, int(self.error_decision_count)))
        object.__setattr__(self, "webhook_count", max(0, int(self.webhook_count)))
        object.__setattr__(self, "model_usage_events", max(0, int(self.model_usage_events)))
        object.__setattr__(self, "avg_cycle_time_ms", _round_optional(self.avg_cycle_time_ms))
        object.__setattr__(self, "p95_cycle_time_ms", _round_optional(self.p95_cycle_time_ms))
        object.__setattr__(
            self,
            "avg_model_duration_ms",
            _round_optional(self.avg_model_duration_ms),
        )
        object.__setattr__(self, "total_cost_usd", round(max(0.0, float(self.total_cost_usd)), 6))
        object.__setattr__(self, "max_lane_queue_size", max(0, int(self.max_lane_queue_size)))
        object.__setattr__(self, "heartbeat_max_active", max(0, int(self.heartbeat_max_active)))
        object.__setattr__(self, "heartbeat_max_waiting", max(0, int(self.heartbeat_max_waiting)))
        object.__setattr__(self, "heartbeat_max_queued", max(0, int(self.heartbeat_max_queued)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_count": self.decision_count,
            "completed_decision_count": self.completed_decision_count,
            "skipped_decision_count": self.skipped_decision_count,
            "error_decision_count": self.error_decision_count,
            "webhook_count": self.webhook_count,
            "model_usage_events": self.model_usage_events,
            "avg_cycle_time_ms": self.avg_cycle_time_ms,
            "p95_cycle_time_ms": self.p95_cycle_time_ms,
            "avg_model_duration_ms": self.avg_model_duration_ms,
            "total_cost_usd": self.total_cost_usd,
            "max_lane_queue_size": self.max_lane_queue_size,
            "heartbeat_max_active": self.heartbeat_max_active,
            "heartbeat_max_waiting": self.heartbeat_max_waiting,
            "heartbeat_max_queued": self.heartbeat_max_queued,
        }


@dataclass(frozen=True)
class IsolationBoundary:
    """Isolation contract for clean-room comparison systems."""

    namespace: str
    secrets_scope: str = "isolated"
    state_scope: str = "isolated"
    wallet_access: str = "none"
    shared_state_access: str = "none"
    log_index_prefix: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        namespace = str(self.namespace).strip()
        if not namespace:
            raise ValueError("namespace is required")
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "secrets_scope", str(self.secrets_scope).strip() or "isolated")
        object.__setattr__(self, "state_scope", str(self.state_scope).strip() or "isolated")
        object.__setattr__(self, "wallet_access", str(self.wallet_access).strip() or "none")
        object.__setattr__(
            self,
            "shared_state_access",
            str(self.shared_state_access).strip() or "none",
        )
        object.__setattr__(
            self,
            "log_index_prefix",
            None if self.log_index_prefix is None else str(self.log_index_prefix).strip() or None,
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "secrets_scope": self.secrets_scope,
            "state_scope": self.state_scope,
            "wallet_access": self.wallet_access,
            "shared_state_access": self.shared_state_access,
            "log_index_prefix": self.log_index_prefix,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BenchmarkEvidencePacket:
    """Machine-readable benchmark artifact emitted by external-system adapters."""

    system_id: str
    system_name: str
    run_id: str
    comparison_mode: str
    allocator_eligible: bool
    upstream_repo: str
    upstream_commit: str
    spec_version: str = BENCHMARK_EVIDENCE_SPEC_VERSION
    execution_label: str = "internal_simulation"
    evaluation_track: str = COMPARISON_ONLY_MODE
    captured_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    telemetry: BenchmarkTelemetrySummary = field(default_factory=BenchmarkTelemetrySummary)
    isolation: IsolationBoundary = field(default_factory=lambda: IsolationBoundary(namespace="comparison-only"))
    outcome_comparisons: tuple[OutcomeComparison, ...] = field(default_factory=tuple)
    source_artifacts: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_id", str(self.system_id).strip())
        object.__setattr__(self, "system_name", str(self.system_name).strip())
        object.__setattr__(self, "run_id", str(self.run_id).strip())
        object.__setattr__(self, "comparison_mode", str(self.comparison_mode).strip() or COMPARISON_ONLY_MODE)
        object.__setattr__(self, "allocator_eligible", bool(self.allocator_eligible))
        object.__setattr__(self, "upstream_repo", str(self.upstream_repo).strip())
        object.__setattr__(self, "upstream_commit", str(self.upstream_commit).strip())
        object.__setattr__(self, "execution_label", str(self.execution_label).strip() or "internal_simulation")
        object.__setattr__(self, "evaluation_track", str(self.evaluation_track).strip() or COMPARISON_ONLY_MODE)
        object.__setattr__(
            self,
            "telemetry",
            self.telemetry
            if isinstance(self.telemetry, BenchmarkTelemetrySummary)
            else BenchmarkTelemetrySummary(**dict(self.telemetry)),
        )
        object.__setattr__(
            self,
            "isolation",
            self.isolation
            if isinstance(self.isolation, IsolationBoundary)
            else IsolationBoundary(**dict(self.isolation)),
        )
        object.__setattr__(
            self,
            "outcome_comparisons",
            tuple(
                item if isinstance(item, OutcomeComparison) else OutcomeComparison.from_mapping(item)
                for item in self.outcome_comparisons
            ),
        )
        object.__setattr__(
            self,
            "source_artifacts",
            tuple(str(item) for item in self.source_artifacts),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "system_id": self.system_id,
            "system_name": self.system_name,
            "run_id": self.run_id,
            "comparison_mode": self.comparison_mode,
            "allocator_eligible": self.allocator_eligible,
            "upstream_repo": self.upstream_repo,
            "upstream_commit": self.upstream_commit,
            "execution_label": self.execution_label,
            "evaluation_track": self.evaluation_track,
            "captured_at": self.captured_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "telemetry": self.telemetry.to_dict(),
            "isolation": self.isolation.to_dict(),
            "outcome_comparisons": [item.to_dict() for item in self.outcome_comparisons],
            "source_artifacts": list(self.source_artifacts),
            "metadata": dict(self.metadata),
        }
