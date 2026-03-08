"""Phase 6 Kibana dashboard pack generator for Elastifund."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import glob
import json
import math
from pathlib import Path
import statistics
from typing import Any
import uuid

from sqlalchemy.orm import Session

from data_layer import crud
from orchestration.store import AllocatorStore, DEFAULT_DB_PATH as DEFAULT_ALLOCATOR_DB_PATH

try:
    from nontrading.store import RevenueStore
except Exception:  # pragma: no cover - nontrading stays optional for pack generation
    RevenueStore = None  # type: ignore[assignment]

KIBANA_STACK_VERSION = "8.15.0"
DONATION_RATE = 0.20
DEFAULT_REVENUE_DB_PATH = Path("data") / "revenue_agent.db"
DEFAULT_GUARANTEED_DOLLAR_AUDIT_PATH = Path("reports") / "guaranteed_dollar_audit.json"
DEFAULT_B1_TEMPLATE_AUDIT_PATH = Path("reports") / "b1_template_audit.json"
DEFAULT_RESEARCH_METRICS_GLOB = "reports/run_*_metrics.json"
DEFAULT_PHASE6_OUTPUT_DIR = Path("deploy") / "kibana" / "phase6"
_UUID_NAMESPACE = uuid.UUID("c11f62ba-fd33-4d8a-b4d2-4d4e45a2cda6")


def build_phase6_dashboard_pack(
    session: Session,
    *,
    allocator_db_path: str | Path = DEFAULT_ALLOCATOR_DB_PATH,
    revenue_db_path: str | Path = DEFAULT_REVENUE_DB_PATH,
    guaranteed_dollar_audit_path: str | Path = DEFAULT_GUARANTEED_DOLLAR_AUDIT_PATH,
    b1_template_audit_path: str | Path = DEFAULT_B1_TEMPLATE_AUDIT_PATH,
    research_metrics_glob: str = DEFAULT_RESEARCH_METRICS_GLOB,
) -> dict[str, Any]:
    """Build the full Phase 6 dashboard pack from repo state."""

    versions = {row.id: row for row in crud.list_strategy_versions(session, limit=2_000)}
    deployments = crud.list_deployments(session, limit=2_000)
    snapshots = crud.list_daily_snapshots(session, limit=5_000)
    decisions = crud.list_promotion_decisions(session, limit=2_000)
    cycles = crud.list_flywheel_cycles(session, limit=2_000)
    tasks = crud.list_flywheel_tasks(session, limit=5_000)
    peer_bundles = crud.list_peer_improvement_bundles(session, limit=2_000)

    strategy_rows, histories = _build_strategy_rows(
        versions=versions,
        deployments=deployments,
        snapshots=snapshots,
        decisions=decisions,
    )
    allocator_summary = _load_allocator_summary(allocator_db_path)
    revenue_summary = _load_revenue_summary(revenue_db_path)
    guaranteed_dollar_summary = _load_guaranteed_dollar_summary(guaranteed_dollar_audit_path)
    b1_template_summary = _load_b1_template_summary(b1_template_audit_path)
    regime_summary = _load_market_regime_summary(research_metrics_glob)

    collective_health = _build_collective_health(
        strategy_rows=strategy_rows,
        histories=histories,
        snapshots=snapshots,
        revenue_summary=revenue_summary,
    )
    leaderboard = _build_leaderboard(strategy_rows)
    strategy_diversity = _build_strategy_diversity(
        strategy_rows=strategy_rows,
        decisions=decisions,
        guaranteed_dollar_summary=guaranteed_dollar_summary,
        b1_template_summary=b1_template_summary,
    )
    knowledge_flow = _build_knowledge_flow(
        cycles=cycles,
        tasks=tasks,
        peer_bundles=peer_bundles,
        allocator_summary=allocator_summary,
        revenue_summary=revenue_summary,
    )
    charitable_impact = _build_charitable_impact(strategy_rows)
    alert_rules = _build_alert_rules(
        strategy_rows=strategy_rows,
        snapshots=snapshots,
        revenue_summary=revenue_summary,
    )

    model = {
        "generated_at": _utcnow_iso(),
        "sources": {
            "allocator_db_path": str(allocator_db_path),
            "revenue_db_path": str(revenue_db_path),
            "guaranteed_dollar_audit_path": str(guaranteed_dollar_audit_path),
            "b1_template_audit_path": str(b1_template_audit_path),
            "research_metrics_glob": research_metrics_glob,
        },
        "collective_health": collective_health,
        "leaderboard": leaderboard,
        "strategy_diversity": strategy_diversity,
        "market_regime": regime_summary,
        "knowledge_flow": knowledge_flow,
        "charitable_impact": charitable_impact,
        "alert_rules": alert_rules,
    }

    dashboards = _build_dashboard_specs(model)
    canvas_workpad = _build_canvas_workpad(model)

    return {
        **model,
        "dashboards": dashboards,
        "canvas_workpad": canvas_workpad,
    }


def write_phase6_dashboard_pack(output_dir: str | Path, pack: dict[str, Any]) -> dict[str, str]:
    """Write the Phase 6 pack to disk."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    model_path = root / "phase6_dashboard_model.json"
    dashboards_path = root / "phase6_dashboards.json"
    saved_objects_path = root / "phase6_saved_objects.ndjson"
    canvas_path = root / "phase6_canvas_workpad.json"
    alert_rules_path = root / "phase6_alert_rules.json"
    readme_path = root / "README.md"

    model_path.write_text(json.dumps(_jsonable(pack, drop={"dashboards", "canvas_workpad"}), indent=2, sort_keys=True))
    dashboards_path.write_text(json.dumps(pack["dashboards"], indent=2, sort_keys=True))
    saved_objects_path.write_text(render_saved_objects_ndjson(pack))
    canvas_path.write_text(json.dumps(pack["canvas_workpad"], indent=2, sort_keys=True))
    alert_rules_path.write_text(json.dumps(pack["alert_rules"], indent=2, sort_keys=True))
    readme_path.write_text(_render_readme(pack))

    return {
        "model_json": str(model_path),
        "dashboards_json": str(dashboards_path),
        "saved_objects_ndjson": str(saved_objects_path),
        "canvas_workpad_json": str(canvas_path),
        "alert_rules_json": str(alert_rules_path),
        "readme_md": str(readme_path),
    }


def render_saved_objects_ndjson(pack: dict[str, Any]) -> str:
    """Render the markdown-first Kibana saved object pack as NDJSON."""

    lines: list[str] = []
    for dashboard in pack["dashboards"]:
        vis_id = _stable_id(f"vis:{dashboard['title']}")
        dashboard_id = _stable_id(f"dashboard:{dashboard['title']}")
        lines.append(
            json.dumps(
                {
                    "id": vis_id,
                    "type": "visualization",
                    "attributes": {
                        "title": dashboard["title"],
                        "description": dashboard["description"],
                        "version": 1,
                        "visState": json.dumps(
                            {
                                "title": dashboard["title"],
                                "type": "markdown",
                                "aggs": [],
                                "params": {
                                    "markdown": dashboard["markdown"],
                                    "fontSize": 12,
                                    "openLinksInNewTab": True,
                                },
                            }
                        ),
                        "uiStateJSON": "{}",
                        "kibanaSavedObjectMeta": {
                            "searchSourceJSON": json.dumps({"query": {"language": "kuery", "query": ""}, "filter": []})
                        },
                    },
                    "references": [],
                    "migrationVersion": {"visualization": KIBANA_STACK_VERSION},
                    "coreMigrationVersion": KIBANA_STACK_VERSION,
                }
            )
        )
        lines.append(
            json.dumps(
                {
                    "id": dashboard_id,
                    "type": "dashboard",
                    "attributes": {
                        "title": dashboard["title"],
                        "description": dashboard["description"],
                        "hits": 0,
                        "timeRestore": False,
                        "optionsJSON": json.dumps(
                            {
                                "useMargins": True,
                                "syncColors": False,
                                "syncCursor": False,
                                "syncTooltips": False,
                            }
                        ),
                        "panelsJSON": json.dumps(
                            [
                                {
                                    "embeddableConfig": {},
                                    "gridData": {"x": 0, "y": 0, "w": 48, "h": 28, "i": "1"},
                                    "panelIndex": "1",
                                    "panelRefName": "panel_0",
                                    "type": "visualization",
                                    "version": KIBANA_STACK_VERSION,
                                }
                            ]
                        ),
                        "kibanaSavedObjectMeta": {
                            "searchSourceJSON": json.dumps({"query": {"language": "kuery", "query": ""}, "filter": []})
                        },
                    },
                    "references": [{"id": vis_id, "name": "panel_0", "type": "visualization"}],
                    "migrationVersion": {"dashboard": KIBANA_STACK_VERSION},
                    "coreMigrationVersion": KIBANA_STACK_VERSION,
                }
            )
        )
    return "\n".join(lines) + "\n"


def _build_strategy_rows(
    *,
    versions: dict[int, Any],
    deployments: list[Any],
    snapshots: list[Any],
    decisions: list[Any],
) -> tuple[list[dict[str, Any]], dict[int, list[Any]]]:
    histories: dict[int, list[Any]] = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.strategy_version_id is None:
            continue
        histories[snapshot.strategy_version_id].append(snapshot)

    for history in histories.values():
        history.sort(key=lambda row: (str(row.snapshot_date), row.created_at))

    latest_deployment_by_strategy: dict[int, Any] = {}
    for row in deployments:
        current = latest_deployment_by_strategy.get(row.strategy_version_id)
        if current is None or row.started_at > current.started_at:
            latest_deployment_by_strategy[row.strategy_version_id] = row

    latest_decision_by_strategy: dict[int, Any] = {}
    for row in decisions:
        current = latest_decision_by_strategy.get(row.strategy_version_id)
        if current is None or row.created_at > current.created_at:
            latest_decision_by_strategy[row.strategy_version_id] = row

    rows: list[dict[str, Any]] = []
    for strategy_version_id, history in histories.items():
        version = versions.get(strategy_version_id)
        if version is None:
            continue
        latest = history[-1]
        deployment = latest_deployment_by_strategy.get(strategy_version_id)
        decision = latest_decision_by_strategy.get(strategy_version_id)
        score, score_method = _risk_adjusted_score(history)
        rows.append(
            {
                "strategy_version_id": strategy_version_id,
                "strategy": f"{version.strategy_key}:{version.version_label}",
                "strategy_key": version.strategy_key,
                "version_label": version.version_label,
                "lane": version.lane,
                "environment": latest.environment,
                "deployment_status": deployment.status if deployment is not None else "unknown",
                "capital_cap_usd": float(deployment.capital_cap_usd) if deployment is not None else 0.0,
                "starting_bankroll": float(latest.starting_bankroll or 0.0),
                "ending_bankroll": float(latest.ending_bankroll or 0.0),
                "realized_pnl": float(latest.realized_pnl or 0.0),
                "unrealized_pnl": float(latest.unrealized_pnl or 0.0),
                "open_positions": int(latest.open_positions or 0),
                "closed_trades": int(latest.closed_trades or 0),
                "win_rate": _float_or_none(latest.win_rate),
                "fill_rate": _float_or_none(latest.fill_rate),
                "avg_slippage_bps": _float_or_none(latest.avg_slippage_bps),
                "rolling_brier": _float_or_none(latest.rolling_brier),
                "rolling_ece": _float_or_none(latest.rolling_ece),
                "max_drawdown_pct": float(latest.max_drawdown_pct or 0.0),
                "kill_events": int(latest.kill_events or 0),
                "decision": decision.decision if decision is not None else "unknown",
                "reason_code": decision.reason_code if decision is not None else "n/a",
                "risk_adjusted_return": round(score, 6),
                "risk_metric": score_method,
                "reserved_donation_usd": round(max(float(latest.realized_pnl or 0.0), 0.0) * DONATION_RATE, 2),
                "last_seen": latest.created_at.isoformat() if latest.created_at is not None else None,
                "last_seen_age_minutes": _age_minutes(latest.created_at),
            }
        )

    rows.sort(key=lambda row: (row["risk_adjusted_return"], row["realized_pnl"]), reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows, histories


def _build_collective_health(
    *,
    strategy_rows: list[dict[str, Any]],
    histories: dict[int, list[Any]],
    snapshots: list[Any],
    revenue_summary: dict[str, Any],
) -> dict[str, Any]:
    environment_rows: dict[str, dict[str, Any]] = {}
    lane_environment_heatmap: list[dict[str, Any]] = []
    grouped_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in strategy_rows:
        env_bucket = environment_rows.setdefault(
            row["environment"],
            {
                "strategies": 0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "open_positions": 0,
                "kill_events": 0,
                "max_drawdown_pct": 0.0,
            },
        )
        env_bucket["strategies"] += 1
        env_bucket["realized_pnl"] += row["realized_pnl"]
        env_bucket["unrealized_pnl"] += row["unrealized_pnl"]
        env_bucket["open_positions"] += row["open_positions"]
        env_bucket["kill_events"] += row["kill_events"]
        env_bucket["max_drawdown_pct"] = max(env_bucket["max_drawdown_pct"], row["max_drawdown_pct"])
        grouped_by_pair[(row["lane"], row["environment"])].append(row)

    for (lane, environment), rows in sorted(grouped_by_pair.items()):
        lane_environment_heatmap.append(
            {
                "lane": lane,
                "environment": environment,
                "strategies": len(rows),
                "max_drawdown_pct": round(max(row["max_drawdown_pct"] for row in rows), 4),
                "realized_pnl": round(sum(row["realized_pnl"] for row in rows), 2),
            }
        )

    trading_agents = sum(1 for row in strategy_rows if row["deployment_status"] == "active")
    non_trading_agents = 1 if revenue_summary.get("configured") else 0
    latest_by_date: dict[str, dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "starting": 0.0})
    for snapshot in snapshots:
        latest_by_date[str(snapshot.snapshot_date)]["pnl"] += float(snapshot.realized_pnl or 0.0)
        latest_by_date[str(snapshot.snapshot_date)]["starting"] += float(snapshot.starting_bankroll or 0.0)
    daily_returns = [
        bucket["pnl"] / bucket["starting"]
        for _, bucket in sorted(latest_by_date.items())
        if bucket["starting"] > 0
    ]

    return {
        "agent_totals": {
            "total_agents": trading_agents + non_trading_agents,
            "trading_agents": trading_agents,
            "non_trading_agents": non_trading_agents,
        },
        "financials": {
            "aggregate_realized_pnl": round(sum(row["realized_pnl"] for row in strategy_rows), 2),
            "aggregate_unrealized_pnl": round(sum(row["unrealized_pnl"] for row in strategy_rows), 2),
            "aggregate_sharpe": round(_annualized_sharpe(daily_returns), 4),
            "reserved_donation_usd": round(sum(row["reserved_donation_usd"] for row in strategy_rows), 2),
        },
        "risk": {
            "open_positions": int(sum(row["open_positions"] for row in strategy_rows)),
            "closed_trades": int(sum(row["closed_trades"] for row in strategy_rows)),
            "kill_events": int(sum(row["kill_events"] for row in strategy_rows)),
            "max_drawdown_pct": round(max((row["max_drawdown_pct"] for row in strategy_rows), default=0.0), 4),
        },
        "by_environment": environment_rows,
        "drawdown_heatmap": lane_environment_heatmap,
        "latest_snapshot_count": len(histories),
        "non_trading_operational": {
            "configured": bool(revenue_summary.get("configured")),
            "deliverability_status": revenue_summary.get("deliverability_status", "unknown"),
            "heartbeat_age_minutes": revenue_summary.get("heartbeat_age_minutes"),
            "campaigns": revenue_summary.get("campaigns", 0),
        },
    }


def _build_leaderboard(strategy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for row in strategy_rows:
        rows.append(
            {
                "rank": row["rank"],
                "strategy": row["strategy"],
                "lane": row["lane"],
                "environment": row["environment"],
                "risk_adjusted_return": row["risk_adjusted_return"],
                "risk_metric": row["risk_metric"],
                "realized_pnl": round(row["realized_pnl"], 2),
                "win_rate": row["win_rate"],
                "fill_rate": row["fill_rate"],
                "max_drawdown_pct": round(row["max_drawdown_pct"], 4),
                "decision": row["decision"],
                "reason_code": row["reason_code"],
            }
        )
    return {"rows": rows}


def _build_strategy_diversity(
    *,
    strategy_rows: list[dict[str, Any]],
    decisions: list[Any],
    guaranteed_dollar_summary: dict[str, Any],
    b1_template_summary: dict[str, Any],
) -> dict[str, Any]:
    lane_counts = Counter(row["lane"] for row in strategy_rows)
    environment_counts = Counter(row["environment"] for row in strategy_rows)
    decision_counts = Counter(row.decision for row in decisions)
    crowding_alerts = [
        {
            "label": construction_type,
            "count": count,
            "status": "watch" if count >= 10 else "ok",
        }
        for construction_type, count in sorted(
            guaranteed_dollar_summary.get("best_construction_counts", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    return {
        "lane_counts": dict(sorted(lane_counts.items())),
        "environment_counts": dict(sorted(environment_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "a6_audit": guaranteed_dollar_summary,
        "b1_audit": b1_template_summary,
        "crowding_alerts": crowding_alerts,
    }


def _build_knowledge_flow(
    *,
    cycles: list[Any],
    tasks: list[Any],
    peer_bundles: list[Any],
    allocator_summary: dict[str, Any],
    revenue_summary: dict[str, Any],
) -> dict[str, Any]:
    open_tasks = [row for row in tasks if row.status == "open"]
    high_priority_open = [row for row in open_tasks if int(row.priority or 50) <= 25]
    cycle_status = Counter(row.status for row in cycles)
    imported_bulletins = sum(1 for row in cycles if str(row.cycle_key).startswith("bulletin-"))
    imported_improvements = sum(1 for row in peer_bundles if row.direction == "imported")
    exported_improvements = sum(1 for row in peer_bundles if row.direction == "exported")

    return {
        "cycles_total": len(cycles),
        "cycle_status_counts": dict(sorted(cycle_status.items())),
        "open_tasks": len(open_tasks),
        "high_priority_open_tasks": len(high_priority_open),
        "imported_bulletins": imported_bulletins,
        "imported_peer_improvements": imported_improvements,
        "exported_peer_improvements": exported_improvements,
        "allocator": allocator_summary,
        "revenue_agent": revenue_summary,
        "top_open_tasks": [
            {
                "priority": row.priority,
                "action": row.action,
                "title": row.title,
            }
            for row in sorted(open_tasks, key=lambda item: (item.priority, item.created_at))[:5]
        ],
    }


def _build_charitable_impact(strategy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    reserved_total = round(sum(row["reserved_donation_usd"] for row in strategy_rows), 2)
    milestones = []
    for amount, label in ((100.0, "Seed"), (500.0, "First Meaningful Month"), (1_000.0, "Five Figures Annualized")):
        milestones.append(
            {
                "label": label,
                "target_usd": amount,
                "progress_pct": round(min((reserved_total / amount) * 100.0, 100.0), 2),
                "hit": reserved_total >= amount,
            }
        )
    return {
        "reserved_total_usd": reserved_total,
        "donation_rate": DONATION_RATE,
        "by_strategy": [
            {
                "strategy": row["strategy"],
                "lane": row["lane"],
                "reserved_donation_usd": row["reserved_donation_usd"],
            }
            for row in strategy_rows
        ],
        "milestones": milestones,
    }


def _build_alert_rules(
    *,
    strategy_rows: list[dict[str, Any]],
    snapshots: list[Any],
    revenue_summary: dict[str, Any],
) -> dict[str, Any]:
    by_date: dict[str, float] = defaultdict(float)
    for snapshot in snapshots:
        by_date[str(snapshot.snapshot_date)] += float(snapshot.realized_pnl or 0.0)
    sorted_dates = sorted(by_date)
    current_total = by_date[sorted_dates[-1]] if sorted_dates else 0.0
    previous_total = by_date[sorted_dates[-2]] if len(sorted_dates) >= 2 else None
    revenue_change_pct = None
    revenue_status = "insufficient_data"
    if previous_total not in (None, 0.0):
        revenue_change_pct = ((current_total - previous_total) / abs(previous_total)) * 100.0
        revenue_status = "firing" if revenue_change_pct <= -20.0 else "ok"

    drawdown_affected = [
        row["strategy"]
        for row in strategy_rows
        if float(row["max_drawdown_pct"] or 0.0) >= 0.15
    ]
    offline_affected = [
        row["strategy"]
        for row in strategy_rows
        if row["deployment_status"] == "active"
        and row["last_seen_age_minutes"] is not None
        and row["last_seen_age_minutes"] > 60.0
    ]
    heartbeat_age = revenue_summary.get("heartbeat_age_minutes")
    if revenue_summary.get("configured") and (heartbeat_age is None or heartbeat_age > 60.0):
        offline_affected.append("non_trading:revenue_agent")

    return {
        "rules": [
            {
                "id": "collective-revenue-drop-gt-20pct",
                "name": "Collective revenue drop >20%",
                "threshold_pct": -20.0,
                "status": revenue_status,
                "current_change_pct": None if revenue_change_pct is None else round(revenue_change_pct, 2),
                "current_total": round(current_total, 2),
                "previous_total": None if previous_total is None else round(previous_total, 2),
                "notes": "Compares the latest two snapshot dates across all stored strategy snapshots.",
            },
            {
                "id": "drawdown-gt-15pct",
                "name": "Max drawdown >15%",
                "threshold_pct": 15.0,
                "status": "firing" if drawdown_affected else "ok",
                "affected_agents": drawdown_affected,
            },
            {
                "id": "agent-offline-gt-1h",
                "name": "Agent offline >1 hour",
                "threshold_minutes": 60.0,
                "status": "firing" if offline_affected else "ok",
                "affected_agents": offline_affected,
            },
        ]
    }


def _load_allocator_summary(path: str | Path) -> dict[str, Any]:
    db_path = Path(path)
    if not db_path.exists():
        return {"configured": False}
    store = AllocatorStore(db_path)
    store.init_db()
    latest = store.latest_decision()
    stats = store.arm_stats()
    return {
        "configured": True,
        "db_path": str(db_path),
        "latest_decision": None
        if latest is None
        else {
            "decision_date": latest.decision_date.isoformat(),
            "mode": latest.mode.value,
            "trading_share": latest.trading_share,
            "non_trading_share": latest.non_trading_share,
            "trading_budget_usd": latest.trading_budget_usd,
            "non_trading_send_quota": latest.non_trading_send_quota,
            "non_trading_llm_token_budget": latest.non_trading_llm_token_budget,
            "deliverability_risk": latest.deliverability_risk.value,
            "risk_override_applied": latest.risk_override_applied,
        },
        "arm_stats": {
            name: {
                "observations": row.observations,
                "successes": row.successes,
                "failures": row.failures,
                "avg_roi": row.avg_roi,
            }
            for name, row in stats.items()
        },
    }


def _load_revenue_summary(path: str | Path) -> dict[str, Any]:
    db_path = Path(path)
    if RevenueStore is None or not db_path.exists():
        return {"configured": False}
    store = RevenueStore(db_path)
    state = store.get_agent_state()
    status_snapshot = store.status_snapshot()
    outbox_messages = store.list_outbox_messages()
    outbox_status = Counter(message.status for message in outbox_messages)
    return {
        "configured": True,
        "db_path": str(db_path),
        "campaigns": int(status_snapshot.get("campaigns", 0)),
        "leads": int(status_snapshot.get("leads", 0)),
        "outbox_messages": int(status_snapshot.get("outbox_messages", 0)),
        "suppression_entries": int(status_snapshot.get("suppression_entries", 0)),
        "global_kill_switch": bool(status_snapshot.get("global_kill_switch", False)),
        "deliverability_status": str(status_snapshot.get("deliverability_status", "unknown")),
        "heartbeat_age_minutes": _age_minutes(_parse_optional_iso(state.last_heartbeat_at)),
        "outbox_status_counts": dict(sorted(outbox_status.items())),
        "sends_today": store.count_total_sends_today(),
        "unsubscribes_today": store.count_send_events_today("unsubscribe"),
    }


def _load_guaranteed_dollar_summary(path: str | Path) -> dict[str, Any]:
    rows = _load_json(Path(path), default=[])
    if not isinstance(rows, list):
        rows = []
    construction_counts = Counter()
    executable = 0
    ready = 0
    top_edges: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        best = row.get("best_construction") or {}
        construction_type = str(best.get("construction_type") or "unknown")
        construction_counts[construction_type] += 1
        if best.get("executable"):
            executable += 1
        if isinstance(best.get("readiness"), dict) and best["readiness"].get("ready"):
            ready += 1
        top_edges.append(float(best.get("maker_gross_edge") or 0.0))
    return {
        "events_scanned": len(rows),
        "best_construction_counts": dict(sorted(construction_counts.items())),
        "executable_events": executable,
        "ready_events": ready,
        "max_maker_gross_edge": round(max(top_edges, default=0.0), 6),
    }


def _load_b1_template_summary(path: str | Path) -> dict[str, Any]:
    payload = _load_json(Path(path), default={})
    template_markets = payload.get("template_markets") if isinstance(payload, dict) else {}
    template_pairs = payload.get("template_pairs") if isinstance(payload, dict) else []
    if not isinstance(template_markets, dict):
        template_markets = {}
    if not isinstance(template_pairs, list):
        template_pairs = []
    dominant_template = None
    if template_markets:
        dominant_template = max(template_markets.items(), key=lambda item: item[1])[0]
    return {
        "template_market_counts": dict(sorted((str(key), int(value)) for key, value in template_markets.items())),
        "template_pair_count": len(template_pairs),
        "dominant_template": dominant_template,
    }


def _load_market_regime_summary(glob_pattern: str) -> dict[str, Any]:
    paths = sorted(Path(path) for path in glob.glob(glob_pattern))
    if not paths:
        return {"configured": False}
    report_path = paths[-1]
    payload = _load_json(report_path, default={})
    results = payload.get("results") if isinstance(payload, dict) else {}
    results = results if isinstance(results, dict) else {}
    vol_regime = results.get("vol_regime") if isinstance(results.get("vol_regime"), dict) else {}
    breakdown = []
    for key, row in results.items():
        if not isinstance(row, dict):
            continue
        breakdown.append(
            {
                "strategy_key": key,
                "strategy": row.get("strategy", key),
                "signals": int(row.get("signals") or 0),
                "win_rate": _float_or_none(row.get("win_rate")),
                "ev_maker": _float_or_none(row.get("ev_maker")),
                "sharpe": _float_or_none(row.get("sharpe")),
                "regime_decay": bool(row.get("regime_decay", False)),
            }
        )
    breakdown.sort(key=lambda item: ((item["ev_maker"] or float("-inf")), item["signals"]), reverse=True)
    current_regime, inference = _infer_market_regime(payload, vol_regime)
    return {
        "configured": True,
        "report_path": str(report_path),
        "recommendation": payload.get("recommendation", "unknown"),
        "reasoning": payload.get("reasoning", ""),
        "current_regime": current_regime,
        "regime_inference": inference,
        "vol_regime": {
            "signals": int(vol_regime.get("signals") or 0),
            "win_rate": _float_or_none(vol_regime.get("win_rate")),
            "ev_maker": _float_or_none(vol_regime.get("ev_maker")),
            "regime_decay": bool(vol_regime.get("regime_decay", False)),
            "notes": vol_regime.get("notes", []),
        },
        "performance_breakdown": breakdown[:6],
        "next_actions": payload.get("next_actions", [])[:5],
    }


def _build_dashboard_specs(pack: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "title": "Collective Health",
            "description": "Portfolio-wide health across trading and non-trading lanes.",
            "markdown": _render_collective_health_markdown(pack),
        },
        {
            "title": "Leaderboard",
            "description": "Risk-adjusted ranking of active Elastifund strategies.",
            "markdown": _render_leaderboard_markdown(pack),
        },
        {
            "title": "Strategy Diversity",
            "description": "Lane mix, environment concentration, and structural crowding signals.",
            "markdown": _render_strategy_diversity_markdown(pack),
        },
        {
            "title": "Market Regime",
            "description": "Latest research-regime read and regime-specific performance breakdown.",
            "markdown": _render_market_regime_markdown(pack),
        },
        {
            "title": "Knowledge Flow",
            "description": "Flywheel cycles, peer exchange, allocator posture, and revenue-agent state.",
            "markdown": _render_knowledge_flow_markdown(pack),
        },
        {
            "title": "Charitable Impact",
            "description": "Donation reserve tracking and milestone progress.",
            "markdown": _render_charitable_impact_markdown(pack),
        },
    ]


def _build_canvas_workpad(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "Elastifund Executive Review",
        "size": {"width": 1920, "height": 1080},
        "autoplay": {"enabled": True, "interval_seconds": 15},
        "pages": [
            {
                "name": "Collective Health",
                "sections": [
                    {"title": "Collective Health", "markdown": _render_collective_health_markdown(pack)},
                    {"title": "Leaderboard", "markdown": _render_leaderboard_markdown(pack)},
                ],
            },
            {
                "name": "Strategy and Knowledge",
                "sections": [
                    {"title": "Strategy Diversity", "markdown": _render_strategy_diversity_markdown(pack)},
                    {"title": "Market Regime", "markdown": _render_market_regime_markdown(pack)},
                    {"title": "Knowledge Flow", "markdown": _render_knowledge_flow_markdown(pack)},
                ],
            },
            {
                "name": "Impact and Alerts",
                "sections": [
                    {"title": "Charitable Impact", "markdown": _render_charitable_impact_markdown(pack)},
                    {"title": "Alert Rules", "markdown": _render_alert_rules_markdown(pack)},
                ],
            },
        ],
    }


def _render_collective_health_markdown(pack: dict[str, Any]) -> str:
    health = pack["collective_health"]
    totals = health["agent_totals"]
    financials = health["financials"]
    risk = health["risk"]
    env_rows = [
        [env, metrics["strategies"], f"{metrics['realized_pnl']:.2f}", f"{metrics['unrealized_pnl']:.2f}", metrics["open_positions"], f"{metrics['max_drawdown_pct']:.1%}"]
        for env, metrics in sorted(health["by_environment"].items())
    ]
    lines = [
        "## Collective Health",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Total agents", totals["total_agents"]],
                ["Trading agents", totals["trading_agents"]],
                ["Non-trading agents", totals["non_trading_agents"]],
                ["Aggregate realized PnL", f"${financials['aggregate_realized_pnl']:.2f}"],
                ["Aggregate unrealized PnL", f"${financials['aggregate_unrealized_pnl']:.2f}"],
                ["Aggregate Sharpe", financials["aggregate_sharpe"]],
                ["Reserved donations", f"${financials['reserved_donation_usd']:.2f}"],
                ["Open positions", risk["open_positions"]],
                ["Closed trades", risk["closed_trades"]],
                ["Kill events", risk["kill_events"]],
                ["Max drawdown", f"{risk['max_drawdown_pct']:.1%}"],
            ],
        ),
        "",
        "### By Environment",
        "",
        _markdown_table(
            ["Environment", "Strategies", "Realized PnL", "Unrealized PnL", "Open Positions", "Max Drawdown"],
            env_rows,
        ),
        "",
        "### Alert Snapshot",
        "",
        _render_alert_rules_markdown(pack),
    ]
    return "\n".join(lines)


def _render_leaderboard_markdown(pack: dict[str, Any]) -> str:
    rows = pack["leaderboard"]["rows"]
    if not rows:
        return "## Leaderboard\n\nNo strategy snapshots found.\n"
    table_rows = [
        [
            row["rank"],
            row["strategy"],
            row["lane"],
            row["environment"],
            f"{row['risk_adjusted_return']:.3f}",
            row["risk_metric"],
            f"${row['realized_pnl']:.2f}",
            _pct_or_dash(row["win_rate"]),
            _pct_or_dash(row["fill_rate"]),
            f"{row['max_drawdown_pct']:.1%}",
            row["decision"],
        ]
        for row in rows[:10]
    ]
    return "\n".join(
        [
            "## Leaderboard",
            "",
            _markdown_table(
                [
                    "Rank",
                    "Strategy",
                    "Lane",
                    "Env",
                    "Risk-Adj",
                    "Metric",
                    "Realized PnL",
                    "Win Rate",
                    "Fill Rate",
                    "Max DD",
                    "Decision",
                ],
                table_rows,
            ),
        ]
    )


def _render_strategy_diversity_markdown(pack: dict[str, Any]) -> str:
    diversity = pack["strategy_diversity"]
    lane_rows = [[key, value] for key, value in sorted(diversity["lane_counts"].items())]
    env_rows = [[key, value] for key, value in sorted(diversity["environment_counts"].items())]
    crowding_rows = [
        [row["label"], row["count"], row["status"]]
        for row in diversity["crowding_alerts"][:8]
    ]
    return "\n".join(
        [
            "## Strategy Diversity",
            "",
            "### Lane Mix",
            "",
            _markdown_table(["Lane", "Strategies"], lane_rows or [["n/a", 0]]),
            "",
            "### Environment Mix",
            "",
            _markdown_table(["Environment", "Strategies"], env_rows or [["n/a", 0]]),
            "",
            "### A-6 / B-1 Structural Audit",
            "",
            _markdown_table(
                ["Metric", "Value"],
                [
                    ["A-6 events scanned", diversity["a6_audit"]["events_scanned"]],
                    ["A-6 executable events", diversity["a6_audit"]["executable_events"]],
                    ["A-6 ready events", diversity["a6_audit"]["ready_events"]],
                    ["A-6 max maker gross edge", diversity["a6_audit"]["max_maker_gross_edge"]],
                    ["B-1 template pairs", diversity["b1_audit"]["template_pair_count"]],
                    ["B-1 dominant template", diversity["b1_audit"]["dominant_template"] or "n/a"],
                ],
            ),
            "",
            "### Crowding Watchlist",
            "",
            _markdown_table(["Construction", "Count", "Status"], crowding_rows or [["n/a", 0, "ok"]]),
        ]
    )


def _render_market_regime_markdown(pack: dict[str, Any]) -> str:
    regime = pack["market_regime"]
    if not regime.get("configured"):
        return "## Market Regime\n\nNo research regime report found.\n"
    rows = [
        [
            row["strategy"],
            row["signals"],
            _pct_or_dash(row["win_rate"]),
            _float_or_dash(row["ev_maker"], digits=3),
            _float_or_dash(row["sharpe"], digits=3),
            "yes" if row["regime_decay"] else "no",
        ]
        for row in regime["performance_breakdown"]
    ]
    lines = [
        "## Market Regime",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Current regime", regime["current_regime"]],
                ["Inference", regime["regime_inference"]],
                ["Recommendation", regime["recommendation"]],
                ["Vol-regime signals", regime["vol_regime"]["signals"]],
                ["Vol-regime win rate", _pct_or_dash(regime["vol_regime"]["win_rate"])],
                ["Vol-regime maker EV", _float_or_dash(regime["vol_regime"]["ev_maker"], digits=3)],
                ["Vol-regime decay", "yes" if regime["vol_regime"]["regime_decay"] else "no"],
            ],
        ),
        "",
        "### Performance Breakdown",
        "",
        _markdown_table(
            ["Strategy", "Signals", "Win Rate", "Maker EV", "Sharpe", "Regime Decay"],
            rows or [["n/a", 0, "-", "-", "-", "-"]],
        ),
    ]
    if regime.get("next_actions"):
        lines.extend(["", "### Next Actions", ""])
        lines.extend([f"- {item}" for item in regime["next_actions"]])
    return "\n".join(lines)


def _render_knowledge_flow_markdown(pack: dict[str, Any]) -> str:
    flow = pack["knowledge_flow"]
    allocator = flow["allocator"]
    revenue = flow["revenue_agent"]
    latest_decision = allocator.get("latest_decision") or {}
    return "\n".join(
        [
            "## Knowledge Flow",
            "",
            _markdown_table(
                ["Metric", "Value"],
                [
                    ["Flywheel cycles", flow["cycles_total"]],
                    ["Open tasks", flow["open_tasks"]],
                    ["High-priority open tasks", flow["high_priority_open_tasks"]],
                    ["Imported bulletins", flow["imported_bulletins"]],
                    ["Imported improvements", flow["imported_peer_improvements"]],
                    ["Exported improvements", flow["exported_peer_improvements"]],
                    ["Allocator configured", "yes" if allocator.get("configured") else "no"],
                    ["Allocator mode", latest_decision.get("mode", "n/a")],
                    ["Trading share", _pct_or_dash(latest_decision.get("trading_share"))],
                    ["Non-trading share", _pct_or_dash(latest_decision.get("non_trading_share"))],
                    ["Revenue agent configured", "yes" if revenue.get("configured") else "no"],
                    ["Deliverability", revenue.get("deliverability_status", "n/a")],
                    ["Revenue heartbeat age", _minutes_or_dash(revenue.get("heartbeat_age_minutes"))],
                ],
            ),
            "",
            "### Top Open Tasks",
            "",
            _markdown_table(
                ["Priority", "Action", "Title"],
                [
                    [row["priority"], row["action"], row["title"]]
                    for row in flow["top_open_tasks"]
                ]
                or [["n/a", "none", "No open flywheel tasks"]],
            ),
        ]
    )


def _render_charitable_impact_markdown(pack: dict[str, Any]) -> str:
    impact = pack["charitable_impact"]
    return "\n".join(
        [
            "## Charitable Impact",
            "",
            _markdown_table(
                ["Metric", "Value"],
                [
                    ["Donation reserve rate", _pct_or_dash(impact["donation_rate"])],
                    ["Reserved total", f"${impact['reserved_total_usd']:.2f}"],
                ],
            ),
            "",
            "### Strategy Contributions",
            "",
            _markdown_table(
                ["Strategy", "Lane", "Reserved Donation"],
                [
                    [row["strategy"], row["lane"], f"${row['reserved_donation_usd']:.2f}"]
                    for row in impact["by_strategy"]
                ]
                or [["n/a", "n/a", "$0.00"]],
            ),
            "",
            "### Milestones",
            "",
            _markdown_table(
                ["Milestone", "Target", "Progress", "Hit"],
                [
                    [row["label"], f"${row['target_usd']:.0f}", f"{row['progress_pct']:.1f}%", "yes" if row["hit"] else "no"]
                    for row in impact["milestones"]
                ],
            ),
        ]
    )


def _render_alert_rules_markdown(pack: dict[str, Any]) -> str:
    rules = pack["alert_rules"]["rules"]
    rows = []
    for row in rules:
        current_value = row.get("current_change_pct")
        if current_value is None and "affected_agents" in row:
            current_value = len(row["affected_agents"])
        rows.append(
            [
                row["name"],
                row["status"],
                _value_or_dash(current_value),
                row.get("threshold_pct") or row.get("threshold_minutes") or "-",
            ]
        )
    return _markdown_table(["Rule", "Status", "Current", "Threshold"], rows or [["n/a", "ok", "-", "-"]])


def _render_readme(pack: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 6 Kibana Pack",
            "",
            "Generated artifacts for the Elastifund.io Phase 6 leaderboard and monitoring layer.",
            "",
            "## Contents",
            "",
            "- `phase6_dashboard_model.json`: normalized source model built from the control-plane DB, allocator DB, revenue-agent DB, structural-arb audits, and the latest research metrics report.",
            "- `phase6_dashboards.json`: six dashboard specs with rendered markdown content.",
            "- `phase6_saved_objects.ndjson`: Kibana saved-object import pack for six markdown-first dashboards.",
            "- `phase6_canvas_workpad.json`: three-page executive workpad spec (health, knowledge, impact).",
            "- `phase6_alert_rules.json`: repo-side rule definitions plus current evaluations for revenue drop, drawdown, and offline agents.",
            "",
            "## Regenerate",
            "",
            "```bash",
            "python -m data_layer flywheel-kibana-pack \\",
            f"  --output-dir {DEFAULT_PHASE6_OUTPUT_DIR}",
            "```",
            "",
            "## Import Workflow",
            "",
            "1. Import `phase6_saved_objects.ndjson` in Kibana Saved Objects.",
            "2. Rebuild the Canvas workpad from `phase6_canvas_workpad.json` if you want the 1920x1080 executive deck.",
            "3. Translate `phase6_alert_rules.json` into live Kibana rules once the target Elastic indices are in place.",
            "",
            "## Honest Caveats",
            "",
            "- The dashboards are markdown-first because this repo does not yet store Elastic-exported Lens/TSVB schemas.",
            "- The Canvas artifact is a deterministic page spec, not a raw Kibana export.",
            "- The alert file evaluates the rules against repo state; it is not a POST-ready Kibana rule payload.",
            "- Non-trading revenue is operational-state only until a billing ledger lands in the repo.",
            "",
            f"_Generated at {pack['generated_at']}_",
            "",
        ]
    )


def _risk_adjusted_score(history: list[Any]) -> tuple[float, str]:
    returns = [
        (float(row.ending_bankroll or 0.0) - float(row.starting_bankroll or 0.0))
        / max(float(row.starting_bankroll or 0.0), 1e-9)
        for row in history
    ]
    if len(returns) >= 2:
        stdev = statistics.stdev(returns)
        if stdev > 0:
            return statistics.mean(returns) / stdev * math.sqrt(252), "sharpe"
    cumulative_return = sum(returns)
    latest = history[-1]
    max_drawdown = abs(float(latest.max_drawdown_pct or 0.0))
    if max_drawdown > 0:
        return cumulative_return / max_drawdown, "return_to_drawdown"
    return cumulative_return, "cumulative_return"


def _annualized_sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    stdev = statistics.stdev(returns)
    if stdev <= 0:
        return 0.0
    return statistics.mean(returns) / stdev * math.sqrt(252)


def _infer_market_regime(payload: dict[str, Any], vol_regime: dict[str, Any]) -> tuple[str, str]:
    if vol_regime.get("regime_decay"):
        return "unstable", "Latest volatility-regime diagnostics show regime decay."
    if str(payload.get("recommendation", "")).upper() == "REJECT ALL":
        return "adverse", "The latest research cycle rejected all currently tested hypotheses."
    if float(vol_regime.get("ev_maker") or 0.0) > 0 and float(vol_regime.get("win_rate") or 0.0) >= 0.55:
        return "favorable", "Volatility-regime mismatch is currently positive on maker assumptions."
    return "neutral", "No single research signal dominates the latest report."


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    rendered_rows = [[_stringify(cell) for cell in row] for row in rows]
    rendered_headers = [_stringify(cell) for cell in headers]
    lines = [
        "| " + " | ".join(rendered_headers) + " |",
        "| " + " | ".join(["---"] * len(rendered_headers)) + " |",
    ]
    for row in rendered_rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _jsonable(payload: dict[str, Any], *, drop: set[str] | None = None) -> dict[str, Any]:
    result = {}
    drop = drop or set()
    for key, value in payload.items():
        if key in drop:
            continue
        result[key] = value
    return result


def _stable_id(label: str) -> str:
    return str(uuid.uuid5(_UUID_NAMESPACE, label))


def _age_minutes(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - value
    return round(delta.total_seconds() / 60.0, 2)


def _parse_optional_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_or_dash(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}"


def _float_or_dash(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _minutes_or_dash(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}m"


def _value_or_dash(value: Any) -> str:
    if value is None:
        return "-"
    return _stringify(value)


def _stringify(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value}"
    return str(value)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
