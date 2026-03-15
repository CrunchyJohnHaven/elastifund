"""CLI for the edge backlog system."""

from __future__ import annotations
import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .models import Edge, EdgeStore, Status

DEFAULT_STORE = Path.home() / ".edge-backlog" / "edges.json"


def get_store(args) -> EdgeStore:
    path = Path(getattr(args, "store", None) or DEFAULT_STORE)
    return EdgeStore(path)


def cmd_add(args) -> None:
    store = get_store(args)
    now = datetime.now(timezone.utc).isoformat()
    edge = Edge(
        id=uuid.uuid4().hex[:8],
        name=args.name,
        hypothesis=args.hypothesis,
        status=Status.IDEA,
        created=now,
        updated=now,
        tags=[t.strip() for t in args.tags.split(",")] if args.tags else [],
    )
    edge.history.append(f"[{now}] Created")
    store.save(edge)
    print(f"Created edge {edge.id}: {edge.name} [IDEA]")


def cmd_list(args) -> None:
    store = get_store(args)
    status_filter = Status(args.status.upper()) if args.status else None
    edges = store.list_all(status=status_filter)
    if not edges:
        print("No edges found.")
        return
    for e in edges:
        score_str = f"  score={e.score}" if e.score is not None else ""
        exp_str = f"  exps={len(e.experiments)}" if e.experiments else ""
        print(f"  {e.id}  [{e.status.value:>8}]{score_str}{exp_str}  {e.name}")


def cmd_score(args) -> None:
    store = get_store(args)
    edge = store.get(args.edge_id)
    edge.set_score(args.value, notes=args.notes or "")
    store.save(edge)
    print(f"Scored edge {edge.id} = {args.value}" + (f" ({args.notes})" if args.notes else ""))


def cmd_start_experiment(args) -> None:
    store = get_store(args)
    edge = store.get(args.edge_id)
    exp = edge.start_experiment(args.name)
    store.save(edge)
    print(f"Started experiment '{exp.name}' ({exp.id}) on edge {edge.id}")


def cmd_log_result(args) -> None:
    store = get_store(args)
    edge = store.get(args.edge_id)
    # Find experiment
    exp = None
    for e in edge.experiments:
        if e.id == args.experiment_id:
            exp = e
            break
    if exp is None:
        print(f"Experiment '{args.experiment_id}' not found on edge {edge.id}", file=sys.stderr)
        sys.exit(1)
    r = exp.add_result(metric=args.metric, value=args.value, notes=args.notes or "")
    edge._log(f"Logged result on exp {exp.id}: {args.metric}={args.value}")
    store.save(edge)
    print(f"Logged {args.metric}={args.value} on experiment {exp.id}")


def cmd_promote(args) -> None:
    store = get_store(args)
    edge = store.get(args.edge_id)
    old = edge.status.value
    try:
        new = edge.promote()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    store.save(edge)
    print(f"Promoted edge {edge.id}: {old} → {new.value}")


def cmd_demote(args) -> None:
    store = get_store(args)
    edge = store.get(args.edge_id)
    old = edge.status.value
    try:
        new = edge.demote()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    store.save(edge)
    print(f"Demoted edge {edge.id}: {old} → {new.value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edge-backlog", description="Edge Backlog Manager")
    parser.add_argument("--store", help="Path to edges JSON file", default=None)
    sub = parser.add_subparsers(dest="command")

    # add-edge
    p_add = sub.add_parser("add-edge", help="Add a new edge")
    p_add.add_argument("name", help="Short name for the edge")
    p_add.add_argument("hypothesis", help="Edge hypothesis description")
    p_add.add_argument("--tags", help="Comma-separated tags", default="")

    # list-edges
    p_list = sub.add_parser("list-edges", help="List edges")
    p_list.add_argument("--status", help="Filter by status (IDEA/BACKTEST/PAPER/SHADOW/LIVE)", default=None)

    # score-edge
    p_score = sub.add_parser("score-edge", help="Score an edge")
    p_score.add_argument("edge_id", help="Edge ID")
    p_score.add_argument("value", type=float, help="Score value")
    p_score.add_argument("--notes", help="Score notes", default="")

    # start-experiment
    p_exp = sub.add_parser("start-experiment", help="Start an experiment on an edge")
    p_exp.add_argument("edge_id", help="Edge ID")
    p_exp.add_argument("name", help="Experiment name")

    # log-result
    p_log = sub.add_parser("log-result", help="Log result to an experiment")
    p_log.add_argument("edge_id", help="Edge ID")
    p_log.add_argument("experiment_id", help="Experiment ID")
    p_log.add_argument("metric", help="Metric name")
    p_log.add_argument("value", type=float, help="Metric value")
    p_log.add_argument("--notes", help="Result notes", default="")

    # promote
    p_prom = sub.add_parser("promote", help="Promote edge to next status")
    p_prom.add_argument("edge_id", help="Edge ID")

    # demote
    p_dem = sub.add_parser("demote", help="Demote edge to previous status")
    p_dem.add_argument("edge_id", help="Edge ID")

    return parser


COMMANDS = {
    "add-edge": cmd_add,
    "list-edges": cmd_list,
    "score-edge": cmd_score,
    "start-experiment": cmd_start_experiment,
    "log-result": cmd_log_result,
    "promote": cmd_promote,
    "demote": cmd_demote,
}


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
