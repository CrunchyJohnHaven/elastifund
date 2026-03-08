"""Phase 10 hardening helpers for agent control and robust aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from statistics import fmean, pstdev
from typing import Any, Sequence

import numpy as np
from sqlalchemy.orm import Session

from data_layer import crud


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActivityAnomaly:
    """Result of comparing one activity measurement against recent history."""

    agent_id: str
    metric: str
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    threshold: float
    triggered: bool
    reason: str


@dataclass(frozen=True)
class ModelUpdate:
    """One local model delta submitted by an agent."""

    agent_id: str
    weights: tuple[float, ...]
    stake: float = 1.0
    sample_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregationConfig:
    """Robust aggregation settings for one federated round."""

    byzantine_fraction: float = 0.10
    trim_ratio: float = 0.10
    norm_cap: float = 25.0


@dataclass(frozen=True)
class AggregationResult:
    """Robust aggregation output with explicit provenance."""

    method: str
    aggregate: tuple[float, ...]
    naive_mean: tuple[float, ...]
    selected_agent_ids: tuple[str, ...]
    rejected_agent_ids: tuple[str, ...]
    krum_scores: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)


class HubControlPlane:
    """Minimal hub-side registry and command queue for autonomous agents."""

    def __init__(self, session: Session):
        self.session = session

    def register_agent(
        self,
        *,
        agent_id: str,
        lane: str,
        environment: str,
        metadata: dict[str, Any] | None = None,
    ):
        return crud.upsert_agent_runtime(
            self.session,
            agent_id=agent_id,
            lane=lane,
            environment=environment,
            runtime_metadata=metadata or {},
            status="active",
            anomaly_state="normal",
        )

    def record_heartbeat(
        self,
        *,
        agent_id: str,
        lane: str,
        environment: str,
        activity_metric: str,
        activity_value: float | None,
        metadata: dict[str, Any] | None = None,
        status: str = "active",
        observed_at: datetime | None = None,
    ):
        when = observed_at or _utcnow()
        runtime = crud.upsert_agent_runtime(
            self.session,
            agent_id=agent_id,
            lane=lane,
            environment=environment,
            runtime_metadata=metadata or {},
            status=status,
            last_heartbeat_at=when,
            last_activity_metric=activity_metric,
            last_activity_value=None if activity_value is None else float(activity_value),
        )
        return runtime

    def issue_command(
        self,
        *,
        agent_id: str,
        command_type: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        issued_by: str = "hub",
        ttl_hours: int | None = 24,
    ):
        existing = crud.get_open_agent_command(
            self.session,
            agent_id=agent_id,
            command_type=command_type,
        )
        if existing is not None:
            return existing

        expires_at = None
        if ttl_hours is not None:
            expires_at = _utcnow() + timedelta(hours=max(1, int(ttl_hours)))
        return crud.create_agent_command(
            self.session,
            agent_id=agent_id,
            command_type=command_type,
            reason=reason,
            payload=payload or {},
            issued_by=issued_by,
            expires_at=expires_at,
            status="pending",
        )

    def poll_commands(self, *, agent_id: str):
        return crud.deliver_agent_commands(self.session, agent_id=agent_id)

    def acknowledge_command(self, *, agent_id: str, command_id: int):
        return crud.acknowledge_agent_command(
            self.session,
            command_id=command_id,
            agent_id=agent_id,
        )

    def autopause_on_anomaly(
        self,
        *,
        agent_id: str,
        lane: str,
        environment: str,
        metric: str,
        history_values: Sequence[float | int | None],
        current_value: float | int | None,
        sigma_threshold: float = 3.0,
        min_history: int = 5,
        metadata: dict[str, Any] | None = None,
    ) -> ActivityAnomaly:
        anomaly = detect_activity_anomaly(
            agent_id=agent_id,
            metric=metric,
            history_values=history_values,
            current_value=current_value,
            sigma_threshold=sigma_threshold,
            min_history=min_history,
        )

        status = "paused" if anomaly.triggered else "active"
        anomaly_state = "paused" if anomaly.triggered else "normal"
        self.record_heartbeat(
            agent_id=agent_id,
            lane=lane,
            environment=environment,
            activity_metric=metric,
            activity_value=None if current_value is None else float(current_value),
            metadata=metadata,
            status=status,
        )
        crud.upsert_agent_runtime(
            self.session,
            agent_id=agent_id,
            lane=lane,
            environment=environment,
            status=status,
            runtime_metadata=metadata or {},
            anomaly_state=anomaly_state,
            anomaly_reason=anomaly.reason if anomaly.triggered else "",
        )

        if anomaly.triggered:
            self.issue_command(
                agent_id=agent_id,
                command_type="pause",
                reason=anomaly.reason,
                payload={
                    "metric": anomaly.metric,
                    "z_score": anomaly.z_score,
                    "baseline_mean": anomaly.baseline_mean,
                    "baseline_std": anomaly.baseline_std,
                    "current_value": anomaly.current_value,
                },
                issued_by="auto_guardrail",
            )
        return anomaly


def detect_activity_anomaly(
    *,
    agent_id: str,
    metric: str,
    history_values: Sequence[float | int | None],
    current_value: float | int | None,
    sigma_threshold: float = 3.0,
    min_history: int = 5,
) -> ActivityAnomaly:
    """Flag a pause-worthy activity deviation once enough baseline exists."""

    current = 0.0 if current_value is None else float(current_value)
    baseline = [float(value) for value in history_values if value is not None]
    if len(baseline) < min_history:
        return ActivityAnomaly(
            agent_id=agent_id,
            metric=metric,
            current_value=current,
            baseline_mean=0.0,
            baseline_std=0.0,
            z_score=0.0,
            threshold=sigma_threshold,
            triggered=False,
            reason="insufficient_history",
        )

    mean = fmean(baseline)
    std = pstdev(baseline)
    deviation = current - mean
    if std <= 1e-9:
        z_score = math.inf if abs(deviation) > 1e-9 else 0.0
    else:
        z_score = deviation / std

    triggered = abs(z_score) >= float(sigma_threshold)
    if triggered:
        direction = "high" if z_score > 0 else "low"
        reason = (
            f"{metric}_activity_anomaly_{direction}: "
            f"value={current:.4f} mean={mean:.4f} std={std:.4f} z={z_score:.2f}"
        )
    else:
        reason = "within_expected_range"
    return ActivityAnomaly(
        agent_id=agent_id,
        metric=metric,
        current_value=current,
        baseline_mean=mean,
        baseline_std=std,
        z_score=z_score,
        threshold=float(sigma_threshold),
        triggered=triggered,
        reason=reason,
    )


def aggregate_model_updates(
    updates: Sequence[ModelUpdate],
    *,
    config: AggregationConfig | None = None,
) -> AggregationResult:
    """Aggregate one federated round with Krum-style filtering and stake weighting."""

    if not updates:
        raise ValueError("updates must not be empty")

    cfg = config or AggregationConfig()
    vectors = _matrix_from_updates(updates, norm_cap=cfg.norm_cap)
    agent_ids = [update.agent_id for update in updates]
    stakes = np.asarray([max(0.0001, float(update.stake)) for update in updates], dtype=float)
    stakes = stakes / stakes.sum()

    naive_mean = np.average(vectors, axis=0, weights=stakes)
    byzantine_count = min(
        max(0, int(math.floor(len(updates) * cfg.byzantine_fraction))),
        max(0, len(updates) - 3),
    )
    scores = _krum_scores(vectors, byzantine_count=byzantine_count)
    survivors = _select_survivors(scores, byzantine_count=byzantine_count)
    selected_vectors = vectors[survivors]
    selected_stakes = stakes[survivors]
    selected_agent_ids = tuple(agent_ids[index] for index in survivors)
    rejected_agent_ids = tuple(
        agent_ids[index]
        for index in range(len(agent_ids))
        if index not in survivors
    )

    robust = _stake_weighted_trimmed_mean(
        selected_vectors,
        selected_stakes,
        trim_ratio=cfg.trim_ratio,
    )
    return AggregationResult(
        method="krum_trimmed_mean",
        aggregate=tuple(float(value) for value in robust),
        naive_mean=tuple(float(value) for value in naive_mean),
        selected_agent_ids=selected_agent_ids,
        rejected_agent_ids=rejected_agent_ids,
        krum_scores={agent_ids[index]: float(scores[index]) for index in range(len(agent_ids))},
        metadata={
            "update_count": len(updates),
            "byzantine_count": byzantine_count,
            "survivor_count": len(selected_agent_ids),
            "trim_ratio": cfg.trim_ratio,
            "norm_cap": cfg.norm_cap,
        },
    )


def simulate_federated_round(
    *,
    agent_count: int = 50,
    malicious_fraction: float = 0.10,
    dimensions: int = 12,
    seed: int = 7,
    benign_noise: float = 0.08,
    poison_scale: float = 8.0,
) -> dict[str, Any]:
    """Simulate a robust aggregation round with 10% malicious updates."""

    if agent_count < 5:
        raise ValueError("agent_count must be at least 5")

    rng = np.random.default_rng(seed)
    malicious_count = int(round(agent_count * malicious_fraction))
    if malicious_fraction > 0.0:
        malicious_count = max(1, malicious_count)
    benign_count = agent_count - malicious_count
    target = rng.normal(0.0, 0.35, size=dimensions)
    updates: list[ModelUpdate] = []
    benign_vectors: list[np.ndarray] = []
    malicious_ids: list[str] = []

    for index in range(benign_count):
        vector = target + rng.normal(0.0, benign_noise, size=dimensions)
        benign_vectors.append(vector)
        updates.append(
            ModelUpdate(
                agent_id=f"agent-{index:03d}",
                weights=tuple(float(value) for value in vector),
                stake=float(rng.uniform(0.5, 2.5)),
            )
        )

    poison_direction = np.sign(target)
    poison_direction[poison_direction == 0.0] = 1.0
    for offset in range(malicious_count):
        vector = (-poison_direction * poison_scale) + rng.normal(0.0, 0.25, size=dimensions)
        agent_id = f"agent-m{offset:02d}"
        malicious_ids.append(agent_id)
        updates.append(
            ModelUpdate(
                agent_id=agent_id,
                weights=tuple(float(value) for value in vector),
                stake=float(rng.uniform(0.5, 2.5)),
                metadata={"malicious": True},
            )
        )

    result = aggregate_model_updates(updates)
    benign_mean = np.mean(np.vstack(benign_vectors), axis=0)
    naive_error = float(np.linalg.norm(np.asarray(result.naive_mean) - benign_mean))
    robust_error = float(np.linalg.norm(np.asarray(result.aggregate) - benign_mean))
    rejected_malicious = sorted(set(result.rejected_agent_ids).intersection(malicious_ids))

    return {
        "agent_count": agent_count,
        "malicious_fraction": malicious_fraction,
        "malicious_agent_ids": malicious_ids,
        "rejected_agent_ids": list(result.rejected_agent_ids),
        "rejected_malicious_ids": rejected_malicious,
        "naive_error": naive_error,
        "robust_error": robust_error,
        "aggregate": list(result.aggregate),
        "naive_mean": list(result.naive_mean),
        "survivor_count": result.metadata["survivor_count"],
    }


def monitor_snapshot_activity(
    session: Session,
    *,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    deployment_id: int,
    snapshot: Any,
    sigma_threshold: float = 3.0,
    min_history: int = 5,
) -> ActivityAnomaly:
    """Register one snapshot heartbeat and auto-pause on activity outliers."""

    metric, current_value = _snapshot_activity_metric(snapshot)
    agent_id = _snapshot_agent_id(
        snapshot=snapshot,
        strategy_key=strategy_key,
        version_label=version_label,
        environment=environment,
    )
    history_rows = crud.list_daily_snapshots(
        session,
        deployment_id=deployment_id,
        limit=max(min_history + 5, 20),
    )
    history_values = [
        value
        for row in history_rows
        if row.id != snapshot.id
        for value in [_snapshot_metric_value(row, metric)]
        if value is not None
    ]

    control = HubControlPlane(session)
    control.register_agent(
        agent_id=agent_id,
        lane=lane,
        environment=environment,
        metadata={
            "strategy_key": strategy_key,
            "version_label": version_label,
        },
    )
    return control.autopause_on_anomaly(
        agent_id=agent_id,
        lane=lane,
        environment=environment,
        metric=metric,
        history_values=history_values,
        current_value=current_value,
        sigma_threshold=sigma_threshold,
        min_history=min_history,
        metadata={
            "snapshot_date": getattr(snapshot, "snapshot_date", None),
            "strategy_key": strategy_key,
            "version_label": version_label,
        },
    )


def _matrix_from_updates(
    updates: Sequence[ModelUpdate],
    *,
    norm_cap: float,
) -> np.ndarray:
    dimensions = len(updates[0].weights)
    rows = []
    for update in updates:
        if len(update.weights) != dimensions:
            raise ValueError("all updates must share the same dimensionality")
        vector = np.asarray(update.weights, dtype=float)
        norm = float(np.linalg.norm(vector))
        if norm_cap > 0.0 and norm > norm_cap and norm > 0.0:
            vector = vector * (norm_cap / norm)
        rows.append(vector)
    return np.vstack(rows)


def _krum_scores(vectors: np.ndarray, *, byzantine_count: int) -> np.ndarray:
    if vectors.shape[0] < 3:
        raise ValueError("krum requires at least 3 updates")

    n = vectors.shape[0]
    neighbor_count = max(1, n - byzantine_count - 2)
    scores = np.zeros(n, dtype=float)
    for index in range(n):
        deltas = vectors - vectors[index]
        distances = np.sum(deltas * deltas, axis=1)
        distances = np.delete(distances, index)
        nearest = np.sort(distances)[:neighbor_count]
        scores[index] = float(nearest.sum())
    return scores


def _select_survivors(scores: np.ndarray, *, byzantine_count: int) -> list[int]:
    n = len(scores)
    survivor_count = max(1, n - (2 * byzantine_count) - 2)
    ranked = np.argsort(scores)
    return [int(index) for index in ranked[:survivor_count]]


def _stake_weighted_trimmed_mean(
    vectors: np.ndarray,
    stakes: np.ndarray,
    *,
    trim_ratio: float,
) -> np.ndarray:
    trim_ratio = max(0.0, min(float(trim_ratio), 0.49))
    trim_count = int(math.floor(vectors.shape[0] * trim_ratio))
    output = np.zeros(vectors.shape[1], dtype=float)
    for column in range(vectors.shape[1]):
        order = np.argsort(vectors[:, column])
        kept = order[trim_count : max(trim_count + 1, len(order) - trim_count)]
        kept_values = vectors[kept, column]
        kept_stakes = stakes[kept]
        if float(kept_stakes.sum()) <= 0.0:
            output[column] = float(np.mean(kept_values))
        else:
            output[column] = float(np.average(kept_values, weights=kept_stakes))
    return output


def _snapshot_activity_metric(snapshot: Any) -> tuple[str, float | None]:
    metrics = getattr(snapshot, "metrics", None) or {}
    metric = metrics.get("activity_metric") or "closed_trades"
    return metric, _snapshot_metric_value(snapshot, metric)


def _snapshot_metric_value(snapshot: Any, metric: str) -> float | None:
    metrics = getattr(snapshot, "metrics", None) or {}
    metric_name = metrics.get("activity_metric")
    if metric_name == metric and metrics.get("activity_value") is not None:
        return float(metrics["activity_value"])
    value = getattr(snapshot, metric, None)
    if value is None:
        return None
    return float(value)


def _snapshot_agent_id(
    *,
    snapshot: Any,
    strategy_key: str,
    version_label: str,
    environment: str,
) -> str:
    metrics = getattr(snapshot, "metrics", None) or {}
    if metrics.get("agent_id"):
        return str(metrics["agent_id"])
    return f"{strategy_key}:{version_label}:{environment}"
