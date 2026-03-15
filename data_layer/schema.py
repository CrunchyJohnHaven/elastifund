"""SQLAlchemy 2.0 models — synchronous SQLite data layer.

Tables:
  markets, orderbook_snapshots, trade_ticks, edge_cards,
  experiments, detector_runs, opportunities, system_logs,
  flywheel control-plane entities, contributor incentives
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Float, Index, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Markets ──────────────────────────────────────────────────────────

class Market(Base):
    """Canonical market record.  One row per Polymarket condition_id."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    condition_id: Mapped[Optional[str]] = mapped_column(String(255))
    question: Mapped[Optional[str]] = mapped_column(Text)
    slug: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    outcome_yes_price: Mapped[Optional[float]] = mapped_column(Float)
    outcome_no_price: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    liquidity: Mapped[Optional[float]] = mapped_column(Float)
    clob_token_id_yes: Mapped[Optional[str]] = mapped_column(String(255))
    clob_token_id_no: Mapped[Optional[str]] = mapped_column(String(255))
    end_date: Mapped[Optional[str]] = mapped_column(String(50))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    resolution: Mapped[Optional[str]] = mapped_column(String(10))  # YES, NO, null
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


# ── Orderbook snapshots ─────────────────────────────────────────────

class OrderbookSnapshot(Base):
    """Point-in-time orderbook snapshot."""

    __tablename__ = "orderbook_snapshots"
    __table_args__ = (
        Index("ix_ob_token_ts", "token_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side_label: Mapped[Optional[str]] = mapped_column(String(10))  # YES / NO
    best_bid: Mapped[Optional[float]] = mapped_column(Float)
    best_ask: Mapped[Optional[float]] = mapped_column(Float)
    spread: Mapped[Optional[float]] = mapped_column(Float)
    midpoint: Mapped[Optional[float]] = mapped_column(Float)
    bid_depth: Mapped[int] = mapped_column(Integer, default=0)
    ask_depth: Mapped[int] = mapped_column(Integer, default=0)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


# ── Trade ticks ──────────────────────────────────────────────────────

class TradeTick(Base):
    """Individual trade tick."""

    __tablename__ = "trade_ticks"
    __table_args__ = (
        Index("ix_tt_token_ts", "token_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(255), index=True)
    side_label: Mapped[Optional[str]] = mapped_column(String(10))
    price: Mapped[Optional[float]] = mapped_column(Float)
    size: Mapped[Optional[float]] = mapped_column(Float)
    side: Mapped[Optional[str]] = mapped_column(String(10))  # BUY / SELL
    trade_ts: Mapped[Optional[str]] = mapped_column(String(50))  # original API ts
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


# ── Detector runs ────────────────────────────────────────────────────

class DetectorRun(Base):
    """One execution of the edge-detection pipeline."""

    __tablename__ = "detector_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="running")
    markets_scanned: Mapped[int] = mapped_column(Integer, default=0)
    edges_found: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_created: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[Optional[dict]] = mapped_column(JSON)
    error_detail: Mapped[Optional[str]] = mapped_column(Text)


# ── Edge cards ───────────────────────────────────────────────────────

class EdgeCard(Base):
    """A single edge signal produced by the detector."""

    __tablename__ = "edge_cards"
    __table_args__ = (
        Index("ix_ec_market_created", "market_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("detector_runs.id"), index=True
    )
    side: Mapped[str] = mapped_column(String(10))  # buy_yes / buy_no
    model_prob: Mapped[float] = mapped_column(Float)
    market_price: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    confidence: Mapped[Optional[str]] = mapped_column(String(20))
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


# ── Opportunities ────────────────────────────────────────────────────

class Opportunity(Base):
    """Actionable trade opportunity derived from an edge card."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    edge_card_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("edge_cards.id"), index=True
    )
    market_id: Mapped[str] = mapped_column(String(255), index=True)
    side: Mapped[str] = mapped_column(String(10))
    entry_price: Mapped[float] = mapped_column(Float)
    model_prob: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")
    outcome: Mapped[Optional[str]] = mapped_column(String(10))  # win / loss
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column()


# ── Experiments ──────────────────────────────────────────────────────

class Experiment(Base):
    """Tracked experiment (prompt variant, threshold change, etc.)."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    result_summary: Mapped[Optional[str]] = mapped_column(Text)
    result_data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column()


# ── System logs ──────────────────────────────────────────────────────

class SystemLog(Base):
    """Structured log entry."""

    __tablename__ = "system_logs"
    __table_args__ = (
        Index("ix_syslog_level_ts", "level", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(10))  # DEBUG..CRITICAL
    component: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


# ── Flywheel control plane ───────────────────────────────────────────

class StrategyVersion(Base):
    """Immutable deployable strategy artifact tracked by the control plane."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_key", "version_label", name="uq_strategy_version"),
        Index("ix_sv_lane_status", "lane", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_key: Mapped[str] = mapped_column(String(255), index=True)
    version_label: Mapped[str] = mapped_column(String(255))
    lane: Mapped[str] = mapped_column(String(50), index=True)
    artifact_uri: Mapped[Optional[str]] = mapped_column(String(500))
    git_sha: Mapped[Optional[str]] = mapped_column(String(64))
    config: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="candidate")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class StrategyDeployment(Base):
    """A strategy version running in one environment."""

    __tablename__ = "strategy_deployments"
    __table_args__ = (
        Index("ix_sd_env_status", "environment", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("strategy_versions.id"), index=True
    )
    environment: Mapped[str] = mapped_column(String(30), index=True)
    capital_cap_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column()


class DailySnapshot(Base):
    """Environment- or strategy-level scorecard used by flywheel automations."""

    __tablename__ = "daily_snapshots"
    __table_args__ = (
        Index("ix_ds_env_date", "environment", "snapshot_date"),
        Index("ix_ds_strategy_date", "strategy_version_id", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategy_versions.id"), index=True
    )
    deployment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategy_deployments.id"), index=True
    )
    environment: Mapped[str] = mapped_column(String(30), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)
    starting_bankroll: Mapped[float] = mapped_column(Float)
    ending_bankroll: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    closed_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(Float)
    fill_rate: Mapped[Optional[float]] = mapped_column(Float)
    avg_slippage_bps: Mapped[Optional[float]] = mapped_column(Float)
    rolling_brier: Mapped[Optional[float]] = mapped_column(Float)
    rolling_ece: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    kill_events: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class PromotionDecision(Base):
    """Audit trail for every promotion, hold, demotion, or kill evaluation."""

    __tablename__ = "promotion_decisions"
    __table_args__ = (
        Index("ix_pd_strategy_created", "strategy_version_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("strategy_versions.id"), index=True
    )
    deployment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategy_deployments.id"), index=True
    )
    from_stage: Mapped[str] = mapped_column(String(30))
    to_stage: Mapped[str] = mapped_column(String(30))
    decision: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(100))
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class FlywheelCycle(Base):
    """Sequential control-plane cycle run."""

    __tablename__ = "flywheel_cycles"
    __table_args__ = (
        UniqueConstraint("cycle_key", name="uq_flywheel_cycle_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cycle_key: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    summary: Mapped[Optional[str]] = mapped_column(Text)
    artifacts_path: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column()


class FlywheelFinding(Base):
    """Structured lesson, regression, or promotion signal captured by the control plane."""

    __tablename__ = "flywheel_findings"
    __table_args__ = (
        UniqueConstraint("finding_key", name="uq_flywheel_finding_key"),
        Index("ix_ff_lane_status", "lane", "status"),
        Index("ix_ff_source_priority", "source_kind", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_key: Mapped[str] = mapped_column(String(255), index=True)
    cycle_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("flywheel_cycles.id"), index=True
    )
    strategy_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategy_versions.id"), index=True
    )
    lane: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    environment: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    source_kind: Mapped[str] = mapped_column(String(50), index=True)
    finding_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    lesson: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class FlywheelTask(Base):
    """Explicit next action generated by a flywheel cycle."""

    __tablename__ = "flywheel_tasks"
    __table_args__ = (
        Index("ix_ft_cycle_status", "cycle_id", "status"),
        Index("ix_ft_action_priority", "action", "priority"),
        Index("ix_ft_lane_status_priority", "lane", "status", "priority"),
        Index("ix_ft_source_created", "source_kind", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cycle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("flywheel_cycles.id"), index=True
    )
    strategy_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategy_versions.id"), index=True
    )
    finding_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("flywheel_findings.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(20), default="open")
    lane: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    environment: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    source_kind: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255))
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class PeerImprovementBundle(Base):
    """Portable peer bundle containing code, claims, and evidence."""

    __tablename__ = "peer_improvement_bundles"
    __table_args__ = (
        UniqueConstraint("bundle_id", "direction", name="uq_peer_improvement_bundle"),
        Index("ix_pib_peer_direction", "peer_name", "direction"),
        Index("ix_pib_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bundle_id: Mapped[str] = mapped_column(String(255), index=True)
    peer_name: Mapped[str] = mapped_column(String(255), index=True)
    strategy_key: Mapped[str] = mapped_column(String(255), index=True)
    version_label: Mapped[str] = mapped_column(String(255))
    lane: Mapped[Optional[str]] = mapped_column(String(50))
    outcome: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(20))
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    status: Mapped[str] = mapped_column(String(20), default="recorded")
    summary: Mapped[Optional[str]] = mapped_column(Text)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text)
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    signature_hmac_sha256: Mapped[Optional[str]] = mapped_column(String(128))
    review_artifact_path: Mapped[Optional[str]] = mapped_column(String(500))
    cycle_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("flywheel_cycles.id"), index=True
    )
    raw_bundle: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class AgentRuntime(Base):
    """Control-plane view of one forked agent runtime."""

    __tablename__ = "agent_runtimes"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_runtime_agent_id"),
        Index("ix_ar_lane_status", "lane", "status"),
        Index("ix_ar_heartbeat", "last_heartbeat_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(255), index=True)
    lane: Mapped[str] = mapped_column(String(50), index=True)
    environment: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(index=True)
    last_activity_metric: Mapped[Optional[str]] = mapped_column(String(100))
    last_activity_value: Mapped[Optional[float]] = mapped_column(Float)
    anomaly_state: Mapped[str] = mapped_column(String(20), default="normal")
    anomaly_reason: Mapped[Optional[str]] = mapped_column(Text)
    runtime_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow, index=True)


class AgentCommand(Base):
    """Hub-issued command delivered to one agent."""

    __tablename__ = "agent_commands"
    __table_args__ = (
        Index("ix_ac_agent_status_created", "agent_id", "status", "created_at"),
        Index("ix_ac_command_status", "command_type", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(255), index=True)
    command_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reason: Mapped[str] = mapped_column(Text)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    issued_by: Mapped[Optional[str]] = mapped_column(String(100))
    expires_at: Mapped[Optional[datetime]] = mapped_column(index=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(index=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


# ── Flywheel incentive system ────────────────────────────────────────

class ContributorProfile(Base):
    """Community contributor tracked for reputation and funding rights."""

    __tablename__ = "contributor_profiles"
    __table_args__ = (
        Index("ix_cp_status_reputation", "status", "total_reputation_points"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contributor_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    github_handle: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    total_reputation_points: Mapped[int] = mapped_column(Integer, default=0)
    code_points: Mapped[int] = mapped_column(Integer, default=0)
    performance_points: Mapped[int] = mapped_column(Integer, default=0)
    bug_points: Mapped[int] = mapped_column(Integer, default=0)
    docs_points: Mapped[int] = mapped_column(Integer, default=0)
    review_points: Mapped[int] = mapped_column(Integer, default=0)
    reputation_tier: Mapped[str] = mapped_column(String(30), default="seed")
    unlocks: Mapped[Optional[dict]] = mapped_column(JSON)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class ReputationEvent(Base):
    """Immutable reputation delta tied to one contributor and one evidence source."""

    __tablename__ = "reputation_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_reputation_event_key"),
        Index("ix_re_contributor_created", "contributor_profile_id", "created_at"),
        Index("ix_re_type_created", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    contributor_profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contributor_profiles.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    points_delta: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[Optional[str]] = mapped_column(String(50))
    source_ref: Mapped[Optional[str]] = mapped_column(String(500))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class FundingRound(Base):
    """Quadratic-funding round for community-prioritized build work."""

    __tablename__ = "funding_rounds"
    __table_args__ = (
        UniqueConstraint("round_key", name="uq_funding_round_key"),
        Index("ix_fr_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    round_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    matching_pool_usd: Mapped[float] = mapped_column(Float, default=0.0)
    results: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column()
    closed_at: Mapped[Optional[datetime]] = mapped_column()


class FundingProposal(Base):
    """Feature or template proposal competing for a funding round."""

    __tablename__ = "funding_proposals"
    __table_args__ = (
        UniqueConstraint("round_id", "proposal_key", name="uq_funding_proposal_key"),
        Index("ix_fp_round_status_match", "round_id", "status", "matched_amount_usd"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("funding_rounds.id"), index=True)
    proposal_key: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    owner_contributor_profile_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contributor_profiles.id"), index=True
    )
    requested_amount_usd: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="active")
    direct_voice_credits: Mapped[int] = mapped_column(Integer, default=0)
    unique_supporters: Mapped[int] = mapped_column(Integer, default=0)
    quadratic_score: Mapped[float] = mapped_column(Float, default=0.0)
    matched_amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)


class FundingAllocation(Base):
    """Voice-credit allocation from one contributor to one funding proposal."""

    __tablename__ = "funding_allocations"
    __table_args__ = (
        UniqueConstraint(
            "round_id",
            "proposal_id",
            "contributor_profile_id",
            name="uq_funding_allocation",
        ),
        Index("ix_fa_round_contributor", "round_id", "contributor_profile_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("funding_rounds.id"), index=True)
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("funding_proposals.id"), index=True
    )
    contributor_profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contributor_profiles.id"), index=True
    )
    voice_credits: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
