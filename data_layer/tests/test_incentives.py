"""Tests for the contributor reputation and quadratic-funding system."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data_layer import crud, database
from data_layer.cli import main as cli_main
from data_layer.schema import Base
from flywheel.incentives import (
    allocate_voice_credits,
    award_github_contribution,
    award_reputation_event,
    award_strategy_performance,
    create_funding_round,
    submit_funding_proposal,
    tally_funding_round,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def reset_engine_cache():
    database.reset_engine()
    yield
    database.reset_engine()


def _snapshot_payload(**overrides):
    payload = {
        "snapshot_date": "2026-03-07",
        "starting_bankroll": 100.0,
        "ending_bankroll": 112.0,
        "realized_pnl": 12.0,
        "unrealized_pnl": 1.0,
        "open_positions": 1,
        "closed_trades": 24,
        "win_rate": 0.62,
        "fill_rate": 0.71,
        "avg_slippage_bps": 12.0,
        "rolling_brier": 0.21,
        "rolling_ece": 0.06,
        "max_drawdown_pct": 0.08,
        "kill_events": 0,
    }
    payload.update(overrides)
    return payload


def test_award_github_contribution_refreshes_profile_and_unlocks(session):
    first = award_github_contribution(
        session,
        contributor_key="alice",
        display_name="Alice",
        github_handle="alice-dev",
        contribution_type="code_contribution",
        merged_prs=2,
        files_changed=8,
        lines_changed=600,
        source_ref="pr-42",
    )
    second = award_reputation_event(
        session,
        contributor_key="alice",
        event_type="bug_report",
        points_delta=45,
        source_kind="manual",
        source_ref="bug-7",
    )
    session.commit()

    profile = crud.get_contributor_profile(session, "alice")
    assert profile is not None
    assert first["points_delta"] > 40
    assert second["profile"]["total_reputation_points"] >= 100
    assert "governance_voting" in second["profile"]["unlocks"]
    assert profile.github_handle == "alice-dev"


def test_award_strategy_performance_uses_latest_verified_snapshot(session):
    version = crud.create_strategy_version(
        session,
        strategy_key="wallet-flow",
        version_label="wf-20260307",
        lane="fast_flow",
    )
    deployment = crud.create_deployment(
        session,
        strategy_version_id=version.id,
        environment="paper",
        capital_cap_usd=25.0,
    )
    crud.create_daily_snapshot(
        session,
        strategy_version_id=version.id,
        deployment_id=deployment.id,
        environment="paper",
        **_snapshot_payload(),
    )
    crud.create_promotion_decision(
        session,
        strategy_version_id=version.id,
        deployment_id=deployment.id,
        from_stage="paper",
        to_stage="shadow",
        decision="promote",
        reason_code="promotion_policy_pass",
        metrics={"realized_pnl": 12.0},
    )

    result = award_strategy_performance(
        session,
        contributor_key="jj",
        display_name="JJ",
        strategy_key="wallet-flow",
        version_label="wf-20260307",
    )
    session.commit()

    assert result["points_delta"] > 0
    assert result["profile"]["performance_points"] == result["points_delta"]
    assert result["profile"]["contributor_key"] == "jj"


def test_quadratic_funding_prefers_broad_support(session):
    create_funding_round(
        session,
        round_key="round-1",
        title="Phase 9",
        matching_pool_usd=1000.0,
        status="open",
    )
    submit_funding_proposal(
        session,
        round_key="round-1",
        proposal_key="solo-bot",
        title="Solo Bot Upgrade",
        description="One large ask with concentrated support.",
    )
    submit_funding_proposal(
        session,
        round_key="round-1",
        proposal_key="shared-hub",
        title="Shared Knowledge Hub",
        description="A cross-agent improvement with broad support.",
    )

    allocate_voice_credits(
        session,
        round_key="round-1",
        proposal_key="solo-bot",
        contributor_key="alice",
        voice_credits=9,
    )
    allocate_voice_credits(
        session,
        round_key="round-1",
        proposal_key="shared-hub",
        contributor_key="bob",
        voice_credits=4,
    )
    allocate_voice_credits(
        session,
        round_key="round-1",
        proposal_key="shared-hub",
        contributor_key="carol",
        voice_credits=4,
    )
    results = allocate_voice_credits(
        session,
        round_key="round-1",
        proposal_key="shared-hub",
        contributor_key="dave",
        voice_credits=4,
    )["results"]
    session.commit()

    by_key = {row["proposal_key"]: row for row in results["proposals"]}
    assert by_key["shared-hub"]["matched_amount_usd"] > by_key["solo-bot"]["matched_amount_usd"]
    assert by_key["shared-hub"]["quadratic_score"] > by_key["solo-bot"]["quadratic_score"]


def test_voice_credit_budget_is_enforced(session):
    create_funding_round(
        session,
        round_key="round-budget",
        title="Budget Guardrail",
        matching_pool_usd=100.0,
        status="open",
    )
    submit_funding_proposal(
        session,
        round_key="round-budget",
        proposal_key="proposal-a",
        title="Proposal A",
        description="Budget check.",
    )

    with pytest.raises(ValueError):
        allocate_voice_credits(
            session,
            round_key="round-budget",
            proposal_key="proposal-a",
            contributor_key="seed-user",
            voice_credits=11,
        )


def test_cli_reputation_award_and_leaderboard(tmp_path, capsys):
    db_url = f"sqlite:///{tmp_path / 'control.db'}"
    cli_main(
        [
            "flywheel-reputation-award",
            "--db-url",
            db_url,
            "--contributor-key",
            "alice",
            "--display-name",
            "Alice",
            "--event-type",
            "documentation",
            "--points",
            "55",
            "--source-kind",
            "manual",
            "--source-ref",
            "docs-1",
        ]
    )
    award_out = json.loads(capsys.readouterr().out)
    assert award_out["profile"]["total_reputation_points"] == 55

    cli_main(
        [
            "flywheel-reputation-leaderboard",
            "--db-url",
            db_url,
            "--limit",
            "1",
        ]
    )
    board_out = json.loads(capsys.readouterr().out)
    assert board_out[0]["contributor_key"] == "alice"


def test_cli_funding_round_flow(tmp_path, capsys):
    db_url = f"sqlite:///{tmp_path / 'funding.db'}"
    cli_main(
        [
            "flywheel-funding-create-round",
            "--db-url",
            db_url,
            "--round-key",
            "round-cli",
            "--title",
            "CLI Round",
            "--matching-pool-usd",
            "250",
        ]
    )
    round_out = json.loads(capsys.readouterr().out)
    assert round_out["round_key"] == "round-cli"

    cli_main(
        [
            "flywheel-funding-submit-proposal",
            "--db-url",
            db_url,
            "--round-key",
            "round-cli",
            "--proposal-key",
            "proposal-cli",
            "--title",
            "CLI Proposal",
            "--description",
            "Ship the reputation dashboard.",
        ]
    )
    proposal_out = json.loads(capsys.readouterr().out)
    assert proposal_out["proposal_key"] == "proposal-cli"

    cli_main(
        [
            "flywheel-funding-vote",
            "--db-url",
            db_url,
            "--round-key",
            "round-cli",
            "--proposal-key",
            "proposal-cli",
            "--contributor-key",
            "alice",
            "--voice-credits",
            "6",
        ]
    )
    vote_out = json.loads(capsys.readouterr().out)
    assert vote_out["voice_credits_used"] == 6

    cli_main(
        [
            "flywheel-funding-tally",
            "--db-url",
            db_url,
            "--round-key",
            "round-cli",
        ]
    )
    tally_out = json.loads(capsys.readouterr().out)
    assert tally_out["proposal_count"] == 1
    assert tally_out["proposals"][0]["proposal_key"] == "proposal-cli"
