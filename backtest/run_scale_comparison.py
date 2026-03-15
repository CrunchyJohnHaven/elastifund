#!/usr/bin/env python3
"""Compatibility shim for scale-comparison entrypoint."""

import sys

from backtest import run_scale_comparison_core as _core

sys.modules[__name__] = _core
