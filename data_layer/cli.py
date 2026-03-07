"""CLI: db-init, db-status, db-vacuum.

Usage:
    python -m data_layer init      # create tables
    python -m data_layer status    # show row counts & size
    python -m data_layer vacuum    # reclaim space
"""

import argparse
import json
import sys

from . import database


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


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="data_layer",
        description="Quant data layer CLI",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create all tables")
    sub.add_parser("status", help="Show table row counts and DB size")
    sub.add_parser("vacuum", help="Run VACUUM to reclaim space")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    handlers = {"init": cmd_init, "status": cmd_status, "vacuum": cmd_vacuum}
    handlers[args.command](args)


if __name__ == "__main__":
    main()
