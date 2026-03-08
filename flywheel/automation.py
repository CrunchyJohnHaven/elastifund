"""Config-driven automation entrypoint for the flywheel control plane."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_layer import database

from .bridge import build_payload_from_bot_db
from .runner import DEFAULT_ARTIFACT_ROOT, run_cycle


def load_config(path: str | Path) -> dict[str, Any]:
    """Load an automation config file from JSON."""

    return json.loads(Path(path).read_text())


def build_payload_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Build one combined flywheel payload from a runtime config."""

    strategies: list[dict[str, Any]] = []
    for item in config.get("strategies", []):
        payload = build_payload_from_bot_db(
            item["bot_db"],
            strategy_key=item["strategy_key"],
            version_label=item["version_label"],
            lane=item["lane"],
            environment=item["environment"],
            capital_cap_usd=float(item["capital_cap_usd"]),
            artifact_uri=item.get("artifact_uri"),
            git_sha=item.get("git_sha"),
            lookback_days=int(item.get("lookback_days", 7)),
        )
        strategies.extend(payload["strategies"])

    cycle_key = config.get("cycle_key") or _cycle_key(config.get("cycle_key_prefix", "runtime"))
    return {"cycle_key": cycle_key, "strategies": strategies}


def run_from_config(path: str | Path) -> dict[str, Any]:
    """Run the full flywheel cycle from a runtime config file."""

    config = load_config(path)
    payload = build_payload_from_config(config)
    artifact_root = config.get("artifact_dir", str(DEFAULT_ARTIFACT_ROOT))
    control_db_url = config.get("control_db_url")

    database.reset_engine()
    engine = database.get_engine(control_db_url)
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        return run_cycle(session, payload, artifact_root=artifact_root)
    finally:
        session.close()
        database.reset_engine()


def _cycle_key(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}"
