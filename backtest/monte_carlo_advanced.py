#!/usr/bin/env python3
"""Compatibility shim for moved historical utility.

Target module: backtest/historical/monte_carlo_advanced.py
"""

from __future__ import annotations

from pathlib import Path
import runpy


_TARGET = Path(__file__).with_name("historical") / "monte_carlo_advanced.py"

if __name__ == "__main__":
    runpy.run_path(str(_TARGET), run_name="__main__")
else:
    globals().update(runpy.run_path(str(_TARGET)))
