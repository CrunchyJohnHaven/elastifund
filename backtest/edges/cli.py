#!/usr/bin/env python3
"""CLI for Edge Backlog + Experiment Harness.

Usage:
    python -m edges.cli add-edge --name "NO bias" --hypothesis "Crowd overprices YES"
    python -m edges.cli list-edges [--status backlog]
    python -m edges.cli start-experiment --edge-id abc123 [--config '{"threshold": 0.10}']
    python -m edges.cli log-result --exp-id def456 --won --pnl 0.60
    python -m edges.cli promote --edge-id abc123
    python -m edges.cli demote --edge-id abc123
    python -m edges.cli no-trade [on|off|status]
    python -m edges.cli ev --win-prob 0.75 --price 0.50 --direction buy_no
    python -m edges.cli dashboard
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from .metrics import arr_estimate, expected_value, kelly_fraction
from .models import EdgeCard, EdgeStatus, Experiment, ExperimentStatus
from .store import EdgeStore


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def cmd_add_edge(args, store: EdgeStore):
    edge = EdgeCard(
        name=args.name,
        hypothesis=args.hypothesis,
        source=getattr(args, "source", "manual"),
        expected_win_rate=getattr(args, "win_rate", None),
        expected_ev_per_trade=getattr(args, "ev", None),
        tags=getattr(args, "tags", ""),
        notes=getattr(args, "notes", ""),
    )
    store.add_edge(edge)
    print(f"Created edge [{edge.id}] \"{edge.name}\"")
    print(f"  Hypothesis: {edge.hypothesis}")
    print(f"  Status: {edge.status}")


def cmd_list_edges(args, store: EdgeStore):
    status = getattr(args, "status", None)
    edges = store.list_edges(status=status)
    if not edges:
        print("No edges found." + (f" (filter: {status})" if status else ""))
        return

    print(f"\n{'ID':<14} {'Status':<10} {'Name':<30} {'WR%':<8} {'EV$':<8} {'Created'}")
    print("-" * 90)
    for e in edges:
        wr = f"{e.expected_win_rate:.0%}" if e.expected_win_rate else "-"
        ev = f"${e.expected_ev_per_trade:.2f}" if e.expected_ev_per_trade else "-"
        print(f"{e.id:<14} {e.status:<10} {e.name[:30]:<30} {wr:<8} {ev:<8} {_ts(e.created_at)}")

    # Summary
    by_status = {}
    for e in edges:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    parts = [f"{s}: {c}" for s, c in sorted(by_status.items())]
    print(f"\nTotal: {len(edges)} edges ({', '.join(parts)})")


def cmd_start_experiment(args, store: EdgeStore):
    edge = store.get_edge(args.edge_id)
    if not edge:
        print(f"Edge {args.edge_id} not found")
        sys.exit(1)

    config = getattr(args, "config", "{}")
    exp = Experiment(edge_id=args.edge_id, config=config)
    store.start_experiment(exp)
    print(f"Started experiment [{exp.id}] for edge \"{edge.name}\"")
    print(f"  Edge status -> testing")
    if config != "{}":
        print(f"  Config: {config}")


def cmd_log_result(args, store: EdgeStore):
    exp = store.log_result(args.exp_id, args.won, args.pnl)
    if not exp:
        print(f"Experiment {args.exp_id} not found or not running")
        sys.exit(1)

    status = "WIN" if args.won else "LOSS"
    print(f"[{status}] P&L: ${args.pnl:+.2f} | "
          f"Record: {exp.wins}W-{exp.losses}L ({exp.win_rate:.0%}) | "
          f"Total P&L: ${exp.total_pnl:+.2f}")


def cmd_complete_experiment(args, store: EdgeStore):
    notes = getattr(args, "notes", "")
    exp = store.complete_experiment(args.exp_id, notes=notes)
    if not exp:
        print(f"Experiment {args.exp_id} not found")
        sys.exit(1)
    print(f"Completed experiment [{exp.id}]")
    print(f"  Result: {exp.wins}W-{exp.losses}L ({exp.win_rate:.0%})")
    print(f"  Total P&L: ${exp.total_pnl:+.2f}")


def cmd_promote(args, store: EdgeStore):
    ok = store.update_edge_status(args.edge_id, EdgeStatus.PROMOTED)
    if not ok:
        print(f"Edge {args.edge_id} not found")
        sys.exit(1)
    edge = store.get_edge(args.edge_id)
    print(f"Promoted edge [{edge.id}] \"{edge.name}\" -> PROMOTED")


def cmd_demote(args, store: EdgeStore):
    ok = store.update_edge_status(args.edge_id, EdgeStatus.DEMOTED)
    if not ok:
        print(f"Edge {args.edge_id} not found")
        sys.exit(1)
    edge = store.get_edge(args.edge_id)
    print(f"Demoted edge [{edge.id}] \"{edge.name}\" -> DEMOTED")


def cmd_no_trade(args, store: EdgeStore):
    action = getattr(args, "action", "status")
    if action == "on":
        store.no_trade_mode = True
        print("No-trade mode: ON (trading disabled)")
    elif action == "off":
        store.no_trade_mode = False
        print("No-trade mode: OFF (trading enabled)")
    else:
        status = "ON" if store.no_trade_mode else "OFF"
        print(f"No-trade mode: {status}")


def cmd_ev(args, store: EdgeStore):
    result = expected_value(
        win_prob=args.win_prob,
        market_price=args.price,
        direction=args.direction,
        order_size=getattr(args, "size", 2.0),
    )
    kelly = kelly_fraction(args.win_prob, args.price, args.direction)

    print(f"\n  EV Analysis: {args.direction} @ {args.price:.2f}")
    print(f"  Win probability: {result['p_win']:.0%}")
    print(f"  Entry (after slippage): {result['entry_price']:.4f}")
    print(f"  Shares: {result['shares']:.2f}")
    print(f"  Win P&L: ${result['win_pnl']:+.2f} | Loss P&L: ${result['lose_pnl']:+.2f}")
    print(f"  Gross EV: ${result['gross_ev']:+.4f}")
    print(f"  Fee cost: ${result['fee_cost']:+.4f}")
    print(f"  Slippage cost: ${result['slippage_cost']:+.4f}")
    print(f"  Net EV: ${result['ev']:+.4f}")
    print(f"  Breakeven prob: {result['breakeven_prob']:.0%}")
    print(f"  Edge over breakeven: {result['edge_over_breakeven']:+.1%}")
    print(f"  Quarter-Kelly: {kelly:.1%} of bankroll")


def cmd_dashboard(args, store: EdgeStore):
    edges = store.list_edges()
    experiments = store.list_experiments()
    running = [e for e in experiments if e.status == ExperimentStatus.RUNNING]

    print("\n" + "=" * 60)
    print("  EDGE BACKLOG DASHBOARD")
    print("=" * 60)

    # No-trade mode
    ntm = "ON" if store.no_trade_mode else "OFF"
    print(f"  No-trade mode: {ntm}")

    # Edge counts
    by_status = {}
    for e in edges:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    print(f"\n  Edges: {len(edges)} total")
    for s in [EdgeStatus.BACKLOG, EdgeStatus.TESTING, EdgeStatus.PROMOTED, EdgeStatus.DEMOTED]:
        print(f"    {s:<12} {by_status.get(s, 0)}")

    # Running experiments
    if running:
        print(f"\n  Active Experiments:")
        for exp in running:
            edge = store.get_edge(exp.edge_id)
            name = edge.name if edge else "?"
            print(f"    [{exp.id}] {name}: {exp.wins}W-{exp.losses}L "
                  f"({exp.win_rate:.0%}) P&L: ${exp.total_pnl:+.2f}")

    # Promoted edges
    promoted = store.list_edges(status=EdgeStatus.PROMOTED)
    if promoted:
        print(f"\n  Promoted Edges (production-ready):")
        for e in promoted:
            wr = f"{e.expected_win_rate:.0%}" if e.expected_win_rate else "?"
            print(f"    [{e.id}] {e.name} (WR: {wr})")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Edge Backlog + Experiment Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", help="SQLite database path", default=None)
    sub = parser.add_subparsers(dest="command")

    # add-edge
    p = sub.add_parser("add-edge", help="Add a new edge hypothesis")
    p.add_argument("--name", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--source", default="manual")
    p.add_argument("--win-rate", type=float, default=None)
    p.add_argument("--ev", type=float, default=None)
    p.add_argument("--tags", default="")
    p.add_argument("--notes", default="")

    # list-edges
    p = sub.add_parser("list-edges", help="List edges")
    p.add_argument("--status", default=None)

    # start-experiment
    p = sub.add_parser("start-experiment", help="Start experiment for an edge")
    p.add_argument("--edge-id", required=True)
    p.add_argument("--config", default="{}")

    # log-result
    p = sub.add_parser("log-result", help="Log a trade result")
    p.add_argument("--exp-id", required=True)
    p.add_argument("--won", action="store_true")
    p.add_argument("--lost", action="store_true")
    p.add_argument("--pnl", type=float, required=True)

    # complete-experiment
    p = sub.add_parser("complete-experiment", help="Mark experiment complete")
    p.add_argument("--exp-id", required=True)
    p.add_argument("--notes", default="")

    # promote
    p = sub.add_parser("promote", help="Promote edge to production")
    p.add_argument("--edge-id", required=True)

    # demote
    p = sub.add_parser("demote", help="Demote edge")
    p.add_argument("--edge-id", required=True)

    # no-trade
    p = sub.add_parser("no-trade", help="Toggle no-trade mode")
    p.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"])

    # ev
    p = sub.add_parser("ev", help="Calculate expected value")
    p.add_argument("--win-prob", type=float, required=True)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--direction", required=True, choices=["buy_yes", "buy_no"])
    p.add_argument("--size", type=float, default=2.0)

    # dashboard
    sub.add_parser("dashboard", help="Show dashboard summary")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    store = EdgeStore(db_path=args.db)

    # Handle --won/--lost for log-result
    if args.command == "log-result":
        if not args.won and not args.lost:
            print("Must specify --won or --lost")
            sys.exit(1)
        args.won = args.won  # True if --won, False if --lost

    commands = {
        "add-edge": cmd_add_edge,
        "list-edges": cmd_list_edges,
        "start-experiment": cmd_start_experiment,
        "log-result": cmd_log_result,
        "complete-experiment": cmd_complete_experiment,
        "promote": cmd_promote,
        "demote": cmd_demote,
        "no-trade": cmd_no_trade,
        "ev": cmd_ev,
        "dashboard": cmd_dashboard,
    }

    commands[args.command](args, store)
    store.close()


if __name__ == "__main__":
    main()
