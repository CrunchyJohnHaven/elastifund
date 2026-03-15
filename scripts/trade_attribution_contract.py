"""Trade attribution contract — stub.

Provides ``build_trade_attribution_contract`` used by
``write_remote_cycle_status.py``.  A full implementation will land once
the attribution data pipeline is wired up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_trade_attribution_contract(
    *,
    root: Path,
    btc5_maker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an empty attribution contract (stub)."""
    return {
        "version": "0.1.0-stub",
        "trades": [],
    }
