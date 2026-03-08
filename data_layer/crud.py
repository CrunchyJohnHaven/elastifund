"""Clean CRUD access layer for all tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .schema import (
    AgentCommand,
    AgentRuntime,
    DailySnapshot,
    DetectorRun,
    EdgeCard,
    Experiment,
    FlywheelCycle,
    FlywheelFinding,
    FlywheelTask,
    FundingAllocation,
    FundingProposal,
    FundingRound,
    Market,
    Opportunity,
    OrderbookSnapshot,
    PeerImprovementBundle,
    PromotionDecision,
    ContributorProfile,
    ReputationEvent,
    StrategyDeployment,
    StrategyVersion,
    SystemLog,
    TradeTick,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_reserved_metadata(
    kwargs: dict[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    if "metadata" not in kwargs or field_name in kwargs:
        return kwargs
    normalized = dict(kwargs)
    normalized[field_name] = normalized.pop("metadata")
    return normalized


# ── Markets ──────────────────────────────────────────────────────────

def upsert_market(session: Session, market_id: str, **kwargs) -> Market:
    """Insert or update a market by market_id."""
    row = session.execute(
        select(Market).where(Market.market_id == market_id)
    ).scalar_one_or_none()
    if row is None:
        row = Market(market_id=market_id, **kwargs)
        session.add(row)
    else:
        for k, v in kwargs.items():
            setattr(row, k, v)
        row.updated_at = _utcnow()
    session.flush()
    return row


def get_market(session: Session, market_id: str) -> Market | None:
    return session.execute(
        select(Market).where(Market.market_id == market_id)
    ).scalar_one_or_none()


def list_markets(
    session: Session,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Market]:
    q = select(Market)
    if status:
        q = q.where(Market.status == status)
    q = q.order_by(Market.updated_at.desc()).limit(limit).offset(offset)
    return list(session.execute(q).scalars().all())


# ── Orderbook snapshots ─────────────────────────────────────────────

def add_orderbook_snapshot(session: Session, **kwargs) -> OrderbookSnapshot:
    row = OrderbookSnapshot(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_orderbook_snapshots(
    session: Session,
    token_id: str,
    limit: int = 50,
) -> list[OrderbookSnapshot]:
    q = (
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.token_id == token_id)
        .order_by(OrderbookSnapshot.fetched_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Trade ticks ──────────────────────────────────────────────────────

def add_trade_tick(session: Session, **kwargs) -> TradeTick:
    row = TradeTick(**kwargs)
    session.add(row)
    session.flush()
    return row


def add_trade_ticks_bulk(session: Session, rows: list[dict]) -> int:
    objects = [TradeTick(**r) for r in rows]
    session.add_all(objects)
    session.flush()
    return len(objects)


def get_trade_ticks(
    session: Session,
    token_id: str,
    limit: int = 100,
) -> list[TradeTick]:
    q = (
        select(TradeTick)
        .where(TradeTick.token_id == token_id)
        .order_by(TradeTick.fetched_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Detector runs ────────────────────────────────────────────────────

def create_detector_run(session: Session, **kwargs) -> DetectorRun:
    row = DetectorRun(**kwargs)
    session.add(row)
    session.flush()
    return row


def finish_detector_run(
    session: Session,
    run_id: int,
    *,
    status: str = "success",
    markets_scanned: int = 0,
    edges_found: int = 0,
    opportunities_created: int = 0,
    error_detail: str | None = None,
) -> None:
    session.execute(
        update(DetectorRun)
        .where(DetectorRun.id == run_id)
        .values(
            finished_at=_utcnow(),
            status=status,
            markets_scanned=markets_scanned,
            edges_found=edges_found,
            opportunities_created=opportunities_created,
            error_detail=error_detail,
        )
    )
    session.flush()
    session.expire_all()


def get_detector_run(session: Session, run_id: int) -> DetectorRun | None:
    return session.get(DetectorRun, run_id)


def list_detector_runs(
    session: Session, limit: int = 20
) -> list[DetectorRun]:
    q = (
        select(DetectorRun)
        .order_by(DetectorRun.started_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Edge cards ───────────────────────────────────────────────────────

def add_edge_card(session: Session, **kwargs) -> EdgeCard:
    row = EdgeCard(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_edge_cards_for_run(
    session: Session, run_id: int
) -> list[EdgeCard]:
    q = (
        select(EdgeCard)
        .where(EdgeCard.run_id == run_id)
        .order_by(EdgeCard.edge.desc())
    )
    return list(session.execute(q).scalars().all())


def get_edge_cards_for_market(
    session: Session, market_id: str, limit: int = 20
) -> list[EdgeCard]:
    q = (
        select(EdgeCard)
        .where(EdgeCard.market_id == market_id)
        .order_by(EdgeCard.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── Opportunities ────────────────────────────────────────────────────

def create_opportunity(session: Session, **kwargs) -> Opportunity:
    row = Opportunity(**kwargs)
    session.add(row)
    session.flush()
    return row


def resolve_opportunity(
    session: Session,
    opp_id: int,
    *,
    outcome: str,
    pnl: float,
) -> None:
    session.execute(
        update(Opportunity)
        .where(Opportunity.id == opp_id)
        .values(
            status="resolved",
            outcome=outcome,
            pnl=pnl,
            resolved_at=_utcnow(),
        )
    )
    session.flush()
    session.expire_all()


def list_opportunities(
    session: Session,
    status: str | None = None,
    limit: int = 50,
) -> list[Opportunity]:
    q = select(Opportunity)
    if status:
        q = q.where(Opportunity.status == status)
    q = q.order_by(Opportunity.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Experiments ──────────────────────────────────────────────────────

def create_experiment(session: Session, **kwargs) -> Experiment:
    row = Experiment(**kwargs)
    session.add(row)
    session.flush()
    return row


def complete_experiment(
    session: Session,
    exp_id: int,
    *,
    status: str = "completed",
    result_summary: str | None = None,
    result_data: dict | None = None,
) -> None:
    session.execute(
        update(Experiment)
        .where(Experiment.id == exp_id)
        .values(
            status=status,
            result_summary=result_summary,
            result_data=result_data,
            completed_at=_utcnow(),
        )
    )
    session.flush()
    session.expire_all()


def get_experiment(session: Session, name: str) -> Experiment | None:
    return session.execute(
        select(Experiment).where(Experiment.name == name)
    ).scalar_one_or_none()


def list_experiments(session: Session, limit: int = 20) -> list[Experiment]:
    q = (
        select(Experiment)
        .order_by(Experiment.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(q).scalars().all())


# ── System logs ──────────────────────────────────────────────────────

def log(
    session: Session,
    level: str,
    component: str,
    message: str,
    data: dict | None = None,
) -> SystemLog:
    row = SystemLog(level=level, component=component, message=message, data=data)
    session.add(row)
    session.flush()
    return row


def get_logs(
    session: Session,
    level: str | None = None,
    component: str | None = None,
    limit: int = 100,
) -> list[SystemLog]:
    q = select(SystemLog)
    if level:
        q = q.where(SystemLog.level == level)
    if component:
        q = q.where(SystemLog.component == component)
    q = q.order_by(SystemLog.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Flywheel strategy registry ───────────────────────────────────────

def create_strategy_version(session: Session, **kwargs) -> StrategyVersion:
    row = StrategyVersion(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_strategy_version(
    session: Session,
    strategy_key: str,
    version_label: str,
) -> StrategyVersion | None:
    return session.execute(
        select(StrategyVersion).where(
            StrategyVersion.strategy_key == strategy_key,
            StrategyVersion.version_label == version_label,
        )
    ).scalar_one_or_none()


def get_or_create_strategy_version(
    session: Session,
    strategy_key: str,
    version_label: str,
    **kwargs,
) -> StrategyVersion:
    row = get_strategy_version(session, strategy_key, version_label)
    if row is None:
        row = create_strategy_version(
            session,
            strategy_key=strategy_key,
            version_label=version_label,
            **kwargs,
        )
    return row


def list_strategy_versions(
    session: Session,
    lane: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[StrategyVersion]:
    q = select(StrategyVersion)
    if lane:
        q = q.where(StrategyVersion.lane == lane)
    if status:
        q = q.where(StrategyVersion.status == status)
    q = q.order_by(StrategyVersion.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Flywheel deployments ─────────────────────────────────────────────

def create_deployment(session: Session, **kwargs) -> StrategyDeployment:
    row = StrategyDeployment(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_active_deployment(
    session: Session,
    strategy_version_id: int,
    environment: str,
) -> StrategyDeployment | None:
    return session.execute(
        select(StrategyDeployment).where(
            StrategyDeployment.strategy_version_id == strategy_version_id,
            StrategyDeployment.environment == environment,
            StrategyDeployment.status == "active",
        )
    ).scalar_one_or_none()


def get_or_create_deployment(
    session: Session,
    strategy_version_id: int,
    environment: str,
    **kwargs,
) -> StrategyDeployment:
    row = get_active_deployment(session, strategy_version_id, environment)
    if row is None:
        row = create_deployment(
            session,
            strategy_version_id=strategy_version_id,
            environment=environment,
            **kwargs,
        )
    else:
        for key, value in kwargs.items():
            setattr(row, key, value)
        session.flush()
    return row


def end_deployment(
    session: Session,
    deployment_id: int,
    *,
    status: str = "ended",
) -> None:
    session.execute(
        update(StrategyDeployment)
        .where(StrategyDeployment.id == deployment_id)
        .values(status=status, ended_at=_utcnow())
    )
    session.flush()
    session.expire_all()


def list_deployments(
    session: Session,
    environment: str | None = None,
    status: str | None = None,
    strategy_version_id: int | None = None,
    limit: int = 100,
) -> list[StrategyDeployment]:
    q = select(StrategyDeployment)
    if environment:
        q = q.where(StrategyDeployment.environment == environment)
    if status:
        q = q.where(StrategyDeployment.status == status)
    if strategy_version_id is not None:
        q = q.where(StrategyDeployment.strategy_version_id == strategy_version_id)
    q = q.order_by(StrategyDeployment.started_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Flywheel snapshots ───────────────────────────────────────────────

def create_daily_snapshot(session: Session, **kwargs) -> DailySnapshot:
    row = DailySnapshot(**kwargs)
    session.add(row)
    session.flush()
    return row


def list_daily_snapshots(
    session: Session,
    environment: str | None = None,
    strategy_version_id: int | None = None,
    deployment_id: int | None = None,
    limit: int = 100,
) -> list[DailySnapshot]:
    q = select(DailySnapshot)
    if environment:
        q = q.where(DailySnapshot.environment == environment)
    if strategy_version_id is not None:
        q = q.where(DailySnapshot.strategy_version_id == strategy_version_id)
    if deployment_id is not None:
        q = q.where(DailySnapshot.deployment_id == deployment_id)
    q = q.order_by(DailySnapshot.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def get_latest_snapshot(
    session: Session,
    *,
    environment: str | None = None,
    strategy_version_id: int | None = None,
    deployment_id: int | None = None,
) -> DailySnapshot | None:
    rows = list_daily_snapshots(
        session,
        environment=environment,
        strategy_version_id=strategy_version_id,
        deployment_id=deployment_id,
        limit=1,
    )
    return rows[0] if rows else None


# ── Flywheel promotion decisions ─────────────────────────────────────

def create_promotion_decision(session: Session, **kwargs) -> PromotionDecision:
    row = PromotionDecision(**kwargs)
    session.add(row)
    session.flush()
    return row


def list_promotion_decisions(
    session: Session,
    strategy_version_id: int | None = None,
    decision: str | None = None,
    limit: int = 100,
) -> list[PromotionDecision]:
    q = select(PromotionDecision)
    if strategy_version_id is not None:
        q = q.where(PromotionDecision.strategy_version_id == strategy_version_id)
    if decision:
        q = q.where(PromotionDecision.decision == decision)
    q = q.order_by(PromotionDecision.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Flywheel cycles and tasks ────────────────────────────────────────

def create_flywheel_cycle(session: Session, **kwargs) -> FlywheelCycle:
    row = FlywheelCycle(**kwargs)
    session.add(row)
    session.flush()
    return row


def finish_flywheel_cycle(
    session: Session,
    cycle_id: int,
    *,
    status: str = "completed",
    summary: str | None = None,
    artifacts_path: str | None = None,
) -> None:
    session.execute(
        update(FlywheelCycle)
        .where(FlywheelCycle.id == cycle_id)
        .values(
            status=status,
            summary=summary,
            artifacts_path=artifacts_path,
            finished_at=_utcnow(),
        )
    )
    session.flush()
    session.expire_all()


def get_flywheel_cycle(session: Session, cycle_key: str) -> FlywheelCycle | None:
    return session.execute(
        select(FlywheelCycle).where(FlywheelCycle.cycle_key == cycle_key)
    ).scalar_one_or_none()


def list_flywheel_cycles(session: Session, limit: int = 20) -> list[FlywheelCycle]:
    q = select(FlywheelCycle).order_by(FlywheelCycle.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def create_flywheel_finding(session: Session, **kwargs) -> FlywheelFinding:
    row = FlywheelFinding(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_flywheel_finding(session: Session, finding_key: str) -> FlywheelFinding | None:
    return session.execute(
        select(FlywheelFinding).where(FlywheelFinding.finding_key == finding_key)
    ).scalar_one_or_none()


def get_or_create_flywheel_finding(
    session: Session,
    *,
    finding_key: str,
    **kwargs,
) -> FlywheelFinding:
    row = get_flywheel_finding(session, finding_key)
    if row is None:
        row = create_flywheel_finding(session, finding_key=finding_key, **kwargs)
        return row
    return row


def list_flywheel_findings(
    session: Session,
    *,
    cycle_id: int | None = None,
    lane: str | None = None,
    environment: str | None = None,
    source_kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[FlywheelFinding]:
    q = select(FlywheelFinding)
    if cycle_id is not None:
        q = q.where(FlywheelFinding.cycle_id == cycle_id)
    if lane:
        q = q.where(FlywheelFinding.lane == lane)
    if environment:
        q = q.where(FlywheelFinding.environment == environment)
    if source_kind:
        q = q.where(FlywheelFinding.source_kind == source_kind)
    if status:
        q = q.where(FlywheelFinding.status == status)
    q = q.order_by(FlywheelFinding.priority.asc(), FlywheelFinding.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def create_flywheel_task(session: Session, **kwargs) -> FlywheelTask:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="metadata_json")
    row = FlywheelTask(**kwargs)
    session.add(row)
    session.flush()
    return row


def list_flywheel_tasks(
    session: Session,
    cycle_id: int | None = None,
    lane: str | None = None,
    environment: str | None = None,
    source_kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[FlywheelTask]:
    q = select(FlywheelTask)
    if cycle_id is not None:
        q = q.where(FlywheelTask.cycle_id == cycle_id)
    if lane:
        q = q.where(FlywheelTask.lane == lane)
    if environment:
        q = q.where(FlywheelTask.environment == environment)
    if source_kind:
        q = q.where(FlywheelTask.source_kind == source_kind)
    if status:
        q = q.where(FlywheelTask.status == status)
    q = q.order_by(FlywheelTask.priority.asc(), FlywheelTask.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Peer improvement exchange ────────────────────────────────────────

def create_peer_improvement_bundle(session: Session, **kwargs) -> PeerImprovementBundle:
    row = PeerImprovementBundle(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_peer_improvement_bundle(
    session: Session,
    bundle_id: str,
    *,
    direction: str | None = None,
) -> PeerImprovementBundle | None:
    q = select(PeerImprovementBundle).where(PeerImprovementBundle.bundle_id == bundle_id)
    if direction:
        q = q.where(PeerImprovementBundle.direction == direction)
    q = q.order_by(PeerImprovementBundle.created_at.desc()).limit(1)
    return session.execute(q).scalar_one_or_none()


def list_peer_improvement_bundles(
    session: Session,
    *,
    peer_name: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[PeerImprovementBundle]:
    q = select(PeerImprovementBundle)
    if peer_name:
        q = q.where(PeerImprovementBundle.peer_name == peer_name)
    if direction:
        q = q.where(PeerImprovementBundle.direction == direction)
    if status:
        q = q.where(PeerImprovementBundle.status == status)
    q = q.order_by(PeerImprovementBundle.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


# ── Agent runtimes and hub commands ──────────────────────────────────

def create_agent_runtime(session: Session, **kwargs) -> AgentRuntime:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="runtime_metadata")
    row = AgentRuntime(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_agent_runtime(session: Session, agent_id: str) -> AgentRuntime | None:
    return session.execute(
        select(AgentRuntime).where(AgentRuntime.agent_id == agent_id)
    ).scalar_one_or_none()


def upsert_agent_runtime(
    session: Session,
    *,
    agent_id: str,
    lane: str,
    environment: str,
    **kwargs,
) -> AgentRuntime:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="runtime_metadata")
    row = get_agent_runtime(session, agent_id)
    if row is None:
        row = create_agent_runtime(
            session,
            agent_id=agent_id,
            lane=lane,
            environment=environment,
            **kwargs,
        )
        return row

    row.lane = lane
    row.environment = environment
    for key, value in kwargs.items():
        setattr(row, key, value)
    row.updated_at = _utcnow()
    session.flush()
    return row


def list_agent_runtimes(
    session: Session,
    *,
    lane: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[AgentRuntime]:
    q = select(AgentRuntime)
    if lane:
        q = q.where(AgentRuntime.lane == lane)
    if status:
        q = q.where(AgentRuntime.status == status)
    q = q.order_by(AgentRuntime.updated_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def create_agent_command(session: Session, **kwargs) -> AgentCommand:
    row = AgentCommand(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_agent_command(session: Session, command_id: int) -> AgentCommand | None:
    return session.get(AgentCommand, command_id)


def list_agent_commands(
    session: Session,
    *,
    agent_id: str | None = None,
    command_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[AgentCommand]:
    q = select(AgentCommand)
    if agent_id:
        q = q.where(AgentCommand.agent_id == agent_id)
    if command_type:
        q = q.where(AgentCommand.command_type == command_type)
    if status:
        q = q.where(AgentCommand.status == status)
    q = q.order_by(AgentCommand.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def get_open_agent_command(
    session: Session,
    *,
    agent_id: str,
    command_type: str,
) -> AgentCommand | None:
    return session.execute(
        select(AgentCommand).where(
            AgentCommand.agent_id == agent_id,
            AgentCommand.command_type == command_type,
            AgentCommand.status.in_(("pending", "delivered")),
        )
    ).scalar_one_or_none()


def deliver_agent_commands(
    session: Session,
    *,
    agent_id: str,
    now: datetime | None = None,
    limit: int = 100,
) -> list[AgentCommand]:
    current = now or _utcnow()
    rows = list_agent_commands(session, agent_id=agent_id, status="pending", limit=limit)
    delivered: list[AgentCommand] = []
    for row in rows:
        expires_at = row.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at is not None and expires_at <= current:
            row.status = "expired"
            continue
        row.status = "delivered"
        row.delivered_at = current
        delivered.append(row)
    session.flush()
    return delivered


def acknowledge_agent_command(
    session: Session,
    *,
    command_id: int,
    agent_id: str,
    now: datetime | None = None,
) -> AgentCommand | None:
    row = session.execute(
        select(AgentCommand).where(
            AgentCommand.id == command_id,
            AgentCommand.agent_id == agent_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.status = "acknowledged"
    row.acknowledged_at = now or _utcnow()
    session.flush()
    return row


# ── Contributor incentives ───────────────────────────────────────────

def create_contributor_profile(session: Session, **kwargs) -> ContributorProfile:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="metadata_json")
    row = ContributorProfile(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_contributor_profile(
    session: Session,
    contributor_key: str,
) -> ContributorProfile | None:
    return session.execute(
        select(ContributorProfile).where(ContributorProfile.contributor_key == contributor_key)
    ).scalar_one_or_none()


def get_or_create_contributor_profile(
    session: Session,
    contributor_key: str,
    **kwargs,
) -> ContributorProfile:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="metadata_json")
    row = get_contributor_profile(session, contributor_key)
    if row is None:
        row = create_contributor_profile(
            session,
            contributor_key=contributor_key,
            **kwargs,
        )
    else:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(row, key, value)
        session.flush()
    return row


def list_contributor_profiles(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[ContributorProfile]:
    q = select(ContributorProfile)
    if status:
        q = q.where(ContributorProfile.status == status)
    q = q.order_by(
        ContributorProfile.total_reputation_points.desc(),
        ContributorProfile.updated_at.desc(),
    ).limit(limit)
    return list(session.execute(q).scalars().all())


def create_reputation_event(session: Session, **kwargs) -> ReputationEvent:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="metadata_json")
    row = ReputationEvent(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_reputation_event(
    session: Session,
    event_key: str,
) -> ReputationEvent | None:
    return session.execute(
        select(ReputationEvent).where(ReputationEvent.event_key == event_key)
    ).scalar_one_or_none()


def list_reputation_events(
    session: Session,
    *,
    contributor_profile_id: int | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[ReputationEvent]:
    q = select(ReputationEvent)
    if contributor_profile_id is not None:
        q = q.where(ReputationEvent.contributor_profile_id == contributor_profile_id)
    if event_type:
        q = q.where(ReputationEvent.event_type == event_type)
    q = q.order_by(ReputationEvent.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def summarize_reputation_events(
    session: Session,
    contributor_profile_id: int,
) -> dict[str, int]:
    rows = session.execute(
        select(
            ReputationEvent.event_type,
            func.coalesce(func.sum(ReputationEvent.points_delta), 0),
        )
        .where(ReputationEvent.contributor_profile_id == contributor_profile_id)
        .group_by(ReputationEvent.event_type)
    ).all()
    return {event_type: int(total or 0) for event_type, total in rows}


def create_funding_round(session: Session, **kwargs) -> FundingRound:
    row = FundingRound(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_funding_round(session: Session, round_key: str) -> FundingRound | None:
    return session.execute(
        select(FundingRound).where(FundingRound.round_key == round_key)
    ).scalar_one_or_none()


def list_funding_rounds(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[FundingRound]:
    q = select(FundingRound)
    if status:
        q = q.where(FundingRound.status == status)
    q = q.order_by(FundingRound.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())


def create_funding_proposal(session: Session, **kwargs) -> FundingProposal:
    kwargs = _normalize_reserved_metadata(kwargs, field_name="metadata_json")
    row = FundingProposal(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_funding_proposal(
    session: Session,
    *,
    round_id: int | None = None,
    round_key: str | None = None,
    proposal_key: str,
) -> FundingProposal | None:
    q = select(FundingProposal).where(FundingProposal.proposal_key == proposal_key)
    if round_id is not None:
        q = q.where(FundingProposal.round_id == round_id)
    elif round_key is not None:
        round_row = get_funding_round(session, round_key)
        if round_row is None:
            return None
        q = q.where(FundingProposal.round_id == round_row.id)
    return session.execute(q).scalar_one_or_none()


def list_funding_proposals(
    session: Session,
    *,
    round_id: int | None = None,
    status: str | None = None,
    owner_contributor_profile_id: int | None = None,
    limit: int = 100,
) -> list[FundingProposal]:
    q = select(FundingProposal)
    if round_id is not None:
        q = q.where(FundingProposal.round_id == round_id)
    if status:
        q = q.where(FundingProposal.status == status)
    if owner_contributor_profile_id is not None:
        q = q.where(FundingProposal.owner_contributor_profile_id == owner_contributor_profile_id)
    q = q.order_by(
        FundingProposal.matched_amount_usd.desc(),
        FundingProposal.created_at.desc(),
    ).limit(limit)
    return list(session.execute(q).scalars().all())


def create_funding_allocation(session: Session, **kwargs) -> FundingAllocation:
    row = FundingAllocation(**kwargs)
    session.add(row)
    session.flush()
    return row


def get_funding_allocation(
    session: Session,
    *,
    round_id: int,
    proposal_id: int,
    contributor_profile_id: int,
) -> FundingAllocation | None:
    return session.execute(
        select(FundingAllocation).where(
            FundingAllocation.round_id == round_id,
            FundingAllocation.proposal_id == proposal_id,
            FundingAllocation.contributor_profile_id == contributor_profile_id,
        )
    ).scalar_one_or_none()


def upsert_funding_allocation(
    session: Session,
    *,
    round_id: int,
    proposal_id: int,
    contributor_profile_id: int,
    voice_credits: int,
    notes: str | None = None,
) -> FundingAllocation:
    row = get_funding_allocation(
        session,
        round_id=round_id,
        proposal_id=proposal_id,
        contributor_profile_id=contributor_profile_id,
    )
    if row is None:
        row = create_funding_allocation(
            session,
            round_id=round_id,
            proposal_id=proposal_id,
            contributor_profile_id=contributor_profile_id,
            voice_credits=voice_credits,
            notes=notes,
        )
    else:
        row.voice_credits = voice_credits
        row.notes = notes
        row.updated_at = _utcnow()
        session.flush()
    return row


def list_funding_allocations(
    session: Session,
    *,
    round_id: int | None = None,
    proposal_id: int | None = None,
    contributor_profile_id: int | None = None,
    limit: int = 1000,
) -> list[FundingAllocation]:
    q = select(FundingAllocation)
    if round_id is not None:
        q = q.where(FundingAllocation.round_id == round_id)
    if proposal_id is not None:
        q = q.where(FundingAllocation.proposal_id == proposal_id)
    if contributor_profile_id is not None:
        q = q.where(FundingAllocation.contributor_profile_id == contributor_profile_id)
    q = q.order_by(FundingAllocation.created_at.desc()).limit(limit)
    return list(session.execute(q).scalars().all())
