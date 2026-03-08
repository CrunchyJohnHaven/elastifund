"""Contributor reputation and quadratic-funding utilities for the flywheel."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from data_layer import crud
from data_layer.schema import ContributorProfile, DailySnapshot, PromotionDecision

EVENT_BUCKETS = {
    "code_contribution": "code_points",
    "strategy_performance": "performance_points",
    "bug_report": "bug_points",
    "documentation": "docs_points",
    "peer_review": "review_points",
}

DEFAULT_EVENT_POINTS = {
    "code_contribution": 40,
    "strategy_performance": 25,
    "bug_report": 30,
    "documentation": 20,
    "peer_review": 15,
}

DECISION_BONUS = {
    "promote": 40,
    "hold": 10,
    "demote": -20,
    "kill": -40,
}


def award_reputation_event(
    session: Session,
    *,
    contributor_key: str,
    event_type: str,
    points_delta: int | None = None,
    display_name: str | None = None,
    github_handle: str | None = None,
    event_key: str | None = None,
    source_kind: str | None = None,
    source_ref: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one immutable reputation event and refresh contributor totals."""

    normalized_event = _normalize_event_type(event_type)
    profile = crud.get_or_create_contributor_profile(
        session,
        contributor_key=contributor_key,
        display_name=display_name,
        github_handle=github_handle,
    )
    resolved_key = event_key or _derive_event_key(
        contributor_key=contributor_key,
        event_type=normalized_event,
        source_kind=source_kind,
        source_ref=source_ref,
        summary=summary,
        metadata=metadata,
    )
    existing = crud.get_reputation_event(session, resolved_key)
    if existing is not None:
        return {
            "already_recorded": True,
            "event_key": resolved_key,
            "points_delta": existing.points_delta,
            "profile": refresh_contributor_profile(session, contributor_profile_id=profile.id),
        }

    points = int(points_delta if points_delta is not None else DEFAULT_EVENT_POINTS[normalized_event])
    crud.create_reputation_event(
        session,
        event_key=resolved_key,
        contributor_profile_id=profile.id,
        event_type=normalized_event,
        points_delta=points,
        source_kind=source_kind,
        source_ref=source_ref,
        summary=summary,
        metadata=metadata,
    )
    return {
        "already_recorded": False,
        "event_key": resolved_key,
        "points_delta": points,
        "profile": refresh_contributor_profile(session, contributor_profile_id=profile.id),
    }


def award_github_contribution(
    session: Session,
    *,
    contributor_key: str,
    contribution_type: str,
    merged_prs: int = 0,
    files_changed: int = 0,
    lines_changed: int = 0,
    linked_issues: int = 0,
    review_comments: int = 0,
    display_name: str | None = None,
    github_handle: str | None = None,
    event_key: str | None = None,
    source_ref: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Award reputation points from GitHub-style contribution evidence."""

    normalized_event = _normalize_event_type(contribution_type)
    points = calculate_github_points(
        contribution_type=normalized_event,
        merged_prs=merged_prs,
        files_changed=files_changed,
        lines_changed=lines_changed,
        linked_issues=linked_issues,
        review_comments=review_comments,
    )
    metadata = {
        "merged_prs": merged_prs,
        "files_changed": files_changed,
        "lines_changed": lines_changed,
        "linked_issues": linked_issues,
        "review_comments": review_comments,
    }
    return award_reputation_event(
        session,
        contributor_key=contributor_key,
        display_name=display_name,
        github_handle=github_handle,
        event_type=normalized_event,
        points_delta=points,
        event_key=event_key,
        source_kind="github_activity",
        source_ref=source_ref,
        summary=summary,
        metadata=metadata,
    )


def award_strategy_performance(
    session: Session,
    *,
    contributor_key: str,
    strategy_key: str,
    version_label: str,
    display_name: str | None = None,
    github_handle: str | None = None,
    event_key: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Award reputation based on the latest verified flywheel performance."""

    version = crud.get_strategy_version(session, strategy_key, version_label)
    if version is None:
        raise RuntimeError(f"Unknown strategy version: {strategy_key}:{version_label}")

    snapshot = crud.get_latest_snapshot(session, strategy_version_id=version.id)
    if snapshot is None:
        raise RuntimeError(
            f"No verified snapshot found for strategy version {strategy_key}:{version_label}"
        )

    decision = next(
        iter(crud.list_promotion_decisions(session, strategy_version_id=version.id, limit=1)),
        None,
    )
    points = calculate_performance_points(snapshot, decision)
    source_ref = f"{strategy_key}:{version_label}:{snapshot.snapshot_date}"
    metadata = {
        "strategy_key": strategy_key,
        "version_label": version_label,
        "snapshot_date": snapshot.snapshot_date,
        "environment": snapshot.environment,
        "realized_pnl": snapshot.realized_pnl,
        "starting_bankroll": snapshot.starting_bankroll,
        "closed_trades": snapshot.closed_trades,
        "max_drawdown_pct": snapshot.max_drawdown_pct,
        "decision": decision.decision if decision else None,
        "reason_code": decision.reason_code if decision else None,
    }
    return award_reputation_event(
        session,
        contributor_key=contributor_key,
        display_name=display_name,
        github_handle=github_handle,
        event_type="strategy_performance",
        points_delta=points,
        event_key=event_key,
        source_kind="flywheel_snapshot",
        source_ref=source_ref,
        summary=summary or _default_performance_summary(strategy_key, version_label, snapshot, decision),
        metadata=metadata,
    )


def refresh_contributor_profile(
    session: Session,
    *,
    contributor_profile_id: int | None = None,
    contributor_key: str | None = None,
) -> dict[str, Any]:
    """Recompute contributor totals, tier, and unlocks from immutable events."""

    profile = _get_profile(session, contributor_profile_id=contributor_profile_id, contributor_key=contributor_key)
    if profile is None:
        raise RuntimeError("Unknown contributor profile")

    summary = crud.summarize_reputation_events(session, profile.id)
    code_points = int(summary.get("code_contribution", 0))
    performance_points = int(summary.get("strategy_performance", 0))
    bug_points = int(summary.get("bug_report", 0))
    docs_points = int(summary.get("documentation", 0))
    review_points = int(summary.get("peer_review", 0))
    total_points = code_points + performance_points + bug_points + docs_points + review_points
    unlock_state = compute_unlock_state(
        total_points=total_points,
        code_points=code_points,
        performance_points=performance_points,
        bug_points=bug_points,
        docs_points=docs_points,
        review_points=review_points,
    )

    profile.code_points = code_points
    profile.performance_points = performance_points
    profile.bug_points = bug_points
    profile.docs_points = docs_points
    profile.review_points = review_points
    profile.total_reputation_points = total_points
    profile.reputation_tier = unlock_state["tier"]
    profile.unlocks = unlock_state["unlocks"]
    session.flush()
    return _profile_payload(profile)


def build_reputation_leaderboard(session: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return the top contributors ordered by total reputation points."""

    rows = crud.list_contributor_profiles(session, limit=limit)
    return [_profile_payload(row) for row in rows]


def create_funding_round(
    session: Session,
    *,
    round_key: str,
    title: str,
    description: str | None = None,
    matching_pool_usd: float = 0.0,
    status: str = "open",
) -> dict[str, Any]:
    """Create or update a funding round."""

    row = crud.get_funding_round(session, round_key)
    now = _utcnow()
    if row is None:
        row = crud.create_funding_round(
            session,
            round_key=round_key,
            title=title,
            description=description,
            matching_pool_usd=float(matching_pool_usd),
            status=status,
            opened_at=now if status == "open" else None,
        )
    else:
        row.title = title
        row.description = description
        row.matching_pool_usd = float(matching_pool_usd)
        row.status = status
        if status == "open" and row.opened_at is None:
            row.opened_at = now
        session.flush()
    return _round_payload(row)


def submit_funding_proposal(
    session: Session,
    *,
    round_key: str,
    proposal_key: str,
    title: str,
    description: str,
    owner_contributor_key: str | None = None,
    owner_display_name: str | None = None,
    owner_github_handle: str | None = None,
    requested_amount_usd: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update one proposal inside a funding round."""

    round_row = crud.get_funding_round(session, round_key)
    if round_row is None:
        raise RuntimeError(f"Unknown funding round: {round_key}")

    owner_id = None
    if owner_contributor_key:
        owner = crud.get_or_create_contributor_profile(
            session,
            contributor_key=owner_contributor_key,
            display_name=owner_display_name,
            github_handle=owner_github_handle,
        )
        owner_id = owner.id

    proposal = crud.get_funding_proposal(session, round_id=round_row.id, proposal_key=proposal_key)
    if proposal is None:
        proposal = crud.create_funding_proposal(
            session,
            round_id=round_row.id,
            proposal_key=proposal_key,
            title=title,
            description=description,
            owner_contributor_profile_id=owner_id,
            requested_amount_usd=requested_amount_usd,
            metadata=metadata,
        )
    else:
        proposal.title = title
        proposal.description = description
        proposal.owner_contributor_profile_id = owner_id
        proposal.requested_amount_usd = requested_amount_usd
        proposal.metadata_json = metadata
        session.flush()
    return _proposal_payload(proposal)


def allocate_voice_credits(
    session: Session,
    *,
    round_key: str,
    proposal_key: str,
    contributor_key: str,
    voice_credits: int,
    display_name: str | None = None,
    github_handle: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Allocate a contributor's bounded voice credits to one funding proposal."""

    if voice_credits <= 0:
        raise ValueError("voice_credits must be positive")

    round_row = crud.get_funding_round(session, round_key)
    if round_row is None:
        raise RuntimeError(f"Unknown funding round: {round_key}")
    if round_row.status not in {"draft", "open"}:
        raise RuntimeError(f"Funding round {round_key} is not open for allocations")

    proposal = crud.get_funding_proposal(session, round_id=round_row.id, proposal_key=proposal_key)
    if proposal is None:
        raise RuntimeError(f"Unknown proposal {proposal_key} in round {round_key}")
    if proposal.status != "active":
        raise RuntimeError(f"Proposal {proposal_key} is not active")

    profile = crud.get_or_create_contributor_profile(
        session,
        contributor_key=contributor_key,
        display_name=display_name,
        github_handle=github_handle,
    )
    budget = voice_credit_budget(profile.total_reputation_points)
    existing_allocations = crud.list_funding_allocations(
        session,
        round_id=round_row.id,
        contributor_profile_id=profile.id,
    )
    used_without_target = sum(
        row.voice_credits for row in existing_allocations if row.proposal_id != proposal.id
    )
    if used_without_target + voice_credits > budget:
        raise ValueError(
            f"Voice-credit budget exceeded: requested {used_without_target + voice_credits}, "
            f"budget {budget}"
        )

    crud.upsert_funding_allocation(
        session,
        round_id=round_row.id,
        proposal_id=proposal.id,
        contributor_profile_id=profile.id,
        voice_credits=voice_credits,
        notes=notes,
    )
    round_results = tally_funding_round(session, round_key=round_key, close_round=False)
    used = sum(
        row.voice_credits
        for row in crud.list_funding_allocations(
            session,
            round_id=round_row.id,
            contributor_profile_id=profile.id,
        )
    )
    return {
        "round": _round_payload(round_row),
        "proposal": _proposal_payload(proposal),
        "contributor": _profile_payload(profile),
        "voice_credit_budget": budget,
        "voice_credits_used": used,
        "voice_credits_remaining": budget - used,
        "results": round_results,
    }


def tally_funding_round(
    session: Session,
    *,
    round_key: str,
    close_round: bool = False,
) -> dict[str, Any]:
    """Compute quadratic-funding results and persist the latest round scoreboard."""

    round_row = crud.get_funding_round(session, round_key)
    if round_row is None:
        raise RuntimeError(f"Unknown funding round: {round_key}")

    proposals = crud.list_funding_proposals(session, round_id=round_row.id, limit=500)
    allocations = crud.list_funding_allocations(session, round_id=round_row.id, limit=5000)
    by_proposal: dict[int, list[Any]] = {proposal.id: [] for proposal in proposals}
    for allocation in allocations:
        by_proposal.setdefault(allocation.proposal_id, []).append(allocation)

    intermediate: list[dict[str, Any]] = []
    total_matching_units = 0.0
    for proposal in proposals:
        proposal_allocations = by_proposal.get(proposal.id, [])
        direct_credits = int(sum(row.voice_credits for row in proposal_allocations))
        supporter_count = len({row.contributor_profile_id for row in proposal_allocations})
        root_sum = sum(math.sqrt(max(row.voice_credits, 0)) for row in proposal_allocations)
        quadratic_score = round(root_sum ** 2, 6)
        matching_units = max(quadratic_score - float(direct_credits), 0.0)
        total_matching_units += matching_units
        intermediate.append(
            {
                "proposal": proposal,
                "direct_credits": direct_credits,
                "supporter_count": supporter_count,
                "quadratic_score": quadratic_score,
                "matching_units": matching_units,
            }
        )

    proposal_results: list[dict[str, Any]] = []
    for row in intermediate:
        proposal = row["proposal"]
        matched_amount = 0.0
        if total_matching_units > 0:
            matched_amount = round(
                round_row.matching_pool_usd * row["matching_units"] / total_matching_units,
                2,
            )
        proposal.direct_voice_credits = row["direct_credits"]
        proposal.unique_supporters = row["supporter_count"]
        proposal.quadratic_score = row["quadratic_score"]
        proposal.matched_amount_usd = matched_amount
        session.flush()
        proposal_results.append(
            {
                "proposal_key": proposal.proposal_key,
                "title": proposal.title,
                "direct_voice_credits": row["direct_credits"],
                "unique_supporters": row["supporter_count"],
                "quadratic_score": row["quadratic_score"],
                "matching_units": round(row["matching_units"], 6),
                "matched_amount_usd": matched_amount,
                "requested_amount_usd": proposal.requested_amount_usd,
                "status": proposal.status,
            }
        )

    proposal_results.sort(
        key=lambda row: (
            -row["matched_amount_usd"],
            -row["quadratic_score"],
            row["proposal_key"],
        )
    )
    if round_row.status == "draft":
        round_row.status = "open"
        round_row.opened_at = round_row.opened_at or _utcnow()
    if close_round:
        round_row.status = "settled"
        round_row.closed_at = _utcnow()

    results = {
        "round_key": round_row.round_key,
        "title": round_row.title,
        "status": round_row.status,
        "matching_pool_usd": round_row.matching_pool_usd,
        "proposal_count": len(proposal_results),
        "contributor_count": len({row.contributor_profile_id for row in allocations}),
        "total_voice_credits": int(sum(row.voice_credits for row in allocations)),
        "total_matching_units": round(total_matching_units, 6),
        "proposals": proposal_results,
    }
    round_row.results = results
    session.flush()
    return results


def calculate_github_points(
    *,
    contribution_type: str,
    merged_prs: int = 0,
    files_changed: int = 0,
    lines_changed: int = 0,
    linked_issues: int = 0,
    review_comments: int = 0,
) -> int:
    """Translate GitHub contribution evidence into reputation points."""

    normalized_event = _normalize_event_type(contribution_type)
    if normalized_event == "documentation":
        raw_points = (
            20 * max(merged_prs, 0)
            + min(max(files_changed, 0) * 2, 24)
            + min(max(lines_changed, 0) // 120, 20)
        )
    elif normalized_event == "bug_report":
        raw_points = (
            20 * max(linked_issues, 0)
            + 15 * max(merged_prs, 0)
            + min(max(review_comments, 0), 20)
            + min(max(files_changed, 0) * 2, 20)
        )
    else:
        raw_points = (
            35 * max(merged_prs, 0)
            + min(max(files_changed, 0) * 2, 30)
            + min(max(lines_changed, 0) // 75, 35)
            + min(max(linked_issues, 0) * 5, 20)
        )
    return int(max(raw_points, DEFAULT_EVENT_POINTS[normalized_event]))


def calculate_performance_points(
    snapshot: DailySnapshot,
    decision: PromotionDecision | None = None,
) -> int:
    """Translate verified strategy results into reputation points."""

    starting_bankroll = max(float(snapshot.starting_bankroll), 1.0)
    return_ratio = float(snapshot.realized_pnl) / starting_bankroll
    decision_bonus = DECISION_BONUS.get(decision.decision, 0) if decision else 0
    activity_bonus = min(int(snapshot.closed_trades), 25)
    drawdown_bonus = 10 if float(snapshot.max_drawdown_pct) <= 0.10 else 0
    calibration_bonus = (
        5 if snapshot.rolling_brier is not None and float(snapshot.rolling_brier) <= 0.22 else 0
    )
    raw_points = round(return_ratio * 500) + activity_bonus + drawdown_bonus + calibration_bonus + decision_bonus
    return int(max(-100, min(250, raw_points)))


def compute_unlock_state(
    *,
    total_points: int,
    code_points: int = 0,
    performance_points: int = 0,
    bug_points: int = 0,
    docs_points: int = 0,
    review_points: int = 0,
) -> dict[str, Any]:
    """Derive contributor tier and utility unlocks from reputation totals."""

    if total_points >= 500:
        tier = "steward"
    elif total_points >= 250:
        tier = "operator"
    elif total_points >= 100:
        tier = "builder"
    elif total_points >= 50:
        tier = "contributor"
    else:
        tier = "seed"

    unlocks: list[str] = []
    if total_points >= 50:
        unlocks.append("leaderboard_bronze")
    if total_points >= 150:
        unlocks.append("leaderboard_silver")
    if total_points >= 300:
        unlocks.append("leaderboard_gold")
    if total_points >= 100:
        unlocks.append("governance_voting")
    if total_points >= 250 and code_points >= 100:
        unlocks.append("priority_agent_templates")
    if total_points >= 200 and (bug_points + docs_points + review_points) >= 50:
        unlocks.append("community_steward_badge")
    if total_points >= 250 and performance_points >= 75:
        unlocks.append("verified_alpha_badge")

    return {"tier": tier, "unlocks": unlocks}


def voice_credit_budget(total_points: int) -> int:
    """Bound quadratic-funding influence without creating a tokenized system."""

    normalized_points = max(int(total_points), 1)
    return max(10, min(100, int(math.sqrt(normalized_points) * 4)))


def _get_profile(
    session: Session,
    *,
    contributor_profile_id: int | None = None,
    contributor_key: str | None = None,
) -> ContributorProfile | None:
    if contributor_profile_id is not None:
        return session.get(ContributorProfile, contributor_profile_id)
    if contributor_key is not None:
        return crud.get_contributor_profile(session, contributor_key)
    raise RuntimeError("Contributor profile lookup requires an id or contributor key")


def _profile_payload(profile: ContributorProfile) -> dict[str, Any]:
    return {
        "contributor_key": profile.contributor_key,
        "display_name": profile.display_name,
        "github_handle": profile.github_handle,
        "status": profile.status,
        "total_reputation_points": profile.total_reputation_points,
        "code_points": profile.code_points,
        "performance_points": profile.performance_points,
        "bug_points": profile.bug_points,
        "docs_points": profile.docs_points,
        "review_points": profile.review_points,
        "reputation_tier": profile.reputation_tier,
        "unlocks": profile.unlocks or [],
        "voice_credit_budget": voice_credit_budget(profile.total_reputation_points),
    }


def _round_payload(round_row: Any) -> dict[str, Any]:
    return {
        "round_key": round_row.round_key,
        "title": round_row.title,
        "description": round_row.description,
        "status": round_row.status,
        "matching_pool_usd": round_row.matching_pool_usd,
        "results": round_row.results,
    }


def _proposal_payload(proposal: Any) -> dict[str, Any]:
    return {
        "proposal_key": proposal.proposal_key,
        "title": proposal.title,
        "description": proposal.description,
        "requested_amount_usd": proposal.requested_amount_usd,
        "status": proposal.status,
        "direct_voice_credits": proposal.direct_voice_credits,
        "unique_supporters": proposal.unique_supporters,
        "quadratic_score": proposal.quadratic_score,
        "matched_amount_usd": proposal.matched_amount_usd,
    }


def _normalize_event_type(event_type: str) -> str:
    normalized = str(event_type).strip().lower()
    if normalized not in EVENT_BUCKETS:
        raise ValueError(f"Unsupported event type: {event_type}")
    return normalized


def _derive_event_key(
    *,
    contributor_key: str,
    event_type: str,
    source_kind: str | None,
    source_ref: str | None,
    summary: str | None,
    metadata: dict[str, Any] | None,
) -> str:
    if not any([source_kind, source_ref, summary, metadata]):
        timestamp = _utcnow().strftime("%Y%m%d%H%M%S%f")
        return f"{event_type}-{contributor_key}-{timestamp}"
    body = {
        "contributor_key": contributor_key,
        "event_type": event_type,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "summary": summary,
        "metadata": metadata or {},
    }
    digest = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()[:20]
    return f"{event_type}-{digest}"


def _default_performance_summary(
    strategy_key: str,
    version_label: str,
    snapshot: DailySnapshot,
    decision: PromotionDecision | None,
) -> str:
    decision_label = decision.decision if decision else "recorded"
    return (
        f"Verified {strategy_key}:{version_label} {snapshot.environment} performance on "
        f"{snapshot.snapshot_date} with realized PnL {snapshot.realized_pnl:.2f} and "
        f"{decision_label} decision."
    )


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
