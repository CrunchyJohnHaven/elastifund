#!/usr/bin/env python3
"""Generate the A-6 / B-1 structural-alpha decision report."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


UTC = timezone.utc
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_RELAXED_A6_THRESHOLD = 0.97


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        numeric = safe_int(raw)
        if numeric is not None and raw.lstrip("-").isdigit():
            return datetime.fromtimestamp(numeric, tz=UTC)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_log_window(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"rows": 0, "start": None, "end": None}

    count = 0
    start: datetime | None = None
    end: datetime | None = None
    with log_path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            detected_at = parse_datetime(
                row.get("detected_at_ts")
                or row.get("timestamp")
                or row.get("ts")
                or row.get("observed_at")
            )
            if detected_at is None:
                continue
            count += 1
            start = detected_at if start is None else min(start, detected_at)
            end = detected_at if end is None else max(end, detected_at)
    return {"rows": count, "start": iso_or_none(start), "end": iso_or_none(end)}


def read_db_window(db_path: Path) -> dict[str, dict[str, Any]]:
    result = {
        "a6_violation_episode": {"rows": 0, "start": None, "end": None},
        "constraint_violations": {"rows": 0, "start": None, "end": None},
        "graph_edges": {"rows": 0, "start": None, "end": None},
    }
    if not db_path.exists():
        return result

    queries = {
        "a6_violation_episode": (
            "SELECT COUNT(*), MIN(ts_start_utc), MAX(COALESCE(ts_end_utc, ts_start_utc)) "
            "FROM a6_violation_episode"
        ),
        "constraint_violations": (
            "SELECT COUNT(*), MIN(detected_at_ts), MAX(detected_at_ts) "
            "FROM constraint_violations"
        ),
        "graph_edges": (
            "SELECT COUNT(*), MIN(created_at_ts), MAX(updated_at_ts) "
            "FROM graph_edges"
        ),
    }

    with sqlite3.connect(db_path) as conn:
        for key, query in queries.items():
            try:
                row = conn.execute(query).fetchone()
            except sqlite3.OperationalError:
                continue
            if not row:
                continue
            count, start_raw, end_raw = row
            result[key] = {
                "rows": int(count or 0),
                "start": iso_or_none(parse_datetime(start_raw)),
                "end": iso_or_none(parse_datetime(end_raw)),
            }
    return result


def collect_observation_window(
    snapshot: Mapping[str, Any],
    *,
    db_path: Path | None,
    log_path: Path | None,
    lookback_days: int,
) -> dict[str, Any]:
    sources: dict[str, dict[str, Any]] = {}
    points: list[datetime] = []

    replay = snapshot.get("a6_replay", {})
    replay_start = parse_datetime(replay.get("observed_start"))
    replay_end = parse_datetime(replay.get("observed_end"))
    sources["snapshot_a6_replay"] = {
        "rows": int(replay.get("row_count") or 0),
        "start": iso_or_none(replay_start),
        "end": iso_or_none(replay_end),
    }
    if replay_start is not None:
        points.append(replay_start)
    if replay_end is not None:
        points.append(replay_end)

    db_sources = read_db_window(db_path) if db_path is not None else {}
    sources.update(db_sources)
    for payload in db_sources.values():
        start = parse_datetime(payload.get("start"))
        end = parse_datetime(payload.get("end"))
        if start is not None:
            points.append(start)
        if end is not None:
            points.append(end)

    if log_path is not None:
        log_source = read_log_window(log_path)
        sources["sum_violation_events_log"] = log_source
        log_start = parse_datetime(log_source.get("start"))
        log_end = parse_datetime(log_source.get("end"))
        if log_start is not None:
            points.append(log_start)
        if log_end is not None:
            points.append(log_end)

    start = min(points) if points else None
    end = max(points) if points else None
    target_end = start + timedelta(days=lookback_days) if start is not None else None
    seconds_observed = max(0.0, (end - start).total_seconds()) if start is not None and end is not None else 0.0
    seconds_remaining = (
        max(0.0, (target_end - end).total_seconds())
        if target_end is not None and end is not None
        else None
    )

    return {
        "start": iso_or_none(start),
        "end": iso_or_none(end),
        "hours_observed": round(seconds_observed / 3600.0, 3),
        "days_observed": round(seconds_observed / 86400.0, 3),
        "target_end": iso_or_none(target_end),
        "window_complete": bool(target_end is not None and end is not None and end >= target_end),
        "hours_remaining": None if seconds_remaining is None else round(seconds_remaining / 3600.0, 3),
        "sources": sources,
    }


def summarize_a6_audit(rows: Sequence[Mapping[str, Any]], *, relaxed_threshold: float) -> dict[str, Any]:
    min_cost: float | None = None
    best_type_counter: Counter[str] = Counter()
    below_relaxed = 0
    executable_below_relaxed = 0
    ready_below_relaxed = 0

    for row in rows:
        best = row.get("best_construction") or {}
        if not isinstance(best, Mapping):
            continue
        best_type = str(best.get("construction_type") or "unknown")
        best_type_counter[best_type] += 1
        cost = safe_float(best.get("top_of_book_cost"))
        if cost is None:
            continue
        min_cost = cost if min_cost is None else min(min_cost, cost)
        if cost < relaxed_threshold:
            below_relaxed += 1
            if bool(best.get("executable")):
                executable_below_relaxed += 1
            readiness = best.get("readiness") or {}
            if isinstance(readiness, Mapping) and bool(readiness.get("ready")):
                ready_below_relaxed += 1

    dominant_best_type = best_type_counter.most_common(1)[0][0] if best_type_counter else None
    return {
        "event_count": len(rows),
        "relaxed_threshold": relaxed_threshold,
        "best_construction_below_relaxed_threshold_count": below_relaxed,
        "executable_below_relaxed_threshold_count": executable_below_relaxed,
        "ready_below_relaxed_threshold_count": ready_below_relaxed,
        "minimum_top_of_book_cost": min_cost,
        "dominant_best_construction_type": dominant_best_type,
    }


def summarize_b1_audit(payload: Mapping[str, Any]) -> dict[str, Any]:
    template_pairs = payload.get("template_pairs") or []
    template_markets = payload.get("template_markets") or {}
    dominant_family = None
    dominant_count = None
    if isinstance(template_markets, Mapping) and template_markets:
        dominant_family, dominant_count = max(
            ((str(key), int(value)) for key, value in template_markets.items()),
            key=lambda item: item[1],
        )
    return {
        "template_pair_count": len(template_pairs),
        "template_market_family_counts": dict(template_markets) if isinstance(template_markets, Mapping) else {},
        "dominant_family": dominant_family,
        "dominant_family_market_count": dominant_count,
    }


def decide_a6(
    snapshot: Mapping[str, Any],
    *,
    window: Mapping[str, Any],
    relaxed_audit: Mapping[str, Any],
    lookback_days: int,
) -> dict[str, Any]:
    lane_status = snapshot.get("lane_status", {}).get("a6", {})
    repo_truth = snapshot.get("repo_truth", {}).get("public_a6_audit", {})
    gating = snapshot.get("gating_metrics", {})
    live = snapshot.get("live_surface", {})
    fill_proxy = snapshot.get("fill_proxy", {})

    relaxed_count = int(relaxed_audit.get("best_construction_below_relaxed_threshold_count") or 0)
    decision = "continue"
    decision_scope = "provisional_until_window_complete"
    headline = (
        "Keep A-6 blocked and continue shadow collection until the seven-day window completes."
    )
    if window.get("window_complete"):
        decision_scope = "final_for_current_window"
        if relaxed_count == 0 and int(live.get("qualified_underround_count") or 0) == 0:
            decision = "kill"
            headline = (
                f"Kill A-6 for the current regime: zero relaxed candidates below "
                f"{relaxed_audit.get('relaxed_threshold')} after the full {lookback_days}-day window."
            )
        else:
            headline = "Keep A-6 blocked, but continue the lane into a maker-fill / settlement validation pass."

    rationale = [
        (
            f"Public audit still shows "
            f"{repo_truth.get('executable_constructions_below_threshold')} executable constructions below "
            f"{repo_truth.get('execute_threshold')} across "
            f"{repo_truth.get('allowed_neg_risk_event_count')} allowed neg-risk events."
        ),
        (
            f"Relaxed A-6 density is {relaxed_count} events below "
            f"{relaxed_audit.get('relaxed_threshold')} with minimum top-of-book cost "
            f"{relaxed_audit.get('minimum_top_of_book_cost')}."
        ),
        (
            f"Live surface currently has {live.get('qualified_underround_count', 0)} underround and "
            f"{live.get('qualified_overround_count', 0)} overround qualified A-6 observations."
        ),
    ]
    if gating.get("kill_decision") == "kill":
        rationale.append(
            "Current shadow replay already emits a kill signal "
            f"({gating.get('kill_reason')})."
        )
    if fill_proxy.get("eligible_probe_count", 0) == 0:
        rationale.append("Maker-fill proxy is still unmeasured because the trade tape cannot be joined to condition IDs.")
    if not window.get("window_complete") and window.get("target_end"):
        rationale.append(f"If the relaxed density remains zero by {window['target_end']}, kill A-6.")

    return {
        "status": lane_status.get("status", "unknown"),
        "decision": decision,
        "decision_scope": decision_scope,
        "headline": headline,
        "kill_if_unchanged_by": window.get("target_end") if decision == "continue" else None,
        "blocked_reasons": list(lane_status.get("blocked_reasons") or []),
        "metrics": {
            "allowed_neg_risk_event_count": repo_truth.get("allowed_neg_risk_event_count"),
            "executable_below_0_95_count": repo_truth.get("executable_constructions_below_threshold"),
            "relaxed_below_0_97_count": relaxed_count,
            "relaxed_executable_below_0_97_count": relaxed_audit.get("executable_below_relaxed_threshold_count"),
            "relaxed_ready_below_0_97_count": relaxed_audit.get("ready_below_relaxed_threshold_count"),
            "minimum_top_of_book_cost": relaxed_audit.get("minimum_top_of_book_cost"),
            "qualified_underround_count": live.get("qualified_underround_count"),
            "qualified_overround_count": live.get("qualified_overround_count"),
            "fill_proxy_probe_count": fill_proxy.get("eligible_probe_count"),
        },
        "rationale": rationale,
    }


def decide_b1(
    snapshot: Mapping[str, Any],
    *,
    window: Mapping[str, Any],
    b1_audit: Mapping[str, Any],
    lookback_days: int,
) -> dict[str, Any]:
    lane_status = snapshot.get("lane_status", {}).get("b1", {})
    repo_truth = snapshot.get("repo_truth", {}).get("public_b1_audit", {})
    b1_summary = snapshot.get("b1", {})

    pair_count = int(b1_audit.get("template_pair_count") or 0)
    accuracy = safe_float(b1_summary.get("classification_accuracy"))
    false_positive_rate = safe_float(b1_summary.get("false_positive_rate"))
    decision = "continue"
    decision_scope = "provisional_until_window_complete"
    headline = "Keep B-1 blocked and continue the narrowed template audit until the seven-day window completes."

    if window.get("window_complete"):
        decision_scope = "final_for_current_window"
        if pair_count == 0:
            decision = "kill"
            headline = (
                f"Kill B-1 for the current regime: zero deterministic template pairs after the full "
                f"{lookback_days}-day observation window."
            )
        elif accuracy is not None and accuracy < 0.80:
            decision = "kill"
            headline = f"Kill B-1: classification accuracy {accuracy:.3f} is below the 0.80 floor."
        elif false_positive_rate is not None and false_positive_rate > 0.05:
            decision = "kill"
            headline = (
                f"Kill B-1: false-positive rate {false_positive_rate:.3f} is above the 0.05 ceiling."
            )
        else:
            headline = "Keep B-1 blocked and finish the gold-set precision audit before any expansion."

    rationale = [
        (
            f"Public audit still shows {repo_truth.get('deterministic_template_pair_count')} deterministic "
            f"pairs in the first {repo_truth.get('allowed_market_sample_size')} allowed markets."
        ),
        (
            f"Current template-family scan tracks {b1_audit.get('template_market_family_counts')} and "
            f"finds {pair_count} compatible pairs."
        ),
        (
            f"Historical B-1 graph edges={b1_summary.get('graph_edge_count')}, "
            f"violations={b1_summary.get('historical_violation_count')}."
        ),
    ]
    if accuracy is None or false_positive_rate is None:
        rationale.append("Precision metrics are still unmeasured because the gold-set audit is unfinished.")
    if not window.get("window_complete") and window.get("target_end"):
        rationale.append(f"If template-pair density remains zero by {window['target_end']}, kill B-1.")

    return {
        "status": lane_status.get("status", "unknown"),
        "decision": decision,
        "decision_scope": decision_scope,
        "headline": headline,
        "kill_if_unchanged_by": window.get("target_end") if decision == "continue" else None,
        "blocked_reasons": list(lane_status.get("blocked_reasons") or []),
        "metrics": {
            "allowed_market_sample_size": repo_truth.get("allowed_market_sample_size"),
            "template_pair_count": pair_count,
            "dominant_family": b1_audit.get("dominant_family"),
            "dominant_family_market_count": b1_audit.get("dominant_family_market_count"),
            "classification_accuracy": accuracy,
            "false_positive_rate": false_positive_rate,
            "historical_violation_count": b1_summary.get("historical_violation_count"),
        },
        "rationale": rationale,
    }


def build_decision_report(
    snapshot: Mapping[str, Any],
    *,
    guaranteed_dollar_audit: Sequence[Mapping[str, Any]],
    b1_template_audit: Mapping[str, Any],
    lookback_days: int,
    relaxed_a6_threshold: float = DEFAULT_RELAXED_A6_THRESHOLD,
    db_path: Path | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    window = collect_observation_window(
        snapshot,
        db_path=db_path,
        log_path=log_path,
        lookback_days=lookback_days,
    )
    a6_audit = summarize_a6_audit(guaranteed_dollar_audit, relaxed_threshold=relaxed_a6_threshold)
    b1_audit = summarize_b1_audit(b1_template_audit)
    a6 = decide_a6(snapshot, window=window, relaxed_audit=a6_audit, lookback_days=lookback_days)
    b1 = decide_b1(snapshot, window=window, b1_audit=b1_audit, lookback_days=lookback_days)

    portfolio_status = "keep_blocked"
    portfolio_summary = (
        "Keep both structural-alpha lanes blocked. The observation window is incomplete and neither lane has "
        "earned promotion."
    )
    if window.get("window_complete") and a6.get("decision") == "kill" and b1.get("decision") == "kill":
        portfolio_status = "kill_both"
        portfolio_summary = "Kill both structural-alpha lanes for the current regime and reallocate effort."

    return {
        "generated_at": utc_now_iso(),
        "source_snapshot_generated_at": snapshot.get("generated_at"),
        "lookback_days": int(lookback_days),
        "observation_window": window,
        "a6": a6,
        "b1": b1,
        "portfolio_call": {
            "status": portfolio_status,
            "summary": portfolio_summary,
        },
    }


def build_markdown_report(report: Mapping[str, Any]) -> str:
    window = report["observation_window"]
    a6 = report["a6"]
    b1 = report["b1"]
    portfolio = report["portfolio_call"]

    lines = [
        "# Structural Alpha Decision",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Source snapshot generated: {report.get('source_snapshot_generated_at')}",
        f"- Lookback target: {report['lookback_days']} days",
        "",
        "## Observation Window",
        "",
        f"- Start: {window.get('start')}",
        f"- End: {window.get('end')}",
        f"- Hours observed: {window.get('hours_observed')}",
        f"- Days observed: {window.get('days_observed')}",
        f"- Target end: {window.get('target_end')}",
        f"- Window complete: **{window.get('window_complete')}**",
        f"- Hours remaining: {window.get('hours_remaining')}",
        "",
        "## A-6",
        "",
        f"- Status: **{a6.get('status')}**",
        f"- Decision: **{a6.get('decision')}**",
        f"- Scope: {a6.get('decision_scope')}",
        f"- Headline: {a6.get('headline')}",
        f"- Kill if unchanged by: {a6.get('kill_if_unchanged_by')}",
        f"- Metrics: {a6.get('metrics')}",
        f"- Blocked reasons: {a6.get('blocked_reasons')}",
        "",
        "### A-6 Rationale",
        "",
    ]
    for item in a6.get("rationale", []):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## B-1",
            "",
            f"- Status: **{b1.get('status')}**",
            f"- Decision: **{b1.get('decision')}**",
            f"- Scope: {b1.get('decision_scope')}",
            f"- Headline: {b1.get('headline')}",
            f"- Kill if unchanged by: {b1.get('kill_if_unchanged_by')}",
            f"- Metrics: {b1.get('metrics')}",
            f"- Blocked reasons: {b1.get('blocked_reasons')}",
            "",
            "### B-1 Rationale",
            "",
        ]
    )
    for item in b1.get("rationale", []):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Portfolio Call",
            "",
            f"- Status: **{portfolio.get('status')}**",
            f"- Summary: {portfolio.get('summary')}",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the structural-alpha decision report.")
    parser.add_argument("--snapshot-json", default="reports/arb_empirical_snapshot.json")
    parser.add_argument("--guaranteed-dollar-audit-json", default="reports/guaranteed_dollar_audit.json")
    parser.add_argument("--b1-template-audit-json", default="reports/b1_template_audit.json")
    parser.add_argument("--db-path", default="data/constraint_arb.db")
    parser.add_argument("--log-path", default="logs/sum_violation_events.jsonl")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--relaxed-a6-threshold", type=float, default=DEFAULT_RELAXED_A6_THRESHOLD)
    parser.add_argument("--output-json", default="reports/structural_alpha_decision.json")
    parser.add_argument("--output-md", default="reports/structural_alpha_decision.md")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    snapshot_path = Path(args.snapshot_json)
    audit_path = Path(args.guaranteed_dollar_audit_json)
    b1_audit_path = Path(args.b1_template_audit_json)
    db_path = Path(args.db_path)
    log_path = Path(args.log_path)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    snapshot = load_json(snapshot_path, {})
    guaranteed_dollar_audit = load_json(audit_path, [])
    b1_template_audit = load_json(b1_audit_path, {})

    report = build_decision_report(
        snapshot,
        guaranteed_dollar_audit=guaranteed_dollar_audit,
        b1_template_audit=b1_template_audit,
        lookback_days=max(1, int(args.lookback_days)),
        relaxed_a6_threshold=float(args.relaxed_a6_threshold),
        db_path=db_path,
        log_path=log_path,
    )

    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(build_markdown_report(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
