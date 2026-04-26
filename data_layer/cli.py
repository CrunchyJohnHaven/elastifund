"""CLI: db-init, db-status, db-vacuum.

Usage:
    python -m data_layer init      # create tables
    python -m data_layer status    # show row counts & size
    python -m data_layer vacuum    # reclaim space
"""

import argparse
import json
from pathlib import Path
import sys

from . import database
from flywheel.bridge import build_payload_from_bot_db, write_payload
from flywheel.federation import export_bulletin, import_bulletin, load_bulletin, write_bulletin
from flywheel.incentives import (
    allocate_voice_credits,
    award_github_contribution,
    award_reputation_event,
    award_strategy_performance,
    build_reputation_leaderboard,
    create_funding_round,
    submit_funding_proposal,
    tally_funding_round,
)
from flywheel.improvement_exchange import (
    export_improvement_bundle,
    import_improvement_bundle,
    load_improvement_bundle,
    load_knowledge_pack,
    publish_knowledge_pack,
    pull_knowledge_pack,
)
from flywheel.kibana_pack import (
    DEFAULT_AUDIT_OPS_PATH,
    DEFAULT_B1_TEMPLATE_AUDIT_PATH,
    DEFAULT_GUARANTEED_DOLLAR_AUDIT_PATH,
    DEFAULT_PHASE6_OUTPUT_DIR,
    DEFAULT_RESEARCH_METRICS_GLOB,
    DEFAULT_REVENUE_DB_PATH,
    build_phase6_dashboard_pack,
    write_phase6_dashboard_pack,
)
from flywheel.naming_guard import run_cycle_packet_naming_check
from flywheel.resilience import HubControlPlane, simulate_federated_round
from flywheel.runner import build_scorecard_from_db, load_payload, run_cycle
from orchestration.store import DEFAULT_DB_PATH as DEFAULT_ALLOCATOR_DB_PATH


def _open_session(db_url=None):
    database.reset_engine()
    engine = database.get_engine(db_url)
    database.init_db(engine)
    return database.get_session_factory(engine)()


def _close_session(session):
    session.close()
    database.reset_engine()


def cmd_init(_args):
    database.init_db()
    info = database.db_status()
    print(f"Database initialized at {info['url']}")
    print(f"Tables created: {len(info['tables'])}")


def cmd_status(_args):
    try:
        info = database.db_status()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Run 'python -m data_layer init' first.", file=sys.stderr)
        sys.exit(1)

    print(f"URL: {info['url']}")
    if "size_bytes" in info:
        size_kb = info["size_bytes"] / 1024
        print(f"Size: {size_kb:.1f} KB")
    print()
    total = 0
    for table, count in sorted(info["tables"].items()):
        print(f"  {table:30s} {count:>8,d}")
        total += count
    print(f"  {'TOTAL':30s} {total:>8,d}")


def cmd_vacuum(_args):
    database.vacuum()
    print("VACUUM completed.")


def cmd_flywheel_cycle(args):
    session = _open_session(args.db_url)
    try:
        payload = load_payload(args.input)
        result = run_cycle(session, payload, artifact_root=args.artifact_dir)
    finally:
        _close_session(session)

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    print(f"Cycle: {result['cycle_key']}")
    print(f"Deployments evaluated: {result['evaluated']}")
    print(f"Artifacts: {result['artifacts']}")


def cmd_flywheel_scorecard(args):
    session = _open_session(args.db_url)
    try:
        scorecard = build_scorecard_from_db(session, environment=args.environment)
    finally:
        _close_session(session)

    print(json.dumps(scorecard, indent=2, sort_keys=True))


def cmd_flywheel_bridge(args):
    payload = build_payload_from_bot_db(
        args.bot_db,
        strategy_key=args.strategy_key,
        version_label=args.version_label,
        lane=args.lane,
        environment=args.environment,
        capital_cap_usd=args.capital_cap_usd,
        artifact_uri=args.artifact_uri,
        git_sha=args.git_sha,
        lookback_days=args.lookback_days,
    )
    if args.output:
        path = write_payload(payload, args.output)
        print(path)
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_flywheel_export_bulletin(args):
    session = _open_session(args.db_url)
    try:
        bulletin = export_bulletin(
            session,
            peer_name=args.peer_name,
            decision_types=tuple(args.decision),
            limit=args.limit,
        )
    finally:
        _close_session(session)

    if args.output:
        print(write_bulletin(bulletin, args.output))
        return
    print(json.dumps(bulletin, indent=2, sort_keys=True))


def cmd_flywheel_import_bulletin(args):
    session = _open_session(args.db_url)
    try:
        bulletin = load_bulletin(args.input)
        result = import_bulletin(session, bulletin)
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_export_improvement(args):
    session = _open_session(args.db_url)
    try:
        bundle = export_improvement_bundle(
            session,
            peer_name=args.peer_name,
            strategy_key=args.strategy_key,
            version_label=args.version_label,
            include_paths=args.include_path,
            outcome=args.outcome,
            summary=args.summary,
            hypothesis=args.hypothesis,
            repo_root=args.repo_root,
            output_path=args.output,
            signing_secret=args.signing_secret,
            base_ref=args.base_ref,
        )
    finally:
        _close_session(session)

    if args.output:
        print(args.output)
        return
    print(json.dumps(bundle, indent=2, sort_keys=True))


def cmd_flywheel_import_improvement(args):
    session = _open_session(args.db_url)
    try:
        bundle = load_improvement_bundle(args.input)
        result = import_improvement_bundle(
            session,
            bundle,
            review_root=args.review_dir,
            signing_secret=args.signing_secret,
            require_signature=args.require_signature,
        )
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_publish_knowledge_pack(args):
    spec = json.loads(Path(args.input).read_text())
    engine_metadata = dict(spec.get("engine_metadata") or spec.get("engine") or {})
    engine_key = args.engine_key or engine_metadata.get("engine_key") or spec.get("engine_key")
    engine_version = (
        args.engine_version
        or engine_metadata.get("engine_version")
        or spec.get("engine_version")
    )
    if not engine_key or not engine_version:
        raise SystemExit("knowledge-pack publish requires engine_key and engine_version")

    session = _open_session(args.db_url)
    try:
        bundle = publish_knowledge_pack(
            session,
            peer_name=args.peer_name,
            engine_key=engine_key,
            engine_version=engine_version,
            engine_metadata=engine_metadata,
            detector_summaries=spec.get("detector_summaries") or [],
            template_variants=spec.get("template_variants") or [],
            aggregated_outcomes=spec.get("aggregated_outcomes") or {},
            penalty_metrics=spec.get("penalty_metrics") or {},
            proof_references=spec.get("proof_references") or [],
            output_path=args.output,
            signing_secret=args.signing_secret,
        )
    finally:
        _close_session(session)

    if args.output:
        print(args.output)
        return
    print(json.dumps(bundle, indent=2, sort_keys=True))


def cmd_flywheel_pull_knowledge_pack(args):
    session = _open_session(args.db_url)
    try:
        bundle = load_knowledge_pack(args.input)
        result = pull_knowledge_pack(
            session,
            bundle,
            review_root=args.review_dir,
            signing_secret=args.signing_secret,
            require_signature=args.require_signature,
        )
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_reputation_award(args):
    session = _open_session(args.db_url)
    try:
        result = award_reputation_event(
            session,
            contributor_key=args.contributor_key,
            display_name=args.display_name,
            github_handle=args.github_handle,
            event_type=args.event_type,
            points_delta=args.points,
            event_key=args.event_key,
            source_kind=args.source_kind,
            source_ref=args.source_ref,
            summary=args.summary,
            metadata=_json_or_default(args.metadata_json, None),
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_reputation_award_github(args):
    session = _open_session(args.db_url)
    try:
        result = award_github_contribution(
            session,
            contributor_key=args.contributor_key,
            display_name=args.display_name,
            github_handle=args.github_handle,
            contribution_type=args.contribution_type,
            merged_prs=args.merged_prs,
            files_changed=args.files_changed,
            lines_changed=args.lines_changed,
            linked_issues=args.linked_issues,
            review_comments=args.review_comments,
            event_key=args.event_key,
            source_ref=args.source_ref,
            summary=args.summary,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_reputation_award_performance(args):
    session = _open_session(args.db_url)
    try:
        result = award_strategy_performance(
            session,
            contributor_key=args.contributor_key,
            display_name=args.display_name,
            github_handle=args.github_handle,
            strategy_key=args.strategy_key,
            version_label=args.version_label,
            event_key=args.event_key,
            summary=args.summary,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_reputation_leaderboard(args):
    session = _open_session(args.db_url)
    try:
        result = build_reputation_leaderboard(session, limit=args.limit)
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_funding_create_round(args):
    session = _open_session(args.db_url)
    try:
        result = create_funding_round(
            session,
            round_key=args.round_key,
            title=args.title,
            description=args.description,
            matching_pool_usd=args.matching_pool_usd,
            status=args.status,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_funding_submit_proposal(args):
    session = _open_session(args.db_url)
    try:
        result = submit_funding_proposal(
            session,
            round_key=args.round_key,
            proposal_key=args.proposal_key,
            title=args.title,
            description=args.description,
            owner_contributor_key=args.owner_contributor_key,
            owner_display_name=args.owner_display_name,
            owner_github_handle=args.owner_github_handle,
            requested_amount_usd=args.requested_amount_usd,
            metadata=_json_or_default(args.metadata_json, None),
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_funding_vote(args):
    session = _open_session(args.db_url)
    try:
        result = allocate_voice_credits(
            session,
            round_key=args.round_key,
            proposal_key=args.proposal_key,
            contributor_key=args.contributor_key,
            display_name=args.display_name,
            github_handle=args.github_handle,
            voice_credits=args.voice_credits,
            notes=args.notes,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_funding_tally(args):
    session = _open_session(args.db_url)
    try:
        result = tally_funding_round(
            session,
            round_key=args.round_key,
            close_round=args.close_round,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_agent_register(args):
    session = _open_session(args.db_url)
    try:
        hub = HubControlPlane(session)
        runtime = hub.register_agent(
            agent_id=args.agent_id,
            lane=args.lane,
            environment=args.environment,
            metadata=_json_or_default(args.metadata_json, {}),
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(_runtime_payload(runtime), indent=2, sort_keys=True))


def cmd_flywheel_agent_heartbeat(args):
    session = _open_session(args.db_url)
    try:
        hub = HubControlPlane(session)
        runtime = hub.record_heartbeat(
            agent_id=args.agent_id,
            lane=args.lane,
            environment=args.environment,
            activity_metric=args.activity_metric,
            activity_value=args.activity_value,
            metadata=_json_or_default(args.metadata_json, {}),
            status=args.status,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(_runtime_payload(runtime), indent=2, sort_keys=True))


def cmd_flywheel_agent_command(args):
    session = _open_session(args.db_url)
    try:
        hub = HubControlPlane(session)
        command = hub.issue_command(
            agent_id=args.agent_id,
            command_type=args.command_type,
            reason=args.reason,
            payload=_json_or_default(args.payload_json, {}),
            issued_by=args.issued_by,
            ttl_hours=args.ttl_hours,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(_command_payload(command), indent=2, sort_keys=True))


def cmd_flywheel_agent_poll(args):
    session = _open_session(args.db_url)
    try:
        hub = HubControlPlane(session)
        commands = hub.poll_commands(agent_id=args.agent_id)
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps([_command_payload(row) for row in commands], indent=2, sort_keys=True))


def cmd_flywheel_agent_ack(args):
    session = _open_session(args.db_url)
    try:
        hub = HubControlPlane(session)
        command = hub.acknowledge_command(
            agent_id=args.agent_id,
            command_id=args.command_id,
        )
        session.commit()
    finally:
        _close_session(session)
    print(json.dumps(_command_payload(command) if command else {}, indent=2, sort_keys=True))


def cmd_flywheel_simulate_federation(args):
    result = simulate_federated_round(
        agent_count=args.agent_count,
        malicious_fraction=args.malicious_fraction,
        dimensions=args.dimensions,
        seed=args.seed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_flywheel_kibana_pack(args):
    session = _open_session(args.db_url)
    try:
        pack = build_phase6_dashboard_pack(
            session,
            allocator_db_path=args.allocator_db,
            revenue_db_path=args.revenue_db,
            guaranteed_dollar_audit_path=args.guaranteed_dollar_audit,
            b1_template_audit_path=args.b1_template_audit,
            research_metrics_glob=args.research_metrics_glob,
            audit_ops_path=args.audit_ops,
        )
    finally:
        _close_session(session)

    artifacts = write_phase6_dashboard_pack(args.output_dir, pack)
    print(
        json.dumps(
            {
                "generated_at": pack["generated_at"],
                "dashboards": len(pack["dashboards"]),
                "collective_agents": pack["collective_health"]["agent_totals"]["total_agents"],
                "alert_rules": len(pack["alert_rules"]["rules"]),
                "artifacts": artifacts,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _json_or_default(raw, default):
    if raw is None:
        return default
    return json.loads(raw)


def _runtime_payload(runtime):
    return {
        "agent_id": runtime.agent_id,
        "lane": runtime.lane,
        "environment": runtime.environment,
        "status": runtime.status,
        "last_activity_metric": runtime.last_activity_metric,
        "last_activity_value": runtime.last_activity_value,
        "anomaly_state": runtime.anomaly_state,
        "anomaly_reason": runtime.anomaly_reason,
        "metadata": runtime.runtime_metadata,
        "last_heartbeat_at": runtime.last_heartbeat_at.isoformat() if runtime.last_heartbeat_at else None,
    }


def _command_payload(command):
    return {
        "id": command.id,
        "agent_id": command.agent_id,
        "command_type": command.command_type,
        "status": command.status,
        "reason": command.reason,
        "payload": command.payload,
        "issued_by": command.issued_by,
        "expires_at": command.expires_at.isoformat() if command.expires_at else None,
        "delivered_at": command.delivered_at.isoformat() if command.delivered_at else None,
        "acknowledged_at": command.acknowledged_at.isoformat() if command.acknowledged_at else None,
    }


def cmd_flywheel_naming_check(_args):
    result = run_cycle_packet_naming_check()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("ok", False):
        raise SystemExit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="data_layer",
        description="Control-plane persistence CLI",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create all tables")
    sub.add_parser("status", help="Show table row counts and DB size")
    sub.add_parser("vacuum", help="Run VACUUM to reclaim space")
    sub.add_parser("flywheel-init", help="Alias for init")

    p_cycle = sub.add_parser("flywheel-cycle", help="Run one sequential flywheel cycle from a JSON payload")
    p_cycle.add_argument("--input", required=True, help="Path to cycle payload JSON")
    p_cycle.add_argument(
        "--artifact-dir",
        default="reports/flywheel",
        help="Directory for generated cycle artifacts",
    )
    p_cycle.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the full result payload as JSON",
    )
    p_cycle.add_argument("--db-url", help="Optional target control DB URL")

    p_scorecard = sub.add_parser("flywheel-scorecard", help="Render a scorecard from the latest stored snapshots")
    p_scorecard.add_argument("--environment", help="Optional environment filter")
    p_scorecard.add_argument("--db-url", help="Optional control DB URL")

    p_bridge = sub.add_parser("flywheel-bridge", help="Bridge an existing bot.db into a flywheel cycle payload")
    p_bridge.add_argument("--bot-db", required=True, help="Path to source bot SQLite DB")
    p_bridge.add_argument("--strategy-key", required=True, help="Strategy identifier")
    p_bridge.add_argument("--version-label", required=True, help="Strategy version label")
    p_bridge.add_argument("--lane", required=True, help="Lane name, e.g. fast_flow")
    p_bridge.add_argument("--environment", required=True, help="Current deployment environment")
    p_bridge.add_argument("--capital-cap-usd", required=True, type=float, help="Capital cap for this deployment")
    p_bridge.add_argument("--artifact-uri", help="Optional artifact URI for the strategy version")
    p_bridge.add_argument("--git-sha", help="Optional git SHA for the strategy version")
    p_bridge.add_argument("--lookback-days", type=int, default=7, help="Lookback window for fill and risk metrics")
    p_bridge.add_argument("--output", help="Optional output path for the generated payload JSON")

    p_export = sub.add_parser("flywheel-export-bulletin", help="Export recent promotions and kills for peer sharing")
    p_export.add_argument("--peer-name", required=True, help="Name of this autonomous company / fork")
    p_export.add_argument(
        "--decision",
        action="append",
        default=["promote", "kill"],
        help="Decision type to include. Repeatable.",
    )
    p_export.add_argument("--limit", type=int, default=20, help="Maximum items to export")
    p_export.add_argument("--output", help="Optional output path for the bulletin JSON")
    p_export.add_argument("--db-url", help="Optional control DB URL")

    p_import = sub.add_parser("flywheel-import-bulletin", help="Import a peer bulletin and create local review tasks")
    p_import.add_argument("--input", required=True, help="Path to bulletin JSON")
    p_import.add_argument("--db-url", help="Optional control DB URL")

    p_export_improvement = sub.add_parser(
        "flywheel-export-improvement",
        help="Export a signed peer improvement bundle with evidence and code",
    )
    p_export_improvement.add_argument("--db-url", help="Optional control DB URL")
    p_export_improvement.add_argument("--peer-name", required=True, help="Name of this fork / autonomous company")
    p_export_improvement.add_argument("--strategy-key", required=True, help="Strategy identifier")
    p_export_improvement.add_argument("--version-label", required=True, help="Strategy version label")
    p_export_improvement.add_argument(
        "--include-path",
        action="append",
        required=True,
        help="Code file to include. Repeat for multiple files.",
    )
    p_export_improvement.add_argument(
        "--outcome",
        choices=("improved", "failed", "mixed"),
        default="mixed",
        help="Peer's claim about the change outcome",
    )
    p_export_improvement.add_argument("--summary", help="One-line summary of what changed and what happened")
    p_export_improvement.add_argument("--hypothesis", help="Hypothesis behind the change")
    p_export_improvement.add_argument("--repo-root", default=".", help="Repo root used to resolve include paths")
    p_export_improvement.add_argument("--base-ref", default="HEAD", help="Git base ref used for optional patch generation")
    p_export_improvement.add_argument("--signing-secret", help="Optional HMAC secret used to sign the bundle")
    p_export_improvement.add_argument("--output", help="Optional output path for the generated bundle JSON")

    p_import_improvement = sub.add_parser(
        "flywheel-import-improvement",
        help="Import a peer improvement bundle and materialize a local review packet",
    )
    p_import_improvement.add_argument("--db-url", help="Optional control DB URL")
    p_import_improvement.add_argument("--input", required=True, help="Path to improvement bundle JSON")
    p_import_improvement.add_argument(
        "--review-dir",
        default="reports/flywheel/peer_improvements",
        help="Directory where local review packets should be written",
    )
    p_import_improvement.add_argument("--signing-secret", help="Optional HMAC secret used to verify the bundle")
    p_import_improvement.add_argument(
        "--require-signature",
        action="store_true",
        help="Reject unsigned bundles during import",
    )

    p_publish_knowledge = sub.add_parser(
        "flywheel-publish-knowledge-pack",
        help="Publish a sanitized, signed knowledge pack for the revenue-audit lane",
    )
    p_publish_knowledge.add_argument("--db-url", help="Optional control DB URL")
    p_publish_knowledge.add_argument("--peer-name", required=True, help="Name of this fork / autonomous company")
    p_publish_knowledge.add_argument("--input", required=True, help="Path to a JSON knowledge-pack source spec")
    p_publish_knowledge.add_argument("--engine-key", help="Override engine identifier")
    p_publish_knowledge.add_argument("--engine-version", help="Override engine version label")
    p_publish_knowledge.add_argument("--signing-secret", help="Optional HMAC secret used to sign the pack")
    p_publish_knowledge.add_argument("--output", help="Optional output path for the generated pack JSON")

    p_pull_knowledge = sub.add_parser(
        "flywheel-pull-knowledge-pack",
        help="Pull a peer knowledge pack and materialize a local review packet",
    )
    p_pull_knowledge.add_argument("--db-url", help="Optional control DB URL")
    p_pull_knowledge.add_argument("--input", required=True, help="Path to knowledge pack JSON")
    p_pull_knowledge.add_argument(
        "--review-dir",
        default="reports/flywheel/knowledge_packs",
        help="Directory where local review packets should be written",
    )
    p_pull_knowledge.add_argument("--signing-secret", help="Optional HMAC secret used to verify the pack")
    p_pull_knowledge.add_argument(
        "--require-signature",
        action="store_true",
        help="Reject unsigned knowledge packs during pull",
    )

    p_rep_award = sub.add_parser(
        "flywheel-reputation-award",
        help="Award a manual or automation-driven reputation event",
    )
    p_rep_award.add_argument("--db-url", help="Optional control DB URL")
    p_rep_award.add_argument("--contributor-key", required=True, help="Stable contributor identifier")
    p_rep_award.add_argument("--display-name", help="Human-readable contributor label")
    p_rep_award.add_argument("--github-handle", help="Optional GitHub handle")
    p_rep_award.add_argument(
        "--event-type",
        required=True,
        choices=("code_contribution", "strategy_performance", "bug_report", "documentation", "peer_review"),
        help="Reputation event category",
    )
    p_rep_award.add_argument("--points", type=int, help="Explicit point override")
    p_rep_award.add_argument("--event-key", help="Optional idempotency key")
    p_rep_award.add_argument("--source-kind", help="Evidence source kind")
    p_rep_award.add_argument("--source-ref", help="Evidence source identifier")
    p_rep_award.add_argument("--summary", help="One-line summary for the event")
    p_rep_award.add_argument("--metadata-json", help="Optional JSON metadata payload")

    p_rep_github = sub.add_parser(
        "flywheel-reputation-award-github",
        help="Award reputation from GitHub-style contribution metrics",
    )
    p_rep_github.add_argument("--db-url", help="Optional control DB URL")
    p_rep_github.add_argument("--contributor-key", required=True, help="Stable contributor identifier")
    p_rep_github.add_argument("--display-name", help="Human-readable contributor label")
    p_rep_github.add_argument("--github-handle", help="GitHub handle")
    p_rep_github.add_argument(
        "--contribution-type",
        required=True,
        choices=("code_contribution", "documentation", "bug_report"),
        help="Contribution class to score",
    )
    p_rep_github.add_argument("--merged-prs", type=int, default=0, help="Merged PR count")
    p_rep_github.add_argument("--files-changed", type=int, default=0, help="Files changed count")
    p_rep_github.add_argument("--lines-changed", type=int, default=0, help="Approximate changed line count")
    p_rep_github.add_argument("--linked-issues", type=int, default=0, help="Issues linked or closed")
    p_rep_github.add_argument("--review-comments", type=int, default=0, help="Relevant review comments resolved")
    p_rep_github.add_argument("--event-key", help="Optional idempotency key")
    p_rep_github.add_argument("--source-ref", help="GitHub ref, PR URL, or commit SHA")
    p_rep_github.add_argument("--summary", help="One-line summary for the contribution")

    p_rep_perf = sub.add_parser(
        "flywheel-reputation-award-performance",
        help="Award reputation from the latest verified flywheel performance snapshot",
    )
    p_rep_perf.add_argument("--db-url", help="Optional control DB URL")
    p_rep_perf.add_argument("--contributor-key", required=True, help="Stable contributor identifier")
    p_rep_perf.add_argument("--display-name", help="Human-readable contributor label")
    p_rep_perf.add_argument("--github-handle", help="GitHub handle")
    p_rep_perf.add_argument("--strategy-key", required=True, help="Strategy identifier")
    p_rep_perf.add_argument("--version-label", required=True, help="Strategy version label")
    p_rep_perf.add_argument("--event-key", help="Optional idempotency key")
    p_rep_perf.add_argument("--summary", help="Optional override summary")

    p_rep_board = sub.add_parser(
        "flywheel-reputation-leaderboard",
        help="Render the current contributor leaderboard as JSON",
    )
    p_rep_board.add_argument("--db-url", help="Optional control DB URL")
    p_rep_board.add_argument("--limit", type=int, default=20, help="Maximum contributors to return")

    p_round = sub.add_parser(
        "flywheel-funding-create-round",
        help="Create or update a quadratic-funding round",
    )
    p_round.add_argument("--db-url", help="Optional control DB URL")
    p_round.add_argument("--round-key", required=True, help="Stable round identifier")
    p_round.add_argument("--title", required=True, help="Round title")
    p_round.add_argument("--description", help="Round description")
    p_round.add_argument("--matching-pool-usd", type=float, default=0.0, help="Matching pool in USD")
    p_round.add_argument(
        "--status",
        default="open",
        choices=("draft", "open", "closed", "settled"),
        help="Initial round status",
    )

    p_proposal = sub.add_parser(
        "flywheel-funding-submit-proposal",
        help="Submit or update a proposal in a funding round",
    )
    p_proposal.add_argument("--db-url", help="Optional control DB URL")
    p_proposal.add_argument("--round-key", required=True, help="Target funding round")
    p_proposal.add_argument("--proposal-key", required=True, help="Stable proposal identifier")
    p_proposal.add_argument("--title", required=True, help="Proposal title")
    p_proposal.add_argument("--description", required=True, help="Proposal description")
    p_proposal.add_argument("--owner-contributor-key", help="Proposal owner contributor key")
    p_proposal.add_argument("--owner-display-name", help="Proposal owner display name")
    p_proposal.add_argument("--owner-github-handle", help="Proposal owner GitHub handle")
    p_proposal.add_argument("--requested-amount-usd", type=float, help="Requested funding amount")
    p_proposal.add_argument("--metadata-json", help="Optional JSON metadata payload")

    p_vote = sub.add_parser(
        "flywheel-funding-vote",
        help="Allocate voice credits to one proposal in a funding round",
    )
    p_vote.add_argument("--db-url", help="Optional control DB URL")
    p_vote.add_argument("--round-key", required=True, help="Target funding round")
    p_vote.add_argument("--proposal-key", required=True, help="Target proposal")
    p_vote.add_argument("--contributor-key", required=True, help="Voting contributor")
    p_vote.add_argument("--display-name", help="Human-readable contributor label")
    p_vote.add_argument("--github-handle", help="GitHub handle")
    p_vote.add_argument("--voice-credits", required=True, type=int, help="Voice credits to allocate")
    p_vote.add_argument("--notes", help="Optional allocation note")

    p_tally = sub.add_parser(
        "flywheel-funding-tally",
        help="Tally a funding round and compute quadratic matching results",
    )
    p_tally.add_argument("--db-url", help="Optional control DB URL")
    p_tally.add_argument("--round-key", required=True, help="Funding round identifier")
    p_tally.add_argument(
        "--close-round",
        action="store_true",
        help="Close and settle the round after tallying",
    )

    p_agent_register = sub.add_parser("flywheel-agent-register", help="Register or refresh one agent runtime")
    p_agent_register.add_argument("--db-url", help="Optional control DB URL")
    p_agent_register.add_argument("--agent-id", required=True, help="Stable agent identifier")
    p_agent_register.add_argument("--lane", required=True, help="Lane name, e.g. fast_flow")
    p_agent_register.add_argument("--environment", required=True, help="Runtime environment")
    p_agent_register.add_argument("--metadata-json", help="Optional JSON metadata blob")

    p_agent_heartbeat = sub.add_parser("flywheel-agent-heartbeat", help="Record one agent heartbeat")
    p_agent_heartbeat.add_argument("--db-url", help="Optional control DB URL")
    p_agent_heartbeat.add_argument("--agent-id", required=True, help="Stable agent identifier")
    p_agent_heartbeat.add_argument("--lane", required=True, help="Lane name, e.g. fast_flow")
    p_agent_heartbeat.add_argument("--environment", required=True, help="Runtime environment")
    p_agent_heartbeat.add_argument("--activity-metric", default="closed_trades", help="Observed activity metric")
    p_agent_heartbeat.add_argument("--activity-value", type=float, help="Current activity value")
    p_agent_heartbeat.add_argument("--status", default="active", help="Runtime status")
    p_agent_heartbeat.add_argument("--metadata-json", help="Optional JSON metadata blob")

    p_agent_command = sub.add_parser("flywheel-agent-command", help="Issue a hub command to one agent")
    p_agent_command.add_argument("--db-url", help="Optional control DB URL")
    p_agent_command.add_argument("--agent-id", required=True, help="Stable agent identifier")
    p_agent_command.add_argument(
        "--command-type",
        required=True,
        choices=("pause", "resume", "shutdown", "rotate_api_key"),
        help="Command to queue for the agent",
    )
    p_agent_command.add_argument("--reason", required=True, help="Reason for the command")
    p_agent_command.add_argument("--payload-json", help="Optional JSON payload")
    p_agent_command.add_argument("--issued-by", default="hub", help="Issuer label")
    p_agent_command.add_argument("--ttl-hours", type=int, default=24, help="Command TTL in hours")

    p_agent_poll = sub.add_parser("flywheel-agent-poll", help="Deliver pending commands for one agent")
    p_agent_poll.add_argument("--db-url", help="Optional control DB URL")
    p_agent_poll.add_argument("--agent-id", required=True, help="Stable agent identifier")

    p_agent_ack = sub.add_parser("flywheel-agent-ack", help="Acknowledge one delivered command")
    p_agent_ack.add_argument("--db-url", help="Optional control DB URL")
    p_agent_ack.add_argument("--agent-id", required=True, help="Stable agent identifier")
    p_agent_ack.add_argument("--command-id", required=True, type=int, help="Command row ID to acknowledge")

    p_federation_sim = sub.add_parser(
        "flywheel-simulate-federation",
        help="Run a local Byzantine-resilient federated round simulation",
    )
    p_federation_sim.add_argument("--agent-count", type=int, default=50, help="Total simulated agents")
    p_federation_sim.add_argument("--malicious-fraction", type=float, default=0.10, help="Malicious agent share")
    p_federation_sim.add_argument("--dimensions", type=int, default=12, help="Model vector size")
    p_federation_sim.add_argument("--seed", type=int, default=7, help="PRNG seed")

    p_kibana_pack = sub.add_parser(
        "flywheel-kibana-pack",
        help="Generate the Phase 6 Kibana leaderboard, Canvas, and alert pack",
    )
    p_kibana_pack.add_argument("--db-url", help="Optional control DB URL")
    p_kibana_pack.add_argument(
        "--allocator-db",
        default=str(DEFAULT_ALLOCATOR_DB_PATH),
        help="Allocator SQLite DB used for budget decisions",
    )
    p_kibana_pack.add_argument(
        "--revenue-db",
        default=str(DEFAULT_REVENUE_DB_PATH),
        help="Non-trading revenue-agent SQLite DB",
    )
    p_kibana_pack.add_argument(
        "--guaranteed-dollar-audit",
        default=str(DEFAULT_GUARANTEED_DOLLAR_AUDIT_PATH),
        help="Path to the A-6 guaranteed-dollar audit JSON",
    )
    p_kibana_pack.add_argument(
        "--b1-template-audit",
        default=str(DEFAULT_B1_TEMPLATE_AUDIT_PATH),
        help="Path to the B-1 template audit JSON",
    )
    p_kibana_pack.add_argument(
        "--research-metrics-glob",
        default=DEFAULT_RESEARCH_METRICS_GLOB,
        help="Glob for research metrics JSON files used in the market-regime dashboard",
    )
    p_kibana_pack.add_argument(
        "--audit-ops",
        default=str(DEFAULT_AUDIT_OPS_PATH),
        help="Optional non-trading audit-operations snapshot JSON",
    )
    p_kibana_pack.add_argument(
        "--output-dir",
        default=str(DEFAULT_PHASE6_OUTPUT_DIR),
        help="Directory where the Phase 6 pack should be written",
    )
    sub.add_parser(
        "flywheel-naming-check",
        help="Enforce canonical flywheel cycle-packet naming guardrails",
    )

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "vacuum": cmd_vacuum,
        "flywheel-init": cmd_init,
        "flywheel-cycle": cmd_flywheel_cycle,
        "flywheel-scorecard": cmd_flywheel_scorecard,
        "flywheel-bridge": cmd_flywheel_bridge,
        "flywheel-export-bulletin": cmd_flywheel_export_bulletin,
        "flywheel-import-bulletin": cmd_flywheel_import_bulletin,
        "flywheel-export-improvement": cmd_flywheel_export_improvement,
        "flywheel-import-improvement": cmd_flywheel_import_improvement,
        "flywheel-publish-knowledge-pack": cmd_flywheel_publish_knowledge_pack,
        "flywheel-pull-knowledge-pack": cmd_flywheel_pull_knowledge_pack,
        "flywheel-reputation-award": cmd_flywheel_reputation_award,
        "flywheel-reputation-award-github": cmd_flywheel_reputation_award_github,
        "flywheel-reputation-award-performance": cmd_flywheel_reputation_award_performance,
        "flywheel-reputation-leaderboard": cmd_flywheel_reputation_leaderboard,
        "flywheel-funding-create-round": cmd_flywheel_funding_create_round,
        "flywheel-funding-submit-proposal": cmd_flywheel_funding_submit_proposal,
        "flywheel-funding-vote": cmd_flywheel_funding_vote,
        "flywheel-funding-tally": cmd_flywheel_funding_tally,
        "flywheel-agent-register": cmd_flywheel_agent_register,
        "flywheel-agent-heartbeat": cmd_flywheel_agent_heartbeat,
        "flywheel-agent-command": cmd_flywheel_agent_command,
        "flywheel-agent-poll": cmd_flywheel_agent_poll,
        "flywheel-agent-ack": cmd_flywheel_agent_ack,
        "flywheel-simulate-federation": cmd_flywheel_simulate_federation,
        "flywheel-kibana-pack": cmd_flywheel_kibana_pack,
        "flywheel-naming-check": cmd_flywheel_naming_check,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
