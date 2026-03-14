"""Shared CLI helpers for research and simulation scripts."""

from __future__ import annotations

import argparse


def add_mode_argument(parser: argparse.ArgumentParser, *, help_text: str) -> None:
    parser.add_argument(
        "--mode",
        choices=("full", "analyze", "quick"),
        default="full",
        help=help_text,
    )
